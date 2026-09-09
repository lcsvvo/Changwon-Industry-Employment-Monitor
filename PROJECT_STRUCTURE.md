# 저장소 사용 규칙

이 문서는 파일 목록이나 변경 이력이 아니라, 팀원이 새 파일을 어디에 두고 무엇을 Git으로 공유할지 정하는 기준이다. 프로젝트 설명, 분석 기준, 설치 및 실행 방법은 [`README.md`](README.md), 데이터 출처와 확보 현황은 [`data/README.md`](data/README.md), Git 협업 절차는 [`CONTRIBUTING.md`](CONTRIBUTING.md)를 따른다.

## 기본 구조

```text
Changwon-Industry-Employment-Monitor/
├─ src/                 재사용 가능한 수집·전처리·분석·검증 코드
├─ notebooks/           사람이 순서대로 실행하고 결과를 확인하는 노트북
├─ data/
│  ├─ raw/              수정하지 않는 원자료(로컬 보관, Git 제외)
│  └─ processed/        코드로 만든 분석 입력·검증 패널
├─ outputs/
│  ├─ figures/          EDA가 생성한 그림
│  ├─ tables/           보고서·검증에 쓰는 표
│  └─ report/           내보낸 보고서와 로컬 미리보기
├─ logs/preprocessing/  파이프라인 QA·출처 추적 결과와 실행 로그
├─ docs/                기획, 방법론, 공모전 자료, 정책·근거 문서
├─ tests/               재현성과 핵심 분석 규칙을 검사하는 테스트
└─ private/             개인 조사 메모(로컬 전용, Git 제외)
```

하위 파일 전체를 이 문서에 복제하지 않는다. 현재 파일은 저장소 자체와 `git ls-files`로 확인한다.

## 파일 배치 기준

| 새 파일 | 위치 | 기준 |
| --- | --- | --- |
| Python 모듈·파이프라인·공통 함수 | `src/` | 두 번 이상 쓰거나 자동 실행할 로직 |
| EDA·시각화·결과 확인 흐름 | `notebooks/` | 설명과 실행 결과를 함께 검토하는 작업 |
| 수집한 원본 CSV/XLSX 등 | `data/raw/<source>/` | 사람이 값을 수정하지 않음 |
| 정제·결합한 분석용 데이터 | `data/processed/<source>/` | 원자료와 코드로 재생성 가능 |
| 자동 생성 그림·표·보고서 | `outputs/figures/`, `outputs/tables/`, `outputs/report/` | 소스 데이터나 코드 폴더에 저장하지 않음 |
| QA·출처 추적·실행 기록 | `logs/preprocessing/` | 분석 결과와 실행 기록을 분리 |
| 기획·방법론·공모전·근거 문서 | `docs/` | 문서 성격에 맞는 기존 하위 폴더 사용 |
| 테스트 코드 | `tests/` | 분석 규칙과 경로의 회귀 방지 |
| 개인 도구 설정·메모·비밀정보 | Git 제외 경로 | 팀 재현에 필요하지 않은 로컬 자산 |

`notebooks/`에는 `.ipynb`만 둔다. 노트북에서 분리한 Python 코드는 `src/`, 생성한 CSV·JSON·그림·HTML은 `data/processed/` 또는 `outputs/`에 둔다. 절대경로를 저장하지 말고 `Path(__file__)` 또는 프로젝트 루트를 찾아 만든 상대경로를 사용한다.

## 분석 코드의 단일 기준

실행 순서는 다음과 같다.

```text
data/raw/
  → src/build_changwon_master.py
  → src/qa_master.py
  → src/build_kicox_analysis_panel.py
  → src/build_validation_panels.py
  → notebooks/02_eda.ipynb
```

- 생산·고용 YoY와 lag는 마스터 구축 코드가 계산한다.
- S1~S4, N, INVALID, threshold, run, transition은 `src/build_kicox_analysis_panel.py`가 만든 공통 패널을 기준으로 한다.
- EDA 노트북은 공통 state를 다시 만들어 분석 기준을 바꾸지 않는다. 같은 공식을 다시 쓰는 경우는 입력 검증 또는 PPI/EIS 보조분석처럼 목적이 분리된 계산으로 제한한다.
- Q3는 Q1에서 생성한 state 패널을 사용한다. Q1·Q2·Q3마다 상태를 따로 계산하지 않는다.
- PPI·EIS·CCI는 검증·보조 자료이며 KICOX 핵심 패널에 합산하거나 대체하지 않는다.

## Git 공유 정책

| 대상 | 정책 |
| --- | --- |
| `src/`, `notebooks/`, `tests/`, `docs/` | 팀 작업이므로 추적 |
| `data/raw/` | 용량·배포 조건 때문에 제외하고 별도 공유 |
| `data/processed/` | 재현에 필요한 검토 완료 패널은 추적 |
| `outputs/tables/` | 보고서에 사용하는 검토 완료 표는 추적 |
| `outputs/figures/*.png` | 노트북에서 재생성하므로 제외 |
| `outputs/report/*.html` | 기본적으로 로컬이며, 검토 완료된 `eda_preview.html`만 공유 |
| `logs/preprocessing/*.csv`, `*.json`, `*.txt` | QA와 출처 추적에 필요한 결과는 추적 |
| `logs/**/*.log` | 실행할 때마다 생기는 기록이므로 제외 |
| `.venv/`, cache, notebook checkpoint, `.claude/`, IDE 설정, `private/` | 로컬 전용이므로 제외 |

`data/processed/`, `outputs/tables/`, QA 결과는 자동 생성된다는 이유만으로 전부 제외하지 않는다. 팀원이 동일 입력을 갖지 않아도 결과와 검증 근거를 확인해야 하는 파일만 검토 후 커밋한다. 반대로 일회성 미리보기, 그림, 타임스탬프 실행 로그는 커밋하지 않는다.

## 팀 작업 체크리스트

1. 작업 전 `git status`로 다른 사람의 미커밋 변경을 확인한다.
2. 원자료는 `data/raw/`에서 읽기만 한다.
3. 공통 계산은 `src/`에 한 번만 두고 노트북은 이를 호출하거나 산출물을 읽는다.
4. 생성 파일은 역할에 따라 `data/processed/`, `outputs/`, `logs/` 중 하나에 저장한다.
5. 파일 이동 후 기존 경로, import, Markdown 링크를 저장소 전체에서 검색한다.
6. 테스트와 노트북 경로 검사를 마친 뒤 필요한 파일만 선택해 stage한다.

날짜별 이동·삭제 내역, 해결된 오류, 당시 Git 상태는 이 문서에 적지 않는다. 그런 정보는 Git 이력과 Pull Request에서 관리한다.
