# Model Roles

| Component | Role | Source |
|---|---|---|
| Q1–Q3 | 생산, 고용 방향과 규모, 지속과 전환 설명 | `src/core/` |
| Triage | 관찰, 추가확인, 우선점검의 주 판정 규칙 | `src/triage/` |
| ELECTRE TRI-B / SMAA-TRI | 추가확인 사례의 선택적 재검토와 분류 안정성 비교 | `src/electre/`, `logs/experiments/electre_mrsort/src/model/` |
| 외부근거, RAG | 현장 확인 질문과 지원제도 탐색 | `src/evidence/`, `src/policy/`, `src/copilot/` |

- **단계 유지**: 보조 모형과 외부근거가 원 Triage 단계를 변경하지 않음.
- **서열 구분**: Q1의 S1–S4는 생산, 고용 방향의 조합이며 위험 순위가 아님.
- **조건**: ELECTRE/SMAA 결과는 지표, 가중치, 경계와 표집가정에 조건부. 범주 수용도를 실제 위기확률로 해석할 수 없음.
- **민감성**: Triage의 규모 지표, 300인 조건, 반복신호, 결측 처리에 대한 비교는 별도 규칙 민감성 분석.
- **저장 근거**: [Notebook 04](../notebooks/04_model_evolution_and_experiments.ipynb), [최종 재검토 결과](../outputs/final_model/03_electre_smaa/).
