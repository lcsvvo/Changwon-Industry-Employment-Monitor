# -*- coding: utf-8 -*-
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from model import qp_calibration  # noqa: E402


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--no-write',action='store_true')
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    result=qp_calibration.run(root,write=not args.no_write)
    print('run_id:',result['run_id'])
    print('selected_on_calibration:',result['selected'])
    print('final_decision:',result['final_decision'])
    return 0


if __name__=='__main__':
    raise SystemExit(main())
