# 최종 파이프라인 실행

저장소 루트에서 실행합니다.

```powershell
python src/pipeline/run_final_pipeline.py
```

이 명령은 로컬 원자료로 KICOX master와 Q1~Q3를 재구축하고, Triage, 선택적 ELECTRE/SMAA 결합, 외부근거, handoff, 최종 QA와 결과 노트북을 차례로 갱신합니다. 네트워크 수집은 수행하지 않습니다.

단계별 실행이 필요하면 다음 순서를 사용합니다.

```powershell
python src/core/build_changwon_master.py --no-compare
python src/core/build_kicox_analysis_panel.py
python src/evidence/build_validation_panels.py
python src/evidence/build_ppi_industry_panel.py
python src/triage/run_triage.py
python src/evidence/build_industry_crosswalk.py
python src/evidence/build_hs6_universe.py
python src/evidence/build_context_layer.py
python src/evidence/build_kepco_legal_dong_panel.py
python src/pipeline/build_final_outputs.py
python -m pytest -q
python src/pipeline/execute_final_notebook.py
```

주요 결과:

- CORE: `01_core/`
- Triage: `02_triage/`
- 선택적 ELECTRE/SMAA: `03_electre_smaa/`
- 외부근거: `04_external_evidence/`
- 담당자 인계: `05_handoff/`
- 보고서용 자산과 QA: `06_report_assets/`

채용공고 등 외부자료를 다시 수집할 때만 `src/evidence/collection/`의 수집기를 별도로 실행합니다. 인증정보는 환경변수 또는 로컬 `.env.txt`에서만 읽습니다.
