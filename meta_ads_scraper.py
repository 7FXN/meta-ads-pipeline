"""
Meta Ads Library scraper — pulls top active ads for any app/advertiser.

Usage:
  python3 meta_ads_scraper.py "Trivia Crack"
  python3 meta_ads_scraper.py "Duolingo" "Babbel"
  python3 meta_ads_scraper.py --limit 10 "Trivia Crack"
  python3 meta_ads_scraper.py --country ALL "Trivia Crack"
  python3 meta_ads_scraper.py --country US --limit 10 "QuizzLand" "TriviaScapes"
  python3 meta_ads_scraper.py --rank-by age "Trivia Crack"

--country:  US (default) | ALL | GB | DE | FR | UA | any 2-letter country code
--limit:    number of top ads to pull per app (default 6)
--rank-by:  how to define "top performer" — one of:
              combined    (default) scores every ad 1–5 on all four signals below,
                          sums to /20, picks the all-round winners
              age         oldest running ads first — Meta keeps serving them = proven winners
              order       first ads shown on the search results page — Meta's own relevance ranking
              impressions highest estimated impressions first — broadest reach
              copies      most identical ad copies running simultaneously — scaling signal
--filter:     which creative format to keep — one of:
              static      (default) image/static ads only
              video       video ads only
              combined    all formats
--no-copy-req: allow ads with no ad copy text to be uploaded (default: copy required)
--search-by:  how to search the Ads Library — one of:
              page        (default) search by advertiser page name
              keyword     search by keywords across ad copy text
"""

import asyncio
import json
import subprocess
import sys
from pathlib import Path

from playwright.async_api import async_playwright

from scraper_config import RANK_BY_CHOICES, FILTER_CHOICES, SEARCH_BY_CHOICES
from scraper_browser import scrape_competitor, download_image
from scraper_airtable import airtable_upload

OUTPUT_DIR = Path("ads_data")


def parse_args():
    args = sys.argv[1:]
    limit        = 6
    country      = "US"
    page_id      = None
    rank_by      = "combined"
    filter_type  = "static"
    search_by    = "page"
    require_copy = True
    apps         = []
    i = 0
    while i < len(args):
        if args[i] == "--limit" and i + 1 < len(args):
            limit = int(args[i + 1])
            i += 2
        elif args[i] == "--country" and i + 1 < len(args):
            raw = args[i + 1].upper()
            country = "ALL" if raw in ("ALL", "ALL_COUNTRIES") else raw
            i += 2
        elif args[i] == "--page-id" and i + 1 < len(args):
            page_id = args[i + 1]
            i += 2
        elif args[i] == "--rank-by" and i + 1 < len(args):
            val = args[i + 1].lower()
            if val not in RANK_BY_CHOICES:
                print(f"Unknown --rank-by '{val}'. Choose from: {', '.join(RANK_BY_CHOICES)}")
                sys.exit(1)
            rank_by = val
            i += 2
        elif args[i] == "--filter" and i + 1 < len(args):
            val = args[i + 1].lower()
            if val not in FILTER_CHOICES:
                print(f"Unknown --filter '{val}'. Choose from: {', '.join(FILTER_CHOICES)}")
                sys.exit(1)
            filter_type = val
            i += 2
        elif args[i] == "--search-by" and i + 1 < len(args):
            val = args[i + 1].lower()
            if val not in SEARCH_BY_CHOICES:
                print(f"Unknown --search-by '{val}'. Choose from: {', '.join(SEARCH_BY_CHOICES)}")
                sys.exit(1)
            search_by = val
            i += 2
        elif args[i] == "--no-copy-req":
            require_copy = False
            i += 1
        else:
            apps.append(args[i])
            i += 1
    return apps, limit, country, page_id, rank_by, filter_type, search_by, require_copy


async def main():
    apps, limit, country, page_id, rank_by, filter_type, search_by, require_copy = parse_args()

    if not apps:
        print("Usage: python3 meta_ads_scraper.py [--country XX] [--limit N] [--page-id ID] [--rank-by STRATEGY] [--filter FORMAT] [--search-by METHOD] \"App Name\" ...")
        print("Examples:")
        print('  python3 meta_ads_scraper.py "Trivia Crack"')
        print('  python3 meta_ads_scraper.py --country ALL "Trivia Crack"')
        print('  python3 meta_ads_scraper.py --page-id 328627523855071 "Calm"')
        print('  python3 meta_ads_scraper.py --rank-by impressions "Duolingo"')
        print('  python3 meta_ads_scraper.py --filter video "Dressly"')
        print('  python3 meta_ads_scraper.py --search-by keyword "capsule wardrobe"')
        print(f"\n--rank-by choices:   {', '.join(RANK_BY_CHOICES)}  (default: combined)")
        print(f"--filter choices:    {', '.join(FILTER_CHOICES)}  (default: static)")
        print(f"--search-by choices: {', '.join(SEARCH_BY_CHOICES)}  (default: page)")
        sys.exit(0)

    OUTPUT_DIR.mkdir(exist_ok=True)

    print("=== Meta Ads Library Scraper ===")
    print(f"Apps: {', '.join(apps)}  |  country: {country}  |  limit: {limit} per app  |  rank-by: {rank_by}  |  filter: {filter_type}  |  search-by: {search_by}\n")

    all_results = {}

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"]
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()

        for app in apps:
            try:
                ads = await scrape_competitor(
                    page,
                    competitor=app,
                    search_query=app,
                    page_patterns=[app],
                    limit=limit,
                    country=country,
                    page_id=page_id if len(apps) == 1 else None,
                    rank_by=rank_by,
                    filter_type=filter_type,
                    search_by=search_by,
                )
                app_dir = OUTPUT_DIR / app.replace(" ", "_")
                app_dir.mkdir(exist_ok=True)

                await page.screenshot(path=str(app_dir / "snapshot.png"))

                for i, ad in enumerate(ads):
                    if ad.get("image_url"):
                        img_path = app_dir / f"ad_{i+1}.jpg"
                        ok = await download_image(ad["image_url"], img_path)
                        if ok:
                            ad["local_image"] = str(img_path)
                            print(f"    Image {i+1} saved: {img_path.name}")

                all_results[app] = ads
                airtable_upload(ads, competitor=app, country=country, search_by=search_by, require_copy=require_copy)

                try:
                    subprocess.run(
                        [sys.executable, "notion_publisher.py", app],
                        cwd=Path(__file__).parent,
                        check=True,
                    )
                except Exception as e:
                    print(f"  [Notion] Error: {e}")

                await asyncio.sleep(3)

            except Exception as e:
                print(f"  ERROR scraping {app}: {e}")
                all_results[app] = []

        await browser.close()

    output_file = OUTPUT_DIR / "raw_ads.json"
    existing = {}
    if output_file.exists():
        try:
            existing = json.loads(output_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    existing.update(all_results)
    output_file.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n✓ Saved to {output_file}")

    print("\n=== Summary ===")
    for app, ads in all_results.items():
        print(f"  {app}: {len(ads)} ads")

    return all_results


if __name__ == "__main__":
    asyncio.run(main())
