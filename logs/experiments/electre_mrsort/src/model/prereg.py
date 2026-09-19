# -*- coding: utf-8 -*-
"""재검증 사전등록(pre-registration) 문서 로드·스키마 검증·등록 게이트.

veto와 q·p 재보정 같은 ELECTRE 고유 기제는 이 모듈이 REGISTERED 상태를 확인해 준
사전등록 문서 없이는 공식 파이프라인에서 쓰지 않는다. 이 모듈은 문서를 읽고 검증할
뿐 판정 파라미터를 스스로 만들거나 조정하지 않는다.
"""
import hashlib
import json
from pathlib import Path

import yaml

from . import config, params

REQUIRED_KEYS = ('prereg_spec_version', 'prereg_status', 'base_parameter_sha256', 'reference_cases',
                 'parameter_space', 'qp_derivation', 'veto_candidates', 'perturbation', 'acceptance',
                 'registration',
                 # config/model_revalidation_prereg.yaml 스키마 보강분(1-C 확정 스키마 반영)
                 'invalidated_gates', 'reference_case_rule', 'veto_relation', 'veto_missing_rule',
                 'veto_selection_rule', 'concurrent_indicators', 'supporting_temporal_targets',
                 'uncertainty_reporting', 'discriminating_sample_definition',
                 # 개정 이력(빈 리스트 허용) — Phase 2 이후 사전등록 개정분
                 'amendments')
REGISTERED_STATUS = 'REGISTERED'

# veto_candidates 중 enabled: true인 항목이 반드시 채워야 하는 필드
VETO_CANDIDATE_REQUIRED_WHEN_ENABLED = ('boundary', 'criterion', 'threshold_value', 'unit', 'rationale')

# qp_derivation의 *_source 필드가 참조할 수 있는, 실제로 구현된 도출자 이름의 집합.
# 이 집합 밖의 이름을 적으면 코드에 없는 도출자를 가리키는 것이므로 스키마 오류로 취급한다.
KNOWN_QP_DERIVATION_SOURCES = frozenset({
    'vintage_employment_abs_p90', 'vintage_employment_pct_p90',
    'nominal_ppi_adjusted_gap_p75', 'nominal_ppi_adjusted_gap_p50',
})

# acceptance.S1_evaluation_space가 가질 수 있는 값(AM3). 합격 판정은 이 중
# reference_compatible_subspace로만 하고, 나머지 둘은 보고 전용이다.
KNOWN_S1_EVALUATION_SPACES = frozenset({
    'reference_compatible_subspace', 'full_parameter_space', 'crisp_subspace',
})


class PreregSchemaError(ValueError):
    """사전등록 문서가 필수 스키마를 충족하지 않을 때."""


class PreregNotRegisteredError(RuntimeError):
    """사전등록이 REGISTERED 상태로 확정되지 않았을 때."""


class BaseParameterMismatchError(RuntimeError):
    """사전등록 문서의 base_parameter_sha256가 현재 기준파라미터 파일과 다를 때."""


def _validate_veto_candidates(doc, errors):
    for item in doc.get('veto_candidates') or []:
        if not isinstance(item, dict):
            errors.append(f'veto_candidates 항목이 매핑이 아닙니다: {item!r}')
            continue
        if not item.get('enabled'):
            continue
        cid = item.get('id', '?')
        missing = [k for k in VETO_CANDIDATE_REQUIRED_WHEN_ENABLED if item.get(k) is None]
        if missing:
            errors.append(f'veto_candidates[{cid}]는 enabled: true인데 다음 필드가 없습니다: {missing}')


def _validate_s1_evaluation_space(doc, errors):
    acceptance = doc.get('acceptance')
    if not isinstance(acceptance, dict) or 'S1_evaluation_space' not in acceptance:
        return  # 구버전 문서 호환: 이 키가 아예 없으면(AM3 이전) 여기서는 검사하지 않는다
    value = acceptance['S1_evaluation_space']
    if value not in KNOWN_S1_EVALUATION_SPACES:
        errors.append(
            f'acceptance.S1_evaluation_space={value!r}가 허용값 밖입니다: {sorted(KNOWN_S1_EVALUATION_SPACES)}')


def _validate_amendments_content(doc, errors):
    """amendments[].content가 있으면 dict여야 한다(자유 텍스트가 아니라 구조화된 개정 내용)."""
    for a in doc.get('amendments') or []:
        if not isinstance(a, dict):
            errors.append(f'amendments 항목이 매핑이 아닙니다: {a!r}')
            continue
        if 'content' in a and not isinstance(a['content'], dict):
            errors.append(f"amendments[{a.get('id', '?')}].content가 매핑이 아닙니다: {type(a['content'])!r}")


def _iter_amendment_content_key(doc, key):
    """amendments[].content 중 주어진 key를 가진 첫 항목의 값을 돌려준다(없으면 None)."""
    for a in doc.get('amendments') or []:
        content = a.get('content')
        if isinstance(content, dict) and key in content:
            return content[key], a.get('id')
    return None, None


def validate_virtual_reference_cases(doc):
    """amendments[].content.virtual_reference_cases의 각 항목이 profile(g1~g4 전부)·
    relation·stage·rationale을 갖는지 검증한다. 없으면(해당 amendment가 아직 없으면)
    통과로 본다(선택적 확장분이므로). 위반 시 PreregSchemaError.
    """
    cases, amendment_id = _iter_amendment_content_key(doc, 'virtual_reference_cases')
    if cases is None:
        return True
    errors = []
    for item in cases:
        if not isinstance(item, dict):
            errors.append(f'virtual_reference_cases 항목이 매핑이 아닙니다: {item!r}')
            continue
        cid = item.get('id', '?')
        profile = item.get('profile')
        if not isinstance(profile, dict) or not all(j in profile for j in config.CRITERIA):
            errors.append(f'virtual_reference_cases[{cid}].profile이 g1~g4를 전부 갖지 않습니다: {profile!r}')
        for field in ('relation', 'stage', 'rationale'):
            if item.get(field) is None:
                errors.append(f'virtual_reference_cases[{cid}]에 {field}가 없습니다')
    if errors:
        raise PreregSchemaError(f'{amendment_id}.virtual_reference_cases 스키마 오류: ' + '; '.join(errors))
    return True


def validate_interval_acceptance(doc):
    """amendments[].content.interval_acceptance의 각 항목이 id·definition·threshold를
    갖는지 검증한다. 없으면 통과로 본다. 위반 시 PreregSchemaError.
    """
    items, amendment_id = _iter_amendment_content_key(doc, 'interval_acceptance')
    if items is None:
        return True
    errors = []
    for item in items:
        if not isinstance(item, dict):
            errors.append(f'interval_acceptance 항목이 매핑이 아닙니다: {item!r}')
            continue
        iid = item.get('id', '?')
        for field in ('id', 'definition', 'threshold'):
            if item.get(field) is None:
                errors.append(f'interval_acceptance[{iid}]에 {field}가 없습니다')
    if errors:
        raise PreregSchemaError(f'{amendment_id}.interval_acceptance 스키마 오류: ' + '; '.join(errors))
    return True


def _validate_qp_derivation_sources(doc, errors):
    qp = doc.get('qp_derivation')
    if not isinstance(qp, dict):
        return
    for crit_key, spec in qp.items():
        if not isinstance(spec, dict):
            continue  # source_vintage, rounding 같은 기준 외 항목
        for field, value in spec.items():
            if field.endswith('_source') and value not in KNOWN_QP_DERIVATION_SOURCES:
                errors.append(
                    f'qp_derivation.{crit_key}.{field}={value!r}가 구현된 도출자 집합에 없습니다: '
                    f'{sorted(KNOWN_QP_DERIVATION_SOURCES)}')


def load(path):
    """yaml을 읽고 스키마를 검증한다.

    필수 키 존재, veto_candidates(enabled=true 항목의 필수 필드), qp_derivation의
    *_source 값이 구현된 도출자 이름 집합에 속하는지까지 확인한다. 그 밖의 의미론적
    타당성(예: parameter_space 범위의 적절성)은 검증하지 않는다.
    """
    doc = yaml.safe_load(Path(path).read_text(encoding='utf-8'))
    if not isinstance(doc, dict):
        raise PreregSchemaError(f'사전등록 파일 최상위가 매핑이 아닙니다: {path}')
    missing = [k for k in REQUIRED_KEYS if k not in doc]
    if missing:
        raise PreregSchemaError(f'사전등록 파일에 필수 키가 없습니다: {missing} ({path})')
    errors = []
    _validate_veto_candidates(doc, errors)
    _validate_qp_derivation_sources(doc, errors)
    _validate_s1_evaluation_space(doc, errors)
    _validate_amendments_content(doc, errors)
    if errors:
        raise PreregSchemaError(f'사전등록 파일 스키마 오류 ({path}): ' + '; '.join(errors))
    return doc


def payload_sha256(doc):
    """registration 블록을 제외한 나머지 내용의 SHA-256(정규화 JSON, 등록 시점 스냅샷 대조용)."""
    payload = {k: v for k, v in doc.items() if k != 'registration'}
    text = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def require_registered(doc):
    """REGISTERED 상태이고 등록 시점 해시가 현재 문서 내용과 같아야 통과한다.

    그렇지 않으면(DRAFT 상태이거나, 등록 이후 문서가 수정돼 해시가 어긋나면)
    PreregNotRegisteredError를 던진다.
    """
    registration = doc.get('registration') or {}
    status = doc.get('prereg_status')
    if status != REGISTERED_STATUS or registration.get('prereg_sha256') != payload_sha256(doc):
        raise PreregNotRegisteredError(
            '사전등록이 REGISTERED 상태가 아니거나 등록 시점 해시가 현재 문서 내용과 다릅니다.'
            f' (prereg_status={status!r})')


def check_base_parameter(doc, root):
    """doc['base_parameter_sha256']가 현재 config/electre_tri_b_params.yaml 해시와 다르면 중단한다."""
    base_doc = params.load_parameter_file(Path(root) / config.PATHS['params'])
    actual = params.parameter_payload_sha256(base_doc)
    declared = doc.get('base_parameter_sha256')
    if declared != actual:
        raise BaseParameterMismatchError(
            '사전등록 문서의 base_parameter_sha256가 현재 config/electre_tri_b_params.yaml과 다릅니다.'
            f' (declared={declared!r}, actual={actual!r})')


def check_parameter_space_bounds(doc, root):
    """parameter_space.p_upper[j]가 기준파라미터의 b1_j를 넘지 않는지 확인한다.

    p_j > b1_j이면 감소가 전혀 없는 행(g_j = 0)조차 최하위 경계에서 양의 부분
    concordance와 고용증거 게이트를 통과하게 되므로 허용하지 않는다(AM1 참조).
    먼저 세 시나리오의 b1이 서로 같은지 확인한다 — 다르면 "b1_j 하나"라는 전제 자체가
    깨진 것이므로 PreregSchemaError.
    """
    base_doc = params.load_parameter_file(Path(root) / config.PATHS['params'])
    b1_list = [dict(s['profiles']['b1']) for s in base_doc['scenarios']]
    if not all(b1 == b1_list[0] for b1 in b1_list):
        raise PreregSchemaError(
            f'세 시나리오의 b1 프로파일이 서로 달라 p_upper<=b1_j 제약의 전제가 성립하지 않습니다: {b1_list}')
    b1 = b1_list[0]
    p_upper = doc['parameter_space']['p_upper']
    violations = {j: (p_upper[j], b1[j]) for j in config.CRITERIA if float(p_upper[j]) > float(b1[j])}
    if violations:
        raise PreregSchemaError(
            f'parameter_space.p_upper가 b1_j를 초과합니다(p_j <= b1_j 위반): {violations}')
    return True
