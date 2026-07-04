import json
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from src.schema import ClarifyingQuestion, RefusalError
from src.services import orchestrator
from src.stub_templates import pick_system

from tests.conftest import gen_result


@contextmanager
def _fake_llm(text: str):
    """Exercise the orchestrator's real (non-stub) path with llm.generate mocked.
    Without forcing non-stub, generate_modules short-circuits to stub templates
    and never calls the mock."""
    result = gen_result(text)
    with (
        patch("src.services.orchestrator.llm.is_stub_mode", return_value=False),
        patch("src.services.orchestrator.llm.generate", return_value=result) as gen,
    ):
        yield gen


def test_pick_system_broad_returns_multiple():
    sys = pick_system("plan my japan trip")
    assert len(sys) >= 2
    titles = [m["title"] for m in sys]
    assert len(set(titles)) == len(titles)  # distinct tools


def test_pick_system_focused_returns_one():
    assert len(pick_system("a workout log")) == 1


def test_generate_modules_stub_decomposes(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "stub-test")
    mods = orchestrator.generate_modules("organize my wedding")
    assert len(mods) >= 2
    assert all(m.components for m in mods)


def test_generate_modules_parses_array():
    arr = json.dumps(
        [
            {
                "title": "Itinerary",
                "icon": "🗓️",
                "accent": "sky",
                "components": [{"id": "days", "type": "calendar", "label": "Days"}],
            },
            {
                "title": "Budget",
                "icon": "💰",
                "accent": "amber",
                "components": [{"id": "total", "type": "kpi", "label": "Total", "unit": "$"}],
            },
        ]
    )
    with _fake_llm(arr):
        mods = orchestrator.generate_modules("plan my trip")
    assert [m.title for m in mods] == ["Itinerary", "Budget"]
    assert mods[0].components[0].type == "calendar"
    assert mods[1].components[0].type == "kpi"


def test_generate_modules_wraps_single_object():
    obj = json.dumps(
        {
            "title": "Workout Log",
            "components": [{"id": "e", "type": "text_input", "label": "Exercise"}],
        }
    )
    with _fake_llm(obj):
        mods = orchestrator.generate_modules("track workouts")
    assert len(mods) == 1
    assert mods[0].title == "Workout Log"


def test_generate_modules_refusal():
    with _fake_llm('{"refusal": "Out of scope."}'), pytest.raises(RefusalError):
        orchestrator.generate_modules("do something illicit")


def test_generate_modules_question():
    with _fake_llm('{"question": "Which city?"}'), pytest.raises(ClarifyingQuestion):
        orchestrator.generate_modules("plan a trip")


# --- R-103/R-301: proposal plan alongside the decomposed modules ---


def test_parse_modules_tolerates_modules_object_shape_no_plan():
    """{"modules": [...]} with no "plan" key — already-tolerated shape, verified."""
    obj = json.dumps(
        {
            "modules": [
                {"title": "A", "components": [{"id": "x", "type": "text_input", "label": "X"}]}
            ]
        }
    )
    with _fake_llm(obj):
        mods = orchestrator.generate_modules("plan a trip")
    assert [m.title for m in mods] == ["A"]
    assert orchestrator.last_plan.get() is None


def test_generate_modules_extracts_plan_alongside_modules():
    """{"plan": str, "modules": [...]} — the new shape — surfaces the plan via
    orchestrator.last_plan without changing generate_modules' return type."""
    obj = json.dumps(
        {
            "plan": "I'll build a focused itinerary tracker for your trip.",
            "modules": [
                {"title": "A", "components": [{"id": "x", "type": "text_input", "label": "X"}]}
            ],
        }
    )
    with _fake_llm(obj):
        mods = orchestrator.generate_modules("plan a trip")
    assert [m.title for m in mods] == ["A"]
    assert orchestrator.last_plan.get() == "I'll build a focused itinerary tracker for your trip."


def test_generate_modules_stub_mode_has_no_plan(monkeypatch):
    """Stub mode never fabricates a rationale it didn't actually generate."""
    monkeypatch.setenv("GEMINI_API_KEY", "stub-test")
    orchestrator.generate_modules("organize my wedding")
    assert orchestrator.last_plan.get() is None


def test_generate_modules_bare_array_shape_has_no_plan():
    """The old bare-array shape still works and never claims a plan."""
    with _fake_llm(
        json.dumps(
            [{"title": "A", "components": [{"id": "x", "type": "text_input", "label": "X"}]}]
        )
    ):
        orchestrator.generate_modules("plan a trip")
    assert orchestrator.last_plan.get() is None


# --- R-102: exchange_context reaches the model, never the cache key ---


def test_exchange_context_reaches_the_model_message():
    arr = json.dumps(
        [{"title": "A", "components": [{"id": "x", "type": "text_input", "label": "X"}]}]
    )
    with _fake_llm(arr) as mock_gen:
        orchestrator.generate_modules(
            "plan my unique trip prompt", exchange_context="Q: Which city?\nA: Tokyo"
        )
    prompt_used = mock_gen.call_args[0][0]
    assert "Tokyo" in prompt_used


# --- R-302: recent conversation feeds generation context ---


def test_recent_messages_reach_the_model_message():
    arr = json.dumps(
        [{"title": "A", "components": [{"id": "x", "type": "text_input", "label": "X"}]}]
    )
    history = [
        {"role": "user", "text": "a distinctive prior message about narwhals"},
        {"role": "assistant", "text": "Created Narwhal Tracker"},
    ]
    with _fake_llm(arr) as mock_gen:
        orchestrator.generate_modules("plan my context-aware prompt", recent_messages=history)
    prompt_used = mock_gen.call_args[0][0]
    assert "narwhals" in prompt_used
    assert "Recent conversation:" in prompt_used


def test_no_recent_messages_omits_the_conversation_block():
    arr = json.dumps(
        [{"title": "A", "components": [{"id": "x", "type": "text_input", "label": "X"}]}]
    )
    with _fake_llm(arr) as mock_gen:
        orchestrator.generate_modules("plan a trip with no history")
    prompt_used = mock_gen.call_args[0][0]
    assert "Recent conversation:" not in prompt_used


def test_recent_conversation_bounded_to_about_1200_chars():
    arr = json.dumps(
        [{"title": "A", "components": [{"id": "x", "type": "text_input", "label": "X"}]}]
    )
    history = [{"role": "user", "text": f"message number {i} " * 5} for i in range(30)]
    with _fake_llm(arr) as mock_gen:
        orchestrator.generate_modules("plan my bounded context prompt", recent_messages=history)
    prompt_used = mock_gen.call_args[0][0]
    start = prompt_used.index("Recent conversation:")
    end = prompt_used.index("\n\nReturn the adapted", start)
    block = prompt_used[start:end]
    assert len(block) <= 1200 + 100  # header + slack around the ~1200-char budget


def test_recent_conversation_single_oversized_message_keeps_recent_tail():
    """When even the single most recent turn alone exceeds the ~1200-char
    budget, its TAIL (most recent characters, containing the sentinel) is kept
    rather than dropping the turn entirely."""
    arr = json.dumps(
        [{"title": "A", "components": [{"id": "x", "type": "text_input", "label": "X"}]}]
    )
    history = [{"role": "user", "text": ("x" * 2000) + "TAIL-SENTINEL"}]
    with _fake_llm(arr) as mock_gen:
        orchestrator.generate_modules("plan my oversized turn prompt", recent_messages=history)
    prompt_used = mock_gen.call_args[0][0]
    assert "Recent conversation:" in prompt_used
    assert "TAIL-SENTINEL" in prompt_used


# --- Stage-2b backlog: composed-prompt token cap (_MAX_PROMPT_CHARS) ---


def test_cap_composed_prompt_is_a_noop_under_budget():
    result = orchestrator._cap_composed_prompt("h", "c", "v", "e", "t")
    assert result == "hcvet"


def test_cap_composed_prompt_never_truncates_head_exchange_or_tail():
    head = "User request: a distinctive raw prompt\n\n"
    tail = "\n\nReturn the adapted ModuleConfig JSON array."
    exchange_block = "\n\nConversation so far:\nQ: Which city?\nA: Tokyo" * 20
    context = "C" * 20000
    convo_block = "V" * 20000
    result = orchestrator._cap_composed_prompt(head, context, convo_block, exchange_block, tail)
    assert len(result) <= orchestrator._MAX_PROMPT_CHARS
    assert result.startswith(head)
    assert result.endswith(tail)
    assert exchange_block in result


def test_cap_composed_prompt_truncates_conversation_before_module_context():
    """When the module-context block alone fits comfortably but the
    conversation block is oversized, the conversation is cut (or dropped)
    first — module-context stays fully intact."""
    head = "User request: a distinctive raw prompt\n\n"
    tail = "\n\nReturn the adapted ModuleConfig JSON array."
    exchange_block = "\n\nConversation so far:\nQ: Which city?\nA: Tokyo"
    context = "\n\nExisting modules on canvas:\n- Module: field_a, field_b"
    convo_block = "\n\nRecent conversation:\n" + ("user: filler turn. " * 2000)
    result = orchestrator._cap_composed_prompt(head, context, convo_block, exchange_block, tail)
    assert len(result) <= orchestrator._MAX_PROMPT_CHARS
    assert context in result  # module-context untouched
    assert convo_block not in result  # conversation was cut to fit


def test_cap_composed_prompt_also_truncates_module_context_when_conversation_alone_is_not_enough():
    """When even fully dropping the conversation block isn't enough, the
    module-context detail is trimmed too (still never head/exchange/tail)."""
    head = "User request: another distinctive raw prompt\n\n"
    tail = "\n\nReturn the adapted ModuleConfig JSON array."
    exchange_block = "\n\nConversation so far:\nQ: Which city?\nA: Tokyo"
    context = "\n\nExisting modules on canvas:\n" + ("- Module: field_a, field_b\n" * 2000)
    convo_block = "\n\nRecent conversation:\nuser: hi"
    result = orchestrator._cap_composed_prompt(head, context, convo_block, exchange_block, tail)
    assert len(result) <= orchestrator._MAX_PROMPT_CHARS
    assert result.startswith(head)
    assert result.endswith(tail)
    assert exchange_block in result
    assert convo_block not in result  # conversation dropped first
    assert context not in result  # and module-context also had to be trimmed


def test_cap_composed_prompt_keeps_all_protected_content_when_it_alone_exceeds_cap():
    """Safety-critical branch: when the PROTECTED content (head + exchange +
    tail) alone already exceeds _MAX_PROMPT_CHARS, it is STILL never truncated —
    the raw user prompt and every exchange answer survive in full — and the
    lower-priority blocks (conversation, module-context) are dropped to zero.
    The invariant is "never drop protected content", even at the cost of
    overshooting the cap."""
    user_prompt = "UP-START " + ("u" * 15000) + " UP-END"
    head = f"User request: {user_prompt}\n\n"
    exchange_block = "\n\nConversation so far:\nQ: Which city?\nA: TOKYO-ANSWER-SENTINEL"
    tail = "\n\nReturn the adapted ModuleConfig JSON array."
    context = "\n\nExisting modules on canvas:\n- Module: field_a, field_b"
    convo_block = "\n\nRecent conversation:\nuser: some earlier chatter"
    result = orchestrator._cap_composed_prompt(head, context, convo_block, exchange_block, tail)
    # Protected content is fully intact even though the total exceeds the cap.
    assert user_prompt in result
    assert "TOKYO-ANSWER-SENTINEL" in result
    assert result.startswith(head)
    assert result.endswith(tail)
    assert exchange_block in result
    # The lower-priority blocks were dropped entirely to fit.
    assert convo_block not in result
    assert context not in result
    assert result == head + exchange_block + tail
    # And the composed length is exactly the protected content — nothing else.
    assert len(result) == len(head) + len(exchange_block) + len(tail)
    assert len(result) > orchestrator._MAX_PROMPT_CHARS  # overshoots, by design


def test_seeded_system_wires_the_cap_end_to_end():
    """Integration: _seeded_system itself enforces the cap via its own
    (private) helpers _module_context/_conversation_block — patched here to
    return oversized strings so the wiring (not just the pure helper) is
    proven."""
    huge_context = "\n\nExisting modules on canvas:\n" + ("- Module: field_a, field_b\n" * 2000)
    small_convo = "\n\nRecent conversation:\nuser: hi"
    with (
        patch("src.services.orchestrator._module_context", return_value=huge_context),
        patch("src.services.orchestrator._conversation_block", return_value=small_convo),
    ):
        msg = orchestrator._seeded_system(
            "a distinctive raw user prompt", exchange_context="Q: Which city?\nA: Tokyo"
        )
    assert len(msg) <= orchestrator._MAX_PROMPT_CHARS
    assert "a distinctive raw user prompt" in msg
    assert "Tokyo" in msg
    assert small_convo not in msg
    assert huge_context not in msg


def test_new_component_types_validate():
    from src.schema import ModuleConfig

    cfg = ModuleConfig.model_validate(
        {
            "title": "Everything",
            "components": [
                {"id": "r", "type": "rating", "label": "Rating", "max": 5},
                {"id": "tg", "type": "tags", "label": "Tags"},
                {"id": "k", "type": "kpi", "label": "Total", "unit": "$"},
                {"id": "d", "type": "date", "label": "When"},
                {"id": "tb", "type": "table", "label": "Grid", "columns": ["A", "B"]},
                {"id": "c", "type": "calendar", "label": "Days"},
                {"id": "ch", "type": "chart", "label": "Trend", "chart_type": "line"},
            ],
        }
    )
    assert [c.type for c in cfg.components] == [
        "rating",
        "tags",
        "kpi",
        "date",
        "table",
        "calendar",
        "chart",
    ]


# --- R-701/R-702/R-705: orchestrator emits live-data bindings, never fabricates
# an out-of-domain one ---


def test_decompose_prompt_documents_the_two_launched_domains():
    """Pin the prompt contract: nutrition + weather are the only two domains the
    model may bind, with a concrete example for each."""
    prompt = orchestrator.DECOMPOSE_SYSTEM_PROMPT
    assert '"provider": "nutrition"' in prompt
    assert '"provider": "weather"' in prompt
    assert "calorie" in prompt.lower()
    assert "weather" in prompt.lower()


def test_decompose_prompt_forbids_out_of_domain_fabrication():
    """R-705: the prompt must explicitly rule out any domain besides the two
    launched ones — no fabricated live badge for stocks/flights/etc."""
    prompt = orchestrator.DECOMPOSE_SYSTEM_PROMPT
    assert "do not emit a data_source" in prompt.lower() or "never fabricate" in prompt.lower()
    assert "stocks" in prompt.lower() or "flights" in prompt.lower()


def test_generate_modules_keeps_valid_nutrition_data_source():
    arr = json.dumps(
        [
            {
                "title": "Calorie Tracker",
                "components": [
                    {"id": "food", "type": "text_input", "label": "Food"},
                    {
                        "id": "calories",
                        "type": "kpi",
                        "label": "Calories",
                        "unit": "kcal",
                        "data_source": {
                            "provider": "nutrition",
                            "query": {"food": "banana"},
                        },
                    },
                ],
            }
        ]
    )
    with _fake_llm(arr):
        mods = orchestrator.generate_modules("track calories for a banana")
    assert len(mods) == 1
    kpi = mods[0].components[1]
    assert kpi.type == "kpi"
    assert kpi.data_source is not None
    assert kpi.data_source.provider == "nutrition"
    assert kpi.data_source.query == {"food": "banana"}


def test_generate_modules_strips_out_of_domain_data_source():
    """A well-formed but out-of-domain provider (e.g. "stocks") must NOT drop
    the whole module — it is stripped so the component survives as manual
    entry (R-705)."""
    arr = json.dumps(
        [
            {
                "title": "Stock Tracker",
                "components": [
                    {
                        "id": "price",
                        "type": "kpi",
                        "label": "Share Price",
                        "data_source": {"provider": "stocks", "query": {"ticker": "AAPL"}},
                    },
                ],
            }
        ]
    )
    with _fake_llm(arr):
        mods = orchestrator.generate_modules("track a stock price")
    assert len(mods) == 1
    kpi = mods[0].components[0]
    assert kpi.type == "kpi"
    assert kpi.data_source is None


def test_generate_modules_strips_malformed_data_source():
    """A recognized provider with an out-of-bounds field (refresh_secs below the
    schema's 60s floor) is still malformed — stripped, not module-fatal."""
    arr = json.dumps(
        [
            {
                "title": "Hike Planner",
                "components": [
                    {
                        "id": "forecast",
                        "type": "metric",
                        "label": "Forecast",
                        "formula": "avg",
                        "source_component_id": "forecast",
                        "data_source": {
                            "provider": "weather",
                            "query": {"place": "Tokyo"},
                            "refresh_secs": 5,
                        },
                    },
                ],
            }
        ]
    )
    with _fake_llm(arr):
        mods = orchestrator.generate_modules("plan my Tokyo hike")
    assert len(mods) == 1
    metric = mods[0].components[0]
    assert metric.type == "metric"
    assert metric.data_source is None


def test_generate_modules_valid_weather_data_source_survives():
    arr = json.dumps(
        [
            {
                "title": "Trip Planner",
                "components": [
                    {
                        "id": "forecast",
                        "type": "metric",
                        "label": "Saturday Forecast",
                        "formula": "avg",
                        "source_component_id": "forecast",
                        "data_source": {
                            "provider": "weather",
                            "query": {"place": "Boulder"},
                        },
                    },
                ],
            }
        ]
    )
    with _fake_llm(arr):
        mods = orchestrator.generate_modules("plan my Saturday hike")
    metric = mods[0].components[0]
    assert metric.data_source is not None
    assert metric.data_source.provider == "weather"
