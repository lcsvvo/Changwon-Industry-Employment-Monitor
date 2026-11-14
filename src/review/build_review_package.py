# -*- coding: utf-8 -*-
"""저장 출력 확인용 교수 검토 패키지를 최소 구성으로 만든다."""
from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "outputs/final_model/07_review_package"

# 최종 보고서는 패키지 안에서 직접 편집한 문서라 복사하지 않고 있는지만 확인한다(덮어쓰기 방지).
EDITED_FILES = ("01_분석보고서/창원국가산단_산업고용전환진단_분석보고서.docx",)
FILES = {
    "02_분석노트북/07_professor_review_master.ipynb": "notebooks/07_professor_review_master.ipynb",
    "03_핵심_보조자료/triage_panel.csv": "outputs/final_model/02_triage/tables/triage_panel.csv",
    "03_핵심_보조자료/qa_level_shift_cases.csv":
        "outputs/final_model/06_report_assets/professor_feedback/tables/qa_level_shift_cases.csv",
    "03_핵심_보조자료/wood_paper_source_audit.csv":
        "outputs/final_model/06_report_assets/professor_feedback/tables/wood_paper_source_audit.csv",
    "03_핵심_보조자료/wood_paper_boundary_margin.csv":
        "outputs/final_model/06_report_assets/professor_feedback/tables/wood_paper_boundary_margin.csv",
    "03_핵심_보조자료/machine_yoy_qoq_interpretation.csv":
        "outputs/final_model/06_report_assets/professor_feedback/tables/machine_yoy_qoq_interpretation.csv",
    "03_핵심_보조자료/wood_paper_level_shift_decomposition.csv":
        "outputs/final_model/06_report_assets/professor_feedback/tables/wood_paper_level_shift_decomposition.csv",
    "03_핵심_보조자료/priority_base_peak_check.csv":
        "outputs/final_model/06_report_assets/professor_feedback/tables/priority_base_peak_check.csv",
    "03_핵심_보조자료/ratio_boundary_headcount_summary.csv":
        "outputs/final_model/06_report_assets/professor_feedback/tables/ratio_boundary_headcount_summary.csv",
    "03_핵심_보조자료/cci_concurrent_check.csv":
        "outputs/final_model/06_report_assets/professor_feedback/tables/cci_concurrent_check.csv",
    "03_핵심_보조자료/mean_reversion_by_stage.csv":
        "outputs/final_model/06_report_assets/professor_feedback/tables/mean_reversion_by_stage.csv",
    "03_핵심_보조자료/press_concurrent_cases.csv":
        "outputs/final_model/06_report_assets/professor_feedback/tables/press_concurrent_cases.csv",
    "03_핵심_보조자료/signal_followup_summary.csv":
        "outputs/final_model/06_report_assets/professor_feedback/tables/signal_followup_summary.csv",
    "03_핵심_보조자료/validation_model_comparison.csv":
        "outputs/final_model/06_report_assets/professor_feedback/tables/validation_model_comparison.csv",
    "03_핵심_보조자료/external_contemporaneous_cases.csv":
        "outputs/final_model/06_report_assets/professor_feedback/tables/external_contemporaneous_cases.csv",
    "03_핵심_보조자료/handoff_cards_latest.csv":
        "outputs/final_model/05_handoff/tables/handoff_cards_latest.csv",
    "03_핵심_보조자료/feedback_implementation_log.md":
        "outputs/final_model/06_report_assets/professor_feedback/feedback_implementation_log.md",
}


def overview() -> str:
    return """창원국가산단 산업·고용 전환진단 교수 검토 패키지

[패키지 성격]
이 폴더는 저장된 최종 결과를 확인하기 위한 검토용 패키지입니다.
전체 재실행용 코드와 원자료 패키지가 아닙니다. 전체 재현성 기준은 아래 GitHub 저장소입니다.
https://github.com/lcsvvo/Changwon-Industry-Employment-Monitor

[실제 구성]
00_개요.txt
01_분석보고서/
  창원국가산단_산업고용전환진단_분석보고서.docx
02_분석노트북/
  07_professor_review_master.ipynb
03_핵심_보조자료/
  triage_panel.csv
  qa_level_shift_cases.csv
  wood_paper_source_audit.csv
  wood_paper_boundary_margin.csv
  machine_yoy_qoq_interpretation.csv
  wood_paper_level_shift_decomposition.csv
  priority_base_peak_check.csv
  ratio_boundary_headcount_summary.csv
  cci_concurrent_check.csv
  mean_reversion_by_stage.csv
  press_concurrent_cases.csv
  signal_followup_summary.csv
  validation_model_comparison.csv
  external_contemporaneous_cases.csv
  handoff_cards_latest.csv
  feedback_implementation_log.md

[문서 구성 결정]
분석방법론 요약과 분석결과 상세요약은 별도 중복 문서로 추가하지 않고,
01_분석보고서와 02_분석노트북에 통합했습니다. 보조 CSV는 수치 검증과 인계에 필요한 항목만 유지했습니다.

[재실행 안내]
노트북은 실행 결과가 저장돼 있어 이 패키지만으로 열람할 수 있습니다. src 폴더가 없는 곳에서 첫 코드 셀을
실행하면 재실행 위치를 안내하고 멈춥니다. 재실행은 저장소를 내려받아 루트에서 Python 3.11+로 다음을 실행합니다.
  python src/pipeline/run_final_pipeline.py
  python src/review/professor_feedback.py
  python src/review/update_professor_notebook.py
  python src/review/feedback_audit.py
  python src/review/build_review_package.py
분석보고서(docx)는 편집 문서이며 위 명령으로 다시 생성하지 않습니다. 보고서 수치는 03_핵심_보조자료의 표와 대조할 수 있습니다.

Streamlit:
  streamlit run src/app/main.py

최종 노트북:
  notebooks/07_professor_review_master.ipynb

[해석 원칙]
Triage가 주모형이며 ELECTRE TRI-B/SMAA-TRI는 추가확인군의 보조 재검토입니다.
외부자료와 고용24는 검증·맥락 자료이며 Triage 단계를 재계산하지 않습니다.
"""


def main() -> None:
    PACKAGE.mkdir(parents=True, exist_ok=True)
    expected = {"00_개요.txt", *EDITED_FILES, *FILES.keys()}
    for edited in EDITED_FILES:
        if not (PACKAGE / edited).exists():
            raise FileNotFoundError(PACKAGE / edited)
    existing = {str(p.relative_to(PACKAGE)).replace("\\", "/") for p in PACKAGE.rglob("*") if p.is_file()}
    unexpected = existing - expected
    if unexpected:
        raise RuntimeError(f"패키지에 예상하지 않은 파일이 있어 보존을 위해 중단: {sorted(unexpected)}")
    (PACKAGE / "00_개요.txt").write_text(overview(), encoding="utf-8-sig")
    for destination, source in FILES.items():
        src, dst = ROOT / source, PACKAGE / destination
        if not src.exists():
            raise FileNotFoundError(src)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    actual = {str(p.relative_to(PACKAGE)).replace("\\", "/") for p in PACKAGE.rglob("*") if p.is_file()}
    if actual != expected:
        raise RuntimeError(f"개요와 실제 파일 불일치: missing={expected-actual}, extra={actual-expected}")
    print(f"review package ready: {PACKAGE.relative_to(ROOT)} ({len(actual)} files)")


if __name__ == "__main__":
    main()
