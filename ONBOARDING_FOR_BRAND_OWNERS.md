# Your own Ad Radar: setup guide

Ad Radar reads every live Meta ad your competitors are running, tags each one
the way a creative strategist would, compares it with last week, and emails you
a dashboard every Monday morning: what they started, what they killed, their
likely winners, where the white space is, and 3 tests worth briefing your team.

**It is entirely yours.** You make your own private copy. It runs on your own
GitHub account, uses your own Claude subscription, and emails your own inbox.
Your brand, your competitors and your dashboards stay in your private copy.
The person who sent you this never sees any of it.

Setup takes about 15 minutes, once. No coding needed.

**Template link:** https://github.com/fitxnerd/ad-radar

---

### Before you start, you need
- A **GitHub** account (free at github.com)
- A **Claude Pro or Max** subscription (claude.ai)
- A **Gmail** address to send the weekly email from

---

### Step 1. Make your private copy (2 minutes)
1. Open https://github.com/fitxnerd/ad-radar
2. Click the green **Use this template** button, then **Create a new repository**.
3. Name it anything, for example `ad-radar`.
4. Select **Private**. This keeps your competitive reads to yourself.
5. Click **Create repository**.

### Step 2. Connect your Claude account (5 minutes)
This is what makes it run on your own subscription.
1. On your laptop, install Node.js from [nodejs.org](https://nodejs.org) if you
   don't have it.
2. Open Terminal (Mac) or Command Prompt (Windows) and run:
   `npm install -g @anthropic-ai/claude-code`
3. Then run: `claude setup-token`
   A browser window opens. Log in with your Claude account. The terminal then
   prints a long token. Copy it.
4. In your new repo, go to **Settings → Secrets and variables → Actions → New
   repository secret**.
   - Name: `CLAUDE_CODE_OAUTH_TOKEN`
   - Secret: paste the token
   - Click **Add secret**.

### Step 3. Connect your Gmail (3 minutes)
1. Open your Google Account → **Security**. Turn on **2-Step Verification** if
   it's off.
2. Search for **App passwords** in the same page, create one called
   `Ad Radar`, and copy the 16-character code. (This is not your Gmail password.)
3. Back in your repo's **Secrets** page, add two more secrets:
   - `SMTP_USER`: your Gmail address
   - `SMTP_PASSWORD`: the 16-character code

### Step 4. Fill in the setup form (3 minutes)
1. In your repo, open the **Actions** tab. If GitHub asks, click **I understand
   my workflows, go ahead and enable them**.
2. In the left list, click **Set up Ad Radar**.
3. Click **Run workflow** on the right. A form opens:
   1. Your brand name
   2. Your brand's Meta Ad Library link *(optional)*
   3. Your category, in one line
   4. Country
   5. Competitor names, separated by commas (up to 6)
   6. Their Ad Library links *(optional, same order, separated by spaces)*
   7. Email(s) to send the dashboard to
   - Leave **Run the first report now** ticked.
4. Click the green **Run workflow** button.

After a few seconds, open the run. It shows a green ✅ **Ad Radar is set up**
summary listing your brand, competitors, and whether Claude and Gmail are
connected. If anything was wrong, it shows ❌ with exactly what to fix; fix it
and run the form again.

### That's it
Your first dashboard arrives in 20 to 40 minutes. It's the baseline week, so it
shows everything running right now. From next Monday, it arrives every Monday
at 7 AM with what changed that week.

To change competitors or emails later, just run **Set up Ad Radar** again.

---

> **Finding an Ad Library link (optional, but more precise):** open the
> [Meta Ad Library](https://www.facebook.com/ads/library/), choose your country,
> search the brand, click its **page** in the dropdown, and copy the address
> bar. Without a link, Ad Radar finds the page by name and shows you which page
> it matched in the dashboard.

### If something goes wrong
- **No email arrived:** open the **Actions** tab. A red ❌ on **Weekly Ad Radar**
  means a step failed; click it to see which. The usual cause is a typo in one of
  the three secrets.
- **A competitor looks wrong or is missing:** run the setup form again with that
  competitor's Ad Library link.
- **No Claude subscription?** Instead of Step 2, create an API key at
  [console.anthropic.com](https://console.anthropic.com) and add it as a secret
  named `ANTHROPIC_API_KEY`. That bills per use, roughly $0.10 to $0.30 a week.
