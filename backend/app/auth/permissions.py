"""Permission matrix (blueprint section 4) as data. Enforced on the backend for every route."""
from app.enums import PlanType, Role

A, M, O, P, ADM = Role.ANALYST, Role.MANAGER, Role.OPERATOR, Role.PROCUREMENT, Role.ADMIN
ALL_ROLES = frozenset(Role)

PERMISSIONS: dict[str, frozenset[Role]] = {
    "view": ALL_ROLES,  # operators are further scoped to their warehouse inside queries
    "import.run": frozenset({A, ADM}),
    "detect.run": frozenset({A, M, ADM}),
    "ai.use": frozenset({A, M, P}),  # advisory text only; cannot approve or execute anything
    "simulate.run": frozenset({A, M, P, ADM}),  # read-only what-if; network-wide, so not for warehouse-scoped operators
    "plan.create": frozenset({A, M}),
    "plan.propose": frozenset({A}),
    "plan.modify": frozenset({A, M, P}),
    # approval, by plan type
    f"plan.approve:{PlanType.REALLOCATE}": frozenset({M}),
    f"plan.approve:{PlanType.SPLIT}": frozenset({M}),
    f"plan.approve:{PlanType.EXPEDITE}": frozenset({P}),
    f"plan.approve:{PlanType.ALT_SUPPLIER}": frozenset({P}),
    # execution confirmation, by plan type
    f"plan.execute:{PlanType.REALLOCATE}": frozenset({O}),
    f"plan.execute:{PlanType.SPLIT}": frozenset({O}),
    f"plan.execute:{PlanType.EXPEDITE}": frozenset({A}),
    f"plan.execute:{PlanType.ALT_SUPPLIER}": frozenset({A}),
    "audit.read": frozenset({M, P, ADM}),
    "users.manage": frozenset({ADM}),
    "demo.controls": frozenset({ADM}),
}


def can(role: str, permission: str) -> bool:
    return role in PERMISSIONS.get(permission, frozenset())
