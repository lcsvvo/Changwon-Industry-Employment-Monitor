# 창원국가산단 산업·고용 전환진단

창원국가산단의 KICOX 생산·고용을 Q1 상태, Q2 규모, Q3 시간축으로 읽고, Triage로 관찰·추가확인·우선점검을 구분하는 최종 저장소입니다. `추가확인` 35건에만 ELECTRE TRI-B와 SMAA-TRI를 보조 적용하며, 외부자료는 판정 이후의 확인근거로만 사용합니다.

```text
KICOX 생산·고용 → Q1 → Q2 → Q3 → Triage
→ 추가확인만 ELECTRE TRI-B → SMAA-TRI
→ External Evidence → Human Review / Handoff → 기존 지원체계 Routing
```

## 어디를 보면 되는가

- `data/raw/`: 출처별 원자료. 파이프라인은 수정하지 않습니다.
- `data/processed/`: 출처별 가공자료와 `final_model/` 재실행 기준자료입니다.
- `src/`: 최종모형 production 코드만 있습니다.
- `notebooks/`: `00` 데이터 준비 뒤 `01` CORE → `02` Triage → `03` 모형 발전·실험 → `04` 외부근거 → `05` 최종결과 순서로 읽는 분석보고서입니다.
- `outputs/final_model/`: 최종 결과의 유일한 위치입니다.
- `reports/`: 최종 방법론·데이터 역할·결과·QA 문서입니다.
- `logs/experiments/`: 과거 후보모형과 실험입니다.
- `logs/validation/`: 강건성·재현성·민감도·과거 QA입니다.

핵심 결과는 [최종 방법론](reports/final_methodology.md), [Triage 180행](outputs/final_model/02_triage/tables/triage_panel.csv), [선택적 ELECTRE/SMAA 35행](outputs/final_model/03_electre_smaa/tables/electre_smaa_review_cases.csv), [Triage→ELECTRE/SMAA와 실험 HTML](outputs/final_model/06_report_assets/triage_electre_experiments.html), [외부근거 요약](outputs/final_model/04_external_evidence/external_evidence_summary.csv), [인계 trace](outputs/final_model/05_handoff/tables/explanation_trace.csv)에서 확인할 수 있습니다.

현재 결과는 180행이며 관찰 128, 추가확인 35, 우선점검 17입니다. 선택적 ELECTRE 결과는 OBSERVE 2, CHECK 9, PRIORITY 20, UNDETERMINED 4이고 원 Triage 단계를 자동 변경하지 않습니다.

## Streamlit 앱: 행정 의사결정지원 화면

등록된 분석본(`snapshots/`)을 읽어 담당자가 업종별 판정 근거를 확인하고, 현장 점검과 기존 공식 지원체계로 연결하도록 돕는 화면입니다. 앱은 판정을 다시 계산하지 않고, 원인이나 지원 대상을 자동으로 확정하지 않습니다.

| 화면 | 내용 |
| --- | --- |
| 업종 진단 | 분기·업종 선택, 진단 판정 근거, 보조 산업지표, 분기별 판정 추이, 채용시장 보조 신호(Work24), 현장 확인 질문, 지원체계 검토 경로, 담당자 인계용 진단서 발급(HTML·JSON) |
| 점검 관리 | 점검 후보 → 점검 시작 → 진행 중·종결 점검 건 기록(현장 확인, 지원 필요 기능, 인계) |
| 정책·지원 연계 | **공식 지원 연계**: 선택 업종·분기와 연결 가능한 공식 지원사업 카드, 기업마당 최신 공고, 참고 기관, 공식 근거 직접 검색<br>**공모전 팀 제안**: 전 업종 공통 정책 제안 8건. 현재 시행 중인 공식 지원사업이 아닙니다. |
| 설정·정보 | 담당자 이름, 분석 버전, 분석 정보·시스템 상태·AI 연결 설정, 방법론·데이터 기준, 변경 기록 |
| 행정 AI 비서(오른쪽) | 등록 진단 → 공식 문서(RAG) → 기업마당 최신 공고 순으로 근거를 찾아 답하고, 답변마다 근거 유형을 표시합니다. 공모전 팀 제안 탭에서는 팀 제안 원문만 근거로 답합니다. |

### 실행 방법

Python 3.11 이상(개발·검증 환경: Python 3.14, Streamlit 1.64)에서 저장소 루트 기준으로 실행합니다.

```powershell
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
streamlit run src/app/main.py
```

브라우저에서 `http://localhost:8501`이 열립니다.

- API 키가 없어도 모든 화면이 동작합니다. 이 경우 AI 문장 생성과 기업마당 최신 공고만 `미설정`으로 표시되고, 등록 진단·공식 문서 기반 답변은 그대로 동작합니다.
- 업무 기록 DB(`app_state/workflow.db`)와 AI 비서 감사 로그는 처음 실행할 때 로컬에 자동으로 만들어집니다. 둘 다 `.gitignore` 대상이라 각자 PC에만 남고 GitHub에는 올라가지 않습니다.

### AI 비서·기업마당 키 설정(선택)

1. [`.env.example`](.env.example)을 복사해 저장소 루트에 `.env.txt`(또는 `.env`)로 저장합니다.
2. `GEMINI_API_KEY`(Gemini)와 `BIZINFO_API_KEY`(기업마당)를 각자 발급받아 채웁니다.
3. 앱을 다시 시작합니다. 연결 여부는 `설정·정보 → AI 연결 설정`에서 확인할 수 있습니다.

`.env.txt`와 `.env`는 `.gitignore` 대상입니다. 실제 키는 커밋하지 마세요. Gemini 무료 사용량을 넘기면(HTTP 429) 등록 진단 문장이나 팀 제안 원문 요약으로 자동 대체되어 답변이 표시됩니다.

### 개발 메모

- 앱 코드: `src/app/`(`main.py` 화면, `ui.py` HTML 조각, `view_models.py` 표시용 가공, `team_copilot.py` 팀 제안 답변, `styles/dashboard.css`)
- AI 비서: `src/copilot/`(라우팅·근거 경로·guardrail), 정책 근거: `src/policy/`, 공식 원문: `LLM/sources/`
- `tests/`는 GitHub에 올리지 않고 각자 로컬에서만 사용합니다(`pytest -q`).

## 분석 파이프라인 실행

Python 환경에 `pip install -r requirements.txt`를 실행한 뒤 저장소 루트에서 다음 명령을 사용합니다.

```powershell
python src/pipeline/run_final_pipeline.py
```

개별 단계와 산출 위치는 [실행 안내](outputs/final_model/RUNBOOK.md)에 정리되어 있습니다. 외부 API 수집은 최종 오프라인 파이프라인과 분리되어 있으며, 필요할 때만 `src/evidence/collection/`의 수집기를 실행합니다.

과거 전체 180행 ELECTRE, hybrid, rolling backtest, robustness, reproducibility 결과는 최종 산출물이 아닙니다. 필요할 때만 [logs 안내](logs/README.md)를 확인하세요.
