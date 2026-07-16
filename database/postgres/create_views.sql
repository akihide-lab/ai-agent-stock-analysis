-- PostgreSQL views used by the stock analysis AI agent.
--
-- These definitions are based on the verified market_analysis_test /
-- market_analysis PostgreSQL views. Run after create_tables.sql and data
-- migration.

CREATE OR REPLACE VIEW v_agent_stock_master AS
SELECT
    stock_code,
    stock_name,
    market,
    sector
FROM stocks;

CREATE OR REPLACE VIEW v_agent_data_freshness AS
SELECT
    'stock_prices'::text AS data_name,
    max(stock_prices.trade_date)::text AS latest_value,
    count(*) AS record_count
FROM stock_prices
UNION ALL
SELECT
    'finance'::text AS data_name,
    max(finance.fiscal_year_key)::text AS latest_value,
    count(*) AS record_count
FROM finance
UNION ALL
SELECT
    'nikkei_average'::text AS data_name,
    max(nikkei_average.trade_date)::text AS latest_value,
    count(*) AS record_count
FROM nikkei_average
UNION ALL
SELECT
    'exchange_rates'::text AS data_name,
    max(exchange_rates.date)::text AS latest_value,
    count(*) AS record_count
FROM exchange_rates
UNION ALL
SELECT
    'interest_rate_long'::text AS data_name,
    max(interest_rate_long.date)::text AS latest_value,
    count(*) AS record_count
FROM interest_rate_long
UNION ALL
SELECT
    'policy_rate'::text AS data_name,
    max(policy_rate.year_month) AS latest_value,
    count(*) AS record_count
FROM policy_rate
UNION ALL
SELECT
    'oil_prices'::text AS data_name,
    max(oil_prices.date)::text AS latest_value,
    count(*) AS record_count
FROM oil_prices
UNION ALL
SELECT
    'gold_price'::text AS data_name,
    max(gold_price.trade_date)::text AS latest_value,
    count(*) AS record_count
FROM gold_price
UNION ALL
SELECT
    'us_market_indicators'::text AS data_name,
    max(us_market_indicators.trade_date)::text AS latest_value,
    count(*) AS record_count
FROM us_market_indicators;

CREATE OR REPLACE VIEW v_agent_stock_candidates AS
WITH latest_price_date AS (
    SELECT
        stock_prices.stock_code,
        max(stock_prices.trade_date) AS latest_trade_date
    FROM stock_prices
    GROUP BY stock_prices.stock_code
),
latest_price AS (
    SELECT
        sp.stock_code,
        sp.trade_date,
        sp.close_price,
        sp.volume
    FROM stock_prices sp
    JOIN latest_price_date lpd
      ON sp.stock_code = lpd.stock_code
     AND sp.trade_date = lpd.latest_trade_date
),
latest_finance_year AS (
    SELECT
        finance.stock_code,
        max(finance.fiscal_year_key) AS latest_fiscal_year
    FROM finance
    GROUP BY finance.stock_code
),
latest_finance AS (
    SELECT
        f.stock_code,
        f.fiscal_year_key,
        f.roe,
        f.per,
        f.pbr,
        f.dividend_yield,
        f.equity_ratio
    FROM finance f
    JOIN latest_finance_year lfy
      ON f.stock_code = lfy.stock_code
     AND f.fiscal_year_key = lfy.latest_fiscal_year
)
SELECT
    s.stock_code,
    s.stock_name,
    s.market,
    s.sector,
    lp.trade_date AS latest_trade_date,
    lp.close_price AS latest_close_price,
    lp.volume,
    lf.roe,
    lf.per,
    lf.pbr,
    lf.dividend_yield,
    lf.equity_ratio,
    lf.fiscal_year_key AS latest_fiscal_year
FROM stocks s
LEFT JOIN latest_price lp ON s.stock_code = lp.stock_code
LEFT JOIN latest_finance lf ON s.stock_code = lf.stock_code;

CREATE OR REPLACE VIEW v_stock_fundamental AS
SELECT
    sp.stock_code,
    s.stock_name,
    s.market,
    s.sector,
    sp.trade_date,
    sp.open_price,
    sp.high_price,
    sp.low_price,
    sp.close_price,
    sp.volume,
    f.fiscal_year_key AS fiscal_year,
    f.sales,
    f.operating_profit,
    f.net_profit,
    f.roe,
    f.eps,
    f.per,
    f.pbr,
    f.dividend_yield,
    f.equity_ratio
FROM stock_prices sp
LEFT JOIN stocks s ON sp.stock_code = s.stock_code
LEFT JOIN calendar c ON sp.trade_date = c.date
LEFT JOIN finance f
       ON sp.stock_code = f.stock_code
      AND c.fiscal_year = f.fiscal_year_key;

CREATE OR REPLACE VIEW v_macro_economic AS
SELECT
    c.date,
    c.year,
    c.year_month,
    c.quarter,
    c.fiscal_year,
    n.open_price AS nikkei_open_price,
    n.high_price AS nikkei_high_price,
    n.low_price AS nikkei_low_price,
    n.close_price AS nikkei_close_price,
    n.volume AS nikkei_volume,
    er.usd_jpy,
    ir.jgb_10y_yield,
    oil.wti_price,
    gp.gold_close,
    us.sp500_close,
    us.nasdaq100_close,
    us.dow_close,
    us.vix_close,
    us.us_10y_yield,
    cp.cpi_index,
    cp.cpi_mom,
    gd.gdp_amount,
    gd.gdp_growth,
    pr.policy_rate
FROM calendar c
LEFT JOIN nikkei_average n ON c.date = n.trade_date
LEFT JOIN exchange_rates er ON c.date = er.date
LEFT JOIN interest_rate_long ir ON c.date = ir.date
LEFT JOIN oil_prices oil ON c.date = oil.date
LEFT JOIN gold_price gp ON c.date = gp.trade_date
LEFT JOIN us_market_indicators us ON c.date = us.trade_date
LEFT JOIN cpi cp ON c.year_month = cp.year_month
LEFT JOIN gdp gd ON c.fiscal_year = gd.fiscal_year
LEFT JOIN policy_rate pr ON c.year_month = pr.year_month;

CREATE OR REPLACE VIEW v_ai_stock_report_input AS
SELECT
    sf.stock_code,
    sf.stock_name,
    sf.market,
    sf.sector,
    sf.trade_date,
    sf.open_price,
    sf.high_price,
    sf.low_price,
    sf.close_price,
    sf.volume,
    sf.fiscal_year,
    sf.sales,
    sf.operating_profit,
    sf.net_profit,
    sf.roe,
    sf.eps,
    sf.per,
    sf.pbr,
    sf.dividend_yield,
    sf.equity_ratio,
    me.year,
    me.year_month,
    me.quarter,
    me.nikkei_close_price,
    me.usd_jpy,
    me.jgb_10y_yield,
    me.wti_price,
    me.gold_close,
    me.sp500_close,
    me.nasdaq100_close,
    me.dow_close,
    me.vix_close,
    me.us_10y_yield,
    me.cpi_index,
    me.cpi_mom,
    me.gdp_amount,
    me.gdp_growth,
    me.policy_rate
FROM v_stock_fundamental sf
LEFT JOIN v_macro_economic me ON sf.trade_date = me.date;
