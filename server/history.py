from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from server.catalog import catalog
from server.models import (
    APPROVED,
    CANCELLED,
    DENIED,
    PENDING_APPROVAL,
    REQUESTED,
    RETURNED,
    Assignment,
    Child,
    LedgerEntry,
    Redemption,
)
from server.services import child_star_view


def _local_day(dt: datetime | None) -> date | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone().date()


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _chore_title(db: Session, chore_id: str) -> str:
    from server.services import get_live_chore

    managed = get_live_chore(db, chore_id)
    if managed is not None:
        return managed.title
    chore = catalog.get(chore_id)
    return chore["title"] if chore else chore_id


def _assignment_stars(db: Session, asg: Assignment) -> int:
    if asg.stars is not None:
        return int(asg.stars)
    from server.services import get_live_chore

    managed = get_live_chore(db, asg.chore_id)
    if managed is not None:
        return int(managed.stars)
    chore = catalog.get(asg.chore_id) or {}
    return int(chore.get("stars") or 0)


def _reward_title(db: Session, reward_id: str) -> str:
    from server.services import get_live_reward

    row = get_live_reward(db, reward_id)
    if row is not None:
        return row.title
    reward = catalog.get_reward(reward_id)
    return reward["title"] if reward else reward_id


def history_for(db: Session, child: Child, days: int = 14) -> dict:
    end = date.today()
    start = end - timedelta(days=days - 1)
    ledger = list(
        db.scalars(
            select(LedgerEntry)
            .where(LedgerEntry.child_id == child.id)
            .order_by(LedgerEntry.created_at, LedgerEntry.id)
        )
    )
    assignments = list(
        db.scalars(
            select(Assignment)
            .where(Assignment.child_id == child.id)
            .order_by(Assignment.created_at.desc())
        )
    )
    redemptions = list(
        db.scalars(
            select(Redemption)
            .where(Redemption.child_id == child.id)
            .order_by(Redemption.created_at.desc())
        )
    )

    earned_total = sum(row.stars for row in ledger if row.stars > 0)
    spent_total = sum(-row.stars for row in ledger if row.stars < 0)
    approved_chores = sum(1 for a in assignments if a.state == APPROVED)

    by_day = {
        start + timedelta(days=i): {"earned": 0, "spent": 0, "chores": 0, "rewards": 0}
        for i in range(days)
    }
    balance_before = 0
    for row in ledger:
        day = _local_day(row.created_at)
        if day is not None and day < start:
            balance_before += row.stars
        if day is None or day not in by_day:
            continue
        if row.stars > 0:
            by_day[day]["earned"] += row.stars
        elif row.stars < 0:
            by_day[day]["spent"] += -row.stars
    for asg in assignments:
        if asg.state == APPROVED and asg.day in by_day:
            by_day[asg.day]["chores"] += 1
    for red in redemptions:
        day = _local_day(red.decided_at or red.created_at)
        if red.state == APPROVED and day in by_day:
            by_day[day]["rewards"] += 1

    series = []
    running_bal = balance_before
    for i in range(days):
        day = start + timedelta(days=i)
        bucket = by_day[day]
        running_bal += bucket["earned"] - bucket["spent"]
        series.append(
            {
                "date": day.isoformat(),
                "label": f"{day.month}/{day.day}",
                "earned": bucket["earned"],
                "spent": bucket["spent"],
                "chores": bucket["chores"],
                "rewards": bucket["rewards"],
                "balance": running_bal,
            }
        )

    events = []
    for asg in assignments:
        title = _chore_title(db, asg.chore_id)
        if asg.state == APPROVED and asg.approved_at:
            stars = _assignment_stars(db, asg)
            events.append(
                {
                    "at": _iso(asg.approved_at),
                    "kind": "chore_approved",
                    "title": title,
                    "detail": f"Approved · ★ {stars}",
                    "stars": stars,
                }
            )
        elif asg.state == PENDING_APPROVAL and asg.finished_at:
            events.append(
                {
                    "at": _iso(asg.finished_at),
                    "kind": "chore_finished",
                    "title": title,
                    "detail": "Waiting for a grown-up",
                    "stars": 0,
                }
            )
        elif asg.state == RETURNED:
            events.append(
                {
                    "at": _iso(asg.finished_at or asg.created_at),
                    "kind": "chore_returned",
                    "title": title,
                    "detail": asg.return_note or "Please try again",
                    "stars": 0,
                }
            )
        elif asg.state == CANCELLED:
            events.append(
                {
                    "at": _iso(asg.created_at),
                    "kind": "chore_cancelled",
                    "title": title,
                    "detail": "Cancelled",
                    "stars": 0,
                }
            )
        elif asg.state not in (CANCELLED,):
            events.append(
                {
                    "at": _iso(asg.created_at),
                    "kind": "chore_picked",
                    "title": title,
                    "detail": "Started",
                    "stars": 0,
                }
            )
    for red in redemptions:
        title = _reward_title(db, red.reward_id)
        if red.state == APPROVED:
            events.append(
                {
                    "at": _iso(red.decided_at or red.created_at),
                    "kind": "reward_approved",
                    "title": title,
                    "detail": f"Cashed in · ★ {red.stars}",
                    "stars": -int(red.stars),
                }
            )
        elif red.state == REQUESTED:
            events.append(
                {
                    "at": _iso(red.created_at),
                    "kind": "reward_requested",
                    "title": title,
                    "detail": f"Waiting · ★ {red.stars} held",
                    "stars": 0,
                }
            )
        elif red.state == DENIED:
            events.append(
                {
                    "at": _iso(red.decided_at or red.created_at),
                    "kind": "reward_denied",
                    "title": title,
                    "detail": red.note or "Not this time",
                    "stars": 0,
                }
            )
    events.sort(key=lambda e: e.get("at") or "", reverse=True)

    stars_view = child_star_view(db, child)
    return {
        "child": stars_view,
        "range_days": days,
        "summary": {
            "chores_approved": approved_chores,
            "rewards_cashed": sum(1 for r in redemptions if r.state == APPROVED),
            "stars_earned": earned_total,
            "stars_spent": spent_total,
            "stars": stars_view["stars"],
            "available": stars_view["available"],
        },
        "days": series,
        "events": events[:50],
        "rewards": redemption_history(db, redemptions),
    }


def redemption_history(db: Session, redemptions: list[Redemption]) -> list[dict]:
    from server.services import get_live_reward

    rows = []
    for red in redemptions:
        managed = get_live_reward(db, red.reward_id)
        if managed is not None:
            reward = {
                "title": managed.title,
                "emoji": managed.emoji,
            }
        else:
            reward = catalog.get_reward(red.reward_id) or {}
        state_label = {
            APPROVED: "Cashed in",
            REQUESTED: "Waiting for a grown-up",
            DENIED: "Not this time",
            CANCELLED: "Cancelled",
        }.get(red.state, red.state)
        rows.append(
            {
                "id": red.id,
                "reward_id": red.reward_id,
                "title": reward.get("title") or red.reward_id,
                "emoji": reward.get("emoji") or "★",
                "stars": red.stars,
                "state": red.state,
                "state_label": state_label,
                "note": red.note,
                "at": _iso(red.decided_at or red.created_at),
            }
        )
    rows.sort(key=lambda r: r.get("at") or "", reverse=True)
    return rows
