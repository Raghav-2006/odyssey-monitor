# Odyssey 70mm Showtime Monitor (Cineplex Langley)

Polls the Cineplex movie page for *The Odyssey: The IMAX Experience in 70MM* and pings your Discord the moment new showtimes appear at your chosen theatre.

Built for the opening-week ticket scramble — every 5 minutes via free GitHub Actions, or as often as you want on your own machine.

---

## What you need

- A GitHub account (free) — to host the repo and run the cron
- A Discord account + a server you control (free) — to receive notifications
- About 10 minutes

---

## Setup

### 1. Create the Discord webhook

1. In Discord, create a server (or use an existing one). On mobile or desktop.
2. **Server Settings → Integrations → Webhooks → New Webhook**
3. Name it (e.g. "Odyssey Monitor"), pick a channel, then **Copy Webhook URL**.
4. On your phone, install Discord and **turn on notifications** for that channel.

### 2. Push this folder to a new GitHub repo

```bash
cd odyssey-monitor
git init
git add .
git commit -m "initial commit"
git branch -M main
# Create an empty repo on GitHub, then:
git remote add origin git@github.com:YOUR_USERNAME/odyssey-monitor.git
git push -u origin main
```

### 3. Add your Discord webhook as a secret

On the GitHub repo page:

- **Settings → Secrets and variables → Actions → New repository secret**
- Name: `DISCORD_WEBHOOK_URL`
- Value: paste the webhook URL from step 1.

(Optionally also add **Variables** for `MOVIE_URL` and `LOCATION_KEYWORD` if you want to override the defaults without editing files.)

### 4. Enable Actions write permissions

- **Settings → Actions → General → Workflow permissions**
- Select **"Read and write permissions"** (so the bot can commit `state.json`).
- Save.

### 5. Trigger a first run

- **Actions tab → "Odyssey Showtime Monitor" → "Run workflow"**.
- Check the run logs — you should see `keyword found: True` and a parsed showtime count.
- After the first run, every subsequent run will diff against the saved state and only alert on **new** times.

That's it. You'll get a Discord ping the moment new Langley 70mm showtimes drop.

---

## Running locally (optional, for faster checks)

GitHub's cron can lag 5–15 minutes during busy hours. For tighter polling:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# edit .env and put your DISCORD_WEBHOOK_URL in

# load env and run once
set -a; source .env; set +a
python monitor.py
```

Run it on a loop with a 1-minute interval:

```bash
while true; do python monitor.py; sleep 60; done
```

Or via `cron` / `launchd` / a tiny VM (Fly.io, Hetzner, etc.).

---

## How it works

- Fetches the Cineplex page with a normal browser User-Agent.
- Finds the section containing `LOCATION_KEYWORD` ("Langley") and extracts a window of text around it.
- Pulls out date+time pairs (e.g. *"Jul 17 @ 11:00 PM"*) using regex.
- Hashes that section as a backup — even if regex parsing misses new times, any visible change to the Langley section will fire a "section changed, check manually" alert.
- Persists what it's seen in `state.json`; only **new** times trigger notifications.

## When to expect activity

Cineplex publishes showtimes by **Wednesday morning Pacific time** for the upcoming Fri–Thu week. The big drops to watch:

- The Wednesday before Odyssey's wide release (July 15, 2026) — full opening-week 70mm schedule
- Each subsequent Wednesday through the 70mm run
- Any sudden announcements from Universal/IMAX before then (these have happened — first wave of 70mm tickets dropped a full year ahead)

The monitor will catch any of these.

## Troubleshooting

- **`keyword found: False`** — the Langley theatre name isn't in the rendered HTML. Either Cineplex changed the page structure or the showtimes are loaded purely client-side. Open the page in your browser, view source (Cmd/Ctrl+U), and search for "Langley" — if it isn't there, you'll want the Playwright upgrade (see below).
- **Lots of false positives** — narrow `WINDOW_AFTER` or tighten the regex.
- **No Discord notification** — check the Action run log; if it says "would have sent", your `DISCORD_WEBHOOK_URL` secret isn't being read.

## Upgrade path: headless browser

If Cineplex moves to fully client-side rendered showtimes, swap `requests` for [Playwright](https://playwright.dev/python/):

```python
from playwright.sync_api import sync_playwright

def fetch_page(url):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(user_agent=HEADERS["User-Agent"])
        page.goto(url, wait_until="networkidle")
        html = page.content()
        browser.close()
        return html
```

Add `playwright` to `requirements.txt` and `playwright install chromium` to the Actions workflow. Same diff logic afterwards.

---

## Disclaimers

- Polls a public page at a reasonable cadence; doesn't bypass any auth or paywalls.
- GitHub Actions free tier: 2,000 minutes/month for private repos, **unlimited for public repos**. A 5-min cron uses ~5 min/run × ~8,640 runs/month ≈ way more than free private allowance, so **keep the repo public** (it contains no secrets — the webhook is in GitHub Secrets, not in code).
- This will not guarantee tickets. It will give you a head start of however long it takes between the page updating and your Discord buzzing — typically under 10 minutes with the default config.

Good luck. Buy fast.
