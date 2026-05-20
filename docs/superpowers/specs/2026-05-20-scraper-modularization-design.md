# Scraper Modularization Design

**Date:** 2026-05-20
**Goal:** Split `meta_ads_scraper.py` (657 lines) into focused modules so each concern lives in one obvious place.

## Constraint

`meta_ads_scraper.py` must remain the CLI entry point, callable exactly as before. The Telegram bot and GitHub Actions both invoke it by name via subprocess — no changes to callers.

## Approach: Flat file split (Option A)

Four new sibling files, all prefixed `scraper_` so they sort together in the directory listing.

### `scraper_config.py`
Pure data — no logic, no I/O, no imports beyond stdlib.
- URL template constants: `ADS_LIBRARY_URL`, `ADS_LIBRARY_KEYWORD_URL`, `ADS_LIBRARY_PAGE_ID_URL`
- `MEDIA_TYPE_PARAM` dict
- Choice tuples: `RANK_BY_CHOICES`, `FILTER_CHOICES`, `SEARCH_BY_CHOICES`
- `UA_MONTHS` dict
- `EXTRACTION_JS` string

### `scraper_ranking.py`
Pure functions — no I/O, no Playwright, no network calls.
- `parse_date_sort_key(date_str) -> tuple`
- `parse_impression_rank(imp_text) -> int`
- `rank_to_score(rank, total) -> int`
- `score_ads_combined(ads) -> list`

Imports: `re`, `scraper_config.UA_MONTHS`

### `scraper_browser.py`
All Playwright code. Async only.
- `download_image(url, dest) -> bool`
- `scrape_competitor(page, competitor, search_query, page_patterns, limit, country, page_id, rank_by, filter_type, search_by) -> list[dict]`

Imports: `scraper_config`, `scraper_ranking`, `playwright`, stdlib

### `scraper_airtable.py`
All Airtable code. `load_env()` lives here since Airtable is its only consumer.
- `load_env() -> dict`
- `airtable_upload(ads, competitor, country, search_by, require_copy) -> None`

Imports: `requests`, `scraper_config`, stdlib, `notion_publisher` (for name helpers)

### `meta_ads_scraper.py` (entry point, ~80 lines)
- Docstring with CLI usage
- Imports from all four modules
- `parse_args() -> tuple`
- `main()` — orchestration loop only

## What does NOT change
- CLI flags and defaults
- Airtable field names
- Notion publish subprocess call
- Output to `ads_data/`
- `airtable_upload()` signature
- `scrape_competitor()` signature
- `telegram_bot.py` — no changes needed
- `.github/workflows/scrape.yml` — no changes needed
