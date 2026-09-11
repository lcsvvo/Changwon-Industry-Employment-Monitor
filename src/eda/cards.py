# -*- coding: utf-8 -*-
"""Section 7·8 — 업종별 진단카드와 최종 결과 산출물.

notebooks/02_eda.ipynb 셀 63·65(및 셀 2의 markdown_table)의 로직을 그대로 옮겼다.
"""
import json
from pathlib import Path

import pandas as pd

from .panel import state_path


# ---------------------------------------------------------------- Section 7. 진단카드
def diagnostic_card(state, longest, q2, ctx, main_ind, usable, path_n=6, path_sep='→'):
    """최신분기의 상태·규모·현재 지속기간과 보조지표를 한 표로 모은다.

    Q2 기준에 따라 상세 경로 표시 대상으로 선택된 업종에는 ★를 붙인다.
    """
    cur = state[state.quarter == ctx.latest].set_index('industry')
    card = pd.DataFrame({
        '현재국면': cur.state,
        '생산YoY%': cur.production_yoy,
        '고용YoY%': cur.employment_yoy,
        '고용(명)': cur.employment,
        '고용증감(명)': cur.emp_delta,
        '고용비중%': cur.employment / cur.employment.sum() * 100,
        '현재지속(Q)': cur.run_length,
        '최장지속(Q)': longest.지속분기,
        '최장국면': longest.국면,
        '가동률%': cur.op_rate_official,
        '가동률YoY(%p)': cur.op_rate_official_yoy_pp,
        '입주업체': cur.firms_in,
        '입주YoY%': cur.firms_in_yoy,
        '가동업체': cur.firms_op,
        '가동YoY%': cur.firms_op_yoy,
    }).reindex(ctx.ind_order_emp)
    if usable:
        card.insert(6, '기여율%', q2['기여율%'].reindex(ctx.ind_order_emp))
    card['최근경로(6Q)'] = [state_path(state, i, path_n, path_sep) for i in card.index]
    card.index = [f'{i} ★' if i in main_ind else i for i in card.index]
    return card


# ---------------------------------------------------------------- Section 8. 최종 산출물
def final_summary_text(results_summary, latest):
    """Q1·Q2·Q3 요약 Markdown 텍스트."""
    h = results_summary['q1_history']
    q2r = results_summary['q2']
    q3r = results_summary['q3']
    p = results_summary['ppi']
    return f"""### Q1·Q2·Q3 요약

| 질문 | 이번 계산에서 확인한 것 | 해석 범위 |
|---|---|---|
| Q1 상태 | 고용 감소 {h['n_down']}건 중 명목 생산액 증가 {h['n_up_down']}건({h['simple_pct']:.1f}%) | 같은 고용 방향에서도 명목 생산액 방향은 다를 수 있다. |
| Q2 규모 | {latest} 고용 전년동기 증감 {q2r['net_delta']:+,.0f}명, 최대 감소 {', '.join(q2r['largest_decrease_industries'])} | 증감률과 실제 인원 규모를 함께 읽는다. |
| Q3 시간 | 최장 관측 {q3r['max_run']}분기, 인접 유지 {q3r['n_same']}/{q3r['n_adjacent']}건({q3r['same_pct']:.1f}%) | 관측된 지속·전환이며 실제 전체 기간이나 미래 확률이 아니다. |

PPI 비교 {p['n_comparable']}건 중 선택 후보 모두에서 반전 {p['n_opposite']}건, 후보별 방향 차이 {p['n_candidate_dependent']}건이다. 본분석은 명목 기준을 유지한다. 자동화·인력부족·정책효과 등 원인은 이 자료만으로 확인할 수 없다.
"""


def report_text(results_summary, summary_text):
    """outputs/report/EDA_revision_report.md 본문."""
    p = results_summary['ppi']
    return "\n".join([
        '# EDA 실행 결과',
        '',
        '## 분석 결정',
        '',
        '- 본분석 국면은 KICOX 명목 생산액 YoY와 고용 YoY로 계산한다.',
        '- PPI는 선택 후보에 한정한 민감도 분석이며 실제 물량이나 생산성을 뜻하지 않는다.',
        '- EIS는 모집단이 다른 고용 지표의 방향 비교이며 KICOX 정확성 검증이 아니다.',
        '',
        '## 핵심 결과',
        '',
        summary_text.replace('### Q1·Q2·Q3 요약', '').strip(),
        '',
        '## PPI 보조분석',
        '',
        f'- 원자료 {p["month_start"]}~{p["month_end"]}, 선택 후보 {p["selected_series"]}계열.',
        f'- 비교 {p["n_comparable"]}건 중 선택 후보 모두에서 반전 {p["n_opposite"]}건, 후보별 방향 차이 {p["n_candidate_dependent"]}건.',
        '- 선택 후보 결과를 모든 가능한 매핑으로 일반화하지 않으며 본분석 국면을 대체하지 않는다.',
    ])


def save_outputs(results_summary, report, input_audit, verification_scope_df, dir_tab, dir_report):
    """보고서·요약 JSON·출처·검증범위 파일을 저장한다."""
    dir_tab, dir_report = Path(dir_tab), Path(dir_report)
    (dir_report / 'EDA_revision_report.md').write_text(report, encoding='utf-8')
    (dir_tab / 'results_summary.json').write_text(
        json.dumps(results_summary, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    pd.DataFrame(input_audit).to_csv(dir_tab / 'input_provenance.csv', index=False, encoding='utf-8-sig')
    verification_scope_df.to_csv(dir_tab / 'verification_scope.csv', index=False, encoding='utf-8-sig')


# ---------------------------------------------------------------- 표 렌더링 도우미
def markdown_table(frame):
    """표 렌더링을 위해 별도 패키지에 의존하지 않는다."""
    f = frame.reset_index()
    cols = [str(x) for x in f.columns]
    rows = [[str(v).replace('|', '/').replace('\n', ' ') for v in row]
            for row in f.itertuples(index=False, name=None)]
    return '\n'.join(['| ' + ' | '.join(cols) + ' |',
                      '| ' + ' | '.join(['---'] * len(cols)) + ' |'] +
                     ['| ' + ' | '.join(row) + ' |' for row in rows])
