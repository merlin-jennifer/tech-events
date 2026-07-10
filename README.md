# Tech Events Tracker 🎟️

A tiny website that **automatically finds upcoming hackathons and tech/startup
events for your city every day** and publishes them as a free web page — all
hosted on GitHub, no server and no monthly bill.

You do **not** need to know how to code to set this up. Follow the steps below
and copy-paste exactly.

---

## How it works (30-second version)

1. **GitHub Actions** (a free robot built into GitHub) wakes up once a day.
2. It runs `build.py`, which pulls hackathons from **Devpost** and general
   tech/startup meetups, mixers, and demo days from **Luma**, **Eventbrite**,
   and **Meetup** for the city you chose in `config.json` — plus any specific
   organizer calendars you've hand-picked (see `extra_luma_calendars` below).
3. It keeps the ones matching your interests and rebuilds `index.html`.
4. **GitHub Pages** serves `index.html` as a real webpage you can bookmark.

```
                          ┌────────────┐
                    ┌────▶│  Devpost   │
                    │     └────────────┘
                    │     ┌────────────┐
 ┌─────────────┐    ├────▶│    Luma    │
 │GitHub Actions│───▶     └────────────┘
 └─────────────┘    │     ┌────────────┐
                    ├────▶│ Eventbrite │
                    │     └────────────┘
                    │     ┌────────────┐
                    └────▶│   Meetup   │
                          └────────────┘
                                │ writes
                                ▼
                          index.html  ──▶  GitHub Pages (your website)
```

---

## What's in this folder

| File | What it does | Do you edit it? |
|------|--------------|-----------------|
| `config.json` | Your city, interests, page title | ✅ **Yes — this is the only file you need to touch** |
| `build.py` | The program that fetches events and builds the page | ❌ No |
| `index.html` | The finished web page (auto-overwritten each run) | ❌ No |
| `requirements.txt` | Lists the libraries the program needs | ❌ No |
| `.github/workflows/update-events.yml` | The daily-schedule robot | ❌ No |

### Editing `config.json`

```json
{
  "city": "San Francisco",
  "keywords": ["ai", "startup", "web3", "fintech", "hardware", "climate"],
  "site_title": "Tech Events near me",
  "site_subtitle": "Hackathons, tech & startup events, updated daily",
  "repo_url": "https://github.com/YOUR-USERNAME/YOUR-REPO",
  "max_pages": 6,
  "luma_max_events": 80,
  "eventbrite_max_pages": 3,
  "extra_luma_calendars": [],
  "require_keyword_match": false
}
```

- **city** — your city name (e.g. `"Bangalore"`, `"London"`, `"Austin"`).
  Common alt-spellings (`"NYC"`, `"Bangalore"`, `"SF"`, `"Bay Area"`...) are
  recognized. If your city name is ambiguous across countries (there's a
  London, Ontario *and* a London, England), disambiguate with
  `"London, UK"` or `"Portland, OR"` — the part after the comma is only used
  to break ties on Eventbrite, which indexes ~1,000 cities worldwide.
- **keywords** — topics you care about. For Devpost, only used when
  `require_keyword_match` is `true`. For **Luma, Eventbrite, and Meetup,
  keywords are always applied** (plus a built-in list of generic tech/startup
  terms) — those are general local-events feeds, so without keyword
  narrowing you'd get book clubs and run clubs mixed in with hackathons.
- **require_keyword_match** — `false` (default) shows **all** upcoming
  Devpost hackathons for your city, narrowed only for the other three sources
  (see above). Set it to `true` to also narrow Devpost to just your keywords.
- **luma_max_events** — how many Luma events to fetch before filtering
  (default 80). Raise it if your city has a lot of events and you're missing
  ones further out; lower it to speed up the build.
- **eventbrite_max_pages** — how many pages (20 events each) to fetch from
  Eventbrite's "tech" category for your city (default 3, so up to 60).
- **repo_url** — shows a "Go to my GitHub repo to find events for your
  city" banner at the top of the page linking here, so people who land on
  your site can fork it for their own city. Leave it out (or empty) to hide
  the banner.
- **extra_luma_calendars** — a list of specific Luma calendar slugs you
  already follow — see "Tracking specific organizers" below.

---

## Tracking specific organizers, coworking spaces, and connectors

Every city has a handful of "connectors" who run recurring dinners, panels,
and demo nights, plus coworking spaces and incubators that host their own
event series. The city-wide sources above will pick up *some* of these, but
the reliable way to never miss one is to follow their calendar directly:

1. Find their public Luma page (many hosts — coworking spaces, accelerators,
   YC-style demo nights, "AI Engineers" meetup chapters, etc. — run their
   whole event series on Luma). The URL looks like `lu.ma/<something>`.
2. Add the `<something>` part to `extra_luma_calendars` in `config.json`, e.g.:
   ```json
   "extra_luma_calendars": ["sf-hardware-meetup", "sfaiengineers"]
   ```
3. Every event from that calendar shows up on your page — unlike the city
   feeds, these aren't keyword-filtered, since you already picked the source
   yourself.

This is also how to plug in a university or alumni association's event
series, if it publishes one on Luma. If it only publishes on its own website
or a members-only mailing list, that's outside what any scraper can reach —
you'd still need to be on that list.

---

## Setup, step by step (about 10 minutes)

### 1. Create a free GitHub account
Go to <https://github.com> and sign up if you don't have an account.

### 2. Create a new repository
- Click the **+** in the top-right → **New repository**.
- Name it something like `my-events`.
- Choose **Public** (required for free GitHub Pages).
- Click **Create repository**.

### 3. Upload these files
- On your new empty repo page, click **“uploading an existing file”**.
- Drag in **all** the files from this folder, **including the `.github` folder**.
  - ⚠️ If dragging the `.github` folder is tricky, see the note at the bottom.
- Click **Commit changes**.

### 4. Let the robot write to your repo
- Go to **Settings → Actions → General**.
- Scroll to **Workflow permissions**.
- Select **“Read and write permissions”** → **Save**.

### 5. Turn on GitHub Pages
- Go to **Settings → Pages**.
- Under **Source**, choose **Deploy from a branch**.
- Branch: **main**, folder: **/ (root)** → **Save**.
- After a minute, this page shows your website address, like
  `https://YOUR-USERNAME.github.io/my-events/`.

### 6. Run it once now (don't wait a day)
- Go to the **Actions** tab.
- Click **“Update events”** on the left → **Run workflow** → **Run workflow**.
- Wait ~1 minute for the green check.
- Open your GitHub Pages address — your events are live! 🎉

From now on it refreshes itself every day automatically.

---

## Common questions

**How do I change my city later?**
Edit `config.json` on GitHub (click the file → the pencil ✏️ icon → change the
text → Commit). Then run the workflow again from the Actions tab, or just wait
for the next daily run.

**What time does it update?**
Once a day at 13:00 UTC. To change it, edit the `cron` line in
`.github/workflows/update-events.yml`. (`"0 13 * * *"` = 13:00 UTC daily.)

**It says no events found.**
Try broadening: fewer/empty `keywords`, or a larger nearby city name (e.g. a
metro area instead of a suburb).

---

## Honest limitations (worth knowing)

- **Sources:** **Devpost** (hackathons), **Luma**, **Eventbrite**, and
  **Meetup** (general tech/startup meetups, mixers, demo days). All four are
  free and keyless — none require an account or API key — but none of them
  have an official public API contract for the endpoints this project uses
  (we read the same JSON their own web pages embed, not a documented
  developer API), so any of them could change format without notice.
  `build.py` is structured so another source can be added later — copy the
  `fetch_devpost` / `fetch_luma` pattern.
- **Luma's city coverage is a fixed list of ~80 major cities** (San
  Francisco, NYC, London, Bengaluru, Tokyo, etc. — see `get_luma_places()`
  for the full list). **Eventbrite covers ~1,000 cities** worldwide and often
  fills the gap for smaller cities Luma doesn't have. If neither covers your
  city, you'll still get Devpost hackathons; the build won't fail, it just
  prints a note for whichever source came up empty.
- **Meetup is capped to whatever its search page returns publicly**
  (typically 10-20 events) — deeper pagination needs an authenticated GraphQL
  call we intentionally don't reverse-engineer further, since it starts
  needing session cookies/tokens that are fragile and not meant for
  unauthenticated use.
- **Eventbrite occasionally surfaces spam/duplicate listings** — a small
  number of self-serve "trade show" ads get reposted across many cities with
  mistagged addresses (you might see the same conference "in" a city that
  clearly isn't its real location). This is an Eventbrite platform issue, not
  a bug here; we don't try to filter it out because the only reliable signal
  (mismatched address text) would also risk dropping legitimate multi-city or
  hybrid events.
- **Accuracy:** Event data (dates, locations, prizes) comes straight from
  these sites and is only as current as they are. Always click through to
  the event page before making plans.
- **All sources fail gracefully.** If any of them changes its response shape
  or is briefly unreachable, that source is skipped for the run (logged to
  the Action's output) rather than breaking the whole page.
- **Instagram and TikTok are not scraped, on purpose.** Both platforms
  require a logged-in session to browse content and aggressively rate-limit
  or ban scraping — there's no keyless, public, stable way to pull "tech
  events near me" from them without violating their terms of service and
  risking account/IP bans. If you spot an event going viral on social that
  isn't showing up here, the practical bridge is: most organizers who post on
  Instagram/TikTok also run their actual RSVP flow through Luma — check for
  that and add it to `extra_luma_calendars`. (Eventbrite's organizer pages
  don't expose the same scrapeable data as their search pages do, so that
  path isn't available the same way.)

---

## Want to go further?
This is a great candidate for turning into a reusable Claude Skill — if you find
yourself tweaking it often, ask Claude to package the setup steps as a skill so
future edits are one command. You could also add email/Slack notifications when
a new matching event appears.

<sub>Note for step 3: GitHub's drag-and-drop sometimes flattens folders. If the
`.github/workflows/update-events.yml` path gets lost, use **Add file → Create new
file**, type `.github/workflows/update-events.yml` as the name (the slashes make
the folders), and paste the file's contents.</sub>
