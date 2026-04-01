# CTE Trace (MS SQL)

Утилита для пошагового прослеживания выполнения CTE в SQL Server.

Показывает, как меняется набор строк между CTE-этапами:

- `+ {...}` — строка появилась на текущем этапе.
- `- {...}` — строка отсеялась (была на прошлом этапе, но отсутствует на текущем).

## Установка

```bash
pip install pyodbc
```

## Запуск

```bash
python cte_trace.py \
  --connection-string "DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost;DATABASE=MyDb;UID=sa;PWD=YourStrong!Passw0rd;TrustServerCertificate=yes" \
  --sql-file ./example.sql \
  --key-columns id \
  --max-changes 30
```

## Параметры

- `--connection-string` — ODBC строка подключения к MS SQL.
- `--sql-file` — файл со скриптом, содержащим CTE (`WITH ...`) и финальный запрос.
- `--key-columns` — опционально, список ключевых колонок через запятую для сравнения строк (например `id,order_id`). Если не указано — сравнение по всей строке.
- `--max-changes` — лимит отображаемых `+` / `-` строк на этап.

## Пример SQL

```sql
WITH
sales AS (
    SELECT id, customer_id, amount
    FROM dbo.Orders
),
filtered AS (
    SELECT id, customer_id, amount
    FROM sales
    WHERE amount > 1000
),
final_set AS (
    SELECT customer_id, COUNT(*) AS cnt
    FROM filtered
    GROUP BY customer_id
)
SELECT *
FROM final_set;
```

## Ограничения

- Сейчас разбирается один CTE-блок вида `WITH ...` в одном скрипте.
- Поддерживаются обычные CTE; рекурсивные CTE могут работать, но требуют аккуратных запросов.
- В диффе сравниваются результаты соседних CTE по порядку объявления.
