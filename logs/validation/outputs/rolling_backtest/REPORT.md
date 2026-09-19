# 재구축 패널 기반 사후적 시간외 정합성 검증(retrospective reconstructed-panel temporal validation)

CW-RBT-1.0 / 사용자 승인 후 2단계 실행 / 2026-09-18

## 최종 요약과 판단

**주 비교 결론은 `TRADE_OFF / NO_GENERAL_WINNER`다.** 고정 대표 ELECTRE는 더 많은 양성을 포착했고, 최종 트리아지는 점검범위와 proxy상 FP가 작았다. 트리아지의 추가 고용위축 포착 우위는 확인되지 않았다. 두 모형 모두 이 미래 변화 준거를 강하게 구분한다고 주장하기 어렵다. 현재 확인 필요성을 위한 규범적 모형의 목적 자체를 부정하는 결과는 아니지만, 미래 추가 위축을 잘 포착한다는 근거로 사용할 수도 없다.

- 주 공통 140행에서 양성은 58행(41.43%)이다. ELECTRE는 67행을 선별해 TP=24, FP=43, FN=34; 트리아지는 43행을 선별해 TP=16, FP=27, FN=42였다. 트리아지는 순 24행 덜 선별하면서 양성 포착도 순 8행 적었다. Recall 차이는 −13.79%p, precision 차이는 +1.39%p, FPR 차이는 −19.51%p다. 이 차이는 선별 집합이 완전히 포함관계라는 뜻이 아니다.
- 양성은 10업종·14 유효 origin에 분산되어 주 pooled 결과가 사전 희소/집중 경고에 해당하지는 않는다. 그러나 같은 산단의 반복·의존 관측이므로 일반 우열을 선언할 충분조건은 아니다. 주 precision은 두 모형 모두 양성 비율 41.43%보다 낮고, balanced accuracy도 ELECTRE 0.4447·트리아지 0.4733으로 항상 비선별/선별 참고선의 0.5보다 낮았다. 현재 음의 고용 YoY 참고선은 recall 0.5, precision 0.3919, balanced accuracy 0.4756이었다. 그 참고선은 점검비율·FPR도 더 높아 이를 새 모형으로 채택하거나 단일 승자로 해석하지 않는다.
- Secondary 120행에서 양성은 27행이다. ELECTRE TP=9·recall 33.33%, 트리아지 TP=6·recall 22.22%로 같은 누락/범위 교환이 나타났다. 동일 120행 primary는 양성 52행, TP=22 대 15다. 따라서 secondary의 수치 변화는 표본 축소만으로 설명되지 않으며 outcome이 좁아진 영향도 있다. h=1 동일140행에서도 ELECTRE recall 46.15% 대 트리아지 30.77%다.
- 최종 트리아지의 CHECK 이상 cutoff에서 규모 gate·Q3 반복·생산 보강 변형은 판정/성능이 같았다. 이 조건들은 우선점검 승격에 관여하기 때문에 주 cutoff의 추가 위축 포착을 높이는 조건이라고 해석하면 안 된다. A 제거는 TP를 16→12로 줄였고 FP=27은 같았다. A 완화는 TP=16을 유지하면서 FP를 27→29로 늘렸다. 두 결과 모두 숨기지 않았다. A의 우선점검 cutoff 결과는 별도 표에 모두 남겼다.
- 고용<300 층에서는 ELECTRE TP=16·recall 64%, 트리아지 TP=8·recall 32%이고 FPR은 각각 85.19%·70.37%였다. ≥300 층에서는 둘 다 TP=8·recall 24.24%였다. 주 pooled TP 순 차이 8행은 이 층별 재집계에서 <300 층에 있다. 작은 업종의 높은 비율 변동과 낮은 구분력을 함께 보아야 한다. <300에서 트리아지 우선점검은 gate 때문에 0건이며 precision=NA다.
- 기계 제외·기타 제외 및 다른 업종 각각의 leave-out에서도 주 cutoff ELECTRE recall이 높았지만 precision의 상대 방향은 일부 달라졌다. 기계 제외 precision은 ELECTRE 0.3390 대 트리아지 0.3333, 원 고용 감소만 요구하는 outcome에서는 balanced accuracy가 ELECTRE 0.5159 대 트리아지 0.5138로 방향이 바뀌었다. 2022~2023 recall은 48.15% 대 18.52%, 2024~2025는 둘 다 35.48%다. 고용중시 ELECTRE crisp에서도 recall은 둘 다 27.59%이고 ELECTRE precision/FPR/점검비율이 각각 0.4000/0.2927/0.2857로 트리아지 0.3721/0.3293/0.3071보다 높은 precision·낮은 FPR·작은 범위였다. 사양/기간에 무관한 단일 우위라는 설명은 적절하지 않다. 두 비중첩 origin 집합과 알려진 오류 노출 제외 결과도 모두 유지했다.
- **부분결측 운영 포괄성이 outcome 포착 우위로 이어지지 않았다.** 전체160 origin 판정률은 ELECTRE 140/160=87.5%, 트리아지 160/160=100%다. 그러나 생산 미확인20행의 양성9행 중 트리아지 CHECK 이상 선별 TP=0, FP=5, FN=9였고 `INSUFFICIENT_EVIDENCE`다. ELECTRE의 보류 양성9행은 분류 FN에 넣지 않았다. 트리아지가 모든 행에 판정을 제공한다는 운영 장점과 양성을 포착했다는 주장은 분리해야 한다.
- 유한 parameter 표본 집합의 공통 양성8행 중 사건은2행(25%), 모호66행 중27행(40.91%), 공통 음성66행 중29행(43.94%)이었다. 공통 선별이 높은 사건율을 뜻하지 않았다. 보수적 정책 recall은 3.45%, 적극적 정책은 50%로 크게 달랐다. 선호불확실성을 단일 정답 확률이나 신뢰구간으로 축약하지 않는다.
- 정의불가 값은 그대로 남겼다. pooled에서 항상 비선별 및 <300 층 트리아지 우선점검의 precision은 NA다. 업종/분기별 NA는 핵심 CSV에 보존했고, 6003개 theta의 precision/recall/점검비율은 모두 정의 가능했다. 사건9행의 부분결측 운영 분석과 업종/분기별 결과에는 희소·집중 경고를 표시했다.

### 프로젝트·공모전 활용에 대한 최종 권고

이번 결과는 시간적으로 분리한 미래 변화 준거와 오류구성·점검범위를 제공한다는 점에서 기존 구현 감사만으로 알 수 없던 정보를 추가했다. 다만 원래 입력과 같은 자료계열의 proxy이며, 당시 가용정보·현장 정답·외부 모집단의 타당성을 확보하지 못했다. 공모전 본문에는 주 비교의 작은 표와 **“점검범위 감소와 추가 위축 포착 감소의 trade-off; 일반 우열 판단 불가”**를 넣을 가치가 있다. 단, 트리아지의 포착 우위 또는 부분결측에서의 양성 포착 개선을 입증했다는 문장은 사용하지 않는다. 전체 민감도·배정집합·정의불가 결과는 부록과 이 REPORT/CSV에 둔다. 결과를 이유로 최종모형·임계값·outcome을 교체하지 않았다.

최종 QA: 산술·0분모·동결 mask·810행 outcome 원 수준 재계산·모든 내보낸 주/민감도 confusion matrix·6003 theta의 독립 벡터 판정 검산을 포함한 10개 테스트를 통과했다. 기존 최종모형/후보 감사 등 보호 파일 105개와 동결 파일 해시를 실행 전후 대조해 일치했다. 검산은 정의나 임계값의 변경을 수반하지 않았다.

## 1. 해석 범위와 동결 준수

공식 분석명은 위 제목이다. 2026년 고정 사양을 현재 재구축된 패널에 순차 적용한 분석이며, 당시 공표 vintage·가용시각을 복원하지 못했다. 실제 위기·지원 필요의 정답을 평가하지 않으며 일반적 모형 우열을 선언하지 않는다. 기존 자료·모형·감사 산출물과 PROTOCOL은 변경하지 않았다. PROTOCOL과 17개 입력/코드 해시, 180행 최종 트리아지 및 180행 감사 보정 ELECTRE crisp 판정을 대조하여 통과했다. 18개 origin에서 원 수준 prefix 재생성과 미래 제거·0값·배율 변경 불변성을 확인했다. 기계/2022Q1은 고용 하회 런 3, 트리아지 반복 True를 재현했다. RC/VRC는 사용하지 않았다. 입력은 업종·분기·고용·생산·classification_break만 허용했다. 미래 런·전환·저장된 파생값은 판정 입력에서 제외했다. 판정과 구조적 평가행 파일을 먼저 해시 잠금한 뒤 미래 outcome을 생성했다.

Primary/Secondary, 2022Q1~2025Q4, h=2, CHECK 이상 cutoff, 모든 민감도는 승인한 계획 그대로다. 실행상 프로토콜 이탈은 없다. 과거 설계·감사 결과에 대한 개발자의 사후지식과 연간보정본 선택은 제거하지 못한다. PROTOCOL/manifest의 '승인 대기' 표시는 1단계 역사기록으로 그대로 보존했고 2단계 승인은 EXECUTION_LOCK에 별도 기록했다.

## 2. 주 비교 — 고정 대표 crisp vs 최종 트리아지

공통 paired sample 140행, 10업종·14 유효 origin 분기. 양성 58행, 양성 업종 10개, 양성 origin 분기 14개. 140행은 독립 사건 140개가 아니다. CHECK/추가확인 이상을 주 비교로 먼저 계산했다. 아래 비율은 0~1이다.

| experiment | cutoff | model | N | positives | TP | FP | FN | TN | recall | precision | FPR | balanced_accuracy | alert_rate | evidence_status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| MAIN | 1 | electre_fixed | 140 | 58 | 24 | 43 | 34 | 39 | 0.4138 | 0.3582 | 0.5244 | 0.4447 | 0.4786 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| MAIN | 1 | triage_final | 140 | 58 | 16 | 27 | 42 | 55 | 0.2759 | 0.3721 | 0.3293 | 0.4733 | 0.3071 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |

트리아지−고정 ELECTRE paired 차이:

| model | TP | FP | FN | TN | recall | precision | FPR | balanced_accuracy | alert_rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| triage_final_minus_electre_fixed | -8 | -16 | 8 | 16 | -0.1379 | 0.0139 | -0.1951 | 0.0286 | -0.1714 |

## 3. 참고선·우선점검 cutoff

항상 비선별의 precision은 NA이며 0으로 채우지 않았다. 현재 음의 고용 YoY 참고선은 새 운영모형으로 채택하지 않는다. 우선점검 cutoff=2는 주 비교와 별개다.

| experiment | cutoff | model | N | positives | TP | FP | FN | TN | recall | precision | FPR | balanced_accuracy | alert_rate | evidence_status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| PRIORITY_CUTOFF | 2 | electre_fixed | 140 | 58 | 11 | 22 | 47 | 60 | 0.1897 | 0.3333 | 0.2683 | 0.4607 | 0.2357 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| PRIORITY_CUTOFF | 2 | triage_final | 140 | 58 | 6 | 6 | 52 | 76 | 0.1034 | 0.5000 | 0.0732 | 0.5151 | 0.0857 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| BENCHMARKS | 1 | always_none | 140 | 58 | 0 | 0 | 58 | 82 | 0 | NA | 0 | 0.5000 | 0 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| BENCHMARKS | 1 | always_all | 140 | 58 | 58 | 82 | 0 | 0 | 1 | 0.4143 | 1 | 0.5000 | 1 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| BENCHMARKS | 1 | current_negative_e_yoy | 140 | 58 | 29 | 45 | 29 | 37 | 0.5000 | 0.3919 | 0.5488 | 0.4756 | 0.5286 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |

## 4. 모든 고정 민감도 — 유리·불리·정의불가 결과 포함

변형은 각각 한 조건만 변경했다. 업종 삭제는 이미 잠근 판정/라벨의 재집계이며 R/A의 10업종 분모를 다시 계산하지 않았다. secondary는 동일 120행 primary와 함께, h=1은 동일 140행 및 확장 150행과 함께 제시한다. 알려진 원파일 오류 노출 제외는 사전 지정 2024Q1~2025Q4 origins를 제외하고 초기 이력을 유지했다. 최선 사양이나 outcome을 선택하지 않았다.

| experiment | cutoff | model | N | positives | TP | FP | FN | TN | recall | precision | FPR | balanced_accuracy | alert_rate | evidence_status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| magnitude_1pct | 1 | electre_fixed | 140 | 42 | 16 | 51 | 26 | 47 | 0.3810 | 0.2388 | 0.5204 | 0.4303 | 0.4786 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| magnitude_1pct | 1 | triage_final | 140 | 42 | 12 | 31 | 30 | 67 | 0.2857 | 0.2791 | 0.3163 | 0.4847 | 0.3071 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| magnitude_1pct | 2 | electre_fixed | 140 | 42 | 10 | 23 | 32 | 75 | 0.2381 | 0.3030 | 0.2347 | 0.5017 | 0.2357 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| magnitude_1pct | 2 | triage_final | 140 | 42 | 4 | 8 | 38 | 90 | 0.0952 | 0.3333 | 0.0816 | 0.5068 | 0.0857 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| raw_employment_decline | 1 | electre_fixed | 140 | 75 | 37 | 30 | 38 | 35 | 0.4933 | 0.5522 | 0.4615 | 0.5159 | 0.4786 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| raw_employment_decline | 1 | triage_final | 140 | 75 | 24 | 19 | 51 | 46 | 0.3200 | 0.5581 | 0.2923 | 0.5138 | 0.3071 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| raw_employment_decline | 2 | electre_fixed | 140 | 75 | 18 | 15 | 57 | 50 | 0.2400 | 0.5455 | 0.2308 | 0.5046 | 0.2357 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| raw_employment_decline | 2 | triage_final | 140 | 75 | 11 | 1 | 64 | 64 | 0.1467 | 0.9167 | 0.0154 | 0.5656 | 0.0857 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| SECONDARY | 1 | electre_fixed | 120 | 27 | 9 | 50 | 18 | 43 | 0.3333 | 0.1525 | 0.5376 | 0.3978 | 0.4917 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| SECONDARY | 1 | triage_final | 120 | 27 | 6 | 32 | 21 | 61 | 0.2222 | 0.1579 | 0.3441 | 0.4391 | 0.3167 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| SECONDARY | 2 | electre_fixed | 120 | 27 | 5 | 24 | 22 | 69 | 0.1852 | 0.1724 | 0.2581 | 0.4636 | 0.2417 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| SECONDARY | 2 | triage_final | 120 | 27 | 2 | 9 | 25 | 84 | 0.0741 | 0.1818 | 0.0968 | 0.4886 | 0.0917 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| PRIMARY_SAME_SECONDARY_SAMPLE | 1 | electre_fixed | 120 | 52 | 22 | 37 | 30 | 31 | 0.4231 | 0.3729 | 0.5441 | 0.4395 | 0.4917 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| PRIMARY_SAME_SECONDARY_SAMPLE | 1 | triage_final | 120 | 52 | 15 | 23 | 37 | 45 | 0.2885 | 0.3947 | 0.3382 | 0.4751 | 0.3167 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| PRIMARY_SAME_SECONDARY_SAMPLE | 2 | electre_fixed | 120 | 52 | 10 | 19 | 42 | 49 | 0.1923 | 0.3448 | 0.2794 | 0.4564 | 0.2417 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| PRIMARY_SAME_SECONDARY_SAMPLE | 2 | triage_final | 120 | 52 | 6 | 5 | 46 | 63 | 0.1154 | 0.5455 | 0.0735 | 0.5209 | 0.0917 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| H1_SAME_H2_SAMPLE | 1 | electre_fixed | 140 | 52 | 24 | 43 | 28 | 45 | 0.4615 | 0.3582 | 0.4886 | 0.4865 | 0.4786 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| H1_SAME_H2_SAMPLE | 1 | triage_final | 140 | 52 | 16 | 27 | 36 | 61 | 0.3077 | 0.3721 | 0.3068 | 0.5004 | 0.3071 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| H1_SAME_H2_SAMPLE | 2 | electre_fixed | 140 | 52 | 11 | 22 | 41 | 66 | 0.2115 | 0.3333 | 0.2500 | 0.4808 | 0.2357 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| H1_SAME_H2_SAMPLE | 2 | triage_final | 140 | 52 | 5 | 7 | 47 | 81 | 0.0962 | 0.4167 | 0.0795 | 0.5083 | 0.0857 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| H1_FULL_RANGE | 1 | electre_fixed | 150 | 53 | 25 | 48 | 28 | 49 | 0.4717 | 0.3425 | 0.4948 | 0.4884 | 0.4867 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| H1_FULL_RANGE | 1 | triage_final | 150 | 53 | 16 | 29 | 37 | 68 | 0.3019 | 0.3556 | 0.2990 | 0.5015 | 0.3000 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| H1_FULL_RANGE | 2 | electre_fixed | 150 | 53 | 11 | 24 | 42 | 73 | 0.2075 | 0.3143 | 0.2474 | 0.4801 | 0.2333 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| H1_FULL_RANGE | 2 | triage_final | 150 | 53 | 5 | 9 | 48 | 88 | 0.0943 | 0.3571 | 0.0928 | 0.5008 | 0.0933 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| electre_employment | 1 | electre_employment | 140 | 58 | 16 | 24 | 42 | 58 | 0.2759 | 0.4000 | 0.2927 | 0.4916 | 0.2857 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| electre_employment | 1 | triage_final | 140 | 58 | 16 | 27 | 42 | 55 | 0.2759 | 0.3721 | 0.3293 | 0.4733 | 0.3071 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| electre_employment | 2 | electre_employment | 140 | 58 | 2 | 13 | 56 | 69 | 0.0345 | 0.1333 | 0.1585 | 0.4380 | 0.1071 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| electre_employment | 2 | triage_final | 140 | 58 | 6 | 6 | 52 | 76 | 0.1034 | 0.5000 | 0.0732 | 0.5151 | 0.0857 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| electre_persistence | 1 | electre_persistence | 140 | 58 | 23 | 43 | 35 | 39 | 0.3966 | 0.3485 | 0.5244 | 0.4361 | 0.4714 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| electre_persistence | 1 | triage_final | 140 | 58 | 16 | 27 | 42 | 55 | 0.2759 | 0.3721 | 0.3293 | 0.4733 | 0.3071 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| electre_persistence | 2 | electre_persistence | 140 | 58 | 9 | 21 | 49 | 61 | 0.1552 | 0.3000 | 0.2561 | 0.4495 | 0.2143 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| electre_persistence | 2 | triage_final | 140 | 58 | 6 | 6 | 52 | 76 | 0.1034 | 0.5000 | 0.0732 | 0.5151 | 0.0857 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| electre_original_history | 1 | electre_original_history | 140 | 58 | 21 | 41 | 37 | 41 | 0.3621 | 0.3387 | 0.5000 | 0.4310 | 0.4429 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| electre_original_history | 1 | triage_final | 140 | 58 | 16 | 27 | 42 | 55 | 0.2759 | 0.3721 | 0.3293 | 0.4733 | 0.3071 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| electre_original_history | 2 | electre_original_history | 140 | 58 | 8 | 21 | 50 | 61 | 0.1379 | 0.2759 | 0.2561 | 0.4409 | 0.2071 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| electre_original_history | 2 | triage_final | 140 | 58 | 6 | 6 | 52 | 76 | 0.1034 | 0.5000 | 0.0732 | 0.5151 | 0.0857 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| triage_A_half | 1 | electre_fixed | 140 | 58 | 24 | 43 | 34 | 39 | 0.4138 | 0.3582 | 0.5244 | 0.4447 | 0.4786 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| triage_A_half | 1 | triage_A_half | 140 | 58 | 16 | 29 | 42 | 53 | 0.2759 | 0.3556 | 0.3537 | 0.4611 | 0.3214 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| triage_A_half | 2 | electre_fixed | 140 | 58 | 11 | 22 | 47 | 60 | 0.1897 | 0.3333 | 0.2683 | 0.4607 | 0.2357 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| triage_A_half | 2 | triage_A_half | 140 | 58 | 7 | 7 | 51 | 75 | 0.1207 | 0.5000 | 0.0854 | 0.5177 | 0.1000 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| triage_A_double | 1 | electre_fixed | 140 | 58 | 24 | 43 | 34 | 39 | 0.4138 | 0.3582 | 0.5244 | 0.4447 | 0.4786 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| triage_A_double | 1 | triage_A_double | 140 | 58 | 16 | 27 | 42 | 55 | 0.2759 | 0.3721 | 0.3293 | 0.4733 | 0.3071 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| triage_A_double | 2 | electre_fixed | 140 | 58 | 11 | 22 | 47 | 60 | 0.1897 | 0.3333 | 0.2683 | 0.4607 | 0.2357 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| triage_A_double | 2 | triage_A_double | 140 | 58 | 2 | 6 | 56 | 76 | 0.0345 | 0.2500 | 0.0732 | 0.4807 | 0.0571 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| triage_A_removed | 1 | electre_fixed | 140 | 58 | 24 | 43 | 34 | 39 | 0.4138 | 0.3582 | 0.5244 | 0.4447 | 0.4786 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| triage_A_removed | 1 | triage_A_removed | 140 | 58 | 12 | 27 | 46 | 55 | 0.2069 | 0.3077 | 0.3293 | 0.4388 | 0.2786 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| triage_A_removed | 2 | electre_fixed | 140 | 58 | 11 | 22 | 47 | 60 | 0.1897 | 0.3333 | 0.2683 | 0.4607 | 0.2357 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| triage_A_removed | 2 | triage_A_removed | 140 | 58 | 2 | 3 | 56 | 79 | 0.0345 | 0.4000 | 0.0366 | 0.4989 | 0.0357 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| triage_scale_200 | 1 | electre_fixed | 140 | 58 | 24 | 43 | 34 | 39 | 0.4138 | 0.3582 | 0.5244 | 0.4447 | 0.4786 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| triage_scale_200 | 1 | triage_scale_200 | 140 | 58 | 16 | 27 | 42 | 55 | 0.2759 | 0.3721 | 0.3293 | 0.4733 | 0.3071 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| triage_scale_200 | 2 | electre_fixed | 140 | 58 | 11 | 22 | 47 | 60 | 0.1897 | 0.3333 | 0.2683 | 0.4607 | 0.2357 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| triage_scale_200 | 2 | triage_scale_200 | 140 | 58 | 7 | 7 | 51 | 75 | 0.1207 | 0.5000 | 0.0854 | 0.5177 | 0.1000 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| triage_scale_500 | 1 | electre_fixed | 140 | 58 | 24 | 43 | 34 | 39 | 0.4138 | 0.3582 | 0.5244 | 0.4447 | 0.4786 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| triage_scale_500 | 1 | triage_scale_500 | 140 | 58 | 16 | 27 | 42 | 55 | 0.2759 | 0.3721 | 0.3293 | 0.4733 | 0.3071 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| triage_scale_500 | 2 | electre_fixed | 140 | 58 | 11 | 22 | 47 | 60 | 0.1897 | 0.3333 | 0.2683 | 0.4607 | 0.2357 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| triage_scale_500 | 2 | triage_scale_500 | 140 | 58 | 6 | 6 | 52 | 76 | 0.1034 | 0.5000 | 0.0732 | 0.5151 | 0.0857 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| triage_no_scale | 1 | electre_fixed | 140 | 58 | 24 | 43 | 34 | 39 | 0.4138 | 0.3582 | 0.5244 | 0.4447 | 0.4786 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| triage_no_scale | 1 | triage_no_scale | 140 | 58 | 16 | 27 | 42 | 55 | 0.2759 | 0.3721 | 0.3293 | 0.4733 | 0.3071 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| triage_no_scale | 2 | electre_fixed | 140 | 58 | 11 | 22 | 47 | 60 | 0.1897 | 0.3333 | 0.2683 | 0.4607 | 0.2357 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| triage_no_scale | 2 | triage_no_scale | 140 | 58 | 9 | 24 | 49 | 58 | 0.1552 | 0.2727 | 0.2927 | 0.4312 | 0.2357 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| triage_no_Q3 | 1 | electre_fixed | 140 | 58 | 24 | 43 | 34 | 39 | 0.4138 | 0.3582 | 0.5244 | 0.4447 | 0.4786 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| triage_no_Q3 | 1 | triage_no_Q3 | 140 | 58 | 16 | 27 | 42 | 55 | 0.2759 | 0.3721 | 0.3293 | 0.4733 | 0.3071 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| triage_no_Q3 | 2 | electre_fixed | 140 | 58 | 11 | 22 | 47 | 60 | 0.1897 | 0.3333 | 0.2683 | 0.4607 | 0.2357 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| triage_no_Q3 | 2 | triage_no_Q3 | 140 | 58 | 3 | 3 | 55 | 79 | 0.0517 | 0.5000 | 0.0366 | 0.5076 | 0.0429 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| triage_no_P | 1 | electre_fixed | 140 | 58 | 24 | 43 | 34 | 39 | 0.4138 | 0.3582 | 0.5244 | 0.4447 | 0.4786 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| triage_no_P | 1 | triage_no_P | 140 | 58 | 16 | 27 | 42 | 55 | 0.2759 | 0.3721 | 0.3293 | 0.4733 | 0.3071 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| triage_no_P | 2 | electre_fixed | 140 | 58 | 11 | 22 | 47 | 60 | 0.1897 | 0.3333 | 0.2683 | 0.4607 | 0.2357 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| triage_no_P | 2 | triage_no_P | 140 | 58 | 5 | 5 | 53 | 77 | 0.0862 | 0.5000 | 0.0610 | 0.5126 | 0.0714 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| LEAVE_OUT_기계 | 1 | electre_fixed | 126 | 50 | 20 | 39 | 30 | 37 | 0.4000 | 0.3390 | 0.5132 | 0.4434 | 0.4683 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| LEAVE_OUT_기계 | 1 | triage_final | 126 | 50 | 12 | 24 | 38 | 52 | 0.2400 | 0.3333 | 0.3158 | 0.4621 | 0.2857 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| LEAVE_OUT_기계 | 2 | electre_fixed | 126 | 50 | 8 | 19 | 42 | 57 | 0.1600 | 0.2963 | 0.2500 | 0.4550 | 0.2143 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| LEAVE_OUT_기계 | 2 | triage_final | 126 | 50 | 2 | 3 | 48 | 73 | 0.0400 | 0.4000 | 0.0395 | 0.5003 | 0.0397 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| LEAVE_OUT_기타 | 1 | electre_fixed | 126 | 52 | 20 | 37 | 32 | 37 | 0.3846 | 0.3509 | 0.5000 | 0.4423 | 0.4524 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| LEAVE_OUT_기타 | 1 | triage_final | 126 | 52 | 14 | 21 | 38 | 53 | 0.2692 | 0.4000 | 0.2838 | 0.4927 | 0.2778 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| LEAVE_OUT_기타 | 2 | electre_fixed | 126 | 52 | 10 | 17 | 42 | 57 | 0.1923 | 0.3704 | 0.2297 | 0.4813 | 0.2143 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| LEAVE_OUT_기타 | 2 | triage_final | 126 | 52 | 6 | 6 | 46 | 68 | 0.1154 | 0.5000 | 0.0811 | 0.5172 | 0.0952 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| LEAVE_OUT_목재종이 | 1 | electre_fixed | 126 | 48 | 19 | 42 | 29 | 36 | 0.3958 | 0.3115 | 0.5385 | 0.4287 | 0.4841 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| LEAVE_OUT_목재종이 | 1 | triage_final | 126 | 48 | 13 | 26 | 35 | 52 | 0.2708 | 0.3333 | 0.3333 | 0.4688 | 0.3095 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| LEAVE_OUT_목재종이 | 2 | electre_fixed | 126 | 48 | 8 | 21 | 40 | 57 | 0.1667 | 0.2759 | 0.2692 | 0.4487 | 0.2302 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| LEAVE_OUT_목재종이 | 2 | triage_final | 126 | 48 | 6 | 6 | 42 | 72 | 0.1250 | 0.5000 | 0.0769 | 0.5240 | 0.0952 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| LEAVE_OUT_비금속 | 1 | electre_fixed | 126 | 52 | 18 | 35 | 34 | 39 | 0.3462 | 0.3396 | 0.4730 | 0.4366 | 0.4206 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| LEAVE_OUT_비금속 | 1 | triage_final | 126 | 52 | 14 | 23 | 38 | 51 | 0.2692 | 0.3784 | 0.3108 | 0.4792 | 0.2937 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| LEAVE_OUT_비금속 | 2 | electre_fixed | 126 | 52 | 9 | 18 | 43 | 56 | 0.1731 | 0.3333 | 0.2432 | 0.4649 | 0.2143 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| LEAVE_OUT_비금속 | 2 | triage_final | 126 | 52 | 6 | 6 | 46 | 68 | 0.1154 | 0.5000 | 0.0811 | 0.5172 | 0.0952 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| LEAVE_OUT_석유화학 | 1 | electre_fixed | 126 | 55 | 24 | 41 | 31 | 30 | 0.4364 | 0.3692 | 0.5775 | 0.4294 | 0.5159 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| LEAVE_OUT_석유화학 | 1 | triage_final | 126 | 55 | 16 | 26 | 39 | 45 | 0.2909 | 0.3810 | 0.3662 | 0.4624 | 0.3333 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| LEAVE_OUT_석유화학 | 2 | electre_fixed | 126 | 55 | 11 | 21 | 44 | 50 | 0.2000 | 0.3438 | 0.2958 | 0.4521 | 0.2540 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| LEAVE_OUT_석유화학 | 2 | triage_final | 126 | 55 | 6 | 5 | 49 | 66 | 0.1091 | 0.5455 | 0.0704 | 0.5193 | 0.0873 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| LEAVE_OUT_섬유의복 | 1 | electre_fixed | 126 | 53 | 23 | 35 | 30 | 38 | 0.4340 | 0.3966 | 0.4795 | 0.4773 | 0.4603 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| LEAVE_OUT_섬유의복 | 1 | triage_final | 126 | 53 | 15 | 19 | 38 | 54 | 0.2830 | 0.4412 | 0.2603 | 0.5114 | 0.2698 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| LEAVE_OUT_섬유의복 | 2 | electre_fixed | 126 | 53 | 11 | 18 | 42 | 55 | 0.2075 | 0.3793 | 0.2466 | 0.4805 | 0.2302 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| LEAVE_OUT_섬유의복 | 2 | triage_final | 126 | 53 | 6 | 6 | 47 | 67 | 0.1132 | 0.5000 | 0.0822 | 0.5155 | 0.0952 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| LEAVE_OUT_운송장비 | 1 | electre_fixed | 126 | 54 | 23 | 38 | 31 | 34 | 0.4259 | 0.3770 | 0.5278 | 0.4491 | 0.4841 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| LEAVE_OUT_운송장비 | 1 | triage_final | 126 | 54 | 16 | 26 | 38 | 46 | 0.2963 | 0.3810 | 0.3611 | 0.4676 | 0.3333 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| LEAVE_OUT_운송장비 | 2 | electre_fixed | 126 | 54 | 11 | 21 | 43 | 51 | 0.2037 | 0.3438 | 0.2917 | 0.4560 | 0.2540 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| LEAVE_OUT_운송장비 | 2 | triage_final | 126 | 54 | 6 | 6 | 48 | 66 | 0.1111 | 0.5000 | 0.0833 | 0.5139 | 0.0952 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| LEAVE_OUT_음식료 | 1 | electre_fixed | 126 | 54 | 22 | 41 | 32 | 31 | 0.4074 | 0.3492 | 0.5694 | 0.4190 | 0.5000 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| LEAVE_OUT_음식료 | 1 | triage_final | 126 | 54 | 14 | 25 | 40 | 47 | 0.2593 | 0.3590 | 0.3472 | 0.4560 | 0.3095 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| LEAVE_OUT_음식료 | 2 | electre_fixed | 126 | 54 | 9 | 20 | 45 | 52 | 0.1667 | 0.3103 | 0.2778 | 0.4444 | 0.2302 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| LEAVE_OUT_음식료 | 2 | triage_final | 126 | 54 | 4 | 4 | 50 | 68 | 0.0741 | 0.5000 | 0.0556 | 0.5093 | 0.0635 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| LEAVE_OUT_전기전자 | 1 | electre_fixed | 126 | 52 | 23 | 40 | 29 | 34 | 0.4423 | 0.3651 | 0.5405 | 0.4509 | 0.5000 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| LEAVE_OUT_전기전자 | 1 | triage_final | 126 | 52 | 14 | 26 | 38 | 48 | 0.2692 | 0.3500 | 0.3514 | 0.4589 | 0.3175 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| LEAVE_OUT_전기전자 | 2 | electre_fixed | 126 | 52 | 11 | 21 | 41 | 53 | 0.2115 | 0.3438 | 0.2838 | 0.4639 | 0.2540 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| LEAVE_OUT_전기전자 | 2 | triage_final | 126 | 52 | 6 | 6 | 46 | 68 | 0.1154 | 0.5000 | 0.0811 | 0.5172 | 0.0952 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| LEAVE_OUT_철강 | 1 | electre_fixed | 126 | 52 | 24 | 39 | 28 | 35 | 0.4615 | 0.3810 | 0.5270 | 0.4673 | 0.5000 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| LEAVE_OUT_철강 | 1 | triage_final | 126 | 52 | 16 | 27 | 36 | 47 | 0.3077 | 0.3721 | 0.3649 | 0.4714 | 0.3413 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| LEAVE_OUT_철강 | 2 | electre_fixed | 126 | 52 | 11 | 22 | 41 | 52 | 0.2115 | 0.3333 | 0.2973 | 0.4571 | 0.2619 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| LEAVE_OUT_철강 | 2 | triage_final | 126 | 52 | 6 | 6 | 46 | 68 | 0.1154 | 0.5000 | 0.0811 | 0.5172 | 0.0952 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| EMP_LT300 | 1 | electre_fixed | 52 | 25 | 16 | 23 | 9 | 4 | 0.6400 | 0.4103 | 0.8519 | 0.3941 | 0.7500 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| EMP_LT300 | 1 | triage_final | 52 | 25 | 8 | 19 | 17 | 8 | 0.3200 | 0.2963 | 0.7037 | 0.3081 | 0.5192 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| EMP_LT300 | 2 | electre_fixed | 52 | 25 | 6 | 14 | 19 | 13 | 0.2400 | 0.3000 | 0.5185 | 0.3607 | 0.3846 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| EMP_LT300 | 2 | triage_final | 52 | 25 | 0 | 0 | 25 | 27 | 0 | NA | 0 | 0.5000 | 0 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| EMP_GE300 | 1 | electre_fixed | 88 | 33 | 8 | 20 | 25 | 35 | 0.2424 | 0.2857 | 0.3636 | 0.4394 | 0.3182 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| EMP_GE300 | 1 | triage_final | 88 | 33 | 8 | 8 | 25 | 47 | 0.2424 | 0.5000 | 0.1455 | 0.5485 | 0.1818 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| EMP_GE300 | 2 | electre_fixed | 88 | 33 | 5 | 8 | 28 | 47 | 0.1515 | 0.3846 | 0.1455 | 0.5030 | 0.1477 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| EMP_GE300 | 2 | triage_final | 88 | 33 | 6 | 6 | 27 | 49 | 0.1818 | 0.5000 | 0.1091 | 0.5364 | 0.1364 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| ORIGINS_2022_2023 | 1 | electre_fixed | 70 | 27 | 13 | 22 | 14 | 21 | 0.4815 | 0.3714 | 0.5116 | 0.4849 | 0.5000 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| ORIGINS_2022_2023 | 1 | triage_final | 70 | 27 | 5 | 10 | 22 | 33 | 0.1852 | 0.3333 | 0.2326 | 0.4763 | 0.2143 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| ORIGINS_2022_2023 | 2 | electre_fixed | 70 | 27 | 5 | 8 | 22 | 35 | 0.1852 | 0.3846 | 0.1860 | 0.4996 | 0.1857 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| ORIGINS_2022_2023 | 2 | triage_final | 70 | 27 | 4 | 3 | 23 | 40 | 0.1481 | 0.5714 | 0.0698 | 0.5392 | 0.1000 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| ORIGINS_2024_2025 | 1 | electre_fixed | 70 | 31 | 11 | 21 | 20 | 18 | 0.3548 | 0.3438 | 0.5385 | 0.4082 | 0.4571 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| ORIGINS_2024_2025 | 1 | triage_final | 70 | 31 | 11 | 17 | 20 | 22 | 0.3548 | 0.3929 | 0.4359 | 0.4595 | 0.4000 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| ORIGINS_2024_2025 | 2 | electre_fixed | 70 | 31 | 6 | 14 | 25 | 25 | 0.1935 | 0.3000 | 0.3590 | 0.4173 | 0.2857 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| ORIGINS_2024_2025 | 2 | triage_final | 70 | 31 | 2 | 3 | 29 | 36 | 0.0645 | 0.4000 | 0.0769 | 0.4938 | 0.0714 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| NONOVERLAP_START_Q1 | 1 | electre_fixed | 80 | 33 | 13 | 24 | 20 | 23 | 0.3939 | 0.3514 | 0.5106 | 0.4417 | 0.4625 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| NONOVERLAP_START_Q1 | 1 | triage_final | 80 | 33 | 9 | 14 | 24 | 33 | 0.2727 | 0.3913 | 0.2979 | 0.4874 | 0.2875 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| NONOVERLAP_START_Q1 | 2 | electre_fixed | 80 | 33 | 6 | 11 | 27 | 36 | 0.1818 | 0.3529 | 0.2340 | 0.4739 | 0.2125 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| NONOVERLAP_START_Q1 | 2 | triage_final | 80 | 33 | 3 | 3 | 30 | 44 | 0.0909 | 0.5000 | 0.0638 | 0.5135 | 0.0750 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| NONOVERLAP_START_Q2 | 1 | electre_fixed | 60 | 25 | 11 | 19 | 14 | 16 | 0.4400 | 0.3667 | 0.5429 | 0.4486 | 0.5000 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| NONOVERLAP_START_Q2 | 1 | triage_final | 60 | 25 | 7 | 13 | 18 | 22 | 0.2800 | 0.3500 | 0.3714 | 0.4543 | 0.3333 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| NONOVERLAP_START_Q2 | 2 | electre_fixed | 60 | 25 | 5 | 11 | 20 | 24 | 0.2000 | 0.3125 | 0.3143 | 0.4429 | 0.2667 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| NONOVERLAP_START_Q2 | 2 | triage_final | 60 | 25 | 3 | 3 | 22 | 32 | 0.1200 | 0.5000 | 0.0857 | 0.5171 | 0.1000 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| KNOWN_ERROR_EXPOSURE_EXCLUDED | 1 | electre_fixed | 70 | 27 | 13 | 22 | 14 | 21 | 0.4815 | 0.3714 | 0.5116 | 0.4849 | 0.5000 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| KNOWN_ERROR_EXPOSURE_EXCLUDED | 1 | triage_final | 70 | 27 | 5 | 10 | 22 | 33 | 0.1852 | 0.3333 | 0.2326 | 0.4763 | 0.2143 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| KNOWN_ERROR_EXPOSURE_EXCLUDED | 2 | electre_fixed | 70 | 27 | 5 | 8 | 22 | 35 | 0.1852 | 0.3846 | 0.1860 | 0.4996 | 0.1857 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| KNOWN_ERROR_EXPOSURE_EXCLUDED | 2 | triage_final | 70 | 27 | 4 | 3 | 23 | 40 | 0.1481 | 0.5714 | 0.0698 | 0.5392 | 0.1000 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |

## 5. 사건 분산·업종 및 분기별 오류

희소/집중 경고 기준은 양성<10 또는 양성 업종<3 또는 양성 origin<3이다. 해당 경우 INSUFFICIENT_EVIDENCE를 유지한다. 기준을 넘더라도 DESCRIPTIVE_ONLY_NO_GENERAL_WINNER이며 일반적 충분성을 뜻하지 않는다. 기타는 잔여집계다.

| groupby | group_value | model | N | positives | TP | FP | FN | TN | recall | precision | alert_rate | evidence_status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| industry | 기계 | electre_fixed | 14 | 8 | 4 | 4 | 4 | 2 | 0.5000 | 0.5000 | 0.5714 | INSUFFICIENT_EVIDENCE |
| industry | 기계 | triage_final | 14 | 8 | 4 | 3 | 4 | 3 | 0.5000 | 0.5714 | 0.5000 | INSUFFICIENT_EVIDENCE |
| industry | 기타 | electre_fixed | 14 | 6 | 4 | 6 | 2 | 2 | 0.6667 | 0.4000 | 0.7143 | INSUFFICIENT_EVIDENCE |
| industry | 기타 | triage_final | 14 | 6 | 2 | 6 | 4 | 2 | 0.3333 | 0.2500 | 0.5714 | INSUFFICIENT_EVIDENCE |
| industry | 목재종이 | electre_fixed | 14 | 10 | 5 | 1 | 5 | 3 | 0.5000 | 0.8333 | 0.4286 | INSUFFICIENT_EVIDENCE |
| industry | 목재종이 | triage_final | 14 | 10 | 3 | 1 | 7 | 3 | 0.3000 | 0.7500 | 0.2857 | INSUFFICIENT_EVIDENCE |
| industry | 비금속 | electre_fixed | 14 | 6 | 6 | 8 | 0 | 0 | 1 | 0.4286 | 1 | INSUFFICIENT_EVIDENCE |
| industry | 비금속 | triage_final | 14 | 6 | 2 | 4 | 4 | 4 | 0.3333 | 0.3333 | 0.4286 | INSUFFICIENT_EVIDENCE |
| industry | 석유화학 | electre_fixed | 14 | 3 | 0 | 2 | 3 | 9 | 0 | 0 | 0.1429 | INSUFFICIENT_EVIDENCE |
| industry | 석유화학 | triage_final | 14 | 3 | 0 | 1 | 3 | 10 | 0 | 0 | 0.0714 | INSUFFICIENT_EVIDENCE |
| industry | 섬유의복 | electre_fixed | 14 | 5 | 1 | 8 | 4 | 1 | 0.2000 | 0.1111 | 0.6429 | INSUFFICIENT_EVIDENCE |
| industry | 섬유의복 | triage_final | 14 | 5 | 1 | 8 | 4 | 1 | 0.2000 | 0.1111 | 0.6429 | INSUFFICIENT_EVIDENCE |
| industry | 운송장비 | electre_fixed | 14 | 4 | 1 | 5 | 3 | 5 | 0.2500 | 0.1667 | 0.4286 | INSUFFICIENT_EVIDENCE |
| industry | 운송장비 | triage_final | 14 | 4 | 0 | 1 | 4 | 9 | 0 | 0 | 0.0714 | INSUFFICIENT_EVIDENCE |
| industry | 음식료 | electre_fixed | 14 | 4 | 2 | 2 | 2 | 8 | 0.5000 | 0.5000 | 0.2857 | INSUFFICIENT_EVIDENCE |
| industry | 음식료 | triage_final | 14 | 4 | 2 | 2 | 2 | 8 | 0.5000 | 0.5000 | 0.2857 | INSUFFICIENT_EVIDENCE |
| industry | 전기전자 | electre_fixed | 14 | 6 | 1 | 3 | 5 | 5 | 0.1667 | 0.2500 | 0.2857 | INSUFFICIENT_EVIDENCE |
| industry | 전기전자 | triage_final | 14 | 6 | 2 | 1 | 4 | 7 | 0.3333 | 0.6667 | 0.2143 | INSUFFICIENT_EVIDENCE |
| industry | 철강 | electre_fixed | 14 | 6 | 0 | 4 | 6 | 4 | 0 | 0 | 0.2857 | INSUFFICIENT_EVIDENCE |
| industry | 철강 | triage_final | 14 | 6 | 0 | 0 | 6 | 8 | 0 | NA | 0 | INSUFFICIENT_EVIDENCE |
| quarter | 2022Q1 | electre_fixed | 10 | 5 | 3 | 2 | 2 | 3 | 0.6000 | 0.6000 | 0.5000 | INSUFFICIENT_EVIDENCE |
| quarter | 2022Q1 | triage_final | 10 | 5 | 1 | 1 | 4 | 4 | 0.2000 | 0.5000 | 0.2000 | INSUFFICIENT_EVIDENCE |
| quarter | 2022Q2 | electre_fixed | 10 | 6 | 3 | 2 | 3 | 2 | 0.5000 | 0.6000 | 0.5000 | INSUFFICIENT_EVIDENCE |
| quarter | 2022Q2 | triage_final | 10 | 6 | 1 | 1 | 5 | 3 | 0.1667 | 0.5000 | 0.2000 | INSUFFICIENT_EVIDENCE |
| quarter | 2022Q3 | electre_fixed | 10 | 4 | 2 | 3 | 2 | 3 | 0.5000 | 0.4000 | 0.5000 | INSUFFICIENT_EVIDENCE |
| quarter | 2022Q3 | triage_final | 10 | 4 | 1 | 1 | 3 | 5 | 0.2500 | 0.5000 | 0.2000 | INSUFFICIENT_EVIDENCE |
| quarter | 2022Q4 | electre_fixed | 10 | 4 | 1 | 4 | 3 | 2 | 0.2500 | 0.2000 | 0.5000 | INSUFFICIENT_EVIDENCE |
| quarter | 2022Q4 | triage_final | 10 | 4 | 1 | 1 | 3 | 5 | 0.2500 | 0.5000 | 0.2000 | INSUFFICIENT_EVIDENCE |
| quarter | 2023Q1 | electre_fixed | 10 | 3 | 1 | 4 | 2 | 3 | 0.3333 | 0.2000 | 0.5000 | INSUFFICIENT_EVIDENCE |
| quarter | 2023Q1 | triage_final | 10 | 3 | 0 | 2 | 3 | 5 | 0 | 0 | 0.2000 | INSUFFICIENT_EVIDENCE |
| quarter | 2023Q2 | electre_fixed | 10 | 2 | 1 | 4 | 1 | 4 | 0.5000 | 0.2000 | 0.5000 | INSUFFICIENT_EVIDENCE |
| quarter | 2023Q2 | triage_final | 10 | 2 | 0 | 2 | 2 | 6 | 0 | 0 | 0.2000 | INSUFFICIENT_EVIDENCE |
| quarter | 2023Q3 | electre_fixed | 10 | 3 | 2 | 3 | 1 | 4 | 0.6667 | 0.4000 | 0.5000 | INSUFFICIENT_EVIDENCE |
| quarter | 2023Q3 | triage_final | 10 | 3 | 1 | 2 | 2 | 5 | 0.3333 | 0.3333 | 0.3000 | INSUFFICIENT_EVIDENCE |
| quarter | 2024Q1 | electre_fixed | 10 | 3 | 2 | 2 | 1 | 5 | 0.6667 | 0.5000 | 0.4000 | INSUFFICIENT_EVIDENCE |
| quarter | 2024Q1 | triage_final | 10 | 3 | 1 | 1 | 2 | 6 | 0.3333 | 0.5000 | 0.2000 | INSUFFICIENT_EVIDENCE |
| quarter | 2024Q2 | electre_fixed | 10 | 4 | 1 | 2 | 3 | 4 | 0.2500 | 0.3333 | 0.3000 | INSUFFICIENT_EVIDENCE |
| quarter | 2024Q2 | triage_final | 10 | 4 | 1 | 2 | 3 | 4 | 0.2500 | 0.3333 | 0.3000 | INSUFFICIENT_EVIDENCE |
| quarter | 2024Q3 | electre_fixed | 10 | 6 | 2 | 1 | 4 | 3 | 0.3333 | 0.6667 | 0.3000 | INSUFFICIENT_EVIDENCE |
| quarter | 2024Q3 | triage_final | 10 | 6 | 2 | 1 | 4 | 3 | 0.3333 | 0.6667 | 0.3000 | INSUFFICIENT_EVIDENCE |
| quarter | 2025Q1 | electre_fixed | 10 | 5 | 1 | 3 | 4 | 2 | 0.2000 | 0.2500 | 0.4000 | INSUFFICIENT_EVIDENCE |
| quarter | 2025Q1 | triage_final | 10 | 5 | 3 | 2 | 2 | 3 | 0.6000 | 0.6000 | 0.5000 | INSUFFICIENT_EVIDENCE |
| quarter | 2025Q2 | electre_fixed | 10 | 7 | 5 | 2 | 2 | 1 | 0.7143 | 0.7143 | 0.7000 | INSUFFICIENT_EVIDENCE |
| quarter | 2025Q2 | triage_final | 10 | 7 | 4 | 2 | 3 | 1 | 0.5714 | 0.6667 | 0.6000 | INSUFFICIENT_EVIDENCE |
| quarter | 2025Q3 | electre_fixed | 10 | 4 | 0 | 6 | 4 | 0 | 0 | 0 | 0.6000 | INSUFFICIENT_EVIDENCE |
| quarter | 2025Q3 | triage_final | 10 | 4 | 0 | 4 | 4 | 2 | 0 | 0 | 0.4000 | INSUFFICIENT_EVIDENCE |
| quarter | 2025Q4 | electre_fixed | 10 | 2 | 0 | 5 | 2 | 3 | 0 | 0 | 0.5000 | INSUFFICIENT_EVIDENCE |
| quarter | 2025Q4 | triage_final | 10 | 2 | 0 | 5 | 2 | 3 | 0 | 0 | 0.5000 | INSUFFICIENT_EVIDENCE |

## 6. 부분결측 운영 포괄성 — 공통 성능과 분리

2023Q4는 생산 원 수준 결측, 2024Q4는 전년동기 생산 결측으로 YoY 계산불가다. ELECTRE 보류 20행을 관찰로 바꾸거나 FN에 섞지 않았다. 전체 origin 양성 capture의 분모는 outcome 관측 양성 전체이며 보류 양성을 별도로 기록한다.

| scope | model | horizon | cutoff | origins | prediction_valid | prediction_pending | production_missing | core_missing | outcome_valid | paired_primary | paired_secondary | observed_positives | selected_positives | pending_positives | capture_all_observed_positives |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| operational_all_origins | electre_fixed | 2 | 1 | 160 | 140 | 20 | 20 | 0 | 160 | 140 | 120 | 67 | 24 | 9 | 0.3582 |
| operational_all_origins | electre_fixed | 2 | 2 | 160 | 140 | 20 | 20 | 0 | 160 | 140 | 120 | 67 | 11 | 9 | 0.1642 |
| operational_all_origins | triage_final | 2 | 1 | 160 | 160 | 0 | 20 | 0 | 160 | 140 | 120 | 67 | 16 | 0 | 0.2388 |
| operational_all_origins | triage_final | 2 | 2 | 160 | 160 | 0 | 20 | 0 | 160 | 140 | 120 | 67 | 6 | 0 | 0.0896 |

| experiment | cutoff | model | N | positives | TP | FP | FN | TN | recall | precision | FPR | balanced_accuracy | alert_rate | evidence_status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| MISSING_PRODUCTION_OPERATION | 1 | triage_final | 20 | 9 | 0 | 5 | 9 | 6 | 0 | 0 | 0.4545 | 0.2727 | 0.2500 | INSUFFICIENT_EVIDENCE |
| MISSING_PRODUCTION_OPERATION | 2 | triage_final | 20 | 9 | 0 | 1 | 9 | 10 | 0 | 0 | 0.0909 | 0.4545 | 0.0500 | INSUFFICIENT_EVIDENCE |
| TRIAGE_ALL_ORIGINS_OPERATION | 1 | triage_final | 160 | 67 | 16 | 32 | 51 | 61 | 0.2388 | 0.3333 | 0.3441 | 0.4474 | 0.3000 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| TRIAGE_ALL_ORIGINS_OPERATION | 2 | triage_final | 160 | 67 | 6 | 7 | 61 | 86 | 0.0896 | 0.4615 | 0.0753 | 0.5071 | 0.0813 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |

## 7. 보조 parameter-space / 유한 표본 관측 배정집합

seed=2026, 가중치 .10~.40 simplex, lambda .50~.75, p 상한 (100,2,5,2), q~U(0,p/2), 6000개 draw+3개 named crisp=6003개. 동일 theta를 전체 행에 적용했다. RC1/RC2/RC3 및 VRC 필터 없음. 연속 허용공간 전체를 인증한 possible set이 아니라 유한 표본에서 관측된 집합이다. CAI는 outcome 확률·신뢰도·신뢰구간이 아니다. 모호 행을 제외하지 않은 보수/적극 정책 둘 다 보고한다. 행별 정답 맞춤 oracle은 계산하지 않았다.

| group_value | N | positives | prevalence | mean_set_width | ambiguous_fraction |
| --- | --- | --- | --- | --- | --- |
| common_positive | 8 | 2 | 0.2500 | 1.8750 | 0.4714 |
| ambiguous | 66 | 27 | 0.4091 | 2.6061 | 0.4714 |
| common_negative | 66 | 29 | 0.4394 | 1 | 0.4714 |

| experiment | cutoff | model | N | positives | TP | FP | FN | TN | recall | precision | FPR | balanced_accuracy | alert_rate | evidence_status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| FINITE_SET_conservative_common_positive | 1 | conservative_common_positive | 140 | 58 | 2 | 6 | 56 | 76 | 0.0345 | 0.2500 | 0.0732 | 0.4807 | 0.0571 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| FINITE_SET_aggressive_any_positive | 1 | aggressive_any_positive | 140 | 58 | 29 | 45 | 29 | 37 | 0.5000 | 0.3919 | 0.5488 | 0.4756 | 0.5286 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |

전체 paired 140행에서 각 theta의 기술적 민감도 분포 (정책사양 분포이지 표본오차 분포 아님):

| metric | defined | undefined | minimum | p10 | median | p90 | maximum |
| --- | --- | --- | --- | --- | --- | --- | --- |
| precision | 6003 | 0 | 0.1538 | 0.3214 | 0.3830 | 0.4130 | 0.4565 |
| recall | 6003 | 0 | 0.0345 | 0.1552 | 0.2931 | 0.4138 | 0.4828 |
| alert_rate | 6003 | 0 | 0.0714 | 0.2000 | 0.3143 | 0.4629 | 0.5143 |

## 8. 정의불가 결과

분모 0의 precision/recall/FPR/balanced accuracy는 CSV에서 NA로 보존했다. pooled 표에서 하나 이상 NA인 행 2개이며 아래에 모두 포함한다. 모든 업종/분기별 NA도 metrics_long에 남겼다. parameter draw별 정의불가 수는 위 표에 공개했다. outcome 미확인은 outcomes_long의 invalid_reason에 기록했으며 비악화로 채우지 않았다.

전체 origin의 outcome 가용성은 아래와 같다. 이 표의 양성수는 **전체 origin 기준**이며 paired 주 비교의 58행 등과 혼용하지 않는다. Secondary NA 40행은 2023Q2·2023Q4·2024Q2·2024Q4 각 10행이고 모두 생산 필수 수준 결측에 따른 정의불가다.

| outcome | horizon | 전체 origins | 정의가능 | NA | 양성 |
| --- | --- | --- | --- | --- | --- |
| primary | 2 | 160 | 160 | 0 | 67 |
| secondary | 2 | 160 | 120 | 40 | 27 |
| magnitude_1pct | 2 | 160 | 160 | 0 | 49 |
| raw_employment_decline | 2 | 160 | 160 | 0 | 85 |
| primary | 1 | 170 | 170 | 0 | 59 |

모든 model_metrics 245행에서 precision NA는 15행(pooled 2, 업종/분기 13)이다. recall·FPR·balanced accuracy NA는 0행이다. paired_delta는 모형 지표의 차이이므로 한쪽 precision NA가 있으면 차이도 NA로 보존했다. 보조 set_group의 비적용 지표 칸은 성능 정의불가와 구분한다.

| experiment | cutoff | model | N | positives | TP | FP | FN | TN | recall | precision | FPR | balanced_accuracy | alert_rate | evidence_status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| BENCHMARKS | 1 | always_none | 140 | 58 | 0 | 0 | 58 | 82 | 0 | NA | 0 | 0.5000 | 0 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |
| EMP_LT300 | 2 | triage_final | 52 | 25 | 0 | 0 | 25 | 27 | 0 | NA | 0 | 0.5000 | 0 | DESCRIPTIVE_ONLY_NO_GENERAL_WINNER |

업종/분기별 precision 정의불가 13행 전체(모두 선별 0건, TP=FP=0, recall=0이며 해당 층/분기의 우열은 판단하지 않음):

| experiment | cutoff | groupby | group_value | model | N | 양성 | FN | TN | precision |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| MAIN | 1 | industry | 철강 | triage_final | 14 | 6 | 6 | 8 | NA |
| PRIORITY_CUTOFF | 2 | industry | 기타 | triage_final | 14 | 6 | 6 | 8 | NA |
| PRIORITY_CUTOFF | 2 | industry | 목재종이 | triage_final | 14 | 10 | 10 | 4 | NA |
| PRIORITY_CUTOFF | 2 | industry | 비금속 | triage_final | 14 | 6 | 6 | 8 | NA |
| PRIORITY_CUTOFF | 2 | industry | 섬유의복 | triage_final | 14 | 5 | 5 | 9 | NA |
| PRIORITY_CUTOFF | 2 | industry | 운송장비 | triage_final | 14 | 4 | 4 | 10 | NA |
| PRIORITY_CUTOFF | 2 | industry | 전기전자 | triage_final | 14 | 6 | 6 | 8 | NA |
| PRIORITY_CUTOFF | 2 | industry | 철강 | electre_fixed | 14 | 6 | 6 | 8 | NA |
| PRIORITY_CUTOFF | 2 | industry | 철강 | triage_final | 14 | 6 | 6 | 8 | NA |
| PRIORITY_CUTOFF | 2 | quarter | 2022Q1 | electre_fixed | 10 | 5 | 5 | 5 | NA |
| PRIORITY_CUTOFF | 2 | quarter | 2024Q1 | triage_final | 10 | 3 | 3 | 7 | NA |
| PRIORITY_CUTOFF | 2 | quarter | 2024Q2 | triage_final | 10 | 4 | 4 | 6 | NA |
| PRIORITY_CUTOFF | 2 | quarter | 2024Q3 | triage_final | 10 | 6 | 6 | 4 | NA |

## 9. 자료·결론의 한계

Primary는 u_E<0 AND d_E<0, secondary는 여기에 u_P<0 AND d_P<0를 요구한다. d는 전년 동일 이동구간의 단순 준거이며 공식 계절조정이 아니다. 입력과 outcome은 같은 고용 계열을 공유한다. 생산은 미래 단일 분기 명목 flow로 물가/물량을 분리하지 못하며 생산 단독 위축은 이 outcome에 포함되지 않는다. 순고용 감소는 개인 해고/실업 수가 아니다. 공표시각 cutoff와 실제 선행기간은 검증불가다. 중첩 horizon, 업종 반복, 분기 공통충격, 자료 보정 및 알려진 오류정정 때문에 독립표본 검정·CI·bootstrap·통상 정확도·F1·AUC·실제 lead time을 제시하지 않았다. proxy상 FP는 실제 불필요한 점검, FN은 실제 정책 실패를 의미하지 않는다.

## 10. 산출물·재현

핵심 CSV는 7개로 통합했고 parameter draw별 파일은 생성하지 않았다.

- predictions_long.csv: 18개 origin의 고정 판정·축·인과적 설명 및 유한 표본 관측 집합. 자료보류는 stage_code=-1, 집합행 stage_code=NA.
- sample_membership.csv: outcome 부호를 보기 전에 잠근 h1/h2 origin·필수 수준 가용성·paired mask와 제외 사유.
- outcomes_long.csv: 모든 h2 outcome 및 h1 primary, 필수 수준·u/d·라벨·NA 사유.
- evaluation_long.csv: 실험·모형·cutoff별 포함 여부·보류·라벨·오류 유형. NOT_EVALUATED를 FN으로 세지 않는다.
- metrics_long.csv: 주/보조/민감도·업종/분기 건수, paired_delta(트리아지−ELECTRE), set_group. paired_delta의 TP/FP/FN/TN은 차이이며 N/양성/음성은 공통 표본 수다.
- operational_coverage.csv: 전체 origins 판정률·보류 양성·capture, paired 성능과 별개.
- parameter_robustness_long.csv: 6003개 theta의 파라미터 및 각 theta 전체140행 cutoff1 결과; 개별 draw 파일 없음.

EXECUTION_LOCK.json은 승인조건, PREDICTION_LOCK.json은 라벨 생성 전 판정·평가행·표본 파라미터 해시와 검사기록, RUN_METADATA.json은 환경·출처·완료 해시·기존 산출물 불변 확인이다. 코드: scripts/run_temporal_validation.py. 실행 순서: --preflight, 검사 후 --evaluate. 기존 lock/결과가 있으면 덮어쓰기를 거부한다. PROTOCOL 원본: outputs/rolling_backtest_protocol/PROTOCOL.md. 최종모형/기존 감사 결과는 보존했다.
