"""창원국가산단 산업·고용 전환진단 및 점검연계 시스템 — Phase 0~4.5 화면.

실행: streamlit run src/app/main.py
분석값은 등록된 분석 버전(Snapshot)에서만 읽는다. 이 화면은 어떤 판정도 다시 계산하지 않는다.
"""
from __future__ import annotations

import html
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from export import schema as S  # noqa: E402
from export.diff import THRESHOLD_STATUS, record_diff, snapshot_diff  # noqa: E402
from export.documents import registered_document  # noqa: E402
from export.snapshot import (  # noqa: E402
    NATURE_LABEL, list_snapshots, load_snapshot, nature_note, resolve_for_quarter, snapshot_nature,
)
from app import ui  # noqa: E402
from app.view_models import (  # noqa: E402
    RELEVANCE_LABELS, caveat_items, evidence_level_value, fact_items, field_context,
    quick_prompts, report_download, rule_evidence_rows, session_scope, stage_code, stage_counts,
    with_session_context,
)
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
st.html("<style>" + (Path(__file__).resolve().parent / "styles" / "dashboard.css").read_text(encoding="utf-8")
       + "</style>")

STAGE_COLOR = {"우선점검": "red", "추가확인": "orange", "관찰": "gray"}
PAGES = ("업종 진단", "점검 대기열", "점검 건", "분기 사후검토", "정책 근거", "투명성·방법론", "변경 기록")
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
    st.caption(nature_note(run_quarter, target_quarter)
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


def go(page: str, industry: str | None = None, quarter: str | None = None, case_id: int | None = None):
    """화면 이동 요청. 다음 실행에서 위젯이 만들어지기 전에 적용된다."""
    st.session_state._nav = (page, industry, quarter, case_id)


def apply_nav():
    nav = st.session_state.pop("_nav", None)
    if not nav:
        return
    page, industry, quarter, case_id = nav
    st.session_state.page = page
    if industry:
        st.session_state.dx_industry = industry
    if quarter:
        st.session_state.dx_quarter = quarter
    if case_id is not None:
        st.session_state.case_id = case_id


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

if "page" not in st.session_state:
    st.session_state.page = PAGES[0]
apply_nav()

# 화면 이동은 상단 헤더 탭(go → apply_nav)이 st.session_state.page를 바꾼다. 실행 배너는 헤더 상태 표시에 둔다.
labels = [f"{m['quarter']} {m['snapshot_version']}" for m in metas]
st.session_state.setdefault("analysis_version", labels[-1])
st.session_state.setdefault("actor", "")
meta = metas[labels.index(st.session_state.analysis_version)]
snap = snapshot(meta["quarter"], meta["snapshot_version"])
# 신원 경계: 로컬 프로토타입은 입력한 이름을 'local:<이름>' 신원으로 쓴다(인증 아님)
actor = local_actor(st.session_state.actor)

with st.container(key="topbar"):
    with st.container(horizontal=True, vertical_alignment="center", gap="small"):
        st.html(ui.brand_html(f"규칙 {meta['rule_version'].split('/')[-1]}"), width="stretch")
        with st.container(key="topactions", horizontal=True, gap="small", width="content",
                          vertical_alignment="center"):
            # 진단서 출력·다운로드 버튼 자리 — 업종 진단 화면이 payload를 만든 뒤 채운다.
            header_doc_slot = st.container(horizontal=True, gap="small", width="content")
            with st.popover("⚙ 설정", help="담당자 · 분석 버전 · 경계값 규칙"):
                st.text_input("담당자 이름", key="actor", help="모든 검토·개설·결정 기록에 남습니다.")
                st.selectbox("분석 버전", labels, key="analysis_version",
                             help="분석 실행 분기별로 보존된 불변 분석본. 실행 분기 이전 분기는 후향 재구성 값입니다.")
                st.caption(
                    f"기준분기 {meta['quarter']} · 규칙 버전 `{meta['rule_version']}`\n\n"
                    f"분석 실행 {meta['source_run']['triage_run_at_utc'][:10]} · 등록 {meta['created_at'][:10]}"
                )
                st.markdown(f"**규칙 시나리오** · {S.SCENARIO_STATUS_LABEL[meta['scenario_status']]}")
                st.caption(f"분석 범위: {meta['record_scope']}")
                spec = meta["parameter_spec"]
                st.caption(f"선택적 재검토 명세: {spec['electre_specification']} · 적용 범위: {spec['electre_scope']}")
                st.caption("경계값 표 전체는 '관리 · 투명성·방법론' 화면에서 볼 수 있습니다.")
    with st.container(key="topnav", horizontal=True, gap=None):
        for p in PAGES:
            nav_label = f"관리 · {p}" if p in {"투명성·방법론", "변경 기록"} else p
            cur = st.session_state.page == p
            st.button(nav_label, key=("navcur-" if cur else "nav-") + p, on_click=go, args=(p,))
        st.space("stretch")
        data_cutoff = snap.provenance(snap.quarter).get("data_cutoff")
        pills = [("ok", f"분석본 {meta['quarter']} {meta['snapshot_version']} 적재 · 자료 기준 {data_cutoff} · "
                        f"등록 {meta['created_at'][:10]}")]
        if RT.banner:
            pills.append(("warn" if RT.demo else "info", RT.banner))
        st.html(ui.status_pills_html(pills), width="content")

try:
    database_url = M.database_url_for_runtime(RT.demo)
except M.DatabaseScopeError as e:
    st.error(str(e))
    st.stop()
svc = service(database_url, RT.demo)
policy = PolicyRAG(svc.Session)
decision_support = DecisionSupportService(svc.Session, snap, svc)


# ------------------------------------------------------------------ 공통 조각
def stage_badge(stage: str, label: str | None = None):
    st.badge(label or stage, color=STAGE_COLOR.get(stage, "gray"))


def electre_line(e: dict) -> str:
    return (f"ELECTRE: **{e['electre_stage']}** ({e['electre_stage_label']}) · "
            f"SMAA 가능 단계: **{' | '.join(e['possible_stages_list']) or '—'}** · "
            f"파라미터 민감: **{fmt(e['smaa_parameter_sensitive'])}**")


def open_case_form(rec: dict, key: str):
    stage = rec["triage"]["stage"]
    title = "점검 건 개설" if stage != "관찰" else "수동 점검 건 개설(관찰 단계)"
    with st.form(f"open_{key}"):
        st.markdown(f"**{title}** — {rec['industry']} {rec['quarter']} · 분석 버전 {snap.quarter} {snap.version} 기준으로 고정됩니다.")
        reason = st.text_area("개설 사유 (필수)")
        assignee = st.text_input("담당자 (필수)", value=actor.display_name if actor else "")
        st.caption(nature_note(snap.quarter, rec["quarter"])
                   + (" · 시연 모드: 시연 기록으로 개설됩니다(운영지표 제외)." if RT.demo else ""))
        if st.form_submit_button("점검 건 개설", type="primary", disabled=not actor):
            cid = run(lambda: svc.open_case(actor, snap, rec["industry"], rec["quarter"], reason, assignee),
                      f"점검 건을 개설했습니다 — {rec['industry']} {rec['quarter']}.")
            if cid:
                go("점검 건", case_id=cid)
                st.rerun()


# ------------------------------------------------------------------ 화면 A. 점검 대기열
def page_queue():
    st.title("점검 대기열")
    due = svc.due_reviews(resolved)
    st.subheader(f"재점검 예정 · {len(due)}건")
    st.caption("열린 점검 건 중, 담당자가 기록한 다음 검토 분기의 분석 자료가 등록된 건입니다. 그 분기 실행 분석본(당시 분석본)이 "
               "있으면 그것을, 없으면 후향 재구성 분석을 씁니다. 순서는 다음 검토 분기·점검 건 번호 순이며 우선순위가 아닙니다.")
    if not due:
        st.caption("재점검 예정 없음")
    for d in due:
        with st.container(border=True):
            a, b = st.columns([4, 1])
            a.markdown(f"**#{d['case_id']} {d['industry']}** · 직전 점검 {d['previous_quarter']} ({d['previous_stage']}) "
                       f"→ 재점검 분기 **{d['review_quarter']}** · 현재 결정 {d['decision'] or '—'}"
                       + f" · 분석본 {d['snapshot']} ({NATURE_LABEL[d['snapshot_nature']]})"
                       + (" · 모니터링 중" if d["case_status"] == "모니터링" else "")
                       + (" · _시연 기록_" if d["is_example"] else ""))
            b.button("점검 건 열기", key=f"due_{d['case_id']}", on_click=go, args=("점검 건", None, None, d["case_id"]))
    st.divider()
    quarter = st.selectbox("분기", snap.quarters[::-1], index=0, key="queue_quarter")
    st.info("Triage 결과는 **점검 후보**입니다. 점검 건은 담당자가 검토 후 직접 개설할 때만 만들어집니다.")
    nature_badge(snap.quarter, quarter)
    rows = {c["industry"]: c for c in svc.candidates(snap, quarter)}
    recs = snap.by_quarter(quarter)
    groups = [("우선점검", "우선점검 후보"), ("추가확인", "추가확인 검토"), ("관찰", "정기 모니터링(관찰)")]
    for stage, title in groups:
        items = sorted([r for r in recs if r["triage"]["stage"] == stage], key=lambda r: r["triage"]["rank_in_stage"])
        st.subheader(f"{title} · {len(items)}개 업종")
        if not items:
            st.caption("해당 없음")
            continue
        if stage == "관찰":
            st.dataframe(pd.DataFrame([{
                "업종": r["industry"], "Q1 상태": r["q1"]["state_label"],
                "고용 증감(명)": r["q2"]["emp_delta"], "판정 사유": r["triage"]["stage_reason"],
            } for r in items]), hide_index=True, width="stretch")
            pick = st.selectbox("업종 진단 보기", [r["industry"] for r in items], key=f"obs_{quarter}")
            st.button("진단 열기", key=f"obs_go_{quarter}", on_click=go, args=("업종 진단", pick, quarter))
            continue
        for r in items:
            c = rows[r["industry"]]
            with st.container(border=True):
                a, b = st.columns([3, 2])
                with a:
                    stage_badge(stage, r["triage"]["candidate_label"])
                    st.markdown(f"#### {r['industry']} · {quarter}")
                    st.caption(f"단계 내 {r['triage']['rank_in_stage']}순위")
                    st.write(r["triage"]["stage_reason"])
                    st.caption(f"고용 증감 {fmt(r['q2']['emp_delta'], suffix='명')} · 감소 기여율 "
                               f"{fmt(r['q2']['contribution_pct'], 1, '%')} · 1차 검토 기능: {r['triage']['first_owner']}")
                    if r["electre_smaa"]["available"]:
                        st.caption("선택적 재검토 정보 — " + electre_line(r["electre_smaa"]))
                with b:
                    review = c["review"]
                    if c["open_case_id"]:
                        st.success(f"진행 중 점검 건 #{c['open_case_id']}")
                        st.button("점검 건 열기", key=f"case_{r['industry']}_{quarter}",
                                  on_click=go, args=("점검 건", None, None, c["open_case_id"]))
                    elif review:
                        st.write(f"검토 상태: **{review['status']}** ({review['reviewer']})")
                    else:
                        st.write("검토 상태: **검토 전**")
                        if st.button("검토 시작", key=f"rev_{r['industry']}_{quarter}", disabled=not actor):
                            if run(lambda: svc.start_candidate_review(actor, snap, r["industry"], quarter),
                                   "검토를 시작했습니다.") is not None:
                                st.rerun()
                        if not actor:
                            st.caption("상단 ⚙ 설정에서 담당자 이름을 입력하세요.")
                    st.button("업종 진단 보기", key=f"dx_{r['industry']}_{quarter}",
                              on_click=go, args=("업종 진단", r["industry"], quarter))


# ------------------------------------------------------------------ 화면 B. 업종 진단
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
    st.markdown(f"#### 외부자료 ({quarter} 기준)")
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
                    st.markdown(f"- **{src['label']}** — {src['source_period']}")
                    for line in source_lines(src):
                        st.markdown(f"    - {line}")
                    if src["key"] == "eis_cci":
                        st.caption(EIS_POPULATION_NOTE)
                    for n in src["scope_notes"]:
                        if src["key"] != "eis_cci":
                            st.caption(n)
                else:
                    st.markdown(f"- **{src['label']}** — {src['unavailable_label']}")
                    if src.get("quality_only") and src.get("quality"):
                        st.caption("자료 품질·결합 한계")
                        st.json(src["quality"], expanded=False)


def timeline_chips(industry: str, current_quarter: str):
    """분기별 판정 추이 칩. 클릭하면 그 분기로 이동한다(altair 차트 대신 클릭 가능한 chip)."""
    # 전체 등록 분기를 보여주고(최신 분기 기준 이력), 선택 분기는 화면에서 표시한다 — 과거 분기에서도 앞으로 이동 가능
    rows = decision_support.timeline(industry, snap.quarters[-1])
    if not rows:
        st.info("표시할 진단 이력이 없습니다.")
        return
    st.html(ui.timeline_style_html([(row["quarter"], stage_code(row["stage"])) for row in rows], current_quarter))
    with st.container(key="timeline", horizontal=True, gap="small"):
        for row in rows:
            qq = row["quarter"]
            st.button(f"{qq[2:4]}{qq[4:]}", key=f"tl-{qq}", on_click=set_quarter, args=(qq,),
                      help=f"{qq} · {row['stage']}")
    st.caption("칸을 누르면 그 분기로 이동 · 선은 인과관계 아님")


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


def recruitment_view(jobs: dict, keywords: list[dict], is_latest_quarter: bool):
    """F. Work24·FactoryOn Recruitment Layer — 목록/공식확인/현재유효/상세검증을 서로 다른 증거 수준으로 보여준다."""
    keywords = keywords[:12] if jobs.get("status") == "FOUND" else []
    st.html(ui.recruitment_html(jobs, keywords, is_latest_quarter))
    distribution = jobs.get("job_relevance_distribution") or {}
    if distribution:
        st.caption("직무 관련성 분류(상세 검증 공고만): " + " · ".join(
            f"{RELEVANCE_LABELS.get(key, key)} {value}건" for key, value in distribution.items())
            + " · GENERAL_NONCORE는 산업기술·훈련 미스매치의 핵심 지표에서 제외합니다.")
    caveats = jobs.get("caveat", [])
    if caveats and jobs.get("status") == "FOUND":
        box = lazy_expander("해석 주의사항", "exp_jobs_caveat")
        with box:
            for caveat in caveats if box.open else ():
                st.caption(f"- {caveat}")


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


def handoff_view(rec: dict, report_payload: dict):
    """H. 기존 지원체계 검토 경로(dark card) + 공식 요건 카드 + 팀 제안(별도 expander)."""
    t = rec["triage"]
    institutions = list(snap.reference.get("institution_routing_map") or [])
    st.html(ui.handoff_html(t.get("first_owner"), rec["questions"].get("handoff_review_functions"),
                            report_payload.get("support_functions") or [],
                            report_payload.get("requirement_cards") or [], institutions))
    box = lazy_expander("팀 제안 · 공식 정책 아님", "exp_team_proposals")
    with box:
        if not box.open:
            return
        st.caption("아래 항목은 시행 중인 정부 지원사업이 아니라 분석 결과를 바탕으로 팀이 제안한 검토 아이디어입니다.")
        proposals = report_payload.get("team_proposals") or []
        if not proposals:
            st.caption("등록된 팀 제안이 없습니다.")
        for proposal in proposals:
            st.badge("팀 제안 · 공식 정책 아님", color="violet")
            st.markdown(f"**{proposal['title']}**")
            st.caption(proposal.get("purpose") or "제안 목적 미확인")


def copilot_view(industry: str, quarter: str, field_ctx: dict, stage: str | None, industries: list[str]):
    scope = session_scope(industry, quarter)
    histories = st.session_state.setdefault("copilot_histories", {})
    history = histories.setdefault(scope, [])
    with st.container(horizontal=True, vertical_alignment="center"):
        st.html('<div class="dx-copilot-title"><span class="dx-dot"></span>지능형 행정 AI 비서</div>')
        if st.button("↻", key=f"chatreset::{scope}", help="이 업종·분기 대화 초기화"):
            history.clear()
            st.rerun()
    st.html(f'<div class="dx-copilot-sub">컨텍스트 · <b>{html.escape(industry)}</b> · {html.escape(quarter)} · '
            f'{html.escape(stage or "판정 없음")} — 진단·판정 이력·Work24·현장입력·정책 RAG를 Python 객체로 직접 전달</div>')
    other_options = ["(선택 안 함)"] + [i for i in industries if i != industry]
    other = st.selectbox("비교 업종(선택)", other_options, key=f"cmp::{scope}")
    quick = quick_prompts(stage)
    selected, comparison_industry = None, None
    with st.container(key="chips", horizontal=True, gap="small"):
        for index, question in enumerate(quick):
            if st.button(question, key=f"chip-{index}::{scope}"):
                selected = question
        if other != "(선택 안 함)" and st.button(f"{industry}와 {other} 비교", key=f"chip-cmp::{scope}"):
            selected, comparison_industry = f"{industry}와 {other} 비교", other
    with st.container(key="chatlog", height=420):
        if not history:
            st.caption(f"{industry} · {quarter} 진단·현장확인·정책 연계에 대해 무엇이든 물어보세요.")
        for message in history:
            with st.chat_message(message["role"]):
                st.write(message["content"])
                for src in message.get("policy_sources") or []:
                    if src.get("source_url"):
                        st.caption(f"근거: {src.get('document_id', '')} · {src.get('title', '')}")
                        st.markdown(f"[원문 보기]({src['source_url']})")
                if message.get("caveats"):
                    with st.expander("근거 한계"):
                        for caveat in message["caveats"]:
                            st.caption(f"- {caveat}")
    typed = st.chat_input("업종 진단 및 정책 연계에 대해 질문하세요", key=f"chat::{scope}")
    prompt = selected or typed
    if prompt:
        result = decision_support.answer(prompt, quarter, industry, comparison_industry=comparison_industry,
                                         field_context=field_ctx)
        history.extend([
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": result["answer"], "caveats": result.get("caveats", []),
             "policy_sources": result.get("policy_sources", [])},
        ])
        st.rerun()


def report_view(payload: dict):
    st.markdown(f"### {payload['industry']} · {payload['quarter']} 진단 보고서")
    triage, q1, q2, q3 = payload.get("triage") or {}, payload.get("q1") or {}, payload.get("q2") or {}, payload.get("q3") or {}
    st.html(ui.kpi_cards_html([
        {"label": "현재 진단", "value": triage.get("stage") or "자료 없음"},
        {"label": "Q1 상태", "value": " · ".join(x for x in (q1.get("state"), q1.get("state_label")) if x) or "자료 없음"},
        {"label": "Q2 고용 증감", "value": fmt(q2.get("employment_change"), suffix="명"),
         "tone": "rose" if (q2.get("employment_change") or 0) < 0 else "emerald"},
        {"label": "Q3 지속", "value": fmt(q3.get("duration"), suffix="분기")},
    ]))
    st.markdown(f"**우선점검·판정 근거** · {triage.get('reason') or '자료 없음'}")
    jobs = payload.get("recruitment_snapshot") or {}
    st.markdown("**Recruitment Layer** · " + " → ".join(
        f"{level['label']} {evidence_level_value(level)}" for level in jobs.get("evidence_levels", [])))
    checks = payload.get("field_checks", {}).get("session_context", {})
    st.markdown("**현장 확인 입력(현재 세션)**")
    answered = [row for row in checks.get("responses", []) if row.get("checked") or row.get("answer")]
    for row in answered:
        st.markdown(f"- {row['question']} — {row.get('answer') or '확인 표시만 입력'}")
    if not answered:
        st.caption("입력된 현장 확인 내용 없음")
    st.markdown(f"**공식 정책 연결** · {len(payload.get('requirement_cards') or [])}건 (요건·접수 가능 여부 재확인 필요)")
    st.markdown(f"**팀 제안** · {len(payload.get('team_proposals') or [])}건 (공식 정책 아님)")
    with st.expander("데이터 한계·출처 기준"):
        for caveat in payload.get("caveat") or []:
            st.caption(f"- {caveat}")
        st.json({"basis_date": payload.get("basis_date"),
                 "snapshot_provenance": payload.get("snapshot_provenance"),
                 "contract_version": payload.get("contract_version")}, expanded=False)
    st.download_button("진단 payload 다운로드 (JSON)", report_download(payload),
                       file_name=f"diagnosis_{payload['industry']}_{payload['quarter']}.json",
                       mime="application/json", type="primary")
    st.caption("현재 백엔드가 제공하는 JSON payload만 내보냅니다. 지원하지 않는 PDF/HTML을 임의 생성하지 않습니다.")


@st.dialog("1페이지 진단카드", width="large")
def report_dialog(payload: dict):
    report_view(payload)


def left_panel(industries: list[str], quarters: list[str], latest_quarter: str,
              ind: str, q: str, rec: dict | None, report_payload: dict | None):
    st.markdown("**진단 기준 분기**")
    st.selectbox("분기", quarters, key="dx_quarter", label_visibility="collapsed",
                format_func=lambda qq: f"{qq} (최신)" if qq == latest_quarter else qq)
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
        t, q1, q2, q3, sg = rec["triage"], rec["q1"], rec["q2"], rec["q3"], rec["signals"]
        # 경계값은 등록 규칙 문자열 그대로(rule_evidence_rows) — 화면에서 새로 정하지 않는다
        evidence = rule_evidence_rows(rec, {r["rule_name"]: r for r in snap.reference["triage_rules"]})

        def with_bounds(row: dict) -> str:
            bounds = "/".join(x for x in (row["entry_threshold"], row["upper_threshold"]) if x)
            return f"{row['current']} (경계 {bounds})" if bounds else row["current"]
        rows = [
            ("Q1 상태", " · ".join(x for x in (q1["state"], q1["state_label"]) if x) or "자료 없음"),
            ("Q2 고용 증감", f"{fmt(q2['emp_delta'], suffix='명')} (YoY {fmt(q2['employment_yoy'], 2, '%')})"),
            ("E 고용감소율", with_bounds(evidence[0])),
            ("R 산단평균 대비 열위", with_bounds(evidence[1])),
            ("A 산단 대비 감소규모", with_bounds(evidence[2])),
            ("P 생산감소(보강)", with_bounds(evidence[3]) if sg["P"] is not None else "생산 미확인"),
            ("Q3 반복·지속", ("미확인" if q3["repeated_signal"] is None
                          else ("반복 있음" if q3["repeated_signal"] else "반복 없음"))
             + f" · 동일 상태 {fmt(q3['state_run_length'])}분기"),
        ]
        st.html(ui.metric_list_html(f"선택 업종 지표 · {ind}", rows,
                                    badge_html=ui.stage_badge_html(t["stage"], t["stage_label"])))
        if st.button("1페이지 진단카드 보기", key="open_report_dialog", type="primary", width="stretch"):
            report_dialog(report_payload)

    with st.container(key="noticecard"):
        st.caption("본 시스템은 원인을 자동 단정하거나 지원사업을 자동 선정하지 않으며, "
                   "담당자의 확인·판단을 지원합니다.")


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
        st.markdown(f"#### 최신분기 외부근거 요약 카드 · 원천 분기 {ev['source_quarter']}")
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
        st.caption(f"{q} 분기 해석층이 만든 질문 · 현장에서 추가로 확인할 내용이며 "
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


def reviewer_section(ind: str, q: str, rec: dict, t: dict):
    cand = next(c for c in svc.candidates(snap, q) if c["industry"] == ind)
    if cand["open_case_id"]:
        st.success(f"진행 중 점검 건 #{cand['open_case_id']}")
        st.button("점검 건 열기", key="reviewer_open_case",
                 on_click=go, args=("점검 건", None, None, cand["open_case_id"]))
    elif not actor:
        st.caption("상단 ⚙ 설정에서 담당자 이름을 입력하면 검토·개설할 수 있습니다.")
    elif t["stage"] == "관찰":
        st.caption("관찰 단계는 점검 후보가 아닙니다. 필요하면 사유를 적고 수동으로 개설할 수 있습니다.")
        open_case_form(rec, f"{ind}_{q}")
    elif cand["review"] is None:
        if st.button(f"{t['candidate_label']} 검토 시작", type="primary", key="reviewer_start"):
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


def center_card(ind: str, q: str, rec: dict, latest_quarter: str, jobs: dict, field_questions: list[dict],
                current_field_context: dict, report_payload: dict):
    t, q1, q2, q3 = rec["triage"], rec["q1"], rec["q2"], rec["q3"]
    provenance = snap.provenance(q)
    meta_line = (f"자료 기준 {provenance['data_cutoff']} · 산단 제조업 고용의 "
                f"{fmt(q2['employment_share_pct'], 2)}%({fmt(q2['employment'], suffix='명')}) · "
                f"단계 내 {t['rank_in_stage']}순위 · 다음 검토 {t['next_review_quarter']}")
    st.html(ui.header_html(q, ind, t["stage"], t["stage_label"], meta_line))
    # 분석본 성격(당시/후향 재구성)은 텍스트로 항상 드러낸다 — 후향 재구성을 당시 분석본처럼 보이게 하지 않는다
    nat = snapshot_nature(snap.quarter, q)
    st.caption(f":{'blue' if nat == 'contemporaneous' else 'violet'}-badge[{NATURE_LABEL[nat]}] "
               f"{nature_note(snap.quarter, q)}")

    kpi_cards = [
        {"label": "Q1 상태 (국면)", "value": " · ".join(x for x in (q1["state"], q1["state_label"]) if x) or "자료 없음",
         "sub": ("생산 미확인" if q1.get("production_yoy") is None
                else f"생산 {fmt(q1['production_yoy'], 1, '%')}")},
        {"label": "Q2 고용증감 (규모)", "value": fmt(q2["emp_delta"], suffix="명"),
         "tone": "rose" if (q2["emp_delta"] or 0) < 0 else "emerald",
         "sub": f"YoY {fmt(q2['employment_yoy'], 2, '%')}"},
        {"label": "A 산단 대비 감소규모", "value": fmt(rec["signals"]["A"], 2, "%"),
         "sub": f"R {fmt(rec['signals']['R'], 2, '%p')} 열위"},
        {"label": "Q3 시간 (반복·지속)",
         "value": ("미확인" if q3["repeated_signal"] is None
                   else ("반복 있음" if q3["repeated_signal"] else "반복 없음")),
         "sub": f"동일 상태 {fmt(q3['state_run_length'])}분기 · {q3['transition'] or '전환 없음'}"},
    ]
    st.html(ui.kpi_cards_html(kpi_cards))
    st.markdown(f"**등록 판정 근거** · {t['stage_reason']}")

    rules = {r["rule_name"]: r for r in snap.reference["triage_rules"]}
    rows = rule_evidence_rows(rec, rules)
    ladder = rules.get("ladder", {})
    footnote = f"규칙: {ladder.get('definition', '')} · 경계값은 프로젝트 운영규칙이며 법정 기준 또는 최적값이 아닙니다."
    if t.get("scale_flag"):
        footnote += f" · {t['scale_flag']}"
    if t.get("data_quality_minimum_only"):
        footnote += " · 확인 가능한 신호에 따른 최소판정"
    st.html(ui.rule_table_html(rows, footnote))

    st.html(ui.fact_caveat_html(fact_items(rec), caveat_items(rec, provenance, snap.reference.get("scope"))))

    st.markdown(f"**{ind} 분기별 판정 추이**")
    timeline_chips(ind, q)
    box = lazy_expander("최근 6분기 근거값 표", "exp_recent_six")
    with box:
        if box.open:
            st.dataframe(pd.DataFrame([{
                "분기": h["quarter"], "Q1 상태": h["q1"]["state_label"], "Triage": h["triage"]["stage"],
                "E": fmt(h["signals"]["E"], 2), "R": fmt(h["signals"]["R"], 2), "A": fmt(h["signals"]["A"], 2),
                "P": fmt(h["signals"]["P"], 2), "고용 증감(명)": h["q2"]["emp_delta"],
                "상태 지속(분기)": h["q3"]["state_run_length"],
            } for h in snap.history(ind, q)]), hide_index=True, width="stretch")

    postings = (f"목록 {jobs['posting_count']:,}건" if jobs.get("posting_count") is not None else "공고 없음")
    with st.expander(f"고용24 채용시장 스냅샷 · Recruitment Layer — {postings} · 조회 시점 기준, 선택 분기와 무관",
                     expanded=(q == latest_quarter)):
        recruitment_view(jobs, report_payload["recruitment_keywords"]["keywords"], q == latest_quarter)

    st.markdown("### 현장 확인 체크리스트")
    with st.container(key="fieldcheck"):
        field_questions_view(ind, q, field_questions)

    st.markdown("### 기존 지원체계 검토 경로")
    handoff_view(rec, report_payload)

    st.markdown("### 담당자 검토")
    reviewer_section(ind, q, rec, t)

    with st.expander("보조 근거 상세 · 분석 담당자용"):
        aux_evidence_view(rec, q)


@st.cache_data(ttl=300, max_entries=64, show_spinner=False)
def diagnosis_base(snapshot_key: tuple[str, str], quarter: str, industry: str,
                   _service: DecisionSupportService) -> dict:
    """세션 입력 없는 진단 payload. 키: 분석본(분기·버전)·분기·업종.

    앱 계층은 원천 파일을 직접 보지 않으므로(Snapshot·backend만 사용) Work24 layer 갱신은 TTL(5분) 안에
    반영된다. 정책 색인 재구축 시 page_policy가 비운다. 현장 입력은 with_session_context()로 매번 얹는다.
    """
    return _service.report_payload(quarter, industry)


def page_diagnosis():
    industries, quarters = snap.industries, snap.quarters[::-1]
    latest_quarter = snap.quarters[-1]
    latest_recs = snap.by_quarter(latest_quarter)

    if "dx_quarter" not in st.session_state:
        st.session_state.dx_quarter = latest_quarter
    if "dx_industry" not in st.session_state:
        priority = sorted([r for r in latest_recs if r["triage"]["stage"] == "우선점검"],
                          key=lambda r: r["triage"]["rank_in_stage"])
        st.session_state.dx_industry = priority[0]["industry"] if priority else industries[0]

    ind, q = st.session_state.dx_industry, st.session_state.dx_quarter
    rec = snap.get(ind, q)
    # 세션과 무관한 backend payload(분석본·업종·분기·Work24 layer 판본 기준)는 캐시하고,
    # 현장 입력(세션)은 매 실행 새로 얹는다 — 체크 직후 진단서·Copilot이 이전 값을 쓰지 않게.
    base = (diagnosis_base((snap.quarter, snap.version), q, ind, decision_support)
            if rec else None)
    jobs = base["recruitment_snapshot"] if base else None
    field_questions = base["field_checks"]["questions"] if base else []
    sync_field_store(ind, q, field_questions)
    current_field_context = field_context_for(ind, q, field_questions) if rec else {"responses": [], "note": None}
    report_payload = (with_session_context(base, current_field_context, datetime.now(timezone.utc).isoformat())
                      if base else None)

    if report_payload is not None:
        with header_doc_slot:
            if st.button("진단서 출력", key="header_report", help="1페이지 진단카드(요약)를 엽니다."):
                report_dialog(report_payload)
            st.download_button("JSON 다운로드", report_download(report_payload), key="header_download",
                               file_name=f"diagnosis_{ind}_{q}.json", mime="application/json",
                               help="현재 백엔드가 제공하는 진단 payload(JSON). PDF 생성은 지원하지 않습니다.")

    with st.container(key="shell", horizontal=True, gap="small"):
        with st.container(key="leftpanel", width=310):
            left_panel(industries, quarters, latest_quarter, ind, q, rec, report_payload)
        with st.container(key="center", width="stretch"):
            if rec is None:
                st.warning("이 분석 버전에 해당 업종·분기 자료가 없습니다.")
            else:
                center_card(ind, q, rec, latest_quarter, jobs, field_questions, current_field_context,
                           report_payload)
        with st.container(key="copilot", width=380):
            if rec is not None:
                copilot_view(ind, q, current_field_context, rec["triage"]["stage"], industries)


# ------------------------------------------------------------------ 점검 건
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
    return f"{sc['quarter']} {sc['review_kind']}"


def referral_view(r: dict, closed: bool, scope_label: str):
    with st.container(border=True):
        st.badge(r["status"], color=REFERRAL_COLOR.get(r["status"], "gray"))
        st.markdown(f"**#{r['id']} {C.label(r['function_tag'])} → {r['institution']}** · {scope_label}에서 작성")
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
        "번호": c["id"], "업종": c["industry"], "개설 분기": c["quarter"], "개설 경로": c["origin"],
        "담당자": c["assignee"], "상태": c["status"], "현재 결정": c["decision"] or "—",
        "다음 검토": c["next_review_quarter"] or "—",
        "개설 분석본": f"{c['snapshot_quarter']} {c['snapshot_version']} ({NATURE_LABEL[c['snapshot_nature']]})",
        "시연": "시연" if c["is_example"] else "",
    } for c in cases])


def ext_compact(rec: dict) -> list[str]:
    sources = rec.get("external_sources")
    if sources is None:
        return ["이 분석본에는 분기별 외부자료가 없습니다."]
    return [f"{s['label']} · {s['source_period'] if s['available'] else s['unavailable_label']}"
            + (f" ({s['role']})" if s["available"] else "") for s in sources if not s.get("quality_only")]


def point_view(title: str, rec: dict, snap_label: str):
    t, q1, q2, q3 = rec["triage"], rec["q1"], rec["q2"], rec["q3"]
    st.markdown(f"**{title}**")
    stage_badge(t["stage"], f"Triage {t['stage']}")
    st.caption(f"분석본 {snap_label}")
    st.markdown(f"- Q1 상태: {q1['state']} ({q1['state_label']})\n"
                f"- Q2 규모: 고용 {fmt(q2['employment'], suffix='명')} · 증감 {fmt(q2['emp_delta'], suffix='명')} · "
                f"비중 {fmt(q2['employment_share_pct'], 2, '%')} · 순감소 기여율 {fmt(q2['contribution_pct'], 2, '%')}\n"
                f"- Q3 시간: 상태 {fmt(q3['state_run_length'])}분기 지속 · 반복 고용진입신호 {fmt(q3['repeated_signal'])}")
    with st.expander(f"외부자료 ({rec['quarter']} 기준)"):
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
    st.markdown(f"**{d['old']} ↔ {d['new']}** · **{d['verdict']}**")
    st.caption(f"{d['review_threshold_label']} (자동 재검토 표시 비활성) — 차이를 계산해 보여주기만 하며, "
               "재검토 표시를 자동으로 붙이지 않습니다.")
    with st.container(border=True):
        st.markdown("**분석 판정값 (CORE)** · 생산·고용·Q1~Q3·E/R/A/P·Triage·판정 사유·자료품질")
        if d["core_changes"] or d["core_meta_changed"] or d["records_only_in_old"] or d["records_only_in_new"]:
            st.markdown(f"변경된 업종×분기 {len(d['core_changed_records'])}건")
            if d["core_changes"]:
                st.dataframe(pd.DataFrame([{"업종": c["industry"], "분기": c["quarter"], "항목": c["label"],
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
        st.caption(f"이 점검 건({key[0]} {key[1]}): CORE 변경 {len(rd['core_changes'])}건 · "
                   f"부가정보 변경 {len(rd['aux_changes']) + len(rd.get('aux_fields_added', []))}건")


def result_line(item: dict) -> str:
    r = item["latest"]
    q = item["question_text"] if len(item["question_text"]) <= 70 else item["question_text"][:70] + "…"
    if r is None:
        return f"{item['position'] + 1}. {q} → 미실시"
    performed = f"실제 확인 {ts(r['performed_at'])} KST" if r["performed_at"] else "실제 확인 일시 미입력"
    more = f" · 이전 기록 {len(item['history']) - 1}건" if len(item["history"]) > 1 else ""
    return (f"{item['position'] + 1}. {q} → **{r['result_code']}** ({r['method']}) · {performed} · "
            f"기록 {ts(r['recorded_at'])} KST ({r['recorded_by']}){more}" + (f" — {r['note']}" if r["note"] else ""))


def scope_header(sc: dict, case: dict):
    st.markdown(f"#### {scope_title(sc)} · {sc['review_status']}")
    nature_badge(sc["snapshot_quarter"], sc["quarter"], case["is_example"])
    st.caption(f"사용 분석본 {sc['snapshot_quarter']} {sc['snapshot_version']} · 시작 {ts(sc['started_at'])} KST ({sc['reviewer']})"
               + (f" · 완료 {ts(sc['reviewed_at'])} KST" if sc["reviewed_at"] else ""))
    if sc["review_kind"] == "재점검":
        st.markdown(f"단계 이동: **{sc['previous_quarter']} {sc['previous_stage']} → {sc['quarter']} {sc['current_stage']}**")
        st.caption("단계 이동은 분석본 값을 그대로 옮긴 사실입니다. 그 의미는 담당자가 판단합니다.")
    else:
        st.markdown(f"이 시점 Triage: **{sc['current_stage']}**")


def scope_record_view(sc: dict, case: dict):
    """한 점검 시점의 기록(읽기 전용). 이전 시점의 기록은 수정할 수 없다."""
    rec = snapshot(sc["snapshot_quarter"], sc["snapshot_version"]).get(case["industry"], sc["quarter"])
    point_view(f"이 시점 분석값 · {sc['quarter']}", rec, f"{sc['snapshot_quarter']} {sc['snapshot_version']}")
    done = [i for i in sc["checks"] if i["latest"]]
    st.markdown(f"**현장확인 결과** {len(done)}/{len(sc['checks'])}건")
    for item in done:
        st.caption("- " + result_line(item))
    st.markdown("**현장 메모** " + ("" if sc["notes"] else "—"))
    for n in sc["notes"]:
        st.caption(f"- {n['note']} ({n['recorded_by']}, {ts(n['recorded_at'])} KST)")
    st.markdown("**지원 필요 기능** " + ("" if sc["support_need_history"] else "—"))
    for n in sc["support_need_history"]:
        st.caption(f"- {', '.join(C.label(t) for t in n['function_tags']) or '선택 없음'}"
                   + ("" if n["field_checked"] else " (현장확인 전·참고용)")
                   + f" — {n['note'] or ''} ({n['recorded_by']}, {ts(n['recorded_at'])} KST)")
    st.markdown("**결정** " + ("" if sc["decisions"] else "—"))
    for d in sc["decisions"]:
        st.caption(f"- {d['decision']} · {d['rationale']} · 다음 검토 {d['next_review_quarter'] or '—'} "
                   f"({d['decided_by']}, {ts(d['decided_at'])} KST)")
    st.markdown("**이 시점에서 작성한 인계** " + (", ".join(
        f"#{r['id']} {C.label(r['function_tag'])} → {r['institution']} ({r['status']})" for r in sc["referrals"]) or "—"))


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
        st.markdown(f"**이번 시점 지원 필요 기능** · {', '.join(C.label(t) for t in chosen) or '선택 없음'}"
                    + ("" if need["field_checked"] else " · _현장확인 전·참고용 선택_"))
        st.caption(f"선택 이유·메모: {need['note'] or '—'} ({need['recorded_by']}, {ts(need['recorded_at'])} KST)")
    else:
        st.caption("이번 시점에 선택된 지원 필요 기능 없음")
    with st.form("support"):
        cols = st.columns(4)
        picked = [f["tag"] for i, f in enumerate(C.functions())
                  if cols[i % 4].checkbox(f["label"], value=f["tag"] in chosen, key=f"fn_{sc['id']}_{f['tag']}")]
        note = st.text_area("선택 이유 또는 메모", value=need["note"] if need and need["note"] else "")
        if st.form_submit_button("지원 필요 기능 저장", disabled=not actor):
            if run(lambda: svc.record_support_needs(actor, cid, picked, note),
                   f"{scope_title(sc)} 지원 필요 기능 선택을 기록했습니다.") is not None:
                st.rerun()
    for tag in chosen:
        with st.container(border=True):
            st.markdown(f"**선택 기능 · {C.label(tag)}**")
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
                                  format_func=C.label, placeholder="지원 기능 선택")
            basis = st.text_input("근거 메모 (선택)")
            if st.form_submit_button("기관 후보 제안", disabled=not actor):
                if run(lambda: svc.propose_institution(actor, name, desc, url, tags, unit, basis),
                       "기관 후보를 제안했습니다(검토 중 — 인계 대상 아님).") is not None:
                    st.rerun()
        for r in svc.institution_registry():
            st.caption(f"- {r['institution']} · {', '.join(C.label(t) for t in r['function_tags'])} · 상태 "
                       f"{ {'proposed': '검토 중(인계 불가)', 'verified': '검증됨', 'rejected': '반려'}[r['status']] } "
                       f"({r['proposed_by']}, {ts(r['proposed_at'])} KST)")

    # ④ 결정
    st.markdown("##### ④ 결정 · 어디로 인계했는가")
    for d in sc["decisions"]:
        st.markdown(f"- **{d['decision']}** · {d['rationale']} · 다음 검토 {d['next_review_quarter'] or '—'} "
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
        nrq = st.text_input("다음 검토 분기 (예: 2026Q3 · 계속 점검·추가확인·모니터링 전환은 필수)",
                            value=case["next_review_quarter"] if (case["next_review_quarter"] or "") > sc["quarter"]
                            else (rec["triage"]["next_review_quarter"] or ""))
        picks = st.multiselect("인계할 곳 (결정이 '인계'일 때만 사용)", targets,
                               format_func=lambda x: f"{C.label(x[0])} → {x[1]}",
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
                                    format_func=lambda x: f"{C.label(x[0])} → {x[1]}")
                if st.form_submit_button("인계 기록 추가", disabled=not actor) and pick:
                    if run(lambda: svc.create_referral(actor, fixed, cid, pick[0], pick[1]),
                           "인계 기록을 작성했습니다.") is not None:
                        st.rerun()


def page_cases():
    st.title("점검 건")
    st.caption("점검 건 = 업종 × 분기 단위 점검 기록(기업 사건이 아님). 최초 점검과 분기 재점검이 한 점검 건에 시점별로 쌓입니다. "
               "개설·현장확인·지원 기능 선택·인계·재점검·종결은 담당자가 직접 합니다.")
    cases = svc.list_cases()
    if not cases:
        st.info("아직 개설된 점검 건이 없습니다. 점검 대기열이나 업종 진단 화면에서 개설하세요.")
        return
    st.dataframe(case_table(cases), hide_index=True, width="stretch")
    ids = [c["id"] for c in cases]
    default = ids.index(st.session_state.get("case_id")) if st.session_state.get("case_id") in ids else 0
    cid = st.selectbox("점검 건 선택", ids, index=default, format_func=lambda i: f"#{i}")
    case = svc.get_case(cid)
    fixed = snapshot(case["snapshot_quarter"], case["snapshot_version"])
    rec = fixed.get(case["industry"], case["quarter"])
    closed = case["status"] == "종결"
    cur = case["current_scope"]

    # ① 왜 이 업종을 확인했는가
    st.subheader("① 왜 이 업종을 확인했는가")
    with st.container(border=True):
        st.badge(f"점검 건 상태: {case['status']}", color=CASE_STATUS_COLOR[case["status"]])
        st.markdown(f"### #{case['id']} {case['industry']} · {case['quarter']} 개설 — {case['status']}"
                    + (" · 시연 기록" if case["is_example"] else ""))
        st.markdown(f"**개설 시 판정 사유** {rec['triage']['stage_reason']}")
        st.markdown(f"**개설 경로** {case['origin']} · **담당자** {case['assignee']} · **개설** {case['opened_by']} {ts(case['opened_at'])} KST")
        st.markdown(f"**개설 사유** {case['opening_reason']}")
        st.caption(f"개설에 사용한 분석본: {case['snapshot_quarter']} {case['snapshot_version']} (고정)")
        nature_badge(case["snapshot_quarter"], case["quarter"], case["is_example"])
        if closed:
            st.info(f"종결: {case['closed_by']} {ts(case['closed_at'])} KST — 종결 사유: {case['closing_note']}")
        elif case["status"] == "모니터링":
            st.info(f"모니터링 중 — 적극 점검은 멈췄고 다음 검토 분기 {case['next_review_quarter']} 재점검 계획이 남아 있습니다.")
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
                    point_view(f"직전 점검 · {cur['previous_quarter']}", prev,
                               f"{cur['previous_snapshot_quarter']} {cur['previous_snapshot_version']}")
                with right, st.container(border=True):
                    point_view(f"이번 시점 · {cur['quarter']}", cur_rec, f"{cur['snapshot_quarter']} {cur['snapshot_version']}")
                st.markdown("**직전 시점 대비 변화** (값의 차이만 표시)")
                st.dataframe(change_table(prev, cur_rec), hide_index=True, width="stretch")
            else:
                point_view(f"이 시점 분석값 · {cur['quarter']}", cur_rec, f"{cur['snapshot_quarter']} {cur['snapshot_version']}")
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
            st.caption(f"{nrq} 분석 자료가 아직 없습니다 — 자료가 등록되면 재점검 예정 목록에 나타납니다.")
        else:
            st.caption(f"{nrq} 재점검에 쓸 분석본: {target.quarter} {target.version} · {nature_note(target.quarter, nrq)}")
            if st.button(f"{nrq} 재점검 시작", disabled=not actor, type="primary"):
                if run(lambda: svc.start_quarterly_review(actor, case["id"], target),
                       f"#{case['id']} {nrq} 재점검을 시작했습니다.") is not None:
                    st.rerun()

    with st.expander("이 점검 건의 변경 기록"):
        st.dataframe(audit_frame(case_logs(cid)), hide_index=True, width="stretch")


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
    st.title("분기 사후검토")
    st.warning(SELECTION_BIAS_NOTE)
    quarter = st.selectbox("기준 분기", svc.operations_quarters(snap)[::-1], index=0, key="ops_quarter")
    o = svc.operations_summary(snap, quarter)
    b = o["basis"]
    st.caption(f"후보 수는 분석본 {o['snapshot']} 기준 · 시연 기록 {o['excluded_example_cases']}건(점검 건 단위, 그 하위 기록 전부)은 "
               "모든 지표에서 제외 · 지표마다 기준 시점이 다릅니다(각 영역 설명 참고).")
    recorded = (o["cases_opened"] + o["scopes"] + o["referrals_created"] + o["cases_closed"]
                + sum(o["occurred_in_quarter"].values()))
    if recorded == 0:
        st.info(f"{quarter}에 해당하는 운영 점검 기록이 아직 없습니다. 아래 기록 지표는 0 또는 '아직 기록 없음'입니다.")
    if quarter not in snap.quarters:
        st.caption(f"{quarter}는 분석본 {o['snapshot']}에 없는 분기입니다 — 후보·개설 지표는 해당 없음"
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
        count_table({C.label(k): v for k, v in o["support_functions"].items()}, "지원 필요 기능", "아직 기록 없음")
        st.markdown(f"**⑩ 결정** · 기준: {b['decisions']}")
        count_table(o["decisions"], "결정", "아직 기록 없음")
    with right:
        st.markdown(f"**⑦·⑧ 인계와 회신** · 기준: {b['referrals']}")
        st.markdown(f"- 이 분기 점검 시점에서 작성한 인계 {o['referrals_created']}건 · 그중 발송이 기록된 인계 {o['referrals_sent']}건")
        st.markdown(f"- 회신이 기록된 인계: {share(o['referral_reply'], '발송 기록된 인계')}")
        st.caption("회신율 분모 = 이 분기 시점에서 작성되고 발송이 기록된 인계(작성만 된 인계 제외), 분자 = 그중 회신이 기록된 인계.")
        st.markdown(f"**발송·접수·회신 발생** · 기준: {b['occurred']}")
        occ, unk = o["occurred_in_quarter"], o["occurred_unknown_all_quarters"]
        st.markdown(f"- {quarter}에 실제로 발생: 발송 {occ['발송']} · 접수 {occ['접수']} · 회신 {occ['회신']}")
        st.caption(f"발생시각 미입력(분기 배정 불가, 전체 기간): 발송 {unk['발송']} · 접수 {unk['접수']} · 회신 {unk['회신']}")
        st.markdown(f"**⑨ 단계 이동** · 기준: {b['stage_moves']} (분석본 단계를 옮긴 사실, 해석 없음)")
        count_table(o["stage_moves"], "단계 이동", "아직 기록 없음")
        st.markdown(f"**점검 건 종결** · 기준: {b['closed']}")
        st.markdown(f"- {quarter}에 종결한 운영 점검 건: {o['cases_closed']}건")


# ------------------------------------------------------------------ 정책 근거
def page_policy():
    st.title("정책 근거 검색")
    st.caption("공식 원문과 팀 제안을 분리해 검색합니다. 결과는 일반 조건 확인용이며 적격·승인·지급을 자동 판정하지 않습니다.")
    with svc.Session() as s:
        chunk_count = s.query(M.SourceEvidence).count()
        cards = s.query(M.RequirementCard).order_by(M.RequirementCard.requirement_id).all()
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

    with st.expander(f"요건 카드 {len(cards)}건"):
        for card in cards:
            st.markdown(f"- **{card.requirement_id}** {card.title or card.program_name} · "
                        f"{card.current_intake_status} / {card.card_status} · {card.caveat or '—'}")


# ------------------------------------------------------------------ 투명성·방법론
def quote(doc: dict, section: str):
    body = doc.get("sections", {}).get(section) if doc.get("available") else None
    if body:
        with st.expander(f"원문 인용 — {doc['path']} · {section}"):
            st.markdown(body)


def page_methodology():
    st.title("투명성·방법론")
    doc = registered_document(snap, "final_methodology")
    if doc.get("available"):
        st.caption(f"방법론 원문: {doc['path']} · 분석본 {snap.quarter} {snap.version} 등록 해시 "
                   + ("일치" if doc["hash_match"] else "불일치 — 문서가 분석본 등록 이후 바뀌었습니다"))
    else:
        st.caption(f"방법론 원문을 찾을 수 없습니다: {doc.get('reason')}")

    with st.container(border=True):
        st.markdown("#### 시스템 목적")
        st.markdown("상태 × 규모 × 시간 진단을 현장확인·기존 지원기능 연결·재점검까지 이어주는 "
                    "Human-in-the-Loop 의사결정 지원체계")
        st.caption(snap.reference.get("scope", ""))
        quote(doc, "최종 채택 구조")

    with st.container(border=True):
        st.markdown("#### 분석 — Q1 상태 · Q2 규모 · Q3 시간 · Triage")
        spec = snap.meta["parameter_spec"]
        st.dataframe(pd.DataFrame(spec["triage_rules"])[["rule_name", "definition", "threshold", "source_category"]]
                     .rename(columns={"rule_name": "규칙", "definition": "정의", "threshold": "경계",
                                      "source_category": "근거 구분"}), hide_index=True, width="stretch")
        st.caption(f"규칙 버전 {spec['triage_rule_version']}")
        quote(doc, "Q1~Q3와 Triage")

    with st.container(border=True):
        st.markdown("#### 선택적 재검토 — ELECTRE/SMAA")
        p = snap.reference["electre_smaa_protocol"]
        st.markdown(f"- 적용 범위: **{p['scope']}**\n"
                    f"- Triage 단계 변경: **{'금지' if p['triage_stage_mutation'] == 'forbidden' else p['triage_stage_mutation']}**\n"
                    f"- ELECTRE 결과 용도: {p['electre_result_use']}\n- SMAA 결과 용도: {p['smaa_result_use']}\n"
                    f"- CAI 해석: {p.get('cai_interpretation', '—')}")
        quote(doc, "ELECTRE 선택적 채택")

    with st.container(border=True):
        st.markdown("#### 외부자료 — 판정 정답 자료가 아님")
        sample = next((r for r in snap.records.values() if r.get("external_sources")), None)
        if sample:
            for role in ("VALIDATION", "CONTEXT"):
                title = ROLE_TITLE[role][0]
                names = [s["label"] for s in sample["external_sources"] if s["role"] == role]
                st.markdown(f"- **{title}** `{role}`: " + ", ".join(names))
        st.caption("외부자료는 Triage·선택적 재검토의 입력이 아니며 판정을 바꾸지 않습니다.")
        quote(doc, "외부데이터 원칙")

    with st.container(border=True):
        st.markdown("#### 사람이 결정하는 지점")
        st.markdown("- 점검 건 개설\n- 현장확인 결과\n- 지원 필요 기능\n- 담당 기관·인계, 발송·접수·회신 기록\n"
                    "- 재점검 판단(계속 점검·추가확인·모니터링 전환·새 인계·종결)\n- 점검 건 종결")
        st.caption("시스템은 위 항목을 자동으로 선택하거나 확정하지 않습니다.")
        quote(doc, "Human Review와 지원연계")

    with st.container(border=True):
        st.markdown("#### 현재 한계")
        cats = sorted({r["source_category"] for r in snap.meta["parameter_spec"]["triage_rules"]})
        unmapped = [f["label"] for f in C.functions() if f["referable"] and not C.institution_candidates(
            f["tag"], snap.reference["institution_routing_map"])]
        jobs = next((s for s in (sample or {}).get("external_sources", []) if s["key"] == "changwon_jobs"), None)
        st.markdown(
            f"- 규칙 시나리오: {S.SCENARIO_STATUS_LABEL[snap.meta['scenario_status']]}\n"
            f"- 경계값 근거 구분: {', '.join(cats)} — 행정 최적값으로 검증된 경계값이 아님\n"
            f"- 현장확인 선택편향: {SELECTION_BIAS_NOTE.split('. ')[0]}.\n"
            f"- 담당기관 미확정 지원 기능: {', '.join(unmapped)}\n"
            f"- 검증된 담당기관 2곳은 기관 기능만 확인 — 실제 접수경로·기관 합의는 미확인\n"
            f"- 지원사업 요건 카드: 공식 원장 {sum(len(svc.requirement_cards(t)) for t in C.function_tags())}건 "
            "— 일반 조건 안내용이며 자동 적격·승인 판정 아님\n"
            f"- 고용24 공개 채용공고: {jobs['unavailable_label'] if jobs else '—'} — 현재 분석기간과 겹치지 않음\n"
            f"- 자동 재검토 표시: 비활성(기준 상태 {THRESHOLD_STATUS}) — 분석본 차이는 표시만 함\n"
            f"- 과거분기 진단: 분석 실행분이 {', '.join(sorted({m['quarter'] for m in metas}))}뿐이므로 그 이전 분기는 "
            "후향 재구성 분석(당시 저장 분석본 없음, 후속 보정자료 반영 가능)\n"
            f"- 인증: {'프로토타입 · 인증 미연결(로컬 이름 입력)' if not RT.authenticated else RT.auth_mode}")
        quote(doc, "상태와 한계")

    with st.container(border=True):
        st.markdown("#### 분석본 버전 비교")
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
        "사용 분석본": f"{a['snapshot_quarter']} {a['snapshot_version']}" if a["snapshot_quarter"] else "—",
    } for a in logs])


def page_audit():
    st.title("변경 기록")
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
    {"점검 대기열": page_queue, "업종 진단": page_diagnosis, "점검 건": page_cases, "분기 사후검토": page_operations,
     "정책 근거": page_policy, "투명성·방법론": page_methodology, "변경 기록": page_audit}[st.session_state.page]()
