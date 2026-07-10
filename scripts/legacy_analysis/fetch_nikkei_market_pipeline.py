import sqlite3
from datetime import datetime

import pandas as pd
import yfinance as yf


DB_PATH = "./db/nikkei_stock_average_analysis.db"

START_DATE = "2020-01-01"


# =========================
# 共通：yfinance取得
# =========================
def fetch_yfinance_data(ticker: str, start_date: str = START_DATE) -> pd.DataFrame:
    """
    yfinanceから株価・指数データを取得する
    """
    print(f"{ticker} のデータ取得中...")

    df = yf.download(
        ticker,
        start=start_date,
        progress=False,
        auto_adjust=False
    )

    if df.empty:
        print(f"{ticker} のデータが取得できませんでした")
        return pd.DataFrame()

    df = df.reset_index()

    # MultiIndex対策
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[0] for col in df.columns]

    df["Date"] = pd.to_datetime(df["Date"]).dt.date

    return df


# =========================
# 日経平均 保存
# =========================
def save_nikkei_average(conn: sqlite3.Connection) -> None:
    """
    日経平均株価を nikkei_average に保存する
    """
    df = fetch_yfinance_data("^N225")

    if df.empty:
        return

    insert_data = []

    for _, row in df.iterrows():
        insert_data.append(
            (
                row["Date"],
                float(row["Open"]) if pd.notna(row["Open"]) else None,
                float(row["High"]) if pd.notna(row["High"]) else None,
                float(row["Low"]) if pd.notna(row["Low"]) else None,
                float(row["Close"]) if pd.notna(row["Close"]) else None,
                float(row["Volume"]) if pd.notna(row["Volume"]) else None,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            )
        )

    conn.execute("DELETE FROM nikkei_average")

    conn.executemany(
        """
        INSERT INTO nikkei_average (
            trade_date,
            open_price,
            high_price,
            low_price,
            close_price,
            volume,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        insert_data
    )

    print("nikkei_average 登録完了")


# =========================
# 米国市場指標 保存
# =========================
def save_us_market_indicators(conn: sqlite3.Connection) -> None:
    """
    米国市場指標を us_market_indicators に保存する
    """
    tickers = {
        "sp500_close": "^GSPC",
        "nasdaq100_close": "^NDX",
        "dow_close": "^DJI",
        "vix_close": "^VIX",
        "us_10y_yield": "^TNX",
    }

    merged_df = None

    for column_name, ticker in tickers.items():
        df = fetch_yfinance_data(ticker)

        if df.empty:
            continue

        temp_df = df[["Date", "Close"]].copy()
        temp_df = temp_df.rename(
            columns={
                "Date": "trade_date",
                "Close": column_name
            }
        )

        if merged_df is None:
            merged_df = temp_df
        else:
            merged_df = pd.merge(
                merged_df,
                temp_df,
                on="trade_date",
                how="outer"
            )

    if merged_df is None or merged_df.empty:
        print("米国市場指標データが取得できませんでした")
        return

    merged_df = merged_df.sort_values("trade_date")

    insert_data = []

    for _, row in merged_df.iterrows():
        insert_data.append(
            (
                row["trade_date"],
                float(row["sp500_close"]) if pd.notna(row.get("sp500_close")) else None,
                float(row["nasdaq100_close"]) if pd.notna(row.get("nasdaq100_close")) else None,
                float(row["dow_close"]) if pd.notna(row.get("dow_close")) else None,
                float(row["vix_close"]) if pd.notna(row.get("vix_close")) else None,
                float(row["us_10y_yield"]) if pd.notna(row.get("us_10y_yield")) else None,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            )
        )

    conn.execute("DELETE FROM us_market_indicators")

    conn.executemany(
        """
        INSERT INTO us_market_indicators (
            trade_date,
            sp500_close,
            nasdaq100_close,
            dow_close,
            vix_close,
            us_10y_yield,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        insert_data
    )

    print("us_market_indicators 登録完了")


# =========================
# 金価格 保存
# =========================
def save_gold_price(conn: sqlite3.Connection) -> None:
    """
    金価格を gold_price に保存する
    """
    df = fetch_yfinance_data("GC=F")

    if df.empty:
        return

    insert_data = []

    for _, row in df.iterrows():
        insert_data.append(
            (
                row["Date"],
                float(row["Close"]) if pd.notna(row["Close"]) else None,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            )
        )

    conn.execute("DELETE FROM gold_price")

    conn.executemany(
        """
        INSERT INTO gold_price (
            trade_date,
            gold_close,
            updated_at
        )
        VALUES (?, ?, ?)
        """,
        insert_data
    )

    print("gold_price 登録完了")


# =========================
# メイン処理
# =========================
def main() -> None:
    """
    日経平均・米国市場指標・金価格を取得してDBへ保存する
    """
    conn = sqlite3.connect(DB_PATH)

    try:
        save_nikkei_average(conn)
        save_us_market_indicators(conn)
        save_gold_price(conn)

        conn.commit()
        print("全データの登録が完了しました")

    except Exception as e:
        conn.rollback()
        print("エラーが発生したためロールバックしました")
        print(e)

    finally:
        conn.close()


if __name__ == "__main__":
    main()