import sqlite3
from datetime import datetime

import pandas as pd
import statsmodels.api as sm
from sklearn.preprocessing import StandardScaler
from statsmodels.stats.outliers_influence import variance_inflation_factor


DB_PATH = "./db/nikkei_stock_average_analysis.db"
VIEW_NAME = "nikkei_analysis_view"
TARGET = "nikkei_close"

FEATURES = [
    "sp500_close",
    "nasdaq100_close",
    "dow_close",
    "vix_close",
    "us_10y_yield",
    "gold_close",
    "wti_price",
    "usd_jpy",
    "policy_rate",
    "jgb_10y_yield",
    "cpi_index",
    "cpi_mom",
    "gdp_growth",
]


def load_analysis_view():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql(f"SELECT * FROM {VIEW_NAME}", conn)
    conn.close()

    df["trade_date"] = pd.to_datetime(df["trade_date"])
    return df

#データの前処理
def preprocess_data(df):
    use_cols = ["trade_date", TARGET] + FEATURES #必要列の抽出
    df = df[use_cols].copy()

    for col in [TARGET] + FEATURES:
        df[col] = pd.to_numeric(df[col], errors="coerce") #数値変換

    df = df.dropna().reset_index(drop=True) #欠損削除
    return df

#相関分析
def calculate_correlation(df):
    results = []

    for feature in FEATURES:
        corr = df[[TARGET, feature]].corr().iloc[0, 1] #相関係数の算出
        results.append({
            "analysis_date": datetime.now().strftime("%Y-%m-%d"),
            "target": TARGET,
            "indicator": feature,
            "correlation": corr,
        })

    return pd.DataFrame(results)


#重回帰分析でT検定を行う
def regression_with_pvalue(df):
    X = df[FEATURES]
    y = df[TARGET]

    X = sm.add_constant(X)#定数項の追加
    model = sm.OLS(y, X).fit()#重回帰モデルの作成

    results = []

    for indicator in model.params.index:
        if indicator == "const":
            continue

        results.append({
            "analysis_date": datetime.now().strftime("%Y-%m-%d"),
            "target": TARGET,
            "indicator": indicator,
            "coefficient": model.params[indicator],
            "t_value": model.tvalues[indicator],
            "p_value": model.pvalues[indicator],
        })

    summary_df = pd.DataFrame([{
        "analysis_date": datetime.now().strftime("%Y-%m-%d"),
        "target": TARGET,
        "r2": model.rsquared,#決定係数
        "adj_r2": model.rsquared_adj,#調整済み決定係数
    }])

    return pd.DataFrame(results), summary_df

#多重共線性
def calculate_vif(df):
    X = df[FEATURES].copy()
    X = X.dropna()

    results = []

    for i, col in enumerate(X.columns):
        results.append({
            "analysis_date": datetime.now().strftime("%Y-%m-%d"),
            "target": TARGET,
            "indicator": col,
            "vif": variance_inflation_factor(X.values, i),#多重共線性の計算
        })

    return pd.DataFrame(results)

#標準化回帰係数
def calculate_standardized_regression(df):
    scaler = StandardScaler()

    X_scaled = scaler.fit_transform(df[FEATURES])
    X_scaled_df = pd.DataFrame(
        X_scaled,
        columns=FEATURES
    )#説明変数の標準化

    y = df[TARGET]

    X_scaled_df = sm.add_constant(X_scaled_df)
    model = sm.OLS(y, X_scaled_df).fit()

    results = []

    for feature in FEATURES:
        results.append({
            "analysis_date": datetime.now().strftime("%Y-%m-%d"),
            "target": TARGET,
            "indicator": feature,
            "standardized_coefficient": model.params[feature],#標準化回帰係数の取得
        })

    return pd.DataFrame(results)

#DB更新
def replace_table_data(table_name, df):
    conn = sqlite3.connect(DB_PATH)

    conn.execute(f"DELETE FROM {table_name}")
    df.to_sql(table_name, conn, if_exists="append", index=False)

    conn.commit()
    conn.close()

    print(f"{table_name} 更新完了")


def main():
    df = load_analysis_view()
    print("データ読み込み完了:", df.shape)

    df = preprocess_data(df)
    print("前処理完了:", df.shape)

    correlation_df = calculate_correlation(df)
    regression_df, summary_df = regression_with_pvalue(df)
    vif_df = calculate_vif(df)
    standardized_df = calculate_standardized_regression(df)

    print("\n相関分析")
    print(correlation_df.sort_values("correlation", ascending=False))

    print("\n重回帰分析")
    print(regression_df)

    print("\n決定係数")
    print(summary_df)

    print("\nVIF")
    print(vif_df.sort_values("vif", ascending=False))

    print("\n標準化回帰係数")
    print(standardized_df.sort_values("standardized_coefficient", ascending=False))

    replace_table_data("nikkei_correlation_analysis", correlation_df)
    replace_table_data("nikkei_regression_analysis", regression_df)
    replace_table_data("nikkei_regression_summary", summary_df)
    replace_table_data("nikkei_vif_analysis", vif_df)
    replace_table_data("nikkei_standardized_regression", standardized_df)

    print("\n日経平均 統計解析 完了")


if __name__ == "__main__":
    main()