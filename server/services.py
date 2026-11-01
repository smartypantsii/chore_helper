from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from server.catalog import catalog
from server.models import (
    APPROVED,
    CANCELLED,
    CLAIMED_STATES,
    COMPLETE_FOR_EXTRAS,
    DAILY,
    DENIED,
    EXTRA,
    IN_PROGRESS,
    OPEN_STATES,
    PENDING_APPROVAL,
    REQUESTED,
    RETURNED,
    Assignment,
    Child,
    ChildChore,
    LedgerEntry,
    ManagedChore,
    ManagedReward,
    Parent,
    PoolEntry,
    Redemption,
)
from server.passwords import hash_secret, verify_secret

from server.config import CATALOG_DIR, PARENT_PASSWORD, PARENT_USERNAME

CHORE_ID_RE = re.compile(r"^[a-z0-9_]+$")
MAX_COVER_BYTES = 8 * 1024 * 1024
MAX_VIDEO_BYTES = 50 * 1024 * 1024
UPLOAD_DIR = "media/uploads"


def today() -> date:
    return date.today()


def stars_for(db: Session, child_id: int) -> int:
    total = db.scalar(
        select(func.coalesce(func.sum(LedgerEntry.stars), 0)).where(
            LedgerEntry.child_id == child_id
        )
    )
    return int(total or 0)


def held_stars(db: Session, child_id: int) -> int:
    total = db.scalar(
        select(func.coalesce(func.sum(Redemption.stars), 0)).where(
            Redemption.child_id == child_id,
            Redemption.state == REQUESTED,
        )
    )
    return int(total or 0)


def available_stars(db: Session, child_id: int) -> int:
    return max(0, stars_for(db, child_id) - held_stars(db, child_id))


def child_star_view(db: Session, child: Child) -> dict:
    earned = stars_for(db, child.id)
    held = held_stars(db, child.id)
    return {
        "id": child.id,
        "display_name": child.display_name,
        "age": child.age,
        "stars": earned,
        "available": max(0, earned - held),
        "held": held,
    }


def get_child(db: Session, child_id: int) -> Child:
    child = db.get(Child, child_id)
    if child is None:
        raise HTTPException(404, "Child not found")
    return child


def assignments_today(db: Session, child_id: int, day: date) -> list[Assignment]:
    return list(
        db.scalars(
            select(Assignment)
            .where(
                Assignment.child_id == child_id,
                Assignment.day == day,
                Assignment.state != CANCELLED,
            )
            .order_by(Assignment.created_at)
        )
    )


def daily_for(db: Session, child_id: int, day: date) -> Assignment | None:
    rows = [a for a in assignments_today(db, child_id, day) if a.kind == DAILY]
    return rows[-1] if rows else None


def extras_unlocked(daily: Assignment | None) -> bool:
    return daily is not None and daily.state in COMPLETE_FOR_EXTRAS


def open_assignment(rows: list[Assignment]) -> Assignment | None:
    open_rows = [a for a in rows if a.state in OPEN_STATES]
    return open_rows[-1] if open_rows else None


def pool_ids(db: Session, day: date, kind: str) -> list[str]:
    rows = list(
        db.scalars(
            select(PoolEntry)
            .where(PoolEntry.day == day, PoolEntry.kind == kind)
            .order_by(PoolEntry.sort_order, PoolEntry.id)
        )
    )
    return [r.chore_id for r in rows]


def ensure_today_pools(db: Session, day: date | None = None) -> None:
    day = day or today()
    if pool_ids(db, day, DAILY) or pool_ids(db, day, EXTRA):
        return
    set_pools(db, day, catalog.default_ids(DAILY), catalog.default_ids(EXTRA))


def set_pools(db: Session, day: date, daily: list[str], extra: list[str]) -> None:
    for chore_id in daily + extra:
        if catalog.get(chore_id) is None:
            raise HTTPException(400, f"Unknown chore {chore_id}")
    existing = list(db.scalars(select(PoolEntry).where(PoolEntry.day == day)))
    for row in existing:
        db.delete(row)
    db.flush()
    for i, chore_id in enumerate(daily):
        db.add(PoolEntry(day=day, kind=DAILY, chore_id=chore_id, sort_order=i))
    for i, chore_id in enumerate(extra):
        db.add(PoolEntry(day=day, kind=EXTRA, chore_id=chore_id, sort_order=i))
    db.commit()


def kid_state(db: Session, child: Child, day: date | None = None) -> dict:
    day = day or today()
    seed_child_chores(db, child)
    rows = assignments_today(db, child.id, day)
    daily = daily_for(db, child.id, day)
    current = open_assignment(rows)
    unlocked = extras_unlocked(daily)
    daily_pickable = []
    extra_listed = visible_chores(db, child, day, EXTRA)
    claimed_extra = {
        a.chore_id
        for a in rows
        if a.kind == EXTRA and a.state in (IN_PROGRESS, PENDING_APPROVAL, APPROVED, RETURNED)
    }
    extra_pickable = []
    if daily is None:
        daily_pickable = visible_chores(db, child, day, DAILY)
    if unlocked and current is None:
        extra_pickable = [
            c for c in extra_listed if c["id"] not in claimed_extra and not c.get("taken_by")
        ]
    return {
        "today": day.isoformat(),
        "child": child_star_view(db, child),
        "daily": {
            "assignment": assignment_view(daily, db) if daily else None,
            "complete": unlocked,
            "pickable": daily_pickable,
        },
        "extra": {
            "unlocked": unlocked,
            "listed": extra_listed,
            "pickable": extra_pickable,
        },
        "current": assignment_view(current, db) if current else None,
        "pending": [
            assignment_view(a, db) for a in rows if a.state == PENDING_APPROVAL
        ],
    }


def pick_chore(db: Session, child: Child, chore_id: str, day: date | None = None) -> Assignment:
    day = day or today()
    seed_child_chores(db, child)
    rows = assignments_today(db, child.id, day)
    if open_assignment(rows) is not None:
        raise HTTPException(400, "Finish your current chore first")
    chore = get_live_chore(db, chore_id)
    if chore is None or not chore.enabled:
        raise HTTPException(404, "Unknown chore")
    link = db.scalar(
        select(ChildChore).where(
            ChildChore.child_id == child.id,
            ChildChore.chore_id == chore_id,
            ChildChore.enabled.is_(True),
        )
    )
    if link is None:
        raise HTTPException(400, "That chore is not on your list")
    taken = claimed_chores_today(db, day, exclude_child_id=child.id)
    if chore_id in taken:
        raise HTTPException(400, f"{taken[chore_id]} already picked that chore today")
    daily = daily_for(db, child.id, day)
    if daily is None:
        kind = DAILY
        if link.kind != DAILY:
            raise HTTPException(400, "Pick today's chore from the regular list")
    else:
        if not extras_unlocked(daily):
            raise HTTPException(400, "Finish today's chore before extras")
        kind = EXTRA
        if link.kind != EXTRA:
            raise HTTPException(400, "That chore is not on your optional list")
        claimed = {
            a.chore_id
            for a in rows
            if a.kind == EXTRA and a.state in (IN_PROGRESS, PENDING_APPROVAL, APPROVED, RETURNED)
        }
        if chore_id in claimed:
            raise HTTPException(400, "You already did that extra today")
    asg = Assignment(
        child_id=child.id,
        chore_id=chore_id,
        day=day,
        kind=kind,
        stars=int(link.stars),
        state=IN_PROGRESS,
    )
    db.add(asg)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(400, "Someone else already picked that chore today")
    db.refresh(asg)
    return asg


def finish_assignment(db: Session, child: Child, assignment_id: int) -> Assignment:
    asg = db.get(Assignment, assignment_id)
    if asg is None or asg.child_id != child.id or asg.state == CANCELLED:
        raise HTTPException(404, "Assignment not found")
    if asg.state not in OPEN_STATES:
        raise HTTPException(400, "That chore is already finished")
    asg.state = PENDING_APPROVAL
    asg.finished_at = datetime.now(timezone.utc)
    asg.return_note = None
    db.commit()
    db.refresh(asg)
    return asg


def approve_assignment(db: Session, assignment_id: int) -> Assignment:
    asg = db.get(Assignment, assignment_id)
    if asg is None or asg.state == CANCELLED:
        raise HTTPException(404, "Assignment not found")
    if asg.state == APPROVED:
        return asg
    if asg.state != PENDING_APPROVAL:
        raise HTTPException(400, "Only finished chores can be approved")
    existing = db.scalar(select(LedgerEntry).where(LedgerEntry.assignment_id == asg.id))
    if existing is None:
        stars = asg.stars
        if stars is None:
            link = db.scalar(
                select(ChildChore).where(
                    ChildChore.child_id == asg.child_id,
                    ChildChore.chore_id == asg.chore_id,
                )
            )
            if link is not None:
                stars = link.stars
            else:
                managed = get_live_chore(db, asg.chore_id)
                stars = managed.stars if managed is not None else None
        if stars is None:
            raise HTTPException(400, "Chore missing from catalog")
        stars = int(stars)
        if stars < 1:
            raise HTTPException(400, "Chore stars must be at least 1")
        db.add(
            LedgerEntry(
                child_id=asg.child_id,
                assignment_id=asg.id,
                stars=stars,
            )
        )
    asg.state = APPROVED
    asg.approved_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(asg)
    return asg


def return_assignment(db: Session, assignment_id: int, note: str) -> Assignment:
    asg = db.get(Assignment, assignment_id)
    if asg is None or asg.state == CANCELLED:
        raise HTTPException(404, "Assignment not found")
    if asg.state == APPROVED:
        raise HTTPException(400, "Already approved")
    if asg.state != PENDING_APPROVAL:
        raise HTTPException(400, "Only finished chores can be sent back")
    asg.state = RETURNED
    asg.return_note = (note or "").strip() or "Please try this one again."
    db.commit()
    db.refresh(asg)
    return asg


def reset_assignment(db: Session, assignment_id: int) -> Assignment:
    asg = db.get(Assignment, assignment_id)
    if asg is None or asg.state == CANCELLED:
        raise HTTPException(404, "Assignment not found")
    if asg.state == APPROVED:
        raise HTTPException(400, "Approved chores keep their Stars")
    asg.state = CANCELLED
    db.commit()
    db.refresh(asg)
    return asg


def cancel_assignment(db: Session, child: Child, assignment_id: int) -> Assignment:
    asg = db.get(Assignment, assignment_id)
    if asg is None or asg.child_id != child.id or asg.state == CANCELLED:
        raise HTTPException(404, "Assignment not found")
    if asg.state == APPROVED:
        raise HTTPException(400, "That chore is already done")
    ledger = db.scalar(select(LedgerEntry).where(LedgerEntry.assignment_id == asg.id))
    if ledger is not None:
        raise HTTPException(400, "That chore already has Stars")
    asg.state = CANCELLED
    db.commit()
    db.refresh(asg)
    return asg


def seed_rewards(db: Session) -> None:
    existing = {row.id for row in db.scalars(select(ManagedReward)).all()}
    for i, reward in enumerate(catalog.all_rewards()):
        if reward["id"] in existing:
            continue
        db.add(
            ManagedReward(
                id=reward["id"],
                title=reward["title"],
                description=reward.get("description") or "",
                stars=int(reward["stars"]),
                min_age=int(reward.get("min_age") or 4),
                emoji=reward.get("emoji") or "★",
                season=reward.get("season"),
                grown_up_required=bool(reward.get("grown_up_required", True)),
                parent_notes=reward.get("parent_notes"),
                enabled=True,
                sort_order=i,
                source="catalog",
            )
        )
    db.commit()


def seed_chores(db: Session) -> None:
    existing = {row.id for row in db.scalars(select(ManagedChore)).all()}
    for i, chore in enumerate(catalog.all()):
        if chore["id"] in existing:
            continue
        db.add(
            ManagedChore(
                id=chore["id"],
                title=chore["title"],
                category=chore.get("category") or "living",
                kind=chore.get("kind") or DAILY,
                min_age=int(chore.get("min_age") or 4),
                minutes=int(chore.get("minutes") or 5),
                stars=int(chore["stars"]),
                grown_up_required=bool(chore.get("grown_up_required", False)),
                materials_json=json.dumps(chore.get("materials") or []),
                steps_json=json.dumps(chore.get("steps") or []),
                done_when_json=json.dumps(chore.get("done_when") or []),
                cover_image=chore.get("cover_image"),
                demo_video=chore.get("demo_video"),
                parent_notes=chore.get("parent_notes"),
                enabled=True,
                sort_order=i,
                source="catalog",
            )
        )
    db.commit()


def seed_all_child_chores(db: Session) -> None:
    seed_chores(db)
    for child in db.scalars(select(Child)).all():
        seed_child_chores(db, child)


def seed_child_chores(db: Session, child: Child) -> None:
    seed_chores(db)
    already = db.scalar(
        select(func.count()).select_from(ChildChore).where(ChildChore.child_id == child.id)
    )
    if int(already or 0) > 0:
        return
    for chore in db.scalars(select(ManagedChore).where(ManagedChore.enabled.is_(True))).all():
        if chore.source != "catalog":
            continue
        if chore.min_age > child.age:
            continue
        db.add(
            ChildChore(
                child_id=child.id,
                chore_id=chore.id,
                kind=chore.kind if chore.kind in (DAILY, EXTRA) else DAILY,
                stars=chore.stars,
                enabled=True,
            )
        )
    db.commit()


def _loads(raw: str | None, default):
    try:
        return json.loads(raw or "") if raw else default
    except json.JSONDecodeError:
        return default


def chore_public(row: ManagedChore, *, stars: int | None = None, kind: str | None = None, parent: bool = False) -> dict:
    view = {
        "id": row.id,
        "title": row.title,
        "category": row.category,
        "kind": kind or row.kind,
        "min_age": row.min_age,
        "minutes": row.minutes,
        "stars": stars if stars is not None else row.stars,
        "grown_up_required": bool(row.grown_up_required),
        "materials": _loads(row.materials_json, []),
        "cover_image": row.cover_image,
        "demo_video": row.demo_video,
        "steps": _loads(row.steps_json, []),
        "done_when": _loads(row.done_when_json, []),
        "enabled": bool(row.enabled),
        "source": row.source,
        "default_stars": row.stars,
        "default_kind": row.kind,
    }
    if parent:
        view["parent_notes"] = row.parent_notes
    return view


def list_managed_chores(db: Session) -> list[ManagedChore]:
    seed_chores(db)
    return list(db.scalars(select(ManagedChore).order_by(ManagedChore.sort_order, ManagedChore.title)))


def get_live_chore(db: Session, chore_id: str) -> ManagedChore | None:
    return db.get(ManagedChore, chore_id)


def _parse_lines(raw) -> list:
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    return [ln.strip() for ln in str(raw).splitlines() if ln.strip()]


def _parse_steps(raw) -> list:
    if isinstance(raw, list):
        return raw
    steps = []
    for line in _parse_lines(raw):
        if " | " in line:
            text, tip = line.split(" | ", 1)
            steps.append({"text": text.strip(), "tip": tip.strip()})
        else:
            steps.append({"text": line, "tip": ""})
    return steps


def create_chore(db: Session, data: dict) -> ManagedChore:
    title = (data.get("title") or "").strip()
    if not title:
        raise HTTPException(400, "Title is required")
    stars = int(data.get("stars") or 0)
    if stars < 1 or stars > 999:
        raise HTTPException(400, "Stars must be 1–999")
    min_age = int(data.get("min_age") or 4)
    if min_age < 3 or min_age > 18:
        raise HTTPException(400, "Age must be 3–18")
    kind = data.get("kind") or DAILY
    if kind not in (DAILY, EXTRA):
        raise HTTPException(400, "Kind must be daily or extra")
    base = _slug_id(title)
    chore_id = base
    n = 2
    while db.get(ManagedChore, chore_id) is not None:
        chore_id = f"{base}_{n}"
        n += 1
    max_order = db.scalar(select(func.max(ManagedChore.sort_order))) or 0
    row = ManagedChore(
        id=chore_id,
        title=title,
        category=(data.get("category") or "living").strip() or "living",
        kind=kind,
        min_age=min_age,
        minutes=int(data.get("minutes") or 5),
        stars=stars,
        grown_up_required=bool(data.get("grown_up_required", False)),
        materials_json=json.dumps(_parse_lines(data.get("materials"))),
        steps_json=json.dumps(_parse_steps(data.get("steps"))),
        done_when_json=json.dumps(_parse_lines(data.get("done_when"))),
        parent_notes=(data.get("parent_notes") or "").strip() or None,
        enabled=bool(data.get("enabled", True)),
        sort_order=max_order + 1,
        source="custom",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_chore(db: Session, chore_id: str, data: dict) -> ManagedChore:
    row = db.get(ManagedChore, chore_id)
    if row is None:
        raise HTTPException(404, "Unknown chore")
    if "title" in data and data["title"] is not None:
        title = str(data["title"]).strip()
        if not title:
            raise HTTPException(400, "Title is required")
        row.title = title
    if "category" in data and data["category"] is not None:
        row.category = str(data["category"]).strip() or "living"
    if "kind" in data and data["kind"] is not None:
        kind = data["kind"]
        if kind not in (DAILY, EXTRA):
            raise HTTPException(400, "Kind must be daily or extra")
        row.kind = kind
    if "stars" in data and data["stars"] is not None:
        stars = int(data["stars"])
        if stars < 1 or stars > 999:
            raise HTTPException(400, "Stars must be 1–999")
        row.stars = stars
    if "min_age" in data and data["min_age"] is not None:
        min_age = int(data["min_age"])
        if min_age < 3 or min_age > 18:
            raise HTTPException(400, "Age must be 3–18")
        row.min_age = min_age
    if "minutes" in data and data["minutes"] is not None:
        row.minutes = int(data["minutes"])
    if "grown_up_required" in data and data["grown_up_required"] is not None:
        row.grown_up_required = bool(data["grown_up_required"])
    if "materials" in data:
        row.materials_json = json.dumps(_parse_lines(data.get("materials")))
    if "steps" in data:
        row.steps_json = json.dumps(_parse_steps(data.get("steps")))
    if "done_when" in data:
        row.done_when_json = json.dumps(_parse_lines(data.get("done_when")))
    if "parent_notes" in data:
        notes = data.get("parent_notes")
        row.parent_notes = (str(notes).strip() if notes else "") or None
    if "enabled" in data and data["enabled"] is not None:
        row.enabled = bool(data["enabled"])
    db.commit()
    db.refresh(row)
    return row


def delete_chore(db: Session, chore_id: str) -> None:
    row = db.get(ManagedChore, chore_id)
    if row is None:
        raise HTTPException(404, "Unknown chore")
    used = db.scalar(select(func.count()).select_from(Assignment).where(Assignment.chore_id == chore_id))
    if row.source == "catalog" or int(used or 0) > 0:
        row.enabled = False
        db.commit()
        return
    db.execute(delete(ChildChore).where(ChildChore.chore_id == chore_id))
    _unlink_upload(row.cover_image)
    _unlink_upload(row.demo_video)
    db.delete(row)
    db.commit()


def _uploads_root() -> Path:
    root = CATALOG_DIR / "media" / "uploads"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _unlink_upload(rel: str | None) -> None:
    if not rel or not str(rel).startswith(UPLOAD_DIR + "/"):
        return
    path = (CATALOG_DIR / rel).resolve()
    root = _uploads_root().resolve()
    if path.is_file() and path.is_relative_to(root):
        path.unlink()


def catalog_default_cover(chore_id: str) -> str | None:
    for ext in ("jpg", "jpeg", "png", "webp", "gif"):
        rel = f"media/images/{chore_id}.{ext}"
        if (CATALOG_DIR / rel).is_file():
            return rel
    return None


def catalog_default_video(chore_id: str) -> str | None:
    for ext in ("mp4", "webm"):
        rel = f"media/videos/{chore_id}.{ext}"
        if (CATALOG_DIR / rel).is_file():
            return rel
    return None


def _sniff_media(data: bytes) -> tuple[str, str]:
    """Return (kind, extension) for cover or video bytes."""
    if len(data) >= 3 and data[:3] == b"\xff\xd8\xff":
        return "cover", "jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "cover", "png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "cover", "gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "cover", "webp"
    if len(data) >= 12 and data[4:8] == b"ftyp":
        brand = data[8:12]
        if brand in (b"qt  ", b"mqt "):
            return "video", "mov"
        return "video", "mp4"
    if data[:4] == b"\x1a\x45\xdf\xa3":
        return "video", "webm"
    raise HTTPException(400, "Use a JPEG, PNG, WebP, GIF, MP4, or WebM file")


def save_chore_media(db: Session, chore_id: str, kind: str, data: bytes) -> ManagedChore:
    if not CHORE_ID_RE.fullmatch(chore_id or ""):
        raise HTTPException(400, "Bad chore id")
    row = db.get(ManagedChore, chore_id)
    if row is None:
        raise HTTPException(404, "Unknown chore")
    kind = (kind or "").strip().lower()
    if kind not in ("cover", "video"):
        raise HTTPException(400, "Kind must be cover or video")
    sniffed, ext = _sniff_media(data)
    if sniffed == "video" and ext == "mov":
        raise HTTPException(400, "Video must be MP4 or WebM")
    if sniffed != kind:
        if kind == "cover":
            raise HTTPException(400, "Picture must be a JPEG, PNG, WebP, or GIF")
        raise HTTPException(400, "Video must be MP4 or WebM")
    limit = MAX_COVER_BYTES if kind == "cover" else MAX_VIDEO_BYTES
    if len(data) > limit:
        raise HTTPException(400, "That file is too large")
    dest = _uploads_root() / f"{chore_id}.{ext}"
    if kind == "cover":
        _unlink_upload(row.cover_image)
        dest.write_bytes(data)
        row.cover_image = f"{UPLOAD_DIR}/{chore_id}.{ext}"
    else:
        _unlink_upload(row.demo_video)
        dest.write_bytes(data)
        row.demo_video = f"{UPLOAD_DIR}/{chore_id}.{ext}"
    db.commit()
    db.refresh(row)
    return row


def clear_chore_media(db: Session, chore_id: str, kind: str) -> ManagedChore:
    if not CHORE_ID_RE.fullmatch(chore_id or ""):
        raise HTTPException(400, "Bad chore id")
    row = db.get(ManagedChore, chore_id)
    if row is None:
        raise HTTPException(404, "Unknown chore")
    kind = (kind or "").strip().lower()
    if kind == "cover":
        _unlink_upload(row.cover_image)
        row.cover_image = catalog_default_cover(chore_id)
    elif kind == "video":
        _unlink_upload(row.demo_video)
        row.demo_video = catalog_default_video(chore_id)
    else:
        raise HTTPException(400, "Kind must be cover or video")
    db.commit()
    db.refresh(row)
    return row


def child_assignments_payload(db: Session, child: Child) -> dict:
    seed_child_chores(db, child)
    links = {row.chore_id: row for row in child_chore_rows(db, child.id)}
    items = []
    for chore in list_managed_chores(db):
        if not chore.enabled and chore.id not in links:
            continue
        link = links.get(chore.id)
        items.append(
            {
                "chore": chore_public(chore, parent=True),
                "assigned": link is not None and link.enabled,
                "kind": link.kind if link else chore.kind,
                "stars": link.stars if link else chore.stars,
            }
        )
    return {"child": child_star_view(db, child), "items": items}


def set_child_chores(db: Session, child: Child, items: list[dict]) -> dict:
    seed_chores(db)
    existing = {row.chore_id: row for row in child_chore_rows(db, child.id)}
    keep = set()
    for item in items:
        chore_id = item.get("chore_id")
        chore = get_live_chore(db, chore_id) if chore_id else None
        if chore is None:
            raise HTTPException(400, f"Unknown chore {chore_id}")
        kind = item.get("kind") or chore.kind
        if kind not in (DAILY, EXTRA):
            raise HTTPException(400, "Kind must be daily or extra")
        stars = int(item.get("stars") or chore.stars)
        if stars < 1 or stars > 999:
            raise HTTPException(400, "Stars must be 1–999")
        enabled = bool(item.get("enabled", True))
        keep.add(chore_id)
        row = existing.get(chore_id)
        if row is None:
            db.add(
                ChildChore(
                    child_id=child.id,
                    chore_id=chore_id,
                    kind=kind,
                    stars=stars,
                    enabled=enabled,
                )
            )
        else:
            row.kind = kind
            row.stars = stars
            row.enabled = enabled
    for chore_id, row in existing.items():
        if chore_id not in keep:
            db.delete(row)
    db.commit()
    return child_assignments_payload(db, child)


def child_chore_rows(db: Session, child_id: int) -> list[ChildChore]:
    return list(
        db.scalars(
            select(ChildChore)
            .where(ChildChore.child_id == child_id)
            .order_by(ChildChore.id)
        )
    )


def claimed_chores_today(db: Session, day: date, exclude_child_id: int | None = None) -> dict[str, str]:
    q = (
        select(Assignment, Child)
        .join(Child, Child.id == Assignment.child_id)
        .where(Assignment.day == day, Assignment.state.in_(CLAIMED_STATES))
    )
    if exclude_child_id is not None:
        q = q.where(Assignment.child_id != exclude_child_id)
    taken: dict[str, str] = {}
    for asg, other in db.execute(q):
        taken[asg.chore_id] = other.display_name
    return taken


def visible_chores(db: Session, child: Child, day: date, kind: str) -> list[dict]:
    seed_child_chores(db, child)
    taken = claimed_chores_today(db, day, exclude_child_id=child.id)
    out = []
    for link in child_chore_rows(db, child.id):
        if not link.enabled or link.kind != kind:
            continue
        chore = get_live_chore(db, link.chore_id)
        if chore is None or not chore.enabled:
            continue
        view = chore_public(chore, stars=link.stars, kind=link.kind)
        if chore.id in taken:
            view["taken_by"] = taken[chore.id]
        out.append(view)
    return out


def assignment_view(asg: Assignment, db: Session | None = None) -> dict:
    chore = None
    if db is not None:
        managed = get_live_chore(db, asg.chore_id)
        if managed is not None:
            chore = chore_public(managed, stars=asg.stars, kind=asg.kind, parent=True)
    if chore is None:
        raw = catalog.get(asg.chore_id)
        chore = catalog.public(raw) if raw else None
        if chore is not None:
            if asg.stars is not None:
                chore["stars"] = asg.stars
            chore["kind"] = asg.kind
    return {
        "id": asg.id,
        "chore_id": asg.chore_id,
        "kind": asg.kind,
        "state": asg.state,
        "return_note": asg.return_note,
        "chore": chore,
    }


def seed_parent(db: Session) -> None:
    existing = db.scalar(select(Parent).where(Parent.username == PARENT_USERNAME))
    if existing is None:
        db.add(
            Parent(
                username=PARENT_USERNAME,
                password_hash=hash_secret(PARENT_PASSWORD),
            )
        )
        db.commit()
        return
    # Keep a known password in empty-dev only if still the default hash of change-me.
    # Do not reset a parent-changed password.


def create_child(db: Session, display_name: str, age: int, pin: str) -> Child:
    name = display_name.strip()
    if not name:
        raise HTTPException(400, "Name is required")
    if age < 3 or age > 18:
        raise HTTPException(400, "Age must be 3–18")
    if not pin.isdigit() or not (4 <= len(pin) <= 8):
        raise HTTPException(400, "PIN must be 4–8 digits")
    child = Child(display_name=name, age=age, pin_hash=hash_secret(pin))
    db.add(child)
    db.commit()
    db.refresh(child)
    seed_child_chores(db, child)
    return child


def update_child(db: Session, child_id: int, age: int | None, pin: str | None) -> Child:
    child = get_child(db, child_id)
    if age is not None:
        if age < 3 or age > 18:
            raise HTTPException(400, "Age must be 3–18")
        child.age = age
    if pin is not None:
        if not pin.isdigit() or not (4 <= len(pin) <= 8):
            raise HTTPException(400, "PIN must be 4–8 digits")
        child.pin_hash = hash_secret(pin)
    db.commit()
    db.refresh(child)
    return child


def login_child(db: Session, child_id: int, pin: str) -> Child:
    child = get_child(db, child_id)
    if not verify_secret(pin, child.pin_hash):
        raise HTTPException(401, "Wrong PIN")
    return child


def login_parent(db: Session, username: str, password: str) -> Parent:
    parent = db.scalar(select(Parent).where(Parent.username == username))
    if parent is None or not verify_secret(password, parent.password_hash):
        raise HTTPException(401, "Wrong username or password")
    return parent


def inbox(db: Session, day: date | None = None) -> list[dict]:
    day = day or today()
    rows = list(
        db.scalars(
            select(Assignment)
            .where(
                Assignment.day == day,
                Assignment.state.in_((PENDING_APPROVAL, RETURNED)),
            )
            .order_by(Assignment.finished_at.desc().nullslast(), Assignment.id)
        )
    )
    out = []
    for asg in rows:
        child = db.get(Child, asg.child_id)
        view = assignment_view(asg, db)
        view["child"] = child_star_view(db, child) if child else None
        out.append(view)
    return out


def reward_public(row: ManagedReward, parent: bool = False) -> dict:
    view = {
        "id": row.id,
        "title": row.title,
        "description": row.description or "",
        "stars": row.stars,
        "min_age": row.min_age,
        "emoji": row.emoji or "★",
        "season": row.season,
        "grown_up_required": bool(row.grown_up_required),
        "enabled": bool(row.enabled),
        "source": row.source,
        "sort_order": row.sort_order,
    }
    if parent:
        view["parent_notes"] = row.parent_notes
    return view


def get_live_reward(db: Session, reward_id: str) -> ManagedReward | None:
    return db.get(ManagedReward, reward_id)


def list_managed_rewards(db: Session) -> list[ManagedReward]:
    seed_rewards(db)
    return list(db.scalars(select(ManagedReward).order_by(ManagedReward.sort_order, ManagedReward.title)))


def _slug_id(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")
    return slug[:48] or "reward"


def create_reward(db: Session, data: dict) -> ManagedReward:
    title = (data.get("title") or "").strip()
    if not title:
        raise HTTPException(400, "Title is required")
    stars = int(data.get("stars") or 0)
    if stars < 1 or stars > 999:
        raise HTTPException(400, "Stars must be 1–999")
    min_age = int(data.get("min_age") or 4)
    if min_age < 3 or min_age > 18:
        raise HTTPException(400, "Age must be 3–18")
    base = _slug_id(title)
    reward_id = base
    n = 2
    while db.get(ManagedReward, reward_id) is not None:
        reward_id = f"{base}_{n}"
        n += 1
    max_order = db.scalar(select(func.max(ManagedReward.sort_order))) or 0
    season = (data.get("season") or "").strip() or None
    row = ManagedReward(
        id=reward_id,
        title=title,
        description=(data.get("description") or "").strip(),
        stars=stars,
        min_age=min_age,
        emoji=(data.get("emoji") or "★").strip()[:16] or "★",
        season=season,
        grown_up_required=bool(data.get("grown_up_required", True)),
        parent_notes=(data.get("parent_notes") or "").strip() or None,
        enabled=bool(data.get("enabled", True)),
        sort_order=max_order + 1,
        source="custom",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_reward(db: Session, reward_id: str, data: dict) -> ManagedReward:
    row = db.get(ManagedReward, reward_id)
    if row is None:
        raise HTTPException(404, "Unknown reward")
    if "title" in data and data["title"] is not None:
        title = str(data["title"]).strip()
        if not title:
            raise HTTPException(400, "Title is required")
        row.title = title
    if "description" in data and data["description"] is not None:
        row.description = str(data["description"]).strip()
    if "stars" in data and data["stars"] is not None:
        stars = int(data["stars"])
        if stars < 1 or stars > 999:
            raise HTTPException(400, "Stars must be 1–999")
        row.stars = stars
    if "min_age" in data and data["min_age"] is not None:
        min_age = int(data["min_age"])
        if min_age < 3 or min_age > 18:
            raise HTTPException(400, "Age must be 3–18")
        row.min_age = min_age
    if "emoji" in data and data["emoji"] is not None:
        row.emoji = str(data["emoji"]).strip()[:16] or "★"
    if "season" in data:
        season = (data.get("season") or "").strip() or None
        row.season = season
    if "grown_up_required" in data and data["grown_up_required"] is not None:
        row.grown_up_required = bool(data["grown_up_required"])
    if "parent_notes" in data:
        notes = data.get("parent_notes")
        row.parent_notes = (str(notes).strip() if notes else "") or None
    if "enabled" in data and data["enabled"] is not None:
        row.enabled = bool(data["enabled"])
    if "sort_order" in data and data["sort_order"] is not None:
        row.sort_order = int(data["sort_order"])
    db.commit()
    db.refresh(row)
    return row


def delete_reward(db: Session, reward_id: str) -> None:
    row = db.get(ManagedReward, reward_id)
    if row is None:
        raise HTTPException(404, "Unknown reward")
    used = db.scalar(select(func.count()).select_from(Redemption).where(Redemption.reward_id == reward_id))
    if row.source == "catalog" or int(used or 0) > 0:
        row.enabled = False
        db.commit()
        return
    db.delete(row)
    db.commit()


def redemption_view(db: Session, row: Redemption, parent: bool = False) -> dict:
    managed = get_live_reward(db, row.reward_id)
    if managed is not None:
        public = reward_public(managed, parent=parent)
    else:
        reward = catalog.get_reward(row.reward_id)
        public = catalog.public_reward(reward) if reward else None
        if parent and public and reward:
            public["parent_notes"] = reward.get("parent_notes")
    child = db.get(Child, row.child_id)
    return {
        "id": row.id,
        "reward_id": row.reward_id,
        "stars": row.stars,
        "state": row.state,
        "note": row.note,
        "reward": public,
        "child": child_star_view(db, child) if child else None,
    }


def shop_for(db: Session, child: Child) -> dict:
    listed = []
    for reward in list_managed_rewards(db):
        if not reward.enabled:
            continue
        if reward.min_age > child.age:
            continue
        listed.append(reward_public(reward))
    pending = list(
        db.scalars(
            select(Redemption)
            .where(Redemption.child_id == child.id, Redemption.state == REQUESTED)
            .order_by(Redemption.created_at.desc())
        )
    )
    return {
        "child": child_star_view(db, child),
        "rewards": listed,
        "pending": [redemption_view(db, r) for r in pending],
    }


def request_redemption(db: Session, child: Child, reward_id: str) -> Redemption:
    reward = get_live_reward(db, reward_id)
    if reward is None or not reward.enabled:
        raise HTTPException(404, "Unknown reward")
    if reward.min_age > child.age:
        raise HTTPException(400, "That reward is for older kids")
    cost = int(reward.stars)
    if cost < 1:
        raise HTTPException(400, "Reward stars must be at least 1")
    if available_stars(db, child.id) < cost:
        raise HTTPException(400, "Not enough Stars yet")
    row = Redemption(
        child_id=child.id,
        reward_id=reward_id,
        stars=cost,
        state=REQUESTED,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def cancel_redemption(db: Session, child: Child, redemption_id: int) -> Redemption:
    row = db.get(Redemption, redemption_id)
    if row is None or row.child_id != child.id or row.state == CANCELLED:
        raise HTTPException(404, "Reward request not found")
    if row.state != REQUESTED:
        raise HTTPException(400, "That reward request already finished")
    row.state = CANCELLED
    row.decided_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return row


def approve_redemption(db: Session, redemption_id: int) -> Redemption:
    row = db.get(Redemption, redemption_id)
    if row is None or row.state == CANCELLED:
        raise HTTPException(404, "Reward request not found")
    if row.state == APPROVED:
        return row
    if row.state != REQUESTED:
        raise HTTPException(400, "Only waiting requests can be approved")
    existing = db.scalar(select(LedgerEntry).where(LedgerEntry.redemption_id == row.id))
    if existing is None:
        db.add(
            LedgerEntry(
                child_id=row.child_id,
                assignment_id=None,
                redemption_id=row.id,
                stars=-int(row.stars),
            )
        )
    row.state = APPROVED
    row.decided_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return row


def deny_redemption(db: Session, redemption_id: int, note: str) -> Redemption:
    row = db.get(Redemption, redemption_id)
    if row is None or row.state == CANCELLED:
        raise HTTPException(404, "Reward request not found")
    if row.state == APPROVED:
        raise HTTPException(400, "Already cashed in")
    if row.state != REQUESTED:
        raise HTTPException(400, "Only waiting requests can be sent back")
    row.state = DENIED
    row.note = (note or "").strip() or "A grown-up said not this time."
    row.decided_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return row


def redemption_inbox(db: Session) -> list[dict]:
    rows = list(
        db.scalars(
            select(Redemption)
            .where(Redemption.state == REQUESTED)
            .order_by(Redemption.created_at)
        )
    )
    return [redemption_view(db, r, parent=True) for r in rows]
