# -*- coding: utf-8 -*-
"""최신분기 업종별 진단카드(CSV·Markdown).

카드는 다섯 구획을 분리한다: 데이터가 확인한 사실 / 모형의 점검단계 / 품질·경계 플래그 /
추가 확인 질문 / 현재 자료로 판단 불가. 파라미터가 등록되지 않았으면 점검단계를 만들지 않는다.
업종 순서는 최신분기 고용 규모순(기존 노트북 정렬 기준)이며 점검 우선순위가 아니다.
nullable 값(pd.NA 포함)은 bool 문맥에서 직접 평가하지 않는다.
"""
import pandas as pd

from . import config
from .ppi_aux import is_missing

G = config.CRITERION_COLUMNS


def is_true(value):
    """결측이면 False, 아니면 bool 값. pd.NA를 bool로 직접 평가하지 않는다."""
    return False if is_missing(value) else bool(value)


def _fmt(value, spec='{:,.2f}', missing='결측'):
    if is_missing(value):
        return missing
    if value == 0:
        return spec.replace('+', '').format(0.0)
    return spec.format(value)


def g4_text(delta, run, left_censored, open_run, window_saturated):
    """전년동기 대비 고용 하회 연속분기 표시문."""
    if is_missing(run):
        return f'δ={delta:.1f}: 고용 YoY 결측으로 계산불가'
    run = int(run)
    if run == 0:
        return f'δ={delta:.1f}: 고용 YoY가 기준을 하회하지 않음(0분기)'
    left = is_true(left_censored)
    text = f"δ={delta:.1f}: 고용 YoY가 기준을 {'최소 ' if left else ''}{run}분기 연속 하회"
    notes = []
    if left:
        notes.append('분석 시작분기부터 이어진 좌절단 관측')
    if is_true(window_saturated):
        notes.append('분석창 전체 길이 도달')
    if is_true(open_run):
        notes.append('최신분기까지 이어진 열린 run')
    return text + (f" ({'; '.join(notes)})" if notes else '')


def confirmation_text(row):
    status = row.get('ppi_mapping_confirmation_status')
    if is_missing(status):
        status = 'CONFIRMATION_MISSING'
    return config.PPI_CONFIRMATION_LABELS.get(status, f'매핑 확정 상태 알 수 없음({status})')


def ppi_text(row):
    status = row.get('ppi_direction_status')
    label = config.PPI_STATUS_LABELS.get(status, status)
    confirmed = confirmation_text(row)
    if status not in config.PPI_COMPARABLE_STATUSES:
        return f"{label}({row.get('ppi_comparison_reason')}) · {confirmed}"
    lo, hi = row['ppi_adjusted_prod_yoy_lower'], row['ppi_adjusted_prod_yoy_upper']
    rng = f'{lo:+.2f}%' if lo == hi else f'{lo:+.2f}%~{hi:+.2f}%'
    return (f"PPI 조정 생산 YoY {rng}(후보 {row['ppi_candidate_n']}개) · "
            f"PPI 후보 적용 시 Q1 상태 집합 {row['ppi_alt_state_set']} · {label} · {confirmed}")


def firm_change_text(value):
    if is_missing(value):
        return '계산불가'
    return '있음' if bool(value) else '없음'


def check_questions(row):
    questions = [config.Q1_CHECK_QUESTIONS[row['state']]]
    if row['ppi_direction_status'] in ('OPPOSITE_ALL', 'CANDIDATE_DEPENDENT', 'ZERO_BOUNDARY'):
        questions.append('PPI 후보 적용 시 명목 생산 방향과의 불일치가 있다: 가격 변화와 물량 변화의 구분을 '
                         '원자료·현장 확인으로 점검한다(매핑 미확정, 판정 변경 없음).')
    if is_true(row.get('op_rate_prod_direction_differs')):
        questions.append('가동률 전년동기 차이의 방향이 명목 생산 YoY 방향과 다르다: 설비·제품구성·재고 변화 '
                         '여부를 확인한다(판정 변경 없음).')
    if is_true(row.get('qoq_recovery_while_yoy_below')):
        questions.append('고용 YoY는 음수이지만 직전분기 대비 고용은 증가했다: 계절성·일시 요인 여부를 확인한다.')
    if is_true(row.get('small_firm_count_flag')):
        questions.append(f'{config.SMALL_FIRM_LABEL} 소규모 집계이므로 개별 업체 단위 변화가 있었는지 원자료로 확인한다.')
    if str(row['threshold_flag']).startswith('SENSITIVE_'):
        questions.append(f"Q1 상태가 0% 경계에 가깝다(threshold {row['first_neutral_threshold']:.1f}%에서 N): "
                         '상태 해석에 유의한다.')
    if is_true(row.get('residual_category')):
        questions.append(config.RESIDUAL_CARD_TEXT)
    return questions


def latest_cards(panel, ctx, validation, summary=None, assignments=None):
    """최신분기 업종별 카드 표."""
    lat = panel[panel['quarter'] == ctx.latest].set_index('industry').reindex(ctx.ind_order_emp)
    rows = []
    for industry, r in lat.iterrows():
        rec = {
            'industry': industry, 'quarter': ctx.latest,
            # 1. 데이터가 확인한 사실
            'state': r['state'], 'production_yoy_nominal': r['production_yoy'],
            'employment_yoy': r['employment_yoy'], 'employment': r['employment'],
            'employment_lag4': r['employment_lag4'], 'emp_delta': r['emp_delta'],
            G['g1']: r[G['g1']], G['g2']: r[G['g2']], G['g3']: r[G['g3']],
            **{col: r[col] for col in config.G4_DELTA_COLUMNS},
            **{f'{col}_text': g4_text(d, r[col], r[f'{col}_left_censored'], r[f'{col}_open_run'],
                                      r[f'{col}_window_saturated'])
               for col, d in config.G4_DELTA_COLUMNS.items()},
            'recent4_emp_yoy_negative_count': r['recent4_emp_yoy_negative_count'],
            'recent4_emp_valid_n': r['recent4_emp_valid_n'],
            'emp_qoq_delta': r['emp_qoq_delta'],
            'qoq_recovery_while_yoy_below': r['qoq_recovery_while_yoy_below'],
            'firms_op': r['firms_op'], 'firm_count_delta_qoq': r['firm_count_delta_qoq'],
            'firm_count_delta_yoy': r['firm_count_delta_yoy'], 'emp_per_firm': r['emp_per_firm'],
            'op_rate_used': r['op_rate_used'], 'op_rate_used_source': r['op_rate_used_source'],
            'op_rate_is_approx': r['op_rate_is_approx'], 'op_rate_used_yoy_pp': r['op_rate_used_yoy_pp'],
            'op_rate_yoy_basis': r['op_rate_yoy_basis'],
            'employment_share_pct': r['employment_share_pct'], 'contribution_pct': r['contribution_pct'],
            'contrib_usable': r['contrib_usable'],
            'proportional_expected_delta': r['proportional_expected_delta'], 'excess_delta': r['excess_delta'],
            'previous_state': r['previous_state'],
            'recent_state_transition': (None if is_missing(r['previous_state'])
                                        else f"{r['previous_state']}->{r['state']}"),
            'same_state_run_length': r['run_length'],
            # 2. 모형의 점검단계
            'model_run_status': validation.run_mode,
            'scenario_display_text': None, 'display_class': None,
            'action_review_status': 'NOT_REVIEWED',
            # 3. 품질·경계 플래그
            'core_data_status': r['core_data_status'], 'scorable': r['scorable'],
            'unscorable_reason': r['unscorable_reason'], 'threshold_flag': r['threshold_flag'],
            'first_neutral_threshold': r['first_neutral_threshold'],
            'q1_routing_status': r['q1_routing_status'],
            'ppi_direction_status': r['ppi_direction_status'], 'ppi_summary': ppi_text(r),
            'ppi_alt_state_set': r['ppi_alt_state_set'],
            'ppi_mapping_review_type': r['ppi_mapping_review_type'],
            'ppi_mapping_confirmed': r['ppi_mapping_confirmed'],
            'ppi_mapping_confirmation_status': r['ppi_mapping_confirmation_status'],
            'firm_count_changed_yoy': r['firm_count_changed_yoy'],
            'small_firm_count_flag': r['small_firm_count_flag'], 'small_firm_caution': r['small_firm_caution'],
            'residual_category': r['residual_category'], 'routeability_status': r['routeability_status'],
            'residual_note': config.RESIDUAL_CARD_TEXT if is_true(r['residual_category']) else '',
            # 4·5
            'check_questions': ' / '.join(check_questions(r)),
            'not_determinable': ' / '.join(config.NOT_DETERMINABLE_STATEMENTS),
            **{c: r[c] for c in config.PROVENANCE_COLUMNS},
        }
        if summary is not None:
            s = summary[(summary['industry'] == industry) & (summary['quarter'] == ctx.latest)]
            if len(s):
                rec['scenario_display_text'] = s.iloc[0]['scenario_display_text']
                if validation.can_emit_display_class:
                    rec['display_class'] = s.iloc[0].get('display_class')
        if assignments is not None:
            a = assignments[(assignments['industry'] == industry) & (assignments['quarter'] == ctx.latest)]
            for sid, cls in zip(a['scenario_id'], a['display_class_by_scenario']):
                rec[f'display_class_by_scenario[{sid}]'] = cls
        rows.append(rec)
    return pd.DataFrame(rows)


def _bullets(items):
    return '\n'.join(f'- {x}' for x in items)


def cards_markdown(cards, ctx, meta, validation, eis_context, stage_actions_status,
                   recent_history=None, unscorable_panel_rows=0):
    blocked = not validation.can_run_scenarios
    lines = [
        f'# 최신분기 업종별 진단카드 ({ctx.latest})', '',
        f'> {config.MODEL_TITLE}', '',
        f"- 실행 ID: `{meta['run_id']}`",
        f"- 모형 명세 버전: `{config.MODEL_SPEC_VERSION}`",
        f"- 기준 패널 입력 해시: `{meta['input_sha256']}` (원본 바이트 `{meta['input_sha256_raw_bytes']}`)",
        f"- 실행 시작: {meta['run_started_at']}",
        f"- 파라미터 상태: `{validation.effective_status}` · 실행 상태: `{validation.run_mode}`", '',
        '## 읽는 방법', '',
        _bullets([
            '카드는 **데이터가 확인한 사실 / 모형의 점검단계 / 품질·경계 플래그 / 추가 확인 질문 / 현재 자료로 판단 불가**를 구분한다.',
            '업종 순서는 최신분기 고용 규모순이며 점검 우선순위가 아니다.',
            'Q1 상태(S1~S4·N)는 무엇을 확인할지 정하는 라우팅 범주이며 위험 서열이 아니다.',
            '생산 YoY는 명목 생산액 기준이다. PPI 조정 생산 YoY는 미확정 매핑에 따른 민감도 값이다.',
            '가동률·업체 수·PPI·EIS는 점검단계를 올리거나 내리지 않는다.',
            config.MODEL_ASSIGNMENT_METHOD_NOTE,
        ]), '',
    ]
    if blocked:
        lines += [
            '## 모형 점검단계: 산출하지 않음', '',
            f'실행 상태 `{validation.run_mode}` — 가중치·경계(b1·b2)·lambda·delta_emp·'
            'require_employment_evidence가 등록되지 않아 ELECTRE 점검단계를 만들지 않았다. '
            '아래 카드에는 점검단계가 없으며, 비어 있는 값을 임의로 채우지 않았다.', '',
            f'- 비어 있는 파라미터 필드 수: {len(validation.missing_parameter_fields)}',
            f'- 비어 있는 등록 필드 수: {len(validation.missing_registration_fields)}',
            f'- 비어 있는 승인 필드 수: {len(validation.missing_approval_fields)}',
            '- 전체 목록: `outputs/tables/model_validation_report.json`의 `parameter_validation`',
            '- canonical 위치에 과거 ELECTRE 산출물이 있어도 현재 결과가 아니다. '
            f'현재 실행 여부는 `{config.CURRENT_MANIFEST.as_posix()}`로 확인한다.', '',
        ]
    lines += ['## 지역 맥락(EIS, 창원시 전체 제조업)', '', config.EIS_SCOPE_NOTE, '']
    if eis_context is not None and len(eis_context):
        recent = eis_context.tail(config.RECENT_HISTORY_N)
        lines += ['| 분기 | EIS 창원시 제조업 피보험자(명) | 전년동기 대비(%) |', '|---|---:|---:|']
        lines += [f"| {r.quarter} | {_fmt(r.eis_changwon_manufacturing, '{:,.0f}')} | "
                  f"{_fmt(r.eis_manufacturing_yoy_pct, '{:+.2f}')} |" for r in recent.itertuples()]
        lines += ['', 'EIS와 국가산단 고용의 동행 정도로 산단 밖 제조업의 변화 원인을 추론하지 않는다.', '']
    else:
        lines += ['EIS 맥락 자료 없음', '']

    lines += ['## 업종별 카드', '']
    for r in cards.to_dict('records'):
        run_text = (f"동일 Q1 상태 연속 {_fmt(r['same_state_run_length'], '{:.0f}')}분기"
                    if not is_missing(r['same_state_run_length']) else '동일 Q1 상태 연속기간 해당 없음(S1~S4가 아님)')
        facts = [
            f"Q1 상태 `{r['state']}` · 명목 생산 YoY {_fmt(r['production_yoy_nominal'], '{:+.2f}')}% · "
            f"고용 YoY {_fmt(r['employment_yoy'], '{:+.2f}')}%",
            f"고용 {_fmt(r['employment'], '{:,.0f}')}명(전년동기 {_fmt(r['employment_lag4'], '{:,.0f}')}명, "
            f"증감 {_fmt(r['emp_delta'], '{:+,.0f}')}명)",
            f"{config.CRITERION_LABELS['g1']} {_fmt(r[G['g1']], '{:,.0f}')} · "
            f"{config.CRITERION_LABELS['g2']} {_fmt(r[G['g2']], '{:.4f}')} · "
            f"{config.CRITERION_LABELS['g3']} {_fmt(r[G['g3']], '{:.4f}')}",
            f"{config.CRITERION_LABELS['g4']}: " + ' · '.join(r[f'{c}_text'] for c in config.G4_DELTA_COLUMNS),
            f"최근 4분기 중 고용 YoY 음수 분기 {r['recent4_emp_yoy_negative_count']}/{r['recent4_emp_valid_n']}",
            f"직전분기 대비 고용 {_fmt(r['emp_qoq_delta'], '{:+,.0f}')}명"
            + (' (고용 YoY 음수 구간 중 직전분기 대비 증가)' if is_true(r['qoq_recovery_while_yoy_below']) else ''),
            f"가동업체 {_fmt(r['firms_op'], '{:,.0f}')}개(전년동기 대비 {_fmt(r['firm_count_delta_yoy'], '{:+,.0f}')}개, "
            f"직전분기 대비 {_fmt(r['firm_count_delta_qoq'], '{:+,.0f}')}개) · "
            f"업체당 고용 {_fmt(r['emp_per_firm'], '{:,.1f}')}명",
            f"가동률 {_fmt(r['op_rate_used'], '{:.1f}')}% "
            f"({'근사값' if is_true(r['op_rate_is_approx']) else '공식값'}: {r['op_rate_used_source']}) · "
            f"전년동기 대비 {_fmt(r['op_rate_used_yoy_pp'], '{:+.1f}', '계산하지 않음')}%p ({r['op_rate_yoy_basis']})",
            f"고용비중 {_fmt(r['employment_share_pct'], '{:.2f}')}% · 비례배분 기준선 대비 초과증감 "
            f"{_fmt(r['excess_delta'], '{:+,.1f}')}명(원인 아님)",
            f"최근 상태 전환 `{r['recent_state_transition'] or '직전 관측 없음'}`(관측 경로이며 악화·회복 판정이 아님) · "
            + run_text,
        ]
        if blocked:
            stage = [f"점검단계 미산출 — `{r['model_run_status']}`", f"후속 행동 검토 상태: `{r['action_review_status']}`"]
        else:
            stage = [f"시나리오 요약: {r['scenario_display_text']}"]
            stage += [f"{k[len('display_class_by_scenario['):-1]}: `{v}`" for k, v in r.items()
                      if k.startswith('display_class_by_scenario[')]
            if not is_missing(r.get('display_class')):
                stage.append(f"승인 파라미터 기준 점검단계: `{r['display_class']}`")
            if recent_history is not None and len(recent_history):
                h = recent_history[recent_history['industry'] == r['industry']].drop_duplicates('scenario_id')
                stage += [f"{config.RECENT_HISTORY_TITLE} [{x.scenario_id}]: {x.window_class_path}"
                          for x in h.itertuples()]
            stage.append(f"후속 행동 검토 상태: `{r['action_review_status']}`")
        flags = [
            f"판정가능 여부 `{r['core_data_status']}` · Q1 라우팅 `{r['q1_routing_status']}` · "
            f"threshold 플래그 `{r['threshold_flag']}`",
            r['ppi_summary'],
            f"PPI 매핑 검토유형: {r['ppi_mapping_review_type']} · 확정 상태 `{r['ppi_mapping_confirmation_status']}`",
            f"가동업체 수 전년동기 대비 변화(firm_count_changed_yoy): {firm_change_text(r['firm_count_changed_yoy'])} "
            '— 표시용이며 고용 변화의 원인 판단이 아님',
            f"{config.SMALL_FIRM_LABEL}(small_firm_count_flag): {'해당' if is_true(r['small_firm_count_flag']) else '해당 없음'}",
        ]
        if is_true(r['small_firm_count_flag']):
            flags.append(r['small_firm_caution'])
        if is_true(r['residual_category']):
            flags.append(f"`{r['routeability_status']}` — {r['residual_note']}")
        lines += [f"### {r['industry']}", '', '**1. 데이터가 확인한 사실**', '', _bullets(facts), '',
                  '**2. 모형의 점검단계**', '', _bullets(stage), '',
                  '**3. 품질·경계 플래그**', '', _bullets(flags), '',
                  '**4. 추가 확인 질문**', '', _bullets(r['check_questions'].split(' / ')), '',
                  '**5. 현재 자료로 판단 불가**', '', _bullets(r['not_determinable'].split(' / ')), '']

    latest_undetermined = cards[~cards['scorable'].astype(bool)]
    lines += ['## 판정불가 행(데이터 검토)', '']
    if len(latest_undetermined):
        lines += [_bullets([f"{x.industry}: {x.unscorable_reason}" for x in latest_undetermined.itertuples()]), '']
    else:
        lines += [f'최신분기에는 판정불가 행이 없다. 전체 패널의 판정불가 행 {unscorable_panel_rows}건은 '
                  '`outputs/tables/electre_eligibility_audit.csv`에 원인과 함께 보존했다. '
                  '판정불가는 관찰보다 낮은 단계가 아니라 별도 데이터 검토 대상이다.', '']
    lines += ['## 단계별 후속 행동', '',
              f'상태 `{stage_actions_status}` — 담당 역할·처리기한·필수 확인·산출물은 실제 기관이 정해야 하며 '
              '이 카드에서 임의로 지정하지 않았다(`config/stage_actions.template.yaml`).', '']
    return '\n'.join(lines)
