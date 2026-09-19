# -*- coding: utf-8 -*-
"""ELECTRE 파라미터 파일 검증과 등록·승인 상태 판정.

- 값이 비어 있으면 채우지 않는다(기본값 주입 없음). 비어 있는 필드를 그대로 보고한다.
- parameter_file_sha256은 parameter_status·registration·approval 블록을 제외한 파라미터 본문을
  정규화 JSON(키 정렬, UTF-8)으로 직렬화한 SHA-256이다. 파일이 자기 자신의 해시를 담을 수 없기 때문이다.
- 공모전 팀의 사전등록(SCENARIO_REGISTERED)은 실제 행정 승인(APPROVED)이 아니다.
"""
import copy
import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import pandas as pd
import yaml

from . import config, inputs

HASH_EXCLUDED_KEYS = ('parameter_status', 'registration', 'approval')
TOP_KEYS = ('model_spec_version', 'parameter_set_id', 'parameter_status', 'fixed', 'scenarios',
            'registration', 'approval')
FIXED_EXPECTED = {'q': 0, 'p': 0, 'veto': None, 'assignment_rule': 'pessimistic',
                  'missing_rule': 'complete_case_no_renormalization'}
SCENARIO_KEYS = ('scenario_id', 'weights', 'profiles', 'lambda', 'delta_emp', 'require_employment_evidence')
REGISTRATION_KEYS = ('registered_at', 'registered_by', 'briefing_doc_sha256', 'parameter_file_sha256')
APPROVAL_KEYS = ('approved_scenario_id', 'approved_parameter_file_sha256', 'approved_scenario_block_sha256',
                 'approver_name', 'approver_role', 'approver_org', 'approved_at', 'approval_reference')
WEIGHT_SUM_TOLERANCE = 1e-9


@dataclass
class ParameterValidation:
    parameter_file: str
    parameter_file_present: bool
    declared_status: object = None
    effective_status: str = 'DRAFT'
    run_mode: str = config.RUN_BLOCKED_MISSING
    missing_parameter_fields: list = field(default_factory=list)
    missing_registration_fields: list = field(default_factory=list)
    missing_approval_fields: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    scenarios: list = field(default_factory=list)
    parameter_set_id: object = None
    parameter_file_sha256_declared: object = None
    parameter_file_sha256_computed: object = None
    briefing_doc_sha256_declared: object = None
    briefing_doc_sha256_actual: object = None
    registered_at: object = None
    approved_at: object = None
    approved_scenario_id: object = None
    approval_audit: dict = field(default_factory=dict)
    run_started_at: object = None

    @property
    def can_run_scenarios(self):
        return self.run_mode in ('SCENARIO_REGISTERED', 'APPROVED')

    @property
    def can_emit_display_class(self):
        return self.run_mode == 'APPROVED'

    def to_dict(self):
        out = asdict(self)
        out['can_run_scenarios'] = self.can_run_scenarios
        out['can_emit_display_class'] = self.can_emit_display_class
        return out


def load_parameter_file(path):
    with open(path, encoding='utf-8') as f:
        doc = yaml.safe_load(f)
    if not isinstance(doc, dict):
        raise ValueError(f'파라미터 파일 최상위가 매핑이 아닙니다: {path}')
    return doc


def parameter_payload_sha256(doc):
    payload = {k: v for k, v in doc.items() if k not in HASH_EXCLUDED_KEYS}
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str)
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def scenario_block_sha256(block):
    """승인 대상 시나리오 블록의 정규화 JSON SHA-256."""
    if not isinstance(block, dict):
        return None
    text = json.dumps(block, ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str)
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _parse_time(value, path, errors):
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            errors.append(f'INVALID_DATETIME:{path}')
            return None
    else:
        errors.append(f'INVALID_DATETIME:{path}')
        return None
    if parsed.tzinfo is None:
        errors.append(f'NAIVE_DATETIME_REQUIRES_TIMEZONE:{path}')
        return None
    return parsed


def _check_criterion_dict(block, path, errors, missing, check_value):
    if not isinstance(block, dict):
        if block is None:
            missing.extend(f'{path}.{g}' for g in config.CRITERIA)
        else:
            errors.append(f'INVALID_TYPE:{path}')
        return {}
    extra = sorted(set(block) - set(config.CRITERIA))
    if extra:
        errors.append(f'UNKNOWN_CRITERIA:{path}:{extra}')
    values = {}
    for g in config.CRITERIA:
        if g not in block:
            errors.append(f'MISSING_KEY:{path}.{g}')
        elif block[g] is None:
            missing.append(f'{path}.{g}')
        elif not _is_number(block[g]):
            errors.append(f'INVALID_NUMBER:{path}.{g}')
        else:
            check_value(g, block[g])
            values[g] = block[g]
    return values


def _validate_scenario(s, analysis_window_n, errors, warnings, missing):
    sid = s.get('scenario_id')
    p = f'scenarios[{sid}]'
    for key in SCENARIO_KEYS:
        if key not in s:
            errors.append(f'MISSING_KEY:{p}.{key}')

    def weight_check(g, v):
        if v <= 0:
            errors.append(f'WEIGHT_NOT_POSITIVE:{p}.weights.{g}')

    weights = _check_criterion_dict(s.get('weights'), f'{p}.weights', errors, missing, weight_check)
    if len(weights) == len(config.CRITERIA):
        if abs(sum(weights.values()) - 1) > WEIGHT_SUM_TOLERANCE:
            errors.append(f'WEIGHT_SUM_NOT_ONE:{p}.weights')

    profiles = s.get('profiles')
    if not isinstance(profiles, dict):
        errors.append(f'INVALID_TYPE:{p}.profiles')
        profiles = {}
    limits = {'g1': (0, math.inf), 'g2': (0, 100), 'g3': (0, 100), 'g4': (0, analysis_window_n)}
    bounds = {}
    for h in ('b1', 'b2'):
        if h not in profiles:
            errors.append(f'MISSING_KEY:{p}.profiles.{h}')

        def range_check(g, v, h=h):
            lo, hi = limits[g]
            if not lo <= v <= hi:
                errors.append(f'BOUNDARY_OUT_OF_RANGE:{p}.profiles.{h}.{g}')
            if v == 0:
                warnings.append(f'BOUNDARY_ZERO_ALWAYS_SATISFIED:{p}.profiles.{h}.{g}')
            if g == 'g4' and float(v) != int(v):
                warnings.append(f'NON_INTEGER_G4_BOUNDARY:{p}.profiles.{h}.g4')

        bounds[h] = _check_criterion_dict(profiles.get(h), f'{p}.profiles.{h}', errors, missing, range_check)
    for g in config.CRITERIA:
        if g in bounds.get('b1', {}) and g in bounds.get('b2', {}) and bounds['b1'][g] > bounds['b2'][g]:
            errors.append(f'PROFILE_ORDER_VIOLATION_B1_GT_B2:{p}.{g}')
    if 'g4' in bounds.get('b1', {}) and bounds['b1']['g4'] < 2:
        errors.append(f'B1_G4_BELOW_2:{p}.profiles.b1.g4')
    if 'g4' in bounds.get('b2', {}) and bounds['b2']['g4'] >= analysis_window_n - 1:
        warnings.append(f'WINDOW_SATURATION_WARNING:{p}.profiles.b2.g4')

    lam = s.get('lambda')
    if 'lambda' in s:
        if lam is None:
            missing.append(f'{p}.lambda')
        elif not _is_number(lam):
            errors.append(f'INVALID_NUMBER:{p}.lambda')
        elif not 0.5 <= lam <= 1:
            errors.append(f'LAMBDA_OUT_OF_RANGE:{p}.lambda')

    delta = s.get('delta_emp')
    if 'delta_emp' in s:
        if delta is None:
            missing.append(f'{p}.delta_emp')
        elif not _is_number(delta):
            errors.append(f'INVALID_NUMBER:{p}.delta_emp')
        elif delta < 0:
            errors.append(f'DELTA_EMP_NEGATIVE:{p}.delta_emp')

    if 'require_employment_evidence' in s:
        gate = s['require_employment_evidence']
        if gate is None:
            missing.append(f'{p}.require_employment_evidence')
        elif not isinstance(gate, bool):
            errors.append(f'INVALID_BOOLEAN:{p}.require_employment_evidence')


def validate_parameters(doc, *, analysis_window_n, run_started_at, briefing_path,
                        parameter_file_label, present=True):
    """파라미터 문서를 검증하고 실행 가능 상태를 판정한다. 문서를 수정하지 않는다."""
    original = copy.deepcopy(doc)
    result = ParameterValidation(parameter_file=parameter_file_label, parameter_file_present=present,
                                 run_started_at=run_started_at.isoformat())
    errors, warnings = result.errors, result.warnings
    missing = result.missing_parameter_fields

    for key in TOP_KEYS:
        if key not in doc:
            errors.append(f'MISSING_KEY:{key}')
    result.parameter_set_id = doc.get('parameter_set_id')
    if doc.get('model_spec_version') not in (None, config.MODEL_SPEC_VERSION):
        errors.append('MODEL_SPEC_VERSION_MISMATCH')

    fixed = doc.get('fixed') if isinstance(doc.get('fixed'), dict) else {}
    for key, expected in FIXED_EXPECTED.items():
        if key not in fixed:
            errors.append(f'MISSING_KEY:fixed.{key}')
        elif fixed[key] != expected or isinstance(fixed[key], bool):
            errors.append(f'FIXED_SETTING_VIOLATION:fixed.{key}')
    direction = fixed.get('criteria_direction')
    if direction != {g: config.CRITERION_DIRECTION for g in config.CRITERIA}:
        errors.append('FIXED_SETTING_VIOLATION:fixed.criteria_direction')

    scenarios = doc.get('scenarios')
    if not isinstance(scenarios, list):
        errors.append('INVALID_TYPE:scenarios')
        scenarios = []
    ids = [s.get('scenario_id') for s in scenarios if isinstance(s, dict)]
    if len(ids) != len(scenarios) or sorted(ids) != sorted(config.SCENARIO_IDS):
        errors.append(f'SCENARIO_ID_SET_MISMATCH:{ids}')
    for s in scenarios:
        if isinstance(s, dict):
            _validate_scenario(s, analysis_window_n, errors, warnings, missing)

    # 등록 조건
    registration = doc.get('registration') if isinstance(doc.get('registration'), dict) else {}
    for key in REGISTRATION_KEYS:
        if key not in registration:
            errors.append(f'MISSING_KEY:registration.{key}')
        elif registration[key] is None:
            result.missing_registration_fields.append(f'registration.{key}')
    registered_at = _parse_time(registration.get('registered_at'), 'registration.registered_at', errors)
    result.registered_at = registered_at.isoformat() if registered_at else None
    result.parameter_file_sha256_computed = parameter_payload_sha256(doc)
    result.parameter_file_sha256_declared = registration.get('parameter_file_sha256')
    briefing_path = Path(briefing_path)
    result.briefing_doc_sha256_actual = (inputs.sha256_text_file(briefing_path)
                                         if briefing_path.is_file() else None)
    result.briefing_doc_sha256_declared = registration.get('briefing_doc_sha256')
    registered = False
    if not result.missing_registration_fields and registered_at is not None:
        registered = True
        if not registered_at < run_started_at:
            errors.append('REGISTERED_AT_NOT_BEFORE_RUN_STARTED_AT')
            registered = False
        if result.briefing_doc_sha256_declared != result.briefing_doc_sha256_actual:
            errors.append('BRIEFING_DOC_SHA256_MISMATCH')
            registered = False
        if result.parameter_file_sha256_declared != result.parameter_file_sha256_computed:
            errors.append('PARAMETER_FILE_SHA256_MISMATCH')
            registered = False

    # 승인 조건(실제 행정 담당자의 승인정보)
    approval = doc.get('approval') if isinstance(doc.get('approval'), dict) else {}
    for key in APPROVAL_KEYS:
        if key not in approval:
            errors.append(f'MISSING_KEY:approval.{key}')
        elif approval[key] is None:
            result.missing_approval_fields.append(f'approval.{key}')
    approved_at = _parse_time(approval.get('approved_at'), 'approval.approved_at', errors)
    result.approved_at = approved_at.isoformat() if approved_at else None
    result.approved_scenario_id = approval.get('approved_scenario_id')
    approved = False
    approved_hash = approval.get('approved_parameter_file_sha256')
    approved_block = next((s for s in scenarios if isinstance(s, dict)
                           and s.get('scenario_id') == result.approved_scenario_id), None)
    approved_block_hash = scenario_block_sha256(approved_block)
    declared_block_hash = approval.get('approved_scenario_block_sha256')
    if approved_at is not None and registered_at is not None and approved_at < registered_at:
        errors.append('APPROVED_AT_BEFORE_REGISTERED_AT')
    if not result.missing_approval_fields and approved_at is not None:
        approved = True
        if approved_at > run_started_at:
            errors.append('APPROVED_AT_NOT_BEFORE_RUN_STARTED_AT')
            approved = False
        if registered_at is None or approved_at < registered_at:
            approved = False
        if result.approved_scenario_id not in ids:
            errors.append('APPROVED_SCENARIO_ID_UNKNOWN')
            approved = False
        if approved_hash != result.parameter_file_sha256_computed:
            errors.append('APPROVED_PARAMETER_FILE_SHA256_MISMATCH')
            approved = False
        if declared_block_hash != approved_block_hash:
            errors.append('APPROVED_SCENARIO_BLOCK_SHA256_MISMATCH')
            approved = False
    result.approval_audit = {
        'approved_scenario_id': result.approved_scenario_id,
        'approved_scenario_found': approved_block is not None,
        'approved_scenario_block_sha256_declared': declared_block_hash,
        'approved_scenario_block_sha256_computed': approved_block_hash,
        'parameter_file_sha256_computed': result.parameter_file_sha256_computed,
        'registered_parameter_file_sha256': result.parameter_file_sha256_declared,
        'approved_parameter_file_sha256': approved_hash,
        'registration_hash_matches_current_payload':
            result.parameter_file_sha256_declared == result.parameter_file_sha256_computed,
        'approval_hash_matches_current_payload': approved_hash == result.parameter_file_sha256_computed,
        'approval_scenario_hash_matches_current_block': declared_block_hash == approved_block_hash,
        'registered_at': result.registered_at,
        'approved_at': result.approved_at,
        'approved_not_before_registered': (None if approved_at is None or registered_at is None
                                           else bool(approved_at >= registered_at)),
    }

    numeric_complete = not missing
    computed_rank = 0
    if numeric_complete and registered:
        computed_rank = 2 if approved else 1
    declared = doc.get('parameter_status')
    result.declared_status = declared
    if declared not in config.PARAMETER_STATUSES:
        errors.append(f'INVALID_PARAMETER_STATUS:{declared!r}')
        declared_rank = 0
    else:
        declared_rank = config.PARAMETER_STATUSES.index(declared)
        if declared_rank > computed_rank:
            errors.append(f'DECLARED_STATUS_NOT_SUPPORTED:{declared}>'
                          f'{config.PARAMETER_STATUSES[computed_rank]}')
    result.effective_status = config.PARAMETER_STATUSES[min(declared_rank, computed_rank)]

    if not present:
        result.run_mode = config.RUN_BLOCKED_MISSING
    elif errors:
        result.run_mode = config.RUN_BLOCKED_INVALID
    elif missing:
        result.run_mode = config.RUN_BLOCKED_MISSING
    elif result.effective_status == 'DRAFT':
        result.run_mode = config.RUN_BLOCKED_NOT_REGISTERED
    else:
        result.run_mode = result.effective_status
    if result.can_run_scenarios:
        result.scenarios = [copy.deepcopy(s) for s in scenarios]
    if doc != original:
        raise AssertionError('파라미터 검증 중 문서가 변경되었습니다(기본값 주입 금지).')
    return result


def parameter_register_frame(doc, validation):
    """파라미터 버전×시나리오×항목 등록부. 비어 있는 값은 MISSING으로 남긴다."""
    rows = []
    registration = doc.get('registration') or {}
    approval = doc.get('approval') or {}
    common = {
        'parameter_set_id': doc.get('parameter_set_id'),
        'parameter_file': validation.parameter_file,
        'parameter_file_present': validation.parameter_file_present,
        'declared_parameter_status': validation.declared_status,
        'effective_parameter_status': validation.effective_status,
        'run_mode': validation.run_mode,
        'registered_at': registration.get('registered_at'),
        'registered_by': registration.get('registered_by'),
        'briefing_doc_sha256': registration.get('briefing_doc_sha256'),
        'parameter_file_sha256': registration.get('parameter_file_sha256'),
        'approved_at': approval.get('approved_at'),
        'approved_scenario_id': approval.get('approved_scenario_id'),
        'approved_parameter_file_sha256': approval.get('approved_parameter_file_sha256'),
        'approved_scenario_block_sha256': approval.get('approved_scenario_block_sha256'),
        'approver_role': approval.get('approver_role'),
        'approver_org': approval.get('approver_org'),
        'model_spec_version': config.MODEL_SPEC_VERSION,
    }

    def add(scenario_id, parameter, criterion, boundary, value):
        rows.append({**common, 'scenario_id': scenario_id, 'parameter': parameter,
                     'criterion': criterion, 'boundary': boundary,
                     'value': value, 'value_status': 'MISSING' if value is None else 'PROVIDED'})

    for s in doc.get('scenarios') or []:
        if not isinstance(s, dict):
            continue
        sid = s.get('scenario_id')
        for g in config.CRITERIA:
            add(sid, 'weight', g, None, (s.get('weights') or {}).get(g))
        for h in ('b1', 'b2'):
            for g in config.CRITERIA:
                add(sid, 'profile', g, h, ((s.get('profiles') or {}).get(h) or {}).get(g))
        add(sid, 'lambda', None, None, s.get('lambda'))
        add(sid, 'delta_emp', None, None, s.get('delta_emp'))
        add(sid, 'require_employment_evidence', None, None, s.get('require_employment_evidence'))
    return pd.DataFrame(rows)
