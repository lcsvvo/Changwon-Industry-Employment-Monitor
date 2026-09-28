# 교수 피드백 반영 검증 로그

자동검증일: 2026-09-28

| 구분 | 상태 | 어떻게 수정했는가 | 검증 근거 |
|---|---|---|---|
| 1. 목재·종이 급변 QA | PASS | 분포기반 QA·원자료 추적표에 더해, 급변 분기를 분리한 YoY 분해로 2025년 S1 기저효과와 2022Q4 수준하락 효과를 수치화 | qa_level_shift_cases.csv; wood_paper_source_audit.csv; wood_paper_level_shift_decomposition.csv |
| 2. 기계업종 기저효과 | PASS | YoY·QoQ·2023년 이후 고점을 병기하고 2025Q2 고기저 여부를 계산 | machine_yoy_qoq_interpretation.csv |
| 3. 목재·종이 경계 민감도 | PASS | 48명/47명 감소와 E 상위경계 여유를 인원으로 제시하고, 규모별 비율경계 인원 민감도로 규모게이트 근거를 보강 | wood_paper_boundary_margin.csv; ratio_boundary_headcount_summary.csv; ratio_boundary_headcount_latest.csv |
| 4. 시점분리 검증 | PASS | 검증 결과를 본론(2-3)으로 옮겨 추가 위축 예측용이 아님을 설명하고, 신호 이후 회복률·비교기준 고점·창원상의 동시점 대조를 보강 | signal_followup_summary.csv; priority_base_peak_check.csv; cci_concurrent_check.csv; external_contemporaneous_cases.csv |
| 5. 보고서·그림 | PASS | Q1·Q2·기준선·단계격자와 원본 Streamlit 화면 2장을 배치하고 해석 문단을 추가 | 교수피드백반영본.docx 그림 1~7 및 본문 |
| 6. 서술·용어 | PASS | 최초 용어를 풀어 쓰고 단계명을 우선점검·추가확인·관찰로 통일, 해석범위 부정 서술은 4-1 한계 절로 모음 | 보고서; src/app/view_models.py |
| 7. 선별효과 | PASS | 2/10 선별과 고용비중 51.56%를 구분하고 80% 업무절감 표현을 제거 | 보고서 선별효과 문단 |
| 8. 검토 패키지·재현성 | PASS | 저장 출력 확인용 패키지와 전체 재실행 저장소를 구분하고, src가 없으면 노트북 첫 셀이 재실행 위치를 안내하고 멈춤 | 00_개요.txt; build_review_package.py; 최종 노트북 17.8 |
| 9. Streamlit | PASS | 업종 표식 도형(●▲■×, 회색 테두리)+단계색·범례, 선택 카드 버튼 강조, Q1~Q3 3칸, 추이 띠 빗금/점선 구분, 채용카드 포함관계 순서, 섹션 바로가기 | src/app/main.py; src/app/ui.py; src/app/view_models.py; handoff_cards_latest.csv |

미완료: 목재·종이 2025Q1 급증의 실제 원인(기업 증원·분류/집계범위 변경)과 2026Q2 감소의 기업별 집중 여부는 공개 업종 집계표로 확인할 수 없다. 원자료 수치 대조, 수준변화 QA, 이후 분기 지속 여부와 기저효과 해석은 완료했지만 원인 규명 완료로 표시하지 않는다.
