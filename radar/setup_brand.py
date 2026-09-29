"""Turn the "Set up Ad Radar" form (a GitHub workflow_dispatch form) into this
repo's brand config.

One copy of this repo = one brand. Everything typed into the form stays in the
owner's own private repo: it is written to clients/my-brand.yaml and nowhere else.

Inputs arrive as environment variables (never interpolated into shell code):
    BRAND_NAME, BRAND_AD_LIBRARY, CATEGORY, COUNTRY, COMPETITORS,
    COMPETITOR_URLS, EMAILS, HAS_CLAUDE, HAS_SMTP
Writes a Markdown report to $GITHUB_STEP_SUMMARY when running in Actions.
Exit code 1 on invalid input, so the run shows red and nothing is committed.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CLIENTS = ROOT / "clients"
TARGET = "my-brand.yaml"
MARKER = "# Written by the \"Set up Ad Radar\" form. Run the form again to change it.\n"
MAX_COMPETITORS = 6
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def split_list(raw: str) -> list[str]:
    return [p.strip() for p in re.split(r"[,;\n]+", raw or "") if p.strip()]


def build(env: dict) -> tuple[dict, list[str]]:
    """Validate the form. Returns (config, errors)."""
    errors = []
    brand = (env.get("BRAND_NAME") or "").strip()
    if not brand:
        errors.append("**Brand name** is empty.")

    names = split_list(env.get("COMPETITORS", ""))
    urls = [u for u in re.split(r"[\s,;]+", env.get("COMPETITOR_URLS") or "") if u]
    if not names:
        errors.append("Add at least one **competitor**, separated by commas.")
    if len(names) > MAX_COMPETITORS:
        errors.append(f"Up to {MAX_COMPETITORS} competitors are supported; you entered {len(names)}.")
    if urls and len(urls) != len(names):
        errors.append(f"You gave {len(names)} competitor names but {len(urls)} Ad Library URLs. "
                      "Give one URL per competitor, in the same order, or leave the URL box empty.")
    for u in urls + ([env["BRAND_AD_LIBRARY"].strip()] if (env.get("BRAND_AD_LIBRARY") or "").strip() else []):
        if not re.match(r"^https?://(www\.)?facebook\.com/ads/library/", u):
            errors.append(f"`{u[:80]}` is not a Meta Ad Library link (it should start with facebook.com/ads/library/).")

    emails = [e for e in re.split(r"[\s,;]+", env.get("EMAILS") or "") if e]
    if not emails:
        errors.append("Add at least one **email** to send the Monday dashboard to.")
    for e in emails:
        if not EMAIL_RE.match(e):
            errors.append(f"`{e}` does not look like an email address.")

    country = (env.get("COUNTRY") or "IN").strip().upper()[:2] or "IN"
    cfg = {
        "slug": slug(brand) or "my-brand",
        "brand": {"name": brand, "ad_library": (env.get("BRAND_AD_LIBRARY") or "").strip()},
        "category": (env.get("CATEGORY") or "").strip(),
        "country": country,
        "competitors": [{"name": n, "ad_library": urls[i] if i < len(urls) else ""}
                        for i, n in enumerate(names[:MAX_COMPETITORS])],
        "emails": emails,
    }
    return cfg, errors


def write(cfg: dict) -> Path:
    CLIENTS.mkdir(exist_ok=True)
    # One copy = one brand: drop any config an earlier run of this form wrote.
    for p in CLIENTS.glob("*.yaml"):
        if p.name != TARGET and p.read_text().startswith(MARKER):
            p.unlink()
    path = CLIENTS / TARGET
    path.write_text(MARKER + yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True))
    return path


def summary(cfg: dict, errors: list[str], has_claude: bool, has_smtp: bool) -> str:
    if errors:
        return ("## ❌ Setup not saved\n\nFix these and run **Set up Ad Radar** again:\n\n"
                + "\n".join(f"- {e}" for e in errors) + "\n")
    comp_rows = "\n".join(f"| {c['name']} | {'linked' if c['ad_library'] else 'looked up by name'} |"
                          for c in cfg["competitors"])
    lines = [
        "## ✅ Ad Radar is set up",
        "",
        f"**Brand:** {cfg['brand']['name']}  ",
        f"**Category:** {cfg['category'] or 'not given'}  ",
        f"**Country:** {cfg['country']}  ",
        f"**Dashboard goes to:** {', '.join(cfg['emails'])}",
        "",
        "| Competitor | Ad Library page |",
        "|---|---|",
        comp_rows,
        "",
        "### Secrets",
        f"- Claude account: {'✅ connected' if has_claude else '❌ missing, add `CLAUDE_CODE_OAUTH_TOKEN`'}",
        f"- Gmail: {'✅ connected' if has_smtp else '❌ missing, add `SMTP_USER` and `SMTP_PASSWORD`'}",
        "",
    ]
    if has_claude and has_smtp:
        lines.append("Every Monday at 7 AM IST this repo will email the dashboard. "
                     "If you ticked **Run the first report now**, it has already started: see the Actions tab.")
    else:
        lines.append("Add the missing secrets under **Settings → Secrets and variables → Actions**, "
                     "then run **Weekly Ad Radar** once from the Actions tab.")
    return "\n".join(lines) + "\n"


def main():
    env = dict(os.environ)
    cfg, errors = build(env)
    has_claude = env.get("HAS_CLAUDE") == "true"
    has_smtp = env.get("HAS_SMTP") == "true"
    report = summary(cfg, errors, has_claude, has_smtp)
    print(report)
    if env.get("GITHUB_STEP_SUMMARY"):
        with open(env["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write(report)
    if errors:
        sys.exit(1)
    path = write(cfg)
    print(f"Wrote {path.relative_to(ROOT)}")
    if env.get("GITHUB_OUTPUT"):
        with open(env["GITHUB_OUTPUT"], "a") as f:
            f.write(f"ready={'true' if has_claude and has_smtp else 'false'}\n")


if __name__ == "__main__":
    main()
