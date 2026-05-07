"""
Syncs Airtable schema + data to match the Notion naming system.

What it does:
  1. Adds 'Name' text field (same format as Notion page titles)
  2. Converts 'Start Date' to DD.MM.YYYY format
  3. Ensures 'Ad Library URL' is set from Library ID
  4. Deletes internal/aesthetic columns: Scraped At, Page Name,
     Copy Summary (AI), Language Detected (AI), Ad Type (AI),
     Sentiment (AI), Image Relevance (AI)

Usage:
  python3 airtable_updater.py
  python3 airtable_updater.py --dry-run
"""

import re
import sys
import time
from pathlib import Path
from typing import Optional

try:
    import requests
except ImportError:
    print("Run: pip3 install requests")
    sys.exit(1)

# Import shared logic from notion_publisher
sys.path.insert(0, str(Path(__file__).parent))
from notion_publisher import analyze_hook, format_date_dmy, format_date_short, build_name, NAME_FORMAT


def load_env():
    env = {}
    for line in (Path(__file__).parent / ".env").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


ENV      = load_env()
TOKEN    = ENV["AIRTABLE_TOKEN"]
BASE_ID  = ENV["AIRTABLE_BASE_ID"]
TABLE_ID = ENV["AIRTABLE_TABLE_ID"]

META_URL    = f"https://api.airtable.com/v0/meta/bases/{BASE_ID}/tables/{TABLE_ID}/fields"
RECORDS_URL = f"https://api.airtable.com/v0/{BASE_ID}/{TABLE_ID}"

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type":  "application/json",
}

DRY_RUN = "--dry-run" in sys.argv

COLUMNS_TO_DELETE = [
    "Scraped At",
    "Page Name",
    "Copy Summary (AI)",
    "Language Detected (AI)",
    "Ad Type (AI)",
    "Sentiment (AI)",
    "Image Relevance (AI)",
]


# ── Schema helpers ────────────────────────────────────────────────────────────

def get_fields() -> dict:
    """Return {field_name: field_id} for all fields in the table."""
    r = requests.get(
        f"https://api.airtable.com/v0/meta/bases/{BASE_ID}/tables",
        headers=HEADERS,
    )
    for table in r.json().get("tables", []):
        if table["id"] == TABLE_ID:
            return {f["name"]: f["id"] for f in table["fields"]}
    return {}


def add_field(name: str, field_type: str = "singleLineText") -> Optional[str]:
    """Create a new field and return its ID, or None on failure."""
    if DRY_RUN:
        print(f"  [dry-run] Would create field '{name}' ({field_type})")
        return None
    r = requests.post(META_URL, headers=HEADERS, json={"name": name, "type": field_type})
    if r.status_code == 200:
        fid = r.json().get("id")
        print(f"  Created field '{name}' → {fid}")
        return fid
    # 422 = field already exists with that name
    if r.status_code == 422 and "already" in r.text.lower():
        print(f"  Field '{name}' already exists")
        return None
    print(f"  Failed to create '{name}': {r.status_code} {r.text[:120]}")
    return None


def delete_field(field_name: str, field_id: str):
    if DRY_RUN:
        print(f"  [dry-run] Would delete field '{field_name}' ({field_id})")
        return
    r = requests.delete(f"{META_URL}/{field_id}", headers=HEADERS)
    if r.status_code == 200:
        print(f"  Deleted field '{field_name}'")
    else:
        print(f"  Could not delete '{field_name}': {r.status_code} {r.text[:120]}")


# ── Record helpers ────────────────────────────────────────────────────────────

def fetch_all_records() -> list:
    records = []
    params = {"pageSize": 100}
    while True:
        r = requests.get(RECORDS_URL, headers=HEADERS, params=params)
        data = r.json()
        records += data.get("records", [])
        if not data.get("offset"):
            break
        params["offset"] = data["offset"]
    return records


def batch_update(updates: list[dict]):
    """Send PATCH updates in chunks of 10 (Airtable limit)."""
    for i in range(0, len(updates), 10):
        chunk = updates[i:i + 10]
        if DRY_RUN:
            for u in chunk:
                print(f"  [dry-run] {u['id']} → {list(u['fields'].keys())}")
            continue
        r = requests.patch(RECORDS_URL, headers=HEADERS, json={"records": chunk})
        if r.status_code != 200:
            print(f"  Batch update error: {r.status_code} {r.text[:200]}")
        time.sleep(0.25)  # stay under Airtable's 5 req/s limit


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if DRY_RUN:
        print("=== DRY RUN — no changes will be written ===\n")

    print(f'Using NAME_FORMAT: "{NAME_FORMAT}"\n')

    # 1. Check/create 'Name' field
    print("── Step 1: Schema — 'Name' field ──")
    fields = get_fields()
    name_field_exists = "Name" in fields

    if not name_field_exists:
        fid = add_field("Name", "singleLineText")
        if fid:
            fields = get_fields()
            name_field_exists = "Name" in fields

    if not name_field_exists and not DRY_RUN:
        print("  ⚠  'Name' field could not be created (token lacks schema.bases:write).")
        print("     → In Airtable UI: add a 'Name' text column, then re-run this script.")
        print("     Continuing with Start Date + Ad Library URL updates only.\n")

    # 2. Fetch all records and build updates
    print("── Step 2: Update records ──")
    records = fetch_all_records()
    print(f"  {len(records)} records loaded")

    updates = []
    for rec in records:
        f = rec["fields"]
        competitor = f.get("Competitor", "")
        country    = f.get("Country", "US")
        raw_date   = f.get("Start Date", "")
        ad_copy    = f.get("Ad Copy", "")
        lib_id     = f.get("Library ID", "")

        hook     = analyze_hook(ad_copy)
        fmt_date = format_date_dmy(raw_date)
        name     = build_name(competitor, country, raw_date, hook)
        ad_url   = f"https://www.facebook.com/ads/library/?id={lib_id}" if lib_id else None

        new_fields: dict = {"Start Date": fmt_date}
        if name_field_exists:
            new_fields["Name"] = name
        if ad_url:
            new_fields["Ad Library URL"] = ad_url

        updates.append({"id": rec["id"], "fields": new_fields})

    print(f"  Updating {'Name + ' if name_field_exists else ''}Start Date + Ad Library URL on {len(updates)} records...")
    batch_update(updates)
    if not DRY_RUN:
        print(f"  Done — {len(updates)} records updated")

    # 3. Delete internal/aesthetic columns
    print("\n── Step 3: Delete internal columns ──")
    fields = get_fields()
    manual_delete = []
    for col_name in COLUMNS_TO_DELETE:
        fid = fields.get(col_name)
        if not fid:
            print(f"  '{col_name}' not found — skipping")
            continue
        r = requests.delete(f"{META_URL}/{fid}", headers=HEADERS)
        if DRY_RUN:
            print(f"  [dry-run] Would delete '{col_name}' ({fid})")
        elif r.status_code == 200:
            print(f"  Deleted '{col_name}'")
        elif r.status_code in (403, 404):
            manual_delete.append(col_name)
        else:
            print(f"  Could not delete '{col_name}': {r.status_code} {r.text[:100]}")

    if manual_delete:
        print("\n  ⚠  Token lacks schema.bases:write — delete these columns manually in Airtable UI:")
        for col in manual_delete:
            print(f"     • {col}")
        print("\n  How to fix the token (to automate this in future):")
        print("     1. Go to https://airtable.com/create/tokens")
        print("     2. Edit your token → add scope 'schema.bases:write'")
        print("     3. Re-run:  python3 airtable_updater.py")

    print("\nDone.")


if __name__ == "__main__":
    main()
