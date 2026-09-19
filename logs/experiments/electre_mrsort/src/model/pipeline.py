# -*- coding: utf-8 -*-
"""전체 실행 — 입력 패널·품질 플래그·기준 중복성 진단·(등록된 경우) 시나리오별 ELECTRE·진단카드·검증 보고서.

파라미터가 없거나 등록조건을 충족하지 않으면 ELECTRE 실증 배정과 그 산출물을 만들지 않고,
model_validation_report.json에 차단 사유와 비어 있는 필드를 기록한다.
모든 CSV에 run_id 등 provenance를 넣고, 실행별 디렉터리와 현재 실행 manifest를 분리해 저장한다.
"""
import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yaml

from eda import config as eda_config
from eda import panel as eda_panel

from . import (cards, config, derive, diagnostics, electre, inputs, manifest, params, pilot, ppi_aux,
               stage_actions, validation)

G = config.CRITERION_COLUMNS


def _rel(root, path):
    try:
        return Path(path).resolve().relative_to(Path(root).resolve())
    except ValueError:
        return Path(path)


def _stage_actions(reg, root, overrides):
    """단계별 후속 행동 설정 검증. 파일이 없으면 템플릿을 검증하며 APPROVED가 될 수 없다."""
    P = config.PATHS
    if 'stage_actions' in overrides and overrides['stage_actions'] is not None:
        reg.record_override(P['stage_actions'], '단계별 후속 행동 설정(override)', True)
        return stage_actions.validate_stage_actions(overrides['stage_actions'], 'override')
    path, source = None, None
    if 'stage_actions' in overrides:
        reg.record_override(P['stage_actions'], '단계별 후속 행동 설정(override: 없음)', False)
    else:
        path = reg.record(P['stage_actions'], '단계별 후속 행동 설정', required=False)
        source = P['stage_actions'].as_posix()
    if path is None:
        path = reg.record(P['stage_actions_template'], '단계별 후속 행동 템플릿', required=False)
        source = P['stage_actions_template'].as_posix()
    if path is None:
        return {'status': stage_actions.STATUS_POLICY, 'source': None, 'errors': [],
                'missing_fields': ['stage_actions'], 'stage_counts': {}, 'undetermined_included': False}
    try:
        doc = yaml.safe_load(path.read_text(encoding='utf-8'))
    except yaml.YAMLError as exc:
        return {'status': stage_actions.STATUS_INVALID, 'source': source, 'errors': [f'YAML_PARSE_ERROR:{exc}'],
                'missing_fields': [], 'stage_counts': {}, 'undetermined_included': False}
    return stage_actions.validate_stage_actions(doc, source)


def _eis_context(reg, root, ctx, overrides):
    frame = _optional_csv(reg, root, overrides, 'eis_panel', 'EIS 지역 맥락(창원시 제조업; 업종 패널 미결합)')
    if frame is None:
        return None
    out = frame[frame['quarter'].astype(str).isin(ctx.quarters)][
        ['quarter', 'changwon_manufacturing', 'eis_manufacturing_yoy_pct']].rename(
        columns={'changwon_manufacturing': 'eis_changwon_manufacturing'}).reset_index(drop=True)
    out['scope_note'] = config.EIS_SCOPE_NOTE
    out['eis_input_sha256'] = reg.sha(config.PATHS['eis_panel'])
    return out


def _optional_csv(reg, root, overrides, key, role):
    if key in overrides:
        value = overrides[key]
        reg.record_override(config.PATHS[key], f'{role}(override)', value is not None)
        return None if value is None else value.copy()
    path = reg.record(config.PATHS[key], role, required=False)
    return inputs.read_csv(path) if path else None


def run(root=None, params_path=None, write=True, run_started_at=None, output_root=None, input_overrides=None):
    """모형 실행.

    output_root : 산출물 저장 루트(기본: root). 입력은 항상 root에서 읽는다.
    input_overrides : 선택 입력 대체(key → DataFrame, dict 또는 None=없음). 키는 config.OPTIONAL_INPUT_KEYS.
    """
    root = Path(root) if root is not None else Path(eda_config.find_root())
    output_root = Path(output_root) if output_root is not None else root
    overrides = dict(input_overrides or {})
    unknown = set(overrides) - set(config.OPTIONAL_INPUT_KEYS)
    if unknown:
        raise ValueError(f'대체할 수 없는 입력 키: {sorted(unknown)}')
    started = run_started_at or datetime.now(timezone.utc)
    reg = inputs.InputRegistry(root)
    P = config.PATHS

    # ------------------------------------------------------------ 기준 패널(03 노트북과 동일 경로·검산)
    reg.record(P['state_panel'], '기준 패널(03 노트북 입력)')
    reg.record(P['total_master'], '산단 총계(eda.panel.load_panels가 함께 읽음, 모형 계산 미사용)')
    state, _ = eda_panel.load_panels(root / 'data' / 'processed')
    ctx = eda_panel.build_context(state)
    state = eda_panel.add_display_columns(state)
    base_verification = eda_panel.verify_panel(state, ctx)
    mfg = eda_panel.manufacturing_totals(state, ctx)
    window_n = len(ctx.quarters)
    input_sha, input_sha_raw = reg.sha(P['state_panel']), reg.sha_raw(P['state_panel'])

    # ------------------------------------------------------------ 파라미터(판정은 등록 이상일 때만)
    reg.record(P['briefing'], '파라미터 브리핑 문서', required=False)
    params_path = Path(params_path) if params_path is not None else root / P['params']
    if params_path.is_file():
        reg.record(_rel(root, params_path), 'ELECTRE 파라미터 파일')
        doc, present, label = params.load_parameter_file(params_path), True, _rel(root, params_path).as_posix()
    else:
        template = reg.record(P['params_template'], 'ELECTRE 파라미터 템플릿(누락 필드 목록용)')
        doc, present, label = params.load_parameter_file(template), False, P['params_template'].as_posix()
    pv = params.validate_parameters(doc, analysis_window_n=window_n, run_started_at=started,
                                    briefing_path=root / P['briefing'], parameter_file_label=label,
                                    present=present)
    run_id = manifest.make_run_id(started, input_sha, pv.parameter_file_sha256_computed)
    prov = manifest.provenance(run_id, started, input_sha, input_sha_raw, pv.parameter_set_id,
                               pv.effective_status, pv.parameter_file_sha256_computed)

    # ------------------------------------------------------------ 입력 패널·PPI 보조자료
    master = _optional_csv(reg, root, overrides, 'industry_master', '가동률 전년동기 출처 확인')
    panel = derive.build_input_panel(state, ctx, mfg, master)
    candidates = _optional_csv(reg, root, overrides, 'ppi_candidates', 'PPI 후보별 분기 YoY 원자료(전 기간, 1순위)')
    sensitivity = _optional_csv(reg, root, overrides, 'ppi_sensitivity', 'PPI 민감도 기존 산출(전 기간 교차검산)')
    resolved = _optional_csv(reg, root, overrides, 'ppi_mapping_resolved', 'PPI 매핑 확정 여부(confirmed 컬럼만 사용)')
    aux_summary = _optional_csv(reg, root, overrides, 'aux_summary', '최신분기 보조요약(교차검산)')
    criteria = _optional_csv(reg, root, overrides, 'ppi_review_criteria', 'PPI 매핑 검토유형 기준')
    reg.record(P['aux_report_html'], '보조분석 보고서(해석·표시 참고, 계산 미사용)', required=False)
    ppi, confirmation = ppi_aux.ppi_fields(panel, candidates, resolved, criteria, aux_summary, ctx.latest,
                                           return_summary=True)
    panel = manifest.with_provenance(pd.concat([panel, ppi], axis=1), prov)
    moves = derive.threshold_state_moves(panel)
    redundancy = diagnostics.criteria_redundancy(panel)
    register = params.parameter_register_frame(doc, pv)

    # ------------------------------------------------------------ 시나리오별 ELECTRE(등록 이상일 때만)
    param_tables, electre_summary = {}, None
    assignments = summary = history = None
    if pv.can_run_scenarios:
        scenarios = [electre.Scenario.from_block(b) for b in pv.scenarios]
        results, evidence, removal, pass_counts, g1_reach, combos, divergence = [], [], [], [], [], [], []
        traces, comparisons, detailed_removal, monotonicity, dominance = [], [], [], [], []
        base_values = base_rule = None
        never = {}
        for s in scenarios:
            res, values = electre.run_scenario(panel, s, window_n, ctx.latest, pv.parameter_set_id)
            evaluation = electre.evaluate(values, s)
            profiles = {'b1': s.b1, 'b2': s.b2}
            rule = pilot.simple_rule(values, profiles)
            if s.scenario_id == '기준':
                base_values, base_rule = values, rule
            results.append(res)
            evidence.append(electre.boundary_evidence(panel, values, s))
            removal.append(electre.criterion_removal_sensitivity(values, s))
            c, ind, cmb, nv = electre.reachability(panel, values, s)
            pass_counts.append(c)
            g1_reach.append(ind)
            combos.append(cmb)
            never[s.scenario_id] = nv
            divergence.append(electre.ppi_stage_divergence(panel, values, s, res['display_class_by_scenario']))
            traces.append(pilot.assignment_trace(panel, values, s, evaluation))
            comparisons.append(pilot.comparison_table(panel, values, s, evaluation, rule))
            detailed_removal.append(pilot.leave_one_out(panel, values, s))
            monotonicity.append(pilot.monotonicity_tests(s))
            dominance.append(pilot.dominance_tests(panel, values, s))
        assignments = pd.concat(results, ignore_index=True)
        comparison_detailed = pd.concat(comparisons, ignore_index=True)
        removal_detailed = pd.concat(detailed_removal, ignore_index=True)
        comparison, comparison_summary = electre.rule_comparison(assignments)
        coalitions, coalition_summary = electre.enumerate_coalitions(scenarios)
        summary = electre.scenario_summary(assignments, pv.approved_scenario_id if pv.can_emit_display_class else None)
        history = electre.recent_stage_history(assignments, ctx.quarters)
        removal_table = pd.concat(removal, ignore_index=True)
        param_tables = {
            'assignments': assignments, 'scenario_summary': summary,
            'boundary_evidence': pd.concat(evidence, ignore_index=True),
            'coalition_table': coalitions, 'simple_rule_comparison': comparison,
            'criterion_removal_sensitivity': removal_table,
            'criteria_activation_crosstab': pd.concat(combos, ignore_index=True),
            'criterion_boundary_pass_counts': pd.concat(pass_counts, ignore_index=True),
            'g1_boundary_reachability': pd.concat(g1_reach, ignore_index=True),
            'ppi_stage_divergence': pd.concat(divergence, ignore_index=True),
            'recent4_stage_history': history,
            'electre_parameter_registry': pilot.parameter_registry(doc, pv),
            'simple_rule_latest': pilot.simple_rule_latest(
                panel, base_values, {'b1': scenarios[0].b1, 'b2': scenarios[0].b2}, ctx.latest),
            'electre_latest_classification': pilot.latest_classification(panel, assignments, ctx.latest),
            'electre_vs_rule_comparison': comparison_detailed,
            'electre_assignment_trace': pd.concat(traces, ignore_index=True),
            'electre_leave_one_criterion_out': removal_detailed,
            'electre_monotonicity_test': pd.concat(monotonicity, ignore_index=True),
            'electre_dominance_test': pd.concat(dominance, ignore_index=True),
            'electre_pilot_scenario_summary': pilot.scenario_summary(assignments, comparison_detailed, ctx.latest),
        }
        electre_summary = {
            'model_title': config.MODEL_TITLE,
            'assignment_method_note': config.MODEL_ASSIGNMENT_METHOD_NOTE,
            'concordance_note': ('q=p=0이고 veto가 없으므로 경계 신뢰도는 concordance와 같고, '
                                 'concordance는 가중 경계통과 합계 Σ w_j·I(g_j >= b_hj)와 정확히 같다.'),
            'scenarios': [s.scenario_id for s in scenarios],
            'class_counts': {sid: {k: int(v) for k, v in g['display_class_by_scenario'].value_counts().items()}
                             for sid, g in assignments.groupby('scenario_id')},
            'production_only_pass_rows': {
                sid: {h: int(g[f'production_only_pass_{h}'].fillna(False).sum()) for h in electre.BOUNDARIES}
                for sid, g in assignments.groupby('scenario_id')},
            'simple_rule_observed': comparison_summary,
            'simple_rule_function_level': coalition_summary,
            'criterion_removal_changed_rows': {
                f'{sid}|{method}|{crit}': int(g.loc[g['changed'], 'n_rows'].sum())
                for (sid, method, crit), g in removal_table.groupby(['scenario_id', 'method', 'removed_criterion'])},
            'reachability_title': config.REACHABILITY_TITLE,
            'g1_never_passed_industries': never,
            'recent_history_title': config.RECENT_HISTORY_TITLE,
        }

    # ------------------------------------------------------------ 카드·맥락
    card_frame = cards.latest_cards(panel, ctx, pv, summary, assignments)
    eis_context = _eis_context(reg, root, ctx, overrides)
    stage_result = _stage_actions(reg, root, overrides)
    cards_md = cards.cards_markdown(card_frame, ctx, prov, pv, eis_context, stage_result['status'],
                                    history, int((~panel['scorable']).sum()))

    # ------------------------------------------------------------ 검증 보고서
    fixture = validation.load_json(root / P['fixture'])
    current_meta = {'input_sha256': input_sha,
                    'preprocess_config_sha256': inputs.sha256_files(root, config.PREPROCESS_DEFINITION_FILES)}
    actuals = validation.regression_actuals(panel, ctx, moves, (fixture or {}).get('expected', {}), redundancy)
    rules = validation.load_json(root / P['wording_rules'])
    texts = {'diagnostic_cards_latest.md': cards_md,
             'diagnostic_cards_latest.csv': card_frame.to_csv(index=False)}
    for key in ('briefing', 'params_template', 'stage_actions_template'):
        if (root / P[key]).is_file():
            texts[P[key].as_posix()] = (root / P[key]).read_text(encoding='utf-8')

    criterion_columns_used = [G['g1'], G['g2'], G['g3']] + list(config.G4_DELTA_COLUMNS)
    blocked_outputs = [] if pv.can_run_scenarios else [
        {'path': p.as_posix(), 'reason': pv.run_mode} for p in config.PARAMETER_OUTPUTS.values()]
    policy = {
        'parameters': pv.missing_parameter_fields,
        'registration': pv.missing_registration_fields,
        'approval': pv.missing_approval_fields,
        'stage_actions': stage_result,
        'decisions': ['세 시나리오별 weights', 'b1·b2', 'lambda', 'delta_emp', 'require_employment_evidence',
                      '단계별 담당 역할', '처리기한', '공식 승인 여부', '단순 개수규칙 최종 채택 여부'],
    }
    report = {
        'run_id': run_id,
        'model_spec_version': config.MODEL_SPEC_VERSION, 'model_title': config.MODEL_TITLE,
        'model_assignment_method_note': config.MODEL_ASSIGNMENT_METHOD_NOTE,
        'run_started_at': started.isoformat(), **inputs.git_state(root),
        'run_mode': pv.run_mode,
        'model_status': 'BLOCKED_MISSING_PARAMETERS' if pv.run_mode == config.RUN_BLOCKED_MISSING else pv.run_mode,
        'provenance': prov,
        'inputs': reg.records,
        'base_panel_verification': base_verification,
        'parameter_validation': pv.to_dict(),
        'stage_actions': stage_result,
        'panel_validation': {
            'V1': validation.check_v1(panel, ctx), 'V2': validation.check_v2(panel),
            'V3': validation.check_v3(panel), 'V4': validation.check_v4(panel),
            'V5': validation.check_v5(moves), 'V6': validation.check_v6(panel, assignments),
        },
        'structural_observations': validation.structural_observations(panel),
        'criteria_redundancy': {
            'table': config.OUTPUTS['criteria_redundancy'].as_posix(),
            'note': config.REDUNDANCY_NOTE,
            'g4_column_used': diagnostics.REDUNDANCY_COLUMNS['g4'],
            'rows': redundancy[['scope', 'criterion_x', 'criterion_y', 'method', 'correlation',
                                'n_rows_used', 'n_rows_excluded_missing', 'n_rows_excluded_by_scope']]
            .to_dict('records'),
        },
        'crosschecks': {
            'ppi_ratio_formula': (ppi_aux.formula_check(panel, candidates) if candidates is not None
                                  else {'status': 'NOT_AVAILABLE'}),
            'ppi_sensitivity_full_period': (ppi_aux.crosscheck_ppi_sensitivity(panel, sensitivity)
                                            if sensitivity is not None else {'status': 'NOT_AVAILABLE'}),
            'aux_summary_latest': ppi_aux.crosscheck_aux_summary(panel, aux_summary, ctx.latest),
            'ppi_mapping_confirmation': confirmation,
            'ppi_mapping_all_unconfirmed': {
                'status_counts_by_industry': confirmation['status_counts_by_industry'],
                'passed': bool(panel['ppi_mapping_confirmation_status'].eq('NOT_CONFIRMED').all())},
            'residual_category_not_comparable': {
                'passed': bool(panel.loc[panel['residual_category'], 'ppi_direction_status']
                               .eq('NOT_COMPARABLE').all())},
            'eis_isolation': validation.eis_isolation_check(panel),
            'firm_count_isolation': validation.firm_count_isolation(panel.columns, criterion_columns_used),
        },
        'ppi_latest': ppi_aux.latest_ppi_table(panel, ctx.latest).to_dict('records'),
        'electre': electre_summary,
        'wording_audit': validation.wording_audit(texts, rules),
        'fixture_check': validation.compare_to_fixture(actuals, fixture, current_meta),
        'outputs_written': [], 'outputs_blocked': blocked_outputs,
        'stale_parameter_outputs_present': [
            {'canonical_path': p.as_posix(), 'status': manifest.STATUS_STALE}
            for key, p in config.PARAMETER_OUTPUTS.items()
            if key not in param_tables and (output_root / p).exists()],
        'policy_decisions_required': policy,
    }

    # ------------------------------------------------------------ 표(모든 CSV에 provenance)
    ident = ['industry', 'quarter']
    g4_cols = [c for c in panel.columns if c.startswith('g4_delta')]
    tables = {
        'input_panel': panel,
        'eligibility_audit': panel[ident + ['state', G['g1'], G['g2'], G['g3'], 'g4_delta00',
                                            'core_data_status', 'scorable', 'unscorable_reason',
                                            'unscorable_root_cause', 'unscorable_propagation',
                                            'q1_routing_status', 'threshold_flag', 'residual_category',
                                            'routeability_status']].assign(
            g1_available=panel[G['g1']].notna(), g2_available=panel[G['g2']].notna(),
            g3_available=panel[G['g3']].notna(), g4_available=panel['g4_delta00'].notna()),
        'criteria_redundancy': redundancy,
        'g4_delta_sensitivity': panel[ident + ['employment_yoy'] + g4_cols].assign(
            g4_values_differ_by_delta=panel[list(config.G4_DELTA_COLUMNS)].nunique(axis=1).gt(1)),
        'qoq_yoy_comparison': panel[ident + ['employment', 'employment_lag4', 'emp_delta', 'employment_yoy',
                                             'emp_qoq_delta', 'qoq_recovery_while_yoy_below', 'g4_delta00']],
        'firm_count_context': panel[ident + ['firms_op', 'firms_op_lag4', 'firms_in', 'firm_count_delta_qoq',
                                             'firm_count_delta_yoy', 'firm_count_changed_yoy', 'emp_per_firm',
                                             'small_firm_count_flag', 'small_firm_caution', 'residual_category']],
        'parameter_register': register,
        'cards_csv': card_frame,
    }
    if eis_context is not None:
        tables['eis_regional_context'] = eis_context
    tables.update(param_tables)
    tables = {key: manifest.with_provenance(frame, prov) for key, frame in tables.items()}

    run_manifest = None
    if write:
        report['run_finished_at'] = datetime.now(timezone.utc).isoformat()
        report = validation.jsonable(report)
        run_meta = {'run_started_at': prov['run_started_at'], 'run_finished_at': report['run_finished_at'],
                    'run_mode': pv.run_mode, 'effective_parameter_status': pv.effective_status,
                    'parameter_set_id': pv.parameter_set_id, 'input_sha256': input_sha,
                    'input_sha256_raw_bytes': input_sha_raw, 'model_spec_version': config.MODEL_SPEC_VERSION}
        run_manifest = manifest.write_run_outputs(
            output_root, run_id, tables, {**config.OUTPUTS, **config.PARAMETER_OUTPUTS},
            {'cards_md': (config.OUTPUTS['cards_md'], cards_md)}, report, run_meta)
        if pv.can_run_scenarios:
            pilot.write_figures(output_root, tables['electre_latest_classification'],
                                tables['simple_rule_latest'], tables['electre_leave_one_criterion_out'])

    return {'root': root, 'output_root': output_root, 'run_id': run_id, 'provenance': prov, 'ctx': ctx,
            'panel': panel, 'moves': moves, 'parameter_validation': pv, 'register': register,
            'redundancy': redundancy, 'stage_actions': stage_result,
            'assignments': assignments, 'scenario_summary': summary, 'history': history,
            'param_tables': param_tables, 'cards': card_frame, 'cards_md': cards_md,
            'eis_context': eis_context, 'report': validation.jsonable(report), 'tables': tables,
            'actuals': actuals, 'manifest': run_manifest}


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, ValueError):
        pass
    parser = argparse.ArgumentParser(description='창원국가산단 전환진단 모형 실행')
    parser.add_argument('--params', default=None, help='파라미터 YAML 경로(기본: config/electre_tri_b_params.yaml)')
    parser.add_argument('--no-write', action='store_true', help='산출물을 저장하지 않음')
    parser.add_argument('--print-parameter-hashes', default=None, metavar='PARAMS_YAML',
                        help='파라미터 본문 해시와 브리핑 문서 해시를 출력하고 종료')
    args = parser.parse_args(argv)
    if args.print_parameter_hashes:
        root = Path(eda_config.find_root())
        doc = params.load_parameter_file(args.print_parameter_hashes)
        print(f'parameter_file_sha256: {params.parameter_payload_sha256(doc)}')
        print(f"briefing_doc_sha256:   {inputs.sha256_text_file(root / config.PATHS['briefing'])}")
        return 0
    bundle = run(params_path=args.params, write=not args.no_write)
    rep = bundle['report']
    print(f"run_id: {rep['run_id']}")
    print(f"run_mode: {rep['run_mode']}")
    for key, v in rep['panel_validation'].items():
        print(f"{key}: passed={v['passed']} — {v['label']}")
    print(f"fixture_check: {rep['fixture_check']['status']}")
    print(f"wording_audit: {rep['wording_audit']['status']} passed={rep['wording_audit']['passed']}")
    print(f"stage_actions: {rep['stage_actions']['status']}")
    print(f"missing parameter fields: {len(rep['parameter_validation']['missing_parameter_fields'])}")
    for path in rep['outputs_written']:
        print(f'written: {path}')
    for item in rep['outputs_blocked']:
        print(f"blocked: {item['path']} ({item['reason']})")
    for item in rep['stale_parameter_outputs_present']:
        print(f"stale (not current): {item['canonical_path']}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
