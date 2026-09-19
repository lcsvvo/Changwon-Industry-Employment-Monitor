# 로그 보존 기준

- `experiments/`: 폐기된 후보모형, 전체 ELECTRE/MRSort, hybrid 구조, 과거 노트북과 코드, 후보 산출물.
- `validation/`: robustness, reproducibility, sensitivity, temporal/hybrid validation, 과거 QA와 저장소 정리 기록.

`experiments/`·`validation/` 아래의 코드는 실행 당시의 경로와 모듈명을 그대로 보존하므로 현재 pipeline 구조와 직접 호환되지 않을 수 있습니다. 기록 보존이 목적이므로 현재 구조에 맞춰 고치지 않습니다.

현재 최종 실행에는 `logs/`의 파일을 입력으로 사용하지 않습니다. 최종 재실행 기준자료는 `data/processed/final_model/`, 최종 결과는 `outputs/final_model/`에 있습니다.
