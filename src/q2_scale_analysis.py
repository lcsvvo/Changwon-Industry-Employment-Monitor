"""
Q2. 산업·고용 규모 및 집중도 분석 모듈 (src/q2_scale_analysis.py)
====================================================================
창원국가산단 패널 데이터를 바탕으로 고용 증감의 규모효과, 
업종별 기여율, 집중도(HHI), 그리고 주력 업종의 동조화 현상을 분석합니다.

주요 분석 항목:
  - 분기별 순증감 기여율 및 표시 게이트(R), HHI 지수 산출
  - 비례 기대치 대비 규모효과 보정(초과 증감 분석)
  - 기계 업종과 잔여 업종 간 상관성 및 공통 충격(동조화) 검증
  - 상세 추적 대상 업종 임계값(Threshold) 민감도 분석
  - 국면 전이 및 지속기간(Run-length) 분석
  - 사업체 수 및 업체당 평균 고용(규모 분해) 분석
  - 고용보험(EIS) 통계 교차 검증 (자격요건 평가용)
  - 창원상의(CCI) 수출-고용 시계열 추이 분석
"""

import io
import re
from pathlib import Path
import numpy as np
import pandas as pd

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 40)
pd.set_option("display.float_format", lambda x: f"{x:,.2f}")

# ---------------------------------------------------------------------------
# 경로 설정: src/ 내부 또는 루트 어디서 실행해도 프로젝트 루트를 잡도록 설정
# ---------------------------------------------------------------------------
CURRENT_FILE = Path(__file__).resolve()
ROOT_DIR = CURRENT_FILE.parents[1] if CURRENT_FILE.parent.name == "src" else CURRENT_FILE.parent
DATA_DIR = ROOT_DIR / "data"

KICOX_PANEL = DATA_DIR / "processed" / "kicox" / "changwon_state_panel.csv"
EIS_PANEL = DATA_DIR / "processed" / "eis" / "eis_validation_panel.csv"
CCI_DIR = DATA_DIR / "raw" / "cci_report"

# 최신분기는 하드코딩하지 않고 패널에서 계산한다(latest_quarter()).


def hr(title):
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


# ---------------------------------------------------------------------------
# 0. 데이터 로드
# ---------------------------------------------------------------------------
def load_panel():
    if not KICOX_PANEL.exists():
        raise FileNotFoundError(f"[오류] 데이터 파일이 존재하지 않습니다: {KICOX_PANEL}")
    df = pd.read_csv(KICOX_PANEL)
    df["emp_delta"] = df["employment"] - df["employment_lag4"]
    # 분기 문자열이 아니라 달력 순서 키(quarter_index)로 정렬한다.
    return df.sort_values(["industry", "quarter_index"]).reset_index(drop=True)


def latest_quarter(df):
    """패널의 최신분기(달력 순서 기준)."""
    return df.loc[df["quarter_index"].idxmax(), "quarter"]


# ---------------------------------------------------------------------------
# 1. 분기별 기여율 / 표시게이트 R / HHI 지수 산출
# ---------------------------------------------------------------------------
def calculate_quarterly_decomposition(df):
    hr("1. 분기별 기여율 / 표시게이트 R / HHI 산출")
    rows = []
    for q, g in df.groupby("quarter"):
        gv = g[g["employment_yoy_computable"] == True]
        if len(gv) == 0:
            continue
        net = gv["emp_delta"].sum()
        abssum = gv["emp_delta"].abs().sum()
        R = abs(net) / abssum if abssum else np.nan
        top = gv.loc[gv["emp_delta"].abs().idxmax()]
        contrib = top["emp_delta"] / net if net != 0 else np.nan
        hhi = (gv["employment_share"] * 100).pow(2).sum()
        rows.append(
            dict(
                quarter=q,
                net_emp_change=net,
                R=R,
                display_ok=R >= 0.30,          # 공통기준: 기여율 표시 규칙 (R >= 0.30)
                top_industry=top["industry"],
                top_contrib_pct=contrib * 100 if pd.notna(contrib) else np.nan,
                HHI=hhi,
            )
        )
    res = pd.DataFrame(rows)
    print(res.to_string(index=False))
    return res


# ---------------------------------------------------------------------------
# 2. 규모효과 보정 분석 (비례 기대치 대비 초과 증감 검증)
# ---------------------------------------------------------------------------
def analyze_scale_effect(df, quarter=None):
    quarter = quarter or latest_quarter(df)
    hr(f"2. 규모효과 보정 분석 ({quarter})")
    g = df[(df["quarter"] == quarter) & (df["employment_yoy_computable"] == True)].copy()
    total_delta = g["emp_delta"].sum()
    base_total = g["employment_lag4"].sum()
    overall_rate = total_delta / base_total

    g["share_base"] = g["employment_lag4"] / base_total
    g["expected_delta"] = g["share_base"] * total_delta      # 비례배분 기대 증감
    g["excess_delta"] = g["emp_delta"] - g["expected_delta"]  # 초과 편차분

    print(f"전체 고용 YoY(규모 무관 기준선): {overall_rate*100:.2f}%")
    out = g[["industry", "employment_lag4", "emp_delta", "expected_delta", "excess_delta", "employment_yoy"]]
    out = out.sort_values("emp_delta")
    print(out.to_string(index=False))

    print("\n-- YoY%(속도 기준) 순위 --")
    print(g[["industry", "employment_yoy"]].sort_values("employment_yoy").to_string(index=False))
    return g


# ---------------------------------------------------------------------------
# 3. 주력 업종(기계) vs 잔여 업종 간 동조화 및 상관관계 분석
# ---------------------------------------------------------------------------
def evaluate_industry_comovement(df):
    hr("3. 기계 vs 나머지 9개 업종 동조화 분석")

    # 3-1. 최신분기 기계 제외 순증감
    latest = latest_quarter(df)
    g = df[(df["quarter"] == latest) & (df["employment_yoy_computable"] == True)]
    rest_latest = g[g["industry"] != "기계"]["emp_delta"].sum()
    print(f"{latest} 기계 제외 나머지 9개 업종 순증감: {rest_latest:,.0f}명")

    # 3-2. 18분기 전체 상관관계
    mach = df[df["industry"] == "기계"].set_index("quarter")["emp_delta"]
    rest = df[df["industry"] != "기계"].groupby("quarter")["emp_delta"].sum()
    comb = pd.concat([mach.rename("기계"), rest.rename("나머지9개합")], axis=1).dropna()
    corr = comb["기계"].corr(comb["나머지9개합"])
    print(f"\n{len(comb)}분기 상관계수(기계 Δ vs 나머지9개 합 Δ): {corr:.3f}")
    print(comb)

    # 3-3. 동시 순감소 분기 수
    both_neg = comb[(comb["기계"] < 0) & (comb["나머지9개합"] < 0)]
    print(f"\n기계·나머지 동시 순감소 분기: {len(both_neg)}개 / {len(comb)}개")
    print(both_neg)

    # 3-4. 분기별 순감소 업종 수 시계열
    print("\n-- 분기별 순감소 업종 수 --")
    for q, gq in df[df["employment_yoy_computable"] == True].groupby("quarter"):
        n_neg = (gq["emp_delta"] < 0).sum()
        print(f"{q}: {n_neg}/{len(gq)}")

    return comb, corr


# ---------------------------------------------------------------------------
# 4. 상세 추적 대상 업종 임계값(Threshold) 민감도 분석
# ---------------------------------------------------------------------------
def test_threshold_robustness(df, quarter=None):
    quarter = quarter or latest_quarter(df)
    hr("4. 상세추적 기준 임계값 민감도 분석")
    d = df.sort_values(["industry", "quarter_index"])
    last4_abs = d.groupby("industry").tail(4).groupby("industry")["emp_delta"].apply(
        lambda s: s.abs().sum()
    )
    share_latest = d[d["quarter"] == quarter].set_index("industry")["employment_share"] * 100
    combo = pd.concat(
        [share_latest.rename("emp_share_pct"), last4_abs.rename("abs_sum_4q")], axis=1
    ).sort_values("abs_sum_4q", ascending=False)
    print(combo)

    print("\n-- 기준 조합 시나리오별 상세추적 대상 --")
    for share_th, abs_th in [(5, 300), (5, 500), (10, 300), (3, 200), (5, 200)]:
        sel = combo[(combo["emp_share_pct"] >= share_th) & (combo["abs_sum_4q"] >= abs_th)]
        print(f"비중>={share_th}%, 절대합>={abs_th}명 -> {list(sel.index)}")
    return combo


# ---------------------------------------------------------------------------
# 5. 국면 전이확률행렬 & run_length (지속성 검증)
# ---------------------------------------------------------------------------
def state_transition_and_runs(df):
    hr("5. 국면 전이확률행렬 및 run_length 지속기간")
    tv = df[df["valid_transition"] == True]
    trans = pd.crosstab(tv["state"], tv["next_state"])
    trans_prob = trans.div(trans.sum(axis=1), axis=0)
    print("-- 전이 건수 --")
    print(trans)
    print("\n-- 전이확률 (행 기준) --")
    print(trans_prob.round(3))

    runs = df.dropna(subset=["run_id"]).drop_duplicates(subset=["run_id"])
    print("\n-- state별 run_total_length 분포 --")
    print(runs.groupby("state")["run_total_length"].describe()[["count", "mean", "min", "50%", "max"]])

    print(f"\n-- 기계 업종 {df['quarter'].nunique()}분기 국면 이력 --")
    m = df[df["industry"] == "기계"][["quarter", "state", "production_yoy", "employment_yoy"]]
    print(m.to_string(index=False))
    return trans_prob, runs


# ---------------------------------------------------------------------------
# 6. 기계 업종 사업체 수 및 업체당 평균 고용 (규모 분해)
# ---------------------------------------------------------------------------
def check_firm_employment_dynamics(df, industry="기계"):
    hr(f"6. {industry} 사업체 수 및 업체당 고용인원 동태")
    m = df[df["industry"] == industry][["quarter", "employment", "firms_in", "firms_op"]].copy()
    m["emp_per_firm"] = m["employment"] / m["firms_op"]
    print(m.to_string(index=False))
    return m


# ---------------------------------------------------------------------------
# 7. 외부 지표(EIS, CCI) 보조 교차검증
# ---------------------------------------------------------------------------
def read_cci_csv(path):
    """창원상의 보고서 전사본 CSV를 읽는다.

    상단 출처·주석 줄이 '"# 출처: ..."'처럼 따옴표로 시작해 pd.read_csv(comment="#")가
    주석으로 인식하지 못하고 데이터 행으로 읽는다(열 수가 맞지 않아 ParserError).
    따옴표를 벗긴 뒤 '#'으로 시작하는 줄만 걸러내고 읽는다.
    """
    lines = Path(path).read_text(encoding="utf-8-sig").splitlines()
    body = [ln for ln in lines if not ln.strip().lstrip('"').lstrip().startswith("#")]
    return pd.read_csv(io.StringIO("\n".join(body)))


def load_external_indicators():
    hr("7. 외부 지표(EIS, CCI) 교차검증")
    # EIS 고용보험 패널
    if EIS_PANEL.exists():
        eis = pd.read_csv(EIS_PANEL)
        cols = [c for c in ["quarter", "changwon_manufacturing", "eis_manufacturing_yoy_pct"] if c in eis.columns]
        print("\n[EIS 피보험자 동향 최근 시점]")
        print(eis[cols].tail(10).to_string(index=False))

    # CCI 수출 실적 데이터
    if CCI_DIR.exists():
        frames = []
        for f in sorted(CCI_DIR.glob("*.csv")):
            m = re.search(r"(20\d{2}Q[1-4])", f.name)
            if not m:
                continue
            d = read_cci_csv(f)
            if "업종" not in d.columns or "수출_전년동기대비(%)" not in d.columns:
                continue
            d["quarter"] = m.group(1)
            frames.append(d)
        if frames:
            cci = pd.concat(frames, ignore_index=True)
            m = cci[cci["업종"] == "기계"][["quarter", "수출_전년동기대비(%)", "고용_전년동기대비(%)"]]
            # 4개 분기 보고서 전사본을 나열할 뿐이며 시차(선후행) 관계를 추정하지 않는다.
            print("\n[CCI 기계 수출·고용 전년동기대비 (창원상의 보고서 전사본)]")
            print(m.to_string(index=False))


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    df = load_panel()

    calculate_quarterly_decomposition(df)
    analyze_scale_effect(df)
    evaluate_industry_comovement(df)
    test_threshold_robustness(df)
    state_transition_and_runs(df)
    check_firm_employment_dynamics(df)
    load_external_indicators()

    hr("[완료] Q2 산업·고용 규모 및 집중도 정량 분석 파이프라인 실행 종료")