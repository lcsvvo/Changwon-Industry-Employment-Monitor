"""Run the adopted final model from local raw data through final deliverables."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def run(*args: str) -> None:
    command = [sys.executable, *args]
    print("[run] " + " ".join(args), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-tests", action="store_true")
    parser.add_argument("--skip-notebook", action="store_true")
    args = parser.parse_args()

    steps = [
        ("src/core/build_changwon_master.py", "--no-compare"),
        ("src/core/build_kicox_analysis_panel.py",),
        ("src/evidence/build_validation_panels.py",),
        ("src/evidence/build_ppi_industry_panel.py",),
        ("src/triage/run_triage.py",),
        ("src/evidence/build_industry_crosswalk.py",),
        ("src/evidence/build_hs6_universe.py",),
        ("src/evidence/build_context_layer.py",),
        ("src/evidence/build_kepco_legal_dong_panel.py",),
        ("src/pipeline/build_final_outputs.py",),
    ]
    for step in steps:
        run(*step)

    if not args.skip_tests:
        run("-m", "pytest", "-q")
    if not args.skip_notebook:
        run("src/pipeline/execute_final_notebook.py")


if __name__ == "__main__":
    main()
