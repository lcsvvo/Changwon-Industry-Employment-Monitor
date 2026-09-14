# Data Catalog

이 문서는 프로젝트에서 사용하는 데이터의 출처, 수집 상태, 저장 위치와 Git 추적 정책을 관리한다.
2026-09-08 기준 KICOX core+revision → master → 국면(S1~S4)·run·transition 패널까지, 그리고
PPI(총지수 검증)·EIS(고용 검증) 패널까지 오프라인 파이프라인이 완료되었다. PPI 업종별 후보 계열 민감도는
`notebooks/02_eda.ipynb` Section 6에서 별도로 수행한다.

## 현재 데이터

| 데이터명 | 출처 | 데이터셋 ID·조회조건 | 확보 기간 | 저장 위치 | Git 정책 | 상태 |
| --- | --- | --- | --- | --- | --- | --- |
| 생산실적 | 한국산업단지공단(KICOX), 공공데이터포털 | 업종별 `15085898`, 단지전체 `15085891` | 2018Q1~2026Q2 | `data/raw/kicox/core/`, `data/raw/kicox/revision/` | 원자료 제외, 가공본 추적 | 완료 |
| 고용현황 | 한국산업단지공단(KICOX), 공공데이터포털 | 업종별 `15085897`, 단지전체 `15085890` | 2018Q1~2026Q2 | `data/raw/kicox/core/`, `data/raw/kicox/revision/` | 원자료 제외, 가공본 추적 | 완료 |
| 가동률 | 한국산업단지공단(KICOX), 공공데이터포털 | 업종별 `15085895`, 단지전체 `15085889` | 2018Q1~2026Q2 | `data/raw/kicox/core/`, `data/raw/kicox/revision/` | 원자료 제외, 가공본 추적 | 완료 |
| 입주업체 | 한국산업단지공단(KICOX), 공공데이터포털 | 업종별 `15085901`, 단지전체 `15085894` | 2018Q1~2026Q2 | `data/raw/kicox/core/`, `data/raw/kicox/revision/` | 원자료 제외, 가공본 추적 | 완료 |
| 가동업체 | 한국산업단지공단(KICOX), 공공데이터포털 | 업종별 `15085896` | 2018Q1~2026Q2 | `data/raw/kicox/core/`, `data/raw/kicox/revision/` | 원자료 제외, 가공본 추적 | 완료 |
| 생산자물가지수(PPI) | KOSIS(통계청) 생산자물가지수(기본분류) | `DT_404Y014`, 전국·월별, 계정코드별 | 2021M01~2026M06 | `data/raw/ppi/`, `data/processed/ppi/` | 원자료 제외, 가공본 추적 | 완료(전처리: 총지수 검증 패널 / EDA: 업종별 후보 계열 민감도, 공식 매핑 미확정) |
| 창원시 고용보험 피보험자(EIS) | 고용노동부 고용행정통계(EIS) | 창원시 5개 구, 전체산업·제조업, 월말 기준 | 2022Q1~2026Q2 | `data/raw/eis/`, `data/processed/eis/` | 원자료 제외, 가공본 추적 | 완료 |
| 창원상공회의소 경제동향보고서 | 창원상공회의소 | 보고서 표 수기 전사본 | 2022Q2~2026Q1 | `data/raw/cci_report/` | 원자료 제외 | 확보(검증·교차확인용, KICOX 원자료 아님) |
| 사업체노동력조사류(보류) | 고용노동부 | 2026.1/2 기준, 경상남도 단위(창원시 단위 없음) | 2026M01~M02 | `data/raw/_pending_review/` | 원자료 제외 | 보류(이번 파이프라인 미사용) |
| 고용24 채용·훈련 | 검토 예정 | KICOX 핵심 파이프라인에는 미사용 | - | - | - | 후보 |

KICOX의 상세 수집 방식, 시점 변환, 수정치 우선순위와 알려진 이슈는
[`../docs/01_planning/methodology/data_collection_standard.md`](../docs/01_planning/methodology/data_collection_standard.md)를 따른다.

## 폴더와 공유 정책

```text
data/raw/                     원자료. Git에서 제외, 별도 팀 공유 저장소로 전달
├─ kicox/core/                공공데이터포털 원본 CSV 498개
├─ kicox/revision/            KICOX 연간보정본 XLSX 24개 (2022_10_2025_Q1/, 2026_Q1_Q2/)
├─ ppi/ppi_raw.csv            KOSIS 생산자물가지수(기본분류) 원자료
├─ eis/                       고용노동부 EIS 창원시 고용보험 피보험자 집계본
├─ cci_report/                창원상공회의소 경제동향보고서 전사본 (KICOX 원자료 아님)
└─ _pending_review/           검토 대기 중인 원자료 (이번 파이프라인 미사용)

data/processed/                코드로 재생성하는 최종 산출물. 코드와 함께 Git에서 추적
├─ kicox/                     industry/total master, state/run/transition 패널
├─ ppi/                       PPI 총지수 검증 패널, 전처리 단계 업종 대분류 매핑 후보표(미확정)
└─ eis/                       EIS 검증 패널
```

**주의 — 혼동하기 쉬운 지점**

- `data/raw/cci_report/`의 파일들은 KICOX 원자료가 **아니다.** 창원상공회의소 보고서 표를 수기
  전사한 것이므로 `kicox/` 아래 core master 구축에 사용하지 않는다.
- `data/raw/ppi/ppi_raw.csv`는 **전국 단위** 월별 자료다(지역 구분 없음). 창원 지역 PPI가 아니며
  KICOX 10개 업종과의 공식 대응표도 확정되지 않았다(`ppi_industry_mapping_candidates.csv` 참고,
  전부 `confirmed=False`). EDA의 업종별 조정은 후보 계열(`src/eda/config.py`의 `PPI_MAPPING_ROWS`)에
  따른 조건부 민감도이며, 전처리 후보표와 계열 선택이 일부 다르다(예: 철강은 1차금속 대분류 대신 철강1차제품).
- `data/raw/eis/`의 고용보험 피보험자 수는 KICOX 산단 고용과 모집단이 다르다. 합산·대체·비율계산
  금지.

팀원이 저장소를 clone한 뒤 완전한 오프라인 재현을 하려면 별도 전달받은 파일을 위 트리 그대로
`data/raw/` 아래 배치한다. 그 후 저장소 루트에서 순서대로 실행한다.

```bash
python src/build_changwon_master.py
python src/qa_master.py
python src/build_kicox_analysis_panel.py
python src/build_validation_panels.py
python -m pytest tests/test_pipeline_rules.py -v
```

또는 `notebooks/01_data_preprocessing.ipynb`를 Run All 한다.

## 관리 원칙

- 원본 데이터(`data/raw/`)는 수정하지 않는다. 모든 파이프라인은 오프라인이며 네트워크에 접근하지 않는다.
- 원본에서 재생성할 수 있는 전처리 코드와 출처 추적 컬럼을 함께 관리한다.
- API 키, 인증정보, 개인정보와 개인 조사메모는 저장소에 커밋하지 않는다.
- 외부 배포 제한이나 이용약관이 있는 데이터는 GitHub에 포함하지 않는다.
- 새 데이터를 추가할 때 출처, 수집일, 조회조건, 기간, 단위와 저장 위치를 이 문서에 기록한다.
- 검증·보조 데이터(PPI/EIS/CCI)는 KICOX core state panel에 병합하지 않는다.
