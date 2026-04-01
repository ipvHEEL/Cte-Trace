#!/usr/bin/env python3
"""CTE runtime tracer for Microsoft SQL Server.

Utility executes each CTE stage and prints row-level diff between stages:
+ row appears on current stage
- row disappeared on current stage
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from typing import Iterable, List, Sequence

try:
    import pyodbc
except Exception:  # pragma: no cover - only raised when dependency absent at runtime
    pyodbc = None


@dataclass
class CteDef:
    name: str
    query: str


@dataclass
class ParsedSql:
    ctes: List[CteDef]
    final_query: str


def _skip_ws(sql: str, i: int) -> int:
    while i < len(sql) and sql[i].isspace():
        i += 1
    return i


def _find_keyword_top_level(sql: str, keyword: str, start: int = 0) -> int:
    kw = keyword.upper()
    depth = 0
    in_string = False
    i = start

    while i < len(sql):
        ch = sql[i]

        if in_string:
            if ch == "'":
                if i + 1 < len(sql) and sql[i + 1] == "'":
                    i += 2
                    continue
                in_string = False
            i += 1
            continue

        if ch == "'":
            in_string = True
            i += 1
            continue

        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif depth == 0:
            segment = sql[i : i + len(kw)]
            if segment.upper() == kw:
                prev_ok = i == 0 or not (sql[i - 1].isalnum() or sql[i - 1] == "_")
                next_i = i + len(kw)
                next_ok = next_i >= len(sql) or not (sql[next_i].isalnum() or sql[next_i] == "_")
                if prev_ok and next_ok:
                    return i
        i += 1

    return -1


def parse_cte_script(sql: str) -> ParsedSql:
    script = sql.strip().rstrip(";")

    with_idx = _find_keyword_top_level(script, "WITH")
    if with_idx == -1:
        raise ValueError("В скрипте не найден блок WITH (CTE).")

    i = _skip_ws(script, with_idx + 4)
    ctes: List[CteDef] = []

    while i < len(script):
        name_start = i
        while i < len(script) and (script[i].isalnum() or script[i] in "_[]#."):
            i += 1
        if i == name_start:
            raise ValueError(f"Ожидалось имя CTE на позиции {i}.")
        name = script[name_start:i].strip("[]")

        i = _skip_ws(script, i)

        if script[i : i + 2].upper() == "AS":
            i += 2
        else:
            raise ValueError(f"Ожидался AS после имени CTE {name}.")

        i = _skip_ws(script, i)
        if i >= len(script) or script[i] != "(":
            raise ValueError(f"Ожидалась открывающая скобка после AS для CTE {name}.")

        depth = 0
        in_string = False
        body_start = i + 1
        i += 1
        while i < len(script):
            ch = script[i]
            if in_string:
                if ch == "'":
                    if i + 1 < len(script) and script[i + 1] == "'":
                        i += 2
                        continue
                    in_string = False
                i += 1
                continue

            if ch == "'":
                in_string = True
                i += 1
                continue

            if ch == "(":
                depth += 1
            elif ch == ")":
                if depth == 0:
                    body = script[body_start:i].strip()
                    ctes.append(CteDef(name=name, query=body))
                    i += 1
                    break
                depth -= 1
            i += 1
        else:
            raise ValueError(f"Не закрыта скобка в CTE {name}.")

        i = _skip_ws(script, i)
        if i < len(script) and script[i] == ",":
            i += 1
            i = _skip_ws(script, i)
            continue

        final_query = script[i:].strip()
        if not final_query:
            raise ValueError("После CTE блока отсутствует финальный SELECT/INSERT/UPDATE/DELETE запрос.")
        return ParsedSql(ctes=ctes, final_query=final_query)

    raise ValueError("Не удалось разобрать CTE блок.")


def build_with_clause(ctes: Sequence[CteDef]) -> str:
    parts = [f"{c.name} AS (\n{c.query}\n)" for c in ctes]
    return "WITH\n" + ",\n".join(parts)


def row_signature(row: dict, key_columns: Sequence[str] | None) -> str:
    if key_columns:
        payload = {k: row.get(k) for k in key_columns}
    else:
        payload = row
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)


def diff_rows(prev_rows: Sequence[dict], curr_rows: Sequence[dict], key_columns: Sequence[str] | None):
    prev_counter = Counter(row_signature(r, key_columns) for r in prev_rows)
    curr_counter = Counter(row_signature(r, key_columns) for r in curr_rows)

    added = list((curr_counter - prev_counter).elements())
    removed = list((prev_counter - curr_counter).elements())
    return added, removed


def fetch_rows(conn, sql: str) -> List[dict]:
    cur = conn.cursor()
    cur.execute(sql)
    columns = [c[0] for c in cur.description]
    out = []
    for rec in cur.fetchall():
        out.append({col: val for col, val in zip(columns, rec)})
    return out


def trace_ctes(conn, parsed: ParsedSql, key_columns: Sequence[str] | None, max_changes: int):
    prev_rows: List[dict] = []

    for idx, cte in enumerate(parsed.ctes, start=1):
        with_clause = build_with_clause(parsed.ctes[:idx])
        stage_sql = f"{with_clause}\nSELECT * FROM {cte.name};"
        curr_rows = fetch_rows(conn, stage_sql)

        added, removed = diff_rows(prev_rows, curr_rows, key_columns)

        print(f"\n=== CTE {idx}/{len(parsed.ctes)}: {cte.name} ===")
        print(f"rows={len(curr_rows)} added={len(added)} removed={len(removed)}")

        for item in added[:max_changes]:
            print(f"+ {item}")
        if len(added) > max_changes:
            print(f"+ ... ({len(added) - max_changes} more)")

        for item in removed[:max_changes]:
            print(f"- {item}")
        if len(removed) > max_changes:
            print(f"- ... ({len(removed) - max_changes} more)")

        prev_rows = curr_rows


def parse_args(argv: Iterable[str]):
    p = argparse.ArgumentParser(
        description="Trace CTE execution for MS SQL and show +- row changes between stages.")
    p.add_argument("--connection-string", required=True, help="ODBC connection string for SQL Server")
    p.add_argument("--sql-file", required=True, help="Path to SQL script with CTE block")
    p.add_argument(
        "--key-columns",
        default="",
        help="Comma-separated columns for row identity diff. By default, full row is used.",
    )
    p.add_argument("--max-changes", type=int, default=20, help="Maximum +/- rows to print per stage")
    return p.parse_args(list(argv))


def main(argv: Iterable[str] | None = None):
    args = parse_args(argv or sys.argv[1:])

    if pyodbc is None:
        print("Ошибка: пакет pyodbc не установлен. Установите: pip install pyodbc", file=sys.stderr)
        return 2

    with open(args.sql_file, "r", encoding="utf-8") as f:
        script = f.read()

    parsed = parse_cte_script(script)
    key_columns = [c.strip() for c in args.key_columns.split(",") if c.strip()] or None

    conn = pyodbc.connect(args.connection_string)
    try:
        trace_ctes(conn, parsed, key_columns, args.max_changes)
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
