# KEPCO 법정동×KSIC 전력자료 QA 보고서

## 1. 한 줄 결론

법정동×KSIC 자료는 기존 businessType보다 업종 정의와 공간단위가 개선되고 10업종을 모두 관측하지만, 비식별 때문에 업종 합계 기준 COMPLETE 분기가 없어 현재는 맥락자료로만 적합하다.

최종 후보 지위: **CONTEXT_ONLY**

## 2. 로컬 원자료 inventory

- 파일 수: 35개
- 범위 내 읽기 성공: 21개 / 실패: -54개
- 2021 파일: 사용자 지시에 따라 범위 제외·미검사
- 손상·비정상 파일: changwon_business_type_power_monthly.json, changwon_custnum_change_monthly.json, changwon_industry_type_power_monthly.json, collection_status.json, kepco_open_api_manual.json, portal_verification_20260919.json, request_failures.json, changwon_business_type_power_monthly.csv, changwon_custnum_change_monthly.csv, changwon_industry_type_power_monthly.csv, kepco_open_api_manual.pptx, kepco_raw_responses.json
- 동일 SHA-256 중복 파일: 2개
- 헤더-값 스키마 이상 및 처리: 2022-06|2022-07|2022-08|2023-10|2023-11|2023-12|2024-01|2024-02|2024-03 (7,737행): swapped by code-value shape; raw files unchanged
- 상세: `raw_file_inventory.csv`, `raw_sheet_inventory.csv`

## 3. 수집 가능한 실제 기간

- 최초월: 2022-04
- 최종월: 2026-03
- expected / available / missing: 48 / 48 / 0
- 누락월: 없음
- 원자료 중복월(정상 파일 우선·행수 기준으로 1개 선택): 2022-04, 2022-05, 2026-01, 2026-02, 2026-03
- 최종 월 패널은 월별 source를 하나만 선택했으며, 자료가 없는 월을 0으로 만들지 않았다.

## 4. 18개 제조업 집적 법정동 패널

이 공간범위는 **창원 제조업 집적 법정동 proxy**이며 창원국가산단 경계가 아니다.

- 월 패널: 41,508행
- 분기 패널: 13,869행
- 비식별률: 40.47%
- 일반 결측률(비식별 제외): 0.00%
- 관측 법정동: 18/18
- 분기 `power_usage`는 3개월이 모두 숫자이고 비식별·결측이 없을 때만 합계했다.
- `customer_count`는 합계하지 않고 분기말값과 3개월 평균을 분리했다.

## 5. KICOX 10업종 매핑

| KICOX 업종 | 대응 KSIC(등급) | 종합 grade | 기간 | COMPLETE 분기 | 비식별률 | 2026Q2 사용가능 |
|---|---|---|---|---:|---:|---|
| 음식료 | 10(A)|11(A) | A | 2022-04~2026-03 | 0 | 51.52% | 불가 |
| 섬유의복 | 13(A)|14(A)|15(B) | B | 2022-04~2026-03 | 0 | 88.51% | 불가 |
| 목재종이 | 16(A)|17(A)|18(C) | C | 2022-04~2026-03 | 0 | 50.28% | 불가 |
| 석유화학 | 19(A)|20(A)|21(C)|22(B) | C | 2022-04~2026-03 | 0 | 48.35% | 불가 |
| 비금속 | 23(A) | A | 2022-04~2026-03 | 0 | 54.34% | 불가 |
| 철강 | 24(B) | B | 2022-04~2026-03 | 0 | 29.41% | 불가 |
| 기계 | 25(C)|29(A) | C | 2022-04~2026-03 | 0 | 3.41% | 불가 |
| 전기전자 | 26(A)|27(B)|28(A) | B | 2022-04~2026-03 | 0 | 22.92% | 불가 |
| 운송장비 | 30(A)|31(A) | A | 2022-04~2026-03 | 0 | 20.11% | 불가 |
| 기타 | 32(C)|33(C) | C | 2022-04~2026-03 | 0 | 52.93% | 불가 |

`COMPLETE 분기`는 해당 KICOX 업종의 관측 행에서 세 달 모두 전력값이 숫자이고 비식별·일반결측이 없는 분기다. 구조적으로 존재하지 않는 법정동×업종 조합을 0으로 보충하지 않았다.

## 6. businessType 대비 개선점/한계

| 비교축 | 법정동×KSIC | 기존 businessType | 판단 |
|---|---|---|---|
| 업종 정의 | 공식 KSIC 중분류 코드 | KEPCO 비공식 businessType 명칭 | 법정동×KSIC 개선 |
| KICOX 매핑 신뢰도 | 기존 코드 crosswalk A/B/C/D 유지; fuzzy matching 없음 | 업종명→KSIC→KICOX 간접 대응 | 법정동×KSIC 개선 |
| 공간단위 | 창원 제조업 집적 법정동 proxy 18개 | 기존 창원시 집계 | 법정동×KSIC가 세밀하지만 산단 경계는 아님 |
| 기간 coverage | 2022-04~2026-03 | 2021-01~2026-06 | 서로 기간·자료계열이 다름 |
| 비식별률 | 40.4717% | 별도 suppression_flag 없음 | 신규 자료는 비식별을 명시 |
| 결측률 | 0.0000% | 0.0000% | 정의 차이로 단순 우열 해석 금지 |
| 10업종 coverage | 10/10 | 10/10 | 신규 자료는 코드별 근거 추적 가능 |

## 7. 신규 전력자료의 최종 후보 지위

**CONTEXT_ONLY**

KSIC 코드와 공간단위가 명확해 기존 businessType보다 매핑·공간 해석은 개선됐다. 다만 이 18개 법정동은 산단 경계가 아니고, B/C 등급 매핑·비식별·최신 분기 미확보 제약이 있어 현재 단계에서 핵심 판정기준으로 승격하지 않는다.

## 8. Triage 불변성

- 행 수: 180
- 관찰 / 추가확인 / 우선점검: 128 / 35 / 17
- decision_panel.csv SHA-256: `a328c9677d851b7b066e00eadc7ecf7fdd59f9297149dd2ea5952b4770fa3c1a`
- 작업 전후 hash 동일: 예

## 9. 남은 한계

- 2026Q2(4~6월)는 원자료가 없어 사용할 수 없다.
- 비식별값은 0이나 추정치로 보완하지 않았으므로 업종 합계가 하한처럼 보일 수 있다.
- KSIC 18·21·25·32·33 등 C등급은 부분 대응 또는 복수 범위여서 단정형 업종 신호에 부적합하다.
- 법정동 proxy는 제조업 집적지역을 나타낼 뿐 창원국가산단 입주기업 모집단과 일치하지 않는다.
- 원자료에 법정동 코드가 없어 명칭 기반의 엄격한 정규화만 사용했다.

## 10. 생성·수정 파일

- `data/processed/kepco/legal_dong_ksic_monthly_panel.csv`
- `data/processed/kepco/legal_dong_ksic_quarterly_panel.csv`
- `outputs/final_model/04_external_evidence/kepco/quality/` 아래 inventory, coverage, mapping, 비식별률, QA, metadata, 본 보고서
- `src/evidence/build_kepco_legal_dong_panel.py`

QA 실패 항목: 없음
