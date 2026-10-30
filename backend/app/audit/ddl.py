"""DDL that makes audit_log append-only. Used by the Alembic migration."""

AUDIT_IMMUTABLE_UP = [
    """
    CREATE OR REPLACE FUNCTION audit_log_immutable() RETURNS trigger AS $$
    BEGIN
        RAISE EXCEPTION 'audit_log is append-only';
    END;
    $$ LANGUAGE plpgsql;
    """,
    """
    CREATE TRIGGER audit_log_no_update_delete
    BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_immutable();
    """,
    """
    CREATE TRIGGER audit_log_no_truncate
    BEFORE TRUNCATE ON audit_log
    FOR EACH STATEMENT EXECUTE FUNCTION audit_log_immutable();
    """,
]

AUDIT_IMMUTABLE_DOWN = [
    "DROP TRIGGER IF EXISTS audit_log_no_truncate ON audit_log;",
    "DROP TRIGGER IF EXISTS audit_log_no_update_delete ON audit_log;",
    "DROP FUNCTION IF EXISTS audit_log_immutable();",
]
