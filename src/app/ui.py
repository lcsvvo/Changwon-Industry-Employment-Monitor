"""3패널 업종 진단/점검 관리/정책 연계 화면을 위한 순수 HTML 조각 빌더.

여기 함수는 streamlit을 import하지 않고 문자열만 만든다(단위 테스트 대상). 모든
데이터 값은 html.escape 처리하며, 렌더링은 호출부에서 ``st.html(...)``로 한다.
숫자·경계값을 새로 계산하지 않고 이미 포맷된 문자열만 조합한다.
"""
from __future__ import annotations

import html as _html
from typing import Iterable

STAGE_TONE = {"우선점검": "rose", "추가확인": "amber", "관찰": "emerald"}
VERDICT_TONE = {
    "상위": "rose", "진입": "amber", "충족": "amber", "통과": "emerald",
    "미달": "muted", "미확인": "muted",
}
_CIRCLED = ["①", "②", "③", "④"]


def _e(value) -> str:
    if value is None or value == "":
        return "—"
    return _html.escape(str(value))


def stage_badge_html(stage: str | None, label: str | None = None) -> str:
    tone = STAGE_TONE.get(stage or "", "muted")
    return f'<span class="dx-badge dx-badge--{tone}">{_e(label or stage)}</span>'


def section_head_html(title: str, helper: str | None = None, badge: str | None = None) -> str:
    """화면 안 소제목(업종 진단·정책 연계·점검 관리 공용). helper는 줄바꿈해 아래에, badge는 dx-tag-line."""
    badge_html = f'<span class="dx-tag-line">{_e(badge)}</span>' if badge else ""
    helper_html = f'<span class="dx-section-helper">{_e(helper)}</span>' if helper else ""
    return (f'<div class="dx-section-head"><span class="dx-section-title">{_e(title)}</span>'
            f'{badge_html}{helper_html}</div>')


def stage_legend_html() -> str:
    """판정 추이 범례 — 칩과 같은 톤 3개 + 순서는 인과관계가 아니라는 안내 아이콘."""
    order = (("우선점검", "우선점검 후보"), ("추가확인", "추가확인"), ("관찰", "관찰"))
    pills = "".join(f'<span class="dx-pill dx-tone-{STAGE_TONE[stage]}">{_e(label)}</span>' for stage, label in order)
    tip = "상태 변화의 시간 순서를 보여주며 인과관계를 의미하지 않습니다."
    return f'<div class="dx-legend">{pills}<span class="dx-muted" title="{_e(tip)}">ⓘ</span></div>'


def page_header_html(title: str, subtitle: str, badge_html: str = "") -> str:
    """일반 페이지 헤더(점검 관리·정책 연계·관리 화면 공용)."""
    return (
        '<div class="dx-report-header">'
        '<div class="dx-report-header-main">'
        f'<div class="dx-report-title">{_e(title)}</div>'
        f'<div class="dx-report-meta">{_e(subtitle)}</div>'
        '</div>'
        f'<div class="dx-report-stage">{badge_html}</div>'
        '</div>'
    )


def header_html(quarter: str, industry: str, stage: str | None, stage_label: str | None, meta_line: str) -> str:
    """업종 진단 헤더. page_header_html을 업종 진단 문구로 채운다."""
    title = f"[{quarter}] 창원국가산단 산업·고용 진단카드 : {industry}"
    return page_header_html(title, meta_line, stage_badge_html(stage, stage_label))


def kpi_cards_html(cards: Iterable[dict]) -> str:
    items = "".join(
        '<div class="dx-kpi">'
        f'<div class="dx-kpi-label">{_e(c.get("label"))}</div>'
        f'<div class="dx-kpi-value dx-tone-{_e(c.get("tone") or "default")}">{_e(c.get("value"))}</div>'
        f'<div class="dx-kpi-sub">{_e(c.get("sub"))}</div>'
        '</div>'
        for c in cards
    )
    return f'<div class="dx-kpi-grid">{items}</div>'


def rule_table_html(rows: list[dict], footnote: str) -> str:
    body = "".join(
        "<tr>"
        f'<td>{_e(r.get("signal"))}</td>'
        f'<td>{_e(r.get("current"))}</td>'
        f'<td>{_e(r.get("entry_threshold"))}</td>'
        f'<td>{_e(r.get("upper_threshold"))}</td>'
        f'<td><span class="dx-verdict dx-tone-{VERDICT_TONE.get(r.get("verdict"), "muted")}">'
        f'{_e(r.get("verdict"))}</span></td>'
        f'<td class="dx-muted">{_e(r.get("basis"))}</td>'
        "</tr>"
        for r in rows
    )
    return (
        '<table class="dx-rule-table">'
        '<thead><tr><th>신호</th><th>현재값</th><th>진입경계</th><th>상위경계</th>'
        '<th>판정</th><th>근거구분</th></tr></thead>'
        f'<tbody>{body}</tbody>'
        '</table>'
        f'<div class="dx-footnote">{_e(footnote)}</div>'
    )


def fact_caveat_html(facts: list[str], caveats: list[str], fact_title: str = "보조 산업지표",
                     caveat_title: str = "해석 주의") -> str:
    fact_lines = "".join(f"<li>{_e(x)}</li>" for x in facts) or "<li>확인된 사실 없음</li>"
    caveat_lines = "".join(f"<li>{_e(x)}</li>" for x in caveats) or "<li>표시할 한계 없음</li>"
    return (
        '<div class="dx-two-col">'
        '<div class="dx-panel-card dx-panel-card--emerald">'
        f'<div class="dx-panel-title">{_e(fact_title)}</div>'
        f'<ul>{fact_lines}</ul>'
        '</div>'
        '<div class="dx-panel-card dx-panel-card--amber">'
        f'<div class="dx-panel-title">{_e(caveat_title)}</div>'
        f'<ul>{caveat_lines}</ul>'
        '</div>'
        '</div>'
    )


def metric_list_html(title: str, rows: list[tuple[str, str]], badge_html: str = "") -> str:
    body = "".join(
        f'<div class="dx-metric-row"><span>{_e(k)}</span><strong>{_e(v)}</strong></div>' for k, v in rows
    )
    return (
        '<div class="dx-metric-card">'
        f'<div class="dx-metric-head"><span>{_e(title)}</span>{badge_html}</div>'
        f'{body}'
        '</div>'
    )


def reason_cards_html(title: str, items: list[dict], empty_text: str) -> str:
    """"왜 {stage}인가?" 번호 카드(①②③④). items가 비면 단일 muted 카드로 stage_reason을 보여준다."""
    if not items:
        body = f'<div class="dx-reason dx-reason--empty dx-muted">{_e(empty_text)}</div>'
    else:
        body = "".join(
            f'<div class="dx-reason dx-tone-{_e(it.get("tone") or "amber")}">'
            f'<div class="dx-reason-no">{_CIRCLED[i]}</div>'
            f'<div class="dx-reason-title">{_e(it.get("title"))}</div>'
            f'<div class="dx-reason-value">{_e(it.get("value"))}</div>'
            f'<div class="dx-reason-rule">{_e(it.get("rule"))}</div>'
            '</div>'
            for i, it in enumerate(items[:4])
        )
    head = f'<div class="dx-sub-title">{_e(title)}</div>' if title else ""
    return f'{head}<div class="dx-reason-grid">{body}</div>'


def note_html(text: str) -> str:
    """카드 안 한 줄짜리 옅은 안내문(회색 스트립이 아님) — 왜인가 요약줄, 확인질문 안내, 지원기능 안내 등."""
    return f'<div class="dx-note">{_e(text)}</div>'


def notice_html(title: str, body: str, source_line: str, tone: str = "violet") -> str:
    """후향 재구성 등 화면 공지 카드."""
    return (
        f'<div class="dx-notice dx-notice--{_e(tone)}">'
        f'<div class="dx-notice-title">{_e(title)}</div>'
        f'<div class="dx-notice-body">{_e(body)}</div>'
        f'<div class="dx-notice-source">{_e(source_line)}</div>'
        '</div>'
    )


def timeline_trail_html(rows_desc: list[dict]) -> str:
    """rows_desc[0] = 선택 분기(현재), 이후 최대 3개 이전 분기. 값은 재계산하지 않는다.

    row에 "stage_display"가 있으면 표시 문구로 쓰고, 칩 색(tone)은 항상 등록된 "stage" 원값으로 정한다.
    """
    if not rows_desc:
        return '<div class="dx-trail dx-muted">표시할 진단 이력이 없습니다.</div>'
    parts = []
    for i, row in enumerate(rows_desc):
        tone = STAGE_TONE.get(row.get("stage"), "muted")
        label = row.get("stage_display") or row.get("stage")
        prefix = "현재 " if i == 0 else ""
        parts.append(f'{prefix}{_e(row.get("quarter"))} '
                     f'<span class="dx-pill dx-tone-{tone}">{_e(label)}</span>')
    return '<div class="dx-trail">' + " ← ".join(parts) + '</div>'


def question_list_html(title: str | None, items: list[tuple[str, str]], caption: str = "") -> str:
    """현장 확인 질문 번호 목록. items = [(질문, 출처 라벨)]. title이 없으면(화면에서 section()을 쓸 때) 생략."""
    rows = "".join(f'<li>{_e(q)} <span class="dx-muted">· {_e(src)}</span></li>' for q, src in items)
    cap = f'<div class="dx-footnote">{_e(caption)}</div>' if caption else ""
    head = f'<div class="dx-sub-title">{_e(title)}</div>' if title else ""
    return f'<div class="dx-qlist">{head}<ol class="dx-qlist-items">{rows}</ol>{cap}</div>'


def chip_row_html(items: list[tuple[str, int]], tone: str = "sky") -> str:
    chips = "".join(f'<span class="dx-chip dx-chip--{_e(tone)}">{_e(term)} <b>{_e(count)}</b></span>'
                    for term, count in items) or '<span class="dx-muted">확인된 키워드 없음</span>'
    return f'<div class="dx-chip-row">{chips}</div>'


def bullet_list_html(items: list[str], empty_text: str = "") -> str:
    body = "".join(f"<li>{_e(x)}</li>" for x in items) or (f"<li>{_e(empty_text)}</li>" if empty_text else "")
    return f'<ul class="dx-qlist-items">{body}</ul>'


def section_html(title: str, inner: str) -> str:
    """진단서 출력(handover) 섹션 wrapper."""
    return f'<div class="dx-sec-title">{_e(title)}</div><div class="dx-sec-body">{inner}</div>'


def document_html(title: str, body: str, css: str) -> str:
    """진단 요약 인쇄용 단독 HTML 문서(다운로드용). body는 이미 만들어진 HTML(그대로 삽입)."""
    return (
        '<!doctype html><html lang="ko"><head><meta charset="utf-8">'
        f'<title>{_e(title)}</title><style>{css} '
        'body{background:#fff;padding:24px;max-width:960px;margin:auto;font-family:Pretendard,sans-serif}'
        '</style></head>'
        f'<body>{body}</body></html>'
    )


# 업종 버튼·판정 추이 칩은 위젯 key를 고정(ind-{i}, tl-{분기})하고 단계 색·선택 표시는 이 style로만 바꾼다.
# key에 단계·선택 상태를 넣으면 클릭마다 위젯이 새로 만들어져(remount) 느려지고 잔상 요소가 남는다.
_DOT = {"priority": "var(--dx-rose)", "check": "#F59E0B", "watch": "#34D399"}
_CHIP = {"priority": ("var(--dx-rose)", "var(--dx-rose)", "#fff"),
         "check": ("#FBBF24", "#FBBF24", "#fff"),
         "watch": ("var(--dx-emerald-bg)", "#A7F3D0", "#047857")}


def industry_style_html(codes: list[str], selected: int | None) -> str:
    """codes[i] = i번째 업종 버튼의 stage_code. 선택 버튼은 sky 배경."""
    rules = [f".st-key-ind-{i} button::after{{background:{_DOT[c]};}}" for i, c in enumerate(codes) if c in _DOT]
    if selected is not None:
        rules.append(f".st-key-ind-{selected} button{{background:var(--dx-sky)!important;"
                     "border-color:var(--dx-sky)!important;}"
                     f".st-key-ind-{selected} button p{{color:#fff!important;}}"
                     f".st-key-ind-{selected} button::after{{box-shadow:0 0 0 2px #fff;}}")
    return "<style>" + "".join(rules) + "</style>"


def timeline_style_html(chips: list[tuple[str, str]], current: str) -> str:
    """chips = [(분기, stage_code)]. 현재 분기는 sky 외곽선."""
    rules = []
    for quarter, code in chips:
        if code in _CHIP:
            bg, border, fg = _CHIP[code]
            rules.append(f".st-key-tl-{quarter} button{{background:{bg};border-color:{border};}}"
                         f".st-key-tl-{quarter} button p{{color:{fg};}}")
    rules.append(f".st-key-tl-{current} button{{outline:2px solid var(--dx-sky);outline-offset:1px;}}")
    return "<style>" + "".join(rules) + "</style>"


def _link(url: str | None, label: str) -> str:
    """http(s) 출처만 링크로 만든다(그 외 스킴은 표시하지 않음)."""
    if not url or not str(url).startswith(("http://", "https://")):
        return ""
    return f'<a class="dx-link" href="{_e(url)}" target="_blank" rel="noopener">{_e(label)}</a>'


def context_tags_html(title: str, tags: list[str]) -> str:
    """Copilot 헤더 아래 컨텍스트 한 줄 — 굵은 제목 + 태그 칩(dx-chip--sky)."""
    chips = "".join(f'<span class="dx-chip dx-chip--sky">{_e(t)}</span>' for t in tags)
    return f'<div class="dx-copilot-sub"><b>{_e(title)}</b> {chips}</div>'


def brand_html(rule_version: str) -> str:
    return (
        '<div class="dx-brand">'
        '<div class="dx-brand-icon">◆</div>'
        '<div class="dx-brand-text"><div class="dx-brand-title">창원국가산단 산업·고용 전환진단'
        '<span class="dx-brand-tag">AI 코파일럿</span>'
        f'<span class="dx-brand-tag">{_e(rule_version)}</span></div>'
        '<div class="dx-brand-sub">산업·고용 통계(KICOX) → Triage 진단 → 현장 확인 → 기존 지원체계 연계 · '
        'Human-in-the-Loop 행정 의사결정지원</div></div>'
        '</div>'
    )


def status_pills_html(items: list[tuple[str, str]]) -> str:
    """헤더 상태 pill. items = [(tone, text)], tone ∈ ok/warn/info."""
    return '<div class="dx-status-row">' + "".join(
        f'<span class="dx-status dx-status--{_e(tone)}"><i></i>{_e(text)}</span>' for tone, text in items
    ) + "</div>"


def _level_tile(label: str, count, sub: str | None, unit: str = "건") -> str:
    value = "상세 미확인" if count is None else f"{int(count):,}{unit}"
    return ('<div class="dx-level">'
            f'<div class="dx-level-label">{_e(label)}</div>'
            f'<div class="dx-level-value">{value}</div>'
            + (f'<div class="dx-level-sub">{_e(sub)}</div>' if sub else "")
            + '</div>')


def recruitment_summary_html(jobs: dict, keywords: list[dict], is_latest: bool, selected_quarter: str,
                             observations: list[str], keyword_basis: dict[str, str],
                             keyword_posting_count=None) -> str:
    """채용시장 보조 신호 요약 — 4개 증거수준 tile(각 tile sub = 그 수준의 정의) + 주요 키워드 + 관찰된 표현.

    제목·tag-line은 화면에서 section()으로 그리므로 여기서는 만들지 않는다. keyword_basis = WORK24_BASIS.
    keyword_posting_count = report_payload["recruitment_keywords"]["posting_count"](목록 건수, 재계산 아님).
    """
    if jobs.get("status") != "FOUND":
        caveats = "; ".join(jobs.get("caveat") or ["해당 업종으로 매핑된 Work24 공고가 없습니다."])
        return f'<div class="dx-empty">현재 확보된 채용공고 없음 · {_e(caveats)}</div>'
    collected = (jobs.get("collected_at") or "")[:10] or None
    meta = (f'수집 {_e(collected)} · 유효 기준일 {_e(jobs.get("activity_as_of"))} · '
            f'Work24 {_e(jobs.get("quarter"))} 공고')
    warn = "" if is_latest else (
        f'<div class="dx-warn">선택 분기 {_e(selected_quarter)}와 다른 시점(Work24 {_e(jobs.get("quarter"))}) '
        '자료입니다. 과거 분기 진단의 근거로 쓰지 마세요.</div>')
    levels = {lv.get("key"): lv for lv in jobs.get("evidence_levels") or []}
    lst, active = levels.get("LIST") or {}, levels.get("ACTIVE_CONFIRMED") or {}
    detail = levels.get("DETAIL_VERIFIED") or {}
    tiles = (_level_tile("목록 데이터", lst.get("count"), keyword_basis.get("LIST"))
            + _level_tile("현재 유효", active.get("count"), keyword_basis.get("ACTIVE_CONFIRMED"))
            + _level_tile("상세 검증", detail.get("count"), keyword_basis.get("DETAIL_VERIFIED"))
            + _level_tile("확인 기업", detail.get("company_count"), keyword_basis.get("DETAIL_COMPANY"), unit="개"))
    kw = [(k["term"], k["count"]) for k in keywords]
    kw_helper = f"목록 {_e(keyword_posting_count)}건의 {_e(keyword_basis.get('KEYWORD'))}"
    return (
        f'<div class="dx-report-meta">{meta}</div>{warn}'
        f'<div class="dx-level-grid">{tiles}</div>'
        '<div class="dx-note">공고 수는 모집인원이나 전체 노동수요가 아닙니다.</div>'
        '<div class="dx-sub-title">주요 키워드</div>'
        f'<div class="dx-sub-helper">{kw_helper}</div>'
        f'{chip_row_html(kw)}'
        '<div class="dx-sub-title">관찰된 표현</div>'
        f'{bullet_list_html(observations)}'
    )


def representative_postings_html(details: list[dict]) -> str:
    """대표 공고(최대 3건) — 없으면 표를 만들지 않고 빈 상태 안내만 보여준다."""
    if not details:  # 빈 상태(표시할 공고 없음)와 데이터 한계(추정하지 않음)는 서로 다른 정보라 따로 둔다
        return ('<div class="dx-sub-title">대표 공고</div>'
                '<div class="dx-empty-note">상세 검증 공고가 없어 대표 공고를 표시하지 않습니다.</div>'
                '<div class="dx-note">목록 정보만으로 직무·임금·경력 분포를 추정하지 않습니다.</div>')
    return ('<div class="dx-sub-title">대표 공고</div>'
            '<div class="dx-sub-helper">상세 검증 공고 중 최대 3건</div>'
            f'{posting_table_html(details)}')


def posting_table_html(records: list[dict]) -> str:
    if not records:
        return '<div class="dx-muted">상세 직무 데이터 미확보 · 목록 정보만으로 직무·임금·경력 분포를 만들지 않습니다.</div>'
    rows = "".join(
        "<tr>"
        f'<td><b>{_e(d.get("company_name"))}</b><br><span class="dx-muted">{_e(d.get("posting_title"))}</span></td>'
        f'<td>{_e(d.get("occupation"))}</td><td>{_e(d.get("career"))}</td><td>{_e(d.get("education"))}</td>'
        f'<td>{_e(d.get("wage"))}</td><td>{_e(d.get("certificate"))}</td>'
        f'<td>{_e(d.get("industrial_complex_match_status"))}</td>'
        "</tr>"
        for d in records
    )
    return (
        '<div class="dx-table-wrap"><table class="dx-rule-table dx-detail-table">'
        # 열 폭 고정(경력·임금·모집직종은 넉넉히, 자격은 좁게) — 좁은 화면에서는 표만 가로 스크롤
        '<colgroup><col style="width:18%"><col style="width:18%"><col style="width:11%"><col style="width:9%">'
        '<col style="width:17%"><col style="width:12%"><col style="width:15%"></colgroup>'
        '<thead><tr><th>기업 · 공고</th><th>모집직종</th><th>경력</th><th>학력</th><th>임금</th>'
        '<th>자격</th><th>산단 확인</th></tr></thead>'
        f'<tbody>{rows}</tbody></table></div>'
    )


def recruitment_detail_html(jobs: dict) -> str:
    """전체 상세 검증 공고 보기 — 4개 증거수준 tile + 전체 표. 해석 캡션은 호출부(main.py)가 따로 얹는다."""
    if jobs.get("status") != "FOUND":
        return '<div class="dx-empty">현재 확보된 채용공고 없음</div>'
    levels = jobs.get("evidence_levels") or []
    tiles = "".join(
        _level_tile(lv.get("label"), lv.get("count"),
                    None if lv.get("company_count") is None else f"기업 {lv['company_count']:,}개")
        for lv in levels
    )
    details = jobs.get("detail_records") or []
    return (
        f'<div class="dx-level-grid">{tiles}</div>'
        f'<div class="dx-sub-title">상세 검증 공고 {len(details):,}건 — 표본 사실이며 업종 전체의 직무·임금·경력 분포가 아님</div>'
        f'{posting_table_html(details)}'
    )


def candidate_card_html(industry: str, stage: str, display: str, metrics: str,
                        questions: list[str], status_note: str | None = None) -> str:
    """점검 후보 카드(점검 관리 화면). 값은 모두 호출부에서 이미 포맷돼 들어온다."""
    q_html = "".join(f"<li>{_e(q)}</li>" for q in questions)
    q_block = (f'<div class="dx-cand-q"><div class="dx-cand-q-label">핵심 확인</div><ul>{q_html}</ul></div>'
              if questions else "")
    note = f'<div class="dx-footnote dx-muted">{_e(status_note)}</div>' if status_note else ""
    return (
        '<div class="dx-cand-head">'
        f'<span class="dx-cand-name">{_e(industry)}</span>{stage_badge_html(stage, display)}'
        '</div>'
        f'<div class="dx-cand-metrics">{_e(metrics)}</div>'
        f'{q_block}'
        f'{note}'
    )


def support_summary_html(first_owner: str | None, functions: list[dict], cards: list[dict],
                         title: str | None = "지원체계 검토 경로", label_of=None) -> str:
    """"지원체계 검토 경로" 요약 카드 — 기능별 등록 요건 카드 수만 센다(적격 판정 아님).

    title=None이면 카드 안 panel-title을 생략한다(화면에서 section()으로 이미 제목을 그릴 때).
    label_of(tag)가 있으면 기능 표시명을 그것으로 쓴다(화면 용어 통일 — backend 라벨·분류값은 그대로).
    """
    counts: dict[str | None, int] = {}
    for card in cards:
        tag = card.get("function_tag")
        counts[tag] = counts.get(tag, 0) + 1
    rows = []
    for f in functions:
        n = counts.get(f.get("function_tag"), 0)
        right = f"관련 공식사업 {n}건" if n else "공식 요건 카드 없음"
        rows.append('<div class="dx-support-row">'
                    f'<span>✓ {_e(label_of(f.get("function_tag")) if label_of else f.get("function_label"))}</span>'
                    f'<span class="dx-support-count">{_e(right)}</span>'
                    '</div>')
    body = "".join(rows) or '<div class="dx-support-row dx-muted">확인된 지원 기능 후보 없음</div>'
    head = f'<div class="dx-panel-title">{_e(title)}</div>' if title else ""
    return (
        '<div class="dx-support-card">'
        f'{head}'
        f'<div class="dx-report-meta">1차 검토 기능 · {_e(first_owner)}</div>'
        '<div class="dx-sub-title">관련 지원 기능</div>'
        f'{body}'
        '<div class="dx-note">채용 키워드·확인 신호 기반 후보 · 자동 추천·적격 판정 아님</div>'
        '</div>'
    )


def route_summary_html(first_owner: str | None, handoff_functions: str | None, institutions: list[dict]) -> str:
    """정책·지원 연계 화면의 검토 경로 요약(1차/인계 검토 기능 + 참고 기관). 기능별 카드는 support_function_card_html이 맡는다."""
    # 참고 기관은 공식 지원사업보다 한 단계 낮은 보조정보 — 기관명 semibold, 기능 muted, 출처는 작은 링크
    inst_items = "".join(
        f'<li><span class="dx-inst-name">{_e(i.get("institution"))}</span>'
        f'<span class="dx-inst-fn">{_e(i.get("role"))} · {_e(i.get("function"))}</span>'
        f'{_link(i.get("source_url"), "기관 출처")}</li>'
        for i in institutions
    ) or "<li>참고 기관 없음</li>"
    return (
        '<div class="dx-handoff-card">'
        '<div class="dx-handoff-title">기존 지원체계 검토 경로 (참고)</div>'
        f'<div class="dx-handoff-row"><span>1차 검토 기능</span><strong>{_e(first_owner)}</strong></div>'
        f'<div class="dx-handoff-row"><span>인계 검토 기능</span><strong>{_e(handoff_functions)}</strong></div>'
        f'<div class="dx-inst-head">참고 기관(기능 확인됨) {len(institutions)}곳</div>'
        f'<ul class="dx-inst-list">{inst_items}</ul>'
        '<div class="dx-handoff-note">자동 추천·적격 판정이 아니며, 개별 기업의 적격·승인·지급 여부는 담당기관 확인 후, '
        '지원 여부는 담당자 현장 검토 후 결정합니다.</div>'
        '</div>'
    )


def support_function_card_html(function: dict, cards: list[dict]) -> str:
    """정책·지원 연계 화면 — 선택 기능 1개의 공식 요건 카드 목록(대상/요건/지원내용/문의/확인일/근거 위치까지 그대로)."""
    intake_label = {"OPEN": "접수 OPEN", "UNKNOWN": "접수 상태 확인 필요"}
    card_html = "".join(
        '<div class="dx-fn-card">'
        f'<div class="dx-fn-card-title">{_e(c.get("title"))}</div>'
        f'<div class="dx-fn-card-inst">{_e(c.get("institution"))} · '
        f'{_e(intake_label.get(c.get("current_intake_status"), c.get("current_intake_status")))}</div>'
        + (f'<div class="dx-route-caveat">{_e(c.get("caveat"))}</div>' if c.get("caveat") else "")
        + f'<div class="dx-fn-card-links">{_link(c.get("source_url"), "공식 근거")}</div>'
        + '<details class="dx-more"><summary>상세 보기</summary>'
        + f'<div>대상 · {_e(c.get("target"))}</div>'
        + f'<div>요건 · {_e(c.get("eligibility"))}</div>'
        + f'<div>지원 내용 · {_e(c.get("support_content"))}</div>'
        + f'<div>문의 · {_e(c.get("contact"))}</div>'
        + f'<div>확인일 · {_e(c.get("verified_at"))}</div>'
        + "".join(f'<div>근거 위치 · {_e(p.get("page") or p.get("section"))}</div>'
                  for p in (c.get("provenance") or []))
        + '</details>'
        '</div>'
        for c in cards
    ) or '<div class="dx-fn-card dx-muted">등록된 요건 카드 없음</div>'
    kw = ", ".join(function.get("evidence_keywords") or [])
    return (
        '<div class="dx-fn-group">'
        f'<div class="dx-fn-group-head"><b>{_e(function.get("function_label"))}</b>'
        f'<span class="dx-muted">관련 사업 {len(cards)}건</span></div>'
        f'<div class="dx-route-kw">근거 신호 · {_e(kw)}</div>'
        f'<div class="dx-support-grid">{card_html}</div>'
        '</div>'
    )


def distribution_pills_html(counts: dict[str, int]) -> str:
    order = (("우선점검", "우선점검 후보", "rose"), ("추가확인", "추가확인", "amber"), ("관찰", "관찰", "emerald"))
    items = "".join(
        f'<span class="dx-pill dx-tone-{tone}">{_e(display)} {counts.get(stage, 0)}</span>'
        for stage, display, tone in order
    )
    return f'<div class="dx-pill-row">{items}</div>'


# ------------------------------------------------------------------ 행정 AI 비서 답변 표시
def answer_html(structured: dict) -> str:
    """결론 → 근거 → 다음 확인. structured = view_models.structure_answer() 결과(문장은 backend 원문 그대로)."""
    lead = f'<div class="dx-ans-lead">{_e(structured.get("conclusion"))}</div>' if structured.get("conclusion") else ""
    points = "".join(f"<li>{_e(p)}</li>" for p in structured.get("points") or [])
    points_html = f'<ul class="dx-ans-points">{points}</ul>' if points else ""
    nxt = " ".join(structured.get("next") or [])
    next_html = f'<div class="dx-ans-next">다음 확인 · {_e(nxt)}</div>' if nxt else ""
    return f'<div class="dx-ans">{lead}{points_html}{next_html}</div>'


def comparison_html(view: dict) -> str:
    """업종 비교 — 한 줄 결론 / 업종별 수치 표 + 핵심 해석 / 차이 / 해석 주의. 중첩 카드 없이 구분선만 쓴다."""
    def side(s: dict) -> str:
        rows = "".join(
            f'<tr><td>{_e(k)}</td><td class="{"dx-cmp-hit" if hit else ""}">{_e(v)}</td></tr>'
            for k, v, hit in s["metrics"])
        notes = "".join(f"<li>{_e(n)}</li>" for n in s["notes"])
        return (f'<div class="dx-cmp-side"><div class="dx-cmp-name">{_e(s["name"])} '
                f'{stage_badge_html(s["stage"], s["display"])}</div>'
                f'<table class="dx-cmp-table">{rows}</table>'
                f'<div class="dx-cmp-label">핵심 해석</div><ul class="dx-ans-points">{notes}</ul></div>')
    diff = "".join(f"<li>{_e(d)}</li>" for d in view["diff"])
    return (f'<div class="dx-ans"><div class="dx-ans-lead">{_e(view["conclusion"])}</div>'
            f'<div class="dx-cmp">{"".join(side(s) for s in view["sides"])}</div>'
            f'<div class="dx-cmp-label">차이</div><ul class="dx-ans-points">{diff}</ul>'
            f'<div class="dx-ans-next">해석 주의 · {_e(view["caveat"])}</div></div>')


# ------------------------------------------------------------------ 공모전 팀 제안(정본 자료)
# ------------------------------------------------------------------ 정책·지원 연계(공식 지원 연계 / 공모전 팀 제안)
POLICY_TABS = (("공식 지원 연계", "현재 업종·분기와 연결 가능한 기존 지원사업", ""),
               ("공모전 팀 제안", "분석 기반 정책 개선·신규 제안", "전 업종 공통"))


def policy_guide_html(active: str) -> str:
    """왼쪽 패널의 '이 페이지의 구성' — 위치 안내만(링크·버튼 없음, 새 navigation 아님)."""
    rows = "".join(
        f'<div class="dx-guide-row{" is-active" if name == active else ""}{" is-team" if note else ""}">'
        f'<div class="dx-guide-name">{_e(name)}</div><div class="dx-guide-desc">{_e(desc)}</div>'
        + (f'<div class="dx-guide-note">({_e(note)})</div>' if note else "") + '</div>'
        for name, desc, note in POLICY_TABS)
    return f'<div class="dx-guide"><div class="dx-guide-head">이 페이지의 구성</div>{rows}</div>'


def policy_context_html(industry: str, quarter: str, badge_html: str) -> str:
    return ('<div class="dx-pctx"><div class="dx-pctx-label">현재 선택 업종 및 진단 결과</div>'
            f'<div class="dx-pctx-row"><b>{_e(industry)}</b><span class="dx-pctx-sep">|</span><b>{_e(quarter)}</b>'
            f'<span class="dx-pctx-sep">|</span>{badge_html}</div>'
            '<div class="dx-pctx-help">현재 화면은 선택한 업종과 분기를 기준으로 조회합니다. '
            '적격·선정 여부를 자동 판정하지 않습니다.</div></div>')


def official_programs_html(cards: list[dict], fn_label) -> str:
    """공식 지원사업 카드(등록 요건 카드 값만 — 없는 대상·내용은 만들지 않는다). fn_label(tag) = 화면 라벨."""
    intake = {"OPEN": ("접수 중", "open"), "UNKNOWN": ("접수 상태 확인 필요", "unknown")}

    def card(c: dict) -> str:
        status, tone = intake.get(c.get("current_intake_status"), (c.get("current_intake_status") or "—", "unknown"))
        more = "".join(f'<div><b>{k}</b> {_e(v)}</div>' for k, v in (
            ("요건", c.get("eligibility")), ("문의", c.get("contact")), ("확인일", c.get("verified_at"))) if v)
        more += "".join(f'<div><b>근거 위치</b> {_e(p.get("page") or p.get("section"))}</div>'
                        for p in (c.get("provenance") or []))
        apply = _link(c.get("intake_url"), "신청 경로")
        return (
            '<div class="dx-prog">'
            f'<div class="dx-prog-top"><span class="dx-prog-fn">{_e(fn_label(c.get("function_tag")))}</span>'
            f'<span class="dx-prog-status is-{tone}">{_e(status)}</span></div>'
            f'<div class="dx-prog-title">{_e(c.get("title"))}</div>'
            f'<div class="dx-prog-inst">{_e(c.get("institution"))}</div>'
            + (f'<div class="dx-prog-desc">유의 · {_e(c.get("caveat"))}</div>' if c.get("caveat") else "")
            + '<dl class="dx-prog-rows">'
            f'<dt>지원 대상</dt><dd>{_e(c.get("target"))}</dd>'
            f'<dt>지원 내용</dt><dd>{_e(c.get("support_content"))}</dd>'
            f'<dt>접수 상태</dt><dd>{_e(status)}</dd></dl>'
            '<div class="dx-prog-actions">'
            f'<details class="dx-prog-more"><summary>상세 보기</summary><div class="dx-prog-detail">'
            f'{more or "<div>등록된 추가 정보 없음</div>"}{f"<div>{apply}</div>" if apply else ""}</div></details>'
            f'{_link(c.get("source_url"), "공식 근거").replace("dx-link", "dx-link dx-prog-src")}'
            '</div></div>')
    if not cards:
        return '<div class="dx-prog-empty">조건에 맞는 등록 공식 지원사업이 없습니다.</div>'
    return f'<div class="dx-prog-grid">{"".join(card(c) for c in cards)}</div>'


def bizinfo_list_html(items: list[dict]) -> str:
    """기업마당 최신 공고(공고명·기관·접수기간/상태·공고 보기만). 업종 적합성·신청자격은 표시하지 않는다."""
    status = {"OPEN": "접수 중"}
    rows = "".join(
        '<div class="dx-biz-item">'
        f'<div class="dx-biz-title">{_e(i.get("title"))}</div>'
        f'<div class="dx-biz-meta">{_e(i.get("agency") or i.get("executor"))} · '
        f'{_e(i.get("period_text") or " ~ ".join(x for x in (i.get("start"), i.get("end")) if x))} · '
        f'{_e(status.get(i.get("recruitment_status"), i.get("recruitment_status")))}</div>'
        f'{_link(i.get("detail_url"), "공고 보기")}</div>'
        for i in items)
    return f'<div class="dx-biz">{rows}</div>'


def team_flow_html(steps) -> str:
    """산업·고용 전환 대응 정책체계 — 단순 단계 흐름(가로, 좁은 화면은 가로 스크롤)."""
    cells = '<span class="dx-flow-arrow">→</span>'.join(
        f'<div class="dx-flow-step"><div class="dx-flow-name">{_e(name)}</div><div class="dx-flow-help">{_e(help_)}</div></div>'
        for name, help_ in steps)
    return ('<div class="dx-flow-wrap"><div class="dx-flow-head">산업·고용 전환 대응 정책체계</div>'
            f'<div class="dx-flow">{cells}</div></div>')


def team_cards_html(proposals, kpis, principles) -> str:
    """팀 제안 카드(2열, 좁으면 1열). 자세히 보기 = A 왜 필요한가 / B 작동 방식 / C 기대효과 / D 성과 확인 지표 /
    E 추진 전 확인사항·원칙 / F 시스템 연결. 모두 정본·팀 정리 문구만 쓴다(KPI는 정본에 있는 것만)."""
    def section(tag: str, title: str, body: str) -> str:
        return f'<div class="dx-tsec"><div class="dx-tsec-h">{tag}. {title}</div>{body}</div>'

    def steps(xs) -> str:
        return '<ol class="dx-tsteps">' + "".join(f"<li>{_e(x)}</li>" for x in xs) + "</ol>"

    def card(p: dict) -> str:
        kp = kpis(p)
        rows = principles(p)
        core = [v for k, v in rows if k == "핵심 기대효과"]  # 정본의 '핵심 기대효과' 서술은 C로
        pr = [(k, v) for k, v in rows if k not in ("운영", "구조", "핵심 기대효과")]  # 운영·구조 흐름은 B에 있음
        body = (
            section("A", "왜 필요한가", f'<p>{_e(p["why"])}</p>')
            + section("B", "작동 방식", steps(p["flow"]))
            + section("C", "기대효과", f'<p>{_e(p["effect_detail"])}</p>' + "".join(f"<p>{_e(v)}</p>" for v in core))
            + section("D", "성과 확인 지표",
                      ('<ul>' + "".join(f"<li>{_e(k)}</li>" for k in kp) + '</ul>') if kp
                      else '<p class="dx-muted">정본에 별도 KPI가 없습니다(조건부 검토안).</p>')
            + section("E", "추진 전 확인사항·원칙",
                      "".join(f'<p><b>{_e(k)}</b> · {_e(v)}</p>' for k, v in pr) or '<p class="dx-muted">—</p>')
            + section("F", "시스템 연결", f'<p>{" → ".join(_e(x) for x in p["linkage"])}</p>'))
        stages = "".join(f'<span class="dx-tstage">{_e(s)}</span>' for s in p["stages"])
        return (
            '<div class="dx-tcard">'
            f'<div class="dx-tcard-badges"><span class="dx-tkind">{_e(p["kind"])}</span>{stages}</div>'
            f'<div class="dx-tcard-title">{_e(p["title"])}</div>'
            f'<div class="dx-tcard-summary">{_e(p["summary"])}</div>'
            f'<div class="dx-tcard-effect"><span>기대효과</span> {_e(p["effect"])}</div>'
            f'<details class="dx-tmore"><summary>자세히 보기</summary>{body}</details>'
            '</div>')
    return f'<div class="dx-tgrid">{"".join(card(p) for p in proposals)}</div>'


POLICY_TAB_HELP = {
    "공식 지원 연계": "현재 업종·분기와 연계 가능한 기존 공식 지원사업과 관련 기관을 확인합니다.",
    "공모전 팀 제안": "분석 결과를 기반으로 제안하는 정책 개선·신규 제안입니다. 지금 활용 가능한 기존 제도는 [공식 지원 연계]에서 확인합니다.",
}


def team_intro_html() -> str:
    return ('<div class="dx-team-intro">아래 내용은 현재 시행 중인 공식 지원사업이 아니라, 기존 사업·제도와 분석 결과를 '
            '바탕으로 구성한 정책 개선·신규 제안입니다. 전 업종 공통이며 선택한 업종에 맞춘 정책이 아닙니다.</div>')


def section_count_html(title: str, count: str) -> str:
    """소제목 + 오른쪽 건수(공식 지원사업 · 관련 사업 N건)."""
    return (f'<div class="dx-section-head dx-count-head"><span class="dx-section-title">{_e(title)}</span>'
            f'<span class="dx-count">{_e(count)}</span></div>')


def labeled_badge_html(label: str, badge_html: str) -> str:
    return f'<div class="dx-labeled"><span>{_e(label)}</span>{badge_html}</div>'
