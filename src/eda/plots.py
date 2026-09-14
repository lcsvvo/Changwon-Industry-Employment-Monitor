# -*- coding: utf-8 -*-
"""EDA 시각화 — notebooks/02_eda.ipynb의 그림을 그대로 옮긴 함수 모음.

변수·축·정렬·기준선·표시 대상·label·범례·색상 의미·figure 저장 이름은 노트북과 동일하다.
새 디자인을 만들지 않으며, 계산은 각 분석 모듈에서 끝낸 결과를 입력으로 받는다.
"""
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from matplotlib.colors import ListedColormap, BoundaryNorm
from matplotlib.lines import Line2D

from . import config

STATE_COLORS = config.STATE_COLORS
STATE_LABELS = config.STATE_LABELS
STATES4 = config.STATES4
STATES5 = config.STATES5
STATES6 = config.STATES6
DELTA_COLORS = config.DELTA_COLORS
SERIES_COLORS = config.SERIES_COLORS
MAIN_COLORS = config.MAIN_COLORS
REST_COLOR = config.REST_COLOR


# ---------------------------------------------------------------- 도우미 함수
def style_ax(ax, ygrid=True, xgrid=False):
    """상단/우측 spine 제거 + grid 규칙 — 전 Figure 공통 레이아웃."""
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.grid(axis='y', alpha=0.22) if ygrid else None
    ax.grid(axis='x', alpha=0.22) if xgrid else None
    ax.set_axisbelow(True)
    return ax


def save_fig(fig, name, dir_fig):
    fig.savefig(dir_fig / f'{name}.png', dpi=300, bbox_inches='tight')


def n_fmt(v, unit='명'):
    """증감 인원 표기: 부호 유지 + 천단위 구분."""
    if pd.isna(v):
        return '-'
    return f'{v:+,.0f}{unit}'


def bar_labels(ax, ys, values, fmt=lambda v: f'{v:+,.0f}', pad=None, fontsize=8.8):
    """수평 bar 끝에 값 라벨 — 막대 방향에 따라 좌/우 정렬을 바꿔 겹침을 막는다."""
    span = max(abs(v) for v in values if not pd.isna(v)) or 1
    pad = pad if pad is not None else span * 0.02
    for y, v in zip(ys, values):
        if pd.isna(v):
            continue
        ha = 'left' if v >= 0 else 'right'
        ax.text(v + (pad if v >= 0 else -pad), y, fmt(v),
                va='center', ha=ha, fontsize=fontsize, color='#333333')


def place_labels(ax, xs, ys, texts, offsets=None, fontsize=9.3, min_gap_px=13, split_at=None):
    """산점도 라벨을 점 오른쪽에 두고 화면좌표에서 세로 간격을 강제해 겹침을 없앤다.

    split_at을 주면 그 값 위/아래 점의 라벨이 경계를 넘지 않도록 각각 바깥쪽으로 밀어낸다
    (예: split_at=0이면 S1·S3 라벨은 0 위, S2·S4 라벨은 0 아래에 머문다).
    """
    ax.figure.canvas.draw()
    trans = ax.transData
    inv = trans.inverted()
    pts = trans.transform(np.column_stack([xs, ys])).astype(float)
    offsets = np.zeros(len(xs)) if offsets is None else np.asarray(offsets, float)
    lab = pts.copy()
    if split_at is None:
        groups = [(np.arange(len(xs)), 'up')]
    else:
        y0 = trans.transform([[np.mean(xs), split_at]])[0, 1]
        groups = [(np.where(pts[:, 1] >= y0)[0], 'up'), (np.where(pts[:, 1] < y0)[0], 'down')]
    for idx, direction in groups:
        if len(idx) == 0:
            continue
        if direction == 'up':
            order = idx[np.argsort(pts[idx, 1])]
            yy = pts[order, 1].copy()
            for i in range(1, len(yy)):
                yy[i] = max(yy[i], yy[i - 1] + min_gap_px)
        else:
            order = idx[np.argsort(-pts[idx, 1])]
            yy = pts[order, 1].copy()
            for i in range(1, len(yy)):
                yy[i] = min(yy[i], yy[i - 1] - min_gap_px)
        lab[order, 1] = yy
    lab[:, 0] += offsets
    label_data = inv.transform(lab)
    for (lx, ly), (px, py), t in zip(label_data, np.column_stack([xs, ys]), texts):
        ax.annotate(t, xy=(px, py), xytext=(lx, ly), textcoords='data',
                    va='center', ha='left', fontsize=fontsize,
                    arrowprops=dict(arrowstyle='-', color='#B8B8B8', lw=0.7,
                                    shrinkA=0, shrinkB=3))


# ---------------------------------------------------------------- 1-2. 총량 지수
def plot_total_index(t, ctx, dir_fig):
    """S1_배경_총량지수 — 산단 전체 생산·고용 지수."""
    fig, ax = plt.subplots(figsize=(10, 4.2))
    ax.plot(t.quarter, t.production_idx, color=SERIES_COLORS['production'], lw=2.2, label='명목 생산액 (지수)')
    ax.plot(t.quarter, t.employment_idx, color=SERIES_COLORS['employment'], lw=2.2, label='고용 (지수)')

    main_start_i = int(t.index[t.quarter == ctx.quarters[0]][0])
    ax.axvspan(main_start_i, len(t) - 1, color='#4C78A8', alpha=0.05, zorder=0)
    ax.axhline(100, color='#999999', lw=0.8, ls=':')
    ax.text(main_start_i + 0.3, 0.97, f'본분석기간({ctx.quarters[0]}~)', fontsize=8.5, color='#555555',
            va='top', ha='left', transform=ax.get_xaxis_transform())

    for col, key in [('production_idx', 'production'), ('employment_idx', 'employment')]:
        ax.annotate(f'{t[col].iloc[-1]:.1f}', (len(t) - 1, t[col].iloc[-1]), xytext=(6, 0),
                    textcoords='offset points', va='center', fontsize=9,
                    color=SERIES_COLORS[key], fontweight='bold')

    ax.set_xticks(range(0, len(t), 2))
    ax.set_xticklabels(t.quarter[::2], rotation=90, fontsize=7.5)
    ax.set_ylabel(f'{t.quarter.iloc[0]} = 100')
    ax.set_xlim(-0.5, len(t) + 1.5)
    ax.set_title(f'창원국가산단 전체 생산·고용 지수 ({t.quarter.iloc[0]}~{t.quarter.iloc[-1]}, {t.quarter.iloc[0]}=100)',
                 fontsize=11)
    ax.legend(loc='upper left', frameon=False, fontsize=9)
    style_ax(ax)
    plt.tight_layout()
    save_fig(fig, 'S1_배경_총량지수', dir_fig)
    return fig


# ---------------------------------------------------------------- 1-3. 업종별 규모
def plot_industry_share(share, ctx, dir_fig):
    """S1_배경_규모비중 — 최신분기 업종별 생산·고용 비중."""
    fig, ax = plt.subplots(figsize=(8, 4.6))
    y = np.arange(len(share))
    for yi, ind in zip(y, share.index):
        p, e = share.loc[ind, '생산비중'], share.loc[ind, '고용비중']
        ax.plot([p, e], [yi, yi], color='#CFCFCF', lw=1.8, zorder=1)
    ax.scatter(share.생산비중, y, color=SERIES_COLORS['production'], s=80, zorder=2, label='생산비중')
    ax.scatter(share.고용비중, y, s=80, zorder=2, label='고용비중',
               facecolor='white', edgecolor=SERIES_COLORS['employment'], linewidth=2.2)

    ax.set_yticks(y)
    ax.set_yticklabels(share.index, fontsize=10)
    ax.set_xlabel(f'제조업 전체(10개 업종) 대비 비중 (%, {ctx.latest})')
    ax.set_xlim(-2, max(share.max()) * 1.18)
    ax.set_title(f'{ctx.latest} 업종별 생산·고용 비중', fontsize=11)
    ax.legend(loc='lower right', frameon=False, fontsize=9)
    style_ax(ax, ygrid=False, xgrid=True)
    plt.tight_layout()
    save_fig(fig, 'S1_배경_규모비중', dir_fig)
    return fig


# ---------------------------------------------------------------- 1-4. 업종별 지수
def plot_industry_index(eda_idx, share, ctx, missing_prod_q, dir_fig, ncol=2):
    """S1_EDA_업종별_생산고용지수 — 각 업종의 분석 시작분기 = 100."""
    qpos = {q: i for i, q in enumerate(ctx.quarters)}
    nrow = int(np.ceil(len(ctx.ind_order_emp) / ncol))
    fig, axes = plt.subplots(nrow, ncol, figsize=(12.6, 2.3 * nrow), sharex=True)
    for k, ind in enumerate(ctx.ind_order_emp):
        ax = axes[k // ncol, k % ncol]
        g = eda_idx[eda_idx.industry == ind].sort_values('quarter_index').reset_index(drop=True)
        xs = [qpos[q] for q in g.quarter]
        ax.axhline(100, color='#999999', lw=0.8, ls=':', zorder=1)
        for q_na in missing_prod_q:                   # 생산액이 없는 분기를 옅은 세로띠로 표시
            ax.axvspan(qpos[q_na] - 0.5, qpos[q_na] + 0.5, color='#EFEFEF', lw=0, zorder=0)
        for col, key, lab in [('production_index_industry', 'production', '명목 생산액 지수'),
                              ('employment_index_industry', 'employment', '고용 지수')]:
            ax.plot(xs, g[col], color=SERIES_COLORS[key], lw=1.8, marker='o', ms=3.0, label=lab, zorder=3)
            last = g[col].dropna()
            if len(last):
                ax.annotate(f'{last.iloc[-1]:.0f}', (xs[last.index[-1]], last.iloc[-1]),
                            xytext=(4, 0), textcoords='offset points', va='center',
                            fontsize=8.2, color=SERIES_COLORS[key], fontweight='bold')
        emp_sh = share.loc[ind, '고용비중']
        sh_txt = f'{emp_sh:.1f}%' if emp_sh >= 0.1 else f'{emp_sh:.2f}%'
        ax.text(0.015, 0.94, f'{ind}  ({ctx.latest} 고용비중 {sh_txt})', transform=ax.transAxes,
                va='top', ha='left', fontsize=10, fontweight='bold')
        ax.set_xlim(-0.6, len(ctx.quarters) + 0.8)
        ax.margins(y=0.22)
        if k % ncol == 0:
            ax.set_ylabel(f'지수({ctx.quarters[0]}=100)', fontsize=8.8)
        style_ax(ax)
    axes[0, 0].set_xticks(range(0, len(ctx.quarters), 2))
    axes[-1, 0].set_xticklabels(ctx.quarters[::2], rotation=90, fontsize=7.4)
    axes[-1, 1].set_xticklabels(ctx.quarters[::2], rotation=90, fontsize=7.4)
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc='lower center', ncol=2, bbox_to_anchor=(0.5, -0.012),
               frameon=False, fontsize=9.5)                # 범례는 그림 전체에 한 번만
    fig.suptitle(f'업종별 명목 생산액·고용 지수 ({ctx.quarters[0]}=100, {ctx.quarters[0]}~{ctx.latest}) — 패널별 y축 범위 다름, '
                 f'회색 띠는 생산액이 없는 분기({", ".join(missing_prod_q)})', fontsize=12, y=0.995)
    fig.tight_layout(rect=[0, 0.018, 1, 0.985])
    save_fig(fig, 'S1_EDA_업종별_생산고용지수', dir_fig)
    return fig


# ---------------------------------------------------------------- 1-5. YoY 범위
def plot_yoy_range(eda_valid, ctx, dir_fig):
    """S1_EDA_YoY분포_범위 — 업종별 생산·고용 YoY의 최소~최대와 중앙값."""
    fig, axs = plt.subplots(1, 2, figsize=(12.6, 4.4))
    order = ctx.ind_order_emp[::-1]
    yy = np.arange(len(order))
    for ax, col, key, lab in [(axs[0], 'production_yoy', 'production', '명목 생산액 YoY'),
                              (axs[1], 'employment_yoy', 'employment', '고용 YoY')]:
        stat = eda_valid.groupby('industry')[col].agg(['min', 'median', 'max']).reindex(order)
        ax.axvline(0, color='black', lw=1.0, zorder=1)
        ax.hlines(yy, stat['min'], stat['max'], color=SERIES_COLORS[key], lw=3.0, alpha=0.45, zorder=2)
        ax.scatter(stat['min'], yy, color=SERIES_COLORS[key], s=26, zorder=3)
        ax.scatter(stat['max'], yy, color=SERIES_COLORS[key], s=26, zorder=3)
        ax.scatter(stat['median'], yy, facecolor='white', edgecolor=SERIES_COLORS[key],
                   linewidth=1.6, s=42, zorder=4, label='중앙값')
        ax.set_yticks(yy)
        ax.set_yticklabels(stat.index, fontsize=9.5)
        ax.set_xlabel(f'{lab} (%, 최소~최대)', fontsize=9.5)
        ax.set_title(f'{lab}의 업종별 범위', fontsize=11)
        ax.legend(loc='upper right', frameon=False, fontsize=8.6)
        style_ax(ax, ygrid=False, xgrid=True)
    fig.suptitle(f'업종별 생산·고용 YoY의 관측 범위 ({ctx.quarters[0]}~{ctx.latest}, 유효 관측 {len(eda_valid)}건) — '
                 f'좌우 패널의 x축 범위는 서로 다름', fontsize=12, y=1.0)
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    save_fig(fig, 'S1_EDA_YoY분포_범위', dir_fig)
    return fig


# ---------------------------------------------------------------- 1-6. 생산–고용 관계
def plot_pair_scatter(eda_pair, zoom, ctx, dir_fig):
    """S1_EDA_전체기간_생산고용관계 — 국면 색·이름을 쓰지 않는 탐색용 산점도."""
    xr, yr, xp, yp, n_out = zoom['xr'], zoom['yr'], zoom['xp'], zoom['yp'], zoom['n_out']
    fig, axs = plt.subplots(1, 2, figsize=(13.0, 5.6))
    for j, ax in enumerate(axs):
        is_zoom = (j == 1)
        past = eda_pair[eda_pair.quarter != ctx.latest]
        lat = eda_pair[eda_pair.quarter == ctx.latest]
        ax.axhline(0, color='black', lw=1.1, zorder=2)
        ax.axvline(0, color='black', lw=1.1, zorder=2)
        ax.scatter(past.production_yoy, past.employment_yoy, s=26, color='#C4C4C4',
                   edgecolor='white', linewidth=0.4, zorder=3,
                   label=f'{ctx.quarters[0]}~{ctx.prev} ({len(past)}건)')
        ax.scatter(lat.production_yoy, lat.employment_yoy, s=74, color='#3A3A3A',
                   edgecolor='white', linewidth=1.0, zorder=4, label=f'{ctx.latest} ({len(lat)}건)')
        if is_zoom:
            ax.set_xlim(xr[0] - xp, xr[1] + xp)
            ax.set_ylim(yr[0] - yp, yr[1] + yp)
            # 최신분기 10개 업종이 좁은 구간에 모여 라벨이 겹치므로 업종명은 붙이지 않는다.
            # 최신분기의 업종별 위치는 Section 2 Q1-A에서 업종명과 함께 본다.
            ax.set_title(f'확대 — 1-5의 극단 관측 {n_out}건을 뺀 범위\n(뺀 관측은 왼쪽 패널에 모두 표시)', fontsize=10.5)
        else:
            ax.set_title(f'전체 범위 — 유효 관측 {len(eda_pair)}건 모두 표시', fontsize=10.5)
            ax.legend(loc='upper right', frameon=False, fontsize=9)
        ax.set_xlabel('명목 생산액 증감률 (YoY, %)', fontsize=10)
        ax.set_ylabel('고용 증감률 (YoY, %)', fontsize=10)
        style_ax(ax, ygrid=False)
    fig.suptitle(f'전체기간 업종×분기의 생산·고용 증감률 ({ctx.quarters[0]}~{ctx.latest}) — '
                 f'두 변화율이 같은 방향인지 탐색', fontsize=12.5, y=1.0)
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    save_fig(fig, 'S1_EDA_전체기간_생산고용관계', dir_fig)
    return fig


# ---------------------------------------------------------------- Q1-A. 최신분기 사분면
def plot_q1_quadrant(q, ctx, dir_fig):
    """Q1A_최신분기_사분면 — 점 크기 = 최신분기 고용 인원."""
    fig, ax = plt.subplots(figsize=(9.2, 6.6))

    xpad = (q.production_yoy.max() - q.production_yoy.min()) * 0.12
    ypad = (q.employment_yoy.max() - q.employment_yoy.min()) * 0.14
    xlim = (q.production_yoy.min() - xpad, q.production_yoy.max() + xpad * 2.2)
    ylim = (q.employment_yoy.min() - ypad, q.employment_yoy.max() + ypad)
    ax.set_xlim(xlim)
    ax.set_ylim(ylim)

    # 사분면 배경 — 아주 옅게. 코너 라벨이 국면 의미를 직접 말한다.
    for (sx, sy), s in [((1, 1), 'S1'), ((1, -1), 'S2'), ((-1, 1), 'S3'), ((-1, -1), 'S4')]:
        x0 = 0 if sx > 0 else xlim[0]
        y0 = 0 if sy > 0 else ylim[0]
        ax.add_patch(Rectangle((x0, y0), (xlim[1] if sx > 0 else 0) - x0,
                               (ylim[1] if sy > 0 else 0) - y0,
                               color=STATE_COLORS[s], alpha=0.055, lw=0, zorder=0))
        ax.text(xlim[1] - (xlim[1] - xlim[0]) * 0.012 if sx > 0 else xlim[0] + (xlim[1] - xlim[0]) * 0.012,
                ylim[1] - (ylim[1] - ylim[0]) * 0.015 if sy > 0 else ylim[0] + (ylim[1] - ylim[0]) * 0.015,
                STATE_LABELS[s], ha='right' if sx > 0 else 'left', va='top' if sy > 0 else 'bottom',
                fontsize=10, color=STATE_COLORS[s], fontweight='bold', zorder=1)

    ax.axhline(0, color='black', lw=1.2, zorder=2)
    ax.axvline(0, color='black', lw=1.2, zorder=2)

    emp_max = q.employment.max()
    sizes = 70 + 620 * np.sqrt(q.employment / emp_max)
    ax.scatter(q.production_yoy, q.employment_yoy, s=sizes,
               color=[STATE_COLORS[s] for s in q.state],
               edgecolor='white', linewidth=1.0, zorder=4)

    radii = (np.sqrt(sizes / np.pi) + 6) * 1.4   # points -> 화면 px 환산
    # 라벨은 업종명만 — 고용 인원은 점 크기와 범례가 이미 전달한다(라벨을 길게 하면 서로 겹친다).
    place_labels(ax, q.production_yoy.values, q.employment_yoy.values, list(q.index),
                 offsets=radii, fontsize=10.2, min_gap_px=15, split_at=0)

    # 점 크기 범례 — 텍스트 설명 대신 실제 원으로 보여준다.
    leg_vals = [5_000, 30_000, 60_000]
    handles = [Line2D([], [], marker='o', ls='', markerfacecolor='#BBBBBB', markeredgecolor='white',
                      markersize=np.sqrt(70 + 620 * np.sqrt(v / emp_max)) * 0.62,
                      label=f'{v:,}명') for v in leg_vals]
    # 사분면 코너 라벨과 겹치지 않도록 좌측 여백(관측치가 없는 영역)에 둔다.
    ax.legend(handles=handles, loc='center left', bbox_to_anchor=(0.015, 0.62),
              frameon=True, framealpha=0.95, edgecolor='#DDDDDD',
              fontsize=8.6, title=f'점 크기 = {ctx.latest} 고용 인원', title_fontsize=8.6,
              labelspacing=1.5, borderpad=0.9, handletextpad=1.4)

    ax.set_xlabel('명목 생산액 증감률 (YoY, %)', fontsize=10.5)
    ax.set_ylabel('고용 증감률 (YoY, %)', fontsize=10.5)
    ax.set_title(f'{ctx.latest} 업종별 생산·고용 증감률과 국면 위치\n'
                 f'(전년동기 {ctx.base_q} 대비, 중립구간 threshold={ctx.threshold})', fontsize=11.5)
    style_ax(ax, ygrid=False)
    plt.tight_layout()
    save_fig(fig, 'Q1A_최신분기_사분면', dir_fig)
    return fig


# ---------------------------------------------------------------- Q1-B. 국면 격자
def plot_state_grid(pivot, comp, ctx, dir_fig):
    """Q1B_국면격자 — 업종×분기 국면 격자와 업종별 국면 구성비."""
    code_map = {s: i for i, s in enumerate(STATES6)}
    code_arr = pivot.apply(lambda col: col.map(code_map)).astype(float).values
    n_ind, n_q = code_arr.shape

    fig = plt.figure(figsize=(14.5, 5.6))
    gs = fig.add_gridspec(1, 2, width_ratios=[5.2, 1], wspace=0.04)
    ax = fig.add_subplot(gs[0])
    axr = fig.add_subplot(gs[1], sharey=ax)

    cmap = ListedColormap([STATE_COLORS[s] for s in STATES6])
    norm = BoundaryNorm(np.arange(-0.5, len(STATES6) + 0.5, 1), cmap.N)
    ax.pcolormesh(code_arr, cmap=cmap, norm=norm, edgecolors='white', linewidth=0.8)

    ax.set_xticks(np.arange(n_q) + 0.5)
    ax.set_xticklabels(ctx.quarters, rotation=90, fontsize=8)
    ax.set_yticks(np.arange(n_ind) + 0.5)
    ax.set_yticklabels(ctx.ind_order_emp, fontsize=10)
    ax.set_ylim(0, n_ind)
    ax.invert_yaxis()

    for ri in range(n_ind):
        for qi in range(n_q):
            label = pivot.iloc[ri, qi]
            if label != 'INVALID':
                ax.text(qi + .5, ri + .5, label, ha='center', va='center', fontsize=6.7, color='#222222')

    for q_inv in ctx.invalid_quarters:
        qi = ctx.quarters.index(q_inv)
        for ri in range(n_ind):
            ax.add_patch(Rectangle((qi, ri), 1, 1, fill=False, hatch='////',
                                   edgecolor='#B8B8B8', linewidth=0))
        ax.text(qi + 0.5, -0.28, 'YoY\n계산불가', ha='center', va='bottom', fontsize=7, color='#888888')

    for i, qq in enumerate(ctx.quarters):
        if qq.endswith('Q1'):
            ax.axvline(i, color='#AAAAAA', lw=0.7, alpha=0.8)
    ax.add_patch(Rectangle((n_q - 1, 0), 1, n_ind, fill=False, edgecolor='black', linewidth=1.8))
    ax.text(n_q - 0.5, -0.28, f'{ctx.latest}\n(최신)', ha='center', va='bottom', fontsize=7.5,
            color='#333333', fontweight='bold')

    # 우측: 업종별 국면 구성비. INVALID는 두 분기 모두 전 업종 공통이라 정보가 없어 제외하고,
    # 유효 분기 기준으로 정규화한다. y좌표는 히트맵 셀 중심(+0.5)에 맞춘다.
    yb = np.arange(n_ind) + 0.5
    left = np.zeros(n_ind)
    for col in STATES5:
        axr.barh(yb, comp[col].values, left=left, color=STATE_COLORS[col], height=0.84)
        left += comp[col].values
    axr.set_xlim(0, 1)
    axr.set_xticks([0, 0.5, 1])
    axr.set_xticklabels(['0%', '50%', '100%'], fontsize=8)
    axr.set_xlabel(f'국면 구성비 (유효 {len(ctx.quarters) - len(ctx.invalid_quarters)}분기 기준)', fontsize=9)
    plt.setp(axr.get_yticklabels(), visible=False)
    axr.tick_params(axis='y', length=0)
    axr.spines['top'].set_visible(False)
    axr.spines['right'].set_visible(False)
    axr.spines['left'].set_visible(False)

    handles = [Rectangle((0, 0), 1, 1, color=STATE_COLORS[k]) for k in STATES6]
    fig.legend(handles, [STATE_LABELS[k] for k in STATES6], loc='lower center', ncol=6,
               bbox_to_anchor=(0.5, -0.10), frameon=False, fontsize=9)
    ax.set_title(f'업종 x 분기 국면 격자 ({ctx.quarters[0]}~{ctx.latest}, 업종은 {ctx.latest} 고용비중 내림차순)',
                 fontsize=11.5, pad=40)
    plt.tight_layout()
    save_fig(fig, 'Q1B_국면격자', dir_fig)
    return fig


# ---------------------------------------------------------------- Q2-A. 고용 증감·비중
def plot_q2_scale(q2, net, ctx, dir_fig):
    """Q2A_고용증감_비중 — 증감 인원 오름차순 공통 정렬."""
    fig, axes = plt.subplots(1, 2, figsize=(13.2, 5.0), sharey=True,
                             gridspec_kw={'width_ratios': [1.45, 1], 'wspace': 0.06})
    y = np.arange(len(q2))

    ax = axes[0]
    ax.barh(y, q2.증감인원, height=0.66,
            color=[DELTA_COLORS['down'] if v < 0 else (DELTA_COLORS['up'] if v > 0 else DELTA_COLORS['neutral'])
                   for v in q2.증감인원])
    ax.axvline(0, color='black', lw=1.0)
    bar_labels(ax, y, q2.증감인원.values, fmt=lambda v: f'{v:+,.0f}', fontsize=9.2)
    ax.set_yticks(y)
    ax.set_yticklabels(q2.index, fontsize=10.5)
    ax.set_xlabel(f'고용 증감 인원 (명, {ctx.latest} vs 전년동기 {ctx.base_q})', fontsize=10.2)
    span = q2.증감인원.max() - q2.증감인원.min()
    ax.set_xlim(q2.증감인원.min() - span * 0.22, max(q2.증감인원.max(), 0) + span * 0.16)
    ax.set_title(f'① 고용 증감 인원 — 제조업 전체 {net:+,.0f}명', fontsize=11, loc='left')
    style_ax(ax, ygrid=False, xgrid=True)

    ax = axes[1]
    ax.barh(y, q2['고용비중%'], height=0.66, color='#9AA5B1')
    bar_labels(ax, y, q2['고용비중%'].values, fmt=lambda v: f'{v:.1f}%', fontsize=9.2)
    ax.set_xlabel(f'제조업 전체 고용 대비 비중 (%, {ctx.latest})', fontsize=10.2)
    ax.set_xlim(0, max(q2['고용비중%'].max() * 1.2, 1))
    ax.set_title('② 고용 비중', fontsize=11, loc='left')
    style_ax(ax, ygrid=False, xgrid=True)

    fig.suptitle(f'{ctx.latest} 업종별 고용 증감 인원과 고용 비중 (같은 업종 순서 — 증감 인원 오름차순)',
                 fontsize=12, y=1.02)
    plt.tight_layout()
    save_fig(fig, 'Q2A_고용증감_비중', dir_fig)
    return fig


# ---------------------------------------------------------------- Q2-B. 분기별 구성
def plot_q2_composition(plot_df, qs, dir_fig):
    """Q2B_분기별_고용변화구성 — 막대는 업종별 증감, 검은 선은 순증감."""
    cols = list(plot_df.columns)
    colors = MAIN_COLORS + [REST_COLOR]

    fig, ax = plt.subplots(figsize=(12.5, 5.0))
    x = np.arange(len(qs))
    pos = np.zeros(len(qs))
    neg = np.zeros(len(qs))
    for col, c in zip(cols, colors):
        v = plot_df[col].fillna(0).values
        vp = np.where(v > 0, v, 0)
        vn = np.where(v < 0, v, 0)
        ax.bar(x, vp, bottom=pos, color=c, width=0.68, label=col, edgecolor='white', linewidth=0.4)
        ax.bar(x, vn, bottom=neg, color=c, width=0.68, edgecolor='white', linewidth=0.4)
        pos += vp
        neg += vn

    netv = plot_df.sum(axis=1).values
    ax.plot(x, netv, color='black', lw=1.6, marker='D', ms=5, zorder=5, label='제조업 전체 순증감')
    for xi, v in zip(x, netv):
        ax.annotate(f'{v:+,.0f}', (xi, v), xytext=(0, 9 if v >= 0 else -16), textcoords='offset points',
                    ha='center', fontsize=7.8, color='black', fontweight='bold')

    ax.axhline(0, color='black', lw=1.0)
    ax.set_xticks(x)
    ax.set_xticklabels(qs, rotation=90, fontsize=8.5)
    ax.set_ylabel('고용 증감 인원 (명, 전년동기 대비)', fontsize=10.2)
    ax.set_title('분기별 제조업 전체 고용 증감의 업종 구성 — 막대는 업종별 증감, 검은 선은 순증감',
                 fontsize=11.5)
    ax.legend(loc='upper left', frameon=False, fontsize=9, ncol=2)
    style_ax(ax)
    plt.tight_layout()
    save_fig(fig, 'Q2B_분기별_고용변화구성', dir_fig)
    return fig


# ---------------------------------------------------------------- Q2-C. 비례배분 기준선
def plot_q2_baseline(q2, main_ind, net, ctx, dir_fig):
    """Q2C_비례기준선_비교 — 상세표시 대상 업종의 실제 증감 vs 비례배분 기준선.

    q2에는 q2_scale.baseline_comparison()이 붙인 비례기대증감·초과증감 컬럼이 있어야 한다.
    """
    if not main_ind:
        return None
    bl = q2.loc[main_ind, ['증감인원', '비례기대증감', '초과증감']]
    fig, ax = plt.subplots(figsize=(10.5, 5.2))
    x = np.arange(len(bl))
    w = 0.36
    ax.bar(x - w / 2, bl.증감인원, w, label='실제 증감',
           color=[DELTA_COLORS['down'] if v < 0 else (DELTA_COLORS['up'] if v > 0 else DELTA_COLORS['neutral'])
                  for v in bl.증감인원])
    ax.bar(x + w / 2, bl.비례기대증감, w, label='비례배분 기준선', color='#C9C9C9')
    lo = min(bl.증감인원.min(), bl.비례기대증감.min(), 0)
    hi = max(bl.증감인원.max(), bl.비례기대증감.max(), 0)
    pad = (hi - lo) * 0.18 or 1.0
    for xi, (ind, row) in zip(x, bl.iterrows()):
        anchor = min(row.증감인원, row.비례기대증감, 0)
        ax.text(xi, anchor - pad * 0.12, f'기준선 대비 {row.초과증감:+,.0f}명', ha='center', va='top',
                fontsize=9.5, fontweight='bold', color='#333333')
    ax.axhline(0, color='black', lw=1.0)
    ax.set_xticks(x)
    ax.set_xticklabels(bl.index, fontsize=10.5)
    ax.set_ylim(lo - pad * 1.3, hi + pad * 0.9)
    ax.set_ylabel(f'고용 증감 인원 (명, {ctx.latest} vs 전년동기 {ctx.base_q})', fontsize=10.2)
    ax.set_title(f'{ctx.latest} 규모를 통제한 비교 — 실제 증감 vs 비례배분 기준선\n'
                 f'(제조업 전체 {net:+,.0f}명을 전년동기 고용비중대로 배분, 상세표시 대상 업종)', fontsize=11.5)
    ax.legend(loc='upper left', frameon=False, fontsize=9)
    style_ax(ax)
    plt.tight_layout()
    save_fig(fig, 'Q2C_비례기준선_비교', dir_fig)
    return fig


# ---------------------------------------------------------------- Q3-A. 주요 업종 경로
def plot_q3_paths(state, ctx, main_ind, dir_fig):
    """Q3A_주요업종_경로 — 생산·고용 YoY 경로 + 국면 리본(연속기간)."""
    sub = state[state.industry.isin(main_ind)]
    ymin = min(sub.production_yoy.min(), sub.employment_yoy.min())
    ymax = max(sub.production_yoy.max(), sub.employment_yoy.max())
    pad = (ymax - ymin) * 0.10
    qi_all = sorted(state.quarter_index.unique())
    qi2x = {qi: i for i, qi in enumerate(qi_all)}

    panel_rows = max(1, int(np.ceil(len(main_ind) / 2)))
    fig = plt.figure(figsize=(13.5, 3.8 * panel_rows))
    gs = fig.add_gridspec(panel_rows * 2, 2, height_ratios=[1, 0.16] * panel_rows, hspace=0.25, wspace=0.10)
    cmap = ListedColormap([STATE_COLORS[s] for s in STATES6])
    norm = BoundaryNorm(np.arange(-0.5, len(STATES6) + 0.5, 1), cmap.N)
    code_map = {s: i for i, s in enumerate(STATES6)}

    for k, ind in enumerate(main_ind):
        r, c = 2 * (k // 2), k % 2
        axl = fig.add_subplot(gs[r, c])
        axb = fig.add_subplot(gs[r + 1, c])

        g = state[state.industry == ind].sort_values('quarter_index')
        xs = [qi2x[v] for v in g.quarter_index]

        axl.axhline(0, color='black', lw=1.0)
        for q_inv in ctx.invalid_quarters:                       # 결측 분기를 옅은 세로띠로 표시
            axl.axvspan(qi2x[g.loc[g.quarter == q_inv, 'quarter_index'].iloc[0]] - 0.5,
                        qi2x[g.loc[g.quarter == q_inv, 'quarter_index'].iloc[0]] + 0.5,
                        color='#EFEFEF', lw=0, zorder=0)
        axl.plot(xs, g.production_yoy, color=SERIES_COLORS['production'], lw=1.9, marker='o', ms=3.6,
                 label='생산 YoY')
        axl.plot(xs, g.employment_yoy, color=SERIES_COLORS['employment'], lw=1.9, marker='o', ms=3.6,
                 label='고용 YoY')
        axl.set_ylim(ymin - pad, ymax + pad)
        axl.set_xlim(-0.6, len(qi_all) - 0.4)
        axl.set_xticks(range(len(qi_all)))
        axl.set_xticklabels([])
        emp_sh = g.loc[g.quarter == ctx.latest, 'employment'].iloc[0] / \
            state.loc[state.quarter == ctx.latest, 'employment'].sum() * 100
        axl.text(0.012, 0.965, f'{ind}  (고용비중 {emp_sh:.1f}%)', transform=axl.transAxes,
                 va='top', fontsize=11, fontweight='bold')
        axl.set_ylabel('YoY (%)', fontsize=9.5)
        style_ax(axl)
        if k == 0:
            axl.legend(loc='lower left', frameon=False, fontsize=8.8, ncol=2)

        arr = np.array([[code_map[s] for s in g.state]], dtype=float)
        axb.pcolormesh(np.arange(len(qi_all) + 1) - 0.5, np.array([0.0, 1.0]), arr,
                       cmap=cmap, norm=norm, edgecolors='white', linewidth=0.7)
        axb.set_xlim(axl.get_xlim())
        axb.set_yticks([])
        axb.set_xticks(np.arange(len(qi_all)))
        # 분기 라벨은 아래쪽 두 패널에만 — 위 패널 리본의 라벨은 아래 패널 제목과 겹친다
        axb.set_xticklabels(g.quarter if k // 2 == panel_rows - 1 else [''] * len(qi_all),
                            rotation=90, fontsize=7.6)
        axb.tick_params(axis='x', length=3 if k // 2 == panel_rows - 1 else 0)
        for sp in axb.spines.values():
            sp.set_visible(False)
        # 연속기간(2분기 이상)를 리본 위에 숫자로 표기 — Q1B 격자가 보여주지 않는 정보
        states_list = g.state.tolist()
        i = 0
        while i < len(states_list):
            s = states_list[i]
            j = i
            while j + 1 < len(states_list) and states_list[j + 1] == s:
                j += 1
            run_len = j - i + 1
            if s in STATES4 and run_len >= 2:
                axb.text((i + j) / 2, 0.5, f'{s}·{run_len}Q', ha='center', va='center',
                         fontsize=7.6, color='#222222', fontweight='bold')
            elif s in STATES4:
                axb.text((i + j) / 2, 0.5, s, ha='center', va='center',
                         fontsize=7.0, color='#222222')
            i = j + 1
        axb.set_ylabel('국면', fontsize=8.5, rotation=0, ha='right', va='center', labelpad=6)

    handles = [Rectangle((0, 0), 1, 1, color=STATE_COLORS[k]) for k in STATES6]
    fig.legend(handles, [STATE_LABELS[k] for k in STATES6], loc='lower center', ncol=6,
               bbox_to_anchor=(0.5, -0.03), frameon=False, fontsize=9)
    fig.suptitle(f'주요 업종의 생산·고용 증감률 경로와 국면 지속 ({len(main_ind)}개 패널 y축 동일: '
                 f'{ymin - pad:.0f}~{ymax + pad:.0f}%)', fontsize=12, y=0.965)
    save_fig(fig, 'Q3A_주요업종_경로', dir_fig)
    return fig


# ---------------------------------------------------------------- Q3-B. 현재 국면 지속
def plot_current_runs(cur, ctx, main_ind, dir_fig):
    """Q3B_현재국면_지속 — ◁ 는 좌측 절단(run이 관측 블록 시작과 함께 시작)."""
    fig, ax = plt.subplots(figsize=(9.6, 5.0))
    y = np.arange(len(cur))
    bar_len = cur.run_length.fillna(0)
    ax.barh(y, bar_len, color=[STATE_COLORS.get(s, '#BDBDBD') for s in cur.state], height=0.64)
    ax.set_yticks(y)
    ax.set_yticklabels([f'{i} ★' if i in main_ind else i for i in cur.index], fontsize=10.5)
    ax.invert_yaxis()
    ax.set_xlabel(f'현재 국면이 연속된 분기 수 ({ctx.latest} 기준)', fontsize=10.2)
    ax.set_xlim(0, bar_len.max() + 3.0)
    ax.set_xticks(range(0, int(bar_len.max()) + 2))

    for yi, (ind, row) in zip(y, cur.iterrows()):
        if row.state == 'N':
            label = 'N · 한 지표 이상 0% · 지속집계 제외'
        elif row.state == 'INVALID':
            label = '계산 불가 · 지속집계 제외'
        else:
            label = f'{row.state} · {int(row.run_length)}분기째'
        ax.text(bar_len[ind] + 0.14, yi, label, va='center', fontsize=9.3, color='#333333')
        if pd.notna(row.run_left_censored) and bool(row.run_left_censored):
            ax.text(-0.22, yi, '◁', va='center', ha='right', fontsize=11, color='#555555')

    ax.set_title(f'업종별 현재 국면 지속기간 ({ctx.latest} 기준, ★ = Q2에서 선별한 주요 업종)', fontsize=11.5)
    style_ax(ax, ygrid=False, xgrid=True)
    plt.tight_layout()
    save_fig(fig, 'Q3B_현재국면_지속', dir_fig)
    return fig


# ---------------------------------------------------------------- Q3-C. 최장 지속
def plot_longest_runs(longest, dir_fig, max_observable_run=None):
    """Q3C_업종별_최장지속 — 지속분기 → 시작분기 오름차순.

    max_observable_run을 주면 제목에 연속 판정 가능한 최장 구간(관측 한계)을 함께 적는다.
    """
    long_plot = longest.sort_values(['지속분기', '시작분기'])
    fig, ax = plt.subplots(figsize=(9.4, 5.0))
    y = np.arange(len(long_plot))
    ax.barh(y, long_plot.지속분기, height=0.64,
            color=[STATE_COLORS[s] for s in long_plot.국면])
    ax.set_yticks(y)
    ax.set_yticklabels(long_plot.index, fontsize=10.5)
    ax.set_xlabel('최장 관측 지속기간 (분기)', fontsize=10.2)
    ax.set_xlim(0, long_plot.지속분기.max() + 2.4)
    for yi, (ind, row) in zip(y, long_plot.iterrows()):
        censor = ' · 경계절단' if bool(row.좌절단) or bool(row.우절단) else ''
        ax.text(row.지속분기 + 0.12, yi,
                f'{row.국면} · {int(row.지속분기)}Q · {row.시작분기}{censor}',
                va='center', fontsize=8.9, color='#333333')
    title = '업종별 최장 관측 국면 지속기간'
    if max_observable_run is not None:
        title += f' (연속 판정 가능한 최장 구간 {max_observable_run}분기)'
    ax.set_title(title, fontsize=11.5)
    style_ax(ax, ygrid=False, xgrid=True)
    plt.tight_layout()
    save_fig(fig, 'Q3C_업종별_최장지속', dir_fig)
    return fig


# ---------------------------------------------------------------- Q3-C. 전환행렬
def plot_transition(mat, mat_pct, row_n, trans, ctx, dir_fig, min_row_n=config.TRANSITION_MIN_ROW_N):
    """Q3C_전환행렬 — 행 기준 비율, 대각선 = 같은 국면 유지.

    행 관측이 min_row_n보다 적으면 1건이 비율을 크게 움직이므로 그 행은 비율 대신 건수만 표시한다.
    """
    low_rows = [s for s in STATES5 if row_n[s] < min_row_n]
    fig, ax = plt.subplots(figsize=(6.6, 5.9))
    shown = mat_pct.astype(float).copy()
    shown.loc[low_rows] = np.nan
    cmap = plt.get_cmap('Blues').copy()
    cmap.set_bad('#F2F2F2')
    im = ax.imshow(np.ma.masked_invalid(shown.values), cmap=cmap, vmin=0, vmax=100)
    ax.set_xticks(range(5))
    ax.set_xticklabels(STATES5, fontsize=10.5)
    ax.set_yticks(range(5))
    ax.set_yticklabels([f'{s} (n={row_n[s]}){" *" if s in low_rows else ""}' for s in STATES5],
                       fontsize=10.5)
    ax.set_xlabel('t+1 분기 국면', fontsize=10.5)
    ax.set_ylabel('t 분기 국면', fontsize=10.5)
    for i in range(5):
        for j in range(5):
            pct, cnt = mat_pct.values[i, j], mat.values[i, j]
            if STATES5[i] in low_rows:
                ax.text(j, i, f'{cnt}건', ha='center', va='center', fontsize=9, color='#222222')
            else:
                ax.text(j, i, f'{pct:.0f}%\n({cnt}건)', ha='center', va='center', fontsize=9,
                        color='white' if pct > 55 else '#222222')
        ax.add_patch(Rectangle((i - 0.5, i - 0.5), 1, 1, fill=False, edgecolor='black', linewidth=2))
    cbar = plt.colorbar(im, ax=ax, fraction=0.046)
    cbar.set_label('행 기준 비율 (%)', fontsize=9)
    ax.set_title(f'관측된 국면 전환 빈도 ({ctx.quarters[0]}~{ctx.latest}, 전환 {len(trans)}건)\n'
                 '대각선 = 같은 국면 유지', fontsize=11.5)
    fig.text(0.5, -0.02,
             '과거 인접 관측의 비율이다. 미래 전환확률이 아니며 행별 관측 수를 함께 읽는다.'
             + (f'\n* 관측 {min_row_n}건 미만 행은 1건이 비율을 {100 / min_row_n:.0f}%p 이상 움직여 비율 대신 건수만 표시한다.'
                if low_rows else ''),
             ha='center', fontsize=8.8, color='#555555')
    plt.tight_layout()
    save_fig(fig, 'Q3C_전환행렬', dir_fig)
    return fig


# ---------------------------------------------------------------- Section 5. 가동률·업체수
def plot_op_rate(op, op_qs, main_ind, dir_fig):
    """S5_보조_가동률추이 — 입력에 값이 있는 기간만."""
    fig, ax = plt.subplots(figsize=(10.2, 4.4))
    x = np.arange(len(op_qs))
    for ind, c in zip(main_ind, MAIN_COLORS):
        g = op[op.industry == ind].set_index('quarter').reindex(op_qs)
        ax.plot(x, g.op_rate_official, color=c, lw=2.0, marker='o', ms=4.2, label=ind)
        ax.annotate(f'{g.op_rate_official.iloc[-1]:.1f}', (x[-1], g.op_rate_official.iloc[-1]),
                    xytext=(7, 0), textcoords='offset points', va='center', fontsize=9,
                    color=c, fontweight='bold')
    ax.set_xticks(x)
    ax.set_xticklabels(op_qs, rotation=90, fontsize=8.5)
    ax.set_xlim(-0.4, len(op_qs) + 0.9)
    ax.set_ylabel('가동률 (%)', fontsize=10.2)
    lo, hi = ax.get_ylim()
    ax.set_ylim(lo - (hi - lo) * 0.16, hi)     # 좌하단 범례가 선을 가리지 않도록 여백
    ax.set_title(f'주요 업종 가동률 추이 ({op_qs[0]}~{op_qs[-1]}, 입력에 값이 있는 기간)', fontsize=11.5)
    ax.legend(loc='lower left', frameon=False, fontsize=9, ncol=4)
    style_ax(ax)
    plt.tight_layout()
    save_fig(fig, 'S5_보조_가동률추이', dir_fig)
    return fig


def plot_firm_decomposition(margin, parts, ctx, dir_fig):
    """S5_보조_고용업체수_산술분해 — E = F x (E/F)의 산술 분해."""
    fig, ax = plt.subplots(figsize=(9.4, 4.2))
    y = np.arange(len(parts))
    left_pos = np.zeros(len(parts))
    left_neg = np.zeros(len(parts))
    part_colors = [SERIES_COLORS['production'], SERIES_COLORS['employment'], '#9AA5B1']
    for col, color in zip(parts.columns, part_colors):
        values = parts[col].values
        pos = np.where(values > 0, values, 0)
        neg = np.where(values < 0, values, 0)
        ax.barh(y, pos, left=left_pos, color=color, height=0.62, label=col)
        ax.barh(y, neg, left=left_neg, color=color, height=0.62)
        left_pos += pos
        left_neg += neg
    ax.scatter(margin.고용증감, y, color='black', marker='D', s=36, zorder=4, label='고용 증감')
    ax.axvline(0, color='black', lw=1)
    ax.set_yticks(y)
    ax.set_yticklabels(parts.index, fontsize=10.5)
    ax.set_xlabel(f'고용 증감의 산술 분해 (명, {ctx.latest} vs {ctx.base_q})')
    ax.set_title('주요 업종의 고용·가동업체수 산술 분해')
    ax.legend(frameon=False, ncol=2, fontsize=8.8)
    style_ax(ax, ygrid=False, xgrid=True)
    plt.tight_layout()
    save_fig(fig, 'S5_보조_고용업체수_산술분해', dir_fig)
    return fig


# ---------------------------------------------------------------- Section 6. PPI · EIS
def plot_ppi_status(arr, ind_ppi, ctx, ppi_results, dir_fig):
    """V1_PPI_후보별_방향비교 — 후보에 따라 해석이 달라지는 위치를 보여준다."""
    fig, ax = plt.subplots(figsize=(12.5, 5.5))
    ax.pcolormesh(arr, cmap=ListedColormap(config.PPI_COLORS),
                  norm=BoundaryNorm(np.arange(-.5, 5.5), 5), edgecolors='white', linewidth=.8)
    for ri in range(len(ind_ppi)):
        for qi in range(len(ctx.quarters)):
            value = arr[ri, qi]
            label = {0: '·', 1: '반전', 2: '상이', 3: '0%', 4: '—'}[value]
            ax.text(qi + .5, ri + .5, label, ha='center', va='center', fontsize=7.5,
                    color='white' if value == 1 else '#333333')
    ax.set_xticks(np.arange(len(ctx.quarters)) + .5, ctx.quarters, rotation=90, fontsize=8.5)
    ax.set_yticks(np.arange(len(ind_ppi)) + .5, ind_ppi, fontsize=10)
    ax.invert_yaxis()
    ax.set_title(f'선택한 PPI 후보에 따른 생산 방향 비교 | {ppi_results["n_comparable"]}건 중 '
                 f'전체 후보 반전 {ppi_results["n_opposite"]}건', loc='left', pad=18)
    fig.legend([Rectangle((0, 0), 1, 1, color=x) for x in config.PPI_COLORS], config.PPI_STATUS,
               loc='lower center', ncol=3, frameon=False, bbox_to_anchor=(.5, -.06), fontsize=9)
    plt.tight_layout()
    save_fig(fig, 'V1_PPI_후보별_방향비교', dir_fig)
    return fig


def plot_eis(merged, dir_fig):
    """V2_EIS_YoY비교 — 모집단이 다른 두 고용 지표의 증감 방향."""
    fig, ax = plt.subplots(figsize=(9.6, 4.1))
    x = np.arange(len(merged))
    ax.plot(x, merged.kicox_mfg_yoy, color=SERIES_COLORS['employment'], lw=2.1, marker='o', ms=4,
            label='KICOX 산단 제조업 고용 YoY (10개 업종 합)')
    ax.plot(x, merged.eis_manufacturing_yoy_pct, color='#8E8E8E', lw=2.1, marker='s', ms=4,
            label='EIS 창원시 제조업 피보험자 YoY')
    ax.axhline(0, color='black', lw=0.9)
    ax.set_xticks(x)
    ax.set_xticklabels(merged.quarter, rotation=90, fontsize=8.5)
    ax.set_ylabel('YoY (%)', fontsize=10.2)
    lo, hi = ax.get_ylim()
    ax.set_ylim(lo - (hi - lo) * 0.18, hi)     # 좌하단 범례가 선을 가리지 않도록 여백
    ax.set_title('모집단이 다른 두 고용 지표의 증감 방향 비교 (수준값은 비교하지 않는다)', fontsize=11)
    ax.legend(loc='lower left', frameon=False, fontsize=9)
    style_ax(ax)
    plt.tight_layout()
    save_fig(fig, 'V2_EIS_YoY비교', dir_fig)
    return fig
