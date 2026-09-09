# 창원국가산단 업종별 산업·고용 전환진단
## 방법론 근거 및 EDA 실행계획

본 문서는 최종 기획안의 「6. 핵심 분석 방법」·「5. 전체 분석 흐름」을 실제 데이터셋에 매핑하고, 각 단계마다 학술적 근거와 심사위원 반문 대응 논리를 결합하여, 보고서 작성과 EDA를 동시에 진행할 수 있도록 정리한 실행계획서이다.

### 공통 데이터 스키마 (가정)

아래 코드는 실제 KICOX 원자료 컬럼명이 확정되기 전, 다음과 같은 **패널 데이터프레임 `df`**를 가정하고 작성되었다. 실제 파일을 받으면 컬럼명만 맞춰주면 그대로 동작한다.

```python
import pandas as pd
import numpy as np

# df 예시 구조 (10개 업종 × 33분기 = 330행)
# industry            : 업종명 (예: '철강', '전기전자', ...)
# quarter             : 분기 (예: '2018Q1', ..., '2026Q2', pandas Period 권장)
# production          : 생산실적 (명목, 원)
# employment          : 고용인원 (명)
# utilization_rate    : 제조업 가동률 (%)
# num_registered      : 입주업체수
# num_operating       : 가동업체수

# 필요 라이브러리 (최초 1회 설치)
# pip install pandas numpy scikit-learn lifelines networkx matplotlib seaborn --break-system-packages

df['quarter'] = pd.PeriodIndex(df['quarter'], freq='Q')
df = df.sort_values(['industry', 'quarter']).reset_index(drop=True)
```

---

## 0. 전체 매핑 요약표

| 분석 단계 | 사용 데이터 | 핵심 방법론 | 근거 문헌 | EDA 산출물 |
|---|---|---|---|---|
| STEP 0 정합성 검증 | 전체 원자료 | 결측·보정 처리 | - | 결측맵, 보정이력 로그 |
| STEP 1 장기흐름 | 생산·고용 실적 | 시계열 플롯 | - | 산단 전체/업종별 라인차트 |
| STEP 2 국면분류 | 생산·고용 YoY | 부호 기반 4분류 + 군집분석 | Bry-Boschan(1971), Harding-Pagan(2002) | 국면 히트맵, 산점도 |
| STEP 3 지속성 | 국면 시퀀스 | 지속기간 계산, 생존분석 | Diebold-Rudebusch(1990) | 지속기간 히스토그램, 생존곡선 |
| STEP 4 전환분석 | 국면 시퀀스 | 마르코프 전환행렬 | Hamilton(1989), Hamilton-Owyang(2012) | 전환행렬 히트맵, 네트워크그래프 |
| STEP 5 보조지표 결합 | 가동률·업체수 | 하위군집(계층적 군집) | - | 서브타입 산점도 |
| STEP 6 진단카드 | 전체 결합 | 업종별 요약카드 | - | 카드 10종 |
| STEP 7 후속분석 | FactoryON 등 | 필요시 추가 | - | - |
| STEP 8 후속확인사항 | 전체 결과 | 정책 미결정 원칙 | - | 체크리스트 |

---

## 1. STEP 0 — 데이터 정합성 검증

### 사용 데이터
KICOX 업종별 생산실적, 고용현황, 제조업 가동률, 입주업체수, 가동업체수 (2018Q1~2026Q2, 10개 업종 × 33분기 = 330개 관측치 기본 패널)

### EDA 작업 목록
1. 업종 × 분기 완전 패널 여부 확인 (330행 기준 결측 셀 카운트)
2. KICOX 연간보정본과 분기 공표값 간 차이(revision gap) 계산 — 보정 전후 YoY 변화율 재계산
3. 업종 분류 변경 이력 확인 (통계청 KSIC 개정 등으로 인한 업종 코드 변경 여부)
4. 생산자물가지수(PPI) 대비 명목생산액 디플레이트 — 실질 생산액 병행 산출 여부 결정

### 보고서 서술 포인트
"본 분석은 결측·보정·분류변경을 STEP 0에서 명시적으로 처리하여, 이후 국면분류 결과가 데이터 정합성 문제에서 기인한 것이 아님을 사전에 통제한다."

### 코드

```python
# 1. 완전 패널 여부 확인
industries = df['industry'].unique()
quarters = pd.period_range(df['quarter'].min(), df['quarter'].max(), freq='Q')
full_index = pd.MultiIndex.from_product([industries, quarters], names=['industry', 'quarter'])

panel = df.set_index(['industry', 'quarter']).reindex(full_index)
missing_map = panel[['production', 'employment']].isna()

print(f"전체 셀 수: {len(full_index)}, 결측 셀 수: {missing_map.any(axis=1).sum()}")

# 결측맵 시각화용 피벗 (히트맵 입력)
missing_pivot = missing_map.any(axis=1).unstack('quarter')  # index=industry, columns=quarter

# 2. 보정 전후 YoY 비교 (연간보정본 df_revised가 별도로 있다고 가정)
# merged = df.merge(df_revised, on=['industry', 'quarter'], suffixes=('_orig', '_revised'))
# merged['revision_gap_pct'] = (merged['production_revised'] - merged['production_orig']) / merged['production_orig'] * 100

# 3. YoY 계산 (분기 단위, 전년동기 대비이므로 4분기 shift)
panel = panel.reset_index()
panel = panel.sort_values(['industry', 'quarter'])
panel['production_yoy'] = panel.groupby('industry')['production'].pct_change(4) * 100
panel['employment_yoy'] = panel.groupby('industry')['employment'].pct_change(4) * 100

# 4. (선택) PPI 디플레이트 — ppi 시리즈가 있다면
# panel = panel.merge(ppi_df, on='quarter', how='left')
# panel['production_real'] = panel['production'] / (panel['ppi_index'] / 100)
```

---

## 2. STEP 1 — 장기 흐름 확인

### 사용 데이터
산단 전체 및 10개 업종 생산·고용 원계열 (2018Q1~2026Q2)

### EDA 작업 목록
1. 산단 전체 생산·고용 YoY 라인차트 (좌우 축 이중 스케일)
2. 10개 업종 개별 생산·고용 YoY 소형 다중패널(small multiples) — 업종 간 이질성 시각적 확인
3. 산단 전체 지표만으로는 보이지 않는 업종 간 상쇄효과 존재 여부 확인 (업종별 분산 vs 전체 평균의 괴리)

### 보고서 서술 포인트
"산단 전체 지표는 업종 간 상쇄효과로 인해 개별 업종의 산업·고용 국면을 은폐할 수 있다. 이는 STEP 2 업종별 분해의 필요성을 뒷받침한다."

### 코드

```python
import matplotlib.pyplot as plt
import seaborn as sns

# 1. 산단 전체 YoY 이중축 라인차트
agg = panel.groupby('quarter')[['production', 'employment']].sum().reset_index()
agg['production_yoy'] = agg['production'].pct_change(4) * 100
agg['employment_yoy'] = agg['employment'].pct_change(4) * 100

fig, ax1 = plt.subplots(figsize=(12, 5))
ax2 = ax1.twinx()
ax1.plot(agg['quarter'].astype(str), agg['production_yoy'], color='tab:blue', label='생산 YoY')
ax2.plot(agg['quarter'].astype(str), agg['employment_yoy'], color='tab:red', label='고용 YoY')
ax1.set_ylabel('생산 YoY (%)', color='tab:blue')
ax2.set_ylabel('고용 YoY (%)', color='tab:red')
plt.xticks(rotation=90)
plt.title('창원국가산단 전체 생산·고용 YoY 추이')
plt.tight_layout()
plt.savefig('step1_aggregate_trend.png', dpi=150)

# 2. 업종별 small multiples
g = sns.FacetGrid(panel, col='industry', col_wrap=5, height=2.5, sharey=False)
g.map_dataframe(lambda data, **kw: (
    plt.plot(data['quarter'].astype(str), data['production_yoy'], label='생산YoY'),
    plt.plot(data['quarter'].astype(str), data['employment_yoy'], label='고용YoY')
))
g.set_xticklabels(rotation=90)
g.add_legend()
plt.savefig('step1_industry_small_multiples.png', dpi=150)

# 3. 업종 간 상쇄효과 확인: 업종별 분산 vs 전체 평균 괴리
dispersion = panel.groupby('quarter')['employment_yoy'].agg(['mean', 'std']).reset_index()
print(dispersion.tail(8))  # 최근 8분기 확인 — std가 크면 업종 간 이질성 큼
```

---

## 3. STEP 2 — 생산·고용 4국면 분류

### 사용 데이터
업종별 생산 YoY, 고용 YoY (2018Q1~2026Q2)

### 방법론
1. **기본 분류**: 생산·고용 YoY 부호 조합으로 S1~S4 분류
2. **민감도 검사**: ±0.5%, ±1%, ±2% 중립구간 적용 후 분류 결과 비교 — 경계값 민감도가 낮은 업종·분기만 "확정 국면"으로 신뢰
3. **검증용 군집분석**: 생산 YoY·고용 YoY를 표준화(z-score)하여 K-means(k=4) 또는 GMM 수행 후, 임의 경계선(부호 기준)과 데이터 기반 군집이 얼마나 일치하는지 교차표(confusion matrix) 산출

### 근거 문헌 및 반박 논리
| 예상 질문 | 근거 문헌 | 반박 논리 |
|---|---|---|
| "생산↑·고용↓ 국면이 예외적 노이즈 아니냐" | Gil, E. (2023), "Jobless Growth in the Manufacturing Industry," KIET Industrial Economic Review | 국내 제조업에서 생산과 고용의 탈동조화(decoupling)는 이미 산업연구원(KIET)에서 정식 연구된 현상이며, 우리는 이를 업종 단위로 처음 국면화·추적함 |
| "이 현상이 한국만의 특이 사례 아니냐" | Jaimovich, N. & Siu, H., "Job Polarization and Jobless Recoveries," NBER Working Paper No.18334 | 미국 제조업에서도 최근 경기침체 국면마다 산출 반등 이후 고용이 회복되지 않는 패턴이 반복 확인됨 — 국제적으로 공통된 현상 |
| "부호만으로 국면 나누는 게 자의적이다" | Bry & Boschan(1971); Harding & Pagan(2002), Journal of Monetary Economics | 국제 표준 경기국면 판정법(BBQ 알고리즘)도 방향성 기반 국면식별 + 최소진폭·지속기간 필터를 사용함. ±0.5~2% 민감도 검사가 이 필터에 해당 |

### 방법론 채택 근거 (문헌 기반 서술)

본 연구가 생산·고용 YoY 부호 조합에 기반한 4국면 분류를 채택한 것은 임의적 판단이 아니라 두 갈래의 선행연구에 근거한다.

첫째, 국면 분류의 **실체적 근거**는 생산과 고용의 탈동조화(decoupling) 현상을 다룬 선행연구에 있다. Gil(2023)은 한국 제조업에서 총부가가치가 지속적으로 증가함에도 고용은 감소하는 "고용없는 성장(jobless growth)" 패턴이 2015년 이후 관측되었으며, 이는 경기침체기에 산출과 고용이 함께 감소한다는 통상적 정형화 사실과 배치되는 이례적 현상이라고 밝혔다. Jaimovich & Siu(NBER Working Paper No.18334) 또한 미국 제조업에서 최근 세 차례 경기침체 국면 모두 산출이 반등한 이후에도 고용이 회복되지 못한 패턴을 실증하였다. 두 연구는 공통적으로 생산과 고용이 "함께 움직인다"는 전제가 제조업 부문에서는 성립하지 않을 수 있음을 보여주며, 이는 본 연구가 생산·고용을 별도 축으로 두어 4분면으로 분류해야 하는 이유를 뒷받침한다. 즉 국면 분류는 이례적 조합(S2, S3)이 실제로 존재하고 반복될 수 있다는 문헌적 전제 위에서 설계되었다.

둘째, 국면 분류의 **형식적 근거**는 경기순환 국면 판정의 표준 방법론에 있다. Bry & Boschan(1971)이 제안하고 Harding & Pagan(2002, *Journal of Monetary Economics*)이 정식화한 BBQ(Bry-Boschan Quarterly) 알고리즘은, 시계열의 방향성(상승·하강)을 기준으로 국면을 식별하되 국면이 최소 지속기간·진폭 조건을 만족해야 유효한 국면으로 인정하는 절차를 따른다. 본 연구의 부호 기반 분류와 ±0.5%·±1%·±2% 중립구간 민감도 검사는 이 절차의 핵심 아이디어 — 방향성 기반 식별 + 경계값 필터링 — 를 산업·고용 결합국면에 응용한 것이다. K-means/GMM 군집분석은 이 방향성 기반 분류가 데이터 자체의 군집 구조와 얼마나 부합하는지를 사후적으로 검증하기 위한 보조 절차로 채택되었다.

### EDA 작업 목록
1. 생산 YoY × 고용 YoY 산점도 (4사분면 색상 구분, 업종별 마커)
2. 중립구간 3종(±0.5/1/2%) 적용 시 국면 분류 변화 비율 테이블
3. K-means/GMM 군집 vs 부호기준 분류 교차표 및 일치율(%)
4. 국면별 관측치 비율 파이/막대차트 (S1~S4 전체 비중)
5. **핵심 검증 통계**: 고용 감소 관측치 중 생산 증가 비율 재계산 및 신뢰구간 (현재 예비분석 45%의 정식 검증)

### 코드

```python
from sklearn.cluster import KMeans
from sklearn.mixture import GaussianMixture
from sklearn.preprocessing import StandardScaler
from statsmodels.stats.proportion import proportion_confint

data = panel.dropna(subset=['production_yoy', 'employment_yoy']).copy()

# 1. 기본 부호기준 4국면 분류
def classify_phase(row, threshold=0):
    p, e = row['production_yoy'], row['employment_yoy']
    if p > threshold and e > threshold:
        return 'S1'  # 동반확대
    elif p > threshold and e <= threshold:
        return 'S2'  # 생산확대·고용감소
    elif p <= threshold and e > threshold:
        return 'S3'  # 생산감소·고용증가
    else:
        return 'S4'  # 동반감소

data['phase_base'] = data.apply(classify_phase, threshold=0, axis=1)

# 2. 민감도 검사 (중립구간 ±0.5/1/2%)
for thr in [0.5, 1, 2]:
    def classify_with_band(row, t=thr):
        p, e = row['production_yoy'], row['employment_yoy']
        p_dir = 'up' if p > t else ('down' if p < -t else 'neutral')
        e_dir = 'up' if e > t else ('down' if e < -t else 'neutral')
        return f'{p_dir}_{e_dir}'
    data[f'phase_band_{thr}'] = data.apply(classify_with_band, axis=1)

# 국면 분류가 임계값에 따라 바뀌는 비율 (경계값 민감 관측치)
sensitivity_flip_rate = (data['phase_base'] != data['phase_band_1'].str.contains('neutral')).mean()
print(f"기본분류 대비 ±1% 중립구간 적용 시 재분류율: {sensitivity_flip_rate:.1%}")

# 3. 검증용 군집분석 (K-means, k=4)
X = StandardScaler().fit_transform(data[['production_yoy', 'employment_yoy']])
kmeans = KMeans(n_clusters=4, random_state=42, n_init=10).fit(X)
data['cluster_kmeans'] = kmeans.labels_

gmm = GaussianMixture(n_components=4, random_state=42).fit(X)
data['cluster_gmm'] = gmm.predict(X)

# 부호기준 vs 군집기준 교차표 (일치율 확인)
cross_tab = pd.crosstab(data['phase_base'], data['cluster_kmeans'])
print(cross_tab)

# 4. 국면별 비중
phase_dist = data['phase_base'].value_counts(normalize=True) * 100
print(phase_dist)

# 5. 핵심 검증 통계: 고용감소 중 생산증가 비율 + 95% 신뢰구간
emp_down = data[data['employment_yoy'] < 0]
n_total = len(emp_down)
n_prod_up = (emp_down['production_yoy'] > 0).sum()
prop = n_prod_up / n_total
ci_low, ci_high = proportion_confint(n_prod_up, n_total, method='wilson')
print(f"고용감소 관측치 중 생산증가 비율: {prop:.1%} (95% CI: {ci_low:.1%}~{ci_high:.1%}, n={n_total})")

# 시각화: 생산 YoY x 고용 YoY 산점도
plt.figure(figsize=(7, 7))
sns.scatterplot(data=data, x='employment_yoy', y='production_yoy', hue='phase_base',
                 style='industry', palette='Set1', s=60)
plt.axhline(0, color='gray', lw=1)
plt.axvline(0, color='gray', lw=1)
plt.xlabel('고용 YoY (%)')
plt.ylabel('생산 YoY (%)')
plt.title('생산·고용 4국면 분류')
plt.tight_layout()
plt.savefig('step2_phase_scatter.png', dpi=150)
```

---

## 4. STEP 3 — 국면 지속성 분석

### 사용 데이터
STEP 2에서 산출된 업종별 국면 시퀀스 (10개 업종 × 33분기)

### 방법론
1. 업종별 동일국면 연속분기 수(run-length) 계산
2. 국면별 평균 지속기간, 최장 지속기간
3. **생존분석 관점 추가**: 국면 지속기간을 이벤트(=국면전환)까지의 시간으로 보고 Kaplan-Meier 생존곡선 산출 — 국면 유형별(S1~S4) 지속기간 분포 비교
4. 최근 4분기 내 동일국면 반복 횟수

### 근거 문헌 및 반박 논리
| 예상 질문 | 근거 문헌 | 반박 논리 |
|---|---|---|
| "지속기간 계산이 왜 필요하냐, 그냥 통계 아니냐" | Diebold, F.X. & Rudebusch, G.D.(1990), "A Nonparametric Investigation of Duration Dependence in the American Business Cycle," Journal of Political Economy, 98 | 경기순환 연구에서도 국면 종료확률이 지속기간에 따라 변화하는지(duration dependence)를 검증하는 것이 표준 절차이며, 이 검증 없이 국면을 구조적 특징으로 해석하는 것은 방법론적 결함으로 지적됨 |

### 방법론 채택 근거 (문헌 기반 서술)

STEP 3에서 지속기간을 단순 카운트에 그치지 않고 생존분석(Kaplan-Meier)까지 확장한 것은 Diebold & Rudebusch(1990, *Journal of Political Economy*)의 문제의식에 기반한다. 이들은 경기순환을 팽창·수축이라는 두 이산 상태를 오가는 마르코프 과정으로 모형화할 때, 국면의 종료확률이 지속기간과 무관하게 일정한지(constant hazard, Hamilton(1989)의 가정) 아니면 지속기간에 따라 변화하는지(duration dependence, Neftci(1982)의 가정)를 사전에 검증해야 한다고 지적하였다. 즉 "한 국면이 몇 분기 지속되었다"는 관측만으로는 그 국면이 구조적인지 일시적인지 판단할 수 없으며, 지속기간의 분포 자체를 통계적으로 다루어야 한다는 것이다.

본 연구가 국면 유형별(S1~S4) Kaplan-Meier 생존곡선을 별도로 산출하는 이유도 여기에 있다. 만약 S4(동반감소) 국면의 생존곡선이 S2(생산확대·고용감소) 국면보다 시간이 지나도 완만하게 감소한다면, 이는 S4가 S2보다 더 구조적으로 고착되는 경향이 있다는 정량적 근거가 된다. 이는 계획서 Q2의 "일시적 변동과 반복·지속되는 국면을 구분한다"는 목표를 통계적으로 뒷받침하는 절차이며, 단순 최장지속분기 수 나열보다 방법론적으로 한 단계 더 나아간 접근이다.

### EDA 작업 목록
1. 업종별 국면 지속기간 히스토그램 (S1~S4 색상 구분)
2. Kaplan-Meier 생존곡선 (국면 유형별 4개 곡선 중첩)
3. 업종별 "국면 유지율" = 1 - (전환횟수/전체분기수) 랭킹 테이블
4. S2·S4 최장지속 업종 Top3 하이라이트

### 코드

```python
from lifelines import KaplanMeierFitter

data = data.sort_values(['industry', 'quarter'])

# 1. run-length (연속 지속분기 수) 계산
data['phase_shift'] = data.groupby('industry')['phase_base'].shift(1)
data['is_new_run'] = (data['phase_base'] != data['phase_shift']).astype(int)
data['run_id'] = data.groupby('industry')['is_new_run'].cumsum()

run_length = (data.groupby(['industry', 'run_id', 'phase_base'])
                   .size()
                   .reset_index(name='duration_quarters'))

# 2. 국면별 평균/최장 지속기간
duration_summary = run_length.groupby('phase_base')['duration_quarters'].agg(['mean', 'max', 'count'])
print(duration_summary)

# 업종별 S2, S4 최장지속 Top3
for phase in ['S2', 'S4']:
    top3 = (run_length[run_length['phase_base'] == phase]
            .sort_values('duration_quarters', ascending=False)
            .head(3))
    print(f"\n[{phase}] 최장지속 업종 Top3")
    print(top3[['industry', 'duration_quarters']])

# 3. Kaplan-Meier 생존곡선 (국면 유형별)
# event_observed=1: 관측기간 내 전환 발생(=지속기간 종료가 확인됨)
# 마지막 run은 실제로 언제 끝날지 모르므로 censored(event_observed=0) 처리
run_length['is_censored'] = 0
last_run_idx = data.groupby('industry')['run_id'].transform('max')
censored_runs = data[data['run_id'] == last_run_idx][['industry', 'run_id']].drop_duplicates()
run_length = run_length.merge(censored_runs.assign(is_censored=1), on=['industry', 'run_id'], how='left', suffixes=('', '_c'))
run_length['is_censored'] = run_length['is_censored'].fillna(0)
run_length['event_observed'] = 1 - run_length['is_censored']

plt.figure(figsize=(8, 6))
kmf = KaplanMeierFitter()
for phase in ['S1', 'S2', 'S3', 'S4']:
    subset = run_length[run_length['phase_base'] == phase]
    kmf.fit(subset['duration_quarters'], event_observed=subset['event_observed'], label=phase)
    kmf.plot_survival_function(ci_show=True)
plt.xlabel('지속분기 수')
plt.ylabel('국면 유지 확률')
plt.title('국면 유형별 Kaplan-Meier 생존곡선')
plt.tight_layout()
plt.savefig('step3_survival_curve.png', dpi=150)

# 4. 업종별 국면 유지율 = 1 - (전환횟수 / 전체분기수)
transitions_per_industry = data.groupby('industry')['is_new_run'].sum() - 1  # 첫 관측 제외
total_quarters_per_industry = data.groupby('industry').size()
retention_rate = (1 - transitions_per_industry / total_quarters_per_industry).sort_values(ascending=False)
print("\n업종별 국면 유지율 랭킹")
print(retention_rate)
```

---

## 5. STEP 4 — 국면 전환 분석

### 사용 데이터
업종별 국면 시퀀스 (t → t+1 쌍)

### 방법론
1. 전체 및 업종별 상태전환행렬(transition matrix) 산출 (빈도 및 확률 정규화 버전 병행)
2. 정상분포(stationary distribution) 계산 — 장기적으로 산단이 수렴하는 국면 비율 추정
3. 업종별 State Timeline 시각화
4. (선택) 마르코프성 가정 점검 — 2분기 전 국면이 현재 전환확률에 유의한 영향을 주는지 간단한 교차표 검정

### 근거 문헌 및 반박 논리
| 예상 질문 | 근거 문헌 | 반박 논리 |
|---|---|---|
| "전환행렬/마르코프 접근이 산업분석에 쓰인 적 있냐" | Hamilton, J.D.(1989), Econometrica (마르코프 국면전환모형 원조) / Hamilton, J.D. & Owyang, M.T. 계열 연구 (clustered Markov-switching, 주·산업 단위 경기국면 동조화 분석) | 지역·산업 단위 경기국면의 동조화·전환을 클러스터형 마르코프모형으로 분석한 선례가 있으며, 본 분석은 이를 업종 간 비교가 아닌 개별 업종의 시계열 전환경로 추적에 응용함 |
| "전환확률을 미래 예측처럼 오해하지 않냐" | (계획서 자체 명시) | 전환행렬은 과거 관측 빈도이며 미래 예측확률이 아님을 보고서에 명시적으로 기술 |

### 방법론 채택 근거 (문헌 기반 서술)

전환행렬 및 마르코프 체인 접근은 Hamilton(1989, *Econometrica*)이 제안한 국면전환모형(regime-switching model)의 핵심 개념 — 경제 시계열의 상태가 관측되지 않는 확률변수 s_t ∈ {1, ..., M}에 의해 결정되며, 이 상태가 마르코프 과정을 따라 전환된다는 아이디어 — 를 원용한 것이다. Hamilton의 원 모형은 단일 시계열(미국 GNP)의 국면전환을 다루었으나, 이후 연구는 이를 다변량·다지역·다산업으로 확장하였다. 특히 Hamilton & Owyang 계열 연구는 주(state) 단위 경기순환의 동조화(comovement)를 클러스터형 마르코프 국면전환모형으로 분석하였고, 산업 단위로도 이 동조화가 나타나는지, 나아가 이 동조화가 단일 산업분류 내 하위부문에 국한되는지를 검토하여 4개의 산업 클러스터를 확인하였다.

이는 두 가지 점에서 본 연구의 STEP 4를 뒷받침한다. 첫째, 산업 단위 시계열에 마르코프 국면전환 개념을 적용하는 것이 방법론적으로 이례적이지 않다는 선례를 제공한다. 둘째, 원 문헌이 "국면 간 동조화·클러스터"를 분석 대상으로 삼았다는 점은, 본 연구가 향후 업종 간 전환패턴 비교(9절 "국면별 반복 패턴·전환경로 비교")로 확장할 때도 동일한 이론적 틀 안에서 정당화될 수 있음을 시사한다. 다만 본 연구는 상태 자체를 잠재변수로 추정하는 완전한 Markov-switching 계량모형(모수 추정)을 적용하는 것이 아니라, 이미 확정적으로 분류된 국면 시퀀스로부터 관측된 전환 빈도를 집계하는 기술통계적(descriptive) 접근이라는 점에서 방법론적 범위를 스스로 제한하고 있으며, 이 차이는 보고서에 명확히 기술되어야 한다.

### EDA 작업 목록
1. 전체 전환행렬 히트맵 (4×4, 빈도/확률 2종)
2. 업종별 전환행렬 소형 다중패널
3. 전환 네트워크 그래프 (노드=국면, 엣지 굵기=전환빈도)
4. 정상분포 막대차트 및 실제 최근 4분기 분포와의 비교
5. 업종별 State Timeline (간트차트 스타일)

### 코드

```python
import networkx as nx

phases = ['S1', 'S2', 'S3', 'S4']

# 1. t -> t+1 쌍 만들기 (업종 내에서만, 분기 연속인 경우만)
data['phase_next'] = data.groupby('industry')['phase_base'].shift(-1)
transitions = data.dropna(subset=['phase_next'])[['industry', 'quarter', 'phase_base', 'phase_next']]

# 2. 전체 전환행렬 (빈도)
trans_freq = pd.crosstab(transitions['phase_base'], transitions['phase_next']).reindex(index=phases, columns=phases, fill_value=0)
# 확률 정규화 (행 합=1)
trans_prob = trans_freq.div(trans_freq.sum(axis=1), axis=0)

print("전환행렬 (빈도)\n", trans_freq)
print("\n전환행렬 (확률)\n", trans_prob.round(2))

plt.figure(figsize=(6, 5))
sns.heatmap(trans_prob, annot=True, fmt='.2f', cmap='Blues')
plt.title('전체 국면 전환확률 행렬')
plt.xlabel('t+1 국면')
plt.ylabel('t 국면')
plt.tight_layout()
plt.savefig('step4_transition_matrix.png', dpi=150)

# 3. 정상분포(stationary distribution) 계산
# pi * P = pi 를 만족하는 좌측 고유벡터 (고유값 1)
P = trans_prob.values
eigvals, eigvecs = np.linalg.eig(P.T)
stat_idx = np.argmin(np.abs(eigvals - 1))
stationary = np.real(eigvecs[:, stat_idx])
stationary = stationary / stationary.sum()
stationary_dist = pd.Series(stationary, index=phases)
print("\n정상분포 (장기 수렴 국면 비율)\n", stationary_dist.round(3))

# 실제 최근 4분기 분포와 비교
recent_dist = data[data['quarter'] >= data['quarter'].max() - 3]['phase_base'].value_counts(normalize=True).reindex(phases, fill_value=0)
compare = pd.DataFrame({'정상분포(이론)': stationary_dist, '최근4분기(실제)': recent_dist})
print(compare.round(3))

# 4. 전환 네트워크 그래프
G = nx.DiGraph()
for i in phases:
    for j in phases:
        w = trans_freq.loc[i, j]
        if w > 0:
            G.add_edge(i, j, weight=w)

pos = nx.circular_layout(G)
edge_widths = [G[u][v]['weight'] * 0.3 for u, v in G.edges()]
plt.figure(figsize=(6, 6))
nx.draw(G, pos, with_labels=True, node_size=1500, node_color='lightblue',
        width=edge_widths, arrowsize=20, connectionstyle='arc3,rad=0.1')
edge_labels = nx.get_edge_attributes(G, 'weight')
nx.draw_networkx_edge_labels(G, pos, edge_labels=edge_labels)
plt.title('국면 전환 네트워크')
plt.savefig('step4_transition_network.png', dpi=150)

# 5. 업종별 State Timeline (간트차트 스타일)
industries_list = data['industry'].unique()
fig, ax = plt.subplots(figsize=(14, 6))
phase_colors = {'S1': '#4CAF50', 'S2': '#FFC107', 'S3': '#03A9F4', 'S4': '#F44336'}
for idx, ind in enumerate(industries_list):
    sub = data[data['industry'] == ind].sort_values('quarter')
    for _, row in sub.iterrows():
        ax.barh(idx, 1, left=list(quarters).index(row['quarter']),
                color=phase_colors.get(row['phase_base'], 'gray'))
ax.set_yticks(range(len(industries_list)))
ax.set_yticklabels(industries_list)
ax.set_xlabel('분기 인덱스')
ax.set_title('업종별 State Timeline')
plt.tight_layout()
plt.savefig('step4_state_timeline.png', dpi=150)
```

---

## 6. STEP 5 — 가동률·업체수 결합

### 사용 데이터
STEP 2 국면 + 제조업 가동률, 입주업체수, 가동업체수

### 방법론
1. 동일 국면(예: S2) 내에서 가동률·업체수 변화 기준 계층적 군집분석(hierarchical clustering)으로 서브타입 도출
2. 가동업체수 변화와 업체당 평균고용 변화를 분해 — 고용감소가 "기업수 감소" 때문인지 "기업당 고용감소" 때문인지 구분

### 근거 문헌
| 예상 질문 | 근거 문헌 |
|---|---|
| "KICOX 원자료를 이렇게 계량분석에 쓴 선례가 있냐" | 곽철홍·고석남(2005), "기업생산성의 공간격차 분석 - 한국 산업단지 내 제조업을 중심으로 -," 한국경제지리학회지, 8(2), 237-245 — 한국산업단지관리공단(현 KICOX) 원자료(생산·고용·수출·투자)를 계량분석에 활용한 국내 선행연구 |

### 방법론 채택 근거 (문헌 기반 서술)

STEP 5에서 가동률·업체수를 보조축으로 결합하는 방식은, 곽철홍·고석남(2005, 한국경제지리학회지)이 한국산업단지관리공단(현 KICOX)의 전수조사 원자료(생산·고용·수출·투자)를 이용해 산업단지 내 기업의 노동생산성 격차를 분석한 선행연구에서 방법론적 정당성을 얻는다. 해당 연구는 입주기간, 자본규모, 고용자 수, 설비투자 규모 등이 노동생산성에 유의한 영향을 미치며 업종별로도 편차가 크게 나타난다는 점을 확인하였는데, 이는 동일한 산업단지·동일한 생산·고용 국면 안에서도 기업 특성에 따라 이질적인 결과가 나타날 수 있다는 본 연구 Q4의 전제와 부합한다.

다만 해당 선행연구는 2003년 시점의 횡단면(cross-section) 분석인 반면, 본 연구는 2018~2026년 장기 패널을 이용한 시계열 국면·전환 분석이라는 점에서 방법론적으로 차별화된다. 즉 STEP 5의 계층적 군집분석(가동률·업체수 기준 서브타입 도출)은 선행연구의 "동일 산업단지 내 기업 이질성" 문제의식을 시계열 국면 분석 틀 안으로 확장 적용한 것으로 서술하는 것이 적절하다.

### EDA 작업 목록
1. 동일 국면 내 가동률·업체수 변화 산점도 (서브타입 색상 구분)
2. 가동업체수 변화율 vs 업체당 평균고용 변화율 분해 차트
3. 서브타입별 대표 업종 사례 정리

### 코드

```python
from scipy.cluster.hierarchy import linkage, fcluster, dendrogram

# 보조지표 YoY 계산
panel['util_yoy'] = panel.groupby('industry')['utilization_rate'].diff(4)  # 가동률은 %p 차이 권장
panel['num_operating_yoy'] = panel.groupby('industry')['num_operating'].pct_change(4) * 100

merged = data.merge(panel[['industry', 'quarter', 'util_yoy', 'num_operating_yoy',
                            'employment', 'num_operating']],
                     on=['industry', 'quarter'], how='left')

# 1. 동일 국면(S2) 내 서브타입 계층적 군집
s2 = merged[merged['phase_base'] == 'S2'].dropna(subset=['util_yoy', 'num_operating_yoy']).copy()
X_s2 = StandardScaler().fit_transform(s2[['util_yoy', 'num_operating_yoy']])
Z = linkage(X_s2, method='ward')
s2['subtype'] = fcluster(Z, t=2, criterion='maxclust')  # 2개 서브타입으로 분리

plt.figure(figsize=(6, 6))
sns.scatterplot(data=s2, x='num_operating_yoy', y='util_yoy', hue='subtype',
                 style='industry', s=80, palette='Set2')
plt.axhline(0, color='gray', lw=1)
plt.axvline(0, color='gray', lw=1)
plt.title('S2 국면 내 가동률·업체수 기준 서브타입')
plt.tight_layout()
plt.savefig('step5_subtype_scatter.png', dpi=150)

# 2. 가동업체수 변화 vs 업체당 평균고용 변화 분해
merged['emp_per_firm'] = merged['employment'] / merged['num_operating']
merged['emp_per_firm_yoy'] = merged.groupby('industry')['emp_per_firm'].pct_change(4) * 100

decomp = merged[merged['phase_base'] == 'S2'][
    ['industry', 'quarter', 'employment_yoy', 'num_operating_yoy', 'emp_per_firm_yoy']
]
print(decomp)
# employment_yoy ≈ num_operating_yoy + emp_per_firm_yoy (근사) 로 고용감소 원인 성격 구분
```

---

## 7. STEP 6 — 업종별 진단카드

### 구성요소 (업종당 1장, 총 10장)
- 현재 국면 및 지속기간
- 보조지표(가동률/업체수) 현황
- 최근 전환경로 (State Timeline 축약)
- 데이터가 직접 말하는 것 / 판단 불가한 것 / 다음 확인사항 3단 구분

### 코드

```python
next_step_lookup = {
    'S1': '인력공급 지속 가능성, 기업수 변화',
    'S2': '채용수요, 직무구조, 기업별 고용 차이',
    'S3': '고용 유지 배경, 시차 여부',
    'S4': '가동률, 업체수, 수요 변화',
}

def make_diagnostic_card(industry_name):
    sub = merged[merged['industry'] == industry_name].sort_values('quarter')
    latest = sub.iloc[-1]
    current_phase = latest['phase_base']

    # 현재 국면 지속기간 (STEP3의 run_length 활용)
    current_run = run_length[(run_length['industry'] == industry_name)].iloc[-1]
    duration = current_run['duration_quarters']

    recent_path = ' → '.join(sub['phase_base'].tail(5).tolist())

    card = f"""
==================================================
업종: {industry_name}
--------------------------------------------------
현재 국면        : {current_phase}
현재 지속기간    : {duration}분기
가동률 YoY       : {latest['util_yoy']:.1f}%p
가동업체수 YoY   : {latest['num_operating_yoy']:.1f}%
최근 전환경로    : {recent_path}
--------------------------------------------------
데이터가 직접 말하는 것: 생산·고용 변화방향이 {duration}분기 동안 {current_phase} 상태로 나타남
현재 데이터로 판단 불가: 원인(자동화/인력부족/외주화 등)은 본 분석 범위 밖
다음 확인사항    : {next_step_lookup[current_phase]}
==================================================
"""
    return card

for ind in industries_list:
    print(make_diagnostic_card(ind))
```

---

## 8. 전체 보고서 집필 시 유의사항 (한계 명시 파트 강화)

기획안 12번 "프로젝트의 한계"에 아래 방법론적 한계를 추가로 명시할 것을 권장:

1. **생존분석 표본 한계**: 33분기 패널에서 국면전환 이벤트 수가 제한적이므로 Kaplan-Meier 곡선의 신뢰구간이 넓을 수 있음 — 이를 은폐하지 말고 신뢰구간과 함께 제시
2. **마르코프성 가정**: 실제 산업 국면이 2차 이상 마르코프 과정을 따를 가능성 배제 못함 — 1차 근사임을 명시
3. **군집분석의 임의성**: K-means의 k=4 설정 자체도 완전히 데이터 주도적이지 않으므로, 부호기준 분류와의 일치율을 "검증 지표"로만 사용하고 최종 분류 기준은 부호기준임을 명확히

이 한계를 먼저 인정하는 서술이, 오히려 "방법론을 제대로 이해하고 쓴다"는 인상을 주어 반문 방어에 유리함.

---

## 9. 참고문헌 (References)

1. Bry, G. & Boschan, C. (1971). *Cyclical Analysis of Time Series: Selected Procedures and Computer Programs*. NBER, New York.
2. Diebold, F. X. & Rudebusch, G. D. (1990). A Nonparametric Investigation of Duration Dependence in the American Business Cycle. *Journal of Political Economy*, 98(3), 598-616.
3. Gil, E. (2023). Jobless Growth in the Manufacturing Industry - Decoupling Sectoral Output and Employment in the United States and South Korea. *KIET Industrial Economic Review*, Korea Institute for Industrial Economics and Trade.
4. Hamilton, J. D. (1989). A New Approach to the Economic Analysis of Nonstationary Time Series and the Business Cycle. *Econometrica*, 57(2), 357-384.
5. Hamilton, J. D. & Owyang, M. T. (2012) 계열 연구 — Clustered Markov-switching model을 이용한 지역·산업 경기국면 동조화 분석.
6. Harding, D. & Pagan, A. (2002). Dissecting the Cycle: A Methodological Investigation. *Journal of Monetary Economics*, 49(2), 365-381.
7. Jaimovich, N. & Siu, H. Job Polarization and Jobless Recoveries. *NBER Working Paper* No. 18334.
8. 곽철홍·고석남 (2005). 기업생산성의 공간격차 분석 - 한국 산업단지 내 제조업을 중심으로 -. *한국경제지리학회지*, 8(2), 237-245.

---

## 10. EDA 실행 순서 체크리스트 (실무용)

- [ ] STEP 0: 패널 완전성 확인, 보정값 반영, 결측맵 작성
- [ ] STEP 1: 산단 전체 및 업종별 원계열 시각화
- [ ] STEP 2-1: 부호기준 4국면 분류 (기본 + 중립구간 3종)
- [ ] STEP 2-2: K-means/GMM 군집분석 및 부호기준과 교차검증
- [ ] STEP 2-3: 고용감소 중 생산증가 비율 재계산 (신뢰구간 포함)
- [ ] STEP 3-1: 업종별 국면 지속기간 계산
- [ ] STEP 3-2: Kaplan-Meier 생존곡선 (국면유형별)
- [ ] STEP 4-1: 전체/업종별 전환행렬 산출
- [ ] STEP 4-2: 정상분포 계산 및 최근 4분기 실제 분포와 비교
- [ ] STEP 5-1: 국면 내 가동률·업체수 계층적 군집
- [ ] STEP 5-2: 가동업체수 vs 업체당고용 분해
- [ ] STEP 6: 업종별 진단카드 10장 제작
- [ ] STEP 9: 참고문헌 및 한계 서술 최종 반영
