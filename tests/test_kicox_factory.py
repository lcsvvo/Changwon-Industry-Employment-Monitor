from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from evidence.collection import kicox_factory as factory  # noqa: E402


def official(name="에이비씨테크", address="경상남도 창원시 성산구 공단로 10"):
    return {"factory_id": "481230000000001", "company_name": name,
            "factory_address": address,
            "industrial_complex_name": factory.OFFICIAL_COMPLEX_NAME}


def test_official_complex_and_company_normalization():
    row = factory._safe_item({
        "fctryManageNo": "1", "cmpnyNm": "(주) 에이비씨-테크",
        "rnAdres": "경상남도 창원시 성산구 공단로 10",
        "irsttNm": "창원국가산업단지",
    }, "2026-09-23T00:00:00+00:00")
    assert row["industrial_complex_name"] == factory.OFFICIAL_COMPLEX_NAME
    assert factory.normalize_company("주식회사 에이비씨-테크") == "에이비씨테크"
    assert factory.normalize_company("(주) 에이비씨 테크") == "에이비씨테크"


def test_exact_company_and_address_is_confirmed():
    result = factory.match_company(
        "주식회사 에이비씨테크",
        ["경상남도 창원시 성산구 공단로 10 (신촌동)"],
        [official()],
    )
    assert result["status"] == "CONFIRMED"
    assert result["official_evidence"] is True
    assert result["factory_ids"] == "481230000000001"


def test_exact_name_without_address_is_possible_not_confirmed():
    result = factory.match_company("(주)에이비씨테크", [], [official()])
    assert result["status"] == "POSSIBLE"
    assert result["official_evidence"] is False


def test_fuzzy_name_even_with_address_is_never_confirmed():
    result = factory.match_company(
        "에이비씨테크놀로지",
        ["경상남도 창원시 성산구 공단로 10"],
        [official("에이비씨테크놀로지스")],
    )
    assert result["status"] in {"POSSIBLE", "UNKNOWN"}
    assert result["official_evidence"] is False


def test_api_key_is_not_present_in_safe_probe_shape(monkeypatch):
    class FakeClient:
        def request(self, *args, **kwargs):
            return {"http_status": 200, "header": {"resultCode": "00", "resultMsg": "OK"},
                    "format": "XML", "operation_path": "op", "query_parameter": "irsttNm",
                    "body": {"pageNo": "1", "numOfRows": "1", "totalCount": "1"},
                    "items": [{"cmpnyNm": "테스트"}]}

    monkeypatch.setattr(factory, "KicoxFactoryClient", FakeClient)
    result = factory.safe_probe("complex", factory.OFFICIAL_COMPLEX_NAME)
    assert result["api_key_exposed"] is False
    assert "serviceKey" not in str(result)
    assert "company_name" not in str(result)
