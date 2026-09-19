# -*- coding: utf-8 -*-
"""scipy 없이 평균순위 기반 Spearman과 군집(업종) 단위 재표집 진단.

이 모듈은 통계 유틸리티만 제공한다. ELECTRE 판정 로직은 electre.py에,
교란 재계산은 perturb.py에 둔다.
"""
import numpy as np
import pandas as pd


def _ranks(x):
    return pd.Series(x).rank(method='average').to_numpy(dtype=float)


def spearman(x, y):
    """평균순위 기반 Spearman(scipy 미사용).

    유효쌍(둘 다 결측이 아닌 쌍)이 3개 미만이면 nan. x 또는 y의 유효값 분산이
    0이면(전부 같은 값) 상관을 정의할 수 없으므로 nan.
    """
    x = pd.to_numeric(pd.Series(x), errors='coerce').to_numpy(dtype=float)
    y = pd.to_numeric(pd.Series(y), errors='coerce').to_numpy(dtype=float)
    valid = ~np.isnan(x) & ~np.isnan(y)
    if valid.sum() < 3:
        return np.nan
    xv, yv = x[valid], y[valid]
    if np.std(xv) == 0 or np.std(yv) == 0:
        return np.nan
    rx, ry = _ranks(xv), _ranks(yv)
    rx, ry = rx - rx.mean(), ry - ry.mean()
    denom = np.sqrt(np.sum(rx ** 2) * np.sum(ry ** 2))
    if denom == 0:
        return np.nan
    return float(np.sum(rx * ry) / denom)


def cluster_bootstrap_diff(stage_a, stage_b, outcome, groups, mask, n=4000, seed=None):
    """군집(업종) 단위 복원추출로 spearman(stage_b, outcome) - spearman(stage_a, outcome)의
    표집분포를 만든다. 같은 표본(같은 업종 추출)에서 두 모형을 쌍대로 계산한다(paired).

    stage_a, stage_b : 수치화된 단계(예: RANK 매핑 값). 문자열 라벨은 호출자가 변환한다.
    outcome : 수치형 타깃.
    groups : 군집 단위(업종) 식별자, stage_a/stage_b/outcome과 같은 길이.
    mask : 이 진단에 포함할 행(bool 배열).
    반환: {point_a, point_b, point_diff(=point_b-point_a), ci_lo, ci_hi, p_diff_gt_0, n_effective}
    """
    stage_a = np.asarray(pd.to_numeric(pd.Series(stage_a), errors='coerce'), dtype=float)
    stage_b = np.asarray(pd.to_numeric(pd.Series(stage_b), errors='coerce'), dtype=float)
    outcome = np.asarray(pd.to_numeric(pd.Series(outcome), errors='coerce'), dtype=float)
    groups = np.asarray(groups)
    mask = np.asarray(mask, dtype=bool)

    idx = np.nonzero(mask)[0]
    a, b, y, g = stage_a[idx], stage_b[idx], outcome[idx], groups[idx]
    point_a, point_b = spearman(a, y), spearman(b, y)
    point_diff = (point_b - point_a) if not (np.isnan(point_a) or np.isnan(point_b)) else np.nan

    unique_groups = np.unique(g)
    group_indices = {grp: np.nonzero(g == grp)[0] for grp in unique_groups}
    rng = np.random.default_rng(seed)
    diffs = np.full(int(n), np.nan)
    n_effective = 0
    for i in range(int(n)):
        chosen = rng.choice(unique_groups, size=len(unique_groups), replace=True)
        sel = np.concatenate([group_indices[c] for c in chosen])
        da, db = spearman(a[sel], y[sel]), spearman(b[sel], y[sel])
        if np.isnan(da) or np.isnan(db):
            continue
        diffs[n_effective] = db - da
        n_effective += 1
    diffs = diffs[:n_effective]

    if n_effective == 0:
        ci_lo = ci_hi = p_gt0 = np.nan
    else:
        ci_lo, ci_hi = (float(v) for v in np.percentile(diffs, [2.5, 97.5]))
        p_gt0 = float(np.mean(diffs > 0))
    return {'point_a': point_a, 'point_b': point_b, 'point_diff': point_diff,
            'ci_lo': ci_lo, 'ci_hi': ci_hi, 'p_diff_gt_0': p_gt0, 'n_effective': int(n_effective)}


def blocked_leave_one_out(stage_a, stage_b, outcome, groups, mask):
    """군집(업종) 하나씩 제외한 모든 경우의 spearman을 DataFrame으로 돌려준다.

    최선값을 고르지 않는다 — 제외 가능한 군집 수만큼 행을 전부 반환한다.
    """
    stage_a = np.asarray(pd.to_numeric(pd.Series(stage_a), errors='coerce'), dtype=float)
    stage_b = np.asarray(pd.to_numeric(pd.Series(stage_b), errors='coerce'), dtype=float)
    outcome = np.asarray(pd.to_numeric(pd.Series(outcome), errors='coerce'), dtype=float)
    groups = np.asarray(groups)
    mask = np.asarray(mask, dtype=bool)

    rows = []
    for excluded in sorted(set(groups[mask].tolist())):
        sub = mask & (groups != excluded)
        sp_a, sp_b = spearman(stage_a[sub], outcome[sub]), spearman(stage_b[sub], outcome[sub])
        diff = (sp_b - sp_a) if not (np.isnan(sp_a) or np.isnan(sp_b)) else np.nan
        rows.append({'excluded_group': excluded, 'point_a': sp_a, 'point_b': sp_b,
                     'point_diff': diff, 'n_rows': int(sub.sum())})
    return pd.DataFrame(rows)
