"""
Changwon National Industrial Complex: Employment Scale & Contribution Analysis
Module: Core calculations for employment decomposition, scale adjustment, and external validation.
"""

from pathlib import Path
import re
import numpy as np
import pandas as pd

# 출력 옵션 설정
pd.set_option("display.width", 160)
pd.set_option("display.max_columns", 20)
pd.set_option("display.float_format", lambda x: f"{x:,.2f}")

# 경로 동적 설정 (레포지토리 루트 기준)
ROOT_DIR = Path(__file__).resolve().parents[1] if Path(__file__).resolve().parent.name == "src" else Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data"

KICOX_PATH = DATA_DIR / "processed" / "kicox" / "changwon_state_panel.csv"
EIS_PATH = DATA_DIR / "processed" / "eis" / "eis_validation_panel.csv"
CCI_DIR = DATA_DIR / "raw" / "cci_report"

TARGET_QUARTER = "2026Q2"


def load_and_preprocess_panel(filepath: Path) -> pd.DataFrame:
    """KICOX 패널 데이터를 로드하고 기본 고용 차분 지표를 계산합니다."""
    if not filepath.exists():
        raise FileNotFoundError(f"패널 데이터가 존재하지 않습니다: {filepath}")
    
    df = pd.read_csv(filepath)
    df["emp_delta"] = df["employment"] - df["employment_lag4"]
    return df.sort_values(["industry", "quarter"]).reset_index(drop=True)


def calculate_quarterly_decomposition(df: pd.DataFrame) -> pd.DataFrame:
    """
    분기별 고용 순증감 분해, 최대 기여 업종 산출, 
    기여율 표시 게이트(R) 및 고용 집중도(HHI)를 집계합니다.
    """
    results = []
    for quarter, group in df.groupby("quarter"):
        valid = group[group["employment_yoy_computable"] == True]
        if valid.empty:
            continue
            
        net_change = valid["emp_delta"].sum()
        abs_sum_change = valid["emp_delta"].abs().sum()
        
        # 기여율 신뢰성 비율 R (R >= 0.30 필터)
        r_ratio = abs(net_change) / abs_sum_change if abs_sum_change > 0 else np.nan
        
        # 절대 변화량 기준 최대 기여 업종
        dominant = valid.loc[valid["emp_delta"].abs().idxmax()]
        dominant_contrib = (dominant["emp_delta"] / net_change * 100) if net_change != 0 else np.nan
        
        # 고용 점유율 기반 HHI
        hhi = (valid["employment_share"] * 100).pow(2).sum()
        
        results.append({
            "quarter": quarter,
            "net_emp_change": net_change,
            "r_ratio": r_ratio,
            "gate_passed": r_ratio >= 0.30,
            "top_industry": dominant["industry"],
            "top_contribution_pct": dominant_contrib,
            "hhi": hhi
        })
        
    return pd.DataFrame(results)


def analyze_scale_effect(df: pd.DataFrame, quarter: str = TARGET_QUARTER) -> pd.DataFrame:
    """
    기준 시점 고용 규모를 통제하여, 단순 규모에 의한 감소분과 
    산업 고유의 초과 감소분(Excess Shock)을 분리합니다.
    """
    subset = df[(df["quarter"] == quarter) & (df["employment_yoy_computable"] == True)].copy()
    total_delta = subset["emp_delta"].sum()
    base_employment = subset["employment_lag4"].sum()
    benchmark_growth_rate = total_delta / base_employment

    subset["base_share"] = subset["employment_lag4"] / base_employment
    subset["expected_delta"] = subset["base_share"] * total_delta
    subset["excess_delta"] = subset["emp_delta"] - subset["expected_delta"]

    cols = ["industry", "employment_lag4", "emp_delta", "expected_delta", "excess_delta", "employment_yoy"]
    return subset[cols].sort_values("emp_delta")


def evaluate_industry_comovement(df: pd.DataFrame, key_industry: str = "기계") -> tuple:
    """
    주요 업종과 잔여 산업군 간의 상관계수 및 동시 위축 빈도를 분석하여
    공통 대외 충격인지 특정 업종 고유의 충격인지를 판별합니다.
    """
    # 1. 특정 분기 잔여 업종 순증감
    latest_subset = df[(df["quarter"] == TARGET_QUARTER) & (df["employment_yoy_computable"] == True)]
    residual_change = latest_subset[latest_subset["industry"] != key_industry]["emp_delta"].sum()

    # 2. 전 시계열 기준 교차상관
    key_series = df[df["industry"] == key_industry].set_index("quarter")["emp_delta"]
    residual_series = df[df["industry"] != key_industry].groupby("quarter")["emp_delta"].sum()
    
    panel = pd.concat([key_series.rename(key_industry), residual_series.rename("잔여업종합계")], axis=1).dropna()
    correlation = panel[key_industry].corr(panel["잔여업종합계"])
    co_downturn_count = len(panel[(panel[key_industry] < 0) & (panel["잔여업종합계"] < 0)])

    return residual_change, correlation, co_downturn_count, len(panel)


def test_threshold_robustness(df: pd.DataFrame, quarter: str = TARGET_QUARTER) -> pd.DataFrame:
    """
    집중 추적 대상 선정을 위한 고용 비중 및 변화량 절대합 임계값의 민감도를 검증합니다.
    """
    panel = df.sort_values(["industry", "quarter"])
    recent_4q_abs_sum = panel.groupby("industry").tail(4).groupby("industry")["emp_delta"].apply(lambda s: s.abs().sum())
    current_share = panel[panel["quarter"] == quarter].set_index("industry")["employment_share"] * 100

    matrix = pd.concat([current_share.rename("고용비중(%)"), recent_4q_abs_sum.rename("최근4분기_변동절대합")], axis=1)
    return matrix.sort_values("최근4분기_변동절대합", ascending=False)


def check_firm_employment_dynamics(df: pd.DataFrame, target_industry: str = "기계") -> pd.DataFrame:
    """
    가동 사업체 수와 사업체당 평균 고용 인원 간 동태적 변화를 추적합니다.
    """
    ind_df = df[df["industry"] == target_industry][["quarter", "employment", "firms_in", "firms_op"]].copy()
    ind_df["emp_per_operating_firm"] = ind_df["employment"] / ind_df["firms_op"]
    return ind_df.dropna()


def load_external_indicators():
    """행정 지정 요건 및 선행성 검토를 위한 외부 보조 데이터(EIS, CCI)를 확인합니다."""
    # 고용보험 패널 점검
    eis_summary = None
    if EIS_PATH.exists():
        eis_df = pd.read_csv(EIS_PATH)
        target_cols = [c for c in ["quarter", "changwon_manufacturing", "eis_manufacturing_yoy_pct"] if c in eis_df.columns]
        eis_summary = eis_df[target_cols].tail(6)

    # 창원상의 수출 시계열 점검
    cci_summary = None
    if CCI_DIR.exists():
        records = []
        for file in sorted(CCI_DIR.glob("*.csv")):
            match = re.search(r"(20\d{2}Q[1-4])", file.name)
            if not match:
                continue
            temp = pd.read_csv(file, comment="#")
            if "업종" in temp.columns and "수출_전년동기대비(%)" in temp.columns:
                temp["quarter"] = match.group(1)
                records.append(temp)
        if records:
            concat_cci = pd.concat(records, ignore_index=True)
            cci_summary = concat_cci[concat_cci["업종"] == "기계"][["quarter", "수출_전년동기대비(%)", "고용_전년동기대비(%)"]]

    return eis_summary, cci_summary


def main():
    print(">>> 1. 패널 데이터 로드 및 분기별 고용 분해 실행")
    panel_df = load_and_preprocess_panel(KICOX_PATH)
    decomp_df = calculate_quarterly_decomposition(panel_df)
    print(decomp_df.tail(6).to_string(index=False))

    print(f"\n>>> 2. {TARGET_QUARTER} 기준 규모효과 보정 분석")
    scale_adj = analyze_scale_effect(panel_df)
    print(scale_adj.to_string(index=False))

    print("\n>>> 3. 주요 업종(기계) vs 잔여 산업군 동조성 분석")
    res_change, corr, co_down, total_q = evaluate_industry_comovement(panel_df)
    print(f"- {TARGET_QUARTER} 기계 제외 잔여 9개 업종 순증감: {res_change:,.0f}명")
    print(f"- 장기 시계열 상관계수: {corr:.3f}")
    print(f"- 동반 순감소 발생 빈도: {co_down} / {total_q} 분기")

    print("\n>>> 4. 상세 추적 기준 민감도 점검")
    sensitivity = test_threshold_robustness(panel_df)
    print(sensitivity.to_string())

    print("\n>>> 5. 기계 업종 사업체당 고용인원 시계열 추이")
    firm_dynamics = check_firm_employment_dynamics(panel_df)
    print(firm_dynamics.tail(6).to_string(index=False))

    print("\n>>> 6. 외부 지표(EIS, CCI) 교차검증 상태")
    eis, cci = load_external_indicators()
    if eis is not None:
        print("\n[EIS 피보험자 동향 최근 시점]\n", eis.to_string(index=False))
    if cci is not None:
        print("\n[CCI 기계 수출-고용 시차 관측치]\n", cci.to_string(index=False))


if __name__ == "__main__":
    main()