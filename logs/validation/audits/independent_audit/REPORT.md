# 독립 감사·수정·재실험 보고서

## ① Executive Summary

최종 판단: **HYBRID**. Q1 상태·Q2 규모·Q3 시간과 명시적인 후속 확인 질문을 운영 출력의 중심에 두고, ELECTRE 계열은 연구진 규범에 조건부인 배정/민감도 층으로 유지한다. 단일 등급 자동 우선순위나 정책 승인 모형으로 채택하지 않는다. 단순 규칙으로 바꾸면 문제가 해결된다는 증거도 없다.

1. 원자료→마스터→국면 패널 5종이 재현됐고, 기존 핵심 수치도 재현됐다. 수정 전 테스트는 **277 passed, 2 skipped**다.
2. I3는 최종 양립공간 밖의 고정 파라미터까지 평가했다. 무교란에서도 고용중시 crisp 포함률은 **0.85**다. 기존 Jaccard는 **무제약 공간**의 수치다. 따라서 서로 다른 집합을 비교한 기존 판정은 운영 적합성의 종합 증거가 될 수 없다.
3. 교란은 g를 독립적으로 흔든 것이 아니라 원 수준을 흔들었지만, 같은 분기의 원값과 lag에 다른 개정을 적용했다. 이를 고치고 **비교 가능한 과거 고용 이력**으로 g4를 계산하니 **40행**의 지속기간이 바뀌었다. 재분류 위험 기간에서 런을 끊고 Q1 상태는 보존했다.
4. 개정 pool의 큰 고용 수정은 알려진 **2024Q3 원파일 오류 정정**에 집중됐다. 이를 제외한 시나리오에서 유지율은 0.990~0.993이지만, 표본이 부족해 일반적인 안정성을 입증하지 못한다. 오류 정정을 포함한 스트레스도 함께 남겼다.
5. 연속공간 외부범위 LP와 실제 feasible witness로 **154/160행**의 집합을 확인했다(수치 허용오차 조건). **6행**은 미해결로 남겼다. 기존 표본이 놓친 배정 **5건**이 있어 ‘표본 공통=필연’은 실제로 틀렸다.

새 합격선을 만들어 통과시키지 않았다. legacy `INTERVAL_BLOCKED_BY_I3` 기록은 보존한다. HYBRID는 수정된 도구의 구조에 대한 판단이며, legacy 기준 통과 또는 현장 정책효과 입증 선언이 아니다.

## ② 재현한 baseline

근거: [기준선 원본·실행결과](baseline/), [원자료 재구축 대조](raw_rebuild/comparison.json), [18개 후보 재실행](baseline/point_candidates_18.csv).

| 항목 | 수정 전 재실행 |
|---|---|
| 분석 행 / 완전관측 / 판별표본 | 180 / 160 / 89 |
| 허용공간 | 합계 w=1, 각 w=.10~.40; λ=.50~.75; p=(0~100,0~2,0~5,0~2); q=0~p/2; 경계 고정; veto 없음 |
| 표집 | Dirichlet(1,1,1,1) 기각표집 w; 균등 λ·p, 조건부 균등 q; 6000개, seed=2026 |
| 무제약 / RC / RC+VRC 표본 | 6000 / 1745 / 447 |
| 판별표본 공통 배정 비율 | .011236 / .101124 / .516854 |
| 평균 표본 가능 단계 수 | 1.29375(완전관측 기준) |
| I3 | .8928177083 |
| Jaccard | 판별 .9301498127 / 완전관측 .9477291667(무제약 1000표본) |
| 18개 후보 C3 | 모두 미달, 최대 .935234375 |
| 최신 표본 배정 | 관찰 공통 3개, 두 단계 범위 7개 |

기존 2025Q1~2026Q2는 이미 본 개발자료다. 이번 실험 역시 신규 holdout 검증이 아니다. 입력·설정은 `baseline/hashes.json`으로 고정했으며 기존 실패 기록은 지우지 않았다.

실제 테스트 실행 기록:

| record | tests | failures | errors | skipped | seconds |
|---|---|---|---|---|---|
| baseline_tests.xml | 279 | 0 | 0 | 2 | 731.6280 |
| modified_tests.xml | 285 | 0 | 0 | 2 | 321.9610 |
| final_tests.xml | 287 | 0 | 0 | 2 | 281.2970 |

현재 수정본 전체 재실행 대조: [replay_verification.json](replay_verification.json). 원자료 CSV 5종과 수정 전 18후보의 수치도 별도 재실행으로 대조했다. 테스트 통과는 정책 타당성의 입증이 아니라 구현 검산이다.

건너뛴 2건은 파라미터가 없는 환경 전용 테스트와, 아직 Git HEAD에 없는 `electre.py`의 append-only 비교 테스트다. 후자는 작업 시작 전 파일 스냅샷·해시와 기존 구현 대조로 보완했다. 오류·실패를 skip으로 바꾼 것이 아니다.

## ③ 이전 지적사항 재검증

| 지적 | 판정 | 구분 | 심각도 | 근거 | 파일 |
|---|---|---|---|---|---|
| RC/VRC 독립성 | CONFIRMED | 검증설계 | 중대 | prereg AM3·AM4·AM6의 선행 결과 인지 기록. 다만 작성자의 인지 상태와 실제 등록 시각은 파일만으로 독립 검증 불가. | config/model_revalidation_prereg.yaml; baseline/snapshot |
| VRC4 단일 규범 의존 | CONFIRMED | 정책선호 | 중대 | 양립 표본 1745→447. 지속 2·3·4분기 모두 899/6000 통과로 동일. | parameter_spaces.csv; summary.json |
| 합격선의 운영 근거 | PARTIALLY_CONFIRMED | 검증설계 | 중대 | 합격선·개정 이력은 명시. 실제 담당자 비용·점검 용량에 따른 도출 근거 없음. | config/model_revalidation_prereg.yaml |
| I3/Jaccard 정합 | CONFIRMED | 구현/평가대상 | 치명적 | I3 고정 6조합 일부는 양립공간 밖. C3c는 무제약 1000표본. 같은 최종 구간 검증으로 취급할 수 없음. | i3_zero_noise.csv; src/model/revalidation_phase5.py |
| 필연배정 명칭 | CONFIRMED | 추론 | 치명적 | 표본 공통 배정을 필연/확정으로 표기. 실제 feasible witness가 표본 누락 배정 5건을 확인. | continuous_space_certificates.csv; feasible_witnesses.json |
| MRSort 추가 효용 부재 | PARTIALLY_CONFIRMED | 방법선택 | 중대 | count2와 실제 차이는 2/160행. 다만 중요성을 판정할 현장 정답은 없으므로 무용함까지 입증되지 않음. | alternative_changed_cases.csv |
| g1·g2·g4 중복 | PARTIALLY_CONFIRMED | 지표설계 | 중대 | 공통 원계열이나 각각 배정을 바꾸는 행 존재. 규모/강도/지속 차원이 완전히 동일하지 않음. | criterion_decision_effects.csv |
| 교란의 비현실성 | PARTIALLY_CONFIRMED | 구현/자료생성 | 중대 | g 자체 독립교란은 아님. 원 수준과 lag의 독립 복원추출로 같은 분기 두 값이 불일치. 원파일 오류 정정이 pool에 혼입. | src/model/perturb.py; vintage_by_quarter.csv |
| 기존 예측 검증의 과장 | CONFIRMED | 해석 | 중대 | 관측된 Spearman 차이로 원리적 열위·모든 파라미터 불가능을 선언. 해당 전체 명제는 입증되지 않음. | config/model_revalidation_prereg.yaml invalidated_gates |
| 180행을 모두 독립 취급 | NOT_CONFIRMED | 검증설계 | — | 업종 군집 bootstrap·업종 leave-out이 이미 존재. 다만 기존 교란에는 시간/업종 결합구조가 없음. | src/model/resample.py; revision_by_period.csv; revision_leave_industry_out.csv |
| 등급과 점검순서 불일치 | PARTIALLY_CONFIRMED | 운영 | 중대 | 후속 질문·UNDETERMINED 라우팅은 기존에 존재. 실제 담당자·용량·동률 처리 승인과 현장 효용 검증은 없음. | src/model/stage_actions.py; action_latest.csv |
| 설명비용/공모전 감점 | CANNOT_VERIFY | 외적평가 | — | 실제 심사위원 이해도나 감점은 저장소에서 검증할 수 없음. 연구용 부록과 운영 출력 분리는 가능. | REPORT.md 최종 구조 |
| 고용 게이트 효과 | NOT_CONFIRMED | 인과 설명 | 중대 | 6000×180 배정에서 gate 제거 변화 0. 고정 관찰의 원인을 게이트로 단독 귀속할 수 없음. | summary.json gate_changes |
| g2·g3 단위 오류 | PARTIALLY_CONFIRMED | 문서 | 경미 | 산식·config 표시 단위는 %로 맞음. prereg 일부 rationale과 전달 문구에 %p 혼용. 등록 원문은 보존하고 해석 정정. | src/model/config.py; config/model_revalidation_prereg.yaml |

이전 비평의 **전면적인 독립표본 비판, 원리적인 모형 열위, 단순규칙의 우월성**은 철회하거나 범위를 줄인다. g2·g3는 코드 표시가 이미 %였고, 기존 후속 질문과 결측 라우팅도 존재했다. 반면 표본 필연성, I3 평가대상 불일치, Jaccard 공간 불일치, 개정 시계열 불일치는 실행으로 확인했다.

## ④ 추가로 발견한 문제

- **개정 pool 구성:** 고용 50셀·생산 60셀이고 고용의 실질적 수정은 2024Q3 8셀과 2026Q1 2셀에 집중된다. 2024Q3는 일반 개정과 다른 잘못된 원파일 교체다. 원자료 재구축이 해당 무효 원파일 대체를 재확인했다. 공표 시점/개정 간격 열은 없어 동일한 vintage age의 통상 개정분포라고 확인할 수 없다.
- **g4 기간 절단:** 원 모형은 2022년 시작 분석창에서 런을 다시 세고 좌측절단 플래그를 남겼다. 숨겨진 정렬 오류는 아니다. 새 계산은 2018년부터 고용 이력을 사용하되 업종 재분류 시점을 가로지르는 전년동기 비교 4분기에서는 런을 끊고, 2022년 이후만 출력한다. 2020Q3~2021Q2가 해당한다. 재분류 이전부터 이어진 실제 감소기간 전체를 복원했다는 뜻이 아니라 **연속해서 비교 가능한 하회 분기 수**다. 초기 감사 개선안은 이 위험 구간을 무시해 기계/2022Q1을 13분기로 만들었으므로 기각·수정했고, 3분기로 보정했다. Q3의 ‘분석창 내 국면 런’과 후단 ‘고용 하회 런’은 구분한다.
- **실행의 쓰기 부작용:** Phase 4~6의 `write=False`가 후보 설정·카드·보고서·그림을 쓰고 있었다. 해당 쓰기를 조건문으로 보호했다. baseline은 별도 스냅샷에 보존했다.
- **가상사례의 실현 가능성:** 양의 고용 기준값 아래 `g1=0,g2=2`는 실제 원계열에서 동시에 나올 수 없다. VRC4는 ‘절대규모를 무시하는 추상적 선호 시험’으로는 쓸 수 있지만 실제 가능한 기업 사례라고 부르면 안 된다. g1이 작은 양수인 사례에서도 정책 의도를 확인해야 한다.
- **고정 점 모형과 양립공간:** 고용중시 w2+w4=.50<λ=.60이므로 VRC4를 위반한다. 이 점 배정을 VRC4 양립 구간 안에 넣으라고 요구한 I3는 정책관점 차이까지 실패로 계산했다.
- **4분기 블록의 퇴화:** 완전한 공동 개정 벡터 중 길이 4의 연속 구간이 하나뿐이다. 이를 반복하면 같은 계절의 t와 t−4 승수가 같아 YoY가 상쇄된다. 100% 유지율은 성공이 아니다. 블록 길이 2/분기 벡터는 별도 스트레스 가정으로만 유지한다.

공동 재표집에 실제 사용 가능한 donor 구간은 다음과 같다. 2분기 블록은 3개뿐이며 2026Q1은 짝이 없어 빠진다. 따라서 오류 정정의 노출 빈도가 분기별 표집과 달라진다. 더 현실적인 확률모형이라고 단정하지 않고 의존성 가정에 따른 스트레스로 해석한다. 2026Q2는 고용 개정값이 없어 완전한 공동 벡터에 들어가지 않는다.

| block_length | start | end | includes_known_file_error |
|---|---|---|---|
| 1 | 2024Q2 | 2024Q2 | False |
| 1 | 2024Q3 | 2024Q3 | True |
| 1 | 2024Q4 | 2024Q4 | False |
| 1 | 2025Q1 | 2025Q1 | False |
| 1 | 2026Q1 | 2026Q1 | False |
| 2 | 2024Q2 | 2024Q3 | True |
| 2 | 2024Q3 | 2024Q4 | True |
| 2 | 2024Q4 | 2025Q1 | False |
| 4 | 2024Q2 | 2025Q1 | True |

## ⑤ 수행한 실험 전체

| 실험 | 목적 | 관측 결과 | 판단 | 근거 파일 |
|---|---|---|---|---|
| E00 | 원자료→마스터→국면 재실행 | 5종 CSV 수치 허용오차 내 일치 | 유지 | raw_rebuild/comparison.json |
| E01 | 수정 전 실행 재현 | 447, I3=.8928177, Jaccard=.9301498/.9477292; 18/18 C3 미달 | legacy 기록 보존 | baseline/ |
| E02 | 같은 원계열 재사용·비교 가능한 과거 고용 이력 | g4 40행 변경; lag 값 일관성 테스트 통과 | 계산 정합성 수정 채택 | history_recalculation.csv |
| E03 | 고용 게이트 제거 | 1080000개 배정에서 변화 0 | 현재 공간에서는 중복; 보호 의도는 문서화 | summary.json |
| E04 | VRC4 제거·지속기간 2/4 비교 | 1745→447; 2/4 경계 동일 동작 | 규범 의존성 공개, 자동 승인 안 함 | parameter_spaces.csv |
| E05 | 연속공간 LP 외부범위+feasible witnesses | 154/160 집합 확인, 6행 미해결, 표본 누락 5건 | 표본 필연 용어 폐기; 미해결은 보수적 범위 | continuous_space_certificates.csv |
| E06 | 양립공간으로 I3·Jaccard 평가대상 일치 | 무교란 양립표본 포함률=1; 교란 지표 별도 재산출 | 수정 지표 채택, legacy 실패 삭제 안 함 | revision_metrics.csv |
| E07 | 일관된 cell별 개정 | 같은 분기 lag 재사용; 방법별 유지율 개선 보장 없음 | 독립 cell 가정의 비교용 | revision_metrics.csv |
| E08 | 분기 공동 개정 | 동일 donor 분기의 업종×변수 벡터 보존 | 스트레스 시나리오 유지 | revision_metrics.csv |
| E09 | 4분기 공동 블록 | 유효 donor 블록 하나 반복→YoY 승수 상쇄→모든 방법 유지율 1 | 퇴화 실험 기각; 성공으로 세지 않음 | revision_metrics.csv joint_blocks4 |
| E10 | 2분기 공동 블록·역방향 개정 | 여러 donor 블록; 원값/lag 일관성; 유지율 0.878~0.892 | 가정 민감도 유지, 현실 확률로 해석 안 함 | revision_metrics.csv joint_blocks2 |
| E11 | 알려진 2024Q3 오류정정 제외 | 유지율 0.990~0.993; 남은 고용 개정 2건뿐 | 통상개정 근거 부족; 본 스트레스 결과를 대체하지 않음 | vintage_by_quarter.csv |
| E12 | count2·증거군 규칙·명시적 4분기 규칙 | 실제 변경 행과 점검대상 변경·유지율 비교 | 성능 우위 채택 근거 없음; 정책 대안으로 병기 | alternative_changed_cases.csv |
| E13 | grouped 규칙에 4분기 충분조건을 OR로 추가한 초기안 | 기존 2분기 경로가 이미 수용하므로 전 행 동일(대수적으로 중복) | 중복 설계 기각; E12는 상대감소 단독 경로를 명시적으로 분리 | baseline/snapshot/src/model/audit_tools.py |
| E14 | 기준 지지 제거/기준 삭제·재정규화 | g1~g4 각각 배정 변화 존재 | 동일 정보라는 단정 기각 | criterion_decision_effects.csv |
| E15 | 업종·분기·업종제외 기술통계 | 모든 업종과 결측 20행 유지 | 독립표본 유의성 검증으로 표현하지 않음 | revision_by_industry.csv; revision_by_period.csv |
| E16 | 과거 이력의 재분류 위험 구간 보호 | 기계 2022Q1의 무분별한 전체이력 런 13을 비교 가능한 연속 3분기로 수정 | 초기 전체이력 개선안 수정; 이전 결과 별도 보존 | experiments/pre_classification_guard/; history_recalculation.csv |

실험 E13은 중복 규칙이어서 채택하지 않았다. E09의 100%도 기각했다. E11의 높은 수치만 취해 C3를 통과시켰다고 주장하지 않는다. 서로 다른 규칙·파라미터 불확실성 표현·원계열 개정 방식에서 반복되는 한계는 **선호의 외부 정당화와 개정 이력의 대표성 부족**이다.

## ⑥ 실제 코드 수정 내역

| 파일 | 수정 전 문제 | 수정 내용 / 이유 |
|---|---|---|
| `src/model/audit_tools.py` | 원값-lag 불일치·전체공간 검증 부재 | 동일 industry-quarter 수준 1회 교란, lag 재생성, 전체 이력 g4, 공동 donor 벡터/블록, LP 외부범위·witness, 명시적 대안 규칙 |
| `src/run_independent_audit.py` | 비교실험과 행동표를 재현할 단일 경로 없음 | 8개 교란 방식×400회, 5개 점 규칙, 양립공간 지표, 업종/기간/업종제외 결과, 최종 행동표 |
| `src/model/robust.py` | 유한 표본을 전체공간 필연으로 서술, 반복 계산 비용 | 표본 범위 명시·벡터 연산. 원 구현의 1,080,000개 배정과 정확히 일치 확인 |
| `src/model/revalidation_phase5.py` | ‘확정’·‘가장 가능성 높은’ 표기, 무조건 파일 쓰기 | ‘표본 내 공통’·‘파라미터 표본 최빈’으로 수정, 비연속 집합은 슬래시 표기, legacy 지표 범위 문서화, 쓰기 조건 준수 |
| `src/model/revalidation_phase4.py`, `phase6.py` | `write=False`에서도 설정/문서 변경 | 쓰기 보호. 기존 판정·경계·가중치는 변경하지 않음 |
| `scripts/audit_*.py` | 검토 재현/보고서 근거 연결 부족 | 기준선 보존, 원자료 재실행, 18후보 대조, 연속공간 추가 탐색, 이 보고서 생성 |
| `tests/test_independent_audit.py` | 새 수정의 회귀 방어 없음 | lag 항등식·결측·전체이력 무교란·경계 동작·LP witness·기간 규칙 검증 |
| `notebooks/09_independent_audit.ipynb` | 최신 감사 결과 표시 노트북 없음 | 계산은 Python 모듈에 두고 실행 결과와 근거를 표시 |
| `pytest.ini`, `requirements.txt`, `.gitignore` | 스냅샷 테스트 중복 수집/LP 의존성/로컬 설치물 | 실제 tests 경로만 수집, scipy 명시, 실행 환경·스냅샷 배포 제외 |

## ⑦ 수정 전후 비교

같은 crisp 기준 파라미터에서 입력의 고용 지속기간 정의를 보완한 전후 분포:

| stage | before | after |
|---|---|---|
| UNDETERMINED | 20 | 20 |
| OBSERVE | 86 | 81 |
| CHECK | 41 | 42 |
| PRIORITY | 33 | 37 |

점 단계가 바뀐 행은 9개다. [행별 전후 비교](before_after_assignment.csv)에 전부 남겼다. 고용 이력을 더 이용해 점 단계가 바뀌었다는 사실을 정확도 향상으로 해석하지 않는다. 후단 g4의 기간 정의 수정이며 기존 Q1 국면·Q2 규모·Q3 분석창 국면 런은 보존했다.

### VRC4가 제거하는 공간과 최신 배정 범위

| space | n | lambda_mean | w_g1_mean | w_g2_mean | w_g3_mean | w_g4_mean | sample_singleton_share_disc | mean_width |
|---|---|---|---|---|---|---|---|---|
| full | 6000 | 0.6250 | 0.2512 | 0.2502 | 0.2498 | 0.2489 | 0.0112 | 1.8375 |
| rc | 1745 | 0.5786 | 0.2850 | 0.2857 | 0.2046 | 0.2247 | 0.1011 | 1.7063 |
| with_vrc4 | 447 | 0.5469 | 0.2158 | 0.3244 | 0.1771 | 0.2827 | 0.5169 | 1.3000 |
| without_vrc4 | 1745 | 0.5786 | 0.2850 | 0.2857 | 0.2046 | 0.2247 | 0.1011 | 1.7063 |

| industry | possible_stages_with | possible_stages_without |
|---|---|---|
| 기계 | CHECK / PRIORITY | CHECK / PRIORITY |
| 기타 | OBSERVE | OBSERVE |
| 목재종이 | CHECK / PRIORITY | OBSERVE / CHECK / PRIORITY |
| 비금속 | OBSERVE / CHECK | OBSERVE / CHECK |
| 석유화학 | OBSERVE | OBSERVE |
| 섬유의복 | OBSERVE | OBSERVE |
| 운송장비 | OBSERVE / CHECK | OBSERVE / CHECK |
| 음식료 | CHECK / PRIORITY | OBSERVE / CHECK / PRIORITY |
| 전기전자 | OBSERVE / CHECK | OBSERVE / CHECK |
| 철강 | OBSERVE / CHECK | OBSERVE / CHECK |

고정 파라미터의 점 배정은 참조제약 필터만 바꾸면 변하지 않는다. 달라지는 것은 허용하는 정책관점, 표본 범위와 CAI다. 따라서 공간 축소를 자료 정보량이나 정확도의 증가로 표현하지 않는다. 가중치 분위수·q/p 평균까지 포함한 전체 표는 [parameter_spaces.csv](parameter_spaces.csv)에 있다.

### 개정 방식별 점 배정 유지율

모든 수치는 **각 실험의 원자료 배정 대비 유지율**이다. 아래 비교는 재분류 위험을 끊은 비교 가능한 과거 이력으로 g4를 재계산한 동일 입력과 같은 b1/b2를 사용한다. legacy 원수치와의 차이에는 g4 수정도 있으므로 직접 개선율로 빼지 않는다. `literal_duration4`는 상대감소 단독 지속경로를 4분기로 명시한 정책 대안이며, 결과에 맞춘 임계 튜닝이 아니다.

| revision | D_small_indifference | count2 | grouped_evidence | literal_duration4 | v1.0_crisp |
|---|---|---|---|---|---|
| consistent_cells | 0.9009 | 0.8997 | 0.9126 | 0.9121 | 0.9077 |
| exclude_known_2024Q3_file_error | 0.9902 | 0.9921 | 0.9933 | 0.9933 | 0.9921 |
| joint_blocks2 | 0.8784 | 0.8801 | 0.8917 | 0.8906 | 0.8874 |
| joint_blocks2_inverse | 0.8775 | 0.8800 | 0.8912 | 0.8900 | 0.8875 |
| joint_blocks4 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| joint_blocks4_inverse | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| joint_quarters | 0.9085 | 0.9089 | 0.9183 | 0.9163 | 0.9138 |
| legacy_independent | 0.9026 | 0.9017 | 0.9137 | 0.9126 | 0.9098 |

분모는 완전관측 160행. 판별표본 89행 결과, 5%분위, 실제 점검대상(단계≥CHECK) 유지율은 [revision_metrics.csv](revision_metrics.csv)에 별도 보존했다. ‘오류정정 제외’는 상대적으로 작은 개정 사례만 남으므로 전체 스트레스를 대체할 수 없다.

### 같은 양립공간에 대한 자료 안정성

| revision | metric | all | disc |
|---|---|---|---|
| legacy_independent | compatible_set_jaccard | 0.9075 | 0.8655 |
| legacy_independent | compatible_point_containment | 0.9331 | 0.9044 |
| consistent_cells | compatible_set_jaccard | 0.9087 | 0.8683 |
| consistent_cells | compatible_point_containment | 0.9338 | 0.9071 |
| joint_quarters | compatible_set_jaccard | 0.9141 | 0.8667 |
| joint_quarters | compatible_point_containment | 0.9364 | 0.8994 |
| joint_blocks2 | compatible_set_jaccard | 0.8837 | 0.8222 |
| joint_blocks2 | compatible_point_containment | 0.9105 | 0.8591 |
| joint_blocks2_inverse | compatible_set_jaccard | 0.8825 | 0.8201 |
| joint_blocks2_inverse | compatible_point_containment | 0.9096 | 0.8576 |
| joint_blocks4 | compatible_set_jaccard | 1.0000 | 1.0000 |
| joint_blocks4 | compatible_point_containment | 1.0000 | 1.0000 |
| joint_blocks4_inverse | compatible_set_jaccard | 1.0000 | 1.0000 |
| joint_blocks4_inverse | compatible_point_containment | 1.0000 | 1.0000 |
| exclude_known_2024Q3_file_error | compatible_set_jaccard | 0.9951 | 0.9913 |
| exclude_known_2024Q3_file_error | compatible_point_containment | 0.9995 | 0.9991 |

정의: 고정 양립표본 Θ에서 `SΘ(x)={fθ(x):θ∈Θ}`.

- `compatible_point_containment`: 각 개정 복제본의 Θ 전체 점 배정 중 원 집합 SΘ(x)에 포함되는 비중. 무교란에서는 정확히 1이다.
- `compatible_set_jaccard`: 같은 Θ에서 원 집합과 개정 집합의 교집합 크기/합집합 크기. 두 집합이 공집합인 결측행은 제외한다.
- `paired_parameter_retention`: θ를 고정하고 x만 바뀔 때 점 배정이 같은 비중.
- `any_set_escape`: 개정 집합에 기존 집합 밖 단계가 하나라도 나타나는 행 비중. 높을수록 불안정하다.

이들은 **유한 파라미터 표본과 명시된 재표집 가정**에 조건부인 기술통계다. 새 합격 판정을 붙이지 않았다. 전역 정책선호의 확률, 위기 확률, 일반적 신뢰구간이 아니다.

### 모형을 바꾸면 실제 무엇이 달라지는가

| model | changed_rows | check_membership_changes |
|---|---|---|
| D_small_indifference | 6 | 4 |
| count2 | 2 | 2 |
| grouped_evidence | 4 | 3 |
| literal_duration4 | 11 | 10 |

단순 count2와 crisp 기준모형의 차이는 **운송장비/2025Q1, 전기전자/2025Q1** 두 행이다. 두 기준 g1·g2를 통과하지만 g3·g4는 통과하지 않는 경우다. 기준모형은 관찰, count2는 추가확인으로 배정한다. 전기전자/2025Q1은 RC2이기도 하므로 사례 양립성이 더 높다는 사실만으로 독립적 우월성을 주장할 수 없다. 현장 담당자가 ‘규모와 강도만으로 즉시 확인해야 하는가’를 결정해야 한다.

기준별 배정 변화(160행; 가중치 재정규화와 단순 지지 제거를 구분):

| criterion | remove_renormalize | suppress_no_renormalize |
|---|---|---|
| g1 | 12 | 12 |
| g2 | 31 | 31 |
| g3 | 12 | 13 |
| g4 | 43 | 50 |

g1·g2가 수학적으로 연결돼도 g1 제거와 g2 제거의 결과가 동일하지 않다. g4·g3도 실제 배정을 바꾼다. 이 결과는 각 차원의 정책적 필요성까지 입증하는 것은 아니다.

### 표본이 놓친 실제 feasible 배정

| industry | quarter | sample_possible | witnessed_possible |
|---|---|---|---|
| 기계 | 2026Q1 | OBSERVE / CHECK | OBSERVE / CHECK / PRIORITY |
| 비금속 | 2022Q4 | CHECK | CHECK / PRIORITY |
| 비금속 | 2023Q3 | CHECK | CHECK / PRIORITY |
| 전기전자 | 2022Q4 | CHECK | CHECK / PRIORITY |
| 철강 | 2025Q3 | OBSERVE | OBSERVE / CHECK |

연속공간 검증은 무작위 표본을 늘려 필연이라고 부르는 방식이 아니다. 단조적인 concordance의 최소/최대와 RC/VRC에서 유도한 필요조건으로 원공간을 포함하는 외부공간을 만들고 LP로 배제 범위를 구했다. 그 외부범위에 남은 단계마다 실제 허용 파라미터 해를 찾아 원 배정함수로 재검산했다. 두 집합이 같을 때만 전체 집합 확인으로 표시한다. 부동소수점 수치 허용오차가 있으며, 미해결을 불가능으로 바꾸지 않는다.

남은 미해결 행:

| industry | quarter | witnessed_possible | outer_possible |
|---|---|---|---|
| 목재종이 | 2023Q1 | CHECK | CHECK / PRIORITY |
| 운송장비 | 2022Q2 | CHECK | CHECK / PRIORITY |
| 운송장비 | 2025Q1 | CHECK | OBSERVE / CHECK |
| 전기전자 | 2022Q4 | CHECK / PRIORITY | OBSERVE / CHECK / PRIORITY |
| 전기전자 | 2025Q1 | CHECK | OBSERVE / CHECK |
| 철강 | 2022Q4 | CHECK | OBSERVE / CHECK |

### 최신분기 행동 출력

| industry | q1_state | g1 | g2 | g4 | parameter_stages | revision_scenario_stages | action_group |
|---|---|---|---|---|---|---|---|
| 기계 | S4 | 3979.0000 | 6.3397 | 2.0000 | CHECK / PRIORITY | CHECK / PRIORITY | 불확실 공동 점검군 |
| 기타 | S1 | 0.0000 | 0.0000 | 0.0000 | OBSERVE | OBSERVE | 현재 관찰군 |
| 목재종이 | S4 | 48.0000 | 10.0840 | 2.0000 | CHECK / PRIORITY | OBSERVE / CHECK / PRIORITY | 불확실 공동 점검군 |
| 비금속 | S2 | 2.0000 | 1.0811 | 19.0000 | OBSERVE / CHECK | OBSERVE / CHECK / PRIORITY | 불확실 공동 점검군 |
| 석유화학 | S3 | 0.0000 | 0.0000 | 0.0000 | OBSERVE | OBSERVE | 현재 관찰군 |
| 섬유의복 | N | 0.0000 | -0.0000 | 0.0000 | OBSERVE | OBSERVE | 현재 관찰군 |
| 운송장비 | S2 | 129.0000 | 0.7848 | 6.0000 | OBSERVE / CHECK | OBSERVE / CHECK | 불확실 공동 점검군 |
| 음식료 | S2 | 25.0000 | 3.7879 | 6.0000 | CHECK / PRIORITY | OBSERVE / CHECK / PRIORITY | 불확실 공동 점검군 |
| 전기전자 | S2 | 116.0000 | 0.4129 | 6.0000 | OBSERVE / CHECK | OBSERVE / CHECK | 불확실 공동 점검군 |
| 철강 | S2 | 112.0000 | 1.1427 | 4.0000 | OBSERVE / CHECK | OBSERVE / CHECK / PRIORITY | 불확실 공동 점검군 |

`parameter_stages`는 증명/실제 해가 일치한 연속공간 집합이고, 미해결 행은 보수적 외부범위를 쓴다. `revision_scenario_stages`는 해당 범위와 실행한 비퇴화 공동 개정 시나리오에서 관측된 단계의 합집합이다. 미래 모든 개정을 포괄하는 보장 구간은 아니다. 불확실성 확대를 감추지 않는다.

## ⑧ 최종 모형 구조

**HYBRID: 원자료 품질 확인 → Q1/Q2/Q3 근거 → 조건부 배정 범위 → 명시적 확인 행동.**

1. 원자료 오류·결측은 `자료 확인 대상`으로 남긴다. 180행을 유지하고 단계 불명 20행을 숨기지 않는다.
2. 고용 감소 인원(g1, 명), 고용 감소율(g2, %), 명목 생산 감소율(g3, %), 비교 가능한 고용 하회 연속분기(g4)를 각각 보여준다. g4는 재분류 위험·자료 공백에서 끊으며 관측되지 않은 이전 지속기간을 추정하지 않는다. Q1 국면·Q2 규모·Q3 시간의 설명을 보존한다.
3. 기존 규범을 정책 승인으로 격상하지 않고, RC/VRC 조건부 파라미터 범위와 수용지수를 병기한다. VRC4 제외 결과도 함께 검토할 수 있다.
4. 자료 불확실성은 동일 원계열에서 계산한 개정 스트레스 결과로 별도 표시한다. 퇴화한 4분기 실험은 운영 범위에서 제외한다.
5. 단계가 겹치면 공동 점검군으로 두고 Q1 국면별 확인 질문을 제공한다. 완전순위·강제 top-k는 만들지 않는다. 최신 10개 업종의 세부 확인 질문은 [action_latest.csv](action_latest.csv)에 있다.
6. 담당자·확인 기한·분기별 점검 가능 업종 수는 실제 운영 주체가 정해야 한다. 이를 연구진이 정한 CAI로 자동 대체하지 않는다.

연구 재실행: `python src/run_independent_audit.py --replicates 400`, 보고서 갱신: `python scripts/audit_report.py`.
최초 감사 기준선: `python scripts/audit_baseline.py`(기존 스냅샷이 있으면 덮어쓰기 거부). 원자료 확인: `python scripts/audit_raw_pipeline.py`. 전체 테스트: `python -m pytest tests -q`.
현재 기본 분석창은 기존 저장소의 2022Q1~2026Q2다. 새 분기를 운영에 추가할 때는 원자료 파이프라인의 분석창·참조사례 적용 범위도 버전 관리해야 하며, 이 도구가 자동으로 정책 승인을 갱신하지 않는다.

## ⑨ 남은 한계

- 외부 담당자가 결과를 보지 않고 제시한 정책선호 자료가 없다. RC/VRC는 개발용 규범이며 독립 평가셋이 아니다.
- 정상 개정 이력이 너무 적고 공표 간격 메타데이터가 없어 개정분포를 신뢰성 있게 추정하지 못한다. 블록 재표집 역시 입증된 생성모형이 아니다.
- 6행은 전체 q,p 연속공간의 정확한 집합이 아직 확인되지 않았다. 81개 끝점 q,p 조합에서도 해결되지 않은 것으로, 해가 없다는 증명이 아니다.
- CAI는 표집분포와 참조제약에 의존한다. 원공간 경계에 있는 feasible 해는 표본 CAI가 0이어도 존재할 수 있다.
- 업종은 10개이고 업종/기간별 분석은 기술적 민감도이다. 반복관측을 독립 180사례로 간주한 신뢰수준을 붙이지 않는다.
- 명목 생산은 물량/가격을 분리하지 못하고 PPI 매핑도 미확정이다. 현장 점검의 적절성·정책효과·심사 점수는 검증하지 못했다.
- 0.95·0.90 등의 legacy 실패 기록은 남지만, 새 운영 기준의 정당화 자료는 없다. 확인 명단 변경률·심한 단계 이동·소요시간을 현장에서 먼저 측정해야 한다.

## ⑩ 공모전 보고서에서 주장 가능한 것 / 안 되는 것

**주장 가능:** 원자료에서 재현되는 업종별 변화 진단; 같은 고용 계열의 규모·강도·지속 측면 비교; 명시적 규범에 조건부인 배정 차이; 표본과 연속공간을 구분한 불확실성; 원파일 오류와 통상 개정의 구분 필요; 실제 점검 질문을 제시하는 시범 도구.

**주장 금지:** 정책적으로 최적인 점검순서, 위기/정답 확률, 담당자보다 우수한 성과, 일반적 95% 안정성, 단순 규칙보다 더 적절한 업종 선정, 정상 개정에도 본질적으로 불안정하다는 단정, 4분기 블록의 100%를 성공으로 홍보, CAI=0을 불가능으로 해석, 심사위원이 이해하지 못해 감점할 것이라는 단정.

20쪽 본문은 문제·자료 품질·Q1/Q2/Q3·최신 행동표·한계/운영 절차를 중심에 놓는다. LP·파라미터 표집·실험 전체는 재현 부록으로 분리한다. 방법명보다 어떤 경우에 담당자가 무엇을 확인하는지가 먼저다.

## ⑪ 최종 판정

**HYBRID.** 기존 outranking 구조를 연구진의 정책규범을 구현하고 민감도를 드러내는 층으로 유지하며, 실제 사용은 근거 지표와 명시적인 공동 점검·자료 확인 절차로 연결한다. 이는 모델을 성공시키기 위한 기준 변경도, 단순규칙으로의 성급한 폐기도 아니다.

**“연구진 규범을 구현한 것 이상의 실질적 정보가 있는가?”** 입력 자료와 개정 기록에는 실질적 정보가 있다. 모형은 그 정보의 충돌과 규범 의존성을 정리하지만 새로운 독립 증거를 생성하지 않는다. LP 검증이 표본 누락 5건을 찾아낸 것과 개정 오류의 집중을 드러낸 것은 정보의 한계를 더 정확히 표현한 성과다. 정책적 타당성이 추가로 입증된 것은 아니다.

**“단순 규칙보다 더 적절한 업종·더 정직한 불확실성·더 안정적인 대응이 가능해졌는가?”** 더 적절한 업종 선정은 현장 기준이 없어 확인하지 못했다. 안정성 우위도 작고 방식 의존적이어서 채택 근거가 아니다. 불확실성 표현은 실제로 개선됐다. 표본 공통을 확정으로 부르지 않고, 누락 배정을 추가하고, 두 개정 유형과 미해결 6행을 구분했다. 이 개선은 ELECTRE만의 고유 장점이 아니라 단순 규칙에도 적용 가능한 검증 절차의 장점이다.
