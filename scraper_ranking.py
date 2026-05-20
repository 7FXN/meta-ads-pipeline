# scraper_ranking.py
import re
from scraper_config import UA_MONTHS


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
        return to_int(over.group(1)) * 2

    rng = re.search(r"([\d.]+[km]?)[-–]([\d.]+[km]?)", text)
    if rng:
        return (to_int(rng.group(1)) + to_int(rng.group(2))) // 2

    single = re.search(r"([\d.]+[km]?)", text)
    return to_int(single.group(1)) if single else 0


def rank_to_score(rank: int, total: int) -> int:
    if total <= 1:
        return 5
    return round(5 - (rank / (total - 1)) * 4)


def score_ads_combined(ads: list) -> list:
    n = len(ads)
    if n == 0:
        return ads

    by_age = sorted(range(n), key=lambda i: parse_date_sort_key(ads[i].get("start_date", "")))
    age_scores = [0] * n
    for rank, idx in enumerate(by_age):
        age_scores[idx] = rank_to_score(rank, n)

    order_scores = [rank_to_score(i, n) for i in range(n)]

    by_imp = sorted(range(n), key=lambda i: parse_impression_rank(ads[i].get("impression_text", "")), reverse=True)
    imp_scores = [0] * n
    for rank, idx in enumerate(by_imp):
        imp_scores[idx] = rank_to_score(rank, n)

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
