# scraper_airtable.py
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import requests as _requests
except ImportError:
    _requests = None


def load_env() -> dict:
    env = {}
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def airtable_upload(ads: list, competitor: str, country: str, search_by: str = "page", require_copy: bool = True):
    env = load_env()
    token    = env.get("AIRTABLE_TOKEN")
    base_id  = env.get("AIRTABLE_BASE_ID")
    table_id = env.get("AIRTABLE_TABLE_ID")

    if not all([token, base_id, table_id]):
        print("  [Airtable] Skipping — missing token/base/table in .env")
        return

    if _requests is None:
        print("  [Airtable] Skipping — requests library not installed")
        return

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    url        = f"https://api.airtable.com/v0/{base_id}/{table_id}"
    scraped_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from notion_publisher import analyze_hook as _analyze_hook, build_name as _build_name, format_date_dmy as _fmt_dmy
        _name_helpers = (_analyze_hook, _build_name, _fmt_dmy)
    except Exception:
        _name_helpers = None

    uploaded = 0
    skipped  = 0
    for ad in ads:
        raw_date  = ad.get("start_date") or ""
        ad_copy   = ad.get("ad_copy") or ""
        lib_id    = ad.get("library_id") or ""
        page_name = (ad.get("page_name") or "").lower()

        if not lib_id:
            print("  [Airtable] Skipping ad — missing Library ID")
            skipped += 1
            continue
        if not raw_date:
            print(f"  [Airtable] Skipping ad {lib_id} — missing Start Date")
            skipped += 1
            continue
        if require_copy and not ad_copy:
            print(f"  [Airtable] Skipping ad {lib_id} — missing Ad Copy (use --no-copy-req to allow)")
            skipped += 1
            continue

        if search_by == "page":
            competitor_lower = competitor.lower()
            if page_name and not any(w in page_name for w in competitor_lower.split()):
                print(f"  [Airtable] Skipping ad {lib_id} — page '{ad.get('page_name')}' not related to '{competitor}'")
                skipped += 1
                continue

        if _name_helpers:
            _analyze_hook, _build_name, _fmt_dmy = _name_helpers
            record_name = _build_name(competitor, country, raw_date, _analyze_hook(ad_copy))
            fmt_date    = _fmt_dmy(raw_date)
        else:
            record_name = competitor
            fmt_date    = raw_date

        ad_url = f"https://www.facebook.com/ads/library/?id={lib_id}" if lib_id else (ad.get("ad_library_url") or "")

        fields = {
            "Competitor":     record_name,
            "Page Name":      ad.get("page_name") or "",
            "Ad Copy":        ad_copy,
            "Start Date":     fmt_date,
            "Library ID":     lib_id,
            "Ad Library URL": ad_url,
            "Country":        country,
            "Scraped At":     scraped_at,
        }

        img_url = ad.get("image_url")
        if img_url:
            fields["Image"] = [{"url": img_url}]

        resp = _requests.post(url, headers=headers, json={"fields": fields})
        if resp.status_code in (200, 201):
            uploaded += 1
        else:
            print(f"  [Airtable] Failed to upload ad {ad.get('library_id')}: {resp.text[:100]}")

    total = uploaded + skipped
    print(f"  [Airtable] Uploaded {uploaded}/{total} records ({skipped} skipped)")
