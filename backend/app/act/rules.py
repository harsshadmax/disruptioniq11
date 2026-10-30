"""Workflow rules as pure functions: the plan state machine and separation of duties (blueprint section 4)."""
from app.enums import PlanStatus as S

TRANSITIONS: dict[str, set[str]] = {
    S.DRAFT: {S.PROPOSED, S.CANCELLED, S.STALE},
    S.PROPOSED: {S.PROPOSED, S.APPROVED, S.REJECTED, S.CANCELLED, S.STALE},  # PROPOSED -> PROPOSED is a modification
    S.APPROVED: {S.EXECUTING, S.STALE, S.CANCELLED},
    S.EXECUTING: {S.COMPLETED, S.STALE},
    S.REJECTED: set(), S.COMPLETED: set(), S.STALE: set(), S.CANCELLED: set(),
}
ACTIVE = (S.PROPOSED, S.APPROVED, S.EXECUTING)  # at most one of these per disruption


def can_transition(src: str, dst: str) -> bool:
    return dst in TRANSITIONS.get(src, set())


def approval_block(approver_id: int, proposer_id: int | None, modifier_ids: list[int]) -> str | None:
    """Why this user may not approve, or None. The approver may not have proposed or modified the plan."""
    if proposer_id is not None and approver_id == proposer_id:
        return "approver proposed this plan"
    if approver_id in (modifier_ids or []):
        return "approver modified this plan"
    return None


def execution_block(executor_id: int, approver_id: int | None) -> str | None:
    if approver_id is not None and executor_id == approver_id:
        return "executor approved this plan"
    return None
