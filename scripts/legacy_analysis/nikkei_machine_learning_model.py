import sqlite3
from datetime import datetime

import numpy as np
import pandas as pd

from sklearn.linear_model import LinearRegression
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import r2_score, mean_absolute_error, mean_squared_error
from xgboost import XGBRegressor


DB_PATH = "./db/nikkei_stock_average_analysis.db"
VIEW_NAME = "nikkei_analysis_view"
TARGET = "nikkei_close"

BASE_FEATURES = [
    "nasdaq100_close",
    "usd_jpy",
    "vix_close",
    "wti_price",
    "gold_close",
    "us_10y_yield",
    "jgb_10y_yield",
    "policy_rate",
    "cpi_index",
    "gdp_growth",
]

LAG_DAYS = 1


def load_data():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql(f"SELECT * FROM {VIEW_NAME}", conn)
    conn.close()

    df["trade_date"] = pd.to_datetime(df["trade_date"])
    return df

#ラグ特徴量の作成
def add_lag_features(df):
    df = df.sort_values("trade_date").copy()

    lag_features = []

    for col in BASE_FEATURES:
        lag_col = f"{col}_lag{LAG_DAYS}"
        df[lag_col] = df[col].shift(LAG_DAYS)
        lag_features.append(lag_col)

    return df, lag_features

#データの前処理
def preprocess_data(df):
    df, lag_features = add_lag_features(df)

    use_cols = ["trade_date", TARGET] + lag_features
    df = df[use_cols].copy()

    for col in [TARGET] + lag_features:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna().sort_values("trade_date").reset_index(drop=True)

    return df, lag_features

#分析対象となる最新６か月分を取得する関数
def get_recent_target_months(df, n_months=6):
    months = (
        df["trade_date"]
        .dt.strftime("%Y-%m")
        .drop_duplicates()
        .sort_values()
        .tolist()
    )

    return months[-n_months:]

#指定した月の「最後の営業日」のデータを取得する関数
def get_target_row(df, target_month):
    target_df = df[df["trade_date"].dt.strftime("%Y-%m") == target_month]

    if target_df.empty:
        return None

    return target_df.sort_values("trade_date").iloc[-1]

#機械学習モデルで予測モデルの作成
def evaluate_model(model_name, model, df, features, target_month):
    target_row = get_target_row(df, target_month)

    if target_row is None:
        return None

    target_date = target_row["trade_date"]

    train_df = df[df["trade_date"] < target_date].copy()

    X = train_df[features]
    y = train_df[TARGET]

    split_index = int(len(train_df) * 0.8)

    X_train = X.iloc[:split_index]
    X_test = X.iloc[split_index:]
    y_train = y.iloc[:split_index]
    y_test = y.iloc[split_index:]

    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)

    r2 = r2_score(y_test, y_pred)
    mae = mean_absolute_error(y_test, y_pred)
    rmse = np.sqrt(mean_squared_error(y_test, y_pred))

    target_X = pd.DataFrame(
        [target_row[features].values],
        columns=features
    )

    predicted_value = model.predict(target_X)[0]
    actual_value = target_row[TARGET]

    error = predicted_value - actual_value #実績との誤差比較
    abs_error = abs(error)#絶対誤差の取得

    return {
        "analysis_date": datetime.now().strftime("%Y-%m-%d"),
        "model_name": model_name,
        "target_month": target_month,
        "target_date": target_date.strftime("%Y-%m-%d"),
        "target": TARGET,
        "feature_type": f"lag{LAG_DAYS}",
        "r2": r2,
        "mae": mae,
        "rmse": rmse,
        "predicted_value": predicted_value,
        "actual_value": actual_value,
        "error": error,
        "abs_error": abs_error,
    }

#モデルごとにバックテストをおこない、実績との比較
def run_backtest(df, features, n_months=6):
    models = {
        "LinearRegression": LinearRegression(),
        "RandomForest": RandomForestRegressor(
            n_estimators=300,
            max_depth=5,
            random_state=42
        ),
        "XGBoost": XGBRegressor(
            n_estimators=300,
            learning_rate=0.05,
            max_depth=3,
            random_state=42,
            objective="reg:squarederror"
        ),
    }

    target_months = get_recent_target_months(df, n_months=n_months)
    print("バックテスト対象月:", target_months)

    results = []

    for target_month in target_months:
        for model_name, model in models.items():
            result = evaluate_model(
                model_name=model_name,
                model=model,
                df=df,
                features=features,
                target_month=target_month
            )

            if result is not None:
                results.append(result)

    return pd.DataFrame(results)

#データベースにバックテストの結果を更新
def save_results(result_df):
    conn = sqlite3.connect(DB_PATH)

    conn.execute("DELETE FROM nikkei_model_backtest")

    result_df.to_sql(
        "nikkei_model_backtest",
        conn,
        if_exists="append",
        index=False
    )

    conn.commit()
    conn.close()

    print("nikkei_model_backtest 更新完了")


def main():
    df = load_data()
    print("データ読み込み完了:", df.shape)

    df, features = preprocess_data(df)
    print("前処理完了:", df.shape)
    print("使用特徴量:", features)

    result_df = run_backtest(df, features, n_months=6)

    print("\nバックテスト結果")
    print(result_df)

    save_results(result_df)

    print("\n日経平均 機械学習バックテスト 完了")


if __name__ == "__main__":
    main()