-- MART view consumed by the AI agent as optional additional analysis context.

CREATE OR REPLACE VIEW MART.STOCK_ANALYSIS AS
WITH price_changes AS (
    SELECT
        STOCK_CODE,
        TRADE_DATE,
        CLOSE_PRICE,
        VOLUME,
        CLOSE_PRICE - LAG(CLOSE_PRICE) OVER (
            PARTITION BY STOCK_CODE
            ORDER BY TRADE_DATE
        ) AS PRICE_CHANGE,
        CASE
            WHEN LAG(CLOSE_PRICE) OVER (
                PARTITION BY STOCK_CODE
                ORDER BY TRADE_DATE
            ) IS NULL THEN NULL
            WHEN LAG(CLOSE_PRICE) OVER (
                PARTITION BY STOCK_CODE
                ORDER BY TRADE_DATE
            ) = 0 THEN NULL
            ELSE (
                CLOSE_PRICE - LAG(CLOSE_PRICE) OVER (
                    PARTITION BY STOCK_CODE
                    ORDER BY TRADE_DATE
                )
            ) / LAG(CLOSE_PRICE) OVER (
                PARTITION BY STOCK_CODE
                ORDER BY TRADE_DATE
            )
        END AS CHANGE_RATE
    FROM CLEAN.STOCK_PRICES
),
latest_finance AS (
    SELECT *
    FROM CLEAN.FINANCE
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY STOCK_CODE
        ORDER BY FISCAL_YEAR DESC
    ) = 1
)
SELECT
    p.STOCK_CODE,
    p.TRADE_DATE,
    p.CLOSE_PRICE,
    p.VOLUME,
    p.PRICE_CHANGE,
    p.CHANGE_RATE,
    f.SALES,
    f.OPERATING_PROFIT,
    f.NET_PROFIT,
    f.ROE,
    f.PER,
    f.PBR,
    f.DIVIDEND_YIELD,
    m.USD_JPY,
    m.NIKKEI_CLOSE
FROM price_changes p
LEFT JOIN latest_finance f
  ON p.STOCK_CODE = f.STOCK_CODE
LEFT JOIN CLEAN.MACRO_ECONOMIC m
  ON p.TRADE_DATE = m.TRADE_DATE;
