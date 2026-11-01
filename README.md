# Chore Helper

A family chore app for kids. Children pick one job from today’s **regular chores**, follow step-by-step instructions, then may pick **optional extras** after that job is finished. Parents choose which chores and Stars each child sees, and approve completions. **Points live on the parent’s server**, not only on the kids’ PC.

v1 is runnable: a FastAPI server on the parent machine and a Web UI for kids (`/`) and parents (`/parent`). Design: [`docs/DESIGN.md`](docs/DESIGN.md).

## Why it exists

Kids can help keep the house clean when the job is the right size, the steps are clear, and finishing something is rewarded. Chore Helper is a Windows PC they can sit down at, plus a small home server the parent controls.

## Who it is for

- **Kids** on a Windows PC: big, readable UI, one chore at a time, short sentences, pictures where they help. They **pick** from lists; they are not handed a single assigned card.
- **Parents** on the same LAN: profiles, chore catalog, per-child chore lists and Stars, approval, and the points ledger.

This is a **household** tool. It is not a public product, not a social network, and not an app store account system.

## Product in one screen

1. Kid chooses their name (PIN or simple password).
2. They see two lists: **Today's chore** (regular, pick one) and **Optional chores** (extra Stars). Optional cards stay visible; they unlock after today's chore is finished.
3. They walk the steps (what to grab, what to do, how to know it is done) and tap **I finished**, or **Pick a different chore** to go back to the list.
4. A parent **approves**. The server adds Stars for that chore.
5. After the daily chore is **complete**, the **extra chores** list appears. The kid may pick extras, one at a time, the same way.
6. The kid sees their Stars total.

Kids cannot grant themselves points. The Windows PC is a client. The server is the source of truth.

## Daily chores and extra chores

Two lists **per child**, curated by a parent. Catalog `min_age` is a default; a parent can still give a younger child a harder job and raise the Stars for that child:

| List | When the kid sees it | Pick rule |
| --- | --- | --- |
| **Daily chores** | After login, until they have picked today’s daily chore | Pick **exactly one** per child per day |
| **Extra chores** | Only after today’s daily chore is **complete** | Optional; pick one at a time; as many as they want |

**Complete** (unlocks extras): the kid finished the walkthrough and tapped **I finished** (`pending_approval` or `approved`). Stars still wait on parent approval.

If a parent **returns** the daily chore, extras hide again until the kid finishes that daily job a second time. A child has at most **one active chore** (daily or extra) at a time.

They cannot pick a second daily chore the same day. Two children cannot pick the **same chore** on the same day; canceling frees it for a sibling. They cannot open extras while the daily chore is still in progress. A parent can reset today’s daily pick if the kid chose the wrong job before starting.

The same catalog chore can be Regular for one child and Optional for another. Default `kind` and Stars on the chore are starting values; Assign sets the live list and Stars for each kid.

## Age bands (working defaults)

| Band | Ages | Instruction style | Typical jobs |
| --- | --- | --- | --- |
| Little helpers | 4–6 | Few steps, pictures, a grown-up nearby | Toys in bin, dirty clothes in hamper, wipe a low table |
| Growing helpers | 7–9 | Short numbered steps, simple “why” | Make bed, empty small trash, set table, feed pet with checklist |
| House teammates | 10–12 | Full steps, materials list, quality check | Vacuum a room, load/unload dishwasher, bathroom sink, laundry start/move |
| Independent | 13+ | Standards, time estimate, extra credit | Kitchen reset, bathroom clean, outdoor sweep, meal-prep assist |

A chore has a **minimum age**. A parent can still assign a younger child a job with supervision notes.

## Chore record (catalog)

Each chore is data, not a hard-coded screen:

- `id`, title, category (kitchen, bathroom, bedroom, laundry, living, pets, outdoor)
- optional default `kind`: `daily` or `extra` (Assign sets the live list per child)
- `min_age`, estimated minutes, points
- materials / tools
- numbered steps (action + optional tip)
- “done when” checklist
- `cover_image` (16:9 still; starter set is first-person hands / room, no faces)
- `demo_video` (optional clip; kids walkthrough plays it when set)
- parent notes (safety: chemicals, stairs, hot water, knives)

A **starter catalog of 12 chores** is in [`catalog/`](catalog/README.md), with cover stills in `catalog/media/images/`. Parents upload replacement pictures and videos on the **Chores** tab (`catalog/media/uploads/`).

## Rewards

- Currency name: **Stars** (integer points).
- Awarded only after **parent approval** of a completion.
- Stored on the parent server per child.
- Kids **cash in** Stars for rewards (computer time, cash, TV control, ice cream, special time, movies, rifle shooting, beach day, zoo day). A parent must approve. Stars come off the ledger only then. Edit prices on the parent **Rewards** tab (JSON only seeds the first boot).

## Architecture

| Piece | Role |
| --- | --- |
| **Parent server** | Profiles, chore catalog, per-child lists and Stars, media, picks, completions, rewards, ledger. LAN HTTP API. SQLite. |
| **Kids Windows PC** | Browser or shortcut to `/`. Pick today’s chore → walk steps → extras after complete. |
| **Catalog files** | Starter JSON and stills in git. Live chores, rewards, and uploads live in SQLite + `catalog/media/uploads/`. |

**Stack**

- Server: Python 3.10+, FastAPI, SQLAlchemy, SQLite at `data/chore_helper.db`
- Kids + parent UI: HTML/CSS/JS served by the same process. Kids on Windows open the server in a browser.
- Auth: child PIN; parent password. Session cookie. No third-party login.

Develop on Linux; kids use Windows against the home server.

## Status

| Milestone | State |
| --- | --- |
| `docs/DESIGN.md` | Matches the running v1 |
| Server API + SQLite ledger | Current |
| Kids UI + parent Inbox / Assign / Chores / Kids / Rewards / History | Current |
| Per-child chore lists and Stars | Current |
| One child per chore per day | Current |
| Starter catalog (12 chores + cover stills) | Current |
| Parent upload of pictures and video | Current |
| Starter demo clips in git | Not generated; upload your own |
| Native Windows `.exe` | Later |

## Layout

```
chore_helper/
  docs/DESIGN.md
  server/               # FastAPI app
  web/                  # kids + parent UI
  catalog/              # starter chores + stills; uploads gitignored
  data/                 # sqlite (gitignored)
  tests/
```

## Run

On **plexserver** the app is a systemd **user** service (`chore-helper.service`) as `jbarnes`, enabled with linger so it starts at boot on port **8765**.

```bash
systemctl --user status chore-helper.service
journalctl --user -u chore-helper.service -f
```

First-time install (already done on this host):

```bash
cd /home/jbarnes/projects/chore_helper
python3 -m virtualenv .venv   # this machine has no python3-venv package
.venv/bin/pip install -r requirements.txt
mkdir -p ~/.config/systemd/user
cp deploy/chore-helper.user.service ~/.config/systemd/user/chore-helper.service
systemctl --user daemon-reload
loginctl enable-linger "$USER"
systemctl --user enable --now chore-helper.service
```

To run it as a machine service instead (needs sudo): `deploy/install-systemd.sh`.

Open `http://192.168.38.50:8765/` on the kids PC and `http://192.168.38.50:8765/parent` for you.

Default parent login: **parent** / **change-me**. Set `CHORE_HELPER_PARENT_PASSWORD` before the first start to pick your own. Add kids on the **Kids** tab. **Assign** chooses which chores and Stars each child sees. **Chores** adds jobs and uploads pictures or video.

Tests: `.venv/bin/pytest -q`

## Non-goals (v1)

No public internet accounts, ads, in-app purchases, friend feeds, phone apps, camera “proof” of cleaning, or automatic point grants from the client.

## Safety

- Parent is the only person who can award Stars or edit the catalog.
- Chores that need chemicals, heat, blades, or ladders carry a **grown-up required** flag.
- No tracking outside the house. No analytics vendors.
- Copy and UI stay encouraging. Incomplete work is a retry, not a punishment score.

## Identifiers

- Display name: **Chore Helper**
- Repo directory: `/home/jbarnes/projects/chore_helper/`
- Package / project id: `chore_helper`
- Currency: **Stars**

## License

Not chosen yet. Do not publish this repo until a license is set.
