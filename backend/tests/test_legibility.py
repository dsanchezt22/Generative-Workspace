"""Legibility golden strings (load-bearing — frozen copy makes these permanent).

The summaries are composed once at row-creation time and frozen into the DB, so
a copy change here is a history-visible change. Explicit per-type functions,
never str.format(**payload) — so a brace in user input must compose safely.
"""

from src.services import legibility
from src.services.legibility import PreviewPayload

# ── will_do (approval cards, future tense) ───────────────────────────────────


def test_will_do_send_email():
    assert (
        legibility.will_do("send_email", {"to": "a@b.co", "subject": "Weekly note"})
        == 'Will send an email to a@b.co — "Weekly note" (simulated in this build)'
    )


def test_will_do_message_human():
    assert (
        legibility.will_do("message_human", {"to": "Sam", "text": "running late"})
        == 'Will message Sam: "running late" (simulated in this build)'
    )


def test_will_do_pay_formats_amount():
    assert (
        legibility.will_do("pay", {"payee": "Landlord", "amount_usd": 1500})
        == "Would pay $1,500.00 to Landlord — simulated in this build"
    )


def test_will_do_delete_data_uses_resolved_name():
    assert (
        legibility.will_do("delete_data", {"target": "module", "target_name": "Old Notes"})
        == 'Will permanently delete the module "Old Notes" — cannot be undone'
    )


def test_will_do_archive_uses_resolved_title():
    assert (
        legibility.will_do("archive_module", {"module_id": "m1", "module_title": "Scratchpad"})
        == 'Will archive "Scratchpad" — restorable from Archived'
    )


def test_will_do_message_human_and_autonomous_phrases():
    assert legibility.will_do("message_human", {"to": "Sam", "text": "hi"}) == (
        'Will message Sam: "hi" (simulated in this build)'
    )
    # A dial-0 hold of each autonomous action gets a "Wants to:" phrase.
    assert legibility.will_do("remind", {}) == "Wants to: send you a reminder"
    assert legibility.will_do("watch", {"query": {"place": "SF"}}) == "Wants to: check SF"
    assert legibility.will_do("sort", {"module_id": "m1"}) == 'Wants to: sort "m1"'
    assert legibility.will_do("track", {"label": "weight"}) == "Wants to: track weight"
    assert legibility.will_do("track", {}) == "Wants to: track a value"
    assert legibility.will_do("summarize", {}) == "Wants to: compile a digest"
    assert legibility.will_do("draft", {"recipient": "Sam"}) == "Wants to: draft a message to Sam"
    assert legibility.will_do("learn", {}) == "Wants to: learn from your recent activity"


# ── did_do (activity feed, past tense) ───────────────────────────────────────


def test_did_do_watch_flagged_and_quiet():
    p = {"query": {"place": "SF"}}
    assert legibility.did_do("watch", p, {"value": 32.4, "flagged": True}) == (
        "Checked SF: 32.4 — flagged"
    )
    assert legibility.did_do("watch", p, {"value": 27.1, "flagged": False}) == (
        "Checked SF: 27.1 — all quiet"
    )


def test_did_do_sort():
    assert (
        legibility.did_do("sort", {"by": "date"}, {"n": 5, "module_title": "Tasks"})
        == 'Sorted 5 items in "Tasks" by date'
    )


def test_did_do_track():
    assert (
        legibility.did_do(
            "track", {}, {"metric": "weight", "value": 180.0, "module_title": "Trends"}
        )
        == 'Tracked weight: 180.0 → "Trends"'
    )


def test_did_do_summarize():
    assert (
        legibility.did_do("summarize", {}, {"name": "Fitness", "n": 3})
        == "Compiled the Fitness digest — 3 items"
    )


def test_did_do_draft():
    assert (
        legibility.did_do("draft", {}, {"topic": "thank-you", "module_title": "Drafts"})
        == 'Drafted "thank-you" — waiting in "Drafts"'
    )


def test_did_do_archive():
    assert (
        legibility.did_do("archive_module", {}, {"module_title": "Scratchpad"})
        == 'Archived "Scratchpad" — restorable'
    )


def test_did_do_remind_and_learn():
    assert legibility.did_do("remind", {}, {"body": "2 not done today: water"}) == (
        "Reminder — 2 not done today: water"
    )
    assert legibility.did_do("learn", {}, {"n": 2}) == "Learned 2 new thing(s) about you"


def test_did_do_appends_simulated_for_stub_results():
    assert legibility.did_do("send_email", {}, {"simulated": True, "to": "a@b.co"}) == (
        "Prepared an email to a@b.co (simulated)"
    )
    assert legibility.did_do("message_human", {}, {"simulated": True, "to": "Sam"}) == (
        "Prepared a message to Sam (simulated)"
    )
    assert legibility.did_do("pay", {}, {"simulated": True, "payee": "P"}) == (
        "Prepared a payment to P (simulated)"
    )


def test_did_do_delete_data():
    assert (
        legibility.did_do("delete_data", {}, {"target": "module", "target_id": "m1"})
        == 'Deleted the module "m1"'
    )


# ── status-line helpers ──────────────────────────────────────────────────────


def test_status_helpers():
    assert legibility.held_summary("Will do X") == "Holding for your tap: Will do X"
    assert legibility.rejected_summary("Will do X") == "You dismissed: Will do X"
    assert legibility.expired_summary("Will do X") == "Expired unanswered: Will do X"
    assert (
        legibility.failed_summary("Weather watch", "TimeoutError")
        == '"Weather watch" failed — TimeoutError'
    )


# ── truncation + brace safety ────────────────────────────────────────────────


def test_trunc_caps_at_200_with_ellipsis():
    out = legibility._trunc("x" * 300)
    assert len(out) == 200
    assert out.endswith("…")


def test_brace_containing_user_input_is_safe():
    # No .format(**payload): a literal brace must not raise or interpolate.
    line = legibility.will_do("send_email", {"to": "a@b.co", "subject": "Hi {name} {0}"})
    assert "{name}" in line and "{0}" in line


def test_preview_only_for_consequential_types():
    assert legibility.preview("watch", {"query": {}}) is None
    assert legibility.preview("summarize", {}) is None
    email = legibility.preview("send_email", {"to": "a@b.co", "subject": "S", "body": "hello"})
    assert isinstance(email, PreviewPayload)
    assert email.simulated is True
    assert email.body == "hello"
    assert [f.label for f in email.fields] == ["To", "Subject"]


def test_preview_pay_fields_and_delete_body():
    pay = legibility.preview("pay", {"payee": "P", "amount_usd": 12.5, "memo": "rent"})
    assert pay is not None and pay.simulated is True
    assert {f.label for f in pay.fields} == {"Payee", "Amount", "Memo"}
    dele = legibility.preview("delete_data", {"target": "page", "target_name": "Home"})
    assert dele is not None and dele.simulated is False
    assert dele.body == "This cannot be undone."


def test_preview_message_and_archive():
    msg = legibility.preview("message_human", {"to": "Sam", "text": "hey"})
    assert msg is not None and msg.simulated is True
    assert msg.body == "hey" and [f.label for f in msg.fields] == ["To"]
    arch = legibility.preview("archive_module", {"module_id": "m", "module_title": "Scratch"})
    assert arch is not None and arch.simulated is False
    assert arch.fields[0].value == "Scratch"


def test_preview_values_truncated():
    long = "y" * 400
    pv = legibility.preview("send_email", {"to": long, "subject": "s", "body": "b"})
    assert pv is not None
    assert len(pv.fields[0].value) == 200
