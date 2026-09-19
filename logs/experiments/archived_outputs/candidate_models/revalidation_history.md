# 창원국가산단 ELECTRE TRI-B 재검증 전체 이력

## 1. 왜 재검증했는가

**IG1** — calibration/holdout next_negative_state 기반 후보 선택 및 채택 판정

타깃 next_negative_state는 "다음 분기 고용 YoY < 0"과 동치이며, "현재 고용이 감소 중인가"라는 이진변수 하나가 모든 ELECTRE 후보보다 전 구간에서 순위연관이 높다(CAL 0.7995 / HOLD 0.6190 / ALL 0.7501 vs 후보 D의 0.7470 / 0.4446 / 0.6497). 이 타깃 위에서 다기준 분류모형은 원리적으로 열위이므로 선택 기준으로 쓸 수 없다.

**IG2** — holdout_ordered_next_negative (PRIORITY > CHECK > OBSERVE 엄격 순서)

고용 감소가 시작되면 다음 분기 감소 확률이 88~90%로 포화되어 CHECK와 PRIORITY가 분리되지 않는다(전체기간 CHECK 0.882 vs PRIORITY 0.885, 차이 0.003). 어떤 파라미터로도 달성할 수 없는 조건이다.

**IG3** — external_direction_supported (가동률·가동업체수 순위연관 동시 양수)

가동률은 순위연관 0.012이고 값의 50%가 근사값, 40행 결측이다. 가동업체수는 세 단계 모두 중앙값이 0으로 판별력이 없다. 구성타당도가 확립되지 않은 지표를 필수 게이트로 쓸 수 없다.

## 2. Phase 0~6 이력

| Phase | 목적 | 산출물 수 | 주요 발견 | 다음 결정 |
|---|---|---|---|---|
| 0 | 기준선 고정 — 재현 앵커 대조, 동결 대상 해시 기록 | - | v1.0/후보 D 분포·강제 관찰 71행·crisp 불일치 고유조합 1개, 전부 재현 확인 | Phase 1 진행 |
| 1 | electre.py 함수 추가(낙관적 배정·veto) + prereg.py 사전등록 게이트 | - | 비관·낙관 배정 v1.0/D 모두 160/160 일치, veto 부등호 오류 발견·수정 | Phase 2 진행 |
| 2 | 진단 산출물 3종 — 낙관/비관 일치율, 입력교란 유지율, 파라미터공간 필연/가능배정 | 6 | 필연배정 비율 0.0112(전체공간), AM1로 p_upper<=b1 제약 발견 | AM1 개정 후 Phase 2 재실행, Phase 3 진행 |
| 3 | 검증 설계 교체 — C1~C4·S1 재판정, 기존 next_negative_state 게이트 폐기 | 9 | 6개 model×scenario 조합 모두 BLOCKED_MULTIPLE, C3·S1이 공통 병목 | AM4로 Phase 4 종료규칙 사전확정 후 REGISTERED 전환 |
| 4 | 모형 변경 시도 — veto 확정(Step1), 가중치·λ 재추론(Step2), C3 원인진단(Step3) | 6 | 18개 조합 전부 C3 미달(최대 0.935), g2 b1 경계=개정폭 90분위(비율 1.029) | EX2·EX3 발동 — AM6로 선호정보 확충 후 Phase 5(구간 배정 전환) |
| 5 | 공식 산출물을 점 배정에서 구간 배정으로 전환 — I1~I4 재판정 | 5 | 필연배정 0.011→0.517(가상 프로파일 포함), I3(0.893<0.95) 미달로 INTERVAL_BLOCKED_BY_I3 | Phase 6(VRC4 의존성 검증·최종 기록) |
| 6 | 최종 검증·기록·제출물 — VRC4 근거 수집, I3 구조 기록, 이력 문서 | 9 | (이 문서 자체가 결과) | 사람의 결정 대기 |

## 3. 사전등록 개정 이력

**AM1** (Phase 2, 등록상태=DRAFT, 결과 인지 전 개정=True)

- 변경: parameter_space.p_upper 를 {150, 2.5, 7.0, 2.0} → {100, 2.0, 5.0, 2.0} 으로 축소하고 p_constraint: p_j <= b1_j 를 명시
- 사유: p_j > b1_j 인 영역에서 g_j = 0 인 행이 양의 부분 concordance와 고용증거를 얻는 이론적 결함을 확인했다. 결과를 개선하기 위한 조정이 아니라 허용공간에서 정합성을 위반하는 영역을 제거하는 것이다.

**AM2** (Phase 2, 등록상태=DRAFT, 결과 인지 전 개정=False)

- 변경: acceptance.C2 의 분모를 scorable 행으로 한정하고 시나리오별 개별 판정으로 명시
- 사유: UNDETERMINED 행의 일치는 배정절차 강건성의 증거가 아니다.

**AM3** (Phase 2, 등록상태=DRAFT, 결과 인지 전 개정=False)

- 변경: acceptance.S1 의 평가 공간을 참조사례 양립 부분공간으로 명시하고 전체 공간·crisp 부분공간 값은 보고 항목으로 분리
- 사유: 원안은 S1을 어느 공간에서 재는지 명시하지 않았다. 제약 없는 공간에서 필연배정을 요구하는 것은 강건 배정의 정의와 맞지 않는다. 합격선 수치는 바꾸지 않는다.

**AM4** (Phase 3, 등록상태=DRAFT, 결과 인지 전 개정=True)

- 변경: Phase 4 종료 후의 분기 행동과 Phase 5 산출물 형태 전환 기준을 사전 확정
- 사유: Phase 3에서 C3와 S1이 구조 수준 병목으로 확인됐다. Phase 4는 마지막 모형 변경 시도이며, 그 결과에 따른 행동을 결과를 보기 전에 고정하지 않으면 사후 결정이 된다.

**AM5** (Phase 3, 등록상태=DRAFT, 결과 인지 전 개정=True)

- 변경: veto 후보를 V1(10명)·V2(30명) 2개에서 V1(30명) 1개로 축소하고 veto_selection_rule 을 단일 후보 기준으로 수정. RC1·RC2 의 rationale 에 법정 기준 대비 규모 문장을 추가(사례 자체는 불변).
- 사유: 30명은 고용정책 기본법 제33조 대량 고용변동 신고 기준(상시근로자 300명 미만 사업장, 1개월 내 이직 30명 이상)과 일치하는 외부 행정 근거가 있는 값이다. 10명에는 그러한 근거가 없어 후보에서 제외한다. 후보를 1개로 줄이면 사후선택 여지가 사라진다.

**AM6** (Phase 4, 등록상태=REGISTERED, 결과 인지 전 개정=True)

- 변경: AM4.preference_information_expansion 을 발동해 가상 프로파일 참조사례 5건을 추가하고, 구간 배정 산출물의 합격 기준(I1~I4)과 교란 강건성 재정의(C3b·C3c)를 사전등록한다.
- 사유: Phase 4 에서 18개 조합 전부가 C3 를 미달했고(최댓값 0.935) S1 도 0.101 로 미달했다. AM4 의 EX2·EX3 가 동시에 발동하므로 공식 산출물을 구간 배정으로 전환하며, 그에 맞는 합격 기준을 결과를 보기 전에 고정한다.

## 4. 무엇이 확정됐는가

- 참조사례·가상 프로파일과 양립하는 파라미터 부분공간(447표본)에서 필연배정 비율이 0.517로, 전체 공간(0.011)이나 참조사례만의 공간(0.101)보다 뚜렷이 높다.
- 2026Q2 기준 10개 업종 중 3개(기타·석유화학·섬유의복)는 가능 단계가 1개로 확정된다.
- 가능 단계 집합 자체는 자료 교란에 안정적이다(C3c 판별표본 0.930, 전체 0.948, 임계 0.90 통과).
- 강제 관찰 71행(g1=g2=g4=0)은 개정 전후 어느 경우에도 필연적으로 관찰이다.

## 5. 무엇이 확정되지 않았는가

**LIM1** — 점 배정은 입력자료 개정 교란에 대해 합격선을 충족하지 못한다. g2의 b1 경계값 2.0%p는 고용 자료 개정폭 90분위 1.944%p와 거의 같은 크기이며(비율 1.029), 판별표본 89행 중 67.4%가 어떤 기준에서든 경계까지의 거리가 개정폭 90분위 안에 있다. Phase 4에서 시도한 18개 조합 전부가 미달했고 최댓값은 0.935였다. 이는 파라미터 선택의 문제가 아니라 경계값과 자료 개정폭의 크기 관계에서 오는 구조적 제약이다.

**LIM2** — 구간 배정 산출물은 사전등록한 I3(교란 후 점 단계가 가능 단계 집합에 포함되는 비율, 임계 0.95)를 충족하지 못했다(실측 0.893). I3는 자료 불확실성과 파라미터 불확실성을 결합한 지표이며, 가능 단계 집합이 좁을수록 값이 낮아지는 구조를 갖는다(평균 가능 단계 수 1.294). 두 불확실성을 분리해 자료 교란 하의 가능 집합 안정성만 측정한 C3c는 판별표본 0.930, 전체 0.948로 임계 0.90을 충족했다. 합격선을 낮추지 않았으며 최종 판정은 INTERVAL_BLOCKED_BY_I3로 유지한다.

- VRC4(지속기간 단독 추가확인 규범)가 결합 양립공간을 사실상 단독으로 결정한다(marginal_narrowing 0.744). 이 규범의 기획 문서 근거는 `outputs/tables/vrc4_provenance_evidence.csv`에 수집했을 뿐 자동 판정하지 않았다 — 사람이 읽고 판단해야 한다.

## 6. 최종 판정과 그 의미

공식 산출물(구간 배정, `reference_plus_virtual_subspace`)의 최종 상태는 **INTERVAL_BLOCKED_BY_I3**이다.

- I1=1.000(통과), I2=0.955(통과), **I3=0.893(미달, 임계 0.95)**, I4=1.000(통과)
- 미달 원인은 파라미터 선택이 아니라 g2 경계값과 자료 개정폭이 같은 크기라는 구조적 사실이다(LIM1).
- 합격선은 어떤 단계에서도 낮추지 않았다.

## 7. 재현 절차

```
.venv\Scripts\python.exe src\run_model_revalidation.py --phase 2
.venv\Scripts\python.exe src\run_model_revalidation.py --phase 3
.venv\Scripts\python.exe src\run_model_revalidation.py --phase 4
.venv\Scripts\python.exe src\run_model_revalidation.py --phase 5
.venv\Scripts\python.exe src\run_model_revalidation.py --phase 6
.venv\Scripts\python.exe -m pytest tests -q
```

필요한 입력: `data/processed/model/electre_input_panel.csv`(현재 run manifest와 정합), `config/electre_tri_b_params.yaml`, `config/model_revalidation_prereg.yaml`(REGISTERED), `outputs/tables/vintage_수정폭_실측.csv`. Phase 4는 REGISTERED 상태에서만 실행된다. 예상 소요: Phase 2~6 각 1~20분, 전체 테스트(`pytest tests -q`)는 약 15~20분.
