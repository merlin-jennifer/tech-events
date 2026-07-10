#!/usr/bin/env python3
"""
Fetches tech / hackathon / startup events for your city and builds a web page
(index.html) that GitHub Pages will host for you.

You almost never need to edit this file.
To change your city or interests, edit  config.json  instead.
"""

import json
import re
import html
import datetime
import unicodedata
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from dateutil import parser as dateparser

ROOT = Path(__file__).parent
CONFIG_PATH = ROOT / "config.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (event-tracker; personal use)"}

# Sources whose city feeds are general-purpose (not inherently tech/startup),
# so they always get narrowed by GENERIC_TECH_KEYWORDS + your own keywords —
# see filter_events(). Devpost (hackathons only) and your explicitly curated
# extra_luma_calendars are exempt: Devpost has no noise to begin with, and
# calendars you hand-picked are trusted as-is.
BROAD_SOURCES = {"Luma", "Eventbrite", "Meetup"}

GENERIC_TECH_KEYWORDS = [
    "tech", "startup", "startups", "founder", "founders", "venture", "vc",
    "hackathon", "hackathons", "engineer", "engineers", "engineering",
    "developer", "developers", "product", "ai", "ml",
    "machine learning", "artificial intelligence", "web3", "crypto",
    "blockchain", "saas", "software", "coding", "hacker", "hackers",
    "demo day", "pitch", "y combinator",
]

# A few common shorthands/alt-names people type as "city" that don't match
# Luma's or Eventbrite's official place names.
CITY_ALIASES = {
    "nyc": "new york",
    "new york city": "new york",
    "sf": "san francisco",
    "bay area": "san francisco",
    "la": "los angeles",
    "dc": "washington, dc",
    "washington dc": "washington, dc",
    "bangalore": "bengaluru",
    "delhi": "new delhi",
    "bombay": "mumbai",
    "saigon": "ho chi minh city",
}

# For disambiguating "City, <hint>" against Eventbrite's country/state prefix
# (e.g. "London, UK" vs the Canadian London) — Eventbrite's slugs spell out
# "united-kingdom", not the ISO code, so common shorthands need mapping.
COUNTRY_HINT_ALIASES = {
    "uk": "united kingdom",
    "england": "united kingdom",
    "scotland": "united kingdom",
    "usa": "united states",
    "us": "united states",
    "america": "united states",
    "uae": "united arab emirates",
}


def fold_accents(text):
    """'São Paulo' -> 'sao paulo', so typed input without accents still
    matches place names from Luma/Eventbrite."""
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(c for c in normalized if not unicodedata.combining(c)).lower()


def split_city_hint(raw_city):
    """'London, UK' -> ('London', 'UK'). The hint disambiguates cities that
    share a name across countries (there's a London, Ontario and a London,
    England) — only Eventbrite's city list is large enough for this to bite.
    """
    city_part, _, hint = raw_city.partition(",")
    return city_part.strip(), hint.strip()


def keyword_match(haystack, keywords):
    """Word-boundary match so short keywords like 'ai' don't fire on
    substrings inside unrelated words (e.g. 'trail', 'captain')."""
    return any(re.search(rf"\b{re.escape(k)}\b", haystack) for k in keywords if k)


# Nicer display labels for keywords that shouldn't just be .title()-cased.
CATEGORY_LABELS = {"ai": "AI", "vc": "VC", "web3": "Web3"}


def category_label(keyword):
    return CATEGORY_LABELS.get(keyword, keyword.title())


def event_categories(ev, keywords):
    """Which of your config.json keywords (plus a built-in 'hackathon'
    bucket) this event matches — powers the category filter buttons on the
    page. Reuses the same word-boundary matching as the source filters."""
    haystack = " ".join([ev["title"], " ".join(ev["themes"])]).lower()
    cats = [k for k in keywords if keyword_match(haystack, [k])]
    if ev["source"] == "Devpost" or keyword_match(haystack, ["hackathon", "hackathons"]):
        cats.append("hackathons")
    return cats


# ----------------------------------------------------------------------
# 1. Load your settings
# ----------------------------------------------------------------------
def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# ----------------------------------------------------------------------
# 2. Get events from Devpost (hackathons). No API key needed.
#    Devpost has a public JSON endpoint we can politely query.
# ----------------------------------------------------------------------
def fetch_devpost(city, max_pages=6):
    events = []
    for page in range(1, max_pages + 1):
        url = "https://devpost.com/api/hackathons"
        # Ask Devpost only for events still open or upcoming, soonest first —
        # so we don't waste pages on hackathons that already ended.
        params = {
            "search": city,
            "page": page,
            "status[]": ["upcoming", "open"],
            "order_by": "deadline",
        }
        try:
            resp = requests.get(url, params=params, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:  # network hiccup, bad page, etc.
            print(f"  ! skipped Devpost page {page}: {e}")
            continue

        batch = data.get("hackathons", [])
        if not batch:
            break

        for h in batch:
            loc = (h.get("displayed_location") or {}).get("location", "")
            themes = [t.get("name", "") for t in h.get("themes", [])]
            dates = h.get("submission_period_dates", "").strip()
            events.append(
                {
                    "source": "Devpost",
                    "title": h.get("title", "").strip(),
                    "url": h.get("url", ""),
                    "location": loc.strip(),
                    "dates": dates,
                    "sort_date": parse_devpost_date(dates),
                    "state": h.get("open_state", ""),  # upcoming / open / ended
                    "themes": themes,
                    "prize": strip_html(h.get("prize_amount", "")),
                    "organization": h.get("organization_name") or "",
                    "curated": False,
                }
            )
    return events


def parse_devpost_date(text):
    """Devpost's date field is a display string like 'Oct 03 - 04, 2026', not
    ISO, and ranges can span months/years ('Dec 01, 2026 - Jan 05, 2027'). We
    only need the *start* date, so take the first segment and, if it's
    missing a year (the common same-month-range case), borrow the year from
    the second segment. Anything we can't confidently parse (e.g. 'Ongoing')
    returns None rather than guessing.
    """
    if not text:
        return None
    first_part, _, rest = text.strip().partition(" - ")
    if not re.search(r"\d{4}", first_part) and rest:
        year_match = re.search(r"\d{4}", rest)
        if year_match:
            first_part = f"{first_part}, {year_match.group()}"
    if not re.search(r"\d{4}", first_part):
        return None
    try:
        return dateparser.parse(first_part, default=datetime.datetime(2000, 1, 1))
    except (ValueError, OverflowError):
        return None


def strip_html(text):
    """Devpost wraps prize numbers in HTML tags — clean them up."""
    if not text:
        return ""
    return re.sub(r"<[^>]+>", "", text).strip()


# ----------------------------------------------------------------------
# 3. Get events from Luma (lu.ma) — general tech/startup meetups, mixers,
#    demo days. No API key needed: lu.ma/discover embeds a JSON blob in the
#    page HTML that lists every city it covers, and its pagination API is
#    open to the public (it's what the site's own frontend calls).
# ----------------------------------------------------------------------
def get_luma_places():
    try:
        resp = requests.get("https://lu.ma/discover", headers=HEADERS, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        print(f"  ! could not load Luma's city list: {e}")
        return []

    match = re.search(
        r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', resp.text, re.S
    )
    if not match:
        print("  ! Luma discover page format changed, skipping Luma")
        return []

    try:
        data = json.loads(match.group(1))
        raw_places = data["props"]["pageProps"]["initialData"]["places"]
    except Exception as e:
        print(f"  ! could not parse Luma's city list: {e}")
        return []

    places = []
    for entry in raw_places:
        place = entry.get("place") or {}
        if place.get("slug") and place.get("api_id"):
            places.append(
                {
                    "name": place.get("name", ""),
                    "slug": place["slug"],
                    "api_id": place["api_id"],
                }
            )
    return places


def match_luma_place(city, places):
    if not city or not places:
        return None
    needle = fold_accents(city.strip())
    needle = CITY_ALIASES.get(needle, needle)
    needle_slug = re.sub(r"[^a-z0-9]+", "-", needle).strip("-")

    for p in places:
        if fold_accents(p["name"]) == needle:
            return p
    for p in places:
        if p["slug"] == needle_slug:
            return p
    for p in places:
        name_folded = fold_accents(p["name"])
        if needle in name_folded or name_folded in needle:
            return p
    return None


def _map_luma_event(ev, organization="", curated=False, now=None):
    """Shared mapping for both the city discover feed and hand-picked
    calendars — Luma returns the same event shape in both APIs."""
    start_iso = ev.get("start_at")
    if not start_iso:
        return None
    start_utc = datetime.datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
    if now and start_utc < now:
        return None

    tz_name = ev.get("timezone")
    local_start = start_utc.astimezone(ZoneInfo(tz_name)) if tz_name else start_utc
    time_str = local_start.strftime("%I:%M %p").lstrip("0")
    dates = f"{local_start.strftime('%b %d, %Y')} · {time_str}"

    geo = ev.get("geo_address_info") or {}
    if ev.get("location_type") == "virtual":
        location = "Online"
    else:
        location = geo.get("city_state") or geo.get("city") or ""

    return {
        "source": "Luma",
        "title": (ev.get("name") or "").strip(),
        "url": f"https://lu.ma/{ev.get('url', '')}",
        "location": location,
        "dates": dates,
        "sort_date": start_utc.replace(tzinfo=None),
        "state": "upcoming",
        "themes": [],
        "prize": "",
        "organization": organization,
        "curated": curated,
    }


def fetch_luma(city, max_events=80):
    places = get_luma_places()
    place = match_luma_place(city, places)
    if not place:
        print(f"  ! Luma doesn't have a discover page matching '{city}', skipping Luma")
        return []

    events = []
    cursor = ""
    now = datetime.datetime.now(datetime.timezone.utc)
    while len(events) < max_events:
        params = {
            "discover_place_api_id": place["api_id"],
            "pagination_limit": 50,
            "pagination_cursor": cursor,
        }
        try:
            resp = requests.get(
                "https://api.lu.ma/discover/get-paginated-events",
                params=params,
                headers=HEADERS,
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"  ! skipped a Luma page: {e}")
            break

        entries = data.get("entries", [])
        if not entries:
            break

        for entry in entries:
            calendar = entry.get("calendar") or {}
            mapped = _map_luma_event(
                entry.get("event") or {}, organization=calendar.get("name", ""), now=now
            )
            if mapped:
                events.append(mapped)

        if not data.get("has_more") or not data.get("next_cursor"):
            break
        cursor = data["next_cursor"]

    return events


def fetch_luma_calendar(slug):
    """Pull upcoming events from one specific Luma calendar (a coworking
    space, incubator, or 'connector' you've already found and follow) rather
    than a whole city — configure these under extra_luma_calendars."""
    try:
        resp = requests.get(f"https://lu.ma/{slug}", headers=HEADERS, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        print(f"  ! could not load Luma calendar '{slug}': {e}")
        return []

    match = re.search(
        r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', resp.text, re.S
    )
    if not match:
        print(f"  ! Luma calendar '{slug}' page format changed, skipping")
        return []

    try:
        data = json.loads(match.group(1))
        payload = data["props"]["pageProps"]["initialData"]
    except Exception as e:
        print(f"  ! could not parse Luma calendar '{slug}': {e}")
        return []

    if payload.get("kind") != "calendar":
        print(f"  ! '{slug}' isn't a Luma calendar page, skipping")
        return []

    calendar_data = payload.get("data", {})
    calendar_name = (calendar_data.get("calendar") or {}).get("name", slug)
    now = datetime.datetime.now(datetime.timezone.utc)

    events = []
    for item in calendar_data.get("featured_items", []):
        mapped = _map_luma_event(
            item.get("event") or {}, organization=calendar_name, curated=True, now=now
        )
        if mapped:
            events.append(mapped)
    return events


# ----------------------------------------------------------------------
# 4. Get events from Eventbrite's city + category search pages. No API key
#    needed: the search results page embeds a JSON blob (window.__SERVER_DATA__)
#    including the event list AND a global list of every city slug Eventbrite
#    indexes, which we use to build the URL for whatever city you configure.
# ----------------------------------------------------------------------
EVENTBRITE_BOOTSTRAP_URL = "https://www.eventbrite.com/d/ca--san-francisco/tech/"


def _parse_eventbrite_server_data(text):
    match = re.search(r"window\.__SERVER_DATA__\s*=\s*(\{.*?\});\s*\n", text, re.S)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except Exception:
        return None


def get_eventbrite_cities():
    try:
        resp = requests.get(EVENTBRITE_BOOTSTRAP_URL, headers=HEADERS, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        print(f"  ! could not load Eventbrite's city list: {e}")
        return []

    data = _parse_eventbrite_server_data(resp.text)
    if data is None:
        print("  ! Eventbrite page format changed, skipping Eventbrite")
        return []

    try:
        # Despite the name, this is Eventbrite's full ~1000-city index, not
        # just "trending" ones — it's the same list on every /d/ search page
        # regardless of the city you searched.
        raw_cities = data["trending_search_cities"]
    except Exception as e:
        print(f"  ! could not parse Eventbrite's city list: {e}")
        return []

    cities = []
    for country_code, slug in raw_cities:
        display = slug.rsplit("--", 1)[-1].replace("-", " ")
        cities.append({"country_code": country_code, "slug": slug, "display": display})
    return cities


def match_eventbrite_city(city, region_hint, cities):
    if not city or not cities:
        return None
    needle = fold_accents(city)
    needle = CITY_ALIASES.get(needle, needle)
    hint = fold_accents(region_hint) if region_hint else ""
    hint = COUNTRY_HINT_ALIASES.get(hint, hint)

    matches = [c for c in cities if fold_accents(c["display"]) == needle]
    if not matches:
        matches = [
            c
            for c in cities
            if needle in fold_accents(c["display"]) or fold_accents(c["display"]) in needle
        ]
    if not matches:
        return None
    if hint:
        for c in matches:
            # Eventbrite slugs are "{country-or-state}--{city}", e.g.
            # "united-kingdom--london" or "tx--austin" — compare the hint
            # against that prefix, spelled out, not the raw ISO country code.
            region_slug = c["slug"].rsplit("--", 1)[0].replace("-", " ")
            if hint in region_slug or region_slug in hint:
                return c
    return matches[0]


def fetch_eventbrite(city, region_hint="", max_pages=3):
    cities = get_eventbrite_cities()
    place = match_eventbrite_city(city, region_hint, cities)
    if not place:
        print(f"  ! Eventbrite doesn't cover a city matching '{city}', skipping Eventbrite")
        return []

    events = []
    for page in range(1, max_pages + 1):
        url = f"https://www.eventbrite.com/d/{place['slug']}/tech/"
        try:
            resp = requests.get(url, params={"page": page}, headers=HEADERS, timeout=30)
            resp.raise_for_status()
        except Exception as e:
            print(f"  ! skipped Eventbrite page {page}: {e}")
            break

        data = _parse_eventbrite_server_data(resp.text)
        if data is None:
            print("  ! Eventbrite page format changed, stopping early")
            break

        try:
            event_block = data["search_data"]["events"]
            results = event_block["results"]
        except Exception as e:
            print(f"  ! could not parse an Eventbrite page: {e}")
            break

        if not results:
            break

        for h in results:
            venue = h.get("primary_venue") or {}
            address = venue.get("address") or {}
            if h.get("is_online_event"):
                location = "Online"
            else:
                location = ", ".join(
                    p for p in [address.get("city"), address.get("region")] if p
                ) or venue.get("name", "")

            start_date = h.get("start_date", "")
            start_time = h.get("start_time", "")
            sort_date = None
            if start_date:
                try:
                    sort_date = dateparser.parse(f"{start_date} {start_time}".strip())
                except (ValueError, OverflowError, TypeError):
                    sort_date = None

            dates = ""
            if sort_date:
                if start_time:
                    time_str = sort_date.strftime("%I:%M %p").lstrip("0")
                    dates = f"{sort_date.strftime('%b %d, %Y')} · {time_str}"
                else:
                    dates = sort_date.strftime("%b %d, %Y")

            themes = [
                t.get("display_name", "") for t in h.get("tags", []) if t.get("display_name")
            ]

            events.append(
                {
                    "source": "Eventbrite",
                    "title": (h.get("name") or "").strip(),
                    "url": h.get("url", ""),
                    "location": location,
                    "dates": dates,
                    "sort_date": sort_date,
                    "state": "upcoming",
                    "themes": themes[:4],
                    "prize": "",
                    "organization": "",
                    "curated": False,
                }
            )

        page_count = event_block.get("pagination", {}).get("page_count", page)
        if page >= page_count:
            break

    return events


# ----------------------------------------------------------------------
# 5. Get events from Meetup's public search page (categoryId 546 = Tech).
#    No API key needed — the page server-renders results into a GraphQL
#    cache (__APOLLO_STATE__) in the page HTML. Meetup only exposes this
#    first page publicly (deeper pagination needs an authenticated GraphQL
#    call), so this is capped at whatever it returns — usually 10-20 events.
# ----------------------------------------------------------------------
MEETUP_TECH_CATEGORY_ID = "546"


def fetch_meetup(city):
    try:
        resp = requests.get(
            "https://www.meetup.com/find/",
            params={
                "location": city,
                "source": "EVENTS",
                "categoryId": MEETUP_TECH_CATEGORY_ID,
            },
            headers=HEADERS,
            timeout=30,
        )
        resp.raise_for_status()
    except Exception as e:
        print(f"  ! could not load Meetup events: {e}")
        return []

    match = re.search(
        r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', resp.text, re.S
    )
    if not match:
        print("  ! Meetup page format changed, skipping Meetup")
        return []

    try:
        data = json.loads(match.group(1))
        apollo = data["props"]["pageProps"]["__APOLLO_STATE__"]
    except Exception as e:
        print(f"  ! could not parse Meetup data: {e}")
        return []

    events = []
    now = datetime.datetime.now(datetime.timezone.utc)
    for key, obj in apollo.items():
        if not key.startswith("Event:") or not obj.get("title") or not obj.get("dateTime"):
            continue
        try:
            start = dateparser.parse(obj["dateTime"])
        except (ValueError, TypeError, OverflowError):
            continue
        if start.tzinfo is None:
            start = start.replace(tzinfo=datetime.timezone.utc)
        if start < now:
            continue

        venue = obj.get("venue") or {}
        if obj.get("eventType") == "PHYSICAL":
            location = ", ".join(p for p in [venue.get("city"), venue.get("state")] if p)
        else:
            location = "Online"

        group_ref = (obj.get("group") or {}).get("__ref")
        group = apollo.get(group_ref, {}) if group_ref else {}

        time_str = start.strftime("%I:%M %p").lstrip("0")
        dates = f"{start.strftime('%b %d, %Y')} · {time_str}"

        events.append(
            {
                "source": "Meetup",
                "title": obj["title"].strip(),
                "url": obj.get("eventUrl", ""),
                "location": location,
                "dates": dates,
                "sort_date": start.replace(tzinfo=None),
                "state": "upcoming",
                "themes": [],
                "prize": "",
                "organization": group.get("name", ""),
                "curated": False,
            }
        )
    return events


# ----------------------------------------------------------------------
# 6. Keep only the events you care about
# ----------------------------------------------------------------------
def filter_events(events, config):
    # Devpost's own search already matches events to your city (it's fuzzy and
    # covers nearby venues like "Bay Area" or a named building), so we trust it
    # for location and don't re-filter on the city name here — that would wrongly
    # drop real local events whose venue text doesn't literally say the city.
    # Luma/Eventbrite/Meetup are already scoped to your city via their own
    # location lookups.
    keywords = [k.lower() for k in config.get("keywords", [])]
    # By default we show ALL upcoming hackathons for your city. Set
    # "require_keyword_match": true in config.json to keep ONLY events that
    # match one of your keywords — this only applies to Devpost; see below
    # for the general-purpose sources (Luma/Eventbrite/Meetup).
    require_kw = config.get("require_keyword_match", False)
    # Luma/Eventbrite/Meetup city feeds are general local events (book clubs,
    # concerts, run clubs...), not inherently tech/startup, so they're always
    # narrowed by your keywords plus a built-in list of generic tech/startup
    # terms, regardless of require_keyword_match. Anything from
    # extra_luma_calendars is exempt — you already hand-picked that source.
    broad_keywords = list({*keywords, *GENERIC_TECH_KEYWORDS})

    kept = []
    seen_urls = set()
    seen_titles = set()
    for ev in events:
        # Drop anything already finished.
        if ev["state"] == "ended":
            continue

        # De-duplicate by URL, and by normalized title as a safety net for
        # the same event listed on two sources under slightly different URLs.
        if ev["url"] in seen_urls:
            continue
        title_key = re.sub(r"[^a-z0-9]+", "", ev["title"].lower())
        if title_key and title_key in seen_titles:
            continue

        haystack = " ".join(
            [ev["title"], ev["location"], " ".join(ev["themes"])]
        ).lower()

        if ev.get("curated"):
            pass  # you picked this source yourself — no narrowing
        elif ev["source"] in BROAD_SOURCES:
            if not keyword_match(haystack, broad_keywords):
                continue
        elif require_kw and keywords and not keyword_match(haystack, keywords):
            continue

        seen_urls.add(ev["url"])
        if title_key:
            seen_titles.add(title_key)
        kept.append(ev)

    # Upcoming-state events first, then soonest date, then alphabetical.
    kept.sort(
        key=lambda e: (
            e["state"] != "upcoming",
            e["sort_date"] or datetime.datetime.max,
            e["title"].lower(),
        )
    )
    return kept


# ----------------------------------------------------------------------
# 7. Turn the events into a nice web page
# ----------------------------------------------------------------------
def render_html(events, config):
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    # %Z picks PST vs PDT automatically depending on daylight saving.
    now_pt = now_utc.astimezone(ZoneInfo("America/Los_Angeles"))
    time_str = now_pt.strftime("%I:%M %p").lstrip("0")
    updated = f"{now_pt.strftime('%b %d, %Y')} at {time_str} {now_pt.strftime('%Z')}"
    title = html.escape(config.get("site_title", "Tech Events"))
    subtitle = html.escape(config.get("site_subtitle", ""))
    city = html.escape(config.get("city", ""))

    keywords = [k.lower() for k in config.get("keywords", [])]
    seen_categories = []  # keep first-seen order, only ones that actually occur

    cards = []
    for ev in events:
        themes = "".join(
            f'<span class="tag">{html.escape(t)}</span>' for t in ev["themes"][:4]
        )
        prize = (
            f'<span class="prize">💰 {html.escape(ev["prize"])}</span>'
            if ev["prize"] and ev["prize"] != "$0"
            else ""
        )
        state_label = "Upcoming" if ev["state"] == "upcoming" else "Open now"
        state_class = "upcoming" if ev["state"] == "upcoming" else "open"
        categories = event_categories(ev, keywords)
        for c in categories:
            if c not in seen_categories:
                seen_categories.append(c)
        cards.append(
            f"""
        <a class="card" data-categories="{html.escape(' '.join(categories))}" href="{html.escape(ev['url'])}" target="_blank" rel="noopener">
          <div class="card-top">
            <span class="state {state_class}">{state_label}</span>
            <span class="src">{html.escape(ev['source'])}</span>
          </div>
          <h2>{html.escape(ev['title'])}</h2>
          <p class="meta">📍 {html.escape(ev['location'] or 'Location TBA')}</p>
          <p class="meta">🗓️ {html.escape(ev['dates'] or 'Dates TBA')}</p>
          <div class="tags">{themes}</div>
          {prize}
        </a>"""
        )

    if not cards:
        cards.append(
            '<p class="empty">No matching upcoming events found right now. '
            "Try broadening your keywords or city in <code>config.json</code>.</p>"
        )

    filter_buttons = "".join(
        f'<button class="filter-btn" data-filter="{html.escape(c)}">{html.escape(category_label(c))}</button>'
        for c in seen_categories
    )
    filters_bar = (
        f"""
  <div class="filters">
    <button class="filter-btn active" data-filter="all">All</button>
    {filter_buttons}
  </div>"""
        if seen_categories
        else ""
    )

    count = len([e for e in events])
    repo_url = config.get("repo_url", "")
    repo_banner = (
        f"""
  <div class="topbar">
    <a href="{html.escape(repo_url)}" target="_blank" rel="noopener">
      🚀 Go to my GitHub repo to find events for your city
    </a>
  </div>"""
        if repo_url
        else ""
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  :root {{
    --bg: #f6f7fb; --card: #ffffff; --line: #e3e6ee;
    --text: #1a1d29; --muted: #667085; --accent: #2563eb;
    --shadow: 0 1px 2px rgba(16, 24, 40, .04), 0 1px 3px rgba(16, 24, 40, .08);
    --shadow-hover: 0 4px 10px rgba(16, 24, 40, .08), 0 2px 4px rgba(16, 24, 40, .06);
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; background: var(--bg); color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    line-height: 1.5;
  }}
  header {{
    padding: 24px 24px 24px; max-width: 1100px; margin: 0 auto; text-align: center;
  }}
  header h1 {{ margin: 0 0 8px; font-size: 2rem; }}
  header p {{ margin: 4px 0; color: var(--muted); }}
  .count {{ color: var(--accent); font-weight: 600; }}
  .topbar {{
    max-width: 1100px; margin: 0 auto; padding: 20px 24px 0;
    display: flex; justify-content: center;
  }}
  .topbar a {{
    display: inline-flex; align-items: center; gap: 8px; max-width: 100%;
    background: var(--card); border: 1px solid var(--line); color: var(--text);
    text-decoration: none; font-size: .8rem; font-weight: 600;
    padding: 8px 16px; border-radius: 999px; transition: .15s; box-shadow: var(--shadow);
  }}
  .topbar a:hover {{ border-color: var(--accent); color: var(--accent); box-shadow: var(--shadow-hover); }}
  @media (max-width: 480px) {{
    .topbar a {{ text-align: center; white-space: normal; }}
  }}
  main {{
    max-width: 1100px; margin: 0 auto; padding: 16px 24px 64px;
    display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
    gap: 16px;
  }}
  .card {{
    background: var(--card); border: 1px solid var(--line); border-radius: 14px;
    padding: 18px; text-decoration: none; color: inherit; transition: .15s;
    display: flex; flex-direction: column; gap: 6px; box-shadow: var(--shadow);
  }}
  .card:hover {{ border-color: var(--accent); transform: translateY(-2px); box-shadow: var(--shadow-hover); }}
  .card-top {{ display: flex; justify-content: space-between; align-items: center; }}
  .card h2 {{ font-size: 1.1rem; margin: 4px 0; }}
  .meta {{ margin: 0; color: var(--muted); font-size: .9rem; }}
  .state {{ font-size: .72rem; font-weight: 700; padding: 3px 8px; border-radius: 20px; }}
  .state.upcoming {{ background: #dbeafe; color: #1d4ed8; }}
  .state.open {{ background: #dcfce7; color: #15803d; }}
  .src {{ font-size: .72rem; color: var(--muted); }}
  .tags {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }}
  .tag {{ background: #f1f5f9; color: #475569; font-size: .72rem;
          padding: 3px 8px; border-radius: 6px; }}
  .prize {{
    margin-top: 8px; font-size: .85rem; font-weight: 600; color: #92400e;
    background: #fef3c7; display: inline-block; padding: 3px 10px; border-radius: 6px;
    align-self: flex-start;
  }}
  .empty {{ grid-column: 1/-1; text-align: center; color: var(--muted); padding: 40px; }}
  footer {{ text-align: center; color: var(--muted); font-size: .8rem; padding: 24px; }}
  code {{ background: #f1f5f9; color: var(--text); padding: 2px 6px; border-radius: 4px; }}
  .filters {{
    max-width: 1100px; margin: 0 auto; padding: 4px 24px 0;
    display: flex; flex-wrap: wrap; gap: 8px; justify-content: center;
  }}
  .filter-btn {{
    background: var(--card); border: 1px solid var(--line); color: var(--muted);
    font: inherit; font-size: .82rem; font-weight: 600; cursor: pointer;
    padding: 6px 14px; border-radius: 999px; transition: .15s;
  }}
  .filter-btn:hover {{ border-color: var(--accent); color: var(--accent); }}
  .filter-btn.active {{ background: var(--accent); border-color: var(--accent); color: #fff; }}
</style>
</head>
<body>{repo_banner}
  <header>
    <h1>{title}</h1>
    <p>{subtitle}</p>
    <p>Showing <span class="count" id="event-count">{count}</span> events for <strong>{city}</strong></p>
    <p style="font-size:.8rem">Last updated {updated}</p>
  </header>{filters_bar}
  <main>
    {''.join(cards)}
  </main>
  <footer>
    Built automatically with GitHub Actions · Data from Devpost, Luma, Eventbrite &amp; Meetup
  </footer>
  <script>
    (function () {{
      var buttons = document.querySelectorAll(".filter-btn");
      var cards = document.querySelectorAll(".card");
      var countEl = document.getElementById("event-count");
      buttons.forEach(function (btn) {{
        btn.addEventListener("click", function () {{
          buttons.forEach(function (b) {{ b.classList.remove("active"); }});
          btn.classList.add("active");
          var filter = btn.dataset.filter;
          var visible = 0;
          cards.forEach(function (card) {{
            var match = filter === "all" || (card.dataset.categories || "").split(" ").indexOf(filter) !== -1;
            card.style.display = match ? "" : "none";
            if (match) visible++;
          }});
          if (countEl) countEl.textContent = visible;
        }});
      }});
    }})();
  </script>
</body>
</html>
"""


# ----------------------------------------------------------------------
# 8. Run everything
# ----------------------------------------------------------------------
def main():
    config = load_config()
    raw_city = config.get("city", "")
    city, region_hint = split_city_hint(raw_city)
    print(f"Fetching events for: {raw_city}")

    events = fetch_devpost(city, config.get("max_pages", 6))
    print(f"  found {len(events)} raw Devpost events")

    luma_events = fetch_luma(city, config.get("luma_max_events", 80))
    print(f"  found {len(luma_events)} raw Luma events")
    events += luma_events

    eventbrite_events = fetch_eventbrite(
        city, region_hint, config.get("eventbrite_max_pages", 3)
    )
    print(f"  found {len(eventbrite_events)} raw Eventbrite events")
    events += eventbrite_events

    meetup_events = fetch_meetup(city)
    print(f"  found {len(meetup_events)} raw Meetup events")
    events += meetup_events

    for slug in config.get("extra_luma_calendars", []):
        calendar_events = fetch_luma_calendar(slug)
        print(f"  found {len(calendar_events)} upcoming events from Luma calendar '{slug}'")
        events += calendar_events

    events = filter_events(events, config)
    print(f"  {len(events)} match your filters")

    html_out = render_html(events, config)
    (ROOT / "index.html").write_text(html_out, encoding="utf-8")

    # Also save the raw data in case you want it later.
    (ROOT / "events.json").write_text(
        json.dumps(events, indent=2, default=str), encoding="utf-8"
    )
    print("Wrote index.html and events.json")


if __name__ == "__main__":
    main()
