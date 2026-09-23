"""Export 계약(Export Contract): 기존 분석 산출물 → Snapshot 필드 매핑.

이 모듈은 '어느 원천 파일의 어느 컬럼을 Snapshot 의 어느 필드로 옮기는가'만 정의한다.
분석 규칙(Q1·Q2·Q3·Triage·E/R/A/P·ELECTRE/SMAA·외부근거·확인질문)은 여기서 계산하지 않는다.
허용 변환: 컬럼 이름 변경, 코드 → 라벨, 타입 변환, 기존 값 결합.
"""
from __future__ import annotations

EXPORT_CONTRACT_VERSION = "dss-export/1.3.0"

# 규칙 시나리오의 승인 상태. 원천에 시나리오 등록·승인 기록이 없으면 draft.
SCENARIO_STATUSES = ("draft", "registered", "approved")
SCENARIO_STATUS_LABEL = {
    "draft": "시나리오 미등록(DRAFT)",
    "registered": "시나리오 등록(승인 전)",
    "approved": "승인된 시나리오",
}

# 원천 산출물. key 는 Snapshot provenance 에서 쓰는 이름, path 는 저장소 루트 기준.
SOURCES = {
    "triage_panel": {
        "path": "outputs/final_model/02_triage/tables/triage_panel.csv",
        "role": "Q1·Q2·Q3·Triage·E/R/A/P·자료품질·확인질문(check_question) 정본 — 180행(10업종×18분기)",
    },
    "triage_distribution_by_quarter": {
        "path": "outputs/final_model/02_triage/tables/triage_distribution_by_quarter.csv",
        "role": "분기별 Triage 단계 분포(대조용)",
    },
    "explanation_trace": {
        "path": "outputs/final_model/05_handoff/tables/explanation_trace.csv",
        "role": "최신분기 판정 설명·확인질문 context·인계검토 기능",
    },
    "handoff_cards_latest": {
        "path": "outputs/final_model/05_handoff/tables/handoff_cards_latest.json",
        "role": "최신분기 인계카드(대조용)",
    },
    "check_questions_context_panel": {
        "path": "outputs/final_model/05_handoff/tables/check_questions_context_panel.csv",
        "role": "분기별 맥락 기반 추가 확인질문(180행) — 외부근거 카드가 아니며 판정을 바꾸지 않음",
    },
    "external_evidence_panel": {
        "path": "outputs/final_model/04_external_evidence/external_evidence_panel.csv",
        "role": "분기별 외부자료 패널(180행) — 해석층이 해당 분기에 정렬한 값 그대로, 판정 입력 아님",
    },
    "data_role_table": {
        "path": "outputs/final_model/04_external_evidence/data_role_table.csv",
        "role": "외부자료 역할 정의(CORE/VALIDATION/CONTEXT/EXCLUDE)",
    },
    "recruiting_snapshot_metadata": {
        "path": "outputs/final_model/04_external_evidence/employment_center/recruiting_snapshot_metadata.json",
        "role": "고용24 공고 단면의 등록 분기·범위",
    },
    "institution_routing_map": {
        "path": "outputs/final_model/05_handoff/tables/institution_routing_map.csv",
        "role": "기관 기능 참고표(검토 기능 제안, 지원대상 선정 아님)",
    },
    "electre_smaa_review_cases": {
        "path": "outputs/final_model/03_electre_smaa/tables/electre_smaa_review_cases.csv",
        "role": "추가확인 사례의 선택적 재검토 정보(ELECTRE/SMAA) — Triage 변경 금지",
    },
    "electre_smaa_protocol": {
        "path": "outputs/final_model/03_electre_smaa/electre_smaa_protocol.json",
        "role": "ELECTRE/SMAA 사용 범위·명세",
    },
    "external_evidence_summary": {
        "path": "outputs/final_model/04_external_evidence/external_evidence_summary.csv",
        "role": "외부근거 요약(원천 분기만)",
    },
    "external_evidence_card_preview": {
        "path": "outputs/final_model/05_handoff/tables/external_evidence_card_preview.csv",
        "role": "외부근거 카드 문구(원천 분기만)",
    },
    "triage_run_metadata": {
        "path": "outputs/final_model/06_report_assets/qa/triage_run_metadata.json",
        "role": "Triage 규칙 버전·임계값·실행 시점",
    },
    "external_evidence_run_metadata": {
        "path": "outputs/final_model/06_report_assets/qa/external_evidence_run_metadata.json",
        "role": "해석층 실행 메타(Triage 불변 선언)",
    },
    "final_result_summary": {
        "path": "reports/final_result_summary.md",
        "role": "최종 결과 요약 문서(참조)",
    },
    "final_methodology": {
        "path": "reports/final_methodology.md",
        "role": "최종 방법론 문서(참조)",
    },
}

KEY = ("industry", "quarter")

# 공식 Triage 단계. ELECTRE 코드(OBSERVE 등)는 여기에 속하지 않는다.
TRIAGE_STAGES = ("우선점검", "추가확인", "관찰")

# 코드 → 라벨 (업무 용어)
CANDIDATE_LABEL = {"우선점검": "우선점검 후보", "추가확인": "검토 후보", "관찰": None}
QUEUE_LABEL = {"우선점검": "우선점검 후보", "추가확인": "추가확인 검토", "관찰": "정기 모니터링(관찰)"}
ELECTRE_LABEL = {
    "OBSERVE": "관찰 수준",
    "CHECK": "추가확인 수준",
    "PRIORITY": "우선검토 수준",
    "UNDETERMINED": "판단 유보",
}

# 섹션별 필드 매핑: (snapshot 필드, triage_panel 컬럼)
TRIAGE_SECTIONS = {
    "q1": [
        ("state", "q1_state"),
        ("state_label", "q1_state_label"),
        ("production_yoy", "production_yoy"),
        ("employment_yoy", "employment_yoy"),
        ("quadrant_yoy_valid", "quadrant_yoy_valid"),
        ("question_route", "q1_question_route"),
    ],
    "q2": [
        ("employment", "employment"),
        ("employment_lag4", "employment_lag4"),
        ("emp_delta", "emp_delta"),
        ("employment_yoy", "q2_employment_yoy"),
        ("employment_share_pct", "employment_share_pct"),
        ("contribution_pct", "contribution_pct"),
        ("same_stage_rank", "q2_same_stage_rank"),
        ("mfg_emp", "mfg_emp"),
        ("mfg_emp_lag4", "mfg_emp_lag4"),
        ("mfg_emp_delta", "mfg_emp_delta"),
        ("mfg_emp_yoy", "mfg_emp_yoy"),
        ("net_gross_ratio", "net_gross_ratio"),
    ],
    "q3": [
        ("state_run_length", "q3_state_run_length"),
        ("transition", "q3_transition"),
        ("previous_state", "previous_state"),
        ("repeated_signal", "q3_repeated_signal"),
        ("persist", "persist"),
    ],
    "triage": [
        ("stage", "stage"),
        ("stage_reason", "stage_reason"),
        ("entry_trigger", "decision_entry_trigger"),
        ("reinforcement", "decision_reinforcement"),
        ("rank_in_stage", "rank_in_stage"),
        ("scale_ok", "scale_ok"),
        ("scale_threshold", "scale_threshold"),
        ("scale_flag", "scale_flag"),
        ("first_owner", "first_owner"),
        ("next_review_quarter", "next_review_quarter"),
        ("data_quality_minimum_only", "data_quality_minimum_only"),
        ("prod_only_decline", "prod_only_decline"),
    ],
    "signals": [
        ("E", "E"), ("R", "R"), ("A", "A"), ("P", "P"),
        ("E_entry", "E_entry"), ("E_up", "E_up"),
        ("R_entry", "R_entry"), ("R_up", "R_up"),
        ("A_entry", "A_entry"), ("A_up", "A_up"),
        ("P_support", "P_support"),
        ("n_entry", "n_entry"), ("n_up", "n_up"),
        ("emp_entry", "emp_entry"), ("emp_up", "emp_up"),
    ],
    "activity": [
        ("production", "production"),
        ("production_lag4", "production_lag4"),
        ("production_yoy", "production_yoy"),
        ("op_rate_official", "op_rate_official"),
        ("op_rate_approx", "op_rate_approx"),
        ("firms_in", "firms_in"),
        ("firms_op", "firms_op"),
    ],
    "data_quality": [
        ("core_missing", "data_quality_core_missing"),
        ("production_missing", "data_quality_production_missing"),
        ("previous_signal_unknown", "data_quality_previous_signal_unknown"),
        ("revision_boundary", "datarev"),
        ("review_required", "review_required"),
        ("classification_break", "classification_break"),
        ("production_yoy_reason", "production_yoy_reason"),
        ("employment_yoy_reason", "employment_yoy_reason"),
    ],
}
QUALITY_FIELDS = ("production", "employment", "op_rate", "firms_in", "firms_op")
QUALITY_ATTRS = ("source", "is_revised", "masked", "invalid_source", "note")

# 정수로 표시해야 하는 수(원천은 float 로 저장). 정수값일 때만 int 로 변환한다.
INT_FIELDS = {
    "employment", "employment_lag4", "emp_delta", "mfg_emp", "mfg_emp_lag4",
    "mfg_emp_delta", "firms_in", "firms_op", "state_run_length",
}

ELECTRE_FIELDS = [
    ("electre_stage", "electre_stage"),
    ("electre_specification", "electre_specification"),
    ("boundary_action", "boundary_action"),
    ("review_queue_group", "review_queue_group"),
    ("cai_observe", "cai_observe"),
    ("cai_check", "cai_check"),
    ("cai_priority", "cai_priority"),
    ("cai_undetermined", "cai_undetermined"),
    ("necessary_stage", "necessary_stage"),
    ("possible_stages", "possible_stages"),
    ("n_possible", "n_possible"),
    ("smaa_parameter_sensitive", "smaa_parameter_sensitive"),
    ("smaa_note", "smaa_note"),
    ("prereg_status", "prereg_status"),
    ("g1", "g1"), ("g2", "g2"), ("g3", "g3"), ("g4", "g4"),
    ("external_evidence_role", "external_evidence_role"),
]

EVIDENCE_EXCLUDE = {"industry", "quarter", "stage", "check_questions_context", "handoff_review_functions"}

TRACE_FIELDS = [
    "signal_profile", "model_path", "electre_used", "human_decision_required",
    "routing_disclaimer", "kepco_legal_dong_note", "jobs_note",
]

NO_EVIDENCE_REASON = "최신분기 외부근거 요약 카드 없음(요약 카드는 최신분기만 export) — 이 분기의 외부자료는 source별로 표시"
NO_SOURCE_DATA = "해당 시점 자료 없음"

# 분기별 외부자료 source. role 은 data_role_table(dataset_id) 에서 조회한다(여기서 분류하지 않음).
# available_any: 이 열 중 하나라도 값이 있으면 해당 분기 자료 있음 / available_flag: 해석층의 기존 가용 플래그.
EVIDENCE_SOURCES = [
    {"key": "ppi", "dataset_id": "ppi", "label": "생산자물가(PPI) 조정 생산",
     "available_any": ["ppi_adjusted_production_yoy", "ppi_adjusted_low"], "period": "quarter",
     "columns": ["nominal_production_yoy", "ppi_mapping_grade", "ppi_mapping_uncertainty", "n_ppi_candidates",
                 "ppi_candidate_items", "ppi_adjusted_production_yoy", "ppi_adjusted_low", "ppi_adjusted_high",
                 "ppi_adjusted_band_only", "sign_agreement"]},
    {"key": "eis_cci", "dataset_id": "eis_cci", "label": "고용보험 피보험자(EIS·창원상의)",
     "available_any": ["eis_manufacturing_yoy", "insured_yoy"], "period": "quarter_end_month",
     "columns": ["eis_manufacturing_yoy", "mfg_emp_yoy", "aggregate_direction", "aggregate_yoy_gap_pp",
                 "source_category", "insured_level", "insured_yoy", "industry_direction", "industry_yoy_gap_pp",
                 "mapping_confidence", "cross_source_available", "cross_source_population_note"],
     "scope_cols": ["cross_source_population_note"]},
    {"key": "customs_trade", "dataset_id": "customs_trade", "label": "수출(관세청 HS6)",
     "available_flag": "trade_data_available", "reason_col": "trade_unavailable_reason", "period": "quarter",
     "columns": ["trade_export_usd", "trade_export_yoy", "trade_import_yoy", "trade_n_items", "trade_mapping_grade",
                 "trade_coverage_flag", "trade_data_available", "trade_coverage_status", "trade_unavailable_reason",
                 "trade_scope"], "scope_cols": ["trade_scope"]},
    {"key": "kepco_business_type", "dataset_id": "kepco_business_type", "label": "전력사용(창원시 제조업 총계)",
     "available_flag": "power_data_available", "period": "quarter",
     "columns": ["power_usage_kwh", "power_usage_yoy", "power_customers", "power_customers_yoy",
                 "power_data_available", "power_scope"], "scope_cols": ["power_scope"]},
    {"key": "ecos_bsi", "dataset_id": "ecos_bsi", "label": "기업경기실사지수(BSI)",
     "available_flag": "bsi_data_available", "period": "quarter",
     "columns": ["bsi_region_business", "bsi_region_production", "bsi_region_new_orders", "bsi_region_operation",
                 "bsi_region_labor", "bsi_industry_business", "bsi_industry_mapping_grade", "bsi_data_available",
                 "bsi_region_scope", "bsi_industry_scope"], "scope_cols": ["bsi_region_scope", "bsi_industry_scope"]},
    {"key": "kosis_labor_flow", "dataset_id": "kosis_labor_flow", "label": "노동이동(입직·이직, 반기)",
     "available_flag": "mfg_flow_data_available", "period": "half_year",
     "columns": ["mfg_flow_period", "mfg_flow_workers", "mfg_flow_workers_yoy", "mfg_flow_acquisitions",
                 "mfg_flow_acquisition_yoy", "mfg_flow_losses", "mfg_flow_loss_yoy", "mfg_flow_net",
                 "mfg_flow_job_openings", "mfg_flow_data_available", "mfg_flow_scope"],
     "scope_cols": ["mfg_flow_scope"]},
]
# 분기 열이 없는 source: 고용24(등록 분기 단면), KEPCO 법정동(품질정보만)
JOBS_SOURCE = {"key": "changwon_jobs", "dataset_id": "changwon_jobs", "label": "고용24 공개 채용공고"}
KEPCO_LEGAL_SOURCE = {"key": "kepco_legal_dong_ksic", "dataset_id": "kepco_legal_dong_ksic",
                      "label": "전력사용(법정동×업종) — 품질정보만"}
# 최신분기 요약에 있는 KEPCO 법정동 열 중 분기와 무관한 자료 품질 정보(2026Q2 가용 여부 열은 제외)
KEPCO_LEGAL_QUALITY_COLS = [
    "kepco_legal_dong_observation_period", "kepco_legal_dong_suppression_pct_all",
    "kepco_legal_dong_complete_industry_quarters", "kepco_legal_dong_note", "kepco_legal_mapping_grade",
    "kepco_legal_ksic_codes", "kepco_legal_industry_suppression_rate", "kepco_legal_proxy_dong_coverage",
    "kepco_legal_complete_quarter_count",
]
NO_CONTEXT_QUESTION = "등록된 확인질문 없음"

# 맥락 기반 추가 확인질문의 구성요소(원천 열 그대로). check_questions_context = 세 열의 결합.
CONTEXT_COMPONENTS = {
    "signal_questions": "해석신호",
    "external_questions": "외부 수집자료 맥락",
    "quality_questions": "자료품질",
}
CONTEXT_QUESTION_ROLE = "맥락 기반 추가 확인질문 — 담당자 현장 확인용이며 Triage·ELECTRE 판정을 바꾸지 않고, 외부근거 카드가 아님"
