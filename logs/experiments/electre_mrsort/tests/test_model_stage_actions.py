# -*- coding: utf-8 -*-
"""단계별 후속 행동 설정 검증 테스트.

채운 값은 검증기 동작 확인용 합성 문자열이며 실제 담당 부서·처리기한이 아니다.
"""
import copy
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from model import config, pipeline  # noqa: E402
from model import stage_actions as sa  # noqa: E402

TEMPLATE = ROOT / config.PATHS['stage_actions_template']


def template():
    return yaml.safe_load(TEMPLATE.read_text(encoding='utf-8'))


def filled(include_undetermined=True, approval='APPROVED'):
    doc = template()
    for s in doc['stages']:
        s.update(owner_role='unit-test role', deadline_rule='unit-test rule',
                 required_checks=['unit-test check'], required_output=['unit-test output'],
                 approval_status=approval)
    if not include_undetermined:
        doc['stages'] = [s for s in doc['stages'] if s['stage'] != 'UNDETERMINED']
    return doc


def stage(doc, name):
    return next(s for s in doc['stages'] if s['stage'] == name)


def test_template_requires_policy_decision_without_errors():
    result = sa.validate_stage_actions(template())
    assert result['status'] == 'POLICY_DECISION_REQUIRED'
    assert not result['errors']
    assert len(result['missing_fields']) == 4 * 4


@pytest.mark.parametrize('doc, code', [
    ({'stages': []}, 'EMPTY_STAGES'),
    ({}, 'MISSING_KEY:stages'),
    ({'stages': 'OBSERVE'}, 'INVALID_TYPE:stages'),
    ([], 'INVALID_TYPE:document'),
])
def test_empty_or_malformed_documents_are_never_approved(doc, code):
    result = sa.validate_stage_actions(doc)
    assert result['status'] == 'INVALID_STAGE_ACTIONS'
    assert code in result['errors']
    assert result['status'] != 'APPROVED'


def test_empty_stages_reports_each_missing_required_stage():
    errors = sa.validate_stage_actions({'stages': []})['errors']
    for name in config.REQUIRED_STAGES:
        assert f'MISSING_STAGE:{name}' in errors


def test_fully_filled_and_approved_is_approved():
    result = sa.validate_stage_actions(filled())
    assert result['status'] == 'APPROVED', result
    assert result['undetermined_included'] is True


def test_undetermined_is_optional():
    result = sa.validate_stage_actions(filled(include_undetermined=False))
    assert result['status'] == 'APPROVED'
    assert result['undetermined_included'] is False


def test_any_unapproved_stage_keeps_policy_decision():
    doc = filled()
    stage(doc, 'CHECK')['approval_status'] = 'POLICY_DECISION_REQUIRED'
    assert sa.validate_stage_actions(doc)['status'] == 'POLICY_DECISION_REQUIRED'


def test_duplicate_missing_and_unknown_stages():
    doc = filled()
    doc['stages'].append(copy.deepcopy(stage(doc, 'CHECK')))
    assert 'DUPLICATE_STAGE:CHECK' in sa.validate_stage_actions(doc)['errors']

    doc = filled()
    doc['stages'] = [s for s in doc['stages'] if s['stage'] != 'PRIORITY']
    assert 'MISSING_STAGE:PRIORITY' in sa.validate_stage_actions(doc)['errors']

    doc = filled()
    doc['stages'].append({**copy.deepcopy(stage(doc, 'CHECK')), 'stage': 'URGENT'})
    result = sa.validate_stage_actions(doc)
    assert 'UNKNOWN_STAGE:URGENT' in result['errors'] and result['status'] == 'INVALID_STAGE_ACTIONS'

    doc = filled()
    doc['stages'].append(copy.deepcopy(stage(doc, 'UNDETERMINED')))
    assert 'DUPLICATE_STAGE:UNDETERMINED' in sa.validate_stage_actions(doc)['errors']


def test_undetermined_must_be_separate_data_review_procedure():
    doc = filled()
    stage(doc, 'UNDETERMINED')['procedure_type'] = 'STAGE_FOLLOW_UP'
    assert any(e.startswith('PROCEDURE_TYPE_MISMATCH:stages[UNDETERMINED]')
               for e in sa.validate_stage_actions(doc)['errors'])
    doc = filled()
    stage(doc, 'OBSERVE')['procedure_type'] = 'DATA_REVIEW'
    assert any(e.startswith('PROCEDURE_TYPE_MISMATCH:stages[OBSERVE]')
               for e in sa.validate_stage_actions(doc)['errors'])


@pytest.mark.parametrize('field, value, code', [
    ('owner_role', '', 'EMPTY_FIELD'),
    ('owner_role', '   ', 'EMPTY_FIELD'),
    ('owner_role', 3, 'INVALID_TYPE'),
    ('deadline_rule', ['unit-test'], 'INVALID_TYPE'),
    ('required_checks', 'unit-test', 'INVALID_TYPE'),
    ('required_checks', [], 'EMPTY_FIELD'),
    ('required_output', ['', 'unit-test'], 'INVALID_LIST_ITEM'),
    ('required_output', [1], 'INVALID_LIST_ITEM'),
    ('approval_status', 'YES', 'INVALID_APPROVAL_STATUS'),
])
def test_invalid_field_values_are_errors(field, value, code):
    doc = filled()
    stage(doc, 'PRIORITY')[field] = value
    result = sa.validate_stage_actions(doc)
    assert any(e.startswith(f'{code}:stages[PRIORITY]') for e in result['errors']), result['errors']
    assert result['status'] == 'INVALID_STAGE_ACTIONS'


def test_missing_field_key_and_non_mapping_item_are_errors():
    doc = filled()
    del stage(doc, 'OBSERVE')['owner_role']
    assert 'MISSING_KEY:stages[OBSERVE].owner_role' in sa.validate_stage_actions(doc)['errors']
    doc = filled()
    doc['stages'].append('CHECK')
    assert any(e.startswith('INVALID_TYPE:stages[') for e in sa.validate_stage_actions(doc)['errors'])


def test_pipeline_never_approves_empty_stage_actions():
    bundle = pipeline.run(ROOT, write=False, input_overrides={'stage_actions': {'stages': []}})
    result = bundle['report']['stage_actions']
    assert result['status'] == 'INVALID_STAGE_ACTIONS'
    assert 'EMPTY_STAGES' in result['errors']
    assert bundle['report']['policy_decisions_required']['stage_actions']['status'] != 'APPROVED'
