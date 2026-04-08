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
MAIN_CATEGORIES = {"정치", "경제", "사회", "국제", "기술", "산업"}

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

KOREAN_STOPWORDS = {
    "기자",
    "오늘",
    "관련",
    "통해",
    "대해",
    "대한",
    "이번",
    "지난",
    "최근",
    "정부",
    "국내",
    "국제",
    "시장",
    "정책",
    "뉴스",
    "보도",
    "발표",
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


def extract_topical_keywords(item: dict[str, Any], limit: int = 5) -> list[str]:
    base_text = f"{item.get('title', '')} {item.get('description', '')}"
    tokens = [
        token
        for token in re.findall(r"[가-힣A-Za-z0-9]+", base_text)
        if len(token) >= 2 and token.lower() not in KOREAN_STOPWORDS
    ]
    freq: dict[str, int] = {}
    for token in tokens:
        freq[token] = freq.get(token, 0) + 1

    scored = sorted(freq.items(), key=lambda x: (x[1], len(x[0])), reverse=True)
    concrete = [kw for kw, _ in scored if kw not in {"기사", "단독", "속보"}]
    merged = item.get("matched_keywords", []) + concrete
    uniq: list[str] = []
    for kw in merged:
        if kw not in uniq:
            uniq.append(kw)
    return uniq[:limit]


def too_similar_to_title(text: str, title: str) -> bool:
    title_tokens = tokenize(title)
    text_tokens = tokenize(text)
    if not title_tokens or not text_tokens:
        return False
    sim = jaccard(title_tokens, text_tokens)
    return sim >= 0.45 or title[:16] in text


def sanitize_editorial_line(line: str, title: str, fallback: str) -> str:
    clean = line.strip()
    if not clean:
        return fallback
    if too_similar_to_title(clean, title):
        return fallback
    return clean


def split_korean_sentences(text: str) -> list[str]:
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if not cleaned:
        return []
    # Split by sentence punctuation while keeping complete Korean sentence units.
    parts = re.split(r"(?<=[\.\!\?다요])\s+", cleaned)
    sentences: list[str] = []
    for part in parts:
        s = part.strip(" \t\r\n-–—")
        if not s:
            continue
        sentences.append(s)
    return sentences


def is_complete_sentence(sentence: str) -> bool:
    s = sentence.strip()
    if len(s) < 8:
        return False
    # Allow sentence-final punctuation, but ensure the base token is valid.
    base = re.sub(r"[\.!?]+$", "", s).strip()
    if re.search(r"[가-힣A-Za-z0-9]$", base) is None:
        return False
    if s.endswith(("다", "요", ".", "!", "?", "니다", "됩니다", "했습니다", "입니다", "됨")):
        return True
    return False


def finalize_sentence(sentence: str) -> str | None:
    s = sentence.strip()
    if not s:
        return None
    if not re.search(r"[\.!?]$", s):
        # Korean briefing style can end with "다/요" without punctuation; add period for consistency.
        if s.endswith(("다", "요", "니다", "됨")):
            s = f"{s}."
    if not is_complete_sentence(s):
        return None
    return s


def sanitize_summary_lines(lines: list[str], title: str) -> list[str]:
    final: list[str] = []
    for line in lines:
        safe = sanitize_editorial_line(
            line,
            title,
            "핵심 사실과 후속 발표 내용을 중심으로 추가 확인이 필요합니다.",
        )
        normalized = finalize_sentence(safe)
        if normalized is None:
            continue
        if too_similar_to_title(normalized, title):
            continue
        final.append(normalized)
        if len(final) == 5:
            break
    return final


def build_structured_summary(item: dict[str, Any], cluster: list[dict[str, Any]], score: float) -> dict[str, str]:
    top_keywords = item.get("major_keywords", [])[:3]
    keyword_text = ", ".join(top_keywords) if top_keywords else "핵심 변수"
    title = item.get("title", "")
    description = (item.get("description", "") or "").strip()
    split_desc = split_korean_sentences(description)
    desc_part = split_desc[0] if split_desc else "정책·시장 변수에 영향이 큰 사안으로 해석됩니다."
    return {
        "핵심": sanitize_editorial_line(
            f"{desc_part}",
            title,
            "핵심 당사자들의 대응 방향이 추가로 확인되고 있습니다.",
        ),
        "배경": sanitize_editorial_line(
            f"{item.get('category', '일반')} 현안의 연장선에서 파급 범위가 커진 이슈입니다.",
            title,
            "기존 현안의 누적 영향으로 중요도가 높아진 사안입니다.",
        ),
        "확산": sanitize_editorial_line(
            f"주요 매체 {len({c.get('outlet','') for c in cluster})}곳에서 후속 보도를 이어가고 있습니다.",
            title,
            "여러 매체에서 후속 사실관계를 연속 보도하고 있습니다.",
        ),
        "포인트": sanitize_editorial_line(
            f"{keyword_text} 등 핵심 변수의 방향성이 관전 포인트입니다.",
            title,
            "핵심 변수의 방향성과 당국·기업 대응이 관전 포인트입니다.",
        ),
        "종합": sanitize_editorial_line(
            "단기 반응보다 후속 발표와 실행 단계에서의 변화 확인이 중요합니다.",
            title,
            "후속 발표의 구체성과 실행 속도를 함께 점검해야 합니다.",
        ),
    }


def build_article_5lines(item: dict[str, Any], cluster: list[dict[str, Any]], score: float) -> list[str]:
    title = item.get("title", "")
    description = (item.get("description", "") or "").strip()
    body_sentences = split_korean_sentences(description)
    primary_body = body_sentences[0] if body_sentences else "핵심 쟁점과 이해관계자 반응이 함께 보도됐습니다."
    secondary_body = body_sentences[1] if len(body_sentences) > 1 else "주요 수치와 일정이 추가 보도에서 점차 구체화되고 있습니다."
    keywords = item.get("major_keywords", [])[:3]
    keyword_text = ", ".join(keywords) if keywords else "핵심 변수"
    candidates = [
        primary_body,
        secondary_body,
        f"{item.get('category', '일반')} 분야의 의사결정과 일정에 직접 영향을 줄 수 있는 내용입니다.",
        f"{keyword_text} 중심으로 이해관계자들의 해석이 엇갈리고 있습니다.",
        "후속 발표에서 수치·일정·집행 방식이 구체화되는지가 중요합니다.",
        "단기 이슈에 그치지 않고 중장기 흐름으로 이어질 가능성이 거론됩니다.",
    ]
    validated = sanitize_summary_lines(candidates, title)
    fallback = [
        "핵심 사실관계와 이해관계자 입장이 본문에서 확인됩니다.",
        "기사에서 제시된 수치와 일정의 변화가 후속 쟁점으로 이어지고 있습니다.",
        "관련 당사자의 대응 방향이 시장과 정책 판단에 영향을 줄 수 있습니다.",
        "추가 발표에서 집행 범위와 시점이 더 구체화될 전망입니다.",
        "단기 반응보다 중장기 파급 흐름을 함께 점검할 필요가 있습니다.",
    ]
    while len(validated) < 5:
        candidate = fallback[len(validated)]
        norm = finalize_sentence(candidate)
        if norm:
            validated.append(norm)
    return validated[:5]


def clean_title_score(title: str) -> float:
    score = 0.0
    if 12 <= len(title) <= 58:
        score += 1.2
    if "[" not in title and "]" not in title:
        score += 0.5
    if "속보" not in title and "단독" not in title:
        score += 0.3
    if "기자" not in title:
        score += 0.2
    return score


def select_representative_article(cluster: list[dict[str, Any]]) -> dict[str, Any]:
    """Choose the cleanest and most recent real title within the valid cluster window."""
    timestamps = [datetime.fromisoformat(item["pub_date_kst"]).timestamp() for item in cluster]
    min_ts, max_ts = min(timestamps), max(timestamps)
    range_ts = max(1.0, max_ts - min_ts)

    def rep_score(item: dict[str, Any]) -> float:
        ts = datetime.fromisoformat(item["pub_date_kst"]).timestamp()
        recency_norm = (ts - min_ts) / range_ts
        return (recency_norm * 2.0) + clean_title_score(item.get("title", ""))

    ranked = sorted(cluster, key=rep_score, reverse=True)
    return ranked[0]


def build_cluster_record(
    cluster: list[dict[str, Any]],
    trend_scores: dict[str, float],
    now: datetime,
    representative_reason: str,
) -> dict[str, Any]:
    representative = select_representative_article(cluster)
    score = importance_score(representative, cluster, trend_scores, now)

    representative["related_count"] = len(cluster)
    representative["outlet_count"] = len({item.get("outlet", "") for item in cluster})
    representative["categories_merged"] = sorted({item.get("category", "일반") for item in cluster})
    representative["score"] = round(score, 4)
    representative["importance_stars"] = assign_stars(score)
    representative["major_keywords"] = extract_topical_keywords(representative, limit=5)
    one_line_core = sanitize_editorial_line(
        f"{representative.get('category', '일반')} 이슈가 정책·시장 반응에 미치는 영향이 커진 국면입니다.",
        representative.get("title", ""),
        "핵심 변수의 변동성이 확대되며 파급력이 커진 이슈입니다.",
    )
    representative["one_line_core"] = one_line_core
    representative["structured_summary"] = build_structured_summary(representative, cluster, score)
    representative["article_summary_5lines"] = build_article_5lines(representative, cluster, score)
    representative["cluster_representative_reason"] = representative_reason
    return representative


def filter_recent_24h(items: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    cutoff = now.timestamp() - (24 * 3600)
    filtered: list[dict[str, Any]] = []
    for item in items:
        pub_kst = item.get("pub_date_kst")
        if not pub_kst:
            continue
        try:
            ts = datetime.fromisoformat(pub_kst).timestamp()
        except ValueError:
            continue
        if cutoff <= ts <= now.timestamp():
            filtered.append(item)
    return filtered


def split_candidate_pools(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    main_pool = [item for item in items if item.get("category") in MAIN_CATEGORIES]
    semiconductor_pool = [item for item in items if item.get("category") == "반도체" or item.get("is_semiconductor")]
    return main_pool, semiconductor_pool


def make_top_summary(main_items: list[dict[str, Any]], semicon_items: list[dict[str, Any]]) -> list[str]:
    if not main_items:
        return [
            "지난 24시간(KST) 내 주요 이슈 데이터가 제한적입니다.",
            "확인 가능한 사실 중심으로 브리핑을 최소 구성했습니다.",
            "새로운 발표가 반영되면 항목이 즉시 보강됩니다.",
        ]

    return [
        "정책·거시경제·국제정세 중심으로 오늘의 핵심 흐름을 압축했습니다.",
        f"복수 매체가 동시 보도한 상위 이슈를 우선 배치했습니다.",
        f"반도체는 투자·생산·수요 체인 변화 중심으로 {len(semicon_items)}건을 선정했습니다.",
    ]


def main() -> None:
    source_path = Path("data/news_candidates.json")
    if not source_path.exists():
        raise FileNotFoundError("Missing data/news_candidates.json. Run fetch_naver_news.py first.")

    payload = json.loads(source_path.read_text(encoding="utf-8"))
    all_items = payload.get("items", [])
    trend_scores = payload.get("trend_scores", {})
    now = datetime.now(tz=KST)

    # Keep main and semiconductor pipelines explicitly separate.
    main_pool_raw, semiconductor_pool_raw = split_candidate_pools(all_items)

    # Strict 24-hour filter is applied before any clustering/ranking.
    main_pool_24h = filter_recent_24h(main_pool_raw, now)
    semiconductor_pool_24h = filter_recent_24h(semiconductor_pool_raw, now)

    main_clusters = cluster_items(main_pool_24h)
    semicon_clusters = cluster_items(semiconductor_pool_24h)

    main_merged = [
        build_cluster_record(
            cluster,
            trend_scores,
            now,
            representative_reason="cleanest_and_most_recent_real_title_within_main_24h_cluster",
        )
        for cluster in main_clusters
    ]
    semicon_merged = [
        build_cluster_record(
            cluster,
            trend_scores,
            now,
            representative_reason="cleanest_and_most_recent_real_title_within_semiconductor_24h_cluster",
        )
        for cluster in semicon_clusters
    ]

    main_merged.sort(key=lambda x: x["score"], reverse=True)
    semicon_merged.sort(key=lambda x: x["score"], reverse=True)

    # No fallback to older stories or to semiconductor pool for the main section.
    main_items = main_merged[:10]
    semicon_items = semicon_merged[:3]

    debug_main_checks = [
        {
            "title": item.get("title", ""),
            "original_publication_datetime": item.get("pub_date", ""),
            "normalized_kst_datetime": item.get("pub_date_kst", ""),
            "passed_24h_filter": True,
            "cluster_representative_selection_reason": item.get("cluster_representative_reason", ""),
        }
        for item in main_items
    ]

    output = {
        "generated_at_kst": now.isoformat(),
        "date": now.date().isoformat(),
        "top_summary": make_top_summary(main_items, semicon_items),
        "main_news": main_items,
        "semiconductor_news": semicon_items,
        "stats": {
            "raw_main_candidates": len(main_pool_raw),
            "raw_semiconductor_candidates": len(semiconductor_pool_raw),
            "main_candidates_24h": len(main_pool_24h),
            "semiconductor_candidates_24h": len(semiconductor_pool_24h),
            "main_clustered_groups": len(main_clusters),
            "semiconductor_clustered_groups": len(semicon_clusters),
            "trend_boost_enabled": bool(trend_scores),
        },
        "debug": {
            "selected_main_story_checks": debug_main_checks,
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
