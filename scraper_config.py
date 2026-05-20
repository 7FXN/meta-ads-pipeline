# scraper_config.py
ADS_LIBRARY_URL = (
    "https://www.facebook.com/ads/library/"
    "?active_status=active&ad_type=all&country={country}"
    "&q={query}&search_type=page{media_type}"
)
ADS_LIBRARY_KEYWORD_URL = (
    "https://www.facebook.com/ads/library/"
    "?active_status=active&ad_type=all&country={country}"
    "&q={query}&search_type=keyword_unordered{media_type}"
)
ADS_LIBRARY_PAGE_ID_URL = (
    "https://www.facebook.com/ads/library/"
    "?active_status=active&ad_type=all&country=ALL"
    "&view_all_page_id={page_id}{media_type}"
)

MEDIA_TYPE_PARAM = {
    "static":   "",                   # images + memes — no URL pre-filter, client-side drops videos
    "images":   "&media_type=image",  # plain image ads only
    "memes":    "&media_type=meme",   # meme/text-overlay ads only
    "video":    "&media_type=video",
    "combined": "",
}

RANK_BY_CHOICES   = ("combined", "age", "order", "impressions", "copies")
FILTER_CHOICES    = ("static", "images", "memes", "video", "combined")
SEARCH_BY_CHOICES = ("page", "keyword")

UA_MONTHS = {
    "січ": 1, "лют": 2, "бер": 3, "кві": 4, "трав": 5, "черв": 6,
    "лип": 7, "серп": 8, "вер": 9, "жовт": 10, "лист": 11, "груд": 12,
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

        // Impression range
        const impMatch = text.match(
            /([\\d,.]+[KMk]?\\s*[-–]\\s*[\\d,.]+[KMk]?\\s*(?:impressions?|показів|тис\\.?|млн\\.?)|(?:over|>)\\s*[\\d,.]+[KMk]?M?\\s*(?:impressions?|показів)?)/i
        );
        const impressionText = impMatch ? impMatch[0].trim() : null;

        // Identical copies running
        const copiesMatch = text.match(/(\\d+)\\s+(?:identical|однакових)/i)
                         || text.match(/(?:identical|однакових)[^\\d]*(\\d+)/i);
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
