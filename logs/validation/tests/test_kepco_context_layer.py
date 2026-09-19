# -*- coding: utf-8 -*-
"""KEPCO context layer 신규 지표 회귀검사.

기존 `tests/test_kepco_power.py` 는 손대지 않았다. 그 파일은 **실제 수집자료**에
대한 검사이고, 여기서는 합성 패널로 **경계조건**을 찍는다.

지키려는 것
    1. 불완전 분기를 완전 분기와 같게 취급하지 않는다 (INCOMPLETE).
    2. 0·결측 분모에서 비율을 만들지 않는다.
    3. stock 을 3개월 합산하지 않고, flow 를 분기말 값으로 쓰지 않는다.
    4. YoY 기준은 정확히 4분기 전이며, 양쪽이 모두 COMPLETE 일 때만 만든다.
    5. 같은 (업종, 월) 이 두 번 들어오면 조용히 지나가지 않는다.
    6. 재시도는 선형이 아니라 지수 백오프이고, 무한재시도가 아니다.
    7. crosswalk confidence 를 근거 없이 올리지 않는다.
    8. Triage 판정(180/128/35/17)은 무슨 일이 있어도 그대로다.
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
from data_collection import collect_kepco_power as ck  # noqa: E402

PROC = ROOT / "data/processed/kepco"
OUT = ROOT / "outputs/kepco_robustness"
LEGAL_DONG_VERIFY = (ROOT / "data/raw/external/kepco/legal_dong/_metadata"
                     / "legal_dong_2021_verification.json")
TRIAGE = ROOT / "outputs/decision_support_final/decision_panel.csv"


# ------------------------------------------------------------------ 합성 패널
def synth_monthly(spec: list[tuple], industry: str = "기계") -> pd.DataFrame:
    """(ym, completeness, power, cust, cntr) 목록 → 월 패널 (지표 부착 전)."""
    rows = []
    for ym, comp, power, cust, cntr in spec:
        rows.append(dict(
            quarter=kp.quarter_of(ym), ym=ym, kicox_industry=industry,
            month_completeness=comp, power_usage_kwh=power,
            cust_cnt=cust, cntr_pwr_kw=cntr, power_usage_kwh_B=power,
            n_biz_types=1, evidence_level="B", biz_types="기계", kicox_mapped=True))
    return pd.DataFrame(rows)


def full_year(base: float, comp: str = "COMPLETE") -> list[tuple]:
    """2024·2025 두 해를 채운다. 2025 는 base 의 절반이라 YoY 는 -50 %."""
    out = []
    for y, mult in ((2024, 1.0), (2025, 0.5)):
        for m in range(1, 13):
            out.append((f"{y}-{m:02d}", comp, base * mult, 100.0, 500.0))
    return out


def build(spec, industry="기계"):
    m = kp._add_monthly_metrics(synth_monthly(spec, industry))
    return m, kp.build_quarterly_panel(m)


# ------------------------------------------------------------------ 지속성
class PersistenceTests(unittest.TestCase):
    def test_three_declining_months_is_persistent(self):
        _m, q = build(full_year(1000.0))
        r = q[q["quarter"] == "2025Q1"].iloc[0]
        self.assertEqual(r["monthly_negative_months"], 3)
        self.assertEqual(r["monthly_signal_consistency"], "PERSISTENT")

    def test_labels_follow_the_declared_definition(self):
        spec = full_year(1000.0)
        # 2025-02, 2025-03 을 전년보다 크게 만들어 감소월을 1개로 줄인다
        spec = [(ym, c, (2000.0 if ym in ("2025-02", "2025-03") else p), cu, cn)
                for ym, c, p, cu, cn in spec]
        _m, q = build(spec)
        r = q[q["quarter"] == "2025Q1"].iloc[0]
        self.assertEqual(r["monthly_negative_months"], 1)
        self.assertEqual(r["monthly_signal_consistency"], "WEAK")

    def test_no_declining_month_is_none_not_incomplete(self):
        spec = [(ym, c, (p * 4 if ym.startswith("2025") else p), cu, cn)
                for ym, c, p, cu, cn in full_year(1000.0)]
        _m, q = build(spec)
        r = q[q["quarter"] == "2025Q1"].iloc[0]
        self.assertEqual(r["monthly_negative_months"], 0)
        self.assertEqual(r["monthly_signal_consistency"], "NONE")

    def test_incomplete_quarter_is_not_treated_as_complete(self):
        """3개월이 다 있지 않으면 지속성을 만들지 않는다."""
        spec = [(ym, ("SOURCE_DEGENERATE" if ym == "2025-02" else c), p, cu, cn)
                for ym, c, p, cu, cn in full_year(1000.0)]
        _m, q = build(spec)
        r = q[q["quarter"] == "2025Q1"].iloc[0]
        self.assertNotEqual(r["completeness"], "COMPLETE")
        self.assertTrue(pd.isna(r["monthly_negative_months"]))
        self.assertEqual(r["monthly_signal_consistency"], "INCOMPLETE")

    def test_labels_are_only_the_declared_five(self):
        _m, q = build(full_year(1000.0))
        self.assertTrue(set(q["monthly_signal_consistency"]) <= set(kp.PERSISTENCE_LEVELS))


# ------------------------------------------------------------------ 정규화 분모
class RatioDenominatorTests(unittest.TestCase):
    def _q2025q1(self, cust, cntr):
        spec = [(ym, c, p, (cust if ym.startswith("2025") else cu),
                 (cntr if ym.startswith("2025") else cn))
                for ym, c, p, cu, cn in full_year(1000.0)]
        _m, q = build(spec)
        return q[q["quarter"] == "2025Q1"].iloc[0]

    def test_zero_customer_count_makes_no_ratio(self):
        r = self._q2025q1(0.0, 500.0)
        self.assertTrue(pd.isna(r["power_usage_per_customer"]))

    def test_zero_contract_power_makes_no_ratio(self):
        r = self._q2025q1(100.0, 0.0)
        self.assertTrue(pd.isna(r["power_usage_per_contract_power"]))

    def test_missing_customer_count_makes_no_ratio(self):
        r = self._q2025q1(np.nan, 500.0)
        self.assertTrue(pd.isna(r["power_usage_per_customer"]))

    def test_missing_contract_power_makes_no_ratio(self):
        r = self._q2025q1(100.0, np.nan)
        self.assertTrue(pd.isna(r["power_usage_per_contract_power"]))

    def test_negative_denominator_makes_no_ratio(self):
        r = self._q2025q1(-5.0, 500.0)
        self.assertTrue(pd.isna(r["power_usage_per_customer"]))

    def test_valid_denominator_makes_the_ratio(self):
        r = self._q2025q1(100.0, 500.0)
        self.assertAlmostEqual(r["power_usage_per_customer"], 1500.0 / 100.0, places=6)
        self.assertAlmostEqual(r["power_usage_per_contract_power"], 1500.0 / 500.0,
                               places=6)


# ------------------------------------------------------------------ flow / stock
class AggregationTests(unittest.TestCase):
    def test_flow_is_summed_over_three_months(self):
        _m, q = build(full_year(1000.0))
        r = q[q["quarter"] == "2024Q1"].iloc[0]
        self.assertAlmostEqual(r["power_usage_kwh"], 3000.0, places=6)

    def test_stock_is_quarter_end_not_summed(self):
        spec = [(ym, c, p, (110.0 if ym == "2024-03" else 100.0), cn)
                for ym, c, p, cu, cn in full_year(1000.0)]
        _m, q = build(spec)
        r = q[q["quarter"] == "2024Q1"].iloc[0]
        self.assertAlmostEqual(r["cust_cnt"], 110.0, places=6)      # 분기말
        self.assertAlmostEqual(r["cust_cnt_mean"], 310.0 / 3, places=6)

    def test_incomplete_quarter_has_no_flow_sum(self):
        spec = [(ym, ("REQUEST_FAILED" if ym == "2024-02" else c), p, cu, cn)
                for ym, c, p, cu, cn in full_year(1000.0)]
        _m, q = build(spec)
        r = q[q["quarter"] == "2024Q1"].iloc[0]
        self.assertEqual(r["completeness"], "REQUEST_FAILED")
        self.assertTrue(pd.isna(r["power_usage_kwh"]))


# ------------------------------------------------------------------ YoY 기준
class YoYBaselineTests(unittest.TestCase):
    def test_yoy_uses_exactly_four_quarters_back(self):
        _m, q = build(full_year(1000.0))
        r = q[q["quarter"] == "2025Q1"].iloc[0]
        self.assertAlmostEqual(r["power_usage_kwh_yoy"], -50.0, places=6)

    def test_first_year_has_no_yoy(self):
        _m, q = build(full_year(1000.0))
        self.assertTrue(q[q["quarter"].str.startswith("2024")]
                        ["power_usage_kwh_yoy"].isna().all())

    def test_yoy_absent_when_baseline_quarter_incomplete(self):
        spec = [(ym, ("NO_DATA" if ym == "2024-02" else c), p, cu, cn)
                for ym, c, p, cu, cn in full_year(1000.0)]
        _m, q = build(spec)
        r = q[q["quarter"] == "2025Q1"].iloc[0]
        self.assertEqual(r["completeness"], "COMPLETE")
        self.assertTrue(pd.isna(r["power_usage_kwh_yoy"]))
        self.assertTrue(str(r["power_yoy_reason"]).startswith("lag4_"))

    def test_stock_yoy_also_requires_both_quarters_complete(self):
        spec = [(ym, ("NO_DATA" if ym == "2024-02" else c), p, cu, cn)
                for ym, c, p, cu, cn in full_year(1000.0)]
        _m, q = build(spec)
        r = q[q["quarter"] == "2025Q1"].iloc[0]
        self.assertTrue(pd.isna(r["cust_cnt_yoy"]))
        self.assertTrue(pd.isna(r["cntr_pwr_kw_yoy"]))

    def test_monthly_yoy_joins_on_calendar_month_not_row_position(self):
        """중간 월이 빠져도 다른 달을 전년동월로 잘못 쓰지 않는다."""
        spec = [s for s in full_year(1000.0) if s[0] != "2024-07"]
        m = kp._add_monthly_metrics(synth_monthly(spec))
        row = m[m["ym"] == "2025-07"].iloc[0]
        self.assertTrue(pd.isna(row["total_power_usage_yoy"]))
        row6 = m[m["ym"] == "2025-06"].iloc[0]
        self.assertAlmostEqual(row6["total_power_usage_yoy"], -50.0, places=6)


# ------------------------------------------------------------------ 중복 방지
class DuplicateTests(unittest.TestCase):
    def test_duplicate_month_is_rejected_not_silently_multiplied(self):
        spec = full_year(1000.0)
        spec.append(("2025-01", "COMPLETE", 500.0, 100.0, 500.0))
        with self.assertRaises(ValueError):
            kp._add_monthly_metrics(synth_monthly(spec))

    def test_quarterly_lag_merge_does_not_multiply_rows(self):
        m = kp._add_monthly_metrics(synth_monthly(full_year(1000.0)))
        q = kp.build_quarterly_panel(m)
        self.assertEqual(len(q), q[["quarter", "kicox_industry"]].drop_duplicates().shape[0])

    def test_already_judged_month_is_not_requested_again(self):
        for comp in ("COMPLETE", "NO_DATA", "SOURCE_DEGENERATE"):
            self.assertFalse(ck.should_request({"completeness": comp}),
                             f"{comp} 를 다시 호출한다")

    def test_failed_month_is_requested_again(self):
        self.assertTrue(ck.should_request({"completeness": "REQUEST_FAILED"}))
        self.assertTrue(ck.should_request(None))

    def test_refresh_overrides_the_cache(self):
        self.assertTrue(ck.should_request({"completeness": "COMPLETE"}, refresh=True))


# ------------------------------------------------------------------ 재시도
class _FakeResponse:
    def __init__(self, status: int):
        self.status = status
        self.body = b'{"data": []}' if status == 200 else b"{}"
        self.error = None if status == 200 else f"HTTPError {status}"

    @property
    def ok(self) -> bool:
        return self.error is None and 200 <= self.status < 300


def _drive(statuses: list[int]):
    """call() 을 가짜 응답으로 돌린다. 실제 네트워크·대기는 없다."""
    seq = list(statuses)
    calls = {"n": 0}
    waits: list[float] = []

    def fake_fetch(url, **kw):
        calls["n"] += 1
        return _FakeResponse(seq[min(calls["n"] - 1, len(seq) - 1)])

    orig_fetch, orig_sleep = ck.fetch, ck.time.sleep
    ck.fetch = fake_fetch
    ck.time.sleep = waits.append
    try:
        res = ck.call("powerUsage/businessType.do", {"year": "2024", "month": "01"},
                      "DUMMY_KEY", {})
    finally:
        ck.fetch, ck.time.sleep = orig_fetch, orig_sleep
    return calls["n"], waits, res


class RetryPolicyTests(unittest.TestCase):
    def test_backoff_is_exponential_not_linear(self):
        w = [ck.backoff_seconds(i) for i in range(3)]
        self.assertEqual(w, [4.0, 8.0, 16.0])
        self.assertAlmostEqual(w[1] / w[0], 2.0)
        self.assertAlmostEqual(w[2] / w[1], 2.0)
        # 선형이면 간격이 일정하다. 그렇지 않음을 명시적으로 찍는다.
        self.assertNotEqual(w[1] - w[0], w[2] - w[1])

    def test_retry_count_is_bounded(self):
        self.assertGreaterEqual(ck.MAX_ATTEMPTS, 2)
        self.assertLessEqual(ck.MAX_ATTEMPTS, 6)
        self.assertLessEqual(sum(ck.backoff_seconds(i)
                                 for i in range(ck.MAX_ATTEMPTS - 1)), 120)

    def test_rate_limit_and_auth_failure_are_distinct(self):
        self.assertTrue(issubclass(ck.RateLimited, Exception))
        self.assertTrue(issubclass(ck.AuthFailed, Exception))
        self.assertIsNot(ck.RateLimited, ck.AuthFailed)

    def test_403_is_not_retried(self):
        """접근거부를 같은 키로 다시 보내지 않는다. 원인도 단정하지 않는다."""
        calls, _waits, res = _drive([403])
        self.assertEqual(calls, 1, "403 을 재시도했다")
        self.assertEqual(res["outcome"], "REQUEST_FAILED")
        # 원인을 단정하지 않는 표현이어야 한다
        self.assertIn("가능성", res["error"])
        self.assertIn("호출 한도로 단정하지 않는다", res["error"])

    def test_server_error_is_retried_with_growing_waits(self):
        calls, waits, res = _drive([500, 500, 200])
        self.assertEqual(calls, 3)
        self.assertEqual(res["outcome"], "OK")
        self.assertEqual(waits, [4.0, 8.0])
        self.assertTrue(all(b > a for a, b in zip(waits, waits[1:])))

    def test_rate_limit_stops_immediately(self):
        with self.assertRaises(ck.RateLimited):
            _drive([429])

    def test_repeated_401_stops_and_does_not_loop_forever(self):
        with self.assertRaises(ck.AuthFailed):
            _drive([401] * 10)

    def test_transient_401_recovers_without_failing(self):
        calls, waits, res = _drive([401, 200])
        self.assertEqual(calls, 2)
        self.assertEqual(res["outcome"], "OK")
        self.assertEqual(waits, [4.0])


# ------------------------------------------------------------------ 키 노출
class SecretHygieneTests(unittest.TestCase):
    def test_api_key_is_not_written_into_source(self):
        for p in (ROOT / "src/data_collection/collect_kepco_power.py",
                  ROOT / "src/context/kepco_power.py",
                  ROOT / "src/build_kepco_robustness.py"):
            t = p.read_text(encoding="utf-8")
            self.assertNotIn("apiKey=", t.replace('apiKey=key', '')
                             .replace('dict(params, apiKey=key', ''),
                             f"소스에 키가 박혔을 수 있다: {p.name}")

    def test_collector_masks_before_writing_metadata(self):
        import inspect
        src = inspect.getsource(ck)
        self.assertIn("S.mask_params", src)
        self.assertIn("S.assert_clean", src)

    def test_key_absent_from_generated_artifacts(self):
        import os
        from data_collection import secrets as S
        key = os.environ.get("KEPCO_API_KEY")
        if not key:
            S.load_env(ROOT)
            key = os.environ.get("KEPCO_API_KEY")
        if not key:
            self.skipTest("키 없음")
        for f in list(PROC.glob("*.csv")) + list(OUT.glob("*")):
            if f.is_file():
                self.assertNotIn(key, f.read_text(encoding="utf-8", errors="replace"),
                                 f"인증키 노출: {f}")


# ------------------------------------------------------------------ crosswalk
class CrosswalkConfidenceTests(unittest.TestCase):
    def setUp(self):
        self.x = kp.load_crosswalk(ROOT)

    def test_confidence_is_not_promoted_above_B(self):
        """공표 정의가 없는 한 A 등급은 존재할 수 없다."""
        self.assertTrue(set(self.x["evidence_level"]) <= {"B", "C", "D"},
                        f"예상 밖 등급: {set(self.x['evidence_level'])}")

    def test_grade_distribution_is_unchanged(self):
        """근거 없이 등급을 올리거나 내리지 않았는지 고정한다."""
        got = self.x["evidence_level"].value_counts().to_dict()
        self.assertEqual(got, {"D": 15, "B": 12, "C": 11})

    def test_no_official_crosswalk_flag(self):
        self.assertTrue((self.x["official_crosswalk"].astype(str).str.upper()
                         == "FALSE").all())

    def test_grade_D_is_never_forced_onto_an_industry(self):
        d = self.x[self.x["evidence_level"] == "D"]
        self.assertTrue((d["kicox_industry"] == "해당없음").all(),
                        "D 등급이 특정 KICOX 업종에 배정됐다")


# ------------------------------------------------------------------ 2021 대체자료
class LegalDong2021Tests(unittest.TestCase):
    def setUp(self):
        if not LEGAL_DONG_VERIFY.exists():
            self.skipTest("2021 검증 파일 미생성")
        self.r = json.loads(LEGAL_DONG_VERIFY.read_text(encoding="utf-8"))

    def test_schema_is_reported_from_the_actual_file(self):
        h = self.r["header_actual"]
        for col in ("년도", "월", "시도", "시군구", "읍면동(법정동)",
                    "산업분류명(대)", "산업분류코드(대)", "산업분류명(중)",
                    "산업분류코드(중)", "고객호수", "판매량", "판매요금"):
            self.assertIn(col, h, f"실제 컬럼에 {col} 이 없다")

    def test_legal_dong_code_is_absent(self):
        """법정동 '코드' 가 없다는 사실을 조용히 넘기지 않는다."""
        self.assertFalse(self.r["legal_dong_code_present"])

    def test_changwon_is_five_districts_not_one(self):
        self.assertEqual(len(self.r["changwon_sigungu"]), 5)
        self.assertTrue(all(s.startswith("창원시") for s in self.r["changwon_sigungu"]))

    def test_masking_is_a_string_token_not_a_number(self):
        self.assertEqual(self.r["masking_token"], "5호미만제거")
        self.assertGreater(self.r["masked_share_pct"], 0)

    def test_verdict_is_not_overstated(self):
        """분류·공간 정의가 다르므로 RECOVERED 로 올리지 않는다."""
        self.assertIn(self.r["substitution_verdict"],
                      {"PARTIAL", "STRUCTURALLY_UNAVAILABLE"})
        self.assertNotEqual(self.r["substitution_verdict"], "RECOVERED")

    def test_truncation_is_recorded_not_hidden(self):
        if self.r["integrity"] != "COMPLETE":
            self.assertTrue(self.r["sheets_unrecoverable"],
                            "잘렸다고 하면서 복원불가 시트를 적지 않았다")
            self.assertLess(self.r["months_recoverable"], self.r["months_declared"])


# ------------------------------------------------------------------ 공간 context
SPATIAL = OUT / "spatial_context_legal_dong.json"
PORTAL = (ROOT / "data/raw/external/kepco/_metadata"
          / "portal_verification_20260919.json")


class SpatialContextTests(unittest.TestCase):
    """법정동 집적도 산출이 '산단 경계 복원'으로 과장되지 않는지."""

    def setUp(self):
        if not SPATIAL.exists():
            self.skipTest("공간 context 미생성")
        self.r = json.loads(SPATIAL.read_text(encoding="utf-8"))

    def test_does_not_claim_a_complex_boundary(self):
        self.assertFalse(self.r["boundary_polygon_available"])
        self.assertIn("상한", self.r["caveat"])

    def test_forbidden_readings_are_recorded(self):
        joined = " ".join(self.r["forbidden_reading"])
        self.assertIn("성산구", joined)
        self.assertIn("창원국가산단", joined)

    def test_address_parsing_is_high_coverage(self):
        """해석률이 낮으면 비중 수치를 믿을 수 없다."""
        self.assertGreaterEqual(self.r["factories_parsed_pct"], 95.0)
        self.assertGreaterEqual(self.r["factories_matched_pct"], 95.0)

    def test_seongsan_is_not_the_whole_of_changwon_manufacturing(self):
        """이 검사가 깨지면 '성산구 = 산단' 표현이 되살아난다."""
        ss = self.r["seongsan_share_of_changwon_mfg_power_pct"]
        self.assertIsNotNone(ss)
        self.assertLess(ss, 90.0, "성산구가 창원 제조업 전력의 대부분이라면 주장이 달라진다")

    def test_dense_dong_are_a_subset_not_everything(self):
        self.assertGreater(self.r["dense_dong_count"], 0)
        self.assertLess(self.r["dense_dong_count"], self.r["changwon_dong_total"])


class PortalVerificationTests(unittest.TestCase):
    """포털 재확인 기록이 근거 없는 단정으로 바뀌지 않았는지."""

    def setUp(self):
        if not PORTAL.exists():
            self.skipTest("포털 확인 기록 없음")
        self.r = json.loads(PORTAL.read_text(encoding="utf-8"))

    def test_no_api_key_recorded(self):
        import os
        from data_collection import secrets as S
        key = os.environ.get("KEPCO_API_KEY")
        if not key:
            S.load_env(ROOT)
            key = os.environ.get("KEPCO_API_KEY")
        if not key:
            self.skipTest("키 없음")
        self.assertNotIn(key, PORTAL.read_text(encoding="utf-8"))

    def test_403_cause_is_not_asserted(self):
        h = self.r["http_403_investigation"]
        self.assertIn("미확정", h["remaining"])
        self.assertIn("기각", h["rejected_hypothesis_1"])
        self.assertIn("근거 없음", h["rejected_hypothesis_2"])

    def test_call_counts_cover_the_three_datasets(self):
        c = self.r["http_403_investigation"]["finding_call_counts_20260919"]
        for name in ("업종별 전력사용량", "산업분류별 전력사용량",
                     "산업분류별 전기사용고객 증감"):
            self.assertGreater(c.get(name, 0), 0, f"{name} 호출이 집계되지 않았다")

    def test_custnum_conflict_is_still_recorded(self):
        c = self.r["custnum_definition_conflict"]
        self.assertIn("건수", c["api_intro_text"])
        self.assertIn("KWH", c["statistics_screen_and_api_values"])
        self.assertIn("NOT_SUITABLE", c["verdict"])

    def test_2021_is_not_claimed_recoverable(self):
        s = self.r["legal_dong_series"]
        self.assertIn("2022년 4월", s["oldest_entry"])
        self.assertIn("2021년 자료는 없다", s["no_2021_file"])


# ------------------------------------------------------------------ Triage 불변성
class TriageInvarianceTests(unittest.TestCase):
    EXPECTED = {"관찰": 128, "추가확인": 35, "우선점검": 17}

    def test_decision_panel_is_unchanged(self):
        if not TRIAGE.exists():
            self.skipTest("decision_panel 없음")
        d = pd.read_csv(TRIAGE, encoding="utf-8-sig")
        self.assertEqual(len(d), 180)
        self.assertEqual(d["stage"].value_counts().to_dict(), self.EXPECTED)

    def test_robustness_run_recorded_the_invariant(self):
        p = OUT / "results_summary.json"
        if not p.exists():
            self.skipTest("강건성 산출물 미생성")
        r = json.loads(p.read_text(encoding="utf-8"))
        inv = r.get("triage_invariance")
        self.assertIsNotNone(inv, "실행이 Triage 불변성을 기록하지 않았다")
        self.assertTrue(inv["unchanged"])
        self.assertEqual(inv["before"]["sha256"], inv["after"]["sha256"])
        for side in ("before", "after"):
            self.assertEqual(inv[side]["rows"], 180)
            self.assertEqual(inv[side]["stages"], self.EXPECTED)

    def test_join_did_not_add_triage_rows(self):
        p = OUT / "kepco_vs_production_employment.csv"
        if not p.exists():
            self.skipTest("비교표 미생성")
        self.assertEqual(len(pd.read_csv(p, encoding="utf-8-sig")), 180)

    def test_kepco_does_not_write_a_stage_column(self):
        """전력자료가 새 판정열을 만들지 않았는지."""
        p = PROC / "kepco_power_quarterly_panel.csv"
        if not p.exists():
            self.skipTest("분기패널 미생성")
        cols = set(pd.read_csv(p, encoding="utf-8-sig", nrows=1).columns)
        self.assertFalse(cols & {"stage", "stage_reason", "E", "R", "A", "P"})

    def test_final_status_is_not_inflated(self):
        p = OUT / "results_summary.json"
        if not p.exists():
            self.skipTest("강건성 산출물 미생성")
        r = json.loads(p.read_text(encoding="utf-8"))
        self.assertIn(r["final_kepco_status"],
                      {"USABLE_CONTEXT", "PARTIAL_CONTEXT", "NOT_SUITABLE"})
        self.assertEqual(r["custnum_assessment"]["status"], "NOT_SUITABLE")


if __name__ == "__main__":
    unittest.main()
