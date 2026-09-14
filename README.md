# Changwon-Industry-Employment-Monitor

창원국가산업단지의 업종별 산업 성장과 고용 변화를 분기 단위로 진단하기 위한 데이터 파이프라인.

창원국가산단의 산업 성장과 고용 변화가 함께 움직이고 있는지를 분석하고, 업종별 차이를 바탕으로 산업·기업·인력 정책의 우선 검토 대상을 제시합니다. 핵심 산출물은 업종별 산업·고용 상황을 한눈에 살펴볼 수 있는 **창원 산업·고용 국면판**입니다.

현재 단계는 **KICOX 마스터 구축 → 국면(S1~S4)·지속·전환 패널 생성 → PPI/EIS 검증 패널 생성 → EDA**까지 오프라인 파이프라인이 갖춰진 상태다. 처리 순서는 `notebooks/01_data_preprocessing.ipynb`(전처리)와 `notebooks/02_eda.ipynb`(EDA) 두 노트북으로 나뉘며, 실제 처리 로직은 전부 `src/*.py`에 있다.

## 1. 현재 목적

핵심 질문: **창원국가산단의 산업 성장과 고용 변화가 업종별로 어떻게 함께 나타나고 있는가?**

분석 흐름 (예정): 생산 변화 → 고용 변화 → 업종별 차이 → 최근 산업·고용 국면 → 방향의 지속성·안정성 검토 → 가동률·입주업체·가동업체 보조진단 → EDA 결과를 본 뒤 정책 연결 방향 결정.

기본 분석단위: **창원국가산단 × 업종 × 분기**

## 2. 사용 데이터 — KICOX 5개 지표

한국산업단지공단(KICOX) 「국가산업단지 산업동향」 통계, 공공데이터포털 제공.

| 지표 | 데이터셋 ID (업종별) | 데이터셋 ID (단지 전체) | 기준 |
| --- | --- | --- | --- |
| 생산실적 | 15085898 | 15085891 | 당분기 3개월 생산실적 합계 |
| 고용현황 | 15085897 | 15085890 | 당분기말 기준 |
| 가동률 | 15085895 | 15085889 | 생산액 ÷ 최대생산능력 × 100 |
| 입주업체 | 15085901 | 15085894 | 당분기말 기준 |
| 가동업체 | 15085896 | — | 당분기말 기준 |

가동률은 `가동업체 ÷ 입주업체`가 **아니다**.

## 3. KICOX 업종분류와 KSIC의 관계

KICOX 업종분류는 KSIC를 그대로 쓰지 않고, **한국표준산업분류(KSIC) 중분류를 토대로 산업단지 특성에 맞게 재분류**한 체계다. 10개 업종: 음식료, 섬유의복, 목재종이, 석유화학, 비금속, 철강, 기계, 전기전자, 운송장비, 기타.

따라서 다음과 같은 동일시는 금지한다.

- 기계 ≠ 방산, 기계 ≠ SMR
- 운송장비 ≠ 방산
- 전기전자 ≠ 의료기기

## 4. 원자료 확보기간과 공표체계 변경

```
2018-01 ~ 2024-03 : 월별 공표
2024Q2 이후       : 공식 분기별 공표
```

코드에서는 파일 개수로 추정하지 않고 `QUARTERLY_FROM = "2024Q2"` 상수로 전환시점을 명시 관리한다.

- flow 지표(생산): 월별 구간에서 3개월 합산
- stock 지표(고용·입주·가동업체): 3·6·9·12월 값 사용

확보 기간: **2018Q1 ~ 2026Q2 (34개 분기, 누락 없음)**

## 5. 데이터 source priority

```
KICOX 연간보정본 > 수정·재공시본 > 공공데이터포털 과거파일
```

raw 원본은 수정하지 않고, 최종 master 생성 시점에만 우선순위를 적용한다.

확보한 연간보정 자료 2구간:

- `data/raw/kicox/revision/2022_10_2025_Q1/xlsx/` — 2022년 10월 ~ 2025년 1분기 (22개)
- `data/raw/kicox/revision/2026_Q1_Q2/xlsx/` — 2026Q1 ~ 2026Q2 (2개)

공공데이터포털 원자료(9개 데이터셋, 총 498개 CSV)는 `data/raw/kicox/core/`에 있다.

출처 구성 (34분기 기준): `data_portal_monthly` 19분기 / `data_portal_quarterly` 3분기 / `kicox_annual_revision` 12분기.

출처 추적 컬럼: `{지표}_source`, `{지표}_is_revised`, `{지표}_masked`, `{지표}_invalid_source`, `{지표}_note`

## 6. 알려진 데이터 이슈와 처리 방식

### 2023Q4 업종별 생산 = 결측

2023년 12월 창원 업종별 생산은 연간보정본에서도 `X`(조사대상 소수 보호)다. 따라서 **2023Q4 업종별 production은 NaN**으로 유지한다.

금지 사항: `X → 0` 치환, 전체 생산의 업종별 비중 배분, 보간, 임의 추정.

**단지 전체 2023Q4 생산은 정상 존재**(146,848억원, 연간보정본)하므로 전체 산단 시계열에서는 사용 가능하다. 전체와 업종별을 반드시 구분한다.

### 2024Q3 업종별 고용 = 연간보정본으로 복구

공공데이터포털의 2024Q3 업종별 고용 파일은 2024Q1 파일과 동일한 잘못된 파일이었다(업종별 합계 117,705 ≠ 단지 전체 120,217, 원파일 중복). 파이프라인이 이를 자동 무효 판정하고 연간보정본으로 대체한다. 최종 master의 2024Q3 `employment_source = kicox_annual_revision`, 단지 전체 고용 **120,217명**.

### 2020Q3 단지 전체 생산 원자료 불일치

`production_total 20200930`은 3중 대조에서 불일치(121,973 vs 합의값 35,943)로 무효 판정되어 다른 출처로 대체됐다.

### 업종별 고용 합계 ≠ 단지 전체 고용 — 차이는 비제조 고용

업종별 10개 합계와 `employment_total`은 일치하지 않는다. 반면 **생산은 업종별 합계와 전체가 정확히 일치**한다(상대오차 최대 0.003%, 반올림 수준).

이 비대칭은 KICOX 원표의 구조에서 나온다.

| 원표 | 열 구성 | 계 |
| --- | --- | --- |
| 표5 업종별 생산 | 10개 제조업 + 계 | 10개 제조업 합계 |
| 표9 업종별 고용 | 10개 제조업 + **비제조** + 계 | 10개 제조업 합계 + 비제조 |

즉 **단지 전체 고용에는 비제조 고용이 포함되고, 생산에는 포함되지 않는다.** industry master는 생산자료와 결합 가능한 10개 제조업만 대상으로 하므로, 두 합계의 차이는 정확히 비제조 고용이다.

연간보정본 24개 시점 중 고용이 유효한 분기말 12개 시점 전부에서 **오차 0으로 검증**했다(`logs/preprocessing/nonmfg_check.csv`).

```
2026Q2  제조업 114,830 + 비제조 4,851 = 전체 119,681
2024Q3  제조업 116,432 + 비제조 3,785 = 전체 120,217
```

비제조 고용은 최근으로 올수록 커진다(전 기간 579~4,851명). 따라서 산단 전체 고용 추이를 제조업 고용 추이로 읽으면 안 되고, 그 반대도 안 된다. 두 master를 목적에 맞게 구분해 쓴다.

### 섬유의복 업종의 초기 구간

창원 섬유의복은 2018Q1~2020Q4 생산이 **원자료에 0으로 공표**되어 있다(공백이 아니라 숫자 0). 2018Q1~2020Q3은 가동률도 공표되지 않았다. 파싱 오류가 아니라 해당 기간 창원 섬유의복의 활동이 사실상 없었던 것으로, 값을 채우거나 고치지 않는다.

이 때문에 2021Q1~2021Q4의 YoY는 기준값이 0이 되어 산출되지 않는다(§10 참조). 섬유의복은 최근 4분기 생산비중 0.0%로 핵심 분석 대상이 아니다.

### 업종 재분류 주의시점

KICOX 조사개요상 다음 시점에 표본업체 교체·일부 표본업체 업종 재분류로 실적변동이 발생했다.

```
2018년 10월  → classification_break 플래그: 2018Q4
2020년 9월   → classification_break 플래그: 2020Q3
```

창원에서는 두산에너빌리티(구 두산중공업)가 **기계 → 철강**으로 재분류된 사례가 확인된다.

→ 장기 업종별 변화 전체를 실제 고용 이동이나 산업구조 변화로 해석하면 안 된다.

## 7. 최신 공통 시점

```
latest_common_quarter = 2026Q2
```

생산·고용·가동률·입주업체·가동업체 5개 지표 모두 2026Q2까지 업종별 값이 존재한다. 코드가 자동 판정하며 `logs/preprocessing/latest_points.json`에 기록된다.

## 8. 산출물 구조

```
data/processed/
├─ kicox/
│  ├─ changwon_industry_master.csv          340행 = 34분기(2018Q1~2026Q2) × 10업종
│  ├─ changwon_total_master.csv              34행 = 34분기 × 창원국가산단 전체
│  ├─ changwon_state_panel.csv              180행 = 18분기(본분석 2022Q1~2026Q2) × 10업종, 국면·run·transition 포함
│  ├─ changwon_state_reference_panel.csv    340행 = 참고기간 전체(2018Q1~2026Q2) 국면 패널
│  ├─ changwon_state_sensitivity_panel.csv  540행 = 본분석기간 × threshold(0.5/1/2)
│  ├─ quality_report.json                    국면·run·transition 자체 검증 리포트
│  └─ _previous/                             이전 실행 산출물 백업 (재실행 시 자동 이동, 삭제하지 않음)
├─ ppi/
│  ├─ ppi_validation_panel.csv               PPI 총지수(전국) 분기 평균 검증 패널
│  └─ ppi_industry_mapping_candidates.csv    전처리 단계 업종 대분류 매핑 후보 (전부 confirmed=False)
└─ eis/
   └─ eis_validation_panel.csv               EIS 창원시 고용보험 피보험자 (2022Q1~2026Q2)
```

- **industry/total master**: 생산·고용 원자료 기반 마스터. QA와 state panel 생성의 입력
- **state panel**: 국면(S1~S4/N/INVALID)·run(지속)·transition(전환)·recent4 카운트가 담긴 핵심 분석 패널
- **ppi/eis validation panel**: KICOX core에 병합하지 않는 별도 검증 자료 (§12 참고)
- **PPI 업종별 후보 민감도**: 위 패널과 별도로 `notebooks/02_eda.ipynb` Section 6에서 수행하며 결과는 `outputs/tables/PPI_*.csv`에 저장한다 (§12 참고)

## 9. 가동률 official / approx

| 컬럼 | 정의 | 분기 수 |
| --- | --- | --- |
| `op_rate_official` | 2024Q2 이후 KICOX 공식 분기값 | 9 (2024Q2~2026Q2) |
| `op_rate_approx` | 그 이전 월별 자료를 분기 참고용으로 변환한 값 | 25 (2018Q1~2024Q1) |

월별 가동률을 분기로 변환하는 공식 기준은 확인되지 않았다. 따라서 **핵심 분석에는 `op_rate_official`만 사용**하고 `approx`는 참고용으로만 쓴다. 두 컬럼이 동시에 채워지는 분기는 없다.

## 10. YoY 정의와 결측 처리

- 정의: 전년동기 대비 변화율 = `(당분기 / 4분기 전 - 1) × 100`
- `pct_change(4, fill_method=None)`을 **명시**한다. pandas 2.x의 기본값 `fill_method='pad'`는 결측을 앞 값으로 채워 2023Q4·2024Q4처럼 기준값이 없는 분기에서도 YoY를 만들어낸다.
- 추가 방어: 당분기 값 또는 4분기 전 기준값이 결측이면 YoY를 무조건 NaN 처리한다.
- `inf` / `-inf`는 NaN 처리한다(고용 0 → 양수 구간에서 발생).
- **결측 보간 금지.**

결과: 10개 업종 모두 4분면 산출 가능한 분기 **16개**

```
2022Q1~2022Q4, 2023Q1~2023Q3, 2024Q1~2024Q3, 2025Q1~2025Q4, 2026Q1, 2026Q2
```

제외 사유

- 2018Q1~2020Q4: 기준분기 부재 또는 초기 구간
- 2021Q1~2021Q4: 섬유의복 업종의 2020년 생산·고용 0 → YoY가 inf
- **2023Q4**: 업종별 production 자체가 결측
- **2024Q4**: 기준분기인 2023Q4 production이 결측

## 11. 국면(S1~S4)·지속(run)·전환(transition)·sensitivity

`src/build_kicox_analysis_panel.py`가 industry master로부터 국면 패널을 만든다.

**본분석 국면**: 생산·고용 YoY의 부호로 4국면을 나눈다. threshold는 **0**이며, **정확히 0인 경우는 N**(중립)으로 분류한다. YoY 자체가 결측/계산불가(예: 2023Q4·2024Q4)인 관측치는 N이 아니라 **INVALID**로 별도 구분한다 — N과 INVALID는 절대 같은 상태가 아니다.

```
S1 동반확대        production_yoy > 0, employment_yoy > 0
S2 생산확대·고용감소  production_yoy > 0, employment_yoy < 0
S3 생산감소·고용증가  production_yoy < 0, employment_yoy > 0
S4 동반감소        production_yoy < 0, employment_yoy < 0
N  중립            둘 중 하나 이상이 정확히 0
INVALID           결측/계산불가/재분류 비교위험 등으로 국면 판정이 부적절
```

**sensitivity(±0.5/1/2%)**: 본분석 state(threshold=0)와는 완전히 분리된 별도 패널
(`changwon_state_sensitivity_panel.csv`)이다. 미세한 변화까지 증가·감소로 강제하지 않도록 중립구간을
±0.5%, ±1%, ±2%로 넓혀가며 국면 분류가 얼마나 달라지는지 검사한다. **본분석 국면을 대체하지 않는다.**

과거 버전에는 "최근 4분기 vs 직전 4분기, mean/median 방향 일치"를 보는 별도의 sensitivity 개념도 있었으나,
최종 기획안의 sensitivity(임계값 기반)와 개념이 겹치고 혼동을 일으켜 이번 파이프라인에서는 제거했다.

**지속(run)**: 같은 업종 내에서 동일 4상태(S1~S4)가 연속 분기에 이어질 때만 run으로 본다. INVALID를
만나면 run이 끊기고(gap bridging 없음), N은 4상태 run에 포함하지 않는다.

**전환(transition)**: `t분기 상태 → t+1분기 상태`는 같은 업종 + 실제 연속분기일 때만 유효하다. 이 값은
**과거에 관측된 전환 빈도/비율**이며 미래 예측 확률이 아니다.

## 12. PPI·EIS·CCI — 검증·보조 데이터의 역할

KICOX core state panel에 **병합하지 않는다.** 각각 별도 검증 패널로만 존재한다.

| 데이터 | 위치 | 역할 | 비고 |
| --- | --- | --- | --- |
| PPI(생산자물가지수) | `data/raw/ppi/`, `data/processed/ppi/`, `outputs/tables/PPI_*.csv` | 명목 생산액 가격효과 민감도 확인 | 전국 단위 KOSIS 월별 자료(지역 구분 없음). 두 단계로 나뉜다. **① 전처리**(`src/build_validation_panels.py`): 총지수 분기 평균 검증 패널과 업종 대분류 매핑 후보표(`confirmed=False`)만 만든다. **② EDA**(`notebooks/02_eda.ipynb` Section 6): 업종별 PPI **후보 계열**(기타 제외 9개 업종, 11계열)로 명목 생산 YoY를 조정해 국면 방향이 유지되는지 비교한다. 후보가 여럿이면 최솟값~최댓값 범위로 제시한다. KICOX 업종과 PPI 품목의 공식 대응표가 없으므로 조정값은 **조건부 민감도**이며 본분석(명목) 국면을 대체하지 않는다. 최신분기 명목·조정 비교는 진단카드와 Section 8 요약에 함께 싣는다 |
| EIS(고용행정통계) | `data/raw/eis/`, `data/processed/eis/` | KICOX 고용과 통계 정의 비교·배경자료 | 가용기간 2022Q1~2026Q2이며 첫 YoY는 2023Q1이다(보간 금지). KICOX 산단 고용과 모집단이 달라 **합산·대체·비율계산 금지** |
| CCI(창원상공회의소 경제동향보고서) | `data/raw/cci_report/` | 외부 대조·최근 분기 교차확인 | 보고서 표를 수기 전사한 자료이며 **KICOX 원자료가 아니다.** core master 구축에 사용하지 않는다 |

## 13. 저장소 구조

핵심 폴더는 `src/`(공통 코드), `notebooks/`(실행·분석 흐름), `data/raw/`(원자료),
`data/processed/`(분석용 패널), `outputs/`(표·그림·보고서), `logs/`(QA·실행 기록),
`docs/`(기획·방법론·근거), `tests/`(회귀 테스트)로 나뉜다.

파일 배치와 Git 추적 기준은 [`PROJECT_STRUCTURE.md`](PROJECT_STRUCTURE.md), 데이터별 상세 위치와
공유 상태는 [`data/README.md`](data/README.md)를 따른다.

### 팀원 최초 clone

GitHub Collaborator 초대를 수락한 뒤 기본 브랜치인 `main`을 clone한다.

```bash
git clone https://github.com/lcsvvo/Changwon-Industry-Employment-Monitor.git
cd Changwon-Industry-Employment-Monitor
```

Git에 포함되지 않는 원자료는 팀 공유 저장소에서 별도로 받아 `data/raw/` 아래 위 구조대로 배치한다. 상세 목록과 배치 방법은 [`data/README.md`](data/README.md)를 확인한다.

## 14. 실행방법

### 환경 구성

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate        # macOS / Linux
pip install -r requirements.txt
python -m ipykernel install --user --name changwon-venv   # 이 프로젝트 전용 Jupyter 커널 등록(권장)
```

`requirements.txt`: pandas, numpy, openpyxl, ipykernel, jupyterlab, nbconvert, pytest, matplotlib

> 이 저장소는 `.venv/`에 프로젝트 전용 가상환경을 두고 있다. Jupyter의 `python3` 커널이 다른
> 프로젝트의 가상환경을 가리키고 있으면(전역 커널 등록 충돌) 노트북 실행 시 패키지 오류가
> 날 수 있으니, 반드시 이 프로젝트의 `.venv`로 커널을 등록해 사용한다.

### 파이프라인 실행 (오프라인 전용 — 네트워크 접근 코드 없음)

```bash
python src/build_changwon_master.py                # KICOX master 구축 (+ _previous/ 대비 diff)
python src/qa_master.py                            # 품질 QA, exit code 0 = FAIL 없음
python src/build_kicox_analysis_panel.py           # 국면·run·transition·sensitivity 패널
python src/build_validation_panels.py              # PPI 총지수/EIS 검증 패널
python -m pytest tests/test_pipeline_rules.py -v   # 핵심 규칙 회귀 테스트
```

### 노트북 실행

```bash
jupyter lab   # notebooks/01_data_preprocessing.ipynb 를 먼저 Run All, 그다음 02_eda.ipynb
```

두 노트북 모두 커널을 재시작한 뒤 Run All로 끝까지 실행되는 것을 기준으로 검증했다(오프라인,
`data/raw/` 변경 없음). Windows 콘솔 기본 인코딩이 cp949라 한글 출력이 깨지는 문제가 있어,
notebook이 호출하는 자식 프로세스에는 `PYTHONIOENCODING=utf-8`을 넘긴다.

`data/raw/`는 저장소에 커밋하지 않으며, 파이프라인 어디에서도 쓰기 작업을 하지 않는다.

## 15. 확정된 사항 / 아직 확정하지 않은 사항

| 항목 | 현재 상태 |
| --- | --- |
| 참고기간(reference) | **확정** 2018Q1~2026Q2 (산단 전체 장기 흐름) |
| 본분석기간(main) | **확정** 2022Q1~2026Q2 — 10개 업종 모두 4분면 산출 가능한 첫 분기부터. 2018Q4·2020Q3 재분류, 2021년 섬유의복 YoY inf, 2023Q4 생산 X 결측을 근거로 실측 검증(§10~11) |
| 국면(S1~S4)·run·transition | **핵심 산출물로 사용** — `changwon_state_panel.csv`. ±0.5/1/2% sensitivity는 별도 검증용 |
| PPI(생산자물가지수) | **민감도 분석으로 사용**. 전처리 단계는 총지수 검증 패널, EDA 단계는 업종별 후보 계열 조정 비교(조건부). 공식 업종 대응표는 미확정이며 본분석 국면은 명목 기준을 유지한다 |
| EIS(고용행정통계) | **검증용으로 사용**. 2022Q1~2026Q2 가용, KICOX 고용과 합산·대체 안 함 |
| 제조 AX 연결 | **정책 배경 후보** — 창원시가 제조 AX 전환 정책을 추진 중이나, 본 프로젝트를 제조 AX를 위한 프로젝트로 규정하지 않는다 |
| 전략산업 추가 | 미확정 |
| 고용24 채용수요 | 이번 파이프라인 제외 |

## 16. 해석 주의사항

- 생산과 고용의 관계는 **상관이며 인과가 아니다.**
- 전환(transition) 빈도/비율은 과거 관측치이며 미래 예측 확률이 아니다.
- ±0.5/1/2% sensitivity에서 국면이 바뀌는 업종을 특정 유형으로 단정하지 않는다.
- 업종 재분류 시점(2018Q4, 2020Q3)을 가로지르는 장기 비교는 구조 변화로 해석하지 않는다.
- 생산액은 명목금액(억원)이며 가격효과를 포함한다 — PPI 조정은 업종별 후보 계열에 따른 조건부 민감도이며 실제 물량·실질생산이 아니다. 최신분기 명목 결과와 조정 결과가 다르면 두 값을 함께 제시한다.
- EIS는 KICOX와 모집단·통계 정의가 달라 비율/점유율을 계산하지 않는다.
- 2023Q4·2024Q4의 production YoY/국면 결측은 데이터 오류가 아니라 정상적인 구조적 결측(INVALID)이다.
