"""Scrape the public Meta Ad Library with a real (headless) Chrome.

No API keys, no paid scrapers. Two things make this work reliably:
  1. channel="chrome" -- Playwright's bundled Chromium gets served an empty
     result set; real Google Chrome does not.
  2. A warm-up visit to /ads/library/ first, so the anti-bot challenge cookie
     is set before we hit the search URL.

The first ~30 ads are embedded in the HTML as JSON; the rest arrive through
/api/graphql/ responses as we scroll. We collect both.
"""
from __future__ import annotations

import asyncio
import io
import json
import re
import time
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

from playwright.async_api import async_playwright

BASE = "https://www.facebook.com/ads/library/"
SCRIPT_JSON = re.compile(r'<script type="application/json"[^>]*>(.*?)</script>', re.S)


SORT_VIEWS = "total_impressions"          # "Impressions: high to low"
SORT_RECENT = "relevancy_monthly_grouped"  # "Most recent"


def page_url(page_id: str, country: str, sort: str = SORT_VIEWS, media: str = "all") -> str:
    q = {
        "active_status": "active", "ad_type": "all", "country": country,
        "is_targeted_country": "false", "media_type": media,
        "search_type": "page", "view_all_page_id": page_id,
        "sort_data[mode]": sort, "sort_data[direction]": "desc",
    }
    return BASE + "?" + urllib.parse.urlencode(q)


def keyword_url(term: str, country: str) -> str:
    q = {
        "active_status": "active", "ad_type": "all", "country": country,
        "is_targeted_country": "false", "media_type": "all", "q": term,
        "search_type": "keyword_unordered",
        "sort_data[mode]": "total_impressions", "sort_data[direction]": "desc",
    }
    return BASE + "?" + urllib.parse.urlencode(q)


def page_id_from(value: str) -> str | None:
    """Accept a bare page ID or any Ad Library URL containing view_all_page_id."""
    value = str(value).strip()
    if value.isdigit():
        return value
    m = re.search(r"view_all_page_id=(\d+)", value)
    return m.group(1) if m else None


def _walk(o, out):
    if isinstance(o, dict):
        if "ad_archive_id" in o and "snapshot" in o:
            out.append(o)
            return
        for v in o.values():
            _walk(v, out)
    elif isinstance(o, list):
        for v in o:
            _walk(v, out)


def _ads_from_html(html: str) -> list[dict]:
    out: list[dict] = []
    for m in SCRIPT_JSON.finditer(html):
        if "ad_archive_id" in m.group(1):
            try:
                _walk(json.loads(m.group(1)), out)
            except json.JSONDecodeError:
                pass
    return out


def _ads_from_graphql(text: str) -> list[dict]:
    out: list[dict] = []
    for line in text.splitlines():
        if "ad_archive_id" in line:
            try:
                _walk(json.loads(line), out)
            except json.JSONDecodeError:
                pass
    return out


def _first(*vals):
    for v in vals:
        if v:
            return v
    return None


def normalize(raw: dict, rank: int) -> dict:
    """Flatten Meta's snapshot into the fields the analysis actually uses."""
    s = raw.get("snapshot") or {}
    cards = s.get("cards") or []
    images = s.get("images") or []
    videos = s.get("videos") or []
    body = (s.get("body") or {}).get("text") or ""
    if (not body or "{{" in body) and cards:
        body = cards[0].get("body") or body
    thumb = _first(
        images[0].get("resized_image_url") if images else None,
        images[0].get("original_image_url") if images else None,
        videos[0].get("video_preview_image_url") if videos else None,
        cards[0].get("resized_image_url") if cards else None,
        cards[0].get("original_image_url") if cards else None,
        cards[0].get("video_preview_image_url") if cards else None,
    )
    fmt = s.get("display_format") or "UNKNOWN"
    if fmt in ("DCO", "DPA", "MULTI_IMAGES", "CAROUSEL") and videos:
        media = "video"
    elif fmt == "VIDEO" or (cards and any(c.get("video_preview_image_url") for c in cards) and fmt != "DPA"):
        media = "video"
    elif fmt in ("CAROUSEL", "MULTI_IMAGES") or (fmt == "DCO" and len(cards) > 1):
        media = "carousel"
    elif fmt == "DPA":
        media = "catalog"
    else:
        media = "static"
    key = str(raw.get("collation_id") or raw["ad_archive_id"])
    return {
        "key": key,
        "ad_archive_id": str(raw["ad_archive_id"]),
        "page_id": str(raw.get("page_id") or s.get("page_id") or ""),
        "page_name": s.get("page_name") or raw.get("page_name"),
        "versions": raw.get("collation_count") or 1,
        "start_date": raw.get("start_date"),
        "platforms": raw.get("publisher_platform") or [],
        "display_format": fmt,
        "media": media,
        "body": body.strip()[:1500],
        "title": (s.get("title") or (cards[0].get("title") if cards else "") or "")[:200],
        "link_description": (s.get("link_description") or "")[:200],
        "cta": s.get("cta_text"),
        "link_url": s.get("link_url") or (cards[0].get("link_url") if cards else None),
        "card_titles": [c.get("title") for c in cards[:6] if c.get("title")],
        "thumb_url": thumb,
        "impression_rank": rank,
        "library_url": f"https://www.facebook.com/ads/library/?id={raw['ad_archive_id']}",
    }


class Scraper:
    def __init__(self, country: str = "IN", max_ads: int = 500, log=print):
        self.country = country
        self.max_ads = max_ads
        self.log = log

    async def __aenter__(self):
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(
            channel="chrome", headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        return self

    async def __aexit__(self, *exc):
        await self._browser.close()
        await self._pw.stop()

    async def _new_page(self):
        ctx = await self._browser.new_context(
            locale="en-US", viewport={"width": 1400, "height": 1000})
        page = await ctx.new_page()
        await page.goto(BASE, wait_until="load", timeout=90000)
        await page.wait_for_timeout(4000)
        return ctx, page

    async def _load(self, page, url) -> tuple[str, int | None]:
        """Navigate and wait until the result count or the empty state renders.
        Returns (status, the "~N results" count Meta shows, if any)."""
        await page.goto(url, wait_until="load", timeout=90000)
        for _ in range(25):
            await page.wait_for_timeout(1500)
            txt = await page.inner_text("body")
            m = re.search(r"~?([\d,.]+)(K?)\s+results?", txt)
            if m:
                n = float(m.group(1).replace(",", ""))
                return "ok", int(n * 1000 if m.group(2) else n)
            if "No ads match" in txt:
                return "empty", 0
        return "timeout", None

    async def _scroll(self, page) -> None:
        """Nudge the infinite scroll three ways: some environments only react to one."""
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.mouse.wheel(0, 6000)
        await page.keyboard.press("End")

    async def fetch(self, url: str, attempts: int = 3) -> dict:
        """Return {"ads": [normalized...], "complete": bool, "status": str}."""
        status = "error"
        for attempt in range(attempts):
            ctx, page = await self._new_page()
            gql: list[str] = []
            self.trace: list[str] = []

            async def on_resp(r):
                if "/api/graphql" in r.url:
                    try:
                        body = await r.text()
                        gql.append(body)
                        post = r.request.post_data or ""
                        name = re.search(r"fb_api_req_friendly_name=([^&]+)", post)
                        self.trace.append(f"{r.status} {name.group(1) if name else '?'} {len(body)}b "
                                          f"{re.sub(chr(92) + 's+', ' ', body)[:90]}")
                    except Exception:
                        pass
            page.on("response", on_resp)
            try:
                status, expected = await self._load(page, url)
                if status != "ok":
                    self.log(f"    attempt {attempt + 1}: {status}")
                    await ctx.close()
                    continue
                seen: dict[str, dict] = {}
                order: list[str] = []

                def absorb(raws):
                    for r in raws:
                        aid = str(r["ad_archive_id"])
                        if aid not in seen:
                            seen[aid] = r
                            order.append(aid)

                absorb(_ads_from_html(await page.content()))
                from_html = len(order)
                gql_seen, gql_with_ads, sample = 0, 0, ""
                stale, exhausted = 0, False
                while len(order) < self.max_ads:
                    before = len(order)
                    await self._scroll(page)
                    await page.wait_for_timeout(3000)
                    while gql:
                        body = gql.pop(0)
                        gql_seen += 1
                        found = _ads_from_graphql(body)
                        if found:
                            gql_with_ads += 1
                        elif not sample and "ad_library" in body.lower():
                            sample = re.sub(r"\s+", " ", body)[:160]
                        absorb(found)
                    if len(order) == before:
                        stale += 1
                        if stale >= 5:
                            exhausted = True
                            break
                    else:
                        stale = 0
                # Only trust "we saw everything" when the count matches what Meta says is live;
                # otherwise a stalled scroll would make every unseen ad look "killed".
                complete = exhausted and (expected is None or len(order) >= 0.85 * expected)
                self.log(f"    read {len(order)} of ~{expected if expected is not None else '?'} live "
                         f"({from_html} from page, {len(order) - from_html} from {gql_with_ads}/{gql_seen} "
                         f"scroll responses){'' if complete else ', list incomplete'}"
                         + (f" | sample: {sample}" if sample and not gql_with_ads else ""))
                ads = [normalize(seen[a], i + 1) for i, a in enumerate(order)]
                await ctx.close()
                limited = any("Rate limit" in t for t in self.trace)
                return {"ads": ads, "complete": complete, "status": "ok", "expected": expected,
                        "rate_limited": limited}
            except Exception as e:  # network hiccup, retry with a fresh context
                self.log(f"    attempt {attempt + 1}: {type(e).__name__}: {str(e)[:120]}")
                status = "error"
                await ctx.close()
        return {"ads": [], "complete": False, "status": status}

    async def fetch_page(self, page_id: str, country: str) -> dict:
        """All live ads of one brand. Scrolls for the full list; where Meta rate-limits
        scrolling (it does for cloud servers such as GitHub's), falls back to a sample
        built only from first pages: newest and most viewed, overall and per format."""
        res = await self.fetch(page_url(page_id, country))
        if res["status"] != "ok" or res["complete"]:
            for a in res["ads"]:
                a["rank_known"] = True
            res["mode"] = "full"
            return res
        order = {a["key"]: a for a in res["ads"]}
        for a in order.values():
            a["rank_known"] = True  # position in Meta's own sort by impressions
        ctx, page = await self._new_page()
        loads = 0
        try:
            slices = [(SORT_RECENT, "all")] + [(sort, media) for media in ("video", "meme", "image")
                                                for sort in (SORT_VIEWS, SORT_RECENT)]
            skip_media = set()
            for sort, media in slices:
                if media in skip_media or len(order) >= self.max_ads:
                    continue
                status, n = await self._load(page, page_url(page_id, country, sort, media))
                loads += 1
                if status != "ok" or not n:
                    skip_media.add(media)
                    continue
                for i, raw in enumerate(_ads_from_html(await page.content())):
                    ad = normalize(raw, len(order) + 1)
                    ad["rank_known"] = False
                    order.setdefault(ad["key"], ad)
                if n <= 30:  # the first page already held every ad of this format
                    skip_media.add(media)
        finally:
            await ctx.close()
        ads = list(order.values())
        expected = res.get("expected")
        self.log(f"    scrolling was {'rate-limited' if res.get('rate_limited') else 'incomplete'}; "
                 f"sampled {len(ads)} of ~{expected} live from {loads + 1} first pages")
        return {"ads": ads, "status": "ok", "expected": expected, "mode": "sample",
                "complete": expected is not None and len(ads) >= 0.85 * expected}

    async def check_active(self, archive_ids: list[str]) -> dict[str, bool]:
        """Open each ad's own Ad Library page and read whether it is still live."""
        out: dict[str, bool] = {}
        if not archive_ids:
            return out
        ctx, page = await self._new_page()
        try:
            for aid in archive_ids:
                try:
                    await page.goto(f"{BASE}?id={aid}", wait_until="load", timeout=60000)
                    await page.wait_for_timeout(2500)
                    raws = [r for r in _ads_from_html(await page.content()) if str(r["ad_archive_id"]) == aid]
                    if raws:
                        out[aid] = bool(raws[0].get("is_active"))
                except Exception:
                    pass  # unknown stays unknown; it gets checked again next week
        finally:
            await ctx.close()
        return out

    async def resolve_page(self, name: str) -> dict | None:
        """Find the page ID for a brand name via keyword search: the page whose
        name best matches and which runs the most ads wins."""
        res = await self.fetch(keyword_url(name, self.country))
        want = re.sub(r"[^a-z0-9]", "", name.lower())
        counts: Counter = Counter()
        names: dict[str, str] = {}
        for ad in res["ads"]:
            pn = ad["page_name"] or ""
            norm = re.sub(r"[^a-z0-9]", "", pn.lower())
            if want and (want in norm or norm in want) and norm:
                counts[ad["page_id"]] += 1
                names[ad["page_id"]] = pn
        if not counts:
            return None
        pid, _ = counts.most_common(1)[0]
        return {"page_id": pid, "page_name": names[pid]}


def download_thumb(url: str, dest: Path, width: int = 360) -> bool:
    """Save a small JPEG thumbnail (fbcdn URLs expire, so we keep our own copy)."""
    if dest.exists():
        return True
    if not url:
        return False
    try:
        from PIL import Image
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        data = urllib.request.urlopen(req, timeout=20).read()
        im = Image.open(io.BytesIO(data)).convert("RGB")
        if im.width > width:
            im = im.resize((width, int(im.height * width / im.width)))
        dest.parent.mkdir(parents=True, exist_ok=True)
        im.save(dest, "JPEG", quality=72, optimize=True)
        return True
    except Exception:
        return False


if __name__ == "__main__":  # quick manual test: python -m radar.scrape <page_id or name>
    import sys

    async def _main():
        async with Scraper() as s:
            arg = sys.argv[1]
            pid = page_id_from(arg)
            if not pid:
                r = await s.resolve_page(arg)
                print("resolved", r)
                pid = r["page_id"]
            t = time.time()
            res = await s.fetch(page_url(pid, "IN"))
            print(res["status"], res["complete"], len(res["ads"]), f"{time.time() - t:.0f}s")
            for a in res["ads"][:5]:
                print(a["media"], a["versions"], a["body"][:70].replace("\n", " "))
    asyncio.run(_main())
