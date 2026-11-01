from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from server.config import CATALOG_DIR


def add_child(client: TestClient, name: str, age: int, pin: str) -> int:
    r = client.post(
        "/api/parent/children",
        json={"display_name": name, "age": age, "pin": pin},
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def login_kid(client: TestClient, child_id: int, pin: str) -> None:
    r = client.post("/api/kids/login", json={"child_id": child_id, "pin": pin})
    assert r.status_code == 200, r.text


def test_parent_login_rejects_bad_password(client: TestClient):
    r = client.post("/api/parent/login", json={"username": "parent", "password": "nope"})
    assert r.status_code == 401


def test_finish_does_not_award_stars_approve_does_once(parent: TestClient):
    kid_id = add_child(parent, "Sam", 8, "1234")
    login_kid(parent, kid_id, "1234")
    state = parent.get("/api/kid/state").json()
    assert state["child"]["stars"] == 0
    pickable = {c["id"]: c for c in state["daily"]["pickable"]}
    assert "make_bed" in pickable
    r = parent.post("/api/kid/pick", json={"chore_id": "make_bed"})
    assert r.status_code == 200, r.text
    asg_id = r.json()["id"]
    r = parent.post("/api/kid/finish", json={"assignment_id": asg_id})
    assert r.status_code == 200
    state = parent.get("/api/kid/state").json()
    assert state["child"]["stars"] == 0
    assert state["daily"]["complete"] is True

    parent.post("/api/parent/login", json={"username": "parent", "password": "secret"})
    r = parent.post(f"/api/parent/assignments/{asg_id}/approve")
    assert r.status_code == 200
    parent.post("/api/parent/assignments/{}/approve".format(asg_id))
    login_kid(parent, kid_id, "1234")
    state = parent.get("/api/kid/state").json()
    assert state["child"]["stars"] == pickable["make_bed"]["stars"]


def test_extra_locked_until_daily_finished(parent: TestClient):
    kid_id = add_child(parent, "Lee", 12, "2222")
    login_kid(parent, kid_id, "2222")
    state = parent.get("/api/kid/state").json()
    assert state["extra"]["unlocked"] is False
    assert state["extra"]["pickable"] == []
    listed = {c["id"] for c in state["extra"]["listed"]}
    assert "match_socks" in listed
    r = parent.post("/api/kid/pick", json={"chore_id": "match_socks"})
    assert r.status_code == 400
    r = parent.post("/api/kid/pick", json={"chore_id": "make_bed"})
    assert r.status_code == 200
    asg_id = r.json()["id"]
    parent.post("/api/kid/finish", json={"assignment_id": asg_id})
    state = parent.get("/api/kid/state").json()
    assert state["extra"]["unlocked"] is True
    extra_ids = {c["id"] for c in state["extra"]["pickable"]}
    assert "match_socks" in extra_ids


def test_second_daily_pick_rejected(parent: TestClient):
    kid_id = add_child(parent, "Jo", 9, "1111")
    login_kid(parent, kid_id, "1111")
    r = parent.post("/api/kid/pick", json={"chore_id": "make_bed"})
    assert r.status_code == 200
    r = parent.post("/api/kid/pick", json={"chore_id": "set_table"})
    assert r.status_code == 400


def test_age_filter_hides_older_chores(parent: TestClient):
    kid_id = add_child(parent, "Tiny", 5, "9999")
    login_kid(parent, kid_id, "9999")
    state = parent.get("/api/kid/state").json()
    ids = {c["id"] for c in state["daily"]["pickable"]}
    assert "toys_in_bin" in ids
    assert "make_bed" not in ids
    r = parent.post("/api/kid/pick", json={"chore_id": "make_bed"})
    assert r.status_code == 400


def test_two_children_cannot_pick_same_chore(parent: TestClient):
    a = add_child(parent, "Avery", 10, "4444")
    b = add_child(parent, "Blake", 10, "5555")
    login_kid(parent, a, "4444")
    r = parent.post("/api/kid/pick", json={"chore_id": "make_bed"})
    assert r.status_code == 200, r.text
    asg = r.json()["id"]
    login_kid(parent, b, "5555")
    state = parent.get("/api/kid/state").json()
    pickable = {c["id"]: c for c in state["daily"]["pickable"]}
    assert pickable["make_bed"]["taken_by"] == "Avery"
    r = parent.post("/api/kid/pick", json={"chore_id": "make_bed"})
    assert r.status_code == 400
    r = parent.post("/api/kid/pick", json={"chore_id": "set_table"})
    assert r.status_code == 200, r.text
    login_kid(parent, a, "4444")
    parent.post("/api/kid/cancel", json={"assignment_id": asg})
    login_kid(parent, b, "5555")
    parent.post("/api/kid/cancel", json={"assignment_id": r.json()["id"]})
    r = parent.post("/api/kid/pick", json={"chore_id": "make_bed"})
    assert r.status_code == 200, r.text
    parent.post("/api/kid/cancel", json={"assignment_id": r.json()["id"]})


def test_two_children_do_not_share_stars(parent: TestClient):
    a = add_child(parent, "Avery", 10, "4444")
    b = add_child(parent, "Blake", 10, "5555")
    login_kid(parent, a, "4444")
    asg = parent.post("/api/kid/pick", json={"chore_id": "make_bed"}).json()["id"]
    parent.post("/api/kid/finish", json={"assignment_id": asg})
    parent.post("/api/parent/login", json={"username": "parent", "password": "secret"})
    parent.post(f"/api/parent/assignments/{asg}/approve")
    kids = {row["display_name"]: row for row in parent.get("/api/parent/children").json()}
    assert kids["Avery"]["stars"] == 5
    assert kids["Blake"]["stars"] == 0


def test_kid_can_cancel_and_pick_again(parent: TestClient):
    kid_id = add_child(parent, "Drew", 9, "3333")
    login_kid(parent, kid_id, "3333")
    asg = parent.post("/api/kid/pick", json={"chore_id": "make_bed"}).json()["id"]
    r = parent.post("/api/kid/cancel", json={"assignment_id": asg})
    assert r.status_code == 200
    state = parent.get("/api/kid/state").json()
    assert state["current"] is None
    assert state["daily"]["assignment"] is None
    ids = {c["id"] for c in state["daily"]["pickable"]}
    assert "set_table" in ids
    r = parent.post("/api/kid/pick", json={"chore_id": "set_table"})
    assert r.status_code == 200
    asg2 = r.json()["id"]
    parent.post("/api/kid/finish", json={"assignment_id": asg2})
    parent.post("/api/kid/cancel", json={"assignment_id": asg2})
    state = parent.get("/api/kid/state").json()
    assert state["extra"]["unlocked"] is False
    assert state["child"]["stars"] == 0


def test_cannot_cancel_approved_chore(parent: TestClient):
    kid_id = add_child(parent, "Eden", 10, "6666")
    login_kid(parent, kid_id, "6666")
    asg = parent.post("/api/kid/pick", json={"chore_id": "make_bed"}).json()["id"]
    parent.post("/api/kid/finish", json={"assignment_id": asg})
    parent.post("/api/parent/login", json={"username": "parent", "password": "secret"})
    parent.post(f"/api/parent/assignments/{asg}/approve")
    login_kid(parent, kid_id, "6666")
    r = parent.post("/api/kid/cancel", json={"assignment_id": asg})
    assert r.status_code == 400
    state = parent.get("/api/kid/state").json()
    assert state["child"]["stars"] == 5


def _finish_and_approve(client: TestClient, kid_id: int, pin: str, chore_id: str) -> None:
    login_kid(client, kid_id, pin)
    asg = client.post("/api/kid/pick", json={"chore_id": chore_id}).json()["id"]
    client.post("/api/kid/finish", json={"assignment_id": asg})
    client.post("/api/parent/login", json={"username": "parent", "password": "secret"})
    assert client.post(f"/api/parent/assignments/{asg}/approve").status_code == 200


def test_redeem_holds_then_spends_stars(parent: TestClient):
    kid_id = add_child(parent, "Quinn", 12, "1212")
    _finish_and_approve(parent, kid_id, "1212", "make_bed")
    login_kid(parent, kid_id, "1212")
    r = parent.post("/api/kid/redeem", json={"reward_id": "computer_time"})
    assert r.status_code == 400
    login_kid(parent, kid_id, "1212")
    parent.post("/api/kid/pick", json={"chore_id": "match_socks"})
    extra = parent.get("/api/kid/state").json()["current"]["id"]
    parent.post("/api/kid/finish", json={"assignment_id": extra})
    parent.post("/api/parent/login", json={"username": "parent", "password": "secret"})
    parent.post(f"/api/parent/assignments/{extra}/approve")
    login_kid(parent, kid_id, "1212")
    state = parent.get("/api/kid/state").json()
    assert state["child"]["stars"] == 11
    assert state["child"]["available"] == 11
    r = parent.post("/api/kid/redeem", json={"reward_id": "computer_time"})
    assert r.status_code == 200, r.text
    shop = parent.get("/api/kid/rewards").json()
    assert shop["child"]["available"] == 1
    assert shop["child"]["held"] == 10
    assert shop["child"]["stars"] == 11
    r = parent.post("/api/kid/redeem", json={"reward_id": "ice_cream"})
    assert r.status_code == 400
    rid = shop["pending"][0]["id"]
    parent.post("/api/parent/login", json={"username": "parent", "password": "secret"})
    assert parent.post(f"/api/parent/redemptions/{rid}/approve").status_code == 200
    parent.post(f"/api/parent/redemptions/{rid}/approve")
    login_kid(parent, kid_id, "1212")
    shop = parent.get("/api/kid/rewards").json()
    assert shop["child"]["stars"] == 1
    assert shop["child"]["available"] == 1
    assert shop["child"]["held"] == 0
    hist = parent.get("/api/kid/history").json()
    assert hist["summary"]["rewards_cashed"] == 1
    assert hist["rewards"][0]["reward_id"] == "computer_time"
    assert hist["rewards"][0]["state"] == "approved"


def test_deny_redemption_returns_stars(parent: TestClient):
    kid_id = add_child(parent, "Riley", 12, "1313")
    _finish_and_approve(parent, kid_id, "1313", "make_bed")
    login_kid(parent, kid_id, "1313")
    extra = parent.post("/api/kid/pick", json={"chore_id": "match_socks"}).json()["id"]
    parent.post("/api/kid/finish", json={"assignment_id": extra})
    parent.post("/api/parent/login", json={"username": "parent", "password": "secret"})
    parent.post(f"/api/parent/assignments/{extra}/approve")
    login_kid(parent, kid_id, "1313")
    rid = parent.post("/api/kid/redeem", json={"reward_id": "computer_time"}).json()["id"]
    parent.post("/api/parent/login", json={"username": "parent", "password": "secret"})
    parent.post(
        f"/api/parent/redemptions/{rid}/deny",
        json={"note": "Tomorrow."},
    )
    login_kid(parent, kid_id, "1313")
    shop = parent.get("/api/kid/rewards").json()
    assert shop["child"]["stars"] == 11
    assert shop["child"]["available"] == 11


def test_return_hides_extras_until_finished_again(parent: TestClient):
    kid_id = add_child(parent, "Casey", 11, "7777")
    login_kid(parent, kid_id, "7777")
    asg = parent.post("/api/kid/pick", json={"chore_id": "set_table"}).json()["id"]
    parent.post("/api/kid/finish", json={"assignment_id": asg})
    parent.post("/api/parent/login", json={"username": "parent", "password": "secret"})
    r = parent.post(
        f"/api/parent/assignments/{asg}/return",
        json={"note": "Tuck the chairs in."},
    )
    assert r.status_code == 200
    login_kid(parent, kid_id, "7777")
    state = parent.get("/api/kid/state").json()
    assert state["extra"]["unlocked"] is False
    assert state["current"]["state"] == "returned"
    parent.post("/api/kid/finish", json={"assignment_id": asg})
    state = parent.get("/api/kid/state").json()
    assert state["extra"]["unlocked"] is True
    assert state["child"]["stars"] == 0


def test_history_charts_and_is_per_child(parent: TestClient):
    a = add_child(parent, "HistA", 10, "1414")
    b = add_child(parent, "HistB", 10, "1515")
    _finish_and_approve(parent, a, "1414", "make_bed")
    login_kid(parent, a, "1414")
    kid_hist = parent.get("/api/kid/history").json()
    assert kid_hist["summary"]["stars_earned"] == 5
    assert kid_hist["summary"]["chores_approved"] == 1
    assert kid_hist["days"][-1]["earned"] == 5
    kinds = {e["kind"] for e in kid_hist["events"]}
    assert "chore_approved" in kinds
    assert kid_hist["rewards"] == []
    assert kid_hist["summary"]["rewards_cashed"] == 0
    parent.post("/api/parent/login", json={"username": "parent", "password": "secret"})
    other = parent.get(f"/api/parent/children/{b}/history").json()
    assert other["summary"]["stars_earned"] == 0
    mine = parent.get(f"/api/parent/children/{a}/history").json()
    assert mine["summary"]["stars_earned"] == 5
    login_kid(parent, b, "1515")
    r = parent.get(f"/api/parent/children/{a}/history")
    assert r.status_code == 401


def test_parent_can_manage_chores(parent: TestClient):
    listed = parent.get("/api/parent/chores").json()
    ids = {c["id"] for c in listed}
    assert "make_bed" in ids
    kid_id = add_child(parent, "ChoreKid", 8, "1717")
    created = parent.post(
        "/api/parent/chores",
        json={
            "title": "Feed the fish",
            "stars": 4,
            "kind": "extra",
            "min_age": 5,
            "minutes": 3,
            "steps": "Sprinkle two pinches of food.",
        },
    )
    assert created.status_code == 200, created.text
    cid = created.json()["id"]
    r = parent.patch(f"/api/parent/chores/{cid}", json={"stars": 6, "kind": "daily"})
    assert r.status_code == 200
    assert r.json()["stars"] == 6
    assert r.json()["kind"] == "daily"
    payload = parent.get(f"/api/parent/children/{kid_id}/chores").json()
    by_id = {row["chore"]["id"]: row for row in payload["items"]}
    assert cid in by_id
    assert by_id[cid]["assigned"] is False
    items = [
        {
            "chore_id": cid,
            "kind": "daily",
            "stars": 6,
            "enabled": True,
        }
    ]
    saved = parent.put(
        f"/api/parent/children/{kid_id}/chores",
        json={"items": items},
    )
    assert saved.status_code == 200, saved.text
    login_kid(parent, kid_id, "1717")
    state = parent.get("/api/kid/state").json()
    daily_ids = {c["id"]: c for c in state["daily"]["pickable"]}
    assert cid in daily_ids
    assert daily_ids[cid]["stars"] == 6
    assert "make_bed" not in daily_ids


def test_younger_child_can_get_harder_chore_with_more_stars(parent: TestClient):
    tiny = add_child(parent, "Pip", 5, "1818")
    login_kid(parent, tiny, "1818")
    state = parent.get("/api/kid/state").json()
    daily = {c["id"]: c for c in state["daily"]["pickable"]}
    assert "toys_in_bin" in daily
    assert "make_bed" not in daily
    parent.post("/api/parent/login", json={"username": "parent", "password": "secret"})
    payload = parent.get(f"/api/parent/children/{tiny}/chores").json()
    items = []
    for row in payload["items"]:
        chore_id = row["chore"]["id"]
        if chore_id == "make_bed":
            items.append({"chore_id": "make_bed", "kind": "daily", "stars": 8, "enabled": True})
        elif row["assigned"]:
            items.append(
                {
                    "chore_id": chore_id,
                    "kind": row["kind"],
                    "stars": row["stars"],
                    "enabled": True,
                }
            )
    saved = parent.put(
        f"/api/parent/children/{tiny}/chores",
        json={"items": items},
    )
    assert saved.status_code == 200, saved.text
    login_kid(parent, tiny, "1818")
    state = parent.get("/api/kid/state").json()
    daily = {c["id"]: c for c in state["daily"]["pickable"]}
    assert daily["make_bed"]["stars"] == 8
    asg = parent.post("/api/kid/pick", json={"chore_id": "make_bed"}).json()["id"]
    parent.post("/api/kid/finish", json={"assignment_id": asg})
    parent.post("/api/parent/login", json={"username": "parent", "password": "secret"})
    assert parent.post(f"/api/parent/assignments/{asg}/approve").status_code == 200
    login_kid(parent, tiny, "1818")
    state = parent.get("/api/kid/state").json()
    assert state["child"]["stars"] == 8
    hist = parent.get("/api/kid/history").json()
    approved = [e for e in hist["events"] if e["kind"] == "chore_approved"]
    assert approved[0]["stars"] == 8


def test_parent_can_upload_chore_media(parent: TestClient):
    jpeg = (CATALOG_DIR / "media" / "images" / "make_bed.jpg").read_bytes()
    r = parent.post(
        "/api/parent/chores/make_bed/media",
        data={"kind": "cover"},
        files={"file": ("cover.jpg", jpeg, "image/jpeg")},
    )
    assert r.status_code == 200, r.text
    assert r.json()["cover_image"] == "media/uploads/make_bed.jpg"
    assert (CATALOG_DIR / "media" / "uploads" / "make_bed.jpg").is_file()
    served = parent.get("/catalog/media/uploads/make_bed.jpg")
    assert served.status_code == 200
    bad = parent.post(
        "/api/parent/chores/make_bed/media",
        data={"kind": "cover"},
        files={"file": ("notes.txt", b"not a picture", "text/plain")},
    )
    assert bad.status_code == 400
    mp4 = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom"
    vid = parent.post(
        "/api/parent/chores/make_bed/media",
        data={"kind": "video"},
        files={"file": ("clip.mp4", mp4, "video/mp4")},
    )
    assert vid.status_code == 200, vid.text
    assert vid.json()["demo_video"] == "media/uploads/make_bed.mp4"
    kid_id = add_child(parent, "MediaKid", 8, "1919")
    login_kid(parent, kid_id, "1919")
    state = parent.get("/api/kid/state").json()
    pickable = {c["id"]: c for c in state["daily"]["pickable"]}
    assert pickable["make_bed"]["cover_image"] == "media/uploads/make_bed.jpg"
    assert pickable["make_bed"]["demo_video"] == "media/uploads/make_bed.mp4"
    parent.post("/api/parent/login", json={"username": "parent", "password": "secret"})
    cleared = parent.delete("/api/parent/chores/make_bed/media/cover")
    assert cleared.status_code == 200
    assert cleared.json()["cover_image"] == "media/images/make_bed.jpg"
    parent.delete("/api/parent/chores/make_bed/media/video")


def test_parent_can_manage_rewards(parent: TestClient):
    listed = parent.get("/api/parent/rewards").json()
    ids = {r["id"] for r in listed}
    assert "computer_time" in ids
    r = parent.patch("/api/parent/rewards/computer_time", json={"stars": 12, "enabled": True})
    assert r.status_code == 200
    assert r.json()["stars"] == 12
    created = parent.post(
        "/api/parent/rewards",
        json={"title": "Pizza night", "stars": 40, "min_age": 6, "emoji": "🍕", "description": "Family pizza"},
    )
    assert created.status_code == 200, created.text
    pid = created.json()["id"]
    kid_id = add_child(parent, "RewardKid", 8, "1616")
    login_kid(parent, kid_id, "1616")
    shop = parent.get("/api/kid/rewards").json()
    shop_ids = {r["id"]: r for r in shop["rewards"]}
    assert shop_ids["computer_time"]["stars"] == 12
    assert pid in shop_ids
    parent.post("/api/parent/login", json={"username": "parent", "password": "secret"})
    parent.patch("/api/parent/rewards/computer_time", json={"enabled": False})
    login_kid(parent, kid_id, "1616")
    shop = parent.get("/api/kid/rewards").json()
    assert "computer_time" not in {r["id"] for r in shop["rewards"]}
    parent.post("/api/parent/login", json={"username": "parent", "password": "secret"})
    parent.patch("/api/parent/rewards/computer_time", json={"stars": 10, "enabled": True})
