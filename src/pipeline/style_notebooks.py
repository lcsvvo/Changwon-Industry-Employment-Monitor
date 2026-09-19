"""Apply the repository notebook style contract without changing calculations."""
from __future__ import annotations

import re
from pathlib import Path

import nbformat


ROOT = Path(__file__).resolve().parents[2]
NB_DIR = ROOT / "notebooks"

SPECS = {
    "00_data_preparation.ipynb": {
        "step": 0,
        "title": "데이터 준비와 품질검증",
        "takeaway": "원자료를 수정하지 않고 KICOX 마스터와 검증 패널을 재현한다.",
        "question": "동일한 원자료에서 본분석 입력을 누락·중복 없이 다시 만들 수 있는가?",
        "inputs": [("원자료", "config.RAW_DIR"), ("경로 설정", "config.PROCESSED_DIR")],
        "outputs": [("KICOX 업종 마스터", "config.KICOX_INDUSTRY_PATH"), ("상태 패널", "config.STATE_PANEL_PATH")],
        "flow": "원자료 확인 → 마스터 구축 → 분석기간 확정 → 상태·검증 패널 생성 → QA",
        "observation": "행 수, 기간, 중복, 결측 및 원자료 불변 여부를 출력으로 확인한다.",
        "interpretation": "이 단계의 산출물은 뒤 단계의 공통 입력이며 별도의 정책 판정을 만들지 않는다.",
        "limitations": "외부 원천의 개정·공표 지연은 이 저장소 내부 QA만으로 해소되지 않는다.",
    },
    "01_core_analysis.ipynb": {
        "step": 1,
        "title": "핵심 산업·고용 상태 분석",
        "takeaway": "생산과 고용의 상태·규모·시간 구조를 동일한 180행 패널에서 읽는다.",
        "question": "업종별 생산·고용 변화는 어떤 상태와 전환 패턴을 보이는가?",
        "inputs": [("본분석 상태 패널", "config.STATE_PANEL_PATH")],
        "outputs": [("핵심 표", "config.CORE_TABLE_DIR"), ("핵심 그림", "config.CORE_FIGURE_DIR")],
        "flow": "공통 패널 로드 → 상태(Q1) → 규모(Q2) → 전환(Q3) → 핵심 관찰 정리",
        "observation": "상태 분포, 고용 증감 규모, 지속기간과 전환을 각각 분리해 확인한다.",
        "interpretation": "핵심 분석은 업종 수준의 관찰 신호이며 기업 원인이나 지원 필요성을 확정하지 않는다.",
        "limitations": "명목 생산액, 분기 자료, 업종 집계 단위의 제약이 있다.",
    },
    "05_final_results.ipynb": {
        "step": 5,
        "title": "최종 결과와 지원연계",
        "takeaway": "핵심 신호부터 현장 확인 질문과 기존 기관 인계까지 한 흐름으로 제시한다.",
        "question": "어느 업종을 먼저 확인하고 무엇을 확인한 뒤 어디로 인계할 것인가?",
        "inputs": [("분류 결과", "config.TRIAGE_PANEL_PATH"), ("설명 근거", "config.HANDOFF_TRACE_PATH")],
        "outputs": [("인계 카드", "config.HANDOFF_CARD_PATH"), ("보고 자산", "config.REPORT_ASSET_DIR")],
        "flow": "핵심 신호 → 1차 분류 → 선택적 재검토 → 외부 근거 → 설명·인계",
        "observation": "최신 분류와 근거 추적표를 함께 표시해 각 카드의 출처를 확인한다.",
        "interpretation": "우선순위는 행정적 확정이 아니라 기업·현장 확인 순서를 표준화하는 지원 정보다.",
        "limitations": "실제 지원 가능성, 담당기관, 기업 상황은 인계 시점에 다시 확인해야 한다.",
    },
}

READ_NOTEBOOKS = {
    "02_triage.ipynb": {
        "step": 2,
        "title": "규칙 기반 1차 분류",
        "takeaway": "설명 가능한 E/R/A/P 규칙으로 180개 업종×분기를 관찰·추가확인·우선점검으로 나눈다.",
        "question": "핵심 신호만으로 어떤 관측을 먼저 확인해야 하는가?",
        "inputs": [("핵심 패널", "config.CORE_TABLE_DIR")],
        "outputs": [("전체 분류", "config.TRIAGE_PANEL_PATH"), ("최신 분류", "config.TRIAGE_LATEST_PATH")],
        "flow": "핵심 지표 → E/R/A/P → 규칙 판정 → 분포·최신 결과 점검",
        "path": "TRIAGE_PANEL_PATH",
        "preview": ["quarter", "industry", "stage", "E", "R", "A", "P"],
        "observation": "단계별 건수와 최신분기 업종별 판정을 확인한다.",
        "interpretation": "규칙 기반 분류는 재현 가능한 1차 스크리닝이며 원인 판정이 아니다.",
        "limitations": "임계값 인접 관측과 상충 신호는 다음 단계의 선택적 검토가 필요하다.",
    },
    "03_selective_electre_smaa.ipynb": {
        "step": 3,
        "title": "선택적 ELECTRE·SMAA 재검토",
        "takeaway": "1차 분류의 경계·상충 사례 35건에만 다기준 불확실성 검토를 적용한다.",
        "question": "1차 규칙만으로 단정하기 어려운 사례의 우선순위가 가중치 불확실성에도 유지되는가?",
        "inputs": [("추가확인 사례", "config.ELECTRE_REVIEW_PATH")],
        "outputs": [("재검토 결과", "config.ELECTRE_REVIEW_PATH"), ("분포 요약", "config.ELECTRE_SUMMARY_PATH")],
        "flow": "35건 선택 → ELECTRE 비보상 비교 → SMAA 가중치 표본 → 안정성 요약",
        "path": "ELECTRE_REVIEW_PATH",
        "preview": ["quarter", "industry", "stage", "electre_class", "smaa_top_rank_acceptability"],
        "observation": "선정 35건과 재검토 등급 분포를 확인한다.",
        "interpretation": "다기준 결과는 1차 규칙을 대체하지 않고 경계 사례의 추가 설명만 제공한다.",
        "limitations": "가중치·임계값 사양과 표본 수에 따라 안정성 지표가 달라질 수 있다.",
    },
    "04_external_evidence.ipynb": {
        "step": 4,
        "title": "외부 근거와 데이터 역할",
        "takeaway": "외부 자료는 핵심 판정을 덮어쓰지 않고 해석·현장 확인 질문을 보강한다.",
        "question": "각 외부 자료는 핵심·보조·맥락 중 어떤 역할로 사용할 수 있는가?",
        "inputs": [("외부 근거 요약", "config.EVIDENCE_SUMMARY_PATH")],
        "outputs": [("자료 역할표", "config.DATA_ROLE_PATH"), ("외부 근거 패키지", "config.EVIDENCE_DIR")],
        "flow": "원천별 패널 → 범위·품질 확인 → 역할 분류 → 현장 확인 근거 연결",
        "path": "EVIDENCE_SUMMARY_PATH",
        "preview": [],
        "observation": "자료별 기간, 공간·산업 단위, 품질 상태와 최종 역할을 확인한다.",
        "interpretation": "교역·물가·전력·고용보험 자료는 서로 다른 현상을 측정하므로 동일 신호로 합산하지 않는다.",
        "limitations": "시차, 분류 매핑, 비식별 및 공간 proxy 제약이 자료별로 다르다.",
    },
}


def table(rows: list[tuple[str, str]]) -> str:
    return "\n".join(["| 구분 | 설정 변수 |", "|---|---|"] + [f"| {label} | `{value}` |" for label, value in rows])


def overview(spec: dict) -> str:
    return (
        f"# STEP{spec['step']}. {spec['title']}\n\n"
        f"> **Takeaway.** {spec['takeaway']}\n\n"
        f"## 분석 질문\n\n{spec['question']}\n\n"
        f"## 입력\n\n{table(spec['inputs'])}\n\n"
        f"## 출력\n\n{table(spec['outputs'])}"
    )


def flow_cell(spec: dict) -> str:
    return f"## 전체 흐름\n\n`{spec['flow']}`"


def closing(spec: dict) -> str:
    return (
        "## 관찰\n\n" + spec["observation"] + "\n\n"
        "## 해석\n\n" + spec["interpretation"] + "\n\n"
        "## 한계\n\n" + spec["limitations"] + "\n\n"
        "## Takeaway\n\n" + spec["takeaway"]
    )


def demote_h1(source: str) -> str:
    return re.sub(r"(?m)^# (?!#)", "## ", source)


def style_existing(path: Path, spec: dict) -> None:
    nb = nbformat.read(path, as_version=4)
    if nb.cells and nb.cells[0].cell_type == "markdown" and nb.cells[0].source.startswith(f"# STEP{spec['step']}."):
        # The repository stores the styled notebooks. Re-running this helper
        # must not prepend a second overview/flow or append another takeaway.
        return
    for cell in nb.cells:
        if cell.cell_type == "markdown":
            cell.source = demote_h1(cell.source)
    nb.cells = [nbformat.v4.new_markdown_cell(overview(spec)), nbformat.v4.new_markdown_cell(flow_cell(spec)), *nb.cells]
    nb.cells.append(nbformat.v4.new_markdown_cell(closing(spec)))
    nbformat.write(nb, path)


def create_reader(path: Path, spec: dict) -> None:
    if path.exists():
        existing = nbformat.read(path, as_version=4)
        if existing.cells and existing.cells[0].cell_type == "markdown" and existing.cells[0].source.startswith(f"# STEP{spec['step']}."):
            return
    setup = """from pathlib import Path
import sys
import pandas as pd
from IPython.display import display

ROOT = next(p for p in [Path.cwd(), *Path.cwd().parents] if (p / 'src').is_dir())
sys.path.insert(0, str(ROOT / 'src'))
from utils import notebook_config as config
"""
    data_code = f"""data = pd.read_csv(config.{spec['path']}, encoding='utf-8-sig')
print(f'rows={{len(data):,}} | columns={{len(data.columns):,}}')
if 'stage' in data.columns:
    display(data['stage'].value_counts(dropna=False).rename_axis('stage').to_frame('rows'))
preview = {spec['preview']!r}
display(data[[c for c in preview if c in data.columns]].head(20) if preview else data.head(20))
"""
    nb = nbformat.v4.new_notebook(
        cells=[
            nbformat.v4.new_markdown_cell(overview(spec)),
            nbformat.v4.new_markdown_cell(flow_cell(spec)),
            nbformat.v4.new_markdown_cell("## 설정과 입력 로드\n\n경로는 사용자 PC의 절대경로가 아니라 `config.*` 변수에서 가져온다."),
            nbformat.v4.new_code_cell(setup),
            nbformat.v4.new_markdown_cell("## 관찰 결과\n\n행 수와 주요 분포를 먼저 확인한다."),
            nbformat.v4.new_code_cell(data_code),
            nbformat.v4.new_markdown_cell(closing(spec)),
        ],
        metadata={
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3"},
        },
    )
    nbformat.write(nb, path)


def main() -> None:
    for name, spec in SPECS.items():
        style_existing(NB_DIR / name, spec)
    for name, spec in READ_NOTEBOOKS.items():
        create_reader(NB_DIR / name, spec)
    for path in sorted(NB_DIR.glob("*.ipynb")):
        nb = nbformat.read(path, as_version=4)
        h1 = sum(
            1 for cell in nb.cells if cell.cell_type == "markdown"
            for line in cell.source.splitlines() if re.match(r"^# (?!#)", line)
        )
        if h1 != 1:
            raise RuntimeError(f"{path.name}: expected one H1, found {h1}")
        print(f"[ok] {path.name}: cells={len(nb.cells)} H1={h1}")


if __name__ == "__main__":
    main()
