# -*- coding: utf-8 -*-
"""창원국가산단 EDA 재사용 모듈.

notebooks/02_eda.ipynb에서 반복 사용하는 계산·시각화 로직을 그대로 옮긴 패키지다.
계산식·분석 기준·threshold·결측 처리·업종 선택 기준은 노트북과 동일하며,
노트북은 이 함수들을 호출해 분석 흐름과 결과 설명만 담당한다.

모듈 구성
    config     경로·배색·분석 설정값 (Section 0 설정 블록)
    panel      데이터 적재·공통 기준·검산·가산성 (Section 0)
    explore    분석 대상 요약·총량/업종 지수·YoY 분포·생산고용 관계 (Section 1)
    q1_state   최신분기 국면·국면 격자·방향 비교·threshold 민감도 (Section 2)
    q2_scale   고용 증감 규모·분기별 구성·상세표시 업종 선정 (Section 3)
    q3_time    현재 지속기간·최장 지속기간·전환행렬 (Section 4)
    aux_firms  가동률·업체수·고용증감 산술분해 (Section 5)
    ppi        PPI 후보 매핑·조정식·민감도 (Section 6)
    eis        EIS 방향 비교 (Section 6)
    cards      업종별 진단카드·최종 요약·결과 저장 (Section 7·8)
    plots      노트북의 그림을 그대로 옮긴 시각화 함수
"""
from . import config, panel, explore, q1_state, q2_scale, q3_time, aux_firms, ppi, eis, cards, plots

__all__ = ['config', 'panel', 'explore', 'q1_state', 'q2_scale', 'q3_time',
           'aux_firms', 'ppi', 'eis', 'cards', 'plots']
