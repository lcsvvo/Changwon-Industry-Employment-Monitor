# -*- coding: utf-8 -*-
"""PPI 보조분석 결합 — 후보별 PPI 조정 생산 YoY와 생산 방향 민감도.

- 조정식: ((1 + production_yoy/100) / (1 + ppi_yoy/100) - 1) * 100 (비율식, 단순 차감 아님)
- PPI는 공식 점검등급이 아니며 명목 g3를 대체하지 않는다.
- 복수 후보가 서로 다른 상태를 만들 수 있으므로 대안 상태는 집합(ppi_alt_state_set)으로 저장한다.
- 매핑 확정 여부는 선택 입력이다. 파일이 없거나 값이 비어 있어도 패널·카드는 생성하며,
  잘못된 confirmed 값은 NA로 숨기지 않고 INVALID_CONFIRMED_VALUE 상태와 검증 오류로 남긴다.
"""
import numpy as np
import pandas as pd

from eda import config as eda_config
from eda.panel import classify

from . import config

PPI_COLUMNS = [
    'ppi_source', 'ppi_candidate_n', 'ppi_candidate_items', 'ppi_yoy_min', 'ppi_yoy_max',
    'ppi_adjusted_prod_yoy_lower', 'ppi_adjusted_prod_yoy_upper', 'ppi_direction_status',
    'ppi_comparison_reason', 'ppi_alt_state_set', 'ppi_alt_state_all_same',
    'ppi_mapping_review_type', 'ppi_mapping_confirmed', 'ppi_mapping_confirmation_status',
]
EDA_STATUS_TO_CODE = {'모든 후보에서 유지': 'SAME_ALL', '모든 후보에서 반전': 'OPPOSITE_ALL',
                      '후보별 방향 다름': 'CANDIDATE_DEPENDENT', '0% 경계 변화': 'ZERO_BOUNDARY'}
AUX_DIRECTION_TO_CODE = {'유지': 'SAME_ALL', '모든 후보 유지': 'SAME_ALL', '반전': 'OPPOSITE_ALL',
                         '모든 후보 반전': 'OPPOSITE_ALL', '후보별 방향 다름': 'CANDIDATE_DEPENDENT',
                         '0% 경계': 'ZERO_BOUNDARY', '비교불가': 'NOT_COMPARABLE'}
AUX_CONFIRMATION_MATCH = {'미확정': ('NOT_CONFIRMED', 'PARTIALLY_CONFIRMED'), '확정': ('CONFIRMED',)}
AUX_REQUIRED_COLUMNS = ['업종', '국면', '생산YoY', '고용YoY', '가동률_사용값', '가동률YoY_pp_사용값',
                        '가동업체YoY', 'PPI_YoY_min', 'PPI_YoY_max', 'PPI조정_생산YoY_하한',
                        'PPI조정_생산YoY_상한', 'PPI_방향상태', 'PPI_매핑검토유형', 'PPI_매핑확정여부']
_MISSING, _INVALID = 'MISSING', 'INVALID'


def adjusted_production_yoy(production_yoy, ppi_yoy):
    """PPI 조정 생산 YoY(비율식). 0% 입력의 수치오차만 0으로 정리한다."""
    adj = ((1 + np.asarray(production_yoy, dtype=float) / 100)
           / (1 + np.asarray(ppi_yoy, dtype=float) / 100) - 1) * 100
    return np.where(np.abs(adj) < 1e-10, 0.0, adj)


def direction_status(nominal, adjusted):
    """명목 생산 YoY 부호와 후보별 PPI 조정 생산 YoY 부호 비교."""
    nom = np.sign(nominal)
    signs = np.sign(np.asarray(adjusted, dtype=float))
    if (signs == nom).all():
        return 'SAME_ALL'
    if nom != 0 and (signs == -nom).all():
        return 'OPPOSITE_ALL'
    if min(adjusted) < 0 < max(adjusted):
        return 'CANDIDATE_DEPENDENT'
    return 'ZERO_BOUNDARY'


def state_set_label(states):
    order = {s: i for i, s in enumerate(config.STATES6)}
    return '|'.join(sorted(set(states), key=order.get))


def is_missing(value):
    """스칼라 결측 판정(pd.NA를 bool 문맥에서 평가하지 않는다)."""
    if value is None:
        return True
    if isinstance(value, str):
        return False
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


# ---------------------------------------------------------------- 매핑 정보
def candidate_lookup(candidates, require_all=True):
    """후보별 PPI YoY 원자료를 (분기, 업종) → {후보: YoY}로 만들고 매핑 입력과 대조한다.

    require_all=False는 일부 업종만 담은 합성 후보표(단위테스트)를 허용한다. 이때도 포함된 업종의
    후보 구성은 매핑 입력과 같아야 한다.
    """
    c = candidates[['quarter', 'industry', 'ppi_item', 'ppi_yoy']].copy()
    c['quarter'] = c['quarter'].astype(str)
    if c.duplicated(['quarter', 'industry', 'ppi_item']).any():
        raise ValueError('PPI 후보 원자료에 분기·업종·후보 중복이 있습니다.')
    items = {ind: tuple(sorted(set(g))) for ind, g in c.groupby('industry')['ppi_item']}
    expected = {}
    for industry, _, item, _ in eda_config.PPI_MAPPING_ROWS:
        expected.setdefault(industry, set()).add(item)
    wrong = [k for k, v in items.items() if set(v) != expected.get(k)]
    absent = sorted(set(expected) - set(items)) if require_all else []
    if wrong or absent:
        raise ValueError(f'PPI 후보 원자료의 후보 구성이 src/eda 매핑 입력과 다릅니다: {wrong or absent}')
    lookup = {}
    for r in c.itertuples(index=False):
        lookup.setdefault((r.quarter, r.industry), {})[r.ppi_item] = r.ppi_yoy
    return items, lookup


def mapping_review_types(criteria, industries):
    """ppi_grade_criteria.csv의 매핑 검토유형을 업종별로 펼친다(업종마다 정확히 1개)."""
    if criteria is None or 'mapping_type' not in criteria or '해당업종' not in criteria:
        return {}
    out = {}
    for r in criteria.itertuples(index=False):
        for industry in str(getattr(r, '해당업종')).split('·'):
            industry = industry.strip()
            if industry in out:
                raise ValueError(f'매핑 검토유형이 중복 지정된 업종: {industry}')
            out[industry] = r.mapping_type
    unknown = set(out) - set(industries)
    if unknown:
        raise ValueError(f'패널에 없는 업종이 매핑 검토유형에 있습니다: {sorted(unknown)}')
    return out


def parse_confirmed_value(value):
    """confirmed 원자료 값 → True / False / 'MISSING' / 'INVALID'."""
    if is_missing(value):
        return _MISSING
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text == '':
            return _MISSING
        if text == 'true':
            return True
        if text == 'false':
            return False
    return _INVALID


def mapping_confirmation(resolved, industries):
    """업종별 매핑 확정 상태. grade 등 다른 컬럼은 읽지 않는다.

    Returns
    -------
    status : dict industry → (confirmation_status, confirmed bool 또는 None)
    summary : dict  입력 상태·상태별 업종·잘못된 값 목록
    """
    industries = list(industries)
    if resolved is None:
        return ({ind: ('CONFIRMATION_MISSING', None) for ind in industries},
                {'input_status': 'NOT_AVAILABLE', 'invalid_values': []})
    missing_cols = sorted({'kicox_industry', 'confirmed'} - set(resolved.columns))
    if missing_cols:
        return ({ind: ('CONFIRMATION_MISSING', None) for ind in industries},
                {'input_status': 'SCHEMA_MISSING_COLUMNS', 'missing_columns': missing_cols, 'invalid_values': []})
    status, invalid = {}, []
    for industry in industries:
        values = resolved.loc[resolved['kicox_industry'] == industry, 'confirmed'].tolist()
        parsed = [parse_confirmed_value(v) for v in values]
        if not parsed:
            status[industry] = ('CONFIRMATION_MISSING', None)
        elif _INVALID in parsed:
            status[industry] = ('INVALID_CONFIRMED_VALUE', None)
            invalid += [{'industry': industry, 'value': str(v)} for v, p in zip(values, parsed) if p == _INVALID]
        elif _MISSING in parsed:
            status[industry] = ('CONFIRMATION_MISSING', None)
        elif all(p is True for p in parsed):
            status[industry] = ('CONFIRMED', True)
        elif all(p is False for p in parsed):
            status[industry] = ('NOT_CONFIRMED', False)
        else:
            status[industry] = ('PARTIALLY_CONFIRMED', False)
    return status, {'input_status': 'READ', 'invalid_values': invalid}


def confirmation_summary(panel, resolved_summary):
    """보고서용 매핑 확정 상태 요약. 잘못된 값이 있으면 passed=False."""
    by_industry = panel.drop_duplicates('industry').set_index('industry')['ppi_mapping_confirmation_status']
    counts = {k: int(v) for k, v in by_industry.value_counts().sort_index().items()}
    return {'input_status': resolved_summary.get('input_status'),
            'status_counts_by_industry': counts,
            'invalid_values': resolved_summary.get('invalid_values', []),
            'errors': [f"INVALID_CONFIRMED_VALUE:{d['industry']}={d['value']!r}"
                       for d in resolved_summary.get('invalid_values', [])],
            'passed': not resolved_summary.get('invalid_values')}


# ---------------------------------------------------------------- 행별 PPI 필드
def _empty_record():
    return {c: None for c in PPI_COLUMNS}


def ppi_fields(panel, candidates=None, resolved=None, criteria=None, aux_summary=None, latest=None,
               require_all_candidates=True, return_summary=False):
    """행별 PPI 보조 필드. 후보별 원자료가 없으면 최신분기만 보조요약에서 결합한다."""
    industries = panel['industry'].unique()
    review = mapping_review_types(criteria, industries)
    confirmation, resolved_summary = mapping_confirmation(resolved, industries)
    items_by_industry, lookup = (candidate_lookup(candidates, require_all_candidates)
                                 if candidates is not None else (None, None))
    aux = None
    if aux_summary is not None and set(AUX_REQUIRED_COLUMNS) <= set(aux_summary.columns):
        aux = aux_summary.set_index('업종')

    records = []
    for r in panel.itertuples(index=False):
        rec = _empty_record()
        rec['ppi_mapping_review_type'] = review.get(r.industry)
        conf_status, conf_value = confirmation.get(r.industry, ('CONFIRMATION_MISSING', None))
        rec['ppi_mapping_confirmation_status'] = conf_status
        rec['ppi_mapping_confirmed'] = conf_value
        p, e = float(r.production_yoy), float(r.employment_yoy)
        if items_by_industry is None:
            if latest is not None and str(r.quarter) == latest and aux is not None and r.industry in aux.index:
                a = aux.loc[r.industry]
                rec['ppi_source'] = 'aux_summary_latest_only'
                status = AUX_DIRECTION_TO_CODE.get(str(a['PPI_방향상태']))
                rec['ppi_direction_status'] = status
                if status != 'NOT_COMPARABLE' and not np.isnan(p) and not np.isnan(e):
                    lo, hi = float(a['PPI조정_생산YoY_하한']), float(a['PPI조정_생산YoY_상한'])
                    rec.update({'ppi_yoy_min': float(a['PPI_YoY_min']), 'ppi_yoy_max': float(a['PPI_YoY_max']),
                                'ppi_adjusted_prod_yoy_lower': lo, 'ppi_adjusted_prod_yoy_upper': hi,
                                'ppi_comparison_reason': 'BOUNDS_ONLY_FROM_LATEST_SUMMARY'})
                    states = {classify(lo, e), classify(hi, e)}
                    rec['ppi_alt_state_set'] = state_set_label(states)
                    rec['ppi_alt_state_all_same'] = len(states) == 1
                else:
                    rec['ppi_comparison_reason'] = 'NO_MAPPING_CANDIDATE'
            else:
                rec['ppi_direction_status'] = 'PPI_SOURCE_NOT_AVAILABLE'
                rec['ppi_comparison_reason'] = 'PPI_SOURCE_NOT_AVAILABLE'
            records.append(rec)
            continue

        rec['ppi_source'] = config.PATHS['ppi_candidates'].name
        items = items_by_industry.get(r.industry)
        if not items:
            rec['ppi_direction_status'] = 'NOT_COMPARABLE'
            rec['ppi_comparison_reason'] = 'NO_MAPPING_CANDIDATE'
        elif np.isnan(p) or np.isnan(e):
            rec['ppi_direction_status'] = 'NOT_COMPARABLE'
            rec['ppi_comparison_reason'] = ('NOMINAL_PRODUCTION_YOY_MISSING' if np.isnan(p)
                                            else 'EMPLOYMENT_YOY_MISSING')
            rec['ppi_candidate_n'] = len(items)
            rec['ppi_candidate_items'] = '; '.join(items)
        else:
            values = lookup.get((str(r.quarter), r.industry), {})
            ppi = np.array([values.get(item, np.nan) for item in items], dtype=float)
            rec['ppi_candidate_n'] = len(items)
            rec['ppi_candidate_items'] = '; '.join(items)
            if np.isnan(ppi).any():
                rec['ppi_direction_status'] = 'NOT_COMPARABLE'
                rec['ppi_comparison_reason'] = 'PPI_CANDIDATE_INCOMPLETE'
            else:
                adjusted = adjusted_production_yoy(np.full(len(ppi), p), ppi)
                states = [classify(a, e) for a in adjusted]
                rec.update({
                    'ppi_yoy_min': float(ppi.min()), 'ppi_yoy_max': float(ppi.max()),
                    'ppi_adjusted_prod_yoy_lower': float(adjusted.min()),
                    'ppi_adjusted_prod_yoy_upper': float(adjusted.max()),
                    'ppi_direction_status': direction_status(p, adjusted),
                    'ppi_comparison_reason': 'COMPARABLE',
                    'ppi_alt_state_set': state_set_label(states),
                    'ppi_alt_state_all_same': len(set(states)) == 1,
                })
        records.append(rec)
    out = pd.DataFrame(records, index=panel.index, columns=PPI_COLUMNS)
    out['ppi_candidate_n'] = out['ppi_candidate_n'].astype('Int64')
    for col in ['ppi_alt_state_all_same', 'ppi_mapping_confirmed']:
        out[col] = out[col].astype('boolean')
    for col in ['ppi_yoy_min', 'ppi_yoy_max', 'ppi_adjusted_prod_yoy_lower', 'ppi_adjusted_prod_yoy_upper']:
        out[col] = out[col].astype(float)
    if return_summary:
        return out, confirmation_summary(out.assign(industry=panel['industry']), resolved_summary)
    return out


# ---------------------------------------------------------------- 교차검산
def formula_check(panel, candidates):
    """저장값이 비율식과 일치하고 단순 차감식과는 다른지 확인한다."""
    _, lookup = candidate_lookup(candidates)
    rows = panel[panel['ppi_direction_status'].isin(config.PPI_COMPARABLE_STATUSES)]
    max_ratio_gap, n_subtraction_differs, n = 0.0, 0, 0
    for r in rows.itertuples(index=False):
        values = lookup[(str(r.quarter), r.industry)]
        ppi = np.array(list(values.values()), dtype=float)
        ratio = adjusted_production_yoy(np.full(len(ppi), r.production_yoy), ppi)
        subtraction = r.production_yoy - ppi
        max_ratio_gap = max(max_ratio_gap, abs(ratio.min() - r.ppi_adjusted_prod_yoy_lower),
                            abs(ratio.max() - r.ppi_adjusted_prod_yoy_upper))
        n_subtraction_differs += int(np.any(np.abs(ratio - subtraction) > 1e-6))
        n += 1
    return {'n_rows_checked': n, 'max_abs_gap_vs_ratio_formula': max_ratio_gap,
            'n_rows_where_simple_subtraction_differs': n_subtraction_differs,
            'passed': n > 0 and max_ratio_gap < 1e-9 and n_subtraction_differs > 0}


def crosscheck_ppi_sensitivity(panel, sensitivity):
    """기존 PPI_sensitivity.csv(src/eda 산출, 전 기간)와 행별 결과 대조."""
    sens = sensitivity.copy()
    sens['quarter'] = sens['quarter'].astype(str)
    cols = ['quarter', 'industry', 'ppi_adjusted_prod_yoy_lower', 'ppi_adjusted_prod_yoy_upper',
            'ppi_direction_status', 'ppi_alt_state_set']
    mine = panel[panel['ppi_direction_status'].isin(config.PPI_COMPARABLE_STATUSES)][cols].copy()
    mine['quarter'] = mine['quarter'].astype(str)
    merged = sens.merge(mine, on=['quarter', 'industry'], how='outer', indicator=True, validate='one_to_one')
    both = merged[merged['_merge'] == 'both']
    gap = float(np.nanmax(np.abs(np.r_[both.adjusted_lo - both.ppi_adjusted_prod_yoy_lower,
                                       both.adjusted_hi - both.ppi_adjusted_prod_yoy_upper]), initial=0.0))
    status_mismatch = int((both['status'].map(EDA_STATUS_TO_CODE) != both['ppi_direction_status']).sum())
    single = both['ppi_alt_state_set'].where(~both['ppi_alt_state_set'].astype(str).str.contains('|', regex=False),
                                             '후보별 상이')
    state_mismatch = int((single != both['adjusted_state']).sum())
    return {
        'n_reference_rows': int(len(sens)), 'n_model_comparable_rows': int(len(mine)),
        'n_matched_rows': int(len(both)), 'n_unmatched_rows': int((merged['_merge'] != 'both').sum()),
        'max_abs_adjusted_gap': gap, 'n_direction_status_mismatch': status_mismatch,
        'n_alt_state_mismatch': state_mismatch,
        'model_direction_status_counts': {k: int(v) for k, v in
                                          mine['ppi_direction_status'].value_counts().sort_index().items()},
        'passed': bool(len(both) == len(sens) == len(mine) and gap < 1e-9
                       and status_mismatch == 0 and state_mismatch == 0),
    }


def crosscheck_aux_summary(panel, aux_summary, latest):
    """최신분기 보조요약(aux_summary_2026Q2.csv)과 대조. 요약표의 반올림 자릿수를 허용오차로 쓴다."""
    if aux_summary is None:
        return {'status': 'NOT_AVAILABLE', 'passed': None}
    missing_cols = sorted(set(AUX_REQUIRED_COLUMNS) - set(aux_summary.columns))
    if missing_cols:
        return {'status': 'AUX_SCHEMA_MISMATCH', 'missing_columns': missing_cols, 'passed': False}
    lat = panel[panel['quarter'].astype(str) == latest].set_index('industry')
    mismatches = []

    def close(a, b, tol):
        if is_missing(a) and is_missing(b):
            return True
        return not (is_missing(a) or is_missing(b)) and abs(float(a) - float(b)) <= tol

    one_decimal, six_decimal = 0.05 + 1e-9, 5e-7 + 1e-9
    for a in aux_summary.itertuples(index=False):
        industry = getattr(a, '업종')
        if industry not in lat.index:
            mismatches.append({'industry': industry, 'field': 'industry', 'reason': 'NOT_IN_PANEL'})
            continue
        m = lat.loc[industry]
        checks = [
            ('국면', m['state'] == getattr(a, '국면')),
            ('생산YoY', close(m['production_yoy'], getattr(a, '생산YoY'), one_decimal)),
            ('고용YoY', close(m['employment_yoy'], getattr(a, '고용YoY'), one_decimal)),
            ('가동률_사용값', close(m['op_rate_used'], getattr(a, '가동률_사용값'), one_decimal)),
            ('가동률YoY_pp_사용값', close(m['op_rate_used_yoy_pp'], getattr(a, '가동률YoY_pp_사용값'), one_decimal)),
            ('가동업체YoY', close(m['firms_op_yoy'], getattr(a, '가동업체YoY'), one_decimal)),
            ('PPI_YoY_min', close(m['ppi_yoy_min'], getattr(a, 'PPI_YoY_min'), six_decimal)),
            ('PPI_YoY_max', close(m['ppi_yoy_max'], getattr(a, 'PPI_YoY_max'), six_decimal)),
            ('PPI조정_생산YoY_하한', close(m['ppi_adjusted_prod_yoy_lower'],
                                       getattr(a, 'PPI조정_생산YoY_하한'), six_decimal)),
            ('PPI조정_생산YoY_상한', close(m['ppi_adjusted_prod_yoy_upper'],
                                       getattr(a, 'PPI조정_생산YoY_상한'), six_decimal)),
            ('PPI_방향상태', AUX_DIRECTION_TO_CODE.get(getattr(a, 'PPI_방향상태')) == m['ppi_direction_status']),
            ('PPI_매핑검토유형', getattr(a, 'PPI_매핑검토유형') == m['ppi_mapping_review_type']),
            ('PPI_매핑확정여부', m['ppi_mapping_confirmation_status']
             in AUX_CONFIRMATION_MATCH.get(getattr(a, 'PPI_매핑확정여부'), ())),
        ]
        for field, ok in checks:
            if ok is not True and not (isinstance(ok, (bool, np.bool_)) and bool(ok)):
                mismatches.append({'industry': industry, 'field': field})
    return {'status': 'COMPARED', 'quarter': latest, 'n_rows': int(len(aux_summary)),
            'n_mismatches': len(mismatches), 'mismatches': mismatches, 'passed': not mismatches}


def latest_ppi_table(panel, latest):
    """최신분기 명목 상태와 PPI 후보 적용 시 대안 상태 집합."""
    lat = panel[panel['quarter'].astype(str) == latest]
    return lat[['industry', 'state', 'production_yoy', 'ppi_candidate_n', 'ppi_yoy_min', 'ppi_yoy_max',
                'ppi_adjusted_prod_yoy_lower', 'ppi_adjusted_prod_yoy_upper', 'ppi_direction_status',
                'ppi_alt_state_set', 'ppi_alt_state_all_same', 'ppi_mapping_review_type',
                'ppi_mapping_confirmed', 'ppi_mapping_confirmation_status']].reset_index(drop=True)
