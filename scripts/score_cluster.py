#!/usr/bin/env python3
"""Cluster, score, and select stories for the daily briefing.

Inputs:
- data/news_candidates.json

Outputs:
- data/scored_news.json
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")

SEMICONDUCTOR_KEYWORDS = {
    "반도체": 2.0,
    "hbm": 2.0,
    "sk하이닉스": 1.8,
    "삼성전자": 1.7,
    "euv": 1.5,
    "파운드리": 1.5,
    "d램": 1.3,
    "낸드": 1.3,
    "ai 반도체": 2.2,
}


def tokenize(text: str) -> set[str]:
    return {
        t
        for t in re.findall(r"[가-힣A-Za-z0-9]+", text.lower())
        if len(t) > 1
    }


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def story_similarity(a: dict[str, Any], b: dict[str, Any]) -> float:
    a_title = tokenize(a["title"])
    b_title = tokenize(b["title"])
    title_sim = jaccard(a_title, b_title)

    a_kw = set(k.lower() for k in a.get("matched_keywords", []))
    b_kw = set(k.lower() for k in b.get("matched_keywords", []))
    kw_sim = jaccard(a_kw, b_kw)

    return title_sim * 0.75 + kw_sim * 0.25


def cluster_items(items: list[dict[str, Any]], threshold: float = 0.38) -> list[list[dict[str, Any]]]:
    clusters: list[list[dict[str, Any]]] = []
    for item in items:
        best_idx = -1
        best_sim = 0.0
        for i, cluster in enumerate(clusters):
            rep = cluster[0]
            sim = story_similarity(item, rep)
            if sim > best_sim:
                best_sim = sim
                best_idx = i

        if best_idx >= 0 and best_sim >= threshold:
            clusters[best_idx].append(item)
        else:
            clusters.append([item])

    return clusters


def recency_score(pub_date_kst: str, now: datetime) -> float:
    published = datetime.fromisoformat(pub_date_kst)
    delta_hours = max(0.0, (now - published).total_seconds() / 3600)
    return math.exp(-delta_hours / 18)


def keyword_strength(item: dict[str, Any]) -> float:
    tokens = tokenize(f"{item['title']} {item.get('description', '')}")
    score = 0.0
    for kw, weight in SEMICONDUCTOR_KEYWORDS.items():
        if kw in tokens or kw in (item.get("query", "").lower()):
            score += weight
    score += len(item.get("matched_keywords", [])) * 0.4
    return score


def summarize_item(item: dict[str, Any], cluster_size: int, score: float) -> list[str]:
    keywords = item.get("matched_keywords", [])[:3]
    kw_text = ", ".join(keywords) if keywords else "주요 이슈"
    return [
        f"핵심: {item['title'][:54]}",
        f"배경: {item.get('category', '일반')} 분야에서 다수 매체가 동시 보도했습니다.",
        f"확산: 유사 기사 {cluster_size}건이 묶여 이슈 강도가 높게 평가되었습니다.",
        f"포인트: {kw_text} 관련 키워드가 확인되었습니다.",
        f"종합: 중요도 점수 {score:.2f}로 오늘 브리핑 상위권에 반영되었습니다.",
    ]


def assign_stars(score: float) -> int:
    if score >= 4.2:
        return 5
    if score >= 3.3:
        return 4
    if score >= 2.5:
        return 3
    if score >= 1.8:
        return 2
    return 1


def build_cluster_record(cluster: list[dict[str, Any]], trend_scores: dict[str, float], now: datetime) -> dict[str, Any]:
    sorted_cluster = sorted(cluster, key=lambda x: x["pub_date_kst"], reverse=True)
    representative = sorted_cluster[0]

    recency = recency_score(representative["pub_date_kst"], now)
    cluster_power = math.log1p(len(cluster))
    kw_strength = keyword_strength(representative)

    semicon_priority = 1.2 if representative.get("is_semiconductor") else 0.0
    trend_boost = 0.0
    for kw in representative.get("matched_keywords", []):
        trend_boost = max(trend_boost, trend_scores.get(kw, 0.0))

    total_score = recency * 2.2 + cluster_power * 1.6 + kw_strength * 0.35 + semicon_priority + trend_boost

    categories = sorted(set(item.get("category", "일반") for item in cluster))
    representative["related_count"] = len(cluster)
    representative["categories_merged"] = categories
    representative["score"] = round(total_score, 4)
    representative["importance_stars"] = assign_stars(total_score)
    representative["summary_lines"] = summarize_item(representative, len(cluster), total_score)
    return representative


def make_top_summary(main_items: list[dict[str, Any]], semicon_items: list[dict[str, Any]]) -> list[str]:
    if not main_items:
        return [
            "오늘은 수집된 기사가 부족해 간략 브리핑으로 제공됩니다.",
            "잠시 후 다시 새로고침하면 더 많은 기사가 반영될 수 있습니다.",
            "반도체 섹션은 별도 키워드로 우선 수집됩니다.",
        ]

    top_title = main_items[0]["title"]
    top_cat = main_items[0].get("category", "일반")
    semicon_count = len(semicon_items)

    return [
        f"오늘의 최상위 이슈는 {top_cat} 분야의 ‘{top_title[:26]}’ 입니다.",
        f"주요 뉴스 {len(main_items)}건과 반도체 특화 뉴스 {semicon_count}건을 선별했습니다.",
        "중복 보도를 클러스터링해 핵심 이슈 중심으로 압축 제공했습니다.",
    ]


def main() -> None:
    source_path = Path("data/news_candidates.json")
    if not source_path.exists():
        raise FileNotFoundError("Missing data/news_candidates.json. Run fetch_naver_news.py first.")

    payload = json.loads(source_path.read_text(encoding="utf-8"))
    items = payload.get("items", [])
    trend_scores = payload.get("trend_scores", {})
    now = datetime.now(tz=KST)

    clusters = cluster_items(items)
    merged_items = [build_cluster_record(cluster, trend_scores, now) for cluster in clusters]
    merged_items.sort(key=lambda x: x["score"], reverse=True)

    semiconductor_items = [item for item in merged_items if item.get("is_semiconductor")]
    main_pool = [item for item in merged_items if not item.get("is_semiconductor")]

    if len(main_pool) < 10:
        supplement = [item for item in semiconductor_items if item not in main_pool]
        main_pool.extend(supplement)

    main_items = main_pool[:10]
    semicon_top = semiconductor_items[:3]

    output = {
        "generated_at_kst": now.isoformat(),
        "date": now.date().isoformat(),
        "top_summary": make_top_summary(main_items, semicon_top),
        "main_news": main_items,
        "semiconductor_news": semicon_top,
        "stats": {
            "raw_candidates": len(items),
            "clustered_groups": len(clusters),
            "trend_boost_enabled": bool(trend_scores),
        },
    }

    Path("data/scored_news.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("Saved scoring output to data/scored_news.json")


if __name__ == "__main__":
    main()
