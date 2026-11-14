# -*- coding: utf-8 -*-
"""파생지표·품질 플래그·라우팅 필드.

모든 값은 기준 패널(changwon_state_panel.csv)과 src/eda의 정의에서 파생한다.
Q1 state·YoY·기존 run은 재정의하지 않고, 결측은 0으로 채우거나 보간하지 않는다.
"""
import numpy as np
import pandas as pd

from eda.panel import classify

from . import config

BASE_COLUMNS = [
    'industry', 'quarter', 'quarter_index',
    'employment', 'employment_lag4', 'emp_delta', 'employment_yoy',
    'production', 'production_lag4', 'production_yoy',
    'state', 'run_length', 'run_left_censored', 'run_right_censored', 'previous_state',
    'transition_type',
]


# ---------------------------------------------------------------- 공통 도우미
def clean_negative_zero(values):
    """-0.0을 0.0으로 정규화한다. NaN은 그대로 둔다."""
    arr = np.asarray(values, dtype=float)
    return np.where(arr == 0, 0.0, arr)


def masked_bool(values, na_mask, index):
    """bool 값에 결측 마스크를 적용한 nullable boolean Series."""
    series = pd.Series(np.asarray(values, dtype=bool), index=index, dtype='boolean')
    return series.mask(pd.Series(np.asarray(na_mask, dtype=bool), index=index))


def sort_panel(panel):
    return panel.sort_values(['industry', 'quarter_index'], kind='mergesort').reset_index(drop=True)


def calendar_ordinal(quarters):
    period = pd.PeriodIndex(pd.Series(quarters, dtype=str), freq='Q')
    return np.asarray(period.year * 4 + period.quarter - 1, dtype=int)


def previous_quarter_adjacent(panel):
    """직전 행이 같은 업종의 실제 직전 달력분기이면 True(industry, quarter_index 정렬 전제)."""
    cal = pd.Series(calendar_ordinal(panel['quarter']), index=panel.index)
    if (panel['quarter_index'] - cal).nunique() != 1:
        raise ValueError('quarter_index와 달력분기 순서가 일치하지 않습니다.')
    if not panel.groupby('industry', sort=False)['quarter_index'].apply(
            lambda s: s.is_monotonic_increasing).all():
        raise ValueError('업종별 quarter_index 오름차순 정렬이 필요합니다.')
    prev = cal.groupby(panel['industry']).shift(1)
    return (cal - prev).eq(1).to_numpy()


def adjacent_previous(panel, column, adjacent):
    """실제 직전 달력분기 값. 직전 분기가 없으면 NaN."""
    prev = panel.groupby('industry', sort=False)[column].shift(1)
    return prev.where(adjacent)


# ---------------------------------------------------------------- g1~g3
def core_criteria(panel):
    """g1·g2·g3. 범위를 벗어난 입력은 절단하지 않고 오류로 중단한다."""
    employment = panel['employment'].astype(float)
    employment_lag4 = panel['employment_lag4'].astype(float)
    if (employment < 0).any():
        raise ValueError('음수 고용 인원이 있습니다: 데이터 오류로 중단합니다.')
    if (employment_lag4 <= 0).any():
        raise ValueError('전년동기 고용이 0 이하입니다: 데이터 오류로 중단합니다.')
    g1 = clean_negative_zero(np.maximum(0.0, employment_lag4 - employment))
    g2 = clean_negative_zero(np.maximum(0.0, -panel['employment_yoy'].astype(float)))
    g3 = clean_negative_zero(np.maximum(0.0, -panel['production_yoy'].astype(float)))
    if np.nanmax(g2, initial=0.0) > 100 or np.nanmax(g3, initial=0.0) > 100:
        raise ValueError('감소율이 100%를 넘습니다: 데이터 오류로 중단합니다.')
    if 'emp_delta' in panel:
        expected = clean_negative_zero(np.maximum(0.0, -panel['emp_delta'].astype(float)))
        if not np.allclose(g1, expected, equal_nan=True):
            raise ValueError('g1과 기존 emp_delta 정의가 일치하지 않습니다.')
    return pd.DataFrame({config.CRITERION_COLUMNS['g1']: g1,
                         config.CRITERION_COLUMNS['g2']: g2,
                         config.CRITERION_COLUMNS['g3']: g3}, index=panel.index)


# ---------------------------------------------------------------- g4
def _validate_delta(delta):
    if isinstance(delta, bool) or not isinstance(delta, (int, float)) or not np.isfinite(delta) or delta < 0:
        raise ValueError(f'delta_emp는 0 이상의 유한한 수여야 합니다: {delta!r}')
    return float(delta)


def emp_yoy_below_run(panel, delta, window_n, latest_quarter):
    """전년동기 대비 고용 하회 연속분기(g4)와 절단·포화 플래그.

    - employment_yoy < -delta이면 직전 값 + 1, employment_yoy >= -delta이면 0.
    - employment_yoy가 NA이면 NA이며 run을 초기화한다.
    - 직전 행이 실제 직전 달력분기가 아니면 연결하지 않는다.
    - 생산 YoY·Q1 state·PPI는 사용하지 않는다(생산 결측분기를 가로질러 계산).
    """
    delta = _validate_delta(delta)
    yoy_all = panel['employment_yoy'].to_numpy(dtype=float)
    adjacent = previous_quarter_adjacent(panel)
    n_all = len(panel)
    run = np.full(n_all, np.nan)
    left = np.zeros(n_all, dtype=bool)
    open_run = np.zeros(n_all, dtype=bool)
    after_break = np.zeros(n_all, dtype=bool)
    quarters = panel['quarter'].astype(str).to_numpy()

    for positions in panel.groupby('industry', sort=False).indices.values():
        idx = np.sort(np.asarray(positions))
        yoy, adj = yoy_all[idx], adjacent[idx]
        r = np.full(len(idx), np.nan)
        start = np.full(len(idx), -1)
        for k, value in enumerate(yoy):
            if np.isnan(value):
                continue
            if value < -delta:
                if k > 0 and adj[k] and r[k - 1] > 0:
                    r[k], start[k] = r[k - 1] + 1, start[k - 1]
                else:
                    r[k], start[k] = 1, k
            else:
                r[k] = 0
        positive = r > 0
        brk = np.zeros(len(idx), dtype=bool)
        for k in np.flatnonzero(positive & (start > 0)):
            s0 = start[k]
            brk[k] = (not adj[s0]) or np.isnan(yoy[s0 - 1])
        last = len(idx) - 1
        reaches_latest = quarters[idx[last]] == latest_quarter and r[last] > 0
        run[idx] = r
        left[idx] = positive & (start == 0)
        after_break[idx] = brk
        open_run[idx] = positive & reaches_latest & (start == start[last])

    na = np.isnan(run)
    index = panel.index
    return pd.DataFrame({
        'run': pd.Series(run, index=index).astype('Int64'),
        'left_censored': masked_bool(left, na, index),
        'open_run': masked_bool(open_run, na, index),
        'window_saturated': masked_bool(run == window_n, na, index),
        'start_after_break': masked_bool(after_break, na, index),
    }, index=index)


def g4_sensitivity_columns(panel, window_n, latest_quarter):
    """g4_delta00·g4_delta05·g4_delta10과 δ별 절단·포화 플래그."""
    out = pd.DataFrame(index=panel.index)
    for column, delta in config.G4_DELTA_COLUMNS.items():
        g4 = emp_yoy_below_run(panel, delta, window_n, latest_quarter)
        out[column] = g4['run']
        for flag in config.G4_FLAGS:
            out[f'{column}_{flag}'] = g4[flag]
    return out


# ---------------------------------------------------------------- threshold 품질 플래그
def state_column(threshold):
    return 'state_t' + (f'{threshold:.1f}'.replace('.', '') if threshold else '0')


def threshold_tag(threshold):
    return f'{threshold:.1f}'.replace('.', '_')


def threshold_flag_labels(thresholds=config.SENSITIVITY_THRESHOLDS):
    return ([f'STABLE_{threshold_tag(max(thresholds))}']
            + [f'SENSITIVE_{threshold_tag(t)}' for t in thresholds] + ['EXACT_ZERO', 'INVALID'])


def threshold_quality_flags(panel, thresholds=config.SENSITIVITY_THRESHOLDS):
    """threshold 0·0.5·1·2%의 상태와 품질 플래그. 본분석 state(threshold=0)는 바꾸지 않는다."""
    thresholds = tuple(sorted(thresholds))
    p = panel['production_yoy'].to_numpy(dtype=float)
    e = panel['employment_yoy'].to_numpy(dtype=float)
    out = pd.DataFrame(index=panel.index)
    out[state_column(0)] = [classify(a, b, 0) for a, b in zip(p, e)]
    if 'state' in panel and not out[state_column(0)].eq(panel['state'].astype(str)).all():
        raise ValueError('threshold=0 재분류가 기준 패널 state와 다릅니다.')
    for t in thresholds:
        out[state_column(t)] = [classify(a, b, t) for a, b in zip(p, e)]

    flags, first_neutral = [], []
    for i in range(len(out)):
        s0 = out[state_column(0)].iat[i]
        path = [out[state_column(t)].iat[i] for t in thresholds]
        if s0 == 'INVALID':
            flags.append('INVALID')
            first_neutral.append(np.nan)
            continue
        if s0 == 'N':
            flags.append('EXACT_ZERO')
            first_neutral.append(0.0)
            continue
        hit = next((t for t, s in zip(thresholds, path) if s == 'N'), None)
        if hit is not None and any(s != 'N' for t, s in zip(thresholds, path) if t > hit):
            raise ValueError('threshold 상향 시 N이 다시 S상태로 돌아가는 비단조 관측이 있습니다.')
        flags.append(f'SENSITIVE_{threshold_tag(hit)}' if hit is not None
                     else f'STABLE_{threshold_tag(thresholds[-1])}')
        first_neutral.append(np.nan if hit is None else float(hit))
    out['threshold_flag'] = flags
    out['first_neutral_threshold'] = first_neutral
    return out


def threshold_state_moves(flags, thresholds=config.SENSITIVITY_THRESHOLDS):
    """threshold=0 상태에서 상향 threshold 상태로의 이동 건수(long)."""
    rows = []
    base = flags[state_column(0)]
    for t in thresholds:
        moved = pd.crosstab(base, flags[state_column(t)])
        for s_from in moved.index:
            for s_to in moved.columns:
                n = int(moved.loc[s_from, s_to])
                if n:
                    rows.append({'threshold': t, 'state_t0': s_from, 'state_at_threshold': s_to,
                                 'n_rows': n,
                                 's_to_other_s': s_from in config.STATES4 and s_to in config.STATES4
                                 and s_from != s_to})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- 판정가능 여부·라우팅
def status_fields(panel, criteria):
    """core_data_status·scorable·결측 원인·Q1 라우팅·잔여 범주."""
    g1 = criteria[config.CRITERION_COLUMNS['g1']]
    g2 = criteria[config.CRITERION_COLUMNS['g2']]
    g3 = criteria[config.CRITERION_COLUMNS['g3']]
    emp_missing = g1.isna() | g2.isna() | panel['employment_yoy'].isna()
    prod_missing = g3.isna()
    other_invalid = pd.Series(False, index=panel.index)
    for col in ['production_yoy_valid', 'employment_yoy_valid']:
        if col in panel:
            other_invalid |= panel[col].astype('boolean').eq(False).fillna(False) & ~(emp_missing | prod_missing)
    core = np.select([emp_missing, prod_missing, other_invalid],
                     ['EMP_CORE_MISSING', 'PROD_YOY_MISSING', 'OTHER_CORE_INVALID'], default='COMPLETE')
    out = pd.DataFrame(index=panel.index)
    out['core_data_status'] = core
    out['scorable'] = out['core_data_status'].eq('COMPLETE')
    out['unscorable_reason'] = out['core_data_status'].where(~out['scorable'])

    root, propagation = [], []
    quarters = panel['quarter'].astype(str)
    for i in range(len(panel)):
        status = core[i]
        if status == 'COMPLETE':
            root.append(None)
            propagation.append(None)
            continue
        prefix = 'EMPLOYMENT' if status == 'EMP_CORE_MISSING' else 'PRODUCTION'
        var = prefix.lower()
        lag_q = str(pd.Period(quarters.iat[i], freq='Q') - 4)
        if bool(panel.get(f'{var}_current_missing', pd.Series(False, index=panel.index)).iat[i]):
            root.append(f'{quarters.iat[i]}_{prefix}_SOURCE_MISSING')
            propagation.append(None)
        elif bool(panel.get(f'{var}_lag4_missing', pd.Series(False, index=panel.index)).iat[i]):
            root.append(f'{lag_q}_{prefix}_SOURCE_MISSING')
            propagation.append(f'LAG4_FROM_{lag_q}_SOURCE_MISSING')
        elif bool(panel.get(f'{var}_lag4_absent', pd.Series(False, index=panel.index)).iat[i]):
            root.append(f'{prefix}_LAG4_ABSENT')
            propagation.append(None)
        elif bool(panel.get(f'{var}_denominator_zero', pd.Series(False, index=panel.index)).iat[i]):
            root.append(f'{prefix}_LAG4_ZERO')
            propagation.append(None)
        else:
            root.append(f'{prefix}_YOY_UNAVAILABLE')
            propagation.append(None)
    out['unscorable_root_cause'] = root
    out['unscorable_propagation'] = propagation

    missing_state = panel['state'].astype(str).map(config.Q1_ROUTING)
    if missing_state.isna().any():
        raise ValueError('Q1 라우팅에 없는 state가 있습니다.')
    out['q1_routing_status'] = missing_state
    out['residual_category'] = panel['industry'].isin(config.RESIDUAL_CATEGORIES)
    out['routeability_status'] = np.where(out['residual_category'], config.ROUTEABILITY_RESIDUAL,
                                          config.ROUTEABILITY_SINGLE)
    return out


# ---------------------------------------------------------------- QoQ·업체 수 보조지표
def qoq_and_firm_context(panel):
    """QoQ 고용 변화와 업체 수 보조지표. ELECTRE 기준·점검단계에는 사용하지 않는다."""
    adjacent = previous_quarter_adjacent(panel)
    index = panel.index
    out = pd.DataFrame(index=index)
    prev_emp = adjacent_previous(panel, 'employment', adjacent)
    out['emp_qoq_delta'] = clean_negative_zero(panel['employment'] - prev_emp)
    qoq_na = out['emp_qoq_delta'].isna() | panel['employment_yoy'].isna()
    out['qoq_recovery_while_yoy_below'] = masked_bool(
        (out['emp_qoq_delta'] > 0) & (panel['employment_yoy'] < 0), qoq_na, index)

    firms = panel['firms_op'].astype(float)
    prev_firms = adjacent_previous(panel, 'firms_op', adjacent)
    out['firm_count_delta_qoq'] = clean_negative_zero(firms - prev_firms)
    out['firm_count_delta_yoy'] = clean_negative_zero(firms - panel['firms_op_lag4'].astype(float))
    out['firm_count_changed_yoy'] = masked_bool(out['firm_count_delta_yoy'] != 0,
                                                out['firm_count_delta_yoy'].isna(), index)
    out['emp_per_firm'] = (panel['employment'] / firms).where(firms > 0)
    out['small_firm_count_flag'] = masked_bool(firms <= config.SMALL_FIRM_COUNT_MAX, firms.isna(), index)
    out['small_firm_caution'] = np.where(out['small_firm_count_flag'].fillna(False),
                                         config.SMALL_FIRM_CAUTION, '')
    return out


# ---------------------------------------------------------------- 최근·규모 설명 지표(카드용)
def recent_and_scale_context(panel, mfg):
    """최근 4분기 고용 YoY 음수 횟수, 고용 YoY 음수 진입, 고용비중, 기여율, 비례배분 기준선.

    mfg는 src/eda/panel.manufacturing_totals()의 결과이며 기여율 표시 기준(contrib_usable)을 그대로 쓴다.
    """
    index = panel.index
    cal = calendar_ordinal(panel['quarter'])
    yoy = panel['employment_yoy'].to_numpy(dtype=float)
    count = np.zeros(len(panel))
    valid_n = np.zeros(len(panel))
    for positions in panel.groupby('industry', sort=False).indices.values():
        idx = np.asarray(positions)
        lookup = dict(zip(cal[idx], yoy[idx]))
        for i in idx:
            window = [lookup.get(c, np.nan) for c in range(cal[i] - 3, cal[i] + 1)]
            valid = [v for v in window if not np.isnan(v)]
            valid_n[i] = len(valid)
            count[i] = sum(v < 0 for v in valid)
    out = pd.DataFrame(index=index)
    out['recent4_emp_yoy_negative_count'] = count.astype(int)
    out['recent4_emp_valid_n'] = valid_n.astype(int)

    adjacent = previous_quarter_adjacent(panel)
    prev_yoy = adjacent_previous(panel, 'employment_yoy', adjacent)
    entry_na = prev_yoy.isna() | panel['employment_yoy'].isna()
    out['emp_yoy_negative_entry'] = masked_bool((prev_yoy >= 0) & (panel['employment_yoy'] < 0),
                                                entry_na, index)

    quarter_emp = panel.groupby('quarter')['employment'].transform('sum')
    quarter_lag = panel.groupby('quarter')['employment_lag4'].transform('sum')
    out['employment_share_pct'] = panel['employment'] / quarter_emp * 100
    m = mfg.reindex(panel['quarter'].astype(str))
    net = pd.Series(m['mfg_emp_delta'].to_numpy(dtype=float), index=index)
    usable = pd.Series(m['contrib_usable'].to_numpy(dtype=bool), index=index)
    out['mfg_emp_delta'] = net
    out['net_gross_ratio'] = m['net_gross_ratio'].to_numpy(dtype=float)
    out['contrib_usable'] = usable
    out['contribution_pct'] = (panel['emp_delta'] / net * 100).where(usable)
    out['proportional_expected_delta'] = panel['employment_lag4'] / quarter_lag * net
    out['excess_delta'] = panel['emp_delta'] - out['proportional_expected_delta']
    return out


# ---------------------------------------------------------------- 가동률(카드 보조정보)
def _used_op_rate(frame):
    official, approx = frame['op_rate_official'], frame['op_rate_approx']
    used = official.where(official.notna(), approx)
    source = np.select([official.notna(), approx.notna()], ['op_rate_official', 'op_rate_approx'],
                       default='')
    return used, pd.Series(source, index=frame.index).replace('', None)


def op_rate_context(panel, master=None):
    """가동률 사용값: 공식값 우선, 결측이면 근사값. 출처·근사 여부를 별도 컬럼으로 둔다.

    전년동기 대비 %p 변화는 당분기와 전년동기의 출처가 같을 때만 계산한다(공식·근사 혼합 금지).
    가동률 방향은 판정을 바꾸지 않는다.
    """
    out = pd.DataFrame(index=panel.index)
    used, source = _used_op_rate(panel)
    out['op_rate_used'] = used
    out['op_rate_used_source'] = source
    out['op_rate_is_approx'] = masked_bool(source.eq('op_rate_approx').fillna(False), source.isna(),
                                           panel.index)
    lag_q = [str(pd.Period(q, freq='Q') - 4) for q in panel['quarter'].astype(str)]
    if master is None:
        out['op_rate_used_yoy_pp'] = np.nan
        out['op_rate_yoy_basis'] = 'LAG_SOURCE_NOT_AVAILABLE'
        return out
    m_used, m_source = _used_op_rate(master)
    lag = pd.DataFrame({'industry': master['industry'], 'quarter': master['quarter'].astype(str),
                        'lag_used': m_used, 'lag_source': m_source})
    keys = pd.DataFrame({'industry': panel['industry'].to_numpy(), 'quarter': lag_q})
    joined = keys.merge(lag, on=['industry', 'quarter'], how='left', validate='many_to_one')
    lag_used = pd.Series(joined['lag_used'].to_numpy(dtype=float), index=panel.index)
    lag_source = pd.Series(joined['lag_source'].to_numpy(dtype=object), index=panel.index)
    same = source.notna() & lag_source.notna() & source.eq(lag_source).fillna(False)
    out['op_rate_used_yoy_pp'] = clean_negative_zero((used - lag_used).where(same))
    out['op_rate_yoy_basis'] = np.select(
        [same, source.notna() & lag_source.notna()],
        ['SAME_SOURCE', 'MIXED_SOURCE_NOT_COMPUTED'], default='MISSING')
    if 'op_rate_official_yoy_pp' in panel:
        both = panel['op_rate_official_yoy_pp'].notna()
        if not np.allclose(out.loc[both, 'op_rate_used_yoy_pp'], panel.loc[both, 'op_rate_official_yoy_pp']):
            raise ValueError('가동률 공식값 전년동기 차이가 기준 패널과 다릅니다.')
    out['op_rate_prod_direction_differs'] = masked_bool(
        np.sign(out['op_rate_used_yoy_pp']) != np.sign(panel['production_yoy']),
        out['op_rate_used_yoy_pp'].isna() | panel['production_yoy'].isna()
        | out['op_rate_used_yoy_pp'].eq(0) | panel['production_yoy'].eq(0), panel.index)
    return out


# ---------------------------------------------------------------- 180행 입력 패널
def build_input_panel(state, ctx, mfg, master=None):
    """ELECTRE 입력 패널(업종×분기 전체 행). 결측행을 삭제하지 않는다."""
    base = sort_panel(state)
    missing = [c for c in BASE_COLUMNS if c not in base]
    if missing:
        raise KeyError(f'기준 패널 필수 컬럼 누락: {missing}')
    window_n = len(ctx.quarters)
    criteria = core_criteria(base)
    parts = [
        base[BASE_COLUMNS],
        criteria,
        g4_sensitivity_columns(base, window_n, ctx.latest),
        threshold_quality_flags(base),
        status_fields(base, criteria),
        qoq_and_firm_context(base),
        base[['firms_op', 'firms_op_lag4', 'firms_in', 'firms_op_yoy']],
        recent_and_scale_context(base, mfg),
        op_rate_context(base, master),
    ]
    panel = pd.concat(parts, axis=1)
    panel.insert(3, 'analysis_window_n', window_n)
    return panel
