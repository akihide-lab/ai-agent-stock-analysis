# ChromaDB / RAG 再構築手順

このドキュメントは、READMEから分離したChromaDB / RAGの詳細手順です。READMEでは全体像と代表コマンドだけを扱い、ここでは元文書配置、再構築、確認、Git管理対象をまとめます。

## 1. 役割

`chroma_db/` はRAG検索で使うローカルChromaDBです。`scripts/rag_retriever.py` がこのDBを読み込み、ユーザー質問に関連する補足文書を検索します。

`chroma_db/` は生成物のためGit管理しません。GitHubにはDB本体ではなく、元文書、再構築スクリプト、テスト、手順を登録します。

## 2. 元文書の配置場所

Markdownまたはテキストファイルを `rag_documents/` 配下に配置します。サブディレクトリも再帰的に読み込まれます。

対象拡張子:

- `.md`
- `.txt`

サンプル文書は `rag_documents/sample/` に配置できます。

## 3. Windowsでの再構築

```powershell
.\.venv\Scripts\python.exe .\scripts\build_chroma_db.py
```

既定の入力と出力:

- 入力: `rag_documents/`
- 保存先: `chroma_db/`
- コレクション名: `news_chunks`

## 4. macOS / Linux / AWS EC2での再構築

```bash
./.venv/bin/python scripts/build_chroma_db.py
```

## 5. チャンクサイズ変更

チャンクサイズと重なり幅を変更する場合は、次のように指定します。

```powershell
.\.venv\Scripts\python.exe .\scripts\build_chroma_db.py --chunk-size 800 --chunk-overlap 120
```

再構築時は一時的に新しいDBを作成し、成功後に `chroma_db/` を置き換えます。既存データへ無制限に追記しません。

## 6. 単体検索確認

ChromaDB作成後、`scripts.rag_retriever.search_rag_context()` を直接呼び出して検索結果を確認できます。

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe -c "from scripts.rag_retriever import search_rag_context; from scripts.query_flow_models import DataSourcePlan, QueryFlowInput; q=QueryFlowInput(user_question='AIエージェントとは何ですか？', primary_intent='Intent008'); p=DataSourcePlan(intent_id='Intent008', action_name='rag_check', rdb_targets=[], rag_targets=['news'], next_flow='rag_check'); results,warnings=search_rag_context(q,p); print('results:', len(results)); print('warnings:', warnings); print('document:', results[0].document if results else '')"
```

macOS / Linux / AWS EC2:

```bash
./.venv/bin/python -c 'from scripts.rag_retriever import search_rag_context; from scripts.query_flow_models import DataSourcePlan, QueryFlowInput; q=QueryFlowInput(user_question="AIエージェントとは何ですか？", primary_intent="Intent008"); p=DataSourcePlan(intent_id="Intent008", action_name="rag_check", rdb_targets=[], rag_targets=["news"], next_flow="rag_check"); results,warnings=search_rag_context(q,p); print("results:", len(results)); print("warnings:", warnings); print("document:", results[0].document if results else "")'
```

## 7. 分析フローからの確認

RAG検索単体ではなく、分析Contextへ統合される流れを確認する場合は、`analysis_connector.py` をcontext-onlyで実行します。

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe .\scripts\analysis_connector.py "トヨタを分析して" --intent-id Intent008 --context-only --no-update
```

## 8. RAG関連テスト

DBなしでRAG部分を継続的に確認したい場合は、次のテストを実行します。

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_build_chroma_db
```

## 9. AWS EC2での再現手順

```bash
git clone <repository-url>
cd <repository-directory>
python3 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -r requirements.txt

# 必要なMarkdown/TXTをrag_documents/配下へ配置
./.venv/bin/python scripts/build_chroma_db.py

# RAG検索確認
./.venv/bin/python -c 'from scripts.rag_retriever import search_rag_context; from scripts.query_flow_models import DataSourcePlan, QueryFlowInput; q=QueryFlowInput(user_question="AIエージェントとは何ですか？", primary_intent="Intent008"); p=DataSourcePlan(intent_id="Intent008", action_name="rag_check", rdb_targets=[], rag_targets=["news"], next_flow="rag_check"); results,warnings=search_rag_context(q,p); print("results:", len(results)); print("warnings:", warnings); print("document:", results[0].document if results else "")'

# AIエージェント実行例
./.venv/bin/python scripts/question_agent.py "トヨタを分析して" --skip-web-update
```

## 10. Git管理

GitHubへ登録するもの:

- `scripts/build_chroma_db.py`
- `tests/test_build_chroma_db.py`
- `rag_documents/` 配下の元文書
- READMEとこの再構築手順

GitHubへ登録しないもの:

- `chroma_db/`
- `chroma.sqlite3`
- ChromaDB内部のUUIDディレクトリ
- `.env`
- ローカル絶対パス
