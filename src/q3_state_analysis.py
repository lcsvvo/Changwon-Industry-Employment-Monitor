"""
Q3 — 창원국가산단 업종별 국면(S1~S4) 지속·전환 분석 및 시각화

Q1이 확정한 국면(S1~S4, threshold=0)을 그대로 입력값으로 사용해 지속기간(run)과
인접분기 전환을 계산한다. 추가로 (1) 현재 진행 중인 run이 threshold 민감도에
얼마나 취약한지, (2) 그 취약성이 가동률 같은 독립 지표로도 뒷받침되는지를
검증하는 로직을 포함한다.

입력 파일 (data/processed/ 에 위치):
    - changwon_state_panel.csv            : 본분석 패널 (Q1 국면 판정 포함)
    - changwon_state_sensitivity_panel.csv : threshold 0.5/1/2% 민감도 패널

출력:
    - outputs/figures/ 에 PNG 5종
      (q3_top4_timeline, q3_current_run_bar, q3_transition_matrix,
       q3_s2_boundary, q3_corroboration)
    - 콘솔에 주요 통계 출력 (run 통계, 전환행렬, 경계칸 비율, 교차검증 표)

사용법:
    python src/q3_state_analysis.py
"""

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from matplotlib.patches import Rectangle, Patch
import numpy as np
import pandas as pd

DATA_DIR = Path("data/processed")
FIG_DIR = Path("outputs/figures")
FIG_DIR.mkdir(parents=True, exist_ok=True)

COLOR = {
    "S1": "#4A75A4", "S2": "#72B7B2", "S3": "#F2CF5B", "S4": "#B279A2", "N": "#BDBDBD",
}
TOP4 = ["기계", "전기전자", "운송장비", "철강"]
TOP4_SHARE = {"기계": "51.2%", "전기전자": "24.4%", "운송장비": "14.2%", "철강": "8.4%"}

_FONT_PATH = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
_FONT_BOLD_PATH = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
try:
    FP = fm.FontProperties(fname=_FONT_PATH)
    FP_BOLD = fm.FontProperties(fname=_FONT_BOLD_PATH)
except FileNotFoundError:
    FP = FP_BOLD = fm.FontProperties()
plt.rcParams["axes.unicode_minus"] = False


# ---------------------------------------------------------------------------
# 데이터 로드
# ---------------------------------------------------------------------------
def load_state_panel() -> pd.DataFrame:
    return pd.read_csv(DATA_DIR / "changwon_state_panel.csv")


def load_sensitivity_panel() -> pd.DataFrame:
    return pd.read_csv(DATA_DIR / "changwon_state_sensitivity_panel.csv")


# ---------------------------------------------------------------------------
# 지속성 통계
# ---------------------------------------------------------------------------
def run_statistics(df: pd.DataFrame) -> dict:
    """연속구간(run) 개수·평균길이·최장길이·2분기 이상 비율."""
    runs = df[df["valid_four_state"] == True].drop_duplicates(subset=["industry", "run_id"])  # noqa: E712
    return {
        "n_runs": len(runs),
        "avg_length": runs["run_total_length"].mean(),
        "max_length": runs["run_total_length"].max(),
        "n_ge2": int((runs["run_total_length"] >= 2).sum()),
        "pct_ge2": float((runs["run_total_length"] >= 2).mean() * 100),
    }


def current_run_by_industry(df: pd.DataFrame, latest_quarter: str) -> pd.DataFrame:
    """각 업종의 최신분기 기준 현재 국면·지속기간."""
    latest = df[df["quarter"] == latest_quarter][
        ["industry", "state", "run_total_length", "state_start_quarter"]
    ]
    return latest.sort_values("run_total_length", ascending=False)


def transition_matrix_5state(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """t분기 state -> t+1분기 next_state 5국면 전환행렬. (건수, 비율%) 반환."""
    trans = df[df["valid_transition5"] == True]  # noqa: E712
    order = ["S1", "S2", "S3", "S4", "N"]
    counts = pd.crosstab(trans["state"], trans["next_state"]).reindex(
        index=order, columns=order, fill_value=0
    )
    pct = counts.div(counts.sum(axis=1), axis=0) * 100
    return counts, pct


# ---------------------------------------------------------------------------
# threshold 경계칸 대조 — 현재 run이 얼마나 취약한가
# ---------------------------------------------------------------------------
def boundary_cells(df: pd.DataFrame, sens: pd.DataFrame) -> set:
    """threshold 0.5/1/2% 중 하나라도 본분석(0%) 국면과 다른 (quarter, industry) 집합."""
    base = df[["quarter", "industry", "state"]].rename(columns={"state": "state_0"})
    merged = sens.merge(base, on=["quarter", "industry"])
    merged["changed"] = merged["state"] != merged["state_0"]
    flags = merged.groupby(["quarter", "industry"])["changed"].any()
    return set(flags[flags].index)


def current_run_boundary_ratio(df: pd.DataFrame, sens: pd.DataFrame,
                                industries: list, latest_quarter: str) -> pd.DataFrame:
    """상위 업종들의 현재 run 중 threshold 경계칸 비율."""
    boundary = boundary_cells(df, sens)
    rows = []
    for ind in industries:
        sub = df[df["industry"] == ind].sort_values("quarter")
        latest_row = sub[sub["quarter"] == latest_quarter].iloc[0]
        run_id = latest_row["run_id"]
        run_quarters = sub[sub["run_id"] == run_id]["quarter"].tolist()
        n_boundary = sum(1 for q in run_quarters if (q, ind) in boundary)
        rows.append({
            "industry": ind,
            "state": latest_row["state"],
            "run_length": len(run_quarters),
            "run_quarters": run_quarters,
            "n_boundary": n_boundary,
            "boundary_ratio": n_boundary / len(run_quarters),
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 가동률 교차검증 — 독립 지표로 다시 확인
# ---------------------------------------------------------------------------
def corroboration_table(df: pd.DataFrame, industries: list, quarters: list) -> pd.DataFrame:
    """고용YoY와 가동률YoY(pp)가 같은 방향인지 분기별로 대조."""
    sub = df[(df["industry"].isin(industries)) & (df["quarter"].isin(quarters))][
        ["industry", "quarter", "state", "employment_yoy_master", "op_rate_official_yoy_pp"]
    ].copy()
    sub["same_direction"] = (sub["employment_yoy_master"] * sub["op_rate_official_yoy_pp"]) > 0
    return sub.sort_values(["industry", "quarter"])


def corroboration_summary(corr_df: pd.DataFrame) -> pd.DataFrame:
    """업종별 '고용·가동률 같은 방향' 비율 요약."""
    return corr_df.groupby("industry")["same_direction"].agg(
        n_match="sum", n_total="count"
    ).assign(match_ratio=lambda d: d["n_match"] / d["n_total"])


# ---------------------------------------------------------------------------
# 차트 1 — 상위4개 업종 생산·고용 경로 + 병합 국면 리본
# ---------------------------------------------------------------------------
def _merged_runs(sub: pd.DataFrame, quarters: list) -> list:
    blocks, cur_state, start = [], None, 0
    for j, q in enumerate(quarters):
        st = sub.loc[q, "state"] if q in sub.index else None
        if pd.isna(st):
            st = "INVALID"
        if st != cur_state:
            if cur_state is not None:
                blocks.append((start, j - start, cur_state))
            cur_state, start = st, j
    blocks.append((start, len(quarters) - start, cur_state))
    return blocks


def plot_top4_timeline(df: pd.DataFrame, save_path: Path | None = None):
    save_path = save_path or FIG_DIR / "q3_top4_timeline.png"
    quarters = sorted(df["quarter"].unique())
    fig = plt.figure(figsize=(13.5, 11.5), dpi=100)
    gs = fig.add_gridspec(5, 2, height_ratios=[3, 0.55, 0.55, 3, 0.55],
                           hspace=0.35, wspace=0.16, left=0.06, right=0.98, top=0.93, bottom=0.13)
    row_pairs = [(0, 1), (3, 4)]
    positions = [(0, row_pairs[0]), (1, row_pairs[0]), (0, row_pairs[1]), (1, row_pairs[1])]

    for ind, (c, (main_r, ribbon_r)) in zip(TOP4, positions):
        sub = df[df["industry"] == ind].set_index("quarter").reindex(quarters)
        ax = fig.add_subplot(gs[main_r, c])
        axr = fig.add_subplot(gs[ribbon_r, c])
        x = np.arange(len(quarters))
        ax.plot(x, sub["production_yoy_master"].values, marker="o", markersize=3.5,
                color="#2c3e6b", linewidth=1.4, label="생산 YoY")
        ax.plot(x, sub["employment_yoy_master"].values, marker="o", markersize=3.5,
                color="#a04f8a", linewidth=1.4, label="고용 YoY")
        ax.axhline(0, color="#94a3b8", linewidth=0.6)
        ax.set_ylim(-27, 61)
        ax.set_xlim(-0.5, len(quarters) - 0.5)
        ax.text(0.01, 0.95, f"{ind} (고용비중 {TOP4_SHARE[ind]})", transform=ax.transAxes,
                fontsize=12, fontproperties=FP_BOLD, va="top")
        ax.set_xticks(x); ax.set_xticklabels([]); ax.tick_params(axis="x", length=0)
        for spine in ["top", "right"]:
            ax.spines[spine].set_visible(False)
        if c == 0:
            ax.set_ylabel("YoY (%)", fontsize=9.5, fontproperties=FP)
        if main_r == 0 and c == 0:
            ax.legend(prop=FP, fontsize=9, frameon=False, loc="lower right")

        for start, length, st in _merged_runs(sub, quarters):
            x0 = start - 0.5
            if st == "INVALID":
                axr.add_patch(Rectangle((x0, 0), length, 1, facecolor="#f1f5f9",
                                         edgecolor="#cbd5e1", linewidth=0.4))
            else:
                axr.add_patch(Rectangle((x0, 0), length, 1, facecolor=COLOR.get(st, "#ddd"),
                                         edgecolor="white", linewidth=1.2))
                label = f"{st}·{length}Q" if length >= 2 else st
                txt_color = "white" if st in ("S1", "S4") else "#1e293b"
                axr.text(start + length / 2 - 0.5, 0.5, label, ha="center", va="center",
                          fontsize=9.5 if length >= 2 else 8.5, color=txt_color, fontproperties=FP_BOLD)
        axr.set_xlim(-0.5, len(quarters) - 0.5); axr.set_ylim(0, 1); axr.set_yticks([])
        axr.set_xticks(x)
        axr.set_xticklabels(quarters, rotation=45, ha="right", fontsize=8, fontproperties=FP)
        axr.tick_params(axis="x", length=2, pad=2)
        for spine in axr.spines.values():
            spine.set_visible(False)

    fig.suptitle("주요 4개 업종의 생산·고용 YoY 경로와 국면 (y축 동일: -27~61%)",
                  fontsize=14, fontproperties=FP_BOLD, y=0.975)
    legend_items = [Patch(facecolor=COLOR[s], label=s) for s in ["S1", "S2", "S3", "S4"]]
    legend_items.append(Patch(facecolor="#f1f5f9", edgecolor="#cbd5e1", label="INVALID"))
    fig.legend(handles=legend_items, loc="lower center", ncol=5, fontsize=10, frameon=False,
               bbox_to_anchor=(0.5, 0.015), prop=FP)
    fig.savefig(save_path, facecolor="white")
    plt.close(fig)
    return save_path


# ---------------------------------------------------------------------------
# 차트 2 — 업종별 현재 국면 지속기간
# ---------------------------------------------------------------------------
def plot_current_run_bar(df: pd.DataFrame, latest_quarter: str,
                          save_path: Path | None = None):
    save_path = save_path or FIG_DIR / "q3_current_run_bar.png"
    latest = df[df["quarter"] == latest_quarter]
    latest = latest[latest["state"] != "N"].sort_values("run_total_length")

    fig, ax = plt.subplots(figsize=(10.5, 5.6), dpi=100)
    y = np.arange(len(latest))
    colors = [COLOR.get(s, "#ccc") for s in latest["state"]]
    bars = ax.barh(y, latest["run_total_length"], color=colors, height=0.6)
    labels = [f"{ind}{'★' if ind in TOP4 else ''}" for ind in latest["industry"]]
    ax.set_yticks(y); ax.set_yticklabels(labels, fontsize=11, fontproperties=FP)
    for b, (_, row) in zip(bars, latest.iterrows()):
        ax.text(b.get_width() + 0.05, b.get_y() + b.get_height() / 2,
                f"{row['state']}·{int(row['run_total_length'])}분기째",
                va="center", fontsize=9.5, fontproperties=FP, color="#334155")
    ax.set_xlabel("현재 국면이 연속된 분기 수", fontsize=10, fontproperties=FP)
    ax.set_title(f"업종별 현재 국면 지속기간 ({latest_quarter} 기준, ★=Q1 고용비중 상위4)",
                 fontsize=12.5, fontproperties=FP_BOLD, pad=10)
    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)
    ax.spines["left"].set_visible(False)
    ax.tick_params(left=False)
    fig.tight_layout()
    fig.savefig(save_path, facecolor="white", bbox_inches="tight")
    plt.close(fig)
    return save_path


# ---------------------------------------------------------------------------
# 차트 3 — 전환행렬 히트맵
# ---------------------------------------------------------------------------
def plot_transition_matrix(counts: pd.DataFrame, pct: pd.DataFrame,
                            save_path: Path | None = None):
    save_path = save_path or FIG_DIR / "q3_transition_matrix.png"
    order = list(counts.index)
    fig, ax = plt.subplots(figsize=(8.5, 7.3), dpi=100)
    im = ax.imshow(pct.values, cmap="Blues", vmin=0, vmax=100, aspect="auto")
    for i in range(len(order)):
        for j in range(len(order)):
            v, c = pct.values[i, j], counts.values[i, j]
            ax.text(j, i, f"{v:.0f}%\n({c}건)", ha="center", va="center", fontsize=10.5,
                    color="white" if v > 55 else "#334155", fontproperties=FP)
    for i in range(len(order)):
        ax.add_patch(Rectangle((i - 0.5, i - 0.5), 1, 1, fill=False, edgecolor="black", linewidth=2))
    ax.set_xticks(range(len(order))); ax.set_xticklabels(order, fontsize=11, fontproperties=FP)
    ax.set_yticks(range(len(order)))
    ax.set_yticklabels([f"{o} (n={int(counts.loc[o].sum())})" for o in order], fontsize=11, fontproperties=FP)
    ax.set_xlabel("t+1 분기 국면", fontsize=10.5, fontproperties=FP)
    ax.set_ylabel("t 분기 국면", fontsize=10.5, fontproperties=FP)
    ax.set_title(f"관측된 국면 전환 빈도 (전환 {int(counts.values.sum())}건)\n대각선 = 같은 국면 유지",
                 fontsize=12.5, fontproperties=FP_BOLD)
    cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    cbar.set_label("행 기준 비율 (%)", fontsize=9.5, fontproperties=FP)
    fig.tight_layout()
    fig.savefig(save_path, facecolor="white", bbox_inches="tight")
    plt.close(fig)
    return save_path


# ---------------------------------------------------------------------------
# 차트 4 — 현재 run의 threshold 경계칸 비율
# ---------------------------------------------------------------------------
def plot_s2_boundary(boundary_df: pd.DataFrame, save_path: Path | None = None):
    save_path = save_path or FIG_DIR / "q3_s2_boundary.png"
    df = boundary_df.set_index("industry").loc[TOP4].reset_index()
    fig, ax = plt.subplots(figsize=(9.5, 4.6), dpi=100)
    y = np.arange(len(df))
    colors = [COLOR[s] for s in df["state"]]
    bars = ax.barh(y, df["boundary_ratio"] * 100, color=colors, height=0.55, alpha=0.9)
    for b, (_, row) in zip(bars, df.iterrows()):
        ax.text(b.get_width() + 2, b.get_y() + b.get_height() / 2,
                f"{row['n_boundary']}/{row['run_length']}분기가 경계칸 ({row['boundary_ratio']*100:.0f}%)",
                va="center", fontsize=10, fontproperties=FP, color="#334155")
    ax.set_yticks(y)
    ax.set_yticklabels([f"{r.industry} (현재 {r.state}, {r.run_length}분기째)" for r in df.itertuples()],
                        fontsize=11, fontproperties=FP)
    ax.set_xlim(0, 115)
    ax.set_xlabel("현재 run 중 threshold 민감(경계칸) 비율 (%)", fontsize=10, fontproperties=FP)
    ax.set_title("현재 진행 중인 연속기록(run), threshold를 바꾸면 얼마나 흔들리나",
                 fontsize=12.5, fontproperties=FP_BOLD, pad=10)
    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)
    ax.spines["left"].set_visible(False)
    ax.tick_params(left=False)
    fig.tight_layout()
    fig.savefig(save_path, facecolor="white", bbox_inches="tight")
    plt.close(fig)
    return save_path


# ---------------------------------------------------------------------------
# 차트 5 — 고용YoY vs 가동률YoY 교차검증
# ---------------------------------------------------------------------------
def plot_corroboration(df: pd.DataFrame, latest_quarter: str,
                        save_path: Path | None = None):
    save_path = save_path or FIG_DIR / "q3_corroboration.png"
    latest = df[(df["industry"].isin(TOP4)) & (df["quarter"] == latest_quarter)].set_index("industry").loc[TOP4]
    x = np.arange(len(TOP4))
    width = 0.35
    fig, ax = plt.subplots(figsize=(9.5, 5.2), dpi=100)
    b1 = ax.bar(x - width / 2, latest["employment_yoy_master"], width, label="고용 YoY (%)",
                color=[COLOR[s] for s in latest["state"]], alpha=0.95)
    b2 = ax.bar(x + width / 2, latest["op_rate_official_yoy_pp"], width, label="가동률 YoY (%p)",
                color="#cbd5e1", edgecolor="#64748b", linewidth=0.8)
    ax.axhline(0, color="#334155", linewidth=0.8)
    for b in list(b1) + list(b2):
        v = b.get_height()
        ax.text(b.get_x() + b.get_width() / 2, v + (0.15 if v >= 0 else -0.35), f"{v:+.1f}",
                ha="center", fontsize=9.5, fontproperties=FP, color="#334155")
    ax.set_xticks(x)
    ax.set_xticklabels([f"{ind}\n({latest.loc[ind, 'state']})" for ind in TOP4], fontsize=11, fontproperties=FP)
    ax.set_ylabel("YoY 변화", fontsize=10.5, fontproperties=FP)
    ax.set_title(f"{latest_quarter} — 고용 YoY와 가동률 YoY, 같은 방향인가 다른 방향인가",
                 fontsize=12.5, fontproperties=FP_BOLD, pad=10)
    ax.legend(prop=FP, fontsize=10, frameon=False, loc="lower left")
    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)
    fig.tight_layout()
    fig.savefig(save_path, facecolor="white", bbox_inches="tight")
    plt.close(fig)
    return save_path


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------
def main():
    df = load_state_panel()
    sens = load_sensitivity_panel()
    quarters = sorted(df["quarter"].unique())
    latest_q = quarters[-1]
    last4 = quarters[-4:]

    print("=== 지속성 통계 ===")
    print(run_statistics(df))

    print("\n=== 업종별 현재 국면 (", latest_q, ") ===")
    print(current_run_by_industry(df, latest_q).to_string(index=False))

    counts, pct = transition_matrix_5state(df)
    print("\n=== 전환행렬 (건수) ===")
    print(counts)
    print("\n=== 전환행렬 (비율 %) ===")
    print(pct.round(0))

    print("\n=== 상위4개 업종 현재 run의 threshold 경계칸 비율 ===")
    boundary_df = current_run_boundary_ratio(df, sens, TOP4, latest_q)
    print(boundary_df[["industry", "state", "run_length", "n_boundary", "boundary_ratio"]].to_string(index=False))

    print("\n=== 가동률 교차검증 (최근 4분기) ===")
    corr = corroboration_table(df, TOP4, last4)
    print(corr.to_string(index=False))
    print("\n=== 교차검증 요약 (같은 방향 비율) ===")
    print(corroboration_summary(corr))

    plot_top4_timeline(df)
    plot_current_run_bar(df, latest_q)
    plot_transition_matrix(counts, pct)
    plot_s2_boundary(boundary_df)
    plot_corroboration(df, latest_q)

    print(f"\n차트 저장 완료: {FIG_DIR}/")


if __name__ == "__main__":
    main()
