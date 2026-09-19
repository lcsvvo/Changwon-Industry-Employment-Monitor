# -*- coding: utf-8 -*-
"""최종 판단모형 선발(model selection)용 후보모형 구현.

이 모듈은 outputs/independent_audit 의 결과를 지우거나 대체하지 않는다.
동일한 입력 g(비교 가능한 과거 이력으로 재계산한 g4 포함)를 공통 입력으로 받아
서로 다른 선호모형을 같은 조건에서 비교하기 위한 계산만 제공한다.

공통 전제
- 판단 대상은 순서형 3계급 sorting이다: OBSERVE < CHECK < PRIORITY.
- 어떤 함수도 "정확도"를 계산하지 않는다. 현장 정답(ground truth)이 없기 때문이다.
- 모든 집합형 출력은 "명시된 전제 아래 가능한 단계"이며 확률이 아니다.

구현한 후보
1. MRSort(현행, incumbent) — crisp q=p=0 에서 (w, lambda) 연속공간 전체를 LP로 정확히 푼다.
   참조제약을 층(layer)별로 넣고 빼서 규범 의존성을 분해한다.
2. COUNT-CORE — 가중치·lambda를 전혀 고르지 않고 허용 박스만 쓰는 최소가정 모형.
   경계 통과 기준 개수 k 만으로 필연통과/필연불통과를 판정한다.
3. PARETO / 부분순서 — 경계 프로파일에 대한 지배관계와 업종 간 부분순서.
4. UTADIS-GMS / Robust Ordinal Regression — 가법 가치함수 + 계급 문턱의
   필연/가능 배정. 특성점(characteristic point)만 변수로 두는 정확한 구현.
5. PROMETHEE-II + SMAA — 같은 w 박스에서 순위수용도(rank acceptability). 서술용.
6. 변화점 탐지 — g4(지속기간)가 담지 못하는 구조변화 정보가 실제로 추가되는지 확인.

용어
- necessary(필연): 명시된 전제를 만족하는 모든 파라미터에서 같은 배정.
- possible(가능): 그런 파라미터가 하나라도 존재하는 배정.
"""
from itertools import combinations

import numpy as np
import pandas as pd
from scipy.optimize import linprog

from . import config, electre

CRIT = list(config.CRITERIA)
EMP = list(config.EMPLOYMENT_CRITERIA)
NAMES = np.array(['OBSERVE', 'CHECK', 'PRIORITY'])
EPS = electre.EPS
SLACK_MIN = 1e-8  # LP 해의 강부등호 여유 하한(수치 허용오차). 판정 파라미터가 아니다.


# ==================================================================== 공통
def space_bounds(doc):
    """사전등록 문서의 허용 파라미터 박스를 (w_min, w_max, lam_min, lam_max)로 돌려준다."""
    ps = doc['parameter_space']
    return (float(ps['weights']['min']), float(ps['weights']['max']),
            float(ps['lambda']['min']), float(ps['lambda']['max']))


def reference_cases(doc, values, panel, include=('RC', 'VRC'), exclude_ids=()):
    """참조사례를 (기준값 dict, relation, stage, id) 목록으로 만든다.

    include 에 'RC'가 있으면 실제 업종×분기 참조사례, 'VRC'가 있으면 가상 프로파일을 넣는다.
    가상 프로파일은 패널에 추가하지 않는다(사전등록 AM6 규칙).
    """
    cases = []
    if 'RC' in include:
        for case in doc['reference_cases']:
            if case['id'] in exclude_ids:
                continue
            pos = panel.index[(panel.industry == case['industry']) & (panel.quarter == case['quarter'])][0]
            cases.append({'id': case['id'], 'x': {j: float(values.loc[pos, j]) for j in CRIT},
                          'relation': case['relation'], 'stage': case['stage'], 'kind': 'real_row'})
    if 'VRC' in include:
        for case in _vrc_list(doc):
            if case['id'] in exclude_ids:
                continue
            cases.append({'id': case['id'], 'x': {j: float(case['profile'][j]) for j in CRIT},
                          'relation': case['relation'], 'stage': case['stage'], 'kind': 'virtual_profile'})
    return cases


def _vrc_list(doc):
    am6 = next(a for a in doc['amendments'] if a['id'] == 'AM6')
    return am6['content']['virtual_reference_cases']


def stage_text(flags):
    return '|'.join(NAMES[np.asarray(flags, bool)])


# ==================================================================== 1. MRSort 연속공간(crisp)
def _pass_pattern(x, profile):
    """q=p=0 에서 각 기준이 경계를 통과하는지의 0/1 벡터."""
    return np.array([1.0 if float(x[j]) >= float(profile[j]) - 0.0 else 0.0 for j in CRIT])


def _gate_ok(pattern):
    """고용증거 게이트: 고용 기준(g1·g2·g4) 중 하나라도 해당 경계를 통과해야 한다."""
    return any(pattern[CRIT.index(j)] > 0 for j in EMP)


def _case_rows(cases, profiles):
    """참조사례를 LP 제약 행으로 바꾼다. 반환: (A_ub 행 목록, b_ub 목록).

    변수 순서: [w_g1, w_g2, w_g3, w_g4, lambda, s]  (s = 강부등호 여유, 최대화 대상)
    통과 제약:  -c·w + lambda           <= EPS
    불통과 제약:  c·w - lambda + s       <= -EPS
    게이트가 막혀 통과가 불가능한 사례는 즉시 모순으로 표시한다.
    """
    a, b, impossible = [], [], []
    for case in cases:
        rank = list(NAMES).index(case['stage'])
        if case['relation'] == 'at_least' and rank >= 1:
            h = 'b' + str(rank)
            c = _pass_pattern(case['x'], profiles[h])
            if not _gate_ok(c):
                impossible.append(case['id'])
                continue
            a.append(np.r_[-c, 1.0, 0.0]); b.append(EPS)
        elif case['relation'] == 'at_most' and rank <= 1:
            h = 'b' + str(rank + 1)
            c = _pass_pattern(case['x'], profiles[h])
            if not _gate_ok(c):
                continue  # 게이트가 이미 막으므로 제약이 자동 충족된다.
            a.append(np.r_[c, -1.0, 1.0]); b.append(-EPS)
    return a, b, impossible


def mrsort_crisp_sets(values, profiles, doc, cases=(), gate=True, return_witnesses=False):
    """q=p=0 MRSort 의 가능 단계 집합을 (w, lambda) 연속공간 전체에서 LP로 정확히 구한다.

    audit 의 continuous_certificates 는 q,p 가 자유로운 비선형 공간이라 외부범위+witness 가
    필요했다. 여기서는 q=p=0 으로 고정하므로 concordance 가 w 에 선형이고, 각 (행, 단계)의
    존재성은 하나의 선형계획으로 정확히 판정된다(수치 허용오차 제외).
    """
    w_min, w_max, lam_min, lam_max = space_bounds(doc)
    base_a, base_b, impossible = _case_rows(cases, profiles)
    if impossible:
        raise ValueError('고용증거 게이트와 모순되는 참조사례: ' + ','.join(impossible))
    bounds = [(w_min, w_max)] * 4 + [(lam_min, lam_max), (0.0, 1.0)]
    a_eq, b_eq = [[1, 1, 1, 1, 0, 0]], [1.0]
    flags = np.zeros((len(values), 3), dtype=bool)
    witnesses = []
    for pos, (idx, x) in enumerate(values.iterrows()):
        if x.isna().any():
            continue
        c1 = _pass_pattern(x, profiles['b1'])
        c2 = _pass_pattern(x, profiles['b2'])
        gate1 = _gate_ok(c1) or not gate
        gate2 = _gate_ok(c2) or not gate
        for stage in range(3):
            rows, rhs = list(base_a), list(base_b)
            feasible = True
            # 단계 정의: OBSERVE = b1 불통과, CHECK = b1 통과 & b2 불통과, PRIORITY = b2 통과.
            for h, c, gate_ok, need_pass in (('b1', c1, gate1, stage >= 1), ('b2', c2, gate2, stage >= 2)):
                if h == 'b2' and stage == 0:
                    continue  # b1 불통과이면 b2 불통과는 단조성으로 자동이다.
                if need_pass:
                    if not gate_ok:
                        feasible = False
                        break
                    rows.append(np.r_[-c, 1.0, 0.0]); rhs.append(EPS)
                else:
                    if not gate_ok:
                        continue  # 게이트가 막으므로 불통과가 자동 충족된다.
                    rows.append(np.r_[c, -1.0, 1.0]); rhs.append(-EPS)
            if not feasible:
                continue
            sol = linprog([0, 0, 0, 0, 0, -1], A_ub=rows or None, b_ub=rhs or None,
                          A_eq=a_eq, b_eq=b_eq, bounds=bounds, method='highs')
            if sol.success and sol.x[-1] > SLACK_MIN:
                flags[pos, stage] = True
                if return_witnesses:
                    witnesses.append({'row': int(pos), 'stage': str(NAMES[stage]),
                                      **{'w_' + j: float(v) for j, v in zip(CRIT, sol.x[:4])},
                                      'lambda': float(sol.x[4]), 'slack': float(sol.x[5])})
    return (flags, witnesses) if return_witnesses else flags


# ==================================================================== 2. COUNT-CORE
def count_core_bounds(k, w_min, w_max, n=4):
    """기준 k개가 경계를 통과할 때 concordance 의 최소·최대(가중치 박스와 단순 제약만 사용)."""
    lo = max(k * w_min, 1.0 - (n - k) * w_max)
    hi = min(k * w_max, 1.0 - (n - k) * w_min)
    return lo, hi


def count_core(values, profiles, doc, gate=True):
    """가중치·lambda를 고르지 않고 허용 박스만 쓴 필연/가능 판정.

    이 모형은 참조사례를 전혀 쓰지 않는다. 따라서 여기서 나오는 판별력은
    "정책 선호를 넣기 전에 자료만으로 결정되는 부분"의 하한이다.
    """
    w_min, w_max, lam_min, lam_max = space_bounds(doc)
    rows = []
    for pos, (idx, x) in enumerate(values.iterrows()):
        rec = {'row': pos}
        if x.isna().any():
            rows.append({**rec, 'k_b1': np.nan, 'k_b2': np.nan, 'possible_stages': '',
                         'core_status': 'UNDETERMINED'})
            continue
        for h in ('b1', 'b2'):
            c = _pass_pattern(x, profiles[h])
            k = int(c.sum())
            lo, hi = count_core_bounds(k, w_min, w_max)
            blocked = gate and not _gate_ok(c)
            rec['k_' + h] = k
            rec['gate_blocked_' + h] = bool(blocked)
            rec['pass_' + h] = ('NECESSARY_FAIL' if blocked or hi < lam_min - EPS
                                else 'NECESSARY_PASS' if lo >= lam_max - EPS else 'PARAMETER_DEPENDENT')
        rows.append(rec)
    return pd.DataFrame(rows)


# ==================================================================== 3. PARETO / 부분순서
def dominance_matrix(frame, criteria=None):
    """A가 B를 지배: 모든 기준에서 같거나 더 심각하고 최소 한 기준에서 더 심각하다."""
    criteria = list(criteria or CRIT)
    x = frame[criteria].to_numpy(float)
    ge = (x[:, None, :] >= x[None, :, :] - 0.0).all(axis=2)
    gt = (x[:, None, :] > x[None, :, :]).any(axis=2)
    dom = ge & gt
    np.fill_diagonal(dom, False)
    return dom


def partial_order_summary(frame, key_columns, criteria=None):
    """부분순서 요약: 지배 건수, 피지배 건수, 최대원소(비지배) 여부, 비교불가 쌍 수."""
    criteria = list(criteria or CRIT)
    dom = dominance_matrix(frame, criteria)
    n = len(frame)
    equal = (frame[criteria].to_numpy(float)[:, None, :] == frame[criteria].to_numpy(float)[None, :, :]).all(axis=2)
    np.fill_diagonal(equal, False)
    incomparable = ~dom & ~dom.T & ~equal
    np.fill_diagonal(incomparable, False)
    out = frame[key_columns].copy().reset_index(drop=True)
    out['dominates_n'] = dom.sum(axis=1)
    out['dominated_by_n'] = dom.sum(axis=0)
    out['is_maximal'] = dom.sum(axis=0) == 0
    out['incomparable_n'] = incomparable.sum(axis=1)
    stats = {'n': n, 'n_pairs': n * (n - 1) // 2,
             'n_comparable_pairs': int(dom.sum()),
             'n_equal_pairs': int(equal.sum() // 2),
             'n_incomparable_pairs': int(incomparable.sum() // 2),
             'criteria': ','.join(criteria)}
    return out, stats, dom


def boundary_dominance(values, profiles):
    """경계 프로파일에 대한 지배관계. 가중치를 전혀 쓰지 않는다.

    dominates_b2 = 네 기준이 모두 b2 이상 → 어떤 허용 가중치에서도 우선점검.
    no_pass_b1   = 어떤 기준도 b1 이상이 아님 → 어떤 허용 가중치에서도 관찰.
    """
    rows = []
    for pos, (idx, x) in enumerate(values.iterrows()):
        if x.isna().any():
            rows.append({'row': pos, 'dominates_b1': None, 'dominates_b2': None, 'no_pass_b1': None})
            continue
        c1, c2 = _pass_pattern(x, profiles['b1']), _pass_pattern(x, profiles['b2'])
        rows.append({'row': pos, 'dominates_b1': bool(c1.all()), 'dominates_b2': bool(c2.all()),
                     'no_pass_b1': bool(c1.sum() == 0)})
    return pd.DataFrame(rows)


def criterion_decisiveness(frame, criteria=None):
    """각 기준이 지배관계를 결정하는 정도: 그 기준을 빼면 새로 생기는 지배 쌍 수.

    g1·g2·g4 가 같은 고용계열에서 파생되므로 naive Pareto 가 사실상 고용 차원만으로
    결정되는지 확인하기 위한 진단이다.
    """
    criteria = list(criteria or CRIT)
    base = dominance_matrix(frame, criteria)
    rows = []
    for j in criteria:
        rest = [c for c in criteria if c != j]
        alt = dominance_matrix(frame, rest)
        rows.append({'removed_criterion': j, 'base_dominance_pairs': int(base.sum()),
                     'dominance_pairs_without': int(alt.sum()),
                     'pairs_blocked_only_by_this_criterion': int((alt & ~base).sum())})
    return pd.DataFrame(rows)


# ==================================================================== 4. UTADIS-GMS / ROR
def _value_points(values, cases, alternative):
    """기준별 특성점. 가법 가치함수는 제약에 등장하는 값에서만 평가되므로 이 점들로 충분하다."""
    points = {}
    for j in CRIT:
        universe = [0.0, float(values[j].max())]
        universe += [float(c['x'][j]) for c in cases]
        universe += [float(alternative[j])]
        points[j] = sorted(set(round(v, 10) for v in universe))
    return points


def _u_index(points):
    """변수 인덱스: 각 기준의 최솟값(=0) 은 u=0 으로 고정하므로 변수에서 제외한다."""
    index, n = {}, 0
    for j in CRIT:
        for v in points[j][1:]:
            index[(j, v)] = n
            n += 1
    return index, n


def _u_row(index, n_u, x, points):
    """U(x) = sum_j u_j(x_j) 의 계수 행. x_j 가 정확히 특성점 위에 있다고 가정한다."""
    row = np.zeros(n_u)
    for j in CRIT:
        v = round(float(x[j]), 10)
        if v > points[j][0]:
            row[index[(j, v)]] = 1.0
    return row


def ror_sets(values, cases, share_bounds=None, ok_mask=None):
    """UTADIS-GMS 의 가능 단계 집합(가능 배정). 단일 원소이면 필연 배정이다.

    가치함수: U(x) = sum_j u_j(g_j), u_j 는 비감소, u_j(0)=0, sum_j u_j(max_j)=1.
    계급: U < t1 → OBSERVE, t1 <= U < t2 → CHECK, U >= t2 → PRIORITY.
    share_bounds: (lo, hi) 를 주면 u_j(max_j) 를 그 구간으로 제한한다(MRSort 의 w 박스와 대응).
    변수: [u..., t1, t2, eps]. eps 를 최대화하고 eps > SLACK_MIN 이면 가능으로 본다.
    """
    flags = np.zeros((len(values), 3), dtype=bool)
    ok_mask = values.notna().all(axis=1).to_numpy() if ok_mask is None else ok_mask
    for pos, (idx, x) in enumerate(values.iterrows()):
        if not ok_mask[pos]:
            continue
        points = _value_points(values, cases, x)
        index, n_u = _u_index(points)
        n = n_u + 3  # + t1, t2, eps
        a_ub, b_ub = [], []

        def add(row, rhs):
            a_ub.append(row); b_ub.append(rhs)

        # 단조성: u_j(v_{i+1}) - u_j(v_i) >= 0
        for j in CRIT:
            pts = points[j]
            for lo_v, hi_v in zip(pts[:-1], pts[1:]):
                row = np.zeros(n)
                if lo_v > pts[0]:
                    row[index[(j, lo_v)]] = 1.0
                row[index[(j, hi_v)]] -= 1.0
                add(row, 0.0)
        # t2 >= t1
        row = np.zeros(n); row[n_u] = 1.0; row[n_u + 1] = -1.0
        add(row, 0.0)
        norm = np.zeros(n)
        for j in CRIT:
            norm[index[(j, points[j][-1])]] = 1.0
        a_eq = [norm]
        b_eq = [1.0]
        bounds = [(0.0, 1.0)] * n_u + [(0.0, 1.0), (0.0, 1.0), (0.0, 1.0)]
        if share_bounds is not None:
            lo_s, hi_s = share_bounds
            for j in CRIT:
                top = np.zeros(n); top[index[(j, points[j][-1])]] = -1.0
                add(top, -lo_s)
                top = np.zeros(n); top[index[(j, points[j][-1])]] = 1.0
                add(top, hi_s)

        def value_row(xx):
            return np.r_[_u_row(index, n_u, xx, points), 0.0, 0.0, 0.0]

        for case in cases:
            rank = list(NAMES).index(case['stage'])
            u = value_row(case['x'])
            if case['relation'] == 'at_least' and rank >= 1:
                # U(x) >= t_rank + eps
                row = -u.copy(); row[n_u + rank - 1] = 1.0; row[-1] = 1.0
                add(row, 0.0)
            elif case['relation'] == 'at_most' and rank <= 1:
                # U(x) <= t_{rank+1} - eps
                row = u.copy(); row[n_u + rank] = -1.0; row[-1] = 1.0
                add(row, 0.0)
        ux = value_row(x)
        for stage in range(3):
            rows, rhs = list(a_ub), list(b_ub)
            if stage == 0:                      # U(x) <= t1 - eps
                r = ux.copy(); r[n_u] = -1.0; r[-1] = 1.0; rows.append(r); rhs.append(0.0)
            elif stage == 1:                    # t1 <= U(x) <= t2 - eps
                r = -ux.copy(); r[n_u] = 1.0; rows.append(r); rhs.append(0.0)
                r = ux.copy(); r[n_u + 1] = -1.0; r[-1] = 1.0; rows.append(r); rhs.append(0.0)
            else:                               # U(x) >= t2
                r = -ux.copy(); r[n_u + 1] = 1.0; rows.append(r); rhs.append(0.0)
            obj = np.zeros(n); obj[-1] = -1.0
            sol = linprog(obj, A_ub=np.array(rows), b_ub=np.array(rhs),
                          A_eq=np.array(a_eq), b_eq=b_eq, bounds=bounds, method='highs')
            if sol.success and sol.x[-1] > SLACK_MIN:
                flags[pos, stage] = True
    return flags


def ror_base_feasible(values, cases, share_bounds=None):
    """선호정보 자체의 양립성(inconsistency 점검). eps>0 해가 없으면 모순이다."""
    probe = values.dropna().iloc[[0]]
    points = _value_points(values, cases, probe.iloc[0])
    index, n_u = _u_index(points)
    n = n_u + 3
    a_ub, b_ub = [], []
    for j in CRIT:
        pts = points[j]
        for lo_v, hi_v in zip(pts[:-1], pts[1:]):
            row = np.zeros(n)
            if lo_v > pts[0]:
                row[index[(j, lo_v)]] = 1.0
            row[index[(j, hi_v)]] -= 1.0
            a_ub.append(row); b_ub.append(0.0)
    row = np.zeros(n); row[n_u] = 1.0; row[n_u + 1] = -1.0
    a_ub.append(row); b_ub.append(0.0)
    norm = np.zeros(n)
    for j in CRIT:
        norm[index[(j, points[j][-1])]] = 1.0
    bounds = [(0.0, 1.0)] * n_u + [(0.0, 1.0), (0.0, 1.0), (0.0, 1.0)]
    if share_bounds is not None:
        lo_s, hi_s = share_bounds
        for j in CRIT:
            top = np.zeros(n); top[index[(j, points[j][-1])]] = -1.0
            a_ub.append(top); b_ub.append(-lo_s)
            top = np.zeros(n); top[index[(j, points[j][-1])]] = 1.0
            a_ub.append(top); b_ub.append(hi_s)
    for case in cases:
        rank = list(NAMES).index(case['stage'])
        u = np.r_[_u_row(index, n_u, case['x'], points), 0.0, 0.0, 0.0]
        if case['relation'] == 'at_least' and rank >= 1:
            r = -u.copy(); r[n_u + rank - 1] = 1.0; r[-1] = 1.0
            a_ub.append(r); b_ub.append(0.0)
        elif case['relation'] == 'at_most' and rank <= 1:
            r = u.copy(); r[n_u + rank] = -1.0; r[-1] = 1.0
            a_ub.append(r); b_ub.append(0.0)
    obj = np.zeros(n); obj[-1] = -1.0
    sol = linprog(obj, A_ub=np.array(a_ub), b_ub=np.array(b_ub), A_eq=[norm], b_eq=[1.0],
                  bounds=bounds, method='highs')
    return bool(sol.success and sol.x[-1] > SLACK_MIN), float(sol.x[-1]) if sol.success else float('nan')


# ==================================================================== 5. PROMETHEE-II + SMAA
def promethee_rank_acceptability(frame, doc, n_draws=20000, seed=2026, criteria=None):
    """같은 w 박스에서 뽑은 가중치로 PROMETHEE-II 순수흐름 순위의 수용도를 센다.

    선호함수는 usual criterion(문턱 없음)만 쓴다. q/p 문턱을 새로 도입하지 않기 위해서다.
    결과는 "표집분포에 조건부인 빈도"이며 위기 확률이나 정답 확률이 아니다.
    """
    criteria = list(criteria or CRIT)
    w_min, w_max, _, _ = space_bounds(doc)
    x = frame[criteria].to_numpy(float)
    n = len(x)
    pref = (x[:, None, :] > x[None, :, :]).astype(float)   # usual criterion
    rng = np.random.default_rng(seed)
    accept = np.zeros((n, n))
    kept = 0
    while kept < n_draws:
        batch = rng.dirichlet(np.ones(len(criteria)), size=n_draws)
        batch = batch[(batch >= w_min).all(1) & (batch <= w_max).all(1)]
        for w in batch:
            if kept >= n_draws:
                break
            net = (pref * w).sum(2).sum(1) - (pref.transpose(1, 0, 2) * w).sum(2).sum(1)
            order = np.argsort(-net, kind='mergesort')
            ranks = np.empty(n, dtype=int)
            ranks[order] = np.arange(n)
            accept[np.arange(n), ranks] += 1
            kept += 1
    out = frame.copy().reset_index(drop=True)
    for r in range(n):
        out['rank_' + str(r + 1) + '_acceptability'] = accept[:, r] / n_draws
    out['expected_rank'] = (accept / n_draws @ (np.arange(n) + 1))
    out['scope'] = 'w 박스 균등표집에 조건부인 순위 빈도; 위기 확률이나 정답 확률이 아님'
    return out


# ==================================================================== 6. 변화점 탐지
def single_changepoint(series, n_perm=2000, seed=2026, min_segment=3):
    """평균 이동 1개를 가정한 단일 변화점 탐지 + 순열검정.

    분기 수가 적으므로 HMM·딥러닝 시계열은 적용하지 않는다.
    반환: (변화점 위치, 검정통계량, 순열 p값). 유효 관측이 부족하면 NaN.
    """
    y = np.asarray(series, dtype=float)
    y = y[np.isfinite(y)]
    n = len(y)
    if n < 2 * min_segment:
        return np.nan, np.nan, np.nan

    def best_split(v):
        stats = []
        for k in range(min_segment, len(v) - min_segment + 1):
            left, right = v[:k], v[k:]
            pooled = np.sqrt(left.var(ddof=1) / len(left) + right.var(ddof=1) / len(right))
            stats.append(0.0 if pooled == 0 else abs(left.mean() - right.mean()) / pooled)
        return (int(np.argmax(stats)) + min_segment, float(np.max(stats))) if stats else (np.nan, np.nan)

    pos, stat = best_split(y)
    if not np.isfinite(stat):
        return np.nan, np.nan, np.nan
    rng = np.random.default_rng(seed)
    null = np.array([best_split(rng.permutation(y))[1] for _ in range(n_perm)])
    return pos, stat, float((np.sum(null >= stat) + 1) / (n_perm + 1))
