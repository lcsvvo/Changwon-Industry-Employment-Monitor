# 저장소 구조

```text
data/
├── raw/                         # 출처별 원자료
└── processed/                   # 출처별 가공자료 + final_model 기준자료
src/
├── core/                        # KICOX 전처리, Q1·Q2·Q3
├── triage/                      # Triage 규칙과 실행
├── electre/                     # 추가확인 35건 선택적 ELECTRE/SMAA
├── evidence/                    # 외부자료 처리·수집
├── handoff/                     # 설명·진단카드·routing
├── pipeline/                    # 전체 실행과 최종 산출
├── policy/                      # 정책 원장 bootstrap, PDF/HTML 추출·검색, Work24 append-only 외부근거
├── export/                      # 최종 산출물 → 불변 Snapshot (재계산 없음) · 분석본 버전 비교(diff) · 등록 문서 인용
├── workflow/                    # 점검 후보·점검 건·점검 시점(최초/재점검)·현장확인·지원 기능·인계·사후검토·감사 (PostgreSQL 기준 ORM, Alembic migrations/, identity 경계, function_catalog.json)
├── app/                         # Streamlit 점검연계 화면
└── utils/
notebooks/                       # 최종 데이터 준비·CORE·결과
outputs/
└── final_model/
    ├── 01_core/
    ├── 02_triage/
    ├── 03_electre_smaa/
    ├── 04_external_evidence/
    ├── 05_handoff/
    └── 06_report_assets/
snapshots/<기준분기>/v<n>/        # 판정 당시 분석본(추가만, 덮어쓰기 없음)
LLM/sources/official/             # 공식 HTML 원문 corpus(PDF 원문은 루트 파일을 중복 없이 참조)
reports/                         # 최종 문서만
logs/
├── experiments/                 # 후보모형·과거 실험
└── validation/                  # 강건성·재현성·민감도·QA
```

`outputs/`의 정상 산출 영역은 `final_model/` 하나뿐입니다. `scripts/`, 전역 `outputs/tables/`, 전역 `outputs/figures/`는 사용하지 않습니다.
