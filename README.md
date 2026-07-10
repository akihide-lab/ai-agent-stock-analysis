# 株の銘柄分析

SQLiteの承認済みVIEWと既存Python分析ロジックを利用し、銘柄分析レポートを
Markdownで生成するローカルCLIプロジェクトです。

## AIエージェント実行

初心者の自然言語質問から、Intent / Entity / 不足情報を判定し、銘柄選定から
HTMLレポート生成まで実行します。

```powershell
.\.venv\Scripts\python.exe .\scripts\question_agent.py "初心者向けにおすすめの株を選んで"
```

動作確認でWeb更新を省略し、既存DBだけでレポートを作る場合:

```powershell
.\.venv\Scripts\python.exe .\scripts\question_agent.py "初心者向けにおすすめの株を選んで" --skip-web-update
```

質問文に銘柄コードや銘柄名が含まれる場合は、その銘柄を分析します。

```powershell
.\.venv\Scripts\python.exe .\scripts\question_agent.py "9202って買い？" --skip-web-update
```

銘柄が指定されていない場合は、質問内容から条件を推定して候補銘柄を選定し、
最上位候補のレポートを生成します。質問解釈と選定理由は
`logs/question_flow_<日時>.json` に保存されます。

バックグラウンド化や将来の常駐ワーカー化に向けて、ジョブJSONを作成してから
別プロセスで実行することもできます。

```powershell
.\.venv\Scripts\python.exe .\scripts\agent_jobs.py create "初心者向けにおすすめの株を選んで" --skip-web-update
.\.venv\Scripts\python.exe .\scripts\agent_jobs.py run <job_id>
.\.venv\Scripts\python.exe .\scripts\agent_jobs.py status <job_id>
```

ジョブ状態は `logs/job_<job_id>.json` に保存されます。複数ワーカーを用意すれば、
候補検索、確認待ち、分析実行を並列化しやすくなります。

## AIエージェントのVIEW参照順

AIエージェントは、最初の検索・確認では軽量なエージェント用VIEWを参照します。
既存の詳細分析用VIEWを最初から全件検索しません。

1. 候補検索: `v_agent_stock_candidates`
2. データ鮮度確認: `v_agent_data_freshness`
3. 銘柄名検索: `v_agent_stock_master`

詳細な時系列分析、相関・回帰、レポート生成が必要になった場合のみ、
`v_ai_stock_report_input` などの詳細分析用VIEWを参照します。

## レポート生成

依存ライブラリを導入:

```powershell
uv pip install --python .\.venv\Scripts\python.exe -r requirements.txt
```

既定のANAホールディングス（9202）を分析:

```powershell
.\.venv\Scripts\python.exe .\scripts\generate_stock_report.py
```

別の銘柄を指定:

```powershell
.\.venv\Scripts\python.exe .\scripts\generate_stock_report.py --stock-code 6857
```

主出力は自己完結型の `reports/stock_report_<銘柄コード>.html` です。
グラフはHTML内部へ埋め込まれるため、HTMLファイル単体で閲覧できます。
確認・差分管理用として同名のMarkdownも同時に生成します。

ラッパーは `v_ai_stock_report_input` のみを読み取り、DBを読み取り専用モードで
開きます。既存PythonのDB書き込み処理は呼び出しません。

生成レポートには次を含みます。

- 相関・回帰・財務情報の自然文による考察
- 上昇要因、リスク要因、根拠付き総合判断
- 1年前・3年前との株価比較
- 財務年度推移と前年度比較
- 同一セクターの競合比較
- 株価推移・競合パフォーマンスのグラフ

自然言語で銘柄候補を探索:

```powershell
.\.venv\Scripts\python.exe .\scripts\search_stocks.py "航空でROEが高くPERが低い銘柄"
```

対応する代表的な条件は、業界名、ROE、割安・低PER、高配当、上昇・好調、
安定・安全・初心者向け、円安に強い、原油高に弱い、です。探索結果は候補抽出であり投資推奨ではありません。

## データ更新

通常の銘柄分析は、次の統合コマンドを使用します。

```powershell
.\.venv\Scripts\python.exe .\scripts\analyze_stock.py 9202
```

このコマンドは次を順番に実行します。

1. Yahoo Financeから対象銘柄・市場・財務データを取得
2. 総務省・日本銀行・財務省の公式Webからマクロデータを取得
3. WebとSQLiteの最新日を比較
4. Webが新しい対象だけをステージングDBで更新
5. VIEW経由で分析
6. Web比較結果とデータ鮮度を含む自己完結HTMLを生成

Web取得に失敗した場合、該当するDBデータは上書きせず、既存値でレポートを
生成して失敗内容をHTMLへ記載します。

Yahoo Financeから株価・財務・市場指標を取得し、作業用DBの検証後に反映:

```powershell
.\.venv\Scripts\python.exe .\scripts\update_market_data.py
```

既存CSVと既存の `import_macro_data.py` でマクロデータを更新:

```powershell
.\.venv\Scripts\python.exe .\scripts\update_macro_from_existing.py
```

どちらも更新前DBを `data/backups/` へ保存します。Yahoo Finance取得に失敗した
銘柄・データ種別は既存値を維持し、更新ログを `logs/` へ出力します。

公式Web更新のみを個別実行:

```powershell
.\.venv\Scripts\python.exe .\scripts\update_official_macro_web.py
```

現在の公式取得元は、総務省統計局（CPI）、日本銀行（政策金利系列）、
財務省（日本10年国債金利）です。GDPは既存の内閣府最新年次CSVを使用します。
CPI最新月の総合指数は公式概要から取得します。前月比を同一系列で直接確認できない
場合、誤計算を避けるため `cpi_mom` はNULLとして扱います。

構成とパイプラインの解析結果は
[`docs/existing_project_analysis.md`](docs/existing_project_analysis.md) を参照してください。

## 現在の開発環境

- 確認日: 2026-07-06
- OS: Windows
- Git: 2.55.0.windows.2
- Python: 3.12.13（Codex同梱版）
- 仮想環境: `.venv`
- uv: 0.11.26
- Python追加ライブラリ: `requirements.txt` に記載し、`.venv` へ導入済み

GitとuvはPATHへ登録済みです。Python仮想環境の作成にはCodex同梱の
Python 3.12.13を使用しました。

## 仮想環境

PowerShellでの有効化:

```powershell
.\.venv\Scripts\Activate.ps1
```

有効化せずにPythonを実行する場合:

```powershell
.\.venv\Scripts\python.exe --version
```

## フォルダ構成

```text
docs/      ドキュメント
sql/       SQLファイル
scripts/   実行・補助スクリプト
reports/   生成レポート
logs/      ログ
data/      データ
```

既存Pythonは内容を変更せず `scripts/legacy_analysis/` へ複製しています。
AIエージェントはDBへ直接書き込まず、許可されたVIEWを読み取り専用で参照します。

## DB変更方針

SQLやVIEWの検索・参照は直接行ってよいですが、テーブル作成、VIEW作成、ALTER、
DROPなどのDDLはPythonファイルを通してのみ実行します。DDLを変更する場合は、
内容を追跡できる専用スクリプトを `scripts/` 配下に作成または更新し、その
Pythonファイルを実行してDBへ反映します。

SQLやDDLを実行するPythonファイルの作成は原則ユーザー側で行います。Codexは、
必要なVIEW、列、インデックス、DDL方針の提案・レビューを行い、ユーザーから
明示依頼があった場合のみSQL実行用ファイルを作成します。
