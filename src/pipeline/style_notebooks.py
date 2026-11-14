"""Build the final notebook storyline from production outputs and archived evidence.

The notebooks are report chapters, not alternative implementations of the model.
They read the production pipeline's canonical outputs and archived experiment records,
then visualise, verify and interpret them.
"""
from __future__ import annotations

from pathlib import Path
import re

import nbformat


ROOT = Path(__file__).resolve().parents[2]
NB_DIR = ROOT / "notebooks"


def md(source: str):
    return nbformat.v4.new_markdown_cell(source.strip())


def code(source: str):
    return nbformat.v4.new_code_cell(source.strip())


def intro(number: str, title: str, question: str, previous: str, doing: str, not_doing: str) -> str:
    return f"""
# Notebook {number}. {title}

## 이 단계의 질문

{question}

## 이전 단계에서 확인한 것

{previous}

## 이번 단계에서 하는 것

{doing}

## 이번 단계에서 하지 않는 것

{not_doing}
"""


def conclusion(facts: str, interpretation: str, limits: str, reason: str, next_file: str | None) -> str:
    tail = f"\n\n→ 다음: `{next_file}`" if next_file else "\n\n→ 다음: 담당자 확인 결과를 기록하고 다음 분기에 재점검"
    return f"""
# 단계 결론

## 확인된 사실

{facts}

## 해석

{interpretation}

## 이 단계만으로 말할 수 없는 것

{limits}

## 다음 단계가 필요한 이유

{reason}{tail}
"""


SETUP = r'''
from pathlib import Path
import sys, json
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from IPython.display import display, Markdown

ROOT = next(p for p in [Path.cwd(), *Path.cwd().parents] if (p / 'src').is_dir())
sys.path.insert(0, str(ROOT / 'src'))
from utils import notebook_config as config
from core.analysis.config import setup_matplotlib
setup_matplotlib()
pd.set_option('display.max_columns', 40)
pd.set_option('display.max_colwidth', 120)

def _md_value(value):
    if pd.isna(value): return '—'
    if isinstance(value, (float, np.floating)): return f'{value:,.2f}'
    return str(value).replace('|', '\\|').replace('\n', ' / ')

def show_table(frame, max_rows=30):
    view=frame.head(max_rows)
    header='| '+' | '.join(map(str,view.columns))+' |'
    rule='| '+' | '.join(['---']*len(view.columns))+' |'
    rows=['| '+' | '.join(_md_value(v) for v in row)+' |' for row in view.itertuples(index=False,name=None)]
    note=f'\n\n*상위 {max_rows}행만 표시*' if len(frame)>max_rows else ''
    display(Markdown('\n'.join([header,rule,*rows])+note))

def show_records(frame, title_col, fields=None, max_rows=30):
    fields=fields or [c for c in frame.columns if c!=title_col]
    blocks=[]
    for _, row in frame.head(max_rows).iterrows():
        blocks.append('#### '+_md_value(row[title_col]))
        blocks.extend(f'- **{c}:** {_md_value(row[c])}' for c in fields)
    if len(frame)>max_rows: blocks.append(f'*상위 {max_rows}건만 표시*')
    display(Markdown('\n\n'.join(blocks)))

STAGE_ORDER = ['관찰', '추가확인', '우선점검', '자료확인']
STAGE_COLORS = {'관찰':'#7895A8', '추가확인':'#D39A2C', '우선점검':'#C5523F', '자료확인':'#777777'}
STATE_ORDER = ['S1', 'S2', 'S3', 'S4', 'N', 'INVALID']
STATE_COLORS = {'S1':'#4C78A8','S2':'#72B7B2','S3':'#F2CF5B','S4':'#B279A2','N':'#BDBDBD','INVALID':'#F2F2F2'}
'''


def notebook_01():
    return [
        md(intro(
            "01", "CORE 진단 — 상태·규모·시간",
            "창원국가산단의 생산과 고용은 어떻게 변화했고, 그 변화는 업종별로 어떻게 다른가?",
            "Notebook 00에서 KICOX 원자료를 동일한 업종×분기 패널로 정리하고 결측·개정·분류 경계를 검증했다.",
            "Q1 상태(State), Q2 규모(Scale), Q3 시간(Time)을 분리해 관찰한 뒤 하나의 진단표로 결합한다. 과거 `02_eda.ipynb`와 `03_q1_q2_q3_integrated_analysis.ipynb`의 핵심 분석을 production 산출물로 재현한다.",
            "정책 우선순위, 위기 여부, 기업별 원인 또는 지원대상을 결정하지 않는다. 생산액은 명목값이며 가격과 물량을 분리하지 않는다."
        )),
        md('''
## 분석 흐름

```text
KICOX 업종×분기 패널
├─ Q1 State : 생산 YoY × 고용 YoY
├─ Q2 Scale : 고용 증감 인원·비중·기여
└─ Q3 Time  : 지속기간·전환·반복
          ↓
      CORE 진단표
```

Q1의 S1~S4는 좋고 나쁨의 순위가 아니라 두 축의 방향 조합이다.
'''),
        code(SETUP),
        code('''
core = pd.read_csv(config.CORE_TABLE_DIR / 'core_panel.csv', encoding='utf-8-sig')
state = pd.read_csv(config.STATE_PANEL_PATH, encoding='utf-8-sig')
total = pd.read_csv(config.KICOX_TOTAL_PATH, encoding='utf-8-sig')
assert len(core) == 180 and not core.duplicated(['industry','quarter']).any()
assert core['industry'].nunique() == 10 and core['quarter'].nunique() == 18
latest_q = core['quarter'].max()
latest = core.loc[core.quarter.eq(latest_q)].copy()
print(f'분석 단위: {len(core):,}개 업종×분기 | 업종 {core.industry.nunique()}개 | 기간 {core.quarter.min()}~{latest_q}')
'''),
        md('''
## 1. 전체 흐름 — 생산과 고용의 공통 배경

업종 상태를 보기 전에 산단 전체 수준의 장기 방향을 확인한다. 서로 단위가 다른 생산액과 고용은 2022Q1=100 지수로 비교한다.
'''),
        code('''
t = total.loc[total.quarter.between(core.quarter.min(), latest_q), ['quarter','production_total','employment_total']].copy().sort_values('quarter')
for col in ['production_total','employment_total']:
    t[col.replace('_total','_index')] = t[col] / t[col].iloc[0] * 100
ax = t.plot(x='quarter', y=['production_index','employment_index'], marker='o', figsize=(11,4), color=['#2F5C8F','#9C5C86'])
ax.axhline(100, color='#999', lw=0.8); ax.set_ylabel('2022Q1=100'); ax.set_xlabel(''); ax.set_title('창원국가산단 전체 생산·고용 지수')
ax.legend(['명목 생산액','고용'], frameon=False); plt.xticks(rotation=45); plt.tight_layout(); plt.show()
display(Markdown(f"""### 관찰

- {latest_q}의 생산지수는 **{t.production_index.iloc[-1]:.1f}**, 고용지수는 **{t.employment_index.iloc[-1]:.1f}**이다.

### 해석

- 두 지수의 경로가 같지 않으므로 산단 총량만으로 업종별 고용 변화를 설명할 수 없다.

### 주의

- 생산은 명목액이므로 지수 상승·하락을 물량 변화로 단정할 수 없다."""))
'''),
        md('''
## 2. Q1 State — 생산과 고용은 어느 방향으로 움직였는가?

- S1: 생산↑·고용↑
- S2: 생산↑·고용↓
- S3: 생산↓·고용↑
- S4: 생산↓·고용↓
- N/INVALID: 0% 경계 또는 계산 불가
'''),
        code('''
valid = latest.dropna(subset=['production_yoy','employment_yoy']).copy()
fig, ax = plt.subplots(figsize=(9,6))
for s, g in valid.groupby('state'):
    ax.scatter(g.production_yoy, g.employment_yoy, s=90, color=STATE_COLORS.get(s,'#999'), label=s, alpha=.9)
    for r in g.itertuples(): ax.annotate(r.industry, (r.production_yoy, r.employment_yoy), xytext=(5,4), textcoords='offset points', fontsize=9)
ax.axhline(0,color='#555',lw=1); ax.axvline(0,color='#555',lw=1)
ax.set(xlabel='명목 생산 YoY(%)', ylabel='고용 YoY(%)', title=f'Q1 최신분기 사분면 — {latest_q}')
ax.legend(title='상태', frameon=False, ncol=3); plt.tight_layout(); plt.show()
show_table(latest[['industry','state','production_yoy','employment_yoy']].sort_values(['state','industry']).round(2))
display(Markdown(f"""### 관찰

- 최신분기에는 **{latest.state.value_counts().to_dict()}**의 상태 분포가 관측된다.

### 해석

- 같은 고용 감소라도 생산 방향이 다른 S2와 S4는 확인 질문이 달라야 한다.

### 주의

- 사분면 위치는 상태 묘사이며 위험 순위나 원인 진단이 아니다."""))
'''),
        code('''
pivot = core.pivot(index='industry', columns='quarter', values='state')
code_map = {s:i for i,s in enumerate(STATE_ORDER)}
z = pivot.map(lambda x: code_map.get(x, len(STATE_ORDER)-1)).to_numpy()
from matplotlib.colors import ListedColormap
fig, ax = plt.subplots(figsize=(14,5))
ax.imshow(z, aspect='auto', cmap=ListedColormap([STATE_COLORS[s] for s in STATE_ORDER]), vmin=0, vmax=len(STATE_ORDER)-1)
ax.set_xticks(range(len(pivot.columns)), pivot.columns, rotation=45, ha='right'); ax.set_yticks(range(len(pivot.index)), pivot.index)
for i in range(z.shape[0]):
    for j in range(z.shape[1]): ax.text(j,i,pivot.iloc[i,j],ha='center',va='center',fontsize=7)
ax.set_title('업종×분기 상태 히트맵'); plt.tight_layout(); plt.show()
display(Markdown("""### 관찰

- 상태는 업종별로 반복·전환되며, 한 분기의 위치만으로 장기 경로를 대표할 수 없다.

### 해석

- Q1은 변화의 방향을 압축하지만 변화의 크기와 지속성을 별도로 봐야 한다.

### 주의

- 색은 범주 구분용이며 좋음/나쁨의 연속 척도가 아니다."""))
'''),
        md('''
## 3. Q2 Scale — 고용 변화의 실제 규모는 얼마인가?

고용 YoY 비율만 보면 작은 업종의 큰 비율 변화와 큰 업종의 작은 비율 변화를 구분하기 어렵다. 그래서 증감 인원, 현재 고용비중, 산단 순변화 기여율을 함께 본다. 기여율은 순변화가 업종별 총변화에 비해 충분히 클 때만 해석한다.
'''),
        code('''
q2 = latest.sort_values('emp_delta')
fig, ax = plt.subplots(figsize=(9,5)); colors = ['#B4485F' if x < 0 else '#3F6FA8' for x in q2.emp_delta]
ax.barh(q2.industry, q2.emp_delta, color=colors); ax.axvline(0,color='#555',lw=.8); ax.set_xlabel('전년동기 대비 고용 증감(명)')
ax.set_title(f'Q2 최신분기 고용 증감 규모 — {latest_q}')
for y, x in enumerate(q2.emp_delta): ax.text(x, y, f' {x:,.0f}', va='center', ha='left' if x>=0 else 'right', fontsize=8)
plt.tight_layout(); plt.show()
show = q2[['industry','emp_delta','employment_share_pct','contribution_pct']].copy()
show.columns=['업종','고용증감(명)','현재 고용비중(%)','산단 순변화 기여율(%)']; show_table(show.round(2))
display(Markdown(f"""### 관찰

- 최신분기 산단 제조업 고용 순증감은 **{latest.emp_delta.sum():,.0f}명**이며, 업종별 증감 규모는 크게 다르다.

### 해석

- 같은 Q1 상태라도 절대 고용 영향이 다르므로 확인 순서에는 Q2 규모가 필요하다.

### 주의

- 기여율은 인과 기여가 아니라 산술적 순변화 구성이다. 업종 간 상쇄가 큰 분기에는 표시·해석을 제한한다."""))
'''),
        md('''
## 4. Q3 Time — 변화는 얼마나 지속되고 어떻게 전환했는가?

Q3는 동일 상태의 관측 지속기간, 직전→현재 상태 전환, 실제 직전 달력분기의 고용 진입신호 반복을 구분한다. 이 셋은 같은 개념이 아니다.
'''),
        code('''
top4 = latest.nlargest(4, 'employment').industry.tolist()
timeline = core.loc[core.industry.isin(top4)].pivot(index='quarter',columns='industry',values='state')
z = timeline.T.map(lambda x: code_map.get(x,5)).to_numpy(); fig, ax = plt.subplots(figsize=(13,3.6))
ax.imshow(z, aspect='auto', cmap=ListedColormap([STATE_COLORS[s] for s in STATE_ORDER]), vmin=0, vmax=5)
ax.set_xticks(range(len(timeline.index)),timeline.index,rotation=45,ha='right'); ax.set_yticks(range(len(timeline.columns)),timeline.columns)
for i in range(z.shape[0]):
    for j in range(z.shape[1]): ax.text(j,i,timeline.iloc[j,i],ha='center',va='center',fontsize=7)
ax.set_title('주요 4개 업종 상태 timeline'); plt.tight_layout(); plt.show()
runs = latest[['industry','state','run_length']].sort_values('run_length')
ax = runs.plot.barh(x='industry',y='run_length',legend=False,color='#657E92',figsize=(8,4))
ax.set_xlabel('현재 상태 관측 지속분기'); ax.set_title(f'현재 상태 지속기간 — {latest_q}'); plt.tight_layout(); plt.show()
'''),
        code('''
tr = core.loc[core.previous_state.isin(STATE_ORDER[:5]) & core.state.isin(STATE_ORDER[:5])]
matrix = pd.crosstab(tr.previous_state, tr.state).reindex(index=STATE_ORDER[:5],columns=STATE_ORDER[:5],fill_value=0)
fig, ax = plt.subplots(figsize=(6,5)); im=ax.imshow(matrix,cmap='Blues')
ax.set_xticks(range(5),matrix.columns); ax.set_yticks(range(5),matrix.index); ax.set_xlabel('현재 상태'); ax.set_ylabel('직전 상태'); ax.set_title('상태 전환행렬(건수)')
for i in range(5):
    for j in range(5): ax.text(j,i,int(matrix.iloc[i,j]),ha='center',va='center')
plt.colorbar(im,ax=ax,shrink=.75); plt.tight_layout(); plt.show()
display(Markdown(f"""### 관찰

- 최신분기 현재 상태 지속기간은 **{int(latest.run_length.min())}~{int(latest.run_length.max())}분기** 범위다.
- 전환행렬은 반복 상태와 상태 간 이동을 건수로 보여준다.

### 해석

- 일시적 변화와 반복·지속 변화를 구분하려면 Q3가 필요하다.

### 주의

- 관측기간 시작·끝 또는 결측에 닿는 run은 실제 전체 지속기간보다 짧을 수 있다. 전환건수는 전환확률이 아니다."""))
'''),
        md('''
## 5. Q1~Q3 통합 진단표

아래 표는 우선순위가 아니라 다음 단계가 사용할 사실 묶음이다.
'''),
        code('''
integrated = latest[['industry','state','production_yoy','employment_yoy','emp_delta','employment_share_pct','contribution_pct','run_length','previous_state']].copy()
integrated['transition'] = integrated.previous_state.fillna('?') + ' → ' + integrated.state.fillna('?')
integrated = integrated.drop(columns='previous_state').sort_values('emp_delta')
integrated.columns=['업종','Q1 상태','생산 YoY(%)','고용 YoY(%)','고용증감(명)','고용비중(%)','순변화 기여율(%)','현재상태 지속(Q)','직전→현재']
show_table(integrated.round(2))
'''),
        md(conclusion(
            "180개 업종×분기에서 생산·고용 방향(Q1), 고용 변화 규모(Q2), 상태 지속·전환(Q3)을 분리해 확인했다. 최신분기에도 같은 상태 안에서 증감 인원과 지속기간이 다르다.",
            "상태만으로는 정책적 확인 순서를 정하기 어렵다. 방향·규모·시간을 결합하되 각 지표의 역할을 유지하는 1차 선별이 필요하다.",
            "집계자료만으로 기업별 원인, 인과관계, 지원 필요성 또는 정책효과를 확정할 수 없다.",
            "동일한 상태라도 변화 규모와 지속성이 다르므로 Q1~Q3를 결합해 어떤 업종×분기를 먼저 확인할지 선별해야 한다.",
            "02_triage.ipynb")),
    ]


def notebook_02():
    return [
        md(intro(
            "02", "Triage — 먼저 확인할 업종×분기",
            "Q1~Q3 결과 중 어떤 업종×분기를 먼저 확인해야 하는가?",
            "Notebook 01에서 상태만으로는 규모와 지속성의 차이를 반영한 확인 순서를 정할 수 없음을 확인했다.",
            "production 코드의 E/R/A/P, 반복신호, 규모 gate와 threshold 출처를 그대로 읽어 관찰·추가확인·우선점검으로 선별하고, 추가확인 사례만 ELECTRE/SMAA로 보내는 경로를 검증한다.",
            "법정 위기 지정, 지원대상 자동 선정, 원인 판정 또는 ELECTRE 결과에 의한 Triage 단계 변경을 하지 않는다.")),
        md('''
## 판정 흐름

```text
Q1 State + Q2 Scale + Q3 Time
                ↓
              Triage
     ┌──────────┼────────────┐
   관찰       추가확인       우선점검
정기 모니터링   │          외부근거·담당자 검토
 ELECTRE X      ↓             ELECTRE X
        선택적 ELECTRE/SMAA
                ↓
          Human-in-the-Loop
```
'''),
        code(SETUP),
        code('''
triage = pd.read_csv(config.TRIAGE_PANEL_PATH, encoding='utf-8-sig')
latest = pd.read_csv(config.TRIAGE_LATEST_FULL_PATH, encoding='utf-8-sig')
rules = pd.read_csv(config.TRIAGE_RULE_PROVENANCE_PATH, encoding='utf-8-sig')
review = pd.read_csv(config.ELECTRE_REVIEW_PATH, encoding='utf-8-sig')
check_keys = set(map(tuple, triage.loc[triage.stage.eq('추가확인'), ['industry','quarter']].to_numpy()))
review_keys = set(map(tuple, review[['industry','quarter']].to_numpy()))
assert len(triage) == 180 and check_keys == review_keys and len(check_keys) == 35
assert review.triage_stage_preserved.eq('추가확인').all()
latest_q = triage.quarter.max()
print(f'전체 {len(triage)}건 | 최신 {latest_q} | 추가확인↔ELECTRE 입력 키 일치: {len(check_keys)}건')
'''),
        md('''
## 1. 신호 정의·산식·threshold·출처 성격

`PRINCIPLE_ADAPTED`는 외부 기준의 원리를 자료 단위와 목적에 맞게 변형한 값이고, `PROJECT_OPERATIONAL`은 프로젝트 자체 운영기준이다. 이 저장소에는 단위·기간·목적이 모두 같은 직접 공식 threshold가 없다.
'''),
        code('''
rule_view = rules[['rule_name','definition','threshold','role','source_category','source_note']].copy()
rule_view.columns=['신호/규칙','정의·산식','threshold','역할','출처 성격','적용상 주의']
show_records(rule_view,'신호/규칙',['정의·산식','threshold','역할','출처 성격','적용상 주의'])
'''),
        md('''
## 2. 실제 단계 규칙

```text
진입신호 = E≥5% 또는 R≥5%p 또는 A≥1%
상위신호 = E≥10% 또는 R≥10%p 또는 A≥2%
보강신호 = P≥5% 또는 직전분기에도 진입신호

우선점검 = 상위신호 AND 보강신호 AND 현재 고용≥300명
추가확인 = 진입신호는 있으나 우선점검 조건이 완결되지 않음
관찰     = 고용축 진입신호 없음
```

P는 단독으로 단계에 진입시키지 않으며, 300인 gate는 우선점검만 제한한다. 작은 업종의 고용 신호를 삭제하지 않고 추가확인에 남긴다.
'''),
        code('''
dist = triage.stage.value_counts().reindex(STAGE_ORDER,fill_value=0)
ax = dist.plot.bar(color=[STAGE_COLORS[s] for s in dist.index],figsize=(7,4)); ax.set_title('전체 기간 Triage 단계 분포'); ax.set_xlabel(''); ax.set_ylabel('업종×분기 수')
for p in ax.patches: ax.text(p.get_x()+p.get_width()/2,p.get_height()+1,int(p.get_height()),ha='center')
plt.xticks(rotation=0); plt.tight_layout(); plt.show()
display(Markdown(f"""### 관찰

- 전체 180건은 **관찰 {dist['관찰']}건, 추가확인 {dist['추가확인']}건, 우선점검 {dist['우선점검']}건**이다.

### 해석

- Triage는 전체를 다시 등급화하는 위험점수가 아니라 확인 강도를 세 단계로 나누는 운영 사다리다.

### 주의

- 분포 자체는 threshold의 정책 타당성을 증명하지 않는다."""))
'''),
        code('''
grid = triage.pivot(index='industry',columns='quarter',values='stage'); stage_map={s:i for i,s in enumerate(STAGE_ORDER)}
from matplotlib.colors import ListedColormap
z=grid.map(lambda x: stage_map.get(x,3)).to_numpy(); fig,ax=plt.subplots(figsize=(14,5))
ax.imshow(z,aspect='auto',cmap=ListedColormap([STAGE_COLORS[s] for s in STAGE_ORDER]),vmin=0,vmax=3)
ax.set_xticks(range(len(grid.columns)),grid.columns,rotation=45,ha='right'); ax.set_yticks(range(len(grid.index)),grid.index)
for i in range(z.shape[0]):
    for j in range(z.shape[1]): ax.text(j,i,grid.iloc[i,j],ha='center',va='center',fontsize=6)
ax.set_title('업종×분기 Triage stage'); plt.tight_layout(); plt.show()
display(Markdown("""### 관찰

- 단계는 업종별로 고정되지 않고 분기마다 이동한다.

### 해석

- 이 구조는 업종 낙인이나 영구 순위가 아니라 분기별 확인 큐에 가깝다.

### 주의

- 과거 우선점검 이력은 해당 시점의 집계신호이며 실제 위기 발생의 사후 라벨이 아니다."""))
'''),
        md('## 3. 최신분기 결과와 주요 사례'),
        code('''
latest = latest.copy(); latest['triggered_signals'] = latest.decision_entry_trigger + ' / 보강:' + latest.decision_reinforcement
latest['electre_review_required'] = latest.stage.eq('추가확인')
cols=['industry','quarter','stage','triggered_signals','emp_delta','e_yoy','A','run_length','stage_reason','electre_review_required']
view=latest.sort_values(['stage','rank_in_stage'])[cols]; view.columns=['업종','분기','단계','발동신호','고용증감(명)','고용YoY(%)','A(%)','상태지속(Q)','선정 이유','ELECTRE 재검토']
show_table(view.round(2))
priority_or_check = triage.loc[triage.stage.isin(['우선점검','추가확인'])].sort_values(['quarter','stage','rank_in_stage'])
show_table(priority_or_check.tail(15)[['quarter','industry','stage','decision_entry_trigger','decision_reinforcement','stage_reason']])
'''),
        md('''
### 관찰

- 최신분기에는 우선점검 2개 업종이 있고 추가확인은 없다. 과거 기간 전체에서는 추가확인 35건이 존재한다.

### 해석

- 최신분기 우선점검은 ELECTRE를 거치지 않고 외부근거·담당자 검토로 이동한다. 추가확인은 기준 간 경계와 미완결 조건을 사람이 다시 볼 수 있도록 선택적 다기준 재검토로 보낸다.

### 주의

- 최신분기 추가확인이 0건이라는 사실은 ELECTRE 경로가 불필요하다는 뜻이 아니라, 이번 분기에는 해당 경로로 들어갈 사례가 없다는 뜻이다.
'''),
        md('## 4. 추가확인 → 선택적 ELECTRE/SMAA 입력 검증'),
        code('''
entry = triage.loc[triage.stage.eq('추가확인'), ['quarter','industry','stage','decision_entry_trigger','decision_reinforcement','stage_reason']].copy()
entry['electre_review_required']=True
entry=entry.merge(review[['quarter','industry','electre_stage','possible_stages','n_possible','smaa_parameter_sensitive','boundary_action']],on=['quarter','industry'],how='left',validate='one_to_one')
assert entry.electre_stage.notna().all(); show_table(entry.head(20))
print('Triage 추가확인:',len(entry),'| ELECTRE 결과:',entry.electre_stage.value_counts().to_dict(),'| SMAA 파라미터 민감:',int(entry.smaa_parameter_sensitive.sum()))
'''),
        md('''
### 관찰

- 추가확인 35건과 선택적 재검토 35건의 `(quarter, industry)` 키가 정확히 일치한다.
- ELECTRE 결과와 SMAA 수용도·가능단계가 저장되어 있으며 `triage_stage_preserved`는 모두 추가확인이다.

### 해석

- ELECTRE/SMAA는 추가확인군 내부의 불일치·민감성·검토순서를 설명한다.

### 주의

- ELECTRE의 OBSERVE는 관찰로 자동 하향하지 않고 PRIORITY는 우선점검으로 자동 승격하지 않는다.
'''),
        md(conclusion(
            "E/R/A/P, 반복신호, 300인 gate의 실제 산식과 출처 성격을 확인했고, 180건을 관찰 128·추가확인 35·우선점검 17건으로 선별했다. 추가확인 35건만 선택적 ELECTRE/SMAA 입력과 정확히 일치한다.",
            "Triage는 설명 가능한 1차 선별이며, 추가확인은 경계·상충·불확실성을 사람이 다시 보기 위한 큐다. 우선점검은 핵심 신호가 충분히 명확해 외부근거와 담당자 확인으로 바로 이동한다.",
            "운영 threshold는 법정 지정기준이나 최적 cut-off가 아니며, 단계는 위기확률·정답라벨·정책대상 선정이 아니다.",
            "Triage에도 운영 threshold가 있고 초기에는 ELECTRE TRI-B를 전체 주모형 후보로 검토했으므로, 실제 후보모형·SMAA·민감도·PPI 실험을 통해 현재 역할분담의 근거를 확인해야 한다.",
            "03_model_evolution_and_experiments.ipynb")),
    ]


def notebook_03():
    return [
        md(intro(
            "03", "모형 발전과 실험 기록",
            "왜 현재의 Triage + 선택적 ELECTRE/SMAA 구조를 선택했는가?",
            "Notebook 02에서 Triage의 운영기준과 35건의 선택적 재검토 경로를 확인했다.",
            "과거 ELECTRE TRI-B 주모형 후보, SMAA-TRI, 독립감사, Triage ablation·threshold 민감도, PPI 보정 실험을 문제→가설→실험→결과→해석→설계 영향 순서로 정리한다.",
            "과거 실험을 현재 운영결과와 섞거나, 미수행 실험을 수행한 것처럼 쓰거나, 실험 결과로 Triage의 우월성을 주장하지 않는다.")),
        md('''
## 전체 모형 발전과정

```text
Q1~Q3 유형화
      ↓
ELECTRE TRI-B 주모형 후보
      ↓
SMAA-TRI 파라미터 불확실성 검토
      ↓
강건성·독립감사: 외적 정당화와 안정성 한계 확인
      ↓
명시적 규칙 기반 Triage
      ↓
추가확인 사례만 선택적 ELECTRE/SMAA
      ↓
Human-in-the-Loop
```

**프로젝트 역사**와 **현재 운영구조**를 구분한다. 과거 전체 180행 실험은 후보모형 검증 기록이고, 현재 ELECTRE는 추가확인 35건에만 쓰는 advisory layer다.
'''),
        code(SETUP),
        code('''
params = pd.read_csv(config.ELECTRE_PARAMETER_PATH, encoding='utf-8-sig')
robust = pd.read_csv(config.ELECTRE_ROBUSTNESS_PATH, encoding='utf-8-sig')
limitations = pd.read_csv(config.ELECTRE_LIMITATION_PATH, encoding='utf-8-sig')
sensitivity = pd.read_csv(config.TRIAGE_SENSITIVITY_PATH, encoding='utf-8-sig')
changed = pd.read_csv(config.TRIAGE_SENSITIVITY_CHANGED_PATH, encoding='utf-8-sig')
ppi = pd.read_csv(config.PPI_DISAGREEMENT_PATH, encoding='utf-8-sig')
review = pd.read_csv(config.ELECTRE_REVIEW_PATH, encoding='utf-8-sig')
source_review = pd.read_csv(config.ELECTRE_SOURCE_PATH, encoding='utf-8-sig')
triage = pd.read_csv(config.TRIAGE_PANEL_PATH, encoding='utf-8-sig')
with open(config.MODEL_SELECTION_SUMMARY_PATH, encoding='utf-8') as f: model_summary=json.load(f)
print('실험 산출물 로드 완료:', {'ELECTRE parameter scenarios':len(params),'robustness rows':len(robust),'triage specifications':len(sensitivity),'PPI disagreement rows':len(ppi),'selective review rows':len(review)})
'''),
        md('''
## 실험 inventory와 역할

| 실험 | 실제 질문 | 현재 역할 |
|---|---|---|
| ELECTRE TRI-B / MRSort | 여러 기준을 비보상적으로 범주 배정할 수 있는가? | 초기 주모형 후보, 현재 선택적 재검토 |
| SMAA-TRI | 정한 파라미터 공간에서 배정이 얼마나 유지되는가? | 불확실성 설명 |
| 독립감사·revision robustness | 자료 개정·표집·가능공간에서 결론이 안정적인가? | 역할 축소의 근거 |
| Triage threshold/ablation | 운영규칙을 바꾸면 단계가 얼마나 달라지는가? | 현재 모형의 민감성 공개 |
| PPI 보정 | 명목 생산 방향이 가격조정 후 달라지는가? | 생산 해석의 한계·검증 |
| Isolation Forest | 저장소 실행 근거 없음 | 미수행, 결과로 주장하지 않음 |
'''),
        md('''
## A. ELECTRE TRI-B 초기 주모형 실험

### 문제 → 가설

Q1~Q3 기준은 서로 다른 단위를 가지며 한 기준의 큰 값이 다른 기준의 약점을 완전히 보상하게 하고 싶지 않았다. 따라서 비보상적 outranking과 사전 범주 profile을 쓰는 ELECTRE TRI-B/MRSort가 전체 업종×분기의 주 분류모형 후보가 될 수 있다고 보았다.

### 실험

g1 고용감소 인원, g2 고용감소율, g3 명목 생산감소율, g4 비교 가능한 고용 하회 지속기간을 기준으로 3개 가중치 시나리오와 두 profile을 등록했다. 초기형은 q=p=0, veto 없음, 비관적 할당, 완전사례·무재정규화였다.
'''),
        code('''
pcols=['scenario_id','weight_g1','weight_g2','weight_g3','weight_g4','b1_g1','b1_g2','b1_g3','b1_g4','b2_g1','b2_g2','b2_g3','b2_g4','lambda','q','p','veto','assignment_rule','administratively_approved']
show_table(params[pcols])
'''),
        md('''
### 결과 → 해석 → 최종 설계 영향

등록된 시나리오는 행순서·단조성 등 구현 검사를 통과했지만, 자료개정 교란과 파라미터 공간 안정성의 사전 기준을 일관되게 충족하지 못했다. 이는 ELECTRE가 “실패”했다는 단순 결론이 아니라, 전체 자동판정을 맡기기에는 일부 parameter의 외적 정당화와 안정성·운영 설명비용이 충분히 해결되지 않았다는 뜻이다.
'''),
        code('''
c3b=robust.loc[robust.metric_id.eq('C3b')].copy(); c3b['label']=c3b.model_id+' / '+c3b.scenario_id
ax=c3b.plot.barh(x='label',y='value',legend=False,color='#7A6C9D',figsize=(9,4.8)); ax.axvline(.95,color='#C5523F',ls='--',label='사전 기준 0.95')
ax.set_xlim(.75,1); ax.set_xlabel('교란 후 점 단계가 원 가능집합에 포함된 비율'); ax.set_title('ELECTRE 구간 강건성 C3b'); ax.legend(frameon=False); plt.tight_layout(); plt.show()
show_records(limitations,'limitation_id',['statement'])
display(Markdown(f"""### 관찰

- C3b 6개 조합은 모두 사전 기준 0.95에 미달했다. 최고값은 **{c3b.value.max():.3f}**이다.
- 독립감사는 기존 표본이 놓친 가능 배정 5건과 I3/Jaccard 평가공간 불일치를 확인했다.

### 해석

- ELECTRE는 다기준 구조를 표현하는 데 유용하지만 전체 자동판정의 단일 확정값으로 쓰기에는 parameter·자료개정·표집공간 의존성이 컸다.

### 주의

- 이 결과는 규칙 기반 Triage가 더 정확하다는 검증이 아니다. 정답 label과 현장 정책효과 자료가 없다."""))
'''),
        md('''
## B. SMAA-TRI — weight uncertainty는 어디까지 해결했는가?

### 문제 → 가설 → 실험

단일 weight 고정의 자의성을 줄이기 위해 명시한 weight·lambda·q/p 공간에서 파라미터를 표집하고 class acceptability와 가능한 단계 집합을 계산했다.

### 결과 → 해석 → 설계 영향

SMAA는 “어떤 가정에서 배정이 얼마나 자주 나오는지”를 보여주지만 정답 weight, 위기확률, 연속공간 전체의 필연성을 주지 않는다. 현재는 추가확인군에서 파라미터 민감 사례를 표시하는 용도로만 사용한다.
'''),
        code('''
cai_cols=['cai_observe','cai_check','cai_priority','cai_undetermined']
u=review.copy(); u['uncertainty']=1-u[cai_cols].max(axis=1); u=u.nlargest(12,'uncertainty').sort_values('uncertainty')
labels=u['quarter']+' '+u['industry']; left=np.zeros(len(u)); fig,ax=plt.subplots(figsize=(10,6))
for c,color,name in zip(cai_cols,['#7895A8','#D39A2C','#C5523F','#777777'],['OBSERVE','CHECK','PRIORITY','UNDETERMINED']):
    ax.barh(labels,u[c],left=left,label=name,color=color); left+=u[c].to_numpy()
ax.set_xlim(0,1); ax.set_xlabel('Class acceptability index'); ax.set_title('추가확인군 중 수용도 분산이 큰 사례')
ax.legend(frameon=False,ncol=4,loc='lower center',bbox_to_anchor=(.5,-.18)); plt.tight_layout(); plt.show()
print('가능단계 2개 이상:',int(review.n_possible.gt(1).sum()),'/',len(review),'| necessary_stage 결측(단일 필연단계 없음):',int(review.necessary_stage.isna().sum()))
'''),
        md('''
## C. Triage robustness / sensitivity

### 문제 → 가설 → 실험

Triage도 운영 threshold에 의존한다. A 경계, 300인 gate, 반복(Q3), 생산(P), R 상위경계, 결측정책을 바꾼 15개 사양을 baseline과 비교했다.

### 결과 → 해석 → 설계 영향

변경 건수와 최신분기 변경을 함께 공개해 “어떤 규칙이 결과에 영향을 주는지”를 숨기지 않는다. baseline 300인은 최적값이 아니라 명시적 운영기준으로 유지한다.
'''),
        code('''
s=sensitivity.copy().sort_values('changed_rows'); fig,ax=plt.subplots(figsize=(10,6)); ax.barh(s.variant,s.changed_rows,color='#607D8B')
for y,v in enumerate(s.changed_rows): ax.text(v+.5,y,str(int(v)),va='center',fontsize=8)
ax.set_xlabel('baseline 대비 stage 변경 행'); ax.set_title('Triage 사양별 민감도'); plt.tight_layout(); plt.show()
stack=sensitivity.set_index('variant')[['관찰','추가확인','우선점검','자료확인','규모미달']]
stack.plot.bar(stacked=True,figsize=(13,5),color=['#7895A8','#D39A2C','#C5523F','#777777','#BDBDBD'])
plt.ylabel('업종×분기 수'); plt.title('사양별 stage 분포'); plt.xticks(rotation=50,ha='right'); plt.legend(frameon=False,ncol=5); plt.tight_layout(); plt.show()
show_table(sensitivity)
'''),
        code('''
major=['A 제거','규모 1000','Q3 제거','P 제거','R 상위 제거']
base_priority=triage.loc[triage.stage.eq('우선점검'),['industry','quarter']].copy()
loss=changed.loc[changed.variant.isin(major) & changed.stage.eq('우선점검') & ~changed.stage_variant.eq('우선점검'),['industry','quarter']].drop_duplicates()
stable=base_priority.merge(loss.assign(_lost=True),on=['industry','quarter'],how='left'); stable=stable.loc[stable._lost.isna(),['industry','quarter']]
sensitive=changed.loc[changed.variant.isin(major) & changed.changed.astype(str).str.lower().eq('true'), ['industry','quarter','stage','stage_variant','variant']]
print(f'주요 5개 ablation/강화 사양 모두에서 우선점검 유지: {len(stable)}/{len(base_priority)}건')
show_table(stable.sort_values(['quarter','industry'])); show_table(sensitive.head(25))
display(Markdown("""### 관찰

- gate를 없애면 24건, hard exclusion은 66건, Q3 제거는 8건, P 제거는 4건이 baseline과 달라진다.
- A 제거와 1000인 gate는 최신분기 결과도 각각 1건 바꾼다.

### 해석

- 규모 gate와 시간·생산 보강이 우선점검 진입을 실제로 제한한다. 따라서 운영기준의 영향은 결과와 함께 공개해야 한다.

### 주의

- 변경이 적다는 것과 기준이 옳다는 것은 다르다. 안정적 사례도 현장 정답이 확인된 사례는 아니다."""))
'''),
        md('''
## D. PPI 보정 실험

### 문제 → 가설 → 실험

명목 생산액 변화에는 가격효과가 섞인다. 전국 PPI를 업종에 매핑해 명목 생산 YoY와 가격조정 생산 YoY의 부호와 5% 감소경계를 비교했다.

### 결과 → 해석 → 설계 영향

PPI는 창원산단 물량지수가 아니며 매핑등급이 혼재한다. 그래서 CORE의 상태를 자동 교체하지 않고, 부호가 달라지는 사례를 외부 검증·해석 경고로 남긴다.
'''),
        code('''
fig,ax=plt.subplots(figsize=(7,6)); flag=ppi.sign_agreement.astype(str).str.lower().eq('true')
ax.scatter(ppi.nominal_production_yoy,ppi.ppi_adjusted_production_yoy,c=np.where(flag,'#4C78A8','#C5523F'),s=65)
lo=min(ppi.nominal_production_yoy.min(),ppi.ppi_adjusted_production_yoy.min()); hi=max(ppi.nominal_production_yoy.max(),ppi.ppi_adjusted_production_yoy.max())
ax.plot([lo,hi],[lo,hi],color='#777',ls='--'); ax.axhline(0,color='#999',lw=.7); ax.axvline(0,color='#999',lw=.7)
ax.set(xlabel='명목 생산 YoY(%)',ylabel='PPI 조정 생산 YoY(%)',title='명목 vs PPI 조정 방향 불일치 사례'); plt.tight_layout(); plt.show()
show_table(ppi); print('부호 불일치:',int((~flag).sum()),'건 / 기록된 불일치·경계변경',len(ppi),'건')
'''),
        md('''
## E. Isolation Forest

저장소의 `src`, notebooks, outputs, logs, Git 이력에서 Isolation Forest 실행 코드·점수·산출물을 확인하지 못했다. 따라서 수행 완료나 보조검증 결과로 기록하지 않는다. 이후 새로 수행한다면 “희귀한 관측형태”를 찾는 독립 보조분석일 뿐 위기 라벨이나 Triage 정답 검증으로 해석해서는 안 된다.
'''),
        md('''
## F. 기타 중요한 과거 실험

| 실험 | 확인된 결과 | 최종 설계 영향 |
|---|---|---|
| 독립 감사 | 표본이 놓친 가능배정 5건, 평가공간 불일치, revision pool 문제 확인 | 단일 확정배정 표현 폐기, HYBRID 결론 |
| 후보모형 비교 | 선호정보 층에 따라 60행 변경, VRC4 의존성 확인 | 규범가정을 운영 출력에서 분리 |
| rolling/hybrid validation | 신규 holdout 정답 검증이 아니라 과거자료 기반 운영범위 점검 | 예측정확도 주장 금지 |
| 외부 context threshold | 가동률·업체수·PPI 보조신호 threshold 변화행 기록 | 외부자료를 판정변수로 승격하지 않음 |
'''),
        md('## G. 최종 모형 선택과 선택적 경로 재검증'),
        code('''
check_keys=set(map(tuple,triage.loc[triage.stage.eq('추가확인'),['industry','quarter']].to_numpy()))
source_keys=set(map(tuple,source_review[['industry','quarter']].to_numpy())); output_keys=set(map(tuple,review[['industry','quarter']].to_numpy()))
assert check_keys==source_keys==output_keys and len(check_keys)==35; assert review.triage_stage_preserved.eq('추가확인').all()
comparison=pd.DataFrame([
 ['Q1~Q3','현상진단','직관적·역할 분리','확인 우선순위 없음','CORE'],
 ['ELECTRE TRI-B','다기준 범주분류','비보상 구조','parameter 외적 정당화·개정/표집 안정성','추가확인 선택적 재검토'],
 ['SMAA-TRI','파라미터 불확실성','수용도·가능단계 표시','정답 weight·위기확률을 제공하지 않음','재검토 robustness'],
 ['Isolation Forest','이상치 탐지','독립적 희귀형태 탐색 가능','실행 근거 없음','미수행'],
 ['Rule-based Triage','1차 선별','설명·감사·운영이 쉬움','운영 threshold 민감성·정답 label 부재','현재 1차 구조'],
],columns=['후보','목적','장점','실제 확인된 한계','최종 역할'])
show_table(comparison); print('경로 검증: Triage 추가확인=원천 ELECTRE/SMAA=최종 선택패널=35건; overwrite=0건')
'''),
        md(conclusion(
            "ELECTRE/SMAA는 다기준 구조와 불확실성을 유용하게 보여줬지만, 전체 자동판정을 맡기기에는 외적 정당화·자료개정·파라미터/표집 안정성 한계가 확인됐다. Triage 자체도 gate·A·Q3·P 등에 민감하며 이를 15개 사양으로 공개했다. PPI 보정은 일부 생산 방향과 5% 경계를 바꿨다.",
            "현재는 Q1~Q3를 CORE로, 규칙 기반 Triage를 1차 선별로, ELECTRE/SMAA를 추가확인군의 선택적 재검토로 제한하는 HYBRID 구조가 실험 이력과 가장 정합적이다.",
            "어느 후보도 현장 정답·인과효과·정책효과를 검증하지 못했다. SMAA는 정답 weight를 찾지 않으며 Triage의 투명성이 정확성 우월성을 뜻하지 않는다.",
            "모형은 확인 순서를 정하지만 변화 원인을 자동 설명하지 못하므로, 외부자료를 판정을 덮어쓰지 않는 맥락·교차확인 층으로 붙여야 한다.",
            "04_external_evidence.ipynb")),
    ]


def notebook_04():
    return [
        md(intro(
            "04", "External Evidence — 맥락과 교차확인",
            "Triage 및 선택적 재검토로 확인된 사례가 다른 외부자료에서도 설명 또는 확인되는가?",
            "Notebook 03에서 CORE와 Triage는 확인 순서를 정하지만 원인을 설명하지 못하며, ELECTRE/SMAA도 그 한계를 해결하지 못함을 확인했다.",
            "PPI·EIS·업체수·가동률·관세청·KEPCO·KOSIS·ECOS·고용24의 실제 가용성, 범위, 업종 정합성, 최신성, 역할을 구분하고 최신 주요 사례의 맥락을 확인한다.",
            "외부자료로 CORE/Triage 단계를 덮어쓰거나 서로 다른 모집단의 신호를 합산해 새 점수를 만들지 않는다.")),
        md('''
## 증거의 위치

```text
CORE
  ↓
Triage
  ↓ (추가확인일 때만)
Selective ELECTRE/SMAA
  ↓
External Evidence  ── 판정 변경 X / 맥락·원인후보·확인질문 보강 O
```
'''),
        code(SETUP),
        code('''
roles=pd.read_csv(config.DATA_ROLE_PATH,encoding='utf-8-sig'); evidence=pd.read_csv(config.EVIDENCE_SUMMARY_PATH,encoding='utf-8-sig')
trace=pd.read_csv(config.HANDOFF_TRACE_PATH,encoding='utf-8-sig'); triage=pd.read_csv(config.TRIAGE_PANEL_PATH,encoding='utf-8-sig')
assert set(evidence.stage)==set(triage.loc[triage.quarter.eq(triage.quarter.max()),'stage']); assert trace.human_decision_required.astype(str).str.lower().eq('true').all()
print(f'현재 자료 역할 {len(roles)}종 | 최신 외부근거 {len(evidence)}개 업종 | latest={evidence.quarter.max()}')
'''),
        md('''
## 1. 데이터 가용성·역할 표

`CORE`는 판정의 직접 입력, `VALIDATION`은 방향·측정 한계의 제한적 교차검증, `CONTEXT`는 원인후보와 현장 질문을 보강하는 자료, `EXCLUDE`는 현재 판정에 사용할 수 없는 자료다. “파일이 있다”와 “이번 업종×분기 판정 근거로 쓸 수 있다”를 구분한다.
'''),
        code('''
availability=roles[['dataset','role','direct_measure','indirect_signal','cannot_claim','limitations','exists']].copy()
availability['판정 근거 사용']=availability.role.map({'CORE':'예','VALIDATION':'제한적 교차확인','CONTEXT':'아니오(맥락만)','EXCLUDE':'아니오'})
availability.columns=['자료','역할','직접 측정','가능한 사용','말할 수 없음','기간·공간·업종·품질 제약','파일 존재','판정 근거 사용']
show_records(availability,'자료',['역할','직접 측정','가능한 사용','말할 수 없음','기간·공간·업종·품질 제약','판정 근거 사용'])
print(roles.groupby('role').size().to_dict())
'''),
        md('''
### 관찰

- KICOX 생산·고용만 CORE다. PPI와 EIS/창원상의는 VALIDATION이며, 수출입·전력·노동이동·BSI·고용24는 서로 다른 공간·빈도·업종단위의 CONTEXT다.
- KEPCO 법정동×KSIC는 비식별 40.47%, 완전한 업종분기 0건, 최신 2026Q2 없음이다. 고용24는 2026Q3 단면으로 모형 최신분기와 겹치지 않는다.

### 해석

- 확보된 데이터라도 업종×분기 정합성이 부족하면 자동 판정변수로 사용할 수 없다.

### 주의

- proxy의 방향 일치·불일치는 인과 확인이나 반증이 아니다.
'''),
        md('## 2. PPI — 명목 생산과 가격조정 생산의 최신 비교'),
        code('''
p=evidence.loc[evidence.ppi_adjusted_production_yoy.notna(),['industry','nominal_production_yoy','ppi_adjusted_production_yoy','ppi_mapping_grade']].sort_values('nominal_production_yoy')
y=np.arange(len(p)); fig,ax=plt.subplots(figsize=(9,5)); ax.barh(y-.18,p.nominal_production_yoy,height=.36,label='명목',color='#2F5C8F')
ax.barh(y+.18,p.ppi_adjusted_production_yoy,height=.36,label='PPI 조정',color='#D39A2C'); ax.axvline(0,color='#555',lw=.8)
ax.set_yticks(y,p.industry); ax.set_xlabel('YoY(%)'); ax.set_title(f'명목 vs PPI 조정 생산 — {evidence.quarter.max()}'); ax.legend(frameon=False); plt.tight_layout(); plt.show()
show_table(p.round(2))
display(Markdown("""### 관찰

- 최신분기에도 음식료처럼 명목과 PPI 조정 방향이 다른 사례가 있다. 기계·목재종이는 두 기준 모두 감소 방향이다.

### 해석

- PPI는 명목 생산 변화가 가격효과만으로 설명되지 않는지 점검하는 보조 근거다.

### 주의

- 전국 PPI의 업종 매핑은 창원산단 실질생산량이 아니며 등급 C/D는 단일값 해석을 제한한다."""))
'''),
        md('## 3. EIS — 서로 다른 모집단의 고용 방향 교차확인'),
        code('''
eis=pd.read_csv(config.EIS_PANEL_PATH,encoding='utf-8-sig').sort_values('quarter')
k=triage.groupby('quarter',as_index=False).employment.sum().sort_values('quarter'); k['kicox_yoy']=k.employment.pct_change(4)*100
e=eis.merge(k[['quarter','kicox_yoy']],on='quarter',how='left')
ax=e.plot(x='quarter',y=['eis_manufacturing_yoy_pct','kicox_yoy'],marker='o',figsize=(10,4),color=['#D39A2C','#2F5C8F'])
ax.axhline(0,color='#777',lw=.8); ax.set_ylabel('고용 YoY(%)'); ax.set_xlabel(''); ax.set_title('창원시 제조업 EIS vs 창원국가산단 KICOX 고용')
ax.legend(['EIS 창원시 제조업','KICOX 창원국가산단'],frameon=False); plt.xticks(rotation=45); plt.tight_layout(); plt.show()
display(Markdown("""### 관찰

- 두 계열은 같은 지역 고용을 보지만 모집단이 창원시 전역과 국가산단으로 다르며 분기별 방향·크기가 항상 같지 않다.

### 해석

- 방향이 같을 때는 지역 고용 맥락을 보강하고, 다를 때는 산단 고유 변화인지 확인할 질문을 만든다.

### 주의

- EIS 제조업 총계로 KICOX 10개 업종의 개별 단계를 검증할 수 없다."""))
'''),
        md('''
## 4. 최신 주요 사례의 외부근거

최신분기 추가확인은 0건이므로, 아래는 우선점검 2개 업종을 중심으로 본다. 과거 추가확인 35건의 ELECTRE/SMAA 결과는 Notebook 03에 보존했다.
'''),
        code('''
case_cols=['industry','quarter','stage','signal_profile','nominal_production_yoy','ppi_adjusted_production_yoy','trade_export_yoy','power_usage_yoy','bsi_region_business','bsi_industry_business','mfg_flow_job_openings','check_questions_context','handoff_review_functions']
cases=evidence.loc[evidence.stage.isin(['우선점검','추가확인']),case_cols]; show_table(cases)
for r in cases.itertuples():
    display(Markdown(f"""### {r.industry}

**CORE/Triage.** {r.stage}; 명목 생산 YoY {r.nominal_production_yoy:.2f}%.

**External Evidence.** {r.signal_profile}. PPI 조정 생산은 {r.ppi_adjusted_production_yoy if pd.notna(r.ppi_adjusted_production_yoy) else '비교불가'}%이다.

**해석.** 외부자료는 생산·가동·수요·지역고용의 맥락을 보강하지만, 서로 다른 범위 때문에 기업별 원인을 확정하지 않는다.

**추가 확인.** {r.check_questions_context}
"""))
'''),
        md('''
## 5. 불일치와 미확인의 처리

- 일치: “CORE와 방향이 함께 관측된다”까지 기록한다.
- 불일치: 어느 자료가 틀렸다고 단정하지 않고 공간·업종·빈도·가격/물량 차이를 확인한다.
- 미확인: 최신분기 부재, 매핑 불충분, 단면자료이면 `unavailable / insufficient`로 남긴다.
- 어떤 경우에도 외부자료가 Triage stage를 자동 변경하지 않는다.
'''),
        md(conclusion(
            "외부자료의 파일 존재 여부와 실제 판정 사용 가능성을 분리했다. PPI·EIS는 제한적 validation, 수출입·KEPCO·KOSIS·ECOS·고용24는 context이며, 최신 우선점검 사례의 해석과 확인질문을 보강했다.",
            "외부근거는 CORE와 같은 방향을 보이거나 다른 범위의 배경을 제공할 수 있지만, 서로 다른 모집단과 매핑 제약 때문에 판정을 덮어쓰지 않는 것이 타당하다.",
            "기업 개별 사정, 수주·투자·자동화·외주화·휴폐업의 원인, 실제 지원 필요성은 집계 외부자료만으로 확정할 수 없다.",
            "외부근거도 기업별 원인을 확정하지 못하므로, 최종 단계에서 담당자가 확인할 질문과 기존 지원기능으로의 인계경로를 명시해야 한다.",
            "05_final_results.ipynb")),
    ]


def notebook_05():
    return [
        md(intro(
            "05", "최종 결과와 Human-in-the-Loop 인계",
            "현재 어떤 업종을 무엇 때문에 확인해야 하며, 담당자가 무엇을 확인한 뒤 어디로 연결할 수 있는가?",
            "Notebook 04에서 외부근거는 판정을 덮어쓰지 않고 변화의 맥락과 확인질문을 보강한다는 원칙을 확인했다.",
            "최신분기 결과를 먼저 요약하고, 중요 사례를 CORE→Triage→선택적 재검토(해당 시)→외부근거→확인질문→기존 기능 인계의 진단카드로 제시한다.",
            "자동 정책대상 선정, 사업 처방, 예산 배분, 위기 확정 또는 기업별 지원결정을 하지 않는다.")),
        md('''
## 최종 운영 흐름

```text
Q1~Q3 CORE
     ↓
   Triage
     ├─ 관찰 ─────────────────────→ 정기 모니터링
     ├─ 추가확인 → Selective ELECTRE/SMAA → 외부근거 확인
     └─ 우선점검 ─────────────────→ 외부근거 확인
                                      ↓
                             담당자 Human-in-the-Loop
                                      ↓
                              기업·현장 추가 확인
                                      ↓
                 기존 산업동향·기업·고용·훈련·위기대응 기능 인계
                                      ↓
                              다음 분기 재점검
```

ELECTRE는 모든 경로의 필수 단계가 아니며 **추가확인에서만** 선택적으로 진입한다.
'''),
        code(SETUP),
        code('''
triage=pd.read_csv(config.TRIAGE_PANEL_PATH,encoding='utf-8-sig'); trace=pd.read_csv(config.HANDOFF_TRACE_PATH,encoding='utf-8-sig')
evidence=pd.read_csv(config.EVIDENCE_SUMMARY_PATH,encoding='utf-8-sig'); review=pd.read_csv(config.ELECTRE_REVIEW_PATH,encoding='utf-8-sig')
routing=pd.read_csv(config.ROUTING_MAP_PATH,encoding='utf-8-sig'); latest_q=triage.quarter.max(); latest=triage.loc[triage.quarter.eq(latest_q)].copy()
assert len(latest)==10 and len(trace)==10
expected=trace.stage.eq('추가확인'); actual=trace.electre_used.astype(str).str.lower().eq('true'); assert actual.equals(expected)
print(f'최신분기 {latest_q} | stage={latest.stage.value_counts().to_dict()} | Human review required={trace.human_decision_required.unique().tolist()}')
'''),
        md('''
## 1. 최신분기 한눈에 보기

결론을 뒤에 숨기지 않고 최신 10개 업종을 먼저 제시한다. `외부근거 가용`은 적어도 하나의 맥락자료가 있다는 뜻이지 판정에 쓸 수 있다는 뜻이 아니다.
'''),
        code('''
summary=trace.merge(evidence[['industry','signal_profile','ppi_mapping_grade','trade_export_yoy','power_usage_yoy']],on=['industry','signal_profile'],how='left',validate='one_to_one')
summary['triggered_signals']=summary.apply(lambda r:'|'.join(x for x,c in [('E',r.signal_e>=5),('R',r.signal_r>=5),('A',r.signal_a>=1),('P',r.signal_p>=5)] if c) or '없음',axis=1)
summary['external_available']=summary[['ppi_mapping_grade','trade_export_yoy','power_usage_yoy']].notna().any(axis=1)
out=summary[['industry','stage','triggered_signals','q2_employment_delta','q2_employment_share','q3_state_run_length','q3_repeated_signal','external_available','signal_profile','stage_reason']].copy()
out.columns=['업종','단계','핵심 trigger','고용증감(명)','고용비중(%)','상태지속(Q)','고용진입 반복','외부근거 가용','외부 맥락','주요 해석/선정 이유']
order={'우선점검':0,'추가확인':1,'관찰':2,'자료확인':3}; out=out.assign(_o=out['단계'].map(order)).sort_values(['_o','고용증감(명)']).drop(columns='_o')
show_table(out.round(2))
'''),
        md('''
### 관찰

- 최신 2026Q2에는 기계·목재종이가 우선점검이고 나머지 8개 업종은 관찰이다. 추가확인은 0건이다.
- 기계는 고용 감소 규모가 크고 A 상위경계와 생산 보강을 충족한다. 목재종이는 비율·상대열위·반복·생산 보강이 함께 나타나지만 절대 감소 인원은 작다.

### 해석

- 두 사례는 같은 우선점검이라도 Q2 규모와 확인 질문이 다르므로 진단카드로 분리해 인계한다.

### 주의

- 관찰 업종도 정기 모니터링 대상이며, 생산 단독 감소나 외부 맥락신호는 확인질문에 남는다.
'''),
        md('''
## 2. 중요 사례 진단카드

다기준 재검토는 해당 사례의 Triage 단계가 추가확인일 때만 표시한다. 최신 우선점검 2건은 ELECTRE/SMAA를 거치지 않는다.
'''),
        code('''
stage_order={'우선점검':0,'추가확인':1,'관찰':2}
for r in summary.assign(_o=summary.stage.map(stage_order)).sort_values('_o').itertuples():
    if r.stage not in ['우선점검','추가확인']: continue
    electre='해당 없음 — 우선점검은 외부근거·담당자 검토로 직접 이동'
    if r.stage=='추가확인':
        rr=review.loc[(review.industry==r.industry)&(review.quarter==r.quarter)]
        electre='결과 없음' if rr.empty else f"{rr.iloc[0].electre_stage}; 가능단계 {rr.iloc[0].possible_stages}; 민감={rr.iloc[0].smaa_parameter_sensitive}"
    display(Markdown(f"""### {r.industry}

#### 1. CORE 진단

- Q1: {r.q1_state_label}
- Q2: 고용 {r.q2_employment_delta:,.0f}명, YoY {r.q2_employment_yoy:.2f}%, 고용비중 {r.q2_employment_share:.2f}%
- Q3: 현재 상태 {r.q3_state_run_length:.0f}분기, {r.q3_transition}, 반복신호={r.q3_repeated_signal}

#### 2. Triage

- 단계: **{r.stage}**
- 선택 이유: {r.stage_reason}

#### 3. 다기준 재검토

- {electre}

#### 4. 외부근거

- {r.signal_profile}
- 범위 주의: 산단·창원시·경남·전국 자료가 혼재하므로 판정을 덮어쓰지 않음

#### 5. 해석

- 데이터로 확인: {r.stage_reason}
- 아직 추정: 기업별 수주·자동화·외주화·휴업·투자·이직 원인

#### 6. 담당자 확인 질문

- {r.check_question}
- {r.check_questions_context}

#### 7. 인계 가능한 기존 기능

- {r.first_owner}
- {r.handoff_review_functions}
"""))
'''),
        md('## 3. 선택적 ELECTRE/SMAA와 Human-in-the-Loop'),
        code('''
path_check=pd.DataFrame({'경로':['관찰','추가확인','우선점검'],'다음 단계':['정기 모니터링','선택적 ELECTRE/SMAA → 외부근거','외부근거'],'ELECTRE 필수':[False,True,False],'자동 stage 변경':[False,False,False],'최종 판단':['담당자','담당자','담당자']})
show_table(path_check)
print('전체 추가확인:',int(triage.stage.eq('추가확인').sum()),'| 선택 재검토:',len(review),'| ELECTRE stage 분포:',review.electre_stage.value_counts().to_dict(),'| overwrite:',int((review.triage_stage_preserved!='추가확인').sum()))
'''),
        md('''
## 4. 기존 기능으로의 인계

아래는 자동 사업추천이 아니라 담당자가 현장 확인 후 검토할 수 있는 기존 기능의 지도다. 실제 기관명·사업 운영 여부·지원요건은 인계 시점에 다시 확인한다.
'''),
        code("show_table(routing[['role','institution','unit','function','source_url']])"),
        md('''
## 5. 담당자 기록 필드와 다음 분기 재점검

1. 기업·현장 확인 대상과 근거
2. 수주·가동·설비·외주·인력·고용조정 관련 확인 사실
3. 외부자료와 CORE의 일치/불일치 이유
4. 기존 지원기능 검토 결과(연계/미연계/추가자료 필요)
5. 다음 분기 재점검 시 비교할 지표

이 기록은 모형의 자동 학습 label로 즉시 사용하지 않는다. 정의·수집방식·검증절차가 합의된 뒤 별도 평가자료로 관리해야 한다.
'''),
        md(conclusion(
            "최신 2026Q2에는 기계와 목재종이가 우선점검이며 추가확인은 없다. 전체 기간 추가확인 35건은 선택적 ELECTRE/SMAA 35건과 일치하고 단계 overwrite는 0건이다. 모든 최신 사례는 Human review가 필요하다.",
            "현재 구조는 CORE로 현상을 진단하고, Triage로 확인 순서를 정하며, 추가확인만 다기준 재검토하고, 외부근거와 담당자 확인을 거쳐 기존 기능으로 인계하는 의사결정지원 흐름이다.",
            "이 결과는 위기 확정, 기업별 원인, 지원대상 선정, 사업 처방, 예산 배분 또는 정책효과를 자동 결정하지 않는다.",
            "담당자 확인 결과를 기록하고 다음 분기 CORE·Triage와 비교해야 모니터링이 완결된다.",
            None)),
    ]


def restyle_00():
    path=NB_DIR/'00_data_preparation.ipynb'; nb=nbformat.read(path,as_version=4); cells=list(nb.cells)
    while cells and cells[0].cell_type=='markdown' and (
        cells[0].source.startswith('# STEP0.') or cells[0].source.startswith('# Notebook 00.')
    ):
        cells=cells[2:]
    while cells and cells[-1].cell_type=='markdown' and (
        '## Takeaway' in cells[-1].source or cells[-1].source.startswith('# 단계 결론')
    ):
        cells=cells[:-1]
    opening=md(intro('00','데이터 준비와 품질검증','분석에 사용할 업종×분기 패널을 동일한 정의와 품질규칙으로 재현할 수 있는가?','첫 단계이므로 이전 분석 결론은 없다. 이 노트북은 01~05 보고서의 기술적 전제다.','KICOX 원자료와 개정본을 master·state·run·transition 패널로 만들고 PPI/EIS validation 입력을 점검한다.','산업상태를 해석하거나 Triage·정책 우선순위를 결정하지 않는다.'))
    flow=md('## 전체 흐름\n\n`원자료·개정본 → master → YoY·state·run·transition → validation panel → QA`')
    close=md(conclusion('행 수·기간·중복·결측·원자료 불변 여부를 점검하고 01~05의 공통 입력을 생성했다.','뒤 단계는 동일한 source of truth에서 상태·규모·시간과 의사결정지원 결과를 읽을 수 있다.','외부 공표지연·재개정 가능성과 집계자료의 모집단 제약은 이 QA만으로 해소되지 않는다.','준비된 패널에서 실제 생산·고용 변화의 상태·규모·시간을 진단해야 한다.','01_core_analysis.ipynb'))
    return [opening,flow,*cells,close]


def write_notebook(name: str, cells) -> None:
    nb=nbformat.v4.new_notebook(cells=cells,metadata={'kernelspec':{'display_name':'Python 3','language':'python','name':'python3'},'language_info':{'name':'python','version':'3'}})
    nbformat.write(nb,NB_DIR/name)


def main() -> None:
    NB_DIR.mkdir(parents=True,exist_ok=True)
    canonical={
        '00_data_preparation.ipynb':restyle_00(),
        '01_core_analysis.ipynb':notebook_01(),
        '02_triage.ipynb':notebook_02(),
        '03_model_evolution_and_experiments.ipynb':notebook_03(),
        '04_external_evidence.ipynb':notebook_04(),
        '05_final_results.ipynb':notebook_05(),
    }
    for name,cells in canonical.items():
        write_notebook(name,cells)
    for name in canonical:
        path=NB_DIR/name
        nb=nbformat.read(path,as_version=4)
        h1=sum(1 for cell in nb.cells if cell.cell_type=='markdown' for line in cell.source.splitlines() if re.match(r'^# (?!#)',line))
        if h1!=2: raise RuntimeError(f'{path.name}: expected title and conclusion H1, found {h1}')
        print(f'[ok] {path.name}: cells={len(nb.cells)} code={sum(c.cell_type=="code" for c in nb.cells)}')


if __name__=='__main__':
    main()
