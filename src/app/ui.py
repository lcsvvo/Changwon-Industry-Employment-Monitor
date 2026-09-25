"""3패널 업종 진단/점검 관리/정책 연계 화면을 위한 순수 HTML 조각 빌더.

여기 함수는 streamlit을 import하지 않고 문자열만 만든다(단위 테스트 대상). 모든
데이터 값은 html.escape 처리하며, 렌더링은 호출부에서 ``st.html(...)``로 한다.
숫자·경계값을 새로 계산하지 않고 이미 포맷된 문자열만 조합한다.
"""
from __future__ import annotations

import html as _html
from typing import Iterable

from app.view_models import REPORT_NOTICE as REPORT_NOTICE_TEXT, provenance_lines, quarter_text  # 분기 표시 '2026년 2분기'(저장값은 2026Q2)

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
    title = f"[{quarter_text(quarter)}] 창원국가산단 산업·고용 진단카드 : {industry}"
    return page_header_html(title, meta_line, stage_badge_html(stage, stage_label))


def kpi_cards_html(cards: Iterable[dict]) -> str:
    items = "".join(
        '<div class="dx-kpi">'
        f'<div class="dx-kpi-label">{_e(c.get("label"))}</div>'
        f'<div class="dx-kpi-value dx-tone-{_e(c.get("tone") or "default")}'
        f'{" dx-kpi-value--text" if c.get("text") else ""}">{_e(c.get("value"))}</div>'
        f'<div class="dx-kpi-sub">{_e(c.get("sub"))}</div>'
        '</div>'
        for c in cards
    )
    return f'<div class="dx-kpi-grid">{items}</div>'


def rule_table_html(rows: list[dict], footnote: str) -> str:
    # 현재값 숫자는 판정 배지와 같은 색(상위=빨강, 진입·충족=주황, 통과=초록, 미달·미확인=기본)
    body = "".join(
        "<tr>"
        f'<td>{_e(r.get("signal"))}</td>'
        f'<td class="dx-cur dx-cur--{VERDICT_TONE.get(r.get("verdict"), "muted")}">{_e(r.get("current"))}</td>'
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
            # 숫자가 없는 문장형 값(예: '직전 분기에도 진입신호')은 카드 폭에 맞춘 작은 글씨로 한 줄에
            f'<div class="dx-reason-value{"" if any(ch.isdigit() for ch in str(it.get("value") or "")) else " dx-reason-value--text"}">'
            f'{_e(it.get("value"))}</div>'
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
        state = f' <span class="dx-muted">{_e(row["q1_state"])}</span>' if row.get("q1_state") else ""
        parts.append(f'{prefix}{_e(quarter_text(row.get("quarter")))} '
                     f'<span class="dx-pill dx-tone-{tone}">{_e(label)}</span>{state}')
    return '<div class="dx-trail">' + " ← ".join(parts) + '</div>'


# ------------------------------------------------------------------ 업종 진단 상단 점검 대기열 · 5초 요약
def _state_cls(state: str | None) -> str:
    """Q1 국면별 글자색 class(S1~S4, 그 밖은 muted). 색만으로 구분하지 않도록 문구·S코드는 항상 함께 쓴다."""
    return state if state in ("S1", "S2", "S3", "S4") else "muted"


def queue_card_html(row: dict, selected: bool) -> str:
    """점검 대기열의 우선점검 후보·추가확인 카드(값은 view_models.queue_rows가 포맷한 그대로)."""
    cls = "dx-qcard is-selected" if selected else "dx-qcard"
    sel = '<span class="dx-qcard-sel">선택됨</span>' if selected else ""
    return (
        f'<div class="{cls}">'
        f'<div class="dx-qcard-head"><span class="dx-qcard-name">{_e(row["industry"])}</span>'
        f'{stage_badge_html(row["stage"], row["display"])}<span class="dx-qcard-status">점검상태 · {_e(row["status"])}</span>{sel}</div>'
        f'<div class="dx-qcard-state dx-state--{_state_cls(row["state"])}">{_e(row["state_plain"])} '
        f'<span class="dx-muted">{_e(row["state"])}</span></div>'
        '<div class="dx-qcard-metrics">'
        f'<span>고용 <b>{_e(row["emp_delta"])}</b> (YoY {_e(row["emp_yoy"])})</span>'
        f'<span>산단 고용 비중 <b>{_e(row["share"])}</b></span>'
        f'<span>지속 <b>{_e(row["run"])}</b></span></div>'
        f'<div class="dx-qcard-reason">{_e(row.get("summary") or row["reason"])}</div>'
        '</div>'
    )


def queue_table_html(rows: list[dict], selected: str | None, rank_help: str) -> str:
    """관찰 업종 압축 표(카드 반복 대신). 참고 순위는 관찰 단계 안의 비교 순위다."""
    body = "".join(
        f'<tr class="{"is-selected" if r["industry"] == selected else ""}">'
        f'<td>{_e(r["rank"])}</td><td class="dx-state--{_state_cls(r["state"])}"><b>{_e(r["industry"])}</b>'
        f'{" ✓" if r["industry"] == selected else ""}</td>'
        f'<td class="dx-muted">{_e(r["state_plain"])} '
        f'<span class="dx-muted">{_e(r["state"])}</span></td>'
        f'<td>{_e(r["emp_delta"])} <span class="dx-muted">({_e(r["emp_yoy"])})</span></td>'
        f'<td>{_e(r["share"])}</td><td>{_e(r["run"])}</td><td>{_e(r["status"])}</td></tr>'
        for r in rows)
    return (
        '<div class="dx-table-wrap"><table class="dx-rule-table dx-queue-table">'
        f'<thead><tr><th title="{_e(rank_help)}">참고 순위 ⓘ</th><th>업종</th><th>산업·고용 상태</th>'
        '<th>고용 증감 (YoY)</th><th>산단 고용 비중</th><th>지속</th><th>점검상태</th></tr></thead>'
        f'<tbody>{body}</tbody></table></div>'
        f'<div class="dx-footnote">참고 순위 = {_e(rank_help)}</div>'
    )


def case_progress_html(title: str, status: str, rows: list[tuple[str, str]], next_text: str | None,
                       tone: str = "") -> str:
    """점검 진행 요약 — 제목·상태 한 줄, 항목 격자, '다음 할 일' 한 줄(next_text=None이면 생략 — 종결 건).

    tone='closed'면 종결 결과 요약 모양(회색 띠)으로 그린다. 값은 view_models가 만든 그대로 escape해서 쓴다.
    """
    items = "".join(f'<div class="dx-cprog-item"><span>{_e(k)}</span><b>{_e(v)}</b></div>' for k, v in rows)
    nxt = f'<div class="dx-cprog-next"><span>다음 할 일</span> {_e(next_text)}</div>' if next_text else ""
    return (
        f'<div class="dx-cprog{" dx-cprog--closed" if tone == "closed" else ""}">'
        f'<div class="dx-cprog-head"><span class="dx-cprog-title">{_e(title)}</span>'
        f'<span class="dx-cprog-status">{_e(status)}</span></div>'
        f'<div class="dx-cprog-grid">{items}</div>{nxt}'
        '</div>'
    )


def simple_table_html(headers: list[str], rows: list[list], num_cols: tuple[int, ...] = (),
                      widths: list[str] | None = None, row_classes: list[str] | None = None) -> str:
    """읽기 전용 표(모든 값 escape). 빈 값은 '—'. 좁은 화면에서는 표만 가로 스크롤."""
    cols = "".join(f'<col style="width:{w}">' if w else "<col>" for w in widths) if widths else ""
    head = "".join(f'<th class="{"num" if i in num_cols else ""}">{_e(h)}</th>' for i, h in enumerate(headers))
    body = "".join(
        f'<tr class="{(row_classes or [""] * len(rows))[r]}">'
        + "".join(f'<td class="{"num" if i in num_cols else ""}">{_e(v)}</td>' for i, v in enumerate(row)) + "</tr>"
        for r, row in enumerate(rows))
    return (f'<div class="dx-table-wrap"><table class="dx-rule-table dx-simple-table">'
            f'{f"<colgroup>{cols}</colgroup>" if cols else ""}<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>')


def check_table_html(rows: list[dict]) -> str:
    """현장확인 문항 압축 표 — rows = [{no, text, done, result}]. 기록·미기록은 글자와 색으로 함께 구분한다."""
    body = "".join(
        f'<tr class="{"is-done" if r["done"] else "is-pending"}"><td>{_e(r["no"])}</td>'
        f'<td class="dx-chk-q">{_e(r["text"])}</td>'
        f'<td><span class="dx-chk-state">{"기록됨" if r["done"] else "미기록"}</span></td>'
        f'<td>{_e(r["result"])}</td></tr>'
        for r in rows)
    return ('<div class="dx-table-wrap"><table class="dx-rule-table dx-chk-table">'
            '<colgroup><col style="width:3rem"><col><col style="width:5.5rem"><col style="width:13rem"></colgroup>'
            '<thead><tr><th>번호</th><th>확인사항</th><th>상태</th><th>최근 결과</th></tr></thead>'
            f'<tbody>{body}</tbody></table></div>')


def snapshot_brief_html(rows: list[tuple[str, str]]) -> str:
    """5초 요약의 문장 줄(판정 이유·우선 확인). rows = [(라벨, 문장)]."""
    body = "".join(f'<div class="dx-brief-row"><span class="dx-brief-k">{_e(k)}</span>'
                   f'<span class="dx-brief-v">{_e(v)}</span></div>' for k, v in rows)
    return f'<div class="dx-brief">{body}</div>'


def link_flow_html(steps: Iterable[str]) -> str:
    """진단 신호 → … → 공식 문의·접수 경로 한 줄 흐름(좁은 화면에서는 줄바꿈)."""
    cells = '<span class="dx-lflow-arrow">→</span>'.join(f'<span class="dx-lflow-step">{_e(s)}</span>' for s in steps)
    return f'<div class="dx-lflow">{cells}</div>'


def disclaimer_html(text: str) -> str:
    return f'<div class="dx-disclaimer">{_e(text)}</div>'


def copilot_title_html(name: str, mode: str) -> str:
    """AI 패널 제목 — 이름 + 응답 방식(Gemini 설정 여부와 일치)."""
    pill = f'<span class="dx-copilot-mode">{_e(mode)}</span>' if mode else ""  # 방식 표시가 없으면 이름만
    return f'<div class="dx-copilot-title"><span class="dx-dot"></span>{_e(name)}{pill}</div>'


def question_list_html(title: str | None, items: list[tuple[str, str]], caption: str = "", start: int = 1) -> str:
    """현장 확인 질문 번호 목록. items = [(질문, 출처 라벨)]. title이 없으면(화면에서 section()을 쓸 때) 생략.

    start = 첫 번호(추가 확인사항은 4번부터 이어서). 출처 라벨이 빈 값이면 표시하지 않는다.
    """
    rows = "".join(f'<li>{_e(q)}' + (f' <span class="dx-muted">· {_e(src)}</span>' if src else "") + '</li>'
                   for q, src in items)
    cap = f'<div class="dx-footnote">{_e(caption)}</div>' if caption else ""
    head = f'<div class="dx-sub-title">{_e(title)}</div>' if title else ""
    start_attr = f' start="{int(start)}"' if start != 1 else ""
    return f'<div class="dx-qlist">{head}<ol class="dx-qlist-items"{start_attr}>{rows}</ol>{cap}</div>'


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


def _text_units(text: str) -> float:
    """글자 폭 추정(em 단위): 한글 1.0 · 숫자/영문/기호 0.6 · 공백 0.3 · 이모지 1.2."""
    units = 0.0
    for ch in str(text):
        if "가" <= ch <= "힣":
            units += 1.0
        elif ch == " ":
            units += 0.3
        elif ord(ch) > 0x2600:
            units += 1.2
        else:
            units += 0.6
    return units


def context_tags_html(title: str, tags: list[str], optional_tags: bool = False) -> str:
    """Copilot 헤더 아래 컨텍스트 한 줄 — 굵은 제목 + 태그 칩(dx-chip--sky).

    업종명 길이(예: 전기전자)나 태그 수와 관계없이 항상 한 줄: 문구 폭(--ctx-units, em 단위 추정)을 넘겨
    CSS가 '패널 폭 ÷ 문구 폭'으로 글씨 크기를 정한다(짧으면 기본 크기 그대로).
    optional_tags=True(모든 업종에 같은 일반 태그)면 패널이 좁을 때 태그를 숨기고 제목 폭(--ctx-units-min)으로 맞춘다.
    """
    title_units = _text_units(title) * 1.06 + 0.4  # 굵은 제목 가산
    units = title_units + sum(_text_units(t) + 1.25 for t in tags)  # 칩 여백·간격
    chip_cls = "dx-chip dx-chip--sky" + (" dx-chip--opt" if optional_tags else "")
    chips = "".join(f'<span class="{chip_cls}">{_e(t)}</span>' for t in tags)
    line_cls = "dx-copilot-sub dx-ctx-line" + (" dx-ctx-line--opt" if optional_tags else "")
    return (f'<div class="dx-ctx-wrap"><div class="{line_cls}" '
            f'style="--ctx-units:{units * 1.04:.2f};--ctx-units-min:{title_units * 1.04:.2f}">'
            f'<b>{_e(title)}</b> {chips}</div></div>')


def brand_html(rule_version: str, ai_tag: str = "AI 코파일럿") -> str:
    """ai_tag = AI 기능 표시(Gemini 미설정이면 호출부가 규칙 기반 표기를 넘긴다)."""
    return (
        '<div class="dx-brand">'
        '<div class="dx-brand-icon">◆</div>'
        '<div class="dx-brand-text"><div class="dx-brand-title">창원국가산단 산업·고용 전환진단'
        f'<span class="dx-brand-tag">{_e(ai_tag)}</span>'
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
        return (f'<div class="dx-empty">현재 확보된 채용공고 없음 · {_e(caveats)}</div>'
                '<div class="dx-note">채용공고가 없어 채용수요를 판단할 수 없습니다.</div>')
    collected = (jobs.get("collected_at") or "")[:10] or None
    meta = (f'수집 {_e(collected)} · 유효 기준일 {_e(jobs.get("activity_as_of"))} · '
            f'Work24 {_e(quarter_text(jobs.get("quarter")))} 공고')
    warn = "" if is_latest else (
        f'<div class="dx-warn">선택 분기 {_e(quarter_text(selected_quarter))}와 다른 시점(Work24 {_e(quarter_text(jobs.get("quarter")))}) '
        '자료입니다. 과거 분기 진단의 근거로 쓰지 마세요.</div>')
    levels = {lv.get("key"): lv for lv in jobs.get("evidence_levels") or []}
    lst, active = levels.get("LIST") or {}, levels.get("ACTIVE_CONFIRMED") or {}
    detail = levels.get("DETAIL_VERIFIED") or {}
    # KPI 칸에는 숫자만 — 각 수준의 정의는 아래 한 줄(자세한 기준·한계는 방법론·데이터 기준 화면)
    tiles = (_level_tile("목록 데이터", lst.get("count"), None)
            + _level_tile("현재 유효", active.get("count"), None)
            + _level_tile("상세 검증", detail.get("count"), None)
            + _level_tile("확인 기업", detail.get("company_count"), None, unit="개"))
    kw = [(k["term"], k["count"]) for k in keywords]
    # 현재 유효·상세 검증이 모두 0건(또는 미확인)이면 목록 키워드를 채용수요 근거처럼 보이지 않게 한다
    unverified = not active.get("count") and not detail.get("count")
    if unverified:
        warn += ('<div class="dx-warn">현재 검증된 채용공고가 없어 채용수요를 판단할 수 없습니다. '
                 '아래 키워드는 목록 제목 기준 참고값입니다.</div>')
    return (
        f'<div class="dx-report-meta">{meta}</div>{warn}'
        f'<div class="dx-level-grid">{tiles}</div>'
        '<div class="dx-note">현재 유효 = 저장된 목록 마감일 기준 · 상세 검증 = 상세 페이지까지 확인한 공고 · '
        '확인 기업 = 상세 검증 공고의 기업 수</div>'
        f'<div class="dx-sub-title">{"목록 키워드 (참고)" if unverified else "주요 키워드"}</div>'
        f'{chip_row_html(kw, "muted" if unverified else "sky")}'
        # '관찰된 표현'은 observations가 있을 때만(업종 진단 화면은 빈 목록을 넘겨 그리지 않는다)
        + (f'<div class="dx-sub-title">관찰된 표현</div>{bullet_list_html(observations)}' if observations else "")
    )


def representative_postings_html(details: list[dict]) -> str:
    """대표 공고(최대 3건) — 없으면 표를 만들지 않고 빈 상태 안내만 보여준다."""
    if not details:  # 빈 상태(표시할 공고 없음)와 데이터 한계(추정하지 않음)는 서로 다른 정보라 따로 둔다
        return ('<div class="dx-sub-title">대표 공고</div>'
                '<div class="dx-empty-note">상세 검증 공고가 없어 대표 공고를 표시하지 않습니다.</div>')
    return ('<div class="dx-sub-title">대표 공고</div>'
            f'{posting_table_html(details)}')


def posting_table_html(records: list[dict]) -> str:
    if not records:
        return '<div class="dx-muted">상세 직무 데이터 미확보</div>'
    rows = "".join(
        "<tr>"
        f'<td><b>{_e(d.get("company_name"))}</b><br><span class="dx-muted">{_e(d.get("posting_title"))}</span></td>'
        f'<td>{_e(d.get("occupation"))}</td><td>{_e(d.get("career"))}</td><td>{_e(d.get("education"))}</td>'
        f'<td>{_e(d.get("wage"))}</td><td>{_e(d.get("certificate"))}</td>'
        "</tr>"
        for d in records
    )
    return (
        '<div class="dx-table-wrap"><table class="dx-rule-table dx-detail-table">'
        # 열 폭 고정(경력·임금·모집직종은 넉넉히, 자격은 좁게) — 좁은 화면에서는 표만 가로 스크롤
        '<colgroup><col style="width:21%"><col style="width:21%"><col style="width:13%"><col style="width:10%">'
        '<col style="width:20%"><col style="width:15%"></colgroup>'
        '<thead><tr><th>기업 · 공고</th><th>모집직종</th><th>경력</th><th>학력</th><th>임금</th>'
        '<th>자격</th></tr></thead>'
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
        f'<div class="dx-sub-title">상세 검증 공고 {len(details):,}건</div>'
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
                         title: str | None = "지원체계 검토 경로", label_of=None, status_of=None,
                         show_owner: bool = True) -> str:
    """"지원체계 검토 경로" 요약 카드 — 기능별 등록 요건 카드 수만 센다(적격 판정 아님).

    title=None이면 카드 안 panel-title을 생략한다(화면에서 section()으로 이미 제목을 그릴 때).
    label_of(tag)가 있으면 기능 표시명을 그것으로 쓴다(화면 용어 통일 — backend 라벨·분류값은 그대로).
    status_of(tag)가 있으면 기능 아래에 담당기관 검증상태 한 줄을 덧붙인다(등록 매핑 그대로).
    """
    counts: dict[str | None, int] = {}
    for card in cards:
        tag = card.get("function_tag")
        counts[tag] = counts.get(tag, 0) + 1
    rows, confirmed, unmapped = [], [], False
    for f in functions:
        n = counts.get(f.get("function_tag"), 0)
        right = f"관련 공식사업 {n}건" if n else "공식 요건 카드 없음"
        label = label_of(f.get("function_tag")) if label_of else f.get("function_label")
        # 담당기관 검증상태는 기능마다 달지 않고 아래 회색 안내 한 줄로 모은다(등록 매핑 그대로)
        text = status_of(f.get("function_tag")) if status_of else ""
        if text.startswith("담당기관 확인 · "):
            confirmed.append(f"{label} — {text.removeprefix('담당기관 확인 · ')}")
        elif text:
            unmapped = True
        rows.append('<div class="dx-support-row">'
                    f'<span>✓ {_e(label)}</span>'
                    f'<span class="dx-support-count">{_e(right)}</span>'
                    '</div>')
    inst_parts = ([f"담당기관 확인: {', '.join(confirmed)}"] if confirmed else []) + (
        [("그 외 기능은" if confirmed else "모든 기능이") + " 담당기관 미확정(실제 인계 전 담당기관 확인 필요)"]
        if unmapped else [])
    inst_note = f'<div class="dx-note">{_e(" · ".join(["채용 키워드·확인 신호 기반 후보", *inst_parts]))}</div>'
    body = "".join(rows) or '<div class="dx-support-row dx-muted">확인된 지원 기능 후보 없음</div>'
    head = f'<div class="dx-panel-title">{_e(title)}</div>' if title else ""
    return (
        '<div class="dx-support-card">'
        f'{head}'
        + (f'<div class="dx-report-meta">1차 검토 기능 · {_e(first_owner)}</div>' if show_owner else '')
        + '<div class="dx-sub-title">관련 지원 기능</div>'
        f'{body}'
        f'{inst_note}'
        '</div>'
    )


def route_summary_html(first_owner: str | None, handoff_functions: str | None, institutions: list[dict],
                       status_of=None) -> str:
    """정책·지원 연계 화면의 검토 경로 요약(1차/인계 검토 기능 + 참고 기관). 기능별 카드는 support_function_card_html이 맡는다.

    status_of(institution) = 기관 검증상태 표시(기관 감사 결과 그대로). 없으면 '실제 인계 전 담당기관 확인 필요'.
    """
    # 참고 기관은 공식 지원사업보다 한 단계 낮은 보조정보 — 기관명 semibold, 기능 muted, 출처는 작은 링크
    def status(i: dict) -> str:
        label = status_of(i) if status_of else "관련기관 참고 · 실제 인계 전 담당기관 확인 필요"
        tone = "ok" if label.startswith("담당기관 확인") else "warn"
        return f'<span class="dx-inst-status is-{tone}">{_e(label)}</span>'
    inst_items = "".join(
        f'<li><span class="dx-inst-name">{_e(i.get("institution"))}</span>{status(i)}'
        f'<span class="dx-inst-fn">{_e(i.get("role"))} · {_e(i.get("function"))}</span>'
        f'{_link(i.get("source_url"), "기관 출처")}</li>'
        for i in institutions
    ) or "<li>참고 기관 없음</li>"
    confirmed = sum(1 for i in institutions if status_of and status_of(i).startswith("담당기관 확인"))
    return (
        '<div class="dx-handoff-card">'
        '<div class="dx-handoff-title">기존 지원체계 검토 경로 (참고)</div>'
        f'<div class="dx-handoff-row"><span>1차 검토 기능</span><strong>{_e(first_owner)}</strong></div>'
        f'<div class="dx-handoff-row"><span>인계 검토 기능</span><strong>{_e(handoff_functions)}</strong></div>'
        f'<div class="dx-inst-head">참고 기관 {len(institutions)}곳 · 담당기관 확인 {confirmed}곳</div>'
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
        + "".join(f'<div>근거 위치 · {_e(x)}</div>' for x in provenance_lines(c))
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
POLICY_TABS = (("공식 지원 연계", "검토 가능한 지원제도·모집 중 공고·담당기관", ""),
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
            f'<div class="dx-pctx-row"><b>{_e(industry)}</b><span class="dx-pctx-sep">|</span><b>{_e(quarter_text(quarter))}</b>'
            f'<span class="dx-pctx-sep">|</span>{badge_html}</div>'
            '<div class="dx-pctx-help">현재 화면은 선택한 업종과 분기를 기준으로 조회합니다.</div></div>')


def official_programs_html(cards: list[dict], fn_label, doc_titles: dict | None = None) -> str:
    """공식 지원사업 카드(등록 요건 카드 값만 — 없는 대상·내용은 만들지 않는다). fn_label(tag) = 화면 라벨.

    doc_titles = {document_id: 공식문서명}(근거 위치 표시용). 쪽·절이 등록되지 않았으면 '공식 근거 위치 상세 미등록'.
    """
    intake = {"OPEN": ("접수 중", "open"), "UNKNOWN": ("접수 상태 확인 필요", "unknown")}

    def card(c: dict) -> str:
        status, tone = intake.get(c.get("current_intake_status"), (c.get("current_intake_status") or "—", "unknown"))
        more = "".join(f'<div><b>{k}</b> {_e(v)}</div>' for k, v in (
            ("요건", c.get("eligibility")), ("유의", c.get("caveat")), ("확인일", c.get("verified_at"))) if v)
        more += "".join(f'<div><b>근거 위치</b> {_e(x)}</div>'
                        for x in provenance_lines(c, (doc_titles or {}).get(c.get("document_id"))))
        apply = _link(c.get("intake_url"), "신청 경로")
        contact = c.get("contact") or "공식 근거·공고문에서 확인"
        return (
            '<div class="dx-prog">'
            f'<div class="dx-prog-top"><span class="dx-prog-fn">{_e(fn_label(c.get("function_tag")))}</span>'
            f'<span class="dx-prog-status is-{tone}">{_e(status)}</span></div>'
            f'<div class="dx-prog-title">{_e(c.get("title"))}</div>'
            f'<div class="dx-prog-inst">{_e(c.get("institution"))}</div>'
            + '<dl class="dx-prog-rows">'
            f'<dt>지원 대상</dt><dd>{_e(c.get("target"))}</dd>'
            f'<dt>지원 내용</dt><dd>{_e(c.get("support_content"))}</dd>'
            f'<dt>접수 상태</dt><dd>{_e(status)}</dd>'
            f'<dt>문의·접수</dt><dd>{_e(contact)}</dd></dl>'
            '<div class="dx-prog-actions">'
            f'<details class="dx-prog-more"><summary>상세 보기</summary><div class="dx-prog-detail">'
            f'{more or "<div>등록된 추가 정보 없음</div>"}{f"<div>{apply}</div>" if apply else ""}</div></details>'
            f'{_link(c.get("source_url"), "공식 근거").replace("dx-link", "dx-link dx-prog-src")}'
            '</div></div>')
    if not cards:
        return '<div class="dx-prog-empty">조건에 맞는 등록 지원제도가 없습니다.</div>'
    return f'<div class="dx-prog-grid">{"".join(card(c) for c in cards)}</div>'


def notice_cards_html(items: list[dict], fn_label, reasons_of) -> str:
    """현재 모집 중인 관련 공고 카드(공식 지원제도 카드와 같은 모양, 출처는 작은 메타데이터로만).

    fn_label(tag) = 지원 기능 표시명. reasons_of는 호출 호환용으로 받기만 한다 — 카드에 연결 사유 목록을 그리지 않는다.
    지원대상 적합성·신청 가능 여부는 판정하지 않는다(확인 안내는 목록 아래 한 줄 caption이 맡는다).
    """
    def card(i: dict) -> str:
        badges = [fn_label(t) for t in (i.get("function_tags") or [])][:2] or ([i["category"].split(" > ")[0]]
                                                                               if i.get("category") else [])
        badge_html = "".join(f'<span class="dx-prog-fn">{_e(b)}</span>' for b in badges)
        agency = i.get("agency") or i.get("executor")
        period = " ~ ".join(x for x in (i.get("start"), i.get("end")) if x) or i.get("period_text")
        # 공식 지원제도 카드(official_programs_html)와 같은 틀·행 이름·버튼 모양. 'dx-notice'(안내 상자) class는 쓰지 않는다
        return (
            '<div class="dx-prog dx-prog--notice">'
            f'<div class="dx-prog-top"><span class="dx-notice-badges">{badge_html}</span>'
            '<span class="dx-prog-status is-open">접수 중</span></div>'
            f'<div class="dx-prog-title">{_e(i.get("title"))}</div>'
            f'<div class="dx-prog-inst">{_e(agency)} · <span class="dx-notice-src">출처 · 기업마당</span></div>'
            '<dl class="dx-prog-rows">'
            f'<dt>지원 대상</dt><dd>{_e(i.get("target") or "공고문 확인")}</dd>'
            f'<dt>접수 기간</dt><dd>{_e(period)}</dd>'
            '<dt>접수 상태</dt><dd>접수 중</dd>'
            '<dt>문의·접수</dt><dd>공고문에서 확인</dd>'
            '</dl>'
            + f'<div class="dx-prog-actions">{_link(i.get("detail_url"), "공고 보기").replace("dx-link", "dx-link dx-prog-src")}</div>'
            '</div>')
    return f'<div class="dx-prog-grid">{"".join(card(i) for i in items)}</div>'


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
    "공식 지원 연계": "현재 진단 결과로 검토할 수 있는 지원제도, 지금 모집 중인 관련 공고, 담당기관을 차례로 확인합니다.",
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


# ------------------------------------------------------------------ 담당자 인계용 진단 요약(진단서) — 전용 HTML·CSS
# 앱 전체 CSS(dashboard.css)를 넣지 않고 진단서 전용 스타일만 쓴다. class는 모두 'rp-' 접두어(앱 화면 CSS와 충돌 없음).
REPORT_CSS = """
@page { size: A4; margin: 14mm; }
.rp-doc { font-family: Pretendard, 'Noto Sans KR', 'Malgun Gothic', sans-serif; color: #1F2937; font-size: 10pt;
  line-height: 1.5; background: #fff; max-width: 182mm; margin: 0 auto; }
.rp-doc * { box-sizing: border-box; }
.rp-doc p { margin: 0 0 2pt; font-size: 10pt; line-height: 1.5; }
.rp-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 12pt;
  border-bottom: 2px solid #0F172A; padding-bottom: 6pt; }
.rp-title { font-size: 19pt; font-weight: 800; color: #0F172A; line-height: 1.25; margin: 0; padding: 0; }
.rp-sub { font-size: 11.5pt; font-weight: 650; margin-top: 3pt; display: flex; flex-wrap: wrap; align-items: center; gap: 6pt; }
.rp-badge { display: inline-block; border: 1px solid #CBD5E1; border-radius: 999px; padding: 0 7pt; font-size: 9pt; font-weight: 700; }
.rp-badge--rose { color: #BE123C; border-color: #FDA4AF; background: #FFF1F2; }
.rp-badge--amber { color: #B45309; border-color: #FCD34D; background: #FFFBEB; }
.rp-badge--emerald { color: #047857; border-color: #6EE7B7; background: #ECFDF5; }
.rp-meta { display: grid; grid-template-columns: auto auto; gap: 1pt 8pt; font-size: 9pt; margin: 0; min-width: 44mm; }
.rp-meta dt { color: #64748B; } .rp-meta dd { margin: 0; font-weight: 650; color: #0F172A; }
.rp-doc p.rp-notice { font-size: 8.5pt; color: #64748B; margin: 4pt 0 0; }
.rp-sec { margin-top: 10pt; break-inside: avoid; page-break-inside: avoid; }
.rp-h { font-size: 11.5pt; font-weight: 750; color: #0F172A; border-bottom: 1px solid #CBD5E1; padding: 0 0 2pt; margin: 0 0 5pt;
  break-after: avoid; page-break-after: avoid; }
.rp-doc p.rp-lead { font-size: 10.5pt; font-weight: 600; color: #0F172A; }
.rp-kpis { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); border: 1px solid #CBD5E1; border-radius: 5pt; }
.rp-kpi { padding: 5pt 7pt; border-left: 1px solid #E2E8F0; }
.rp-kpi:first-child { border-left: none; }
.rp-kpi span { display: block; font-size: 8.5pt; color: #64748B; }
.rp-kpi b { display: block; font-size: 12.5pt; font-weight: 750; color: #0F172A; font-variant-numeric: tabular-nums; }
.rp-kpi small { display: block; font-size: 8.5pt; color: #475569; }
.rp-rows { display: grid; grid-template-columns: 24mm minmax(0, 1fr); gap: 2pt 8pt; margin: 0; }
.rp-rows dt { color: #64748B; font-size: 9.5pt; } .rp-rows dd { margin: 0; overflow-wrap: anywhere; }
.rp-doc p.rp-small { font-size: 8.5pt; color: #64748B; margin: 3pt 0 0; }
.rp-doc p.rp-warn { color: #92400E; }
.rp-list { margin: 2pt 0 0 14pt; padding: 0; } .rp-list li { margin: 1pt 0; font-size: 9.5pt; }
.rp-table { width: 100%; border-collapse: collapse; font-size: 9pt; table-layout: fixed; }
.rp-table th { text-align: left; color: #475569; font-weight: 650; border-bottom: 1px solid #94A3B8; padding: 3pt 4pt; }
.rp-table td { border-bottom: 1px solid #E2E8F0; padding: 3pt 4pt; vertical-align: top; overflow-wrap: anywhere; }
.rp-table tr { break-inside: avoid; page-break-inside: avoid; }
.rp-table .num { text-align: right; font-variant-numeric: tabular-nums; }
.rp-ok { color: #047857; font-weight: 650; } .rp-no { color: #64748B; font-weight: 650; } .rp-up { color: #BE123C; font-weight: 700; }
.rp-appendix { margin-top: 16pt; border-top: 2px dashed #CBD5E1; padding-top: 10pt; }
.rp-doc p.rp-appendix-title { font-size: 14pt; font-weight: 800; color: #0F172A; margin: 0 0 4pt; }
.rp-doc a { color: #0369A1; }
@media print {
  body { padding: 0 !important; max-width: none !important; }
  .rp-doc { max-width: none; }
  .rp-appendix { break-before: page; page-break-before: always; border-top: none; margin-top: 0; padding-top: 0; }
  .rp-doc a { color: inherit; text-decoration: none; }
}
"""
_RP_TONE = {"우선점검": "rose", "추가확인": "amber", "관찰": "emerald"}
_VERDICT_CLS = {"상위": "rp-up", "진입": "rp-ok", "충족": "rp-ok", "통과": "rp-ok", "미달": "rp-no", "미확인": "rp-no"}
_SOURCE_NAME = {"Q1": "진단 Q1", "Q2": "진단 Q2", "Q3": "진단 Q3", "WORK24": "채용공고", "SNAPSHOT": "등록 확인질문"}


def _rp_rows(rows: list[tuple[str, str]]) -> str:
    return '<dl class="rp-rows">' + "".join(f"<dt>{_e(k)}</dt><dd>{_e(v)}</dd>" for k, v in rows if v) + "</dl>"


def _rp_list(items: list[str]) -> str:
    items = [x for x in items if x and str(x).strip()]  # 빈 글머리표를 만들지 않는다
    return f'<ul class="rp-list">{"".join(f"<li>{_e(x)}</li>" for x in items)}</ul>' if items else ""


def _rp_count(v, unit="건") -> str:
    return "미확인" if v is None else f"{int(v):,}{unit}"


def render_report_summary_html(vm: dict) -> str:
    """1페이지 요약본 — 판정 → 핵심지표 → 현재 상태·다음 행동 → 우선 확인 → 지원 검토 → 채용 보조신호 → 자료 기준."""
    tone = _RP_TONE.get(vm["stage"], "")
    head = (
        '<div class="rp-head"><div>'
        '<h1 class="rp-title">담당자 인계용 진단 요약</h1>'
        f'<div class="rp-sub">{_e(vm["industry"])} · {_e(vm["quarter"])}'
        f'<span class="rp-badge rp-badge--{tone}">{_e(vm["stage_display"])}</span></div></div>'
        '<dl class="rp-meta">'
        f'<dt>점검 상태</dt><dd>{_e(vm["case_status"])}</dd><dt>담당자</dt><dd>{_e(vm["assignee"])}</dd>'
        f'<dt>현장확인</dt><dd>{_e(vm["field_done"])}/{_e(vm["field_total"])}건</dd></dl></div>'
        f'<p class="rp-notice">{_e(REPORT_NOTICE_TEXT)}</p>'
    )
    verdict = (f'<div class="rp-sec"><h2 class="rp-h">핵심 판정</h2><p class="rp-lead">{_e(vm["reason"])}</p>'
               f'<p class="rp-small">{_e(vm["production"])}</p></div>')
    kpis = "".join(f'<div class="rp-kpi"><span>{_e(k)}</span><b>{_e(v)}</b><small>{_e(s)}</small></div>'
                   for k, v, s in vm["kpis"])
    kpi_sec = f'<div class="rp-sec"><h2 class="rp-h">핵심 지표</h2><div class="rp-kpis">{kpis}</div></div>'
    has_fn = bool(vm["candidates"] or vm["selected"])
    support_state = ((f"후보 기능 {len(vm['candidates'])}개"
                      + (f" · 담당자 선택 {len(vm['selected'])}개" if vm["selected"] else "")
                      + f" · 담당기관 확인 {len(vm['confirmed'])}개") if has_fn else "검토 후보 없음")
    state = _rp_rows([("현장확인", vm["field_text"]), ("지원 검토", support_state), ("결정", vm["decision"]),
                      ("인계", vm["referral_text"]), vm["review"], ("다음 행동", vm["next_action"])])
    state_sec = f'<div class="rp-sec"><h2 class="rp-h">현재 확인상태와 다음 행동</h2>{state}</div>'
    if vm["priority"]:
        prio = (f'<p class="rp-lead">{_e(vm["priority"])}</p>'
                + (f'<p class="rp-small">추가 확인사항 {vm["more_questions"]}건은 상세본에서 확인할 수 있습니다.</p>'
                   if vm["more_questions"] else ""))
    else:
        prio = f'<p>우선 확인사항 미지정 · 상세 확인문항 {vm["question_total"]}건</p>'
    prio_sec = f'<div class="rp-sec"><h2 class="rp-h">우선 확인사항</h2>{prio}</div>'
    sup_rows = [("검토 후보", " · ".join(vm["candidates"]))]
    if vm["selected"]:
        sup_rows.append(("담당자 선택", " · ".join(vm["selected"])))
    sup_rows += [("기관 확인", " · ".join(vm["confirmed"])), ("확인 필요", " · ".join(vm["need_check"]))]
    sup = _rp_rows(sup_rows) if has_fn else "<p>채용 키워드·확인 신호로 연결된 검토 후보 기능이 없습니다.</p>"
    if not vm["field_done"] and has_fn:
        sup += '<p class="rp-small rp-warn">현장확인 전 검토 후보이며 실제 인계·지원 적격은 확정되지 않았습니다.</p>'
    sup_sec = f'<div class="rp-sec"><h2 class="rp-h">지원 검토</h2>{sup}</div>'
    if vm["jobs_found"]:
        c = vm["jobs_counts"]
        kw = " · ".join(f"{t} {n}건" for t, n in vm["keywords_top"]) or "확인된 키워드 없음"
        jobs = (f'<p>현재 유효 공고 {_rp_count(c["현재 유효"])} · 확인 기업 {_rp_count(c["확인 기업"], "개")}</p>'
                f'<p>주요 확인 키워드 {_e(kw)}</p>'
                f'<p class="rp-small">Work24 {_e(vm["jobs_quarter"])} 공고 기준 보조자료이며 진단 판정에는 사용하지 않았습니다.</p>')
    else:
        jobs = '<p>확보된 채용공고 없음</p><p class="rp-small">채용공고는 진단 판정에 사용하지 않는 보조자료입니다.</p>'
    jobs_sec = f'<div class="rp-sec"><h2 class="rp-h">채용시장 보조신호</h2>{jobs}</div>'
    basis_lines = [" · ".join(vm["basis"]), "생산지표는 가격변동 효과가 포함될 수 있는 명목 생산액입니다.",
                   "통계 신호는 원인이나 지원 적격을 자동 확정하지 않습니다."]
    basis = "".join(f'<p class="rp-small">{_e(x)}</p>' for x in basis_lines if x)
    basis_sec = f'<div class="rp-sec"><h2 class="rp-h">자료 기준</h2>{basis}</div>'
    return head + verdict + kpi_sec + state_sec + prio_sec + sup_sec + jobs_sec + basis_sec


def render_report_appendix_html(vm: dict) -> str:
    """상세본 부록 A~E — 판정근거 · 전체 현장 확인문항 · 지원 검토 상세 · 채용 보조자료 · 자료 한계와 출처(새 페이지에서 시작)."""
    rule = "".join(
        f'<tr><td>{_e(r.get("signal"))}</td><td class="num">{_e(r.get("current"))}</td>'
        f'<td>{_e(" / ".join(x for x in (r.get("entry_threshold"), r.get("upper_threshold")) if x) or "—")}</td>'
        f'<td class="{_VERDICT_CLS.get(r.get("verdict"), "")}">{_e(r.get("verdict"))}</td><td>{_e(r["role"])}</td></tr>'
        for r in vm["rule_rows"])
    a = ('<div class="rp-sec"><h2 class="rp-h">부록 A. 판정근거</h2>'
         '<table class="rp-table"><colgroup><col style="width:34%"><col style="width:14%"><col style="width:18%">'
         '<col style="width:12%"><col style="width:22%"></colgroup>'
         '<thead><tr><th>지표</th><th class="num">관측값</th><th>기준(진입 / 상위)</th><th>결과</th><th>증거 역할</th></tr></thead>'
         f'<tbody>{rule}</tbody></table><p class="rp-small">{_e(vm["rule_summary"])} · '
         'P(명목 생산액 감소)는 고용 진입신호가 아니라 상위 판정의 보강근거입니다.</p></div>')

    with_result = vm["any_results"]
    result_col = '<col style="width:20%">' if with_result else ""
    result_head = "<th>최근 결과</th>" if with_result else ""
    qrows = "".join(
        f'<tr><td class="num">{q["no"]}</td><td>{_e(q["text"])}</td>'
        f'<td>{_e(_SOURCE_NAME.get(q["source"], q["source"]) or "—")}</td>'
        + (f'<td>{_e(q["result"] or "—")}</td>' if with_result else "") + "</tr>"
        for q in vm["question_rows"])
    b = ('<div class="rp-sec"><h2 class="rp-h">부록 B. 현장 확인사항</h2>'
         f'<p class="rp-small">현장확인 입력 {_e(vm["field_text"])}</p>'
         f'<table class="rp-table"><colgroup><col style="width:6%"><col><col style="width:15%">{result_col}</colgroup>'
         f'<thead><tr><th class="num">번호</th><th>확인사항(원문)</th><th>근거·출처</th>{result_head}</tr></thead>'
         f'<tbody>{qrows}</tbody></table></div>')

    frows = "".join(
        f'<tr><td>{_e(r["label"])}</td><td>{_e(r["status"])}</td>'
        f'<td class="num">{"—" if r["cards"] is None else _e(r["cards"])}</td>'
        f'<td>{_e(r["institutions"] or "담당기관 미확정")}</td><td>{_e(r["intake"])}</td><td>{_e(r["referral"])}</td></tr>'
        for r in vm["fn_rows"])
    cards = "".join(
        f'<tr><td>{_e(c.get("title"))}</td><td>{_e(c.get("institution"))}</td><td>{_e(c.get("current_intake_status"))}</td>'
        f'<td>{_e(c.get("verified_at"))}</td><td>{_link(c.get("source_url"), "공식 출처") or "—"}</td></tr>'
        for c in vm["cards"])
    fn_table = ('<table class="rp-table"><thead><tr><th>기능</th><th>상태</th><th class="num">요건 카드</th>'
                f'<th>검증된 담당기관</th><th>접수경로</th><th>인계</th></tr></thead><tbody>{frows}</tbody></table>'
                if frows else "<p>검토 후보·선택 기능 없음</p>")
    card_table = ('<table class="rp-table" style="margin-top:6pt"><thead><tr><th>공식 요건 카드</th><th>기관</th>'
                  f'<th>접수 상태</th><th>확인일</th><th>출처</th></tr></thead><tbody>{cards}</tbody></table>'
                  if cards else '<p class="rp-small">확인된 공식 요건 카드 없음</p>')
    c_sec = ('<div class="rp-sec"><h2 class="rp-h">부록 C. 지원 검토 상세</h2>' + fn_table
             + ('<p class="rp-small">후보는 채용 키워드·확인 신호로 제시된 검토 대상이며 지원 확정이 아닙니다. '
                '요건 카드는 일반 조건 안내이며 개별 적격을 판정하지 않습니다.</p>')
             + card_table + '</div>')

    if vm["jobs_found"]:
        cnt = vm["jobs_counts"]
        d_body = (_rp_rows([("목록", _rp_count(cnt["목록"])), ("현재 유효", _rp_count(cnt["현재 유효"])),
                            ("상세 검증", _rp_count(cnt["상세 검증"])), ("확인 기업", _rp_count(cnt["확인 기업"], "개")),
                            ("기준 분기", f"Work24 {vm['jobs_quarter']} 공고")])
                  + '<p style="margin-top:4pt">' + _e(" · ".join(f"{t} {n}건" for t, n in vm["keywords_all"])) + "</p>")
    else:
        d_body = "<p>확보된 채용공고 없음</p>"
    d = ('<div class="rp-sec"><h2 class="rp-h">부록 D. 채용시장 보조자료</h2>' + d_body
         + '<p class="rp-small">채용공고 자료는 현장 확인을 위한 보조근거이며 진단 판정 입력값이 아닙니다.</p></div>')

    src = "".join(f"<li>{_e(t)} · {_link(u, '원문')}</li>" for t, u in vm["sources"])
    source_block = f'<p style="margin-top:4pt"><b>공식 출처</b></p><ul class="rp-list">{src}</ul>' if src else ""
    e = '<div class="rp-sec"><h2 class="rp-h">부록 E. 자료 한계와 출처</h2>' + _rp_list(vm["limits"]) + source_block + "</div>"
    return f'<div class="rp-appendix"><p class="rp-appendix-title">상세 부록</p>{a}{b}{c_sec}{d}{e}</div>'


def render_report_html(vm: dict, detailed: bool = False) -> str:
    """진단서 본문(요약본 또는 요약본 + 부록). 화면 미리보기와 저장 HTML이 같은 것을 쓴다."""
    return f'<div class="rp-doc">{render_report_summary_html(vm)}{render_report_appendix_html(vm) if detailed else ""}</div>'
