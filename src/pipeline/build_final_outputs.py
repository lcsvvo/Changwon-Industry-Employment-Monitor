# -*- coding: utf-8 -*-
"""Build the final decision-support delivery without changing Triage decisions.

Inputs are the canonical Triage and context outputs.  External sources are
classified and exposed as evidence only; this module never recalculates stage.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from electre import build_selective_review  # noqa: E402


OUT = ROOT / "outputs/final_model"
CORE_TABLES = OUT / "01_core/tables"
TRIAGE_TABLES = OUT / "02_triage/tables"
ELECTRE_DIR = OUT / "03_electre_smaa"
ELECTRE_TABLES = ELECTRE_DIR / "tables"
EVIDENCE_DIR = OUT / "04_external_evidence"
HANDOFF_TABLES = OUT / "05_handoff/tables"
REPORT_QA = OUT / "06_report_assets/qa"
DECISION = TRIAGE_TABLES / "triage_panel.csv"
CONTEXT = ROOT / "data/processed/final_model/industry_context_signals.csv"
KEPCO_LEGAL_MONTH = ROOT / "data/processed/kepco/legal_dong_ksic_monthly_panel.csv"
KEPCO_LEGAL_QUARTER = ROOT / "data/processed/kepco/legal_dong_ksic_quarterly_panel.csv"
KEPCO_COVERAGE = EVIDENCE_DIR / "kepco/quality/kicox_coverage.csv"
# Work24 는 canonical normalized 산출물을 읽는다. RAW(data/raw/work24/)는 수집원본·
# provenance 보존용이며 최종 evidence 파이프라인의 분석입력으로 쓰지 않는다.
JOBS = ROOT / "data/processed/work24/work24_analysis_ready.csv"
ELECTRE_SMAA = ROOT / "data/processed/final_model/electre_smaa_check_cases.csv"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_csv(frame: pd.DataFrame, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def data_roles() -> pd.DataFrame:
    rows = [
        ("kicox_production", "KICOX 창원국가산단 업종별 생산", "CORE", "업종별 명목 생산액", "생산 방향·변화율", "실질 생산량이나 가격효과의 원인", "가격효과가 섞이고 일부 공표구간은 보정본", "물량지수 또는 산단 업종별 실질생산 공식통계 확보", "data/processed/kicox/changwon_industry_master.csv", "build_changwon_master → build_kicox_analysis_panel → run_triage_rule"),
        ("kicox_employment", "KICOX 창원국가산단 업종별 고용", "CORE", "산단 입주기업 종사자 수", "고용 증감·비중·기여", "실업·이직·직무 미스매치의 원인", "분기말 집계이며 기업별 분포는 없음", "현행 CORE 유지; 기업별 확인은 Human Review에서 수행", "data/processed/kicox/changwon_industry_master.csv", "build_changwon_master → build_kicox_analysis_panel → run_triage_rule"),
        ("kicox_operation", "KICOX 가동률", "CONTEXT", "산단 가동률", "조업 위축 여부", "생산량·전력량·휴업 원인", "2024Q2 전후 정의 단절 구간 존재", "정의가 일관된 장기 시계열과 산식 확보", "data/processed/kicox/changwon_industry_master.csv", "build_context_layer (Triage 비입력)"),
        ("kicox_firms", "KICOX 입주업체·가동업체", "CONTEXT", "입주·가동 업체 수", "업체 구성·가동상태 변화", "폐업·퇴거·합병 등 개별 사건", "소규모 업종은 비율 변동이 큼", "기업 이벤트 시계열과 산단 경계 식별자 확보", "data/processed/kicox/changwon_industry_master.csv", "build_context_layer (Triage 비입력)"),
        ("ppi", "생산자물가지수(PPI)", "VALIDATION", "전국 품목별 생산자가격", "명목 생산변화의 가격효과 가능성", "창원산단 실질생산량", "전국지수·업종 매핑 A~D 혼재", "산단 품목가중치와 안정된 A/B 매핑 확보", "data/processed/ppi/ppi_validation_panel.csv", "build_context_layer → PPI 조정 부호·경계 비교"),
        ("eis_cci", "EIS 및 창원상의 고용보험 피보험자", "VALIDATION", "창원시 고용보험 피보험자", "KICOX 고용 방향의 제한적 교차확인", "산단 고용 수준·점유율 또는 전체 10업종", "창원시 전역; 업종 비교는 3개 업종·21행", "산단 식별 가능한 10업종 분기 패널 확보", "data/processed/eis/eis_validation_panel.csv", "build_context_layer → employment_crosscheck_panel"),
        ("customs_trade", "관세청 창원시 HS6 수출입", "CONTEXT", "확인된 HS6 품목의 창원시 통관액", "외부수요 방향", "업종 총수출 또는 산단 수출", "창원시 전역·부분 품목·HS→업종 매핑", "전수 HS6 대응표와 산단 귀속 기준 확보", "data/processed/customs/trade_context_panel.csv", "build_context_layer → external questions"),
        ("kepco_business_type", "KEPCO 기존 businessType 전력", "CONTEXT", "창원시/5개 구 전력사용량", "조업활동 보조 방향", "산단 생산량 또는 정확한 KICOX 업종 전력", "비공식 업종분류, 산단 경계 아님, 방향 일치 50~55%", "공식 업종코드·산단 경계·안정된 검증력 확보", "data/processed/kepco/kepco_power_quarterly_panel.csv", "build_context_layer → activity context"),
        ("kepco_legal_dong_ksic", "KEPCO 법정동×KSIC 전력", "CONTEXT", "18개 제조업 집적 법정동의 공개 셀 전력", "공간·업종별 조업 맥락", "산단 또는 업종 전체 전력사용량", "2022-04~2026-03, 비식별 40.47%, 업종합계 COMPLETE 0, 2026Q2 없음", "공식 산단 경계, 비식별 해소, 완전분기와 최신분기 확보", "data/processed/kepco/legal_dong_ksic_quarterly_panel.csv", "final external evidence: 품질정보만; 공개 셀 합계 미사용"),
        ("changwon_jobs", "고용24 창원·마산 고용복지+센터 공개 채용정보(Work24 canonical)", "CONTEXT", "수집시점에 게시 중이던 공개 채용공고(창원시 5개 구 2,045건, 2026-09-19 단면)", "판정 이후 해당 업종에서 어떤 기업이 어떤 직무를 공개채용 중인지 확인하는 단서", "고용 증가, 업종별 채용수요 규모, 구인율, 과거 추세, 모집인원", "등록일 2026-07-21~09-18 의 2026Q3 단일분기로 모형 최종시점 2026Q2 와 overlap 0; recruitment_count 0%; KICOX 매핑 663/2,045(기업매칭 성립분에 한정); 구별 기업매칭률 14.4~43.2% 선택편향; 산업단지 MATCH 0(POSSIBLE 은 소재 확정 아님); 60일 롤링 게시창에 따른 생존편향", "반복 snapshot 누적으로 업종×분기 패널을 만들고 모집인원·직종코드를 공식 경로로 확보", "data/processed/work24/work24_analysis_ready.csv", "post-period corroboration / follow-up evidence / field-check support; Triage 정량 입력 아님, 업종 점수 산출·자동 승격/하향 미사용"),
        ("kosis_labor_flow", "KOSIS 사업체노동력조사 입직·이직·빈일자리", "CONTEXT", "창원시 제조업 총계 반기 노동이동", "채용둔화·이직증가의 지역 배경", "KICOX 업종별 고용 증감", "표본조사·반기·제조업 총계", "시군구×산업중분류 월별 행정통계 확보", "data/processed/employment_insurance/employment_flow_panel.csv", "build_context_layer → flow questions"),
        ("ecos_bsi", "한국은행 경남·전국 업종 BSI", "CONTEXT", "경남 제조업 및 전국 업종 심리", "지역·전국 경기 배경", "창원산단 업종의 실적", "경남은 업종 없음, 업종은 전국; 행 단위 변별력 낮음", "창원 또는 산단×업종 BSI와 실적 검증 확보", "data/processed/ecos/business_sentiment_panel.csv", "build_context_layer → sentiment questions"),
        ("factory_registry", "창원시 공장등록현황", "CONTEXT", "창원시 공장 단일시점 구성", "법정동 제조업 집적 proxy", "업체수 증감·산단 기업 변동", "2024-12-31 단일시점, 산단 내외 미분리", "동일 정의 시계열과 산단 경계 식별 확보", "data/raw/changwon_factory_registry", "KEPCO 18개 법정동 proxy 정의"),
        ("kepco_customer_change", "KEPCO 전기사용고객 증감", "EXCLUDE", "공식 화면상 신설·증설·해지 값", "현재 없음", "고객수·계약건수", "공식 화면의 건수/KWH 정의 충돌 및 비정상 값", "공식 산식·단위·모집단 문서 확보", "data/processed/kepco/kepco_custnum_change_quarterly.csv", "원값 보존; 최종 evidence 미사용"),
        ("other_unavailable", "고용유지지원금·워크넷 집계·기타 미확보 후보", "EXCLUDE", "현재 직접 측정값 없음", "현재 없음", "업종 위험 또는 지원효과", "공개 통계 부재·API 명세/과거 패널 미확보", "공식 지역×업종×기간 패널과 정의 확보", "data/processed/final_model/reference/external_data_inventory.csv", "탐색·제외 근거만 보존"),
    ]
    columns = ["dataset_id", "dataset", "role", "direct_measure", "indirect_signal", "cannot_claim", "limitations", "promotion_condition", "input_path", "code_reference"]
    result = pd.DataFrame(rows, columns=columns)
    result["exists"] = result["input_path"].map(lambda p: (ROOT / p).exists())
    return result


def core_panel(decision: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "industry", "quarter", "production", "employment", "production_yoy",
        "employment_yoy", "emp_delta", "employment_share_pct", "contribution_pct",
        "state", "run_length", "transition_type", "previous_state",
        "production_yoy_valid", "employment_yoy_valid", "data_quality_core_missing",
    ]
    return decision[columns].sort_values(["quarter", "industry"]).reset_index(drop=True)


def jobs_summary(jobs: pd.DataFrame) -> pd.DataFrame:
    summary = jobs.groupby("gu", dropna=False).size().rename("posting_count").reset_index()
    summary = summary.rename(columns={"gu": "region"})
    all_row = pd.DataFrame({"region": ["전체"], "posting_count": [len(jobs)]})
    result = pd.concat([all_row, summary], ignore_index=True)
    result["unique_posting_count"] = jobs["wanted_auth_no"].nunique()
    result["registration_date_min"] = jobs["reg_date"].min()
    result["registration_date_max"] = jobs["reg_date"].max()
    result["role"] = "CONTEXT"
    result["industry_signal_usable"] = False
    result["interpretation"] = (
        "현재 공개공고 조회용; 공고 수를 고용 증가·모집인원·채용수요 규모로 해석하지 않음. "
        "구별 기업매칭률 격차(14.4~43.2%)가 있어 지역 간 공고 수 비교도 하지 않음"
    )
    return result


def external_evidence(context: pd.DataFrame, decision: pd.DataFrame, jobs: pd.DataFrame, legal_month: pd.DataFrame, legal_coverage: pd.DataFrame) -> pd.DataFrame:
    latest_q = decision["quarter"].max()
    latest = context.loc[context["quarter"].eq(latest_q)].copy()
    keep = [
        "industry", "quarter", "stage", "signal_profile", "nominal_production_yoy",
        "ppi_mapping_grade", "ppi_adjusted_production_yoy", "ppi_adjusted_low", "ppi_adjusted_high",
        "industry_direction", "mapping_confidence", "trade_export_yoy", "trade_mapping_grade",
        "trade_coverage_status", "power_usage_yoy", "power_scope", "bsi_region_business",
        "bsi_industry_business", "mfg_flow_period", "mfg_flow_job_openings",
        "check_questions_context", "handoff_review_functions",
    ]
    keep = [c for c in keep if c in latest.columns]
    evidence = latest[keep].copy()

    suppression = pd.to_numeric(legal_month["suppression_flag"], errors="coerce")
    period = legal_month["period"].astype(str)
    evidence["kepco_legal_dong_role"] = "CONTEXT"
    evidence["kepco_legal_dong_observation_period"] = f"{period.min()}~{period.max()}"
    evidence["kepco_legal_dong_suppression_pct_all"] = round(float(suppression.mean() * 100), 4)
    evidence["kepco_legal_dong_complete_industry_quarters"] = 0
    evidence["kepco_legal_dong_2026q2_available"] = False
    evidence["kepco_legal_dong_note"] = "18개 제조업 집적 법정동 proxy; 산단 경계 아님. 비식별 셀을 0·대체·추정하지 않으며 공개 셀 합계를 업종 전체로 해석하지 않음"
    coverage = legal_coverage.rename(columns={
        "kicox_industry": "industry",
        "mapping_grade": "kepco_legal_mapping_grade",
        "ksic_mid_codes": "kepco_legal_ksic_codes",
        "suppression_rate": "kepco_legal_industry_suppression_rate",
        "proxy_legal_dong_coverage_label": "kepco_legal_proxy_dong_coverage",
        "first_observed_month": "kepco_legal_first_month",
        "last_observed_month": "kepco_legal_last_month",
        "complete_quarter_count": "kepco_legal_complete_quarter_count",
        "available_2026Q2": "kepco_legal_available_2026q2_by_industry",
    })
    coverage_cols = [
        "industry", "kepco_legal_mapping_grade", "kepco_legal_ksic_codes",
        "kepco_legal_industry_suppression_rate", "kepco_legal_proxy_dong_coverage",
        "kepco_legal_first_month", "kepco_legal_last_month",
        "kepco_legal_complete_quarter_count", "kepco_legal_available_2026q2_by_industry",
    ]
    evidence = evidence.merge(coverage[coverage_cols], on="industry", how="left", validate="one_to_one")

    evidence["jobs_role"] = "CONTEXT"
    evidence["jobs_snapshot_postings_all_industries"] = len(jobs)
    evidence["jobs_registration_period"] = f"{jobs['reg_date'].min()}~{jobs['reg_date'].max()}"
    evidence["jobs_industry_signal_usable"] = False
    evidence["jobs_note"] = ("2026Q3 단일분기(모형 최종시점 2026Q2 와 overlap 0)이고 모집인원이 없어 업종별 수치 신호로 사용하지 않음; 판정 이후 기업·공고 확인용(post-period corroboration)")
    return evidence.sort_values("industry").reset_index(drop=True)


def explanation_trace(decision: pd.DataFrame, evidence: pd.DataFrame) -> pd.DataFrame:
    latest_q = decision["quarter"].max()
    latest = decision.loc[decision["quarter"].eq(latest_q)].copy()
    base_cols = [
        "industry", "quarter", "decision_stage", "decision_reason", "q1_state_label",
        "q1_question_route", "q2_employment_delta", "q2_employment_yoy",
        "q2_employment_share", "q2_contribution", "q3_state_run_length",
        "q3_transition", "q3_repeated_signal", "signal_e", "signal_r", "signal_a",
        "signal_p", "check_question", "first_owner", "next_review_quarter",
    ]
    trace = latest[base_cols].rename(columns={"decision_stage": "stage", "decision_reason": "stage_reason"})
    extra = evidence[["industry", "signal_profile", "check_questions_context", "handoff_review_functions", "kepco_legal_dong_note", "jobs_note"]]
    trace = trace.merge(extra, on="industry", how="left", validate="one_to_one")
    trace["model_path"] = "CORE→Q1→Q2→Q3→Triage→[추가확인만 ELECTRE/SMAA]→External Evidence→Human Review→Routing"
    trace["electre_used"] = trace["stage"].eq("추가확인")
    trace["human_decision_required"] = True
    trace["routing_disclaimer"] = "검토 기능 제안이며 특정 사업·예산·지원대상 선정이 아님"
    order = {"우선점검": 0, "추가확인": 1, "관찰": 2}
    return trace.assign(_order=trace["stage"].map(order)).sort_values(["_order", "industry"]).drop(columns="_order")


def boundary_review(decision: pd.DataFrame, context: pd.DataFrame, electre: pd.DataFrame, smaa: pd.DataFrame) -> pd.DataFrame:
    """Second-look panel for Triage '추가확인' only.

    ELECTRE/SMAA do not overwrite Triage.  They order and explain the manual
    review queue, including disagreement and parameter sensitivity.
    """
    selected = decision.loc[decision["stage"].eq("추가확인"), [
        "industry", "quarter", "stage_reason", "emp_delta", "E", "P"
    ]].copy()
    if len(selected) != 35:
        raise AssertionError(f"Expected 35 Triage additional-check rows, got {len(selected)}")
    scols = [
        "industry", "quarter", "cai_observe", "cai_check", "cai_priority",
        "cai_undetermined", "necessary_stage", "possible_stages", "n_possible",
        "is_discriminating", "prereg_status", "phase", "d_stage",
    ]
    selected = selected.merge(smaa[scols], on=["industry", "quarter"], how="left", validate="one_to_one")
    selected = selected.merge(electre[["industry", "quarter", "g4"]], on=["industry", "quarter"], how="left", validate="one_to_one")
    selected["g1"] = (-pd.to_numeric(selected["emp_delta"], errors="coerce")).clip(lower=0)
    selected["g2"] = pd.to_numeric(selected["E"], errors="coerce")
    selected["g3"] = pd.to_numeric(selected["P"], errors="coerce")
    selected["electre_stage"] = selected["d_stage"]
    selected["electre_specification"] = "D_small_indifference (same archived run as compatible CAI)"
    selected["triage_stage_preserved"] = "추가확인"
    selected["boundary_action"] = selected["electre_stage"].map({
        "UNDETERMINED": "자료·모형 불확실성 우선 확인",
        "OBSERVE": "Triage-ELECTRE 불일치 확인(관찰로 자동 하향하지 않음)",
        "CHECK": "추가확인 유지",
        "PRIORITY": "추가확인군 내 우선 검토(우선점검으로 자동 승격하지 않음)",
    })
    selected["smaa_parameter_sensitive"] = pd.to_numeric(selected["n_possible"], errors="coerce").gt(1)
    selected["smaa_note"] = "CAI는 명시한 호환 파라미터 표집에서의 배정 비중이며 위기확률·정답률이 아님"
    selected["review_queue_group"] = "6 추가확인"
    selected.loc[selected["electre_stage"].eq("UNDETERMINED"), "review_queue_group"] = "1 자료·모형 불확실 확인"
    selected.loc[selected["electre_stage"].eq("OBSERVE"), "review_queue_group"] = "2 Triage-ELECTRE 불일치 확인"
    selected.loc[selected["electre_stage"].eq("PRIORITY") & selected["smaa_parameter_sensitive"], "review_queue_group"] = "3 파라미터 민감 우선검토 후보"
    selected.loc[selected["electre_stage"].eq("PRIORITY") & ~selected["smaa_parameter_sensitive"], "review_queue_group"] = "4 안정 우선검토 후보"
    selected.loc[selected["electre_stage"].eq("CHECK") & selected["smaa_parameter_sensitive"], "review_queue_group"] = "5 파라미터 민감 추가확인"
    ccols = [
        "industry", "quarter", "ppi_mapping_grade", "ppi_adjusted_production_yoy",
        "cross_source_available", "trade_data_available", "power_data_available",
        "bsi_data_available", "mfg_flow_data_available", "check_questions_context",
        "handoff_review_functions",
    ]
    selected = selected.merge(context[ccols], on=["industry", "quarter"], how="left", validate="one_to_one")
    selected["external_data_used_as_electre_criterion"] = False
    selected["external_evidence_role"] = "ELECTRE 이후 해석·교차확인; 판정 가중치나 veto로 사용하지 않음"
    keep = [
        "industry", "quarter", "triage_stage_preserved", "stage_reason", "g1", "g2", "g3", "g4",
        "electre_stage", "electre_specification", "boundary_action", "review_queue_group", "cai_observe", "cai_check", "cai_priority",
        "cai_undetermined", "necessary_stage", "possible_stages", "n_possible",
        "smaa_parameter_sensitive", "smaa_note", "prereg_status", "ppi_mapping_grade",
        "ppi_adjusted_production_yoy", "cross_source_available", "trade_data_available",
        "power_data_available", "bsi_data_available", "mfg_flow_data_available",
        "external_data_used_as_electre_criterion", "external_evidence_role",
        "check_questions_context", "handoff_review_functions",
    ]
    return selected[keep].sort_values(["review_queue_group", "quarter", "industry"]).reset_index(drop=True)


def qa(decision: pd.DataFrame, context: pd.DataFrame, roles: pd.DataFrame, evidence: pd.DataFrame, boundary: pd.DataFrame, jobs: pd.DataFrame, legal_month: pd.DataFrame, legal_quarter: pd.DataFrame, legal_coverage: pd.DataFrame) -> dict:
    stages = decision["stage"].value_counts().to_dict()
    period = legal_month["period"].astype(str)
    checks = {
        "decision_rows_180": len(decision) == 180,
        "decision_unique_industry_quarter": not decision.duplicated(["industry", "quarter"]).any(),
        "context_rows_180": len(context) == 180,
        "stage_unchanged_after_context": decision[["industry", "quarter", "stage"]].sort_values(["industry", "quarter"]).reset_index(drop=True).equals(context[["industry", "quarter", "stage"]].sort_values(["industry", "quarter"]).reset_index(drop=True)),
        "latest_industries_10": len(evidence) == 10 and evidence["industry"].nunique() == 10,
        "roles_only_four_allowed": set(roles["role"]) <= {"CORE", "VALIDATION", "CONTEXT", "EXCLUDE"},
        "required_series_classified": roles["dataset_id"].nunique() == len(roles) and len(roles) >= 14,
        "kepco_legal_month_rows_41508": len(legal_month) == 41508,
        "kepco_legal_quarter_rows_13869": len(legal_quarter) == 13869,
        "kepco_legal_period_2022_04_to_2026_03": period.min() == "2022-04" and period.max() == "2026-03",
        "kepco_legal_suppression_about_40_47pct": abs(pd.to_numeric(legal_month["suppression_flag"], errors="coerce").mean() - 0.404717) < 0.0001,
        "kepco_legal_no_2026q2": not legal_quarter["period"].astype(str).eq("2026Q2").any(),
        "kepco_legal_all_10_industries_profiled": len(legal_coverage) == 10 and legal_coverage["kicox_industry"].nunique() == 10,
        "kepco_legal_no_complete_industry_quarter": pd.to_numeric(legal_coverage["complete_quarter_count"], errors="coerce").eq(0).all(),
        "kepco_industry_quality_join_complete": evidence["kepco_legal_mapping_grade"].notna().all(),
        "kepco_legal_no_imputation": pd.to_numeric(legal_month.loc[pd.to_numeric(legal_month["suppression_flag"], errors="coerce").eq(1), "power_usage"], errors="coerce").isna().all(),
        "jobs_rows_canonical_2045": len(jobs) == 2045,
        "jobs_single_quarter_no_model_overlap": set(pd.to_datetime(jobs["reg_date"]).dt.to_period("Q").astype(str)) == {"2026Q3"},
        "jobs_recruitment_count_absent": jobs["recruitment_count"].isna().all(),
        "jobs_industrial_complex_no_match": "MATCH" not in set(jobs["industrial_complex_match_status"]),
        "jobs_ids_unique": jobs["wanted_auth_no"].nunique() == len(jobs),
        "jobs_not_used_as_industry_signal": evidence["jobs_industry_signal_usable"].eq(False).all(),
        "selective_electre_rows_equal_triage_additional_check": len(boundary) == int(decision["stage"].eq("추가확인").sum()) == 35,
        "selective_electre_does_not_overwrite_triage": boundary["triage_stage_preserved"].eq("추가확인").all(),
        "external_data_not_used_as_electre_criteria": boundary["external_data_used_as_electre_criterion"].eq(False).all(),
    }
    checks = {name: bool(passed) for name, passed in checks.items()}
    if not all(checks.values()):
        failed = [name for name, passed in checks.items() if not passed]
        raise AssertionError(f"Final-delivery QA failed: {failed}")
    return {
        "status": "READY_FOR_REPORT",
        "checks": checks,
        "decision_panel_sha256": sha256(DECISION),
        "stage_counts": stages,
        "latest_quarter": decision["quarter"].max(),
        "electre_adopted": "SELECTIVE_ADVISORY",
        "electre_scope": "Triage 추가확인 35행에만 적용; 원 Triage 단계 불변",
        "electre_reason": "전체 재분류의 중복을 피하면서 경계사례의 다기준 배정과 파라미터 민감도를 담당자에게 제시한다. ELECTRE OBSERVE도 추가확인을 자동 하향하지 않는다.",
        "electre_stage_counts": boundary["electre_stage"].value_counts().to_dict(),
        "smaa_parameter_sensitive_rows": int(boundary["smaa_parameter_sensitive"].sum()),
        "known_limitations": [
            "Triage thresholds are transparent operating rules, not validated policy cutoffs.",
            "KICOX production is nominal and PPI mapping is incomplete.",
            "External sources differ in geography, population, frequency, and industry mapping.",
            "KEPCO legal-dong×KSIC has 40.47% suppression, no complete industry quarter, and no 2026Q2.",
            "Recruiting data is a current posting snapshot without industry codes or a historical denominator.",
        ],
    }


def main() -> None:
    decision = pd.read_csv(DECISION)
    context = pd.read_csv(CONTEXT)
    legal_month = pd.read_csv(KEPCO_LEGAL_MONTH)
    legal_quarter = pd.read_csv(KEPCO_LEGAL_QUARTER)
    legal_coverage = pd.read_csv(KEPCO_COVERAGE)
    jobs = pd.read_csv(JOBS)
    electre_smaa = pd.read_csv(ELECTRE_SMAA)

    roles = data_roles()
    core = core_panel(decision)
    evidence = external_evidence(context, decision, jobs, legal_month, legal_coverage)
    trace = explanation_trace(decision, evidence)
    boundary = build_selective_review(decision, context, electre_smaa)
    latest = decision.loc[decision["quarter"].eq(decision["quarter"].max())].copy()
    latest = latest.sort_values(["stage", "rank_in_stage"])

    save_csv(roles, EVIDENCE_DIR / "data_role_table.csv")
    save_csv(core, CORE_TABLES / "core_panel.csv")
    save_csv(latest, TRIAGE_TABLES / "triage_latest.csv")
    save_csv(evidence, EVIDENCE_DIR / "external_evidence_summary.csv")
    save_csv(trace, HANDOFF_TABLES / "explanation_trace.csv")
    save_csv(boundary, ELECTRE_TABLES / "electre_smaa_review_cases.csv")
    boundary_summary = (
        boundary.groupby(["review_queue_group", "electre_stage", "smaa_parameter_sensitive"], dropna=False)
        .size().rename("case_count").reset_index()
    )
    save_csv(boundary_summary, ELECTRE_TABLES / "electre_smaa_summary.csv")
    save_csv(
        jobs_summary(jobs),
        EVIDENCE_DIR / "employment_center/recruiting_snapshot_summary.csv",
    )

    deliverables = pd.DataFrame([
        (1, "최종 데이터 역할표", "outputs/final_model/04_external_evidence/data_role_table.csv"),
        (2, "최종 core panel", "outputs/final_model/01_core/tables/core_panel.csv"),
        (3, "최종 decision panel", "outputs/final_model/02_triage/tables/triage_panel.csv"),
        (4, "최종 Triage", "outputs/final_model/02_triage/tables/triage_latest.csv"),
        (5, "선택적 ELECTRE/SMAA", "outputs/final_model/03_electre_smaa/tables/electre_smaa_review_cases.csv"),
        (6, "External Evidence panel", "outputs/final_model/04_external_evidence/external_evidence_summary.csv"),
        (7, "업종별 explanation trace", "outputs/final_model/05_handoff/tables/explanation_trace.csv"),
        (8, "Human Review / Handoff", "outputs/final_model/05_handoff/tables/institution_routing_map.csv"),
        (9, "최종모형 구조도", "reports/final_methodology.md"),
        (10, "최종 방법론", "reports/final_methodology.md"),
        (11, "QA 결과", "outputs/final_model/qa_summary.json"),
        (12, "최종 실행방법", "outputs/final_model/RUNBOOK.md"),
    ], columns=["number", "deliverable", "path"])
    save_csv(deliverables, OUT / "deliverables_index.csv")

    report = qa(decision, context, roles, evidence, boundary, jobs, legal_month, legal_quarter, legal_coverage)
    OUT.mkdir(parents=True, exist_ok=True)
    protocol = {
        "version": "1.0",
        "scope": "Triage 추가확인 사례만",
        "triage_stage_mutation": "forbidden",
        "electre_result_use": "추가확인군 내부 검토순서·불일치 표시",
        "smaa_result_use": "호환 파라미터 표집에서의 배정 민감도 표시",
        "external_data_as_criteria": False,
        "no_retuning": True,
        "electre_specification": "D_small_indifference",
        "electre_assignment_source": str(ELECTRE_SMAA.relative_to(ROOT)) + ":electre_stage",
        "electre_assignment_source_sha256": sha256(ELECTRE_SMAA),
        "g4_auxiliary_source": str(ELECTRE_SMAA.relative_to(ROOT)),
        "g4_auxiliary_source_sha256": sha256(ELECTRE_SMAA),
        "smaa_source": str(ELECTRE_SMAA.relative_to(ROOT)),
        "smaa_source_sha256": sha256(ELECTRE_SMAA),
        "cai_interpretation": "위기확률·정답률이 아니라 명시한 호환 파라미터 표집에서의 범주 배정 비중",
    }
    ELECTRE_DIR.mkdir(parents=True, exist_ok=True)
    (ELECTRE_DIR / "electre_smaa_protocol.json").write_text(json.dumps(protocol, ensure_ascii=False, indent=2), encoding="utf-8")
    jobs_meta = {
        "source": str(JOBS.relative_to(ROOT)),
        "sha256": sha256(JOBS),
        "rows": len(jobs),
        "unique_wanted_auth_no": int(jobs["wanted_auth_no"].nunique()),
        "registration_date_min": jobs["reg_date"].min(),
        "registration_date_max": jobs["reg_date"].max(),
        "role": "CONTEXT",
        "industry_signal_usable": False,
        "source_kind": "canonical_normalized",
        "raw_provenance": "data/raw/work24/ (수집원본; 분석입력으로 사용하지 않음)",
        "registration_quarters": sorted(set(pd.to_datetime(jobs["reg_date"]).dt.to_period("Q").astype(str))),
        "recruitment_count_coverage_pct": 0.0,
        "kicox_mapped_rows": int(jobs["kicox_mapping_status"].eq("MAPPED").sum()),
        "usage": "post-period corroboration / follow-up evidence / field-check support",
    }
    jobs_meta_path = EVIDENCE_DIR / "employment_center/recruiting_snapshot_metadata.json"
    jobs_meta_path.parent.mkdir(parents=True, exist_ok=True)
    jobs_meta_path.write_text(json.dumps(jobs_meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "qa_summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": report["status"], "stage_counts": report["stage_counts"], "checks": len(report["checks"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
