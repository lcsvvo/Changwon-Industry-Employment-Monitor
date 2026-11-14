# -*- coding: utf-8 -*-
"""정부 고시(규모요건 300인, 등 4개 기준)에 정박한 카운트 규칙 판단엔진.

기존 ELECTRE-TRI-B/QP 모형과 독립적으로, 정부 고시에 이미 존재하는 4개 지표(고용감소율,
동종업종대비 고용증감률 격차, 생산감소율, 고용감소 지속분기)를 그대로 사용해 "몇 개 기준이
경계를 통과했는가"만으로 단계를 매기는 단순 카운트 규칙이다. 가중치·선호함수·아웃랭킹 같은
모형 내부 장치를 쓰지 않으므로 scipy 등 최적화 라이브러리가 필요 없다.

이 모듈은 순수 계산만 담당한다. 파일 입출력과 산출물 작성은 src/run_gov_anchored_rule.py 에서
수행한다.
"""
import pandas as pd

RULE_VERSION = 'gov-anchored-count-rule/1.0.0'

CRITERIA = ('C1', 'C2', 'C3', 'C4')

# 경계값: b1(1차 경계), b2(2차 경계). C1~C3는 연속형(%,%p), C4는 정수형(분기 수).
B1 = {'C1': 5.0, 'C2': 5.0, 'C3': 5.0, 'C4': 2}
B2 = {'C1': 10.0, 'C2': 10.0, 'C3': 10.0, 'C4': 4}

LABELS = {
    'C1': '고용감소',
    'C2': '동종업종대비 격차',
    'C3': '생산감소',
    'C4': '지속',
}
UNITS = {'C1': '%', 'C2': '%p', 'C3': '%', 'C4': '분기'}

STAGE_RANK = {'OBSERVE': 0, 'CHECK': 1, 'PRIORITY': 2}
STAGE_LABEL_KO = {'OBSERVE': '관찰', 'CHECK': '추가확인', 'PRIORITY': '우선점검'}

ELIGIBILITY_DATA_REVIEW = 'DATA_REVIEW'
ELIGIBILITY_SCALE_BELOW = 'SCALE_BELOW_THRESHOLD'
ELIGIBILITY_ELIGIBLE = 'ELIGIBLE'
ELIGIBILITY_LABEL_KO = {
    ELIGIBILITY_DATA_REVIEW: '자료확인',
    ELIGIBILITY_SCALE_BELOW: '규모미달',
}

DECISION_PANEL_COLUMNS = [
    'industry', 'quarter', 'state', 'employment', 'emp_delta', 'employment_yoy',
    'production_yoy', 'mfg_total_emp_yoy', 'employment_share_pct', 'contribution_pct',
    'run_length', 'C1_emp_decline', 'C2_emp_rel_gap', 'C3_prod_decline', 'C4_emp_below_run',
    'pass_b1_C1', 'pass_b1_C2', 'pass_b1_C3', 'pass_b1_C4',
    'pass_b2_C1', 'pass_b2_C2', 'pass_b2_C3', 'pass_b2_C4',
    'n_pass_b1', 'n_pass_b2', 'eligibility', 'stage_before_r3', 'boundary_sensitive',
    'stage', 'stage_label', 'reason_codes', 'stage_count3_only', 'stage_and_rule',
]


def quarter_sort_key(quarter):
    """'2022Q1' 형태 분기 문자열을 정렬 가능한 정수 키로 변환한다."""
    year = int(quarter[:4])
    q = int(quarter[5])
    return year * 4 + q


def compute_mfg_total_emp_yoy(master):
    """업종 마스터에서 분기별 10개 업종 고용 합계와 그 전년동기대비 증감률(%)을 계산한다.

    changwon_total_master의 employment_total(비제조 포함)을 쓰지 않고, 반드시 industry_master를
    분기별로 10개 업종 합산해 만든다. 결측 규칙: 당분기 또는 4분기 전 합계가 결측이면 NaN
    (pandas pct_change(4, fill_method=None)의 기본 동작).
    """
    totals = master.groupby('quarter', as_index=False)['employment'].sum()
    totals = totals.rename(columns={'employment': 'mfg_total_emp'})
    totals['_qkey'] = totals['quarter'].map(quarter_sort_key)
    totals = totals.sort_values('_qkey').drop(columns='_qkey').reset_index(drop=True)
    totals['mfg_total_emp_yoy'] = totals['mfg_total_emp'].pct_change(4, fill_method=None) * 100.0
    return totals


def compute_eligibility(employment_yoy, production_yoy, employment):
    """0단계 적격성 게이트. 판정(단계 부여) 이전에 적용한다."""
    if pd.isna(employment_yoy) or pd.isna(production_yoy):
        return ELIGIBILITY_DATA_REVIEW
    if employment < 300:
        return ELIGIBILITY_SCALE_BELOW
    return ELIGIBILITY_ELIGIBLE


def build_pass_flags(c_values):
    """C1~C4 값에서 b1/b2 경계 통과 여부(불리언 dict)를 만든다. 결측은 미통과로 취급한다."""
    pass_b1, pass_b2 = {}, {}
    for Cj in CRITERIA:
        v = c_values[Cj]
        if pd.isna(v):
            pass_b1[Cj] = False
            pass_b2[Cj] = False
        else:
            pass_b1[Cj] = bool(v >= B1[Cj])
            pass_b2[Cj] = bool(v >= B2[Cj])
    return pass_b1, pass_b2


def is_marginal(value, target, integer=False):
    """value가 target 경계의 ±10%(연속형) 또는 ±1분기(정수형) 이내인지 판정한다."""
    if pd.isna(value):
        return False
    if integer:
        return abs(value - target) <= 1
    return abs(value - target) <= 0.1 * target


def determine_stage(pass_b1, pass_b2):
    """3단계 사다리 판정. 위에서부터 먼저 걸리는 규칙을 채택한다.

    반환값: (stage, reason_codes(list)). 2번(단독 심각)과 3·4번(카운트)이 동시에 걸리면
    사유코드를 함께 담아 반환한다(호출부에서 '|'로 연결).
    """
    n1 = sum(1 for v in pass_b1.values() if v)
    n2 = sum(1 for v in pass_b2.values() if v)

    if n2 >= 3:
        return 'PRIORITY', ['R0_COUNT3_B2']

    severe = bool(pass_b2.get('C1')) or bool(pass_b2.get('C2'))
    if n1 >= 3:
        count_code = 'R0_COUNT3_B1'
    elif n1 == 2:
        count_code = 'R1_PARTIAL_REVIEW'
    else:
        count_code = None

    if severe:
        codes = ['R2_SEVERE_SINGLE']
        if count_code:
            codes.append(count_code)
        return 'CHECK', codes
    if count_code:
        return 'CHECK', [count_code]
    return 'OBSERVE', ['R0_NONE']


def stage_count3_only(pass_b1, pass_b2):
    """비교 기준선 1: 3단계의 1·3·5번 규칙만 적용한 순수 정부 count 규칙 (R1/R2/R3 없음)."""
    n1 = sum(1 for v in pass_b1.values() if v)
    n2 = sum(1 for v in pass_b2.values() if v)
    if n2 >= 3:
        return 'PRIORITY'
    if n1 >= 3:
        return 'CHECK'
    return 'OBSERVE'


def stage_and_rule(pass_b1, pass_b2):
    """비교 기준선 2: lambda=1.0 AND 규칙(4개 기준 전부 통과해야 상향)."""
    n1 = sum(1 for v in pass_b1.values() if v)
    n2 = sum(1 for v in pass_b2.values() if v)
    if n2 == 4:
        return 'PRIORITY'
    if n1 == 4:
        return 'CHECK'
    return 'OBSERVE'


def evaluate_boundary_sensitivity(c_values, pass_b1, pass_b2, exclude=None):
    """4단계 경계근접 상향(R3)을 적용한다.

    marginal(경계 ±10%/±1분기 이내)이면서 현재 미통과인 각 기준-경계 쌍을, 각각 독립적으로
    그리고 모두 동시에 유리한 방향(미통과->통과)으로 뒤집어 보아, 단계가 한 단계라도 올라갈 수
    있으면 boundary_sensitive=True 로 표시하고 최종 단계를 그 상위 단계로 상향한다.
    exclude 를 주면 해당 기준은 marginal 후보에서 제외한다(기준 기여도 분석용).
    """
    stage_before, codes_before = determine_stage(pass_b1, pass_b2)

    candidates = []
    for Cj in CRITERIA:
        if Cj == exclude:
            continue
        v = c_values[Cj]
        integer = Cj == 'C4'
        if is_marginal(v, B1[Cj], integer) and not pass_b1[Cj]:
            candidates.append(('b1', Cj))
        if is_marginal(v, B2[Cj], integer) and not pass_b2[Cj]:
            candidates.append(('b2', Cj))

    best_stage = stage_before
    if candidates:
        for which, Cj in candidates:
            pb1c, pb2c = dict(pass_b1), dict(pass_b2)
            if which == 'b1':
                pb1c[Cj] = True
            else:
                pb2c[Cj] = True
            st, _ = determine_stage(pb1c, pb2c)
            if STAGE_RANK[st] > STAGE_RANK[best_stage]:
                best_stage = st
        pb1c, pb2c = dict(pass_b1), dict(pass_b2)
        for which, Cj in candidates:
            if which == 'b1':
                pb1c[Cj] = True
            else:
                pb2c[Cj] = True
        st, _ = determine_stage(pb1c, pb2c)
        if STAGE_RANK[st] > STAGE_RANK[best_stage]:
            best_stage = st

    sensitive = STAGE_RANK[best_stage] > STAGE_RANK[stage_before]
    stage_final = best_stage if sensitive else stage_before
    codes_final = list(codes_before)
    if sensitive:
        codes_final.append('R3_BOUNDARY')

    return {
        'stage_before_r3': stage_before,
        'reason_codes_before': '|'.join(codes_before),
        'boundary_sensitive': sensitive,
        'stage': stage_final,
        'reason_codes': '|'.join(codes_final),
    }


def _row_c_values(row):
    return {
        'C1': row['C1_emp_decline'],
        'C2': row['C2_emp_rel_gap'],
        'C3': row['C3_prod_decline'],
        'C4': row['C4_emp_below_run'],
    }


def build_decision_panel(panel_df, master_df):
    """1~4단계 전체 파이프라인을 실행해 180행 전체 판단 패널을 만든다. 행을 삭제하지 않는다."""
    df = panel_df.copy()
    mfg = compute_mfg_total_emp_yoy(master_df)
    df = df.merge(mfg[['quarter', 'mfg_total_emp_yoy']], on='quarter', how='left')

    df['eligibility'] = [
        compute_eligibility(ey, py, emp)
        for ey, py, emp in zip(df['employment_yoy'], df['production_yoy'], df['employment'])
    ]
    df['emp_delta'] = df['employment'] - df['employment_lag4']
    df['C1_emp_decline'] = (-df['employment_yoy']).clip(lower=0)
    df['C2_emp_rel_gap'] = (-(df['employment_yoy'] - df['mfg_total_emp_yoy'])).clip(lower=0)
    df['C3_prod_decline'] = (-df['production_yoy']).clip(lower=0)
    df['C4_emp_below_run'] = df['g4_delta00']

    records = []
    for row in df.to_dict('records'):
        c_values = _row_c_values(row)
        pass_b1, pass_b2 = build_pass_flags(c_values)
        n1 = sum(1 for v in pass_b1.values() if v)
        n2 = sum(1 for v in pass_b2.values() if v)
        eligible = row['eligibility'] == ELIGIBILITY_ELIGIBLE

        rec = {
            'pass_b1_C1': pass_b1['C1'], 'pass_b1_C2': pass_b1['C2'],
            'pass_b1_C3': pass_b1['C3'], 'pass_b1_C4': pass_b1['C4'],
            'pass_b2_C1': pass_b2['C1'], 'pass_b2_C2': pass_b2['C2'],
            'pass_b2_C3': pass_b2['C3'], 'pass_b2_C4': pass_b2['C4'],
            'n_pass_b1': n1, 'n_pass_b2': n2,
        }
        if eligible:
            result = evaluate_boundary_sensitivity(c_values, pass_b1, pass_b2)
            rec['stage_before_r3'] = result['stage_before_r3']
            rec['boundary_sensitive'] = result['boundary_sensitive']
            rec['stage'] = result['stage']
            rec['reason_codes'] = result['reason_codes']
            rec['stage_count3_only'] = stage_count3_only(pass_b1, pass_b2)
            rec['stage_and_rule'] = stage_and_rule(pass_b1, pass_b2)
            rec['stage_label'] = STAGE_LABEL_KO[result['stage']]
        else:
            rec['stage_before_r3'] = ''
            rec['boundary_sensitive'] = False
            rec['stage'] = ''
            rec['reason_codes'] = ''
            rec['stage_count3_only'] = ''
            rec['stage_and_rule'] = ''
            rec['stage_label'] = ELIGIBILITY_LABEL_KO[row['eligibility']]
        records.append(rec)

    extra = pd.DataFrame.from_records(records)
    out = pd.concat([df.reset_index(drop=True), extra.reset_index(drop=True)], axis=1)
    return out[DECISION_PANEL_COLUMNS]


def build_why_text(row):
    """decision_latest.csv 용, 사람이 읽는 한국어 한 줄 설명을 만든다."""
    col_of = {'C1': 'C1_emp_decline', 'C2': 'C2_emp_rel_gap',
              'C3': 'C3_prod_decline', 'C4': 'C4_emp_below_run'}
    parts = []
    for Cj in CRITERIA:
        v = row[col_of[Cj]]
        if pd.isna(v) or v <= 0:
            continue
        p1, p2 = row[f'pass_b1_{Cj}'], row[f'pass_b2_{Cj}']
        b1v, b2v = B1[Cj], B2[Cj]
        if Cj == 'C4':
            if p2:
                desc = f'b2 {int(b2v)}분기 통과'
            elif p1:
                desc = f'b1 {int(b1v)}분기 통과, b2 {int(b2v)}분기 미통과'
            else:
                desc = f'b1 {int(b1v)}분기 미통과'
            parts.append(f'{LABELS[Cj]} {v:.0f}분기({desc})')
        else:
            if p2:
                desc = f'b2 {b2v:.0f}% 통과'
            elif p1:
                desc = f'b1 {b1v:.0f}% 통과, b2 {b2v:.0f}% 미통과'
            else:
                desc = f'b1 {b1v:.0f}% 미통과'
            parts.append(f'{LABELS[Cj]} {v:.1f}{UNITS[Cj]}({desc})')
    body = '·'.join(parts) if parts else '4개 기준 모두 0 이하(악화 신호 없음)'

    codes = [c for c in str(row['reason_codes']).split('|') if c]
    n1, n2 = row['n_pass_b1'], row['n_pass_b2']
    tail_bits = []
    if 'R0_COUNT3_B2' in codes:
        tail_bits.append(f'b2 {n2}개 충족')
    if 'R2_SEVERE_SINGLE' in codes:
        tail_bits.append('C1/C2 중 하나 이상 10%(p) 이상 단독 충족')
    if 'R0_COUNT3_B1' in codes:
        tail_bits.append(f'b1 {n1}개 충족')
    if 'R1_PARTIAL_REVIEW' in codes:
        tail_bits.append(f'b1 {n1}개 충족(2개)')
    if 'R0_NONE' in codes:
        tail_bits.append('경계 통과 기준 없음')
    tail = '·'.join(tail_bits) if tail_bits else '판정 근거 없음'

    stage_label = STAGE_LABEL_KO.get(row['stage'], row['stage'])
    text = f'{body} → {tail} ({stage_label})'
    if 'R3_BOUNDARY' in codes:
        text += ' · 경계근접 상향 적용'
    return text


def compute_criteria_contribution(panel):
    """기준 하나를 항상 미통과 처리했을 때(=제거했을 때) 최종 단계가 바뀌는 행 수를 센다."""
    col_of = {'C1': 'C1_emp_decline', 'C2': 'C2_emp_rel_gap',
              'C3': 'C3_prod_decline', 'C4': 'C4_emp_below_run'}
    eligible = panel[panel['eligibility'] == ELIGIBILITY_ELIGIBLE]
    n_eligible = len(eligible)
    rows = []
    for Cj in CRITERIA:
        changed = 0
        for row in eligible.to_dict('records'):
            c_values = {k: row[col_of[k]] for k in CRITERIA}
            pass_b1, pass_b2 = build_pass_flags(c_values)
            pass_b1[Cj] = False
            pass_b2[Cj] = False
            result = evaluate_boundary_sensitivity(c_values, pass_b1, pass_b2, exclude=Cj)
            if result['stage'] != row['stage']:
                changed += 1
        rows.append({
            'criterion': Cj,
            'label': LABELS[Cj],
            'eligible_rows_evaluated': n_eligible,
            'rows_changed': changed,
            'rows_changed_pct': round(100.0 * changed / n_eligible, 2) if n_eligible else 0.0,
        })
    return pd.DataFrame(rows)
