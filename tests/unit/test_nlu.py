"""
Unit tests for intent detection and entity extraction. Includes a couple of
questions phrased quite differently from the ones used while writing the
rules, to check the planner is matching phrase categories rather than
memorizing specific sentences.
"""

from apps.backend.copilot.nlu import Intent, analyze


def test_active_alarms_intent_and_asset_and_severity():
    r = analyze("Show active critical alarms for Boiler Feed Pump 102 and recommend immediate actions.")
    assert r.intent == Intent.ACTIVE_ALARMS
    assert r.entities.asset_phrase == "Boiler Feed Pump 102"
    assert "critical" in r.entities.severities
    assert r.entities.status == "active"


def test_recurring_investigation_intent():
    r = analyze("Why are compressor discharge pressure alarms repeatedly occurring?")
    assert r.intent == Intent.RECURRING_INVESTIGATION


def test_highest_priority_intent_with_site():
    r = analyze("Which alarm has the highest priority in EastRefinery, and why?")
    assert r.intent == Intent.HIGHEST_PRIORITY
    assert r.entities.site == "EastRefinery"


def test_related_assets_intent():
    r = analyze("What related assets should be inspected for this motor trip alarm?")
    assert r.intent == Intent.RELATED_ASSETS


def test_procedure_lookup_intent():
    r = analyze("Which operating procedure applies to this alarm?")
    assert r.intent == Intent.PROCEDURE_LOOKUP


def test_recommendation_consistency_intent():
    r = analyze("Are the API recommendations consistent with the maintenance manual?")
    assert r.intent == Intent.RECOMMENDATION_CONSISTENCY


def test_full_investigation_default_and_days_extraction():
    r = analyze(
        "Investigate recurring high-severity alarms for Boiler Feed Pump 101 over the last 90 days, "
        "identify likely contributing factors, retrieve the relevant operating procedure, and provide "
        "recommended actions with source evidence."
    )
    assert r.intent == Intent.RECURRING_INVESTIGATION  # "recurring" phrase wins
    assert r.entities.days_back == 90
    assert r.entities.asset_phrase == "Boiler Feed Pump 101"


def test_generalizes_to_an_unseen_phrasing():
    r = analyze("What is going on with Cooling Water Pump 210 lately?")
    assert r.entities.asset_phrase == "Cooling Water Pump 210"
    r2 = analyze("Show me everything active on Unit 5 right now")
    assert r2.intent == Intent.ACTIVE_ALARMS
    assert r2.entities.unit == "Unit 5"


def test_no_asset_mentioned_returns_none_not_a_guess():
    r = analyze("Which alarm has the highest priority in the plant?")
    assert r.entities.asset_phrase is None
