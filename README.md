# Changwon Industry-Employment Monitor

2026년 창원시 AI·데이터 활용 공모전 참가 프로젝트입니다.

창원국가산단의 산업 성장과 고용 변화가 함께 움직이고 있는지를 분석하고, 업종별 차이를 바탕으로 산업·기업·인력 정책의 우선 검토 대상을 제시합니다. 핵심 산출물은 업종별 산업·고용 상황을 한눈에 살펴볼 수 있는 **「창원 산업·고용 국면판」**입니다.

> 현재는 프로젝트 초기 설정과 데이터 수집 준비 단계입니다. 아직 검증되지 않은 분석 결과나 정책 결론은 포함하지 않습니다.

## Main Research Question

**창원국가산단의 성장이 실제 일자리 증가로 이어지고 있는가?**

## Analysis Flow

1. 창원국가산단 생산·가동률·업체 수 변화 확인
2. 생산과 고용 변화 비교
3. 업종별 산업·고용 유형 분류
4. 주요 업종의 변화 특성 분석
5. 가능할 경우 채용·훈련 데이터 결합
6. 산업별 정책 우선순위 제안
7. 「창원 산업·고용 국면판」 구축

## Main Data Candidates

- 창원국가산단 생산실적
- 창원국가산단 고용현황
- 창원국가산단 가동률
- 입주업체 및 가동업체 현황
- 생산자물가지수 등 가격지수
- 고용24 채용공고
- 고용24 직업훈련 과정
- KOSIS 관련 산업·고용 데이터

실제 데이터의 출처와 수집 상태는 [`data/README.md`](data/README.md)에서 관리합니다.

## 시작하기

이 저장소는 비공개 저장소이므로 GitHub Collaborator 초대를 먼저 수락해야 합니다.

```bash
git clone https://github.com/lcsvvo/Changwon-Industry-Employment-Monitor.git
cd Changwon-Industry-Employment-Monitor
python -m venv .venv
```

Windows PowerShell에서 가상환경 활성화:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

macOS/Linux에서 가상환경 활성화:

```bash
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

현재 `requirements.txt`에는 확정된 실행 의존성이 없습니다. 분석 코드가 추가될 때 사용한 패키지와 버전 범위를 함께 기록합니다.

## 저장소 사용 방법

1. [`docs/planning/final-topic.txt`](docs/planning/final-topic.txt)에서 확정 주제와 분석 흐름을 확인합니다.
2. [`docs/competition/`](docs/competition/)에서 제출요건과 평가기준을 확인합니다.
3. 데이터 수집 전 [`data/README.md`](data/README.md)에 출처·URL·수집 시점·사용 변수를 기록합니다.
4. 원본 데이터는 `data/raw/`에 보관하되 GitHub에는 올리지 않습니다.
5. 탐색 분석은 `notebooks/`, 재사용할 전처리·분석 로직은 `src/`에 작성합니다.
6. 최종 표와 그래프는 각각 `results/tables/`, `results/figures/`에 저장합니다.
7. 국면판 관련 코드는 `dashboard/`에서 관리합니다.

브랜치 생성부터 Pull Request까지의 자세한 절차는 [`CONTRIBUTING.md`](CONTRIBUTING.md)를 확인해 주세요.

## Project Structure

```text
Changwon-Industry-Employment-Monitor/
├── data/
│   ├── raw/             # 원본 데이터: Git 추적 제외
│   ├── processed/       # 전처리 완료 데이터
│   ├── external/        # 외부 기관 보조 데이터
│   └── README.md        # 데이터 카탈로그
├── notebooks/           # 탐색 및 분석 노트북
├── src/                 # 재사용 가능한 Python 모듈
├── dashboard/           # 창원 산업·고용 국면판
├── results/
│   ├── figures/         # 분석 결과 그래프
│   └── tables/          # 분석 결과 표
├── docs/
│   ├── competition/     # 공모전 공고 및 공식 자료
│   ├── planning/        # 최종 주제와 프로젝트 기획
│   └── references/      # 수상작·정책 등 참고자료
├── README.md
├── CONTRIBUTING.md
├── .gitignore
└── requirements.txt
```

## Data and Security Rules

- 원본 데이터는 수정하지 않습니다.
- `data/raw/`의 실제 파일은 Git에 커밋하지 않습니다.
- API 키, 비밀번호, 인증파일, 개인정보는 저장소에 올리지 않습니다.
- 외부 배포 제한이 있는 데이터는 GitHub에 포함하지 않습니다.
- 분석 결과는 코드로 재생성할 수 있도록 출처와 처리 과정을 기록합니다.
- 데이터로 확인하기 전에는 디커플링, 문제 업종, 필요 정책 등을 결론으로 단정하지 않습니다.

## Current Status

- [x] GitHub 저장소 및 기본 폴더 구조 생성
- [x] 공모전 공고·최종 주제·초기 참고자료 정리
- [x] 원본 데이터 및 민감정보 제외 규칙 설정
- [ ] 핵심 데이터 출처 확정 및 수집
- [ ] 데이터 정제·결합
- [ ] 전체 및 업종별 분석
- [ ] 국면판 개발
- [ ] 분석보고서 및 발표자료 작성

## Documents

- [Git 브랜치 및 협업 방법](CONTRIBUTING.md)
- [데이터 카탈로그와 관리 규칙](data/README.md)
- [최종 주제 및 분석 계획](docs/planning/final-topic.txt)
- [공모전 공식 자료](docs/competition/)
- [참고자료 사용 시 주의사항](docs/references/README.md)
