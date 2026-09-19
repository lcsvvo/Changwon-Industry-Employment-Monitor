# 창원국가산단 재검증 서술 규칙

이 문서는 금지 표현을 예시로 원문 인용하므로 check_wording.py 스캔 대상에서 제외한다. 인용은 반드시 코드블록 안에 두며, 코드블록 밖 본문은 아래 자체 검사 규칙을 따른다.

공모전·보고서에서 이 모형의 결과를 서술할 때 쓸 수 있는 문장과 쓸 수 없는 문장을 고정한다. 허용 문장에는 근거 산출물 파일명과 컬럼을 병기한다.

## 허용

```
점검단계는 미래 위기 확률이 아니라 현재 시점의 확인 순서입니다.
```
- 근거: config.NOT_DETERMINABLE_STATEMENTS(고정 문구), outputs/report/interval_diagnostic_cards_2026Q2.md

```
예측 성능으로 검증하지 않았습니다. 이 모형은 예측모형이 아니기 때문입니다. 실제로 예측 타깃으로 평가하면 '현재 고용이 감소 중인가'라는 변수 하나가 어떤 다기준 모형보다 우수합니다(전체기간 순위연관 0.75 vs 후보 D의 0.65). 그 사실 자체가 이 검증이 부적절함을 보여줍니다.
```
- 근거: prereg.invalidated_gates.IG1, outputs/tables/electre_cluster_bootstrap_rank_correlation.csv

```
세 가지로 검증했습니다: 사전 합의한 규범과의 양립, 실측 자료 개정폭을 반영한 교란 안정성, 허용 파라미터 공간 전체에서의 배정 불변성.
```
- 근거: outputs/tables/electre_preference_expansion.csv, outputs/tables/electre_interval_robustness.csv, outputs/tables/electre_robust_assignment_summary.csv

```
단일 등급을 제시하지 않고 가능 단계 범위를 제시합니다. 그 이유는 판별표본에서 파라미터 선택에 따라 등급이 갈리는 비율이 높고(참조사례+가상 프로파일 양립 부분공간 필연배정 비율 51.7%), 교란 강건성도 합격선에 못 미치기 때문입니다.
```
- 근거: outputs/tables/electre_robust_assignment_summary.csv, outputs/tables/electre_interval_robustness.csv

```
고용 자료의 개정폭이 g2 경계값과 같은 크기이기 때문에 점 배정은 자료 개정만으로 바뀔 수 있습니다. 이를 숨기지 않고 구간으로 표시했습니다.
```
- 근거: outputs/tables/electre_c3_diagnosis.csv(g2_b1_vs_emp_revision_p90_ratio), outputs/tables/electre_limitation_record.csv(LIM1)

```
교란 후 점 단계가 원 가능 단계 범위 안에 머무는 비율은 평균 89.3%, 가능 단계 집합 자체의 교란 안정성(Jaccard)은 판별표본 기준 93.0%입니다.
```
- 근거: outputs/tables/electre_interval_robustness.csv(metric_id=C3b, C3c_discriminating)

```
지속기간 기준이 단독으로 추가확인을 만들 수 있다는 규범 하나가 결과를 크게 좌우합니다(이 규범을 뺀 공간은 1745표본으로 넓어지고, 포함한 공식 공간은 447표본입니다). 그 규범을 어디서 가져왔는지와, 그것을 뺐을 때 결과가 어떻게 달라지는지를 함께 공개합니다.
```
- 근거: outputs/tables/vrc4_provenance_evidence.csv, outputs/tables/vrc4_sensitivity.csv, outputs/tables/electre_preference_expansion.csv(case_id=VRC4, marginal_narrowing=0.744)

## 금지

아래는 실제로 써서는 안 되는 표현의 예시다(코드블록 안 인용이며, 코드블록 밖 본문에서는 이 문구를 쓰지 않는다는 뜻이다):

```
우선점검 = 위기업종 / 지원대상
2025Q1~2026Q2는 한 번도 보지 않은 검증구간
180개 표본
강건성 검증 통과
외적 타당성 확보
테스트 264개 통과 = 모형이 타당
이 모형은 미래 값을 예측한다
PPI 조정 없이 계산한 값을 실질치라고 부르는 표현
```

- 가능 단계가 2개 이상인 업종·분기를 단일 단계로만 적는 모든 표기 (반드시 display_label 컬럼을 그대로 쓴다)
