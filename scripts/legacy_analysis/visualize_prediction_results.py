# visualize_prediction_results.py

import sqlite3
import pandas as pd
import matplotlib.pyplot as plt

DB_PATH = "./db/stock_analysis.db"


def load_results():
    conn = sqlite3.connect(DB_PATH)

    query = """
    SELECT
        feature,
        r2,
        mae,
        rmse
    FROM ana_policy_rate_prediction_results
    ORDER BY id
    """

    df = pd.read_sql_query(query, conn)
    conn.close()

    return df

#棒グラフの作成
def plot_r2(df):
    plt.figure(figsize=(8, 5))
    plt.bar(df["feature"], df["r2"])
    plt.title("Policy Rate Lag Feature R2 Comparison")
    plt.xlabel("Lag Feature")
    plt.ylabel("R2")
    plt.xticks(rotation=30)
    plt.tight_layout()
    plt.show()

#誤差比較を折れ線グラフで
def plot_error(df):
    plt.figure(figsize=(8, 5))
    plt.plot(df["feature"], df["mae"], marker="o", label="MAE")
    plt.plot(df["feature"], df["rmse"], marker="o", label="RMSE")
    plt.title("Policy Rate Lag Feature Error Comparison")
    plt.xlabel("Lag Feature")
    plt.ylabel("Error")
    plt.xticks(rotation=30)
    plt.legend()
    plt.tight_layout()
    plt.show()


def main():
    df = load_results()

    print(df)

    plot_r2(df)
    plot_error(df)


if __name__ == "__main__":
    main()