"""Render the self-contained dashboard (thumbnails inlined) and the email body."""
from __future__ import annotations

import base64
import re
from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import taxonomy

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"

MEDIA_ORDER = ["static", "video", "carousel", "catalog"]


def _env(thumbs_dir: Path) -> Environment:
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html", "j2"]))
    cache: dict[str, str] = {}

    def thumb(key: str) -> str:
        if key not in cache:
            p = thumbs_dir / f"{key}.jpg"
            cache[key] = ("data:image/jpeg;base64," + base64.b64encode(p.read_bytes()).decode()) if p.exists() else ""
        return cache[key]

    env.globals.update(thumb=thumb, label=taxonomy.label, MEDIA_ORDER=MEDIA_ORDER,
                       angle_desc=lambda k: taxonomy.ANGLE_FAMILIES.get(k, ""))
    env.filters["pct"] = lambda v: f"{round((v or 0) * 100)}%"
    env.filters["nice_date"] = lambda s: date.fromisoformat(s).strftime("%-d %b %Y")
    env.filters["short_date"] = lambda s: date.fromisoformat(s).strftime("%-d %b")
    env.filters["tag"] = lambda a, f, d="": (a.get("tags") or {}).get(f, d)
    return env


def dedash(html: str) -> str:
    """House style: no em/en dashes anywhere. Ranges become 'to', breaks become commas."""
    html = re.sub(r"(\d)\s*[\u2013\u2014]\s*(\d)", r"\1 to \2", html)
    return re.sub(r"\s*[\u2013\u2014]\s*", ", ", html)


def sparkline(points: list[tuple[str, int]], w: int = 84, h: int = 22) -> str:
    if len(points) < 2:
        return ""
    vals = [v for _, v in points]
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1
    step = w / (len(vals) - 1)
    xy = [(i * step, h - 3 - (v - lo) / span * (h - 6)) for i, v in enumerate(vals)]
    d = " ".join(f"{'M' if i == 0 else 'L'}{x:.1f},{y:.1f}" for i, (x, y) in enumerate(xy))
    lx, ly = xy[-1]
    tip = ", ".join(f"{d_}: {v}" for d_, v in points[-6:])
    return (f'<svg class="spark" viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img" aria-label="Active ads trend: {tip}">'
            f'<title>{tip}</title><path d="{d}" fill="none" stroke="var(--series-1)" stroke-width="2" '
            f'stroke-linecap="round" stroke-linejoin="round"/><circle cx="{lx:.1f}" cy="{ly:.1f}" r="3" '
            f'fill="var(--series-1)" stroke="var(--surface-1)" stroke-width="2"/></svg>')


def dashboard(ctx: dict, thumbs_dir: Path) -> str:
    env = _env(thumbs_dir)
    env.globals["sparkline"] = sparkline
    return dedash(env.get_template("dashboard.html.j2").render(**ctx))


def email(ctx: dict, thumbs_dir: Path) -> str:
    return dedash(_env(thumbs_dir).get_template("email.html.j2").render(**ctx))
