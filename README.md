# Meta Ads Intelligence Pipeline

Automated competitive ad intelligence system for mobile apps. Scrapes top-performing ads from Meta Ads Library, stores creative assets in Airtable, publishes structured analysis to Notion, and generates AI-synthesised creative briefs by combining competitor strategies.

Runs on a weekly schedule via GitHub Actions or on demand from the GitHub UI.

---

## What it does

```
Meta Ads Library (Playwright)
        │  scrapes top active ads per competitor
        ▼
    Airtable
        │  stores ad copy, images, metadata
        ├──► Notion Ads DB        — one page per ad, structured analysis
        └──► Groq (Llama 4 Scout) — multimodal AI mixes competitor ads
                    │               into new creative briefs
                    ▼
             Notion Creatives DB  — AI-generated briefs ready for production
```

**Ranking strategies** — selects top performers by:
- `combined` *(default)* — scores each ad 1–5 on all four signals, picks highest total
- `age` — oldest running ad = longest surviving = proven winner
- `order` — Meta's own page relevance ranking
- `impressions` — highest estimated reach
- `copies` — most identical copies running simultaneously (scaling signal)

---

## Tech stack

- **Playwright** — headless Chromium, scrapes Meta Ads Library (JavaScript-rendered)
- **Airtable API** — stores raw ads + images
- **Notion API** — publishes structured analysis + AI creative briefs
- **Groq API** — Llama 4 Scout 17B multimodal, analyzes ad images + copy, generates briefs
- **GitHub Actions** — scheduled weekly runs, manual trigger with custom parameters

---

## Pipeline scripts

| Script | What it does |
|---|---|
| `meta_ads_scraper.py` | Scrapes Meta Ads Library → uploads to Airtable → triggers Notion publish |
| `notion_publisher.py` | Syncs Airtable → Notion; `--rename` to reformat all pages |
| `creative_generator.py` | Pulls top ads + analysis → sends to Groq → publishes AI brief to Notion |
| `airtable_updater.py` | One-time migration: naming format, date format, Ad Library URLs |

---

## Running locally

```bash
# 1. Clone and install
git clone https://github.com/YOUR_USERNAME/meta-ads-pipeline
cd meta-ads-pipeline
pip install -r requirements.txt
playwright install chromium

# 2. Configure credentials
cp .env.example .env
# Fill in your keys (see .env.example for required services)

# 3. Run
python3 meta_ads_scraper.py --country US --limit 3 "Calm"
python3 meta_ads_scraper.py --rank-by age "Duolingo" "Trivia Crack"
python3 creative_generator.py --mix 3
python3 notion_publisher.py --rename
```

**Full flag reference:**

```
meta_ads_scraper.py  [--country XX] [--limit N] [--rank-by STRATEGY] [--page-id ID] "App"
creative_generator.py  [--mix N] ["Competitor 1"] ["Competitor 2"]
notion_publisher.py  ["Competitor"] | --rename
airtable_updater.py  [--dry-run]
```

---

## GitHub Actions setup

**1. Fork / clone this repo to your GitHub account.**

**2. Add secrets** in `Settings → Secrets → Actions`:

| Secret | Where to get it |
|---|---|
| `AIRTABLE_TOKEN` | [airtable.com/create/tokens](https://airtable.com/create/tokens) |
| `AIRTABLE_BASE_ID` | URL of your base: `airtable.com/appXXXX/...` |
| `AIRTABLE_TABLE_ID` | URL of your table: `.../tblXXXX/...` |
| `NOTION_TOKEN` | [notion.so/my-integrations](https://www.notion.so/my-integrations) |
| `NOTION_DATABASE_ID` | Share your Notion DB → copy ID from URL |
| `NOTION_CREATIVES_DB_ID` | Same, for the Generated Creatives database |
| `GROQ_API_KEY` | [console.groq.com/keys](https://console.groq.com/keys) |
| `GEMINI_API_KEY` | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) *(optional)* |

**3. Run manually:** `Actions → Ad Intelligence Pipeline → Run workflow`

You can override apps, country, limit, and ranking strategy from the GitHub UI without touching code.

The pipeline runs automatically every Monday at 9 AM UTC.

---

## Naming system

Every ad record uses a consistent format across Airtable and Notion:

```
{App} [{Country}] {Month Year} — {hook technique}

Example: Calm [US] Jan 2026 — statement open — leads directly with value or claim
```

To change the format, edit `NAME_FORMAT` in `notion_publisher.py` and run:
```bash
python3 notion_publisher.py --rename
```

---

## Requirements

- Python 3.9+
- A Meta account is **not** required — Meta Ads Library is publicly accessible
- Airtable, Notion, and Groq free tiers are sufficient to run the pipeline
