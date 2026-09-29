"""Persistent per-brand state: every ad ever seen, when it appeared, when it died.

This file is what turns a snapshot into a *diff* -- "what they started, what
they killed" needs last week's list. In GitHub Actions the data/ folder is
committed back to the repo after every run.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

PRUNE_AFTER_DAYS = 180


def load(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text())
    return {"pages": {}, "concepts": {}, "ads": {}, "runs": []}


def save(state: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1))
    tmp.replace(path)


def start_str(ts) -> str | None:
    return datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat() if ts else None


def merge_page(state: dict, page_id: str, scraped: list[dict], complete: bool, today: str) -> dict:
    """Fold this week's scrape into state. Returns {"new": [keys], "killed": [keys]}."""
    ads = state["ads"]
    baseline = not any(page_id in r.get("pages", {}) for r in state["runs"])
    prev_active = {k for k, a in ads.items() if a["page_id"] == page_id and a.get("active")}
    current = set()
    new = []
    for ad in scraped:
        ad["page_id"] = page_id  # collab ads can carry the partner's page id
        ad["start_str"] = start_str(ad.get("start_date"))
        k = ad["key"]
        current.add(k)
        if k in ads:
            old = ads[k]
            tags = old.get("tags")
            first_seen, baseline_flag = old["first_seen"], old.get("baseline", False)
            old.update(ad)
            old.update(first_seen=first_seen, baseline=baseline_flag, last_seen=today,
                       active=True, ended_on=None)
            if tags:
                old["tags"] = tags
        else:
            ad.update(first_seen=today, last_seen=today, active=True, ended_on=None, baseline=baseline)
            ads[k] = ad
            new.append(k)
    killed = []
    if complete:  # only trust disappearances when we saw the whole list
        for k in prev_active - current:
            ads[k].update(active=False, ended_on=today)
            killed.append(k)
    return {"new": new, "killed": killed, "baseline": baseline}


def prune(state: dict, thumbs_dir: Path, today: str) -> None:
    t = date.fromisoformat(today)
    for k in list(state["ads"]):
        a = state["ads"][k]
        if not a.get("active") and a.get("ended_on") and (t - date.fromisoformat(a["ended_on"])).days > PRUNE_AFTER_DAYS:
            del state["ads"][k]
            (thumbs_dir / f"{k}.jpg").unlink(missing_ok=True)
