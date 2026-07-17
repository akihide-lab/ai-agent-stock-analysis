# PostgreSQL接続診断と実行制限時の扱い

## 目的

PostgreSQL接続エラーが発生したときに、接続設定の不備、RDS側の問題、実行環境のネットワーク制限を切り分けやすくする。

## 診断ログ

`scripts/db_connection.py` は PostgreSQL 接続失敗時に、秘密情報を含まない診断ログを `logs/postgres_connection_diagnostic_*.json` に出力する。

ログに残す内容:

- `timestamp`
- `db_type`
- `stage`
- `read_only`
- `exception_type`
- `category`
- 安全化した `message`

ログに残さない内容:

- パスワード
- DSN全体
- RDSエンドポイント全文
- ユーザー名
- `.env` の内容
- 環境変数一覧

## エラー分類

PostgreSQL接続失敗は、可能な範囲で次のカテゴリに分類する。

- `network_permission_denied`
- `connection_timeout`
- `authentication_failed`
- `database_not_found`
- `host_resolution_failed`
- `ssl_error`
- `unknown_connection_error`

`Permission denied (10013)` は `network_permission_denied` として扱う。Codexの通常サンドボックス内でこのエラーが発生した場合、まず実行環境のネットワーク制限を疑う。

## 実接続テストの運用

SQLiteテストは通常サンドボックス内で実行できる。

PostgreSQLのRDS実接続テストは、通常PowerShellまたはネットワーク承認付き実行で確認する。

確認コマンド:

```powershell
uv run python -c "from scripts.db_connection import smoke_test_connection; print(smoke_test_connection())"
```

期待結果:

```python
{'db_type': 'postgres', 'ok': True, 'database': 'market_analysis_test'}
```

通常サンドボックス内でRDS接続が失敗しても、それだけでアプリケーション不具合とは判定しない。`network_permission_denied`、`connection_timeout`、`host_resolution_failed` の分類と、通常PowerShellまたは承認付き実行での再確認結果をあわせて判断する。
