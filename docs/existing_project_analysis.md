# 既存株価分析システムの構成解析

## 解析対象

既存のPython 11ファイルと `market_analysis.db` を解析した。既存Pythonは
`scripts/legacy_analysis/` に内容を変更せず複製し、AIエージェント用ラッパーから
安全に再利用する。

## 各Pythonファイルの役割

| ファイル | 役割 | DB書き込み |
|---|---|---|
| `get_stock_data.py` | yfinanceから株価を取得し、日次株価を保存 | あり |
| `fetch_finance.py` | yfinanceから銘柄・財務情報を取得して保存 | あり |
| `import_macro_data.py` | CPI、GDP、長期金利、政策金利、為替、原油を取得・整形・保存 | あり |
| `fetch_nikkei_market_pipeline.py` | 日経平均、米国市場指標、金価格を取得・保存 | あり |
| `feature_engineering.py` | ANA株価と政策金利から月次ラグ特徴量を作成 | あり |
| `correlation_regression_analysis.py` | 個別株とマクロ指標の相関、OLS回帰、VIF、標準化回帰を実施 | あり |
| `prediction_model.py` | 政策金利ラグ別に線形回帰・Random Forestを比較して株価を予測 | あり |
| `visualize_prediction_results.py` | 保存済み予測評価をグラフ表示 | なし |
| `nikkei_correlation_regression_analysis.py` | 日経平均と市場・マクロ指標の統計解析 | あり |
| `nikkei_machine_learning_model.py` | 線形回帰、Random Forest、XGBoostで日経平均をバックテスト | あり |
| `table_definition.py` | SQLite内のテーブル定義を一覧表示 | なし |

「DB書き込みあり」は既存ファイル単体の性質を示す。今回のラッパーは該当する
保存関数や `main()` を呼ばない。

## データ取得フロー

```text
yfinance / CSV
  ├─ get_stock_data.py
  ├─ fetch_finance.py
  ├─ import_macro_data.py
  └─ fetch_nikkei_market_pipeline.py
        ↓
SQLiteの既存テーブル
        ↓
v_stock_fundamental
v_macro_economic
        ↓
v_ai_stock_report_input
```

取得系スクリプトは既存パイプラインの更新処理であり、今回のAIエージェントからは
実行しない。

## 分析フロー

```text
v_ai_stock_report_input（読み取り専用）
        ↓
銘柄コードで対象行を抽出
        ↓
必要列の数値化・欠損除外
        ↓
correlation_regression_analysis.py の既存関数
  ├─ 相関分析
  ├─ OLS重回帰・p値
  ├─ VIF
  └─ 標準化回帰
        ↓
インメモリのDataFrame
```

## 予測フロー

```text
v_ai_stock_report_input（読み取り専用）
        ↓
feature_engineering.py
  └─ 政策金利ラグ（0・1・2・3・6か月）をメモリ上で作成
        ↓
prediction_model.py
  ├─ LinearRegression
  └─ RandomForestRegressor
        ↓
時系列順の学習・評価・対象月予測
        ↓
インメモリのDataFrame
```

特徴量作成・モデル・評価指標は既存ロジックをそのまま再利用する。既存のDB保存関数は
呼ばないため、分析結果テーブルの削除や挿入は発生しない。

## レポート生成フロー

```text
ユーザー
  ↓ 銘柄コード
scripts/generate_stock_report.py
  ↓
SQLite（mode=ro、query_only）
  ↓ v_ai_stock_report_input のみ
既存統計解析・予測関数
  ↓
ルールベースの分析要約
  ↓
reports/stock_report_<銘柄コード>.html
```

HTMLは文章、表、グラフを1ファイルへまとめた自己完結型とする。グラフはBase64で
HTML内部へ埋め込み、同名のMarkdownは確認・差分管理用の副成果物として生成する。

## VIEW確認結果

| VIEW | 行数（解析時点） | 用途 |
|---|---:|---|
| `v_stock_fundamental` | 7,694 | 株価・銘柄属性・財務 |
| `v_macro_economic` | 13,514 | 日経平均・市場・マクロ指標 |
| `v_ai_stock_report_input` | 7,694 | AIレポート用の統合入力 |

3 VIEWはいずれも読み取り可能だった。2026-07-06の更新後確認では、
`v_ai_stock_report_input` の財務指標は3,307行に反映されている。財務データが
未充足の銘柄については、レポートで「データなし」と表示する。

## 既存資産に対する変更方針

- 原本と複製した既存Pythonの内容は変更しない。
- AIエージェント層のSQLは許可されたVIEWだけを参照する。
- SQLiteはURIの `mode=ro` と `PRAGMA query_only=ON` を併用する。
- DB保存処理、データ取得処理、既存スクリプトの `main()` は呼ばない。
- 分析結果はDBではなくMarkdownへ出力する。
