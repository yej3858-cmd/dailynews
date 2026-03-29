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
from datetime import datetime
from pathlib import Path
from typing import Any


def stars(n: int) -> str:
    return "★" * max(1, min(5, int(n)))


def render_keywords(keywords: list[str]) -> str:
    if not keywords:
        return '<span class="chip">세부 키워드 확인중</span>'
    return "".join(f'<span class="chip">{html.escape(kw)}</span>' for kw in keywords)


def format_kst_datetime(value: str) -> str:
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return value
    return dt.strftime("%Y.%m.%d %H:%M")


def render_structured_summary(summary: dict[str, str]) -> str:
    fields = ["핵심", "배경", "확산", "포인트", "종합"]
    rows = []
    for field in fields:
        rows.append(
            f'<div class="structured-row"><span class="label">{field}</span><span class="value">{html.escape(summary.get(field, ""))}</span></div>'
        )
    return "".join(rows)


def render_5line_summary(lines: list[str]) -> str:
    safe = [html.escape(line) for line in lines[:5]]
    while len(safe) < 5:
        safe.append("추가 요약 데이터가 준비 중입니다.")
    return "".join(f"<li>{line}</li>" for line in safe)


def render_card(item: dict[str, Any]) -> str:
    merged = ", ".join(item.get("categories_merged", [item.get("category", "일반")]))
    structured = item.get("structured_summary", {})
    article_5lines = item.get("article_summary_5lines", [])
    pub_dt = format_kst_datetime(item.get("pub_date_kst", ""))
    return f"""
    <article class="card">
      <div class="meta-row">
        <span class="category">{html.escape(merged)}</span>
        <span class="stars">{stars(item.get('importance_stars', 1))}</span>
      </div>

      <h3>{html.escape(item.get('title', '제목 없음'))}</h3>
      <p class="sub">{html.escape(item.get('outlet', '알 수 없음'))} · {html.escape(pub_dt)}</p>

      <div class="section-block">
        <p class="section-title">주요 키워드</p>
        <div class="keywords">{render_keywords(item.get('major_keywords', []))}</div>
      </div>

      <div class="section-block">
        <p class="section-title">한줄 핵심</p>
        <p class="core-line">{html.escape(item.get('one_line_core', '핵심 변수의 변화를 점검해야 할 이슈입니다.'))}</p>
      </div>

      <div class="section-block structured-box">
        <p class="section-title">구조화 요약</p>
        {render_structured_summary(structured)}
      </div>

      <div class="section-block lines-box">
        <p class="section-title">기사 요약 5줄</p>
        <ol class="summary-lines">{render_5line_summary(article_5lines)}</ol>
      </div>

      <a class="link" href="{html.escape(item.get('link', '#'))}" target="_blank" rel="noopener noreferrer">기사 원문 보기</a>
    </article>
    """


def build_html(payload: dict[str, Any]) -> str:
    date = payload.get("date", "")
    date_for_title = date.replace("-", ".")
    page_title = f"{date_for_title} News Briefing"
    generated = payload.get("generated_at_kst", "")
    generated_fmt = format_kst_datetime(generated)
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
  <title>{html.escape(page_title)}</title>
  <style>
    :root {{
      --bg: #0b0f17;
      --bg-card: #121927;
      --text: #f4f7ff;
      --muted: #a9b5d3;
      --accent: #79adff;
      --chip: #213453;
      --border: #2b3750;
      --block: #0f1522;
      --label: #95b9ff;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Noto Sans KR", sans-serif;
      line-height: 1.48;
    }}
    .container {{
      width: min(760px, 100%);
      margin: 0 auto;
      padding: 16px 14px 32px;
    }}
    h1 {{ font-size: 1.38rem; margin: 8px 0 8px; }}
    h2 {{ font-size: 1.08rem; margin: 22px 0 12px; color: #d3e1ff; }}
    .timestamp {{ color: var(--muted); font-size: 0.84rem; margin-bottom: 14px; }}
    .window-note {{
      margin: 0 0 12px;
      color: #bfd0f6;
      font-size: 0.8rem;
      font-weight: 700;
    }}
    .summary-top {{
      background: #111a2a;
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 14px;
      margin-bottom: 16px;
    }}
    .summary-top .title {{
      margin: 0 0 8px;
      font-size: 0.92rem;
      font-weight: 700;
      color: var(--label);
    }}
    .summary-top ul {{ margin: 0; padding-left: 18px; }}
    .summary-top li {{ margin: 6px 0; }}

    .card {{
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 15px;
      padding: 14px;
      margin-bottom: 14px;
      box-shadow: 0 4px 18px rgba(0, 0, 0, 0.24);
    }}
    .meta-row {{ display: flex; justify-content: space-between; gap: 10px; margin-bottom: 6px; }}
    .category {{ color: #a7c8ff; font-weight: 700; font-size: 0.88rem; }}
    .stars {{ color: #ffdd7a; font-size: 0.94rem; letter-spacing: 1px; }}
    h3 {{ margin: 6px 0 8px; font-size: 1.04rem; line-height: 1.35; }}
    .sub {{ margin: 0 0 10px; font-size: 0.82rem; color: var(--muted); }}

    .section-block {{
      background: var(--block);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 10px;
      margin: 10px 0;
    }}
    .section-title {{
      margin: 0 0 8px;
      color: var(--label);
      font-size: 0.82rem;
      font-weight: 700;
      letter-spacing: 0.1px;
    }}

    .keywords {{ display: flex; gap: 6px; flex-wrap: wrap; }}
    .chip {{
      background: var(--chip);
      color: #d5e7ff;
      border-radius: 999px;
      padding: 4px 9px;
      font-size: 0.76rem;
    }}

    .structured-row {{
      display: grid;
      grid-template-columns: 54px 1fr;
      gap: 8px;
      margin: 6px 0;
      align-items: start;
    }}
    .structured-row .label {{
      color: #8eb8ff;
      font-size: 0.8rem;
      font-weight: 700;
      padding-top: 1px;
    }}
    .structured-row .value {{
      color: #dfe8ff;
      font-size: 0.85rem;
    }}

    .summary-lines {{
      margin: 0;
      padding-left: 18px;
      color: #d9e3fb;
      font-size: 0.86rem;
    }}
    .summary-lines li {{ margin: 5px 0; }}
    .core-line {{ margin: 0; color: #dce6ff; font-size: 0.88rem; }}

    .link {{
      display: inline-block;
      margin-top: 4px;
      color: var(--accent);
      font-weight: 700;
      text-decoration: none;
    }}
    .link:hover {{ text-decoration: underline; }}

    @media (min-width: 720px) {{
      .container {{ padding-top: 24px; }}
      h1 {{ font-size: 1.62rem; }}
      .card {{ padding: 16px; }}
    }}
  </style>
</head>
<body>
  <main class="container">
    <h1>{html.escape(page_title)}</h1>
    <p class="timestamp">기준일: {html.escape(date)} · 생성시각(KST): {html.escape(generated_fmt)}</p>
    <p class="window-note">Coverage window: past 24 hours (KST)</p>

    <section class="summary-top">
      <p class="title">오늘의 3줄 요약</p>
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
