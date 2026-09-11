# -*- coding: utf-8 -*-
"""Section 6 — PPI 보조분석(후보 매핑별 생산 방향 민감도).

notebooks/02_eda.ipynb 셀 56의 계산을 그대로 옮겼다.

- 월별 PPI를 계열 코드별로 선택하고, 세 달이 모두 있는 분기만 산술평균한다.
- 분기 평균의 4분기 lag YoY를 구한 뒤 다음 조정식을 쓴다.
      g_adj = 100 * [ (1 + g_nom/100) / (1 + g_ppi/100) - 1 ]
- 후보 매핑은 조건부 민감도 분석에만 쓰고, 명목 생산 기준 본분석 국면을 대체하지 않는다.
"""
import numpy as np
import pandas as pd

from . import config
from .panel import classify


# ---------------------------------------------------------------- 매핑·계열 선택
def build_mapping():
    """후보 매핑표(ppi_map)와 민감도에 쓰는 부분집합(selected_map)을 만든다."""
    ppi_map = pd.DataFrame(config.PPI_MAPPING_ROWS,
                           columns=['industry', 'code_suffix', 'ppi_item', 'mapping_reason'])
    ppi_map['C1'] = config.PPI_C1_PREFIX + ppi_map.code_suffix + config.PPI_C1_SUFFIX
    ppi_map['mapping_use'] = 'sensitivity_only'
    ppi_map['main_analysis_eligible'] = False
    ppi_map['sensitivity_eligible'] = True
    ppi_map['series_level_digits'] = ppi_map.code_suffix.str.len()
    ppi_map = pd.concat([ppi_map, pd.DataFrame([config.PPI_EXCLUDED_ROW])], ignore_index=True)
    return ppi_map, ppi_map[ppi_map.sensitivity_eligible]


def load_raw(ppi_path):
    """PPI 원자료를 읽고 월 단위 키를 붙인다."""
    raw = pd.read_csv(ppi_path, dtype=str)
    raw.columns = raw.columns.str.lstrip('﻿')
    raw['C1'] = raw.C1.str.strip()
    raw['DT'] = pd.to_numeric(raw.DT, errors='coerce')
    raw['month'] = pd.to_datetime(raw.PRD_DE, format='%Y%m').dt.to_period('M')
    return raw


def select_series(raw, selected_map, series_keys=None):
    """사용 후보 계열만 남기고 코드·단위·중복을 검증한다."""
    series_keys = config.PPI_SERIES_KEYS if series_keys is None else series_keys
    f = config.PPI_FILTER
    selected = raw[(raw.ORG_ID.eq(f['ORG_ID'])) & raw.TBL_ID.eq(f['TBL_ID']) &
                   raw.ITM_ID.eq(f['ITM_ID']) & raw.PRD_SE.eq(f['PRD_SE']) &
                   raw.C1.isin(selected_map.C1)].copy()
    assert set(selected.C1) == set(selected_map.C1), 'PPI 코드 누락'
    assert not selected.duplicated(series_keys + ['month']).any(), '동일 PPI 코드/월 중복: 평균처리 금지'
    assert selected.UNIT_NM.str.replace('＝', '=').eq(config.PPI_BASE_YEAR_UNIT).all(), '사용 계열 기준연도 혼재'
    assert selected.DT.gt(0).all(), 'PPI 결측 또는 0 이하'
    name_by_code = selected.groupby('C1').C1_NM.agg(lambda x: set(x))
    assert all(name_by_code[r.C1] == {r.ppi_item} for r in selected_map.itertuples()), 'PPI 코드-이름 불일치'
    return selected


# ---------------------------------------------------------------- 월 → 분기 → YoY
def quarterly_ppi(raw, selected):
    """완전한 3개월이 있는 분기만 평균해 분기 PPI와 4분기 lag YoY를 만든다.

    월이 하나라도 없으면 그 분기는 계산하지 않는다. 빈 월을 보간하지 않는다.
    """
    calendar = pd.period_range(raw.month.min(), raw.month.max(), freq='M')
    monthly = selected.pivot(index='month', columns='C1', values='DT').reindex(calendar)
    monthly_missing = monthly.isna().sum()
    monthly['quarter'] = monthly.index.asfreq('Q')
    quarterly = monthly.groupby('quarter').mean()
    counts = monthly.groupby('quarter').count()
    quarterly = quarterly.where(counts.eq(3))
    quarterly = quarterly.reindex(pd.period_range(quarterly.index.min(), quarterly.index.max(), freq='Q'))
    return calendar, monthly, monthly_missing, quarterly


def ppi_long_frames(quarterly, selected_map):
    """수준값 long 프레임과 YoY long 프레임을 만든다.

    수준값으로 계산한 조정 생산 YoY와 변화율 공식이 일치하는지 확인하는 데 쓴다.
    """
    ppi_level_long = (quarterly.rename_axis('quarter').reset_index()
                      .melt(id_vars='quarter', var_name='C1', value_name='ppi_level'))
    ppi_lag_long = (quarterly.shift(4).rename_axis('quarter').reset_index()
                    .melt(id_vars='quarter', var_name='C1', value_name='ppi_level_lag4'))
    ppi_level_long = ppi_level_long.merge(ppi_lag_long, on=['quarter', 'C1'], validate='one_to_one')
    ppi_level_long['quarter'] = ppi_level_long.quarter.astype(str)

    ppi_yoy = (quarterly / quarterly.shift(4) - 1) * 100
    ppi_yoy.index.name = 'quarter'
    ppi_long = ppi_yoy.reset_index().melt(id_vars='quarter', var_name='C1', value_name='ppi_yoy')
    ppi_long['quarter'] = ppi_long.quarter.astype(str)
    ppi_long = ppi_long.merge(selected_map[['industry', 'C1', 'ppi_item']], on='C1',
                              validate='many_to_one')
    assert not ppi_long.duplicated(['quarter', 'industry', 'C1']).any()
    assert ppi_long.loc[ppi_long.quarter < str(quarterly.index[0] + 4), 'ppi_yoy'].isna().all(), '초기 YoY 오류'
    return ppi_level_long, ppi_long


# ---------------------------------------------------------------- 조정식·민감도
def adjust(state, ppi_long, ppi_level_long, selected_map):
    """명목 생산 YoY를 PPI로 조정하고 후보별 결과를 집계한다.

    Returns
    -------
    base : DataFrame   생산·고용 YoY가 모두 있는 관측
    mm : DataFrame     후보별 조정 결과
    sig : DataFrame    업종×분기 단위 후보 범위와 방향 판정
    """
    base = state[state.production_yoy.notna() & state.employment_yoy.notna()][
        ['quarter', 'industry', 'production_yoy', 'employment_yoy', 'state', 'employment']]
    mm = base.merge(ppi_long, on=['quarter', 'industry'], how='inner', validate='one_to_many')
    # 각 후보의 자료가 완전할 때만 비교에 포함한다.
    expected_candidates = selected_map.groupby('industry').size()
    complete = mm.groupby(['quarter', 'industry']).ppi_yoy.count().rename('n_valid').reset_index()
    complete['n_expected'] = complete.industry.map(expected_candidates)
    complete = complete[complete.n_valid.eq(complete.n_expected)]
    mm = mm.merge(complete[['quarter', 'industry']], on=['quarter', 'industry'], validate='many_to_one')
    mm['adjusted_yoy'] = ((1 + mm.production_yoy / 100) / (1 + mm.ppi_yoy / 100) - 1) * 100
    # 0% 입력의 수치오차만 처리한다. 분석 중립구간은 변경하지 않는다.
    mm.loc[mm.adjusted_yoy.abs() < 1e-10, 'adjusted_yoy'] = 0

    level_check = mm.merge(ppi_level_long, on=['quarter', 'C1'], validate='many_to_one').merge(
        state[['quarter', 'industry', 'production', 'production_lag4']],
        on=['quarter', 'industry'], validate='many_to_one')
    level_yoy = ((level_check.production / (level_check.ppi_level / 100)) /
                 (level_check.production_lag4 / (level_check.ppi_level_lag4 / 100)) - 1) * 100
    assert np.allclose(level_yoy, level_check.adjusted_yoy), 'PPI 수준값 공식과 YoY 조정 공식 불일치'

    sig = mm.groupby(['quarter', 'industry', 'production_yoy', 'employment_yoy', 'state'],
                     as_index=False).agg(
        adjusted_lo=('adjusted_yoy', 'min'), adjusted_hi=('adjusted_yoy', 'max'),
        ppi_lo=('ppi_yoy', 'min'), ppi_hi=('ppi_yoy', 'max'), n_candidates=('C1', 'nunique'),
        ppi_items=('ppi_item', lambda s: '; '.join(sorted(s.unique()))))
    nom = np.sign(sig.production_yoy)
    sig['all_same'] = np.sign(sig.adjusted_lo).eq(nom) & np.sign(sig.adjusted_hi).eq(nom)
    sig['all_opposite'] = (nom.ne(0) & np.sign(sig.adjusted_lo).eq(-nom)
                           & np.sign(sig.adjusted_hi).eq(-nom))
    sig['status'] = np.select([sig.all_same, sig.all_opposite,
                               sig.adjusted_lo.lt(0) & sig.adjusted_hi.gt(0)],
                              ['모든 후보에서 유지', '모든 후보에서 반전', '후보별 방향 다름'],
                              default='0% 경계 변화')
    sig['adjusted_state'] = [classify(r.adjusted_lo, r.employment_yoy)
                             if classify(r.adjusted_lo, r.employment_yoy)
                             == classify(r.adjusted_hi, r.employment_yoy) else '후보별 상이'
                             for r in sig.itertuples()]
    sig['different'] = ~sig.all_same
    return base, mm, sig


def yearly_summary(sig):
    """연도별 후보 의존·반전 관측 집계."""
    ppi_year = sig.assign(year=sig.quarter.str[:4]).groupby('year').agg(
        관측수=('status', 'size'), 전체후보반전=('all_opposite', 'sum'),
        후보의존=('status', lambda s: s.eq('후보별 방향 다름').sum()),
        차이관측=('different', 'sum'))
    ppi_year['차이비율%'] = ppi_year.차이관측 / ppi_year.관측수 * 100
    return ppi_year


def series_audit(selected_map, selected, monthly_missing):
    """사용 후보 계열의 월 수·결측·단위 감사표."""
    audit = selected_map[['industry', 'C1', 'ppi_item', 'series_level_digits']].copy()
    audit['n_months'] = audit.C1.map(selected.groupby('C1').month.nunique())
    audit['missing_months'] = audit.C1.map(monthly_missing)
    audit['unit'] = audit.C1.map(selected.groupby('C1').UNIT_NM.first())
    return audit


# ---------------------------------------------------------------- 전체 실행
def run(state, ctx, ppi_path, employment_denominator, series_keys=None):
    """PPI 보조분석 전 과정을 실행하고 산출물 묶음을 돌려준다."""
    series_keys = config.PPI_SERIES_KEYS if series_keys is None else series_keys
    ppi_map, selected_map = build_mapping()
    raw = load_raw(ppi_path)
    selected = select_series(raw, selected_map, series_keys)
    calendar, monthly, monthly_missing, quarterly = quarterly_ppi(raw, selected)
    ppi_level_long, ppi_long = ppi_long_frames(quarterly, selected_map)
    base, mm, sig = adjust(state, ppi_long, ppi_level_long, selected_map)
    ppi_year = yearly_summary(sig)

    latest_all = state[state.quarter.eq(ctx.latest)].set_index('industry')
    latest_sig = sig[sig.quarter.eq(ctx.latest)].set_index('industry')
    # 명목 증가 업종에 한정해서 조정 결과를 찾지 않는다: 음→양의 변화도 포착한다.
    comparable_down = latest_sig[latest_sig.employment_yoy.lt(0)]
    nom_up = comparable_down[comparable_down.production_yoy.gt(0)]
    adj_up = comparable_down[comparable_down.adjusted_lo.gt(0)]
    adj_possible_up = comparable_down[comparable_down.adjusted_hi.gt(0)]
    emp_den = employment_denominator
    nom_num = float(latest_all.loc[nom_up.index, 'employment'].sum())
    adj_num = float(latest_all.loc[adj_up.index, 'employment'].sum())
    possible_num = float(latest_all.loc[adj_possible_up.index, 'employment'].sum())
    target = base[base.industry.isin(selected_map.industry)]

    raw_series = raw[series_keys + ['C1_NM']].drop_duplicates()
    raw_month_counts = raw.groupby('C1').month.nunique()
    raw_incomplete = raw_month_counts[raw_month_counts < len(calendar)]
    raw_other_units = raw[raw.UNIT_NM.str.replace('＝', '=').ne(config.PPI_BASE_YEAR_UNIT)][
        ['C1_NM', 'UNIT_NM']].drop_duplicates()
    selected_audit = series_audit(selected_map, selected, monthly_missing)

    results = {
        'raw_rows': len(raw), 'raw_series': len(raw_series), 'raw_names': raw.C1_NM.nunique(),
        'month_start': str(calendar.min()), 'month_end': str(calendar.max()), 'n_months': len(calendar),
        'raw_incomplete_series': len(raw_incomplete),
        'raw_other_units': raw_other_units.to_dict('records'),
        'selected_series': len(selected_map), 'selected_missing_months': int(monthly_missing.sum()),
        'quarter_first': str(quarterly.index.min()),
        'first_yoy_quarter': ppi_long.dropna(subset=['ppi_yoy']).quarter.min(),
        'n_calendar_quarters': len(ctx.quarters),
        'n_ppi_quarters': ppi_long[ppi_long.quarter.isin(ctx.quarters)]
                          .dropna(subset=['ppi_yoy']).quarter.nunique(),
        'n_comparable': len(sig), 'n_target': len(target), 'coverage_pct': len(sig) / len(target) * 100,
        'n_industries': sig.industry.nunique(), 'n_quarters': sig.quarter.nunique(),
        'n_same': int(sig.all_same.sum()), 'n_opposite': int(sig.all_opposite.sum()),
        'n_candidate_dependent': int(sig.status.eq('후보별 방향 다름').sum()),
        'n_zero_boundary': int(sig.status.eq('0% 경계 변화').sum()),
        'n_different': int(sig.different.sum()), 'different_pct': float(sig.different.mean() * 100),
        'yearly': ppi_year.reset_index().to_dict('records'),
        'employment_denominator': emp_den, 'nominal_numerator': nom_num,
        'adjusted_numerator': adj_num,
        'nominal_share_pct': nom_num / emp_den * 100, 'adjusted_share_pct': adj_num / emp_den * 100,
        'possible_adjusted_share_pct': possible_num / emp_den * 100,
        'nominal_up_industries': list(nom_up.index), 'adjusted_up_industries': list(adj_up.index),
        'latest_comparable_down_count': len(comparable_down),
        'latest_uncompared_down': latest_all.index[latest_all.employment_yoy.lt(0)
                                                   & ~latest_all.index.isin(latest_sig.index)].tolist(),
        'latest_rows': latest_sig.reset_index().to_dict('records')}

    return {'ppi_map': ppi_map, 'selected_map': selected_map, 'raw': raw, 'selected': selected,
            'calendar': calendar, 'monthly_missing': monthly_missing, 'quarterly': quarterly,
            'ppi_long': ppi_long, 'ppi_level_long': ppi_level_long, 'base': base, 'mm': mm,
            'sig': sig, 'ppi_year': ppi_year, 'selected_audit': selected_audit,
            'latest_sig': latest_sig, 'results': results}


def save_tables(bundle, dir_tab):
    """후보 계열별 계산 결과를 저장한다. 본분석 생산값은 유지한다."""
    bundle['selected_audit'].to_csv(dir_tab / 'PPI_series_audit.csv', index=False, encoding='utf-8-sig')
    bundle['ppi_map'].to_csv(dir_tab / 'PPI_candidate_mapping.csv', index=False, encoding='utf-8-sig')
    bundle['sig'].to_csv(dir_tab / 'PPI_sensitivity.csv', index=False, encoding='utf-8-sig')
    bundle['ppi_year'].to_csv(dir_tab / 'PPI_by_year.csv', encoding='utf-8-sig')
    bundle['ppi_long'].to_csv(dir_tab / 'PPI_candidate_quarterly_yoy.csv', index=False,
                              encoding='utf-8-sig')


def status_grid(sig, ctx, status_list=None):
    """후보별 방향 비교 격자(그림용). 비교 불가 칸은 '비교 불가'로 채운다."""
    status_list = config.PPI_STATUS if status_list is None else status_list
    ind_ppi = [i for i in ctx.ind_order_emp if i in set(sig.industry)]
    codes = {s: i for i, s in enumerate(status_list)}
    pivot = (sig.pivot(index='industry', columns='quarter', values='status')
             .reindex(index=ind_ppi, columns=ctx.quarters).fillna('비교 불가'))
    arr = pivot.apply(lambda col: col.map(codes)).to_numpy()
    return ind_ppi, pivot, arr


def yearly_split(ppi_year):
    """첫 연도와 나머지 연도를 나눈 요약(노트북 셀 59)."""
    first_year = ppi_year.index.min()
    a = ppi_year.loc[first_year]
    b = ppi_year.drop(first_year)
    other_n = int(b.관측수.sum())
    other_diff = int(b.차이관측.sum())
    other_pct = other_diff / other_n * 100 if other_n else float('nan')
    return first_year, a, b, other_n, other_diff, other_pct


def result_table(results):
    """PPI 보조분석 결과 요약표."""
    return pd.Series({
        '원자료 기간': f'{results["month_start"]}~{results["month_end"]}',
        '선택 후보 계열': results['selected_series'],
        '비교 가능 관측': results['n_comparable'],
        '선택 후보 모두에서 반전': results['n_opposite'],
        '후보별 방향이 다른 관측': results['n_candidate_dependent'],
        '0% 경계 변화': results['n_zero_boundary'],
    }, name='값').to_frame()
