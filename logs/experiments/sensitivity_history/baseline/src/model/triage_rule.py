# -*- coding: utf-8 -*-
"""창원국가산단 업종 단위 점검 트리아지 규칙 (v3).

이 모형은 '정부가 해당 업종을 위기로 판정했다'를 산출하지 않는다.
정부의 선제대응 제도 논리(임계 수준, 결합 방식, 지속 개념, 규모 요건)를 참고해
창원국가산단 10개 제조업종 × 분기에 대해 다음 행정 확인 단계를 결정하는
프로젝트 자체 트리아지다.

규칙 출처 라벨
  DIRECT : 공식기준 직접 차용   (조문의 수치·구조를 그대로)
  PRINCIPLE : 공식기준에서 원리만 차용 (지표·단위가 달라 수치는 재해석)
  OWN : 프로젝트 자체 운영규칙   (조문 근거 없음, 민감도 보고 대상)

기존 ELECTRE/MRSort 산출물은 건드리지 않는다.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

RULE_VERSION = 'changwon-triage-rule/3.0.0'

# ---------------------------------------------------------------- 경계값
LEVEL_ENTRY = 5.0    # DIRECT: 산업위기선제대응 제2조③(5%), 고용위기지역 제3조①2호(5%)
LEVEL_UP = 10.0      # DIRECT: 산업위기대응특별지역 제3조②(10%), 고용재난지역 제3조④2호(10%)
REL_ENTRY = 5.0      # PRINCIPLE: 특별고용지원업종 제2조①1호(전국평균 대비 5%p) → 산단 제조업 평균 대비
REL_UP = 10.0        # OWN: 조문에 상위 %p 기준 없음
ABS_ENTRY = 1.0      # OWN: 고용 감소인원 ÷ 산단 제조업 고용
ABS_UP = 2.0         # OWN
PROD_SUPPORT = 5.0   # PRINCIPLE: 선제대응 제2조③3호 생산액 5%
SCALE_MIN = 300      # PRINCIPLE: 선제대응 제2조①2호 '종사자 300인 이상' → 우선점검 진입요건으로만

STAGES = ('우선점검', '추가확인', '관찰', '자료확인')

# Q1 국면별 확인질문 (단계가 아니라 '무엇을 확인할지'를 결정)
Q1_QUESTIONS = {
    'S1': '미충원·숙련수요·증가의 지속가능성을 확인한다.',
    'S2': '자동화·설비투자, 외주·도급 전환, 미충원·숙련 불일치, 직무구조 변화 가능성을 질문으로 확인한다(원인 후보이며 입증된 원인이 아님).',
    'S3': '선제채용·신규 입주기업·고용조정 시차·생산 단가와 물량 구분 가능성을 확인한다.',
    'S4': '수주잔량·가동률·휴업/감산·기업 수 변동·고용조정 계획 신고 여부를 확인한다(원인 후보이며 입증된 원인이 아님).',
    'N': '원자료상 정확한 0인지 반올림·개정 영향인지, 0이 아닌 축의 방향과 규모를 확인한다.',
    'INVALID': '원자료와 비교기간(전년동기 기준값)의 존재 여부를 먼저 확인한다.',
}
# Q1 국면별 1차 담당 기능 (기존 체계로의 인계 지점, 자동 지원연계가 아님)
Q1_OWNER = {
    'S1': '고용·훈련 기능',
    'S2': '고용·훈련 기능 + 기업지원 기능',
    'S3': '기업지원 기능(모니터링)',
    'S4': '기업지원 기능 + 고용지원 기능',
    'N': '자료 검토',
    'INVALID': '자료 검토',
}


def compute_axes(master: pd.DataFrame) -> pd.DataFrame:
    """industry master에서 5개 축의 원값을 만든다. 결측 보간 없음."""
    m = master.copy()
    m.columns = [c.lstrip('﻿') for c in m.columns]
    m = m.sort_values(['industry', 'quarter']).reset_index(drop=True)
    g = m.groupby('industry')
    m['employment_lag4'] = g['employment'].shift(4)
    m['production_lag4'] = g['production'].shift(4)
    m['emp_delta'] = m['employment'] - m['employment_lag4']
    m['e_yoy'] = (m['employment'] / m['employment_lag4'] - 1) * 100
    m['p_yoy'] = (m['production'] / m['production_lag4'] - 1) * 100
    m[['e_yoy', 'p_yoy']] = m[['e_yoy', 'p_yoy']].replace([np.inf, -np.inf], np.nan)
    # 산단 10개 제조업종 합계 기준 YoY (비제조 포함 total master는 쓰지 않는다)
    tot = m.groupby('quarter')['employment'].sum(min_count=10)
    m['mfg_emp'] = m['quarter'].map(tot)
    m['mfg_emp_yoy'] = m['quarter'].map((tot / tot.shift(4) - 1) * 100)
    m['E'] = np.maximum(0.0, -m['e_yoy'])
    m['P'] = np.maximum(0.0, -m['p_yoy'])
    m['R'] = np.maximum(0.0, -(m['e_yoy'] - m['mfg_emp_yoy']))
    m['A'] = np.where(m['emp_delta'] < 0, -m['emp_delta'] / m['mfg_emp'] * 100, 0.0)
    return m


def apply_rule(df: pd.DataFrame, *, level_entry=LEVEL_ENTRY, level_up=LEVEL_UP,
               rel_entry=REL_ENTRY, rel_up=REL_UP, abs_entry=ABS_ENTRY, abs_up=ABS_UP,
               prod_support=PROD_SUPPORT, scale_min=SCALE_MIN,
               use_persist=True, use_prod=True, gate='priority_gate') -> pd.DataFrame:
    d = df.sort_values(['industry', 'quarter']).copy()
    d['datarev'] = d['e_yoy'].isna() | d['p_yoy'].isna()
    d['E_entry'] = d['E'] >= level_entry
    d['E_up'] = d['E'] >= level_up
    d['R_entry'] = d['R'] >= rel_entry
    d['R_up'] = d['R'] >= rel_up
    d['A_entry'] = d['A'] >= abs_entry
    d['A_up'] = d['A'] >= abs_up
    d['P_support'] = d['P'] >= prod_support
    d['n_entry'] = d[['E_entry', 'R_entry', 'A_entry']].sum(axis=1)
    d['n_up'] = d[['E_up', 'R_up', 'A_up']].sum(axis=1)
    d['emp_entry'] = d['n_entry'] >= 1
    d['emp_up'] = d['n_up'] >= 1
    prev = d.groupby('industry')['emp_entry'].shift(1)
    prev = prev.where(prev.notna(), False).astype(bool)
    d['persist'] = d['emp_entry'] & prev
    d['scale_ok'] = d['employment'] >= scale_min

    stages, reasons = [], []
    for r in d.itertuples(index=False):
        if r.datarev:
            stages.append('자료확인'); reasons.append('YoY 계산 불가(기준분기 결측)'); continue
        support = (bool(r.P_support) if use_prod else False) or (bool(r.persist) if use_persist else False)
        pri = bool(r.emp_up) and support
        if gate == 'priority_gate' and not bool(r.scale_ok):
            pri = False
        if gate == 'hard' and not bool(r.scale_ok):
            stages.append('규모미달'); reasons.append('고용 %d인 < %d인' % (r.employment, scale_min)); continue
        why = []
        if r.E_up: why.append('고용감소 %.1f%%(상위경계 %.0f%% 통과)' % (r.E, level_up))
        elif r.E_entry: why.append('고용감소 %.1f%%(진입경계 %.0f%% 통과)' % (r.E, level_entry))
        if r.R_up: why.append('산단평균 대비 %.1f%%p 열위(상위경계 통과)' % r.R)
        elif r.R_entry: why.append('산단평균 대비 %.1f%%p 열위(진입경계 통과)' % r.R)
        if r.A_up: why.append('산단 제조업 고용의 %.2f%% 감소(상위경계 %.1f%% 통과)' % (r.A, abs_up))
        elif r.A_entry: why.append('산단 제조업 고용의 %.2f%% 감소(진입경계 %.1f%% 통과)' % (r.A, abs_entry))
        if pri:
            sup = []
            if use_prod and r.P_support: sup.append('생산 %.1f%% 감소' % r.P)
            if use_persist and r.persist: sup.append('직전 분기에도 진입신호(지속)')
            stages.append('우선점검'); reasons.append(' · '.join(why) + ' → 보강: ' + ' / '.join(sup))
        elif r.emp_entry:
            tail = ''
            if bool(r.emp_up) and gate == 'priority_gate' and not bool(r.scale_ok):
                tail = ' [상위경계 통과했으나 고용 %d인 < %d인으로 우선점검 제외]' % (r.employment, scale_min)
            elif bool(r.emp_up) and not support:
                tail = ' [상위경계 통과했으나 생산 보강·지속 신호 없음]'
            stages.append('추가확인'); reasons.append(' · '.join(why) + tail)
        else:
            note = '고용 축 진입신호 없음'
            if r.P_support: note += ' (생산 %.1f%% 단독 감소 — 확인질문에 반영)' % r.P
            stages.append('관찰'); reasons.append(note)
    d['stage'] = stages
    d['stage_reason'] = reasons
    d['prod_only_decline'] = (~d['emp_entry']) & d['P_support'] & (~d['datarev'])
    return d


def add_routing(d: pd.DataFrame) -> pd.DataFrame:
    """Q1=확인질문·담당기능, Q2=같은 단계 내 처리순서."""
    d = d.copy()
    st = d['state'].fillna('INVALID').astype(str)
    d['check_question'] = st.map(Q1_QUESTIONS).fillna(Q1_QUESTIONS['INVALID'])
    d['first_owner'] = st.map(Q1_OWNER).fillna(Q1_OWNER['INVALID'])
    order = {'우선점검': 0, '추가확인': 1, '관찰': 2, '자료확인': 3, '규모미달': 4}
    d['_o'] = d['stage'].map(order)
    d['_loss'] = np.where(d['emp_delta'] < 0, -d['emp_delta'], 0.0)
    d = d.sort_values(['quarter', '_o', '_loss'], ascending=[True, True, False])
    d['rank_in_stage'] = d.groupby(['quarter', 'stage']).cumcount() + 1
    d['scale_flag'] = np.where(d['employment'] >= SCALE_MIN, '', '소규모(300인 미만)')
    return d.drop(columns=['_o', '_loss'])
