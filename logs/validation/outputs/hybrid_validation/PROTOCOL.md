# CW-HYB-1.0 — 고정 출력 단계형 결합 후보

작성일: 2026-09-18. 사용자 요청의 Primary Hybrid 및 Strict Serial Hybrid **두 개만** 실행한다. 이 문서는 신규 Hybrid 성능을 계산하기 전에 결합 규칙과 평가 범위를 고정한다. 이미 CW-RBT-1.0의 결과를 본 후 제안된 후속 설계이며 새 독립 사전등록 또는 성능개선 검증이 아니다.

분석명: 재구축 패널 기반 사후적 시간외 정합성 검증(retrospective reconstructed-panel temporal validation)의 고정 출력 기반 Hybrid workflow 후보 평가.

## 1. 변경하지 않는 입력과 평가 정의

- ELECTRE: 기존 rolling `electre_fixed`만 사용. 감사 보정 고용 이력, crisp q=p=0, 가중치 (.2,.2,.3,.3), lambda=.5, b1=(100,2,5,2), b2=(500,5,10,4), veto 없음, 고용증거 gate, 완전자료 정책을 그대로 유지한다.
- Triage: 기존 rolling `triage_final`만 사용. E/R/A/P threshold, 반복 조건, 300인 gate, 생산 보강, 부분결측 정책 모두 유지한다.
- 원 수준부터 새 판정을 만들거나 기존 판정을 변경하지 않는다. 기존 `predictions_long.csv`에서 두 출력만 읽는다. 6003 theta를 결합하거나 검색하지 않는다. RC/VRC 사용 없음.
- Outcome: 기존 `outcomes_long.csv`의 primary/h=2 라벨만 읽는다. 신규 라벨·outcome·threshold·horizon을 만들지 않는다.
- 주 평가: 2022Q1~2025Q4, 기존 `sample_membership.csv`의 `paired_primary_h2`와 기존 MAIN evaluation의 포함행이 정확히 같은 140행.
- 두 cutoff: stage>=1 CHECK/추가확인 이상, stage==2 PRIORITY/우선점검. N, positives, TP/FP/FN/TN, recall, precision, FPR, balanced accuracy, alert rate. 분모0은 NA, 독립검정·CI·F1·AUC·단일 최적순위 없음.
- 사전 희소/집중 경고: 양성<10 또는 양성업종<3 또는 양성origin<3이면 INSUFFICIENT_EVIDENCE. 이 경고를 넘더라도 일반 우열을 선언하지 않는다.

## 2. 고정 결합 규칙

E∈{-1,0,1,2}, T∈{0,1,2}. -1은 ELECTRE UNDETERMINED다. 현재 패널에 없는 Triage 핵심자료보류(T=-1)가 발견되면 자동 결합을 새로 정의하지 않고 중단·보고한다.

Primary H(E,T):

1. E=-1 → T (triage fallback; 자료 미확인 플래그 유지).
2. 그 외 T=2 → 2 (strong-signal override; E=0이면 우회 승격).
3. 그 외 E>=1 → 1.
4. 그 외 → 0. 특히 E=0,T=1은 관찰이며 triage CHECK가 제거되는 경우를 반드시 공개한다.

Strict Serial S(E,T):

1. E=-1 → T (동일 fallback).
2. E=0 → 0 (T=2도 gate에서 소실).
3. E>=1,T=2 → 2.
4. E>=1,T<2 → 1.

Primary의 priority 집합은 Triage priority와 **정의상 동일**하다. 완전관측에서 Primary CHECK+는 (E CHECK+) OR (T priority), Strict CHECK+는 E CHECK+다. 두 Hybrid의 유일한 차이는 E=0,T=2다. 이를 성능 발견/향상이라고 쓰지 않는다. Primary는 완전 직렬이 아니라 screening에 더해 모든 업종의 Triage 강신호를 확인해야 하는 예외 경로가 있는 구조다.

## 3. 성능 계산 전 논리 감사

- 두 모형은 같은 생산·고용 입력을 공유한다. 결합이 독립증거 또는 새 정보를 더하지 않는다.
- E 단계2만으로 Hybrid priority를 주지 않고 T=2로만 승격하므로 역할을 명시적으로 분리한다.
- E=0,T=2 override는 강한 명시적 신호를 보존하는 안전장치다. 하지만 현재/미래 outcome으로 정의를 수정하지 않는다.
- fallback은 알려진 신호의 최소판정과 생산 미확인 표시를 동반해야 한다. 결측 해소, 양성 포착 개선 또는 완전한 판정확실성을 의미하지 않는다.
- T=1,E=0 신호는 사라질 수 있다. 이를 부작용으로 공개하되 좋은 결과를 위해 union이나 추가 Hybrid를 만들지 않는다.
- 관찰=정기 모니터링(위기 부재 확정 아님), 추가확인=자료/기업 확인후보 등록, 우선점검=담당자 검토의 우선순위 부여(지원선정/법정위기 판정 아님).
- 업무량·현장 판단·기관 수용성이 없으므로 실제 행정효율/비용 절감의 우위는 검증할 수 없다. 최종모형 교체 여부는 구조 타당성과 비용·미확인 사항을 함께 판단한다.

## 4. 실행 순서와 고정된 기술적 하위표

1. CW-RBT-1.0 PROTOCOL/FREEZE, rolling 판정·라벨·mask의 lock/해시 확인. 보호 파일 전체 해시 기록.
2. 결합규칙·스크립트·입력 해시를 EXECUTION_LOCK.json에 저장.
3. ELECTRE×Triage 교차표를 **Hybrid 성능보다 먼저** 계산한다. 주 paired140 및 전체 origins160 각각 E=-1/0/1/2 × T=0/1/2 전체12셀을 저장. N, primary 양성수/율, 대표키(분기·업종순 최초3개)를 기록. 비어 있는 셀은 N=0, 양성률=NA.
4. 고정 두 규칙을 판정 출력만으로 적용, 예측 파일 저장/해시잠금. 미래 라벨은 결합함수 입력이 아니다.
5. A ELECTRE / B Triage / C Primary / D Strict를 주140행, EMP<300·>=300 층에서 두 cutoff로 비교. 업종10개 및 유효 origin14개 재집계도 통합 CSV에 기록하며 새 후보·새 실험으로 선발하지 않는다.
6. 생산미확인20행의 fallback 단계·양성·선별 및 지표는 운영 범위로 따로 표시한다. ELECTRE 보류는 관찰/FN으로 바꾸지 않고 지표NA로 표시한다. 전체160행 판정률/보류/capture는 운영 포괄성이지 공통paired 성능이 아니다.
7. 주요 판정 조합과 기계·목재종이·운송장비·철강을 별도 해설한다. 대표행은 outcome에 무관하게 각 조합·업종의 분기순 최초행을 선택. 사례 CSV에는 모든160 origin을 포함한다. 외부사건 audit는 정량 라벨에 사용하지 않는다.
8. 15개 요청 섹션 순서의 REPORT 작성, 공모전 관점은 방법론과 구분한다. 기존 최종파일의 수정 대상은 목록만 제안한다.

## 5. 출력·보존·중단

`outputs/hybrid_validation/` 아래 hybrid_predictions.csv, hybrid_metrics.csv, hybrid_overlap.csv, hybrid_case_comparison.csv, REPORT.md 및 소수 lock/metadata만 작성한다. parameter·업종·분기별 개별 파일을 생성하지 않는다. 기존 final triage, rolling, ELECTRE audit, 외부사건 audit는 변경하지 않는다. lock/결과가 이미 있으면 덮어쓰기를 거부한다.

입력 해시 불일치, key/eligibility 불일치, 기존 A/B 지표 재현 실패, Triage 핵심자료보류, 정의 변경 필요 문제는 성능 계산 중단·보고 조건이다. unfavorable/NA 결과를 보존한다. 실제 지원 결정·기관 통보·새 행정시스템 구축은 범위 밖이다.
