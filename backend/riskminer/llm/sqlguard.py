"""NL→SQL execution guard (docs/impl/llm.md §2.5, api_contract §3.4): sqlglot (MIT) validation, then read-only execution.

Allowed: one SELECT (or UNION of selects, or WITH … SELECT) over whitelisted views only, whitelisted functions only,
no comments, no locking, no INTO; LIMIT forced to ≤ 200. Execution: BEGIN READ ONLY; SET LOCAL ROLE riskminer_ro (when
the role exists); statement_timeout 3 s; then ROLLBACK."""
from __future__ import annotations

from dataclasses import dataclass

import sqlglot
from sqlglot import exp

MAX_ROWS = 200
ALLOWED_FUNCS = {
    "count", "sum", "avg", "min", "max", "percentile_cont", "percentile_disc", "round", "coalesce", "nullif",
    "extract", "date_part", "lower", "upper", "abs", "greatest", "least", "stddev", "stddev_samp", "cast", "trycast",
    "median", "date_trunc", "length", "bool_or", "bool_and", "count_if", "array_length", "cardinality", "floor", "ceil",
    "trim", "substring", "left", "right", "concat", "to_char", "now", "current_date", "case", "if", "filter",
}
FORBIDDEN_NODES = (exp.Insert, exp.Update, exp.Delete, exp.Merge, exp.Create, exp.Drop, exp.Alter, exp.Command,
                   exp.Copy, exp.Set, exp.Transaction, exp.Into, exp.Lock, exp.Commit, exp.Rollback, exp.Use,
                   exp.Grant, exp.TruncateTable)
FORBIDDEN_PREFIXES = ("pg_", "dblink", "lo_", "set_config", "current_setting", "query_to_xml", "xpath", "pg_sleep",
                      "nextval", "setval", "txid", "inet_", "version")


class SqlRejected(ValueError):
    pass


@dataclass
class Checked:
    sql: str
    tables: list[str]
    limit: int


def _func_name(f: exp.Expression) -> str:
    if isinstance(f, exp.Anonymous):
        return str(f.this).lower()
    return (f.sql_name() or type(f).__name__).lower()


def check(sql: str, allowed_tables: set[str], max_rows: int = MAX_ROWS) -> Checked:
    if not sql or not sql.strip():
        raise SqlRejected("pusty SQL")
    if "--" in sql or "/*" in sql or ";" in sql.strip().rstrip(";"):
        raise SqlRejected("komentarze i wiele instrukcji są niedozwolone")
    try:
        trees = sqlglot.parse(sql, read="postgres")
    except sqlglot.errors.ParseError as e:
        raise SqlRejected(f"błąd składni: {str(e)[:200]}") from e
    trees = [t for t in trees if t is not None]
    if len(trees) != 1:
        raise SqlRejected("dozwolona jest dokładnie jedna instrukcja")
    tree = trees[0]
    if not isinstance(tree, (exp.Select, exp.Union, exp.Intersect, exp.Except)):
        if not (isinstance(tree, exp.Query)):
            raise SqlRejected("dozwolone jest tylko SELECT")
    for node in tree.walk():
        if isinstance(node, FORBIDDEN_NODES):
            raise SqlRejected(f"niedozwolona operacja {type(node).__name__}")
    if tree.find(exp.Lock) is not None or " for update" in sql.lower() or " for share" in sql.lower():
        raise SqlRejected("blokady są niedozwolone")
    ctes = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    tables = []
    for t in tree.find_all(exp.Table):
        name = t.name.lower()
        schema = (t.db or "").lower()
        full = f"{schema}.{name}" if schema else name
        if not schema and name in ctes:
            continue
        if full not in allowed_tables and name not in allowed_tables:
            raise SqlRejected(f"tabela {full} jest poza dozwolonymi widokami")
        tables.append(full)
    if not tables:
        raise SqlRejected("zapytanie musi czytać z dozwolonego widoku")
    for f in tree.find_all(exp.Func):
        n = _func_name(f)
        if n.startswith(FORBIDDEN_PREFIXES):
            raise SqlRejected(f"funkcja {n} jest niedozwolona")
        if isinstance(f, exp.Anonymous) and n not in ALLOWED_FUNCS:
            raise SqlRejected(f"funkcja {n} jest niedozwolona")
    # force LIMIT ≤ max_rows on the outermost query
    lim = tree.args.get("limit")
    cur = None
    if lim is not None:
        try:
            cur = int(lim.expression.name) if lim.expression is not None else None
        except (ValueError, AttributeError):
            cur = None
    limit = min(cur, max_rows) if cur else max_rows
    tree = tree.limit(limit, copy=False) if isinstance(tree, exp.Select) else exp.select("*").from_(tree.subquery("q")).limit(limit)
    return Checked(sql=tree.sql(dialect="postgres"), tables=sorted(set(tables)), limit=limit)


async def execute(sql: str, *, timeout_ms: int = 3000) -> tuple[list[str], list[dict]]:
    """Run an already checked query read-only on its own connection; always rolled back."""
    from riskminer.db.session import raw_conn

    async with raw_conn() as conn:
        tr = conn.transaction(readonly=True)
        await tr.start()
        try:
            has_ro = await conn.fetchval("SELECT 1 FROM pg_roles WHERE rolname = 'riskminer_ro'")
            if has_ro:
                await conn.execute("SET LOCAL ROLE riskminer_ro")
            await conn.execute(f"SET LOCAL statement_timeout = '{int(timeout_ms)}ms'")
            await conn.execute("SET LOCAL work_mem = '32MB'")
            stmt = await conn.prepare(sql)
            cols = [a.name for a in stmt.get_attributes()]
            rows = [dict(r) for r in await stmt.fetch()]
        finally:
            await tr.rollback()
    return cols, rows
