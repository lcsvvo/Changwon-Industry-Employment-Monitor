# -*- coding: utf-8 -*-
"""config/model_revalidation_prereg*.yaml 실제 파일과 prereg.py 스키마 검증.

이 파일은 실제 사전등록 파일 두 개(.yaml, .template.yaml)를 읽는다(읽기 전용).
.yaml은 사람이 REGISTERED로 확정했다(등록 자체는 이 테스트가 하지 않는다 — 그건
사람의 행위다). .template.yaml은 양식이므로 DRAFT·registration null을 유지한다.
"""
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from model import config, electre, prereg  # noqa: E402

TEMPLATE_PATH = ROOT / 'config/model_revalidation_prereg.template.yaml'
YAML_PATH = ROOT / 'config/model_revalidation_prereg.yaml'


def _payload_sha256_excluding(doc, excluded_keys):
    payload = {k: v for k, v in doc.items() if k not in excluded_keys}
    text = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def test_template_and_yaml_are_structurally_identical_apart_from_registration_state():
    """base_parameter_sha256·prereg_status·registration을 빼면 .yaml과 .template.yaml이 동일하다.

    .yaml은 REGISTERED로 확정됐고 .template.yaml은 양식이라 DRAFT로 남으므로
    이 세 필드만 다르고 나머지 본문(참조사례·veto_candidates·amendments 등)은 같아야 한다.
    """
    template_doc = prereg.load(TEMPLATE_PATH)
    yaml_doc = prereg.load(YAML_PATH)
    excluded = {'registration', 'base_parameter_sha256', 'prereg_status'}
    assert _payload_sha256_excluding(template_doc, excluded) == _payload_sha256_excluding(yaml_doc, excluded)
    assert template_doc['base_parameter_sha256'] is None
    assert yaml_doc['base_parameter_sha256'] is not None


def test_template_stays_draft_with_null_registration():
    doc = prereg.load(TEMPLATE_PATH)
    assert doc['prereg_status'] == 'DRAFT'
    registration = doc['registration']
    assert registration['registered_at'] is None
    assert registration['registered_by'] is None
    assert registration['prereg_sha256'] is None
    with pytest.raises(prereg.PreregNotRegisteredError):
        prereg.require_registered(doc)


def test_yaml_is_registered_and_require_registered_passes():
    doc = prereg.load(YAML_PATH)
    assert doc['prereg_status'] == 'REGISTERED'
    assert doc['registration']['registered_by'] == 'BOAZ 27기 시각화 미니프로젝트 3조'
    assert doc['registration']['registered_at'] is not None
    assert doc['registration']['prereg_sha256'] == prereg.payload_sha256(doc)
    prereg.require_registered(doc)  # 예외 없이 통과해야 한다


def test_yaml_base_parameter_sha256_matches_current_config():
    """DRAFT 문서라도 base_parameter_sha256 자체는 현재 기준파라미터와 일치해야 한다."""
    doc = prereg.load(YAML_PATH)
    prereg.check_base_parameter(doc, ROOT)  # 예외 없이 통과해야 한다
    assert doc['base_parameter_sha256'] == 'bef58985e0714e5a149bbbbf667ed271296f86fc1b7d056f18d3518723da70f0'


def test_base_parameter_mismatch_detected():
    doc = dict(prereg.load(YAML_PATH))
    doc['base_parameter_sha256'] = 'deadbeef'
    with pytest.raises(prereg.BaseParameterMismatchError):
        prereg.check_base_parameter(doc, ROOT)


def test_parameter_space_p_upper_matches_b1_and_passes():
    doc = prereg.load(YAML_PATH)
    assert prereg.check_parameter_space_bounds(doc, ROOT) is True
    assert doc['parameter_space']['p_upper'] == {'g1': 100, 'g2': 2.0, 'g3': 5.0, 'g4': 2.0}


def test_parameter_space_p_upper_violation_raises():
    doc = dict(prereg.load(YAML_PATH))
    doc['parameter_space'] = dict(doc['parameter_space'])
    doc['parameter_space']['p_upper'] = {'g1': 150, 'g2': 2.5, 'g3': 7.0, 'g4': 2.0}  # b1을 초과(g1,g2,g3)
    with pytest.raises(prereg.PreregSchemaError):
        prereg.check_parameter_space_bounds(doc, ROOT)


def test_reference_cases_exist_in_real_panel():
    doc = prereg.load(YAML_PATH)
    panel = pd.read_csv(ROOT / 'data/processed/model/electre_input_panel.csv')
    panel.columns = [str(c).lstrip('﻿') for c in panel.columns]
    keys = set(map(tuple, panel[['industry', 'quarter']].to_numpy()))
    cases = doc['reference_cases']
    assert {c['id'] for c in cases} == {'RC1', 'RC2', 'RC3'}
    for case in cases:
        assert (case['industry'], case['quarter']) in keys, f"{case['id']}({case['industry']}, {case['quarter']}) 가 패널에 없습니다"
    assert cases[0] == {'id': 'RC1', 'industry': '기계', 'quarter': '2022Q1', 'relation': 'at_least',
                        'stage': 'CHECK',
                        'rationale': '고용 2,394명(-3.67%p) 감소는 단일 분기라도 최소 추가확인 대상이다. '
                                    '이는 대량 고용변동 신고 기준(30명)의 수십 배 규모다.'}


def test_veto_candidates_single_v1_30_persons():
    """AM5: V1(30명) 단일 후보로 축소됐고, 법정 기준 차용 근거 필드를 갖는다."""
    doc = prereg.load(YAML_PATH)
    enabled = [c for c in doc['veto_candidates'] if c.get('enabled')]
    assert {c['id'] for c in enabled} == {'V1'}
    assert enabled[0]['threshold_value'] == 30
    assert 'borrowed_standard' in enabled[0] and 'borrowing_limitation' in enabled[0]
    for c in enabled:
        assert c['criterion'] in config.CRITERIA, f"{c['id']}.criterion={c['criterion']!r}가 config.CRITERIA 밖입니다"
        assert c['boundary'] in electre.BOUNDARIES, f"{c['id']}.boundary={c['boundary']!r}가 electre.BOUNDARIES 밖입니다"
    disabled = [c for c in doc['veto_candidates'] if not c.get('enabled')]
    assert {c['id'] for c in disabled} == {'V0'}
    assert 'V2' not in {c['id'] for c in doc['veto_candidates']}
    assert 'V1 이 C1~C4' in doc['veto_selection_rule']


def test_qp_derivation_sources_are_known():
    """qp_derivation의 *_source 값이 구현된 도출자 집합(prereg.KNOWN_QP_DERIVATION_SOURCES) 안에 있다."""
    doc = prereg.load(YAML_PATH)
    qp = doc['qp_derivation']
    sources = {field: value for crit_spec in qp.values() if isinstance(crit_spec, dict)
              for field, value in crit_spec.items() if field.endswith('_source')}
    assert sources  # 적어도 하나는 있어야 한다(g1/g2/g3에 p_source·q_source가 있음)
    for field, value in sources.items():
        assert value in prereg.KNOWN_QP_DERIVATION_SOURCES


def test_load_rejects_veto_candidate_missing_fields_when_enabled(tmp_path):
    doc = yaml_full_doc()
    doc['veto_candidates'].append({'id': 'VX', 'enabled': True, 'label': '불완전 후보'})  # 필수 필드 누락
    bad_path = tmp_path / 'bad.yaml'
    import yaml as _yaml
    bad_path.write_text(_yaml.safe_dump(doc, allow_unicode=True), encoding='utf-8')
    with pytest.raises(prereg.PreregSchemaError):
        prereg.load(bad_path)


def test_load_rejects_unknown_qp_derivation_source(tmp_path):
    doc = yaml_full_doc()
    doc['qp_derivation']['g1']['p_source'] = 'made_up_source_not_implemented'
    bad_path = tmp_path / 'bad_source.yaml'
    import yaml as _yaml
    bad_path.write_text(_yaml.safe_dump(doc, allow_unicode=True), encoding='utf-8')
    with pytest.raises(prereg.PreregSchemaError):
        prereg.load(bad_path)


def yaml_full_doc():
    """실제 .yaml을 파싱해 얕은 복사 딕셔너리로 돌려준다(테스트별 손상 변형용)."""
    import yaml as _yaml
    return _yaml.safe_load(YAML_PATH.read_text(encoding='utf-8'))


def test_yaml_has_six_amendments_including_am4_am5_am6():
    doc = prereg.load(YAML_PATH)
    assert [a['id'] for a in doc['amendments']] == ['AM1', 'AM2', 'AM3', 'AM4', 'AM5', 'AM6']
    assert doc['acceptance']['S1_evaluation_space'] == 'reference_compatible_subspace'
    assert doc['acceptance']['S1_also_report'] == ['full_parameter_space', 'crisp_subspace']
    assert doc['acceptance']['S1_necessary_share_min_on_discriminating'] == 0.30  # AM3는 합격선을 바꾸지 않는다
    am4 = next(a for a in doc['amendments'] if a['id'] == 'AM4')
    assert [r['id'] for r in am4['content']['phase4_exit_rules']] == ['EX1', 'EX2', 'EX3']
    assert am4['content']['phase5_metric_redefinition']['new_metric_id'] == 'C3b_interval_containment_rate'
    am5 = next(a for a in doc['amendments'] if a['id'] == 'AM5')
    assert am5['result_known_before_amendment'] is False
    assert am5['phase_at_amendment'] == 3
    am6 = next(a for a in doc['amendments'] if a['id'] == 'AM6')
    assert am6['result_known_before_amendment'] is False
    assert am6['phase_at_amendment'] == 4
    assert am6['prereg_status_at_amendment'] == 'REGISTERED'


def test_load_rejects_invalid_s1_evaluation_space(tmp_path):
    doc = yaml_full_doc()
    doc['acceptance']['S1_evaluation_space'] = 'made_up_space'
    bad_path = tmp_path / 'bad_s1_space.yaml'
    import yaml as _yaml
    bad_path.write_text(_yaml.safe_dump(doc, allow_unicode=True), encoding='utf-8')
    with pytest.raises(prereg.PreregSchemaError):
        prereg.load(bad_path)


def test_am6_virtual_reference_cases_five_with_full_profile():
    doc = prereg.load(YAML_PATH)
    assert prereg.validate_virtual_reference_cases(doc) is True
    am6 = next(a for a in doc['amendments'] if a['id'] == 'AM6')
    vrc = am6['content']['virtual_reference_cases']
    assert len(vrc) == 5
    assert {c['id'] for c in vrc} == {'VRC1', 'VRC2', 'VRC3', 'VRC4', 'VRC5'}
    for c in vrc:
        assert set(config.CRITERIA) <= set(c['profile'])
        assert c['relation'] in ('at_least', 'at_most')
        assert c['stage'] in ('OBSERVE', 'CHECK', 'PRIORITY')
        assert c['rationale']


def test_am6_interval_acceptance_four_with_threshold_in_unit_interval():
    doc = prereg.load(YAML_PATH)
    assert prereg.validate_interval_acceptance(doc) is True
    am6 = next(a for a in doc['amendments'] if a['id'] == 'AM6')
    items = am6['content']['interval_acceptance']
    assert len(items) == 4
    assert {i['id'] for i in items} == {'I1', 'I2', 'I3', 'I4'}
    for i in items:
        assert 0 < i['threshold'] <= 1
        assert i['definition']


def test_load_rejects_amendment_content_that_is_not_a_mapping(tmp_path):
    doc = yaml_full_doc()
    doc['amendments'] = list(doc['amendments']) + [{'id': 'AMX', 'content': 'not a mapping'}]
    bad_path = tmp_path / 'bad_amendment_content.yaml'
    import yaml as _yaml
    bad_path.write_text(_yaml.safe_dump(doc, allow_unicode=True), encoding='utf-8')
    with pytest.raises(prereg.PreregSchemaError):
        prereg.load(bad_path)


def test_registration_updated_after_am6():
    doc = prereg.load(YAML_PATH)
    assert doc['prereg_status'] == 'REGISTERED'
    assert doc['registration']['prereg_sha256'] == prereg.payload_sha256(doc)
    assert doc['registration']['registered_by'] == 'BOAZ 27기 시각화 미니프로젝트 3조'
    prereg.require_registered(doc)  # 예외 없이 통과해야 한다
