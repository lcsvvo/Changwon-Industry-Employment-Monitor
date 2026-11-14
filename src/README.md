# Source

| Folder | Role |
|---|---|
| `core/` | KICOX 정제, Q1 방향, Q2 규모, Q3 시간 분석 |
| `triage/`, `electre/` | 점검 단계 계산, 추가확인 사례의 선택적 재검토 |
| `evidence/` | 외부자료 수집, 정제, 매핑과 근거 생성 |
| `handoff/`, `export/` | 진단카드 생성, 등록 분석본 저장과 비교 |
| `policy/`, `copilot/` | 공식 정책과 채용 RAG, Gemini 근거 설명 |
| `workflow/`, `app/` | 점검 기록과 인계, Streamlit 화면 |
| `pipeline/`, `review/` | 최종 산출물 생성과 보완 분석 |

## Run App

Python 3.11 이상, 저장소 루트 기준 실행.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run src/app/main.py
```

- **기본 실행**: 등록 분석본과 공식 정책 RAG는 API 키 없이 사용 가능. 채용공고 화면은 가상 공고 예시를 표시합니다.
- **로컬 채용 분석**: 원자료 이용 권한이 있는 환경에서 로컬 가공 파일을 준비한 뒤 `DSS_LOCAL_WORK24=1`을 설정하면 실제 자료를 조회할 수 있습니다.
- **선택 기능**: `GEMINI_API_KEY`는 문장 생성과 공식기관 최신검색, `BIZINFO_API_KEY`는 기업마당 최신 공고 조회에 사용.
- **설정**: 환경변수 또는 로컬 `.env`, `.env.txt`에 키 저장. `COPILOT_WEB_PROVIDER=off`로 외부 최신검색 해제 가능.
- **업무 기록**: 기본 로컬 SQLite 경로는 `app_state/workflow.db`. 배포 환경의 재시작, 재배포 시 보존을 보장하지 않음.

## Analysis

- **전체 파이프라인**: `python src/pipeline/run_final_pipeline.py --skip-tests`.
- **입력**: [Data 안내](../data/README.md)의 원자료와 가공 패널 필요.
- **실행 순서**: [RUNBOOK](../outputs/final_model/RUNBOOK.md) 참고. 분석 실행은 저장된 결과를 갱신함.
- **기록 경로**: 일부 분석, 보고서 생성 코드는 `logs/validation/`과 `logs/experiments/`의 저장 자료를 참조하므로 해당 경로 유지.

