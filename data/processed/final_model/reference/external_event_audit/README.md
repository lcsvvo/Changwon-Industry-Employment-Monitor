# 외부사건 검증가능성 감사자료 (external_event_audit)

## 0. 이 자료의 성격 — 반드시 먼저 읽을 것

**이 자료는 창원국가산단 업종×분기의 실제 위기 여부를 나타내는 정답라벨 데이터셋이 아니다.**
공개자료를 이용해 독립 외부사건 검증이 가능한지를 조사한 감사자료이며,
**현재 확정적으로 `label_usable=True`인 사건은 0건이다.**
**따라서 모형의 precision, recall, specificity 등의 정량 성능평가에 사용할 수 없다.**

다음 네 가지를 특히 혼동하지 말 것.

1. **기업 사건 ≠ 업종 전체 사건.**
   모든 확인 사건은 기업 단위(`analysis_unit=firm`)다. 업종 단위 라벨로 승격하려면
   해당 기업의 업종 내 생산·고용 비중이 필요하며, 현재 미확보다.
2. **`no_confirmed_event_found` ≠ 정상.**
   이는 결측(unknown)이다. 음성(정상)으로 코딩하면 특이도가 인위적으로 100%에 수렴한다.
3. **counter evidence ≠ 업종 반례.**
   두산에너빌리티·한화에어로스페이스의 개선 사건은 기업 단위다.
   같은 시기 기계 업종 전체는 2026Q1 기준 생산 -8.7%, 수출 -11.1%, 고용 -2.6%로 감소했다.
   기업 개선과 업종 악화는 동시에 성립하며, 어느 한쪽이 다른 쪽을 반증하지 않는다.
4. **창원상공회의소 / KICOX 동일계열 자료는 독립검증 근거로 사용할 수 없다.**
   창원상의 『창원지역 경제동향』의 산단 업종별 생산·고용 수치는 KICOX 원자료이며,
   본 프로젝트 모형의 입력과 동일하다. 이를 외부 검증자료로 쓰면 자기참조가 된다.

## 1. 저장 위치와 파일

- `event_panel.csv` — 사건 14건 × 28열
- `event_panel_coverage.csv` — 업종×분기 180행 × 7열
- `README.md` — 본 문서

`data/processed/final_model/reference/` 하위에 두었으나 **판정 입력데이터가 아니다.**
`src/`의 어떤 파이프라인도 이 파일을 읽지 않으며, 읽도록 연결해서는 안 된다.

## 2. 조사범위

- 기간: 2022Q1~2026Q2 (18분기, 프로젝트 분석기간과 동일)
- 공간: 창원국가산업단지 / 창원시 소재 제조업 사업장 / 창원 소재 기업의 창원 사업장
- 업종: 프로젝트 KICOX 10개 업종 — 기계, 운송장비, 전기전자, 철강, 음식료, 석유화학, 목재종이, 비금속, 섬유의복, 기타
- 조사일: 2026-09-18
- 모형(ELECTRE/MRSort, 트리아지) 결과와의 대조는 **수행하지 않았다.**

## 3. event_panel.csv 스키마 (28열)

| # | 컬럼 | 값 |
|---|---|---|
| 1 | event_id | EV-xx(악화·중립 사건), CE-xx(개선 사건) |
| 2 | industry | KICOX 10업종 / `미상` / `해당없음` / `전체` / 세미콜론 다중 |
| 3 | industry_is_kicox_class | True=프로젝트 업종체계에 직접 대응 |
| 4 | industry_mapping_uncertain | True=업종 확정 불가 |
| 5 | company_or_scope | 기업명 또는 집합 범위 |
| 6 | analysis_unit | firm / industry / region / national |
| 7 | event_date | 발생일(발표일 아님). 범위는 `/` 또는 `~` |
| 8 | event_date_precision | exact_day / week_estimated / month_end_estimated / month_range / year / year_range / multi_year |
| 9 | event_quarter | 발생분기. 범위 가능 |
| 10 | quarter_is_range | True=단일 분기로 귀속 불가 |
| 11 | event_type | 사건 유형 |
| 12 | employment_related | True / False / unknown / increase |
| 13 | production_related | True / False / unknown / circumstantial / increase |
| 14 | changwon_related | True / False / unknown |
| 15 | changwon_national_complex_related | True / False / assumed_true / unknown |
| 16 | complex_membership_verified | **전 행 False** (KICOX 입주기업 명부 미대조) |
| 17 | evidence_grade | A / B / B- / C / X |
| 18 | source_type | 출처 유형 |
| 19 | source_title | 출처 제목 |
| 20 | source_date | 기사·발표일 (event_date와 구분) |
| 21 | source_url | URL |
| 22 | direct_quote_or_fact | 원문 인용 또는 확인된 사실 |
| 23 | industry_mapping_confidence | high / medium / low / n/a |
| 24 | timing_confidence | high / medium / low / n/a |
| 25 | event_classification | core_validation_event / supplementary_event / unusable_event / counter_evidence |
| 26 | label_usable | True / provisional / False |
| 27 | label_block_reason | 라벨 사용을 막는 구체 사유 |
| 28 | notes | 비고 |

### 근거등급 정의
- **A** 정부·지자체·공공기관·기업공시·기업 공식자료에서 사건과 창원 관련성이 직접 확인
- **B** 복수의 신뢰도 높은 언론 또는 구체적 기업·공장·고용사건이 명확히 확인, 공식 1차자료는 제한적
- **B-** 사건 성격은 명확하나 단독보도 1건으로 복수출처 요건 미충족
- **C** 산업 전반 부진·전국 업황·간접 정황
- **X** 사건 존재 또는 창원 관련성 확인 불가

## 4. event_panel_coverage.csv 스키마 (7열)

| 컬럼 | 값 |
|---|---|
| industry | KICOX 10업종 |
| quarter | 2022Q1~2026Q2 (18분기) |
| external_validation_observability | `observable` / `structurally_unobservable_external` |
| label_status | `provisional_event` / `supplementary_event` / `no_confirmed_event_found` / `structurally_unobservable` / `unusable_event` |
| event_id | 해당 셀에 귀속된 악화·중립 사건 ID |
| counter_evidence_event_id | 해당 셀에 귀속된 개선 사건 ID (label_status와 독립) |
| note | 해석 주의사항 |

### `structurally_unobservable_external`의 의미
목재종이·비금속·섬유의복·기타 4개 업종 72셀이 해당한다.
**프로젝트 자체에서 관측이 불가능하다는 뜻이 아니다.** 프로젝트 패널은 이 4개 업종의
생산·고용·업체수를 모두 보유하고 있다.
의미는 **공개 KICOX 집계(창원상의 보고서 등)가 이 업종들을 '기타'로 병합해 발표하기 때문에,
독립 외부자료를 이용한 업종 단위 사건 검증이 구조적으로 어렵다**는 것이다.
또한 이 업종들은 입주업체 수가 극소(2026Q1 기준 목재종이 50, 섬유의복 10, 비금속 5, 기타 36)이며
대기업이 없어 사업장 단위 사건이 보도되지 않는다.

## 5. 분포 요약

### event_panel.csv (14건)
| event_classification | 건수 |
|---|---|
| core_validation_event | 1 |
| supplementary_event | 4 |
| unusable_event | 5 |
| counter_evidence | 4 |

| label_usable | 건수 |
|---|---|
| True | **0** |
| provisional | 1 (EV-01) |
| False | 13 |

| evidence_grade | 건수 |
|---|---|
| A | 1 (개선 사건) |
| B | 6 |
| B- | 1 |
| C | 5 |
| X | 1 |

### event_panel_coverage.csv (180셀)
| external_validation_observability | 셀 수 | 비율 |
|---|---|---|
| observable | 108 | 60.0% |
| structurally_unobservable_external | 72 | 40.0% |

| label_status | 셀 수 | 비율 |
|---|---|---|
| provisional_event | 1 | 0.6% |
| supplementary_event | 5 | 2.8% |
| unusable_event | 1 | 0.6% |
| no_confirmed_event_found | 101 | 56.1% |
| structurally_unobservable | 72 | 40.0% |

## 6. EV-01의 provisional 해제 조건

EV-01(한국GM 창원공장 조업중단, 운송장비×2022Q3)은 유일한 `core_validation_event`이나
`label_usable=provisional`이다. 다음 두 조건을 **모두** 충족해야 `True`로 승격한다.

1. KICOX 입주기업 명부로 한국지엠 창원공장의 창원국가산단 입주 확인
   → `complex_membership_verified=True`
2. 해당 기업의 운송장비 업종 내 생산·고용 비중 확보
   → 기업 단위 사건을 업종 단위 라벨로 승격할 근거

## 7. 알려진 출처자료 내부 불일치 (인용 시 반드시 명시)

창원상공회의소 『2026년 1분기 창원지역 경제동향』(자료: 한국산업단지공단) 내부 모순:

| 항목 | 동향표 | 업종별표 | 프로젝트 패널 |
|---|---|---|---|
| 2026Q1 생산(억원) | 157,499 (+4.87%) | 157,499 (+3.1%) | 156,794 |
| 2026Q1 가동업체(개) | 2,504 (-10.89%) | 2,860 (+1.8%) | 2,504 |
| 2026Q1 입주업체(개) | 3,320 | 3,320 | 2,693 |
| 2026Q1 고용(명) | 119,212 (-2.97%) | 119,212 | 114,945 |

- 동일 수치 157,499에 증감률 +4.87%와 +3.1%가 병기됨(2025Q1 150,178 대비 +4.87%가 정합).
- 가동업체 수가 같은 문서 두 표에서 2,504 vs 2,860으로 불일치.
- 입주업체 차이 627개는 업종 분류 범위 차이(창원상의 7업종 '기타' 728 vs 프로젝트 4업종 합 101).
- 창원시 전체 수출 4,194백만불(-21.2%) < 창원국가산단 수출 4,374백만불(+3.48%).
  산단은 창원시의 부분집합인데 산단 수출이 더 큼. 집계기준 차이(무역협회 통관 vs KICOX)로 추정되나 미확인.

**결론: 창원상의 보고서는 산단 업종 수치의 교차검증 자료로 사용할 수 없다.**

## 8. 자료편향

- **대기업 보도편향**: 확인된 악화 사건 5건 중 3건이 한국지엠(60%). 사건 수는 업종의 실제
  악화 강도가 아니라 업종 내 대기업 존재 여부를 측정한다.
- **업종 규모 교란**: 음식료 7개사, 비금속 5개사, 섬유의복 10개사 등은 애초에 보도 대상 기업이 없다.
- **산단 직접성**: `changwon_national_complex_related`는 대부분 `assumed_true`이며 명부 대조 전이다.
- **시점 불확실성**: 발표일 기준으로 분기를 귀속하면 악화가 1~4분기 늦게 기록되어
  모형의 조기탐지 성능을 과대평가한다. 본 패널은 발생시점 우선, 발표일은 `source_date`에 분리 기록.

## 9. 미수행 항목

- ELECTRE/MRSort·트리아지 결과와의 대조 (**의도적으로 미수행**)
- KICOX 입주기업 명부 대조
- DART 공시 원문 대조
- 고용노동부 창원지청 공고 원문 조회
