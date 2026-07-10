# prediction_model.py

import sqlite3
import pandas as pd

from sklearn.linear_model import LinearRegression
from sklearn.metrics import r2_score, mean_absolute_error, mean_squared_error
from sklearn.model_selection import train_test_split
import numpy as np
from sklearn.ensemble import RandomForestRegressor

DB_PATH = "./db/stock_analysis.db"

TABLE_NAME = "ana_policy_rate_lag_features"
TARGET = "close_price"

LAG_FEATURES = [
    "policy_rate_lag0",
    "policy_rate_lag1",
    "policy_rate_lag2",
    "policy_rate_lag3",
    "policy_rate_lag6",
]


def load_feature_data():
    """
    ラグ特徴量テーブルからデータを取得する
    """
    conn = sqlite3.connect(DB_PATH)

    query = f"""
    SELECT
        trade_date,
        stock_code,
        stock_name,
        close_price,
        policy_rate_lag0,
        policy_rate_lag1,
        policy_rate_lag2,
        policy_rate_lag3,
        policy_rate_lag6
    FROM {TABLE_NAME}
    ORDER BY trade_date
    """

    df = pd.read_sql_query(query, conn)
    conn.close()

    return df


def train_single_feature_model(df, feature_name):
    """
    指定したラグ特徴量のみを使って回帰モデルを作成する
    """

    X = df[[feature_name]]
    y = df[TARGET]

    # 時系列なので、本来はshuffle=Falseが自然
    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=0.2,
        shuffle=False
    )

    model = LinearRegression()
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)

    r2 = r2_score(y_test, y_pred) #決定係数（モデルがどれだけ説明できているか）
    mae = mean_absolute_error(y_test, y_pred) #平均絶対誤差(平均してどれくらいずれているか)
    rmse = np.sqrt(mean_squared_error(y_test, y_pred)) #二乗平均平方根誤差(大きな誤差をより重く評価した誤差)

    return {
        "feature": feature_name,
        "r2": r2,
        "mae": mae,
        "rmse": rmse,
        "coefficient": model.coef_[0],
        "intercept": model.intercept_,
    }


def run_lag_comparison(df):
    """
    各ラグ特徴量ごとにモデルを作成し、精度を比較する
    """

    results = []

    for feature in LAG_FEATURES:
        result = train_single_feature_model(df, feature)
        results.append(result)

    result_df = pd.DataFrame(results)

    return result_df


def save_prediction_results(result_df):
    """
    予測結果をDBへ保存する
    DELETE → INSERT
    """

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        DELETE FROM ana_policy_rate_prediction_results
    """)

    insert_sql = """
    INSERT INTO ana_policy_rate_prediction_results (
        feature,
        r2,
        mae,
        rmse,
        coefficient,
        intercept
    )
    VALUES (?, ?, ?, ?, ?, ?)
    """

    cursor.executemany(
        insert_sql,
        result_df[
            [
                "feature",
                "r2",
                "mae",
                "rmse",
                "coefficient",
                "intercept",
            ]
        ].values.tolist()
    )

    conn.commit()
    conn.close()

    print("ana_policy_rate_prediction_results テーブル更新完了")

def predict_next_month(df, feature_name, forecast_target_month):
    """
    指定した特徴量を使って、次月のANA終値を予測する
    """

    X = df[[feature_name]]
    y = df[TARGET]

    model = LinearRegression()
    model.fit(X, y)

    # 最新行の特徴量を使って予測
    latest_row = df.sort_values("trade_date").iloc[-1]
    input_value = latest_row[feature_name]

    predicted_price = model.predict([[input_value]])[0]

    return {
        "forecast_target_month": forecast_target_month,
        "feature": feature_name,
        "input_policy_rate": input_value,
        "predicted_close_price": predicted_price,
        "coefficient": model.coef_[0],
        "intercept": model.intercept_,
    }


def save_forecast_result(forecast_result):
    """
    予測結果をDBへ保存する
    """

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        DELETE FROM ana_policy_rate_forecast
    """)

    insert_sql = """
    INSERT INTO ana_policy_rate_forecast (
        forecast_target_month,
        feature,
        input_policy_rate,
        predicted_close_price,
        coefficient,
        intercept
    )
    VALUES (?, ?, ?, ?, ?, ?)
    """

    cursor.execute(
        insert_sql,
        (
            forecast_result["forecast_target_month"],
            forecast_result["feature"],
            forecast_result["input_policy_rate"],
            forecast_result["predicted_close_price"],
            forecast_result["coefficient"],
            forecast_result["intercept"],
        )
    )

    conn.commit()
    conn.close()

    print("ana_policy_rate_forecast テーブル更新完了")

def train_random_forest_model(df, feature_name):
    """
    指定したラグ特徴量のみを使ってRandomForest回帰モデルを作成する
    """

    X = df[[feature_name]]
    y = df[TARGET]

    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=0.2,
        shuffle=False
    )

    model = RandomForestRegressor(
        n_estimators=100,
        random_state=42
    )

    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)

    r2 = r2_score(y_test, y_pred)
    mae = mean_absolute_error(y_test, y_pred)
    rmse = np.sqrt(mean_squared_error(y_test, y_pred))

    return {
        "model_name": "RandomForest",
        "feature": feature_name,
        "r2": r2,
        "mae": mae,
        "rmse": rmse,
        "predicted_close_price": model.predict([[df.sort_values("trade_date").iloc[-1][feature_name]]])[0],
    }

def run_random_forest_comparison(df):
    """
    各ラグ特徴量ごとにRandomForestモデルを作成し、精度を比較する
    """

    results = []

    for feature in LAG_FEATURES:
        result = train_random_forest_model(df, feature)
        results.append(result)

    return pd.DataFrame(results)

def get_actual_close_price(df, target_month):
    """
    対象月の最終営業日の終値を取得する
    例: target_month = "2026-06"
    """
    df = df.copy()
    df["trade_date"] = pd.to_datetime(df["trade_date"])

    target_df = df[df["trade_date"].dt.strftime("%Y-%m") == target_month]

    if target_df.empty:
        return None

    latest_row = target_df.sort_values("trade_date").iloc[-1]
    return latest_row[TARGET]


def train_and_predict_model(df, feature_name, model_name, forecast_target_month):
    """
    指定モデルで学習・評価・対象月予測を行う
    """

    df = df.copy()
    df["trade_date"] = pd.to_datetime(df["trade_date"])

    # 未来データを学習に使わない
    train_df = df[df["trade_date"].dt.strftime("%Y-%m") < forecast_target_month]
    train_df = train_df.dropna().reset_index(drop=True)

    X = train_df[[feature_name]]
    y = train_df[TARGET]

    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=0.2,
        shuffle=False
    )

    if model_name == "LinearRegression":
        model = LinearRegression()
    elif model_name == "RandomForest":
        model = RandomForestRegressor(
            n_estimators=100,
            random_state=42
        )
    else:
        raise ValueError("未対応のモデルです")

    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)

    r2 = r2_score(y_test, y_pred)
    mae = mean_absolute_error(y_test, y_pred)
    rmse = np.sqrt(mean_squared_error(y_test, y_pred))

    # 予測に使う入力値：対象月より前の最新データ
    latest_row = train_df.sort_values("trade_date").iloc[-1]
    input_policy_rate = latest_row[feature_name]

    input_df = pd.DataFrame(
        [[input_policy_rate]],
        columns=[feature_name]
    )

    predicted_close_price = model.predict(input_df)[0]

    actual_close_price = get_actual_close_price(df, forecast_target_month)

    if actual_close_price is not None:
        error = predicted_close_price - actual_close_price
        abs_error = abs(error)
    else:
        error = None
        abs_error = None

    return {
        "model_name": model_name,
        "feature": feature_name,
        "forecast_target_month": forecast_target_month,
        "input_policy_rate": input_policy_rate,
        "predicted_close_price": predicted_close_price,
        "actual_close_price": actual_close_price,
        "error": error,
        "abs_error": abs_error,
        "r2": r2,
        "mae": mae,
        "rmse": rmse,
    }


def run_model_comparison(df, forecast_target_month):
    """
    LinearRegressionとRandomForestを比較する
    """

    results = []

    for feature in LAG_FEATURES:
        results.append(
            train_and_predict_model(
                df,
                feature,
                "LinearRegression",
                forecast_target_month
            )
        )

        results.append(
            train_and_predict_model(
                df,
                feature,
                "RandomForest",
                forecast_target_month
            )
        )

    return pd.DataFrame(results)


def save_model_comparison(result_df):
    """
    モデル比較結果をDBへ保存する
    """

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        DELETE FROM ana_policy_rate_model_comparison
    """)

    insert_sql = """
    INSERT INTO ana_policy_rate_model_comparison (
        model_name,
        feature,
        forecast_target_month,
        input_policy_rate,
        predicted_close_price,
        actual_close_price,
        error,
        abs_error,
        r2,
        mae,
        rmse
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    cursor.executemany(
        insert_sql,
        result_df[
            [
                "model_name",
                "feature",
                "forecast_target_month",
                "input_policy_rate",
                "predicted_close_price",
                "actual_close_price",
                "error",
                "abs_error",
                "r2",
                "mae",
                "rmse",
            ]
        ].values.tolist()
    )

    conn.commit()
    conn.close()

    print("ana_policy_rate_model_comparison テーブル更新完了")

def main():
    df = load_feature_data()

    print("特徴量データ読み込み完了")
    print(df.shape)

    df = df.dropna().reset_index(drop=True)

    result_df = run_lag_comparison(df)

    print("予測モデル比較結果")
    print(result_df)

    save_prediction_results(result_df)

    forecast_target_month = "2026-05"

    comparison_df = run_model_comparison(
        df,
        forecast_target_month
    )

    print("モデル比較結果")
    print(comparison_df)

    save_model_comparison(comparison_df)

    print("予測モデル作成完了")


if __name__ == "__main__":
    main()