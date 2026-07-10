# feature_engineering.py

import sqlite3
import pandas as pd

DB_PATH = "./db/stock_analysis.db"
STOCK_CODE = "9202"  # ANAホールディングス


def load_data():
    """
    ANA株価と政策金利をDBから取得する
    """

    conn = sqlite3.connect(DB_PATH)

    query = """
    SELECT
        trade_date,
        stock_code,
        stock_name,
        close_price,
        policy_rate
    FROM stock_selection_view
    WHERE stock_code = ?
      AND policy_rate IS NOT NULL
    ORDER BY trade_date
    """

    df = pd.read_sql_query(query, conn, params=(STOCK_CODE,))
    conn.close()

    return df


def create_lag_features(df):
    """
    政策金利のラグ特徴量を作成する
    """

    df["trade_date"] = pd.to_datetime(df["trade_date"])

    # 月単位に変換
    df["year_month"] = df["trade_date"].dt.to_period("M")

    # 月次単位で政策金利を整理
    monthly_policy_rate = (
        df[["year_month", "policy_rate"]]
        .drop_duplicates()#重複行の削除
        .sort_values("year_month")#年月順に並べ替える
        .reset_index(drop=True)#インデックスを振りなおす
    )

    # ラグ特徴量作成
    monthly_policy_rate["policy_rate_lag0"] = monthly_policy_rate["policy_rate"]
    monthly_policy_rate["policy_rate_lag1"] = monthly_policy_rate["policy_rate"].shift(1)
    monthly_policy_rate["policy_rate_lag2"] = monthly_policy_rate["policy_rate"].shift(2)
    monthly_policy_rate["policy_rate_lag3"] = monthly_policy_rate["policy_rate"].shift(3)
    monthly_policy_rate["policy_rate_lag6"] = monthly_policy_rate["policy_rate"].shift(6)

    # 元の日次データへ結合
    df = df.merge(
        monthly_policy_rate[
            [
                "year_month",
                "policy_rate_lag0",
                "policy_rate_lag1",
                "policy_rate_lag2",
                "policy_rate_lag3",
                "policy_rate_lag6",
            ]
        ],
        on="year_month",
        how="left",
    )

    # ラグ作成で発生した欠損を削除
    df = df.dropna().reset_index(drop=True)

    return df


def save_features(df):
    """
    ラグ特徴量をDBへ保存する
    """

    # SQLiteに入れられる型へ変換
    df = df.copy()
    df["trade_date"] = df["trade_date"].dt.strftime("%Y-%m-%d")
    df["year_month"] = df["year_month"].astype(str)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 既存データ削除
    cursor.execute("""
        DELETE FROM ana_policy_rate_lag_features
    """)

    # INSERT
    insert_sql = """
    INSERT INTO ana_policy_rate_lag_features (
        trade_date,
        stock_code,
        stock_name,
        close_price,
        policy_rate,
        year_month,
        policy_rate_lag0,
        policy_rate_lag1,
        policy_rate_lag2,
        policy_rate_lag3,
        policy_rate_lag6
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    cursor.executemany(
        insert_sql,
        df[
            [
                "trade_date",
                "stock_code",
                "stock_name",
                "close_price",
                "policy_rate",
                "year_month",
                "policy_rate_lag0",
                "policy_rate_lag1",
                "policy_rate_lag2",
                "policy_rate_lag3",
                "policy_rate_lag6",
            ]
        ].values.tolist()
    )

    conn.commit()
    conn.close()

    print("ana_policy_rate_lag_features テーブル更新完了")


def main():
    df = load_data()

    print("データ読み込み完了")
    print(df.shape)

    feature_df = create_lag_features(df)

    print("ラグ特徴量作成完了")
    print(feature_df.head())
    print(feature_df.shape)

    save_features(feature_df)

    print("DB保存完了: ana_policy_rate_lag_features")


if __name__ == "__main__":
    main()