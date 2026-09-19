# -*- coding: utf-8 -*-
"""실제 패널 회귀검산·교차검산·보호 범위·표현 점검.

기대값은 tests/fixtures/model_regression_fixture.json에만 둔다.
입력 해시가 fixture와 같은데 값이 다르면 IMPLEMENTATION_REGRESSION,
입력 해시가 다르면 FIXTURE_REFRESH_REQUIRED로 구분해 실패시킨다.

실행
    pytest tests/test_model_regression.py -v
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from eda import config as eda_config  # noqa: E402
from model import config, derive, pipeline  # noqa: E402

pytestmark = pytest.mark.skipif(not (ROOT / config.PATHS['state_panel']).is_file(),
                                reason='기준 패널이 없습니다.')


@pytest.fixture(scope='module')
def bundle():
    return pipeline.run(ROOT, write=False)


@pytest.fixture(scope='module')
def fixture():
    return json.loads((ROOT / config.PATHS['fixture']).read_text(encoding='utf-8'))


@pytest.fixture(scope='module')
def report(bundle):
    return bundle['report']


def require_fixture_input(report):
    check = report['fixture_check']
    if check['status'] == 'FIXTURE_REFRESH_REQUIRED':
        pytest.fail(f"FIXTURE_REFRESH_REQUIRED: 입력 해시 {check['current_input_sha256']}가 "
                    f"fixture {check['fixture_input_sha256']}와 다릅니다. 기대값을 재검토하세요.")


# ---------------------------------------------------------------- fixture 대조
def test_fixture_check_matches(report):
    require_fixture_input(report)
    check = report['fixture_check']
    assert check['status'] == 'MATCH', f"IMPLEMENTATION_REGRESSION: {check['mismatches']}"


def test_fixture_metadata_fields_present(fixture):
    required = {'input_sha256', 'preprocess_config_sha256', 'parameter_file_sha256', 'briefing_doc_sha256',
                'model_spec_version', 'code_commit_sha', 'fixture_generated_at'}
    assert required <= set(fixture['fixture_metadata'])
    assert fixture['fixture_metadata']['model_spec_version'] == config.MODEL_SPEC_VERSION


# ---------------------------------------------------------------- V1~V6
def test_panel_validation_v1_to_v6_pass(report):
    failed = {k: v for k, v in report['panel_validation'].items() if not v['passed']}
    assert not failed, failed


def test_v4_counts_carry_labels(report, fixture):
    require_fixture_input(report)
    counts = report['panel_validation']['V4']['counts']
    assert all(set(d) == {'label', 'count'} for d in counts)
    assert {d['label']: d['count'] for d in counts} == fixture['expected']['threshold_flag_counts']


def test_v3_missing_is_not_all_one_quarter(report, fixture):
    require_fixture_input(report)
    v3 = report['panel_validation']['V3']
    exp = fixture['expected']['production_yoy']
    assert v3['missing_by_quarter'] == exp['missing_by_quarter']
    assert v3['source_missing_rows_by_quarter'] == exp['source_missing_by_quarter']
    assert v3['propagated_missing_rows_by_quarter'] == exp['propagated_missing_by_quarter']
    assert len(v3['missing_by_quarter']) > 1
    for q, n in exp['source_missing_by_quarter'].items():
        assert f'원천 생산 결측은 {q} {n}행' in v3['description']


def test_invalid_rows_have_no_concordance_or_stage(bundle):
    panel = bundle['panel']
    assert not [c for c in panel.columns if c.startswith(('concordance', 'display_class', 'inspection_stage'))]
    invalid = panel[~panel['scorable']]
    assert invalid[config.CRITERION_COLUMNS['g3']].isna().all(), '생산감소를 0으로 대체하지 않는다'
    assert invalid[config.CRITERION_COLUMNS['g1']].notna().all(), '고용 관련 값은 보존한다'


# ---------------------------------------------------------------- 파라미터 차단
def test_empirical_assignment_blocked_without_parameters(bundle, report):
    if (ROOT / config.PATHS['params']).is_file():
        pytest.skip('파라미터 파일이 존재하는 환경입니다.')
    assert report['run_mode'] == 'BLOCKED_MISSING_PARAMETERS'
    assert bundle['assignments'] is None and not bundle['param_tables']
    assert {d['path'] for d in report['outputs_blocked']} == {
        p.as_posix() for p in config.PARAMETER_OUTPUTS.values()}
    for p in config.PARAMETER_OUTPUTS.values():
        assert not (ROOT / p).exists(), f'파라미터 없이 생성된 산출물: {p}'
    assert bundle['cards']['display_class'].isna().all()
    assert bundle['cards']['scenario_display_text'].isna().all()
    missing = report['parameter_validation']['missing_parameter_fields']
    assert len(missing) == len(config.SCENARIO_IDS) * 15
    assert 'scenarios[기준].require_employment_evidence' in missing


# ---------------------------------------------------------------- 파생지표 성질
def test_g4_uses_sensitivity_column_values(bundle):
    panel, ctx = bundle['panel'], bundle['ctx']
    for column, delta in config.G4_DELTA_COLUMNS.items():
        assert config.g4_column_for_delta(delta) == column
        recomputed = derive.emp_yoy_below_run(panel, delta, len(ctx.quarters), ctx.latest)['run']
        assert recomputed.equals(panel[column])
    assert config.g4_column_for_delta(0.7) is None


def test_g4_does_not_depend_on_production_or_state(bundle):
    panel, ctx = bundle['panel'], bundle['ctx']
    altered = panel.assign(production_yoy=np.nan, state='INVALID')
    out = derive.emp_yoy_below_run(altered, 0.0, len(ctx.quarters), ctx.latest)['run']
    assert out.equals(panel['g4_delta00'])


def test_input_panel_is_row_order_invariant(bundle):
    from eda import panel as eda_panel
    state, _ = eda_panel.load_panels(ROOT / 'data' / 'processed')
    ctx = eda_panel.build_context(state)
    state = eda_panel.add_display_columns(state)
    mfg = eda_panel.manufacturing_totals(state, ctx)
    shuffled = state.sample(frac=1, random_state=7)
    a = derive.build_input_panel(state, ctx, mfg)
    b = derive.build_input_panel(shuffled, ctx, mfg)
    pd.testing.assert_frame_equal(a, b)


def test_no_negative_zero_in_criteria(bundle):
    panel = bundle['panel']
    for col in [config.CRITERION_COLUMNS[g] for g in ('g1', 'g2', 'g3')] + ['emp_qoq_delta',
                                                                           'firm_count_delta_yoy']:
        values = panel[col].to_numpy(dtype=float)
        assert not np.any((values == 0) & np.signbit(values)), col


def test_left_censored_long_run_displayed_as_minimum(bundle):
    cards = bundle['cards']
    censored = cards[cards['g4_delta00_text'].str.contains('좌절단')]
    assert len(censored) and censored['g4_delta00_text'].str.contains('최소 ').all()


# ---------------------------------------------------------------- 보조자료
def test_auxiliary_crosschecks_pass(report):
    checks = report['crosschecks']
    for key in ('ppi_ratio_formula', 'ppi_sensitivity_full_period', 'aux_summary_latest',
                'ppi_mapping_all_unconfirmed', 'residual_category_not_comparable', 'eis_isolation',
                'firm_count_isolation'):
        assert checks[key]['passed'] is True, (key, checks[key])


def test_no_confidence_grade_fields(bundle):
    for frame in (bundle['panel'], bundle['cards']):
        assert not [c for c in frame.columns if 'grade' in c.lower() or '등급' in c]


def test_residual_category_routing(bundle):
    panel, cards = bundle['panel'], bundle['cards']
    residual = panel[panel['industry'].isin(config.RESIDUAL_CATEGORIES)]
    assert residual['residual_category'].all()
    assert residual['routeability_status'].eq('REQUIRES_DISAGGREGATION').all()
    assert panel.loc[~panel['industry'].isin(config.RESIDUAL_CATEGORIES), 'residual_category'].eq(False).all()
    card = cards[cards['industry'].isin(config.RESIDUAL_CATEGORIES)].iloc[0]
    assert card['residual_note'] == config.RESIDUAL_CARD_TEXT


def test_small_firm_flag_is_display_only(bundle):
    panel = bundle['panel']
    flagged = panel['firms_op'] <= config.SMALL_FIRM_COUNT_MAX
    assert panel.loc[flagged, 'small_firm_caution'].eq(config.SMALL_FIRM_CAUTION).all()
    assert panel.loc[~flagged, 'small_firm_caution'].eq('').all()


def test_display_colors_are_separate_from_q1_colors():
    assert config.DISPLAY_COLORS['UNDETERMINED'] != eda_config.STATE_COLORS['INVALID']
    assert not set(config.DISPLAY_COLORS.values()) & set(eda_config.STATE_COLORS.values())


# ---------------------------------------------------------------- 표현 점검
def _sources():
    paths = sorted((ROOT / 'src' / 'model').glob('*.py')) + sorted((ROOT / 'config').glob('*.*'))
    paths += [ROOT / 'src' / 'run_decision_support_model.py', ROOT / 'notebooks' / '04_decision_support_model.ipynb']
    paths += [ROOT / p for p in config.OUTPUTS.values()]
    return [p for p in paths if p.is_file()]


def test_forbidden_wording_absent_in_model_sources_and_outputs(bundle):
    import re
    rules = json.loads((ROOT / config.PATHS['wording_rules']).read_text(encoding='utf-8'))
    texts = {p.relative_to(ROOT).as_posix(): p.read_text(encoding='utf-8') for p in _sources()}
    texts['<generated cards md>'] = bundle['cards_md']
    violations = [(name, lit) for name, text in texts.items() for lit in rules['forbidden_literals'] if lit in text]
    violations += [(name, pat) for name, text in texts.items() for pat in rules['forbidden_patterns']
                   if re.search(pat, text)]
    assert not violations, violations
    assert bundle['report']['wording_audit']['passed'] is True


EXACT_TITLE = 'ELECTRE TRI-B의 경계 프로파일과 할당 절차를 적용한 다기준 경계분류 시범모형'


def test_model_title_is_used_exactly(bundle):
    assert config.MODEL_TITLE == EXACT_TITLE
    for rel in ['config/electre_tri_b_params.template.yaml', 'config/parameter_briefing.md',
                'notebooks/04_decision_support_model.ipynb']:
        assert EXACT_TITLE in (ROOT / rel).read_text(encoding='utf-8'), rel
    assert EXACT_TITLE in bundle['cards_md']
    assert bundle['report']['model_title'] == EXACT_TITLE
    assert 'pessimistic assignment' not in config.MODEL_TITLE
    assert 'pessimistic assignment' in config.MODEL_ASSIGNMENT_METHOD_NOTE


def test_criteria_redundancy_diagnostics(bundle, report, fixture):
    table = bundle['redundancy']
    assert set(table['scope']) == {'complete_cases', 'employment_decline_complete_cases',
                                   'employment_decline_all_rows'}
    complete = table[table['scope'] == 'complete_cases']
    assert len(complete) == 6 * 2 and set(complete['method']) == {'pearson', 'spearman'}
    assert complete['n_rows_used'].eq(complete['n_rows_used'].iloc[0]).all()
    assert (complete['n_rows_used'] + complete['n_rows_excluded_missing']).eq(len(bundle['panel'])).all()
    decline = table[table['scope'] == 'employment_decline_complete_cases']
    assert set(zip(decline['criterion_x'], decline['criterion_y'])) == {('g1', 'g2')}
    assert table['criterion_x_definition'].str.len().gt(0).all()
    assert table['interpretation_note'].eq(config.REDUNDANCY_NOTE).all()
    assert config.OUTPUTS['criteria_redundancy'].as_posix() == 'outputs/tables/criteria_redundancy_diagnostics.csv'
    require_fixture_input(report)
    assert 'criteria_redundancy' in fixture['expected']


def test_cards_include_firm_count_change_flag(bundle):
    cards = bundle['cards']
    assert 'firm_count_changed_yoy' in cards.columns
    latest = bundle['panel'][bundle['panel']['quarter'] == bundle['ctx'].latest].set_index('industry')
    for r in cards.itertuples():
        assert r.firm_count_changed_yoy == latest.loc[r.industry, 'firm_count_changed_yoy']
    assert 'firm_count_changed_yoy' in bundle['cards_md']
    assert config.SMALL_FIRM_LABEL in bundle['cards_md']
    assert config.SMALL_FIRM_COUNT_MAX == 10 and config.SMALL_FIRM_LABEL == '가동업체 10개 이하'


def test_nominal_label_used_for_g3():
    assert '명목' in config.CRITERION_LABELS['g3']
    assert config.CRITERION_COLUMNS['g3'].endswith('_nominal')


# ---------------------------------------------------------------- 기존 코드 보호
def test_protected_files_unchanged_from_head():
    protected = ['notebooks/03_q1_q2_q3_integrated_analysis.ipynb', 'src/eda', 'data/processed/kicox',
                 'data/processed/ppi', 'data/processed/eis', 'outputs/tables/results_summary.json',
                 'outputs/tables/PPI_sensitivity.csv', 'outputs/tables/PPI_candidate_quarterly_yoy.csv']
    try:
        result = subprocess.run(['git', 'diff', '--name-only', 'HEAD', '--', *protected], cwd=ROOT,
                                capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        pytest.skip('git을 사용할 수 없습니다.')
    assert result.stdout.strip() == '', result.stdout
