"""Weekly run: scrape -> diff -> classify -> analyze -> brief -> dashboard -> email.

    python run.py                       # every brand in clients/*.yaml
    python run.py clients/acme.yaml     # one brand
    python run.py --no-email            # build the dashboard only
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml

from radar import analyze, classify, render, store
from radar.llm import LLMError
from radar.scrape import Scraper, download_thumb, page_id_from

ROOT = Path(__file__).resolve().parent
IST = timezone(timedelta(hours=5, minutes=30))

CLASSIFY_MODEL = os.environ.get("CLASSIFY_MODEL", "haiku")
BRIEF_MODEL = os.environ.get("BRIEF_MODEL", "sonnet")
MAX_ADS = int(os.environ.get("MAX_ADS_PER_BRAND", "400"))
MAX_CLASSIFY = int(os.environ.get("MAX_CLASSIFY_PER_BRAND", "250"))
PARALLEL = int(os.environ.get("CLAUDE_PARALLEL", "3"))
CHECK_LIMIT = int(os.environ.get("KILL_CHECKS_PER_BRAND", "25"))


def log(*a):
    print(*a, flush=True)


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def load_config(path: Path) -> dict:
    cfg = yaml.safe_load(path.read_text())

    def entry(x, role):
        if isinstance(x, str):
            x = {"name": x}
        return {"label": x["name"].strip(), "ad_library": str(x.get("ad_library") or "").strip(), "role": role}

    brand = entry(cfg["brand"], "you")
    comps = [entry(c, "competitor") for c in cfg.get("competitors", [])][:6]
    emails = cfg.get("emails") or cfg.get("email") or []
    if isinstance(emails, str):
        emails = [e.strip() for e in emails.split(",")]
    return {"brand": brand, "competitors": comps, "emails": emails,
            "category": cfg.get("category", ""), "country": cfg.get("country", "IN"),
            "slug": slug(cfg.get("slug") or brand["label"])}


async def scrape_all(cfg: dict, state: dict, today: str, thumbs: Path) -> dict:
    runs = {}
    async with Scraper(country=cfg["country"], max_ads=MAX_ADS, log=log) as s:
        for p in [cfg["brand"], *cfg["competitors"]]:
            log(f"  · {p['label']}")
            cached = state["pages"].get(p["label"])
            pid = page_id_from(p["ad_library"]) or (cached or {}).get("page_id")
            if not pid:
                hit = await s.resolve_page(p["ad_library"] or p["label"])
                if not hit:
                    log(f"    could not find a Facebook page for '{p['label']}'. Add its Ad Library URL to the config.")
                    p.update(page_id=None, status="not found")
                    continue
                pid = hit["page_id"]
                log(f"    resolved to page '{hit['page_name']}' ({pid})")
            res = await s.fetch_page(pid, cfg["country"])
            p["page_id"] = pid
            p["status"] = res["status"]
            if res["status"] != "ok":
                log(f"    scrape failed ({res['status']}); keeping last week's data for this brand")
                continue
            if res["ads"]:  # creator/partnership ads carry the creator's name, so take the majority
                own = [a["page_name"] for a in res["ads"] if a["page_id"] == pid] or [a["page_name"] for a in res["ads"]]
                p["page_name"] = Counter(own).most_common(1)[0][0]
            state["pages"][p["label"]] = {"page_id": pid, "page_name": p.get("page_name")}
            checked = {}
            if not res["complete"]:  # a sample can't show kills by absence; check missing ads one by one
                cands = store.missing_candidates(state, pid, res["ads"], CHECK_LIMIT)
                verdicts = await s.check_active([a["ad_archive_id"] for a in cands])
                checked = {a["key"]: verdicts[a["ad_archive_id"]] for a in cands if a["ad_archive_id"] in verdicts}
                if cands:
                    log(f"    checked {len(checked)} ads missing from the sample: "
                        f"{sum(1 for v in checked.values() if not v)} switched off, "
                        f"{sum(1 for v in checked.values() if v)} still live")
            diff = store.merge_page(state, pid, res["ads"], res["complete"], today, checked)
            diff.update(complete=res["complete"], expected=res.get("expected"), mode=res.get("mode", "full"))
            runs[pid] = diff
            got = sum(download_thumb(a["thumb_url"], thumbs / f"{a['key']}.jpg") for a in res["ads"])
            log(f"    {len(res['ads'])} ads read ({'full list' if res['complete'] else 'sample of ~' + str(res.get('expected'))}), "
                f"{len(diff['new'])} unseen before, {len(diff['killed'])} switched off, {got} thumbnails")
    return runs


def classify_all(cfg, state, workdir: Path, thumbs: Path, notes: list, today: str) -> None:
    """Tag untagged live ads, brands in parallel (each Claude call takes ~1-2 min)."""
    recent = (datetime.fromisoformat(today) - timedelta(days=7)).date().isoformat()
    long_run = (datetime.fromisoformat(today) - timedelta(days=21)).date().isoformat()
    jobs = []
    for p in [cfg["brand"], *cfg["competitors"]]:
        pid = p.get("page_id")
        if not pid:
            continue
        todo = sorted([a for a in state["ads"].values()
                       if a["page_id"] == pid and a.get("active") and not a.get("tags")],
                      key=lambda a: (0 if a["first_seen"] == today and (a.get("start_str") or "") >= recent
                                     else 1 if (a.get("start_str") or "9") <= long_run else 2,
                                     a["impression_rank"]))  # new ads, then long-running winners, then by impressions
        if not todo:
            continue
        skipped = max(0, len(todo) - MAX_CLASSIFY)
        log(f"  · {p['label']}: classifying {min(len(todo), MAX_CLASSIFY)} ads"
            + (f" ({skipped} lower-ranked deferred to next week)" if skipped else ""))
        if skipped:
            notes.append(f"{p['label']}: {skipped} low-impression ads were left untagged this week to stay within "
                         "usage limits; they are picked up next run.")
        jobs.append((p["label"], todo[:MAX_CLASSIFY], state["concepts"].setdefault(pid, []), workdir / "work" / pid))

    def work(job):
        label, todo, concepts, wd = job
        try:
            classify.classify_page(label, todo, concepts, wd, thumbs, CLASSIFY_MODEL,
                                   log=lambda *m: log(f"    [{label}]", *m))
        except LLMError as e:
            log(f"    [{label}] Claude unavailable: {e}")
            notes.append(f"{label}: tagging stopped early ({str(e)[:120]}). The rest are picked up next run.")

    with ThreadPoolExecutor(max_workers=PARALLEL) as pool:
        list(pool.map(work, jobs))


def run_client(path: Path, send_email: bool, today: str | None, rerender: bool = False) -> Path:
    cfg = load_config(path)
    now = datetime.now(IST)
    today = today or now.date().isoformat()
    data = ROOT / "data" / cfg["slug"]
    thumbs = data / "thumbs"
    state_path = data / "state.json"
    state = store.load(state_path)
    notes: list[str] = []
    log(f"\n=== {cfg['brand']['label']} · {today} ===")

    last_path = data / "last_run.json"
    if rerender:  # rebuild the dashboard from the saved run, no scraping or Claude calls
        last = json.loads(last_path.read_text())
        today, runs, notes = last["today"], last["runs"], last["notes"]
        for p in [cfg["brand"], *cfg["competitors"]]:
            p.update(last["pages"].get(p["label"], {}))
    else:
        log("1/5 Scraping the Ad Library")
        runs = asyncio.run(scrape_all(cfg, state, today, thumbs))
        store.save(state, state_path)

        log("2/5 Classifying new ads with Claude")
        classify_all(cfg, state, data, thumbs, notes, today)
        store.save(state, state_path)

    log("3/5 Analyzing")
    pages = []
    for p in [cfg["brand"], *cfg["competitors"]]:
        pid = p.get("page_id")
        if not pid:
            notes.append(f"Could not find a Facebook page for {p['label']}. Paste its Ad Library URL into the config.")
            continue
        run = runs.get(pid, {"new": [], "killed": [], "baseline": False, "complete": False})
        run["status"] = p.get("status", "ok")
        pages.append(analyze.analyze_page(state, {**p, "page_name": p.get("page_name")}, run, today))
    cat = analyze.category_view(pages)
    baseline = all(p["baseline"] for p in pages if p["role"] == "competitor")

    brief = None
    if rerender:
        brief = last.get("brief")
    if not brief:
        log("4/5 Writing the Monday brief")
        try:
            brief = classify.write_brief(cfg["brand"]["label"], cfg["category"], analyze.brief_input(pages, cat), BRIEF_MODEL)
        except LLMError as e:
            log(f"    brief skipped: {e}")
            notes.append("The written brief could not be generated this week (Claude unavailable); numbers above are complete.")
        last_path.write_text(json.dumps({
            "today": today, "runs": runs, "notes": notes, "brief": brief,
            "pages": {p["label"]: {k: p.get(k) for k in ("page_id", "page_name", "status")}
                      for p in [cfg["brand"], *cfg["competitors"]]}}, ensure_ascii=False, indent=1))

    if not rerender:
        state["runs"] = [r for r in state["runs"] if r["date"] != today]
        state["runs"].append({"date": today, "pages": {p["page_id"]: {"active": p["active"], "new": p["new_count"],
                                                                  "killed": p["killed_count"]} for p in pages}})
    for p in pages:  # re-read trend now that this run is recorded
        p["trend"] = [(r["date"], r["pages"][p["page_id"]]["active"]) for r in state["runs"] if p["page_id"] in r["pages"]]
    store.prune(state, thumbs, today)
    store.save(state, state_path)

    log("5/5 Rendering")
    ctx = dict(brand=cfg["brand"]["label"], competitors=[c["label"] for c in cfg["competitors"]],
               country=cfg["country"], today=today, generated=now.strftime("%-d %b %Y, %H:%M IST"),
               pages=pages, cat=cat, brief=brief, baseline=baseline, notes=notes)
    out_dir = ROOT / "reports" / cfg["slug"]
    out_dir.mkdir(parents=True, exist_ok=True)
    name = f"ad-radar-{cfg['slug']}-{today}.html"
    out = out_dir / name
    out.write_text(render.dashboard(ctx, thumbs))
    (out_dir / "latest.html").write_text(out.read_text())
    log(f"    dashboard: {out.relative_to(ROOT)} ({out.stat().st_size // 1024} KB)")

    if send_email and cfg["emails"]:
        from radar import mailer
        html = render.email({**ctx, "attachment_name": name}, thumbs)
        subject = f"Ad Radar · {cfg['brand']['label']} · " + (brief["headline"][:90] if brief else f"week of {today}")
        mailer.send(cfg["emails"], subject, html, out)
        log(f"    emailed {', '.join(cfg['emails'])}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("configs", nargs="*", help="client YAML files (default: clients/*.yaml)")
    ap.add_argument("--no-email", action="store_true")
    ap.add_argument("--rerender", action="store_true", help="rebuild the dashboard from the last saved run")
    ap.add_argument("--today", help="override run date (YYYY-MM-DD), for testing")
    args = ap.parse_args()
    paths = [Path(c) for c in args.configs] or sorted(p for p in (ROOT / "clients").glob("*.yaml") if not p.name.startswith("_"))
    if not paths:
        log("Not set up yet: run \"Set up Ad Radar\" from the Actions tab to add your brand.")
        return
    failed = 0
    for p in paths:
        try:
            run_client(p, send_email=not args.no_email, today=args.today, rerender=args.rerender)
        except Exception as e:  # one broken brand must not stop the others
            failed += 1
            log(f"!! {p.name} failed: {type(e).__name__}: {e}")
    sys.exit(1 if failed == len(paths) else 0)


if __name__ == "__main__":
    main()
