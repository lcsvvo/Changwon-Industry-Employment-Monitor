# -*- coding: utf-8 -*-
"""모형 공통 설정 — 명세 버전·기준 정의·표시 규칙·고정 문구·경로.

여기에는 가중치·경계·lambda·delta_emp 같은 판정 파라미터를 두지 않는다.
판정 파라미터는 config/electre_tri_b_params.yaml에서만 읽으며 기본값을 주입하지 않는다.
"""
from pathlib import Path

from eda import config as eda_config

MODEL_SPEC_VERSION = 'changwon-transition-diagnosis-model/1.0.0'
MODEL_TITLE = 'ELECTRE TRI-B의 경계 프로파일과 할당 절차를 적용한 다기준 경계분류 시범모형'
# 방법 설명 전용: 할당 절차의 구체적 방식
MODEL_ASSIGNMENT_METHOD_NOTE = ('할당 절차는 pessimistic assignment이다. 높은 경계 b2부터 비교해 outrank하면 우선점검, '
                                '그렇지 않고 b1을 outrank하면 추가확인, 둘 다 아니면 관찰로 배정한다.')
HASH_METHOD = 'sha256_lf_normalized'

# ---------------------------------------------------------------- 경로(저장소 루트 기준)
PATHS = {
    'state_panel': Path('data/processed/kicox/changwon_state_panel.csv'),
    'total_master': Path('data/processed/kicox/changwon_total_master.csv'),
    'industry_master': Path('data/processed/kicox/changwon_industry_master.csv'),
    'ppi_candidates': Path('outputs/tables/PPI_candidate_quarterly_yoy.csv'),
    'ppi_sensitivity': Path('outputs/tables/PPI_sensitivity.csv'),
    'ppi_mapping_resolved': Path('data/processed/ppi/ppi_industry_mapping_resolved.csv'),
    'aux_summary': Path('data/processed/auxiliary/aux_summary_2026Q2.csv'),
    'ppi_review_criteria': Path('data/processed/auxiliary/ppi_grade_criteria.csv'),
    'aux_report_html': Path('data/processed/auxiliary/aux_analysis_report.html'),
    'eis_panel': Path('data/processed/eis/eis_validation_panel.csv'),
    'params': Path('config/electre_tri_b_params.yaml'),
    'params_template': Path('config/electre_tri_b_params.template.yaml'),
    'briefing': Path('config/parameter_briefing.md'),
    'stage_actions': Path('config/stage_actions.yaml'),
    'stage_actions_template': Path('config/stage_actions.template.yaml'),
    'fixture': Path('tests/fixtures/model_regression_fixture.json'),
    'wording_rules': Path('tests/fixtures/model_wording_rules.json'),
}
OPTIONAL_INPUT_KEYS = ('industry_master', 'ppi_candidates', 'ppi_sensitivity', 'ppi_mapping_resolved',
                       'aux_summary', 'ppi_review_criteria', 'eis_panel', 'stage_actions')
PREPROCESS_DEFINITION_FILES = [Path('src/build_changwon_master.py'),
                               Path('src/build_kicox_analysis_panel.py')]

OUTPUTS = {
    'input_panel': Path('data/processed/model/electre_input_panel.csv'),
    'eligibility_audit': Path('outputs/tables/electre_eligibility_audit.csv'),
    'criteria_redundancy': Path('outputs/tables/criteria_redundancy_diagnostics.csv'),
    'g4_delta_sensitivity': Path('outputs/tables/g4_delta_sensitivity.csv'),
    'qoq_yoy_comparison': Path('outputs/tables/qoq_yoy_comparison.csv'),
    'firm_count_context': Path('outputs/tables/firm_count_context.csv'),
    'eis_regional_context': Path('outputs/tables/eis_regional_context.csv'),
    'parameter_register': Path('outputs/tables/electre_parameter_register.csv'),
    'cards_csv': Path('outputs/tables/diagnostic_cards_latest.csv'),
    'cards_md': Path('outputs/report/diagnostic_cards_latest.md'),
    'validation_report': Path('outputs/tables/model_validation_report.json'),
}
# 등록(SCENARIO_REGISTERED) 이상의 파라미터가 있을 때만 생성하는 산출물
PARAMETER_OUTPUTS = {
    'assignments': Path('outputs/tables/electre_assignments.csv'),
    'scenario_summary': Path('outputs/tables/electre_scenario_consensus.csv'),
    'boundary_evidence': Path('outputs/tables/electre_boundary_evidence.csv'),
    'coalition_table': Path('outputs/tables/electre_coalition_table.csv'),
    'simple_rule_comparison': Path('outputs/tables/simple_rule_comparison.csv'),
    'criterion_removal_sensitivity': Path('outputs/tables/criterion_removal_sensitivity.csv'),
    'criteria_activation_crosstab': Path('outputs/tables/criteria_activation_crosstab.csv'),
    'criterion_boundary_pass_counts': Path('outputs/tables/criterion_boundary_pass_counts.csv'),
    'g1_boundary_reachability': Path('outputs/tables/g1_boundary_reachability.csv'),
    'ppi_stage_divergence': Path('outputs/tables/ppi_stage_divergence.csv'),
    'recent4_stage_history': Path('outputs/tables/recent4_stage_history.csv'),
    'electre_parameter_registry': Path('outputs/tables/electre_parameter_registry.csv'),
    'simple_rule_latest': Path('outputs/tables/simple_rule_latest.csv'),
    'electre_latest_classification': Path('outputs/tables/electre_latest_classification.csv'),
    'electre_vs_rule_comparison': Path('outputs/tables/electre_vs_rule_comparison.csv'),
    'electre_assignment_trace': Path('outputs/tables/electre_assignment_trace.csv'),
    'electre_leave_one_criterion_out': Path('outputs/tables/electre_leave_one_criterion_out.csv'),
    'electre_monotonicity_test': Path('outputs/tables/electre_monotonicity_test.csv'),
    'electre_dominance_test': Path('outputs/tables/electre_dominance_test.csv'),
    'electre_pilot_scenario_summary': Path('outputs/tables/electre_scenario_summary.csv'),
}
RUN_DIR_ROOT = Path('outputs/runs')
CURRENT_MANIFEST = Path('outputs/current_run_manifest.json')
PROVENANCE_COLUMNS = ('run_id', 'run_started_at', 'input_sha256', 'input_sha256_raw_bytes',
                      'model_spec_version', 'parameter_set_id', 'parameter_status',
                      'effective_parameter_status', 'parameter_file_sha256')

# ---------------------------------------------------------------- 핵심 기준(모두 클수록 먼저 확인)
CRITERIA = ('g1', 'g2', 'g3', 'g4')
EMPLOYMENT_CRITERIA = ('g1', 'g2', 'g4')
CRITERION_COLUMNS = {
    'g1': 'g1_emp_abs_decline',
    'g2': 'g2_emp_rel_decline',
    'g3': 'g3_prod_decline_nominal',
    'g4': 'g4_emp_yoy_below_run',
}
CRITERION_LABELS = {
    'g1': '고용감소 절대규모(명)',
    'g2': '고용감소 상대규모(%)',
    'g3': '명목 생산감소 정도(%)',
    'g4': '전년동기 대비 고용 하회 연속분기',
}
CRITERION_DIRECTION = 'increasing'

# g4 민감도 컬럼: 본분석 delta_emp가 이 값 중 하나이면 해당 컬럼을 그대로 사용한다.
G4_DELTA_COLUMNS = {'g4_delta00': 0.0, 'g4_delta05': 0.5, 'g4_delta10': 1.0}
G4_FLAGS = ('left_censored', 'open_run', 'window_saturated', 'start_after_break')

# 기준 제외 민감도 분석 방법(결측 처리 규칙과 별개)
REMOVAL_SUPPORT_ZERO = 'criterion_support_removed_no_renormalization'
REMOVAL_RENORMALIZED = 'criterion_removed_weights_renormalized'
CRITERION_REMOVAL_METHODS = (REMOVAL_SUPPORT_ZERO, REMOVAL_RENORMALIZED)
REMOVAL_EVALUATION_SCOPE = 'base_model_complete_cases'
MISSING_RULE = 'complete_case_no_renormalization'

# ---------------------------------------------------------------- 품질 플래그
SENSITIVITY_THRESHOLDS = tuple(sorted(eda_config.SENSITIVITY_THRESHOLDS))
STATES4 = tuple(eda_config.STATES4)
STATES6 = tuple(eda_config.STATES6)
Q1_ROUTING = {'S1': 'ROUTABLE_S1', 'S2': 'ROUTABLE_S2', 'S3': 'ROUTABLE_S3',
              'S4': 'ROUTABLE_S4', 'N': 'NEUTRAL_REVIEW', 'INVALID': 'DATA_REVIEW'}

# 잔여 범주: 단일 업종으로 해석할 수 없는 KICOX 분류 항목
RESIDUAL_CATEGORIES = ('기타',)
ROUTEABILITY_RESIDUAL = 'REQUIRES_DISAGGREGATION'
ROUTEABILITY_SINGLE = 'SINGLE_INDUSTRY_CATEGORY'

# 가동업체 10개 이하: 업체 1개가 가동업체 수의 10% 이상을 차지할 수 있는 소규모 집계(표시용)
SMALL_FIRM_COUNT_MAX = 10
SMALL_FIRM_LABEL = '가동업체 10개 이하'

# PPI 매핑 확정 상태
PPI_CONFIRMATION_STATUSES = ('CONFIRMED', 'NOT_CONFIRMED', 'PARTIALLY_CONFIRMED',
                             'CONFIRMATION_MISSING', 'INVALID_CONFIRMED_VALUE')
PPI_CONFIRMATION_LABELS = {
    'CONFIRMED': '매핑 확정(confirmed=True)',
    'NOT_CONFIRMED': '매핑 미확정(confirmed=False)',
    'PARTIALLY_CONFIRMED': '일부 후보만 확정(미확정으로 취급)',
    'CONFIRMATION_MISSING': '매핑 확정 여부 정보 없음',
    'INVALID_CONFIRMED_VALUE': '매핑 확정 값 오류(검증 필요)',
}

# ---------------------------------------------------------------- 점검단계
DISPLAY_CLASSES = ('OBSERVE', 'CHECK', 'PRIORITY')
UNDETERMINED = 'UNDETERMINED'
DISPLAY_LABELS = {'OBSERVE': '관찰', 'CHECK': '추가확인', 'PRIORITY': '우선점검',
                  'UNDETERMINED': '판정불가(데이터 검토)'}
# 점검단계 전용 배색. Q1 STATE_COLORS(INVALID #F2F2F2 포함)와 값을 공유하지 않는다.
DISPLAY_COLORS = {'OBSERVE': '#DCE6EF', 'CHECK': '#E3A857', 'PRIORITY': '#8E3B5B',
                  'UNDETERMINED': '#5E6B7A'}

# 단계별 후속 행동
REQUIRED_STAGES = ('OBSERVE', 'CHECK', 'PRIORITY')
OPTIONAL_STAGES = ('UNDETERMINED',)
STAGE_PROCEDURE_TYPES = {'OBSERVE': 'STAGE_FOLLOW_UP', 'CHECK': 'STAGE_FOLLOW_UP',
                         'PRIORITY': 'STAGE_FOLLOW_UP', 'UNDETERMINED': 'DATA_REVIEW'}

SCENARIO_IDS = ('기준', '고용중시', '지속성중시')
PARAMETER_STATUSES = ('DRAFT', 'SCENARIO_REGISTERED', 'APPROVED')
ACTION_REVIEW_STATUSES = ('NOT_REVIEWED', 'ACCEPTED', 'DEFERRED', 'REJECTED')

RUN_BLOCKED_MISSING = 'BLOCKED_MISSING_PARAMETERS'
RUN_BLOCKED_INVALID = 'BLOCKED_INVALID_PARAMETERS'
RUN_BLOCKED_NOT_REGISTERED = 'BLOCKED_NOT_REGISTERED'

RECENT_HISTORY_N = 4
RECENT_HISTORY_TITLE = '최근 4분기 점검단계 이력 및 시간적 안정성'
REACHABILITY_TITLE = '경계 도달가능성 진단'

# ---------------------------------------------------------------- 고정 문구
SMALL_FIRM_CAUTION = ('가동업체 수가 적어 개별 업체 수준 변화가 업종 집계에 크게 반영될 수 있음. '
                      '현재 집계자료만으로 업체 수 변화가 고용 변화의 원인이라고 판단할 수 없음.')
RESIDUAL_CARD_TEXT = ('잔여 범주 — 단일 업종으로 해석하거나 특정 업종 지원사업에 직접 연결할 수 없음. '
                      '구성 업종 확인 후 라우팅 필요.')
REDUNDANCY_NOTE = ('상관계수는 두 기준 값이 함께 움직이는 정도를 요약한 기술통계다. 원인 관계나 기준 중복을 '
                   '확정하지 않으며, 고용이 감소하지 않은 행에서 여러 고용 기준이 함께 0이 되는 구조의 영향을 받는다.')
Q1_CHECK_QUESTIONS = {
    'S1': '미충원·숙련수요·증가 지속가능성을 확인한다(현재 자료로 단정하지 않음).',
    'S2': '자동화·외주화·생산성·인력부족·직무구조 변화 가능성을 질문으로 확인한다(원인 후보이며 입증된 원인이 아님).',
    'S3': '선제채용·신규기업·고용조정 시차·생산 시차 가능성을 질문으로 확인한다(원인 후보이며 입증된 원인이 아님).',
    'S4': '수주·가동·기업 수·휴업·고용조정 가능성을 질문으로 확인한다(원인 후보이며 입증된 원인이 아님).',
    'N': ('원자료상 정확한 0인지 반올림·개정 영향인지, 0이 아닌 다른 축의 방향과 규모, '
          '0.5·1·2% 민감도에서의 해석 변화를 확인한다.'),
    'INVALID': '원자료·전년동기·개정 여부를 확인한다. 정책지원 라우팅은 자료 보완 전 보류한다.',
}
NOT_DETERMINABLE_STATEMENTS = (
    '고용·생산 변화의 원인(자동화, 업체 증감, 산업 여건, 고용조정 등)은 현재 집계자료로 확인할 수 없다.',
    '특정 지원정책의 필요성이나 효과는 현재 자료로 판단할 수 없다.',
    '점검단계는 확인 순서를 정하는 분류이며 미래 상태가 나타날 확률을 뜻하지 않는다.',
)
PPI_STATUS_LABELS = {
    'SAME_ALL': '모든 PPI 후보에서 명목 생산 방향 유지',
    'OPPOSITE_ALL': '모든 PPI 후보에서 명목 생산 방향과의 불일치',
    'CANDIDATE_DEPENDENT': 'PPI 후보에 따라 명목 생산 방향과의 불일치 여부가 다름',
    'ZERO_BOUNDARY': 'PPI 후보 적용 시 0% 경계',
    'NOT_COMPARABLE': '비교불가',
    'PPI_SOURCE_NOT_AVAILABLE': 'PPI 후보별 원자료 없음',
}
PPI_COMPARABLE_STATUSES = ('SAME_ALL', 'OPPOSITE_ALL', 'CANDIDATE_DEPENDENT', 'ZERO_BOUNDARY')
EIS_SCOPE_NOTE = ('EIS는 창원시 전체 제조업 고용보험 피보험자 수이며 국가산단 업종×분기 패널과 모집단·공간단위가 다르다. '
                  '업종별 점수나 점검단계에 넣지 않고 지역 맥락으로만 제시한다.')


def g4_column_for_delta(delta):
    """delta가 민감도 컬럼 값과 정확히 같으면 그 컬럼명을, 아니면 None을 돌려준다."""
    for column, value in G4_DELTA_COLUMNS.items():
        if float(delta) == value:
            return column
    return None
