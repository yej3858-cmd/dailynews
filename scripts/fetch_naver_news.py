#!/usr/bin/env python3
"""Fetch Korean news candidates from Naver Search API.

Outputs:
- data/news_candidates.json
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from html import unescape
from pathlib import Path
from typing import Any

import requests
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
UTC = ZoneInfo("UTC")

NAVER_NEWS_URL = "https://openapi.naver.com/v1/search/news.json"
NAVER_DATALAB_URL = "https://openapi.naver.com/v1/datalab/search"

CATEGORIES = ["정치", "경제", "사회", "국제", "기술", "산업"]
SEMICONDUCTOR_KEYWORDS = [
    "반도체",
    "HBM",
    "SK하이닉스",
    "삼성전자",
    "EUV",
    "파운드리",
    "D램",
    "낸드",
    "AI 반도체",
]


@dataclass
class NewsItem:
    uid: str
    category: str
    query: str
    title: str
    description: str
    link: str
    originallink: str
    pub_date: str
    pub_date_kst: str
    outlet: str
    matched_keywords: list[str]
    is_semiconductor: bool


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _strip_html(text: str) -> str:
    text = unescape(text or "")
    return re.sub(r"<[^>]+>", "", text).strip()


def _extract_outlet(link: str) -> str:
    # Naver often rewrites links. Use domain as best-effort outlet name.
    clean = re.sub(r"^https?://", "", link)
    return clean.split("/")[0].replace("www.", "") or "알 수 없음"


def _parse_pub_date(pub_date: str) -> tuple[str, str]:
    # Naver format example: Tue, 16 Jan 2024 10:21:00 +0900
    dt = datetime.strptime(pub_date, "%a, %d %b %Y %H:%M:%S %z")
    dt_utc = dt.astimezone(UTC)
    dt_kst = dt.astimezone(KST)
    return dt_utc.isoformat(), dt_kst.isoformat()


def _headers() -> dict[str, str]:
    return {
        "X-Naver-Client-Id": _require_env("NAVER_CLIENT_ID"),
        "X-Naver-Client-Secret": _require_env("NAVER_CLIENT_SECRET"),
    }


def fetch_news_for_query(query: str, display: int = 50, pages: int = 2) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for page in range(pages):
        start = 1 + page * display
        params = {
            "query": query,
            "display": display,
            "start": start,
            "sort": "date",
        }
        response = requests.get(
            NAVER_NEWS_URL,
            params=params,
            headers=_headers(),
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        page_items = payload.get("items", [])
        if not page_items:
            break
        items.extend(page_items)
    return items


def fetch_trend_scores(keywords: list[str]) -> dict[str, float]:
    """Fetch optional Naver Datalab trend scores.

    Returns normalized score (0-1) per keyword. If request fails, returns {}.
    """
    end_date = datetime.now(tz=KST).date()
    start_date = end_date - timedelta(days=7)
    keyword_groups = [{"groupName": kw, "keywords": [kw]} for kw in keywords]
    body = {
        "startDate": start_date.isoformat(),
        "endDate": end_date.isoformat(),
        "timeUnit": "date",
        "keywordGroups": keyword_groups,
    }

    try:
        response = requests.post(
            NAVER_DATALAB_URL,
            headers={**_headers(), "Content-Type": "application/json"},
            json=body,
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return {}

    trend_scores: dict[str, float] = {}
    for result in payload.get("results", []):
        keyword = result.get("title", "")
        data_points = result.get("data", [])
        if not data_points:
            continue
        latest_ratio = float(data_points[-1].get("ratio", 0.0))
        trend_scores[keyword] = max(0.0, min(1.0, latest_ratio / 100.0))
    return trend_scores


def build_news_items(raw_items: list[dict[str, Any]], category: str, query: str) -> list[NewsItem]:
    news_items: list[NewsItem] = []
    now_kst = datetime.now(tz=KST)
    cutoff_kst = now_kst - timedelta(hours=24)
    for raw in raw_items:
        title = _strip_html(raw.get("title", ""))
        description = _strip_html(raw.get("description", ""))
        originallink = raw.get("originallink", "")
        link = raw.get("link", "")
        pub_raw = raw.get("pubDate", "")
        if not title or not link or not pub_raw:
            continue

        try:
            pub_date_utc, pub_date_kst = _parse_pub_date(pub_raw)
        except ValueError:
            continue
        pub_kst_dt = datetime.fromisoformat(pub_date_kst)
        if pub_kst_dt < cutoff_kst or pub_kst_dt > now_kst:
            continue

        text_blob = f"{title} {description} {query}".lower()
        matched_keywords = [kw for kw in SEMICONDUCTOR_KEYWORDS if kw.lower() in text_blob]
        is_semiconductor = bool(matched_keywords or category == "반도체")

        uid_source = (originallink or link) + title
        uid = hashlib.sha1(uid_source.encode("utf-8")).hexdigest()

        news_items.append(
            NewsItem(
                uid=uid,
                category=category,
                query=query,
                title=title,
                description=description,
                link=link,
                originallink=originallink,
                pub_date=pub_date_utc,
                pub_date_kst=pub_date_kst,
                outlet=_extract_outlet(originallink or link),
                matched_keywords=matched_keywords,
                is_semiconductor=is_semiconductor,
            )
        )
    return news_items


def dedupe(items: list[NewsItem]) -> list[NewsItem]:
    deduped: dict[str, NewsItem] = {}
    for item in items:
        key = item.originallink or item.link
        existing = deduped.get(key)
        if existing is None:
            deduped[key] = item
            continue
        # Keep newer article copy if duplicates exist.
        if item.pub_date > existing.pub_date:
            deduped[key] = item
    return list(deduped.values())


def main() -> None:
    all_items: list[NewsItem] = []

    for category in CATEGORIES:
        raw_items = fetch_news_for_query(category)
        all_items.extend(build_news_items(raw_items, category=category, query=category))

    for keyword in SEMICONDUCTOR_KEYWORDS:
        raw_items = fetch_news_for_query(keyword, display=30, pages=1)
        all_items.extend(build_news_items(raw_items, category="반도체", query=keyword))

    all_items = dedupe(all_items)
    trend_scores = fetch_trend_scores(SEMICONDUCTOR_KEYWORDS)

    output = {
        "generated_at_kst": datetime.now(tz=KST).isoformat(),
        "source": "Naver Search News API",
        "trend_source": "Naver Datalab Search Trend API",
        "items": [asdict(item) for item in all_items],
        "trend_scores": trend_scores,
    }

    Path("data").mkdir(exist_ok=True)
    Path("data/news_candidates.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"Saved {len(all_items)} unique candidates to data/news_candidates.json")


if __name__ == "__main__":
    main()
