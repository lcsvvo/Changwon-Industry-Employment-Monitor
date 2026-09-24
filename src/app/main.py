"""창원국가산단 산업·고용 전환진단 및 점검연계 시스템 — Phase 0~4.5 화면.

실행: streamlit run src/app/main.py
분석값은 등록된 분석 버전(Snapshot)에서만 읽는다. 이 화면은 어떤 판정도 다시 계산하지 않는다.
"""
from __future__ import annotations

import html
import logging
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# 화면 모듈(app.*): 코드가 바뀐 뒤(예: Streamlit Cloud에 새로 push) 서버가 새 main.py를 다시 실행하면서도 이미 import된
# 옛 모듈을 그대로 쓰면, 새 이름을 찾지 못해 ImportError가 난다. 파일이 바뀐 경우에만 의존 순서대로 다시 읽는다.
UI_MODULES = ("app.view_models", "app.ui", "app.team_copilot")


def _ui_module_mtime(module) -> float | None:
    try:
        return Path(module.__file__).stat().st_mtime
    except (AttributeError, OSError, TypeError):
        return None


def _refresh_ui_modules():
    import importlib
    loaded = [sys.modules.get(name) for name in UI_MODULES]
    if any(m is not None and getattr(m, "_dx_mtime", None) != _ui_module_mtime(m) for m in loaded):
        for m in loaded:
            if m is not None:
                importlib.reload(m)


def _stamp_ui_modules():
    for name in UI_MODULES:
        m = sys.modules.get(name)
        if m is not None:
            m._dx_mtime = _ui_module_mtime(m)


_refresh_ui_modules()

from export import schema as S  # noqa: E402
from export.diff import THRESHOLD_STATUS, record_diff, snapshot_diff  # noqa: E402
from export.documents import registered_document  # noqa: E402
from export.snapshot import (  # noqa: E402
    NATURE_LABEL, list_snapshots, load_snapshot, nature_note, resolve_for_quarter, snapshot_nature,
)
from app import team_copilot, ui  # noqa: E402
from app.view_models import (  # noqa: E402
    COPILOT_ICONS, INTAKE_UI, RELEVANCE_LABELS, SOURCE_CATEGORY_LABEL, TEAM_PROPOSALS, TEAM_STAGE_FILTERS,
    TEAM_STAGE_FLOW, TEAM_SUGGESTIONS, TEAM_SUGGESTIONS_MORE, WORK24_BASIS, chip_label, clarification, comparison_view,
    copilot_suggestions, data_quality_flags, evidence_level, evidence_level_value, field_context, filter_official_cards,
    collect_related_notices, function_card_counts, function_name, function_ui_label, next_quarters, notice_reasons,
    quarter_label, quarter_text, recruitment_observations,
    report_download,
    rule_evidence_rows, session_scope,
    signal_explanation, stage_code, stage_counts, stage_display, structure_answer, supporting_fact_items,
    team_kpis, team_principles, top_questions, with_session_context,
)
_stamp_ui_modules()
from copilot import Copilot  # noqa: E402
from copilot import router as R  # noqa: E402  (읽기 전용: 비교·되묻기 표시에 쓸 업종명만 본다 — 라우팅은 바꾸지 않음)
from copilot.audit import JsonlAuditSink, audit_path_for  # noqa: E402
from copilot.contracts import SOURCE_LABEL as ANSWER_SOURCE_LABEL  # noqa: E402
from policy.decision_support import DecisionSupportService  # noqa: E402
from policy.rag import PolicyRAG, rebuild_policy_index  # noqa: E402
from policy.work24_evidence import register_work24_snapshot  # noqa: E402
from workflow import models as M  # noqa: E402
from workflow import catalog as C  # noqa: E402
from workflow.identity import local_actor, runtime_context  # noqa: E402
from workflow.service import (  # noqa: E402
    ACTION_LABEL, REFERRAL_ACTIONS, REFERRAL_INPUT_LABEL, REFERRAL_OCCURRED, TARGET_LABEL, WorkflowError,
    WorkflowService,
)

st.set_page_config(page_title="창원국가산단 점검연계 시스템", layout="wide", initial_sidebar_state="collapsed")
DASHBOARD_CSS = (Path(__file__).resolve().parent / "styles" / "dashboard.css").read_text(encoding="utf-8")
st.html(f"<style>{DASHBOARD_CSS}</style>")

STAGE_COLOR = {"우선점검": "red", "추가확인": "orange", "관찰": "gray"}
MAIN_PAGES = ("업종 진단", "점검 관리", "정책·지원 연계")
INFO_PAGES = ("방법론·데이터 기준", "변경 기록")  # 설정·정보 popover에서만 연결. 분기 사후검토는 어떤 nav에도 없음(URL/세션으로만 접근)
KST = timezone(timedelta(hours=9))
# 실행 맥락: 인증 모드·시연 범위는 환경으로만 정해진다(화면에서 바꿀 수 없음)
RT = runtime_context()


# ------------------------------------------------------------------ 자원
@st.cache_resource
def service(url: str | None, demo: bool) -> WorkflowService:
    workflow = WorkflowService(M.make_session_factory(url), demo=demo)
    register_work24_snapshot(workflow.Session)
    return workflow


@st.cache_data
def resolved(quarter: str):
    """대상 분기를 볼 분석본(당시 분석본 우선, 없으면 후향 재구성). 캐시된 분석본을 쓴다."""
    snap_ = resolve_for_quarter(quarter)
    return None if snap_ is None else snapshot(snap_.quarter, snap_.version)


def nature_badge(run_quarter: str, target_quarter: str, demo_case: bool = False):
    """분석본 성격 표시. 후향 재구성이면 당시에 저장된 분석본처럼 표기하지 않는다."""
    nat = snapshot_nature(run_quarter, target_quarter)
    st.badge(NATURE_LABEL[nat], color="blue" if nat == "contemporaneous" else "violet")
    st.caption(nature_text(run_quarter, target_quarter)
               + (" · 후향 재구성 데이터 기반 시연" if demo_case and nat == "reconstructed" else ""))


@st.cache_data
def snapshot(quarter: str, version: str):
    return load_snapshot(quarter, version)


def fmt(v, digits=1, suffix=""):
    if v is None:
        return "자료 없음"
    if isinstance(v, bool):
        return "예" if v else "아니오"
    if isinstance(v, int):
        return f"{v:,}{suffix}"
    if isinstance(v, float):
        return f"{v:,.{digits}f}{suffix}"
    return str(v)


def yes(v) -> str:
    return "—" if v is None else ("통과" if v else "미통과")


# 자원(DB)은 nav 처리보다 먼저 만든다 — apply_nav()가 종결 여부 확인을 위해 svc.get_case()를 쓸 수 있어야 한다
try:
    database_url = M.database_url_for_runtime(RT.demo)
except M.DatabaseScopeError as e:
    st.error(str(e))
    st.stop()
svc = service(database_url, RT.demo)


def go(page: str, industry: str | None = None, quarter: str | None = None,
      case_id: int | None = None, view: str | None = None):
    """화면 이동 요청. 다음 실행에서 위젯이 만들어지기 전에 적용된다."""
    st.session_state._nav = (page, industry, quarter, case_id, view)


def apply_nav():
    nav = st.session_state.pop("_nav", None)
    if not nav:
        return
    page, industry, quarter, case_id, view = nav
    st.session_state.page = page
    if industry:
        st.session_state.dx_industry = industry
    if quarter:
        st.session_state.dx_quarter = quarter
    if case_id is not None:
        st.session_state.case_id = case_id
        # '점검 건 선택' selectbox가 이전 선택을 기억하면 index 기본값(case_id)이 무시된다 → 이동 시 위젯 상태를 비운다
        for view_name in ("진행 중", "종결"):
            st.session_state.pop(f"case_pick_{view_name}", None)
        if view is None:
            case = svc.get_case(case_id)
            view = "종결" if case and case["status"] == "종결" else "진행 중"
    if view is not None:
        st.session_state.insp_view = view


def run(action, success: str):
    """업무 행동 실행 + 오류 표시. 성공 알림은 다음 화면 맨 위에 한 번만 표시하고 사라진다."""
    try:
        result = action()
    except WorkflowError as e:
        st.error(str(e))
        return None
    st.session_state._flash = success
    return result


def ts(iso: str | None) -> str:
    """ISO 시각(UTC 저장) → 화면 표시(KST)."""
    if not iso:
        return "—"
    dt = datetime.fromisoformat(iso)
    dt = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(KST).strftime("%Y-%m-%d %H:%M")


# ------------------------------------------------------------------ 상단 헤더(사이드바 대체)
metas = list_snapshots()
if not metas:
    st.error("등록된 분석 버전이 없습니다. `python -m export.snapshot` 으로 기존 분석 산출물을 먼저 등록하세요.")
    st.stop()

QP_PAGES = (*MAIN_PAGES, *INFO_PAGES, "분기 사후검토")
INSP_VIEWS = ("점검 후보", "진행 중", "종결")
if "page" not in st.session_state:
    # 새로고침(새 세션)은 주소의 page·case·view로 이어서 연다 — 방금 개설한 점검 건 화면이 새로고침 후에도 유지된다
    qp = st.query_params
    st.session_state.page = qp.get("page") if qp.get("page") in QP_PAGES else MAIN_PAGES[0]
    if (qp.get("case") or "").isdigit():
        st.session_state.case_id = int(qp["case"])
    if qp.get("view") in INSP_VIEWS:
        st.session_state.insp_view = qp["view"]
apply_nav()

# 화면 이동은 상단 헤더 탭(go → apply_nav)이 st.session_state.page를 바꾼다. 실행 배너는 헤더 상태 표시에 둔다.
labels = [f"{m['quarter']} {m['snapshot_version']}" for m in metas]  # 세션 저장값은 2026Q2 형식 — 표시는 format_func
st.session_state.setdefault("analysis_version", labels[-1])
st.session_state.setdefault("actor", "")
st.session_state.setdefault("copilot_collapsed", False)
meta = metas[labels.index(st.session_state.analysis_version)]
snap = snapshot(meta["quarter"], meta["snapshot_version"])
# 신원 경계: 로컬 프로토타입은 입력한 이름을 'local:<이름>' 신원으로 쓴다(인증 아님)
actor = local_actor(st.session_state.actor)


def ensure_dx_defaults():
    """dx_quarter/dx_industry 세션 기본값 — 없으면 최신 분기·그 분기 최상위 우선점검 업종."""
    latest_quarter = snap.quarters[-1]
    if "dx_quarter" not in st.session_state:
        st.session_state.dx_quarter = latest_quarter
    # dx_quarter는 업종 진단 화면의 분기 selectbox 키이기도 하다 — 그 위젯이 없는 화면(정책·지원 연계 등)에서
    # 실행이 끝나면 Streamlit이 값을 지우므로, 매 실행 다시 대입해 공용 선택 상태로 유지한다.
    st.session_state.dx_quarter = st.session_state.dx_quarter
    if "dx_industry" not in st.session_state:
        latest_recs = snap.by_quarter(latest_quarter)
        priority = sorted([r for r in latest_recs if r["triage"]["stage"] == "우선점검"],
                          key=lambda r: r["triage"]["rank_in_stage"])
        st.session_state.dx_industry = priority[0]["industry"] if priority else snap.industries[0]


with st.container(key="topbar"):
    with st.container(horizontal=True, vertical_alignment="center", gap="small"):
        st.html(ui.brand_html(f"규칙 {meta['rule_version'].split('/')[-1]}"), width="stretch")
        with st.container(key="topactions", horizontal=True, gap="small", width="content",
                          vertical_alignment="center"):
            with st.popover("⚙ 설정·정보", help="담당자 · 분석 버전 · 방법론·변경 기록"):
                st.text_input("담당자 이름", key="actor", help="모든 검토·개설·결정 기록에 남습니다.")
                st.selectbox("분석 버전", labels, key="analysis_version", format_func=quarter_text,
                             help="분석 실행 분기별로 보존된 불변 분석본. 실행 분기 이전 분기는 후향 재구성 값입니다.")
                st.caption("분석 정보")
                st.caption(f"기준분기 {quarter_label(meta['quarter'])} · 분석 버전 {meta['snapshot_version']}")
                st.caption(f"규칙 버전 `{meta['rule_version']}`")
                st.caption(f"분석 실행일 {meta['source_run']['triage_run_at_utc'][:10]}")
                st.caption(f"등록일 {meta['created_at'][:10]}")
                # 개발·운영 상태는 메인 헤더가 아니라 여기서만 보여준다(값은 runtime_context 그대로)
                st.caption("시스템 상태")
                st.caption(f"운영 상태: {'프로토타입' if not RT.authenticated else '운영'}")
                st.caption(f"사용자 인증: {'미연결' if not RT.authenticated else RT.auth_mode}")
                # AI 연결 설정은 copilot 인스턴스가 만들어진 뒤(아래) 이 자리에 채운다
                ai_status_slot = st.container()
                st.divider()
                for info_page in INFO_PAGES:
                    cur = st.session_state.page == info_page
                    st.button(f"{info_page} 보기", key=("navcur-" if cur else "nav-") + info_page, on_click=go,
                             args=(info_page,), width="stretch")
    with st.container(key="topnav", horizontal=True, gap=None):
        for p in MAIN_PAGES:
            cur = st.session_state.page == p
            st.button(p, key=("navcur-" if cur else "nav-") + p, on_click=go, args=(p,))
        st.space("stretch")
        data_cutoff = snap.provenance(snap.quarter).get("data_cutoff")
        # 사용자용 요약만(분석 버전·등록일은 설정·정보 → 분석 정보, 프로토타입·인증 상태는 설정·정보 → 시스템 상태)
        pills = [("ok", f"분석기준 {quarter_label(meta['quarter'])} · 데이터 기준 {data_cutoff}")]
        if RT.demo:  # 시연 기록은 운영지표에서 빠지므로 업무 화면에서도 알린다
            pills.append(("warn", "시연 모드 — 시연 기록(운영지표 제외)"))
        st.html(ui.status_pills_html(pills), width="content")

policy = PolicyRAG(svc.Session)
decision_support = DecisionSupportService(svc.Session, snap, svc)
# Copilot = 기존 backend를 감싸는 계층(등록 진단 → 공식 RAG → 외부 공식 도메인 → 일반 LLM). provider는 환경변수로만 설정.
copilot = Copilot.from_env(decision_support, audit=JsonlAuditSink(audit_path_for(database_url)))
SOURCE_BADGE_COLOR = {"INTERNAL_DIAGNOSTIC": "blue", "INTERNAL_RAG": "green", "EXTERNAL_WEB": "orange",
                      "GENERAL_LLM": "violet", "SYSTEM": "gray"}

# provider 연결 여부(설정값만 읽음 — 실제 호출은 하지 않음). 설정·정보 popover 안 자리(ai_status_slot)를 채운다.
with ai_status_slot:
    st.caption("AI 연결 설정")
    st.caption(f"Gemini 답변 생성: {'설정됨' if copilot.llm.available else '미설정'}")
    st.caption(f"Gemini 검색 grounding: {'설정됨' if copilot.web.available else '미설정'}")
    st.caption(f"기업마당(BIZINFO): "
              f"{'설정됨' if any(getattr(a, 'available', False) for a in copilot.official_apis) else '미설정'}")
    st.caption("설정됨은 키·옵션이 켜져 있다는 뜻이며 실제 호출 성공 여부는 각 답변의 근거 표시·한계에서 확인합니다.")
    st.caption("행정 AI 비서는 답변마다 근거 유형(등록 진단·공식문서·외부 최신정보·일반 AI)을 구분해 표시합니다.")
    # 기존 Copilot 계약: 세션 입력(field_ctx)은 등록 진단 backend에만 쓰이며 외부 provider로 보내지 않는다
    st.caption("현장 메모 등 세션 입력은 외부 AI로 전달하지 않습니다.")


# ------------------------------------------------------------------ 공통 조각
def stage_badge(stage: str, label: str | None = None):
    st.badge(label or stage, color=STAGE_COLOR.get(stage, "gray"))


def nature_text(run_quarter: str, target_quarter: str) -> str:
    """분석본 성격 안내문(export.snapshot 원문)의 표시용 — 분기 표기만 '2026년 2분기'로 바꾼다."""
    return quarter_text(nature_note(run_quarter, target_quarter))


def nature_display(q: str) -> str:
    """분석본 성격의 사용자용 이름. 의미(당시 분석본 / 후향 재구성)는 그대로, 용어만 쉽게 쓴다."""
    return NATURE_LABEL["contemporaneous"] if snapshot_nature(snap.quarter, q) == "contemporaneous" else "과거분기 재계산"


def nature_line(q: str) -> str:
    """분석본 성격 한 줄(진단서·정책 화면 등). 당시 분석본은 기존 표기, 재계산은 적용 분석기준을 함께 쓴다."""
    if snapshot_nature(snap.quarter, q) == "contemporaneous":
        return nature_text(snap.quarter, q)
    return f"과거분기 재계산 결과 · 적용 분석기준 {quarter_label(snap.quarter)} 버전"


def section(title: str, helper: str | None = None, badge: str | None = None):
    """화면 안 소제목(업종 진단·정책 연계·점검 관리 공용) — st.markdown 대신 이걸로 통일한다."""
    st.html(ui.section_head_html(title, helper, badge))


def electre_line(e: dict) -> str:
    return (f"ELECTRE: **{e['electre_stage']}** ({e['electre_stage_label']}) · "
            f"SMAA 가능 단계: **{' | '.join(e['possible_stages_list']) or '—'}** · "
            f"파라미터 민감: **{fmt(e['smaa_parameter_sensitive'])}**")


def open_case_form(rec: dict, key: str):
    stage = rec["triage"]["stage"]
    title = "점검 건 개설" if stage != "관찰" else "수동 점검 건 개설(관찰 단계)"
    with st.form(f"open_{key}"):
        st.markdown(f"**{title}** — {rec['industry']} {quarter_label(rec['quarter'])} · 분석 버전 {quarter_label(snap.quarter)} {snap.version} 기준으로 고정됩니다.")
        reason = st.text_area("개설 사유 (필수)")
        assignee = st.text_input("담당자 (필수)", value=actor.display_name if actor else "")
        st.caption(nature_text(snap.quarter, rec["quarter"])
                   + (" · 시연 모드: 시연 기록으로 개설됩니다(운영지표 제외)." if RT.demo else ""))
        if st.form_submit_button("점검 건 개설", type="primary", disabled=not actor):
            cid = run(lambda: svc.open_case(actor, snap, rec["industry"], rec["quarter"], reason, assignee),
                      f"점검 건을 개설했습니다 — {rec['industry']} {quarter_label(rec['quarter'])}.")
            if cid:
                go("점검 관리", None, None, cid, "진행 중")
                st.rerun()


def reviewer_section(ind: str, q: str, rec: dict, t: dict):
    cand = next(c for c in svc.candidates(snap, q) if c["industry"] == ind)
    if cand["open_case_id"]:
        st.success(f"진행 중 점검 건 #{cand['open_case_id']}")
        st.button("점검 건 열기", key="reviewer_open_case",
                 on_click=go, args=("점검 관리", None, None, cand["open_case_id"], "진행 중"))
    elif not actor:
        st.caption("상단 ⚙ 설정에서 담당자 이름을 입력하면 검토·개설할 수 있습니다.")
    elif t["stage"] == "관찰":
        st.caption("관찰 단계는 점검 후보가 아닙니다. 필요하면 사유를 적고 수동으로 개설할 수 있습니다.")
        open_case_form(rec, f"{ind}_{q}")
    elif cand["review"] is None:
        if st.button(f"{stage_display(t['stage'])} 검토 시작", type="primary", key="reviewer_start"):
            if run(lambda: svc.start_candidate_review(actor, snap, ind, q), "검토를 시작했습니다.") is not None:
                st.rerun()
    elif cand["review"]["status"] == "검토 중":
        open_case_form(rec, f"{ind}_{q}")
        with st.form(f"noneed_{ind}_{q}"):
            note = st.text_input("점검 불필요 사유")
            if st.form_submit_button("점검 건 없이 검토 종료"):
                if run(lambda: svc.conclude_candidate_without_case(actor, cand["review"]["id"], note),
                       "검토를 종료했습니다.") is not None:
                    st.rerun()
    else:
        st.write(f"검토 상태: **{cand['review']['status']}** — {cand['review']['note'] or ''}")


# ------------------------------------------------------------------ 업종 진단
SOURCE_LABEL = {"Q1": "진단 Q1", "Q2": "진단 Q2", "Q3": "진단 Q3", "WORK24": "채용공고", "SNAPSHOT": "등록 확인질문"}


def lazy_expander(label: str, key: str):
    """접혀 있으면 내용을 만들지 않는 expander(Streamlit on_change="rerun" + .open).

    판정·외부근거처럼 화면 계약(테스트)으로 항상 렌더링돼야 하는 내용에는 쓰지 않는다.
    """
    return st.expander(label, key=key, on_change="rerun")


def set_industry(value: str):
    st.session_state.dx_industry = value


def set_quarter(value: str):
    st.session_state.dx_quarter = value


def sync_dx_industry_from_policy():
    """정책·지원 연계의 업종 selectbox → dx_industry(공용 선택 상태)로 되먹임."""
    st.session_state.dx_industry = st.session_state.policy_industry


def sync_dx_quarter_from_policy():
    st.session_state.dx_quarter = st.session_state.policy_quarter


def fn_name(tag: str) -> str:
    """지원 기능 화면 표시명(업무 화면 공통). 변경 기록은 저장된 값 그대로 보여 주므로 쓰지 않는다."""
    return function_name(tag, C.label(tag))


ROLE_TITLE = {
    "VALIDATION": ("교차확인 자료", "CORE 진단과 방향을 견주어 보는 자료입니다. 같은 방향·다른 방향을 보여줄 뿐, 판정의 정답 여부를 가리지 않습니다."),
    "CONTEXT": ("보조 맥락 자료", "진단을 읽을 때 참고하는 배경 자료입니다. 판정 입력이 아니며 교차확인 자료보다 비중이 낮습니다."),
}
EIS_POPULATION_NOTE = ("모집단 차이: KICOX = 창원국가산단 입주기업 / EIS = 창원시 전체 제조업(업종 비교는 창원상의 자료). "
                       "방향 비교만 가능하며, 다른 방향이 곧 CORE 진단 오류를 뜻하지 않습니다.")


def direction(text):
    if not text:
        return "—"
    return str(text).replace("방향 불일치", "다른 방향").replace("방향 일치", "같은 방향")


def count(v):
    return fmt(int(v)) if isinstance(v, float) and v.is_integer() else fmt(v)


def pct(v, digits=1):
    return fmt(v, digits, "%") if isinstance(v, (int, float)) and not isinstance(v, bool) else fmt(v)


def source_lines(src: dict) -> list[str]:
    """source 별 표시 항목(값은 Snapshot 에 옮겨진 기존 산출물 그대로)."""
    v, key = src["values"], src["key"]
    if key == "ppi":
        band = (f"{pct(v['ppi_adjusted_low'])} ~ {pct(v['ppi_adjusted_high'])}"
                if v.get("ppi_adjusted_band_only") in (True, "True") else pct(v["ppi_adjusted_production_yoy"]))
        agree = {True: "같은 방향", False: "다른 방향"}.get(v.get("sign_agreement"), "판단 불가")
        return [f"명목 생산 YoY {pct(v['nominal_production_yoy'])} · PPI 조정 생산 YoY {band}",
                f"명목·PPI 조정 방향: {agree} · 매핑 {v['ppi_mapping_grade']}등급 ({v['ppi_mapping_uncertainty']})"]
    if key == "eis_cci":
        lines = [f"창원시 제조업 피보험자 YoY {pct(v['eis_manufacturing_yoy'])} · 산단 제조업 고용 YoY "
                 f"{pct(v['mfg_emp_yoy'])} → 총량 {direction(v['aggregate_direction'])}"]
        if v.get("insured_yoy") is not None:
            lines.append(f"업종 비교({v['source_category']}): 피보험자 YoY {pct(v['insured_yoy'])} → "
                         f"{direction(v['industry_direction'])} · 매핑 {v['mapping_confidence']}")
        else:
            lines.append("업종 비교: 해당 시점 자료 없음(총량 비교만)")
        return lines
    if key == "customs_trade":
        return [f"수출 YoY {pct(v['trade_export_yoy'])} · 수입 YoY {pct(v['trade_import_yoy'])} · "
                f"HS6 {count(v['trade_n_items'])}개 품목 · 매핑 {v['trade_mapping_grade']}등급"]
    if key == "kepco_business_type":
        return [f"전력사용 YoY {pct(v['power_usage_yoy'])} · 고객수 YoY {pct(v['power_customers_yoy'])}"]
    if key == "ecos_bsi":
        ind = (f"{fmt(v['bsi_industry_business'])} (매핑 {v['bsi_industry_mapping_grade']})"
               if v.get("bsi_industry_business") is not None else "해당 시점 자료 없음")
        return [f"경남 제조업 업황 BSI {fmt(v['bsi_region_business'])} · 전국 동업종 업황 BSI {ind}"]
    if key == "kosis_labor_flow":
        return [f"종사자 YoY {pct(v['mfg_flow_workers_yoy'])} · 입직 YoY {pct(v['mfg_flow_acquisition_yoy'])} · "
                f"이직 YoY {pct(v['mfg_flow_loss_yoy'])} · 빈일자리 {count(v['mfg_flow_job_openings'])}"]
    return []


def external_sources_view(rec: dict, quarter: str):
    st.markdown(f"#### 외부자료 ({quarter_label(quarter)} 기준)")
    sources = rec.get("external_sources")
    if sources is None:
        st.caption("이 분석 버전에는 분기별 외부자료가 포함되어 있지 않습니다. 최신 분석 버전을 선택하세요.")
        return
    st.caption("선택한 분기에 정렬된 자료만 표시합니다. 외부자료는 판정 입력이 아니며 Triage·선택적 재검토 결과를 바꾸지 않습니다.")
    for role in ("VALIDATION", "CONTEXT"):
        title, note = ROLE_TITLE[role]
        group = [s for s in sources if s["role"] == role]
        if not group:
            continue
        with st.container(border=True):
            st.markdown(f"**{title}** · `{role}`")
            st.caption(note)
            for src in group:
                if src["available"]:
                    st.markdown(f"- **{src['label']}** — {quarter_text(src['source_period'])}")
                    for line in source_lines(src):
                        st.markdown(f"    - {line}")
                    if src["key"] == "eis_cci":
                        st.caption(EIS_POPULATION_NOTE)
                    for n in src["scope_notes"]:
                        if src["key"] != "eis_cci":
                            st.caption(n)
                else:
                    st.markdown(f"- **{src['label']}** — {quarter_text(src['unavailable_label'])}")
                    if src.get("quality_only") and src.get("quality"):
                        st.caption("자료 품질·결합 한계")
                        st.json(src["quality"], expanded=False)


def timeline_chips(industry: str, current_quarter: str, rows: list[dict]):
    """분기별 판정 추이 칩. 클릭하면 그 분기로 이동한다(altair 차트 대신 클릭 가능한 chip)."""
    if not rows:
        st.info("표시할 진단 이력이 없습니다.")
        return
    st.html(ui.timeline_style_html([(row["quarter"], stage_code(row["stage"])) for row in rows], current_quarter))
    with st.container(key="timeline", horizontal=True, gap="small"):
        for row in rows:
            qq = row["quarter"]
            # 18개 분기를 한 줄에 — 칩은 짧은 표기(22Q1), 전체 표기(2022년 1분기)는 마우스를 올리면 보인다
            st.button(f"{qq[2:4]}Q{qq[5:]}", key=f"tl-{qq}", on_click=set_quarter, args=(qq,),
                      help=f"{quarter_label(qq)} · {stage_display(row['stage'])}")


def sync_field_store(industry: str, quarter: str, questions: list[dict]):
    """방금 바뀐 체크·입력 위젯 값을 세션 저장소에 먼저 옮긴다.

    진단서 payload·Copilot 맥락은 위젯보다 먼저 만들어지므로, 이 동기화가 없으면 한 번씩 늦은 값을 쓴다.
    """
    scope = session_scope(industry, quarter)
    store = st.session_state.setdefault("field_responses", {}).setdefault(scope, {})
    for item in questions:
        saved = store.setdefault(item["question_id"], {"checked": False, "answer": ""})
        for field, prefix in (("checked", "field_check"), ("answer", "field_answer")):
            key = f"{prefix}::{scope}::{item['question_id']}"
            if key in st.session_state:
                saved[field] = st.session_state[key]
    if f"field_note::{scope}" in st.session_state:
        st.session_state.setdefault("field_notes", {})[scope] = st.session_state[f"field_note::{scope}"]


def field_context_for(industry: str, quarter: str, questions: list[dict]) -> dict:
    scope = session_scope(industry, quarter)
    responses = st.session_state.setdefault("field_responses", {}).setdefault(scope, {})
    note = st.session_state.setdefault("field_notes", {}).get(scope, "")
    return field_context(questions, responses, note)


def field_questions_view(industry: str, quarter: str, questions: list[dict]) -> dict:
    """현장 확인 체크리스트. 체크는 목록에, 확인 내용·메모 입력은 접힌 expander에 둔다."""
    scope = session_scope(industry, quarter)
    store = st.session_state.setdefault("field_responses", {}).setdefault(scope, {})
    notes = st.session_state.setdefault("field_notes", {})
    st.caption("입력은 현재 브라우저 세션에만 유지되며 영구 DB에 저장된 것으로 간주하지 않습니다.")
    if not questions:
        st.caption("등록된 확인질문이 없습니다.")
        return field_context_for(industry, quarter, questions)
    checked_n = 0
    for index, item in enumerate(questions, 1):
        saved = store.setdefault(item["question_id"], {"checked": False, "answer": ""})
        source = SOURCE_LABEL.get(item.get("source"), item.get("source") or "출처 미확인")
        checked = st.checkbox(f"**[질문 {index}]** {item['question']} :gray[· {source}]",
                              value=bool(saved.get("checked")),
                              key=f"field_check::{scope}::{item['question_id']}", help=item.get("reason") or None)
        store[item["question_id"]]["checked"] = checked
        checked_n += int(checked)
    st.caption(f"확인 {checked_n}/{len(questions)} · 질문은 원인 판정이 아니라 현장에서 확인할 가설입니다.")
    # 입력값은 field_responses/field_notes에 보관되므로, 접혀 있는 동안 위젯을 만들지 않아도 유지된다
    box = lazy_expander("확인 내용·세션 메모 입력", "exp_field_answers")
    with box:
        if not box.open:
            return field_context_for(industry, quarter, questions)
        for item in questions:
            saved = store[item["question_id"]]
            answer = st.text_area(f"[{item['question_id']}] 확인 내용", value=saved.get("answer", ""),
                                  key=f"field_answer::{scope}::{item['question_id']}",
                                  placeholder="확인된 사실과 미확인 사항을 구분해 입력하세요.")
            st.caption(f"질문 근거: {item.get('reason', '')}")
            store[item["question_id"]]["answer"] = answer
        notes[scope] = st.text_area("세션 메모", value=notes.get(scope, ""), key=f"field_note::{scope}",
                                    placeholder="추가 인터뷰·확인 계획 등을 기록하세요.")
    return field_context_for(industry, quarter, questions)


def set_copilot(collapsed: bool):
    st.session_state.copilot_collapsed = collapsed


def copilot_panel(render):
    """Copilot 패널 — 접힘(좁은 레일) / 펼침(카드) 두 모양을 감싼다."""
    if st.session_state.copilot_collapsed:
        with st.container(key="copilotrail", width=64):
            st.button("‹ AI", key="copilot_expand", help="행정 AI 비서 펼치기", on_click=set_copilot, args=(False,))
    else:
        with st.container(key="copilot", width=320):  # 왼쪽 패널과 같은 너비
            render()


def copilot_view(industry: str, quarter: str, field_ctx: dict, stage: str | None, industries: list[str],
                 context_title: str, context_tags: list[str], team: bool = False):
    """team=True: 정책·지원 연계의 '공모전 팀 제안' 탭 — 추천 질문과, 팀 제안 질문의 답변 근거만 바뀐다(대화 기록은 공유)."""
    scope = session_scope(industry, quarter)
    histories = st.session_state.setdefault("copilot_histories", {})
    history = histories.setdefault(scope, [])
    # 패널 = 고정 높이 세로 3단: 머리(제목·맥락·추천 질문) / 대화(남는 높이 전부, 이것만 스크롤) / 질문 입력(맨 아래 고정)
    with st.container(horizontal=True, vertical_alignment="center"):
        st.html('<div class="dx-copilot-title"><span class="dx-dot"></span>행정 AI 비서</div>')
        if st.button("↻", key=f"chatreset::{scope}", help="이 업종·분기 대화 초기화"):
            history.clear()
            st.rerun()
        st.button("»", key="copilot_collapse", help="AI 비서 접기", on_click=set_copilot, args=(True,))
    selected, comparison_industry = None, None
    with st.container(key="copilothead"):
        st.html(ui.context_tags_html(context_title, context_tags))
        other = "(선택 안 함)"
        if not team:  # 팀 제안은 전 업종 공통 — 업종 비교는 두지 않는다
            other_options = ["(선택 안 함)"] + [i for i in industries if i != industry]
            other = st.selectbox("비교 업종(선택)", other_options, key=f"cmp::{scope}")
        primary, more = (TEAM_SUGGESTIONS, TEAM_SUGGESTIONS_MORE) if team else copilot_suggestions(stage)
        with st.container(key="chips", horizontal=True, gap="small"):
            for index, (icon, question) in enumerate(zip(COPILOT_ICONS, primary)):
                # 버튼에는 아이콘 + 짧은 표시명, 마우스를 올리면 원문. 보내는 질문은 원문 그대로
                if st.button(f"{icon} {chip_label(question)}", key=f"chip-{index}::{scope}", help=question):
                    selected = question
            if other != "(선택 안 함)" and st.button(f"{other}와 비교", key=f"chip-cmp::{scope}",
                                                   help=f"{industry}와 {other} 비교"):
                selected, comparison_industry = f"{industry}와 {other} 비교", other
        with st.expander("질문 더보기"):
            with st.container(key="chipsmore", horizontal=True, gap="small"):
                for offset, question in enumerate(more, start=len(primary)):
                    if st.button(chip_label(question), key=f"chip-{offset}::{scope}", help=question):
                        selected = question
    # 'AI 비서 안내'(근거 유형 표시·세션 입력 비전송)는 설정·정보 → AI 연결 설정으로 옮겼다 — 대화 영역을 넓게 쓰기 위해
    if history:  # 대화가 생겼을 때만 대화 영역을 만든다(높이는 CSS가 패널 남은 높이로 맞춘다)
        with st.container(key="chatlog", height=420):
            last = len(history) - 1
            for pos, message in enumerate(history):
                with st.chat_message(message["role"]):
                    if message["role"] == "assistant":
                        action = assistant_message_view(message, scope, pos == last)
                        selected = action or selected
                    else:
                        st.write(message["content"])
    else:  # 빈 상자 없이 안내 한 줄 → 바로 입력창
        st.caption("질문을 입력하거나 추천 질문을 눌러 보세요.")
    typed = st.chat_input(f"{industry} · {quarter_label(quarter)}에 대해 질문하세요.", key=f"chat::{scope}")
    prompt = selected or typed
    if prompt:
        decision = R.route(prompt, list(snap.industries), list(snap.quarters))
        if team and team_copilot.applies(prompt, decision):
            # 팀 제안 탭: 팀 제안 정본만 근거로 답한다(업종·세션 입력은 보내지 않음). 그 밖의 질문은 기존 Copilot 그대로.
            result = team_copilot.answer(prompt, copilot.llm, decision)
        else:
            # 세션 입력(field_ctx)은 등록 진단 backend에만 쓰이며 외부 provider로 보내지 않는다(Copilot 계약)
            result = copilot.ask(prompt, quarter, industry, comparison_industry=comparison_industry,
                                 field_context=field_ctx)
        entry = {"role": "assistant", "content": result["answer"], "caveats": result.get("caveats", []),
                 "source_type": result["source_type"], "citations": result.get("citations", []),
                 "route": result["route"], "intent": result["intent"], "meta": result.get("meta") or {},
                 "composer": result.get("composer"), "answer_type": result.get("answer_type"),
                 "llm_provider": getattr(copilot.llm, "name", None) if result.get("composer") == "LLM" else None}
        # 표시용 보조 정보(라우팅·답변 내용은 그대로): 비교 대상 업종, '지원 범위 밖' 답변의 되묻기
        mentioned = decision.industries
        if result["intent"] == "COMPARE":
            pair = list(mentioned[:2]) if len(mentioned) >= 2 else [industry, comparison_industry]
            if all(pair):
                entry["compare"] = pair
                entry["compare_quarter"] = (result.get("target") or {}).get("quarter") or quarter
        if result.get("answer_type") == "UNSUPPORTED":
            entry["clarify"] = clarification(prompt, industry, stage, tuple(mentioned))
        history.extend([{"role": "user", "content": prompt}, entry])
        st.rerun()


def assistant_message_view(message: dict, scope: str, is_last: bool) -> str | None:
    """답변 한 건 표시 — 근거 badge·provider 표시·본문(결론→근거→다음 확인)·출처·짧은 주의. 되묻기 바로가기를 누르면 그 질문을 돌려준다."""
    if message.get("answer_type") == "TEAM_PROPOSAL":
        st.badge("공모전 팀 제안 · 공식 정책 아님", color="violet")
    elif message.get("source_type"):
        st.badge(ANSWER_SOURCE_LABEL.get(message["source_type"], message["source_type"]),
                 color=SOURCE_BADGE_COLOR.get(message["source_type"], "gray"))
    used = provider_usage_marks(message)
    if used:
        st.caption(" ".join(used))
    biz = (message.get("meta") or {}).get("bizinfo")
    if biz and biz.get("status") != "UNAVAILABLE":
        st.caption("모집 중 공고(출처 · 기업마당) · 지원대상·신청자격은 공고문과 담당기관 확인 필요")
    clarify = message.get("clarify")
    view = None
    if message.get("compare"):
        a, b = message["compare"]
        rec_a, rec_b = snap.get(a, message["compare_quarter"]), snap.get(b, message["compare_quarter"])
        if rec_a and rec_b:
            view = comparison_view(a, rec_a, b, rec_b, {r["rule_name"]: r for r in snap.reference["triage_rules"]})
    if clarify:
        st.markdown(quarter_text(clarify["text"]))
    elif view:
        st.html(ui.comparison_html(view))
    else:
        st.html(ui.answer_html(structure_answer(quarter_text(message["content"]))))  # 답변 원문은 그대로, 표시만 분기 표기 통일
    for cite in message.get("citations") or []:
        detail = " · ".join(x for x in (cite.get("institution"), cite.get("locator"),
                                         f"확인 {cite['checked_at']}" if cite.get("checked_at") else None) if x)
        st.caption(f"근거: [{cite['title']}]({cite['url']})" + (f" · {detail}" if detail else ""))
    if (message.get("meta") or {}).get("search_entry_point"):
        st.html(message["meta"]["search_entry_point"])  # Google 검색 제안(grounding 사용 시 표시)
    # 별도 '근거 한계' 상자는 두지 않는다 — 일반 AI 답변은 badge로 충분, 그 밖에는 짧은 주의 한 줄만
    if message.get("caveats") and message.get("source_type") != "GENERAL_LLM" and not clarify and not view:
        st.caption(f"주의 · {quarter_text(message['caveats'][0])}")
    if clarify and is_last:
        with st.container(key="clarifyacts", horizontal=True, gap="small"):
            for i, (label, prompt) in enumerate(clarify["actions"]):
                if st.button(label, key=f"act-{i}::{scope}"):
                    return prompt
    return None


def provider_usage_marks(message: dict) -> list[str]:
    """이 답변에서 외부 provider를 실제로 사용했는지(답변이 돌려준 composer·meta만으로) 표시한다.

    '설정됨'(설정·정보)과 '이 답변에서 사용됨'을 구분한다. 호출 실패는 답변의 근거 한계(caveat)에 이미 남는다.
    """
    marks = []
    if message.get("composer") == "LLM":
        name = "Gemini" if message.get("llm_provider") == "gemini" else (message.get("llm_provider") or "AI")
        marks.append(f":violet-badge[{name} 문장 생성 사용]")
    biz = (message.get("meta") or {}).get("bizinfo")
    if biz:
        marks.append({"OK": ":green-badge[모집 중 공고 조회 · 출처 기업마당]",
                      "NO_MATCH": ":gray-badge[모집 중 공고 조회 · 접수 중 공고 없음]"}.get(
                          biz.get("status"), ":orange-badge[기업마당 조회 실패]"))
    return marks


def handover_sections(payload: dict, rec: dict | None, rows: list[dict]) -> list[str]:
    """담당자 인계용 진단 요약 6개 섹션(HTML). 화면·저장 HTML 파일에 동일하게 쓴다."""
    ind, q = payload["industry"], payload["quarter"]
    triage = payload.get("triage") or {}
    q1, q2, q3 = payload.get("q1") or {}, payload.get("q2") or {}, payload.get("q3") or {}
    sections = []

    kpi = ui.kpi_cards_html([
        {"label": "업종", "value": ind}, {"label": "기준분기", "value": quarter_label(q)},
        {"label": "현재 판정", "value": stage_display(triage["stage"]) if triage.get("stage") else "자료 없음"},
        {"label": "Q1 상태", "value": " · ".join(x for x in (q1.get("state"), q1.get("state_label")) if x) or "자료 없음"},
        {"label": "Q2 고용증감", "value": fmt(q2.get("employment_change"), suffix="명"),
         "sub": f"YoY {fmt(q2.get('employment_yoy'), 2, '%')}",
         "tone": "rose" if (q2.get("employment_change") or 0) < 0 else "emerald"},
        {"label": "Q3 지속", "value": fmt(q3.get("duration"), suffix="분기")},
    ])
    sections.append(ui.section_html("1. 진단 요약", kpi))

    if rec:
        explanation = signal_explanation(rows, rec["signals"])
        summary_line = f"{explanation['summary']} → 등록 판정 {stage_display(rec['triage']['stage'])}"
    else:
        explanation, summary_line = {"items": []}, None
    fallback = rec["triage"]["stage_reason"] if rec else "고용 축 진입신호 없음"
    reason_body = ui.reason_cards_html("", explanation["items"], fallback)
    if summary_line:
        reason_body += f'<div class="dx-footnote">{html.escape(summary_line)}</div>'
    sections.append(ui.section_html("2. 왜 점검 대상인가", reason_body))

    jobs = payload.get("recruitment_snapshot") or {}
    detail = evidence_level(jobs, "DETAIL_VERIFIED")
    n = evidence_level_value(detail) if detail else "상세 미확인"
    company = evidence_level_value({"count": (detail or {}).get("company_count")}) if detail else "상세 미확인"
    kw_payload = payload.get("recruitment_keywords") or {}
    kw = [(k["term"], k["count"]) for k in (kw_payload.get("keywords") or [])[:6]]
    kw_basis = f"주요 키워드 · 목록 {fmt(kw_payload.get('posting_count'))}건의 {WORK24_BASIS['KEYWORD']}"
    jobs_html = (f'<div class="dx-report-meta">상세 검증 {n} · 기업 {company}</div>'
                + ui.chip_row_html(kw)
                + f'<div class="dx-footnote">{html.escape(kw_basis)}</div>'
                + '<div class="dx-tag-line">현재 채용시장 참고자료 · 선택 분기의 진단 판정 입력 아님</div>')
    sections.append(ui.section_html("3. 채용시장 보조신호", jobs_html))

    questions = payload.get("field_checks", {}).get("questions", [])
    q_items = [(item["question"], SOURCE_LABEL.get(item.get("source"), item.get("source") or "출처 미확인"))
              for item in top_questions(questions, 3)]
    checks = payload.get("field_checks", {}).get("session_context", {})
    answered = [f"{row['question']} — {row.get('answer') or '확인 표시만 입력'}"
               for row in checks.get("responses", []) if row.get("checked") or row.get("answer")]
    field_html = (ui.question_list_html("현장 확인 질문", q_items)
                 + ui.bullet_list_html(answered, "입력된 현장 확인 내용 없음"))
    sections.append(ui.section_html("4. 현장 확인", field_html))

    first_owner = rec["triage"].get("first_owner") if rec else None
    support_html = ui.support_summary_html(first_owner, payload.get("support_functions") or [],
                                           payload.get("requirement_cards") or [], label_of=fn_name)
    sections.append(ui.section_html("5. 지원 검토", support_html))

    limits = ["통계 신호는 원인을 자동 판정하지 않습니다(현장 확인 필요).",
              "지원 적격·선정 여부를 자동 판정하지 않습니다(담당기관 확인 필요).",
              nature_line(q), f"자료 기준 {payload.get('basis_date')}"]
    sections.append(ui.section_html("6. 한계", ui.bullet_list_html(limits)))
    return sections


@st.dialog("담당자 인계용 진단 요약", width="large")
def report_dialog(payload: dict, rec: dict | None):
    ind, q = payload["industry"], payload["quarter"]
    body = report_body(payload, rec)
    st.html(body)
    with st.expander("데이터 한계·출처 기준"):
        for caveat in payload.get("caveat") or []:
            st.caption(f"- {quarter_text(caveat)}")
        st.json({"basis_date": payload.get("basis_date"),
                 "snapshot_provenance": payload.get("snapshot_provenance"),
                 "contract_version": payload.get("contract_version")}, expanded=False)
    with st.container(horizontal=True, gap="small"):
        st.download_button("HTML 저장 (인쇄용)", ui.document_html(f"{ind} {quarter_label(q)} 진단 요약", body, DASHBOARD_CSS),
                           file_name=f"diagnosis_{ind}_{q}.html", mime="text/html", type="primary")
        st.download_button("JSON 원본", report_download(payload),
                           file_name=f"diagnosis_{ind}_{q}.json", mime="application/json")
    st.caption("HTML 파일을 브라우저에서 열어 인쇄(PDF로 저장 가능)할 수 있습니다. PDF를 직접 생성하지 않습니다.")


def report_body(payload: dict, rec: dict | None) -> str:
    """담당자 인계용 진단 요약 본문(HTML) — 진단서 발급 dialog의 화면 표시와 HTML 저장이 같은 것을 쓴다."""
    rules = {r["rule_name"]: r for r in snap.reference["triage_rules"]}
    rows = rule_evidence_rows(rec, rules) if rec else []
    return "".join(handover_sections(payload, rec, rows))


def report_card(payload: dict, rec: dict):
    """왼쪽 패널 하단 — 진단서 발급 버튼(진단서 기능의 유일한 진입점, HTML 저장·JSON 원본은 발급 dialog 안).
    업종·분기·판정은 바로 위 '선택 업종' 카드와 같아 따로 반복하지 않는다."""
    with st.container(key="reportcard"):
        if st.button("진단서 발급", key="left_report", type="primary", width="stretch",
                     help="담당자 인계용 진단서를 엽니다(HTML 저장·JSON 원본 포함)."):
            report_dialog(payload, rec)


def left_panel(industries: list[str], quarters: list[str], latest_quarter: str,
              ind: str, q: str, rec: dict | None, report_payload: dict | None = None):
    st.markdown("**진단 기준 분기**")
    st.selectbox("분기", quarters, key="dx_quarter", label_visibility="collapsed",
                format_func=lambda qq: f"{quarter_label(qq)} (최신)" if qq == latest_quarter else quarter_label(qq))
    st.html(ui.distribution_pills_html(stage_counts(snap.by_quarter(q))))

    st.markdown(f"**진단 대상 업종 ({len(industries)})**")
    # dot = 선택 분기의 등록 판정(HTML 레퍼런스와 같이 분기를 바꾸면 dot도 바뀐다)
    st.html(ui.industry_style_html(
        [stage_code(((snap.get(industry, q) or {}).get("triage") or {}).get("stage")) for industry in industries],
        industries.index(ind) if ind in industries else None))
    cols = st.columns(2)
    for i, industry in enumerate(industries):
        cols[i % 2].button(industry, key=f"ind-{i}",
                          on_click=set_industry, args=(industry,), width="stretch")

    if rec is not None:
        t = rec["triage"]
        st.html(ui.metric_list_html(
            f"선택 업종 · {ind}",
            [("기준 분기", quarter_label(q)), ("분석본", nature_display(q)), ("다음 검토", quarter_label(t["next_review_quarter"]))],
            badge_html=ui.stage_badge_html(t["stage"], stage_display(t["stage"]))))

    with st.container(key="noticecard"):
        st.caption("본 시스템은 원인을 자동 단정하거나 지원사업을 자동 선정하지 않으며, "
                   "담당자의 확인·판단을 지원합니다.")
    if rec is not None and report_payload is not None:
        report_card(report_payload, rec)  # 이 아래는 비워 둔다(column 배경만 이어짐)


def aux_evidence_view(rec: dict, q: str):
    """I 보조: 기존 '판정 근거·추적' + '미확인·확인 필요' 탭 내용을 분석 담당자용으로 재사용."""
    t = rec["triage"]
    st.markdown(f"**Triage** · {t['stage']} — {t['stage_reason']}")
    st.markdown(f"진입 신호 `{t['entry_trigger']}` · 보강 `{t['reinforcement']}` · 단계 내 순위 {t['rank_in_stage']}")
    st.markdown(f"**규모 gate** · 기준 {t['scale_threshold']}인 · 통과 {fmt(t['scale_ok'])}"
               + (f" · {t['scale_flag']}" if t["scale_flag"] else ""))
    st.markdown(f"**1차 검토 기능** · {t['first_owner']}")
    if rec["explanation_trace"]:
        tr = rec["explanation_trace"]
        st.markdown(f"**확인신호 프로필** · {tr['signal_profile']}")
        st.caption(f"모형 경로: {tr['model_path']} · {tr['routing_disclaimer']}")
    e = rec["electre_smaa"]
    st.markdown("**선택적 재검토 정보 (추가확인 사례에만)**")
    if e["available"]:
        st.markdown(f"Triage: **{e['triage_stage_preserved']}** (변경되지 않음)")
        st.markdown(electre_line(e))
        st.caption(f"{e['boundary_action']} · {e['review_queue_group']} · {e['smaa_note']}")
    else:
        st.caption(e["reason"])

    external_sources_view(rec, q)
    ev = rec["external_evidence"]
    if ev["available"]:
        st.markdown(f"#### 최신분기 외부근거 요약 카드 · 원천 분기 {quarter_label(ev['source_quarter'])}")
        if ev["card"]:
            card = ev["card"]
            for k in ("확인신호프로필", "교차확인", "고용flow", "수출", "경기심리", "전력", "자료품질"):
                if card.get(k):
                    st.markdown(f"- **{k}** · {card[k]}")
        st.json(ev["summary"], expanded=False)

    dq = rec["data_quality"]
    items = []
    if dq["core_missing"]:
        items.append("핵심 자료 누락")
    if dq["production_missing"]:
        items.append("생산자료 미확인")
    if dq["previous_signal_unknown"]:
        items.append("이전 분기 신호 미확인")
    if t["data_quality_minimum_only"]:
        items.append("확인 가능한 신호에 따른 최소판정")
    if dq["review_required"]:
        items.append("원천 검토 필요 표시")
    masked = [f for f, v in dq["fields"].items() if v["masked"]]
    if masked:
        items.append(f"비공개(마스킹) 항목: {', '.join(masked)}")
    missing_src = [s["label"] for s in rec.get("external_sources") or []
                   if not s["available"] and not s.get("quality_only")]
    if missing_src:
        items.append(f"외부자료 해당 시점 자료 없음: {', '.join(missing_src)}")
    if rec["electre_smaa"]["available"] and len(rec["electre_smaa"]["possible_stages_list"]) > 1:
        items.append("파라미터에 따라 선택적 재검토 단계가 달라짐")
    st.markdown("**자료로 확인되지 않은 점**")
    for i in items or ["원천 자료품질 표시 없음"]:
        st.markdown(f"- {i}")
    if snap.reference.get("scope"):
        st.caption(snap.reference["scope"])

    qs = rec["questions"]
    with st.container(border=True):
        st.markdown("**기본 확인질문**")
        st.caption("Triage 판정에 딸린 기존 확인질문")
        st.markdown(f"- {qs['check_question'] or S.NO_CONTEXT_QUESTION}")
    with st.container(border=True):
        st.markdown("**맥락 기반 추가 확인질문**")
        st.caption(f"{quarter_label(q)} 분기 해석층이 만든 질문 · 현장에서 추가로 확인할 내용이며 "
                   "Triage·선택적 재검토 판정을 바꾸지 않습니다 · 외부근거 카드가 아닙니다")
        if qs["context_available"]:
            for x in qs["context_questions"]:
                st.markdown(f"- {x}")
            prov = qs.get("context_provenance")
            if prov:
                with st.expander("질문 출처(해석층 구성요소)"):
                    for col, label in S.CONTEXT_COMPONENTS.items():
                        lines = prov["components"].get(col) or []
                        st.markdown(f"**{label}** · {len(lines)}건")
                        for x in lines:
                            st.caption(f"- {x}")
                    st.caption(f"신호 프로필: {prov['signal_profile']} · 자료품질 표시: {prov['quality_flag_list']}")
        else:
            st.caption(qs["context_missing_label"])
        if qs["handoff_review_functions"]:
            st.caption(f"인계 검토 기능: {qs['handoff_review_functions']}")

    with st.expander("자료 품질 상세 · 분석 담당자용"):
        st.dataframe(pd.DataFrame([{
            "항목": f, "원천": v["source"], "연간보정": fmt(bool(v["is_revised"])),
            "마스킹": fmt(bool(v["masked"])), "원천 무효": fmt(bool(v["invalid_source"])), "비고": v["note"],
        } for f, v in dq["fields"].items()]), hide_index=True, width="stretch")


def recruitment_signal_view(jobs: dict, keywords: list[dict], q: str, latest_quarter: str,
                            keyword_posting_count):
    """채용시장 보조 신호 — 요약(항상 렌더) + 대표 공고 + 전체 상세(lazy)."""
    section("채용시장 보조 신호", helper="현재 채용정보이며 선택 분기의 진단 판정에는 사용하지 않습니다.",
           badge="현재 시점 참고자료")
    kw = keywords[:8] if jobs.get("status") == "FOUND" else []
    observations = recruitment_observations(jobs, kw)
    st.html(ui.recruitment_summary_html(jobs, kw, q == latest_quarter, q, observations, WORK24_BASIS,
                                        keyword_posting_count))
    if jobs.get("status") != "FOUND":
        return

    details = [d for d in jobs.get("detail_records") or [] if d.get("job_relevance_class") == "CORE_INDUSTRIAL"][:3]
    if not details:
        details = (jobs.get("detail_records") or [])[:3]
    st.html(ui.representative_postings_html(details))

    n = len(jobs.get("detail_records") or [])
    if n > 0:
        box = lazy_expander(f"전체 공고 보기 · 상세 검증 {n}건", "exp_jobs_all")
        with box:
            if box.open:
                st.html(ui.recruitment_detail_html(jobs))
                distribution = jobs.get("job_relevance_distribution") or {}
                if distribution:
                    st.caption("직무 관련성 분류(상세 검증 공고만): " + " · ".join(
                        f"{RELEVANCE_LABELS.get(key, key)} {value}건" for key, value in distribution.items())
                        + " · GENERAL_NONCORE는 산업기술·훈련 미스매치의 핵심 지표에서 제외합니다.")

    st.button("데이터 기준·한계 보기 →", key="dx_to_method_jobs", type="tertiary", on_click=go,
             args=("방법론·데이터 기준",))


def field_summary_view(ind: str, q: str, questions: list[dict]):
    """현장에서 우선 확인할 사항(요약, 읽기 전용) — 체크·입력은 점검 관리로 이동."""
    section("현장에서 우선 확인할 사항", helper="진단 결과를 바탕으로 담당자가 현장에서 추가로 확인할 항목입니다.")
    items = [(item["question"], SOURCE_LABEL.get(item.get("source"), item.get("source") or "출처 미확인"))
             for item in top_questions(questions, 3)]
    st.html(ui.question_list_html(None, items))
    st.html(ui.note_html("질문은 원인 판정이 아니라 현장에서 확인할 가설입니다."))
    if len(questions) > 3:
        box = lazy_expander(f"추가 확인사항 보기 · {len(questions) - 3}건", "exp_field_more")
        with box:
            if box.open:
                for i, item in enumerate(questions[3:], 4):
                    st.markdown(f"{i}. {item['question']}")

    def _to_inspection():
        st.session_state.insp_pick = ind
        go("점검 관리", ind, q, None, "점검 후보")
    st.button("점검 관리에서 체크·기록하기 →", key="dx_to_inspection", type="tertiary", on_click=_to_inspection)


def case_status_bar(ind: str, q: str, t: dict):
    """점검 상태 액션 바(한 줄) — reviewer_section은 점검 관리에 있고, 여기는 상태 안내 + 바로가기만 한다."""
    cand = next((c for c in svc.candidates(snap, q) if c["industry"] == ind), None)
    with st.container(key="casebar", horizontal=True, vertical_alignment="center"):
        if cand and cand["open_case_id"]:
            st.markdown(f"현재 점검 상태: 진행 중 점검 건 #{cand['open_case_id']}")
            st.space("stretch")
            st.button("점검 건 열기 →", key="dx_open_case", type="tertiary", on_click=go,
                     args=("점검 관리", None, None, cand["open_case_id"], "진행 중"))
        elif cand and cand["review"]:
            st.markdown(f"현재 점검 상태: {cand['review']['status']}")
            st.space("stretch")
            st.button("점검 관리로 →", key="dx_case_bar", type="tertiary", on_click=go, args=("점검 관리", ind, q))
        elif t["stage"] in ("우선점검", "추가확인"):
            st.markdown("현재 점검 상태: 점검 미개설 · 점검 후보")
            st.space("stretch")

            def _to_inspection_candidate():
                st.session_state.insp_pick = ind
                go("점검 관리", ind, q, None, "점검 후보")
            st.button("점검 시작·관리 →", key="dx_case_bar", type="tertiary", on_click=_to_inspection_candidate)
        else:
            st.markdown("현재 점검 상태: 점검 미개설 · 관찰 단계")
            st.space("stretch")
            st.button("점검 관리로 →", key="dx_case_bar", type="tertiary", on_click=go, args=("점검 관리", ind, q))


def center_card(ind: str, q: str, rec: dict, latest_quarter: str, jobs: dict, field_questions_all: list[dict],
                report_payload: dict):
    t, q1, q2, q3 = rec["triage"], rec["q1"], rec["q2"], rec["q3"]
    cutoff = snap.provenance(q)["data_cutoff"]

    with st.container(key="dxsec-diag"):
        meta_line = f"자료 기준 {cutoff} · 단계 내 {t['rank_in_stage']}순위 · 다음 검토 {quarter_label(t['next_review_quarter'] or '—')}"
        st.html(ui.header_html(q, ind, t["stage"], stage_display(t["stage"]), meta_line))
        # 분석본 성격(당시/후향 재구성)은 항상 텍스트로 드러낸다 — 후향 재구성을 당시 분석본처럼 보이게 하지 않는다
        nat = snapshot_nature(snap.quarter, q)
        if nat == "contemporaneous":
            st.caption(f":blue-badge[{NATURE_LABEL[nat]}] {nature_text(snap.quarter, q)}")
        else:
            st.html(ui.notice_html(
                "과거분기 재계산 결과",
                f"{quarter_label(q)} 당시 저장된 진단 결과가 없어, 현재 분석기준으로 {quarter_label(q)} 데이터를 다시 계산한 결과입니다. "
                "이후 수정·보정된 자료가 반영되었을 수 있어 당시 실제 판정과 동일하다고 볼 수 없습니다.",
                f"적용 분석기준: {quarter_label(snap.quarter)} 버전", tone="violet"))

        kpi_cards = [
            {"label": "Q1 상태 (국면)", "value": " · ".join(x for x in (q1["state"], q1["state_label"]) if x) or "자료 없음",
             "sub": ("생산 미확인" if q1.get("production_yoy") is None
                    else f"생산 {fmt(q1['production_yoy'], 1, '%')}")},
            {"label": "Q2 고용증감 (규모)", "value": fmt(q2["emp_delta"], suffix="명"),
             "tone": "rose" if (q2["emp_delta"] or 0) < 0 else "emerald",
             "sub": f"YoY {fmt(q2['employment_yoy'], 2, '%')}"},
            {"label": "Q3 지속", "value": f"동일 상태 {fmt(q3['state_run_length'])}분기",
             "sub": ("반복 신호 미확인" if q3["repeated_signal"] is None
                    else ("반복 진입신호 있음" if q3["repeated_signal"] else "반복 진입신호 없음"))
                    + (f" · {q3['transition']}" if q3.get("transition") else "")},
            {"label": "산단 고용 비중 (규모)", "value": fmt(q2["employment_share_pct"], 2, "%"),
             "sub": f"고용 {fmt(q2['employment'], suffix='명')}"},
        ]
        st.html(ui.kpi_cards_html(kpi_cards))

        rules = {r["rule_name"]: r for r in snap.reference["triage_rules"]}
        rows = rule_evidence_rows(rec, rules)
        display = stage_display(t["stage"])
        section("진단 판정 근거")  # 상태(우선점검 후보·추가확인·관찰)와 무관하게 같은 명사형 제목
        explanation = signal_explanation(rows, rec["signals"])
        st.html(ui.reason_cards_html("", explanation["items"], t["stage_reason"]))
        summary_line = f"{explanation['summary']} → 등록 판정 {display}"
        st.html(ui.note_html(summary_line))

        box = lazy_expander("세부 판정규칙 보기 · E/R/A/P · 경계값", "exp_rule_detail")
        with box:
            if box.open:
                st.caption(f"등록 판정 문구 · {t['stage_reason']}")
                ladder = rules.get("ladder", {})
                footnote = f"규칙: {ladder.get('definition', '')} · 경계값은 프로젝트 운영규칙이며 법정 기준 또는 최적값이 아닙니다."
                if t.get("scale_flag"):
                    footnote += f" · {t['scale_flag']}"
                if t.get("data_quality_minimum_only"):
                    footnote += " · 확인 가능한 신호에 따른 최소판정"
                st.html(ui.rule_table_html(rows, footnote))
                st.dataframe(pd.DataFrame([{
                    "분기": quarter_label(h["quarter"]), "Q1 상태": h["q1"]["state_label"], "Triage": h["triage"]["stage"],
                    "E": fmt(h["signals"]["E"], 2), "R": fmt(h["signals"]["R"], 2), "A": fmt(h["signals"]["A"], 2),
                    "P": fmt(h["signals"]["P"], 2), "고용 증감(명)": h["q2"]["emp_delta"],
                    "상태 지속(분기)": h["q3"]["state_run_length"],
                } for h in snap.history(ind, q)]), hide_index=True, width="stretch")

    with st.container(key="dxsec-facts"):
        st.html(ui.fact_caveat_html(supporting_fact_items(rec), [
            "이 진단은 산업·고용 변화의 점검 신호입니다.",
            "감소 원인이나 기업별 지원 필요성을 자동으로 확정하지 않습니다.",
            *data_quality_flags(rec)[:2],
        ]))
        st.button("자세한 방법론·데이터 기준 →", key="dx_to_method_caveat", type="tertiary", on_click=go,
                 args=("방법론·데이터 기준",))

    with st.container(key="dxsec-timeline"):
        section(f"{ind} 분기별 판정 추이", helper="분기 칸을 선택하면 해당 시점의 진단 결과를 확인할 수 있습니다.")
        rows_all = decision_support.timeline(ind, snap.quarters[-1])
        idx = next((i for i, r in enumerate(rows_all) if r["quarter"] == q), None)
        trail_rows = [{**r, "stage_display": stage_display(r.get("stage"))}
                      for r in reversed(rows_all[max(0, idx - 3):idx + 1])] if idx is not None else []
        st.html(ui.timeline_trail_html(trail_rows))
        st.html(ui.stage_legend_html())
        timeline_chips(ind, q, rows_all)

    with st.container(key="dxsec-jobs"):
        recruitment_signal_view(jobs, report_payload["recruitment_keywords"]["keywords"], q, latest_quarter,
                                report_payload["recruitment_keywords"]["posting_count"])

    with st.container(key="dxsec-field"):
        field_summary_view(ind, q, field_questions_all)

    with st.container(key="dxsec-support"):
        section("지원체계 검토 경로", helper="현재 진단·채용·현장 확인 신호를 바탕으로 관련 기존 지원 기능을 확인합니다.")
        st.html(ui.support_summary_html(t.get("first_owner"), report_payload.get("support_functions") or [],
                                        report_payload.get("requirement_cards") or [], title=None,
                                        label_of=fn_name))
        st.button("관련 지원제도 자세히 보기 →", key="dx_to_policy", type="tertiary", on_click=go,
                 args=("정책·지원 연계", ind, q))

    case_status_bar(ind, q, t)
    # 판정 경로·규모 gate·선택적 재검토·외부자료·자료 품질(분석 담당자용)은 설정·정보 → 방법론·데이터 기준에서만 본다


@st.cache_data(ttl=300, max_entries=64, show_spinner=False)
def diagnosis_base(snapshot_key: tuple[str, str], quarter: str, industry: str,
                   _service: DecisionSupportService) -> dict:
    """세션 입력 없는 진단 payload. 키: 분석본(분기·버전)·분기·업종.

    앱 계층은 원천 파일을 직접 보지 않으므로(Snapshot·backend만 사용) Work24 layer 갱신은 TTL(5분) 안에
    반영된다. 정책 색인 재구축 시 page_policy가 비운다. 현장 입력은 with_session_context()로 매번 얹는다.
    """
    return _service.report_payload(quarter, industry)


def page_diagnosis():
    ensure_dx_defaults()
    industries, quarters = snap.industries, snap.quarters[::-1]
    latest_quarter = snap.quarters[-1]

    ind, q = st.session_state.dx_industry, st.session_state.dx_quarter
    rec = snap.get(ind, q)
    # 세션과 무관한 backend payload(분석본·업종·분기·Work24 layer 판본 기준)는 캐시하고,
    # 현장 입력(세션)은 매 실행 새로 얹는다 — 체크 직후 진단서·Copilot이 이전 값을 쓰지 않게.
    base = (diagnosis_base((snap.quarter, snap.version), q, ind, decision_support)
            if rec else None)
    jobs = base["recruitment_snapshot"] if base else None
    field_questions_all = base["field_checks"]["questions"] if base else []
    sync_field_store(ind, q, field_questions_all)
    current_field_context = field_context_for(ind, q, field_questions_all) if rec else {"responses": [], "note": None}
    report_payload = (with_session_context(base, current_field_context, datetime.now(timezone.utc).isoformat())
                      if base else None)

    with st.container(key="shell", horizontal=True, gap="small"):
        with st.container(key="leftpanel", width=320):  # 행정 AI 비서(copilot)와 같은 너비
            left_panel(industries, quarters, latest_quarter, ind, q, rec, report_payload)
        with st.container(key="center", width="stretch"):
            if rec is None:
                st.warning("이 분석 버전에 해당 업종·분기 자료가 없습니다.")
            else:
                center_card(ind, q, rec, latest_quarter, jobs, field_questions_all, report_payload)
        if rec is not None:
            copilot_panel(lambda: copilot_view(ind, q, current_field_context, rec["triage"]["stage"], industries,
                                               f"{ind} · {quarter_label(q)}", ["진단", "현장확인", "정책연계"]))


# ------------------------------------------------------------------ 점검 관리
REFERRAL_COLOR = {"작성": "gray", "발송 기록": "blue", "접수 확인": "violet", "처리·회신 기록": "green",
                  "추가확인 필요": "orange", "종결": "gray"}
CASE_STATUS_COLOR = {"진행 중": "orange", "모니터링": "blue", "종결": "gray"}
OCCURRED_CHOICES = ("직접 입력", "지금 막 발생(기록 시각과 같음)", "모름 — 미입력으로 기록")
AUX_LABEL = {"external_sources": "분기별 외부자료", "external_evidence": "최신분기 외부근거 요약",
             "questions": "확인질문", "electre_smaa": "선택적 재검토(ELECTRE/SMAA)",
             "explanation_trace": "판정 설명 추적", "provenance": "원천 참조"}
SCOPE_TARGETS = ("check_result", "case_note", "case_support_need", "referral", "quarterly_review", "case_check_item")


def case_logs(cid: int) -> list[dict]:
    def related(a):
        if a["target_type"] == "inspection_case":
            return a["target_id"] == str(cid)
        body = a["after"] or a["before"] or {}
        return a["target_type"] in SCOPE_TARGETS and body.get("case_id") == cid
    return [a for a in svc.audit_log() if related(a)]


def institution_view(tag: str, fixed):
    f = C.function(tag)
    if not f["referable"]:
        st.caption(f["not_referable_label"])
        return
    cands = svc.institution_candidates(fixed, tag)
    if not cands:
        st.markdown(f"담당 기관: **{C.UNMAPPED_LABEL}**")
        st.caption(f"{C.NO_VERIFIED_MAPPING} — 시스템이 임의로 기관을 제안하지 않습니다.")
        return
    st.markdown("담당 기관 후보")
    for c in cands:
        st.markdown(f"- ○ **{c['institution']}** · {c['unit']} · {c['function']}")
        st.caption(f"기관 기능 확인: 확인됨({c['verified_at']}, 공식 출처 {c['source_url']}) · "
                   + ("실제 접수경로 확인: 확인됨 — " + c["intake_route"] if c["intake_route_verified"]
                      else "실제 접수경로 확인: **미확인** — 발송을 기록할 때 실제로 사용한 연락·접수 경로를 남기세요. "
                           "기관 합의·접수 가능 여부는 확인되지 않았습니다."))


def occurred_input(key: str, label: str):
    """실제 업무 발생 일시 입력. 선택하지 않으면 저장하지 않는다(현재 시각을 몰래 채우지 않음)."""
    choice = st.radio(label, OCCURRED_CHOICES, index=None, horizontal=True, key=f"occ_{key}")
    a, b = st.columns(2)
    day = a.date_input("날짜 (직접 입력 시)", value=None, key=f"occ_d_{key}")
    tm = b.time_input("시각 KST (직접 입력 시)", value=None, key=f"occ_t_{key}", step=600)
    return choice, day, tm


def resolve_occurred(choice, day, tm):
    """(실제 시각, 모름 여부) 또는 WorkflowError."""
    if choice == OCCURRED_CHOICES[0]:
        if day is None or tm is None:
            raise WorkflowError("직접 입력을 골랐다면 날짜와 시각을 모두 입력하세요.")
        return datetime.combine(day, tm, KST).astimezone(timezone.utc), False
    if choice == OCCURRED_CHOICES[1]:
        return datetime.now(timezone.utc), False
    if choice == OCCURRED_CHOICES[2]:
        return None, True
    return None, False


def scope_title(sc: dict) -> str:
    return f"{quarter_label(sc['quarter'])} {sc['review_kind']}"


def referral_view(r: dict, closed: bool, scope_label: str):
    with st.container(border=True):
        st.badge(r["status"], color=REFERRAL_COLOR.get(r["status"], "gray"))
        st.markdown(f"**#{r['id']} {fn_name(r['function_tag'])} → {r['institution']}** · {scope_label}에서 작성")
        for e in svc.referral_events(r["id"]):
            label = ACTION_LABEL.get(e["action"], e["action"])
            when = ""
            if e["has_occurred_time"]:
                when = (" · 실제 발생 일시 미입력" if e["occurred_unknown"] or not e["occurred_at"]
                        else f" · 실제 {ts(e['occurred_at'])} KST")
            contact = ""
            if e["contact"]:
                m, route, ref = e["contact"]
                contact = f" · 담당자가 사용한 방식 {m} · 경로 {route}" + (f" · 외부 참조 {ref}" if ref else "")
            st.markdown(f"- {label}{when} · 기록 {ts(e['recorded_at'])} KST ({e['actor']}){contact}"
                        + (f" — {e['text']}" if e["text"] else ""))
        nxt = M.REFERRAL_TRANSITIONS[r["status"]]
        if closed or not nxt:
            return
        with st.form(f"ref_{r['id']}", clear_on_submit=True):
            text = st.text_input("메모 · 회신 내용 · 사유",
                                 help=" / ".join(f"{s}: {REFERRAL_INPUT_LABEL[REFERRAL_ACTIONS[s][1]]}"
                                                 + (" (필수)" if REFERRAL_ACTIONS[s][2] else "") for s in nxt))
            contact = (None, None, None)
            if "발송 기록" in nxt:
                st.caption("발송 기록 = 담당자가 기관에 실제로 연락·접수한 사실을 기록합니다. 이 시스템은 기관에 아무것도 보내지 않습니다.")
                a, b, c = st.columns(3)
                contact = (a.selectbox("실제 연락·접수 방식", M.CONTACT_METHODS, index=None, key=f"cm_{r['id']}"),
                           b.text_input("실제 사용한 접수·연락 경로", key=f"cr_{r['id']}"),
                           c.text_input("외부 참조번호·비고 (선택)", key=f"ce_{r['id']}"))
            occ = (None, None, None)
            if any(s in REFERRAL_OCCURRED for s in nxt):
                occ = occurred_input(f"ref{r['id']}", "실제 발생 일시 (발송·접수·회신에 필요)")
                st.caption("실제 발생 일시는 기관과 실제로 주고받은 때입니다. 기록 시각은 시스템이 따로 남깁니다.")
            cols = st.columns(len(nxt))
            for col, to in zip(cols, nxt):
                if col.form_submit_button(f"{to}", disabled=not actor):
                    def act(to=to):
                        at, unknown = resolve_occurred(*occ) if to in REFERRAL_OCCURRED else (None, False)
                        cm, cr, ce = contact if to == "발송 기록" else (None, None, None)
                        return svc.advance_referral(actor, r["id"], to, text, at, unknown, cm, cr, ce)
                    if run(act, f"인계 기록 #{r['id']}: '{to}' 기록 완료 (현재 상태 {to})") is not None:
                        st.rerun()


def case_table(cases):
    return pd.DataFrame([{
        "번호": c["id"], "업종": c["industry"], "개설 분기": quarter_label(c["quarter"]), "개설 경로": c["origin"],
        "담당자": c["assignee"], "상태": c["status"], "현재 결정": c["decision"] or "—",
        "다음 검토": quarter_label(c["next_review_quarter"]),
        "개설 분석본": f"{quarter_label(c['snapshot_quarter'])} {c['snapshot_version']} ({NATURE_LABEL[c['snapshot_nature']]})",
        "시연": "시연" if c["is_example"] else "",
    } for c in cases])


def ext_compact(rec: dict) -> list[str]:
    sources = rec.get("external_sources")
    if sources is None:
        return ["이 분석본에는 분기별 외부자료가 없습니다."]
    return [f"{s['label']} · {quarter_text(s['source_period'] if s['available'] else s['unavailable_label'])}"
            + (f" ({s['role']})" if s["available"] else "") for s in sources if not s.get("quality_only")]


def point_view(title: str, rec: dict, snap_label: str):
    t, q1, q2, q3 = rec["triage"], rec["q1"], rec["q2"], rec["q3"]
    st.markdown(f"**{title}**")
    stage_badge(t["stage"], stage_display(t["stage"]))
    st.caption(f"분석본 {snap_label}")
    st.markdown(f"- Q1 상태: {q1['state']} ({q1['state_label']})\n"
                f"- Q2 규모: 고용 {fmt(q2['employment'], suffix='명')} · 증감 {fmt(q2['emp_delta'], suffix='명')} · "
                f"비중 {fmt(q2['employment_share_pct'], 2, '%')} · 순감소 기여율 {fmt(q2['contribution_pct'], 2, '%')}\n"
                f"- Q3 시간: 상태 {fmt(q3['state_run_length'])}분기 지속 · 반복 고용진입신호 {fmt(q3['repeated_signal'])}")
    with st.expander(f"외부자료 ({quarter_label(rec['quarter'])} 기준)"):
        for line in ext_compact(rec):
            st.caption(f"- {line}")


def change_table(prev: dict, cur: dict) -> pd.DataFrame:
    rows = [("Triage 단계", prev["triage"]["stage"], cur["triage"]["stage"]),
            ("Q1 상태", prev["q1"]["state"], cur["q1"]["state"]),
            ("생산 YoY(%)", prev["activity"]["production_yoy"], cur["activity"]["production_yoy"]),
            ("고용(명)", prev["q2"]["employment"], cur["q2"]["employment"]),
            ("고용 증감(명)", prev["q2"]["emp_delta"], cur["q2"]["emp_delta"]),
            ("고용 YoY(%)", prev["q2"]["employment_yoy"], cur["q2"]["employment_yoy"]),
            ("E", prev["signals"]["E"], cur["signals"]["E"]), ("R", prev["signals"]["R"], cur["signals"]["R"]),
            ("A", prev["signals"]["A"], cur["signals"]["A"]), ("P", prev["signals"]["P"], cur["signals"]["P"]),
            ("Q3 상태 지속(분기)", prev["q3"]["state_run_length"], cur["q3"]["state_run_length"])]

    def diff(a, b):
        if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
            return fmt(b - a, 2)
        return "같음" if a == b else "다름"
    return pd.DataFrame([{"항목": n, "이전": fmt(a, 2), "현재": fmt(b, 2), "차이(현재−이전)": diff(a, b)}
                         for n, a, b in rows])


def version_compare_view(old, new, key: tuple[str, str] | None = None):
    d = snapshot_diff(old, new)
    st.markdown(f"**{quarter_text(d['old'])} ↔ {quarter_text(d['new'])}** · **{d['verdict']}**")
    st.caption(f"{d['review_threshold_label']} (자동 재검토 표시 비활성) — 차이를 계산해 보여주기만 하며, "
               "재검토 표시를 자동으로 붙이지 않습니다.")
    with st.container(border=True):
        st.markdown("**분석 판정값 (CORE)** · 생산·고용·Q1~Q3·E/R/A/P·Triage·판정 사유·자료품질")
        if d["core_changes"] or d["core_meta_changed"] or d["records_only_in_old"] or d["records_only_in_new"]:
            st.markdown(f"변경된 업종×분기 {len(d['core_changed_records'])}건")
            if d["core_changes"]:
                st.dataframe(pd.DataFrame([{"업종": c["industry"], "분기": quarter_label(c["quarter"]), "항목": c["label"],
                                            "이전": fmt(c["old"], 3), "이후": fmt(c["new"], 3)}
                                           for c in d["core_changes"]]), hide_index=True, width="stretch")
            if d["core_meta_changed"]:
                st.caption("판정 규칙·설정 변경: " + ", ".join(d["core_meta_changed"]))
        else:
            st.markdown(f"CORE 값 변경 없음 · 공통 업종×분기 {len(set(old.records) & set(new.records))}건 비교")
    with st.container(border=True):
        st.markdown("**부가정보** · 외부자료·확인질문·선택적 재검토 등 (판정 입력 아님)")
        lines = []
        for k, (a, b) in d["aux_meta_changed"].items():
            lines.append(f"Export 계약 {a} → {b}" if k == "export_contract_version" else f"{k}: {a} → {b}")
        if d["aux_sections_added"]:
            lines.append("추가된 영역: " + ", ".join(AUX_LABEL.get(x, x) for x in d["aux_sections_added"]))
        extra = sorted({f.split(".")[0] for f in d["aux_fields_added"]} - set(d["aux_sections_added"]))
        if extra:
            lines.append("항목이 추가된 영역: " + ", ".join(AUX_LABEL.get(x, x) for x in extra))
        roles = {r["key"]: r["role"] for r in new.meta.get("provenance_refs", [])}
        if d["sources_added"]:
            lines.append("추가된 원천: " + ", ".join(roles.get(x, x) for x in d["sources_added"]))
        if d["aux_changed_records"]:
            lines.append(f"부가정보가 달라진 업종×분기 {len(d['aux_changed_records'])}건")
        for line in lines or ["부가정보 변경 없음"]:
            st.markdown(f"- {line}")
    if key is not None:
        rd = record_diff(old.get(*key), new.get(*key))
        st.caption(f"이 점검 건({key[0]} {quarter_label(key[1])}): CORE 변경 {len(rd['core_changes'])}건 · "
                   f"부가정보 변경 {len(rd['aux_changes']) + len(rd.get('aux_fields_added', []))}건")


def result_line(item: dict) -> str:
    r = item["latest"]
    q = item["question_text"] if len(item["question_text"]) <= 70 else item["question_text"][:70] + "…"
    if r is None:
        return f"{item['position'] + 1}. {quarter_label(q)} → 미실시"
    performed = f"실제 확인 {ts(r['performed_at'])} KST" if r["performed_at"] else "실제 확인 일시 미입력"
    more = f" · 이전 기록 {len(item['history']) - 1}건" if len(item["history"]) > 1 else ""
    return (f"{item['position'] + 1}. {quarter_label(q)} → **{r['result_code']}** ({r['method']}) · {performed} · "
            f"기록 {ts(r['recorded_at'])} KST ({r['recorded_by']}){more}" + (f" — {r['note']}" if r["note"] else ""))


def scope_header(sc: dict, case: dict):
    st.markdown(f"#### {scope_title(sc)} · {sc['review_status']}")
    nature_badge(sc["snapshot_quarter"], sc["quarter"], case["is_example"])
    st.caption(f"사용 분석본 {quarter_label(sc['snapshot_quarter'])} {sc['snapshot_version']} · 시작 {ts(sc['started_at'])} KST ({sc['reviewer']})"
               + (f" · 완료 {ts(sc['reviewed_at'])} KST" if sc["reviewed_at"] else ""))
    if sc["review_kind"] == "재점검":
        st.markdown(f"단계 이동: **{quarter_label(sc['previous_quarter'])} {sc['previous_stage']} → {quarter_label(sc['quarter'])} {sc['current_stage']}**")
        st.caption("단계 이동은 분석본 값을 그대로 옮긴 사실입니다. 그 의미는 담당자가 판단합니다.")
    else:
        st.markdown(f"이 시점 Triage: **{sc['current_stage']}**")


def scope_record_view(sc: dict, case: dict):
    """한 점검 시점의 기록(읽기 전용). 이전 시점의 기록은 수정할 수 없다."""
    rec = snapshot(sc["snapshot_quarter"], sc["snapshot_version"]).get(case["industry"], sc["quarter"])
    point_view(f"이 시점 분석값 · {quarter_label(sc['quarter'])}", rec, f"{quarter_label(sc['snapshot_quarter'])} {sc['snapshot_version']}")
    done = [i for i in sc["checks"] if i["latest"]]
    st.markdown(f"**현장확인 결과** {len(done)}/{len(sc['checks'])}건")
    for item in done:
        st.caption("- " + result_line(item))
    st.markdown("**현장 메모** " + ("" if sc["notes"] else "—"))
    for n in sc["notes"]:
        st.caption(f"- {n['note']} ({n['recorded_by']}, {ts(n['recorded_at'])} KST)")
    st.markdown("**지원 필요 기능** " + ("" if sc["support_need_history"] else "—"))
    for n in sc["support_need_history"]:
        st.caption(f"- {', '.join(fn_name(t) for t in n['function_tags']) or '선택 없음'}"
                   + ("" if n["field_checked"] else " (현장확인 전·참고용)")
                   + f" — {n['note'] or ''} ({n['recorded_by']}, {ts(n['recorded_at'])} KST)")
    st.markdown("**결정** " + ("" if sc["decisions"] else "—"))
    for d in sc["decisions"]:
        st.caption(f"- {d['decision']} · {d['rationale']} · 다음 검토 {quarter_label(d['next_review_quarter'] or '—')} "
                   f"({d['decided_by']}, {ts(d['decided_at'])} KST)")
    st.markdown("**이 시점에서 작성한 인계** " + (", ".join(
        f"#{r['id']} {fn_name(r['function_tag'])} → {r['institution']} ({r['status']})" for r in sc["referrals"]) or "—"))


def current_scope_inputs(case: dict, sc: dict, fixed):
    cid = case["id"]
    # ② 현장확인
    done = [i for i in sc["checks"] if i["latest"]]
    st.markdown("##### ② 무엇을 현장에서 확인했는가")
    st.caption(f"이번 시점 현장확인 결과 {len(done)}/{len(sc['checks'])}건 · 문항은 이 시점 분석본에 등록된 확인질문입니다. "
               "결과를 다시 기록하면 이전 기록은 남고 새 기록이 추가됩니다.")
    for item in sc["checks"]:
        with st.container(border=True):
            st.markdown(f"**{item['position'] + 1}.** {item['question_text']}")
            if item["latest"]:
                st.caption(result_line(item).split(" → ", 1)[1])
            with st.form(f"chk_{item['id']}", clear_on_submit=True):
                a, b = st.columns(2)
                method = a.radio("확인 방법", M.CHECK_METHODS, horizontal=True, index=None)
                result = b.radio("결과", M.CHECK_RESULTS, horizontal=True, index=None)
                note = st.text_input("결과 메모")
                occ = occurred_input(f"chk{item['id']}", "실제 확인 일시")
                if st.form_submit_button("결과 기록", disabled=not actor):
                    def act():
                        at, unknown = resolve_occurred(*occ)
                        return svc.record_check_result(actor, cid, item["id"], method, result, note, at, unknown)
                    if run(act, f"{scope_title(sc)} 현장확인 {item['position'] + 1}번 결과를 기록했습니다.") is not None:
                        st.rerun()
    st.markdown("**현장 메모**")
    for n in sc["notes"]:
        st.caption(f"- {n['note']} ({n['recorded_by']}, {ts(n['recorded_at'])} KST)")
    with st.form("note", clear_on_submit=True):
        text = st.text_area("이번 시점 현장 메모")
        if st.form_submit_button("메모 추가", disabled=not actor):
            if run(lambda: svc.record_note(actor, cid, text), f"{scope_title(sc)} 메모를 추가했습니다.") is not None:
                st.rerun()

    # ③ 지원 필요 기능
    st.markdown("##### ③ 어떤 지원 기능이 필요한가")
    st.caption("담당자가 이번 시점 현장확인 결과를 보고 직접 고릅니다. 시스템은 업종 진단·외부자료로 기능을 고르거나 추천하지 않습니다.")
    need = sc["support_needs"]
    chosen = need["function_tags"] if need else []
    if not done:
        st.warning("이번 시점 현장확인 결과가 아직 없습니다. 지금 고르는 지원 필요 기능은 **현장확인 전·참고용**으로 기록되며, "
                   "인계는 현장확인 결과 기록 후에만 가능합니다.")
    if need:
        st.markdown(f"**이번 시점 지원 필요 기능** · {', '.join(fn_name(t) for t in chosen) or '선택 없음'}"
                    + ("" if need["field_checked"] else " · _현장확인 전·참고용 선택_"))
        st.caption(f"선택 이유·메모: {need['note'] or '—'} ({need['recorded_by']}, {ts(need['recorded_at'])} KST)")
    else:
        st.caption("이번 시점에 선택된 지원 필요 기능 없음")
    with st.form("support"):
        cols = st.columns(4)
        picked = [f["tag"] for i, f in enumerate(C.functions())
                  if cols[i % 4].checkbox(fn_name(f["tag"]), value=f["tag"] in chosen, key=f"fn_{sc['id']}_{f['tag']}")]
        note = st.text_area("선택 이유 또는 메모", value=need["note"] if need and need["note"] else "")
        if st.form_submit_button("지원 필요 기능 저장", disabled=not actor):
            if run(lambda: svc.record_support_needs(actor, cid, picked, note),
                   f"{scope_title(sc)} 지원 필요 기능 선택을 기록했습니다.") is not None:
                st.rerun()
    for tag in chosen:
        with st.container(border=True):
            st.markdown(f"**선택 기능 · {fn_name(tag)}**")
            institution_view(tag, fixed)
            cards = svc.requirement_cards(tag)
            if C.function(tag)["referable"] and not cards:
                st.caption(f"지원사업 요건: {C.NO_REQUIREMENT_CARD}")
            for card in cards:
                status = card.get("current_intake_status") or "UNKNOWN"
                badge = {"OPEN": "접수 안내", "CLOSED": "과거 회차", "UNKNOWN": "확인 요청",
                         "NOT_APPLICABLE": "정보 제공"}.get(status, status)
                st.markdown(f"**{card.get('requirement_id')} · {card.get('title') or card['program_name']}** · `{badge}`")
                st.caption(f"일반 요건: {card.get('eligibility') or '확인 필요'} · 적용 범위: {card.get('scope_note') or '—'}")
                st.caption(f"지원 내용: {card.get('support_content') or '—'} · 확인사항: {card.get('requirements') or '—'}")
                st.caption(f"검증일 {card['verified_at']} · 문의 {card.get('contact') or '관할기관 확인'} · "
                           f"주의: {card.get('caveat') or '개별 적격·승인 여부 별도 확인'}")
                st.link_button("공식 출처", card["official_source_url"], key=f"card_src_{sc['id']}_{card['requirement_id']}")
                if status == "OPEN" and card.get("intake_url"):
                    st.link_button("신청 경로", card["intake_url"], key=f"card_apply_{sc['id']}_{card['requirement_id']}")
    with st.expander("목록에 없는 기관 후보 제안 (검증 전에는 인계 대상 아님)"):
        st.caption("제안은 '검토 중(proposed)'으로만 저장됩니다. 관리자 검증 기능은 로그인 도입 후 제공되며, "
                   "검증(verified) 전에는 인계할 곳으로 나타나지 않습니다.")
        with st.form("propose", clear_on_submit=True):
            a, b = st.columns(2)
            name = a.text_input("기관명")
            unit = b.text_input("담당 단위 (선택)")
            desc = st.text_input("기관 기능 설명")
            url = st.text_input("공식 출처 URL")
            tags = st.multiselect("해당 지원 기능", [f["tag"] for f in C.functions() if f["referable"]],
                                  format_func=fn_name, placeholder="지원 기능 선택")
            basis = st.text_input("근거 메모 (선택)")
            if st.form_submit_button("기관 후보 제안", disabled=not actor):
                if run(lambda: svc.propose_institution(actor, name, desc, url, tags, unit, basis),
                       "기관 후보를 제안했습니다(검토 중 — 인계 대상 아님).") is not None:
                    st.rerun()
        for r in svc.institution_registry():
            st.caption(f"- {r['institution']} · {', '.join(fn_name(t) for t in r['function_tags'])} · 상태 "
                       f"{ {'proposed': '검토 중(인계 불가)', 'verified': '검증됨', 'rejected': '반려'}[r['status']] } "
                       f"({r['proposed_by']}, {ts(r['proposed_at'])} KST)")

    # ④ 결정
    st.markdown("##### ④ 결정 · 어디로 인계했는가")
    for d in sc["decisions"]:
        st.markdown(f"- **{d['decision']}** · {d['rationale']} · 다음 검토 {quarter_label(d['next_review_quarter'] or '—')} "
                    f"({d['decided_by']}, {ts(d['decided_at'])} KST)")
    if not sc["decisions"]:
        st.caption("이번 시점에 기록된 결정 없음")
    st.dataframe(pd.DataFrame([{"결정": k, "결정 후 점검 건 상태": v["case_status"],
                                "다음 검토 분기": {"required": "필수", "optional": "선택", "none": "없음(종결)"}[v["next_review"]]}
                               for k, v in M.DECISION_RULES.items()]), hide_index=True)
    targets = [(t, c["institution"]) for t in chosen if C.function(t)["referable"]
               for c in svc.institution_candidates(fixed, t)]
    active = [r for r in case["referrals"] if r["status"] != "종결"]
    rec = snapshot(sc["snapshot_quarter"], sc["snapshot_version"]).get(case["industry"], sc["quarter"])
    with st.form("decision", clear_on_submit=True):
        decision = st.radio("결정", M.DECISIONS, horizontal=True, index=None)
        rationale = st.text_area("결정 근거 (필수 · 종결이면 종결 사유)")
        prefill = (case["next_review_quarter"] if (case["next_review_quarter"] or "") > sc["quarter"]
                   else (rec["triage"]["next_review_quarter"] or ""))
        nrq_options = ["", *next_quarters(sc["quarter"])]
        if prefill and prefill not in nrq_options:
            nrq_options.append(prefill)
        nrq = st.selectbox("다음 검토 분기 (계속 점검·추가확인·모니터링 전환은 필수)", nrq_options,
                           index=nrq_options.index(prefill) if prefill in nrq_options else 0,
                           format_func=lambda x: quarter_label(x) if x else "선택 안 함")
        picks = st.multiselect("인계할 곳 (결정이 '인계'일 때만 사용)", targets,
                               format_func=lambda x: f"{fn_name(x[0])} → {x[1]}",
                               placeholder="지원 필요 기능 · 담당 기관 선택",
                               help="이번 시점에 고른 지원 필요 기능 중 검증된 담당 기관이 있는 것만 표시됩니다.")
        if not targets:
            st.caption(f"인계 가능한 곳 없음 — 지원 필요 기능을 고르지 않았거나 모두 {C.UNMAPPED_LABEL}입니다.")
        confirm = st.checkbox("'종결'을 고른 경우: 이 점검 건을 종결합니다(종결 후에는 수정할 수 없음)")
        if active:
            st.caption(f"진행 중인 인계 기록 {len(active)}건이 있어 지금은 종결할 수 없습니다.")
        if st.form_submit_button("결정 기록", disabled=not actor):
            if run(lambda: svc.record_decision(actor, cid, decision, rationale, nrq, picks, fixed, confirm),
                   f"{scope_title(sc)} 결정 '{decision}'을(를) 기록했습니다.") is not None:
                st.rerun()
    if case["decision"] == "인계" and any(d["decision"] == "인계" for d in sc["decisions"]):
        existing = {(r["function_tag"], r["institution"]) for r in active}
        more = [t for t in targets if t not in existing]
        if more:
            with st.form("add_referral"):
                pick = st.selectbox("인계 기록 추가", more, index=None, placeholder="지원 필요 기능 · 담당 기관 선택",
                                    format_func=lambda x: f"{fn_name(x[0])} → {x[1]}")
                if st.form_submit_button("인계 기록 추가", disabled=not actor) and pick:
                    if run(lambda: svc.create_referral(actor, fixed, cid, pick[0], pick[1]),
                           "인계 기록을 작성했습니다.") is not None:
                        st.rerun()


def case_detail_view(cid: int):
    case = svc.get_case(cid)
    if case is None:
        st.warning("선택한 점검 건을 찾을 수 없습니다.")
        return
    fixed = snapshot(case["snapshot_quarter"], case["snapshot_version"])
    rec = fixed.get(case["industry"], case["quarter"])
    closed = case["status"] == "종결"
    cur = case["current_scope"]

    # ① 왜 이 업종을 확인했는가
    st.subheader("① 왜 이 업종을 확인했는가")
    with st.container(border=True):
        st.badge(f"점검 건 상태: {case['status']}", color=CASE_STATUS_COLOR[case["status"]])
        st.markdown(f"### #{case['id']} {case['industry']} · {quarter_label(case['quarter'])} 개설 — {case['status']}"
                    + (" · 시연 기록" if case["is_example"] else ""))
        st.markdown(f"**개설 시 판정 사유** {rec['triage']['stage_reason']}")
        st.markdown(f"**개설 경로** {case['origin']} · **담당자** {case['assignee']} · **개설** {case['opened_by']} {ts(case['opened_at'])} KST")
        st.markdown(f"**개설 사유** {case['opening_reason']}")
        st.caption(f"개설에 사용한 분석본: {quarter_label(case['snapshot_quarter'])} {case['snapshot_version']} (고정)")
        nature_badge(case["snapshot_quarter"], case["quarter"], case["is_example"])
        if closed:
            st.info(f"종결: {case['closed_by']} {ts(case['closed_at'])} KST — 종결 사유: {case['closing_note']}")
        elif case["status"] == "모니터링":
            st.info(f"모니터링 중 — 적극 점검은 멈췄고 다음 검토 분기 {quarter_label(case['next_review_quarter'])} 재점검 계획이 남아 있습니다.")
    newer = [m for m in metas if m["quarter"] == case["snapshot_quarter"]][-1]
    if newer["snapshot_version"] != case["snapshot_version"]:
        with st.expander(f"분석본 보정 비교 — 개설 시 사용 {case['snapshot_version']} ↔ 최신 {newer['snapshot_version']}"):
            version_compare_view(fixed, snapshot(newer["quarter"], newer["snapshot_version"]),
                                 (case["industry"], case["quarter"]))

    # 점검 이력: 이전 시점(종결된 건은 모든 시점)
    past = case["scopes"] if closed else case["scopes"][:-1]
    st.subheader(f"점검 이력 · {len(case['scopes'])}개 시점")
    st.caption("각 시점의 현장확인·메모·지원 필요 기능·결정·인계는 그 시점에 묶여 보존되며 수정할 수 없습니다.")
    for sc in past:
        with st.container(border=True):
            scope_header(sc, case)
            scope_record_view(sc, case)

    if not closed:
        st.subheader(f"현재 점검 시점 · {scope_title(cur)}")
        with st.container(border=True):
            scope_header(cur, case)
            cur_rec = snapshot(cur["snapshot_quarter"], cur["snapshot_version"]).get(case["industry"], cur["quarter"])
            if cur["review_kind"] == "재점검":
                prev = snapshot(cur["previous_snapshot_quarter"], cur["previous_snapshot_version"]).get(
                    case["industry"], cur["previous_quarter"])
                left, right = st.columns(2)
                with left, st.container(border=True):
                    point_view(f"직전 점검 · {quarter_label(cur['previous_quarter'])}", prev,
                               f"{quarter_label(cur['previous_snapshot_quarter'])} {cur['previous_snapshot_version']}")
                with right, st.container(border=True):
                    point_view(f"이번 시점 · {quarter_label(cur['quarter'])}", cur_rec, f"{quarter_label(cur['snapshot_quarter'])} {cur['snapshot_version']}")
                st.markdown("**직전 시점 대비 변화** (값의 차이만 표시)")
                st.dataframe(change_table(prev, cur_rec), hide_index=True, width="stretch")
            else:
                point_view(f"이 시점 분석값 · {quarter_label(cur['quarter'])}", cur_rec, f"{quarter_label(cur['snapshot_quarter'])} {cur['snapshot_version']}")
        current_scope_inputs(case, cur, fixed)

    # ⑤ 인계 기록
    st.subheader("⑤ 인계 기록 · 회신 상태")
    st.caption("외부 기관 시스템과 연동하지 않습니다. 발송·접수·회신은 담당자가 실제로 한 일을 기록하는 것입니다.")
    if not case["referrals"]:
        st.caption("인계 기록 없음 — '인계'를 결정한 경우에만 만들어집니다.")
    titles = {sc["id"]: scope_title(sc) for sc in case["scopes"]}
    for r in case["referrals"]:
        referral_view(r, closed, titles[r["quarterly_review_id"]])

    # ⑥ 다음 분기 재점검
    if not closed:
        st.subheader("⑥ 다음 분기 재점검")
        st.caption("다음 검토 분기는 담당자가 기록한 결정값을 따릅니다. 시스템은 단계 변화를 보고 자동으로 종결하거나 순서를 바꾸지 않습니다.")
        nrq = case["next_review_quarter"]
        target = resolved(nrq) if nrq else None
        if not nrq:
            st.caption("다음 검토 분기가 기록되지 않았습니다.")
        elif target is None or target.get(case["industry"], nrq) is None:
            st.caption(f"{quarter_label(nrq)} 분석 자료가 아직 없습니다 — 자료가 등록되면 재점검 예정 목록에 나타납니다.")
        else:
            st.caption(f"{quarter_label(nrq)} 재점검에 쓸 분석본: {quarter_label(target.quarter)} {target.version} · {nature_text(target.quarter, nrq)}")
            if st.button(f"{quarter_label(nrq)} 재점검 시작", disabled=not actor, type="primary"):
                if run(lambda: svc.start_quarterly_review(actor, case["id"], target),
                       f"#{case['id']} {quarter_label(nrq)} 재점검을 시작했습니다.") is not None:
                    st.rerun()

    with st.expander("이 점검 건의 변경 기록"):
        st.dataframe(audit_frame(case_logs(cid)), hide_index=True, width="stretch")


def inspection_left_panel() -> str:
    st.markdown("**점검 기준 분기**")
    quarter = st.selectbox("분기", snap.quarters[::-1], key="queue_quarter", label_visibility="collapsed",
                           format_func=quarter_label)
    st.caption(nature_text(snap.quarter, quarter))

    recs = snap.by_quarter(quarter)
    n_candidates = len([r for r in recs if r["triage"]["stage"] in ("우선점검", "추가확인")])
    cases = svc.list_cases()
    n_open = len([c for c in cases if c["status"] != "종결"])
    n_closed = len([c for c in cases if c["status"] == "종결"])
    n_due = len(svc.due_reviews(resolved))
    st.html(ui.metric_list_html("점검 현황", [
        ("점검 후보", n_candidates), ("진행 중", n_open), ("종결", n_closed), ("재점검 예정", n_due),
    ]))
    with st.container(key="noticecard"):
        st.caption("Triage 결과는 점검 후보입니다. 점검 건은 담당자가 검토 후 직접 개설할 때만 만들어집니다.")
    return quarter


def _observation_block(quarter: str, recs: list[dict]):
    items = sorted([r for r in recs if r["triage"]["stage"] == "관찰"], key=lambda r: r["industry"])
    with st.expander(f"관찰 업종 {len(items)}개"):
        st.caption("정기 모니터링 대상입니다.")
        if not items:
            st.caption("해당 없음")
            return
        st.dataframe(pd.DataFrame([{
            "업종": r["industry"], "Q1 상태": r["q1"]["state_label"],
            "고용 증감(명)": r["q2"]["emp_delta"], "판정 사유": r["triage"]["stage_reason"],
        } for r in items]), hide_index=True, width="stretch")
        pick = st.selectbox("업종 선택", [r["industry"] for r in items], key=f"obs_{quarter}")
        a, b = st.columns(2)
        a.button("진단 열기", key=f"obs_go_{quarter}", on_click=go, args=("업종 진단", pick, quarter))
        if b.button("수동 개설 검토", key=f"obs_pick_{quarter}"):
            st.session_state.insp_pick = pick
            st.rerun()


def _selected_candidate_detail(quarter: str):
    ind = st.session_state.get("insp_pick")
    if not ind or snap.get(ind, quarter) is None:
        return
    rec = snap.get(ind, quarter)
    t = rec["triage"]
    st.markdown(f"#### 선택 후보 · {ind} · {quarter_label(quarter)}")
    with st.container(border=True):
        reviewer_section(ind, quarter, rec, t)
    questions = decision_support.field_questions(quarter, ind)
    sync_field_store(ind, quarter, questions)
    with st.expander("현장 확인 사전 체크 · 현재 세션(저장되지 않음)", expanded=False):
        with st.container(key="fieldcheck"):
            field_questions_view(ind, quarter, questions)


def _start_case_cb(ind: str, quarter: str):
    """점검 시작 = 기존 두 업무(후보 검토 시작 → 점검 건 개설)를 한 번에 잇는다. 새 workflow가 아니다.

    콜백에서 실행하므로 담당자 이름(actor 위젯 값)을 위젯이 다시 그려지기 전에 안전하게 저장할 수 있다.
    """
    name = (st.session_state.get("start_actor") or "").strip()
    reason = (st.session_state.get("start_reason") or "").strip()
    if not name:
        st.session_state._start_error = "담당자 이름을 입력하세요."
        return
    st.session_state.actor = name
    who = local_actor(name)
    existing = next((c for c in svc.candidates(snap, quarter) if c["industry"] == ind), {}).get("open_case_id")
    if existing:  # 이미 진행 중이면 새로 만들지 않고 기존 점검 건으로 이동
        go("점검 관리", None, None, existing, "진행 중")
        st.session_state._start_done = True
        return
    try:
        svc.start_candidate_review(who, snap, ind, quarter)  # 이미 검토 중이면 기존 검토를 그대로 돌려준다
        cid = svc.open_case(who, snap, ind, quarter, reason, name)
    except WorkflowError as e:
        st.session_state._start_error = str(e)
        return
    st.session_state._flash = f"점검 건을 개설했습니다 — {ind} {quarter_label(quarter)}."
    go("점검 관리", None, None, cid, "진행 중")
    st.session_state._start_done = True


@st.dialog("점검 시작")
def start_case_dialog(ind: str, quarter: str):
    t = snap.get(ind, quarter)["triage"]
    display = stage_display(t["stage"])
    st.markdown(f"**{ind} · {quarter_label(quarter)}** · {display}")
    st.caption(f"점검 후보 검토를 시작하고 점검 건을 개설합니다 · 분석 버전 {quarter_label(snap.quarter)} {snap.version} 기준으로 고정")
    st.text_input("담당자 이름 (필수)", value=st.session_state.actor, key="start_actor")
    st.text_area("개설 사유 (필수)", value=f"등록 판정 {display} · {t['stage_reason']}", key="start_reason")
    st.button("점검 건 개설", type="primary", key="start_submit", on_click=_start_case_cb, args=(ind, quarter))
    error = st.session_state.pop("_start_error", None)
    if error:
        st.error(error)
    if st.session_state.pop("_start_done", False):
        st.rerun()  # 앱 전체 재실행 → dialog 닫힘 + 진행 중 화면으로 이동


def inspection_candidates_view(quarter: str):
    rows_by_ind = {c["industry"]: c for c in svc.candidates(snap, quarter)}
    recs = snap.by_quarter(quarter)
    for stage in ("우선점검", "추가확인"):
        items = sorted([r for r in recs if r["triage"]["stage"] == stage], key=lambda r: r["triage"]["rank_in_stage"])
        if not items:  # 0건 묶음은 큰 제목 없이 한 줄로만
            st.caption(f"{stage_display(stage)} 후보 없음")
            continue
        section(f"{stage_display(stage)} · {len(items)}개 업종")
        for r in items:
            ind = r["industry"]
            t, q2, sg = r["triage"], r["q2"], r["signals"]
            c = rows_by_ind.get(ind)
            with st.container(border=True):
                questions = [item["question"] for item in decision_support.field_questions(quarter, ind)[:2]]
                metrics = (f"고용 {fmt(q2['emp_delta'], suffix='명')} | YoY {fmt(q2['employment_yoy'], 2, '%')} | "
                          f"산단 대비 감소규모 {fmt(sg['A'], 2, '%')}")
                if c and c["open_case_id"]:
                    status_note = f"진행 중 점검 건 #{c['open_case_id']}"
                elif c and c["review"]:
                    status_note = f"검토 상태: {c['review']['status']} ({c['review']['reviewer']})"
                else:
                    status_note = None
                st.html(ui.candidate_card_html(ind, stage, stage_display(stage), metrics, questions, status_note))
                with st.container(horizontal=True, vertical_alignment="center"):
                    st.button("진단 보기", key=f"dx_{ind}_{quarter}", on_click=go, args=("업종 진단", ind, quarter))
                    st.space("stretch")
                    if c and c["open_case_id"]:
                        st.button("점검 건 열기", key=f"case_{ind}_{quarter}", type="primary", on_click=go,
                                 args=("점검 관리", None, None, c["open_case_id"], "진행 중"))
                    elif st.button("점검 시작", key=f"pick_{ind}_{quarter}", type="primary"):
                        st.session_state.insp_pick = ind
                        start_case_dialog(ind, quarter)
    _observation_block(quarter, recs)
    _selected_candidate_detail(quarter)


def inspection_cases_view(status_filter: str):
    if status_filter == "진행 중":
        due = svc.due_reviews(resolved)
        st.markdown(f"**재점검 예정 · {len(due)}건**")
        if not due:
            st.caption("재점검 예정 없음")
        for d in due:
            with st.container(border=True):
                a, b = st.columns([4, 1])
                a.markdown(f"**#{d['case_id']} {d['industry']}** · 직전 점검 {quarter_label(d['previous_quarter'])} ({d['previous_stage']}) "
                          f"→ 재점검 분기 **{quarter_label(d['review_quarter'])}** · 현재 결정 {d['decision'] or '—'}"
                          + f" · 분석본 {d['snapshot']} ({NATURE_LABEL[d['snapshot_nature']]})"
                          + (" · 모니터링 중" if d["case_status"] == "모니터링" else "")
                          + (" · _시연 기록_" if d["is_example"] else ""))
                b.button("점검 건 열기", key=f"due_{d['case_id']}", on_click=go,
                        args=("점검 관리", None, None, d["case_id"], "진행 중"))
        st.divider()

    cases = [c for c in svc.list_cases() if (c["status"] != "종결") == (status_filter == "진행 중")]
    if not cases:
        st.info("진행 중인 점검 건이 없습니다. 점검 후보에서 개설하세요." if status_filter == "진행 중"
                else "종결된 점검 건이 없습니다.")
        return
    st.dataframe(case_table(cases), hide_index=True, width="stretch")
    ids = [c["id"] for c in cases]
    by_id = {c["id"]: c for c in cases}
    default = ids.index(st.session_state.get("case_id")) if st.session_state.get("case_id") in ids else 0
    cid = st.selectbox("점검 건 선택", ids, index=default,
                       format_func=lambda i: f"#{i} {by_id[i]['industry']} {quarter_label(by_id[i]['quarter'])}",
                       key=f"case_pick_{status_filter}")
    st.session_state.case_id = cid
    case_detail_view(cid)


def inspection_copilot(quarter: str, view: str):
    cid = st.session_state.get("case_id")
    ind = q = None
    context_title, context_tags = "", ["점검 후보"]
    if view in ("진행 중", "종결") and cid is not None:
        case = svc.get_case(cid)
        if case:
            ind = case["industry"]
            q = (case.get("current_scope") or {}).get("quarter") or case["quarter"]
            context_title, context_tags = f"점검 건 #{cid} · {ind} · {quarter_label(q)}", ["점검 관리"]
    if ind is None:
        pick = st.session_state.get("insp_pick")
        if pick and snap.get(pick, quarter) is not None:
            ind, q = pick, quarter
    if ind is None:
        recs = snap.by_quarter(quarter)
        cand = sorted([r for r in recs if r["triage"]["stage"] in ("우선점검", "추가확인")],
                      key=lambda r: (r["triage"]["stage"] != "우선점검", r["triage"]["rank_in_stage"]))
        if cand:
            ind, q = cand[0]["industry"], quarter
    if ind is None:
        ind, q = st.session_state.dx_industry, st.session_state.dx_quarter
    if not context_title:
        context_title = f"{ind} · {quarter_label(q)}"
    resolved_snap = resolved(q)
    rec = (resolved_snap.get(ind, q) if resolved_snap else None) or snap.get(ind, q)
    stage = (rec or {}).get("triage", {}).get("stage") if rec else None
    questions = decision_support.field_questions(q, ind)
    field_ctx = field_context_for(ind, q, questions)
    copilot_view(ind, q, field_ctx, stage, snap.industries, context_title, context_tags)


def page_inspection():
    ensure_dx_defaults()
    with st.container(key="shell", horizontal=True, gap="small"):
        with st.container(key="leftpanel", width=320):  # 행정 AI 비서(copilot)와 같은 너비
            quarter = inspection_left_panel()
        with st.container(key="center", width="stretch"):
            st.html(ui.page_header_html("점검 관리", "점검 후보 → 검토·개설 → 현장 확인 → 지원 필요 기능 → 결정·인계 → 재점검"))
            st.session_state.setdefault("insp_view", "점검 후보")
            view = st.segmented_control("화면", ["점검 후보", "진행 중", "종결"], key="insp_view",
                                        label_visibility="collapsed")
            if view is None:
                view = "점검 후보"
            if view == "점검 후보":
                inspection_candidates_view(quarter)
            else:
                inspection_cases_view(view)
        copilot_panel(lambda: inspection_copilot(quarter, view))


# ------------------------------------------------------------------ 정책·지원 연계
NOTICE_LIMIT = 5
NOTICE_LOG = logging.getLogger("app.policy_notices")


@st.cache_data(ttl=1800, show_spinner=False)
def related_notices(day: str, industry: str, fn_tags: tuple[str, ...], _api) -> dict:
    """현재 모집 중인 관련 공고(출처: 기업마당). 접수 중(OPEN)·다른 지역 제외는 provider 규칙 그대로.

    선택 업종의 지원 기능별 표현(NOTICE_TERMS)이나 업종명이 공고에 있는 것만 '관련 가능 공고'로 모으고
    rank_notices()로 정렬한다. 지원대상 적합성·신청 가능 여부는 판정하지 않는다.
    """
    try:  # provider가 하루 조회분을 재사용하므로 기능별 검색이 API를 여러 번 부르지 않는다
        items = collect_related_notices(_api, industry, fn_tags, date.fromisoformat(day))
    except Exception as e:  # 외부 API 장애는 화면을 멈추지 않고 로그로만 남긴다(키·URL은 기록하지 않음)
        NOTICE_LOG.warning("related notices unavailable: %s", e if isinstance(e, RuntimeError) else type(e).__name__)
        return {"status": "UNAVAILABLE", "items": [], "checked_at": day}
    return {"status": "OK", "items": items[:NOTICE_LIMIT], "checked_at": day}


def notices_view(industry: str, fn_tags: list[str]) -> None:
    """[3] 현재 모집 중인 관련 공고. 조회가 설정되지 않았거나 관련 공고가 0건이면 섹션을 그리지 않는다(사유는 로그)."""
    api = next((a for a in copilot.official_apis if getattr(a, "available", False)), None)
    if api is None:
        NOTICE_LOG.info("related notices hidden: official notice API not configured")
        return
    with st.spinner("현재 모집 중인 공고를 확인하는 중입니다."):
        notices = related_notices(date.today().isoformat(), industry, tuple(fn_tags), api)
    if not notices["items"]:
        NOTICE_LOG.info("related notices hidden: status=%s, no related open notice", notices["status"])
        return
    with st.container(key="dxsec-policy-biz"):
        section("현재 모집 중인 관련 공고", "선택한 업종·진단 결과와 관련 가능한, 지금 접수 중인 공고입니다.")
        st.html(ui.notice_cards_html(notices["items"], lambda tag: function_ui_label(tag, C.label(tag)), notice_reasons))
        st.caption(f"출처 · 기업마당 공고({notices['checked_at']} 확인) · 공고 표현이 일치한 것만 표시하며 지원대상·신청자격은 "
                   "공고문과 담당기관에서 확인해야 합니다. 더 궁금한 점은 행정 AI 비서에 물어보세요.")


def policy_search_view() -> str | None:
    address = st.text_input("사업장 주소로 관할 확인", placeholder="예: 창원시 성산구 ...")
    if address:
        route = policy.route_jurisdiction(address)
        if route["jurisdiction_status"] == "MATCHED":
            st.info(f"{route['district']} → {route['institution']} · 관할은 사업장 주소 기준이며 사업별 접수부서는 재확인합니다.")
        else:
            st.warning(route["message"])

    a, b = st.columns([2, 1])
    query = a.text_input("근거 검색", placeholder="예: 산업·일자리전환 채용장려금 지원금액은?")
    namespace = b.selectbox("검색 구분", ("공식 정책", "팀 제안"))
    current_only = st.checkbox("현재 신청 가능성이 있는 자료만", value=False,
                               help="종료·정보전용 문서를 제외합니다. UNKNOWN은 재확인 대상으로 남깁니다.")
    if query:
        result = policy.search(query, "team" if namespace == "팀 제안" else "official", current_only=current_only)
        (st.info if result["status"] == "FOUND" else st.warning)(result["message"])
        for hit_index, hit in enumerate(result["hits"]):
            with st.container(border=True):
                locator = f"PDF {hit['page']}쪽" if hit["page"] else (hit["section"] or "본문")
                label = "팀 제안" if hit["source_class"] == "TEAM_PROPOSAL" else "공식 안내"
                st.markdown(f"**{hit['document_id']} · {hit['title']}** · `{label}` · {locator}")
                st.write(hit["excerpt"])
                st.caption(f"접수상태 {hit['current_intake_status']} · 검증일 {hit['verified_at']} · "
                           f"주의: {hit['caveat'] or '개별 적용 여부 재확인'}")
                st.link_button("원문 출처", hit["source_url"],
                               key=f"rag_{hit_index}_{hit['document_id']}_{hit['page']}_{hit['score']}")

    with svc.Session() as s:
        chunk_count = s.query(M.SourceEvidence).count()
        cards = s.query(M.RequirementCard).order_by(M.RequirementCard.requirement_id).all()
    with st.expander(f"요건 카드 {len(cards)}건"):
        for card in cards:
            st.markdown(f"- **{card.requirement_id}** {card.title or card.program_name} · "
                        f"{card.current_intake_status} / {card.card_status} · {card.caveat or '—'}")

    with st.expander("검색 색인 관리 · 관리자"):
        if chunk_count == 0:
            st.warning("검색 색인이 아직 없습니다. 원문 해시 검증 후 색인을 재구축하세요.")
        if st.button("정책 원문 색인 재구축", help="공식 PDF/HTML과 팀 HTML에서 DB 검색 색인을 다시 만듭니다."):
            with st.spinner("원문을 추출하고 페이지·섹션 근거를 색인하는 중입니다."):
                report = rebuild_policy_index(svc.Session)
                diagnosis_base.clear()  # 요건 카드·출처가 바뀌므로 진단 payload 캐시도 비운다
            if report["failures"]:
                st.warning(f"{report['indexed_documents']}개 문서·{report['chunks']}개 청크 색인, 실패 {report['failures']}")
            else:
                st.success(f"{report['indexed_documents']}개 문서·{report['chunks']}개 청크를 색인했습니다.")
            st.rerun()
    return query


def page_policy():
    ensure_dx_defaults()
    ind, q = st.session_state.dx_industry, st.session_state.dx_quarter
    rec = snap.get(ind, q)
    if rec is None:
        st.warning("이 분석 버전에 해당 업종·분기 자료가 없습니다.")
        return
    base = diagnosis_base((snap.quarter, snap.version), q, ind, decision_support)
    field_questions_all = base["field_checks"]["questions"]
    sync_field_store(ind, q, field_questions_all)
    field_ctx = field_context_for(ind, q, field_questions_all)
    report_payload = with_session_context(base, field_ctx, datetime.now(timezone.utc).isoformat())
    t = rec["triage"]
    badge = ui.stage_badge_html(t["stage"], stage_display(t["stage"]))
    functions = report_payload.get("support_functions") or []
    fn_tags = [f["function_tag"] for f in functions]
    all_cards = report_payload.get("requirement_cards") or []
    counts = function_card_counts(functions, all_cards)
    tabs = [name for name, _, _ in ui.POLICY_TABS]
    st.session_state.setdefault("policy_tab", tabs[0])
    tab = st.session_state.policy_tab or tabs[0]
    selected = None

    with st.container(key="shell", horizontal=True, gap="small"):
        with st.container(key="leftpanel", width=320):  # 행정 AI 비서(copilot)와 같은 너비
            st.markdown("**현재 선택**")
            # policy_industry·policy_quarter는 dx_industry·dx_quarter의 거울 위젯 — 매 실행 공용 선택값으로 맞춘 뒤 만든다.
            st.session_state.policy_industry = ind
            st.selectbox("업종", snap.industries, key="policy_industry", on_change=sync_dx_industry_from_policy)
            st.session_state.policy_quarter = q
            st.selectbox("분기", snap.quarters[::-1], key="policy_quarter", on_change=sync_dx_quarter_from_policy,
                         format_func=lambda qq: f"{quarter_label(qq)} (최신)" if qq == snap.quarters[-1] else quarter_label(qq))
            st.html(ui.labeled_badge_html("현재 판정", badge))
            st.caption(nature_line(q))
            st.html(ui.policy_guide_html(tab))  # 위치 안내만 — 탭 전환은 중앙의 탭으로 한다
            st.button("← 업종 진단으로", key="policy_back", type="tertiary", on_click=go, args=("업종 진단",))

        with st.container(key="center", width="stretch"):
            with st.container(key="dxsec-policy-main"):
                st.html(ui.page_header_html("정책·지원 연계", ui.POLICY_TAB_HELP[tab]))
                with st.container(key="policytab"):
                    tab = st.segmented_control("정책·지원 연계 화면", tabs, key="policy_tab", required=True,
                                               label_visibility="collapsed") or tabs[0]
                if tab == tabs[0]:
                    st.html(ui.policy_context_html(ind, q, badge))
                    section("관련 지원 기능")
                    if not fn_tags:
                        st.caption("채용 키워드와 연결된 지원 기능 후보가 없습니다.")
                    options = ["*", *fn_tags]
                    # 0건 기능도 숨기지 않고 옅게만 표시(선택·필터 동작은 그대로)
                    faded = [i + 1 for i, tag in enumerate(options) if tag != "*" and not counts.get(tag, 0)]
                    if faded:
                        st.html("<style>" + ", ".join(
                            f'.st-key-fnpills [data-testid="stButtonGroup"] button:nth-of-type({n})' for n in faded)
                            + " { opacity: .55; }</style>")
                    with st.container(key="fnpills"):
                        pick = st.pills(
                            "관련 지원 기능", options=options, selection_mode="single", default="*", required=True,
                            format_func=lambda tag: (f"전체 · {len(all_cards)}건" if tag == "*" else
                                                     f"{function_ui_label(tag, C.label(tag))} · {counts.get(tag, 0)}건"),
                            key=f"policy_fn2::{ind}::{q}", label_visibility="collapsed")
                    selected = None if pick in (None, "*") else pick
                    intake = st.session_state.get(f"policy_intake::{ind}::{q}") or "*"
                    shown = filter_official_cards(all_cards, selected, None if intake == "*" else intake)
                    st.html(ui.section_count_html("연결 가능한 지원제도", f"관련 제도 {len(shown)}건"))
                    st.caption("현재 진단 결과로 검토할 수 있는 기존 공식 지원제도입니다. 지원 여부는 담당기관 확인이 필요합니다.")
                    with st.container(key="proghead"):
                        st.pills("진행 상태", ("*", *INTAKE_UI), selection_mode="single", default="*", required=True,
                                 format_func=lambda k: "진행 상태 전체" if k == "*" else INTAKE_UI[k],
                                 key=f"policy_intake::{ind}::{q}", label_visibility="collapsed")
                    fn_label = lambda tag: function_ui_label(tag, C.label(tag) if tag else None)  # noqa: E731
                    st.html(ui.official_programs_html(shown[:4], fn_label))
                    if len(shown) > 4:
                        with st.expander(f"더 많은 지원제도 보기 ({len(shown) - 4}건)"):
                            st.html(ui.official_programs_html(shown[4:], fn_label))
                else:
                    st.html(ui.team_intro_html())
                    st.html(ui.team_flow_html(TEAM_STAGE_FLOW))
                    stage_pick = st.pills(
                        "연계 단계", ["*", *TEAM_STAGE_FILTERS], selection_mode="single", default="*", required=True,
                        format_func=lambda s: f"전체 {len(TEAM_PROPOSALS)}" if s == "*" else s,
                        key="team_stage", label_visibility="collapsed")
                    shown = [p for p in TEAM_PROPOSALS if stage_pick in (None, "*") or stage_pick in p["stages"]]
                    st.html(ui.team_cards_html(shown, team_kpis, team_principles))

            if tab == tabs[0]:
                # 흐름: [1] 현재 진단 요약 → [2] 연결 가능한 지원제도(위) → [3] 현재 모집 중인 관련 공고
                #       → [4] 참고 기관·검토 경로(+ 관리자용 공식 근거 직접 검색)
                notices_view(ind, fn_tags)
                with st.container(key="dxsec-policy-more"):
                    with st.expander("참고 기관 · 검토 경로"):
                        institutions = list(snap.reference.get("institution_routing_map") or [])
                        st.html(ui.route_summary_html(t.get("first_owner"),
                                                      rec["questions"].get("handoff_review_functions"), institutions))
                    box = lazy_expander("공식 근거 직접 검색", "exp_policy_search")
                    with box:
                        if box.open:
                            policy_search_view()

        if tab == tabs[0]:
            context_tags = ["정책·지원 연계", *([function_ui_label(selected, C.label(selected))] if selected else [])]
        else:
            context_tags = [tabs[1]]  # 팀 제안은 전 업종 공통 — 업종 추천처럼 보이지 않게 탭 이름만
        copilot_panel(lambda: copilot_view(ind, q, field_ctx, t["stage"], snap.industries, f"{ind} · {quarter_label(q)}",
                                           context_tags, team=tab == tabs[1]))


# ------------------------------------------------------------------ 분기 사후검토
SELECTION_BIAS_NOTE = ("현장확인은 점검 건으로 개설된 사례를 중심으로 수행되므로, 관찰 업종과 개설되지 않은 후보에서 "
                       "놓친 신호는 이 지표로 확인할 수 없습니다. 이 화면은 업무 운영 결과를 돌아보는 것이며, "
                       "현장확인 결과를 판정의 정답으로 쓰지 않습니다.")


def share(m: dict, noun: str, short: bool = False) -> str:
    if not m["denominator"]:
        return "—" if short else f"{noun} 없음 — 비율 계산하지 않음"
    return f"{m['numerator']} / {m['denominator']} ({m['ratio'] * 100:.0f}%)"


def count_table(d: dict, key: str, empty: str):
    rows = [{key: k, "건수": v} for k, v in d.items()]
    if not rows or not sum(v for v in d.values()):
        st.caption(empty)
    st.table(pd.DataFrame(rows or [{key: "—", "건수": 0}]).set_index(key))


def page_operations():
    with st.container(key="adminpage"):
        st.html(ui.page_header_html("분기 사후검토", "관리 · 운영·검증용 보조 화면"))
        st.warning(SELECTION_BIAS_NOTE)
        quarter = st.selectbox("기준 분기", svc.operations_quarters(snap)[::-1], index=0, key="ops_quarter",
                               format_func=quarter_label)
        o = svc.operations_summary(snap, quarter)
        b = o["basis"]
        st.caption(f"후보 수는 분석본 {quarter_text(o['snapshot'])} 기준 · 시연 기록 {o['excluded_example_cases']}건(점검 건 단위, 그 하위 기록 전부)은 "
                   "모든 지표에서 제외 · 지표마다 기준 시점이 다릅니다(각 영역 설명 참고).")
        recorded = (o["cases_opened"] + o["scopes"] + o["referrals_created"] + o["cases_closed"]
                    + sum(o["occurred_in_quarter"].values()))
        if recorded == 0:
            st.info(f"{quarter_label(quarter)}에 해당하는 운영 점검 기록이 아직 없습니다. 아래 기록 지표는 0 또는 '아직 기록 없음'입니다.")
        if quarter not in snap.quarters:
            st.caption(f"{quarter_label(quarter)}는 분석본 {quarter_text(o['snapshot'])}에 없는 분기입니다 — 후보·개설 지표는 해당 없음"
                       "(실제 업무 발생·종결 기준 지표만 집계).")
        st.markdown(f"**①~④ 후보와 개설** · 기준: {b['candidates']}")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("① 우선점검 후보", o["priority_candidates"])
        c2.metric("② 그중 점검 건 개설", share(o["priority_opened"], "후보", short=True))
        c3.metric("③ 추가확인 후보", o["check_candidates"])
        c4.metric("④ 그중 점검 건 개설", share(o["check_opened"], "후보", short=True))
        st.caption("②·④ 분모 = 해당 분기 분석본의 후보 업종 수, 분자 = 그 후보에서 개설된 운영 점검 건의 업종 수. "
                   "분모가 0이면 '—'(비율 계산하지 않음).")

        left, right = st.columns(2)
        with left:
            st.markdown(f"**⑤ 현장확인 결과 분포** · 기준: {b['field_results']} · 단위: 문항(최근 결과)")
            count_table(o["field_results"], "결과", "아직 기록 없음")
            st.markdown(f"**⑥ 지원 필요 기능 선택 분포** · 기준: {b['support']}")
            count_table({fn_name(k): v for k, v in o["support_functions"].items()}, "지원 필요 기능", "아직 기록 없음")
            st.markdown(f"**⑩ 결정** · 기준: {b['decisions']}")
            count_table(o["decisions"], "결정", "아직 기록 없음")
        with right:
            st.markdown(f"**⑦·⑧ 인계와 회신** · 기준: {b['referrals']}")
            st.markdown(f"- 이 분기 점검 시점에서 작성한 인계 {o['referrals_created']}건 · 그중 발송이 기록된 인계 {o['referrals_sent']}건")
            st.markdown(f"- 회신이 기록된 인계: {share(o['referral_reply'], '발송 기록된 인계')}")
            st.caption("회신율 분모 = 이 분기 시점에서 작성되고 발송이 기록된 인계(작성만 된 인계 제외), 분자 = 그중 회신이 기록된 인계.")
            st.markdown(f"**발송·접수·회신 발생** · 기준: {b['occurred']}")
            occ, unk = o["occurred_in_quarter"], o["occurred_unknown_all_quarters"]
            st.markdown(f"- {quarter_label(quarter)}에 실제로 발생: 발송 {occ['발송']} · 접수 {occ['접수']} · 회신 {occ['회신']}")
            st.caption(f"발생시각 미입력(분기 배정 불가, 전체 기간): 발송 {unk['발송']} · 접수 {unk['접수']} · 회신 {unk['회신']}")
            st.markdown(f"**⑨ 단계 이동** · 기준: {b['stage_moves']} (분석본 단계를 옮긴 사실, 해석 없음)")
            count_table(o["stage_moves"], "단계 이동", "아직 기록 없음")
            st.markdown(f"**점검 건 종결** · 기준: {b['closed']}")
            st.markdown(f"- {quarter_label(quarter)}에 종결한 운영 점검 건: {o['cases_closed']}건")


# ------------------------------------------------------------------ 방법론·데이터 기준
def quote(doc: dict, section: str):
    body = doc.get("sections", {}).get(section) if doc.get("available") else None
    if body:
        with st.expander(f"원문 인용 — {doc['path']} · {section}"):
            st.markdown(quarter_text(body))  # 원문 파일은 그대로, 화면 표시만 분기 표기 통일


def page_methodology():
    with st.container(key="adminpage"):
        st.html(ui.page_header_html("방법론·데이터 기준", "설정·정보에서 연 화면 · 진단 구조·판정 기준·데이터 한계"))
        doc = registered_document(snap, "final_methodology")
        if doc.get("available"):
            st.caption(f"방법론 원문: {doc['path']} · 분석본 {quarter_label(snap.quarter)} {snap.version} 등록 해시 "
                       + ("일치" if doc["hash_match"] else "불일치 — 문서가 분석본 등록 이후 바뀌었습니다"))
        else:
            st.caption(f"방법론 원문을 찾을 수 없습니다: {doc.get('reason')}")

        sample = next((r for r in snap.records.values() if r.get("external_sources")), None)

        with st.container(border=True):
            st.markdown("#### 1. 진단 구조")
            st.markdown("상태 × 규모 × 시간 진단을 현장확인·기존 지원기능 연결·재점검까지 이어주는 "
                        "Human-in-the-Loop 의사결정 지원체계")
            states = sorted({(r["q1"]["state"], r["q1"]["state_label"]) for r in snap.records.values()})
            st.markdown("**Q1 상태(국면)**")
            st.dataframe(pd.DataFrame(states, columns=["상태", "설명"]), hide_index=True, width="stretch")
            st.markdown("**Q2 규모** · 고용 증감(명) · 산단 제조업 고용 비중 · 순감소 기여율")
            st.markdown("**Q3 시간** · 동일 상태 지속 분기 · 반복 진입신호 · 상태 전이")
            ladder = {r["rule_name"]: r for r in snap.reference["triage_rules"]}.get("ladder", {})
            st.markdown(f"**Triage** · {ladder.get('definition', '')} · 경계 {ladder.get('threshold') or '—'} · "
                        f"{stage_display('우선점검')} / {stage_display('추가확인')} / {stage_display('관찰')}")
            quote(doc, "최종 채택 구조")
            quote(doc, "Q1~Q3와 Triage")

        with st.container(border=True):
            st.markdown("#### 2. 판정 기준")
            spec = snap.meta["parameter_spec"]
            rule_df = (pd.DataFrame(spec["triage_rules"])[["rule_name", "definition", "threshold", "source_category"]]
                      .rename(columns={"rule_name": "규칙", "definition": "정의", "threshold": "경계",
                                       "source_category": "근거 구분"}))
            rule_df["근거 구분"] = rule_df["근거 구분"].map(lambda x: SOURCE_CATEGORY_LABEL.get(x, x))
            st.dataframe(rule_df, hide_index=True, width="stretch")
            st.caption(f"규칙 버전 {spec['triage_rule_version']}")
            st.caption("경계값은 프로젝트 운영규칙이며 법정 기준 또는 최적값이 아닙니다.")
            st.markdown(f"규칙 시나리오: {S.SCENARIO_STATUS_LABEL[snap.meta['scenario_status']]}")

        with st.container(border=True):
            st.markdown("#### 3. 무엇을 말할 수 있는가")
            st.markdown("- 업종별 산업·고용 변화\n- 점검 우선순위 신호\n- 지속·전환 상태")
            st.caption(quarter_text(snap.reference.get("scope", "")))

        with st.container(border=True):
            st.markdown("#### 4. 무엇을 말할 수 없는가")
            st.markdown("- 고용감소의 원인 자동판정\n- 기업별 위기 여부 확정\n"
                        "- 정책 적격 여부 자동판정\n- 예산/선정 여부 자동결정")
            st.markdown("고용 감소의 원인(수주·자동화·폐업·외주화 등)은 집계자료만으로 판단할 수 없습니다.")
            n_cards = sum(len(svc.requirement_cards(t)) for t in C.function_tags())
            st.markdown(f"지원사업 요건 카드: 공식 원장 {n_cards}건 — 일반 조건 안내용이며 자동 적격·승인 판정 아님")

        with st.container(border=True):
            st.markdown("#### 5. 데이터 기준·한계")
            st.markdown("**KICOX (CORE)**")
            st.caption(f"분석 범위: {quarter_text(meta['record_scope'])}")
            st.caption(f"자료 기준 {snap.provenance(snap.quarter).get('data_cutoff')}")
            st.caption(EIS_POPULATION_NOTE)

            st.markdown("**외부자료 (PPI 포함)**")
            if sample:
                for role in ("VALIDATION", "CONTEXT"):
                    title = ROLE_TITLE[role][0]
                    names = [s["label"] for s in sample["external_sources"] if s["role"] == role]
                    st.markdown(f"- **{title}** `{role}`: " + ", ".join(names))
            st.caption("외부자료는 Triage·선택적 재검토의 입력이 아니며 판정을 바꾸지 않습니다.")
            quote(doc, "외부데이터 원칙")

            st.markdown("**Work24 · FactoryOn**")
            for text_ in WORK24_BASIS.values():
                st.caption(f"- {text_}")
            dx_ind = st.session_state.get("dx_industry") or snap.industries[0]
            job_snapshot = decision_support.recruitment_snapshot(dx_ind)
            st.markdown(f"현재 선택 업종 기준 · {dx_ind}")
            for c in job_snapshot.get("caveat") or []:
                st.caption(f"- {quarter_text(c)}")
            st.caption(" · ".join(f"{k}: {v}" for k, v in RELEVANCE_LABELS.items()))
            st.caption("GENERAL_NONCORE는 산업기술·훈련 미스매치의 핵심 지표에서 제외합니다.")

            st.markdown("**데이터 시점 차이 · 현재 운영 한계**")
            cats = sorted({r["source_category"] for r in snap.meta["parameter_spec"]["triage_rules"]})
            unmapped = [fn_name(f["tag"]) for f in C.functions() if f["referable"] and not C.institution_candidates(
                f["tag"], snap.reference["institution_routing_map"])]
            jobs = next((s for s in (sample or {}).get("external_sources", []) if s["key"] == "changwon_jobs"), None)
            st.markdown(
                f"- 경계값 근거 구분: {', '.join(cats)} — 행정 최적값으로 검증된 경계값이 아님\n"
                f"- 현장확인 선택편향: {SELECTION_BIAS_NOTE.split('. ')[0]}.\n"
                f"- 담당기관 미확정 지원 기능: {', '.join(unmapped)}\n"
                f"- 검증된 담당기관 2곳은 기관 기능만 확인 — 실제 접수경로·기관 합의는 미확인\n"
                f"- 지원사업 요건 카드: 공식 원장 {sum(len(svc.requirement_cards(t)) for t in C.function_tags())}건 "
                "— 일반 조건 안내용이며 자동 적격·승인 판정 아님\n"
                f"- 고용24 공개 채용공고: {quarter_text(jobs['unavailable_label']) if jobs else '—'} — 현재 분석기간과 겹치지 않음\n"
                f"- 자동 재검토 표시: 비활성(기준 상태 {THRESHOLD_STATUS}) — 분석본 차이는 표시만 함\n"
                f"- 과거분기 진단: 분석 실행분이 {', '.join(quarter_label(x) for x in sorted({m['quarter'] for m in metas}))}뿐이므로 그 이전 분기는 "
                "후향 재구성 분석(당시 저장 분석본 없음, 후속 보정자료 반영 가능)\n"
                f"- 인증: {'프로토타입 · 인증 미연결(로컬 이름 입력)' if not RT.authenticated else RT.auth_mode}")
            quote(doc, "상태와 한계")

        with st.container(border=True):
            st.markdown("#### 6. 분석 버전·재구성")
            st.markdown(f"**{NATURE_LABEL['contemporaneous']}** vs **{NATURE_LABEL['reconstructed']}** · "
                        f"예: {nature_text(snap.quarter, snap.quarters[0])}")
            st.caption(f"분석 실행 분기: {', '.join(quarter_label(x) for x in sorted({m['quarter'] for m in metas}))}")
            st.caption("판정 추이 칸의 색은 등록 판정 단계이며 칸 사이 순서는 인과관계를 뜻하지 않습니다.")
            st.markdown("**분석본 버전 비교**")
            st.caption("같은 분석대상 분기의 두 분석본을 비교합니다. 분석본 파일은 수정하지 않습니다.")
            same = [m for m in metas if m["quarter"] == snap.quarter]
            vers = [m["snapshot_version"] for m in same]
            a, b = st.columns(2)
            old_v = a.selectbox("이전 버전", vers, index=max(0, len(vers) - 2), key="cmp_old")
            new_v = b.selectbox("비교 버전", vers, index=len(vers) - 1, key="cmp_new")
            if old_v == new_v:
                st.caption("서로 다른 버전을 고르세요.")
            else:
                version_compare_view(snapshot(snap.quarter, old_v), snapshot(snap.quarter, new_v))

        with st.container(border=True):
            st.markdown("#### 7. 선택적 재검토 — ELECTRE/SMAA")
            p = snap.reference["electre_smaa_protocol"]
            st.markdown(f"- 적용 범위: **{p['scope']}**\n"
                        f"- Triage 단계 변경: **{'금지' if p['triage_stage_mutation'] == 'forbidden' else p['triage_stage_mutation']}**\n"
                        f"- ELECTRE 결과 용도: {p['electre_result_use']}\n- SMAA 결과 용도: {p['smaa_result_use']}\n"
                        f"- CAI 해석: {p.get('cai_interpretation', '—')}")
            elec_spec = meta["parameter_spec"]
            st.caption(f"선택적 재검토 명세: {elec_spec['electre_specification']} · 적용 범위: {elec_spec['electre_scope']}")
            st.caption("Triage를 대체하지 않으며 추가확인 사례의 검토 보조용입니다.")
            quote(doc, "ELECTRE 선택적 채택")

        with st.container(border=True):
            st.markdown("#### 8. Human-in-the-Loop")
            st.markdown("- 점검 건 개설\n- 현장확인 결과\n- 지원 필요 기능\n- 담당 기관·인계, 발송·접수·회신 기록\n"
                        "- 재점검 판단(계속 점검·추가확인·모니터링 전환·새 인계·종결)\n- 점검 건 종결")
            st.caption("시스템은 위 항목을 자동으로 선택하거나 확정하지 않습니다.")
            st.caption(SELECTION_BIAS_NOTE)
            quote(doc, "Human Review와 지원연계")

        # 업종 진단에서 옮긴 분석 담당자용 상세(판정 경로·규모 gate·선택적 재검토·외부자료·분석 보완·자료 품질)
        ensure_dx_defaults()
        dx_ind, dx_q = st.session_state.dx_industry, st.session_state.dx_quarter
        with st.expander(f"선택 업종 분석 상세 · {dx_ind} · {quarter_label(dx_q)} · 판정 경로·규모 gate·선택적 재검토·외부자료·자료 품질"):
            dx_rec = snap.get(dx_ind, dx_q)
            if dx_rec is None:
                st.caption("이 분석 버전에 해당 업종·분기 자료가 없습니다.")
            else:
                aux_evidence_view(dx_rec, dx_q)


# ------------------------------------------------------------------ 변경 기록
FIELD_KO = {
    "id": "번호", "case_id": "점검 건 번호", "industry": "업종", "quarter": "대상 분기",
    "snapshot_quarter": "사용 분석본 실행 분기", "snapshot_version": "사용 분석본",
    "snapshot_data_hash": "분석본 자료 해시", "snapshot_nature": "분석본 성격",
    "triage_stage_at_open": "개설 당시 Triage", "origin": "개설 경로",
    "candidate_review_id": "점검 후보 검토 번호", "opening_reason": "개설 사유", "assignee": "담당자",
    "status": "상태", "decision": "결정", "next_review_quarter": "다음 검토 분기", "opened_by": "개설자",
    "opened_at": "개설 시각", "closed_by": "종결자", "closed_at": "종결 시각", "closing_note": "종결 사유·메모",
    "is_example": "시연 기록", "checklist_size": "현장확인 문항 수", "candidate_type": "후보 구분",
    "reviewer": "담당자", "note": "메모", "position": "문항 순서", "question_text": "확인질문",
    "question_source": "질문 출처", "method": "확인 방법", "result_code": "결과",
    "performed_at": "실제 확인 일시", "performed_at_unknown": "실제 확인 일시 미입력",
    "recorded_by": "기록자", "recorded_at": "기록 시각", "rationale": "결정 근거", "decided_by": "결정자",
    "decided_at": "결정 시각", "decision_record": "결정 기록", "function_tags": "지원 필요 기능",
    "field_checked": "현장확인 후 선택", "catalog_version": "기능 목록 버전", "decision_id": "결정 번호",
    "quarterly_review_id": "점검 시점 번호", "check_item_id": "현장확인 문항 번호",
    "function_tag": "지원 필요 기능", "institution": "담당 기관", "institution_unit": "담당 단위",
    "institution_source_url": "기관 공식 출처", "institution_source": "기관 목록 출처",
    "mapping_verified_at": "기관 기능 확인일", "created_by": "작성자",
    "created_at": "작성 시각", "sent_by": "발송 기록자", "sent_at": "실제 발송 일시", "sent_note": "발송 메모",
    "contact_method": "실제 연락·접수 방식", "contact_route": "실제 사용한 접수·연락 경로",
    "external_reference": "외부 참조번호·비고",
    "received_by": "접수 확인 기록자", "received_at": "실제 접수 일시", "received_note": "접수 메모",
    "replied_by": "회신 기록자", "replied_at": "실제 회신 일시", "reply_content": "회신 내용",
    "followup_note": "추가확인 필요 사유", "occurred_at_unknown": "실제 발생 일시 미입력",
    "review_kind": "점검 시점 구분", "previous_quarter": "직전 점검 분기",
    "previous_snapshot_quarter": "직전 분석본 실행 분기", "previous_snapshot_version": "직전 분석본",
    "previous_stage": "직전 단계", "current_stage": "이 시점 단계", "review_status": "점검 시점 상태",
    "started_at": "시작 시각", "reviewed_at": "완료 시각", "updated_at": "수정 시각", "scope": "점검 시점",
    "function_description": "기관 기능 설명", "source_url": "공식 출처", "basis": "근거 메모",
    "proposed_by": "제안자", "proposed_at": "제안 시각", "reviewed_by": "검토자", "review_note": "검토 메모",
    "intake_route_verified": "실제 접수경로 확인", "intake_route": "실제 접수경로", "unit": "담당 단위",
}
STATUS_KO = {"proposed": "검토 중(인계 불가)", "verified": "검증됨", "rejected": "반려"}


def field_value(key: str, v) -> str:
    if v is None or v == "":
        return "—"
    if isinstance(v, bool):
        return "예" if v else "아니오"
    if key == "function_tags":
        return ", ".join(C.label(t) for t in v) or "선택 없음"
    if key == "function_tag":
        return C.label(v)
    if key == "snapshot_nature":
        return NATURE_LABEL.get(v, v)
    if key == "status" and v in STATUS_KO:
        return STATUS_KO[v]
    if key.endswith("_at") and isinstance(v, str) and "T" in v:
        return f"{ts(v)} KST"
    return str(v)


def change_rows(a: dict) -> pd.DataFrame:
    before, after = a["before"] or {}, a["after"] or {}

    def flat(d):
        out = {}
        for k, v in d.items():
            if isinstance(v, dict):
                out.update({(k, kk): vv for kk, vv in v.items()})
            else:
                out[(k,)] = v
        return out
    b, f = flat(before), flat(after)
    rows = []
    for k in list(dict.fromkeys([*b, *f])):
        name = " · ".join(FIELD_KO.get(x, x) for x in k)
        old, new = field_value(k[-1], b.get(k)), field_value(k[-1], f.get(k))
        rows.append({"항목": name, "변경 전": old if a["before"] else "(새 기록)", "변경 후": new,
                     "바뀜": "●" if old != new else ""})
    rows.sort(key=lambda r: r["바뀜"] != "●")  # 바뀐 항목을 먼저
    return pd.DataFrame(rows)


def audit_frame(logs: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([{
        "기록 시각(KST)": ts(a["created_at"]), "담당자": a["actor"], "행동": ACTION_LABEL.get(a["action"], a["action"]),
        "대상": f"{TARGET_LABEL.get(a['target_type'], a['target_type'])} #{a['target_id']}",
        "사용 분석본": f"{quarter_label(a['snapshot_quarter'])} {a['snapshot_version']}" if a["snapshot_quarter"] else "—",
    } for a in logs])


def page_audit():
    with st.container(key="adminpage"):
        st.html(ui.page_header_html("변경 기록", "관리 · 운영·검증용 보조 화면"))
        st.caption("관리용 보조 화면 · 기록은 추가만 되며 수정·삭제되지 않습니다. 항목 이름은 업무용 표현으로 바꿔 보여줍니다.")
        logs = svc.audit_log()
        if not logs:
            st.info("기록된 변경이 없습니다.")
            return
        st.dataframe(audit_frame(logs), hide_index=True, width="stretch")
        pick = st.selectbox("상세 보기", [a["id"] for a in logs],
                            format_func=lambda i: next(f"기록 #{i} · {ACTION_LABEL.get(x['action'], x['action'])}"
                                                       for x in logs if x["id"] == i))
        a = next(x for x in logs if x["id"] == pick)
        st.markdown(f"**{ACTION_LABEL.get(a['action'], a['action'])}** · "
                    f"{TARGET_LABEL.get(a['target_type'], a['target_type'])} #{a['target_id']} · "
                    f"{a['actor']} · {ts(a['created_at'])} KST")
        st.dataframe(change_rows(a), hide_index=True, width="stretch")


flash = st.session_state.pop("_flash", None)
if flash:
    st.success(flash)
with st.container(key="pagebody"):
    {"업종 진단": page_diagnosis, "점검 관리": page_inspection, "정책·지원 연계": page_policy,
     "분기 사후검토": page_operations, "방법론·데이터 기준": page_methodology, "변경 기록": page_audit}[st.session_state.page]()

# 현재 화면을 주소에 남긴다(새로고침 복원용). 점검 관리에서는 선택한 점검 건·보기도 함께.
_qp = {"page": st.session_state.page}
if st.session_state.page == "점검 관리":
    if st.session_state.get("case_id") is not None:
        _qp["case"] = str(st.session_state.case_id)
    if st.session_state.get("insp_view") in INSP_VIEWS:
        _qp["view"] = st.session_state.insp_view
if dict(st.query_params) != _qp:
    st.query_params.from_dict(_qp)
