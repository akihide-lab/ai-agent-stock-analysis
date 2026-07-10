import sqlite3
import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.metrics import r2_score
import statsmodels.api as sm
from statsmodels.stats.outliers_influence import variance_inflation_factor
from sklearn.preprocessing import StandardScaler


# DBファイルのパス
DB_PATH = "./db/stock_analysis.db"

# 分析用VIEW名
VIEW_NAME = "stock_selection_view"

#データの読み込み
def load_analysis_view():
    """
    SQLiteから分析用VIEWを読み込む
    """
    conn = sqlite3.connect(DB_PATH)

    query = f"""
    SELECT *
    FROM {VIEW_NAME}
    """

    #SQLliteのデータを読み込み、データフレーム化
    df = pd.read_sql_query(query, conn)

    conn.close()

    return df

#データ加工
def preprocess_data(df):
    """
    相関分析・重回帰分析用の前処理
    """
    #航空３社
    TARGET_STOCKS = [
    "ANAホールディングス",
    "日本航空",
    "スカイマーク"
    ]

    #航空３社のみコピー
    analysis_df = df[
    df["stock_name"].isin(TARGET_STOCKS)
    ].copy()

    use_columns = [
        "trade_date",
        "stock_name",
        "close_price",
        "wti_price",
        "usd_jpy",
        "policy_rate",
        "jgb_10y_yield",
        "cpi_index",
        "gdp_growth"
    ]

    # 必要な列のみ抽出
    analysis_df = analysis_df[use_columns].copy()

    # 欠損値を削除
    analysis_df = analysis_df.dropna()

    return analysis_df

#削除新規（ID管理していないため）
def replace_table_data(table_name, df):
    """
    指定テーブルのデータを全削除してから、DataFrameをINSERTする
    """
    conn = sqlite3.connect(DB_PATH)

    try:
        conn.execute(f"DELETE FROM {table_name}")
        df.to_sql(table_name, conn, if_exists="append", index=False)
        conn.commit()
        print(f"{table_name} への保存完了: {len(df)}件")

    except Exception as e:
        conn.rollback()
        print(f"{table_name} への保存失敗: {e}")
        raise

    finally:
        conn.close()

#相関係数（関係のある指標を探す）の算出
def calculate_correlation(df):
    features = [
        "wti_price",
        "usd_jpy",
        "policy_rate",
        "jgb_10y_yield",
        "cpi_index",
        "gdp_growth"
    ]

    target = "close_price"
    results = []

    #各企業ごとに、各説明変数と目的変数の相関を出力
    for stock_name, group in df.groupby("stock_name"):
        for feature in features:
            corr = group[target].corr(group[feature])

            results.append({
                "stock_name": stock_name,
                "indicator": feature,
                "correlation": corr
            })

    return pd.DataFrame(results)

#重回帰分析（他の指標を考慮しても影響があるか確認）(標準化無し)
# def multiple_regression(df):
#     """
#     航空3社ごとに重回帰分析を実施
#     """

#     #説明変数
#     features = [
#         "wti_price",
#         "usd_jpy",
#         "policy_rate",
#         "jgb_10y_yield",
#         "cpi_index",
#         "gdp_growth"
#     ]

#     #目的変数
#     target = "close_price"

#     for stock_name, group in df.groupby("stock_name"):

#         print("=" * 60)
#         print(f"銘柄：{stock_name}")
#         print("=" * 60)

#         X = group[features] #説明変数
#         y = group[target] #目的変数

#         model = LinearRegression()
#         model.fit(X, y) #学習

#         y_pred = model.predict(X)#モデル学習後の結果を格納

#         print("切片:", model.intercept_) #説明変数が０の場合の基準値
#         print()

#         print("回帰係数") #どの要因がどれくらい影響するか
#         for feature, coef in zip(features, model.coef_):
#             print(f"{feature:<20}: {coef:.4f}")

#         print()
#         print(f"決定係数(R²): {r2_score(y, y_pred):.4f}") #このモデルは平均と比べてどのくらい説明できるか
#         print()



#重回帰分析（他の指標を考慮しても影響があるか確認）(標準化無し)
def regression_with_pvalue(df):
    features = [
        "wti_price",
        "usd_jpy",
        "policy_rate",
        "jgb_10y_yield",
        "cpi_index",
        "gdp_growth"
    ]

    target = "close_price"
    regression_results = []
    summary_results = []

    for stock_name, group in df.groupby("stock_name"):
        X = group[features]
        y = group[target]

        X = sm.add_constant(X)
        model = sm.OLS(y, X).fit()#学習

        summary_results.append({
            "stock_name": stock_name,
            "r2": model.rsquared #このモデルは平均と比べてどのくらい説明できるか
        })

        for indicator in model.params.index:
            regression_results.append({
                "stock_name": stock_name,
                "indicator": indicator,
                "coefficient": model.params[indicator],#傾き（変化量の大きさ）
                "t_value": model.tvalues[indicator],#影響量（係数/標準誤差）が正しいのか
                "p_value": model.pvalues[indicator] #t値の数値をもとに確率的起きるか、検証する値（正規分布に沿って）
            })

    regression_df = pd.DataFrame(regression_results)
    summary_df = pd.DataFrame(summary_results)

    return regression_df, summary_df
    

#多重共線性（説明変数同士が似た情報を持っていないかを確認する）
def calculate_vif(df):
    features = [
        "wti_price",
        "usd_jpy",
        "policy_rate",
        "jgb_10y_yield",
        "cpi_index",
        "gdp_growth"
    ]

    results = []

    for stock_name, group in df.groupby("stock_name"):
        X = group[features].copy()

        for i, feature in enumerate(X.columns):
            vif = variance_inflation_factor(X.values, i)

            results.append({
                "stock_name": stock_name,
                "indicator": feature,
                "vif": vif
            })

    return pd.DataFrame(results)

#重回帰分析(標準化して、どの説明変数が一番影響をあたえているか)
def calculate_standardized_regression(df):
    features = [
        "wti_price",
        "usd_jpy",
        "policy_rate",
        "jgb_10y_yield",
        "cpi_index",
        "gdp_growth"
    ]

    target = "close_price"
    results = []

    for stock_name, group in df.groupby("stock_name"):
        X = group[features]
        y = group[target]

        scaler_x = StandardScaler()
        scaler_y = StandardScaler()

        X_std = scaler_x.fit_transform(X)
        #学習用に次元の修正（１次元→２次元→１次元）
        y_std = scaler_y.fit_transform(y.values.reshape(-1, 1)).ravel()

        model = LinearRegression()
        model.fit(X_std, y_std)

        for feature, coef in zip(features, model.coef_):
            results.append({
                "stock_name": stock_name,
                "indicator": feature,
                "standardized_coefficient": coef
            })

    return pd.DataFrame(results)

def main():
    df = load_analysis_view()
    analysis_df = preprocess_data(df)

    corr_df = calculate_correlation(analysis_df)
    regression_df, summary_df = regression_with_pvalue(analysis_df)
    vif_df = calculate_vif(analysis_df)
    std_df = calculate_standardized_regression(analysis_df)

    replace_table_data("correlation_analysis", corr_df)
    replace_table_data("regression_analysis", regression_df)
    replace_table_data("regression_summary", summary_df)
    replace_table_data("vif_analysis", vif_df)
    replace_table_data("standardized_regression", std_df)

    print("分析結果のDB保存が完了しました")


if __name__ == "__main__":
    main()