# PROJECT_STRUCTURE

창원국가산단 업종별 산업·고용 전환진단 프로젝트 파일 구조 정리 기록.
정리일: 2026-09-07 / 범위: 폴더 구조 정리만 수행. 코드 로직·데이터 값·원자료 내용은 변경하지 않음.

---

## 1. 최종 폴더 구조

```text
Changwon-Industry-Employment-Monitor/
│
├─ README.md                     (구조 개편 이전 경로 서술 - 갱신 필요)
├─ CONTRIBUTING.md
├─ requirements.txt
├─ .gitignore                    (신규 raw 경로 기준으로 갱신함)
├─ PROJECT_STRUCTURE.md          (본 문서)
│
├─ docs/
│  ├─ 01_planning/
│  │  ├─ 최종 기획안(0907).txt                                  ← 현재 기준 기획안
│  │  └─ methodology/
│  │     ├─ 창원국가산단_산업고용전환진단_방법론및EDA계획.md
│  │     └─ data_collection_standard.md
│  ├─ 02_competition/
│  │  ├─ 공고문(2026년 창원시 AI_데이터 활용 공모전).pdf
│  │  └─ 홍보 포스터.jpg
│  ├─ 03_policy_reference/
│  │  ├─ changwon-policy-long-list.txt
│  │  └─ reference-notes.md
│  └─ 04_evidence/
│     └─ 2026년 1분기 창원지역 경제동향보고서(최종).pdf
│
├─ data/
│  ├─ README.md                  (구조 개편 이전 경로 서술 - 갱신 필요)
│  ├─ raw/
│  │  ├─ kicox/
│  │  │  ├─ core/                공공데이터포털 원본 CSV 498개
│  │  │  └─ revision/
│  │  │     ├─ 2022_10_2025_Q1/xlsx/   연간보정본 22개
│  │  │     └─ 2026_Q1_Q2/xlsx/        연간보정본 2개
│  │  ├─ ppi/                    ppi_raw.csv (KOSIS 생산자물가지수 원본)
│  │  ├─ eis/                    eis_changwon_insured_2023M12_2026M06.csv
│  │  ├─ cci_report/             창원상공회의소 경제동향보고서 전사본 6개
│  │  └─ _pending_review/        분류 보류 원자료 1개
│  └─ processed/
│     ├─ kicox/
│     │  ├─ changwon_industry_master.csv
│     │  ├─ changwon_total_master.csv
│     │  └─ candidate_v1/        상태패널 후보본 7개
│     ├─ ppi/                    (비어 있음)
│     └─ eis/                    (비어 있음)
│
├─ notebooks/                    기존 노트북 (재작성 시 참고용으로 보존)
│  ├─ 01_data_build.ipynb
│  └─ 02_kicox_analysis_preprocessing.ipynb
│
├─ src/
│  ├─ build_changwon_master.py
│  ├─ build_kicox_analysis_panel.py
│  └─ qa_master.py
│
├─ outputs/
│  ├─ figures/                   (비어 있음)
│  ├─ tables/                    (비어 있음)
│  └─ report/                    (비어 있음)
│
├─ dashboard/                    (비어 있음, 최종 기획안에 없는 잔여 폴더)
└─ private/                      (.gitignore 대상 로컬 조사메모)
   └─ data_guide.md
```

`logs/`, `archive/`, `notebooks/legacy/` 는 사용자가 정리 중 직접 삭제하여 현재 존재하지 않음. 기존 노트북 2개는 `notebooks/` 바로 아래에 보존되어 있음.

---

## 2. 데이터 역할

| 데이터 | 분류 | 위치 | 역할 |
| --- | --- | --- | --- |
| KICOX 생산·고용·가동률·입주업체·가동업체 | **핵심 원자료** | `data/raw/kicox/core/` | 생산·고용 YoY → S1~S4 국면 → 지속 → 전환의 출발점 |
| KICOX 연간보정본 (XLSX 24개) | **보정자료** | `data/raw/kicox/revision/` | 분기 공표값의 최종 기준값 확정. 독립 설명변수 아님 |
| 생산자물가지수 (KOSIS) | **검증·보조** | `data/raw/ppi/` | 명목 생산액의 가격효과 민감도 확인 |
| EIS 고용행정통계 | **검증·보조** | `data/raw/eis/` | KICOX 고용과 정의·흐름 비교. 합산·대체 금지 |
| 창원상공회의소 경제동향보고서 전사본 | **검증·보조** | `data/raw/cci_report/` | 산단 지표의 외부 대조·최근 분기 교차확인 |
| 직종별규모별 노동력조사 | **분류 보류** | `data/raw/_pending_review/` | 최종 기획안 데이터 목록에 없음. 사용 여부 미정 |
| KICOX 마스터·상태패널 후보본 | **가공 결과** | `data/processed/kicox/` | 기존 코드 산출물. 다음 단계에서 재생성 예정 |

### 주의 — 혼동하기 쉬운 지점

- `data/raw/cci_report/창원국가산단_업종별현황_*.csv`, `창원국가산단_전체동향_통합시계열.csv` 는 KICOX 원자료가 **아니다**. 창원상공회의소 보고서 표를 수기 전사한 자료이므로 KICOX core 와 합치지 말 것.
- `data/raw/cci_report/창원시_업종별_고용보험피보험자_동향.csv` 는 창원시 전체 기준 고용보험 피보험자로, 산단 내부 기준인 KICOX 고용과 범위가 다르다. EIS 계열 역할이지만 출처가 보고서이므로 `eis/` 가 아닌 `cci_report/` 에 둠. 역할 기준으로 묶고 싶다면 `data/raw/eis/` 로 옮겨도 무방.
- `data/raw/ppi/ppi_raw.csv` 는 전국 전품목 원본(22,057행)이며 창원·업종 필터가 적용되어 있지 않다.

---

## 3. 현재 기준 문서

| 구분 | 파일 | 비고 |
| --- | --- | --- |
| 최종 기획안 | `docs/01_planning/최종 기획안(0907).txt` | **유일한 기준 버전**. 주제 = 창원국가산단 업종별 산업·고용 전환진단 |
| 방법론·EDA 계획 | `docs/01_planning/methodology/창원국가산단_산업고용전환진단_방법론및EDA계획.md` | |
| 수집·전처리 기준 | `docs/01_planning/methodology/data_collection_standard.md` | |
| 공모전 공고 | `docs/02_competition/공고문(2026년 창원시 AI_데이터 활용 공모전).pdf` | |
| 차별성 근거 | `docs/04_evidence/2026년 1분기 창원지역 경제동향보고서(최종).pdf` | 기존 공개자료와의 비교 대상 |

`README.md` 본문의 주제 서술은 과거 기획(정책 우선순위 도출)에 가깝다. 최종 기획안과 충돌하므로 다음 단계에서 갱신 필요.

---

## 4. 기존 코드 위치

| 구분 | 파일 | 역할 |
| --- | --- | --- |
| 기존 01 | `notebooks/01_data_build.ipynb` | KICOX 수집·마스터 구축·검증 (src 호출 래퍼) |
| 기존 02 | `notebooks/02_kicox_analysis_preprocessing.ipynb` | 마스터 → 상태패널 후보본 생성 |
| src | `src/build_changwon_master.py` | 원자료 → 마스터 빌드 본체 |
| src | `src/build_kicox_analysis_panel.py` | 마스터 → 국면·지속·전환 패널 |
| src | `src/qa_master.py` | 마스터 읽기 전용 QA |

`src/` 는 이번 단계에서 **이동·수정하지 않음**.

---

## 5. 이동한 파일 목록

```text
최종 기획안(0907).txt                              → docs/01_planning/
창원국가산단_산업고용전환진단_방법론및EDA계획.md    → docs/01_planning/methodology/
docs/data_collection_standard.md                   → docs/01_planning/methodology/
공고문(2026년 창원시 AI_데이터 활용 공모전).pdf     → docs/02_competition/
docs/references/changwon-policy-long-list.txt      → docs/03_policy_reference/
docs/references/README.md                          → docs/03_policy_reference/reference-notes.md
2026년 1분기 창원지역 경제동향보고서(최종).pdf      → docs/04_evidence/

data/raw/*.csv (498개)                             → data/raw/kicox/core/
data/annual_revision/2022_10_2025_Q1/              → data/raw/kicox/revision/2022_10_2025_Q1/
data/annual_revision/2026_Q1_Q2/                   → data/raw/kicox/revision/2026_Q1_Q2/
ppi_raw.csv                                        → data/raw/ppi/
data/external/eis_changwon_insured_*.csv           → data/raw/eis/
창원국가산단_업종별현황_2025Q2~2026Q1.csv (4개)     → data/raw/cci_report/
창원국가산단_전체동향_통합시계열.csv                → data/raw/cci_report/
창원시_업종별_고용보험피보험자_동향.csv             → data/raw/cci_report/
직종별규모별_2026년_이후__20260907145119.csv        → data/raw/_pending_review/

data/processed/changwon_industry_master.csv        → data/processed/kicox/
data/processed/changwon_total_master.csv           → data/processed/kicox/
data/analysis/kicox_candidate_v1/*                 → data/processed/kicox/candidate_v1/

results/figures/, results/tables/                  → outputs/figures/, outputs/tables/
(노트북 2개는 notebooks/ 위치 유지 - legacy/ 하위 이동은 사용자가 되돌림)
```

`.gitignore` 갱신: `data/raw/*` → `data/raw/kicox/**`, `data/annual_revision/*`·`data/existing/*` 규칙 제거, `logs/*.log` → `logs/**/*.log`, `archive/**` 추가.

---

## 6. archive 처리 결과

정리 중 아래 항목을 `archive/pre_refactor/` 로 이동했으나, **사용자가 이후 `archive/` 폴더를 직접 삭제**하여 현재 남아 있지 않다.

| 항목 | 이동 사유 | 현재 상태 |
| --- | --- | --- |
| `docs/planning/final-topic.txt` | 과거 기획안(정책 우선순위·고용24 미스매치 중심). 최종 기획안과 주제 충돌 | 삭제됨 — git 추적본이므로 복구 가능 |
| `창원시 기존 우수,유망 정책 Long List (17개).txt` (루트 사본) | `docs/03_policy_reference/` 본과 내용 동일(줄바꿈만 차이) | 삭제됨 — 동일 내용 파일 보존 중 |
| `data/changwon_state_panel.csv` (루트 사본) | `candidate_v1/changwon_state_panel.csv` 와 MD5 동일 | 삭제됨 — 동일 내용 파일 보존 중 |
| `data/annual_revision/verified_input/*.xlsx` 24개 | 2022_10_2025_Q1 + 2026_Q1_Q2 와 **바이트 단위 완전 동일** 사본 | 삭제됨 — 원본 24개 보존 중 |
| `data/existing/changwon_master_2018Q1_2026Q2.csv` | 구버전 대조용 마스터 | 삭제됨 — **git 미추적 파일이라 복구 불가** |
| `docs/competition/2026-changwon-ai-data-competition-notice.pdf` | 루트 공고문 PDF와 동일 문서(파일 해시는 다름) | 삭제됨 — git 추적본이므로 복구 가능 |
| `docs/references/2025-changwon-bigdata-summary.hwp` | 2025 수상후보작 요약 | 삭제됨 — git 추적본이므로 복구 가능 |

git 추적본 복구가 필요하면:

```bash
git checkout HEAD -- docs/planning/final-topic.txt docs/references/2025-changwon-bigdata-summary.hwp docs/competition/2026-changwon-ai-data-competition-notice.pdf
```

---

## 7. 중복 또는 판단 보류 파일

| 파일 | 상태 | 판단 |
| --- | --- | --- |
| `data/raw/_pending_review/직종별규모별_2026년_이후__20260907145119.csv` | 보류 | 전국 17개 시도 × 전규모 × 전직종 20행. 창원·업종 단위 아님. 최종 기획안 데이터 목록에 없음 |
| `data/raw/cci_report/*` | 보류 | 수기 전사본이므로 엄밀히는 원자료가 아님. raw 유지 여부는 다음 단계에서 결정 |
| `private/` | 이동 보류 | `.gitignore` 에 `private/` 규칙이 있어 이동 시 Git 추적 정책이 바뀜 |
| `dashboard/` | 이동 보류 | 빈 폴더. 최종 기획안 구조에 없음. 용도 확인 후 처리 |
| `src/` 전체 | 이동 보류 | 이번 단계 대상 아님. 코드 재작성 단계에서 처리 |
| `data/processed/kicox/*` | **최종 결과 아님** | 기존 코드 버전 산출물. 다음 단계에서 재생성 예정이므로 확정본으로 취급 금지 |

---

## 8. 현재 로컬에 없는 참조 데이터

문서·코드가 참조하지만 실제 파일이 없는 항목. **삭제 대상이 아니며, 임의 재다운로드·빈 파일 생성 금지.**

| 참조 위치 | 없는 파일 | 영향 |
| --- | --- | --- |
| `src/build_kicox_analysis_panel.py:16` | `config/kicox_candidate_lock.json` | `load_inputs()` 실행 불가 |
| `notebooks/02...ipynb` cell 21 | `tests/test_analysis_rules.py` | 최종 품질검증 셀 실행 불가 |
| `notebooks/02...ipynb` cell 21 | `verify_annual_sources.py` | 연간보정 대조 셀 실행 불가 |
| `notebooks/02...ipynb` cell 0 | `docs/kicox_analysis_rules_v1.md` | 분석 규칙 문서 부재 |
| `src/build_kicox_analysis_panel.py:83,86,202,212` | `logs/raw_inventory.csv`, `logs/revision_inventory.csv`, `logs/master_diff.csv` | 사용자가 `logs/` 삭제. git 추적본 복구 또는 파이프라인 재실행 필요 |
| `data/README.md` | FactoryON, 고용24 데이터 | 최종 기획안에서 "필요 시" 확장 데이터로만 언급 |

팀원이 카카오톡 등으로 별도 공유 예정인 파일이 있을 수 있으므로, 위 목록을 근거로 데이터가 없다고 단정하지 말 것.

---

## 9. 다음 Claude Code 작업 시 주의할 점

### 9-1. 경로가 바뀌어 반드시 수정해야 하는 코드

| 파일 | 줄 | 기존 값 | 새 위치 |
| --- | --- | --- | --- |
| `src/build_changwon_master.py` | 58 | `data/raw` | `data/raw/kicox/core` |
| `src/build_changwon_master.py` | 59 | `data/annual_revision` | `data/raw/kicox/revision` |
| `src/build_changwon_master.py` | 60 | `data/processed` | `data/processed/kicox` |
| `src/build_changwon_master.py` | 61 | `data/existing` | **폴더·파일 삭제됨** (987행 `compare_existing_master` 비활성 필요) |
| `src/build_changwon_master.py` | 62 | `logs` | **폴더 삭제됨** (재생성 필요) |
| `src/qa_master.py` | 36~38 | `data/processed`, `data/annual_revision`, `logs` | 위와 동일 |
| `src/build_kicox_analysis_panel.py` | 20~21 | `data/processed/changwon_*_master.csv` | `data/processed/kicox/...` |
| `src/build_kicox_analysis_panel.py` | 83,86,202,212 | `logs/*.csv` | `logs/` 삭제됨 |
| `src/build_kicox_analysis_panel.py` | 221 | `data/analysis/kicox_candidate_v1` | `data/processed/kicox/candidate_v1` |
| `notebooks/01,02.ipynb` | 경로 셀 | `cwd` 이름이 `notebooks` 일 때만 ROOT 인식 | 위치 유지되어 ROOT 계산은 정상 |

### 9-2. 문서 갱신 필요

- `README.md` — 폴더 트리(224~246행), 실행 예시, 데이터 배치 안내가 모두 구버전 경로 기준. 주제 서술도 과거 기획안 기준.
- `data/README.md` — 저장 위치 컬럼과 폴더 정책이 구버전 경로 기준.
- `docs/03_policy_reference/reference-notes.md` — 두 번째 항목이 가리키는 `2025-changwon-bigdata-summary.hwp` 는 현재 삭제 상태.

### 9-3. 작업 원칙

- `01 = 데이터 전처리`, `02 = EDA` 로 재작성. 기존 노트북 2개는 `notebooks/` 에 그대로 있으므로 덮어쓰지 말고 참고용으로 유지할 것.
- `data/raw/` 아래 파일은 읽기 전용. 전처리 결과·QA·로그·그림을 raw 에 쓰지 말 것.
- KICOX 고용과 EIS 고용은 합산·대체 금지. PPI 는 검증용이며 국면 산출에 직접 투입하지 않음.
- `data/processed/kicox/` 의 현재 파일은 확정본이 아니라 이전 코드 버전 산출물이다.
- git 상태에 다수의 삭제·이동이 반영되지 않은 상태이므로, 작업 시작 전 `git status` 확인 및 커밋 여부 결정 필요.

---

## 10. 2026-09-08 갱신 — 전처리·EDA 파이프라인 구현 완료

§8·§9에서 지적된 항목들이 Plan → 승인 → 구현 절차를 거쳐 처리되었다. 상세는 `README.md`,
`data/README.md`, 그리고 대화 세션의 최종 완료 보고를 참고한다. 요약:

- §9-1 경로 문제: `src/build_changwon_master.py`, `src/qa_master.py`, `src/build_kicox_analysis_panel.py`
  모두 새 경로(`data/raw/kicox/core`, `data/raw/kicox/revision`, `data/processed/kicox`,
  `logs/preprocessing`)로 수정 완료. `data/existing/`·구 `logs/`를 복구하지 않고, `compare_existing_master`는
  `data/processed/kicox/_previous/`(기존 산출물 백업) 대비 diff로 교체했다.
- §8 참조 없는 파일(`config/kicox_candidate_lock.json`, `tests/test_analysis_rules.py`,
  `verify_annual_sources.py`, `docs/kicox_analysis_rules_v1.md`): 복구하지 않기로 결정(git blob SHA
  잠금 재도입 안 함, 사용자 확인 완료). 대신 현재 규칙에 맞춘 `tests/test_pipeline_rules.py`를 새로 작성했다.
- `build_changwon_master.py`의 data.go.kr 온라인 스크래핑 코드(`urllib` 기반 `_get`/`_post`/`list_versions`/
  `download_one`)는 완전히 제거했다 — 실제 데이터 수집이 API 키 없이 이루어졌으므로 코드도 오프라인
  전용으로 맞췄다.
- `build_changwon_master.py`의 구 `sensitivity_check()`(최근4 vs 직전4분기, mean/median 방향비교,
  `logs/quadrant_sensitivity.csv`)는 최종 기획안의 ±0.5/1/2% 임계값 sensitivity와 개념이 겹쳐 제거했다.
  본분석 국면(threshold=0)과 sensitivity(threshold=0.5/1/2)는 `src/build_kicox_analysis_panel.py` 하나로 통합.
- `data/processed/kicox/{changwon_industry_master.csv, changwon_total_master.csv, candidate_v1/}`는
  `_previous/`로 이동(삭제 아님) 후 재생성했다. 재생성 결과는 이전 산출물과 **값 차이 없음**으로 확인됨.
- `notebooks/01_data_build.ipynb` + `02_kicox_analysis_preprocessing.ipynb` → `notebooks/01_data_preprocessing.ipynb`
  하나로 통합, `notebooks/02_eda.ipynb`를 신규 작성. 기존 두 노트북은 삭제하지 않고 그대로 두었다
  (더 이상 사용하지 않는 참고용 파일).
- 본분석기간은 2022Q1~2026Q2로 확정(사용자 승인 완료), 참고기간은 2018Q1~2026Q2로 유지.
- PPI 업종별 매핑은 여전히 보류 상태이며(`data/processed/ppi/ppi_industry_mapping_candidates.csv`,
  전부 `confirmed=False`), 이번 파이프라인은 총지수 기준 제한적 검증만 수행한다.
- 이 작업 중 `data/raw/`는 어떤 파일도 수정되지 않았다(파이프라인 자체에 쓰기 방지 가드 포함).
