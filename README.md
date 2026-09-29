# Ad Radar: Monday-morning competitor creative intelligence

Every Monday at 7 AM this reads every live Meta ad your competitors are running,
tags each ad the way a creative strategist would, compares it with last week, and
emails you a dashboard you can read in 5 to 10 minutes:

- **Scoreboard:** live ads, refresh rate, concepts, ads per concept, all normalized so a 400-ad brand and a 120-ad brand compare fairly
- **Competitor snapshots:** what each brand is arguing right now, its top angles and its biggest concepts, at a glance
- **What they started:** new creatives, and which ones are genuinely a *new concept* rather than a new variant
- **What they killed:** each one labelled a failed test (under 14 days) or a fatigued winner (45+ days)
- **Likely winners:** the longest-running ads, plus Meta's own ranking by views
- **Argument map:** which arguments the category is fighting over, who leads each one, and your index against the category average, with white space (arguments nobody is making) called out
- **Formats and execution:** hooks, execution style, offers, language, per brand
- **3 tests to brief this week**, each with a hypothesis, a written-out hook and the competitor signal behind it, plus questions to ask your team

It runs for **₹0** on free infrastructure: GitHub Actions (scheduler), real Chrome
reading the public Ad Library (no Apify, no paid scraper), your existing Claude
Pro or Max plan (tagging and the written brief), and Gmail (delivery). Every
copy belongs entirely to whoever set it up.

---

## Your copy is yours

Ad Radar is shared as a GitHub **template**. When someone clicks **Use this
template**, GitHub creates a brand-new private repo in *their* account with no
link back to the original. From then on:

- **Their cloud:** the weekly job runs on their own GitHub Actions.
- **Their Claude:** tagging and the brief use their own Claude subscription.
- **Their inbox:** the dashboard is sent from and to their own email.
- **Their data:** brand, competitors, emails and every dashboard live only in
  their private repo. The person who shared the template never sees any of it,
  and neither does anyone else.

The template itself holds only code: `data/` and `reports/` are git-ignored in
it, so nobody's results ever ship with it.

The only outside services involved are the ones any run needs: Meta's public Ad
Library (read), the owner's own Claude account (tagging), and the owner's own
Gmail (sending).

---

## Setup (about 15 minutes, once)

Send **[ONBOARDING_FOR_BRAND_OWNERS.md](ONBOARDING_FOR_BRAND_OWNERS.md)** to
whoever is setting it up. It is written for someone with no GitHub or coding
background. In short:

1. **Make your copy.** Click **Use this template → Create a new repository**, and
   set it to **Private**.
2. **Add three secrets** under **Settings → Secrets and variables → Actions**:

   | Secret | How to get it |
   |---|---|
   | `CLAUDE_CODE_OAUTH_TOKEN` | Install Claude Code (`npm i -g @anthropic-ai/claude-code`), run `claude setup-token`, log in with your own Claude Pro or Max account, and paste the token it prints. |
   | `SMTP_USER` | The Gmail address that sends the email. |
   | `SMTP_PASSWORD` | A Gmail **app password**: Google Account → Security → 2-Step Verification → App passwords. 16 characters, not your normal password. |

3. **Fill in the setup form.** **Actions → Set up Ad Radar → Run workflow**. GitHub
   shows a form: your brand, its Ad Library link (optional), category, country,
   up to 6 competitors, and the emails to send the dashboard to. Click **Run
   workflow**. It checks your answers, saves them to `clients/my-brand.yaml`,
   confirms which secrets are connected, and starts the first report.
4. **Wait for the first email** (20 to 40 minutes). That first run is the
   baseline; from the next Monday, every email shows what changed that week.

To change competitors or emails later, run **Set up Ad Radar** again. It
replaces the previous answers.

> **Tip for precision:** open [the Ad Library](https://www.facebook.com/ads/library/),
> search a brand, click its **page**, and copy the link into the form. With only a
> name, Ad Radar looks the page up itself, and the dashboard shows which page it
> matched, so a wrong match is easy to spot.

### Sharing it

Push this project to GitHub as a **public** repo (it contains only code), then
in **Settings → General** tick **Template repository**. Send people the repo
link together with **ONBOARDING_FOR_BRAND_OWNERS.md**. Each person who follows
it ends up with a fully separate copy: five people, five private repos, five
sets of competitors, five inboxes, and no shared data.

### How much does it cost them?

Nothing extra. The job runs on the free GitHub Actions minutes of their own
account and their existing Claude Pro or Max plan. One brand a week sits well
within a Pro plan. Someone without a Claude subscription can instead add an
`ANTHROPIC_API_KEY` secret from console.anthropic.com, which bills per use,
roughly $0.10 to $0.30 per week for one brand.

---

## How it works

```
Monday 07:00 IST  GitHub Actions wakes up, in the owner's own repo
  |
  |- scrape    Real headless Chrome opens the public Ad Library for each page,
  |            scrolls to the end and collects every live ad, sorted by Meta's view rank
  |- diff      Compares against data/<brand>/state.json: new ads, killed ads, lifetimes
  |- classify  Claude (Haiku) tags only ads it has never seen: concept, angle family,
  |            hook family and hook text, execution style, offer, language.
  |            Thumbnails go as one contact-sheet image per 25 ads to save usage.
  |- analyze   Concepts, ads per concept, posture, winners, white space, mix,
  |            all normalized to each brand's own ad count
  |- brief     Claude (Sonnet) writes the headline, the so-whats, 3 tests, team questions
  |- render    One self-contained HTML dashboard (thumbnails embedded, works offline)
  |- email     Summary in the body plus the full dashboard attached
  `- commit    state saved back to the repo, which is what powers next week's diff
```

The taxonomy is in [radar/taxonomy.py](radar/taxonomy.py). It comes from the
Creative System framework (concept vs variant, the angle library, hook families,
the offer as a variable), so it can be extended in one place. Funnel stage
(TOF/MOF/BOF) is deliberately not tagged: it depends on each brand's own funnel,
so it does not compare across brands.

## Knobs (optional)

Set these under **Settings → Secrets and variables → Actions → Variables**, or as env vars locally:

| Variable | Default | Meaning |
|---|---|---|
| `CLASSIFY_MODEL` | `haiku` | Model that tags ads |
| `BRIEF_MODEL` | `sonnet` | Model that writes the brief |
| `MAX_ADS_PER_BRAND` | `400` | Stop scrolling a page after this many ads |
| `MAX_CLASSIFY_PER_BRAND` | `250` | New ads tagged per brand per week, this week's and long-running ads first; the rest carry over |
| `CLAUDE_PARALLEL` | `3` | Brands tagged at once (each Claude call takes a minute or two) |
| `KILL_CHECKS_PER_BRAND` | `25` | In sample mode, how many missing ads get their own page checked for "switched off" each week |

## Running locally
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chrome
python run.py clients/my-brand.yaml --no-email            # writes reports/<brand>/latest.html
python run.py clients/my-brand.yaml --no-email --rerender # rebuild the page only, no scraping or Claude calls
```
Requires Google Chrome and a logged-in `claude` CLI. If Meta ever starts blocking
GitHub's servers, `scripts/schedule_on_mac.sh` schedules the same run on your Mac
every Monday at 08:00.

## Honest limits
- **On cloud servers Meta limits how much of a list can be read.** Scrolling for more
  ads is rate-limited for GitHub's servers, so there Ad Radar reads a **sample**: each
  brand's newest ads and most viewed ads, overall and per format (typically 40 to 50%
  of a brand's live ads, and all of its newest launches). Live counts still come from
  Meta's own "~N results", and a kill is only reported once the ad's own page confirms
  it is off. Brands read this way are marked * in the dashboard. On a home connection
  (see **Running locally**) the full list is read.
- **No spend or ROAS.** Meta does not publish them for commercial ads in India.
  "Winner" means long-running and high on Meta's own ranking by views. That is a
  strong proxy, not ground truth.
- **Video is read from its thumbnail and copy**, not watched. The hook text for
  videos is Claude's best read of the opening frame and caption.
- **Scraping the public Ad Library is unofficial.** Meta can change the page and
  break it (fix in `radar/scrape.py`), and automated collection is a grey area
  under Meta's terms. Keep the volume modest, as this tool does: one visit per
  brand per week.
