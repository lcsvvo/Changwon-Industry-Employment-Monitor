"""Build final presentation notebook and audit report from executed CSVs only."""
import json, sys
from pathlib import Path
import pandas as pd
import nbformat as nbf
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from model import triage_delivery as delivery
OUT=ROOT/'outputs/decision_support_final'
def read(n): return pd.read_csv(OUT/n)
def table(df):
    clean=df.fillna('미확인').map(lambda x:str(x).replace('|',' / ').replace('\n',' '))
    clean=clean.map(lambda x:f'[공식 출처]({x})' if x.startswith('https://') else x)
    return '| '+' | '.join(clean.columns)+' |\n| '+' | '.join(['---']*len(clean.columns))+' |\n'+'\n'.join('| '+' | '.join(row)+' |' for row in clean.values)
def main():
    p=read('decision_panel.csv');l=read('decision_latest.csv');s=read('sensitivity_own_rules.csv');q=read('q3_decisive_rows.csv')
    b=pd.read_csv(ROOT/'data/reference/triage_history/original_v3_stages.csv')
    v=json.loads((OUT/'audit_v3/verification.json').read_text(encoding='utf-8'))
    test_lines=[]
    for name in ['triage_tests','full_tests']:
        file=OUT/'audit_v3'/f'{name}.xml'
        if file.exists():
            suite=ET.parse(file).getroot().find('testsuite')
            test_lines.append(f"{name}: tests={suite.get('tests')}, failures={suite.get('failures')}, errors={suite.get('errors')}, skipped={suite.get('skipped')}")
    report=f'''# {delivery.TITLE} — v3 독립 재현·최종 감사

{delivery.PURPOSE}

창원에는 산업동향·위기대응·기업진단·고용·훈련지원 기능이 이미 존재한다. 확인한 공개자료에서는 업종별 변화 탐지부터 우선점검·확인질문·기업 현장확인·지원체계 검토까지 하나의 표준 흐름으로 연결된 사례를 확인하기 어렵다. 이는 공개자료 확인 범위의 결론이며 실제 기관 간 협업 부재를 입증하지 않는다.

{delivery.FLOW}

## A. 저장소와 보존

현재 실행 코드는 src/, 최종 노트북은 notebooks/01·02·03·11, 최종 산출물은 outputs/에 둔다. 후보 구현·감사·비채택 근거는 logs/로 분리했다. 과거 비교에 필요한 열만 data/reference/triage_history/에 고정하며 현재 판정의 입력으로 사용하지 않는다.

읽은 핵심: triage_rule/run_triage_rule, build_changwon_master/build_kicox_analysis_panel, eda/panel, model/derive, 고정된 과거 비교 기준표 및 기존 11번 노트북. 수정: triage_rule.py, run_triage_rule.py, 11번 노트북, README.md. 신설: triage_delivery.py, triage_audit.py, triage 관련 tests, scripts/triage_raw_rebuild.py·build_triage_notebook.py·execute_triage_notebook.py, 본 출력 폴더의 감사·카드·출처 표.

원자료 재구축은 임시 디렉터리에서 분리 실행하고 비교 결과만 audit_v3/raw_rebuild_verification.json에 저장한다. 340행 업종 master, 34행 전체 master, 180행 상태 패널이 기존 자료와 수치 허용오차 내 일치한다. 독립 scalar 함수는 달력분기 키로 E/R/A/P를 다시 계산하며 180행 축·판정 모두 일치했다. 입력·코드 해시, Git HEAD와 미커밋 코드 해시는 run_metadata.json에 기록한다.

## B. Claude v3 재현

원본 분포: {b.stage.value_counts().to_dict()}. 최신 기계·목재종이 우선점검 및 Q3 제거 6행 변경을 재현했다. 원본과 최종판의 변경은 {v['baseline_to_final_changes']}행이며, P만 결측인 20행과 2022Q1 기계의 기간 절단 문제 1행으로 분해된다.

## C. A축 최종 감사

A = max(0, 전년동기 업종 고용 - 현재 업종 고용) / 현재 산단 제조업 전체 고용 ×100. 현재 산단 고용 100명당 전년동기 대비 감소인원이 1/2명인 경계다. 단일 업종 감소가 전체 기반에서 차지하는 규모를 표시하며 업종 위기율이나 확률이 아니다. 현재 분모는 현재 점검대상 기반 크기이며 산단 전체가 축소하면 같은 감소인원에도 A가 커진다. 전년 분모의 순변화 기여도와 구분해야 한다.

규모효과는 대형 업종에 구조적으로 더 큰 값을 부여한다. 이는 영향인원을 반영하는 설계 의도이지만 기계 의존성을 만든다. A 제거 시 우선점검 변경은 기계에 집중한다. 0.5/1은 기계 1행·전기전자 4행, 2/4는 기계 6행 변경이다. 최신 기계는 2/4 또는 A 제거에서 추가확인으로 바뀌고 목재종이는 유지된다. 따라서 핵심 대상의 점검 필요성은 남지만 **기계의 우선점검 단계는 A 선택에 조건부**다. 규모효과는 운영목적에 부합하나 이 자료만으로 A를 단계에 반드시 넣어야 한다거나 1/2가 최적이라고 증명할 수 없다.

1/2는 기존 후보 사양을 유지한 PROJECT_OPERATIONAL 값이다. 새로 결과에 맞춰 튜닝하지 않았다. 관련 v3 파일이 Git 추적 밖에 있어 사전등록·선택 시점을 입증하는 커밋 근거를 확인하지 못했다. 사후 선택 의혹을 배제할 수 없으며, 향후 분기·담당자 처리용량·현장 검증 이전에는 확정 정책기준으로 취급하지 않는다.

## D. 부분결측

2023Q4 10행은 보정 원자료 월별 비공개(X) 포함으로 생산값이 없고, 2024Q4 10행은 그 전년동기 값이 없어 생산 YoY가 없다. E/R/A 핵심 결측은 0행이다. 보간하지 않았다. Q1은 해당 20행 INVALID 그대로 유지한다. 생산이 없어도 알려진 고용신호로 단계를 반환하고 data_quality_production_missing을 표시한다. 상위 고용신호가 있으나 반복도 입증되지 않으면 추가확인이라는 최소판정과 상향 미확정 플래그를 남긴다.

생산만 미확인인 20행: 관찰 15, 추가확인 4, 우선점검 1(2023Q4 기계; 반복 보강). 완전자료 방식은 같은 20행을 자료확인으로 보류한다. 자료확인은 행동단계가 아니라 핵심자료 부족의 판정보류 상태이며 이번 실자료에는 0행이다.

## E. Q3 반복·지속

현재 및 실제 직전 달력분기에 E/R/A 중 하나 이상 진입했는지를 사용한다. 단순히 연속 두 관측행이 아니라 달력상 연속이어야 한다. 기존 g4는 음의 고용 YoY 연속기간, state run_length는 동일 Q1 국면 기간이므로 서로 같지 않다. 반복 신호는 매 분기 서로 다른 축에서 발생할 수도 있다.

원본에서 제거 시 6행(기계 5, 음식료 1), 수정판에서 {len(q)}행({q.industry.value_counts().to_dict()})이 우선점검에서 추가확인으로 바뀐다. 추가 2행은 2022Q1의 2021Q4 선행정보 복구와 2023Q4 생산결측 최소판정이다. 분석창 절단 전에 반복신호를 계산한다. Q3 영향은 기계에 편중되어 있다. 원본 transition_type은 현재→다음 분기이므로 최신분기가 비어 있다. 원본 필드는 보존하고 카드의 q3_transition은 previous_state→현재 state로 명시해 미래정보 없이 최근 전환을 전달한다.

**Q3 시간축에서 도출한 반복·지속 신호를 상위 점검단계의 보강조건으로 활용하였다.**

## F. 300인

priority gate는 300인 미만의 추가확인을 남기고 우선점검만 제한한다. gate 없음과 flag/정렬만은 동일 단계이며 최종판에서 24행을 우선점검으로 올린다(기타7·목재종이4·비금속4·섬유의복9). hard exclusion은 66행을 규모미달로 제거하며 그중 추가확인 신호도 숨긴다. 표시는 비율변동의 단계 진입 자체를 막지 못한다.

200인: 4행 변경, 500인: 2행, 1000인: 8행. 최신 목재종이는 500인 이상 게이트에서 추가확인이 된다. 300인은 공식 주된 산업의 규모 진입원리를 참고한 프로젝트 운영규칙(PRINCIPLE_ADAPTED)이며 최적값이나 법정요건의 직접 적용이 아니다. 후보값을 유지하고 민감성을 공개한다.

## G. 최종 규칙 사양

{table(read('rule_provenance.csv')[['rule_name','definition','threshold','role','source_category','reason_for_adaptation']])}

DIRECT_OFFICIAL 분류에 해당하는 규칙은 없다. E는 피보험자·평균기간과 KICOX 분기말 고용이 다르고 P는 전전년 비교 및 결합요건을 동일하게 쓰지 않는다. R 상위 10%p는 자체 운영규칙이다. 출처 URL·확인일은 rule_provenance.csv에 있다.

## H. 180행 최종 결과 및 민감도

최종 분포: {p.stage.value_counts().to_dict()}. 생산 미확인 {int(p.data_quality_production_missing.sum())}행, 핵심 고용 미확인 {int(p.data_quality_core_missing.sum())}행. 아래 변경행 수는 최종 수정판 기준이며 원본 기준 민감도는 logs/experiments/sensitivity_history/에 별도 보존했다.

{table(s)}

{table(read('stage_distribution_by_quarter.csv'))}

{table(read('stage_distribution_by_industry.csv'))}

## I. 최신 10개 업종

{table(l[['industry','quarter','stage','rank_in_stage','employment','emp_delta','E','R','A','P']].round(3))}

## J. 대표 진단카드

diagnostic_cards_latest.csv/json/md에 10개 업종 전체 카드가 있다. 기계는 고용 감소율만으로 상위경계를 넘지 않으며 A와 P 결합, 목재종이는 E와 P·반복 조건으로 선정된다. 카드는 근거·질문·담당 기능·미확인 사항을 인계한다. 담당자·현장 근거·지원 검토결과는 미입력 상태다. 자동 원인추정이나 실제 기관 통보를 수행하지 않았다.

## K. 기존 ELECTRE 비교

180행별 possible set은 기존 독립감사 action_panel의 연속공간 범위이며 대표값은 같은 감사 point_decisions의 v1.0_crisp다. 표본 possible set과 혼합하지 않았다. 변경 여부는 대표값 대비이며 집합과 단일 단계의 동등성 비교가 아니다.

{table(read('comparison_vs_legacy.csv').query('quarter == @l.quarter.iloc[0]')[['industry','legacy_possible_set','legacy_representative','stage','change_reason']])}

새 모형이 더 정확하다는 검증은 하지 않았다. 새 모형은 외부 기준과 명시된 운영규칙에 따라 하나의 행동단계를 반환하도록 재설계되었다. ELECTRE/MRSort 독립감사·HYBRID 판정·실패 실험은 후보모형을 선발하기 위한 검증 근거로 보존한다.

추가로 제시된 초기 설계안의 ELECTRE·SMAA·패널 회귀·Isolation Forest 역할은 [초기 설계안과 최종모형 설명](MODEL_ROLE_CLARIFICATION.md)에 구분했다. 초기 설계안은 조건부 후보 제안이지 최종 채택 선언이 아니었다. 회귀·Isolation Forest는 확인한 저장소에 실행 근거가 없으며 완료 성과로 쓰지 않는다.

## L. 행정 연결

{delivery.FLOW}

우리 프로젝트는 업종 단위 진입점과 인계도구를 만든다. 기존 기관을 대체하거나 지원대상을 확정하지 않는다. 담당자가 현장 근거를 검토한 뒤 기업·경영, 고용조정, 인력·숙련 수요에 따라 기존 기능의 검토경로를 선택한다. 다음 분기 새 자료로 재실행하고 담당자 판단을 기록한다. 현장 절차는 제안된 운영 흐름이며 기관 합의·실제 연계 효과는 미검증이다.

{table(read('institution_handoff_map.csv'))}

## M. 실행·테스트

python src/run_triage_rule.py; python -m pytest tests/test_triage_rule.py tests/test_diagnostic_card.py; python -m pytest; python scripts/execute_triage_notebook.py. 실제 결과는 audit_v3/triage_tests.xml, full_tests.xml, notebook_execution.json 및 실행된 11번 노트북에 남긴다. 초기 테스트 경로 누락과 환경 scipy 누락은 수정·설치 후 재실행했다.

{'; '.join(test_lines)}

## N. 남은 한계

명목 생산의 가격·물량 미분리, 집계업종 내부 이질성, 연간보정 자료의 사후 개정, 현장 검증·정답라벨 부재, A 및 규모 게이트의 운영규범성, 선택시점 입증 부족이 남는다. 자료 재현과 규칙 일관성 검증이지 위기 예측 정확도 검증은 아니다. 공개자료에서 연결 사례를 찾기 어렵다는 말은 행정 현장의 비공개 협업 부재 주장이 아니다. 기존 자료의 2026Q2 표기를 재현했으며 외부 공표 시점 검증과 실제 기업 사례 검증은 별도 과제다.
'''
    (OUT/'REPORT.md').write_text(report,encoding='utf-8')
    cells=[]
    def md(s): cells.append(nbf.v4.new_markdown_cell(s))
    def code(s): cells.append(nbf.v4.new_code_cell(s))
    md(f'# {delivery.TITLE}\n\n## 1. 문제 정의\n\n**{delivery.PURPOSE}**\n\n창원에는 산업동향·위기대응·기업진단·고용·훈련지원 기능이 이미 존재한다. 기관별 분석단위와 업무 진입경로가 다르므로, 분산된 기존 체계 사이의 연결 공백을 보완하는 **업종 단위 의사결정 지원모형**을 제안한다.\n\n공개자료 확인 범위에서 표준 연결 사례를 확인하기 어렵다는 뜻이며, 실제 협업이 없다는 주장은 아니다.\n\n{delivery.LIMIT}')
    code("from pathlib import Path\nimport sys, json\nimport pandas as pd\nfrom IPython.display import display, HTML, Markdown\nROOT = Path.cwd() if (Path.cwd()/'src').exists() else Path.cwd().parent\nsys.path.insert(0, str(ROOT/'src'))\nfrom model import triage_delivery as delivery\nOUT=ROOT/'outputs/decision_support_final'\ndef read(name): return pd.read_csv(OUT/name)\npanel=read('decision_panel.csv')\nlatest=read('decision_latest.csv')\nassert len(panel)==180 and len(latest)==10\npd.set_option('display.max_columns', 20)")
    md('## 2. 기존 창원의 관련 체계\n\n기존 기관과 기능을 전제로 한다. 링크는 확인한 공개자료이며 담당기관 배정·사업 이용 가능성은 현장 인계 시 재확인한다.')
    code("display(read('institution_handoff_map.csv'))")
    md('## 3. 연결 공백\n\n**어느 업종을 먼저 확인하고, 무엇을 확인한 뒤, 어느 기존 기능으로 넘길 것인가?**\n\n산업동향은 지역·산단·업종, 위기대응은 밀집지역, 기업지원은 기업, 고용·훈련은 기업·근로자·산업수요 단위다. 이 사이를 잇는 근거와 질문을 표준화한다.')
    md('## 4. 우리가 보완하는 영역')
    code('display(HTML(delivery.flow_html()))')
    md('## 5. 데이터와 독립 재현\n\n로컬 KICOX 원자료 → 제조업 10개 업종 master → Q1~Q3·E/R/A/P → 2022Q1~2026Q2 180행. 명목 생산은 분기 합계, 고용은 분기말. 반복신호는 분석 시작 이전 분기도 사용한다. 원자료 재구축·독립 scalar 검산은 기존 ELECTRE 출력을 덮어쓰지 않는다.')
    code("display(pd.DataFrame(json.loads((OUT/'audit_v3/raw_rebuild_verification.json').read_text())))\ndisplay(json.loads((OUT/'audit_v3/verification.json').read_text(encoding='utf-8')))")
    md('## 6. Q1 상태 — 무엇을 확인할 것인가\n\n상태가 단계를 직접 결정하지 않는다. S1 확장·인력수급, S2 자동화·외주·미충원, S3 선행채용·생산 일시성, S4 수주·감산·고용조정 가능성을 **질문**으로 넘긴다. 원인 확정이 아니다.')
    code("display(latest[['industry','q1_state','q1_state_label','q1_question_route']])")
    md('## 7. Q2 규모 — 얼마나 큰 영향인가\n\n고용인원 변화·비중·순증감 기여율과 같은 단계 내 처리순서를 전달한다. 기여율은 전체 순변화 상쇄가 크면 미표시한다. A는 현재 산단 전체 고용 대비 감소인원으로 별도 정의한 규모효과다. Q2 전체 점수를 만들지 않는다.')
    code("display(latest[['industry','q2_employment_delta','q2_employment_yoy','q2_employment_share','q2_contribution','q2_same_stage_rank']].round(3))")
    md('## 8. Q3 시간 — 반복·지속 여부\n\n**Q3 시간축에서 도출한 반복·지속 신호를 상위 점검단계의 보강조건으로 활용하였다.**\n\n현재와 직전 달력분기의 고용축 진입신호다. 동일 상태 지속기간이나 음의 고용 YoY 연속길이 g4와 다르다. 생산 결측 때 Q1 INVALID는 그대로 남는다.')
    code("display(read('q3_definition_comparison.csv').tail(20))")
    md('## 9. 분석과 판단엔진의 역할\n\n|분석|역할|\n|---|---|\n|Q1|확인질문·담당 기능|\n|Q2|영향 규모·같은 단계 처리순서; A에 감소인원 반영|\n|Q3 시간축|반복 고용진입신호 보강|\n|E/R/A 및 P·반복·규모 조건|점검단계 판단|')
    md('## 10. 최종 트리아지 규칙\n\n고용 핵심자료가 없으면 판정보류(자료확인). 그 외 **상위 고용신호 AND (생산 보강 OR 반복) AND 300인 이상 → 우선점검**. 이 조건에 못 미치더라도 진입신호가 있으면 추가확인, 나머지는 관찰. P만 없으면 알려진 신호로 최소판정하고 자료 플래그를 인계한다. 관찰도 다음 분기 재점검한다.')
    md('## 11. 출처와 프로젝트 운영규칙\n\n법정 지정기준을 직접 적용하지 않는다. 같은 숫자도 대상·기간·목적이 달라 DIRECT_OFFICIAL은 없다. R 상위 10%p와 A 1/2는 자체 운영규칙이다.')
    code("display(read('rule_provenance.csv'))")
    md('## 12. 핵심 민감도와 감사\n\n원본 Q3 제거는 6행, 수정판은 8행이다. 생산결측 20행 처리와 분석창 이전 정보 복구를 분리했다. A 2/4에서 최신 기계, 규모 500인에서 최신 목재종이가 추가확인으로 바뀐다. 핵심 대상의 **우선점검 단계는 운영규칙에 조건부**이며 최적성·예측 정확도를 주장하지 않는다. 1/2 사전 선택의 증거는 확보하지 못했다.')
    code("display(read('sensitivity_own_rules.csv'))\ndisplay(read('missingness_summary.csv').query('data_quality_production_missing'))\ndisplay(read('history_boundary_changed_rows.csv'))\ndisplay(read('q3_decisive_rows.csv')[['industry','quarter','stage','stage_reason']])")
    md('## 13. 180행 전체 결과\n\n색과 단계명을 함께 표시한다. 각 행의 계산·근거·품질 플래그는 decision_panel.csv에 있다.')
    code("display(HTML(delivery.stage_grid(panel)))\ndisplay(panel[['industry','quarter','decision_stage','decision_entry_trigger','decision_reinforcement','decision_scale_gate','decision_reason']])")
    md('## 14. 분기별 단계 분포')
    code("display(HTML(delivery.distribution_html(read('stage_distribution_by_quarter.csv'))))\ndisplay(read('stage_distribution_by_industry.csv'))")
    md('## 15. 최신 10개 업종\n\n같은 단계의 순위는 감소인원 기준이다. 관찰업종의 표시순서를 위험순위로 해석하지 않는다.')
    code("display(latest[['industry','quarter','decision_stage','q2_same_stage_rank','employment','emp_delta','signal_e','signal_r','signal_a','signal_p','decision_reason']].round(3))")
    md('## 16. 대표 진단카드 — 업종 분석을 현장 업무로 인계\n\n구조화 카드 10개와 결정적 템플릿 진단문을 CSV/JSON/Markdown으로 생성했다. AI 추정 없이 실제 수치·질문을 전달한다. 담당자 검토·현장 근거·지원 검토결과는 미입력이다.')
    code("cards=read('diagnostic_cards_latest.csv')\ndisplay(Markdown(delivery.cards_markdown(cards[cards.industry.isin(['기계','목재종이'])])))")
    md('## 17. 기존 ELECTRE/MRSort의 위치\n\n초기 Q1~Q3 → ELECTRE 후보 구현 → 독립 감사(가중치·lambda·RC/VRC·VRC4·possible assignment·revision robustness) → 대안 비교 → 공공 선제대응 논리 조사 → 업종 단위 트리아지. 자유 선호공간에서 연구진 규범이 영향을 주는 점을 확인한 검증 이력이며 삭제하지 않는다.\n\n**새 모형은 외부 기준과 명시된 운영규칙에 따라 하나의 행동단계를 반환하도록 재설계되었다.** 더 정확하다는 주장이 아니다. 대표값은 기존 독립 감사의 v1.0_crisp, possible set은 같은 감사의 연속공간 범위다.')
    code("comparison=read('comparison_vs_legacy.csv')\ndisplay(comparison[comparison.quarter==latest.quarter.iloc[0]][['industry','legacy_possible_set','legacy_representative','stage','changed_vs_representative','change_reason']])")
    md('### 초기 설계안의 채택 조건을 거친 현재 결론\n\n|초기 구상|현재 위치|\n|---|---|\n|ELECTRE TRI-B 주모형 후보|구현·독립 감사한 비교모형|\n|SMAA-TRI 안정성|파라미터 공간에 조건부인 후보 검증; 새 트리아지는 고정 시나리오 민감도|\n|패널 고정효과 회귀|실행 근거 미확인, 수행 완료로 기재하지 않음|\n|Isolation Forest|미수행 선택사항|\n|Q1~Q3·진단카드|최종 핵심 흐름|\n\nELECTRE도 경계별 가중 지지도를 합산하므로 자의성이 자동 제거되는 것은 아니다. veto는 outranking 차단이며 심각한 신호의 자동 승격과 다르다. 표집 수용도는 위기 확률이나 연속공간 전체의 필연성이 아니다. 초기 g4(괴리 후보)와 실제 ELECTRE g4(고용 하회기간), 최종 반복신호는 서로 다르다.\n\n[초기 문서의 항목별 정정과 팀원 공유 문장](../outputs/decision_support_final/MODEL_ROLE_CLARIFICATION.md)')
    md('## 18. 최종 행정 연결과 재점검\n\n진단카드 수신 → 담당자가 집계·개정·질문 검토 → 기업·현장 근거 확인 → 기업·경영 / 고용조정 / 인력·숙련 담당 기능에서 기존 체계 검토 → 판단·근거 기록 → 다음 분기 새 자료 재점검. 이는 제안 흐름이며 실제 기관 인계·지원 효과는 아직 검증하지 않았다.')
    code('display(HTML(delivery.flow_html()))')
    md('## 19. 프로젝트가 만드는 것\n\n업종 단위 점검의 근거·순서·확인질문과 표준 인계카드를 만든다. 기존 행정체계의 기관·지원사업·예산을 새로 만들거나 자동 결정하지 않는다. 선택적 AI는 향후 이 카드의 문장 다듬기로만 제한할 수 있으며 현재 진단문은 결정적 템플릿이다.')
    md('## 20. 한계와 실행 근거\n\nA·300인의 운영규범성, 일부 업종 편중, 사전등록 증거 부족, 명목 생산·집계업종 한계, 개정자료 의존, 현장 정답·연계효과 미검증이 남는다. 전체 감사는 outputs/decision_support_final/REPORT.md, 출처는 rule_provenance.csv와 institution_handoff_map.csv, 코드·원자료 해시는 run_metadata.json에서 확인한다. 노트북은 CSV와 Python 모듈을 표시하며 판정식을 복제하지 않는다.')
    code("display(json.loads((OUT/'run_metadata.json').read_text(encoding='utf-8'))['rule_version'])\nassert not any(c.endswith('_x') or c.endswith('_y') for c in panel.columns)\nprint('180행, 최신 10개 카드, 출처·민감도·인계 흐름 표시 완료')")
    cells[1].source += '''
from IPython.display import display as _display
def display(value):
    if isinstance(value, pd.DataFrame):
        markup=value.to_html(index=False,render_links=True,na_rep='미확인',border=0)
        if len(value)>30:
            markup='<details><summary>전체 '+str(len(value))+'행 펼치기</summary>'+markup+'</details>'
        _display(HTML('<div style="overflow:auto;max-width:100%">'+markup+'</div>'))
    else:
        _display(value)
'''
    for cell in cells:
        if cell.cell_type=='code': cell.metadata['jupyter']={'source_hidden':True}
    md('### 공식 출처와 상세 검증 파일\n\n- [고용위기지역 고시 — 2026.5.4 시행](https://www.law.go.kr/LSW/admRulInfoP.do?admRulSeq=2100000278624&chrClsCd=010201)\n- [지역 산업위기대응 고시 — 2025.3.4 시행](https://www.law.go.kr/LSW/admRulLsInfoP.do?admRulSeq=2100000255684)\n- [최종 감사 보고서 A~N](../outputs/decision_support_final/REPORT.md)\n\n'+ '; '.join(test_lines))
    nb=nbf.v4.new_notebook(cells=cells,metadata={'title':delivery.TITLE,'kernelspec':{'name':'triage-audit','display_name':'Python (triage audit)','language':'python'}})
    nbf.write(nb,ROOT/'notebooks/11_decision_support_final.ipynb')
if __name__=='__main__': main()
