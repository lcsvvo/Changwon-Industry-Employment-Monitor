"""3패널 업종 진단 화면을 위한 순수 HTML 조각 빌더.

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


def _e(value) -> str:
    if value is None or value == "":
        return "—"
    return _html.escape(str(value))


def stage_badge_html(stage: str | None, label: str | None = None) -> str:
    tone = STAGE_TONE.get(stage or "", "muted")
    return f'<span class="dx-badge dx-badge--{tone}">{_e(label or stage)}</span>'


def header_html(quarter: str, industry: str, stage: str | None, stage_label: str | None,
                meta_line: str, nature_html: str = "") -> str:
    return (
        '<div class="dx-report-header">'
        '<div class="dx-report-header-main">'
        f'<div class="dx-report-title">[{_e(quarter)}] 창원국가산단 산업·고용 진단카드 : {_e(industry)}</div>'
        f'<div class="dx-report-meta">{_e(meta_line)}</div>'
        f'{nature_html}'
        '</div>'
        f'<div class="dx-report-stage">{stage_badge_html(stage, stage_label)}</div>'
        '</div>'
    )


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


def fact_caveat_html(facts: list[str], caveats: list[str]) -> str:
    fact_lines = "".join(f"<li>{_e(x)}</li>" for x in facts) or "<li>확인된 사실 없음</li>"
    caveat_lines = "".join(f"<li>{_e(x)}</li>" for x in caveats) or "<li>표시할 한계 없음</li>"
    return (
        '<div class="dx-two-col">'
        '<div class="dx-panel-card dx-panel-card--emerald">'
        '<div class="dx-panel-title">데이터로 직접 확인된 사실 (Fact)</div>'
        f'<ul>{fact_lines}</ul>'
        '</div>'
        '<div class="dx-panel-card dx-panel-card--amber">'
        '<div class="dx-panel-title">현재 통계로 단정할 수 없는 한계 (Caveat)</div>'
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


def brand_html(rule_version: str) -> str:
    return (
        '<div class="dx-brand">'
        '<div class="dx-brand-icon">◆</div>'
        '<div><div class="dx-brand-title">창원국가산단 산업·고용 전환진단 AI 코파일럿'
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


def recruitment_html(jobs: dict, keywords: list[dict], is_latest_quarter: bool) -> str:
    """Recruitment Layer 요약. 목록·확인·유효·상세 단계를 섞지 않고, 상세 항목은 상세 검증 공고에서만 보여준다."""
    if jobs.get("status") != "FOUND":
        return ('<div class="dx-empty">현재 확보된 채용공고 없음 · '
                + _e("; ".join(jobs.get("caveat") or ["해당 업종으로 매핑된 Work24 공고가 없습니다."])) + "</div>")
    collected = (jobs.get("collected_at") or "")[:10] or None
    meta = (f'수집 {_e(collected)} · 유효 기준일 {_e(jobs.get("activity_as_of"))} · '
            f'Work24 {_e(jobs.get("quarter"))} 공고 — CORE {_e(jobs.get("core_quarter"))} 판정 입력 아님')
    warn = ("" if is_latest_quarter else
            '<div class="dx-warn">이 스냅샷은 선택한 과거 분기 시점의 자료가 아닙니다. 과거 분기 진단의 근거로 쓰지 마세요.</div>')
    levels = jobs.get("evidence_levels") or [{"label": "목록 데이터", "count": jobs.get("posting_count"),
                                               "company_count": jobs.get("unique_company_count")}]
    tiles = "".join(
        '<div class="dx-level">'
        f'<div class="dx-level-label">{_e(lv.get("label"))}</div>'
        f'<div class="dx-level-value">{"상세 미확인" if lv.get("count") is None else f"{int(lv["count"]):,}건"}</div>'
        f'<div class="dx-level-sub">기업 {"—" if lv.get("company_count") is None else f"{int(lv["company_count"]):,}개"}</div>'
        '</div>'
        for lv in levels
    )
    kw = "".join(f'<span class="dx-chip dx-chip--sky">{_e(k["term"])} <b>{int(k["count"])}</b></span>'
                 for k in keywords) or '<span class="dx-muted">확인된 키워드 없음</span>'
    details = jobs.get("detail_records") or []
    if details:
        rows = "".join(
            "<tr>"
            f'<td><b>{_e(d.get("company_name"))}</b><br><span class="dx-muted">{_e(d.get("posting_title"))}</span></td>'
            f'<td>{_e(d.get("occupation"))}</td><td>{_e(d.get("career"))}</td><td>{_e(d.get("education"))}</td>'
            f'<td>{_e(d.get("wage"))}</td><td>{_e(d.get("certificate"))}</td>'
            f'<td>{_e(d.get("industrial_complex_match_status"))}</td>'
            "</tr>"
            for d in details
        )
        detail_html = (
            f'<div class="dx-sub-title">상세 검증 공고 {len(details):,}건 — 표본 사실이며 업종 전체의 직무·임금·경력 분포가 아님</div>'
            '<div class="dx-table-wrap"><table class="dx-rule-table dx-detail-table">'
            '<thead><tr><th>기업 · 공고</th><th>모집직종</th><th>경력</th><th>학력</th><th>임금</th>'
            '<th>자격</th><th>산단 확인</th></tr></thead>'
            f'<tbody>{rows}</tbody></table></div>'
        )
    else:
        detail_html = '<div class="dx-muted">상세 직무 데이터 미확보 · 목록 정보만으로 직무·임금·경력 분포를 만들지 않습니다.</div>'
    return (
        f'<div class="dx-report-meta">{meta}</div>{warn}'
        f'<div class="dx-level-grid">{tiles}</div>'
        '<div class="dx-sub-title">목록 텍스트 상위 키워드 (공고 내 빈도 · 모집인원 아님)</div>'
        f'<div class="dx-chip-row">{kw}</div>'
        f'{detail_html}'
    )


def handoff_html(first_owner: str | None, handoff_functions: str | None, functions: list[dict],
                 cards: list[dict], institutions: list[dict]) -> str:
    """기존 지원체계 검토 경로. 기능 후보 → 공식 요건 카드(근거 링크) → 참고 기관 순이며 자동 선정이 아니다."""
    by_tag: dict[str, list[dict]] = {}
    for card in cards:
        by_tag.setdefault(card.get("function_tag"), []).append(card)
    fn_items = "".join(
        '<div class="dx-route">'
        f'<div class="dx-route-head"><b>{_e(f.get("function_label"))}</b>'
        f'<span class="dx-route-kw">근거 키워드 {_e(", ".join(f.get("evidence_keywords") or []))}</span></div>'
        + "".join(
            '<div class="dx-route-card">→ '
            f'<b>{_e(c.get("title"))}</b> · {_e(c.get("institution"))} · 접수 {_e(c.get("current_intake_status"))}'
            f' · 확인 {_e(c.get("verified_at"))} {_link(c.get("source_url"), "공식 근거")}'
            + (f'<div class="dx-route-caveat">{_e(c.get("caveat"))}</div>' if c.get("caveat") else "")
            + '</div>'
            for c in by_tag.get(f.get("function_tag"), [])
        )
        + '</div>'
        for f in functions
    ) or '<div class="dx-handoff-sub">채용 키워드와 연결된 지원 기능 후보 없음</div>'
    inst_items = "".join(
        f'<li><b>{_e(i.get("institution"))}</b> · {_e(i.get("role"))} · {_e(i.get("function"))} '
        f'{_link(i.get("source_url"), "기관 출처")}</li>'
        for i in institutions
    ) or "<li>참고 기관 없음</li>"
    return (
        '<div class="dx-handoff-card">'
        '<div class="dx-handoff-title">기존 지원체계 검토 경로 (참고)</div>'
        f'<div class="dx-handoff-row"><span>1차 검토 기능</span><strong>{_e(first_owner)}</strong></div>'
        f'<div class="dx-handoff-row"><span>인계 검토 기능</span><strong>{_e(handoff_functions)}</strong></div>'
        '<div class="dx-handoff-sub">검토 가능한 지원 기능 후보 → 공식 요건 카드</div>'
        f'{fn_items}'
        '<details class="dx-handoff-inst"><summary>참고 기관(기능 확인됨) '
        f'{len(institutions)}곳</summary><ul>{inst_items}</ul></details>'
        '<div class="dx-handoff-note">자동 추천·적격 판정이 아니며, 개별 기업의 적격·승인·지급 여부는 담당기관 확인 후, '
        '지원 여부는 담당자 현장 검토 후 결정합니다.</div>'
        '</div>'
    )


def distribution_pills_html(counts: dict[str, int]) -> str:
    order = (("우선점검", "rose"), ("추가확인", "amber"), ("관찰", "emerald"))
    items = "".join(
        f'<span class="dx-pill dx-tone-{tone}">{_e(label)} {counts.get(label, 0)}</span>'
        for label, tone in order
    )
    return f'<div class="dx-pill-row">{items}</div>'
