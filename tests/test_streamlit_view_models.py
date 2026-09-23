from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from app.view_models import (  # noqa: E402
    evidence_level_value, field_context, industry_option_label, report_download, session_scope,
)


def test_priority_label_is_data_driven():
    assert industry_option_label("기계", "우선점검") == "기계 · 우선점검"
    assert industry_option_label("기계", "관찰") == "기계"


def test_field_context_keeps_session_answers_without_inventing_values():
    questions = [{"question_id": "FQ01", "question": "확인?", "source": "Q1"},
                 {"question_id": "FQ02", "question": "추가 확인?", "source": "WORK24"}]
    context = field_context(questions, {"FQ01": {"checked": True, "answer": "현장 확인 완료"}}, "메모")
    assert context["responses"][0]["checked"] is True
    assert context["responses"][0]["answer"] == "현장 확인 완료"
    assert context["responses"][1]["answer"] is None
    assert context["note"] == "메모"


def test_scope_and_report_download_are_stable_and_utf8():
    assert session_scope("기계", "2026Q2") == "기계::2026Q2"
    raw = report_download({"industry": "기계", "missing": None})
    assert json.loads(raw.decode("utf-8")) == {"industry": "기계", "missing": None}


def test_missing_evidence_is_not_rendered_as_zero():
    assert evidence_level_value({"count": None}) == "상세 미확인"
    assert evidence_level_value({"count": 0}) == "0건"


def test_streamlit_diagnosis_page_smoke():
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(str(ROOT / "src" / "app" / "main.py"), default_timeout=60).run()
    assert not app.exception
    app.sidebar.radio[0].set_value("업종 진단").run()
    assert not app.exception
    assert {tab.label for tab in app.tabs} >= {"채용시장", "현장 확인", "정책·제안", "Copilot", "진단 보고서"}
    labels = {metric.label for metric in app.metric}
    assert {"현재 판정", "산단 확인 유효공고", "고용 증감"} <= labels
