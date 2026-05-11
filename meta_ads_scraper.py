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
"""

import asyncio
import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from playwright.async_api import async_playwright

try:
    import requests as _requests
except ImportError:
    _requests = None

OUTPUT_DIR = Path("ads_data")
OUTPUT_DIR.mkdir(exist_ok=True)


def load_env():
    env = {}
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def airtable_upload(ads: list[dict], competitor: str, country: str):
    env = load_env()
    token = env.get("AIRTABLE_TOKEN")
    base_id = env.get("AIRTABLE_BASE_ID")
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
    url = f"https://api.airtable.com/v0/{base_id}/{table_id}"
    scraped_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Import name-building helpers from notion_publisher (same format as Notion titles)
    try:
        import sys as _sys
        from pathlib import Path as _Path
        _sys.path.insert(0, str(_Path(__file__).parent))
        from notion_publisher import analyze_hook as _analyze_hook, build_name as _build_name, format_date_dmy as _fmt_dmy
        _name_helpers = (_analyze_hook, _build_name, _fmt_dmy)
    except Exception:
        _name_helpers = None

    uploaded = 0
    for ad in ads:
        raw_date = ad.get("start_date") or ""
        ad_copy  = ad.get("ad_copy") or ""
        lib_id   = ad.get("library_id") or ""

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
        }

        # Attach image by URL — Airtable fetches and caches it
        img_url = ad.get("image_url")
        if img_url:
            fields["Image"] = [{"url": img_url}]

        resp = _requests.post(url, headers=headers, json={"fields": fields})
        if resp.status_code in (200, 201):
            uploaded += 1
        else:
            print(f"  [Airtable] Failed to upload ad {ad.get('library_id')}: {resp.text[:100]}")

    print(f"  [Airtable] Uploaded {uploaded}/{len(ads)} records")

ADS_LIBRARY_URL = (
    "https://www.facebook.com/ads/library/"
    "?active_status=active&ad_type=all&country={country}"
    "&q={query}&search_type=page"
)
ADS_LIBRARY_PAGE_ID_URL = (
    "https://www.facebook.com/ads/library/"
    "?active_status=active&ad_type=all&country=ALL"
    "&view_all_page_id={page_id}"
)

# Ukrainian month abbreviations → month number for sorting
UA_MONTHS = {
    "січ": 1, "лют": 2, "бер": 3, "кві": 4, "трав": 5, "черв": 6,
    "лип": 7, "серп": 8, "вер": 9, "жовт": 10, "лист": 11, "груд": 12,
    # English fallback
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

EXTRACTION_JS = """
() => {
    const results = [];
    const seenIds = new Set();
    const allDivs = Array.from(document.querySelectorAll('div'));

    allDivs.forEach(div => {
        const text = div.innerText || '';

        // Library ID: 15-18 digit number
        const idMatch = text.match(/[^\\d](\\d{15,18})[^\\d]/);
        if (!idMatch) return;
        const adId = idMatch[1];
        if (seenIds.has(adId)) return;

        // Must have a year (ad start date)
        if (!/202[3-6]/.test(text)) return;

        // Card size check — ad cards are roughly 300-500px wide
        const rect = div.getBoundingClientRect();
        if (rect.width < 150 || rect.width > 700) return;
        if (rect.height < 150) return;

        seenIds.add(adId);

        // Largest image in card
        const imgs = Array.from(div.querySelectorAll('img'))
            .filter(img => img.src && img.src.startsWith('http') && img.width > 40);
        const mainImg = imgs.sort((a,b)=>(b.naturalWidth||b.width||0)-(a.naturalWidth||a.width||0))[0];

        // Ad copy — longest text block, skip metadata/UI lines
        const SKIP = /\\d{10,}|Платформи|Platform|бібліотеки|Library ID|Початок|Started|оголошень|Переглянути|View ad|рекламний матеріал|Активна/i;
        const spans = Array.from(div.querySelectorAll('p,[dir=auto],span'))
            .map(el => el.innerText.trim())
            .filter(t => t.length > 20 && t.length < 800 && !SKIP.test(t));
        const adCopy = spans.sort((a,b)=>b.length-a.length)[0] || '';

        // Start date — number + month word + 4-digit year
        const dateMatch = text.match(/(\\d{1,2}\\s+\\S+\\.?\\s+202[3-6])/);
        const startDate = dateMatch ? dateMatch[1].trim() : (text.match(/202[3-6]/)?.[0] || null);

        // Page/advertiser name — first non-library link text
        const links = Array.from(div.querySelectorAll('a[href]'));
        const pageLink = links.find(a => !a.href.includes('/ads/library/') && a.innerText.trim().length > 1);
        const pageName = pageLink ? pageLink.innerText.trim().slice(0, 80) : null;

        // Ad Library detail URL
        const libLink = links.find(a => a.href.includes('/ads/library/'));
        const adLibraryUrl = libLink ? libLink.href : null;

        // Impression range — "1K–5K impressions" / "100K–200K показів" / "> 1M"
        const impMatch = text.match(
            /([\d,.]+[KMk]?\s*[-–]\s*[\d,.]+[KMk]?\s*(?:impressions?|показів|тис\.?|млн\.?)|(?:over|>)\s*[\d,.]+[KMk]?M?\s*(?:impressions?|показів)?)/i
        );
        const impressionText = impMatch ? impMatch[0].trim() : null;

        // Identical copies running — "5 identical ads" / "Запускаються 5 однакових"
        const copiesMatch = text.match(/(\d+)\s+(?:identical|однакових)/i)
                         || text.match(/(?:identical|однакових)[^\d]*(\d+)/i);
        const copies = copiesMatch ? parseInt(copiesMatch[1], 10) : 1;

        results.push({
            library_id: adId,
            image_url: mainImg ? mainImg.src : null,
            ad_copy: adCopy.slice(0, 400),
            start_date: startDate,
            page_name: pageName,
            ad_library_url: adLibraryUrl,
            impression_text: impressionText,
            copies: copies,
        });
    });

    return results;
}
"""


RANK_BY_CHOICES = ("combined", "age", "order", "impressions", "copies")


def parse_date_sort_key(date_str: str) -> tuple:
    if not date_str:
        return (9999, 99, 99)
    year_match = re.search(r"(202\d)", date_str)
    year = int(year_match.group(1)) if year_match else 9999
    month = 99
    for abbr, num in UA_MONTHS.items():
        if abbr in date_str.lower():
            month = num
            break
    day_match = re.match(r"(\d{1,2})", date_str.strip())
    day = int(day_match.group(1)) if day_match else 99
    return (year, month, day)


def parse_impression_rank(imp_text: str) -> int:
    """Convert '1K–5K impressions' or 'Over 1M' → a sortable integer (higher = more impressions)."""
    if not imp_text:
        return 0
    text = imp_text.lower().replace(",", "").replace(" ", "")

    def to_int(s: str) -> int:
        s = s.strip()
        if s.endswith("m"):
            return int(float(s[:-1]) * 1_000_000)
        if s.endswith("k"):
            return int(float(s[:-1]) * 1_000)
        try:
            return int(s)
        except ValueError:
            return 0

    over = re.search(r"(?:over|>)([\d.]+[km]?)", text)
    if over:
        return to_int(over.group(1)) * 2  # rank above any explicit range

    rng = re.search(r"([\d.]+[km]?)[-–]([\d.]+[km]?)", text)
    if rng:
        return (to_int(rng.group(1)) + to_int(rng.group(2))) // 2

    single = re.search(r"([\d.]+[km]?)", text)
    return to_int(single.group(1)) if single else 0


def rank_to_score(rank: int, total: int) -> int:
    """Map sorted rank (0 = best) to a 1–5 score via linear interpolation."""
    if total <= 1:
        return 5
    return round(5 - (rank / (total - 1)) * 4)


def score_ads_combined(ads: list) -> list:
    """
    Score every ad 1–5 on each of the four signals, attach scores, return ads
    sorted by total (max 20) descending.
    """
    n = len(ads)
    if n == 0:
        return ads

    # Age: oldest = rank 0 = score 5
    by_age = sorted(range(n), key=lambda i: parse_date_sort_key(ads[i].get("start_date", "")))
    age_scores = [0] * n
    for rank, idx in enumerate(by_age):
        age_scores[idx] = rank_to_score(rank, n)

    # Order: first on page = rank 0 = score 5 (DOM order preserved from JS)
    order_scores = [rank_to_score(i, n) for i in range(n)]

    # Impressions: highest = rank 0 = score 5
    by_imp = sorted(range(n), key=lambda i: parse_impression_rank(ads[i].get("impression_text", "")), reverse=True)
    imp_scores = [0] * n
    for rank, idx in enumerate(by_imp):
        imp_scores[idx] = rank_to_score(rank, n)

    # Copies: most running = rank 0 = score 5
    by_copies = sorted(range(n), key=lambda i: ads[i].get("copies", 1), reverse=True)
    copies_scores = [0] * n
    for rank, idx in enumerate(by_copies):
        copies_scores[idx] = rank_to_score(rank, n)

    for i, ad in enumerate(ads):
        ad["_score_age"]         = age_scores[i]
        ad["_score_order"]       = order_scores[i]
        ad["_score_impressions"] = imp_scores[i]
        ad["_score_copies"]      = copies_scores[i]
        ad["_score_total"]       = age_scores[i] + order_scores[i] + imp_scores[i] + copies_scores[i]

    ads.sort(key=lambda a: a["_score_total"], reverse=True)
    return ads


async def download_image(url: str, dest: Path):
    if not url or not url.startswith("http"):
        return False
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            dest.write_bytes(resp.read())
        return True
    except Exception as e:
        print(f"    Image download failed: {e}")
        return False


async def scrape_competitor(page, competitor: str, search_query: str, page_patterns: list, limit: int = 6, country: str = "US", page_id: str = None, rank_by: str = "age") -> list[dict]:
    if page_id:
        url = ADS_LIBRARY_PAGE_ID_URL.format(page_id=page_id)
    else:
        url = ADS_LIBRARY_URL.format(query=search_query.replace(" ", "+"), country=country)
    print(f"\n[{competitor}] {url}")

    await page.goto(url, wait_until="networkidle", timeout=60000)
    await page.wait_for_timeout(5000)

    for _ in range(4):
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(2000)

    ads = await page.evaluate(EXTRACTION_JS)

    # Keep only ads from the target advertiser page
    def matches_page(ad):
        name = (ad.get("page_name") or "").lower()
        return any(p.lower() in name for p in page_patterns)

    filtered = [a for a in ads if matches_page(a)]
    if not filtered and ads:
        # Fall back to all results if no exact match (e.g. page not advertising much)
        print(f"  No exact page match — keeping all {len(ads)} results")
        filtered = ads

    # Rank ads according to chosen strategy
    if rank_by == "combined":
        filtered = score_ads_combined(filtered)
        rank_label = "combined score /20 (age + order + impressions + copies)"
    elif rank_by == "age":
        filtered.sort(key=lambda a: parse_date_sort_key(a.get("start_date", "")))
        rank_label = "age (oldest first)"
    elif rank_by == "impressions":
        filtered.sort(key=lambda a: parse_impression_rank(a.get("impression_text", "")), reverse=True)
        rank_label = "impressions (highest first)"
    elif rank_by == "copies":
        filtered.sort(key=lambda a: a.get("copies", 1), reverse=True)
        rank_label = "copies (most identical running first)"
    else:  # "order" — keep DOM order, Meta's own ranking
        rank_label = "page order (Meta's relevance)"

    top = filtered[:limit]
    print(f"  Found {len(filtered)} matched ads (from {len(ads)} total), top {len(top)} by {rank_label}:")
    for i, ad in enumerate(top):
        if rank_by == "combined":
            signal = (
                f"score {ad['_score_total']}/20  "
                f"age:{ad['_score_age']} "
                f"order:{ad['_score_order']} "
                f"imp:{ad['_score_impressions']} "
                f"copies:{ad['_score_copies']}"
            )
        else:
            signal = {
                "age":         f"started {ad.get('start_date', '?')}",
                "impressions": f"~{ad.get('impression_text') or 'unknown'} impressions",
                "copies":      f"{ad.get('copies', 1)} copies running",
                "order":       f"position #{i+1} on page",
            }.get(rank_by, "")
        print(f"    {i+1}. [{signal}] {ad.get('page_name')} — {ad.get('ad_copy', '')[:60]}...")

    # For ads without an image (multi-version cards), visit the detail page to extract it
    for ad in top:
        if not ad.get("image_url") and ad.get("library_id"):
            detail_url = f"https://www.facebook.com/ads/library/?id={ad['library_id']}"
            try:
                await page.goto(detail_url, wait_until="networkidle", timeout=30000)
                await page.wait_for_timeout(3000)
                # Click "See ad details" to expand all creative versions
                await page.evaluate("""() => {
                    const btn = Array.from(document.querySelectorAll('div[role=button],button'))
                        .find(b => b.innerText && /see ad detail|version/i.test(b.innerText));
                    if (btn) btn.click();
                }""")
                await page.wait_for_timeout(2000)
                img_url = await page.evaluate("""() => {
                    // Exclude profile/avatar images (t39.30808), only take ad creatives (t39.35426 / t45.5)
                    const imgs = Array.from(document.querySelectorAll('img'))
                        .filter(img => img.src
                            && img.src.includes('fbcdn')
                            && !img.src.includes('t39.30808')
                            && img.naturalWidth > 300);
                    imgs.sort((a,b) => (b.naturalWidth||0) - (a.naturalWidth||0));
                    return imgs[0] ? imgs[0].src : null;
                }""")
                if img_url:
                    ad["image_url"] = img_url
                    print(f"    [detail] Got image for {ad['library_id']}")
                else:
                    print(f"    [detail] No image found for {ad['library_id']} — skipping")
            except Exception as e:
                print(f"    [detail] Error fetching {ad['library_id']}: {e}")

    # Drop ads that still have no image — they are likely video or carousel ads
    image_ads = [a for a in top if a.get("image_url")]
    skipped = len(top) - len(image_ads)
    if skipped:
        print(f"  Dropped {skipped} non-image ad(s) after detail check")

    return image_ads


def parse_args():
    args = sys.argv[1:]
    limit = 6
    country = "US"
    page_id = None
    rank_by = "combined"
    apps = []
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
        else:
            apps.append(args[i])
            i += 1
    return apps, limit, country, page_id, rank_by


async def main():
    apps, limit, country, page_id, rank_by = parse_args()

    if not apps:
        print("Usage: python3 meta_ads_scraper.py [--country XX] [--limit N] [--page-id ID] [--rank-by STRATEGY] \"App Name\" ...")
        print("Examples:")
        print('  python3 meta_ads_scraper.py "Trivia Crack"')
        print('  python3 meta_ads_scraper.py --country ALL "Trivia Crack"')
        print('  python3 meta_ads_scraper.py --page-id 328627523855071 "Calm"')
        print('  python3 meta_ads_scraper.py --rank-by impressions "Duolingo"')
        print('  python3 meta_ads_scraper.py --rank-by copies "Duolingo"')
        print('  python3 meta_ads_scraper.py --rank-by order "Duolingo"')
        print(f"\n--rank-by choices: {', '.join(RANK_BY_CHOICES)}  (default: combined)")
        sys.exit(0)

    print("=== Meta Ads Library Scraper ===")
    print(f"Apps: {', '.join(apps)}  |  country: {country}  |  limit: {limit} per app  |  rank-by: {rank_by}\n")

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
                # Use the app name as both the search query and the page pattern
                ads = await scrape_competitor(
                    page,
                    competitor=app,
                    search_query=app,
                    page_patterns=[app],
                    limit=limit,
                    country=country,
                    page_id=page_id if len(apps) == 1 else None,
                    rank_by=rank_by,
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
                airtable_upload(ads, competitor=app, country=country)
                # Publish analysis to Notion
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

    # Merge into existing raw_ads.json so reruns accumulate
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
