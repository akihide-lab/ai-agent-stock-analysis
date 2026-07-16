-- PostgreSQL base tables for the stock analysis AI agent.
--
-- This script is intentionally non-destructive:
-- - no DROP TABLE
-- - no TRUNCATE
-- - no DELETE
-- - no CASCADE
--
-- Re-running this script creates missing tables and indexes only. It does not
-- reconcile type differences in existing tables; review schema drift manually.

CREATE TABLE IF NOT EXISTS stocks (
    stock_code text PRIMARY KEY,
    stock_name text NOT NULL,
    market text NOT NULL,
    sector text,
    created_at timestamp without time zone NOT NULL
);

CREATE TABLE IF NOT EXISTS stock_prices (
    id bigint PRIMARY KEY,
    stock_code text NOT NULL,
    trade_date date NOT NULL,
    open_price double precision NOT NULL,
    high_price double precision NOT NULL,
    low_price double precision NOT NULL,
    close_price double precision NOT NULL,
    volume bigint NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_stock_prices_code_date
    ON stock_prices (stock_code, trade_date);
CREATE INDEX IF NOT EXISTS idx_stock_prices_stock_code
    ON stock_prices (stock_code);
CREATE INDEX IF NOT EXISTS idx_stock_prices_trade_date
    ON stock_prices (trade_date);

CREATE TABLE IF NOT EXISTS finance (
    stock_code text NOT NULL,
    ticker text,
    stock_name text,
    fiscal_year text NOT NULL,
    sales double precision,
    operating_profit double precision,
    net_profit double precision,
    roe double precision,
    eps double precision,
    per double precision,
    pbr double precision,
    dividend double precision,
    dividend_yield double precision,
    market_cap double precision,
    total_assets double precision,
    total_liabilities double precision,
    total_debt double precision,
    net_debt double precision,
    cash double precision,
    current_assets double precision,
    current_liabilities double precision,
    working_capital double precision,
    equity double precision,
    equity_ratio double precision,
    debt_ratio double precision,
    debt_to_equity_ratio double precision,
    current_ratio double precision,
    updated_at text,
    fiscal_year_key integer,
    PRIMARY KEY (stock_code, fiscal_year)
);

CREATE INDEX IF NOT EXISTS idx_finance_fiscal_year_key
    ON finance (fiscal_year_key);
CREATE INDEX IF NOT EXISTS idx_finance_stock_code
    ON finance (stock_code);

CREATE TABLE IF NOT EXISTS calendar (
    date date PRIMARY KEY,
    year integer,
    year_month text,
    quarter text,
    fiscal_year integer
);

CREATE INDEX IF NOT EXISTS idx_calendar_fiscal_year
    ON calendar (fiscal_year);
CREATE INDEX IF NOT EXISTS idx_calendar_year_month
    ON calendar (year_month);

CREATE TABLE IF NOT EXISTS cpi (
    year_month text PRIMARY KEY,
    cpi_index double precision,
    cpi_mom double precision
);

CREATE TABLE IF NOT EXISTS exchange_rates (
    date date PRIMARY KEY,
    usd_jpy double precision
);

CREATE TABLE IF NOT EXISTS gdp (
    fiscal_year integer PRIMARY KEY,
    period text,
    gdp_amount double precision,
    gdp_growth double precision
);

CREATE TABLE IF NOT EXISTS gold_price (
    trade_date date PRIMARY KEY,
    gold_close double precision,
    updated_at text
);

CREATE TABLE IF NOT EXISTS interest_rate_long (
    date date PRIMARY KEY,
    jgb_10y_yield double precision
);

CREATE TABLE IF NOT EXISTS nikkei_average (
    trade_date date PRIMARY KEY,
    open_price double precision,
    high_price double precision,
    low_price double precision,
    close_price double precision,
    volume double precision,
    updated_at text
);

CREATE TABLE IF NOT EXISTS oil_prices (
    date date PRIMARY KEY,
    wti_price double precision
);

CREATE TABLE IF NOT EXISTS policy_rate (
    year_month text PRIMARY KEY,
    policy_rate double precision
);

CREATE TABLE IF NOT EXISTS us_market_indicators (
    trade_date date PRIMARY KEY,
    sp500_close double precision,
    nasdaq100_close double precision,
    dow_close double precision,
    vix_close double precision,
    us_10y_yield double precision,
    updated_at text
);
