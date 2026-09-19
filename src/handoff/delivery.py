"""Traceable diagnostic handoff; no causal inference or automatic program selection."""
from pathlib import Path
import html, json
import pandas as pd

TITLE = '창원국가산단 산업·고용 전환진단 및 지원연계 모형'
PURPOSE = '기존 산업동향 분석을 기업·현장 확인의 표준화된 진입점으로 전환한다.'
FLOW = '산업동향 데이터 → Q1 상태 / Q2 규모 / Q3 시간 → 선제점검 판단 → 표준 업종 진단카드 → 담당자 검토 → 기업·현장 확인 → 기존 기업지원·고용지원·직업훈련 체계 검토 → 다음 분기 재점검'
LIMIT = '모형은 이번 분기에 어느 업종을 어느 수준으로 먼저 확인할지만 결정한다. 위기 여부·확률·원인·기업별 지원·사업 선정·예산은 결정하지 않는다.'
STATE_LABELS = {'S1':'생산↑·고용↑','S2':'생산↑·고용↓','S3':'생산↓·고용↑','S4':'생산↓·고용↓','N':'한 축 이상 정확한 0','INVALID':'상태 분류에 필요한 자료 미확인'}

def rule_registry():
    law='https://www.law.go.kr/LSW/admRulLsInfoP.do?admRulSeq=2100000255684'
    old='https://www.law.go.kr/LSW/admRulLsInfoP.do?admRulSeq=2100000209796'
    employment_law='https://www.law.go.kr/LSW/admRulInfoP.do?admRulSeq=2100000278624&chrClsCd=010201'
    work='https://m.work24.go.kr/cm/c/f/1100/selecSystInfo.do?systClId=SC00000364&systCnntId=CI00001365&systId=SI00000375'
    rows=[
        ('E','max(0, -KICOX 분기말 고용 YoY)','5% / 10%','고용 진입·상위 신호','PRINCIPLE_ADAPTED',employment_law,'2026.5.4 시행 고용위기지역 고시 제3조①2호 5%, ④2호 10% 확인. 지역 피보험자 최근 6개월 평균을 업종 종사자 분기말 YoY로 변경. 다른 법정 결합요건·심의절차를 재현하지 않음.'),
        ('R_entry','max(0, 산단 제조업 전체 YoY - 업종 YoY)','5%p','상대 열위 진입','PRINCIPLE_ADAPTED',work,'공식 비교는 모든 업종 피보험자 평균. 본 모형은 동일 산단 제조업 10개 업종 합계와 비교.'),
        ('R_up','R과 동일','10%p','상대 열위 상위','PROJECT_OPERATIONAL','','10%p 상위 경계의 직접 조문 근거 없음. 진입 경계와 출처 분리.'),
        ('A','max(0, 전년동기 고용 - 현재 고용) / 현재 산단 제조업 고용 × 100','1% / 2%','규모효과 진입·상위','PROJECT_OPERATIONAL','','현재 산단 고용 100명당 전년동기 대비 감소인원 1/2명에 해당. 최적값·정책기준 아님. 대형 업종 영향 큼.'),
        ('P','max(0, -명목 분기 생산액 YoY)','5%','상위단계 보강','PRINCIPLE_ADAPTED',law,'현행 제2조는 전년 및 전전년 동기 생산액/생산량 등 결합요건. 본 모형은 명목 생산액 전년동기 비교만 사용하며 가격·물량 분해 불가.'),
        ('repeated_employment_entry_signal','현재 및 실제 직전 달력분기에 E/R/A 진입신호 존재','연속 2분기','Q3 시간축 보강','PRINCIPLE_ADAPTED',old,'지속성 원리 참고. 고시 월별 지속요건, 기존 g4 음의 고용 YoY 연속길이, 동일 Q1 상태 run_length와 모두 다름.'),
        ('scale_gate','현재 업종 고용이 기준 이상','300인','우선점검 진입만 제한','PRINCIPLE_ADAPTED',law,'공식 주된 산업의 비중·종사자 요건 중 규모 원리만 참고한 운영규칙. 추가확인 신호 보존. 300인 최적성 미입증.'),
        ('ladder','상위 고용신호 AND (P OR 반복) AND 규모; 아니면 진입신호','관찰 / 추가확인 / 우선점검','행동단계','PROJECT_OPERATIONAL','','법정 지정의 결합식이 아니라 내부 점검 사다리.'),
        ('missing','핵심 E/R/A·고용 미확인 시 판정보류; P만 없으면 알려진 신호로 최소판정','보간 없음','자료품질','PROJECT_OPERATIONAL','','미확인 보강조건은 충족으로 간주하지 않음. 최소판정과 자료 플래그 함께 전달.'),
        ('same_stage_rank','같은 분기·단계에서 감소인원 내림차순, 동률 업종명','감소인원','처리순서','PROJECT_OPERATIONAL','','Q2 전체 점수화 아님. 동률 순서는 위험 우열이 아닌 결정적 표시순서.'),
    ]
    return pd.DataFrame([dict(rule_name=a,definition=b,threshold=c,role=d,source_category=e,source_url=f,source_note=g,reason_for_adaptation=g,checked_at='2026-09-18') for a,b,c,d,e,f,g in rows])

def institutions():
    return pd.DataFrame([
        ['산업·경제동향','창원상공회의소','지역·산단·업종','정기 경제동향','https://changwoncci.korcham.net/front/board/boardContentsView.do?boardId=11175&contId=130203&menuId=3992'],
        ['산업·고용동향','창원산업진흥원','지역·산업','산업·경제동향 및 고용동향 자료','https://www.cwip.or.kr/'],
        ['지역 위기진단','경남TP 위기지원센터','중소기업 밀집지역·기업','모니터링·심층현장조사·맞춤지원','https://www.gntp.or.kr/introduce/staff'],
        ['기업 진단·고용지원','창원고용복지+센터','기업·구직자','기업 도약보장 패키지 등 진단·연계(운영 공지 시점 확인 필요)','https://www.moel.go.kr/local/changwon/news/reportexplan/view.do?bbs_seq=20240901144'],
        ['기업 현장지원','창원산업진흥원 기업지원 기능·마이스터센터','기업','현장애로 컨설팅·기술지원','https://www.cwip.or.kr/'],
        ['인력·훈련 연계','경남지역인적자원개발위원회','산업·기업 인력수요','수요조사·맞춤형 훈련 연계','https://gnhrd.or.kr/'],
    ],columns=['role','institution','unit','function','source_url'])

def trace_columns(d):
    d=d.copy()
    mapping={'state':'q1_state','check_question':'q1_question_route','emp_delta':'q2_employment_delta','e_yoy':'q2_employment_yoy','employment_share_pct':'q2_employment_share','contribution_pct':'q2_contribution','rank_in_stage':'q2_same_stage_rank','run_length':'q3_state_run_length','transition_type':'q3_transition','persist':'q3_repeated_signal','E':'signal_e','R':'signal_r','A':'signal_a','P':'signal_p','scale_ok':'decision_scale_gate','stage':'decision_stage','stage_reason':'decision_reason'}
    for src,dst in mapping.items(): d[dst]=d[src]
    # The source transition_type is t -> t+1. Handoff must use t-1 -> t,
    # otherwise every latest-quarter card has an empty transition.
    valid=d.previous_state.isin(['S1','S2','S3','S4','N']) & d.state.isin(['S1','S2','S3','S4','N'])
    d['q3_transition']=(d.previous_state.astype(str)+' → '+d.state.astype(str)).where(valid,'이전 또는 현재 상태 미확인')
    d['q1_state_label']=d.state.map(STATE_LABELS)
    d['decision_entry_trigger']=d.apply(lambda r:'|'.join(x for x in 'ERA' if r[x+'_entry']) or '없음',axis=1)
    d['decision_reinforcement']=d.apply(lambda r:'|'.join(x for x,v in [('생산',r.P_support),('반복',r.persist)] if v) or '확인된 보강 없음',axis=1)
    d['next_review_quarter']=(pd.PeriodIndex(d.quarter,freq='Q')+1).astype(str)
    return d

def diagnostic_cards(latest, panel):
    cards=latest.copy()
    def facts(r):
        p='생산자료 미확인' if pd.isna(r.p_yoy) else f'명목 생산 YoY {r.p_yoy:.2f}%'
        return f'{p}; 고용 YoY {r.e_yoy:.2f}%; 고용 증감 {r.emp_delta:,.0f}명; 산단 고용비중 {r.employment_share_pct:.2f}%'
    cards['observed_facts']=cards.apply(facts,axis=1)
    cards['not_identified']='수주·자동화·외주화·기업이전·고용조정 계획·미충원·설비전환의 유무와 원인은 집계자료만으로 확정할 수 없음'
    cards['recent_state_path']=cards.apply(lambda r:' → '.join(panel[(panel.industry==r.industry)&(panel.quarter<=r.quarter)].sort_values('quarter').tail(4).apply(lambda x:f'{x.quarter}:{x.state}',axis=1)),axis=1)
    cards['followup']='현장 확인 결과에 따라 기존 기업지원·고용지원·직업훈련 체계 검토'
    cards['review_status']='담당자 검토 대기'
    cards['reviewer']=''
    cards['field_evidence']=''
    cards['support_review_result']=''
    cards['scope']=LIMIT
    return cards

def cards_markdown(cards):
    def fmt(value, digits=2): return '미확인' if pd.isna(value) else f'{value:.{digits}f}'
    chunks=[f'# {TITLE} — 업종 진단카드\n\n{PURPOSE}\n\n{FLOW}\n\n{LIMIT}\n']
    for r in cards.itertuples():
        chunks.append(f'''## {r.industry} · {r.quarter} · {r.stage}

- 같은 단계 처리순위: {r.rank_in_stage} (감소인원 순; 동률은 업종명 순)
- Q1: {r.q1_state} {r.q1_state_label}
- 관측사실: {r.observed_facts}
- Q2 전체 순증감 기여율: {fmt(r.q2_contribution)}% (상쇄가 커 순변화/총변화 < 0.30이면 미표시)
- Q3 상태 지속: {fmt(r.run_length,0)}분기; 직전→현재 전환: {r.q3_transition}; 반복 고용진입신호: {r.persist}
- 최근 경로: {r.recent_state_path}
- E {r.E:.2f}% / R {r.R:.2f}%p / A {r.A:.2f}% / P {r.P:.2f}%
- 경계 통과: E {r.E_entry}/{r.E_up}, R {r.R_entry}/{r.R_up}, A {r.A_entry}/{r.A_up} (진입/상위); P {r.P_support}; 규모 {r.scale_ok}
- 단계 근거: {r.stage_reason}
- 자료 플래그: 고용핵심 미확인={r.data_quality_core_missing}, 생산 미확인={r.data_quality_production_missing}, 직전신호 미확인={r.data_quality_previous_signal_unknown}
- 집계자료로 알 수 없는 것: {r.not_identified}
- 추가 확인질문: {r.check_question}
- 확인 담당 기능: {r.first_owner}
- 후속 연결: {r.followup}
- 담당자 검토: 미실시 / 현장 근거: 미입력 / 지원 검토결과: 미입력
- 다음 재점검: {r.next_review_quarter}
''')
    return '\n'.join(chunks)

def flow_html():
    return '''<div style="font-family:Malgun Gothic,sans-serif;max-width:1000px;padding:24px;background:#f3f7fa;border-radius:16px;color:#16324a">
<h2>기존 기능 사이를 잇는 업종 단위 진입점</h2>
<div style="padding:16px;background:white;border-left:6px solid #59758b"><b>기존 기능</b>　산업·고용 동향 분석</div>
<p style="text-align:center">↓</p>
<div style="padding:18px;border:2px dashed #bd731d;background:#fff9ed"><b>연결할 질문</b><br>어느 업종을 먼저 볼 것인가?　왜 봐야 하는가?　무엇을 확인할 것인가?</div>
<p style="text-align:center">↓</p>
<div style="padding:20px;background:#123e59;color:white"><b>우리 프로젝트</b><br><br>Q1 상태: 확인질문　│　Q2 규모: 영향·처리순서　│　Q3 시간: 반복신호<br><br>선제점검 판단 → 관찰 / 추가확인 / 우선점검 → 표준 업종 진단카드</div>
<p style="text-align:center">↓ 담당자에게 근거·질문·자료 한계 인계</p>
<div style="padding:18px;background:white;border-left:6px solid #258575"><b>기존 기능</b>　담당자 검토 → 기업·현장 확인<br><br>기업·경영 확인 → 기업지원 검토<br>고용조정 확인 → 고용지원 검토<br>인력·숙련 확인 → 직업훈련 검토</div>
<p><b>↻ 다음 분기 재점검</b>　현장 근거·지원 검토결과는 담당자가 기록</p>
<small>모형은 점검의 순서와 수준을 제안합니다. 위기 확정·기업 선정·지원사업 처방은 하지 않습니다.</small></div>'''

def stage_grid(panel):
    grid=panel.pivot(index='industry',columns='quarter',values='stage')
    colors={'관찰':'#e7eff5','추가확인':'#ffedbc','우선점검':'#ffd5cc','자료확인':'#e2e2e2'}
    return grid.style.map(lambda v:f'background-color:{colors.get(v,"white")};color:#172b3a').set_properties(**{'font-size':'11px','white-space':'nowrap'}).to_html()

def distribution_html(dist):
    colors={'관찰':'#708fa6','추가확인':'#c08a20','우선점검':'#b74c39','자료확인':'#777777'}
    rows=[]
    for r in dist.to_dict('records'):
        bars=''.join(f'<span style="display:inline-block;width:{int(r.get(s,0))*55}px;background:{c};color:white;text-align:center;padding:7px 0">{s} {int(r.get(s,0))}</span>' for s,c in colors.items() if r.get(s,0))
        rows.append(f'<div style="margin:5px 0;white-space:nowrap"><b style="display:inline-block;width:80px">{r["quarter"]}</b>{bars}</div>')
    return '<div style="overflow:auto">'+''.join(rows)+'</div>'
