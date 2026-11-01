# Starter catalog

Twelve household chores with kid-facing steps, Stars, age gates, and **cover stills**. JSON seeds SQLite once; after that, the parent **Chores** and **Assign** tabs are the live source.

## Media rules

- **Starter stills** live in `media/images/<id>.jpg` (16:9). First-person **hands and rooms**, no faces, no on-image text.
- **Parent uploads** (picture or video) live in `media/uploads/<id>.<ext>` (gitignored). JPEG/PNG/WebP/GIF up to 8MB; MP4/WebM up to 50MB. The kids walkthrough plays an uploaded clip.
- JSON paths are relative to `catalog/`.
- Starter `demo_video` is `null`. Upload a clip in the parent UI instead of pointing JSON at a missing mp4.

## Daily defaults

| id | title | min age | Stars |
| --- | --- | --- | --- |
| `toys_in_bin` | Put toys in the bin | 4 | 3 |
| `clothes_in_hamper` | Clothes in the hamper | 4 | 3 |
| `wipe_low_table` | Wipe a low table | 4 | 4 |
| `make_bed` | Make your bed | 7 | 5 |
| `set_table` | Set the table | 7 | 6 |
| `empty_small_trash` | Empty a small trash can | 7 | 5 |

## Extra defaults

| id | title | min age | Stars | Grown-up |
| --- | --- | --- | --- | --- |
| `fill_pet_water` | Fill the pet water bowl | 7 | 4 | no |
| `match_socks` | Match the socks | 7 | 6 | no |
| `wipe_bathroom_sink` | Wipe the bathroom sink | 10 | 8 | yes |
| `load_dishwasher` | Load the dishwasher | 10 | 8 | yes |
| `vacuum_living_room` | Vacuum the living room | 10 | 10 | yes |
| `sweep_porch` | Sweep the porch | 10 | 8 | no |

`kind` is only a default. **Assign** chooses Regular vs Optional and Stars for each child.

## Rewards

JSON in `rewards/` seeds the shop once. After that, edit prices on the parent **Rewards** tab. Kid cash-in holds Stars until a parent approves (debit) or denies.

Starter prices: computer 10, ice cream 15, TV 20, special time 20, cash $5 = 25, movies 50, rifle 80, zoo 100, beach 120 (summer).

## Regenerating starter stills

Household pictures and clips: parent **Chores** tab, Picture / Video file pickers.

Starter covers in git: Imagine `image_gen`, 16:9, photoreal first-person hands, no faces. Copy into `media/images/<id>.jpg`. Optional clips: Imagine `reference_to_video` with that jpg as `first_frame`, 6s, 16:9, then upload in the UI (or copy into `media/uploads/`).
