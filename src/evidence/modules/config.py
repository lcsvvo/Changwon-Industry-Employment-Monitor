# -*- coding: utf-8 -*-
"""해석층(context layer) 설정.

이 층은 Triage 판정단계를 바꾸지 않는다.
여기 있는 경계값 중 어느 것도 `src/triage/triage_rule.py`의 E/R/A/P·규모 게이트에
영향을 주지 않으며, 판정 결과(stage)를 재계산하거나 덮어쓰지 않는다.

경계값의 성격
    아래 baseline 경계는 전부 OWN(프로젝트 운영규칙)이다. 법령·고시에 대응하는
    조문이 없으며, 성능에 맞춰 고른 값도 아니다. 값을 바꿨을 때 신호가 얼마나
    흔들리는지 확인하기 위한 민감도 격자를 함께 둔다.
"""
from __future__ import annotations

WINDOW = ("2022Q1", "2026Q2")
INDUSTRIES = ["음식료", "섬유의복", "목재종이", "석유화학", "비금속",
              "철강", "기계", "전기전자", "운송장비", "기타"]

# ---------------------------------------------------------------- 확인신호 경계
# 모두 OWN. '좋은 값'을 고르기 위한 것이 아니라 흔들림을 재기 위한 기준선이다.
FIRMS_OP_DECLINE = -3.0        # 가동업체수 YoY (%)
OP_RATE_DECLINE = -3.0         # 가동률 YoY (%)
REAL_PROD_DECLINE = -5.0       # PPI 조정 생산 YoY (%)
PROD_MAINTAINED = 0.0          # 생산유지 판단 경계 (명목·조정 생산 YoY >= 0)
EMP_DECLINE_FOR_PATTERN = -1.0 # 생산유지·고용감소 패턴의 고용 YoY 경계

SENSITIVITY_GRID = {
    "firms_op_decline_signal": [-2.0, -3.0, -5.0],
    "operating_rate_decline_signal": [-2.0, -3.0, -5.0],
    "ppi_adjusted_production_decline_signal": [-3.0, -5.0, -7.0],
}

# ---------------------------------------------------------------- 소규모 트랙
# Triage 의 300인 게이트를 그대로 읽어온다. 여기서 재정의하지 않는다.
SMALL_FIRMS_OP_BASE = 20       # 가동업체수가 이 이하면 비율 변동이 과대해진다(OWN)
SMALL_INDUSTRY_NOTE = (
    "소규모 집계 트랙은 업종을 배제하는 장치가 아니라, 분모가 작아 비율 변동이 "
    "커지는 집계군을 별도 방식으로 읽기 위한 표시다.")

# ---------------------------------------------------------------- PPI 매핑 등급
# data/processed/ppi/ppi_industry_mapping_resolved.csv 의 grade 를 그대로 쓴다.
#   A = 비교적 직접 매핑 / B = 넓은 범주 매핑 / C = 복수 후보(밴드로만) / D = 사용불가
PPI_GRADE_SINGLE_VALUE_OK = ("A", "B")
PPI_GRADE_BAND_ONLY = ("C",)
PPI_GRADE_UNUSABLE = ("D",)

# ---------------------------------------------------------------- 자료 정의 단절
# 가동률은 2024Q2 부터 공표 정의가 바뀐다(월별 단순평균 근사 → 분기 공식값).
# 두 정의가 섞인 YoY 는 값으로 쓰되 반드시 플래그를 함께 전달한다.
OP_RATE_DEFINITION_BREAK_QUARTER = "2024Q2"
