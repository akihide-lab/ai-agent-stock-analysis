import sqlite3
import pandas as pd
import yfinance as yf

db_path = "./db/stock_analysis.db"

#データ整形(CPI)
def load_cpi_csv(path, value_column_name):
    #官公庁CSVを読み込み、年月＋値の2列に整形する
    df = pd.read_csv(
        path,
        encoding="cp932"
    )

    # 不要行削除
    df = df.iloc[5:]

    # カラム名変更
    df.columns = [
        "year_month",
        value_column_name
    ]

    # 空白行削除
    df = df.dropna()

    return df

#データ整形(GDP)
def load_gdp_csv(path, value_column_name):
    #GDPのCSVを読み込み、期間＋値の2列に整形する

    df = pd.read_csv(
        path,
        encoding="cp932",
        skiprows=5
    )

    # 必要列取得
    df = df[
        [
            "Unnamed: 0",
            "GDP(Expenditure Approach)"
        ]
    ]

    # カラム名変更
    df.columns = [
        "period",
        value_column_name
    ]

    # 空白行削除
    df = df.dropna()

    return df

#CPIデータをデータフレーム化
def create_cpi_df():
    # CPI指数
    cpi_index_df = load_cpi_csv(
        "./data/zmi2020r.csv",
        "cpi_index"
    )

    # CPI前月比
    cpi_mom_df = load_cpi_csv(
        "./data/zmm2020r.csv",
        "cpi_mom"
    )

    # 左外部結合
    cpi_df = cpi_index_df.merge(
        cpi_mom_df,
        on="year_month",
        how="left"
    )

    cpi_df["cpi_index"] = pd.to_numeric(cpi_df["cpi_index"], errors="coerce")
    cpi_df["cpi_mom"] = pd.to_numeric(cpi_df["cpi_mom"], errors="coerce")
    # print(cpi_df.head(20))
    cpi_df["year_month"] = (
    cpi_df["year_month"]
        .astype(str)
        .str.zfill(6)
    )

    cpi_df["year_month"] = (
        cpi_df["year_month"].str[:4]
        + "-"
        + cpi_df["year_month"].str[4:6]
    )

    return cpi_df


#gdp取得
def create_gdp_df():

    gdp_amount_df = load_gdp_csv(
        "./data/gaku-jfy2612.csv",
        "gdp_amount"
    )

    gdp_growth_df = load_gdp_csv(
        "./data/ritu-jfy2612.csv",
        "gdp_growth"
    )

    # マージ
    gdp_df = gdp_amount_df.merge(
        gdp_growth_df,
        on="period",
        how="left"
    )

    # 文字列を数値化
    gdp_df["gdp_amount"] = (
        gdp_df["gdp_amount"]
        .astype(str)
        .str.replace(",", "", regex=False)
    )

    gdp_df["gdp_amount"] = pd.to_numeric(
        gdp_df["gdp_amount"],
        errors="coerce"
    )

    gdp_df["gdp_growth"] = pd.to_numeric(
        gdp_df["gdp_growth"],
        errors="coerce"
    )

    gdp_df["fiscal_year"] = gdp_df["period"].astype(str).str[:4]

    return gdp_df

#和暦だとDBに挿入する際に文字列順になり順番通りにならないので西暦に変換
def convert_japanese_era_date(value):
    value = str(value)

    era = value[0]
    y, m, d = value[1:].split(".")

    y = int(y)
    m = int(m)
    d = int(d)

    if era == "R":
        year = 2018 + y
    elif era == "H":
        year = 1988 + y
    elif era == "S":
        year = 1925 + y
    else:
        return None

    return f"{year:04d}-{m:02d}-{d:02d}"

def create_jgb_df():
    #長期金利CSVから10年国債利回りDataFrameを作成する

    jgb_df = pd.read_csv(
        "./data/jgbcm_all.csv",
        encoding="cp932",
        header=1
    )

    jgb_df = jgb_df[
        [
            "基準日",
            "10年"
        ]
    ]

    jgb_df.columns = [
        "date",
        "jgb_10y_yield"
    ]

    jgb_df["date"] = jgb_df["date"].apply(convert_japanese_era_date)
    
    jgb_df = jgb_df.replace("-", None)
   

    jgb_df["jgb_10y_yield"] = pd.to_numeric(
        jgb_df["jgb_10y_yield"],
        errors="coerce"
    )

    jgb_df = jgb_df.dropna()

    return jgb_df

def create_policy_rate_df():
    #政策金利CSVから政策金利DataFrameを作成する

    policy_rate_df = pd.read_csv(
        "./data/nme_R031.793954.20260615104522.02.csv",
        encoding="cp932"
    )

    policy_rate_df = policy_rate_df[
        [
            "データコード",
            "FM02'STRECLUCON"
        ]
    ]

    policy_rate_df.columns = [
        "year_month",
        "policy_rate"
    ]

    policy_rate_df = policy_rate_df.iloc[1:]
    policy_rate_df = policy_rate_df.dropna()

    policy_rate_df["year_month"] = (
        policy_rate_df["year_month"]
        .astype(str)
        .str.replace("/", "-", regex=False)
    )

    policy_rate_df["policy_rate"] = pd.to_numeric(
        policy_rate_df["policy_rate"],
        errors="coerce"
    )

    return policy_rate_df

def create_exchange_rate_df():
    """yfinanceからUSD/JPYの日次為替データを取得する"""

    exchange_rate_df = yf.download(
        "USDJPY=X",
        period="10y",
        auto_adjust=False
    )

    exchange_rate_df = exchange_rate_df[("Close", "USDJPY=X")].reset_index()

    exchange_rate_df.columns = [
        "date",
        "usd_jpy"
    ]

    exchange_rate_df["date"] = exchange_rate_df["date"].dt.strftime("%Y-%m-%d")

    exchange_rate_df["usd_jpy"] = pd.to_numeric(
        exchange_rate_df["usd_jpy"],
        errors="coerce"
    )

    return exchange_rate_df

def create_oil_price_df():
    """yfinanceからWTI原油価格データを取得する"""

    oil_df = yf.download(
        "CL=F",
        period="10y",
        auto_adjust=False
    )

    # MultiIndex対策
    if isinstance(oil_df.columns, pd.MultiIndex):
        oil_df = oil_df[("Close", "CL=F")].reset_index()
    else:
        oil_df = oil_df[["Close"]].reset_index()

    oil_df.columns = [
        "date",
        "wti_price"
    ]

    oil_df["date"] = oil_df["date"].dt.strftime(
        "%Y-%m-%d"
    )

    oil_df["wti_price"] = pd.to_numeric(
        oil_df["wti_price"],
        errors="coerce"
    )

    oil_df = oil_df.dropna()

    return oil_df

cpi_df = create_cpi_df() #消費者物価指数
gdp_df = create_gdp_df() #国内総生産
jgb_df = create_jgb_df() #国債金利
policy_rate_df = create_policy_rate_df() #政策金利
exchange_rate_df = create_exchange_rate_df() #為替
oil_price_df = create_oil_price_df() #WTI原油価格

# print(jgb_df.head())
# print(policy_rate_df.head())
# print(gdp_df.head())
# print(exchange_rate_df.head())
# print(exchange_rate_df.columns)

def insert_cpi(conn, cpi_df):

    sql = """
    INSERT INTO cpi (
        year_month,
        cpi_index,
        cpi_mom
    )
    VALUES (
        ?, ?, ?
    )
    """

    data = []

    for _, row in cpi_df.iterrows():

        data.append(
            (
                row["year_month"],
                row["cpi_index"],
                row["cpi_mom"],
            )
        )

    conn.executemany(sql, data) #まとめて実行

def insert_gdp(conn, gdp_df):

    sql = """
    INSERT INTO gdp (
        fiscal_year,
        period,
        gdp_amount,
        gdp_growth
    )
    VALUES (
        ?, ?, ?, ?
    )
    """

    data = []

    for _, row in gdp_df.iterrows():

        data.append(
            (
                row["fiscal_year"],
                row["period"],
                row["gdp_amount"],
                row["gdp_growth"],
            )
        )

    conn.executemany(sql, data) #まとめて実行

def insert_jgb(conn, jgb_df):

    sql = """
    INSERT INTO interest_rate_long (
        date,
        jgb_10y_yield
    )
    VALUES (
        ?, ?
    )
    """

    data = []

    for _, row in jgb_df.iterrows():

        data.append(
            (
                row["date"],
                row["jgb_10y_yield"]
            )
        )

    conn.executemany(sql, data) #まとめて実行


def insert_policy_rate(conn, policy_rate_df):

    sql = """
    INSERT INTO policy_rate (
        year_month,
        policy_rate
    )
    VALUES (
        ?, ?
    )
    """

    data = []

    for _, row in policy_rate_df.iterrows():

        data.append(
            (
                row["year_month"],
                row["policy_rate"]
            )
        )

    conn.executemany(sql, data) #まとめて実行

def insert_exchange_rate(conn, exchange_rate_df):

    sql = """
    INSERT INTO exchange_rates (
        date,
        usd_jpy
    )
    VALUES (
        ?, ?
    )
    """

    data = []

    for _, row in exchange_rate_df.iterrows():

        data.append(
            (
                row["date"],
                row["usd_jpy"]
            )
        )

    conn.executemany(sql, data) #まとめて実行

def insert_oil_price(conn, oil_price_df):

    sql = """
    INSERT INTO oil_prices (
        date,
        wti_price
    )
    VALUES (
        ?, ?
    )
    """

    data = []

    for _, row in oil_price_df.iterrows():

        data.append(
            (
                row["date"],
                row["wti_price"]
            )
        )

    conn.executemany(sql,data)

conn = sqlite3.connect(db_path)

conn.execute("DELETE FROM cpi")
insert_cpi(conn, cpi_df)

conn.execute("DELETE FROM gdp")
insert_gdp(conn, gdp_df)

conn.execute("DELETE FROM interest_rate_long")
insert_jgb(conn, jgb_df)

conn.execute("DELETE FROM policy_rate")
insert_policy_rate(conn, policy_rate_df)

conn.execute("DELETE FROM exchange_rates")
insert_exchange_rate(conn, exchange_rate_df)

conn.execute("DELETE FROM oil_prices")
insert_oil_price(conn,oil_price_df)

conn.commit()
conn.close()