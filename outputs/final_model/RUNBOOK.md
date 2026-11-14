# Run Pipeline

저장소 루트, Python 3.11 이상 기준. 로컬 원자료를 준비한 뒤 실행.

```powershell
python src/pipeline/run_final_pipeline.py --skip-tests
```

- **처리**: KICOX 정제, Q1–Q3, Triage, 외부근거, 진단카드와 결과 Notebook 생성. 네트워크 수집은 별도.
- **출력**: `data/processed/`, `outputs/final_model/`, 일부 `logs/validation/` 갱신.
- **옵션**: `--skip-notebook`으로 결과 Notebook 실행 제외 가능. 테스트 코드는 공개 저장소에 포함하지 않아 `--skip-tests` 사용.
- **외부 수집**: `src/evidence/collection/`의 수집기와 출처별 API 키 필요. 키는 환경변수나 로컬 `.env`, `.env.txt`에서만 관리.
- **후속 보완**: `src/review/`의 입력과 저장 결과는 [보완 결과 안내](06_report_assets/professor_feedback/README.md) 참고.
