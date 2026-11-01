from __future__ import annotations

import json
from pathlib import Path

from server.config import CATALOG_DIR


class Catalog:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or CATALOG_DIR
        self.chores: dict[str, dict] = {}
        self.rewards: dict[str, dict] = {}
        self.reload()

    def reload(self) -> None:
        index_path = self.root / "index.json"
        index = json.loads(index_path.read_text(encoding="utf-8"))
        chores: dict[str, dict] = {}
        for chore_id in index["chores"]:
            path = self.root / "chores" / f"{chore_id}.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("id") != chore_id:
                raise ValueError(f"chore id mismatch in {path}")
            chores[chore_id] = data
        self.chores = chores
        rewards: dict[str, dict] = {}
        for reward_id in index.get("rewards", []):
            path = self.root / "rewards" / f"{reward_id}.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("id") != reward_id:
                raise ValueError(f"reward id mismatch in {path}")
            rewards[reward_id] = data
        self.rewards = rewards

    def get(self, chore_id: str) -> dict | None:
        return self.chores.get(chore_id)

    def all(self) -> list[dict]:
        return [self.chores[k] for k in self.chores]

    def default_ids(self, kind: str) -> list[str]:
        return [c["id"] for c in self.all() if c.get("kind") == kind]

    def public(self, chore: dict) -> dict:
        return {
            "id": chore["id"],
            "title": chore["title"],
            "category": chore["category"],
            "kind": chore["kind"],
            "min_age": chore["min_age"],
            "minutes": chore["minutes"],
            "stars": chore["stars"],
            "grown_up_required": chore.get("grown_up_required", False),
            "materials": chore.get("materials", []),
            "cover_image": chore.get("cover_image"),
            "demo_video": chore.get("demo_video"),
            "steps": chore.get("steps", []),
            "done_when": chore.get("done_when", []),
        }

    def parent_view(self, chore: dict) -> dict:
        view = self.public(chore)
        view["parent_notes"] = chore.get("parent_notes")
        return view

    def get_reward(self, reward_id: str) -> dict | None:
        return self.rewards.get(reward_id)

    def all_rewards(self) -> list[dict]:
        return [self.rewards[k] for k in self.rewards]

    def public_reward(self, reward: dict) -> dict:
        return {
            "id": reward["id"],
            "title": reward["title"],
            "description": reward.get("description", ""),
            "stars": reward["stars"],
            "min_age": reward.get("min_age", 0),
            "emoji": reward.get("emoji", "★"),
            "season": reward.get("season"),
            "grown_up_required": reward.get("grown_up_required", True),
        }

    def parent_reward(self, reward: dict) -> dict:
        view = self.public_reward(reward)
        view["parent_notes"] = reward.get("parent_notes")
        return view


catalog = Catalog()
