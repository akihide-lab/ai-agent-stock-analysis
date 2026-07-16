-- PostgreSQL migration validation queries.
--
-- Expected reference values from the verified environment:
-- stocks=17, stock_prices=7694, finance=24, calendar=13514
-- v_agent_stock_master=17, v_agent_data_freshness=9
-- v_agent_stock_candidates=17, v_stock_fundamental=7694
-- v_macro_economic=13514, v_ai_stock_report_input=7694
-- 9202 total_rows=1578, complete_rows=1470
-- 9202 first_trade_date=2020-01-06, latest_trade_date=2026-06-22
-- 9202 latest_fiscal_year=2024
--
-- Counts can change after data refreshes. Treat the values above as comments,
-- not hard assertions.

SELECT current_database() AS current_database;

SELECT 'stocks' AS object_name, count(*) AS row_count FROM stocks
UNION ALL SELECT 'stock_prices', count(*) FROM stock_prices
UNION ALL SELECT 'finance', count(*) FROM finance
UNION ALL SELECT 'calendar', count(*) FROM calendar
UNION ALL SELECT 'cpi', count(*) FROM cpi
UNION ALL SELECT 'exchange_rates', count(*) FROM exchange_rates
UNION ALL SELECT 'gdp', count(*) FROM gdp
UNION ALL SELECT 'gold_price', count(*) FROM gold_price
UNION ALL SELECT 'interest_rate_long', count(*) FROM interest_rate_long
UNION ALL SELECT 'nikkei_average', count(*) FROM nikkei_average
UNION ALL SELECT 'oil_prices', count(*) FROM oil_prices
UNION ALL SELECT 'policy_rate', count(*) FROM policy_rate
UNION ALL SELECT 'us_market_indicators', count(*) FROM us_market_indicators
ORDER BY object_name;

SELECT 'v_agent_stock_master' AS object_name, count(*) AS row_count FROM v_agent_stock_master
UNION ALL SELECT 'v_agent_data_freshness', count(*) FROM v_agent_data_freshness
UNION ALL SELECT 'v_agent_stock_candidates', count(*) FROM v_agent_stock_candidates
UNION ALL SELECT 'v_stock_fundamental', count(*) FROM v_stock_fundamental
UNION ALL SELECT 'v_macro_economic', count(*) FROM v_macro_economic
UNION ALL SELECT 'v_ai_stock_report_input', count(*) FROM v_ai_stock_report_input
ORDER BY object_name;

SELECT
    stock_code,
    stock_name,
    count(*) AS total_rows,
    sum(
        CASE
            WHEN close_price IS NOT NULL
             AND wti_price IS NOT NULL
             AND usd_jpy IS NOT NULL
             AND policy_rate IS NOT NULL
             AND jgb_10y_yield IS NOT NULL
             AND cpi_index IS NOT NULL
             AND gdp_growth IS NOT NULL
            THEN 1
            ELSE 0
        END
    ) AS complete_rows,
    min(trade_date) AS first_trade_date,
    max(trade_date) AS latest_trade_date,
    max(fiscal_year) AS latest_fiscal_year
FROM v_ai_stock_report_input
WHERE stock_code = '9202'
GROUP BY stock_code, stock_name;

SELECT
    stock_code,
    fiscal_year,
    fiscal_year_key,
    sales,
    operating_profit,
    net_profit,
    roe,
    per,
    pbr,
    dividend_yield,
    equity_ratio,
    updated_at
FROM finance
WHERE stock_code = '9202'
ORDER BY fiscal_year_key DESC NULLS LAST, fiscal_year DESC
LIMIT 1;

SELECT stock_code, count(*) AS duplicate_count
FROM stocks
GROUP BY stock_code
HAVING count(*) > 1
ORDER BY stock_code;

SELECT stock_code, trade_date, count(*) AS duplicate_count
FROM stock_prices
GROUP BY stock_code, trade_date
HAVING count(*) > 1
ORDER BY stock_code, trade_date;

SELECT stock_code, fiscal_year, count(*) AS duplicate_count
FROM finance
GROUP BY stock_code, fiscal_year
HAVING count(*) > 1
ORDER BY stock_code, fiscal_year;

SELECT data_name, latest_value, record_count
FROM v_agent_data_freshness
ORDER BY data_name;

SELECT
    'stock_prices' AS table_name,
    min(trade_date)::text AS min_value,
    max(trade_date)::text AS max_value,
    count(*) AS row_count
FROM stock_prices
UNION ALL
SELECT 'finance', min(fiscal_year_key)::text, max(fiscal_year_key)::text, count(*) FROM finance
UNION ALL
SELECT 'calendar', min(date)::text, max(date)::text, count(*) FROM calendar
UNION ALL
SELECT 'nikkei_average', min(trade_date)::text, max(trade_date)::text, count(*) FROM nikkei_average
UNION ALL
SELECT 'exchange_rates', min(date)::text, max(date)::text, count(*) FROM exchange_rates
UNION ALL
SELECT 'policy_rate', min(year_month), max(year_month), count(*) FROM policy_rate
UNION ALL
SELECT 'us_market_indicators', min(trade_date)::text, max(trade_date)::text, count(*) FROM us_market_indicators
ORDER BY table_name;

SELECT
    stock_code,
    count(*) AS rows_with_any_null_core_macro
FROM v_ai_stock_report_input
WHERE close_price IS NULL
   OR wti_price IS NULL
   OR usd_jpy IS NULL
   OR policy_rate IS NULL
   OR jgb_10y_yield IS NULL
   OR cpi_index IS NULL
   OR gdp_growth IS NULL
GROUP BY stock_code
ORDER BY stock_code;

SELECT
    fiscal_year,
    fiscal_year_key,
    count(*) AS finance_rows
FROM finance
GROUP BY fiscal_year, fiscal_year_key
ORDER BY fiscal_year_key DESC NULLS LAST, fiscal_year DESC;
