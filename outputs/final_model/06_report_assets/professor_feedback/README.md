# Review Results

점검 규칙과 결과 해석을 보완하는 분석표, 그림. 원 Triage 단계는 유지.

| Output | Content |
|---|---|
| `tables/machine_yoy_qoq_interpretation.csv` | 기계 업종의 전년동기 대비, 직전 분기 대비 변화 |
| `tables/wood_paper_boundary_margin.csv` | 목재종이 고용감소율 경계와 인원 차이 |
| `tables/priority_base_peak_check.csv` | 우선점검 사례의 비교시점 고점 여부 |
| `tables/qa_level_shift_cases.csv` | 원자료 수준 급변과 판정 근거 |
| `tables/validation_model_comparison.csv` | 저장된 후속성과 비교와 평가 조건 |
| `tables/press_concurrent_cases.csv` | 보도, 공식자료의 동시기 사례와 모집단 차이 |
| `figures/` | Triage 단계 격자, 운영경계 민감도 |

- **기계 2026Q2**: 고용 전년동기 대비 3,979명 감소, 직전 분기 대비 104명 감소.
- **목재종이 2026Q2**: 476명 중 48명 감소 시 E=10.084%, 47명 감소 시 9.874%. 1명 차이로 10% 경계 통과 여부가 달라짐.
- **후속성과**: 2분기 주평가 균형정확도 Triage 0.473, ELECTRE 0.445. 정책효과나 일반적 우월성의 근거가 아님.
- **문서**: [Notebook 07](../../../../notebooks/07_professor_review_master.ipynb)에 보완 결과 수록.
