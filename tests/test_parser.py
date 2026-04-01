from cte_trace import parse_cte_script


def test_parse_simple_script():
    sql = """
    WITH a AS (
      SELECT 1 AS id
    ),
    b AS (
      SELECT id FROM a WHERE id = 1
    )
    SELECT * FROM b;
    """

    parsed = parse_cte_script(sql)
    assert [c.name for c in parsed.ctes] == ["a", "b"]
    assert "SELECT * FROM b" in parsed.final_query
