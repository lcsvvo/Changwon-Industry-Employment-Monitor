# -*- coding: utf-8 -*-
"""KEPCO 전력사용량 보조패널 테스트.

지키려는 것
    1. '자료 없음'과 '수집 실패'를 같은 상태로 다루지 않는다.
    2. 불완전 분기의 flow 합계를 만들지 않는다.
    3. stock 과 flow 를 같은 방식으로 집계하지 않는다.
    4. crosswalk 를 공식 대응표로 승격하지 않는다.
    5. 대응 근거가 없는 업종을 KICOX 에 강제 배정하지 않는다.
    6. Triage 산출물을 건드리지 않는다.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from context import kepco_power as kp                 # noqa: E402

XWALK = ROOT / "data/reference/industry_crosswalk/kepco_biztype_to_kicox.csv"
RAW = ROOT / "data/raw/external/kepco"
PROC = ROOT / "data/processed/kepco"
OUT = ROOT / "outputs/kepco_robustness"

KICOX10 = {"기계", "기타", "목재종이", "비금속", "석유화학",
           "섬유의복", "운송장비", "음식료", "전기전자", "철강"}


class CrosswalkTests(unittest.TestCase):
    def setUp(self):
        if not XWALK.exists():
            self.skipTest("crosswalk 미생성")
        self.x = pd.read_csv(XWALK, encoding="utf-8-sig")

    def test_not_declared_official(self):
        """공표된 대응표가 없다. 어떤 행도 official 로 표시되면 안 된다."""
        self.assertTrue((self.x["official_crosswalk"].astype(str).str.upper()
                         == "FALSE").all())

    def test_targets_are_kicox10_or_none(self):
        t = set(self.x["target_kicox_industry"])
        self.assertTrue(t <= KICOX10 | {"해당없음"}, f"예상 밖 대상: {t - KICOX10}")

    def test_unmapped_rows_are_grade_D(self):
        """대응이 없으면 D 여야 한다. 억지로 배정하지 않는다."""
        none = self.x[self.x["target_kicox_industry"] == "해당없음"]
        self.assertTrue((none["mapping_confidence"] == "D").all())
        self.assertTrue((none["mapping_type"] == "unavailable").all())

    def test_mapped_rows_never_grade_A(self):
        """원 분류체계에 공표 정의가 없으므로 A 등급은 나올 수 없다."""
        m = self.x[self.x["target_kicox_industry"] != "해당없음"]
        self.assertFalse((m["mapping_confidence"] == "A").any())

    def test_usage_buckets_not_mapped(self):
        """가정용·공공용 등 용도 구분은 산업이 아니다. KICOX 에 배정하면 안 된다."""
        for biz in ("가정용부문", "순수써비스", "관 공 용", "국 군 용",
                    "유엔군 용", "기타공공용", "사업자 용", "전 철"):
            row = self.x[self.x["source_category"] == biz]
            self.assertEqual(len(row), 1, biz)
            self.assertEqual(row["target_kicox_industry"].iloc[0], "해당없음", biz)

    def test_mining_not_mapped_to_manufacturing(self):
        """'금속비금속' 은 이름과 달리 광업이다. 철강·비금속으로 새면 안 된다."""
        row = self.x[self.x["source_category"] == "금속비금속"]
        self.assertEqual(row["target_kicox_industry"].iloc[0], "해당없음")


class QuarterlyPanelTests(unittest.TestCase):
    def setUp(self):
        if not (RAW / "changwon_business_type_power_monthly.csv").exists():
            self.skipTest("KEPCO 원자료 미수집")
        self.m = kp.build_monthly_panel(ROOT)
        self.q = kp.build_quarterly_panel(self.m)

    def test_quarter_of(self):
        self.assertEqual(kp.quarter_of("2026-01"), "2026Q1")
        self.assertEqual(kp.quarter_of("2026-06"), "2026Q2")
        self.assertEqual(kp.quarter_of("2021-12"), "2021Q4")

    def test_incomplete_quarter_has_no_flow_sum(self):
        """3개월이 다 차지 않은 분기의 powerUsage 합계는 만들지 않는다."""
        bad = self.q[self.q["completeness"] != "COMPLETE"]
        self.assertTrue(bad["power_usage_kwh"].isna().all())

    def test_complete_quarter_has_three_months(self):
        ok = self.q[self.q["completeness"] == "COMPLETE"]
        self.assertTrue((ok["n_months_complete"] == 3).all())
        self.assertTrue(ok["power_usage_kwh"].notna().all())

    def test_states_are_the_four_defined_ones(self):
        self.assertTrue(set(self.q["completeness"]) <=
                        {"COMPLETE", "PARTIAL", "NO_DATA", "REQUEST_FAILED"})

    def test_no_data_is_not_request_failed(self):
        """원자료 결손(2021년)을 수집 실패로 기록하면 안 된다."""
        y21 = self.q[self.q["quarter"].str.startswith("2021")]
        self.assertTrue(len(y21) > 0)
        self.assertFalse((y21["completeness"] == "REQUEST_FAILED").any())
        self.assertTrue((y21["completeness"] == "NO_DATA").all())

    def test_stock_is_not_summed_over_months(self):
        """cust_cnt 는 분기말 값이다. 3개월 합이면 3배가 된다."""
        ok = self.q[(self.q["completeness"] == "COMPLETE")
                    & self.q["cust_cnt"].notna() & (self.q["cust_cnt_mean"] > 0)]
        self.assertTrue(len(ok) > 0)
        ratio = (ok["cust_cnt"] / ok["cust_cnt_mean"]).abs()
        self.assertTrue((ratio < 2.0).all(), "stock 이 합산된 것으로 보인다")

    def test_yoy_only_when_both_quarters_complete(self):
        has = self.q[self.q["power_usage_kwh_yoy"].notna()]
        self.assertTrue((has["completeness"] == "COMPLETE").all())
        self.assertTrue((has["completeness_lag4"] == "COMPLETE").all())

    def test_yoy_never_from_2021_base(self):
        """2021년은 원자료가 비어 있다. 이를 분모로 쓴 YoY 가 있으면 안 된다."""
        bad = self.q[self.q["power_usage_kwh_yoy"].notna()
                     & self.q["quarter"].isin(["2022Q1", "2022Q2", "2022Q3", "2022Q4"])]
        self.assertEqual(len(bad), 0)

    def test_all_kicox10_present_when_mapped(self):
        mapped = set(self.q.loc[self.q["kicox_mapped"], "kicox_industry"])
        self.assertEqual(mapped, KICOX10)


class MacroConsistencyTests(unittest.TestCase):
    """서로 다른 두 API 의 제조업 총량이 맞는지. crosswalk 범위의 실증 확인이다."""

    def setUp(self):
        p = OUT / "macro_check_vs_ksic_manufacturing.csv"
        if not p.exists():
            self.skipTest("강건성 산출물 미생성")
        self.d = pd.read_csv(p, encoding="utf-8-sig")

    def test_mapped_sum_matches_ksic_manufacturing(self):
        r = self.d["ratio_mapped_over_C"].dropna()
        self.assertTrue(len(r) >= 10)
        self.assertTrue(((r > 0.97) & (r < 1.03)).all(),
                        f"제조업 총량 불일치: {r.min():.4f}~{r.max():.4f}")


class NoTriageSideEffectTests(unittest.TestCase):
    """KEPCO 작업이 Triage 산출물을 바꾸지 않았는지."""

    def test_decision_panel_shape_and_stages(self):
        p = ROOT / "outputs/decision_support_final/decision_panel.csv"
        if not p.exists():
            self.skipTest("decision_panel 없음")
        d = pd.read_csv(p, encoding="utf-8-sig")
        self.assertEqual(len(d), 180)
        self.assertEqual(d["stage"].value_counts().to_dict(),
                         {"관찰": 128, "추가확인": 35, "우선점검": 17})

    def test_kepco_outputs_are_in_separate_paths(self):
        """기존 산출 경로를 침범하지 않는다."""
        for p in (PROC, OUT):
            if p.exists():
                self.assertNotIn("decision_support_final", str(p))
                self.assertNotIn("rolling_backtest", str(p))


class CollectionStatusTests(unittest.TestCase):
    def setUp(self):
        p = RAW / "_metadata" / "collection_status.json"
        if not p.exists():
            self.skipTest("수집 상태 파일 없음")
        self.s = json.loads(p.read_text(encoding="utf-8"))

    def test_status_is_not_optimistic(self):
        """업종별이 66개월을 다 못 채웠으므로 전체는 PARTIAL 이어야 한다."""
        self.assertEqual(self.s["dataset_status"]["business_type"], "PARTIAL")
        self.assertEqual(self.s["status"], "PARTIAL")

    def test_spec_verified_separately(self):
        self.assertEqual(self.s["spec_verification"], "VERIFIED")

    def test_no_api_key_in_any_artifact(self):
        """산출물 어디에도 인증키가 남으면 안 된다."""
        import os
        key = os.environ.get("KEPCO_API_KEY")
        if not key:
            from data_collection import secrets as S
            S.load_env(ROOT)
            key = os.environ.get("KEPCO_API_KEY")
        if not key:
            self.skipTest("키 없음")
        targets = list(RAW.rglob("*.json")) + list(RAW.rglob("*.csv"))
        targets += list(PROC.glob("*.csv")) + list(OUT.glob("*"))
        for f in targets:
            if f.is_file():
                self.assertNotIn(key, f.read_text(encoding="utf-8", errors="replace"),
                                 f"인증키 노출: {f}")


if __name__ == "__main__":
    unittest.main()
