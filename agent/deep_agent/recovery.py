"""Durable recovery authority is separate from spending approval."""
from __future__ import annotations

from agent.deep_agent.routing import is_free_tool, job_type


class RecoveryPolicy:
    def __init__(self, state: dict | None = None, *, scope: str | None = None):
        self.scope = scope or (state or {}).get('scope')
        self.failures = dict((state or {}).get('failures') or {}) if (
            not scope or (state or {}).get('scope') == scope) else {}
        self.pending_free = (state or {}).get('pending_free') if self.failures else None
        self.parents = dict((state or {}).get('parents') or {}) if self.failures else {}

    def snapshot(self) -> dict:
        return {'scope': self.scope, 'failures': dict(self.failures),
                'pending_free': self.pending_free, 'parents': dict(self.parents)}

    def failure(self, call_id: str, name: str, result: dict) -> dict:
        ambiguous = result.get('status') == 'submission_unknown'
        free = is_free_tool(name)
        root = self.parents.get(call_id, call_id)
        self.failures.setdefault(root, {'tool': name, 'free': free, 'attempts': 0,
                                          'ambiguous': ambiguous, 'job': job_type(name)})
        if free:
            self.pending_free = root
        return {**result, 'recovery': {
            'original_call_id': root,
            'cause': str(result.get('error') or result.get('reason') or result.get('status'))[:400],
            'automatic_retry': 'free_alternative_only' if free and not ambiguous else 'never',
            'requires_fresh_approval': not free,
            'next_action': 'reconcile_saved_job_or_ask_user' if ambiguous else
                           'one_free_alternative_or_report_blocker' if free else 'propose_retry_for_fresh_approval',
            'alternatives': ['execute for a local transform', 'inspect_media for local measurements'] if free else
                            ['Poll an existing saved job.', 'Propose another allowed route with its cost for approval.'],
        }}

    def authorize_call(self, call_id: str, name: str, original_id: str = '') -> str | None:
        original = original_id or (self.pending_free if is_free_tool(name) else None)
        if not original:
            return None
        original = self.parents.get(original, original)
        if reason := self.authorize_retry(original, name):
            return reason
        self.parents[call_id] = original
        return None

    def success(self, call_id: str, name: str) -> None:
        if is_free_tool(name) and self.parents.get(call_id) == self.pending_free:
            self.pending_free = None

    def authorize_retry(self, original_id: str, name: str) -> str | None:
        original = self.failures.get(original_id)
        if not original or original['ambiguous']:
            return 'Reconcile the saved operation before any retry. Submission may have succeeded.'
        if not original['free'] or not is_free_tool(name):
            return 'Paid retries require a fresh approval. Propose a new dispatch through the approval gate.'
        if original['attempts'] >= 1:
            return 'The single free alternative attempt was used. Report the remaining issue.'
        original['attempts'] += 1
        return None

    def needs_approval(self, name: str) -> bool:
        if is_free_tool(name):
            return False
        return any(not row['free'] and (row['job'] == job_type(name) or row['tool'] == name)
                   for row in self.failures.values())

