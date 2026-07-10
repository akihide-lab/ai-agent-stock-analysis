import sqlite3
from datetime import datetime
import yfinance as yf

db_path = "./db/stock_analysis.db"

#必要な銘柄情報の設定
stocks = [
    ("9432", "9432.T", "NTT"),
    ("9433", "9433.T", "KDDI"),
    ("9434", "9434.T", "ソフトバンク"),

    ("9201", "9201.T", "日本航空(JAL)"),  # 日本航空（JAL）
    ("9202", "9202.T", "ANAホールディングス(ANA)"),  # ANAホールディングス（ANA）
    ("9204", "9204.T","スカイマーク"),  # スカイマーク
]

conn = sqlite3.connect(db_path)

conn.execute("DELETE FROM finance")

#データが空の場合にエラー落ち回避と、指定年度のデータ取得
def get_financial_value_by_year(financials, item_name, fiscal_date):
    try:
        if financials is None:
            return None
        if financials.empty:
            return None
        if item_name not in financials.index:
            return None
        
        #指定年度を指定
        value = financials.loc[item_name, fiscal_date]

        if value != value:  # NaN判定
            return None

        return float(value)

    except Exception:
        return None

for stock_code, ticker, stock_name in stocks: #下のブロックのINSERTで使用するため三つの変数でfor文を回している
    print(f"{stock_code} {stock_name} の財務データ取得中...")

    t = yf.Ticker(ticker)

    #基本情報の取得（PBRや配当金など）
    try:
        info = t.info
    except Exception:
        info = {}

    #売上高、営業利益、純利益の取得(PL)
    try:
        financials = t.financials
    except Exception:
        financials = None

    #総資産、純資産、負債（BS）
    try:
        balance_sheet = t.balance_sheet
    except Exception:
        balance_sheet = None
    
    print(balance_sheet.index)

    #財務データの存在チェック（コード間違えの場合のチェック処理）
    if financials is None or financials.empty:
        print(f"{stock_code} は財務データが取得できませんでした")
        continue

    eps = info.get("trailingEps") #一株利益(EPS)
    per = info.get("trailingPE") #株価収益率(PER)
    pbr = info.get("priceToBook") #株価純資産倍率(PBR)
    dividend = info.get("dividendRate")#配当金

    dividend_yield = info.get("dividendYield")#配当利回り
    if dividend_yield is not None and dividend_yield > 1: #パワーBIで％をつけると100がけされるから
        dividend_yield = dividend_yield / 100

    market_cap = info.get("marketCap") #時価総額
    updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S") #更新日時

    for fiscal_date in financials.columns:
        fiscal_year = str(fiscal_date.date())
        #結合用の日付列の追加
        fiscal_year_key = str(fiscal_date.year - 1)

        sales = get_financial_value_by_year(financials, "Total Revenue", fiscal_date) #売上
        
        if sales is None: #PLのデータが無い場合は飛ばす
            #NTTのデータのズレ確認
            print(f"{stock_code} {fiscal_year} は売上が取得できないためスキップ")
            continue

        operating_profit = get_financial_value_by_year(financials, "Operating Income", fiscal_date) #営業利益
        net_profit = get_financial_value_by_year(financials, "Net Income", fiscal_date) #純利益
    
        equity = get_financial_value_by_year(balance_sheet, "Stockholders Equity", fiscal_date) #純資産

        total_assets = get_financial_value_by_year(balance_sheet, "Total Assets", fiscal_date) #総資産
        total_liabilities = get_financial_value_by_year(balance_sheet, "Total Liabilities Net Minority Interest", fiscal_date) #総負債
        total_debt = get_financial_value_by_year(balance_sheet, "Total Debt", fiscal_date) #有利子負債
        net_debt = get_financial_value_by_year(balance_sheet, "Net Debt", fiscal_date) #純有利子負債
        cash = get_financial_value_by_year(balance_sheet, "Cash And Cash Equivalents", fiscal_date) #現金
        current_assets = get_financial_value_by_year(balance_sheet, "Current Assets", fiscal_date) #流動資産
        current_liabilities = get_financial_value_by_year(balance_sheet, "Current Liabilities", fiscal_date) #流動負債
        working_capital = get_financial_value_by_year(balance_sheet, "Working Capital", fiscal_date) #運転資本
        # ここまで追加


        roe = None
        if net_profit is not None and equity not in (None, 0): #ROE(お金を効率よく稼げているか)の計算
            roe = net_profit / equity
        
        equity_ratio = None
        if equity is not None and total_assets not in (None, 0): #自己資本比率　自己資本 ÷ 総資産
            equity_ratio = equity / total_assets

        debt_ratio = None
        if total_liabilities is not None and total_assets not in (None, 0):#負債比率 総負債 ÷ 総資産
            debt_ratio = total_liabilities / total_assets

        debt_to_equity_ratio = None
        if total_debt is not None and equity not in (None, 0):#D/Eレシオ 有利子負債 ÷ 自己資本
            debt_to_equity_ratio = total_debt / equity

        current_ratio = None
        if current_assets is not None and current_liabilities not in (None, 0): #流動比率 流動資産 ÷ 流動負債
            current_ratio = current_assets / current_liabilities

        # conn.execute(
        #     """
        #     DELETE FROM finance
        #     WHERE stock_code = ?
        #       AND fiscal_year = ?
        #     """,
        #     (stock_code, fiscal_year)
        # )

        

        conn.execute(
            """
            INSERT INTO finance (
                stock_code,
                ticker,
                stock_name,
                fiscal_year,
                sales,
                operating_profit,
                net_profit,
                eps,
                per,
                pbr,
                roe,
                dividend,
                dividend_yield,
                market_cap,

                total_assets,
                total_liabilities,
                total_debt,
                net_debt,
                cash,
                current_assets,
                current_liabilities,
                working_capital,

                equity,
                equity_ratio,
                debt_ratio,
                debt_to_equity_ratio,
                current_ratio,

                updated_at,
                fiscal_year_key 
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?,?
            )
            """,
            (
                stock_code,
                ticker,
                stock_name,
                fiscal_year,
                sales,
                operating_profit,
                net_profit,
                eps,
                per,
                pbr,
                roe,
                dividend,
                dividend_yield,
                market_cap,

                total_assets,
                total_liabilities,
                total_debt,
                net_debt,
                cash,
                current_assets,
                current_liabilities,
                working_capital,

                equity,
                equity_ratio,
                debt_ratio,
                debt_to_equity_ratio,
                current_ratio,

                updated_at,
                fiscal_year_key 
            )
        )

        print(f"{stock_code} {fiscal_year} の登録が完了しました")

conn.commit()
conn.close()

print("financeテーブルへの年度別登録が完了しました")