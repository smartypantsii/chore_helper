# Agent notes — Chore Helper

Family chore app: **Windows PC** for kids, **parent-hosted LAN server** for profiles, chores, and **Stars**. v1 is running.

Repo: `/home/jbarnes/projects/chore_helper/`. `cd` here before git or project commands. Product pins in [`README.md`](README.md). HTTP and schema in [`docs/DESIGN.md`](docs/DESIGN.md).

## Product pins

- Display name: **Chore Helper**. Project id: `chore_helper`.
- Audience: household kids on a Windows PC + parent on the LAN.
- Currency: **Stars**. Available balance is never negative. Ledger credits are positive; approved cash-ins are negative rows. Never call it coins, XP, or TDG.
- Source of truth: **the parent server**. The kids PC cannot award Stars.
- Award rule: Stars are added only when a parent **approves** a completion.
- Kids **pick** from two per-child lists: Regular (today’s one chore) then Optional extras. Parents do not push a single forced card.
- Tone: encouraging, short sentences. No shame copy, no public leaderboards.

**Never copy** Minecraft / NeoForge projects in this workspace (`MInecraft_Turtle_Dragon_Quests`, `bigger-chickens`). This is not a mod.

## Stack (current)

| Piece | Pin |
| --- | --- |
| Server | Python 3.10+ (this machine is 3.10.12). FastAPI, SQLAlchemy 2, SQLite `data/chore_helper.db` |
| Venv | `python3 -m virtualenv .venv` (no `python3-venv` package). Do not use user-site pip |
| UI | HTML/CSS/JS in `web/`, served by the same process. Kids `/`, parent `/parent` |
| Auth | Child PIN (4–8 digits, pad + OK). Parent username/password. Session cookie. No OAuth |
| Catalog | JSON under `catalog/` seeds SQLite `managed_chores` / `managed_rewards` once; later edits are in SQLite or parent UI |
| Media | Starter stills `catalog/media/images/<id>.jpg`. Parent uploads `catalog/media/uploads/` (gitignored) |
| Run | systemd user unit `chore-helper.service` (linger), port 8765. Dev: `.venv/bin/python -m uvicorn server.main:app --host 0.0.0.0 --port 8765` |
| Tests | `.venv/bin/pytest -q` (17 tests). Shared SQLite is wiped of children between tests |
| systemd | Units in `deploy/`. plexserver uses `systemctl --user` + linger. Machine unit: `sudo deploy/install-systemd.sh`. Do not start a second uvicorn on 8765. |

Static assets are cache-busted (`web/*.html` `?v=8`). Parent login is a `<form>`; Enter submits.

## Layout

```
chore_helper/
├── README.md
├── CLAUDE.md
├── docs/DESIGN.md
├── server/                 # FastAPI, models, services, history
├── web/                    # index.html, parent.html, css, js
├── catalog/
│   ├── index.json
│   ├── chores/*.json
│   ├── rewards/*.json
│   ├── media/images/*.jpg  # starter 16:9 covers
│   └── media/uploads/      # parent uploads, gitignored
├── data/                   # sqlite + session secret, gitignored
├── deploy/                 # systemd units
└── tests/
```

## Domain

- **Child** — display name, age, hashed PIN
- **Parent** — username, hashed password
- **ManagedChore** — live definition in SQLite (seeded from catalog JSON)
- **ChildChore** — per child: on/off, `daily`|`extra`, Stars
- **Assignment** — one pick today; `stars` frozen at pick
- **Ledger** — append-only Stars (chore credit, reward debit)
- **ManagedReward** / **Redemption** — shop + cash-in hold/approve/deny

Assignment states: `in_progress` → `pending_approval` → `approved` | `returned`. `cancelled` for kid cancel or parent reset.

### Pick rules

- One **daily** assignment per child per local calendar day.
- A chore in `CLAIMED_STATES` (`in_progress`, `pending_approval`, `approved`, `returned`) belongs to **one child per day**. Unique index `ux_assignment_day_chore`. Cancel frees it. Lists mark `taken_by`.
- Optional extras stay on screen; they unlock after today’s daily is `pending_approval` or `approved`.
- `returned` daily locks extras until the kid taps **I finished** again.
- At most one open assignment (`in_progress` or `returned`).
- Many extras after daily is complete; each is its own assignment and approval.
- New children get catalog chores with `min_age` ≤ age. After that, **Assign** owns the list. Custom chores stay off until assigned.
- A younger child may get a harder chore with **higher Stars** on Assign.
- Kid may cancel `in_progress`, `returned`, or `pending_approval`. `approved` cannot be cancelled; Stars stay.

## Parent UI (`/parent`)

Tabs: **Inbox**, **Assign**, **Chores**, **Kids**, **Rewards**, **History**.

- **Inbox** — pending chores and reward cash-ins; approve, return, deny.
- **Assign** — pick a child; on/off, Regular vs Optional, Stars for that child.
- **Chores** — add/edit definitions; upload picture and video; enable/disable.
- **Kids** — name, age, PIN; jump to Assign or History.
- **Rewards** — prices, enable, custom rewards.
- **History** — per-child charts (shared `web/js/charts.js`).

Default login `parent` / `change-me` unless `CHORE_HELPER_PARENT_PASSWORD` was set before the first DB.

## Kids UI (`/`)

Name picker → PIN pad (OK, not auto-submit at 4 digits) → Chores / Rewards / History.

Cards show the cover still. Walkthrough plays `demo_video` when set (poster = cover). Gold number is **available** Stars.

## Catalog and media

One JSON file per chore in `catalog/chores/`, listed in `catalog/index.json`. Fields: `id`, `title`, `category`, default `kind` (`daily`|`extra`), `min_age`, `minutes`, `stars`, `grown_up_required`, `materials`, `steps`, `done_when`, `cover_image`, `demo_video`, `parent_notes`.

Starter ids use `make_bed` (not `bedroom_make_bed`). Covers: `media/images/<id>.jpg`, 16:9, first-person hands and rooms, no faces, no on-image text. Starter `demo_video` is `null`.

**Uploads** from the Chores tab:

- `POST /api/parent/chores/{id}/media` multipart `kind=cover|video` + `file`
- Cover: JPEG/PNG/WebP/GIF, max 8MB → `media/uploads/<id>.<ext>`
- Video: MP4/WebM, max 50MB → same folder
- `DELETE /api/parent/chores/{id}/media/{kind}` drops the upload; catalog chores restore the starter still
- Seed copies JSON into `managed_chores` **only if the id is new**. Parent UI / uploads are the live source after that.

Rewards JSON under `catalog/rewards/` seeds `managed_rewards` once. Parent Rewards tab edits SQLite. Starter prices: computer_time 10, ice_cream 15, tv_control 20, special_time 20, cash 25, movies 50, rifle_shooting 80 (min_age 10), zoo_day 100, beach_day 120 (season summer).

Daily seed (min_age 4): `toys_in_bin`, `clothes_in_hamper`, `wipe_low_table`. (7): `make_bed`, `set_table`, `empty_small_trash`. Extra (7): `fill_pet_water`, `match_socks`. (10): `wipe_bathroom_sink`, `load_dishwasher`, `vacuum_living_room`, `sweep_porch`. `grown_up_required` on sink, dishwasher, vacuum.

## Persistence

- SQLite `data/chore_helper.db`. `SessionLocal` is None until `init_engine()`.
- Lifespan: `migrate_schema` then `create_all`, then seed parent / rewards / chores / child_chores.
- `migrate_schema` adds `assignments.stars`, rebuilds `ledger_entries` if needed, creates `ux_assignment_day_chore`.
- Ledger is append-only. Approve uses `assignment.stars`, else child_chore, else managed chore. Second approve is a no-op.
- Available Stars = SUM(ledger) minus held `requested` redemptions.
- Household `pool_entries` APIs still exist; kids ignore them. Live lists are `child_chores`.

## Verify

- Parent approval credits Stars once.
- Child finish does not change Stars.
- Extras locked until daily is `pending_approval` or `approved`.
- Second daily pick the same day is rejected.
- Two children cannot claim the same chore the same day; cancel frees it.
- Age seed hides `make_bed` from a 5-year-old until Assign turns it on with custom Stars.
- Two children do not share a Stars balance.
- Media upload stores under `media/uploads/` and kids state returns those paths.
- Restart keeps balances, picks, and pending approvals.

## Non-goals (v1)

No public accounts, ads, IAP, social, phone apps, camera proof, GPS, third-party analytics, Minecraft integration, or auto-approve from the kids PC. Native Windows `.exe` is later. Starter demo clips were not generated (Imagine video/ZDR); parents upload their own.

## Next work

1. Playtest with the household; add their chores and pictures in the parent UI.
2. Windows shortcut / kiosk notes for the kids PC.
3. Tune reward prices with the family (Rewards tab or JSON before first seed).
4. Optional: fill starter `demo_video` clips if video gen is available later.
