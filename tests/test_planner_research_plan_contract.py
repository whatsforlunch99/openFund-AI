"""Tests for planner Research Plan contract fields in specialist REQUEST payloads."""

from a2a.message_bus import InMemoryMessageBus
from a2a.acl_message import ACLMessage, Performative
from agents.planner_agent import PlannerAgent
from agents.planner_types import TaskStep
from unittest.mock import MagicMock


def test_create_research_request_includes_research_plan_contract() -> None:
    """Planner REQUEST should carry a stable Research Plan envelope."""
    bus = InMemoryMessageBus()
    mock_llm = MagicMock()
    mock_llm.complete = MagicMock(return_value="price")
    planner = PlannerAgent("planner", bus, llm_client=mock_llm)
    conversation_id = "cid-research-plan"
    planner._user_profile_by_conversation[conversation_id] = "beginner"
    planner._symbol_resolution_by_conversation[conversation_id] = {
        "status": "resolved",
        "listings": [{"symbol_yahoo": "NVDA"}],
    }

    step = TaskStep(agent="websearcher", params={"query": "price of NVDA today"})
    msg = planner.create_research_request(
        "price of NVDA today", step, conversation_id=conversation_id
    )

    assert isinstance(msg.content, dict)
    rp = msg.content.get("research_plan")
    assert isinstance(rp, dict)
    assert rp.get("query_type") == "price"
    assert rp.get("symbols") == ["NVDA"]
    assert rp.get("user_profile") == "beginner"
    assert rp.get("freshness_requirements") == {
        "price_max_age_minutes": 15,
        "fundamentals_max_age_days": 90,
        "news_lookback_days": 7,
    }
    assert rp.get("evidence_requirements") == {
        "min_sources": 2,
        "require_citations": True,
    }


def test_create_research_request_research_plan_defaults_without_resolution() -> None:
    """Research plan should still be present when symbol resolution is unavailable."""
    bus = InMemoryMessageBus()
    mock_llm = MagicMock()
    mock_llm.complete = MagicMock(return_value="compare")
    planner = PlannerAgent("planner", bus, llm_client=mock_llm)

    step = TaskStep(agent="analyst", params={"query": "compare QQQ and SPY"})
    msg = planner.create_research_request("compare QQQ and SPY", step)

    rp = msg.content.get("research_plan")
    assert isinstance(rp, dict)
    assert rp.get("query_type") == "compare"
    assert rp.get("symbols") == []
    assert rp.get("user_profile") == "beginner"


def test_research_plan_query_type_uses_original_conversation_query() -> None:
    """Research plan query_type should be based on original user intent."""
    bus = InMemoryMessageBus()
    mock_llm = MagicMock()
    mock_llm.complete = MagicMock(return_value="compare")
    planner = PlannerAgent("planner", bus, llm_client=mock_llm)
    cid = "cid-query-type-stable"
    planner._original_query_by_conversation[cid] = "compare NVDA and AMD"
    planner._user_profile_by_conversation[cid] = "beginner"
    step = TaskStep(agent="websearcher", params={"query": "price of NVDA today"})

    msg = planner.create_research_request(
        "compare NVDA and AMD", step, conversation_id=cid
    )
    rp = msg.content.get("research_plan")
    assert isinstance(rp, dict)
    assert rp.get("query_type") == "compare"


def test_research_plan_query_type_uses_llm_classification() -> None:
    bus = InMemoryMessageBus()
    mock_llm = MagicMock()
    mock_llm.complete = MagicMock(return_value="news")
    planner = PlannerAgent("planner", bus, llm_client=mock_llm)
    cid = "cid-llm-classification"
    planner._original_query_by_conversation[cid] = (
        "How could recent central bank commentary affect chip equities this quarter?"
    )
    planner._user_profile_by_conversation[cid] = "beginner"
    step = TaskStep(agent="websearcher", params={"query": "latest market reaction"})

    msg = planner.create_research_request("fallback", step, conversation_id=cid)
    rp = msg.content.get("research_plan")
    assert isinstance(rp, dict)
    assert rp.get("query_type") == "news"


def test_research_plan_query_type_falls_back_to_facts_on_invalid_llm_output() -> None:
    bus = InMemoryMessageBus()
    mock_llm = MagicMock()
    mock_llm.complete = MagicMock(return_value="unknown_type")
    planner = PlannerAgent("planner", bus, llm_client=mock_llm)
    cid = "cid-llm-fallback-facts"
    planner._original_query_by_conversation[cid] = "Give me a quick update on Tesla."
    planner._user_profile_by_conversation[cid] = "beginner"
    step = TaskStep(agent="librarian", params={"query": "quick update"})

    msg = planner.create_research_request("fallback", step, conversation_id=cid)
    rp = msg.content.get("research_plan")
    assert isinstance(rp, dict)
    assert rp.get("query_type") == "facts"


def test_research_plan_query_type_falls_back_to_facts_without_llm() -> None:
    bus = InMemoryMessageBus()
    planner = PlannerAgent("planner", bus, llm_client=None)
    step = TaskStep(agent="librarian", params={"query": "compare QQQ and SPY"})
    msg = planner.create_research_request("compare QQQ and SPY", step)
    rp = msg.content.get("research_plan")
    assert isinstance(rp, dict)
    assert rp.get("query_type") == "facts"


def test_build_evidence_ledger_normalizes_specialist_payloads() -> None:
    """Planner should normalize specialist outputs into evidence-ledger facts."""
    bus = InMemoryMessageBus()
    planner = PlannerAgent("planner", bus)
    collected = {
        "librarian": {
            "summary": "NVIDIA has strong data-center exposure.",
            "timestamp": "2026-04-20T01:00:00Z",
            "confidence": 0.8,
        },
        "websearcher": {
            "summary": "NVDA trades near 900.",
            "timestamp": "2026-04-20T01:01:00Z",
            "normalized_fund": [{"symbol": "NVDA", "price": 900.0}],
        },
        "analyst": {
            "summary": "Base scenario shows moderate upside.",
            "confidence": 0.7,
        },
    }

    ledger = planner._build_evidence_ledger(collected)
    assert isinstance(ledger, dict)
    facts = ledger.get("facts")
    assert isinstance(facts, list)
    assert len(facts) >= 3
    assert any(f.get("source") == "librarian" for f in facts)
    assert any(f.get("source") == "websearcher" for f in facts)
    assert any(f.get("source") == "analyst" for f in facts)
    market = ledger.get("market_snapshot")
    assert isinstance(market, dict)
    assert market.get("symbol") == "NVDA"
    assert market.get("price") == 900.0


def test_build_evidence_ledger_reads_nested_analyst_runtime_shape() -> None:
    bus = InMemoryMessageBus()
    planner = PlannerAgent("planner", bus)
    collected = {
        "librarian": {"summary": "Librarian summary"},
        "websearcher": {
            "summary": "Web summary",
            "normalized_fund": [{"symbol": "NVDA", "price": 900.0}],
        },
        "analyst": {
            "analysis": {
                "summary": "Analyst runtime summary",
                "confidence": 0.88,
            }
        },
    }
    ledger = planner._build_evidence_ledger(collected)
    facts = ledger.get("facts") or []
    assert any(
        isinstance(f, dict)
        and f.get("source") == "analyst"
        and f.get("fact") == "Analyst runtime summary"
        for f in facts
    )


def test_planner_inform_to_responder_includes_evidence_ledger() -> None:
    """Final Planner->Responder INFORM should include evidence_ledger contract."""
    bus = InMemoryMessageBus()
    bus.register_agent("responder")
    planner = PlannerAgent("planner", bus)
    cid = "cid-evidence-ledger"
    planner._collected[cid] = {}
    planner._round_pending[cid] = {"librarian", "websearcher", "analyst"}
    planner._user_profile_by_conversation[cid] = "beginner"
    planner._original_query_by_conversation[cid] = "price of NVDA"
    planner._round_number[cid] = 1

    payloads = [
        ("librarian", {"summary": "Librarian facts", "timestamp": "2026-04-20"}),
        (
            "websearcher",
            {
                "summary": "Web facts",
                "timestamp": "2026-04-20T01:01:00Z",
                "normalized_fund": [{"symbol": "NVDA", "price": 900.0}],
            },
        ),
        ("analyst", {"summary": "Analyst view", "confidence": 0.7}),
    ]
    for sender, content in payloads:
        planner.handle_message(
            ACLMessage(
                performative=Performative.INFORM,
                sender=sender,
                receiver="planner",
                content=content,
                conversation_id=cid,
            )
        )

    out = bus.receive("responder", timeout=0.2)
    assert out is not None
    assert out.performative == Performative.INFORM
    assert out.content.get("conversation_id") == cid
    ledger = out.content.get("evidence_ledger")
    assert isinstance(ledger, dict)
    assert isinstance(ledger.get("facts"), list)


def test_recommendation_gate_allows_when_evidence_and_confidence_sufficient() -> None:
    """Planner should allow recommendations when gates pass."""
    bus = InMemoryMessageBus()
    planner = PlannerAgent("planner", bus)
    evidence_ledger = {
        "facts": [
            {"fact": "a", "source": "librarian", "timestamp": "2026-04-20"},
            {"fact": "b", "source": "websearcher", "timestamp": "2026-04-20"},
        ]
    }
    collected = {
        "analyst": {"confidence": 0.81},
        "websearcher": {"normalized_fund": [{"symbol": "NVDA", "price": 900.0}]},
    }
    gate = planner._evaluate_recommendation_gate(collected, evidence_ledger)
    assert gate.get("recommendation_allowed") is True
    assert gate.get("confidence") == 0.81
    assert gate.get("reason_code") == "gate_passed"


def test_recommendation_gate_reads_nested_analyst_confidence() -> None:
    bus = InMemoryMessageBus()
    planner = PlannerAgent("planner", bus)
    gate = planner._evaluate_recommendation_gate(
        {
            "analyst": {"analysis": {"confidence": 0.82}},
            "websearcher": {"normalized_fund": [{"symbol": "NVDA", "price": 900.0}]},
        },
        {
            "facts": [
                {"fact": "one", "source": "librarian", "timestamp": "2026-04-20"},
                {"fact": "two", "source": "websearcher", "timestamp": "2026-04-20"},
            ]
        },
        query_type="thesis",
    )
    assert gate.get("recommendation_allowed") is True
    assert gate.get("confidence") == 0.82


def test_build_final_response_object_uses_caveated_final_text() -> None:
    bus = InMemoryMessageBus()
    planner = PlannerAgent("planner", bus)
    fro = planner._build_final_response_object(
        "CAVEATED FINAL",
        {"facts": [{"fact": "f"}]},
        {"recommendation_allowed": False, "reason_code": "low_confidence"},
        original_query="user q",
        symbols=["NVDA"],
        collected={
            "analyst": {
                "risk_factors": ["model risk"],
                "limitations": ["sample"],
                "scenario_outcomes": [{"scenario": "base"}],
                "confidence": 0.5,
            }
        },
    )
    assert fro.get("summary") == "CAVEATED FINAL"
    assert fro.get("query") == "user q"
    assert fro.get("symbols") == ["NVDA"]
    assert fro.get("disclaimer_required") is True
    assert fro.get("recommendation", {}).get("allowed") is False
    assert fro.get("analysis", {}).get("confidence") == 0.5
    assert fro.get("risks") == ["model risk"]


def test_recommendation_gate_blocks_when_evidence_or_confidence_insufficient() -> None:
    """Planner should block recommendations when either gate fails."""
    bus = InMemoryMessageBus()
    planner = PlannerAgent("planner", bus)
    low_conf_gate = planner._evaluate_recommendation_gate(
        {"analyst": {"confidence": 0.5}, "websearcher": {"normalized_fund": [{"symbol": "NVDA", "price": 900.0}]}},
        {"facts": [{"fact": "one", "source": "websearcher", "timestamp": "2026-04-20"}]},
    )
    assert low_conf_gate.get("recommendation_allowed") is False
    assert low_conf_gate.get("reason_code") in {
        "insufficient_evidence",
        "low_confidence",
        "stale_or_missing_market_data",
    }


def test_recommendation_gate_blocks_for_non_advisory_query_type() -> None:
    bus = InMemoryMessageBus()
    planner = PlannerAgent("planner", bus)
    gate = planner._evaluate_recommendation_gate(
        {
            "analyst": {"confidence": 0.9},
            "websearcher": {"normalized_fund": [{"symbol": "NVDA"}, {"symbol": "AMD", "price": 123.0}]},
        },
        {
            "facts": [
                {"fact": "one", "source": "librarian", "timestamp": "2026-04-20"},
                {"fact": "two", "source": "websearcher", "timestamp": "2026-04-20"},
            ]
        },
        query_type="price",
    )
    assert gate.get("recommendation_allowed") is False
    assert gate.get("reason_code") == "query_type_not_recommendation"


def test_recommendation_gate_blocks_when_freshness_is_stale() -> None:
    bus = InMemoryMessageBus()
    planner = PlannerAgent("planner", bus)
    gate = planner._evaluate_recommendation_gate(
        {
            "analyst": {"analysis": {"confidence": 0.9}},
            "websearcher": {
                "normalized_fund": [{"symbol": "NVDA", "price": 900.0}],
                "freshness": {"price_is_fresh": False},
            },
        },
        {
            "facts": [
                {"fact": "one", "source": "librarian", "timestamp": "2026-04-20"},
                {"fact": "two", "source": "websearcher", "timestamp": "2026-04-20"},
            ]
        },
        query_type="thesis",
    )
    assert gate.get("recommendation_allowed") is False
    assert gate.get("reason_code") == "stale_or_missing_market_data"


def test_research_plan_query_type_cached_per_conversation() -> None:
    bus = InMemoryMessageBus()
    from unittest.mock import MagicMock

    mock_llm = MagicMock()
    mock_llm.complete = MagicMock(return_value="compare")
    planner = PlannerAgent("planner", bus, llm_client=mock_llm)
    cid = "cid-query-type-cache"
    planner._original_query_by_conversation[cid] = "compare NVDA and AMD"
    planner._user_profile_by_conversation[cid] = "beginner"
    step = TaskStep(agent="websearcher", params={"query": "price of NVDA"})

    _ = planner.create_research_request("compare NVDA and AMD", step, conversation_id=cid)
    _ = planner.create_research_request("compare NVDA and AMD", step, conversation_id=cid)
    assert mock_llm.complete.call_count == 1


def test_planner_inform_to_responder_includes_recommendation_allowed() -> None:
    """Planner final INFORM should carry recommendation gate decision fields."""
    bus = InMemoryMessageBus()
    bus.register_agent("responder")
    planner = PlannerAgent("planner", bus)
    cid = "cid-recommendation-gate"
    planner._collected[cid] = {}
    planner._round_pending[cid] = {"librarian", "websearcher", "analyst"}
    planner._user_profile_by_conversation[cid] = "beginner"
    planner._original_query_by_conversation[cid] = "should I buy NVDA?"
    planner._round_number[cid] = 1

    payloads = [
        ("librarian", {"summary": "Librarian facts", "timestamp": "2026-04-20"}),
        (
            "websearcher",
            {
                "summary": "Web facts",
                "timestamp": "2026-04-20T01:01:00Z",
                "normalized_fund": [{"symbol": "NVDA", "price": 900.0}],
            },
        ),
        ("analyst", {"summary": "Analyst view", "confidence": 0.9}),
    ]
    for sender, content in payloads:
        planner.handle_message(
            ACLMessage(
                performative=Performative.INFORM,
                sender=sender,
                receiver="planner",
                content=content,
                conversation_id=cid,
            )
        )

    out = bus.receive("responder", timeout=0.2)
    assert out is not None
    assert isinstance(out.content.get("recommendation"), dict)
    assert out.content["recommendation"].get("recommendation_allowed") in {True, False}
    fro = out.content.get("final_response_object")
    assert isinstance(fro, dict)
    assert isinstance(fro.get("summary"), str)
    assert isinstance(fro.get("evidence"), list)
    assert isinstance(fro.get("recommendation"), dict)
