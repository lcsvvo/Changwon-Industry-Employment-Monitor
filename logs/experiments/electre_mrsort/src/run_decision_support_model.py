# -*- coding: utf-8 -*-
"""창원국가산단 산업·고용 전환진단 모형 실행 스크립트.

실행
    python src/run_decision_support_model.py
    python src/run_decision_support_model.py --params config/electre_tri_b_params.yaml
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from model.pipeline import main  # noqa: E402

if __name__ == '__main__':
    raise SystemExit(main())
