# -*- coding: utf-8 -*-
"""자료 실측 개정폭(vintage)으로 입력을 교란해 파라미터 유지율을 측정한다.

기존 "p ±10% 유지율" 진단은 임계값(파라미터) 교란이었고 자료 교란이 아니었다.
이 모듈은 자료 자체(employment·production 원계열)를 실측 수정율 분포에서 복원추출한
승수로 교란한 뒤 g1~g4를 재계산해, 판정이 자료 개정에 얼마나 민감한지를 측정한다.
"""
import numpy as np
import pandas as pd

from . import config, electre, qp_calibration

PERTURBED_COLUMNS = ('employment', 'employment_lag4', 'production', 'production_lag4')


def revision_pool(path):
    """vintage_수정폭_실측.csv에서 변수별(employment·production) 수정율(비율) 배열.

    반환: {'employment': ndarray, 'production': ndarray}. 값은 수정율pct/100(비율)이며
    NaN은 제외한다.
    """
    df = pd.read_csv(path, encoding='utf-8-sig')
    df.columns = [str(c).lstrip('﻿') for c in df.columns]
    pool = {}
    for var in ('employment', 'production'):
        vals = df.loc[df['변수'] == var, '수정율pct'].astype(float).to_numpy() / 100.0
        pool[var] = vals[~np.isnan(vals)]
    return pool


def _recompute_g4_delta00(original_panel, perturbed_yoy):
    """업종별 g4_delta00(전년동기 대비 고용 하회 연속분기, delta=0) 재계산.

    시드값 = 그 업종의 원 패널 2022Q1 g4_delta00 - 1(음수면 0). 이 값을 첫 분기로
    들어가는 누적 카운터의 초깃값으로 삼아, employment_yoy < 0이면 +1로 이어 붙이고
    employment_yoy >= 0이면 0으로 리셋한다. employment_yoy가 NaN이면 그 분기의 g4는
    NaN이고 카운터는 0으로 리셋한다(다음 분기는 새로 센다).

    이 패널은 업종별로 결측 분기 없는 균등 패널(2022Q1~2026Q2)이므로 derive.py의
    실제-직전분기 인접성 판정은 필요 없다 — quarter_index 오름차순이 곧 실제 인접이다.
    """
    out = np.full(len(original_panel), np.nan)
    quarter_index = original_panel['quarter_index'].to_numpy()
    quarters = original_panel['quarter'].astype(str).to_numpy()
    orig_g4 = original_panel['g4_delta00'].to_numpy(dtype=float)
    for _, positions in original_panel.groupby('industry', sort=False).indices.items():
        order = np.asarray(positions)[np.argsort(quarter_index[positions])]
        seed_rows = order[quarters[order] == '2022Q1']
        if len(seed_rows) and not np.isnan(orig_g4[seed_rows[0]]):
            prev = max(0.0, float(orig_g4[seed_rows[0]]) - 1.0)
        else:
            prev = 0.0
        for pos in order:
            y = perturbed_yoy[pos]
            if np.isnan(y):
                out[pos] = np.nan
                prev = 0.0
            elif y < 0:
                prev = prev + 1.0
                out[pos] = prev
            else:
                prev = 0.0
                out[pos] = 0.0
    return out


def perturb_once(panel, pool, rng):
    """employment·employment_lag4·production·production_lag4에 독립 복원추출 승수
    (1+r)를 곱하고 g1~g4를 재계산한 DataFrame(panel과 같은 행순서·인덱스)을 돌려준다.
    """
    out = panel.copy()
    for column in PERTURBED_COLUMNS:
        var = 'employment' if column.startswith('employment') else 'production'
        r = rng.choice(pool[var], size=len(out), replace=True)
        out[column] = out[column].astype(float) * (1.0 + r)

    lag4_positive = out['production_lag4'].gt(0)
    out['production_yoy'] = ((out['production'] / out['production_lag4'] - 1.0) * 100.0).where(
        lag4_positive & out['production'].notna())
    emp_lag4_positive = out['employment_lag4'].gt(0)
    out['employment_yoy'] = ((out['employment'] / out['employment_lag4'] - 1.0) * 100.0).where(
        emp_lag4_positive & out['employment'].notna())

    out[config.CRITERION_COLUMNS['g1']] = np.maximum(0.0, out['employment_lag4'] - out['employment'])
    out[config.CRITERION_COLUMNS['g2']] = np.maximum(0.0, -out['employment_yoy'])
    out[config.CRITERION_COLUMNS['g3']] = np.maximum(0.0, -out['production_yoy'])
    out['g4_delta00'] = _recompute_g4_delta00(panel, out['employment_yoy'].to_numpy(dtype=float))
    return out


def _boundary_veto(veto, boundary):
    """veto 규약: None(어느 경계에도 veto 없음, Phase 2가 쓰는 형태) 또는
    {'b1': {...}|None, 'b2': {...}|None}(Phase 4가 쓰는 경계별 형태).
    평범한 {criterion: threshold} dict(경계 키가 없는 flat dict)가 오면 두 경계에
    동일하게 적용한다 — 기존 호출부(항상 veto=None)와 완전히 호환된다.
    """
    if veto is None:
        return None
    if 'b1' in veto or 'b2' in veto:
        return veto.get(boundary)
    return veto


def _pessimistic_stage(values, scenario, q, p, veto):
    scorable = values[list(config.CRITERIA)].notna().all(axis=1).to_numpy()
    b1 = electre.forward_outranks(values, scenario, 'b1', q, p, _boundary_veto(veto, 'b1'))
    b2 = electre.forward_outranks(values, scenario, 'b2', q, p, _boundary_veto(veto, 'b2'))
    return electre.pessimistic_assignment(b1, b2, scorable)


def stability(panel, scenario, q, p, veto, pool, n=400, seed=99):
    """교란 재표집에서 판정단계 유지율 분포.

    분모는 두 단계(교란 전·후) 모두 UNDETERMINED가 아닌 행만 포함한다(결측 여부는
    자료 교란과 무관하게 원래부터 정해져 있으므로 이 필터는 거의 항상 전체 완전관측
    행과 같다).
    반환: {'mean','p05','min','replicates': ndarray(길이 n, 실패 시 nan)}
    """
    base_values = qp_calibration.values_from_panel(panel)
    base_stage = _pessimistic_stage(base_values, scenario, q, p, veto)
    rng = np.random.default_rng(seed)
    retentions = np.full(int(n), np.nan)
    for i in range(int(n)):
        perturbed = perturb_once(panel, pool, rng)
        p_values = qp_calibration.values_from_panel(perturbed)
        p_stage = _pessimistic_stage(p_values, scenario, q, p, veto)
        denom_mask = (base_stage != config.UNDETERMINED) & (p_stage != config.UNDETERMINED)
        denom = int(denom_mask.sum())
        if denom == 0:
            continue
        retentions[i] = float(np.mean(base_stage[denom_mask] == p_stage[denom_mask]))
    valid = retentions[~np.isnan(retentions)]
    return {'mean': float(np.mean(valid)) if len(valid) else np.nan,
            'p05': float(np.percentile(valid, 5)) if len(valid) else np.nan,
            'min': float(np.min(valid)) if len(valid) else np.nan,
            'replicates': retentions}


def self_check_zero_perturbation(panel, scenario, q, p, veto, n=3, seed=1):
    """필수 자가검증: 승수를 전부 1.0으로 두는(pool 전부 0) 무교란 실행에서 유지율이
    정확히 1.0이 아니면 RuntimeError. perturb_once의 재계산이 원 자료를 정확히
    재현하는지 확인하는 구조적 점검이다(교란 크기와 무관).
    """
    zero_pool = {'employment': np.array([0.0]), 'production': np.array([0.0])}
    result = stability(panel, scenario, q, p, veto, zero_pool, n=n, seed=seed)
    if result['mean'] != 1.0 or result['min'] != 1.0 or np.isnan(result['mean']):
        raise RuntimeError(
            f'무교란(pool=0) 자가검증 실패: 유지율이 1.0이 아닙니다 (mean={result["mean"]!r}, min={result["min"]!r}). '
            'perturb_once의 g1~g4 재계산이 원 자료를 정확히 재현하지 못합니다.')
    return result
