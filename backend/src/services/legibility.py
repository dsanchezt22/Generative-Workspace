"""Legibility copy for the trust spine — server-side runtime automation, NOT
schema.Automation (a client-side module rule).

Pure, deterministic, NEVER LLM (no spend, no injection vector, golden-string
testable). Explicit per-type functions — NOT str.format(**payload) (brace /
KeyError hazard). All interpolated user strings are truncated via `_trunc`.
Composed once at row-creation time and frozen into the summary columns, so
history never rewrites when a template changes. Failure reasons must already be
sanitized by the caller (the `_llm_error_detail` pattern) before reaching here.
"""

from __future__ import annotations

from src.schema_automations import PreviewField, PreviewPayload

_TRUNC = 200


def _trunc(value: object, n: int = _TRUNC) -> str:
    s = str(value)
    return s if len(s) <= n else s[: n - 1] + "…"


def _watch_label(payload: dict) -> str:
    query = payload.get("query") or {}
    return _trunc(query.get("place") or query.get("food") or payload.get("provider", "value"), 60)


def _autonomous_phrase(action_type: str, payload: dict) -> str:
    """A short verb phrase for a dial-0 hold of an otherwise-autonomous action."""
    if action_type == "watch":
        return f"check {_watch_label(payload)}"
    if action_type == "sort":
        return f'sort "{_trunc(payload.get("module_id", ""))}"'
    if action_type == "track":
        return f"track {_trunc(payload.get('label') or 'a value')}"
    if action_type == "remind":
        return "send you a reminder"
    if action_type == "summarize":
        return "compile a digest"
    if action_type == "draft":
        return f"draft a message to {_trunc(payload.get('recipient', ''))}"
    if action_type == "learn":
        return "learn from your recent activity"
    return action_type


def will_do(action_type: str, payload: dict) -> str:
    """Future-tense line for an approval card."""
    if action_type == "send_email":
        return (
            f"Will send an email to {_trunc(payload.get('to', ''))} — "
            f'"{_trunc(payload.get("subject", ""), 80)}" (simulated in this build)'
        )
    if action_type == "message_human":
        return (
            f"Will message {_trunc(payload.get('to', ''))}: "
            f'"{_trunc(payload.get("text", ""), 80)}" (simulated in this build)'
        )
    if action_type == "pay":
        return (
            f"Would pay ${float(payload.get('amount_usd', 0)):,.2f} to "
            f"{_trunc(payload.get('payee', ''))} — simulated in this build"
        )
    if action_type == "delete_data":
        name = payload.get("target_name") or payload.get("target_id", "")
        return (
            f"Will permanently delete the {payload.get('target', '')} "
            f'"{_trunc(name)}" — cannot be undone'
        )
    if action_type == "archive_module":
        title = payload.get("module_title") or payload.get("module_id", "")
        return f'Will archive "{_trunc(title)}" — restorable from Archived'
    return "Wants to: " + _autonomous_phrase(action_type, payload)


def did_do(action_type: str, payload: dict, result: dict) -> str:
    """Past-tense line for the activity feed. Appends ' (simulated)' whenever the
    executor's result marks the outcome simulated (SEAM-1 stubs)."""
    line = _did_do_core(action_type, payload, result)
    if result.get("simulated"):
        line += " (simulated)"
    return line


def _did_do_core(action_type: str, payload: dict, result: dict) -> str:
    if action_type == "watch":
        state = "flagged" if result.get("flagged") else "all quiet"
        return f"Checked {_watch_label(payload)}: {result.get('value')} — {state}"
    if action_type == "sort":
        return (
            f"Sorted {result.get('n', 0)} items in "
            f'"{_trunc(result.get("module_title", ""))}" by {payload.get("by", "date")}'
        )
    if action_type == "track":
        return (
            f"Tracked {_trunc(result.get('metric', 'value'))}: {result.get('value')} → "
            f'"{_trunc(result.get("module_title", ""))}"'
        )
    if action_type == "remind":
        return f"Reminder — {_trunc(result.get('body', ''))}"
    if action_type == "summarize":
        return f"Compiled the {_trunc(result.get('name', ''))} digest — {result.get('n', 0)} items"
    if action_type == "draft":
        return (
            f'Drafted "{_trunc(result.get("topic", ""))}" — waiting in '
            f'"{_trunc(result.get("module_title", ""))}"'
        )
    if action_type == "learn":
        return f"Learned {result.get('n', 0)} new thing(s) about you"
    if action_type == "archive_module":
        return f'Archived "{_trunc(result.get("module_title", ""))}" — restorable'
    if action_type == "send_email":
        return f"Prepared an email to {_trunc(result.get('to', ''))}"
    if action_type == "message_human":
        return f"Prepared a message to {_trunc(result.get('to', ''))}"
    if action_type == "pay":
        return f"Prepared a payment to {_trunc(result.get('payee', ''))}"
    if action_type == "delete_data":
        return f'Deleted the {result.get("target", "")} "{_trunc(result.get("target_id", ""))}"'
    return action_type


def held_summary(will_do_line: str) -> str:
    return "Holding for your tap: " + will_do_line


def rejected_summary(summary: str) -> str:
    return "You dismissed: " + summary


def expired_summary(summary: str) -> str:
    return "Expired unanswered: " + summary


def failed_summary(automation_name: str, safe_reason: str) -> str:
    return f'"{_trunc(automation_name)}" failed — {_trunc(safe_reason)}'


def auto_disabled_summary(failed_line: str, failures: int) -> str:
    """Append the auto-disable note to a failed row's summary — the runtime turns
    a chronically failing automation off (TRUS_RUNTIME_MAX_FAILURES) rather than
    backing off forever, and says so plainly with the re-enable path."""
    return (
        f"{failed_line} — turned this automation off after {failures} straight "
        "failures; re-enable it from Pulse"
    )


def interrupted_summary(automation_name: str) -> str:
    """One honest 'failed' row for an automation the scheduler was mid-run on when
    the process died (boot reconcile) — never a silent loss."""
    return f'"{_trunc(automation_name)}" was interrupted by a restart mid-run'


def preview(action_type: str, payload: dict) -> PreviewPayload | None:
    """A typed preview for consequential actions only (autonomous holds → None).
    Rendered by trusted components as plain text — no markup path exists."""
    if action_type == "send_email":
        return PreviewPayload(
            title="Email",
            fields=[
                PreviewField(label="To", value=_trunc(payload.get("to", ""))),
                PreviewField(label="Subject", value=_trunc(payload.get("subject", ""))),
            ],
            body=_trunc(payload.get("body", ""), 1000),
            simulated=True,
        )
    if action_type == "message_human":
        return PreviewPayload(
            title="Message",
            fields=[PreviewField(label="To", value=_trunc(payload.get("to", "")))],
            body=_trunc(payload.get("text", ""), 1000),
            simulated=True,
        )
    if action_type == "pay":
        return PreviewPayload(
            title="Payment",
            fields=[
                PreviewField(label="Payee", value=_trunc(payload.get("payee", ""))),
                PreviewField(label="Amount", value=f"${float(payload.get('amount_usd', 0)):,.2f}"),
                PreviewField(label="Memo", value=_trunc(payload.get("memo", ""))),
            ],
            simulated=True,
        )
    if action_type == "delete_data":
        name = payload.get("target_name") or payload.get("target_id", "")
        return PreviewPayload(
            title="Delete",
            fields=[PreviewField(label=str(payload.get("target", "")), value=_trunc(name))],
            body="This cannot be undone.",
            simulated=False,
        )
    if action_type == "archive_module":
        title = payload.get("module_title") or payload.get("module_id", "")
        return PreviewPayload(
            title="Archive",
            fields=[PreviewField(label="Module", value=_trunc(title))],
            simulated=False,
        )
    return None
