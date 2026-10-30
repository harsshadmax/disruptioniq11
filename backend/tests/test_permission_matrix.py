"""The permission matrix from blueprint section 4, checked as data (no database needed)."""
import pytest

from app.auth.permissions import PERMISSIONS, can
from app.enums import PlanType, Role

ANALYST, MANAGER, OPERATOR = Role.ANALYST, Role.MANAGER, Role.OPERATOR
PROCUREMENT, ADMIN = Role.PROCUREMENT, Role.ADMIN


@pytest.mark.parametrize("role", list(Role))
def test_everyone_can_view(role):
    assert can(role, "view")


@pytest.mark.parametrize("ptype", [PlanType.REALLOCATE, PlanType.SPLIT])
def test_manager_approves_physical_plans_only(ptype):
    approvers = {r for r in Role if can(r, f"plan.approve:{ptype}")}
    assert approvers == {MANAGER}


@pytest.mark.parametrize("ptype", [PlanType.EXPEDITE, PlanType.ALT_SUPPLIER])
def test_procurement_approves_procurement_plans_only(ptype):
    approvers = {r for r in Role if can(r, f"plan.approve:{ptype}")}
    assert approvers == {PROCUREMENT}


def test_administrator_has_no_approval_or_execution_rights():
    for perm in PERMISSIONS:
        if perm.startswith(("plan.approve", "plan.execute", "plan.propose")):
            assert not can(ADMIN, perm), perm


def test_only_analyst_proposes():
    assert {r for r in Role if can(r, "plan.propose")} == {ANALYST}


def test_executor_roles_differ_from_approver_roles():
    for ptype in PlanType:
        approvers = {r for r in Role if can(r, f"plan.approve:{ptype}")}
        executors = {r for r in Role if can(r, f"plan.execute:{ptype}")}
        assert approvers.isdisjoint(executors), ptype


def test_operator_executes_warehouse_plans_only():
    assert can(OPERATOR, f"plan.execute:{PlanType.REALLOCATE}")
    assert can(OPERATOR, f"plan.execute:{PlanType.SPLIT}")
    assert not can(OPERATOR, f"plan.execute:{PlanType.EXPEDITE}")
    assert not can(OPERATOR, "import.run")


def test_audit_read_and_user_management():
    assert {r for r in Role if can(r, "audit.read")} == {MANAGER, PROCUREMENT, ADMIN}
    assert {r for r in Role if can(r, "users.manage")} == {ADMIN}


def test_unknown_permission_denies_everyone():
    assert not any(can(r, "does.not.exist") for r in Role)
