# -*- coding: utf-8 -*-
"""Section 1 — EDA(분석 대상 요약·총량 흐름·업종 규모·지수·YoY 분포·생산고용 관계).

notebooks/02_eda.ipynb 셀 18·20·23·25·28·31·32의 계산을 그대로 옮겼다.
이 절은 국면(S1~S4)을 쓰지 않는다.
"""
import numpy as np
import pandas as pd

from . import config


# ---------------------------------------------------------------- 1-1. 분석 대상 요약
def scope_summary(state, ctx):
    """분석에 실제로 쓸 수 있는 구간과 변수 범위를 정리한다.

    Returns
    -------
    eda_scope : DataFrame
    n_valid_pair : int   생산·고용 YoY가 모두 있는 관측 수
    """
    n_valid_pair = int(state.valid_state.sum())
    eda_scope = pd.Series({
        '분석 시작분기': ctx.quarters[0],
        '분석 종료분기': ctx.latest,
        '전체 분기 수': f'{len(ctx.quarters)}분기',
        '업종 수': f'{len(ctx.industries)}개',
        '업종×분기 관측치': f'{len(state):,}행',
        '생산 YoY 유효 관측치': f'{int(state.production_yoy.notna().sum()):,}행 '
                         f'({state.production_yoy.notna().mean() * 100:.1f}%)',
        '고용 YoY 유효 관측치': f'{int(state.employment_yoy.notna().sum()):,}행 '
                         f'({state.employment_yoy.notna().mean() * 100:.1f}%)',
        '생산·고용 YoY 모두 있는 관측치': f'{n_valid_pair:,}행 ({n_valid_pair / len(state) * 100:.1f}%)',
        'INVALID 분기': ', '.join(ctx.invalid_quarters) or '없음',
        '최신분기': f'{ctx.latest} (전년동기 = {ctx.base_q})',
    }, name='값').to_frame()
    return eda_scope, n_valid_pair


def variable_summary(state, eda_vars=None):
    """핵심 변수만 본다. 평균·분산 등 추가 기술통계는 이 단계에서 필요하지 않다."""
    eda_vars = config.EDA_VARS if eda_vars is None else eda_vars
    return pd.DataFrame(
        [{'변수': c, '내용': label,
          '유효 관측': int(state[c].notna().sum()), '결측': int(state[c].isna().sum()),
          '중앙값': state[c].median(), '최소': state[c].min(), '최대': state[c].max()}
         for c, label in eda_vars.items()]).set_index('변수')


def production_na_quarters(state):
    """생산 YoY가 결측인 분기 목록."""
    return sorted(state.loc[state.production_yoy.isna(), 'quarter'].unique())


# ---------------------------------------------------------------- 1-2. 총량 지수
def total_index(total):
    """산단 전체 생산·고용을 첫 분기 = 100으로 지수화한다."""
    t = total.sort_values('quarter').reset_index(drop=True)
    t['production_idx'] = t.production_total / t.production_total.iloc[0] * 100
    t['employment_idx'] = t.employment_total / t.employment_total.iloc[0] * 100
    return t


# ---------------------------------------------------------------- 1-3. 업종별 규모
def industry_share(state, ctx):
    """최신분기 업종별 생산·고용 비중(정렬은 고용비중 오름차순 = IND_ORDER_EMP 역순)."""
    cur_lat = state[state.quarter == ctx.latest].set_index('industry')
    return pd.DataFrame({
        '생산비중': cur_lat.production / cur_lat.production.sum() * 100,
        '고용비중': cur_lat.employment / cur_lat.employment.sum() * 100,
    }).reindex(ctx.ind_order_emp[::-1])


# ---------------------------------------------------------------- 1-4. 업종별 지수
def industry_index(state, ctx):
    """각 업종의 분석 시작분기 값을 100으로 둔 생산·고용 지수.

    state에 덮어쓰지 않는다. EDA 전용 임시 프레임에서만 지수를 만든다.
    """
    eda_idx = state[['industry', 'quarter', 'quarter_index', 'production', 'employment']].copy()
    eda_base = (eda_idx[eda_idx.quarter == ctx.quarters[0]].set_index('industry')
                [['production', 'employment']].replace(0, np.nan))   # 0으로 나누지 않는다
    assert eda_base.notna().all().all(), f'{ctx.quarters[0]} 기준값이 없는 업종이 있어 지수를 만들 수 없다'
    eda_idx['production_index_industry'] = (eda_idx.production
                                            / eda_idx.industry.map(eda_base.production) * 100)
    eda_idx['employment_index_industry'] = (eda_idx.employment
                                            / eda_idx.industry.map(eda_base.employment) * 100)
    return eda_idx, eda_base


def missing_production_quarters(state):
    """생산액이 없는 분기(지수 그림의 회색 띠 대상)."""
    return sorted(state.loc[state.production.isna(), 'quarter'].unique())


def latest_index_summary(eda_idx, ctx):
    """최신분기 업종별 지수와 100 기준 분류.

    Returns
    -------
    eda_last_idx : DataFrame
    eda_pu, eda_eu, eda_split : list   생산지수>100 / 고용지수>100 / 두 지수가 100의 반대편
    """
    eda_last_idx = (eda_idx[eda_idx.quarter == ctx.latest].set_index('industry')
                    .reindex(ctx.ind_order_emp)
                    [['production_index_industry', 'employment_index_industry']]
                    .rename(columns={'production_index_industry': '생산지수',
                                     'employment_index_industry': '고용지수'}))
    eda_last_idx['지수차(생산-고용)'] = eda_last_idx.생산지수 - eda_last_idx.고용지수
    eda_pu = eda_last_idx[eda_last_idx.생산지수 > 100].index.tolist()
    eda_eu = eda_last_idx[eda_last_idx.고용지수 > 100].index.tolist()
    eda_split = eda_last_idx[((eda_last_idx.생산지수 > 100) & (eda_last_idx.고용지수 < 100)) |
                             ((eda_last_idx.생산지수 < 100) & (eda_last_idx.고용지수 > 100))].index.tolist()
    return eda_last_idx, eda_pu, eda_eu, eda_split


# ---------------------------------------------------------------- 1-5. YoY 분포·극단 관측
def yoy_range(state, ctx):
    """유효 관측 프레임과 업종별 생산·고용 YoY의 최소/중앙/최대."""
    eda_valid = state[state.valid_state == True].copy()   # noqa: E712
    eda_range = pd.concat({
        '생산YoY%': eda_valid.groupby('industry').production_yoy.agg(['min', 'median', 'max']),
        '고용YoY%': eda_valid.groupby('industry').employment_yoy.agg(['min', 'median', 'max']),
    }, axis=1).reindex(ctx.ind_order_emp)
    return eda_valid, eda_range


def yoy_range_by_industry(eda_valid, col, order):
    """그림용 — 지정한 업종 순서 기준의 min/median/max."""
    return eda_valid.groupby('industry')[col].agg(['min', 'median', 'max']).reindex(order)


def extreme_observations(state, eda_valid, ctx, topn=config.EDA_TOPN):
    """두 변수 각각의 절대 변화율 상위 관측을 뽑아 합치고 중복을 제거한다.

    같은 업종×분기는 한 번만 남긴다. 과거 극단 관측의 규모는 최신분기가 아니라
    해당 관측 분기의 제조업 고용 합을 분모로 계산한다.
    """
    eda_valid['abs_p'] = eda_valid.production_yoy.abs()
    eda_valid['abs_e'] = eda_valid.employment_yoy.abs()
    pick = pd.concat([eda_valid.nlargest(topn, 'abs_p').assign(선정기준='생산 YoY'),
                      eda_valid.nlargest(topn, 'abs_e').assign(선정기준='고용 YoY')])
    basis = (pick.groupby(['quarter', 'industry']).선정기준
             .agg(lambda s: '생산·고용 모두' if s.nunique() > 1 else s.iloc[0]))
    eda_extreme = (pick.drop_duplicates(['quarter', 'industry']).set_index(['quarter', 'industry'])
                   .assign(선정기준=basis))
    eda_extreme = (eda_extreme.assign(_key=eda_extreme[['abs_p', 'abs_e']].max(axis=1))
                   .sort_values('_key', ascending=False)
                   [['production_yoy', 'employment_yoy', 'production', 'employment', '선정기준']]
                   .rename(columns={'production_yoy': '생산YoY%', 'employment_yoy': '고용YoY%',
                                    'production': '명목생산액(억원)', 'employment': '고용(명)'}))
    quarter_emp_total = state.groupby('quarter').employment.sum(min_count=len(ctx.industries))
    eda_extreme['해당분기_고용비중%'] = [
        emp / quarter_emp_total.loc[quarter] * 100
        for (quarter, _industry), emp in zip(eda_extreme.index, eda_extreme['고용(명)'])
    ]
    return eda_extreme


# ---------------------------------------------------------------- 1-6. 전체기간 생산–고용 관계
EDA_DIRS = ['같은 방향', '다른 방향', '한 지표 0%']


def pair_directions(state, eda_extreme, ctx):
    """전체기간 업종×분기 관측의 변화 방향 분류와 확대 패널 범위.

    STATE_COLORS와 국면 이름을 쓰지 않는다. 여기서는 관측 분포만 본다.
    확대 패널의 범위는 1-5에서 이미 확인한 극단 관측을 제외해서 정한다(새 기준을 만들지 않는다).

    Returns
    -------
    eda_pair : DataFrame
    eda_dir_counts : Series
    zoom : dict   확대 패널 범위(xr/yr/xp/yp)와 제외 건수(n_out)
    """
    eda_pair = state[state.valid_state == True].copy()   # noqa: E712
    p, e = eda_pair.production_yoy, eda_pair.employment_yoy
    eda_pair['방향'] = np.where((p == 0) | (e == 0), '한 지표 0%',
                              np.where(np.sign(p) == np.sign(e), '같은 방향', '다른 방향'))
    eda_dir_counts = eda_pair.방향.value_counts().reindex(EDA_DIRS, fill_value=0)

    ext_keys = set(eda_extreme.index)
    eda_pair['극단'] = [(q, i) in ext_keys for q, i in zip(eda_pair.quarter, eda_pair.industry)]
    core_mask = ~eda_pair.극단 | eda_pair.quarter.eq(ctx.latest)   # 최신분기는 항상 확대 범위에 포함
    core = eda_pair[core_mask]
    xr = (core.production_yoy.min(), core.production_yoy.max())
    yr = (core.employment_yoy.min(), core.employment_yoy.max())
    zoom = {'xr': xr, 'yr': yr,
            'xp': (xr[1] - xr[0]) * 0.14, 'yp': (yr[1] - yr[0]) * 0.12,
            'n_out': int((~core_mask).sum())}
    return eda_pair, eda_dir_counts, zoom


def direction_table(eda_pair, eda_dir_counts):
    """변화 방향별 관측 수와 비율(합계 행 포함)."""
    table = pd.DataFrame({
        '관측 수': eda_dir_counts,
        '비율%': eda_dir_counts / len(eda_pair) * 100,
    })
    table.loc['합계'] = [len(eda_pair), 100.0]
    return table


def eda_results(state, eda_pair, eda_dir_counts):
    """results_summary['eda']에 들어가는 값."""
    return {
        'n_valid_pairs': int(len(eda_pair)),
        'n_same_direction': int(eda_dir_counts['같은 방향']),
        'n_opposite_direction': int(eda_dir_counts['다른 방향']),
        'n_zero_involved': int(eda_dir_counts['한 지표 0%']),
        'opposite_pct_all': float(eda_dir_counts['다른 방향'] / len(eda_pair) * 100),
        'opposite_pct_excl_zero': float(eda_dir_counts['다른 방향'] /
                                        (eda_dir_counts['같은 방향'] + eda_dir_counts['다른 방향']) * 100),
        'n_invalid_excluded': int((~state.valid_state).sum()),
    }


# ---------------------------------------------------------------- EDA → Q1·Q2·Q3 연결
def total_yoy_direction(total, ctx):
    """산단 전체 총량 YoY와 생산·고용 방향이 달랐던 분기."""
    tot = total.set_index(pd.PeriodIndex(total.quarter, freq='Q')).sort_index()
    tot = tot.reindex(pd.period_range(tot.index.min(), tot.index.max(), freq='Q'))
    tot_yoy = pd.DataFrame({
        '명목 생산액': tot.production_total.pct_change(4) * 100,
        '고용': tot.employment_total.pct_change(4) * 100,
    })
    tot_yoy = tot_yoy.loc[[pd.Period(q, freq='Q') for q in ctx.quarters]].dropna()
    tot_diff = tot_yoy[(np.sign(tot_yoy['명목 생산액']) != np.sign(tot_yoy.고용)) &
                       (tot_yoy['명목 생산액'] != 0) & (tot_yoy.고용 != 0)]
    return tot_yoy, tot_diff


def eda_bridge(state, total, ctx):
    """EDA 결과를 Q1 → Q2 → Q3 질문으로 연결하는 값."""
    tot_yoy, tot_diff = total_yoy_direction(total, ctx)
    lat = state[(state.quarter == ctx.latest) & state.valid_state].set_index('industry')
    return {
        'total_quarters_compared': int(len(tot_yoy)),
        'total_quarters_direction_differs': int(len(tot_diff)),
        'latest_top_abs_employment_yoy_industry': lat.employment_yoy.abs().idxmax(),
        'latest_largest_employment_industry': lat.employment.idxmax(),
    }
