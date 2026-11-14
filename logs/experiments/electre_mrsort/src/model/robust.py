# -*- coding: utf-8 -*-
"""유한 파라미터 표본에서의 공통/관측 배정과 등급수용지수(CAI).

여기서 표집하는 (w, lambda, p, q)는 사전등록(config/model_revalidation_prereg.yaml)의
parameter_space에서만 읽는다. 결과를 보고 이 공간을 조정하지 않는다. veto는 이
모듈의 함수들이 받을 수는 있지만, Phase 2 진단 자체는 veto=None(사전등록 REGISTERED
이전)으로 실행한다 — 호출자(run_model_revalidation.py)의 책임이다.
"""
import numpy as np
import pandas as pd

from . import config, electre

STAGE_CODE = {'OBSERVE': 0, 'CHECK': 1, 'PRIORITY': 2, config.UNDETERMINED: -1}
STAGE_NAME = {v: k for k, v in STAGE_CODE.items()}
_MAX_REJECTION_ATTEMPTS = 200_000


def sample_parameter_space(prereg_doc, rng):
    """사전등록 parameter_space에서 (weights, lambda, p, q) n_samples개를 표집한다.

    w ~ Dirichlet(1,1,1,1)에서 각 w_j가 [min,max] 안에 들 때까지 기각 재추출.
    lambda ~ U(min,max). p_j ~ U(0, p_upper_j). q_j ~ U(0, p_j/2)(항상 q_j <= p_j/2 <= p_j
    이므로 0<=q<=p pseudo-criterion 제약을 자동으로 만족한다).
    seed는 이 함수가 스스로 정하지 않는다 — 호출자가 prereg_doc['parameter_space']['seed']로
    만든 rng를 넘긴다.
    반환: [{'weights': {...}, 'lambda': float, 'p': {...}, 'q': {...}}, ...] 길이 n_samples.
    """
    ps = prereg_doc['parameter_space']
    crit = config.CRITERIA
    lam_min, lam_max = float(ps['lambda']['min']), float(ps['lambda']['max'])
    w_min, w_max = float(ps['weights']['min']), float(ps['weights']['max'])
    p_upper = ps['p_upper']
    n_samples = int(ps['n_samples'])

    samples = []
    for _ in range(n_samples):
        for attempt in range(_MAX_REJECTION_ATTEMPTS):
            w = rng.dirichlet(np.ones(len(crit)))
            if np.all(w >= w_min) and np.all(w <= w_max):
                break
        else:
            raise RuntimeError(
                f'{_MAX_REJECTION_ATTEMPTS}회 시도해도 [{w_min},{w_max}] 안의 가중치를 뽑지 못했습니다.')
        lam = float(rng.uniform(lam_min, lam_max))
        p = {j: float(rng.uniform(0.0, float(p_upper[j]))) for j in crit}
        q = {j: float(rng.uniform(0.0, p[j] / 2.0)) for j in crit}
        samples.append({'weights': dict(zip(crit, map(float, w))), 'lambda': lam, 'p': p, 'q': q})
    return samples


def assignment_matrix(values, scenario_profiles, samples, gate=True, veto=None):
    """(n_samples, n_rows) 판정단계 행렬. 비관적 배정(공식 모형의 할당 절차)을 쓴다.

    scenario_profiles : {'b1': {...}, 'b2': {...}} — 표집하지 않는 경계 프로파일(고정).
    gate : require_employment_evidence.
    저장은 int8 코드(0=OBSERVE,1=CHECK,2=PRIORITY,-1=UNDETERMINED)로 한다(메모리 절약).
    """
    crit = config.CRITERIA
    n_rows = len(values)
    scorable = values[list(crit)].notna().all(axis=1).to_numpy()
    matrix = np.full((len(samples), n_rows), -1, dtype=np.int8)
    if veto is None and samples:
        # Same inequalities as forward_outranks, batched to bound memory use.
        # Independent audit compared every cell with the original implementation.
        x = values[list(crit)].to_numpy(dtype=float)
        for start in range(0, len(samples), 1000):
            batch = samples[start:start + 1000]
            w = np.array([[s['weights'][j] for j in crit] for s in batch])
            q = np.array([[s['q'][j] for j in crit] for s in batch])
            p = np.array([[s['p'][j] for j in crit] for s in batch])
            if np.any(q < 0) or np.any(p < q):
                raise ValueError('0 <= q <= p 조건을 충족해야 합니다.')
            lam = np.array([s['lambda'] for s in batch])
            stage = np.zeros((len(batch), n_rows), dtype=np.int8)
            for rank, boundary in enumerate(('b1', 'b2'), 1):
                b = np.array([scenario_profiles[boundary][j] for j in crit])
                den = p - q
                c = np.clip((x[None] - (b-p)[:, None]) / np.where(den == 0, 1, den)[:, None], 0, 1)
                c = np.where((den == 0)[:, None], x[None] >= (b-q)[:, None], c)
                c = np.nan_to_num(c)
                passed = (c * w[:, None]).sum(axis=2) >= lam[:, None] - electre.EPS
                if gate:
                    passed &= (c[:, :, [0, 1, 3]] > 0).any(axis=2)
                stage[passed & scorable[None]] = rank
            stage[:, ~scorable] = -1
            matrix[start:start + len(batch)] = stage
        return matrix
    for i, s in enumerate(samples):
        scenario = electre.Scenario(scenario_id=f'sample_{i}', weights=s['weights'],
                                    b1=scenario_profiles['b1'], b2=scenario_profiles['b2'],
                                    lam=s['lambda'], delta_emp=0.0, require_employment_evidence=gate)
        b1 = electre.forward_outranks(values, scenario, 'b1', s['q'], s['p'], veto)
        b2 = electre.forward_outranks(values, scenario, 'b2', s['q'], s['p'], veto)
        stage = electre.pessimistic_assignment(b1, b2, scorable)
        matrix[i, :] = np.fromiter((STAGE_CODE[c] for c in stage), dtype=np.int8, count=n_rows)
    return matrix


def robust_assignment(matrix, row_keys, discriminating_mask):
    """행별 표본 내 공통/관측 배정 표. legacy 열 이름은 호환성을 위해 보존한다.

    행마다 표집된 모든 샘플에서 나온 단계 집합을 본다. 그 집합이 단일 원소이면
    표본 공통 배정(necessary_stage)이 있는 것이고, 둘 이상이면 없다(NA).
    연속 허용공간 전체의 필연성/불가능성을 증명하지 않는다.
    UNDETERMINED는 완전관측 여부로만 정해지므로(파라미터와 무관) 스코어 가능한 행에서는
    절대 섞이지 않는다.
    """
    n_rows = matrix.shape[1]
    discriminating_mask = np.asarray(discriminating_mask, dtype=bool)
    rows = []
    for j in range(n_rows):
        codes = sorted(set(matrix[:, j].tolist()))
        necessary = STAGE_NAME[codes[0]] if len(codes) == 1 else None
        rows.append({
            'industry': row_keys['industry'].iat[j], 'quarter': row_keys['quarter'].iat[j],
            'necessary_stage': necessary,
            'possible_stages': '|'.join(STAGE_NAME[c] for c in codes),
            'n_possible': len(codes),
            'is_necessary': necessary is not None,
            'is_discriminating': bool(discriminating_mask[j]),
            'assignment_scope': 'finite_parameter_sample',
        })
    return pd.DataFrame(rows)


def class_acceptability(matrix, row_keys):
    """행별 등급수용지수(CAI): 각 단계가 표집에서 선택된 비율. 행 합은 정확히 1이다."""
    n_samples, n_rows = matrix.shape
    rows = []
    for j in range(n_rows):
        col = matrix[:, j]
        cai = {code: float(np.sum(col == code)) / n_samples for code in (0, 1, 2, -1)}
        rows.append({'industry': row_keys['industry'].iat[j], 'quarter': row_keys['quarter'].iat[j],
                     'cai_observe': cai[0], 'cai_check': cai[1], 'cai_priority': cai[2],
                     'cai_undetermined': cai[-1]})
    return pd.DataFrame(rows)
