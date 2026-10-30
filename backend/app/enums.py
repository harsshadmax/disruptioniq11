from enum import StrEnum


class Role(StrEnum):
    ANALYST = "ops_analyst"
    MANAGER = "supply_chain_manager"
    OPERATOR = "warehouse_operator"
    PROCUREMENT = "procurement_approver"
    ADMIN = "administrator"


class PlanType(StrEnum):
    REALLOCATE = "reallocate"
    EXPEDITE = "expedite"
    ALT_SUPPLIER = "alt_supplier"
    SPLIT = "split"


class PlanStatus(StrEnum):
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    STALE = "STALE"
    CANCELLED = "CANCELLED"


class Tier(StrEnum):
    GOLD = "gold"
    SILVER = "silver"
    BRONZE = "bronze"


class DisruptionType(StrEnum):
    LATE_SHIPMENT = "late_shipment"
    SUPPLIER_DELAY = "supplier_delay"
    STOCK_SHORTAGE = "stock_shortage"


class EventOutcome(StrEnum):
    APPLIED = "applied"
    DUPLICATE = "duplicate"
    STALE = "stale"
    INVALID = "invalid"
