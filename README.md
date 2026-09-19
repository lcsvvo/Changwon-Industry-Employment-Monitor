# 창원국가산단 산업·고용 전환진단

창원국가산단의 KICOX 생산·고용을 Q1 상태, Q2 규모, Q3 시간축으로 읽고, Triage로 관찰·추가확인·우선점검을 구분하는 최종 저장소입니다. `추가확인` 35건에만 ELECTRE TRI-B와 SMAA-TRI를 보조 적용하며, 외부자료는 판정 이후의 확인근거로만 사용합니다.

```text
KICOX 생산·고용 → Q1 → Q2 → Q3 → Triage
→ 추가확인만 ELECTRE TRI-B → SMAA-TRI
→ External Evidence → Human Review / Handoff → 기존 지원체계 Routing
```

## 어디를 보면 되는가

- `data/raw/`: 출처별 원자료. 파이프라인은 수정하지 않습니다.
- `data/processed/`: 출처별 가공자료와 `final_model/` 재실행 기준자료입니다.
- `src/`: 최종모형 production 코드만 있습니다.
- `notebooks/`: 최종 데이터 준비·CORE·결과 노트북입니다.
- `outputs/final_model/`: 최종 결과의 유일한 위치입니다.
- `reports/`: 최종 방법론·데이터 역할·결과·QA 문서입니다.
- `logs/experiments/`: 과거 후보모형과 실험입니다.
- `logs/validation/`: 강건성·재현성·민감도·과거 QA입니다.

핵심 결과는 [최종 방법론](reports/final_methodology.md), [Triage 180행](outputs/final_model/02_triage/tables/triage_panel.csv), [선택적 ELECTRE/SMAA 35행](outputs/final_model/03_electre_smaa/tables/electre_smaa_review_cases.csv), [외부근거 요약](outputs/final_model/04_external_evidence/external_evidence_summary.csv), [인계 trace](outputs/final_model/05_handoff/tables/explanation_trace.csv)에서 확인할 수 있습니다.

현재 결과는 180행이며 관찰 128, 추가확인 35, 우선점검 17입니다. 선택적 ELECTRE 결과는 OBSERVE 2, CHECK 9, PRIORITY 20, UNDETERMINED 4이고 원 Triage 단계를 자동 변경하지 않습니다.

## 실행

Python 환경에 `pip install -r requirements.txt`를 실행한 뒤 저장소 루트에서 다음 명령을 사용합니다.

```powershell
python src/pipeline/run_final_pipeline.py
```

개별 단계와 산출 위치는 [실행 안내](outputs/final_model/RUNBOOK.md)에 정리되어 있습니다. 외부 API 수집은 최종 오프라인 파이프라인과 분리되어 있으며, 필요할 때만 `src/evidence/collection/`의 수집기를 실행합니다.

과거 전체 180행 ELECTRE, hybrid, rolling backtest, robustness, reproducibility 결과는 최종 산출물이 아닙니다. 필요할 때만 [logs 안내](logs/README.md)를 확인하세요.
