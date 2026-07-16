# 株の銘柄分析 AI エージェント

## デモ成果物

初見の方は、まず以下の2ファイルを見ると、このプロジェクトが生成する分析レポートと実行時の動きを確認できます。

- HTMLレポート: `reports/stock_report_7203.html`
  - トヨタ自動車（7203）の銘柄分析レポートです。
  - ブラウザで直接開くと、分析結果、財務推移、統計分析、グラフを1ファイルで確認できます。
- 録画動画: `reports/toyota_7203_analysis_20260713.mp4`
  - 自然言語の依頼からトヨタの分析レポートを生成・確認する流れを録画した動画です。

Windows PowerShell では、clone 後に次のコマンドで開けます。

```powershell
Start-Process ".\reports\stock_report_7203.html"
Start-Process ".\reports\toyota_7203_analysis_20260713.mp4"
```

## 1. プロジェクト概要

このリポジトリは、AI エージェントによる株式分析システムの設計・オーケストレーション・分析フローを公開するポートフォリオです。

自然言語の依頼を受け取り、株式関連の依頼かどうかを判定し、Intent / Entity / Missing Information を整理したうえで、適切な Workflow にルーティングします。情報が不足している場合は分析へ進まず、追加質問で停止する設計にしています。

実運用では SQLite の株価・財務・マクロ経済データベースと承認済み VIEW を使い、日本株の銘柄検索、単一銘柄分析、HTML レポート生成を行います。

この公開版では、主に以下の構造を確認できます。

- AI オーケストレーション構造
- Domain / Intent / Entity 処理
- 情報不足時の停止制御
- Workflow / Dispatcher 構造
- State 管理
- 自動テスト

## 2. システム構成図

```mermaid
flowchart TD
    A["User Question"] --> B["Domain Router"]
    B -->|stock| C["Pre-DB Classification"]
    B -->|not stock / unknown| X["Follow-up or General Stop"]
    C -->|insufficient / ambiguous| Y["Follow-up Required"]
    C -->|classified| D["Stock Name Resolver"]
    D --> E["Intent / Entity / Missing Info"]
    E -->|missing required info| Y
    E -->|ready| F["Workflow Selector"]
    F --> G["Dispatcher"]
    G -->|single stock analysis| H["Report Generation Flow"]
    G -->|screening| I["Candidate Selection Flow"]
    H --> J["HTML Report Path"]
    I --> H
    J --> K["Decision Log"]
```

主要な責務:

- `stock_domain_router.py`: 株式関連依頼かどうかの入口判定
- `question_agent.py`: CLI 入口、分類、銘柄解決、ログ出力
- `orchestrator.py`: 状態遷移と Workflow 選択
- `workflows.py`: Workflow 定義
- `dispatcher.py`: 選択された Workflow の実行
- `generate_stock_report.py`: 既存 DB VIEW から HTML レポートを生成
- `update_market_data.py`: 既存 DB の市場データ更新
- `update_macro_from_existing.py`: CSV 由来のマクロデータ更新

## 3. 主な機能

- 自然言語の株式関連依頼を Domain / Intent / Entity に整理
- 銘柄名・銘柄コードの解決
- 情報不足時の停止ゲート
- 単一銘柄分析 Workflow
- 条件検索から候補銘柄を選び、分析へ進める Workflow
- SQLite VIEW を読み取り専用で参照するレポート生成
- 相関、回帰、VIF、標準化回帰、簡易予測モデル比較を含む分析
- HTML レポートと実行ログの生成
- `unittest` によるオーケストレーション層のテスト

投資助言を目的としたものではなく、AI エージェント設計・分析パイプライン実装のデモです。

## 4. ディレクトリ構成

```text
scripts/   CLI、オーケストレーション、分析、更新処理
tests/     unittest ベースの自動テスト
docs/      設計メモ、既存プロジェクト分析メモ
data/      ローカル DB・CSV 入力置き場
logs/      実行ログ
reports/   HTML / Markdown レポート
sql/       SQL 関連ファイル置き場
```

GitHub には、個人環境の DB、ログ、仮想環境は含めません。生成レポートは原則除外しますが、デモ確認用として `reports/stock_report_7203.html` と `reports/toyota_7203_analysis_20260713.mp4` だけを含めています。

## 5. セットアップ方法

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

### macOS / Linux

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -r requirements.txt
./.venv/bin/python -m unittest discover -s tests
```

## 6. 実行方法

### 自動テスト

clone 直後でも、自動テストは実行できます。

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

### 単一銘柄分析

実運用 DB を `data/market_analysis.db` に配置済みの場合のみ、以下のように実行できます。

```powershell
.\.venv\Scripts\python.exe .\scripts\question_agent.py "トヨタを分析して" --skip-web-update
```

HTML レポートは `reports/stock_report_<銘柄コード>.html` に生成されます。

### 市場データ更新

既存 DB がある場合のみ実行できます。

```powershell
.\.venv\Scripts\python.exe .\scripts\update_market_data.py --stock-code 7203
```

### マクロデータ CSV 更新

`scripts/update_macro_from_existing.py` は、既存 CSV を一時作業ディレクトリへコピーしてから既存 importer を実行します。

CSV 入力元の優先順位:

1. `--source-data` CLI 引数
2. 環境変数 `STOCK_MACRO_SOURCE_DATA`
3. リポジトリ相対の `data/import`

```powershell
.\.venv\Scripts\python.exe .\scripts\update_macro_from_existing.py --source-data .\data\import
```

## 7. 現在の制約

本リポジトリには、実運用で使用している株価・財務・マクロ経済データベースは含まれていません。

そのため、clone 直後に実際の株式分析レポートを生成することはできません。

ただし、デモ確認用のHTMLレポートと録画動画は `reports/` に含めているため、ローカルDBなしでも生成結果の見た目と操作の流れは確認できます。

現時点では以下を確認できます。

- AI オーケストレーション構造
- Domain・Intent・Entity 処理
- 情報不足時の停止制御
- Workflow / Dispatcher 構造
- State 管理
- 自動テスト
- デモ用HTMLレポート
- 分析実行の録画動画

現在は AI エージェント基盤の設計・実装を公開しています。

データベース初期構築機能、サンプルデータベース、DBなしで完結するスモークテストについては、今後のバージョンで追加予定です。

実レポート生成に必要な主な VIEW は以下です。

- `v_agent_stock_master`
- `v_agent_data_freshness`
- `v_agent_stock_candidates`
- `v_ai_stock_report_input`
- `v_stock_fundamental`
- `v_macro_economic`

## SQLite / PostgreSQL 対応

本プロジェクトは、ローカル SQLite と AWS RDS PostgreSQL の両方に対応しています。接続先は `.env` または環境変数の `DB_TYPE` で切り替えます。

```text
DB_TYPE=sqlite
→ SQLite

DB_TYPE=postgres
→ PostgreSQL
```

```text
.env / 環境変数
        ↓
     DB_TYPE
   ┌────┴────┐
 SQLite   PostgreSQL
   └────┬────┘
        ↓
 db_connection.py
        ↓
 rdb_retriever.py
        ↓
 analysis_connector.py
        ↓
 AIエージェント
```

PostgreSQL 対応では、SQLite から AWS RDS PostgreSQL へ主要データを移行し、PostgreSQL 向け分析 VIEW を作成しています。検証 DB と本番 DB で読み取り確認を行い、9202 の分析、HTML 生成、ANA の名前解決、9999 の安全停止を確認済みです。

移行・再構築資材は [database/postgres/README.md](database/postgres/README.md) を参照してください。

安全性に関する方針:

- 接続情報は Git 管理しません。
- AI エージェントの分析経路は SELECT 中心です。
- PostgreSQL 利用時は SQLite 用更新スクリプトを自動実行しません。
- 本番 DB へ移行・再構築する前に、RDS スナップショットまたは `pg_dump` によるバックアップを推奨します。

既知の注意点:

- PostgreSQL では `pandas.read_sql_query()` の SQLAlchemy 推奨警告が出る場合があります。現状は処理成功を確認済みです。
- 財務年度は DB により期末日、または年度キーで表示される場合があります。例: `2025-03-31` と `2024` は同じ 2025 年 3 月期を指す表現差です。

## 8. 今後の予定

- 空の SQLite DB から初期スキーマを作成するスクリプトの追加
- 最小サンプルデータベースの追加
- DBなしで完結するスモークテストの追加
- README の実行例とサンプル出力の拡充
- CI によるテスト自動実行
- デモ用HTMLレポート・録画動画の継続的な更新

## 9. ライセンス

このプロジェクトは MIT License で公開しています。

詳細は `LICENSE` を参照してください。
