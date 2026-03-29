#!/usr/bin/env python3
"""Build mobile-friendly dark-theme HTML files from scored news data.

Inputs:
- data/scored_news.json

Outputs:
- index.html
- archive/YYYY-MM-DD.html
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any


def stars(n: int) -> str:
    return "★" * max(1, min(5, int(n)))


def render_keywords(keywords: list[str]) -> str:
    if not keywords:
        return '<span class="chip">일반</span>'
    return "".join(f'<span class="chip">{html.escape(kw)}</span>' for kw in keywords)


def render_summary_lines(lines: list[str]) -> str:
    safe_lines = [html.escape(line) for line in lines[:5]]
    while len(safe_lines) < 5:
        safe_lines.append("추가 분석 데이터가 집계 중입니다.")
    return "".join(f"<li>{line}</li>" for line in safe_lines)


def render_card(item: dict[str, Any]) -> str:
    merged = ", ".join(item.get("categories_merged", [item.get("category", "일반")]))
    return f"""
    <article class="card">
      <div class="meta-row">
        <span class="category">{html.escape(merged)}</span>
        <span class="stars">{stars(item.get('importance_stars', 1))}</span>
      </div>
      <h3>{html.escape(item.get('title', '제목 없음'))}</h3>
      <p class="sub">{html.escape(item.get('outlet', '알 수 없음'))} · {html.escape(item.get('pub_date_kst', ''))}</p>
      <div class="keywords">{render_keywords(item.get('matched_keywords', []))}</div>
      <ul class="summary">{render_summary_lines(item.get('summary_lines', []))}</ul>
      <a class="link" href="{html.escape(item.get('link', '#'))}" target="_blank" rel="noopener noreferrer">기사 원문 보기</a>
    </article>
    """


def build_html(payload: dict[str, Any]) -> str:
    date = payload.get("date", "")
    generated = payload.get("generated_at_kst", "")
    top_summary = payload.get("top_summary", [])
    main_news = payload.get("main_news", [])
    semiconductor_news = payload.get("semiconductor_news", [])

    top_summary_html = "".join(f"<li>{html.escape(line)}</li>" for line in top_summary[:3])
    main_cards = "".join(render_card(item) for item in main_news)
    semi_cards = "".join(render_card(item) for item in semiconductor_news)

    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1" />
  <title>데일리 코리안 뉴스 브리핑 - {html.escape(date)}</title>
  <style>
    :root {{
      --bg: #0f1116;
      --bg-card: #171b24;
      --text: #f2f5ff;
      --muted: #a2acc4;
      --accent: #6aa6ff;
      --chip: #243250;
      --border: #2b3245;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Noto Sans KR", sans-serif;
      line-height: 1.45;
    }}
    .container {{
      width: min(760px, 100%);
      margin: 0 auto;
      padding: 16px 14px 28px;
    }}
    h1 {{ font-size: 1.35rem; margin: 8px 0 6px; }}
    h2 {{ font-size: 1.05rem; margin: 20px 0 12px; color: #c8d5ff; }}
    .timestamp {{ color: var(--muted); font-size: 0.85rem; margin-bottom: 12px; }}
    .summary-top {{
      background: #121826;
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 12px 14px;
      margin-bottom: 14px;
    }}
    .summary-top ul {{ margin: 0; padding-left: 17px; }}
    .summary-top li {{ margin: 6px 0; }}
    .card {{
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 14px;
      margin-bottom: 12px;
      box-shadow: 0 4px 18px rgba(0,0,0,0.22);
    }}
    .meta-row {{ display: flex; justify-content: space-between; gap: 10px; }}
    .category {{ color: #9dc2ff; font-weight: 600; font-size: 0.88rem; }}
    .stars {{ color: #ffd76a; font-size: 0.9rem; }}
    h3 {{ margin: 8px 0 8px; font-size: 1.03rem; }}
    .sub {{ margin: 0 0 8px; font-size: 0.82rem; color: var(--muted); }}
    .keywords {{ display: flex; gap: 6px; flex-wrap: wrap; margin: 7px 0 8px; }}
    .chip {{ background: var(--chip); color: #cadeff; border-radius: 999px; padding: 4px 8px; font-size: 0.76rem; }}
    .summary {{ margin: 8px 0 10px; padding-left: 17px; color: #d8e0f6; font-size: 0.88rem; }}
    .summary li {{ margin: 4px 0; }}
    .link {{ color: var(--accent); font-weight: 600; text-decoration: none; }}
    .link:hover {{ text-decoration: underline; }}
    @media (min-width: 720px) {{
      .container {{ padding-top: 24px; }}
      h1 {{ font-size: 1.6rem; }}
    }}
  </style>
</head>
<body>
  <main class="container">
    <h1>데일리 코리안 뉴스 브리핑</h1>
    <p class="timestamp">기준일: {html.escape(date)} · 생성시각(KST): {html.escape(generated)}</p>

    <section class="summary-top">
      <h2>오늘의 3줄 요약</h2>
      <ul>{top_summary_html}</ul>
    </section>

    <section>
      <h2>주요 뉴스 10선</h2>
      {main_cards}
    </section>

    <section>
      <h2>반도체 뉴스 3선</h2>
      {semi_cards}
    </section>
  </main>
</body>
</html>
"""


def main() -> None:
    source = Path("data/scored_news.json")
    if not source.exists():
        raise FileNotFoundError("Missing data/scored_news.json. Run score_cluster.py first.")

    payload = json.loads(source.read_text(encoding="utf-8"))
    rendered = build_html(payload)

    Path("archive").mkdir(exist_ok=True)
    date = payload.get("date", "unknown")
    archive_file = Path("archive") / f"{date}.html"

    Path("index.html").write_text(rendered, encoding="utf-8")
    archive_file.write_text(rendered, encoding="utf-8")

    print(f"Wrote index.html and {archive_file}")


if __name__ == "__main__":
    main()
