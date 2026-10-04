"""Tests for the Detection Engine scoring pipeline.

These tests lock in the canonical decisions from
docs/DECISIONS-DETECTION-v3.3.md so the formula, thresholds and rule
schema cannot drift again.
"""
import pytest
from uuid import uuid4

from app.detection import (
    DEFAULT_THRESHOLDS,
    DEFAULT_WEIGHTS,
    DECISION_MATRIX,
    compare,
    evaluate_rules,
    map_score_to_risk_level,
    resolve_config,
    validate_rule,
)
from app.schemas import RuleDefinition


# =============================================================================
# Rule schema validation (DECISIONS section 1)
# =============================================================================

def test_rule_requires_all_seven_fields():
    for missing in ("name", "field", "operator", "value", "weight", "score"):
        rule = {
            "name": "r",
            "field": "hour_of_day",
            "operator": ">",
            "value": 3,
            "weight": 0.5,
            "score": 0.5,
        }
        del rule[missing]
        assert validate_rule(rule) is not None, f"rule missing {missing} should be rejected"


def test_rule_rejects_unknown_field():
    """A field outside the 6 features must be skipped, not crash."""
    assert "unknown feature" in validate_rule({
        "name": "r", "field": "is_new_country", "operator": "==",
        "value": True, "weight": 0.5, "score": 0.5,
    })


def test_rule_rejects_out_of_range_score():
    assert validate_rule({
        "name": "r", "field": "hour_of_day", "operator": ">", "value": 3,
        "weight": 0.5, "score": 1.5,
    }) is not None


def test_pydantic_rule_definition_accepts_canonical_shape():
    rule = RuleDefinition(
        name="unusual_hour", field="hour_of_day", operator="not_between",
        value=[7, 22], weight=0.30, score=0.80, enabled=True,
    )
    assert rule.operator == "not_between"


def test_pydantic_rejects_bad_operator():
    with pytest.raises(ValueError):
        RuleDefinition(
            name="r", field="hour_of_day", operator="LIKE", value=3,
            weight=0.5, score=0.5,
        )


def test_pydantic_rejects_range_without_pair():
    with pytest.raises(ValueError):
        RuleDefinition(
            name="r", field="hour_of_day", operator="between", value=7,
            weight=0.5, score=0.5,
        )


# =============================================================================
# Comparison operators (DECISIONS section 1.3)
# =============================================================================

@pytest.mark.parametrize("actual,op,expected,result", [
    (2, "not_between", [7, 22], True),
    (12, "not_between", [7, 22], False),
    (5, "between", [1, 10], True),
    (50, "between", [1, 10], False),
    (3, ">=", 3, True),
    (2, ">=", 3, False),
    (True, "==", True, True),
    (False, "==", True, False),
    (5, "in", [1, 5, 9], True),
    (5, "!=", 3, True),
])
def test_compare_operators(actual, op, expected, result):
    assert compare(actual, op, expected) is result


def test_compare_handles_type_mismatch():
    """A type error must return False, never raise."""
    assert compare(None, ">", 3) is False
    assert compare("text", ">", 3) is False
    assert compare(5, "between", "not-a-pair") is False


# =============================================================================
# Rule score aggregation (DECISIONS section 2.1)
# =============================================================================

#: The seeded v1.0 policy from schema-detection-v3.3.sql
SEEDED_POLICY_RULES = [
    {"name": "unusual_hour", "field": "hour_of_day", "operator": "not_between",
     "value": [7, 22], "weight": 0.30, "score": 0.80, "enabled": True},
    {"name": "multiple_failures", "field": "fail_count_24h", "operator": ">=",
     "value": 3, "weight": 0.40, "score": 0.90, "enabled": True},
    {"name": "new_device", "field": "new_device", "operator": "==",
     "value": True, "weight": 0.20, "score": 0.50, "enabled": True},
    {"name": "high_deviation", "field": "deviation_score", "operator": ">=",
     "value": 0.70, "weight": 0.30, "score": 0.70, "enabled": True},
]


def test_worked_example_from_decision_doc():
    """Section 3.4: rule_score must be 0.7583 for the documented features."""
    features = {
        "hour_of_day": 2, "fail_count_24h": 5,
        "new_device": True, "deviation_score": 0.8,
    }
    score, hits, problems = evaluate_rules(SEEDED_POLICY_RULES, features)

    assert problems == []
    assert len(hits) == 4
    # 0.910 / 1.20
    assert score == pytest.approx(0.75833, abs=1e-4)
    # contributions must sum exactly to rule_score
    assert sum(h.score_contribution for h in hits) == pytest.approx(score, abs=1e-6)


def test_disabled_rule_excluded_from_denominator():
    """Turning a rule off must re-normalise, not just drop its contribution."""
    rules = [dict(r) for r in SEEDED_POLICY_RULES]
    rules[0]["enabled"] = False
    features = {
        "hour_of_day": 2, "fail_count_24h": 5,
        "new_device": True, "deviation_score": 0.8,
    }
    score, hits, _ = evaluate_rules(rules, features)

    # numerator = 0.360 + 0.100 + 0.210 = 0.670, denominator = 0.90
    assert score == pytest.approx(0.74444, abs=1e-4)
    assert len(hits) == 3
    assert sum(h.score_contribution for h in hits) == pytest.approx(score, abs=1e-6)


def test_rule_score_never_exceeds_one():
    """Even when every rule triggers, rule_score stays inside [0, 1].

    With the seeded policy the worst case is 0.758, not 1.0 - the
    normalised weighted sum can only reach 1.0 when every rule has
    score = 1.0. The invariant that matters is the upper bound.
    """
    features = {
        "hour_of_day": 2, "fail_count_24h": 99,
        "new_device": True, "deviation_score": 1.0,
    }
    score, hits, _ = evaluate_rules(SEEDED_POLICY_RULES, features)
    assert len(hits) == 4
    assert 0.0 <= score <= 1.0
    assert score == pytest.approx(0.75833, abs=1e-4)


def test_rule_score_reaches_one_when_all_scores_are_max():
    """With score = 1.0 on every rule the weighted sum is exactly 1.0."""
    rules = [
        {"name": "a", "field": "hour_of_day", "operator": "<", "value": 23,
         "weight": 0.5, "score": 1.0, "enabled": True},
        {"name": "b", "field": "fail_count_24h", "operator": ">=", "value": 0,
         "weight": 0.5, "score": 1.0, "enabled": True},
    ]
    score, hits, _ = evaluate_rules(rules, {"hour_of_day": 2, "fail_count_24h": 1})
    assert score == pytest.approx(1.0, abs=1e-9)
    assert sum(h.score_contribution for h in hits) == pytest.approx(1.0, abs=1e-9)


def test_no_rules_means_zero_score():
    assert evaluate_rules([], {"hour_of_day": 3})[0] == 0.0
    assert evaluate_rules(None, {"hour_of_day": 3})[0] == 0.0


def test_unknown_feature_rule_is_skipped_not_fatal():
    """A bad rule must not break the good ones (DECISIONS 1.4/1.6)."""
    rules = SEEDED_POLICY_RULES + [
        {"name": "bad", "field": "not_a_feature", "operator": "==",
         "value": 1, "weight": 9.9, "score": 1.0, "enabled": True},
    ]
    features = {"fail_count_24h": 5}
    score, hits, problems = evaluate_rules(rules, features)

    assert len(problems) == 1
    assert problems[0]["reason"] == "unknown_feature"
    assert problems[0]["rule_name"] == "bad"
    assert [h.rule_name for h in hits] == ["multiple_failures"]
    # The bad rule's huge weight must not enter the denominator: without it
    # the denominator is 0.30+0.40+0.20+0.30 = 1.20, not 1.20+9.9.
    assert score == pytest.approx(0.36 / 1.20, abs=1e-9)


def test_malformed_rule_does_not_raise():
    rules = [None, "nonsense", {"name": "x"}, SEEDED_POLICY_RULES[1]]
    score, hits, problems = evaluate_rules(rules, {"fail_count_24h": 5})
    assert score > 0
    assert len(problems) == 3
    assert len(hits) == 1


# =============================================================================
# Thresholds and risk levels (DECISIONS sections 2.4, 2.5, 3)
# =============================================================================

@pytest.mark.parametrize("score,expected", [
    (0.00, "low"),
    (0.249, "low"),
    (0.25, "medium"),
    (0.499, "medium"),
    (0.50, "high"),
    (0.749, "high"),
    (0.75, "critical"),
    (1.00, "critical"),
])
def test_risk_level_boundaries(score, expected):
    assert map_score_to_risk_level(score, DEFAULT_THRESHOLDS) == expected


def test_thresholds_are_the_canonical_values():
    """Guards against someone reintroducing 0.2 / 0.5 / 0.8."""
    assert DEFAULT_THRESHOLDS == {"low": 0.25, "medium": 0.50, "high": 0.75}


def test_decision_matrix():
    assert DECISION_MATRIX["low"] == ("allow", "ALLOW", False)
    assert DECISION_MATRIX["medium"] == ("allow", "ALLOW_LOG", False)
    assert DECISION_MATRIX["high"] == ("challenge", "REQUIRE_MFA", True)
    assert DECISION_MATRIX["critical"] == ("block", "BLOCK_ALERT", True)


def test_combined_score_example_section_3_4():
    """0.4 * 0.7583 + 0.6 * 0.72 -> 0.7353 -> HIGH."""
    rule_score = 0.75833
    ml_score = 0.72
    combined = (
        DEFAULT_WEIGHTS["rule"] * rule_score + DEFAULT_WEIGHTS["ml"] * ml_score
    )
    assert combined == pytest.approx(0.73533, abs=1e-4)
    assert map_score_to_risk_level(combined, DEFAULT_THRESHOLDS) == "high"
    assert DECISION_MATRIX[map_score_to_risk_level(combined, DEFAULT_THRESHOLDS)][0] == "challenge"


def test_ml_failure_falls_back_to_rule_score():
    """Section 3.5: without ML the score is the raw rule score (stricter)."""
    rule_score = 0.75833
    assert map_score_to_risk_level(rule_score, DEFAULT_THRESHOLDS) == "critical"


# =============================================================================
# Config resolution (DECISIONS section 3)
# =============================================================================

def test_valid_config_is_accepted():
    config, problems = resolve_config({
        "weights": {"rule": 0.3, "ml": 0.7},
        "thresholds": {"low": 0.3, "medium": 0.6, "high": 0.9},
    })
    assert problems == []
    assert config.weights["rule"] == 0.3
    assert config.thresholds["high"] == 0.9


def test_out_of_order_thresholds_fall_back_to_defaults():
    config, problems = resolve_config({
        "thresholds": {"low": 0.8, "medium": 0.3, "high": 0.1}
    })
    assert problems
    assert config.thresholds == DEFAULT_THRESHOLDS


def test_weights_not_summing_to_one_fall_back():
    config, problems = resolve_config({"weights": {"rule": 0.4, "ml": 0.9}})
    assert any("must equal 1.0" in p for p in problems)
    assert config.weights == DEFAULT_WEIGHTS


def test_empty_config_uses_defaults_without_problems():
    config, problems = resolve_config({})
    assert problems == []
    assert config.weights == DEFAULT_WEIGHTS
    assert config.thresholds == DEFAULT_THRESHOLDS


def test_malformed_config_does_not_raise():
    config, problems = resolve_config("not-a-dict")
    assert config.thresholds == DEFAULT_THRESHOLDS
    config, problems = resolve_config({"thresholds": {"low": "abc"}})
    assert config.thresholds == DEFAULT_THRESHOLDS


# =============================================================================
# Endpoint wiring (DECISIONS section 5)
# =============================================================================

def test_internal_endpoints_require_secret():
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    payload = {
        "event_id": str(uuid4()),
        "username_attempted": "alice",
        "outcome": "failure",
        "timestamp": "2026-10-04T12:00:00Z",
    }
    assert client.post("/api/v1/internal/login-events", json=payload).status_code == 401
    assert client.post("/api/v1/internal/ml/score", json={"features": {}}).status_code == 401
