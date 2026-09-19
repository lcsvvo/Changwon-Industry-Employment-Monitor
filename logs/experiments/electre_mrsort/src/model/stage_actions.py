# -*- coding: utf-8 -*-
"""단계별 후속 행동 설정 검증.

분석 결과(점검단계)와 정책 실행을 구분한다. 담당 역할·처리기한·필수 확인·산출물은 실제 기관이
정해야 하며 모형이 채우지 않는다. 빈 설정, 누락·중복·알 수 없는 단계, 빈 필드, 잘못된 자료형은
모두 오류이며 어떤 경우에도 APPROVED가 되지 않는다.
"""
from collections import Counter

from . import config

STATUS_APPROVED = 'APPROVED'
STATUS_POLICY = 'POLICY_DECISION_REQUIRED'
STATUS_INVALID = 'INVALID_STAGE_ACTIONS'
STAGE_APPROVAL_VALUES = (STATUS_POLICY, STATUS_APPROVED)
TEXT_FIELDS = ('owner_role', 'deadline_rule')
LIST_FIELDS = ('required_checks', 'required_output')


def _check_field(item, key, path, errors, missing):
    if key not in item:
        errors.append(f'MISSING_KEY:{path}.{key}')
        return
    value = item[key]
    if value is None:
        missing.append(f'{path}.{key}')
    elif key in TEXT_FIELDS:
        if not isinstance(value, str):
            errors.append(f'INVALID_TYPE:{path}.{key}')
        elif not value.strip():
            errors.append(f'EMPTY_FIELD:{path}.{key}')
    elif not isinstance(value, list):
        errors.append(f'INVALID_TYPE:{path}.{key}')
    elif not value:
        errors.append(f'EMPTY_FIELD:{path}.{key}')
    elif any(not isinstance(x, str) or not x.strip() for x in value):
        errors.append(f'INVALID_LIST_ITEM:{path}.{key}')


def validate_stage_actions(doc, source=None):
    """단계별 후속 행동 설정 문서를 검증한다. 문서를 수정하지 않는다."""
    errors, missing = [], []
    counts = Counter()
    approvals = []
    stages = None
    if not isinstance(doc, dict):
        errors.append('INVALID_TYPE:document')
    elif 'stages' not in doc:
        errors.append('MISSING_KEY:stages')
    elif not isinstance(doc['stages'], list):
        errors.append('INVALID_TYPE:stages')
    else:
        stages = doc['stages']
        if not stages:
            errors.append('EMPTY_STAGES')

    known = config.REQUIRED_STAGES + config.OPTIONAL_STAGES
    for i, item in enumerate(stages or []):
        if not isinstance(item, dict):
            errors.append(f'INVALID_TYPE:stages[{i}]')
            approvals.append(False)
            continue
        name = item.get('stage')
        if not isinstance(name, str):
            errors.append(f'INVALID_STAGE_NAME:stages[{i}]')
            approvals.append(False)
            continue
        if name not in known:
            errors.append(f'UNKNOWN_STAGE:{name}')
            approvals.append(False)
            continue
        counts[name] += 1
        path = f'stages[{name}]'
        for key in TEXT_FIELDS + LIST_FIELDS:
            _check_field(item, key, path, errors, missing)
        expected_procedure = config.STAGE_PROCEDURE_TYPES[name]
        if item.get('procedure_type') != expected_procedure:
            errors.append(f'PROCEDURE_TYPE_MISMATCH:{path}.procedure_type={item.get("procedure_type")!r}'
                          f'(expected {expected_procedure})')
        status = item.get('approval_status')
        if 'approval_status' not in item:
            errors.append(f'MISSING_KEY:{path}.approval_status')
        elif status not in STAGE_APPROVAL_VALUES:
            errors.append(f'INVALID_APPROVAL_STATUS:{path}.approval_status')
        approvals.append(status == STATUS_APPROVED)

    for name in config.REQUIRED_STAGES:
        if counts[name] == 0:
            errors.append(f'MISSING_STAGE:{name}')
        elif counts[name] > 1:
            errors.append(f'DUPLICATE_STAGE:{name}')
    for name in config.OPTIONAL_STAGES:
        if counts[name] > 1:
            errors.append(f'DUPLICATE_STAGE:{name}')

    all_approved = bool(approvals) and all(approvals)
    if errors:
        status = STATUS_INVALID
    elif missing or not all_approved:
        status = STATUS_POLICY
    else:
        status = STATUS_APPROVED
    return {'status': status, 'source': source, 'errors': errors, 'missing_fields': missing,
            'stage_counts': dict(counts), 'undetermined_included': counts.get('UNDETERMINED', 0) == 1}
