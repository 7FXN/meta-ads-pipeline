"""
Reads scraped ads from Airtable, analyzes each ad, and creates
a Notion page per ad with full analysis + raw data + links.
Skips ads already in Notion (deduplicates by Library ID).

Usage:
  python3 notion_publisher.py                  # sync all from Airtable → Notion
  python3 notion_publisher.py "Trivia Crack"   # only one competitor
  python3 notion_publisher.py --rename         # rename all existing pages using NAME_FORMAT
"""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import requests
except ImportError:
    print("Run: pip3 install requests")
    sys.exit(1)


# ── Config ──────────────────────────────────────────────────────────────────

def load_env():
    env = {}
    for line in (Path(__file__).parent / ".env").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


ENV = load_env()
NOTION_TOKEN    = ENV["NOTION_TOKEN"]
NOTION_DB_ID    = ENV["NOTION_DATABASE_ID"]
AIRTABLE_TOKEN  = ENV["AIRTABLE_TOKEN"]
AIRTABLE_BASE   = ENV.get("AIRTABLE_BASE_ID", "")
AIRTABLE_TABLE  = ENV.get("AIRTABLE_TABLE_ID", "")

AIRTABLE_HEADERS = {"Authorization": f"Bearer {AIRTABLE_TOKEN}"}

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

# ── Naming format ─────────────────────────────────────────────────────────────
# Available tokens: {app} {country} {date} {hook}
# {app}     — competitor name          e.g. "Calm"
# {country} — country code             e.g. "US" or "ALL"
# {date}    — month + year             e.g. "Nov 2025"
# {hook}    — first line of ad copy    e.g. "Too wired to sleep?"
#
# Change this string and run:  python3 notion_publisher.py --rename
NAME_FORMAT = "{app} [{country}] {date} — {hook}"

UA_MONTHS = {
    "січ": "Jan", "лют": "Feb", "бер": "Mar", "кві": "Apr",
    "трав": "May", "черв": "Jun", "лип": "Jul", "серп": "Aug",
    "вер": "Sep", "жовт": "Oct", "лист": "Nov", "груд": "Dec",
}

UA_MONTH_NUMS = {
    "січ": 1, "лют": 2, "бер": 3, "кві": 4, "трав": 5, "черв": 6,
    "лип": 7, "серп": 8, "вер": 9, "жовт": 10, "лист": 11, "груд": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

def format_date_short(date_str: str) -> str:
    """Convert '4 трав 2026', '26 Jan 2026', or '04.05.2026' → 'May 2026'."""
    if not date_str:
        return "?"
    # DD.MM.YYYY → month name + year
    dmy = re.match(r"^(\d{2})\.(\d{2})\.(202\d)$", date_str.strip())
    if dmy:
        month_names = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
        return f"{month_names[int(dmy.group(2))-1]} {dmy.group(3)}"
    s = date_str.lower()
    for ua, en in UA_MONTHS.items():
        if ua in s:
            year = re.search(r"202\d", s)
            return f"{en} {year.group()}" if year else en
    for en_short in ["jan","feb","mar","apr","may","jun","jul","aug","sep","oct","nov","dec"]:
        if en_short in s:
            en_full = en_short.capitalize()
            year = re.search(r"202\d", s)
            return f"{en_full} {year.group()}" if year else en_full
    year = re.search(r"202\d", date_str)
    return year.group() if year else date_str[:10]

def format_date_dmy(date_str: str) -> str:
    """Convert '4 трав 2026' or '26 Jan 2026' → '04.05.2026'. Returns input unchanged if already formatted."""
    if not date_str:
        return ""
    if re.match(r"^\d{2}\.\d{2}\.202\d$", date_str.strip()):
        return date_str.strip()
    s = date_str.lower().strip()
    month_num = 0
    for abbr, num in UA_MONTH_NUMS.items():
        if abbr in s:
            month_num = num
            break
    year_m = re.search(r"(202\d)", s)
    day_m = re.match(r"(\d{1,2})", s)
    if month_num and year_m and day_m:
        return f"{int(day_m.group(1)):02d}.{month_num:02d}.{year_m.group(1)}"
    return date_str

def build_name(app: str, country: str, date_str: str, hook: str) -> str:
    hook_short = hook.split("\n")[0].strip()[:45]
    return NAME_FORMAT.format(
        app=app,
        country=country or "?",
        date=format_date_short(date_str) if date_str else "?",
        hook=hook_short,
    )


# ── Ad analysis ──────────────────────────────────────────────────────────────

EMOJI_SIGNALS = [
    ("🧠", "🧠 brain → intelligence/knowledge theme"),
    ("⚡", "⚡ bolt → speed and quick stimulation"),
    ("🔥", "🔥 fire → high-energy or trending angle"),
    ("🎯", "🎯 target → precision and goal-focus"),
    ("😱", "😱 shock → surprise or difficulty tease"),
    ("🏆", "🏆 trophy → competitive instinct"),
    ("🎮", "🎮 gamepad → entertainment framing, not 'studying'"),
    ("🎲", "🎲 dice → fun and randomness"),
    ("✅", "✅ check → achievement and completion"),
    ("💡", "💡 bulb → insight or learning moment"),
    ("🌍", "🌍 globe → world/geography theme"),
    ("🎵", "🎵 music → music-trivia angle"),
    ("📚", "📚 books → education framing"),
]


def analyze_hook(copy: str) -> str:
    """
    Analyze what catches the eye in the ad creative:
    opening technique, emoji visual signals, copy structure.
    """
    if not copy or not copy.strip():
        return "No copy"
    text = copy.strip()
    first_line = text.split("\n")[0].strip()
    low = first_line.lower()
    parts = []

    # Opening technique
    if re.match(r"^(do you|can you|are you|could you|did you)\b", low):
        parts.append("self-test question — pulls reader into a personal challenge")
    elif re.match(r"^(what|when|who|where|which|how)\b", low) and "?" in first_line:
        parts.append("open question — sparks curiosity, answer lives inside the app")
    elif first_line.endswith("?"):
        parts.append("question hook — prompts self-reflection")
    elif re.match(r"^\d", first_line):
        num_m = re.match(r"^[\d\s,]+", first_line)
        num = num_m.group().strip() if num_m else ""
        parts.append(f"number-led ('{num}') — scale or precision signal creates credibility")
    elif re.match(r"^[^\w\s]", first_line):
        parts.append("emoji-first — visual thumb-stop before any text is processed")
    elif "!" in first_line and len(first_line.split()) <= 6:
        parts.append("short exclamation — punchy command or reveal, low cognitive load")
    else:
        parts.append("statement open — leads directly with value or claim")

    # Emoji signals in first 120 chars
    found = [sig for emoji, sig in EMOJI_SIGNALS if emoji in text[:120]]
    if found:
        parts.append("; ".join(found[:2]))

    # Copy structure
    lines = [l for l in text.split("\n") if l.strip()]
    words = len(text.split())
    if words <= 8:
        parts.append("ultra-short copy — instant readability in feed")
    elif len(lines) >= 3:
        parts.append("multi-line structure — builds context or uses line breaks as pacing")

    return " | ".join(parts)


def analyze_ad(ad: dict, competitor: str) -> dict:
    """
    Rule-based analysis derived from ad copy + metadata.
    Returns structured fields: concept, pain, angle, hook, why_it_works.
    """
    copy = (ad.get("ad_copy") or "").strip()
    copy_lower = copy.lower()

    # --- Concept ---
    if "?" in copy:
        concept = f"Question hook — challenges the user to test themselves"
    elif any(w in copy_lower for w in ["free", "unlimited", "no limit"]):
        concept = f"Value proposition — highlights free access / no limits"
    elif any(w in copy_lower for w in ["learn", "brain", "knowledge", "smart"]):
        concept = f"Self-improvement — positions the app as a brain-training tool"
    elif any(w in copy_lower for w in ["play", "fun", "game", "enjoy"]):
        concept = f"Entertainment hook — leads with fun and gameplay"
    elif any(w in copy_lower for w in ["90s", "80s", "classic", "retro", "nostalgia"]):
        concept = f"Nostalgia hook — targets specific era/generation"
    elif any(w in copy_lower for w in ["compete", "challenge", "beat", "win", "leaderboard"]):
        concept = f"Competition hook — social rivalry and winning instinct"
    else:
        concept = f"Direct value — communicates core app benefit straightforwardly"

    # --- Pain ---
    if "?" in copy:
        pain = "Fear of not knowing / intellectual insecurity"
    elif any(w in copy_lower for w in ["bored", "boring", "time"]):
        pain = "Boredom — need for engaging, time-filling activity"
    elif any(w in copy_lower for w in ["learn", "improve", "skill", "brain"]):
        pain = "Desire for self-improvement and staying mentally sharp"
    elif any(w in copy_lower for w in ["90s", "80s", "classic", "memory"]):
        pain = "Nostalgia gap — fear of forgetting beloved cultural moments"
    else:
        pain = "Entertainment deficit — looking for quality screen-time activity"

    # --- Angle ---
    if copy.startswith("Do you") or copy.startswith("Can you") or copy.startswith("Are you"):
        angle = "Self-test / challenge angle"
    elif "!" in copy and any(w in copy_lower for w in ["free", "now", "download", "play"]):
        angle = "Direct response — urgency + CTA"
    elif any(w in copy_lower for w in ["real", "truly", "actually", "really"]):
        angle = "Authenticity angle — 'real' knowledge vs shallow scrolling"
    elif any(w in copy_lower for w in ["learn", "grow", "skill", "train"]):
        angle = "Self-improvement / growth angle"
    else:
        angle = "Benefit-first angle — leads with the value the user gets"

    # --- Hook ---
    hook = analyze_hook(copy)

    # --- Why it works ---
    reasons = []
    if "?" in copy[:50]:
        reasons.append("opens with a question → instant engagement loop")
    if any(w in copy_lower for w in ["90s", "80s", "classic", "retro"]):
        reasons.append("era specificity narrows audience → lower CPM, higher CTR")
    if any(w in copy_lower for w in ["free", "now", "download"]):
        reasons.append("clear CTA reduces friction")
    if any(emoji in copy for emoji in ["🧠", "⚡", "🎯", "🔥", "😱"]):
        reasons.append("emoji in copy increases thumb-stop rate")
    if len(copy) < 100:
        reasons.append("short copy → easy to read in feed without expanding")
    if not reasons:
        reasons.append("straightforward value prop is easy to understand in under 3 seconds")

    why_it_works = "; ".join(reasons).capitalize()

    return {
        "concept":       concept,
        "pain":          pain,
        "angle":         angle,
        "hook":          hook,
        "why_it_works":  why_it_works,
    }


# ── Notion helpers ───────────────────────────────────────────────────────────

def rt(text: str) -> list:
    """Rich text block."""
    return [{"type": "text", "text": {"content": str(text)[:2000]}}]


def heading(text: str, level: int = 2) -> dict:
    return {
        "object": "block",
        "type": f"heading_{level}",
        f"heading_{level}": {"rich_text": rt(text)},
    }


def bullet(text: str) -> dict:
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": rt(text)},
    }


def paragraph(text: str) -> dict:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": rt(text)},
    }


def divider() -> dict:
    return {"object": "block", "type": "divider", "divider": {}}


def build_page(ad: dict, competitor: str, analysis: dict, country: str) -> dict:
    copy = ad.get("ad_copy") or ""
    lib_id = ad.get("library_id") or ""

    # Always construct Ad Library URL from library_id (more reliable than scraped link)
    ad_lib_url = f"https://www.facebook.com/ads/library/?id={lib_id}" if lib_id else None

    title = build_name(competitor, country, ad.get("start_date") or "", analysis["hook"])

    properties = {
        "Name":           {"title": rt(title)},
        "Competitor":     {"select": {"name": competitor}},
        "Start Date":     {"rich_text": rt(format_date_dmy(ad.get("start_date") or ""))},
        "Country":        {"select": {"name": country}},
        "Library ID":     {"rich_text": rt(lib_id)},
        "Ad Library URL": {"url": ad_lib_url},
        "Concept":        {"rich_text": rt(analysis["concept"])},
        "Pain":           {"rich_text": rt(analysis["pain"])},
        "Angle":          {"rich_text": rt(analysis["angle"])},
        "Hook":           {"rich_text": rt(analysis["hook"])},
        "Why it works":   {"rich_text": rt(analysis["why_it_works"])},
    }

    img_url = ad.get("image_url")
    blocks = [
        heading("🔗 Links", 2),
        {
            "object": "block", "type": "bookmark",
            "bookmark": {"url": ad_lib_url},
        } if ad_lib_url else paragraph("No Ad Library URL"),
        divider(),
        heading("📊 Raw Data", 2),
        bullet(f"Competitor:   {competitor}"),
        bullet(f"Page Name:    {ad.get('page_name') or '—'}"),
        bullet(f"Start Date:   {ad.get('start_date') or '—'}"),
        bullet(f"Country:      {country}"),
        bullet(f"Library ID:   {lib_id}"),
        bullet(f"Ad Copy:      {copy}"),
        divider(),
        heading("🧠 Analysis", 2),
        bullet(f"Concept:      {analysis['concept']}"),
        bullet(f"Pain:         {analysis['pain']}"),
        bullet(f"Angle:        {analysis['angle']}"),
        bullet(f"Hook:         {analysis['hook']}"),
        bullet(f"Why it works: {analysis['why_it_works']}"),
    ]

    if img_url:
        blocks += [
            divider(),
            heading("🖼 Ad Image", 2),
            {
                "object": "block",
                "type": "image",
                "image": {"type": "external", "external": {"url": img_url}},
            },
        ]

    return {"parent": {"database_id": NOTION_DB_ID}, "properties": properties, "children": blocks}


def create_page(page_data: dict):
    r = requests.post("https://api.notion.com/v1/pages", headers=HEADERS, json=page_data)
    if r.status_code == 200:
        return r.json().get("url")
    print(f"  [Notion] Error: {r.status_code} {r.text[:200]}")
    return None


# ── Airtable fetch ───────────────────────────────────────────────────────────

def fetch_airtable_ads(filter_competitor=None):
    """Fetch all records from Airtable, optionally filtered by competitor."""
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE}/{AIRTABLE_TABLE}"
    records = []
    params = {"pageSize": 100}
    while True:
        r = requests.get(url, headers=AIRTABLE_HEADERS, params=params)
        data = r.json()
        records += data.get("records", [])
        if not data.get("offset"):
            break
        params["offset"] = data["offset"]

    ads = []
    for rec in records:
        f = rec.get("fields", {})
        raw_competitor = f.get("Competitor", "")
        if not raw_competitor:
            continue
        # Competitor may now be the full name "Calm [US] Jan 2026 — …"; extract app name
        app_name = raw_competitor.split(" [")[0].strip() if " [" in raw_competitor else raw_competitor
        if filter_competitor and app_name.lower() != filter_competitor.lower():
            continue
        attachments = f.get("Image", [])
        img_url = attachments[0].get("url") if attachments else None
        ads.append({
            "competitor":     app_name,
            "ad_copy":        f.get("Ad Copy", ""),
            "start_date":     f.get("Start Date", ""),
            "library_id":     f.get("Library ID", ""),
            "ad_library_url": f.get("Ad Library URL", ""),
            "country":        f.get("Country", "US"),
            "image_url":      img_url,
        })
    return ads


def get_existing_notion_lib_ids():
    """Return set of library IDs already in Notion."""
    lib_ids = set()
    params = {"page_size": 100}
    while True:
        r = requests.post(
            f"https://api.notion.com/v1/databases/{NOTION_DB_ID}/query",
            headers=HEADERS, json=params
        )
        data = r.json()
        for page in data.get("results", []):
            blocks = (page["properties"].get("Library ID") or {}).get("rich_text") or []
            if blocks:
                lib_ids.add(blocks[0]["plain_text"])
        if not data.get("has_more"):
            break
        params["start_cursor"] = data["next_cursor"]
    return lib_ids


# ── Rename command ────────────────────────────────────────────────────────────

def delete_database_column(prop_name: str):
    """Remove a property column from the Notion database schema."""
    r = requests.patch(
        f"https://api.notion.com/v1/databases/{NOTION_DB_ID}",
        headers=HEADERS,
        json={"properties": {prop_name: None}},
    )
    if r.status_code == 200:
        print(f"  [DB] Deleted column '{prop_name}'")
    else:
        print(f"  [DB] Could not delete '{prop_name}': {r.status_code} {r.text[:120]}")


def rename_all_pages():
    """
    Rename all existing Notion ad pages using current NAME_FORMAT.
    Also re-analyzes Hook from Airtable and converts Start Date to DD.MM.YYYY.
    """
    print(f'Renaming all pages using format: "{NAME_FORMAT}"\n')

    # Pre-fetch all Airtable records keyed by library_id for re-analysis
    print("  Pre-fetching Airtable records...")
    at_by_lib = {a["library_id"]: a for a in fetch_airtable_ads() if a.get("library_id")}
    print(f"  Loaded {len(at_by_lib)} Airtable records\n")

    # Remove Airtable Link column from DB schema
    delete_database_column("Airtable Link")

    params = {"page_size": 100}
    total = updated = skipped = 0
    while True:
        r = requests.post(f"https://api.notion.com/v1/databases/{NOTION_DB_ID}/query",
            headers=HEADERS, json=params)
        data = r.json()
        for page in data.get("results", []):
            props = page["properties"]
            name_blocks = (props.get("Name") or {}).get("title") or []
            current_name = name_blocks[0]["plain_text"] if name_blocks else ""
            if current_name.startswith("[AI]"):
                skipped += 1
                continue

            def txt(prop, _p=props):
                return ((_p.get(prop) or {}).get("rich_text") or [{"plain_text": ""}])[0]["plain_text"]
            def sel(prop, _p=props):
                return ((_p.get(prop) or {}).get("select") or {}).get("name", "")

            app     = sel("Competitor")
            country = sel("Country")
            lib_id  = txt("Library ID")

            if not app:
                skipped += 1
                continue

            # Re-analyze from Airtable if available; fall back to stored values
            at_ad = at_by_lib.get(lib_id)
            if at_ad:
                raw_date = at_ad.get("start_date") or txt("Start Date")
                hook     = analyze_hook(at_ad.get("ad_copy") or "")
            else:
                raw_date = txt("Start Date")
                hook     = txt("Hook")

            fmt_date  = format_date_dmy(raw_date)
            new_name  = build_name(app, country, raw_date, hook)
            ad_lib_url = f"https://www.facebook.com/ads/library/?id={lib_id}" if lib_id else None

            patch = {
                "properties": {
                    "Name":       {"title": rt(new_name)},
                    "Hook":       {"rich_text": rt(hook)},
                    "Start Date": {"rich_text": rt(fmt_date)},
                }
            }
            if ad_lib_url:
                patch["properties"]["Ad Library URL"] = {"url": ad_lib_url}

            r2 = requests.patch(f"https://api.notion.com/v1/pages/{page['id']}",
                headers=HEADERS, json=patch)
            if r2.status_code == 200:
                print(f"  ✓ {new_name}")
                updated += 1
            else:
                print(f"  ✗ {current_name[:50]} — {r2.text[:80]}")
            total += 1

        if not data.get("has_more"):
            break
        params["start_cursor"] = data["next_cursor"]

    print(f"\nDone: {updated} renamed, {skipped} skipped (AI pages + no-competitor)")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--rename":
        rename_all_pages()
        return

    filter_competitor = sys.argv[1] if len(sys.argv) > 1 else None

    print("Fetching existing Notion pages...")
    existing = get_existing_notion_lib_ids()
    print(f"  {len(existing)} ads already in Notion")

    print("Fetching ads from Airtable...")
    ads = fetch_airtable_ads(filter_competitor)
    print(f"  {len(ads)} ads in Airtable{f' for {filter_competitor}' if filter_competitor else ''}")

    to_publish = [a for a in ads if a["library_id"] not in existing]
    print(f"  {len(to_publish)} new ads to publish\n")

    if not to_publish:
        print("Nothing to do — Notion is already up to date.")
        return

    total = 0
    for i, ad in enumerate(to_publish):
        competitor = ad["competitor"]
        analysis = analyze_ad(ad, competitor)
        page_data = build_page(ad, competitor, analysis, ad.get("country", "US"))
        url = create_page(page_data)
        if url:
            print(f"  ✓ [{competitor}] {url}")
            total += 1
        else:
            print(f"  ✗ [{competitor}] {ad.get('library_id')} failed")

    print(f"\n✓ {total} pages created in Notion")


if __name__ == "__main__":
    main()
