# Final model outputs

이 디렉터리는 최종 결과의 유일한 위치입니다.

1. `01_core`: Q1 상태, Q2 규모, Q3 시간축
2. `02_triage`: 관찰·추가확인·우선점검
3. `03_electre_smaa`: 추가확인 35건의 선택적 재검토와 안정성
4. `04_external_evidence`: 출처별 확인근거
5. `05_handoff`: 설명 trace, 진단카드, routing
6. `06_report_assets`: 최종 보고서 표·그림·QA와 단일 `triage_electre_experiments.html`

Notebook별 HTML은 만들지 않습니다. Jupyter Notebook은 Markdown 중심으로 읽고, 별도 HTML은 Triage에서 선택적 ELECTRE/SMAA로 이어지는 흐름과 실제 실험 기록만 담습니다.

과거 실험과 검증 산출물은 `logs/experiments/`와 `logs/validation/`에 있습니다.
