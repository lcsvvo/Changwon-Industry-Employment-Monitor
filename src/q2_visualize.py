"""
Q2(규모) 분석 시각화 모듈
==============================================
"Q2_규모분석" 리포트에 포함된 핵심 시각화 4종을 생성하여
고해상도 이미지(PNG)로 'outputs/figures/' 폴더에 자동 저장합니다.
"""

import sys
from pathlib import Path
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# 1. 경로 및 폰트 설정
# ---------------------------------------------------------------------------
CURRENT_FILE = Path(__file__).resolve()
ROOT_DIR = CURRENT_FILE.parents[1] if CURRENT_FILE.parent.name == "src" else CURRENT_FILE.parent
FIGURE_DIR = ROOT_DIR / "outputs" / "figures"
FIGURE_DIR.mkdir(parents=True, exist_ok=True)

# OS별 한글 폰트 설정
if sys.platform.startswith("win"):
    plt.rcParams["font.family"] = "Malgun Gothic"
elif sys.platform.startswith("darwin"):
    plt.rcParams["font.family"] = "AppleGothic"
else:
    plt.rcParams["font.family"] = "NanumGothic"

plt.rcParams["axes.unicode_minus"] = False


# ---------------------------------------------------------------------------
# [Chart 1] Q2-2. 업종별 고용 순증감 인원 (가로 막대 차트)
# ---------------------------------------------------------------------------
def plot_chart1():
    data = pd.DataFrame({
        "industry": ["기계", "운송장비", "전기전자", "철강", "목재종이", "음식료", "비금속", "섬유의복", "기타", "석유화학"],
        "emp_delta": [-3979, -129, -116, -112, -48, -25, -2, 0, 25, 54]
    }).sort_values("emp_delta", ascending=True)

    fig, ax = plt.subplots(figsize=(10, 5.5))
    ax.grid(True, linestyle="--", alpha=0.5)
    colors = ["#b91c1c" if x < 0 else "#2563eb" for x in data["emp_delta"]]
    bars = ax.barh(data["industry"], data["emp_delta"], color=colors, height=0.6)

    ax.axvline(0, color="#0f172a", linewidth=1.2, linestyle="--")

    for bar in bars:
        width = bar.get_width()
        ha = "right" if width < 0 else "left"
        offset = -80 if width < 0 else 80
        ax.annotate(
            f"{width:+,d}명",
            xy=(width, bar.get_y() + bar.get_height() / 2),
            xytext=(offset, 0),
            textcoords="offset points",
            ha=ha,
            va="center",
            fontsize=9.5,
            fontweight="bold",
            color="#1e293b"
        )

    ax.set_title("[Q2-2] 2026Q2 업종별 고용 순증감 인원 (기계 집중도 91.9%)", fontsize=13, pad=15, fontweight="bold")
    ax.set_xlabel("전년동기대비 고용 순증감 (YoY, 명)", fontsize=11)
    ax.set_xlim(-4500, 1000)
    
    plt.tight_layout()
    save_path = FIGURE_DIR / "chart1_q2_2_hbar.png"
    plt.savefig(save_path, dpi=300)
    plt.close()
    print(f"[저장 완료] {save_path.name}")


# ---------------------------------------------------------------------------
# [Chart 2] Q2-3. 실제 증감 vs 비례배분 기준선 편차 (Grouped Bar Chart)
# ---------------------------------------------------------------------------
def plot_chart2():
    df = pd.DataFrame({
        "industry": ["기계", "전기전자", "운송장비", "철강"],
        "actual": [-3979, -116, -129, -112],
        "expected": [-2282, -1021, -598, -356],
        "excess": [-1697, 905, 469, 244]
    })

    x = np.arange(len(df["industry"]))
    width = 0.35

    fig, ax = plt.subplots(figsize=(9, 5.5))
    ax.grid(True, linestyle="--", alpha=0.5)
    rects1 = ax.bar(x - width/2, df["actual"], width, label="실제 증감 (A)", color="#b91c1c", alpha=0.85)
    rects2 = ax.bar(x + width/2, df["expected"], width, label="비례배분 기준선 (B)", color="#94a3b8", alpha=0.85)

    for i in range(len(df)):
        diff = df["excess"].iloc[i]
        color = "#b91c1c" if diff < 0 else "#166534"
        text = f"기준선 대비 큰 감소: {diff:+,d}명" if diff < 0 else f"감소 억제: {diff:+,d}명"
        ax.text(x[i], df["actual"].iloc[i] - 280, text, ha="center", va="top",
                fontweight="bold", color=color, fontsize=9.5)

    ax.set_title("[Q2-3] 규모를 고려한 비교: 실제 변화 vs 비례 기준선", fontsize=13, pad=15, fontweight="bold")
    ax.set_ylabel("고용 증감 인원 (명)", fontsize=11)
    ax.set_xticks(x)
    ax.set_xticklabels(df["industry"], fontsize=11, fontweight="bold")
    ax.legend(frameon=True, loc="upper right")
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_ylim(-4800, 800)
    
    plt.tight_layout()
    save_path = FIGURE_DIR / "chart2_q2_3_excess.png"
    plt.savefig(save_path, dpi=300)
    plt.close()
    print(f"[저장 완료] {save_path.name}")


# ---------------------------------------------------------------------------
# [Chart 3] Q2-4. 고용 비중(규모) × YoY 증감률(속도) 산점도 (Scatter Plot)
# ---------------------------------------------------------------------------
def plot_chart3():
    data = pd.DataFrame({
        "industry": ["기계", "전기전자", "운송장비", "철강", "석유화학", "음식료", "목재종이", "비금속", "기타"],
        "share": [51.2, 24.4, 14.2, 8.4, 0.5, 0.6, 0.4, 0.2, 0.1],
        "emp_yoy": [-6.34, -0.41, -0.78, -1.14, 9.68, -3.44, -10.15, -0.98, 24.04],
        "emp_delta": [-3979, -116, -129, -112, 54, -25, -48, -2, 25]
    })

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.grid(True, linestyle="--", alpha=0.5)

    sizes = np.clip(data["emp_delta"].abs() * 0.8, 90, 2200)
    colors = [
        "#b91c1c" if (x > 10 and y < -3) else ("#1e3a8a" if x > 5 else "#64748b")
        for x, y in zip(data["share"], data["emp_yoy"])
    ]

    ax.scatter(data["share"], data["emp_yoy"], s=sizes, c=colors, alpha=0.65, edgecolors="black", linewidth=1.5)

    ax.axhline(0, color="gray", linestyle="--", linewidth=1)
    ax.axhline(-3.0, color="#f87171", linestyle=":", linewidth=1.2, label="급감 기준선 (-3.0%)")
    ax.axvline(5.0, color="#60a5fa", linestyle=":", linewidth=1.2, label="주력 업종 기준선 (5.0%)")

    for _, row in data.iterrows():
        offset_y = 1.0 if row["emp_yoy"] >= 0 else -1.2
        ax.annotate(
            row["industry"],
            xy=(row["share"], row["emp_yoy"]),
            xytext=(0, offset_y * 11),
            textcoords="offset points",
            ha="center",
            fontsize=10,
            fontweight="bold"
        )

    ax.set_title("[Q2-4] 고용 비중(규모) × 증감률(속도) 포지셔닝 맵", fontsize=13, pad=15, fontweight="bold")
    ax.set_xlabel("고용 비중 (%)", fontsize=11)
    ax.set_ylabel("고용 전년동기대비 증감률 (YoY, %)", fontsize=11)
    ax.legend(loc="lower right", frameon=True)
    
    plt.tight_layout()
    save_path = FIGURE_DIR / "chart3_q2_4_position.png"
    plt.savefig(save_path, dpi=300)
    plt.close()
    print(f"[저장 완료] {save_path.name}")


# ---------------------------------------------------------------------------
# [Chart 4] Q2-5. 18분기 4대 주력 업종 고용 증감 히트맵 (Matplotlib 순수 구현)
# ---------------------------------------------------------------------------
def plot_chart4():
    quarters = [
        "22Q1", "22Q2", "22Q3", "22Q4",
        "23Q1", "23Q2", "23Q3", "23Q4",
        "24Q1", "24Q2", "24Q3", "24Q4",
        "25Q1", "25Q2", "25Q3", "25Q4",
        "26Q1", "26Q2"
    ]
    industries = ["기계", "전기전자", "운송장비", "철강"]

    matrix = np.array([
        [-2.4, -2.5, -2.4, -2.9, -6.1, -5.4, -5.1, -4.1,  1.5,  1.9,  0.5,  3.7,  4.4,  2.0,  3.4, -1.1, -3.8, -4.0],
        [ 2.8,  2.7,  2.2, -0.7,  1.3,  1.2,  1.9,  4.4,  0.8,  0.4,  0.6, -0.9, -1.3, -1.1, -1.4, -0.4, -0.4, -0.1],
        [-0.3, -0.4, -0.1,  0.4,  1.4,  0.8,  1.1,  0.8,  0.3,  0.1,  0.4, -0.4, -0.4, -0.5, -0.9, -0.2, -0.2, -0.1],
        [ 0.1,  0.1,  0.0, -0.3, -0.4, -0.3, -0.2,  0.0,  0.3,  0.5,  0.5,  0.4,  0.3,  0.0,  0.0, -0.1, -0.1, -0.1]
    ])

    fig, ax = plt.subplots(figsize=(14, 4.2))
    
    # seaborn 없이 matplotlib의 imshow + diverging colormap 사용
    vmax = max(abs(matrix.min()), abs(matrix.max()))
    im = ax.imshow(matrix, cmap="vlag_r", aspect="auto", vmin=-vmax, vmax=vmax)

    # 축 눈금 설정
    ax.set_xticks(np.arange(len(quarters)))
    ax.set_yticks(np.arange(len(industries)))
    ax.set_xticklabels(quarters, fontsize=9.5)
    ax.set_yticklabels(industries, fontsize=10.5, fontweight="bold")

    # 셀 수치 텍스트 표기
    for i in range(len(industries)):
        for j in range(len(quarters)):
            val = matrix[i, j]
            text_color = "white" if abs(val) >= 3.0 else "black"
            ax.text(j, i, f"{val:+.1f}", ha="center", va="center", color=text_color, fontsize=9, fontweight="bold")

    cbar = fig.colorbar(im, ax=ax, pad=0.02)
    cbar.set_label("순증감 인원 (천 명)", fontsize=10)

    ax.set_title("[Q2-5] 18분기 주력 4대 업종 고용 증감 히트맵 (2022Q1–2026Q2, 단위: 천 명)", fontsize=13, pad=15, fontweight="bold")
    
    plt.tight_layout()
    save_path = FIGURE_DIR / "chart4_q2_5_heatmap.png"
    plt.savefig(save_path, dpi=300)
    plt.close()
    print(f"[저장 완료] {save_path.name}")


# ---------------------------------------------------------------------------
# 전체 실행
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=== Q2 시각화 차트 생성 시작 ===")
    plot_chart1()
    plot_chart2()
    plot_chart3()
    plot_chart4()
    print("=== 전체 차트 생성 및 저장 완료 (경로: outputs/figures/) ===")