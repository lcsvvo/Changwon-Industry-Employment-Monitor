"""KICOX master -> state/run/transition analysis panel. Offline only. No collection or external joins.

입력: data/processed/kicox/changwon_industry_master.csv, changwon_total_master.csv
      (build_changwon_master.py 산출물 — 이 모듈은 원자료를 직접 읽지 않는다)
출력: data/processed/kicox/changwon_state_panel.csv            (본분석기간, threshold=0)
      data/processed/kicox/changwon_state_reference_panel.csv  (전체 참고기간, threshold=0)
      data/processed/kicox/changwon_state_sensitivity_panel.csv(본분석기간, threshold=0.5/1/2)
      data/processed/kicox/quality_report.json
      logs/preprocessing/{trace_examples.csv, exclusion_or_review_log.csv}
"""
from pathlib import Path
import json
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
REFERENCE_START = '2018Q1'
START, END = '2022Q1', '2026Q2'   # 본분석기간: 사용자 승인 완료 (2026-09-08). 근거는 docs/01_planning 및 계획서 참조.
STATES = ['S1', 'S2', 'S3', 'S4']
INDUSTRIES = ['음식료', '섬유의복', '목재종이', '석유화학', '비금속', '철강', '기계', '전기전자', '운송장비', '기타']

DIR_PROC = ROOT / 'data' / 'processed' / 'kicox'
DIR_LOG = ROOT / 'logs' / 'preprocessing'


def load_inputs(root=ROOT):
    root = Path(root)
    d = pd.read_csv(root / 'data/processed/kicox/changwon_industry_master.csv')
    t = pd.read_csv(root / 'data/processed/kicox/changwon_total_master.csv')
    return d, t


def validate_schema(d, t):
    n_q = d.quarter.nunique()
    assert len(d) == n_q * len(INDUSTRIES), f'industry master row count mismatch: {len(d)} != {n_q}*{len(INDUSTRIES)}'
    assert len(t) == t.quarter.nunique(), 'total master has duplicate quarters'
    assert set(d.industry) == set(INDUSTRIES)
    assert not d.duplicated(['industry', 'quarter']).any()
    assert not t.quarter.duplicated().any()
    qs = sorted(d.quarter.unique())
    expected = list(pd.period_range(qs[0], qs[-1], freq='Q').astype(str))
    assert sorted(t.quarter) == expected, 'total master quarters are not a continuous range'
    for _, g in d.groupby('industry'):
        assert sorted(g.quarter) == expected, 'industry master quarters are not continuous per industry'
    assert set(d.complex_nm) == {'창원'}
    for v in ['production', 'employment', 'firms_in', 'firms_op']:
        assert d[v].dropna().ge(0).all()
    assert not (d.op_rate_official.notna() & d.op_rate_approx.notna()).any()


def prepare(d):
    """YoY, 재분류 위험 플래그, 보조변수를 만든다. 업종 경계를 넘지 않도록 반드시
    groupby('industry') 내부에서만 shift/lag를 계산한다."""
    d = d.sort_values(['industry', 'quarter']).reset_index(drop=True).copy()
    d['quarter_index'] = pd.PeriodIndex(d.quarter, freq='Q').asi8
    d['in_main_period'] = d.quarter.between(START, END)
    q = d.quarter
    # 조사개요 명시 표본교체·업종재분류 시점을 가로지르는 비교는 위험으로만 표시한다(실증된 개별 업종 영향 아님).
    d['classification_event_recorded'] = q.isin(['2018Q4', '2020Q3'])
    d['classification_scope_verified'] = False
    for v in ['production', 'employment', 'firms_in', 'firms_op']:
        lag = d.groupby('industry')[v].shift(4)
        d[v + '_lag4'] = lag
        d[v + '_current_missing'] = d[v].isna()
        d[v + '_lag4_missing'] = lag.isna()
        d[v + '_lag4_absent'] = d.groupby('industry').cumcount().lt(4)
        d[v + '_current_zero'] = d[v].eq(0)
        d[v + '_denominator_zero'] = lag.eq(0)
        risk = q.between('2018Q4', '2019Q3') | q.between('2020Q3', '2021Q3' if v == 'production' else '2021Q2')
        d[v + '_classification_risk'] = risk
        y = ((d[v] / lag - 1) * 100).where(lag.gt(0) & d[v].notna())
        assert np.isfinite(y.dropna()).all()
        d[v + '_yoy'] = y
        d[v + '_yoy_computable'] = y.notna()
        d[v + '_yoy_valid'] = y.notna() & ~risk
        reasons_col = []
        for _, row in d.iterrows():
            parts = [reason for condition, reason in [
                (row[v + '_current_missing'], 'current_missing'),
                (row[v + '_lag4_absent'], 'lag4_not_observed'),
                (row[v + '_lag4_missing'] and not row[v + '_lag4_absent'], 'lag4_missing'),
                (row[v + '_denominator_zero'], 'denominator_zero'),
                (row[v + '_classification_risk'], 'classification_comparison_risk')] if condition]
            reasons_col.append('|'.join(parts) or 'valid')
        d[v + '_yoy_reason'] = reasons_col
    d['quadrant_yoy_valid'] = d.production_yoy_valid & d.employment_yoy_valid
    d['missing_flag'] = d.production_current_missing | d.employment_current_missing
    d['classification_comparison_risk'] = d.production_classification_risk | d.employment_classification_risk
    d['analysis_exclusion_reason'] = np.where(
        d.quadrant_yoy_valid, '', d.production_yoy_reason + ';' + d.employment_yoy_reason)
    d['review_required'] = d.review_required.astype(bool) | d.classification_comparison_risk

    # 가동률: 공표전환(2024Q2) 이후는 분기 공식값만 사용. %p 변화(수준차, 비율 아님)로 QoQ/YoY 산출.
    d['op_rate_official_valid'] = d.op_rate_official.notna() & d.quarter.ge('2024Q2')
    for lag, label in [(1, 'qoq'), (4, 'yoy')]:
        prev = d.groupby('industry').op_rate_official.shift(lag)
        d['op_rate_official_' + label + '_pp'] = d.op_rate_official - prev

    totals = d.groupby('quarter').production.transform(lambda s: s.sum(min_count=10))
    d['production_share'] = (d.production / totals).where(totals.gt(0))
    d['employment_share'] = d.employment / d.groupby('quarter').employment.transform('sum')
    d['active_firm_ratio'] = (d.firms_op / d.firms_in).where(d.firms_in.gt(0))
    return d


def classify(d, threshold=0):
    """본분석 state: threshold=0, 정확한 0은 N. sensitivity: threshold=0.5/1/2.
    N과 INVALID는 별개 상태다 — INVALID는 quadrant_yoy_valid==False(결측/계산불가)일 때만,
    N은 유효한 YoY가 있으나 절대값이 threshold 이하(정확히 0 포함)일 때만 부여한다."""
    d = d.copy()
    d['threshold'] = threshold
    d['valid_state'] = d.quadrant_yoy_valid.astype(bool)
    p, e = d.production_yoy, d.employment_yoy
    d['exact_zero'] = d.valid_state & (p.eq(0) | e.eq(0))
    d['neutral'] = d.valid_state & (p.abs().le(threshold) | e.abs().le(threshold))
    d['state'] = np.select(
        [~d.valid_state, d.neutral, p.gt(0) & e.gt(0), p.gt(0) & e.lt(0), p.lt(0) & e.gt(0)],
        ['INVALID', 'N', 'S1', 'S2', 'S3'], default='S4')
    d['valid_four_state'] = d.state.isin(STATES)
    return d


def sequences(d):
    """Calendar adjacency only. INVALID breaks four-state runs; no gap bridging.
    같은 업종 + 실제 연속분기일 때만 transition을 유효로 본다."""
    d = d.copy().sort_values(['industry', 'quarter']).reset_index(drop=True)
    for col in ['previous_state', 'previous_valid_state', 'next_state', 'state_start_quarter',
                'run_id', 'transition_type']:
        d[col] = pd.Series(pd.NA, index=d.index, dtype='string')
    for col in ['run_length', 'run_total_length']:
        d[col] = pd.Series(pd.NA, index=d.index, dtype='Int64')
    for col in ['valid_transition', 'valid_transition5', 'valid_previous_transition',
                'run_left_censored', 'run_right_censored']:
        d[col] = False
    d['transition_changed'] = pd.Series(pd.NA, index=d.index, dtype='boolean')
    for industry, g in d.groupby('industry', sort=False):
        ix = list(g.index)
        last_valid = pd.NA
        runs = []
        run = []
        for j, i in enumerate(ix):
            s = d.at[i, 'state']
            d.at[i, 'previous_valid_state'] = last_valid
            if j:
                prev = ix[j - 1]
                assert d.at[i, 'quarter_index'] - d.at[prev, 'quarter_index'] == 1, \
                    '같은 업종 내 인접 분기가 아닌데 transition을 계산하려 했습니다'
                d.at[i, 'previous_state'] = d.at[prev, 'state']
                d.at[i, 'valid_previous_transition'] = s in STATES and d.at[prev, 'state'] in STATES
            if s != 'INVALID':
                last_valid = s
            if s in STATES:
                if run and d.at[run[-1], 'state'] != s:
                    runs.append(run)
                    run = []
                run.append(i)
            elif run:
                runs.append(run)
                run = []
            if j < len(ix) - 1:
                nxt = ix[j + 1]
                ns = d.at[nxt, 'state']
                d.at[i, 'next_state'] = ns
                v5 = s != 'INVALID' and ns != 'INVALID'
                v4 = s in STATES and ns in STATES
                d.at[i, 'valid_transition5'] = v5
                d.at[i, 'valid_transition'] = v4
                if v5:
                    d.at[i, 'transition_type'] = s + '->' + ns
                    d.at[i, 'transition_changed'] = s != ns
        if run:
            runs.append(run)
        for r in runs:
            start, end = r[0], r[-1]
            left = start == ix[0] or d.at[start - 1, 'state'] == 'INVALID'
            right = end == ix[-1] or d.at[end + 1, 'state'] == 'INVALID'
            for k, i in enumerate(r):
                d.at[i, 'run_id'] = industry + ':' + d.at[start, 'quarter']
                d.at[i, 'state_start_quarter'] = d.at[start, 'quarter']
                d.at[i, 'run_length'] = k + 1
                d.at[i, 'run_total_length'] = len(r)
                d.at[i, 'run_left_censored'] = left
                d.at[i, 'run_right_censored'] = right
        for state in STATES + ['N']:
            d.loc[ix, 'recent4_' + state + '_count'] = g.state.eq(state).rolling(4, min_periods=1).sum().to_numpy()
        d.loc[ix, 'recent4_valid_n'] = g.valid_state.rolling(4, min_periods=1).sum().to_numpy()
        d.loc[ix, 'recent4_window_n'] = np.minimum(np.arange(1, len(ix) + 1), 4)
    return d


def audit(full, main, sens):
    report = {
        'pipeline': 'offline_reproducible',
        'main_period': [START, END],
        'reference_period': [REFERENCE_START, END],
        'rows': len(main), 'columns': len(main.columns), 'industries': main.industry.nunique(),
        'valid_state': int(main.valid_state.sum()), 'invalid_state': int((~main.valid_state).sum()),
        'states': main.state.value_counts().to_dict(), 'exact_zero': int(main.exact_zero.sum()),
        'valid_transition4': int(main.valid_transition.sum()),
        'valid_transition5': int(main.valid_transition5.sum()),
        'changed_transition4': int((main.valid_transition & main.transition_changed.fillna(False)).sum()),
        'review_rows': int(main.review_required.sum()),
        'missing': main[['production', 'employment', 'production_yoy', 'employment_yoy',
                         'op_rate_official', 'op_rate_approx']].isna().sum().to_dict(),
    }
    assert not main.duplicated(['industry', 'quarter']).any()
    for _, g in main.groupby('industry'):
        assert g.iloc[0].quarter == START and g.iloc[-1].quarter == END
        assert pd.isna(g.iloc[0].previous_state) and not g.iloc[0].valid_previous_transition
        assert pd.isna(g.iloc[-1].next_state) and not g.iloc[-1].valid_transition5
    report['run_total_length_distribution'] = {
        str(k): int(v) for k, v in main.dropna(subset=['run_id']).drop_duplicates('run_id')
        .run_total_length.value_counts().sort_index().items()}
    report['near_zero_distribution'] = {
        v: {str(h): int((main[v + '_yoy'].abs().le(h) & main.valid_state).sum()) for h in [0, .5, 1, 2]}
        for v in ['production', 'employment']}
    report['yoy_quantiles'] = {
        v: main[v + '_yoy'].quantile([0, .01, .25, .5, .75, .99, 1]).to_dict()
        for v in ['production', 'employment']}
    report['sensitivity'] = {
        str(h): {'states': g.state.value_counts().to_dict(), 'transitions4': int(g.valid_transition.sum())}
        for h, g in sens.groupby('threshold')}
    return report


def save_outputs(full, main, sens, report):
    DIR_PROC.mkdir(parents=True, exist_ok=True)
    DIR_LOG.mkdir(parents=True, exist_ok=True)
    main.to_csv(DIR_PROC / 'changwon_state_panel.csv', index=False, encoding='utf-8-sig')
    full.to_csv(DIR_PROC / 'changwon_state_reference_panel.csv', index=False, encoding='utf-8-sig')
    sens.to_csv(DIR_PROC / 'changwon_state_sensitivity_panel.csv', index=False, encoding='utf-8-sig')
    (DIR_PROC / 'quality_report.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=int) + '\n', encoding='utf-8')

    columns = ['quarter', 'industry', 'production', 'production_lag4', 'employment', 'employment_lag4',
               'production_yoy', 'employment_yoy', 'state', 'previous_state', 'next_state',
               'state_start_quarter', 'run_length', 'run_total_length', 'valid_transition', 'transition_type']
    main[main.industry.isin(['기계', '철강', '섬유의복'])][columns].to_csv(
        DIR_LOG / 'trace_examples.csv', index=False, encoding='utf-8-sig')
    full.loc[(~full.valid_state) | full.review_required,
             ['quarter', 'industry', 'in_main_period', 'valid_state', 'review_required',
              'production_yoy_reason', 'employment_yoy_reason',
              'classification_event_recorded', 'classification_comparison_risk']].to_csv(
        DIR_LOG / 'exclusion_or_review_log.csv', index=False, encoding='utf-8-sig')
    return DIR_PROC


def run(root=ROOT):
    d, t = load_inputs(root)
    validate_schema(d, t)
    prepared = prepare(d)
    full = sequences(classify(prepared))
    main = sequences(classify(prepared[prepared.in_main_period]))
    sens = pd.concat([sequences(classify(prepared[prepared.in_main_period], h)) for h in [.5, 1, 2]],
                     ignore_index=True)
    report = audit(full, main, sens)
    out = save_outputs(full, main, sens, report)
    print(json.dumps(report, ensure_ascii=False, indent=2, default=int))
    return out


if __name__ == '__main__':
    run()
