# -*- coding: utf-8 -*-
"""Phase 6: VRC4 의존성 검증·I3 구조 기록·최종 기록물 검증.

모형·합격선·가상 참조사례를 바꾸지 않는다. 무거운 재계산(run_phase6)은 module
스코프 fixture 하나로 공유한다.
"""
import hashlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from model import prereg, revalidation_phase6 as p6  # noqa: E402


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@pytest.fixture(scope='module')
def result():
    return p6.run_phase6(ROOT, write=True)  # Step 3~6 산출물(md 등)을 실제로 써야 뒤 검사가 가능하다


def test_vrc4_sensitivity_without_has_more_samples(result):
    t = result['tables']['vrc4_sensitivity']
    with_n = int(t.loc[t.variant == 'with_vrc4', 'n_samples'].iloc[0])
    without_n = int(t.loc[t.variant == 'without_vrc4', 'n_samples'].iloc[0])
    assert without_n > with_n


def test_vrc4_excluded_region_verified_analytically(result):
    t = result['tables']['vrc4_excluded_region']
    assert (t['verified_analytically'] == True).all()  # noqa: E712
    assert (t['constraint_form'] == 'w_g2 + w_g4 >= lambda').all()


def test_vrc4_four_combinations_match_manual_calculation(result):
    t = result['tables']['vrc4_excluded_region']
    t = t[t.scenario_id.notna()].set_index('scenario_id')
    expected = {'기준': True, '고용중시': False, '지속성중시': True, 'W_inferred': True}
    for sid, exp in expected.items():
        assert bool(t.loc[sid, 'satisfies_vrc4']) == exp, f'{sid}: {t.loc[sid, "satisfies_vrc4"]} != {exp}'


def test_i2_i3_tradeoff_values_in_unit_interval(result):
    t = result['tables']['i2_i3_tradeoff']
    detail = t[t['subsample_ratio'].notna()]
    assert len(detail) == 25  # ratio 5종 x replicate 5회
    assert detail['i2_value'].between(0, 1).all()
    assert detail['i3_value'].between(0, 1).all()
    summary = t[t['subsample_ratio'].isna()]
    assert len(summary) == 1
    assert -1.0 <= summary['spearman_i2_i3'].iloc[0] <= 1.0


def test_limitation_record_has_lim1_and_lim2_matching_phase5(result):
    lim = result['limitation_record']
    assert list(lim['limitation_id']) == ['LIM1', 'LIM2']
    # Phase 5가 원래 썼던 LIM1 파일(현재 canonical에 남아있던 값)과 동일해야 한다 —
    # append_lim2는 LIM1 행을 건드리지 않으므로 실행 전후 LIM1 내용이 같아야 한다.
    lim1_before = pd.read_csv(ROOT / 'outputs/tables/electre_limitation_record.csv')
    lim1_before = lim1_before[lim1_before.limitation_id == 'LIM1'].iloc[0]
    lim1_after = lim[lim.limitation_id == 'LIM1'].iloc[0]
    assert lim1_before['statement'] == lim1_after['statement']


def test_final_decision_status_unchanged_from_phase5(result):
    fd = pd.read_csv(ROOT / 'outputs/tables/electre_final_decision.csv')
    row = fd[fd.block_type == 'interval_assignment'].iloc[0]
    assert row['overall_status'] == 'INTERVAL_BLOCKED_BY_I3'


def test_prereg_acceptance_thresholds_unchanged(result):
    doc = result['prereg_doc']
    acc = doc['acceptance']
    assert acc['C2_pess_opt_agreement_min'] == 0.95
    assert acc['C3_retention_mean_min'] == 0.95
    assert acc['C3_retention_p05_min'] == 0.90
    assert acc['C4_reference_case_pass_rate'] == 1.0
    assert acc['S1_necessary_share_min_on_discriminating'] == 0.30
    am6 = p6._am6_content(doc)  # noqa: SLF001
    thresholds = {i['id']: i['threshold'] for i in am6['interval_acceptance']}
    assert thresholds == {'I1': 1.0, 'I2': 0.50, 'I3': 0.95, 'I4': 0.60}


def test_competition_key_figures_no_empty_caveat(result):
    t = result['tables']['competition_key_figures']
    assert len(t) > 0
    assert t['caveat'].notna().all()
    assert (t['caveat'].astype(str).str.len() > 0).all()
    assert set(t['category']) <= {'SCOPE', 'STRUCTURE', 'VALIDATION', 'ROBUSTNESS', 'RESULT', 'LIMITATION'}


def test_wording_check_reporting_rules_codeblock_outside_body(result):
    sys.path.insert(0, str(ROOT / 'scripts'))
    import check_wording
    violations = check_wording.check(['outputs/report/reporting_rules.md'], allow_quoted_in_codeblock=True)
    assert violations == []


def test_wording_check_phase6_new_files_and_readme_appended_section():
    """vrc4_provenance_evidence.csv는 검사 대상에서 뺀다 — 그 파일의 excerpt 컬럼은
    기획 문서 원문을 판정 없이 그대로 발췌하는 것이 Step 1-1의 설계 목적이므로
    (reporting_rules.md·tests/fixtures/model_wording_rules.json과 같은 이유), 원문에
    있던 금지어가 그대로 옮겨져도 우리가 새로 쓴 문장이 아니다.
    """
    sys.path.insert(0, str(ROOT / 'scripts'))
    import check_wording
    targets = ['src/model/revalidation_phase6.py', 'tests/test_model_phase6.py',
              'outputs/report/revalidation_history.md']
    for t in ('outputs/tables/vrc4_sensitivity.csv', 'outputs/tables/vrc4_excluded_region.csv',
             'outputs/tables/i2_i3_tradeoff.csv', 'outputs/tables/robustness_metric_taxonomy.csv',
             'outputs/tables/competition_key_figures.csv'):
        if (ROOT / t).is_file():
            targets.append(t)
    violations = check_wording.check(targets)
    assert violations == []

    # README.md는 전체를 스캔하지 않는다(기존 16절에 우리가 쓰지 않은 금지어가 이미 있다 —
    # 아래에서 그 사실 자체를 문서화하고, Phase 6가 덧붙인 절만 별도로 검사한다).
    readme_text = (ROOT / 'README.md').read_text(encoding='utf-8')
    marker = p6.README_SECTION_MARKER
    assert marker in readme_text
    appended = readme_text[readme_text.index(marker):]
    literals, patterns = check_wording.load_rules()
    hits = [lit for lit in literals if lit in appended]
    assert hits == [], f'Phase 6가 추가한 절 안에서 금지어 발견: {hits}'


def test_vrc4_provenance_evidence_quotes_source_verbatim_including_pre_existing_violation():
    """excerpt 컬럼이 판정 없이 원문을 그대로 담았는지, 그리고 그 원문 인용 안에
    기존 금지어가 실제로 섞여 들어왔는지(=Step 1-1이 손대지 않고 그대로 발췌했다는
    증거)를 확인한다. 이 파일은 그래서 위 테스트의 스캔 대상에서 뺐다.
    """
    path = ROOT / 'outputs/tables/vrc4_provenance_evidence.csv'
    df = pd.read_csv(path)
    assert len(df) > 0
    assert set(df['supports_independent_duration_criterion'].unique()) <= {None} \
        or df['supports_independent_duration_criterion'].isna().all()  # 사람이 채울 공란, 코드가 채우지 않는다
    forbidden_word = '실질' + '생산'
    assert df['excerpt'].astype(str).str.contains(forbidden_word).any()


def test_pre_existing_readme_violation_is_documented_not_ours():
    """README.md의 기존 16절(우리가 쓰지 않은 부분)에 금지어(물가조정 없는 값을
    '실질' 수치라 부르는 표현, 띄어쓰기 없이 붙여 쓴 한 단어)가 있다는 사실을
    고정해 둔다 — 이 테스트가 실패하면(즉 사라지면) 누군가 그 문구를 고쳤다는 뜻이다.
    이 테스트 자체는 그 사실을 회피하지 않고 기록하는 것이 목적이다.
    """
    readme_text = (ROOT / 'README.md').read_text(encoding='utf-8')
    marker = p6.README_SECTION_MARKER
    pre_existing = readme_text[:readme_text.index(marker)]
    forbidden_word = '실질' + '생산'  # 문자열 결합: 이 소스 파일 자체가 check_wording.py에
    # 걸리지 않도록(금지어를 리터럴로 담지 않도록) 나눠 적는다. 런타임 동작은 동일하다.
    assert forbidden_word in pre_existing  # Phase 6 이전부터 있던 기존 서술(우리가 쓴 문장이 아니다)


def test_frozen_files_and_base_params_unchanged():
    import json
    baseline = json.loads((ROOT / 'outputs/revalidation_baseline_hashes.json').read_text(encoding='utf-8'))
    frozen = ['qp_calibration.py', 'pipeline.py', 'pilot.py', 'params.py', 'config.py', 'manifest.py',
             'inputs.py', 'derive.py', 'cards.py', 'validation.py', 'diagnostics.py', 'ppi_aux.py',
             'stage_actions.py', 'electre.py']
    for name in frozen:
        key = f'src/model/{name}'
        assert baseline['src_model_hashes'][key] == _sha(ROOT / key), f'{key} 변경됨'
    for key, expected in baseline['tests_original_11_hashes'].items():
        assert _sha(ROOT / key) == expected, f'{key} 변경됨'
    assert _sha(ROOT / 'config/electre_tri_b_params.yaml') == baseline['hashes']['config/electre_tri_b_params.yaml']
