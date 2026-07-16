# PostgreSQL migration assets

This directory contains the reproducible assets for rebuilding the PostgreSQL
database used by the stock analysis AI agent. Start with a test database such as
`market_analysis_test`; do not run these steps directly against production.

## 1. Overview

The application can read either the local SQLite database or PostgreSQL through
`scripts/db_connection.py`. These assets cover the PostgreSQL side: table
creation, SQLite data copy, view creation, and validation.

## 2. Source tables

The migration covers these base tables:

- `stocks`
- `stock_prices`
- `finance`
- `calendar`
- `cpi`
- `exchange_rates`
- `gdp`
- `gold_price`
- `interest_rate_long`
- `nikkei_average`
- `oil_prices`
- `policy_rate`
- `us_market_indicators`

## 3. Views

`create_views.sql` creates the views used by the AI agent in this order:

1. `v_agent_stock_master`
2. `v_agent_data_freshness`
3. `v_agent_stock_candidates`
4. `v_stock_fundamental`
5. `v_macro_economic`
6. `v_ai_stock_report_input`

The definitions are based on the verified PostgreSQL databases
`market_analysis_test` and `market_analysis`.

## 4. Environment variables

Set connection values with environment variables or a local `.env` file that is
not committed to Git.

Required PostgreSQL values:

- `POSTGRES_HOST` or `PGHOST`
- `POSTGRES_PORT` or `PGPORT`
- `POSTGRES_DB` or `PGDATABASE`
- `POSTGRES_USER` or `PGUSER`
- `POSTGRES_PASSWORD` or `PGPASSWORD`
- `POSTGRES_SSLMODE` or `PGSSLMODE`

SQLite source:

- `SQLITE_DB_PATH`, or pass `--sqlite-db`

Do not put real credentials in this repository.

## 5. Recommended order

1. Take an RDS snapshot or `pg_dump` backup.
2. Confirm the target database name.
3. Run `create_tables.sql`.
4. Run `migrate_sqlite_to_postgres.py`.
5. Confirm table counts.
6. Run `create_views.sql`.
7. Run `validate_migration.sql`.
8. Run the AI agent with `--context-only`.

Example for a test database:

```powershell
$env:DB_TYPE = "postgres"
$env:POSTGRES_DB = "market_analysis_test"
psql -f database/postgres/create_tables.sql
.\.venv\Scripts\python.exe database\postgres\migrate_sqlite_to_postgres.py --postgres-db market_analysis_test
psql -f database/postgres/create_views.sql
psql -f database/postgres/validate_migration.sql
.\.venv\Scripts\python.exe scripts\analyze_stock.py 9202 --context-only --skip-web-update
```

## 6. Existing data behavior

`create_tables.sql` uses `CREATE TABLE IF NOT EXISTS` and does not delete data.
It does not automatically fix schema drift in an existing table.

`migrate_sqlite_to_postgres.py` stops by default when target tables already
contain rows. This prevents accidental duplication or production overwrite.
Optional `--mode skip` and `--mode upsert` exist for controlled re-runs, but
they require `--allow-nonempty`.

The script refuses the production database name `market_analysis` unless
`--allow-production` is explicitly provided.

Before using `--allow-production`, take an RDS snapshot or `pg_dump` backup and
verify the same command on `market_analysis_test`.

Use `--allow-nonempty` only when you have intentionally reviewed the existing
target data. In particular, `--mode upsert` can update existing rows on primary
key conflicts.

## 7. Validation

`validate_migration.sql` prints:

- current database
- table counts
- view counts
- 9202 report readiness
- latest finance row for 9202
- duplicate checks
- freshness values
- latest dates
- null counts for core report inputs
- finance fiscal year mapping

Reference values in comments were captured from the verified environment. They
can change after market data refreshes.

## 8. Production precautions

- Do not run first against production.
- Verify on `market_analysis_test`.
- Take an RDS snapshot or `pg_dump` before production work.
- Review every command before execution.
- Do not run `scripts/update_market_data.py` as part of this migration.
- Do not run SQLite update scripts when `DB_TYPE=postgres`.

## 9. Rollback

Preferred rollback options:

1. Restore an RDS snapshot.
2. Restore from `pg_dump`.
3. Recreate only the views if the issue is view-related.
4. Point the AI agent back to `market_analysis_test` while production is fixed.

## 10. Security

- Keep credentials in `.env` or environment variables only.
- Do not commit `.env`, database dumps, logs, reports, or local DB files.
- Migration output prints database names and row counts only; it does not print
  passwords or DSNs.

## 11. Known notes

- PostgreSQL view `fiscal_year` can expose the fiscal year key. For example,
  `fiscal_year_key = 2024` and `finance.fiscal_year = 2025-03-31` both refer to
  the fiscal year ending March 2025. The finance values were confirmed to match
  SQLite.
- `pandas.read_sql_query()` can emit a SQLAlchemy recommendation warning with a
  PostgreSQL DB-API connection. Report generation has been verified despite the
  warning; SQLAlchemy is not required for this project.
