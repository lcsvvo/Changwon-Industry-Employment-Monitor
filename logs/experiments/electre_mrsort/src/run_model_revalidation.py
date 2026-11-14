# -*- coding: utf-8 -*-
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from model import revalidation  # noqa: E402
from model import revalidation_phase3  # noqa: E402
from model import revalidation_phase4  # noqa: E402
from model import revalidation_phase5  # noqa: E402
from model import revalidation_phase6  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--phase', type=int, required=True)
    parser.add_argument('--no-write', action='store_true')
    parser.add_argument('--no-figures', action='store_true')
    parser.add_argument('--before-run-id', default=None,
                        help='(phase 2) outputs/revalidation_runs/<run_id>/의 보존된 이전 실행과 대조해 '
                             'electre_parameter_space_summary.csv에 개정 전후 비교 행을 덧붙인다.')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]

    if args.phase == 2:
        result = revalidation.run_phase2(root, write=not args.no_write, before_run_id=args.before_run_id)
        print('run_id:', result['run_id'])
        print('prereg_status:', result['provenance']['prereg_status'])
        print('prereg_sha256:', result['provenance']['prereg_sha256'])
        if result['written']:
            for name, info in result['written'].items():
                print(f"  {name}: {info['n_rows']}행 -> {info['canonical']}")
        if not args.no_write and not args.no_figures:
            figs = revalidation.write_figures(root, result)
            print('figures:', figs)
    elif args.phase == 3:
        result = revalidation_phase3.decision_and_outputs(root, write=not args.no_write)
        print('run_id:', result['run_id'])
        print('prereg_status:', result['provenance']['prereg_status'])
        print('prereg_amendment_ids:', result['provenance']['prereg_amendment_ids'])
        if result['written']:
            for name, path in result['written'].items():
                print(f'  {name}: {len(result["tables"][name])}행 -> {path}')
        if not args.no_write and not args.no_figures:
            revalidation_phase3.write_figures(root, result)
            print('figures written.')
    elif args.phase == 4:
        try:
            result = revalidation_phase4.run_phase4(root, write=not args.no_write)
        except revalidation_phase4.Phase4GateError as e:
            print(str(e))
            return 0
        print('run_id:', result['run_id'])
        print('selected_veto_id:', result['selected_veto_id'])
        print('v1.2 candidates written to:', result['v12_candidates_path'])
        if result['written']:
            for name, path in result['written'].items():
                print(f'  {name}: {len(result["tables"][name])}행 -> {path}')
    elif args.phase == 5:
        try:
            result = revalidation_phase5.run_phase5(root, write=not args.no_write)
        except revalidation_phase5.Phase5GateError as e:
            print(str(e))
            return 0
        print('run_id:', result['run_id'])
        print('cards:', result['cards_path'])
        print('reporting_rules:', result['reporting_rules_path'])
        if result['written']:
            for name, path in result['written'].items():
                print(f'  {name}: {len(result["tables"][name])}행 -> {path}')
    elif args.phase == 6:
        try:
            result = revalidation_phase6.run_phase6(root, write=not args.no_write)
        except revalidation_phase6.Phase6GateError as e:
            print(str(e))
            return 0
        print('run_id:', result['run_id'])
        print('history:', result['history_path'])
        print('reporting_rules:', result['reporting_rules_path'])
        print('readme:', result['readme_path'])
        if result['written']:
            for name, path in result['written'].items():
                print(f'  {name}: {len(result["tables"][name])}행 -> {path}')
    else:
        raise NotImplementedError(f'--phase {args.phase}는 아직 구현되지 않았습니다(현재 phase 2·3·4·5·6만 지원).')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
