# -*- coding: utf-8 -*-
"""파라미터 검증·등록·승인 상태 단위 테스트.

여기의 수치 파라미터는 검증기 동작을 확인하기 위한 합성값이며, 실제 자료의 점검단계 산출에 쓰지 않는다.
"""
import copy
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from model import config, inputs, params  # noqa: E402

TEMPLATE = ROOT / config.PATHS['params_template']
BRIEFING = ROOT / config.PATHS['briefing']
RUN_AT = datetime(2030, 1, 1, tzinfo=timezone.utc)
WINDOW_N = 18


def synthetic_doc():
    doc = params.load_parameter_file(TEMPLATE)
    doc['parameter_set_id'] = 'UNIT-TEST-ONLY'
    for s in doc['scenarios']:
        s['weights'] = {'g1': 0.25, 'g2': 0.25, 'g3': 0.25, 'g4': 0.25}
        s['profiles'] = {'b1': {'g1': 10, 'g2': 1, 'g3': 1, 'g4': 2},
                         'b2': {'g1': 20, 'g2': 2, 'g3': 2, 'g4': 3}}
        s['lambda'] = 0.5
        s['delta_emp'] = 0.0
        s['require_employment_evidence'] = True
    return doc


def register(doc, at=RUN_AT - timedelta(days=1)):
    doc['registration'] = {'registered_at': at.isoformat(), 'registered_by': 'unit-test',
                           'briefing_doc_sha256': inputs.sha256_text_file(BRIEFING),
                           'parameter_file_sha256': params.parameter_payload_sha256(doc)}
    doc['parameter_status'] = 'SCENARIO_REGISTERED'
    return doc


def approve(doc, at=RUN_AT - timedelta(hours=1)):
    approved_block = next(s for s in doc['scenarios'] if s['scenario_id'] == '기준')
    doc['approval'] = {'approved_scenario_id': '기준',
                       'approved_parameter_file_sha256': params.parameter_payload_sha256(doc),
                       'approved_scenario_block_sha256': params.scenario_block_sha256(approved_block),
                       'approver_name': 'unit-test', 'approver_role': 'unit-test', 'approver_org': 'unit-test',
                       'approved_at': at.isoformat(), 'approval_reference': 'unit-test'}
    doc['parameter_status'] = 'APPROVED'
    return doc


def validate(doc, present=True):
    return params.validate_parameters(doc, analysis_window_n=WINDOW_N, run_started_at=RUN_AT,
                                      briefing_path=BRIEFING, parameter_file_label='unit-test',
                                      present=present)


def has(items, prefix):
    return any(str(x).startswith(prefix) for x in items)


# ---------------------------------------------------------------- 템플릿·기본값 주입 금지
def test_template_lists_all_missing_fields_without_defaults():
    doc = params.load_parameter_file(TEMPLATE)
    before = copy.deepcopy(doc)
    result = validate(doc, present=False)
    assert result.run_mode == 'BLOCKED_MISSING_PARAMETERS'
    assert not result.errors
    assert len(result.missing_parameter_fields) == len(config.SCENARIO_IDS) * 15
    for sid in config.SCENARIO_IDS:
        assert f'scenarios[{sid}].require_employment_evidence' in result.missing_parameter_fields
        assert f'scenarios[{sid}].delta_emp' in result.missing_parameter_fields
    assert result.scenarios == [] and not result.can_run_scenarios
    assert doc == before, '검증기가 값을 채우면 안 된다'


def test_require_employment_evidence_key_must_exist():
    doc = synthetic_doc()
    del doc['scenarios'][0]['require_employment_evidence']
    result = validate(doc)
    assert has(result.errors, 'MISSING_KEY:scenarios[기준].require_employment_evidence')
    assert result.run_mode == 'BLOCKED_INVALID_PARAMETERS'


def test_require_employment_evidence_must_be_boolean():
    doc = synthetic_doc()
    doc['scenarios'][0]['require_employment_evidence'] = 'true'
    assert has(validate(doc).errors, 'INVALID_BOOLEAN')


@pytest.mark.parametrize('mutate, code', [
    (lambda s: s['profiles']['b1'].update(g2=5), 'PROFILE_ORDER_VIOLATION_B1_GT_B2'),
    (lambda s: s['profiles']['b1'].update(g4=1), 'B1_G4_BELOW_2'),
    (lambda s: s['weights'].update(g1=0.15), 'WEIGHT_SUM_NOT_ONE'),
    (lambda s: s['weights'].update(g1=0.0, g2=0.5), 'WEIGHT_NOT_POSITIVE'),
    (lambda s: s.update({'lambda': 0.4}), 'LAMBDA_OUT_OF_RANGE'),
    (lambda s: s.update({'lambda': 1.01}), 'LAMBDA_OUT_OF_RANGE'),
    (lambda s: s.update(delta_emp=-0.5), 'DELTA_EMP_NEGATIVE'),
    (lambda s: s['profiles']['b2'].update(g2=150), 'BOUNDARY_OUT_OF_RANGE'),
])
def test_parameter_constraints(mutate, code):
    doc = synthetic_doc()
    mutate(doc['scenarios'][0])
    result = validate(doc)
    assert has(result.errors, code), result.errors
    assert not result.can_run_scenarios


def test_fixed_settings_cannot_change():
    doc = synthetic_doc()
    doc['fixed']['q'] = 1
    doc['fixed']['assignment_rule'] = 'optimistic'
    errors = validate(doc).errors
    assert 'FIXED_SETTING_VIOLATION:fixed.q' in errors
    assert 'FIXED_SETTING_VIOLATION:fixed.assignment_rule' in errors


def test_scenario_ids_must_match():
    doc = synthetic_doc()
    doc['scenarios'][2]['scenario_id'] = '임의'
    assert has(validate(doc).errors, 'SCENARIO_ID_SET_MISMATCH')


def test_window_saturation_warning():
    doc = synthetic_doc()
    doc['scenarios'][0]['profiles']['b2']['g4'] = WINDOW_N - 1
    result = validate(doc)
    assert 'WINDOW_SATURATION_WARNING:scenarios[기준].profiles.b2.g4' in result.warnings
    assert not has(result.errors, 'WINDOW')


# ---------------------------------------------------------------- 등록·승인 상태
def test_complete_but_unregistered_is_blocked():
    result = validate(synthetic_doc())
    assert result.effective_status == 'DRAFT'
    assert result.run_mode == 'BLOCKED_NOT_REGISTERED'
    assert not result.can_run_scenarios


def test_registered_parameters_allow_scenarios_but_not_single_class():
    result = validate(register(synthetic_doc()))
    assert result.run_mode == 'SCENARIO_REGISTERED', result.errors
    assert result.can_run_scenarios and not result.can_emit_display_class


def test_registration_must_precede_run():
    result = validate(register(synthetic_doc(), at=RUN_AT + timedelta(seconds=1)))
    assert 'REGISTERED_AT_NOT_BEFORE_RUN_STARTED_AT' in result.errors
    assert not result.can_run_scenarios


def test_registration_requires_timezone():
    doc = register(synthetic_doc())
    doc['registration']['registered_at'] = '2029-12-31T00:00:00'
    assert has(validate(doc).errors, 'NAIVE_DATETIME_REQUIRES_TIMEZONE')


def test_parameter_hash_detects_changes_after_registration():
    doc = register(synthetic_doc())
    doc['scenarios'][0]['lambda'] = 0.75
    result = validate(doc)
    assert 'PARAMETER_FILE_SHA256_MISMATCH' in result.errors
    assert not result.can_run_scenarios


def test_briefing_hash_must_match():
    doc = register(synthetic_doc())
    doc['registration']['briefing_doc_sha256'] = '0' * 64
    assert 'BRIEFING_DOC_SHA256_MISMATCH' in validate(doc).errors


def test_hash_excludes_status_registration_and_approval():
    doc = synthetic_doc()
    h = params.parameter_payload_sha256(doc)
    approve(register(doc))
    assert params.parameter_payload_sha256(doc) == h


def test_declared_status_cannot_exceed_conditions():
    doc = register(synthetic_doc())
    doc['parameter_status'] = 'APPROVED'
    result = validate(doc)
    assert has(result.errors, 'DECLARED_STATUS_NOT_SUPPORTED:APPROVED>SCENARIO_REGISTERED')
    assert result.effective_status == 'SCENARIO_REGISTERED'
    assert not result.can_emit_display_class


def test_approved_requires_admin_approval_before_run():
    result = validate(approve(register(synthetic_doc())))
    assert result.run_mode == 'APPROVED', result.errors
    assert result.can_emit_display_class
    late = validate(approve(register(synthetic_doc()), at=RUN_AT + timedelta(hours=1)))
    assert 'APPROVED_AT_NOT_BEFORE_RUN_STARTED_AT' in late.errors
    assert not late.can_emit_display_class


def test_approved_at_cannot_precede_registered_at():
    doc = register(synthetic_doc(), at=RUN_AT - timedelta(hours=2))
    result = validate(approve(doc, at=RUN_AT - timedelta(hours=3)))
    assert 'APPROVED_AT_BEFORE_REGISTERED_AT' in result.errors
    assert not result.can_emit_display_class
    assert result.approval_audit['approved_not_before_registered'] is False


def test_approved_at_equal_to_registered_at_is_allowed():
    at = RUN_AT - timedelta(hours=2)
    result = validate(approve(register(synthetic_doc(), at=at), at=at))
    assert result.run_mode == 'APPROVED', result.errors


def test_approved_at_equal_to_run_started_at_is_allowed():
    doc = register(synthetic_doc(), at=RUN_AT - timedelta(hours=1))
    result = validate(approve(doc, at=RUN_AT))
    assert result.run_mode == 'APPROVED', result.errors


def test_approved_at_requires_timezone():
    doc = approve(register(synthetic_doc()))
    doc['approval']['approved_at'] = '2029-12-31T23:00:00'
    result = validate(doc)
    assert 'NAIVE_DATETIME_REQUIRES_TIMEZONE:approval.approved_at' in result.errors
    assert not result.can_emit_display_class


def test_approval_must_link_to_current_parameter_hash():
    doc = approve(register(synthetic_doc()))
    doc['approval']['approved_parameter_file_sha256'] = 'f' * 64
    result = validate(doc)
    assert 'APPROVED_PARAMETER_FILE_SHA256_MISMATCH' in result.errors
    assert result.approval_audit['approval_hash_matches_current_payload'] is False


def test_approval_must_link_to_current_scenario_block_hash():
    doc = approve(register(synthetic_doc()))
    doc['approval']['approved_scenario_block_sha256'] = 'f' * 64
    result = validate(doc)
    assert 'APPROVED_SCENARIO_BLOCK_SHA256_MISMATCH' in result.errors
    assert result.approval_audit['approval_scenario_hash_matches_current_block'] is False


def test_approval_audit_records_hash_link():
    result = validate(approve(register(synthetic_doc())))
    audit = result.approval_audit
    assert audit['approved_scenario_id'] == '기준' and audit['approved_scenario_found']
    assert audit['approved_parameter_file_sha256'] == audit['parameter_file_sha256_computed']
    assert audit['registration_hash_matches_current_payload'] and audit['approval_hash_matches_current_payload']
    assert len(audit['approved_scenario_block_sha256_computed']) == 64
    assert audit['approved_scenario_block_sha256_declared'] == audit['approved_scenario_block_sha256_computed']
    assert audit['approval_scenario_hash_matches_current_block']
    assert audit['approved_not_before_registered'] is True


def test_template_has_approval_hash_key():
    doc = params.load_parameter_file(TEMPLATE)
    assert 'approved_parameter_file_sha256' in doc['approval']
    assert 'approved_scenario_block_sha256' in doc['approval']
    assert 'approval.approved_parameter_file_sha256' in validate(doc, present=False).missing_approval_fields
    assert 'approval.approved_scenario_block_sha256' in validate(doc, present=False).missing_approval_fields


def test_register_frame_marks_missing_values():
    doc = params.load_parameter_file(TEMPLATE)
    frame = params.parameter_register_frame(doc, validate(doc, present=False))
    assert len(frame) == len(config.SCENARIO_IDS) * 15
    assert frame['value_status'].eq('MISSING').all()


def test_registered_pilot_matches_gpt_sol_decision_and_is_not_approved():
    path = ROOT / config.PATHS['params']
    doc = params.load_parameter_file(path)
    expected = {
        '기준': ({'g1': .2, 'g2': .2, 'g3': .3, 'g4': .3}, .5),
        '고용중시': ({'g1': .3, 'g2': .3, 'g3': .2, 'g4': .2}, .6),
        '지속성중시': ({'g1': .2, 'g2': .2, 'g3': .2, 'g4': .4}, .6),
    }
    assert doc['parameter_set_id'] == 'changwon-electre-pilot-v1'
    assert doc['parameter_status'] == 'SCENARIO_REGISTERED'
    assert all(v is None for v in doc['approval'].values())
    assert 'display_class' not in doc and 'approved_scenario_id' not in doc
    for s in doc['scenarios']:
        weights, lam = expected[s['scenario_id']]
        assert s['weights'] == weights and s['lambda'] == lam
        assert s['profiles'] == {'b1': {'g1': 100, 'g2': 2.0, 'g3': 5.0, 'g4': 2},
                                 'b2': {'g1': 500, 'g2': 5.0, 'g3': 10.0, 'g4': 4}}
        assert s['delta_emp'] == 0.0 and s['require_employment_evidence'] is True
    result = params.validate_parameters(doc, analysis_window_n=WINDOW_N,
                                        run_started_at=datetime.now(timezone.utc),
                                        briefing_path=BRIEFING,
                                        parameter_file_label=str(path), present=True)
    assert result.run_mode == 'SCENARIO_REGISTERED' and not result.errors
    assert result.parameter_file_sha256_computed == doc['registration']['parameter_file_sha256']
