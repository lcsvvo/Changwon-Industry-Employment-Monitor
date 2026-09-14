"""
Q1 — 창원국가산단 업종별 생산·고용 국면(S1~S4) 분석 및 시각화

이 스크립트는 changwon_state_panel.csv(및 관련 검증 패널)를 입력으로 받아
Q1 심화분석 리포트(outputs/report/q1_state_deep_dive.html)에 들어가는
통계 표와 차트(PNG)를 재생성한다.

입력 파일:
    - data/processed/kicox/changwon_state_panel.csv           : 본분석 패널 (2022Q1~2026Q2, 10업종x18분기)
    - data/processed/kicox/changwon_state_reference_panel.csv : 참고기간 확장 패널 (2018Q1~2026Q2)
    - data/processed/kicox/quality_report.json                : 파이프라인 정합성 체크 결과
    - logs/preprocessing/exclusion_or_review_log.csv          : QA 검증/리뷰 플래그 로그

출력:
    - outputs/figures/ 에 PNG 3종 (heatmap_q1, scatter_latest, sensitivity_chart)
    - 콘솔에 주요 통계 표 출력 (업종별 국면비중, 분기별 국면 카운트 등)

주의:
    국면 전환행렬은 Q3(src/q3_state_analysis.py)의 산출물이다. 이 스크립트는
    전환을 계산하지 않는다 — 같은 대상을 두 정의로 이중 산출하지 않기 위함이다.

사용법:
    python src/q1_state_analysis.py
"""

import json
import math
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from matplotlib.patches import Rectangle, Patch
import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# 경로 설정 — 팀 폴더 구조(PROJECT_STRUCTURE.md) 기준
# ---------------------------------------------------------------------------
ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data" / "processed" / "kicox"
LOG_DIR = ROOT_DIR / "logs" / "preprocessing"
FIG_DIR = ROOT_DIR / "outputs" / "figures"
FIG_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(ROOT_DIR / "src"))
from eda import config  # noqa: E402  팀 공통 설정

# 국면 색상 — 팀 공통 팔레트(src/eda/config.py STATE_COLORS)를 그대로 쓴다. 여기서 색을 새로 정의하지 않는다.
COLOR = config.STATE_COLORS

# 업종 순서는 하드코딩하지 않고 industry_order()로 최신분기 고용 내림차순을 계산한다.

# 한글 폰트 — OS별로 설치 폰트가 다르므로 사용 가능한 첫 폰트를 쓴다.
# 후보 순서는 src/eda/config.py의 FONT_CANDIDATES와 동일하게 유지한다.
# 주의: FontProperties(fname=...)는 생성 시점에 파일 존재를 확인하지 않고
#       그리기 시점에 FileNotFoundError를 내므로 try/except로는 막을 수 없다.
_FONT_PATH = Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")
_FONT_BOLD_PATH = Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc")
FONT_CANDIDATES = ["Malgun Gothic", "AppleGothic", "NanumGothic",
                   "Noto Sans CJK KR", "Noto Sans CJK JP", "DejaVu Sans"]

if _FONT_PATH.is_file():
    FP = fm.FontProperties(fname=str(_FONT_PATH))
    FP_BOLD = fm.FontProperties(
        fname=str(_FONT_BOLD_PATH if _FONT_BOLD_PATH.is_file() else _FONT_PATH))
else:
    _installed = {f.name for f in fm.fontManager.ttflist}
    _family = next((c for c in FONT_CANDIDATES if c in _installed), None)
    if _family:
        plt.rcParams["font.family"] = [_family, "sans-serif"]
        FP = fm.FontProperties(family=_family)
        FP_BOLD = fm.FontProperties(family=_family, weight="bold")
    else:
        FP = fm.FontProperties()
        FP_BOLD = fm.FontProperties(weight="bold")
plt.rcParams["axes.unicode_minus"] = False


# ---------------------------------------------------------------------------
# 데이터 로드
# ---------------------------------------------------------------------------
def load_state_panel() -> pd.DataFrame:
    df = pd.read_csv(DATA_DIR / "changwon_state_panel.csv")
    return df


def load_reference_panel() -> pd.DataFrame:
    return pd.read_csv(DATA_DIR / "changwon_state_reference_panel.csv")


def load_review_log() -> pd.DataFrame:
    return pd.read_csv(LOG_DIR / "exclusion_or_review_log.csv")


def industry_order(df: pd.DataFrame) -> list:
    """최신분기 고용 내림차순 업종 순서(노트북 IND_ORDER_EMP와 같은 기준)."""
    latest = sorted(df["quarter"].unique())[-1]
    return df[df["quarter"] == latest].sort_values("employment", ascending=False)["industry"].tolist()


# ---------------------------------------------------------------------------
# 통계 계산
# ---------------------------------------------------------------------------
def industry_state_shares(df: pd.DataFrame) -> pd.DataFrame:
    """업종별 유효 4국면(S1~S4) 비중(%)."""
    valid = df[df["valid_four_state"] == True]  # noqa: E712
    ct = pd.crosstab(valid["industry"], valid["state"], normalize="index") * 100
    cols = [c for c in ["S1", "S2", "S3", "S4"] if c in ct.columns]
    ct = ct[cols].round(1)
    ct["n_valid"] = valid.groupby("industry").size()
    ct["unique_states"] = valid.groupby("industry")["state"].nunique()
    return ct


def quarterly_state_counts(df: pd.DataFrame) -> pd.DataFrame:
    """분기별 국면 관측 건수 (동시성 구간 탐지용)."""
    ct = df.groupby("quarter")["state"].value_counts().unstack(fill_value=0)
    cols = [c for c in ["S1", "S2", "S3", "S4", "N", "INVALID"] if c in ct.columns]
    return ct[cols]


def review_flag_summary(log: pd.DataFrame) -> pd.DataFrame:
    """업종별 review_required 플래그 비율 (본분석 기간)."""
    main = log[log["in_main_period"] == True]  # noqa: E712
    return main.groupby("industry")["review_required"].agg(["sum", "count"])


def reference_period_context(ref: pd.DataFrame) -> pd.Series:
    """참고기간(2018Q1~2021Q4) 유효국면 비중 — 작은 표본 주의."""
    pre = ref[ref["in_main_period"] == False]  # noqa: E712
    valid_pre = pre[pre["valid_four_state"] == True]
    return (valid_pre["state"].value_counts(normalize=True) * 100).round(1)


# ---------------------------------------------------------------------------
# 차트 1 — 업종x분기 국면 히트맵
# ---------------------------------------------------------------------------
def plot_heatmap(df: pd.DataFrame, save_path: Path | None = None):
    save_path = save_path or FIG_DIR / "heatmap_q1.png"
    quarters = sorted(df["quarter"].unique())
    piv = df.pivot(index="industry", columns="quarter", values="state")
    order = industry_order(df)
    piv = piv.reindex(order)[quarters]

    n_ind, n_q = piv.shape
    fig = plt.figure(figsize=(12.2, 6.3), dpi=100)
    ax = fig.add_axes([0.09, 0.12, 0.72, 0.74])
    ax2 = fig.add_axes([0.83, 0.12, 0.14, 0.74])

    for i, ind in enumerate(order):
        row_y = n_ind - 1 - i
        for j, q in enumerate(quarters):
            st = piv.loc[ind, q]
            if pd.isna(st) or st == "INVALID":
                ax.add_patch(Rectangle((j, row_y), 0.92, 0.92, facecolor="white",
                                        edgecolor="#cbd5e1", hatch="////", linewidth=0.6))
            else:
                ax.add_patch(Rectangle((j, row_y), 0.92, 0.92, facecolor=COLOR.get(st, "#ddd")))
                txt_color = "white" if st in ("S1", "S4") else "#3a3a3a"
                ax.text(j + 0.46, row_y + 0.46, st, ha="center", va="center",
                         fontsize=9, color=txt_color, fontproperties=FP_BOLD)

    latest_idx = len(quarters) - 1
    for i in range(n_ind):
        ax.add_patch(Rectangle((latest_idx, n_ind - 1 - i), 0.92, 0.92,
                                facecolor="none", edgecolor="black", linewidth=1.6))

    ax.set_xlim(0, n_q); ax.set_ylim(0, n_ind)
    ax.set_xticks([j + 0.46 for j in range(n_q)])
    ax.set_xticklabels(quarters, rotation=45, ha="right", fontsize=8.5, fontproperties=FP)
    ax.set_yticks([n_ind - 1 - i + 0.46 for i in range(n_ind)])
    ax.set_yticklabels(order, fontsize=10, fontproperties=FP)
    ax.tick_params(length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    fig.suptitle("업종 x 분기 국면 격자 (업종은 최신분기 고용비중 내림차순)",
                  fontsize=12.5, fontproperties=FP_BOLD, y=0.985, x=0.46)

    valid = df[df["valid_four_state"] == True]  # noqa: E712
    for i, ind in enumerate(order):
        row_y = n_ind - 1 - i
        counts = valid[valid["industry"] == ind]["state"].value_counts()
        total = counts.sum()
        x0 = 0
        for st in ["S1", "S2", "S3", "S4"]:
            w = counts.get(st, 0) / total if total else 0
            ax2.add_patch(Rectangle((x0, row_y), w, 0.92, facecolor=COLOR[st]))
            x0 += w
    ax2.set_xlim(0, 1); ax2.set_ylim(0, n_ind)
    ax2.set_xticks([0, 0.5, 1]); ax2.set_xticklabels(["0%", "50%", "100%"], fontsize=8, fontproperties=FP)
    ax2.set_yticks([]); ax2.tick_params(length=0)
    for spine in ax2.spines.values():
        spine.set_visible(False)
    ax2.set_title("국면 구성비", fontsize=8.5, fontproperties=FP, pad=6)

    legend_items = [Patch(facecolor=COLOR[s], label=f"{s}") for s in ["S1", "S2", "S3", "S4"]]
    legend_items.append(Patch(facecolor=COLOR["N"], label="N"))
    legend_items.append(Patch(facecolor="white", edgecolor="#94a3b8", hatch="////", label="INVALID"))
    fig.legend(handles=legend_items, loc="lower center", ncol=6, fontsize=8.5,
               frameon=False, bbox_to_anchor=(0.5, 0.0), prop=FP)

    fig.savefig(save_path, facecolor="white")
    plt.close(fig)
    return save_path


# ---------------------------------------------------------------------------
# 차트 2 — 최신분기 생산·고용 산점도
# ---------------------------------------------------------------------------
def _padded_range(values: pd.Series, pad_lo: float = 0.12,
                   pad_hi: float = 0.12) -> tuple[float, float]:
    """관측값을 모두 담는 축 범위. 0선(사분면 경계)이 항상 포함되도록 0을 넣는다.

    고정값을 쓰면 범위를 벗어난 업종이 경고 없이 그림에서 사라지므로
    축 범위는 반드시 데이터에서 계산한다.
    """
    lo = min(float(values.min()), 0.0)
    hi = max(float(values.max()), 0.0)
    span = (hi - lo) or 1.0
    return lo - span * pad_lo, hi + span * pad_hi


def plot_scatter_latest(df: pd.DataFrame, quarter: str,
                         save_path: Path | None = None):
    save_path = save_path or FIG_DIR / "scatter_latest.png"
    latest = df[df["quarter"] == quarter].copy()
    plotted = latest[latest["state"].ne("INVALID")
                     & latest["production_yoy"].notna()
                     & latest["employment_yoy"].notna()]
    # x축 오른쪽 여백을 더 준다 — 업종명을 점 오른쪽에 붙이기 때문.
    xmin, xmax = _padded_range(plotted["production_yoy"], 0.10, 0.24)
    ymin, ymax = _padded_range(plotted["employment_yoy"])

    fig, ax = plt.subplots(figsize=(9.1, 6.5), dpi=100)
    ax.axvspan(xmin, 0, ymin=(0 - ymin) / (ymax - ymin), ymax=1, color="#fdf8ec", zorder=0)
    ax.axvspan(0, xmax, ymin=(0 - ymin) / (ymax - ymin), ymax=1, color="#eef6f4", zorder=0)
    ax.axvspan(xmin, 0, ymin=0, ymax=(0 - ymin) / (ymax - ymin), color="#f3eef1", zorder=0)
    ax.axvspan(0, xmax, ymin=0, ymax=(0 - ymin) / (ymax - ymin), color="#f2f5f7", zorder=0)
    ax.axhline(0, color="black", linewidth=0.8, zorder=1)
    ax.axvline(0, color="black", linewidth=0.8, zorder=1)

    tot_emp = latest["employment"].sum()
    for _, r in latest.iterrows():
        st = r["state"]
        if st == "INVALID" or pd.isna(r["production_yoy"]):
            continue
        share_pct = r["employment_share"] * 100
        radius = 6 + math.sqrt(max(share_pct, 0.05)) * 5.2
        ax.scatter(r["production_yoy"], r["employment_yoy"],
                   s=radius ** 1.62, color=COLOR.get(st, "#999"), alpha=0.88, zorder=3)
        ax.annotate(r["industry"], (r["production_yoy"], r["employment_yoy"]),
                    xytext=(9, -3), textcoords="offset points", fontsize=10.5, fontproperties=FP)

    ax.set_xlim(xmin, xmax); ax.set_ylim(ymin, ymax)
    ax.set_xlabel("명목 생산액 증감률 (YoY, %)", fontsize=11, fontproperties=FP)
    ax.set_ylabel("고용 증감률 (YoY, %)", fontsize=11, fontproperties=FP)
    ax.set_title(f"{quarter} 업종별 생산·고용 증감률과 국면 위치", fontsize=12.5, fontproperties=FP_BOLD)
    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)

    fig.tight_layout()
    fig.savefig(save_path, facecolor="white")
    plt.close(fig)
    return save_path


# ---------------------------------------------------------------------------
# 차트 3 — 민감도(threshold) 비교 바차트
# ---------------------------------------------------------------------------
def plot_sensitivity(quality_report_path: Path,
                      save_path: Path | None = None):
    save_path = save_path or FIG_DIR / "sensitivity_chart.png"
    with open(quality_report_path, encoding="utf-8") as f:
        qr = json.load(f)

    base = qr["states"]
    sens = qr["sensitivity"]
    thresholds = ["0%\n(본분석)", "±0.5%", "±1%", "±2%"]
    states = ["S1", "S2", "S3", "S4", "N"]
    data = {s: [base.get(s, 0)] for s in states}
    for key in ["0.5", "1.0", "2.0"]:
        st = sens[key]["states"]
        for s in states:
            data[s].append(st.get(s, 0))

    x = np.arange(len(thresholds))
    width = 0.15
    fig, ax = plt.subplots(figsize=(9.2, 4.6), dpi=100)
    for i, st in enumerate(states):
        ax.bar(x + (i - 2) * width, data[st], width, label=st, color=COLOR[st])
    ax.set_xticks(x); ax.set_xticklabels(thresholds, fontsize=10.5, fontproperties=FP)
    ax.set_ylabel("관측치 수 (건)", fontsize=10, fontproperties=FP)
    ax.set_title("중립구간(threshold) 민감도", fontsize=12.5, fontproperties=FP_BOLD, pad=10)
    ax.legend(prop=FP, ncol=5, frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.12))
    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)
    fig.tight_layout()
    fig.savefig(save_path, facecolor="white")
    plt.close(fig)
    return save_path


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------
def main():
    df = load_state_panel()
    ref = load_reference_panel()
    log = load_review_log()

    print("=== 업종별 국면 비중 ===")
    print(industry_state_shares(df))
    print("\n=== 분기별 국면 카운트 ===")
    print(quarterly_state_counts(df))
    print("\n=== 리뷰 플래그 (업종별) ===")
    print(review_flag_summary(log))
    print("\n=== 참고기간(2018Q1~2021Q4) 국면 비중 ===")
    print(reference_period_context(ref))

    latest_q = sorted(df["quarter"].unique())[-1]
    plot_heatmap(df)
    plot_scatter_latest(df, latest_q)
    qr_path = DATA_DIR / "quality_report.json"
    if qr_path.exists():
        plot_sensitivity(qr_path)

    print(f"\n차트 저장 완료: {FIG_DIR}/")


if __name__ == "__main__":
    main()
