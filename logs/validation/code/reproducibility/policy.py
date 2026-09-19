# -*- coding: utf-8 -*-
"""보호정책 V2 — 파일 역할 분류와 canonical 해시 계산.

왜 V2 가 필요한가
    V1 잠금(`outputs/hybrid_validation/EXECUTION_LOCK.json`)은 저장소 125개 파일을
    한 덩어리로 묶어 바이트 해시를 걸었다. 그 안에 실행시각을 매번 새로 쓰는
    `run_metadata.json` 과 개발 중 계속 고쳐지는 `README.md` 가 함께 들어가 있어,
    **모형 결과가 하나도 바뀌지 않아도 재실행·문서수정만으로 검사가 실패**한다.

    V2 는 과거 실패를 지우지 않는다. 보호 대상을 역할별로 나눠, 앞으로 무엇이
    바뀌었을 때 '모형 결과가 바뀌었다' 고 말할 수 있는지를 정의한다.

역할 4분류
    A IMMUTABLE_PROTOCOL       프로토콜·실행잠금·승인 당시 사양. 바이트 고정.
    B DETERMINISTIC_PROTECTED  입력·판정코드·설정·결정적 산출물. 바이트 고정.
    C RUNTIME_METADATA         실행시각·환경·QA 집계. 바이트 고정 대상 아님.
    D MUTABLE_DOCUMENTATION    README·설명문서. 바이트 고정 대상 아님.

    A·B 만 해시 보호 대상이다. C·D 의 해시 불일치는 모형 결과 불일치가 아니다.

C 안에 들어 있는 결정적 조각
    `run_metadata.json` 처럼 한 파일이 static 과 runtime 을 함께 담는 경우가 있다.
    이때 파일 전체가 아니라 **static 부분만** 골라 canonical 해시를 계산한다
    (`split_run_metadata`, `canonical_hash`). 원본 파일은 고치지 않는다.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

POLICY_VERSION = "changwon-protection-policy/2.5.0"
PARENT_MANIFESTS = [
    "outputs/rolling_backtest_protocol/FREEZE_MANIFEST.json",
    "outputs/rolling_backtest/EXECUTION_LOCK.json",
    "outputs/rolling_backtest/PREDICTION_LOCK.json",
    "outputs/hybrid_validation/EXECUTION_LOCK.json",
    "outputs/hybrid_validation/PREDICTION_LOCK.json",
]

IMMUTABLE_PROTOCOL = "IMMUTABLE_PROTOCOL"
DETERMINISTIC_PROTECTED = "DETERMINISTIC_PROTECTED"
RUNTIME_METADATA = "RUNTIME_METADATA"
MUTABLE_DOCUMENTATION = "MUTABLE_DOCUMENTATION"

HASH_PROTECTED_CATEGORIES = (IMMUTABLE_PROTOCOL, DETERMINISTIC_PROTECTED)

# 2.5.0 (2026-09-19): 최종 역할표·선택적 ELECTRE/SMAA 경계검토·외부 evidence와
# KEPCO 법정동×KSIC 품질패널·채용 스냅샷 QA를 보호범위에 추가. Triage 판정층은 그대로다.
# 2.4.0 (2026-09-19): 한국전력 3종 수집 확인 및 전력 활동패널 추가. 판정층은 그대로다.
# 2.3.0 (2026-09-19): 관세청 호출한도 대응 — 이어받기 스크립트, 누적 페이지검증 로그,
# 커버리지 기반 집계 배제를 보호범위에 추가. 판정층은 그대로다.
# 2.2.0 (2026-09-19): 관세청 HS6 모집단 확보로 수출 커버리지 확대(13 → 1,029 품목),
# 수집 커버리지 매니페스트 추가, KEPCO PARTIAL 고정. 판정층은 그대로다.
# 2.1.0 (2026-09-19): 외부 API 수집물(KOSIS 고용 flow, 관세청 수출입, ECOS BSI)과
# 그 수집·해석 코드를 보호범위에 추가. 판정층은 그대로다.
REASON_FOR_POLICY_REVISION = (
    "기존 QA에서 deterministic output과 무관한 runtime timestamp 및 mutable "
    "documentation이 byte-level protection에 포함되어 재실행 시 false failure를 "
    "발생시킴. 과거 실패를 삭제하지 않고 보호범위를 역할별로 분리함."
)

# ---------------------------------------------------------------- runtime 필드
# 같은 입력·같은 코드로 같은 결과를 내도 값이 달라질 수 있는 키.
# 이 키들은 canonical 재현성 해시에서 제외한다.
RUNTIME_KEYS = frozenset({
    "run_at_utc", "completed_at_utc", "locked_at_utc", "executed_at", "checked_at_utc",
    "retrieved_at", "git_head", "python", "pandas", "numpy", "platform",
    "runtime_executable", "hostname", "duration_seconds", "execution_path",
})


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(p: Path | str) -> str:
    return sha256_bytes(Path(p).read_bytes())


def canonical_json(obj) -> bytes:
    """키 순서·공백에 의존하지 않는 직렬화. 해시 비교의 기준."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")


def canonical_hash(obj) -> str:
    return sha256_bytes(canonical_json(obj))


def split_run_metadata(meta: dict) -> tuple[dict, dict]:
    """(static, runtime). 최상위 키만 나눈다 — 중첩 구조를 재해석하지 않는다.

    static  : 입력 해시, 코드 해시, 규칙, 창, 행 수 등 결정적 필드
    runtime : 실행시각, git head, 파이썬·라이브러리 버전 등 환경 필드
    """
    static = {k: v for k, v in meta.items() if k not in RUNTIME_KEYS}
    runtime = {k: v for k, v in meta.items() if k in RUNTIME_KEYS}
    return static, runtime


def describe_split(meta: dict) -> dict:
    static, runtime = split_run_metadata(meta)
    return {
        "static_keys": sorted(static),
        "runtime_keys": sorted(runtime),
        "canonical_static_sha256": canonical_hash(static),
        "canonical_note": (
            "sha256(json.dumps(static, sort_keys=True, ensure_ascii=False, "
            "separators=(',',':')).encode('utf-8')). 파일 전체 바이트 해시가 아니다."
        ),
    }


# ---------------------------------------------------------------- 분류 규칙
# (경로, 카테고리, 사유). 경로는 저장소 루트 기준 POSIX 경로.
# 리스트에 없는 파일은 보호 대상이 아니며 매니페스트에도 들어가지 않는다.

_A_PROTOCOL = [
    ("outputs/rolling_backtest_protocol/PROTOCOL.md", "CW-RBT-1.0 사전등록 프로토콜"),
    ("outputs/rolling_backtest_protocol/FREEZE_MANIFEST.json", "V1 동결 매니페스트(역사기록)"),
    ("outputs/rolling_backtest/EXECUTION_LOCK.json", "CW-RBT 실행잠금"),
    ("outputs/rolling_backtest/PREDICTION_LOCK.json", "CW-RBT 예측잠금"),
    ("outputs/hybrid_validation/PROTOCOL.md", "CW-HYB-1.0 사전등록 프로토콜"),
    ("outputs/hybrid_validation/EXECUTION_LOCK.json", "CW-HYB 실행잠금(V1 보호목록 125건 포함)"),
    ("outputs/hybrid_validation/PREDICTION_LOCK.json", "CW-HYB 예측잠금"),
    ("outputs/decision_support_final/audit_v3/artifact_hashes.json",
     "v3 인도 당시 산출물 해시 기록. 이 안에 runtime 파일(run_metadata.json) 해시가 "
     "포함되어 있다는 점이 V1 설계의 문제를 보여주는 증거라 그대로 보존한다"),
    ("outputs/robustness_extension/PROTECTED_HASH_AMENDMENT.md",
     "V1 보호대상 2건 불일치의 경위 기록. 수정 금지"),
    ("logs/audits/independent_audit/REPORT.md", "독립감사 기록"),
    ("logs/audits/independent_audit/findings.csv", "독립감사 기록"),
    ("logs/audits/independent_audit/summary.json", "독립감사 기록"),
    ("logs/audits/independent_audit/replay_verification.json", "독립감사 기록"),
    ("logs/audits/independent_audit/parameter_spaces.csv", "독립감사 기록"),
    ("logs/audits/independent_audit/criterion_decision_effects.csv", "독립감사 기록"),
    ("logs/audits/independent_audit/alternative_changed_cases.csv", "독립감사 기록"),
    ("docs/02_competition/공고문(2026년 창원시 AI_데이터 활용 공모전).pdf",
     "외부에서 확정된 공모 사양"),
]

_B_INPUT = [
    ("data/processed/kicox/changwon_industry_master.csv", "Triage 1차 입력"),
    ("data/processed/kicox/changwon_state_panel.csv", "Q1 국면 입력"),
    ("data/processed/ppi/ppi_industry_panel.csv", "해석층 PPI 조정 생산 입력"),
    ("data/processed/ppi/ppi_industry_mapping_resolved.csv", "PPI 매핑 등급 확정본"),
    ("data/reference/triage_history/legacy_point.csv", "과거 비교 기준표"),
    ("data/reference/triage_history/legacy_action.csv", "과거 비교 기준표"),
    ("data/reference/triage_history/legacy_time_definition.csv", "과거 비교 기준표"),
    ("data/reference/triage_history/original_v3_stages.csv", "과거 비교 기준표"),
    ("data/reference/external_event_audit/event_panel.csv", "외부사건 감사 동결자료"),
    ("data/reference/external_event_audit/event_panel_coverage.csv", "외부사건 감사 동결자료"),
    ("data/reference/industry_crosswalk/employment_insurance_to_kicox.csv", "업종 대응표"),
    ("data/reference/industry_crosswalk/ksic_to_kicox.csv", "업종 대응표"),
    ("data/reference/industry_crosswalk/hs_to_kicox.csv", "업종 대응표"),
    ("data/reference/industry_crosswalk/ppi_to_kicox.csv", "업종 대응표"),
    ("data/reference/industry_crosswalk/hs6_verified_to_kicox.csv",
     "관세청 API 로 존재를 확인한 HS6 → KICOX 대응표"),
    ("data/reference/industry_crosswalk/ecos_bsi_to_kicox.csv",
     "ECOS 업종코드 → KICOX 대응표"),
    ("data/reference/industry_crosswalk/labor_force_survey_to_kicox.csv",
     "사업체노동력조사 산업분류 → KICOX 대응표(전부 등급 D)"),
    ("data/reference/external_data_inventory.csv", "외부자료 탐색·재판정 결과표"),
    ("data/reference/industry_crosswalk/hs6_universe_customs.csv",
     "관세청 HS부호 원본에서 만든 유효 HS6 모집단 + 류 단위 KICOX 대응"),
    ("logs/experiments/electre_mrsort/data/processed/model/electre_input_panel.csv",
     "ELECTRE 후보모형 입력(역사기록)"),
    ("logs/audits/independent_audit/continuous_space_certificates.csv",
     "CW-RBT 동결 입력"),
    ("logs/archived_outputs/candidate_models/electre_class_acceptability_index_compatible.csv",
     "선택적 ELECTRE/SMAA 경계검토 입력 — 동일 실행의 d_stage와 compatible CAI"),
    ("data/processed/kepco/legal_dong_ksic_monthly_panel.csv",
     "KEPCO 법정동×KSIC 품질·기간 검증 입력"),
    ("data/processed/kepco/legal_dong_ksic_quarterly_panel.csv",
     "KEPCO 법정동×KSIC 분기 품질 검증 입력"),
    ("outputs/kepco_legal_dong_ksic/kicox_coverage.csv",
     "KEPCO 10업종별 매핑·비식별·완전성 품질표"),
    ("data/raw/external/changwon_jobs/changwon_jobs_20260918.csv",
     "채용정보 기준 스냅샷. 업종 신호가 아닌 context QA 입력"),
]

_B_CODE = [
    ("src/model/triage_rule.py", "판정 규칙"),
    ("src/model/triage_delivery.py", "판정 인도·진단카드"),
    ("src/model/triage_audit.py", "판정 감사"),
    ("src/run_triage_rule.py", "판정 실행 진입점"),
    ("src/build_changwon_master.py", "마스터 구축"),
    ("src/build_kicox_analysis_panel.py", "분석패널 구축"),
    ("src/build_ppi_industry_panel.py", "PPI 패널 구축"),
    ("src/build_validation_panels.py", "보조 검증패널 구축"),
    ("src/build_context_layer.py", "해석층·신뢰도층 실행 진입점"),
    ("src/context/config.py", "해석층 설정(경계값)"),
    ("src/context/monthly_panel.py", "월별 지속성"),
    ("src/context/ppi_adjusted.py", "PPI 조정 생산"),
    ("src/context/firm_activity.py", "업체수·가동률·소규모 트랙"),
    ("src/context/cross_source.py", "고용 교차확인"),
    ("src/context/signals.py", "확인신호 프로필·민감도"),
    ("src/context/quality.py", "신뢰도 플래그"),
    ("src/context/questions.py", "확인질문 생성"),
    ("src/context/external_panels.py", "외부 수집자료 → 보조패널"),
    ("src/context/external_signals.py", "외부자료 확인신호·맥락 플래그"),
    ("src/data_collection/secrets.py", "인증정보 로딩·마스킹"),
    ("src/data_collection/http_client.py", "수집용 HTTP 클라이언트"),
    ("src/data_collection/metadata.py", "수집 metadata 스키마"),
    ("src/data_collection/datagokr.py", "공공데이터포털 파일데이터 수집"),
    ("src/data_collection/collect_kosis_employment_insurance.py", "KOSIS 고용 flow 수집기"),
    ("src/data_collection/collect_customs_exports.py", "관세청 수출입 수집기"),
    ("src/data_collection/collect_customs_hs_reference.py", "관세청 HS부호 기준자료 수집기"),
    ("scripts/build_hs6_universe.py", "관세청 원본 → 유효 HS6 모집단 생성"),
    ("scripts/resume_customs_collection.py", "관세청 호출한도 해제 시 자동 이어받기"),
    ("scripts/register_customs_resume_task.ps1", "이어받기 작업 스케줄러 등록(기본 미적용)"),
    ("src/data_collection/collect_ecos_bsi.py", "ECOS BSI 수집기"),
    ("src/data_collection/collect_kepco_power.py", "한국전력 수집기(엔드포인트 미확정)"),
    ("src/data_collection/collect_changwon_jobs.py", "창원고용복지+센터 채용정보 수집기"),
    ("src/data_collection/collect_datagokr_files.py", "포털 파일데이터 수집기"),
    ("src/reproducibility/policy.py", "보호정책 V2 정의 자체"),
    ("scripts/run_hybrid_validation.py", "CW-HYB 실행 스크립트"),
    ("scripts/run_temporal_validation.py", "CW-RBT 실행 스크립트"),
    ("scripts/build_kepco_legal_dong_ksic_panel.py", "KEPCO 법정동×KSIC 패널·QA 구축"),
    ("src/build_final_delivery.py", "최종 역할표·경계검토·evidence·trace 구축"),
    ("logs/experiments/electre_mrsort/src/model/electre.py", "ELECTRE 후보모형(역사기록)"),
    ("logs/experiments/electre_mrsort/src/model/derive.py", "ELECTRE 후보모형(역사기록)"),
    ("logs/experiments/electre_mrsort/src/model/audit_tools.py", "ELECTRE 후보모형(역사기록)"),
    ("logs/experiments/electre_mrsort/src/model/robust.py", "ELECTRE 후보모형(역사기록)"),
    ("logs/legacy_configs/electre_tri_b_params.yaml", "후보모형 설정(역사기록)"),
    ("logs/legacy_configs/model_revalidation_prereg.yaml", "사전등록 설정(역사기록)"),
]

_B_OUTPUT = [
    ("outputs/decision_support_final/decision_panel.csv", "최종 판정 180행"),
    ("outputs/decision_support_final/decision_latest.csv", "최신 분기 판정"),
    ("outputs/decision_support_final/stage_distribution_by_quarter.csv", "단계 분포"),
    ("outputs/decision_support_final/stage_distribution_by_industry.csv", "단계 분포"),
    ("outputs/decision_support_final/diagnostic_cards_latest.csv", "진단카드"),
    ("outputs/decision_support_final/diagnostic_cards_latest.json", "진단카드"),
    ("outputs/decision_support_final/diagnostic_cards_latest.md", "진단카드"),
    ("outputs/decision_support_final/rule_provenance.csv", "규칙 출처"),
    ("outputs/decision_support_final/institution_handoff_map.csv", "인계 지도"),
    ("outputs/decision_support_final/sensitivity_own_rules.csv", "민감도"),
    ("outputs/decision_support_final/sensitivity_latest.csv", "민감도"),
    ("outputs/decision_support_final/sensitivity_by_industry.csv", "민감도"),
    ("outputs/decision_support_final/sensitivity_by_quarter.csv", "민감도"),
    ("outputs/decision_support_final/sensitivity_changed_rows.csv", "민감도"),
    ("outputs/decision_support_final/baseline_to_final.csv", "기준선 대비 변화"),
    ("outputs/decision_support_final/comparison_vs_legacy.csv", "과거 비교"),
    ("outputs/decision_support_final/history_boundary_changed_rows.csv", "경계 변화"),
    ("outputs/decision_support_final/independent_scalar_reproduction.csv", "독립 검산"),
    ("outputs/decision_support_final/missingness_summary.csv", "결측 요약"),
    ("outputs/decision_support_final/missingness_comparison.csv", "결측 비교"),
    ("outputs/decision_support_final/q3_decisive_rows.csv", "Q3 결정행"),
    ("outputs/decision_support_final/q3_definition_comparison.csv", "Q3 정의 비교"),
    ("outputs/decision_support_final/audit_v3/verification.json", "판정 분포 검증결과"),
    ("outputs/decision_support_final/audit_v3/raw_rebuild_verification.json",
     "원자료 재구축 검증결과"),
    ("outputs/rolling_backtest/predictions_long.csv", "CW-RBT 결정적 산출"),
    ("outputs/rolling_backtest/outcomes_long.csv", "CW-RBT 결정적 산출"),
    ("outputs/rolling_backtest/metrics_long.csv", "CW-RBT 결정적 산출"),
    ("outputs/rolling_backtest/evaluation_long.csv", "CW-RBT 결정적 산출"),
    ("outputs/rolling_backtest/sample_membership.csv", "CW-RBT 결정적 산출"),
    ("outputs/rolling_backtest/parameter_robustness_long.csv", "CW-RBT 결정적 산출"),
    ("outputs/rolling_backtest/operational_coverage.csv", "CW-RBT 결정적 산출"),
    ("outputs/rolling_backtest/REPORT.md", "CW-RBT 스크립트 생성 결과보고"),
    ("outputs/hybrid_validation/hybrid_predictions.csv", "CW-HYB 결정적 산출"),
    ("outputs/hybrid_validation/hybrid_overlap.csv", "CW-HYB 결정적 산출"),
    ("outputs/hybrid_validation/hybrid_metrics.csv", "CW-HYB 결정적 산출"),
    ("outputs/hybrid_validation/hybrid_case_comparison.csv", "CW-HYB 결정적 산출"),
    ("outputs/hybrid_validation/REPORT.md", "CW-HYB 스크립트 생성 결과보고"),
    ("data/processed/context/industry_context_signals.csv", "해석층 결정적 산출"),
    ("data/processed/context/employment_crosscheck_panel.csv", "해석층 결정적 산출"),
    ("data/processed/context/monthly_persistence_panel.csv", "해석층 결정적 산출"),
    ("data/processed/context/ppi_adjusted_production_panel.csv", "해석층 결정적 산출"),
    ("data/processed/context/data_quality_panel.csv", "신뢰도층 결정적 산출"),
    ("data/processed/context/employment_flow_panel.csv", "고용 flow 보조패널"),
    ("data/processed/context/trade_context_panel.csv", "수출입 맥락 보조패널"),
    ("data/processed/context/business_sentiment_panel.csv", "경기심리 보조패널"),
    ("data/processed/context/electricity_activity_panel.csv",
     "창원시 제조업 전력사용 활동 보조패널"),
    ("data/processed/context/trade_coverage_by_industry.csv",
     "업종별 수출입 수집 커버리지 — '대응 품목 없음'과 '수집 미완'을 구분"),
    ("outputs/robustness_extension/context_signal_summary.csv", "해석층 요약"),
    ("outputs/robustness_extension/cross_source_summary.csv", "교차확인 요약"),
    ("outputs/robustness_extension/nominal_real_disagreement.csv", "명목·조정 불일치"),
    ("outputs/robustness_extension/signal_threshold_sensitivity.csv", "경계 민감도"),
    ("outputs/robustness_extension/signal_threshold_sensitivity_changed_rows.csv",
     "경계 민감도 상세"),
    ("outputs/robustness_extension/small_industry_track.csv", "소규모 트랙"),
    ("outputs/robustness_extension/diagnostic_card_preview.csv", "진단카드 preview"),
    ("outputs/robustness_extension/source_vintage_check.csv", "포털 공표본 대조"),
    ("outputs/reproducibility/run_metadata_static.json",
     "run_metadata.json 에서 뽑아낸 결정적 부분(파생 산출물)"),
    ("outputs/final_model/data_role_table.csv", "최종 데이터 역할표"),
    ("outputs/final_model/core_panel.csv", "최종 core panel"),
    ("outputs/final_model/triage_latest.csv", "최신 Triage"),
    ("outputs/final_model/boundary_electre_smaa_panel.csv",
     "추가확인 35행의 선택적 ELECTRE/SMAA 경계검토"),
    ("outputs/final_model/boundary_review_summary.csv",
     "선택적 ELECTRE/SMAA 담당자 검토 큐 요약"),
    ("outputs/final_model/external_evidence_panel.csv", "최신 업종별 외부 evidence"),
    ("outputs/final_model/explanation_trace.csv", "업종별 판정·evidence·인계 trace"),
    ("outputs/final_model/recruiting_snapshot_summary.csv", "채용 스냅샷 지역별 QA 요약"),
    ("outputs/final_model/recruiting_snapshot_metadata.json", "채용 스냅샷 해시·중복 QA"),
    ("outputs/final_model/boundary_review_protocol.json",
     "선택적 ELECTRE/SMAA 비변경·비튜닝 실행규약"),
    ("outputs/final_model/cleanup_actions.csv", "최종 정리 작업 기록"),
    ("outputs/final_model/deliverables_index.csv", "최종 13개 산출물 색인"),
    ("outputs/final_model/qa_summary.json", "최종 전달 QA 결과"),
]

# (경로, 사유, 파일 안에서 결정적이라 별도로 검사하는 필드 경로)
_C_RUNTIME = [
    ("outputs/decision_support_final/run_metadata.json",
     "run_at_utc·git_head·라이브러리 버전이 매 실행 갱신됨",
     ["rule_version", "window", "rows", "rules", "inputs", "code_sha256",
      "randomness", "missing_policy", "numeric_comparison_atol_percentage_units"]),
    ("outputs/robustness_extension/run_metadata.json",
     "해석층 실행 metadata. 동일 구조",
     ["layer", "window", "rows", "triage_rule_version", "frozen_columns",
      "inputs", "code_sha256"]),
    ("outputs/rolling_backtest/RUN_METADATA.json",
     "completed_at_utc·platform·runtime_executable 포함(역사기록, 수정 금지)",
     ["output_hashes", "report_sha256", "prediction_lock_sha256"]),
    ("outputs/hybrid_validation/RUN_METADATA.json",
     "completed_at_utc·python 버전 포함(역사기록, 수정 금지)",
     ["output_hashes", "report_sha256", "execution_lock_sha256",
      "prediction_lock_sha256"]),
    ("outputs/reproducibility/run_metadata_runtime.json",
     "분리 저장한 runtime 영역(파생 산출물)", []),
    ("outputs/decision_support_final/audit_v3/full_tests.xml",
     "pytest junit — timestamp·hostname·소요시간 포함. 테스트가 늘면 건수도 바뀐다", []),
    ("outputs/decision_support_final/audit_v3/triage_tests.xml",
     "pytest junit — 위와 동일", []),
    ("outputs/decision_support_final/audit_v3/delivery_verification.json",
     "테스트 건수 집계. 테스트를 추가하면 바뀌며 모형 결과와 무관하다", []),
    ("outputs/decision_support_final/audit_v3/notebook_execution.json",
     "executed_at 및 로컬 파이썬 경로 포함", []),
    ("outputs/decision_support_final/decision_support_final.html",
     "노트북 렌더 산출물. nbconvert·matplotlib 버전에 따라 바이트가 달라질 수 있다. "
     "내용의 수치는 B 범주 CSV 로 검증한다", []),
    ("notebooks/11_decision_support_final.ipynb",
     "실행 결과가 셀에 저장되는 노트북. 재실행하면 바이트가 달라진다", []),
    ("data/raw/external/_collection_log_datagokr.json",
     "외부 수집 실행 로그(run_at 포함)", []),
    ("data/raw/external/employment_insurance/_metadata/changwon_labor_force_flow_halfyear.json",
     "KOSIS 수집 metadata — retrieved_at 포함", ["file_hash_sha256", "raw_response_sha256"]),
    ("data/raw/external/customs_trade/_metadata/changwon_hs6_trade_monthly.json",
     "관세청 수집 metadata — retrieved_at 포함", ["file_hash_sha256", "raw_response_sha256"]),
    ("data/raw/external/ecos/_metadata/bsi_gyeongnam_and_industry_monthly.json",
     "ECOS 수집 metadata — retrieved_at 포함", ["file_hash_sha256", "raw_response_sha256"]),
    ("data/raw/external/kepco/_metadata/collection_status.json",
     "한국전력 PARTIAL 사유 기록 — checked_at 포함", []),
    ("data/raw/external/customs_reference/_metadata/customs_hs_code_20260101.json",
     "관세청 HS부호 원본 metadata — retrieved_at 포함", ["file_hash_sha256"]),
    ("data/raw/external/customs_reference/_metadata/"
     "customs_hsk_nature_classification_20260101.json",
     "관세청 성질분류 원본 metadata — retrieved_at 포함", ["file_hash_sha256"]),
    ("data/raw/external/kepco/_metadata/kepco_open_api_manual.json",
     "한국전력 공식 매뉴얼 metadata — retrieved_at 포함", ["file_hash_sha256"]),
    ("data/raw/external/kepco/_metadata/changwon_industry_type_power_monthly.json",
     "한국전력 산업분류별 전력사용량 metadata — retrieved_at 포함", ["file_hash_sha256"]),
    ("data/raw/external/kepco/_metadata/changwon_business_type_power_monthly.json",
     "한국전력 업종별 전력사용량 metadata — retrieved_at 포함", ["file_hash_sha256"]),
    ("data/raw/external/kepco/_metadata/changwon_custnum_change_monthly.json",
     "한국전력 고객 증감 metadata — retrieved_at 포함. 단위 미확정으로 패널 제외",
     ["file_hash_sha256"]),
    ("data/raw/external/customs_trade/_metadata/coverage_manifest.json",
     "관세청 수집 커버리지 — run_at 포함. 결손 집계는 결정적 필드로 검사",
     ["hs6_complete", "hs6_partial", "missing_combinations", "windows"]),
    ("data/raw/external/customs_trade/_metadata/pagination_checks.json",
     "호출별 페이지 검증 누적기록 — run_at 포함. 누적 요약은 결정적 필드",
     ["cumulative"]),
    ("data/raw/external/customs_trade/_metadata/resume_log.json",
     "이어받기 시도 기록 — 시각 포함", []),
    ("data/raw/external/customs_reference/_metadata/customs_query_codes_v1.3.json",
     "관세청 조회코드 참고문서 metadata — retrieved_at 포함", ["file_hash_sha256"]),
]

_D_DOCUMENTATION = [
    ("README.md", "프로젝트 설명 문서. 개발 중 계속 고쳐진다"),
    ("PROJECT_STRUCTURE.md", "구조 설명 문서"),
    ("CONTRIBUTING.md", "기여 안내"),
    ("docs/expression_audit.md", "표현 감사 문서"),
    ("docs/robustness_extension_report.md", "강건성 보완 보고서"),
    ("docs/reproducibility/PROTECTION_POLICY_V2.md", "보호정책 V2 문서"),
    ("docs/external_data_integration_report.md", "외부데이터 통합 보고서"),
    ("data/raw/external/README.md", "외부 수집 안내"),
    ("outputs/decision_support_final/REPORT.md",
     "최종 보고서(서술). 수치 주장은 B 범주 CSV 로 검증한다"),
    ("outputs/decision_support_final/MODEL_ROLE_CLARIFICATION.md", "모형 역할 설명"),
    ("outputs/robustness_extension/REPORT.md",
     "해석층 결과보고(서술). 수치 주장은 B 범주 CSV 로 검증한다"),
    ("outputs/reproducibility/V2_QA_REPORT.md", "V2 QA 결과 기록"),
    ("data/reference/external_event_audit/README.md", "외부사건 감사 안내"),
    ("data/reference/external_reference_candidate_audit.md", "외부 준거 후보 심사"),
    ("data/reference/industry_crosswalk/README.md", "업종 대응표 안내"),
    ("logs/README.md", "역사자료 안내"),
    ("docs/final_methodology.md", "최종 방법론·구조도"),
    ("outputs/final_model/RUNBOOK.md", "최종 실행방법"),
]


def classification() -> list[dict]:
    """전체 분류표. 순서는 A → B(input/code/output) → C → D."""
    rows: list[dict] = []
    for path, why in _A_PROTOCOL:
        rows.append(dict(path=path, category=IMMUTABLE_PROTOCOL, role="protocol",
                         rationale=why, hash_protected=True))
    for group, role in ((_B_INPUT, "input"), (_B_CODE, "code"), (_B_OUTPUT, "output")):
        for path, why in group:
            rows.append(dict(path=path, category=DETERMINISTIC_PROTECTED, role=role,
                             rationale=why, hash_protected=True))
    for path, why, fields in _C_RUNTIME:
        rows.append(dict(path=path, category=RUNTIME_METADATA, role="runtime",
                         rationale=why, hash_protected=False,
                         deterministic_fields=fields))
    for path, why in _D_DOCUMENTATION:
        rows.append(dict(path=path, category=MUTABLE_DOCUMENTATION, role="documentation",
                         rationale=why, hash_protected=False))
    seen = [r["path"] for r in rows]
    dupes = {p for p in seen if seen.count(p) > 1}
    if dupes:
        raise ValueError(f"한 파일이 두 범주에 들어갔다: {sorted(dupes)}")
    return rows


def load_manifest(root: Path) -> dict:
    p = root / "outputs" / "reproducibility" / "FREEZE_MANIFEST_V2.json"
    return json.loads(p.read_text(encoding="utf-8"))
