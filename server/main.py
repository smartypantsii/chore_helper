from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from server import history as history_mod
from server import services
from server.catalog import catalog
from server.config import CATALOG_DIR, WEB_DIR, session_secret
from server import db as db_mod
from server.db import Base, get_db, init_engine
from server.models import Child, Parent


@asynccontextmanager
async def lifespan(_app: FastAPI):
    engine = init_engine()
    db_mod.migrate_schema(engine)
    Base.metadata.create_all(engine)
    catalog.reload()
    session = db_mod.SessionLocal()
    try:
        services.seed_parent(session)
        services.seed_rewards(session)
        services.seed_chores(session)
        services.seed_all_child_chores(session)
        services.ensure_today_pools(session, services.today())
    finally:
        session.close()
    yield


app = FastAPI(title="Chore Helper", lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=session_secret(),
    session_cookie="chore_helper",
    same_site="lax",
    https_only=False,
    max_age=60 * 60 * 24 * 14,
)

app.mount("/catalog", StaticFiles(directory=CATALOG_DIR), name="catalog")
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


@app.middleware("http")
async def no_cache_ui(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path in ("/", "/parent") or path.startswith("/static/") or path.startswith("/catalog/"):
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
    return response


class KidLoginIn(BaseModel):
    child_id: int
    pin: str


class ParentLoginIn(BaseModel):
    username: str
    password: str


class ChildIn(BaseModel):
    display_name: str
    age: int
    pin: str


class ChildPatch(BaseModel):
    age: int | None = None
    pin: str | None = None


class PickIn(BaseModel):
    chore_id: str


class FinishIn(BaseModel):
    assignment_id: int


class RedeemIn(BaseModel):
    reward_id: str


class RedeemIdIn(BaseModel):
    redemption_id: int


class ReturnIn(BaseModel):
    note: str = ""


class PoolsIn(BaseModel):
    daily: list[str] = Field(default_factory=list)
    extra: list[str] = Field(default_factory=list)


class RewardIn(BaseModel):
    title: str
    description: str = ""
    stars: int
    min_age: int = 4
    emoji: str = "★"
    season: str | None = None
    grown_up_required: bool = True
    parent_notes: str | None = None
    enabled: bool = True


class ChoreIn(BaseModel):
    title: str
    category: str = "living"
    kind: str = "daily"
    stars: int
    min_age: int = 4
    minutes: int = 5
    grown_up_required: bool = False
    materials: str = ""
    steps: str = ""
    done_when: str = ""
    parent_notes: str | None = None
    enabled: bool = True


class ChorePatch(BaseModel):
    title: str | None = None
    category: str | None = None
    kind: str | None = None
    stars: int | None = None
    min_age: int | None = None
    minutes: int | None = None
    grown_up_required: bool | None = None
    materials: str | None = None
    steps: str | None = None
    done_when: str | None = None
    parent_notes: str | None = None
    enabled: bool | None = None


class ChildChoreItem(BaseModel):
    chore_id: str
    kind: str
    stars: int
    enabled: bool = True


class ChildChoresIn(BaseModel):
    items: list[ChildChoreItem] = Field(default_factory=list)


class RewardPatch(BaseModel):
    title: str | None = None
    description: str | None = None
    stars: int | None = None
    min_age: int | None = None
    emoji: str | None = None
    season: str | None = None
    grown_up_required: bool | None = None
    parent_notes: str | None = None
    enabled: bool | None = None
    sort_order: int | None = None


def require_child(request: Request, db: Session = Depends(get_db)) -> Child:
    if request.session.get("role") != "child":
        raise HTTPException(401, "Kid login required")
    return services.get_child(db, int(request.session["child_id"]))


def require_parent(request: Request, db: Session = Depends(get_db)) -> Parent:
    if request.session.get("role") != "parent":
        raise HTTPException(401, "Parent login required")
    parent = db.get(Parent, int(request.session["parent_id"]))
    if parent is None:
        raise HTTPException(401, "Parent login required")
    return parent


@app.get("/")
def kids_page():
    return FileResponse(
        WEB_DIR / "index.html",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@app.get("/parent")
def parent_page():
    return FileResponse(
        WEB_DIR / "parent.html",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@app.get("/api/children")
def list_children_public(db: Session = Depends(get_db)):
    rows = list(db.scalars(select(Child).order_by(Child.display_name)))
    return [{"id": c.id, "display_name": c.display_name, "age": c.age} for c in rows]


@app.post("/api/kids/login")
def kid_login(body: KidLoginIn, request: Request, db: Session = Depends(get_db)):
    child = services.login_child(db, body.child_id, body.pin)
    request.session.clear()
    request.session["role"] = "child"
    request.session["child_id"] = child.id
    return {"ok": True, "child": {"id": child.id, "display_name": child.display_name, "age": child.age}}


@app.post("/api/parent/login")
def parent_login(body: ParentLoginIn, request: Request, db: Session = Depends(get_db)):
    parent = services.login_parent(db, body.username, body.password)
    request.session.clear()
    request.session["role"] = "parent"
    request.session["parent_id"] = parent.id
    return {"ok": True, "username": parent.username}


@app.post("/api/logout")
def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@app.get("/api/session")
def session_info(request: Request, db: Session = Depends(get_db)):
    role = request.session.get("role")
    if role == "child":
        child = services.get_child(db, int(request.session["child_id"]))
        return {
            "role": "child",
            "child": {"id": child.id, "display_name": child.display_name, "age": child.age},
        }
    if role == "parent":
        parent = db.get(Parent, int(request.session["parent_id"]))
        return {"role": "parent", "username": parent.username if parent else None}
    return {"role": None}


@app.get("/api/kid/state")
def kid_state(child: Child = Depends(require_child), db: Session = Depends(get_db)):
    return services.kid_state(db, child)


@app.post("/api/kid/pick")
def kid_pick(
    body: PickIn,
    child: Child = Depends(require_child),
    db: Session = Depends(get_db),
):
    asg = services.pick_chore(db, child, body.chore_id)
    return services.assignment_view(asg, db)


@app.post("/api/kid/finish")
def kid_finish(
    body: FinishIn,
    child: Child = Depends(require_child),
    db: Session = Depends(get_db),
):
    asg = services.finish_assignment(db, child, body.assignment_id)
    return services.assignment_view(asg, db)


@app.post("/api/kid/cancel")
def kid_cancel(
    body: FinishIn,
    child: Child = Depends(require_child),
    db: Session = Depends(get_db),
):
    asg = services.cancel_assignment(db, child, body.assignment_id)
    return {"id": asg.id, "state": asg.state}


@app.get("/api/kid/rewards")
def kid_rewards(child: Child = Depends(require_child), db: Session = Depends(get_db)):
    return services.shop_for(db, child)


@app.get("/api/kid/history")
def kid_history(child: Child = Depends(require_child), db: Session = Depends(get_db)):
    return history_mod.history_for(db, child)


@app.post("/api/kid/redeem")
def kid_redeem(
    body: RedeemIn,
    child: Child = Depends(require_child),
    db: Session = Depends(get_db),
):
    row = services.request_redemption(db, child, body.reward_id)
    return services.redemption_view(db, row)


@app.post("/api/kid/redeem/cancel")
def kid_cancel_redeem(
    body: RedeemIdIn,
    child: Child = Depends(require_child),
    db: Session = Depends(get_db),
):
    row = services.cancel_redemption(db, child, body.redemption_id)
    return {"id": row.id, "state": row.state}


@app.get("/api/parent/children")
def parent_children(_parent: Parent = Depends(require_parent), db: Session = Depends(get_db)):
    rows = list(db.scalars(select(Child).order_by(Child.display_name)))
    return [services.child_star_view(db, c) for c in rows]


@app.get("/api/parent/children/{child_id}/history")
def parent_child_history(
    child_id: int,
    _parent: Parent = Depends(require_parent),
    db: Session = Depends(get_db),
):
    child = services.get_child(db, child_id)
    return history_mod.history_for(db, child)


@app.post("/api/parent/children")
def parent_add_child(
    body: ChildIn,
    _parent: Parent = Depends(require_parent),
    db: Session = Depends(get_db),
):
    child = services.create_child(db, body.display_name, body.age, body.pin)
    return {"id": child.id, "display_name": child.display_name, "age": child.age, "stars": 0}


@app.patch("/api/parent/children/{child_id}")
def parent_patch_child(
    child_id: int,
    body: ChildPatch,
    _parent: Parent = Depends(require_parent),
    db: Session = Depends(get_db),
):
    child = services.update_child(db, child_id, body.age, body.pin)
    return {
        "id": child.id,
        "display_name": child.display_name,
        "age": child.age,
        **services.child_star_view(db, child),
    }


@app.get("/api/parent/catalog")
def parent_catalog(_parent: Parent = Depends(require_parent), db: Session = Depends(get_db)):
    return [services.chore_public(c, parent=True) for c in services.list_managed_chores(db)]


@app.get("/api/parent/chores")
def parent_list_chores(_parent: Parent = Depends(require_parent), db: Session = Depends(get_db)):
    return [services.chore_public(c, parent=True) for c in services.list_managed_chores(db)]


@app.post("/api/parent/chores")
def parent_add_chore(
    body: ChoreIn,
    _parent: Parent = Depends(require_parent),
    db: Session = Depends(get_db),
):
    row = services.create_chore(db, body.model_dump())
    return services.chore_public(row, parent=True)


@app.patch("/api/parent/chores/{chore_id}")
def parent_patch_chore(
    chore_id: str,
    body: ChorePatch,
    _parent: Parent = Depends(require_parent),
    db: Session = Depends(get_db),
):
    row = services.update_chore(db, chore_id, body.model_dump(exclude_unset=True))
    return services.chore_public(row, parent=True)


@app.delete("/api/parent/chores/{chore_id}")
def parent_delete_chore(
    chore_id: str,
    _parent: Parent = Depends(require_parent),
    db: Session = Depends(get_db),
):
    services.delete_chore(db, chore_id)
    return {"ok": True}


@app.post("/api/parent/chores/{chore_id}/media")
def parent_chore_media(
    chore_id: str,
    kind: str = Form(...),
    file: UploadFile = File(...),
    _parent: Parent = Depends(require_parent),
    db: Session = Depends(get_db),
):
    data = file.file.read(services.MAX_VIDEO_BYTES + 1)
    row = services.save_chore_media(db, chore_id, kind, data)
    return services.chore_public(row, parent=True)


@app.delete("/api/parent/chores/{chore_id}/media/{kind}")
def parent_clear_chore_media(
    chore_id: str,
    kind: str,
    _parent: Parent = Depends(require_parent),
    db: Session = Depends(get_db),
):
    row = services.clear_chore_media(db, chore_id, kind)
    return services.chore_public(row, parent=True)


@app.get("/api/parent/children/{child_id}/chores")
def parent_child_chores(
    child_id: int,
    _parent: Parent = Depends(require_parent),
    db: Session = Depends(get_db),
):
    child = services.get_child(db, child_id)
    return services.child_assignments_payload(db, child)


@app.put("/api/parent/children/{child_id}/chores")
def parent_set_child_chores(
    child_id: int,
    body: ChildChoresIn,
    _parent: Parent = Depends(require_parent),
    db: Session = Depends(get_db),
):
    child = services.get_child(db, child_id)
    return services.set_child_chores(db, child, [i.model_dump() for i in body.items])


@app.get("/api/parent/rewards")
def parent_list_rewards(_parent: Parent = Depends(require_parent), db: Session = Depends(get_db)):
    return [services.reward_public(r, parent=True) for r in services.list_managed_rewards(db)]


@app.post("/api/parent/rewards")
def parent_add_reward(
    body: RewardIn,
    _parent: Parent = Depends(require_parent),
    db: Session = Depends(get_db),
):
    row = services.create_reward(db, body.model_dump())
    return services.reward_public(row, parent=True)


@app.patch("/api/parent/rewards/{reward_id}")
def parent_patch_reward(
    reward_id: str,
    body: RewardPatch,
    _parent: Parent = Depends(require_parent),
    db: Session = Depends(get_db),
):
    row = services.update_reward(db, reward_id, body.model_dump(exclude_unset=True))
    return services.reward_public(row, parent=True)


@app.delete("/api/parent/rewards/{reward_id}")
def parent_delete_reward(
    reward_id: str,
    _parent: Parent = Depends(require_parent),
    db: Session = Depends(get_db),
):
    services.delete_reward(db, reward_id)
    return {"ok": True}


@app.get("/api/parent/pools")
def parent_pools(
    _parent: Parent = Depends(require_parent),
    db: Session = Depends(get_db),
    day: date | None = None,
):
    day = day or services.today()
    services.ensure_today_pools(db, day)
    return {
        "day": day.isoformat(),
        "daily": services.pool_ids(db, day, "daily"),
        "extra": services.pool_ids(db, day, "extra"),
    }


@app.put("/api/parent/pools")
def parent_set_pools(
    body: PoolsIn,
    _parent: Parent = Depends(require_parent),
    db: Session = Depends(get_db),
):
    day = services.today()
    services.set_pools(db, day, body.daily, body.extra)
    return {"day": day.isoformat(), "daily": body.daily, "extra": body.extra}


@app.get("/api/parent/inbox")
def parent_inbox(_parent: Parent = Depends(require_parent), db: Session = Depends(get_db)):
    return services.inbox(db)


@app.get("/api/parent/redemptions")
def parent_redemptions(_parent: Parent = Depends(require_parent), db: Session = Depends(get_db)):
    return services.redemption_inbox(db)


@app.post("/api/parent/redemptions/{redemption_id}/approve")
def parent_approve_redeem(
    redemption_id: int,
    _parent: Parent = Depends(require_parent),
    db: Session = Depends(get_db),
):
    row = services.approve_redemption(db, redemption_id)
    return services.redemption_view(db, row, parent=True)


@app.post("/api/parent/redemptions/{redemption_id}/deny")
def parent_deny_redeem(
    redemption_id: int,
    body: ReturnIn,
    _parent: Parent = Depends(require_parent),
    db: Session = Depends(get_db),
):
    row = services.deny_redemption(db, redemption_id, body.note)
    return services.redemption_view(db, row, parent=True)


@app.post("/api/parent/assignments/{assignment_id}/approve")
def parent_approve(
    assignment_id: int,
    _parent: Parent = Depends(require_parent),
    db: Session = Depends(get_db),
):
    asg = services.approve_assignment(db, assignment_id)
    return services.assignment_view(asg, db)


@app.post("/api/parent/assignments/{assignment_id}/return")
def parent_return(
    assignment_id: int,
    body: ReturnIn,
    _parent: Parent = Depends(require_parent),
    db: Session = Depends(get_db),
):
    asg = services.return_assignment(db, assignment_id, body.note)
    return services.assignment_view(asg, db)


@app.post("/api/parent/assignments/{assignment_id}/reset")
def parent_reset(
    assignment_id: int,
    _parent: Parent = Depends(require_parent),
    db: Session = Depends(get_db),
):
    asg = services.reset_assignment(db, assignment_id)
    return {"id": asg.id, "state": asg.state}
