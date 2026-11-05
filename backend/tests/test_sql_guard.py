import pytest

from app.models import SQL_ALLOWED_TABLES
from app.tools.sql_guard import SQLValidationError, validate_and_prepare

D = "sqlite"


def ok(sql, max_rows=100):
    return validate_and_prepare(sql, SQL_ALLOWED_TABLES, D, max_rows)


def blocked(sql):
    with pytest.raises(SQLValidationError) as e:
        ok(sql)
    return e.value


def test_simple_select_allowed_and_limit_added():
    vq = ok("SELECT id, name FROM products ORDER BY name")
    assert "LIMIT 100" in vq.sql.upper() and vq.tables == ["products"]


def test_large_limit_is_capped_small_limit_kept():
    assert "LIMIT 100" in ok("SELECT id FROM orders LIMIT 99999").sql.upper()
    assert "LIMIT 7" in ok("SELECT id FROM orders LIMIT 7").sql.upper()


def test_where_literals_become_bind_parameters():
    vq = ok("SELECT id FROM orders WHERE status = 'completed' AND order_date >= '2026-07-01'")
    assert vq.params == {"p1": "completed", "p2": "2026-07-01"}
    assert "completed" not in vq.sql and ":p1" in vq.sql and ":p2" in vq.sql
    assert "completed" in vq.display_sql  # the user still sees readable SQL


def test_injection_string_stays_a_parameter():
    vq = ok("SELECT id FROM orders WHERE status = 'x'' OR ''1''=''1'")
    assert len(vq.params) == 1 and "OR" not in vq.sql.upper().split("WHERE")[1].replace("ORDER", "")


@pytest.mark.parametrize("sql", [
    "DROP TABLE orders",
    "DELETE FROM orders",
    "UPDATE orders SET status = 'completed'",
    "INSERT INTO products (id) VALUES (1)",
    "ALTER TABLE orders ADD COLUMN x INT",
    "CREATE TABLE t (x INT)",
    "PRAGMA table_info(orders)",
    "ATTACH DATABASE 'x.db' AS x",
    "TRUNCATE TABLE orders",
])
def test_non_select_statements_blocked(sql):
    assert blocked(sql).kind in ("security", "syntax")


def test_multiple_statements_blocked():
    assert "single" in blocked("SELECT id FROM orders; DROP TABLE orders").message.lower()
    blocked("SELECT id FROM orders; SELECT id FROM customers")


def test_trailing_semicolon_ok():
    assert ok("SELECT id FROM orders;").sql


def test_comment_cannot_hide_second_statement():
    blocked("SELECT id FROM orders; -- harmless\nDROP TABLE orders")


def test_non_allowlisted_tables_blocked():
    assert "not available" in blocked("SELECT id FROM users").message
    blocked("SELECT name FROM sqlite_master")
    blocked("SELECT id FROM main.orders")
    blocked("SELECT id FROM orders UNION SELECT id FROM users")
    blocked("SELECT id FROM orders WHERE customer_id IN (SELECT id FROM users)")
    blocked("SELECT * FROM pragma_table_info('orders')")


def test_restricted_columns_blocked():
    blocked("SELECT email FROM customers")
    blocked("SELECT c.email FROM customers c")
    blocked("SELECT id FROM customers WHERE email = 'a@b.c'")


def test_select_star_blocked_but_count_star_allowed():
    assert blocked("SELECT * FROM customers").kind == "syntax"
    blocked("SELECT c.* FROM customers c")
    assert ok("SELECT COUNT(*) AS n FROM orders").sql


def test_dangerous_functions_blocked():
    blocked("SELECT randomblob(1000000000) FROM orders")
    blocked("SELECT load_extension('x') FROM orders")
    blocked("SELECT sqlite_version() FROM orders")


def test_joins_aliases_cte_and_subqueries_allowed():
    sql = """
    WITH rev AS (
      SELECT oi.product_id, SUM(oi.quantity * oi.unit_price - oi.discount) AS revenue
      FROM order_items oi JOIN orders o ON o.id = oi.order_id
      WHERE o.status = 'completed' GROUP BY oi.product_id)
    SELECT p.name, r.revenue FROM rev r JOIN products p ON p.id = r.product_id
    ORDER BY r.revenue DESC
    """
    vq = ok(sql)
    assert set(vq.tables) == {"order_items", "orders", "products"}
    assert ok("SELECT name FROM (SELECT name FROM products) AS t").sql


def test_unknown_qualifier_and_unknown_column_rejected():
    blocked("SELECT z.id FROM orders o")
    blocked("SELECT nonsense FROM orders")


def test_empty_garbage_and_oversized_input():
    with pytest.raises(SQLValidationError):
        ok("")
    with pytest.raises(SQLValidationError):
        ok("this is not sql at all )))")
    with pytest.raises(SQLValidationError):
        ok("SELECT id FROM orders WHERE status = '" + "a" * 5000 + "'")
