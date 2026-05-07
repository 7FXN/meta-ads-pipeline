"""
Pulls top ads from Airtable + their analysis from Notion,
mixes 2-3 ads through Gemini, and publishes a creative brief to Notion.

Usage:
  python3 creative_generator.py                        # mix best 3 ads across all competitors
  python3 creative_generator.py "Trivia Crack"         # mix top 3 ads from one competitor
  python3 creative_generator.py "Trivia Crack" "QuizzLand"  # mix top ads across two competitors
  python3 creative_generator.py --mix 2 "Trivia Crack" # mix 2 ads instead of 3
"""

import base64
import json
import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Optional

try:
    import requests
except ImportError:
    print("Run: pip3 install requests google-genai")
    sys.exit(1)

try:
    from groq import Groq
except ImportError:
    print("Run: pip3 install groq")
    sys.exit(1)


# ── Config ───────────────────────────────────────────────────────────────────

def load_env():
    env = {}
    for line in (Path(__file__).parent / ".env").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env

ENV = load_env()

AIRTABLE_TOKEN  = ENV["AIRTABLE_TOKEN"]
AIRTABLE_BASE   = ENV["AIRTABLE_BASE_ID"]
AIRTABLE_TABLE  = ENV["AIRTABLE_TABLE_ID"]
NOTION_TOKEN    = ENV["NOTION_TOKEN"]
NOTION_ADS_DB   = ENV["NOTION_DATABASE_ID"]
# Separate database for AI-generated creatives (set NOTION_CREATIVES_DB_ID in .env)
# Falls back to NOTION_ADS_DB if not set
NOTION_CREATIVES_DB = ENV.get("NOTION_CREATIVES_DB_ID") or NOTION_ADS_DB
GROQ_KEY        = ENV["GROQ_API_KEY"]

NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

groq_client = Groq(api_key=GROQ_KEY)
GROQ_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"


# ── Step 1: Pull ads from Airtable ───────────────────────────────────────────

def fetch_airtable_ads(competitors: Optional[List[str]] = None, limit: int = 10) -> List[dict]:
    """Fetch top ads from Airtable, optionally filtered by competitor."""
    headers = {"Authorization": f"Bearer {AIRTABLE_TOKEN}"}
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE}/{AIRTABLE_TABLE}"
    params = {"pageSize": 100, "sort[0][field]": "Scraped At", "sort[0][direction]": "desc"}

    r = requests.get(url, headers=headers, params=params)
    if r.status_code != 200:
        print(f"Airtable error: {r.text[:200]}")
        return []

    records = r.json().get("records", [])
    ads = []
    for rec in records:
        f = rec.get("fields", {})
        if not f.get("Ad Copy"):
            continue
        if competitors:
            comp = (f.get("Competitor") or "").lower()
            if not any(c.lower() in comp for c in competitors):
                continue
        img_url = None
        attachments = f.get("Image", [])
        if attachments:
            img_url = attachments[0].get("url") or attachments[0].get("thumbnails", {}).get("large", {}).get("url")
        ads.append({
            "airtable_id":   rec["id"],
            "competitor":    f.get("Competitor", "Unknown"),
            "ad_copy":       f.get("Ad Copy", ""),
            "start_date":    f.get("Start Date", ""),
            "page_name":     f.get("Page Name", ""),
            "library_id":    f.get("Library ID", ""),
            "ad_library_url": f.get("Ad Library URL", ""),
            "country":       f.get("Country", ""),
            "image_url":     img_url,
        })

    print(f"Fetched {len(ads)} ads from Airtable")
    return ads[:limit]


# ── Step 2: Pull analysis from Notion ────────────────────────────────────────

def fetch_notion_analysis(library_id: str) -> dict:
    """Find the Notion page for an ad by Library ID and return its analysis."""
    r = requests.post(
        f"https://api.notion.com/v1/databases/{NOTION_ADS_DB}/query",
        headers=NOTION_HEADERS,
        json={"filter": {"property": "Library ID", "rich_text": {"contains": library_id}}},
    )
    if r.status_code != 200 or not r.json().get("results"):
        return {}

    page = r.json()["results"][0]["properties"]

    def get_text(prop):
        items = page.get(prop, {}).get("rich_text", [])
        return items[0]["plain_text"] if items else ""

    return {
        "concept":      get_text("Concept"),
        "pain":         get_text("Pain"),
        "angle":        get_text("Angle"),
        "hook":         get_text("Hook"),
        "why_it_works": get_text("Why it works"),
    }


# ── Step 3: Load image bytes ──────────────────────────────────────────────────

def load_image(ad: dict) -> Optional[bytes]:
    """Load image from local file first, then fall back to URL."""
    # Try local file
    lib_id = ad.get("library_id", "")
    competitor = ad.get("competitor", "").replace(" ", "_")
    ads_dir = Path("ads_data") / competitor

    if ads_dir.exists():
        for img_path in sorted(ads_dir.glob("ad_*.jpg")):
            # Try to match by reading raw_ads.json
            try:
                raw = json.loads((Path("ads_data") / "raw_ads.json").read_text())
                for comp_ads in raw.values():
                    for a in comp_ads:
                        if a.get("library_id") == lib_id and a.get("local_image"):
                            local = Path(a["local_image"])
                            if local.exists():
                                return local.read_bytes()
            except Exception:
                pass

    # Fall back to URL download
    url = ad.get("image_url")
    if url:
        try:
            r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code == 200:
                return r.content
        except Exception:
            pass

    return None


# ── Step 4: Gemini creative generation ───────────────────────────────────────

def generate_creative(ads_with_analysis: list[dict]) -> dict:
    """Send ads + analysis to Groq (Llama vision) and get back a new creative brief."""

    ads_context = []
    for i, item in enumerate(ads_with_analysis, 1):
        ad = item["ad"]
        analysis = item["analysis"]
        ctx = f"""AD {i} — {ad['competitor']} ({ad['start_date']})
Copy: {ad['ad_copy']}
Concept: {analysis.get('concept', '—')}
Pain targeted: {analysis.get('pain', '—')}
Angle: {analysis.get('angle', '—')}
Hook: {analysis.get('hook', '—')}
Why it works: {analysis.get('why_it_works', '—')}""".strip()
        ads_context.append(ctx)

    ad_labels = "\n".join(f"AD {i+1} = {item['ad']['competitor']}" for i, item in enumerate(ads_with_analysis))

    prompt = f"""You are a senior performance creative director specializing in mobile app advertising.

I'm giving you {len(ads_with_analysis)} top-performing competitor ads with their creative analyses:

{ad_labels}

{chr(10).join(f'---{chr(10)}{ctx}' for ctx in ads_context)}

---

STEP 1 — Extract the single strongest element from EACH ad (what makes it uniquely work):
{chr(10).join(f'AD {i+1} unique strength: ???' for i in range(len(ads_with_analysis)))}

STEP 2 — Now generate ONE new creative brief that SPLICES those unique strengths together into a concept neither competitor has. The output must be clearly different from any individual input ad.

Use these exact labels, no markdown bold, no asterisks:

CONCEPT:
(How this brief combines elements from each input ad — name which competitor each element is borrowed from)

HOOK:
(Scroll-stopping opening line — borrow the best hook mechanic from the ads but make it new)

HEADLINE:
(Under 8 words, punchy)

BODY COPY:
(2-3 sentences combining the tone and pain points of both ads)

PAIN TARGETED:
(The combined pain this new ad attacks — must pull from at least 2 input ads)

ANGLE:
(The strategic angle — must be different from all input angles)

VISUAL DIRECTION:
(Specific image description: composition, colors, text overlays, characters — inspired by the visual style of input ads but distinct)

WHY THIS WILL OUTPERFORM:
(3 bullets — each must reference a specific weakness in one of the input ads that this new brief fixes)

COPY VARIANT A:
(Shorter version)

COPY VARIANT B:
(Different emotional angle than Variant A)"""

    # Build message content — images first, then text
    content = []
    img_count = 0
    for item in ads_with_analysis:
        img_bytes = item.get("image_bytes")
        if img_bytes:
            b64 = base64.b64encode(img_bytes).decode("utf-8")
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
            })
            img_count += 1

    content.append({"type": "text", "text": prompt})

    print(f"\nSending {img_count} images + analysis to Groq ({GROQ_MODEL})...")

    response = groq_client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[{"role": "user", "content": content}],
        max_tokens=2000,
        temperature=0.85,
    )
    raw_text = response.choices[0].message.content.strip()

    def extract_section(text, section):
        import re
        # Strip markdown bold (**) so "**CONCEPT:**" matches as "CONCEPT:"
        clean = re.sub(r'\*+', '', text)
        pattern = rf"{re.escape(section)}:[ \t]*(.*?)(?=\n[A-Z][A-Z ]+:|$)"
        m = re.search(pattern, clean, re.DOTALL)
        return m.group(1).strip() if m else ""

    return {
        "concept":          extract_section(raw_text, "CONCEPT"),
        "hook":             extract_section(raw_text, "HOOK"),
        "headline":         extract_section(raw_text, "HEADLINE"),
        "body_copy":        extract_section(raw_text, "BODY COPY"),
        "pain":             extract_section(raw_text, "PAIN TARGETED"),
        "angle":            extract_section(raw_text, "ANGLE"),
        "visual_direction": extract_section(raw_text, "VISUAL DIRECTION"),
        "why_outperforms":  extract_section(raw_text, "WHY THIS WILL OUTPERFORM"),
        "copy_variant_a":   extract_section(raw_text, "COPY VARIANT A"),
        "copy_variant_b":   extract_section(raw_text, "COPY VARIANT B"),
        "raw":              raw_text,
    }


# ── Step 5: Create Notion page ────────────────────────────────────────────────

def get_or_create_creatives_db() -> str:
    """Return the database ID to publish generated creatives to."""
    return NOTION_CREATIVES_DB


def rt(text: str) -> list:
    return [{"type": "text", "text": {"content": str(text)[:2000]}}]

def heading(text, level=2):
    return {"object": "block", "type": f"heading_{level}",
            f"heading_{level}": {"rich_text": rt(text)}}

def bullet(text):
    return {"object": "block", "type": "bulleted_list_item",
            "bulleted_list_item": {"rich_text": rt(str(text))}}

def divider():
    return {"object": "block", "type": "divider", "divider": {}}

def paragraph(text):
    return {"object": "block", "type": "paragraph",
            "paragraph": {"rich_text": rt(text)}}


def publish_to_notion(creative: dict, source_ads: List[dict], db_id: str):
    title = f"[AI] {creative.get('headline') or creative.get('concept', 'Generated Creative')[:60]}"
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    sources = ", ".join(f"{a['ad']['competitor']} ({a['ad']['start_date']})" for a in source_ads)
    properties = {
        "Name":             {"title": rt(title)},
        "Concept":          {"rich_text": rt(creative.get("concept", ""))},
        "Hook":             {"rich_text": rt(creative.get("hook", ""))},
        "Headline":         {"rich_text": rt(creative.get("headline", ""))},
        "Body Copy":        {"rich_text": rt(creative.get("body_copy", ""))},
        "Pain Targeted":    {"rich_text": rt(creative.get("pain", ""))},
        "Angle":            {"rich_text": rt(creative.get("angle", ""))},
        "Visual Direction": {"rich_text": rt(creative.get("visual_direction", ""))},
        "Copy Variant A":   {"rich_text": rt(creative.get("copy_variant_a", ""))},
        "Copy Variant B":   {"rich_text": rt(creative.get("copy_variant_b", ""))},
        "Sources":          {"rich_text": rt(sources)},
        "Generated At":     {"rich_text": rt(generated_at)},
    }

    # Page body
    blocks = [
        heading("📥 Source Ads Mixed", 2),
    ]
    for item in source_ads:
        ad = item["ad"]
        analysis = item["analysis"]
        blocks += [
            bullet(f"{ad['competitor']} — \"{ad['ad_copy'][:80]}...\""),
            bullet(f"  Concept: {analysis.get('concept', '—')}"),
            bullet(f"  Hook: {analysis.get('hook', '—')}"),
        ]
        if ad.get("image_url"):
            blocks.append({
                "object": "block", "type": "image",
                "image": {"type": "external", "external": {"url": ad["image_url"]}},
            })

    blocks += [
        divider(),
        heading("🧠 Generated Creative Brief", 2),
        heading("Concept", 3), paragraph(creative.get("concept", "")),
        heading("Hook", 3),    paragraph(creative.get("hook", "")),
        heading("Headline", 3), paragraph(creative.get("headline", "")),
        heading("Body Copy", 3), paragraph(creative.get("body_copy", "")),
        heading("Pain Targeted", 3), paragraph(creative.get("pain", "")),
        heading("Angle", 3),   paragraph(creative.get("angle", "")),
        heading("Visual Direction", 3), paragraph(creative.get("visual_direction", "")),
        divider(),
        heading("📈 Why This Will Outperform", 2),
        paragraph(creative.get("why_outperforms", "")),
        divider(),
        heading("✏️ Copy Variants", 2),
        heading("Variant A", 3), paragraph(creative.get("copy_variant_a", "")),
        heading("Variant B", 3), paragraph(creative.get("copy_variant_b", "")),
    ]

    r = requests.post(
        "https://api.notion.com/v1/pages",
        headers=NOTION_HEADERS,
        json={"parent": {"database_id": db_id}, "properties": properties, "children": blocks},
    )
    if r.status_code == 200:
        return r.json().get("url")
    print(f"Notion error: {r.text[:200]}")
    return None


# ── Main ──────────────────────────────────────────────────────────────────────

def parse_args():
    args = sys.argv[1:]
    mix_count = 3
    competitors = []
    i = 0
    while i < len(args):
        if args[i] == "--mix" and i + 1 < len(args):
            mix_count = int(args[i + 1])
            i += 2
        else:
            competitors.append(args[i])
            i += 1
    return competitors, mix_count


def main():
    competitors, mix_count = parse_args()

    print("=== Creative Generator ===")
    print(f"Competitors: {', '.join(competitors) if competitors else 'all'}")
    print(f"Mixing: {mix_count} ads\n")

    # 1. Fetch ads from Airtable
    ads = fetch_airtable_ads(competitors if competitors else None, limit=50)
    if not ads:
        print("No ads found in Airtable. Run the scraper first.")
        sys.exit(1)

    # Pick the mix_count most varied ads (spread across competitors if possible)
    selected = []
    seen_competitors = set()
    # First pass: one per competitor
    for ad in ads:
        if ad["competitor"] not in seen_competitors and len(selected) < mix_count:
            selected.append(ad)
            seen_competitors.add(ad["competitor"])
    # Second pass: fill remaining slots
    for ad in ads:
        if len(selected) >= mix_count:
            break
        if ad not in selected:
            selected.append(ad)

    print(f"Selected {len(selected)} ads to mix:")
    for ad in selected:
        print(f"  • {ad['competitor']} — {ad['ad_copy'][:70]}...")

    # 2. Fetch Notion analysis for each ad
    print("\nFetching analysis from Notion...")
    ads_with_analysis = []
    for ad in selected:
        analysis = {}
        if ad.get("library_id"):
            analysis = fetch_notion_analysis(ad["library_id"])
        img_bytes = load_image(ad)
        ads_with_analysis.append({
            "ad":          ad,
            "analysis":    analysis,
            "image_bytes": img_bytes,
        })
        status = "✓ image" if img_bytes else "no image"
        status += f" | {'✓ analysis' if analysis.get('concept') else 'no analysis'}"
        print(f"  {ad['competitor']}: {status}")

    # 3. Generate creative with Gemini
    creative = generate_creative(ads_with_analysis)

    # 4. Find or create Generated Creatives database
    db_id = get_or_create_creatives_db()

    # 5. Publish to Notion
    url = publish_to_notion(creative, ads_with_analysis, db_id)
    if url:
        print(f"\n✓ Creative brief published: {url}")
    else:
        print("\nFailed to publish to Notion")


if __name__ == "__main__":
    main()
