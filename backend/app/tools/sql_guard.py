"""SQL safety validation for LLM-generated (or user-supplied) queries.

Defence in depth (this module is only ONE layer; the database account is also read-only):
  1. parse with sqlglot; exactly one statement; must be a SELECT / set operation;
  2. reject any data-changing, DDL, admin or command node anywhere in the tree;
  3. only allow-listed tables and columns (no schema-qualified names, no SELECT *);
  4. block dangerous functions;
  5. force a row LIMIT;
  6. turn WHERE/HAVING literal values into bind parameters.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError, SqlglotError, TokenError

MAX_SQL_LENGTH = 4000
MAX_JOINS = 6

_FORBIDDEN_NODE_NAMES = [
    "Insert", "Update", "Delete", "Drop", "Create", "Alter", "Command", "Merge", "TruncateTable",
    "Into", "Set", "Use", "Pragma", "Attach", "Detach", "Transaction", "Commit", "Rollback",
    "LoadData", "Copy", "Grant", "Revoke", "Analyze", "Kill", "Execute", "Describe", "Show",
]
FORBIDDEN_NODES = tuple(getattr(exp, n) for n in _FORBIDDEN_NODE_NAMES if hasattr(exp, n))

FORBIDDEN_FUNCTIONS = {
    "load_file", "sleep", "benchmark", "pg_sleep", "sys_exec", "sys_eval", "load_extension",
    "readfile", "writefile", "randomblob", "zeroblob", "fts3_tokenizer", "sqlite_compileoption_get",
    "sqlite_source_id", "sqlite_version", "version", "user", "current_user", "database", "schema",
    "system_user", "session_user", "connection_id", "get_lock", "release_lock", "into_outfile",
}

_SET_OP = getattr(exp, "SetOperation", exp.Union)


class SQLValidationError(Exception):
    """kind: 'security' (never retry blindly) or 'syntax' (the model may correct it)."""

    def __init__(self, message: str, kind: str = "security"):
        super().__init__(message)
        self.message = message
        self.kind = kind


@dataclass
class ValidatedQuery:
    sql: str                      # executable SQL with :pN bind parameters
    params: dict = field(default_factory=dict)
    display_sql: str = ""         # pretty SQL with the literal values (what the user sees)
    tables: list[str] = field(default_factory=list)


def _func_name(node: exp.Expression) -> str:
    if isinstance(node, exp.Anonymous):
        return str(node.this).lower()
    return node.sql_name().lower()


def _in_filter(node: exp.Expression) -> bool:
    """True for literals inside WHERE/HAVING that are not part of a LIMIT/OFFSET."""
    in_filter = False
    p = node.parent
    while p is not None:
        if isinstance(p, (exp.Limit, exp.Offset)):
            return False
        if isinstance(p, (exp.Where, exp.Having)):
            in_filter = True
        p = p.parent
    return in_filter


def validate_and_prepare(sql: str, allowed_tables: dict[str, list[str]], dialect: str,
                         max_rows: int) -> ValidatedQuery:
    if not sql or not sql.strip():
        raise SQLValidationError("The query is empty.", "syntax")
    if len(sql) > MAX_SQL_LENGTH:
        raise SQLValidationError("The query is too long.", "security")
    allowed = {t.lower(): [c.lower() for c in cols] for t, cols in allowed_tables.items()}

    try:
        statements = [s for s in sqlglot.parse(sql, read=dialect) if s is not None]
    except (ParseError, TokenError, SqlglotError) as exc:
        raise SQLValidationError(f"The query could not be parsed: {str(exc).splitlines()[0][:160]}", "syntax")
    if len(statements) != 1:
        raise SQLValidationError("Only a single SQL statement is allowed.", "security")
    root = statements[0]

    if not isinstance(root, (exp.Select, _SET_OP)):
        raise SQLValidationError("Only read-only SELECT queries are allowed.", "security")
    for node in root.walk():
        if isinstance(node, FORBIDDEN_NODES):
            raise SQLValidationError(
                f"Statements of type {type(node).__name__.upper()} are not allowed (read-only access).", "security")

    for f in root.find_all(exp.Func):
        if _func_name(f) in FORBIDDEN_FUNCTIONS:
            raise SQLValidationError(f"Function {_func_name(f)}() is not allowed.", "security")

    if len(list(root.find_all(exp.Join))) > MAX_JOINS:
        raise SQLValidationError("The query joins too many tables.", "security")

    cte_names = {c.alias_or_name.lower() for c in root.find_all(exp.CTE)}
    subquery_aliases = {s.alias.lower() for s in root.find_all(exp.Subquery) if s.alias}
    select_aliases = {a.alias.lower() for a in root.find_all(exp.Alias) if a.alias}

    alias_to_table: dict[str, str] = {}
    base_tables: list[str] = []
    for t in root.find_all(exp.Table):
        name = (t.name or "").lower()
        if t.db or t.catalog:
            raise SQLValidationError("Schema-qualified table names are not allowed.", "security")
        if name in cte_names:
            continue
        if name not in allowed:
            raise SQLValidationError(
                f"Table '{name or '?'}' is not available. Allowed tables: {', '.join(sorted(allowed))}.", "security")
        alias_to_table[(t.alias or t.name).lower()] = name
        alias_to_table[name] = name
        if name not in base_tables:
            base_tables.append(name)

    for star in root.find_all(exp.Star):
        if isinstance(star.parent, exp.Count):
            continue
        raise SQLValidationError("SELECT * is not allowed; list the columns you need explicitly.", "syntax")

    referenced_cols = {c for t in base_tables for c in allowed[t]}
    for col in root.find_all(exp.Column):
        cname = (col.name or "").lower()
        qualifier = (col.table or "").lower()
        if qualifier:
            table = alias_to_table.get(qualifier)
            if table is None:
                if qualifier in cte_names or qualifier in subquery_aliases:
                    continue
                raise SQLValidationError(f"Unknown table or alias '{qualifier}'.", "syntax")
            if cname not in allowed[table]:
                raise SQLValidationError(f"Column '{table}.{cname}' is not available.", "security")
        else:
            if cname in select_aliases or cname in referenced_cols:
                continue
            raise SQLValidationError(f"Column '{cname}' is not available.", "security")

    # ---- enforce LIMIT
    if isinstance(root, exp.Select):
        limit = root.args.get("limit")
        ok = False
        if limit is not None:
            val = limit.expression
            if isinstance(val, exp.Literal) and val.is_int and int(val.name) <= max_rows:
                ok = True
        if not ok:
            root = root.limit(max_rows)
    else:
        root = sqlglot.select(exp.column("*")).from_(root.subquery("u")).limit(max_rows)

    display_sql = root.sql(dialect=dialect, pretty=True)

    # ---- bind parameters for filter literals
    params: dict = {}
    for i, lit in enumerate([l for l in root.find_all(exp.Literal) if _in_filter(l)], start=1):
        key = f"p{i}"
        if lit.is_string:
            params[key] = lit.name
        else:
            params[key] = int(lit.name) if lit.is_int else float(lit.name)
        lit.replace(exp.Var(this=f":{key}"))
    return ValidatedQuery(sql=root.sql(dialect=dialect), params=params, display_sql=display_sql,
                          tables=base_tables)
