# 최종 저장소 정리·재현 QA 요약

검증일: 2026-09-19 (Asia/Seoul)

## 1. 최종 폴더 구조

정상 작업 영역은 `data → src → notebooks → outputs/final_model → reports` 순서로 읽을 수 있게 정리했다. 과거 실험과 검증은 `logs/experiments`, `logs/validation`로 분리했다.

## 2. outputs/final_model 구조

최종 산출물은 `01_core`, `02_triage`, `03_electre_smaa`, `04_external_evidence`, `05_handoff`, `06_report_assets`의 여섯 단계만 사용한다. 전역 `outputs/tables`, `outputs/figures`는 제거했다.

## 3. src에 남긴 production 코드

`core`, `triage`, `electre`, `evidence`, `handoff`, `pipeline`, `utils`만 남겼다. 파일명과 패키지 경계가 최종 분석 흐름과 일치한다.

## 4. scripts에서 src로 이동한 코드

최종 실행·수집 코드는 `src/evidence`, `src/pipeline`, `src/triage`, `src/electre`로 통합했다. 검증 전용 코드는 `logs/validation/code`로 이동했으며 `scripts/`는 제거했다.

## 5. experiments 이동

후보모형, 전체 ELECTRE 실험, hybrid/rolling-backtest/parameter 탐색, 과거 노트북과 과거 후보 산출물은 `logs/experiments` 아래 원 작업명으로 보존했다.

## 6. validation 이동

강건성·재현성·민감도·holdout·과거 QA·KEPCO 강건성 산출물과 검증 코드는 `logs/validation`에 보존했다.

## 7. 삭제 항목

중복 임시파일, Python/Jupyter/pytest 캐시, 비어 있는 `scripts`, `tmp`, `src/model` 폴더를 삭제했다. 원자료와 유효한 실험·검증 기록은 삭제하지 않았다.

## 8. data 구조

최상위 데이터 폴더는 `raw`, `processed`이며, 하위는 KICOX·PPI·EIS·KEPCO·관세청·고용보험 등 자료 출처 기준으로 정리했다. 최종 모형용 결합 입력만 `data/processed/final_model`에 둔다.

## 9. notebook 구조

`00_data_preparation`부터 `05_final_results`까지 STEP0~STEP5로 정리했다. 각 노트북은 H1 1개, Takeaway, 분석 질문, `config.*` 입력·출력표, 전체 흐름, 관찰·해석·한계를 갖는다. 6개 노트북 모두 새 경로에서 실행됐고 HTML 실행본은 `outputs/final_model/06_report_assets/notebooks`에 생성했다.

## 10. 전체 pipeline 재실행 결과

- 활성 테스트: 63 passed
- core panel: 180행
- Triage: 관찰 128, 추가확인 35, 우선점검 17
- 선택적 ELECTRE·SMAA: 35행
- 외부근거 요약: 10행
- KEPCO 법정동×KSIC: 월 41,508행, 분기 13,869행, QA 전체 통과
- STEP0~STEP5 notebook: 6/6 실행 통과

## 11. 정리 전후 결과 동일성

핵심 결과 CSV의 바이트 SHA-256이 정리 전 기준과 모두 같다.

| 산출물 | 행 | SHA-256 동일 |
|---|---:|---|
| core panel | 180 | `3B10A04A…CE222` |
| triage panel | 180 | `A328C967…3C1A` |
| triage latest | 10 | `4021BD11…1FD` |
| ELECTRE·SMAA review cases | 35 | `E80D04C8…7F17` |
| external evidence summary | 10 | `56DA97BB…1E78` |
| explanation trace | 10 | `6E82B898…8E05` |

원자료는 정리 전후 모두 618개, 718,046,537바이트이며 파이프라인 내부 원자료 불변 검사도 통과했다. 경로만 출처별로 이동했고 파일 내용은 수정하지 않았다.

## 12. Git 분리 원칙

커밋은 `model-experiments`, `model-decision`, `external-evidence` 범주로 분리한다. 원자료 대용량 파일은 `.gitignore` 정책대로 커밋하지 않고, 수집 증빙·metadata·production 코드·가공 결과만 외부자료 커밋에 포함한다.
