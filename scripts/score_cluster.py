#!/usr/bin/env python3
"""Cluster, rank, and select top stories for the daily briefing.

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
    "반도체": 2.2,
    "hbm": 2.3,
    "sk하이닉스": 2.0,
    "삼성전자": 2.0,
    "euv": 1.7,
    "파운드리": 1.8,
    "d램": 1.6,
    "낸드": 1.5,
    "ai 반도체": 2.4,
    "투자": 1.5,
    "증설": 1.5,
    "수율": 1.5,
    "공급망": 1.7,
}

HIGH_IMPACT_KEYWORDS = {
    "정책": 2.5,
    "법안": 2.3,
    "규제": 2.2,
    "금리": 2.4,
    "인플레이션": 2.3,
    "환율": 2.2,
    "무역": 2.2,
    "관세": 2.2,
    "제재": 2.3,
    "에너지": 2.2,
    "국제유가": 2.3,
    "전쟁": 2.5,
    "외교": 2.1,
    "정상회담": 2.2,
    "예산": 2.2,
    "선거": 2.1,
    "대통령": 2.0,
    "총리": 1.9,
    "경제성장": 2.2,
    "수출": 2.0,
    "고용": 2.0,
}

LOW_IMPACT_KEYWORDS = {
    "인터뷰": -1.3,
    "화보": -1.6,
    "비하인드": -1.3,
    "리뷰": -1.2,
    "컬렉션": -1.1,
    "연예": -1.4,
    "예능": -1.5,
    "브이로그": -1.5,
    "행사": -0.9,
}

CATEGORY_PRIORITY = {
    "정치": 0.8,
    "경제": 1.1,
    "사회": 0.8,
    "국제": 1.0,
    "기술": 0.7,
    "산업": 0.9,
    "반도체": 1.2,
}


def tokenize(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[가-힣A-Za-z0-9]+", text.lower())
        if len(token) > 1
    }


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def story_similarity(a: dict[str, Any], b: dict[str, Any]) -> float:
    a_text = tokenize(f"{a['title']} {a.get('description', '')} {a.get('query', '')}")
    b_text = tokenize(f"{b['title']} {b.get('description', '')} {b.get('query', '')}")
    text_sim = jaccard(a_text, b_text)

    a_kw = set(k.lower() for k in a.get("matched_keywords", []))
    b_kw = set(k.lower() for k in b.get("matched_keywords", []))
    kw_sim = jaccard(a_kw, b_kw)

    same_category = 1.0 if a.get("category") == b.get("category") else 0.0
    return text_sim * 0.78 + kw_sim * 0.15 + same_category * 0.07


def cluster_items(items: list[dict[str, Any]], threshold: float = 0.30) -> list[list[dict[str, Any]]]:
    """Aggressive clustering for overlapping reports."""
    clusters: list[list[dict[str, Any]]] = []
    for item in items:
        best_idx = -1
        best_sim = 0.0
        for i, cluster in enumerate(clusters):
            sims = [story_similarity(item, existing) for existing in cluster[:3]]
            sim = sum(sims) / len(sims)
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
    return math.exp(-delta_hours / 20)


def weighted_keyword_score(tokens: set[str], weight_map: dict[str, float]) -> float:
    score = 0.0
    for keyword, weight in weight_map.items():
        if keyword in tokens:
            score += weight
    return score


def importance_score(item: dict[str, Any], cluster: list[dict[str, Any]], trend_scores: dict[str, float], now: datetime) -> float:
    text_tokens = tokenize(f"{item['title']} {item.get('description', '')} {item.get('query', '')}")
    recency = recency_score(item["pub_date_kst"], now)

    cluster_size = len(cluster)
    unique_outlets = len({c.get("outlet", "") for c in cluster})

    high_impact = weighted_keyword_score(text_tokens, HIGH_IMPACT_KEYWORDS)
    low_impact = weighted_keyword_score(text_tokens, LOW_IMPACT_KEYWORDS)
    semicon_strength = weighted_keyword_score(text_tokens, SEMICONDUCTOR_KEYWORDS)

    category_weight = CATEGORY_PRIORITY.get(item.get("category", ""), 0.0)

    trend_boost = 0.0
    for kw in item.get("matched_keywords", []):
        trend_boost = max(trend_boost, trend_scores.get(kw, 0.0))

    # Prefer broadly covered, high-impact national/international stories.
    score = 0.0
    score += recency * 1.9
    score += math.log1p(cluster_size) * 2.4
    score += math.log1p(unique_outlets) * 2.7
    score += high_impact * 0.85
    score += category_weight
    score += trend_boost * 1.2

    if item.get("is_semiconductor"):
        score += semicon_strength * 0.55 + 0.6

    score += low_impact  # negative weights reduce soft features.

    # Penalize repetitive single-outlet low-cluster stories.
    if cluster_size <= 1 and unique_outlets <= 1:
        score -= 1.2

    return score


def assign_stars(score: float) -> int:
    if score >= 8.0:
        return 5
    if score >= 6.4:
        return 4
    if score >= 4.9:
        return 3
    if score >= 3.6:
        return 2
    return 1


def build_structured_summary(item: dict[str, Any], cluster: list[dict[str, Any]], score: float) -> dict[str, str]:
    top_keywords = item.get("matched_keywords", [])[:3]
    keyword_text = ", ".join(top_keywords) if top_keywords else "거시·정책 이슈"
    return {
        "핵심": f"{item['title'][:42]}",
        "배경": f"{item.get('category', '일반')} 분야 핵심 변수 변화가 반영된 사안입니다.",
        "확산": f"유사 기사 {len(cluster)}건, 매체 {len({c.get('outlet','') for c in cluster})}곳에서 동시 보도됐습니다.",
        "포인트": f"주요 키워드: {keyword_text}.",
        "종합": f"영향도 점수 {score:.2f}로 오늘 상위 이슈로 선정했습니다.",
    }


def build_article_5lines(item: dict[str, Any], cluster: list[dict[str, Any]], score: float) -> list[str]:
    return [
        f"1) {item.get('category', '일반')} 핵심 사안으로 분류됩니다.",
        f"2) 대표 제목은 ‘{item['title'][:34]}’ 입니다.",
        f"3) 중복 기사 {len(cluster)}건을 묶어 이슈 단위로 정리했습니다.",
        f"4) 영향도 점수는 {score:.2f}, 중요도는 {assign_stars(score)}성입니다.",
        "5) 정책·시장·국제 파급 가능성을 중심으로 우선 배치했습니다.",
    ]


def build_cluster_record(cluster: list[dict[str, Any]], trend_scores: dict[str, float], now: datetime) -> dict[str, Any]:
    representative = sorted(cluster, key=lambda x: x["pub_date_kst"], reverse=True)[0]
    score = importance_score(representative, cluster, trend_scores, now)

    representative["related_count"] = len(cluster)
    representative["outlet_count"] = len({item.get("outlet", "") for item in cluster})
    representative["categories_merged"] = sorted({item.get("category", "일반") for item in cluster})
    representative["score"] = round(score, 4)
    representative["importance_stars"] = assign_stars(score)
    representative["major_keywords"] = representative.get("matched_keywords", [])[:5]
    representative["structured_summary"] = build_structured_summary(representative, cluster, score)
    representative["article_summary_5lines"] = build_article_5lines(representative, cluster, score)
    return representative


def make_top_summary(main_items: list[dict[str, Any]], semicon_items: list[dict[str, Any]]) -> list[str]:
    if not main_items:
        return [
            "오늘 상위 이슈를 구성할 기사 데이터가 부족합니다.",
            "잠시 후 재생성 시 더 많은 기사 반영이 가능합니다.",
            "반도체 섹션은 별도 키워드 우선순위로 유지됩니다.",
        ]

    return [
        f"최상위 이슈: {main_items[0].get('category','일반')} · {main_items[0]['title'][:30]}",
        f"국가/국제·정책·거시경제 파급력이 큰 뉴스 10건을 우선 선별했습니다.",
        f"반도체 투자·생산·공급망 중심 뉴스 {len(semicon_items)}건을 별도 구성했습니다.",
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
    merged = [build_cluster_record(cluster, trend_scores, now) for cluster in clusters]
    merged.sort(key=lambda x: x["score"], reverse=True)

    semiconductor = [item for item in merged if item.get("is_semiconductor")]
    main_candidates = [item for item in merged if not item.get("is_semiconductor")]

    if len(main_candidates) < 10:
        main_candidates.extend([item for item in semiconductor if item not in main_candidates])

    main_items = main_candidates[:10]
    semicon_items = semiconductor[:3]

    output = {
        "generated_at_kst": now.isoformat(),
        "date": now.date().isoformat(),
        "top_summary": make_top_summary(main_items, semicon_items),
        "main_news": main_items,
        "semiconductor_news": semicon_items,
        "stats": {
            "raw_candidates": len(items),
            "clustered_groups": len(clusters),
            "trend_boost_enabled": bool(trend_scores),
        },
    }

    Path("data").mkdir(exist_ok=True)
    Path("data/scored_news.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("Saved scoring output to data/scored_news.json")


if __name__ == "__main__":
    main()
