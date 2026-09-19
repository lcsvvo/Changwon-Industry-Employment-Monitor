"""Independent, explicitly scoped audit computations. No parameter tuning or adoption gates.

Legacy engines remain available to reproduce historical results. The fast evaluator is
checked against them; continuous-space exclusions are conservative LP certificates,
not inferences from a finite sample. Revision simulations are stress scenarios, not
calibrated predictive probabilities.
"""
from itertools import product

import numpy as np
import pandas as pd
from scipy.optimize import linprog

from . import config, derive, electre, qp_calibration

CRIT = list(config.CRITERIA)
NAMES = np.array(['OBSERVE', 'CHECK', 'PRIORITY'])


def fast_matrix(values, profiles, samples, gate=True):
    """Vectorized equivalent of robust.assignment_matrix for the no-veto model."""
    x = values[CRIT].to_numpy(float)
    ok = np.isfinite(x).all(axis=1)
    w = np.array([[s['weights'][j] for j in CRIT] for s in samples])
    q = np.array([[s['q'][j] for j in CRIT] for s in samples])
    p = np.array([[s['p'][j] for j in CRIT] for s in samples])
    lam = np.array([s['lambda'] for s in samples])
    out = np.zeros((len(samples), len(x)), dtype=np.int8)
    for rank, h in enumerate(('b1', 'b2'), 1):
        b = np.array([profiles[h][j] for j in CRIT])
        lo, hi = b - p, b - q
        den = p - q
        c = np.clip((x[None] - lo[:, None]) / np.where(den == 0, 1, den)[:, None], 0, 1)
        c = np.where((den == 0)[:, None], x[None] >= hi[:, None], c)
        support = np.nan_to_num(c)
        evidence = (support[:, :, [0, 1, 3]] > 0).any(axis=2)
        passed = (support * w[:, None]).sum(axis=2) >= lam[:, None] - electre.EPS
        if gate:
            passed &= evidence
        out[passed & ok[None]] = rank
    out[:, ~ok] = -1
    return out


def sets_from_matrix(matrix):
    if len(matrix) == 0:
        raise ValueError('Empty parameter sample is not evidence of impossibility.')
    return np.array([(matrix == k).any(axis=0) for k in range(3)]).T


def sample_record(scenario, candidate):
    return dict(weights=scenario.weights, **{'lambda': scenario.lam}, q=candidate['q'], p=candidate['p'])


def coherent_revision(panel, master, vintage, rng, mode='quarter_block', block_length=4,
                      direction='forward'):
    """Perturb each industry/quarter level ONCE, then rebuild calendar lag and g4.

    cell: marginal empirical pools, but consistent lags; quarter_block: joint vector
    across industries and variables with contiguous donor blocks (no wrap/gap bridge).
    inverse: reconstruct a plausible earlier vintage from an already revised level.
    These are alternative stress assumptions; vintage publication ages are unknown.
    """
    if mode not in ('cell', 'quarter_block') or direction not in ('forward', 'inverse'):
        raise ValueError('Unknown revision scenario')
    m = master.sort_values(['industry', 'quarter']).copy().reset_index(drop=True)
    if m.duplicated(['industry', 'quarter']).any():
        raise ValueError('Duplicate source level key')
    industries = sorted(m.industry.unique())
    quarters = sorted(m.quarter.unique())
    lag_quarters = {q: str(pd.Period(q, freq='Q') - 4) for q in quarters}
    v = vintage.rename(columns={'업종': 'industry', '분기': 'quarter', '변수': 'variable', '수정율pct': 'rate'})
    if v.duplicated(['industry', 'quarter', 'variable']).any():
        raise ValueError('Duplicate revision key')
    multipliers = {}
    if mode == 'cell':
        for var in ('employment', 'production'):
            rates = v.loc[v.variable == var, 'rate'].dropna().to_numpy(float) / 100
            multipliers[var] = 1 + rng.choice(rates, size=len(m))
    else:
        cols = pd.MultiIndex.from_product([industries, ['employment', 'production']])
        joint = v.pivot(index='quarter', columns=['industry', 'variable'], values='rate').reindex(columns=cols).dropna().sort_index() / 100
        ordinal = pd.PeriodIndex(joint.index, freq='Q').asi8
        length = min(block_length, len(joint))
        while length:
            starts = [i for i in range(len(joint)-length+1)
                      if length == 1 or np.all(np.diff(ordinal[i:i+length]) == 1)]
            if starts:
                break
            length -= 1
        if not length:
            raise ValueError('No complete joint revision vector')
        draws = []
        while len(draws) < len(quarters):
            start = int(rng.choice(starts))
            draws.extend(joint.iloc[start:start+length].to_numpy())
        draws = np.array(draws[:len(quarters)])
        qi = {q: i for i, q in enumerate(quarters)}
        ci = {c: i for i, c in enumerate(cols)}
        for var in ('employment', 'production'):
            multipliers[var] = np.array([1 + draws[qi[q], ci[(ind, var)]] for ind, q in zip(m.industry, m.quarter)])
    for var in ('employment', 'production'):
        mul = multipliers[var]
        if np.any(~np.isfinite(mul)) or np.any(mul <= 0):
            raise ValueError('Invalid multiplicative revision')
        m[var] = m[var] * (mul if direction == 'forward' else 1 / mul)
        levels = m.set_index(['industry', 'quarter'])[var]
        previous = [(ind, lag_quarters[q]) for ind, q in zip(m.industry, m.quarter)]
        m[var + '_lag4'] = levels.reindex(pd.MultiIndex.from_tuples(previous)).to_numpy()
        m[var + '_yoy'] = ((m[var] / m[var + '_lag4'] - 1) * 100).where(m[var + '_lag4'].gt(0))
    m['quarter_index'] = derive.calendar_ordinal(m.quarter)
    # A four-quarter YoY comparison must not bridge a recorded classification event.
    # This reproduces the employment comparison-risk windows in the Q1/Q2/Q3 builder,
    # without changing its observed YoY or state outputs.
    history = m[['industry', 'quarter', 'quarter_index', 'employment_yoy']].copy()
    risk = np.zeros(len(m), dtype=bool)
    if 'classification_break' in m:
        ordinal = m.quarter_index.to_numpy()
        events = m.classification_break.fillna(0).astype(bool).to_numpy()
        for positions in m.groupby('industry', sort=False).indices.values():
            for event in ordinal[positions][events[positions]]:
                risk[positions] |= (ordinal[positions] >= event) & (ordinal[positions] < event + 4)
    history.loc[risk, 'employment_yoy'] = np.nan
    m['g4_delta00'] = derive.emp_yoy_below_run(history, 0, len(quarters), quarters[-1])['run'].to_numpy()
    m[config.CRITERION_COLUMNS['g1']] = np.maximum(0, m.employment_lag4 - m.employment)
    m[config.CRITERION_COLUMNS['g2']] = np.maximum(0, -m.employment_yoy)
    m[config.CRITERION_COLUMNS['g3']] = np.maximum(0, -m.production_yoy)
    cols = ['employment', 'employment_lag4', 'employment_yoy', 'production', 'production_lag4', 'production_yoy', 'g4_delta00'] + [config.CRITERION_COLUMNS[j] for j in CRIT[:3]]
    out = panel.copy()
    selected = m.set_index(['industry', 'quarter']).reindex(pd.MultiIndex.from_frame(panel[['industry', 'quarter']]))
    for c in cols:
        out[c] = selected[c].to_numpy()
    return out


def concordance_vector(x, b, q, p):
    return np.array([qp_calibration.partial_concordance([x[j]], b[j], q[j], p[j])[0] for j in CRIT])


def continuous_certificates(values, profiles, doc, include_vrc4=True, panel=None):
    """Conservative bounds over the full q,p space, and exact crisp LP assignments.

    All reference constraints are enforced for fixed-q,p feasibility. Full-space bounds
    use necessary linear relaxations of RC/VRC constraints plus the VRC4 coalition.
    A relaxed-space exclusion is a valid exclusion for the original space;
    non-exclusion is NOT an existence proof.
    Boundary EPS follows the production evaluator. LP failures remain unresolved.
    """
    ps = doc['parameter_space']
    bounds = [(ps['weights']['min'], ps['weights']['max'])] * 4 + [(ps['lambda']['min'], ps['lambda']['max'])]
    eq = [[1, 1, 1, 1, 0]]
    outer = [[0, -1, 0, -1, 1]] if include_vrc4 else []
    rhs = [electre.EPS] if outer else []
    zero = dict.fromkeys(CRIT, 0.)
    upper = ps['p_upper']
    half = {j: upper[j] / 2 for j in CRIT}
    required_supports = []
    cases = [(c['profile'], c) for c in doc['amendments'][-1]['content']['virtual_reference_cases']
             if include_vrc4 or c['id'] != 'VRC4']
    if panel is not None:
        for case in doc['reference_cases']:
            pos = panel.index[(panel.industry == case['industry']) & (panel.quarter == case['quarter'])][0]
            cases.append((values.loc[pos].to_dict(), case))
    for cx, case in cases:
        rank = list(NAMES).index(case['stage'])
        if case['relation'] == 'at_least' and rank:
            cmax = concordance_vector(cx, profiles['b'+str(rank)], half, upper)
            outer.append(np.r_[-cmax, 1]); rhs.append(electre.EPS)
            required_supports.append(cmax)
        elif case['relation'] == 'at_most' and rank < 2:
            cmin = concordance_vector(cx, profiles['b'+str(rank+1)], zero, zero)
            # Non-strict relaxation of the true strict failure constraint.
            outer.append(np.r_[cmin, -1]); rhs.append(-electre.EPS)
    rows = []
    for idx, x in values.iterrows():
        if x.isna().any():
            rows.append({'row': idx, 'outer_possible': '', 'outer_singleton': False})
            continue
        extremes = {}
        for h in ('b1', 'b2'):
            for kind, q, p in [('min', zero, zero), ('max', half, upper)]:
                c = concordance_vector(x, profiles[h], q, p)
                obj = np.r_[c, -1.]
                sol = linprog(obj if kind == 'min' else -obj, A_ub=outer or None, b_ub=rhs or None,
                              A_eq=eq, b_eq=[1], bounds=bounds, method='highs')
                if not sol.success:
                    raise RuntimeError('Continuous outer-bound LP did not resolve: ' + sol.message)
                extremes[h, kind] = float(obj @ sol.x)
        # Extra 1e-8 numerical guard: only certify exclusions safely away from tolerance.
        lower = 2 if extremes['b2', 'min'] > 1e-8 else (1 if extremes['b1', 'min'] > 1e-8 else 0)
        # Symbolic dominance handles guaranteed passage exactly at lambda-EPS,
        # where a floating-point LP objective cannot safely certify strict margins.
        for rank, h in enumerate(('b1', 'b2'), 1):
            cmin = concordance_vector(x, profiles[h], zero, zero)
            if any(np.all(cmin >= required) for required in required_supports):
                lower = max(lower, rank)
        upper_rank = 0 if extremes['b1', 'max'] < -1e-8 else (1 if extremes['b2', 'max'] < -1e-8 else 2)
        rows.append({'row': idx, 'outer_possible': '|'.join(NAMES[lower:upper_rank+1]),
                     'outer_singleton': lower == upper_rank,
                     **{h+'_'+kind+'_margin': val for (h, kind), val in extremes.items()}})
    return pd.DataFrame(rows)


def fixed_qp_feasible(values, profiles, doc, panel, q, p, include_vrc4=True, target_indices=None):
    """LP existence witnesses over continuous w,lambda for fixed q,p; no grid claims."""
    ps = doc['parameter_space']
    bounds = [(ps['weights']['min'], ps['weights']['max'])] * 4 + [(ps['lambda']['min'], ps['lambda']['max']), (0, 1)]
    cases = []
    for case in doc['reference_cases']:
        pos = panel.index[(panel.industry == case['industry']) & (panel.quarter == case['quarter'])][0]
        cases.append((values.loc[pos].to_dict(), case))
    vrcs = doc['amendments'][-1]['content']['virtual_reference_cases']
    cases += [(c['profile'], c) for c in vrcs if include_vrc4 or c['id'] != 'VRC4']

    def constraint(x, h, passed):
        c = concordance_vector(x, profiles[h], q, p)
        # Last variable is maximized strict-comparison slack for failures.
        return (np.r_[-c, 1, 0], electre.EPS) if passed else (np.r_[c, -1, 1], -electre.EPS)

    a, b = [], []
    for x, case in cases:
        stage = list(NAMES).index(case['stage'])
        if case['relation'] == 'at_least' and stage:
            row, r = constraint(x, 'b'+str(stage), True)
        elif case['relation'] == 'at_most' and stage < 2:
            row, r = constraint(x, 'b'+str(stage+1), False)
        else:
            continue
        a.append(row); b.append(r)
    result = np.zeros((len(values), 3), dtype=bool)
    witnesses = []
    target_values = values if target_indices is None else values.loc[target_indices]
    for i, x in target_values.iterrows():
        if x.isna().any():
            continue
        for stage in range(3):
            aa, bb = list(a), list(b)
            for h, passed in ([('b1', False)] if stage == 0 else [('b1', True), ('b2', False)] if stage == 1 else [('b2', True)]):
                row, r = constraint(x, h, passed); aa.append(row); bb.append(r)
            sol = linprog([0, 0, 0, 0, 0, -1], A_ub=aa, b_ub=bb,
                          A_eq=[[1, 1, 1, 1, 0, 0]], b_eq=[1], bounds=bounds, method='highs')
            if sol.success and sol.x[-1] > 1e-8:
                s = {'weights': dict(zip(CRIT, sol.x[:4])), 'lambda': sol.x[4], 'q': q, 'p': p}
                case_values = pd.DataFrame([cx for cx, _ in cases])
                codes = fast_matrix(case_values, profiles, [s])[0]
                valid = all(code >= list(NAMES).index(case['stage']) if case['relation'] == 'at_least'
                            else code <= list(NAMES).index(case['stage']) for code, (_, case) in zip(codes, cases))
                if valid and fast_matrix(values.loc[[i]], profiles, [s])[0, 0] == stage:
                    result[i, stage] = True
                    witnesses.append({'row': int(i), 'stage': str(NAMES[stage]), **s})
    return result, witnesses


def complete_corner_witnesses(values, profiles, doc, panel, witnessed, outer_sets):
    """Search all 3^4 endpoint q,p configurations only for unresolved rows.

    This is a witness search, never an infeasibility proof for the full nonlinear space.
    Stop only when witnessed and independently certified outer sets coincide.
    """
    witnessed=witnessed.copy(); extra=[]; tried=0
    upper=doc['parameter_space']['p_upper']
    for settings in product(range(3), repeat=4):
        unresolved=[i for i,row in enumerate(witnessed) if '|'.join(NAMES[row])!=outer_sets[i]]
        if not unresolved:
            break
        p={j:0. if setting==0 else upper[j] for j,setting in zip(CRIT,settings)}
        q={j:upper[j]/2 if setting==2 else 0. for j,setting in zip(CRIT,settings)}
        found,ws=fixed_qp_feasible(values,profiles,doc,panel,q,p,target_indices=unresolved)
        added=found & ~witnessed
        extra.extend(dict(qp_case='corner_'+''.join(map(str,settings)),**w) for w in ws
                     if added[w['row'],list(NAMES).index(w['stage'])])
        witnessed |= found; tried+=1
    return witnessed,extra,tried


def point_models(values, profiles, scenario, candidates):
    """Predeclared alternatives; identical profiles, no fitting or outcome targets."""
    samples = [sample_record(scenario, c) for c in candidates.values()]
    matrix = fast_matrix(values, profiles, samples)
    out = dict(zip(candidates, matrix))
    counts = electre.simple_count_rule(values, scenario).simple_class
    out['count2'] = counts.map({'OBSERVE': 0, 'CHECK': 1, 'PRIORITY': 2, config.UNDETERMINED: -1}).to_numpy()
    x = values.to_numpy(float)
    stages = np.zeros(len(x), dtype=np.int8)
    for rank, h in enumerate(('b1', 'b2'), 1):
        passed = x >= np.array([profiles[h][j] for j in CRIT])
        # Group correlated magnitude measures, require persistence OR production corroboration.
        stages[(passed[:, 0] | passed[:, 1]) & (passed[:, 2] | passed[:, 3])] = rank
    stages[~np.isfinite(x).all(axis=1)] = -1
    out['grouped_evidence'] = stages
    # Literal duration policy is an alternative, not silently imposed on adopted preferences.
    literal = np.zeros(len(x), dtype=np.int8)
    b1, b2 = profiles['b1'], profiles['b2']
    # The relative-only persistence route explicitly requires four quarters.
    lower = ((values.g1 >= b1['g1']) & ((values.g3 >= b1['g3']) | (values.g4 >= b1['g4']))) | (
        (values.g2 >= b1['g2']) & ((values.g3 >= b1['g3']) | (values.g4 >= b2['g4'])))
    literal[lower] = 1
    literal[stages == 2] = 2
    literal[stages == -1] = -1
    out['literal_duration4'] = literal
    return out
