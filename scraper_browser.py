# scraper_browser.py
import urllib.request
from pathlib import Path

from scraper_config import (
    ADS_LIBRARY_URL, ADS_LIBRARY_KEYWORD_URL, ADS_LIBRARY_PAGE_ID_URL,
    MEDIA_TYPE_PARAM, EXTRACTION_JS,
)
from scraper_ranking import (
    score_ads_combined, parse_date_sort_key, parse_impression_rank,
)


async def download_image(url: str, dest: Path) -> bool:
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


async def scrape_competitor(
    page,
    competitor: str,
    search_query: str,
    page_patterns: list,
    limit: int = 6,
    country: str = "US",
    page_id: str = None,
    rank_by: str = "age",
    filter_type: str = "static",
    search_by: str = "page",
) -> list:
    mt = MEDIA_TYPE_PARAM.get(filter_type, "")
    if page_id:
        url = ADS_LIBRARY_PAGE_ID_URL.format(page_id=page_id, media_type=mt)
    elif search_by == "keyword":
        url = ADS_LIBRARY_KEYWORD_URL.format(query=search_query.replace(" ", "+"), country=country, media_type=mt)
    else:
        url = ADS_LIBRARY_URL.format(query=search_query.replace(" ", "+"), country=country, media_type=mt)
    print(f"\n[{competitor}] {url}")

    await page.goto(url, wait_until="networkidle", timeout=60000)
    await page.wait_for_timeout(5000)

    for _ in range(4):
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(2000)

    ads = await page.evaluate(EXTRACTION_JS)

    if search_by == "keyword":
        filtered = ads
        print(f"  Found {len(filtered)} ads matching keyword '{search_query}'")
    else:
        def matches_page(ad):
            name = (ad.get("page_name") or "").lower()
            return any(p.lower() in name for p in page_patterns)

        filtered = [a for a in ads if matches_page(a)]
        if not filtered and ads:
            print("  No exact page match — 0 ads kept (use --page-id to target a specific page)")
            return []

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
    else:
        rank_label = "page order (Meta's relevance)"

    print(f"  Found {len(filtered)} matched ads (from {len(ads)} total), targeting {limit} by {rank_label}:")

    result  = []
    checked = 0
    max_check = min(len(filtered), limit * 6)

    for ad in filtered[:max_check]:
        if len(result) >= limit:
            break

        checked  += 1
        rank_pos  = filtered.index(ad)
        if rank_by == "combined":
            signal = (f"score {ad['_score_total']}/20  "
                      f"age:{ad['_score_age']} order:{ad['_score_order']} "
                      f"imp:{ad['_score_impressions']} copies:{ad['_score_copies']}")
        else:
            signal = {
                "age":         f"started {ad.get('start_date', '?')}",
                "impressions": f"~{ad.get('impression_text') or 'unknown'} impressions",
                "copies":      f"{ad.get('copies', 1)} copies running",
                "order":       f"position #{rank_pos+1} on page",
            }.get(rank_by, "")
        print(f"  #{rank_pos+1} [{signal}] {ad.get('page_name')} — {ad.get('ad_copy', '')[:55]}...")

        if not ad.get("image_url") and ad.get("library_id"):
            detail_url = f"https://www.facebook.com/ads/library/?id={ad['library_id']}"
            try:
                await page.goto(detail_url, wait_until="networkidle", timeout=30000)
                await page.wait_for_timeout(3000)
                await page.evaluate("""() => {
                    const btn = Array.from(document.querySelectorAll('div[role=button],button'))
                        .find(b => b.innerText && /see ad detail|version/i.test(b.innerText));
                    if (btn) btn.click();
                }""")
                await page.wait_for_timeout(2000)
                img_url = await page.evaluate("""() => {
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
                    print("    [detail] Got image")
                else:
                    print("    [detail] No image — video, skipping")
            except Exception as e:
                print(f"    [detail] Error: {e}")

        ad["ad_type"] = "static" if ad.get("image_url") else "video"

        if filter_type == "static" and ad["ad_type"] != "static":
            continue
        if filter_type == "video" and ad["ad_type"] != "video":
            continue

        result.append(ad)

    if filter_type == "combined":
        videos  = sum(1 for a in result if a["ad_type"] == "video")
        statics = len(result) - videos
        print(f"  Collected {len(result)}/{limit} ads ({statics} static, {videos} video) after checking {checked}")
    else:
        print(f"  Collected {len(result)}/{limit} {filter_type} ads after checking {checked} candidates")

    return result
