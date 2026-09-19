"""
Q2(규모) 분석 시각화 모듈
==============================================
"Q2_규모분석" 리포트에 들어가는 핵심 시각화 4종을 생성하여
고해상도 이미지(PNG)로 `outputs/final_model/01_core/figures/`에 저장한다.

모든 수치는 본분석 패널에서 직접 계산한다 — 이 파일에 결과값을 적어두지 않는다.
패널이 갱신되면 차트도 함께 갱신된다.

입력 파일:
    - data/processed/kicox/changwon_state_panel.csv : 본분석 패널 (2022Q1~2026Q2, 10업종x18분기)

출력:
    - outputs/final_model/01_core/figures/ 에 PNG 4종
      (chart1_q2_2_hbar, chart2_q2_3_excess, chart3_q2_4_position, chart4_q2_5_heatmap)

배색 규칙은 src/core/analysis/config.py를 따른다(팀 공통 팔레트).
    - 증감 방향(Q2 고유)  : DELTA_COLORS
    - 국면(Q1과 공유)     : STATE_COLORS

사용법:
    python src/core/q2_visualize.py
"""

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# 1. 경로 및 공통 설정
# ---------------------------------------------------------------------------
CURRENT_FILE = Path(__file__).resolve()
SRC_DIR = CURRENT_FILE.parents[1]
ROOT_DIR = CURRENT_FILE.parents[2]
PANEL_PATH = ROOT_DIR / "data" / "processed" / "kicox" / "changwon_state_panel.csv"
FIGURE_DIR = ROOT_DIR / "outputs" / "final_model" / "01_core" / "figures"
FIGURE_DIR.mkdir(parents=True, exist_ok=True)

# 팀 공통 배색·폰트 설정을 재사용한다(색 정의를 이 파일에서 새로 만들지 않는다).
sys.path.insert(0, str(SRC_DIR))
from core.analysis import config  # noqa: E402

config.setup_matplotlib()

TOP_N = 4          # 비례 기준선 비교·히트맵에 개별 표시할 상위 업종 수
UNIT_THOUSAND = 1000.0


# ---------------------------------------------------------------------------
# 2. 데이터 로드 및 파생값
# ---------------------------------------------------------------------------
def load_panel(path: Path = PANEL_PATH) -> pd.DataFrame:
    """본분석 패널을 읽고 고용 증감 인원(emp_delta)을 파생한다."""
    df = pd.read_csv(path)
    df.columns = [c.lstrip("﻿") for c in df.columns]
    df = df.sort_values(["industry", "quarter_index"]).reset_index(drop=True)
    # employment_lag4는 01 산출물의 컬럼이며 업종 내 4분기 전 값이다.
    df["emp_delta"] = df["employment"] - df["employment_lag4"]
    return df


def latest_quarter(df: pd.DataFrame) -> str:
    return sorted(df["quarter"].unique())[-1]


def latest_frame(df: pd.DataFrame, quarter: str) -> pd.DataFrame:
    """최신분기 업종별 고용·증감인원·비중·국면 (증감인원 오름차순)."""
    d = df[df["quarter"] == quarter].set_index("industry")
    out = pd.DataFrame({
        "employment": d["employment"],
        "employment_lag4": d["employment_lag4"],
        "emp_delta": d["emp_delta"],
        "emp_yoy": d["employment_yoy"],
        "state": d["state"],
    })
    # 비중 분모는 패널의 10개 제조업 합계다(단지 전체 고용에는 비제조가 포함되므로 쓰지 않는다).
    out["share"] = out["employment"] / out["employment"].sum() * 100
    return out.sort_values("emp_delta")


def top_industries(frame: pd.DataFrame, n: int = TOP_N) -> list:
    """최신분기 고용비중 상위 n개 업종(내림차순)."""
    return frame.sort_values("share", ascending=False).index[:n].tolist()


def shift_share(frame: pd.DataFrame) -> pd.DataFrame:
    """규모를 통제한 비교 — 비례배분 기준선 대비 초과 증감.

    기준선 = 기준분기(t-4) 고용비중 x 제조업 전체 순증감.
    당분기 비중이 아니라 기준분기 비중을 쓴다(결과가 분모에 다시 들어가지 않도록).
    """
    out = frame.copy()
    total_delta = out["emp_delta"].sum()
    base_total = out["employment_lag4"].sum()
    out["share_base"] = out["employment_lag4"] / base_total
    out["expected"] = out["share_base"] * total_delta
    out["excess"] = out["emp_delta"] - out["expected"]
    return out


def concentration_pct(frame: pd.DataFrame) -> tuple[str, float]:
    """순증감에 가장 크게 기여한 업종과 그 기여율(%)."""
    total_delta = frame["emp_delta"].sum()
    top = frame["emp_delta"].abs().idxmax()
    return top, frame.loc[top, "emp_delta"] / total_delta * 100


def _delta_color(value: float) -> str:
    if value > 0:
        return config.DELTA_COLORS["up"]
    if value < 0:
        return config.DELTA_COLORS["down"]
    return config.DELTA_COLORS["neutral"]


# ---------------------------------------------------------------------------
# [Chart 1] Q2-2. 업종별 고용 순증감 인원 (가로 막대)
# ---------------------------------------------------------------------------
def plot_chart1(frame: pd.DataFrame, quarter: str, save_path: Path | None = None):
    save_path = save_path or FIGURE_DIR / "chart1_q2_2_hbar.png"
    data = frame.sort_values("emp_delta")
    top_ind, top_pct = concentration_pct(frame)

    fig, ax = plt.subplots(figsize=(10, 5.5))
    ax.grid(True, axis="x", linestyle="--", alpha=0.5)
    colors = [_delta_color(v) for v in data["emp_delta"]]
    bars = ax.barh(data.index, data["emp_delta"], color=colors, height=0.6)
    ax.axvline(0, color="#0f172a", linewidth=1.2, linestyle="--")

    span = max(data["emp_delta"].abs().max(), 1)
    for bar in bars:
        width = bar.get_width()
        ha = "right" if width < 0 else "left"
        offset = -8 if width < 0 else 8
        ax.annotate(f"{width:+,.0f}명",
                    xy=(width, bar.get_y() + bar.get_height() / 2),
                    xytext=(offset, 0), textcoords="offset points",
                    ha=ha, va="center", fontsize=9.5, fontweight="bold", color="#1e293b")

    ax.set_title(f"[Q2-2] {quarter} 업종별 고용 순증감 인원 "
                 f"({top_ind} 집중도 {top_pct:.1f}%)",
                 fontsize=13, pad=15, fontweight="bold")
    ax.set_xlabel("전년동기대비 고용 순증감 (YoY, 명)", fontsize=11)
    ax.set_xlim(-span * 1.18, span * 0.32)
    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)

    fig.tight_layout()
    fig.savefig(save_path, dpi=300)
    plt.close(fig)
    print(f"[저장 완료] {save_path.name}")
    return save_path


# ---------------------------------------------------------------------------
# [Chart 2] Q2-3. 실제 증감 vs 비례배분 기준선
# ---------------------------------------------------------------------------
def plot_chart2(frame: pd.DataFrame, quarter: str, industries: list,
                save_path: Path | None = None):
    save_path = save_path or FIGURE_DIR / "chart2_q2_3_excess.png"
    df = shift_share(frame).loc[industries]

    x = np.arange(len(df))
    width = 0.35
    fig, ax = plt.subplots(figsize=(9.5, 5.5))
    ax.grid(True, axis="y", linestyle="--", alpha=0.5)
    ax.bar(x - width / 2, df["emp_delta"], width, label="실제 증감 (A)",
           color=config.DELTA_COLORS["down"], alpha=0.9)
    ax.bar(x + width / 2, df["expected"], width, label="비례배분 기준선 (B)",
           color=config.DELTA_COLORS["neutral"], alpha=0.95)

    lo = min(df["emp_delta"].min(), df["expected"].min())
    hi = max(df["emp_delta"].max(), df["expected"].max(), 0)
    pad = (hi - lo) * 0.16
    for i, (_, row) in enumerate(df.iterrows()):
        diff = row["excess"]
        # 기준선 대비 차이를 부호로만 적는다(노트북 Q2C와 같은 표기). '억제'처럼 원인을 함의하거나,
        # 제조업 전체가 증가한 분기에는 틀리게 되는 '덜 감소' 같은 방향 서술은 쓰지 않는다.
        text = f"기준선 대비 {diff:+,.0f}명"
        color = "#333333"
        ax.text(x[i], min(row["emp_delta"], row["expected"]) - pad * 0.12, text,
                ha="center", va="top", fontweight="bold", color=color, fontsize=9.5)

    ax.set_title(f"[Q2-3] 규모를 고려한 비교: 실제 변화 vs 비례 기준선 ({quarter})",
                 fontsize=13, pad=15, fontweight="bold")
    ax.set_ylabel("고용 증감 인원 (명)", fontsize=11)
    ax.set_xticks(x)
    ax.set_xticklabels(df.index, fontsize=11, fontweight="bold")
    # 막대가 모두 0 아래에 있으므로 범례는 비어 있는 좌상단에 둔다(주석과 겹침 방지).
    ax.legend(frameon=True, loc="upper left")
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_ylim(lo - pad * 1.5, hi + pad * 1.6)
    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)

    fig.tight_layout()
    fig.savefig(save_path, dpi=300)
    plt.close(fig)
    print(f"[저장 완료] {save_path.name}")
    return save_path


# ---------------------------------------------------------------------------
# [Chart 3] Q2-4. 고용 비중(규모) x YoY 증감률(속도) 포지셔닝
# ---------------------------------------------------------------------------
def plot_chart3(frame: pd.DataFrame, quarter: str, save_path: Path | None = None):
    save_path = save_path or FIGURE_DIR / "chart3_q2_4_position.png"
    data = frame.dropna(subset=["emp_yoy", "share"])

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.grid(True, linestyle="--", alpha=0.5)

    # 점 크기 = 증감 인원의 절대 규모, 점 색 = 국면(Q1과 같은 팔레트)
    scale = data["emp_delta"].abs()
    sizes = np.clip(scale / max(scale.max(), 1) * 2000, 90, 2000)
    colors = [config.STATE_COLORS.get(s, "#999999") for s in data["state"]]

    ax.scatter(data["share"], data["emp_yoy"], s=sizes, c=colors,
               alpha=0.75, edgecolors="black", linewidth=1.2, zorder=3)
    ax.axhline(0, color="gray", linestyle="--", linewidth=1, zorder=1)
    # 세로선은 config.SHARE_CUT(Q2 상세표시 대상 고용비중 하한)에서 가져온다.
    # 표시 대상 선정 기준이지 '중요도'의 경계가 아니므로 라벨도 그대로 쓴다.
    ax.axvline(config.SHARE_CUT, color="#60a5fa", linestyle=":", linewidth=1.2, zorder=1,
               label=f"Q2 상세표시 기준 (고용비중 {config.SHARE_CUT:g}%)")

    for ind, row in data.iterrows():
        offset_y = 13 if row["emp_yoy"] >= 0 else -15
        ax.annotate(ind, xy=(row["share"], row["emp_yoy"]),
                    xytext=(0, offset_y), textcoords="offset points",
                    ha="center", fontsize=10, fontweight="bold")

    handles = [plt.Line2D([0], [0], marker="o", linestyle="", markersize=9,
                          markerfacecolor=config.STATE_COLORS[s],
                          markeredgecolor="black", label=config.STATE_LABELS[s])
               for s in config.STATES5 if s in set(data["state"])]
    handles.append(plt.Line2D([0], [0], color="#60a5fa", linestyle=":", linewidth=1.2,
                              label=f"Q2 상세표시 기준 (고용비중 {config.SHARE_CUT:g}%)"))
    ax.legend(handles=handles, loc="best", frameon=True, fontsize=9)

    ax.set_title(f"[Q2-4] 고용 비중(규모) x 증감률(속도) 포지셔닝 맵 ({quarter})\n"
                 "점 크기 = 고용 증감 인원의 절대 규모",
                 fontsize=13, pad=15, fontweight="bold")
    ax.set_xlabel("고용 비중 (%, 10개 제조업종 내)", fontsize=11)
    ax.set_ylabel("고용 전년동기대비 증감률 (YoY, %)", fontsize=11)
    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)

    fig.tight_layout()
    fig.savefig(save_path, dpi=300)
    plt.close(fig)
    print(f"[저장 완료] {save_path.name}")
    return save_path


# ---------------------------------------------------------------------------
# [Chart 4] Q2-5. 전 분기 주요 업종 고용 증감 히트맵
# ---------------------------------------------------------------------------
def plot_chart4(df: pd.DataFrame, industries: list, save_path: Path | None = None):
    save_path = save_path or FIGURE_DIR / "chart4_q2_5_heatmap.png"
    piv = (df.pivot(index="industry", columns="quarter", values="emp_delta")
             .loc[industries])
    quarters = list(piv.columns)
    matrix = piv.to_numpy(dtype=float) / UNIT_THOUSAND

    fig, ax = plt.subplots(figsize=(14, 4.2))
    vmax = np.nanmax(np.abs(matrix)) if np.isfinite(matrix).any() else 1.0
    # RdBu_r: 감소(음수)=파랑, 증가(양수)=빨강. matplotlib 내장 발산 컬러맵.
    im = ax.imshow(matrix, cmap="RdBu_r", aspect="auto", vmin=-vmax, vmax=vmax)

    ax.set_xticks(np.arange(len(quarters)))
    ax.set_yticks(np.arange(len(industries)))
    ax.set_xticklabels([q.replace("20", "", 1) for q in quarters], fontsize=9.5)
    ax.set_yticklabels(industries, fontsize=10.5, fontweight="bold")

    for i in range(matrix.shape[0]):
        for j in range(matrix.shape[1]):
            val = matrix[i, j]
            if not np.isfinite(val):
                ax.text(j, i, "–", ha="center", va="center", color="#94a3b8", fontsize=9)
                continue
            text_color = "white" if abs(val) >= vmax * 0.55 else "black"
            ax.text(j, i, f"{val:+.1f}", ha="center", va="center",
                    color=text_color, fontsize=9, fontweight="bold")

    cbar = fig.colorbar(im, ax=ax, pad=0.02)
    cbar.set_label("순증감 인원 (천 명)", fontsize=10)

    ax.set_title(f"[Q2-5] 주요 {len(industries)}개 업종 고용 증감 히트맵 "
                 f"({quarters[0]}–{quarters[-1]}, 단위: 천 명)",
                 fontsize=13, pad=15, fontweight="bold")

    fig.tight_layout()
    fig.savefig(save_path, dpi=300)
    plt.close(fig)
    print(f"[저장 완료] {save_path.name}")
    return save_path


# ---------------------------------------------------------------------------
# 전체 실행
# ---------------------------------------------------------------------------
def main():
    print("=== Q2 시각화 차트 생성 시작 ===")
    df = load_panel()
    quarter = latest_quarter(df)
    frame = latest_frame(df, quarter)
    industries = top_industries(frame)
    print(f"기준 분기: {quarter} | 상위 {TOP_N}개 업종: {', '.join(industries)}")

    plot_chart1(frame, quarter)
    plot_chart2(frame, quarter, industries)
    plot_chart3(frame, quarter)
    plot_chart4(df, industries)
    print(f"=== 전체 차트 생성 및 저장 완료 (경로: {FIGURE_DIR}) ===")


if __name__ == "__main__":
    main()
