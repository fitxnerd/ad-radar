"""Turn tagged ads into the numbers the dashboard shows.

Every metric maps to a line in the playbook:
  concepts & variants/concept  -> Concept vs Variant ("are they testing or varying?")
  days running                 -> "Active since is the signal"
  impression rank              -> Meta's own sort order, a second winner signal
  killed + lifetime            -> "Watch for what disappears"
  angle heatmap / white space  -> the Angle Library, "the one argument nobody is making"
  format / hook / offer mix     -> Format Mix, Hook Families, Offer as a Variable

Fairness: brands run very different ad volumes, so every mix is a share of that
brand's own ads, and category averages weight every competitor equally.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date
from statistics import median

from . import taxonomy


def _days(a: dict, until: date) -> int:
    s = a.get("start_str")
    return max(0, (until - date.fromisoformat(s)).days) if s else 0


def _share(items, key) -> dict:
    c = Counter(key(a) for a in items)
    n = sum(c.values()) or 1
    return {k: round(v / n, 3) for k, v in c.most_common()}


def _tag(a, field, default="unclassified"):
    return (a.get("tags") or {}).get(field, default)


def killed_verdict(days: int) -> str:
    if days < 14:
        return "Failed test"
    if days >= 45:
        return "Fatigued winner"
    return "Retired"


def posture(n_concepts: int, n_active: int, offer_share: float, med_age: float) -> str:
    ratio = n_active / max(n_concepts, 1)
    if offer_share >= 0.5:
        return "Offer-led push"
    if n_concepts >= 6 and ratio <= 6:
        return "Systematic tester"
    if n_concepts <= 3 and ratio >= 8:
        return "Varying, not testing"
    if med_age >= 60:
        return "Stable library"
    return "Mixed approach"


def analyze_page(state: dict, page: dict, run: dict, today: str) -> dict:
    t = date.fromisoformat(today)
    pid = page["page_id"]
    all_ads = [a for a in state["ads"].values() if a["page_id"] == pid]
    # Live this week = seen in this week's list, or confirmed live on its own page.
    active = [a for a in all_ads if a.get("active") and a.get("last_seen") == today]
    for a in all_ads:
        a["days"] = _days(a, date.fromisoformat(a["ended_on"]) if a.get("ended_on") else t)

    new_keys = set(run.get("new", []))
    if run.get("baseline"):  # first week: "new" = started in the last 7 days
        new = [a for a in active if a["days"] <= 7]
    else:
        new = [a for a in active if a["key"] in new_keys]
    killed = [state["ads"][k] for k in run.get("killed", []) if k in state["ads"]]
    for a in killed:
        a["verdict"] = killed_verdict(a["days"])

    tagged = [a for a in active if a.get("tags")]
    # Meta's own "~N results" is the true live count when only a sample could be read.
    live_total = max(run.get("expected") or 0, len(active)) if not run.get("complete", True) else len(active)
    by_concept = defaultdict(list)
    for a in tagged:
        by_concept[_tag(a, "concept", "Unclassified")].append(a)
    first_seen_by_concept = defaultdict(lambda: today)
    for a in all_ads:
        c = _tag(a, "concept", "Unclassified")
        first_seen_by_concept[c] = min(first_seen_by_concept[c], a["first_seen"])
    new_key_set = {a["key"] for a in new}
    concepts = []
    for name, group in by_concept.items():
        group.sort(key=lambda a: a["impression_rank"])
        is_new = (not run.get("baseline") and first_seen_by_concept[name] == today) or \
                 (run.get("baseline") and all(a["days"] <= 7 for a in group))
        concepts.append({
            "name": name,
            "angle": _tag(group[0], "angle_family", "brand_lifestyle"),
            "variants": len(group),
            "new_variants": sum(1 for a in group if a["key"] in new_key_set),
            "oldest_days": max(a["days"] for a in group),
            "median_days": int(median(a["days"] for a in group)),
            "best_rank": group[0]["impression_rank"],
            "is_new": is_new,
            "summary": _tag(group[0], "summary", ""),
            "media": _share(group, lambda a: a["media"]),
            "top_key": group[0]["key"],
        })
    concepts.sort(key=lambda c: (-c["variants"], c["best_rank"]))
    live_concepts = {c["name"] for c in concepts}
    dead_concepts = sorted({_tag(a, "concept", "") for a in killed} - live_concepts - {""})

    offer_share = sum(1 for a in tagged if _tag(a, "offer_type") != "none") / max(len(tagged), 1)
    med_age = median([a["days"] for a in active]) if active else 0
    winners = sorted([a for a in active if a["days"] >= 21], key=lambda a: (-a["days"], a["impression_rank"]))[:6]
    top_rank = sorted(active, key=lambda a: a["impression_rank"])[:6]
    n_concepts = len(concepts)

    return {
        "name": page["label"], "page_name": page.get("page_name"), "page_id": pid, "role": page["role"],
        "complete": run.get("complete", True), "baseline": run.get("baseline", False),
        "status": run.get("status", "ok"),
        "active": live_total, "read": len(active), "sampled": not run.get("complete", True),
        "new_count": len(new), "killed_count": len(killed),
        "refresh_rate": round(len(new) / max(live_total, 1), 3),
        "churn_rate": round(len(killed) / max(live_total + len(killed), 1), 3),
        "n_concepts": n_concepts,
        "variants_per_concept": round(len(tagged) / max(n_concepts, 1), 1),
        "tagged": len(tagged), "untagged": len(active) - len(tagged),
        "median_age": int(med_age),
        "offer_share": round(offer_share, 3),
        "video_share": round(sum(1 for a in active if a["media"] == "video") / max(len(active), 1), 3),
        "posture": posture(n_concepts, len(tagged), offer_share, med_age),
        "mix": {
            "media": _share(active, lambda a: a["media"]),
            "angle": _share(tagged, lambda a: _tag(a, "angle_family")),
            "hook": _share(tagged, lambda a: _tag(a, "hook_family")),
            "style": _share(tagged, lambda a: _tag(a, "creative_style")),
            "language": _share(tagged, lambda a: _tag(a, "language")),
            "offer": _share([a for a in tagged if _tag(a, "offer_type") != "none"],
                            lambda a: _tag(a, "offer_type")),
        },
        "concepts": concepts,
        "new_concepts": [c["name"] for c in concepts if c["is_new"]],
        "dead_concepts": dead_concepts,
        "new_ads": sorted(new, key=lambda a: a["impression_rank"]),
        "killed_ads": sorted(killed, key=lambda a: -a["days"]),
        "winners": winners,
        "top_rank": top_rank,
        "trend": [(r["date"], r["pages"][pid]["active"]) for r in state["runs"] if pid in r.get("pages", {})],
    }


def category_view(pages: list[dict]) -> dict:
    """Where the category is fighting, normalized so every competitor counts equally."""
    comps = [p for p in pages if p["role"] == "competitor" and p["active"]]
    you = next((p for p in pages if p["role"] == "you" and p["active"]), None)
    angles = list(taxonomy.ANGLE_FAMILIES)
    heat = {p["name"]: {a: p["mix"]["angle"].get(a, 0) for a in angles} for p in pages if p["active"]}
    rows = []
    for a in angles:
        shares = {p["name"]: p["mix"]["angle"].get(a, 0) for p in comps}
        avg = sum(shares.values()) / max(len(comps), 1)
        leader = max(shares, key=shares.get) if shares else None
        users = [n for n, v in shares.items() if v >= 0.05]
        yours = you["mix"]["angle"].get(a, 0) if you else None
        rows.append({
            "angle": a, "avg": round(avg, 3), "leader": leader,
            "leader_share": round(shares.get(leader, 0), 3) if leader else 0,
            "users": users, "you": yours,
            "index": round(yours / avg, 1) if yours is not None and avg >= 0.01 else None,
            "white_space": len(users) <= 1 and avg < 0.05,
        })
    rows.sort(key=lambda r: -r["avg"])
    return {
        "angles": angles, "heat": heat, "rows": rows,
        "fighting": [r for r in rows if not r["white_space"]],
        "white_space": [r for r in rows if r["white_space"]],
        "category_angle": {r["angle"]: r["avg"] for r in rows},
        "totals": {"active": sum(p["active"] for p in comps), "new": sum(p["new_count"] for p in comps),
                   "killed": sum(p["killed_count"] for p in comps),
                   "new_concepts": sum(len(p["new_concepts"]) for p in comps)},
    }


def brief_input(pages: list[dict], cat: dict) -> dict:
    """Compact, text-only view of the week for Claude to write the brief from."""
    def ad_line(a):
        t = a.get("tags") or {}
        return {"concept": t.get("concept"), "angle": t.get("angle_family"), "hook": t.get("hook_text"),
                "format": a["media"], "days_running": a["days"], "impression_rank": a["impression_rank"],
                "offer": t.get("offer_text")}
    out = {"category": {"angle_share": cat["category_angle"],
                        "white_space_angles": [w["angle"] for w in cat["white_space"]],
                        "totals": cat["totals"]}, "brands": []}
    for p in pages:
        out["brands"].append({
            "name": p["name"], "role": p["role"], "baseline_week": p["baseline"],
            "active_ads": p["active"], "ads_tagged": p["tagged"], "new_this_week": p["new_count"], "killed_this_week": p["killed_count"],
            "concepts": p["n_concepts"], "variants_per_concept": p["variants_per_concept"],
            "median_ad_age_days": p["median_age"], "offer_share": p["offer_share"],
            "refresh_rate_new_over_live": p["refresh_rate"],
            "mix": {k: dict(list(v.items())[:5]) for k, v in p["mix"].items()},
            "top_concepts": [{k: c[k] for k in ("name", "angle", "variants", "new_variants", "oldest_days", "summary", "is_new")}
                             for c in p["concepts"][:8]],
            "new_concepts": p["new_concepts"], "dead_concepts": p["dead_concepts"],
            "new_ads": [ad_line(a) for a in p["new_ads"][:8]],
            "killed_ads": [dict(ad_line(a), verdict=a.get("verdict")) for a in p["killed_ads"][:8]],
            "longest_running": [ad_line(a) for a in p["winners"][:4]],
        })
    return out
