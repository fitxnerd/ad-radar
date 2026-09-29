"""Tag each ad with concept, angle, hook, style, offer, language.

Concept vs variant (the core distinction of the session): a *concept* is the
argument/hypothesis, a *variant* is an execution of it. We keep a per-brand
concept registry so the same concept keeps the same name week after week --
that is what makes "they launched a NEW concept" vs "they added variants"
detectable.

Cost control, because this runs on a Pro plan:
  - only ads never classified before are sent;
  - ads with identical copy are classified once (they are variants anyway);
  - each batch's thumbnails go as ONE numbered contact sheet image.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import taxonomy
from .llm import ask_json

BATCH = 25
TILE = 220


def copy_key(ad: dict) -> str:
    txt = f"{ad.get('body', '')}|{ad.get('title', '')}".lower()
    return re.sub(r"[^a-z0-9ऀ-ॿ]+", " ", txt).strip()[:400] or f"__{ad['key']}"


def contact_sheet(items: list[tuple[int, Path | None]], dest: Path) -> Path | None:
    from PIL import Image, ImageDraw
    cols = 5
    rows = (len(items) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * TILE, rows * (TILE + 28)), "white")
    draw = ImageDraw.Draw(sheet)
    any_img = False
    for i, (num, path) in enumerate(items):
        x, y = (i % cols) * TILE, (i // cols) * (TILE + 28)
        draw.rectangle([x, y, x + TILE - 1, y + 27], fill="black")
        draw.text((x + 8, y + 7), f"#{num}", fill="white")
        if path and path.exists():
            im = Image.open(path)
            im.thumbnail((TILE - 4, TILE - 4))
            sheet.paste(im, (x + 2, y + 30))
            any_img = True
        else:
            draw.text((x + 10, y + 100), "(no image)", fill="gray")
    if not any_img:
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(dest, "JPEG", quality=80)
    return dest


def _describe(num: int, ad: dict, dupes: int) -> str:
    parts = [f"#{num} | format={ad['media']} ({ad['display_format']}) | live since {ad.get('start_str', '?')}"]
    if dupes > 1:
        parts.append(f"  ({dupes} creatives share this exact copy)")
    if ad.get("body"):
        parts.append(f"  copy: {ad['body'][:600]!r}")
    if ad.get("title") and "{{" not in ad["title"]:
        parts.append(f"  headline: {ad['title']!r}")
    if ad.get("card_titles"):
        parts.append(f"  cards: {ad['card_titles'][:4]}")
    if ad.get("cta"):
        parts.append(f"  cta: {ad['cta']}")
    return "\n".join(parts)


PROMPT = """Brand: {brand}
These are this brand's currently running Meta ads (India). Tag every ad.

EXISTING CONCEPTS for this brand (reuse the exact name when an ad makes the same argument):
{concepts}

A CONCEPT is the underlying argument/hypothesis (e.g. "Rosemary oil stops hairfall in 8 weeks",
"Cheaper than salon keratin"). Different hooks, creators, lengths, formats or products making the
SAME argument are VARIANTS of one concept. Name concepts in 3-7 words, specific to this brand's
argument (not generic like "Product promo"). Create a new concept only if no existing one fits.

Taxonomy:
{taxonomy}
{sheet_note}
ADS:
{ads}

Return JSON: {{"ads": [{{"n": <number>, "concept": "<name>", "concept_is_new": <bool>,
"concept_desc": "<one line, only if new>", "angle_family": "...", "hook_family": "...",
"hook_text": "<the opening line/frame as the viewer meets it, <=15 words>",
"summary": "<the argument in <=15 words>",
"creative_style": "...", "offer_type": "...", "offer_text": "<e.g. 'Flat 25% off' or ''>",
"product": "<product/category featured, <=4 words>", "language": "..."}}, ...]}}
One entry per ad number, in order."""


def classify_page(brand: str, ads: list[dict], concepts: list[dict], workdir: Path,
                  thumbs_dir: Path, model: str, log=print) -> None:
    """Classify `ads` in place (adds ad['tags']) and append new concepts to `concepts`."""
    groups: dict[str, list[dict]] = {}
    for ad in ads:
        groups.setdefault(copy_key(ad), []).append(ad)
    reps = [(g[0], g) for g in groups.values()]
    log(f"    {len(ads)} ads -> {len(reps)} unique copies -> {(len(reps) + BATCH - 1) // BATCH} Claude call(s)")

    for b in range(0, len(reps), BATCH):
        batch = reps[b:b + BATCH]
        sheet = contact_sheet(
            [(i + 1, thumbs_dir / f"{rep['key']}.jpg") for i, (rep, _) in enumerate(batch)],
            workdir / "contact_sheet.jpg")
        sheet_note = (f"\nFirst use the Read tool on the image {sheet.name} -- a contact sheet whose "
                      "tile numbers match the ad numbers below. Use the visuals for format, style, "
                      "hook and on-image text.\n") if sheet else ""
        concept_lines = "\n".join(f"- {c['name']}: {c.get('desc', '')}" for c in concepts) or "(none yet)"
        prompt = PROMPT.format(
            brand=brand, concepts=concept_lines, taxonomy=taxonomy.prompt_block(),
            sheet_note=sheet_note,
            ads="\n\n".join(_describe(i + 1, rep, len(g)) for i, (rep, g) in enumerate(batch)))
        out = ask_json(prompt, model=model, cwd=str(workdir), allow_read=bool(sheet))
        rows = out.get("ads", out) if isinstance(out, dict) else out
        by_n = {int(r.get("n", 0)): r for r in rows if isinstance(r, dict)}
        known = {c["name"].lower() for c in concepts}
        for i, (rep, group) in enumerate(batch):
            r = by_n.get(i + 1)
            if not r:
                continue
            tags = _clean(r)
            if tags["concept"].lower() not in known:
                concepts.append({"name": tags["concept"], "desc": r.get("concept_desc", ""),
                                 "angle_family": tags["angle_family"]})
                known.add(tags["concept"].lower())
            for ad in group:
                ad["tags"] = dict(tags)
        log(f"    batch {b // BATCH + 1}: tagged {len(by_n)}/{len(batch)}")


def _clean(r: dict) -> dict:
    def pick(v, allowed, default):
        return v if v in allowed else default
    return {
        "concept": (r.get("concept") or "One-off / unclear").strip()[:80],
        "angle_family": pick(r.get("angle_family"), taxonomy.ANGLE_FAMILIES, "brand_lifestyle"),
        "hook_family": pick(r.get("hook_family"), taxonomy.HOOK_FAMILIES, "product_hero"),
        "hook_text": (r.get("hook_text") or "")[:140],
        "summary": (r.get("summary") or "")[:160],
        "creative_style": pick(r.get("creative_style"), taxonomy.CREATIVE_STYLES, "other"),
        "offer_type": pick(r.get("offer_type"), taxonomy.OFFER_TYPES, "none"),
        "offer_text": (r.get("offer_text") or "")[:80],
        "product": (r.get("product") or "")[:60],
        "language": pick(r.get("language"), taxonomy.LANGUAGES, "english"),
    }


BRIEF_PROMPT = """You are writing the Monday-morning competitor creative brief for {brand}'s growth lead.
Category: {category}. They will skim it in 5 minutes, then brief their team. Clarity beats completeness.

Principles you must apply (from the creative-strategy playbook):
- Read ARGUMENTS, not executions. Concepts are hypotheses; variants are executions.
- Days live is the winner signal (nobody funds a loser for months); Meta's impression rank is the second.
  Say "likely winner", never claim to know their ROAS.
- Brands run very different ad volumes. Compare them on NORMALIZED numbers (shares of their own ads,
  refresh rate = new/live, ads per concept), never on raw counts alone.
- A killed ad teaches as much as a live one: killed in under 14 days = failed test; after 45+ days = fatigued winner.
- The output is a hypothesis list, not a copy list. Never suggest copying an ad.

This week's computed data (JSON):
{data}

Writing rules: plain English, short sentences, one idea per line. Never use em dashes or en dashes
(use commas or full stops). Never write snake_case keys in prose; say "Objection handling",
"Proof & efficacy". Round percentages to whole numbers.

Return JSON:
{{"headline": "<the single most important change this week, max 20 words>",
 "so_what": ["<3 or 4 bullets, max 16 words each, each naming a brand and a number>"],
 "competitors": [{{"name": "<every brand in the data, including {brand} itself, name exactly as given>", "read": "<what their creative strategy is doing now, max 16 words>",
                  "posture": "<2-3 words, e.g. Systematic tester, Offer-led push, Few big bets>"}}],
 "white_space": [{{"angle": "<angle key>", "why": "<why it is an opening for {brand}, max 14 words>"}}],
 "tests": [{{"hypothesis": "<We believe X because Y, max 20 words>", "angle_family": "<key>",
            "concept": "<3-6 words>", "hook": "<the on-screen hook, max 12 words>",
            "format": "<e.g. 9:16 UGC video>", "evidence": "<the competitor signal behind it, max 14 words>"}}],
 "ask_your_team": ["<3 questions, max 16 words each>"]}}
Give exactly 3 tests and 2 or 3 white_space items."""


def write_brief(brand: str, category: str, data: dict, model: str):
    return ask_json(BRIEF_PROMPT.format(brand=brand, category=category or "D2C",
                                        data=json.dumps(data, ensure_ascii=False)[:60000]),
                    model=model, timeout=900)
