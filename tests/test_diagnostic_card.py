from pathlib import Path
import pandas as pd
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from handoff import delivery
ROOT=Path(__file__).resolve().parents[1]
def test_handoff_cards_have_facts_questions_and_pending_review():
    panel=pd.read_csv(ROOT/'outputs/final_model/02_triage/tables/triage_panel.csv')
    cards=delivery.diagnostic_cards(panel[panel.quarter==panel.quarter.max()],panel)
    assert len(cards)==10
    assert cards.observed_facts.notna().all()
    assert cards.check_question.notna().all()
    assert cards.first_owner.notna().all()
    assert cards.reviewer.eq('').all()
    assert cards.field_evidence.eq('').all()
    assert cards.next_review_quarter.eq('2026Q3').all()
    assert cards.followup.str.contains('현장 확인 결과에 따라').all()
    assert cards.scope.str.contains('결정하지 않는다').all()
    assert cards.q3_transition.notna().all()
    assert not cards.q3_transition.str.contains('nan').any()
def test_provenance_not_claimed_as_direct_application():
    r=delivery.rule_registry().set_index('rule_name')
    assert r.loc['A','source_category']=='PROJECT_OPERATIONAL'
    assert r.loc['R_up','source_category']=='PROJECT_OPERATIONAL'
    assert r.loc['E','source_category']=='PRINCIPLE_ADAPTED'
    assert r.reason_for_adaptation.ne('').all()
