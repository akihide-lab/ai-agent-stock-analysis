# CloudWatch Logs 連携

このプロジェクトでは、`scripts/analyze_stock.py` の実行時に Python logging を初期化し、アプリケーションログを `logs/agent.log` へ出力します。

## 全体構成

```text
AIエージェント
↓
Python logging
↓
logs/agent.log
↓
CloudWatch Agent
↓
CloudWatch Logs
```

## ローカルログ

- 出力先: `logs/agent.log`
- ログレベル: `INFO`
- 出力先: ファイルと標準出力
- 文字コード: UTF-8
- 形式: 日時、ログレベル、ロガー名、メッセージ

## CloudWatch Logs 設定例

- ロググループ名: `ai-agent-stock-analysis`
- ログストリーム名: EC2 インスタンスID
- CloudWatch Agent 設定例: `config/cloudwatch-agent-example.json`

設定例の `file_path` はサンプルです。実際のEC2上の配置パスに合わせて変更してください。

## 確認用途

- 処理開始
- 処理終了
- DB接続
- 分析開始
- レポート生成
- S3アップロード
- エラー確認

## 注意事項

設定ファイルやドキュメントには、実環境固有の秘密情報を書かないでください。

- AWSアカウントID
- 実際のIAMロールARN
- RDS接続情報
- パスワード
- `.env` の実値
- 実際のアクセストークン
