from typing import Optional
from sqlalchemy import inspect as sa_inspect, text


def get_schemas(engine) -> list[str]:
    dialect = engine.dialect.name
    with engine.connect() as conn:
        if dialect == 'sqlite':
            return []
        if dialect == 'postgresql':
            result = conn.execute(text(
                "SELECT schema_name FROM information_schema.schemata "
                "WHERE schema_name NOT IN ('information_schema','pg_catalog','pg_toast') "
                "AND schema_name NOT LIKE 'pg_temp_%' "
                "AND schema_name NOT LIKE 'pg_toast_temp_%' "
                "ORDER BY schema_name"
            ))
            return [r[0] for r in result]
        if dialect in ('mysql', 'mariadb'):
            result = conn.execute(text(
                "SELECT schema_name FROM information_schema.schemata "
                "WHERE schema_name NOT IN ('information_schema','performance_schema','mysql','sys') "
                "ORDER BY schema_name"
            ))
            return [r[0] for r in result]
    return []


def get_tables(engine, schema: Optional[str] = None) -> list[dict]:
    inspector = sa_inspect(engine)
    items = []
    try:
        for name in sorted(inspector.get_table_names(schema=schema)):
            items.append({'name': name, 'kind': 'table'})
        for name in sorted(inspector.get_view_names(schema=schema)):
            items.append({'name': name, 'kind': 'view'})
    except Exception:
        pass
    return items


def get_columns(engine, table: str, schema: Optional[str] = None) -> list[dict]:
    inspector = sa_inspect(engine)
    cols = []
    try:
        for col in inspector.get_columns(table, schema=schema):
            cols.append({
                'name': col['name'],
                'type': str(col['type']),
                'nullable': col.get('nullable', True),
            })
    except Exception:
        pass
    return cols


def get_primary_keys(engine, table: str, schema: Optional[str] = None) -> list[str]:
    inspector = sa_inspect(engine)
    try:
        pk = inspector.get_pk_constraint(table, schema=schema)
        return pk.get('constrained_columns', [])
    except Exception:
        return []
