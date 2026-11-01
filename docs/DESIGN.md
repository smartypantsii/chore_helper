# Chore Helper v1 design

Matches the running v1. Product pins in `README.md` and `CLAUDE.md` still apply.

## Stack

- Python **3.10+** (3.12 preferred; this machine has 3.10)
- FastAPI + Uvicorn
- SQLAlchemy 2.x + **SQLite** at `data/chore_helper.db`
- Kids + parent UI: static HTML/CSS/JS served by the same process
- Auth: HTTP-only session cookie (Starlette `SessionMiddleware`). Child PIN and parent password hashed with PBKDF2.

## Layout

```
chore_helper/
  catalog/           # starter JSON + stills; parent uploads in media/uploads/
  server/            # FastAPI app
  web/               # kids index.html, parent.html, css, js
  data/              # gitignored sqlite + session secret
  tests/
```

Run: `uvicorn server.main:app --host 0.0.0.0 --port 8765`

## Data

**Catalog JSON** seeds SQLite on first insert of each id. After that, `managed_chores` / `managed_rewards` and parent UI are live. Starter stills stay in `catalog/media/images/`. Parent uploads go to `catalog/media/uploads/`.

**SQLite**

- `parents(id, username, password_hash)`
- `children(id, display_name, age, pin_hash)`
- `managed_chores` — live chore definitions (`source` catalog|custom), including `cover_image` and `demo_video`
- `child_chores(child_id, chore_id, kind, stars, enabled)` — per-child list and Stars
- `managed_rewards` — live shop
- `pool_entries` — leftover household daily/extra lists; kids ignore these
- `assignments(id, child_id, chore_id, day, kind, state, stars, return_note, created_at, finished_at, approved_at)` — `stars` frozen at pick
- `ledger_entries(id, child_id, assignment_id, redemption_id, stars, created_at)` — append-only. Chore approval: `stars > 0` and `assignment_id`. Reward cash-in: `stars < 0` and `redemption_id`.
- `redemptions(id, child_id, reward_id, stars, state, note, created_at, decided_at)` — `requested` → `approved` | `denied` | `cancelled`

Partial unique index `ux_assignment_day_chore` on `(day, chore_id)` where `state != 'cancelled'`.

Assignment `state`: `in_progress` → `pending_approval` → `approved` | `returned`.

Stars **earned** is `SUM(ledger_entries.stars)` (credits minus approved cash-ins). **Available** is earned minus Stars held on `requested` redemptions. Never take a client-supplied total. Chore `approve` inserts one credit row. Reward `approve` inserts one debit row. Second approve is a no-op.

## Rules

- One **daily** assignment per child per local calendar day.
- A chore may be claimed by only **one child per day** (any non-cancelled assignment). Cancel frees it. Kid lists include `taken_by` when a sibling already picked it.
- **Extra** list is visible but locked until today’s daily assignment is `pending_approval` or `approved`.
- `returned` daily hides extras until the kid taps **I finished** again (same assignment, back through `pending_approval`).
- At most one assignment in `in_progress` or `returned` at a time.
- Many extras after daily is complete; each is its own assignment and approval.
- New children are seeded with catalog chores where `min_age <= age`. Parents then turn chores on/off and set Stars on Assign, including harder jobs for younger kids.
- Finish does not credit Stars. Approve uses `assignment.stars`.
- Parent may reset today’s daily pick if it is not `approved` (cancels the row). Kid may then pick again.
- Kid may **cancel** their own assignment while it is `in_progress`, `returned`, or `pending_approval`. That row becomes `cancelled`. They can pick again. `approved` chores cannot be cancelled; Stars stay.
- Kid may **cash in** catalog rewards if `available` Stars ≥ cost and `min_age` fits. That holds Stars until a parent approves (debit) or denies/kid cancels (release).

## HTTP

Cookie session. JSON bodies.

| Method | Path | Who | Effect |
| --- | --- | --- | --- |
| GET | `/api/children` | public (LAN) | `{id, display_name, age}` for the picker |
| POST | `/api/kids/login` | | `{child_id, pin}` |
| POST | `/api/parent/login` | | `{username, password}` |
| POST | `/api/logout` | any | |
| GET | `/api/session` | any | role + child/parent |
| GET | `/api/kid/state` | child | stars, daily, extras, current walkthrough |
| POST | `/api/kid/pick` | child | `{chore_id}` — daily if none today, else extra. One child per chore per day. |
| POST | `/api/kid/finish` | child | `{assignment_id}` |
| POST | `/api/kid/cancel` | child | `{assignment_id}` — not `approved` |
| GET | `/api/kid/history` | child | 14-day series + activity events |
| GET | `/api/kid/rewards` | child | shop + pending cash-ins |
| POST | `/api/kid/redeem` | child | `{reward_id}` |
| POST | `/api/kid/redeem/cancel` | child | `{redemption_id}` |
| GET | `/api/parent/children` | parent | full child list + stars |
| GET | `/api/parent/children/{id}/history` | parent | same history payload as the kid |
| POST | `/api/parent/children` | parent | `{display_name, age, pin}` |
| PATCH | `/api/parent/children/{id}` | parent | age and/or pin |
| GET | `/api/parent/catalog` | parent | all chores (alias of chores list) |
| GET | `/api/parent/chores` | parent | managed chore definitions |
| POST | `/api/parent/chores` | parent | add custom chore |
| PATCH | `/api/parent/chores/{id}` | parent | title, default stars, kind, age, steps |
| DELETE | `/api/parent/chores/{id}` | parent | delete custom, or disable catalog |
| POST | `/api/parent/chores/{id}/media` | parent | multipart `kind=cover|video` + `file` |
| DELETE | `/api/parent/chores/{id}/media/{kind}` | parent | drop upload; catalog chores restore starter still |
| GET | `/api/parent/children/{id}/chores` | parent | per-child on/off, kind, stars |
| PUT | `/api/parent/children/{id}/chores` | parent | `{items: [{chore_id, kind, stars, enabled}]}` |
| GET | `/api/parent/pools` | parent | leftover household lists (kids ignore these) |
| PUT | `/api/parent/pools` | parent | leftover household lists |
| GET | `/api/parent/inbox` | parent | pending + returned |
| POST | `/api/parent/assignments/{id}/approve` | parent | |
| POST | `/api/parent/assignments/{id}/return` | parent | `{note}` |
| POST | `/api/parent/assignments/{id}/reset` | parent | cancel non-approved |
| GET | `/api/parent/rewards` | parent | managed reward list |
| POST | `/api/parent/rewards` | parent | add custom reward |
| PATCH | `/api/parent/rewards/{id}` | parent | price, age, enable, copy |
| DELETE | `/api/parent/rewards/{id}` | parent | delete custom, or disable catalog |
| GET | `/api/parent/redemptions` | parent | requested cash-ins |
| POST | `/api/parent/redemptions/{id}/approve` | parent | debit Stars, you owe the reward |
| POST | `/api/parent/redemptions/{id}/deny` | parent | `{note}` — Stars stay |

Pages: `GET /` kids app, `GET /parent` parent app. Catalog media at `/catalog/media/…`.

## UI

Kids home has **two sections**: **Today's chore** (regular daily pick, exactly one) and **Optional chores** (extra Stars). Optional cards are visible but locked until today's chore is `pending_approval` or `approved`. Cards show the cover still. Walkthrough plays `demo_video` when set. Cream background, large type, PIN pad with OK, **I finished** plus **Pick a different chore**.

Parent: login form (Enter submits), then Inbox / Assign / Chores / Kids / Rewards / History. **Chores** adds and edits definitions and uploads picture (JPEG/PNG/WebP/GIF, 8MB) or video (MP4/WebM, 50MB). **Assign** picks which chores each child sees, Regular vs Optional, and that child’s Stars. Inbox approves or returns chores and reward cash-ins.

## Seed

On first boot, one parent `parent` / `change-me` (override with `CHORE_HELPER_PARENT_PASSWORD`). Catalog chores seed `managed_chores`. New children get enabled chores whose `min_age` is at most their age. Parents override that on Assign. Catalog JSON is not re-applied to existing ids on later boots.

## Non-goals (still)

Native `.exe`, public internet, auto-approve, camera proof of cleaning. Starter demo clips in git were not generated; parents upload video in the UI.
