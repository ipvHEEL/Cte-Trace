from cte_trace import parse_cte_script
from cte_trace import read_sql_file


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


def test_read_sql_file_utf16(tmp_path):
    sql_path = tmp_path / "script.sql"
    expected = "WITH a AS (SELECT 1 AS id) SELECT * FROM a;"
    sql_path.write_bytes(expected.encode("utf-16"))

    result = read_sql_file(str(sql_path))

    assert result == expected
