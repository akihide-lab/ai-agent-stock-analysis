import sqlite3
import yfinance as yf

db_path = "./db/stock_analysis.db"

stocks = [
    # 半導体
    # ("8035", "8035.T"),  # 東京エレクトロン
    # ("6857", "6857.T"),  # アドバンテスト
    # ("6920", "6920.T"),  # レーザーテック

    # 銀行
    # ("8306", "8306.T"),  # 三菱UFJフィナンシャル・グループ
    # ("8316", "8316.T"),  # 三井住友フィナンシャルグループ
    # ("8411", "8411.T"),  # みずほフィナンシャルグループ

    # 商社
    # ("8058", "8058.T"),  # 三菱商事
    # ("8001", "8001.T"),  # 伊藤忠商事
    # ("8031", "8031.T"),  # 三井物産

    # 通信
    # ("9432", "9432.T"),  # NTT
    # ("9433", "9433.T"),  # KDDI
    # ("9434", "9434.T"),  # ソフトバンク

    ("9201", "9201.T"),  # 日本航空（JAL）
    ("9202", "9202.T"),  # ANAホールディングス（ANA）
    ("9204", "9204.T"),  # スカイマーク
]

conn = sqlite3.connect(db_path)

for stock_code, ticker in stocks:

    df = yf.download(
    ticker,
    start="2020-01-01"
    # end="2026-12-31" 現在日まで取得のため
    )

    # MultiIndex列を解除
    if hasattr(df.columns, "levels"):
        df.columns = df.columns.get_level_values(0)

    # 日付を列に戻す
    df = df.reset_index()

    # 銘柄コードを追加
    df["stock_code"] = stock_code

    # DB項目名に変更
    df = df.rename(columns={
        "Date": "trade_date",
        "Open": "open_price",
        "High": "high_price",
        "Low": "low_price",
        "Close": "close_price",
        "Volume": "volume"
    })

    # DBに入れる列だけにする
    df = df[[
        "stock_code",
        "trade_date",
        "open_price",
        "high_price",
        "low_price",
        "close_price",
        "volume"
    ]]

    # 日付を文字列に変換
    df["trade_date"] = df["trade_date"].dt.strftime("%Y-%m-%d")

    # 同じ銘柄の既存データを削除
    conn.execute(
        """
        DELETE FROM stock_prices
        WHERE stock_code = ?
        """,
        (stock_code,)
    )

    # 新規登録
    df.to_sql(
        "stock_prices",
        conn,
        if_exists="append",
        index=False
    )

    print(f"{stock_code} の登録が完了しました")

conn.commit()
conn.close()

print("全銘柄のDB登録が完了しました")