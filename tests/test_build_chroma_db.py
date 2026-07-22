from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import build_chroma_db as builder
from query_flow_models import DataSourcePlan, QueryFlowInput
from rag_retriever import search_rag_context


class BuildChromaDbUnitTests(unittest.TestCase):
    def test_loads_markdown_and_txt_documents(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            docs = root / "rag_documents"
            docs.mkdir()
            (docs / "sample.md").write_text("# Title\nMarkdown body", encoding="utf-8")
            (docs / "note.txt").write_text("Text body", encoding="utf-8")

            loaded, skipped, errors = builder.load_source_documents(docs, root)

        self.assertEqual(len(loaded), 2)
        self.assertEqual(skipped, [])
        self.assertEqual(errors, [])
        self.assertEqual(loaded[0].relative_path, "rag_documents/note.txt")
        self.assertEqual(loaded[1].title, "Title")

    def test_skips_empty_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            docs = root / "rag_documents"
            docs.mkdir()
            empty = docs / "empty.md"
            empty.write_text("  \n", encoding="utf-8")

            loaded, skipped, errors = builder.load_source_documents(docs, root)

        self.assertEqual(loaded, [])
        self.assertEqual(len(skipped), 1)
        self.assertEqual(errors, [])

    def test_split_text_creates_overlapping_chunks_without_loss(self) -> None:
        text = "abcdefghijklmnopqrstuvwxyz"

        chunks = builder.split_text(text, chunk_size=10, chunk_overlap=3)

        self.assertEqual(chunks, ["abcdefghij", "hijklmnopq", "opqrstuvwx", "vwxyz"])
        reconstructed = chunks[0] + "".join(chunk[3:] for chunk in chunks[1:])
        self.assertEqual(reconstructed, text)

    def test_stable_chunk_id_is_deterministic(self) -> None:
        first = builder.stable_chunk_id("rag_documents/a.md", 0, "same text")
        second = builder.stable_chunk_id("rag_documents/a.md", 0, "same text")

        self.assertEqual(first, second)

    def test_metadata_is_created_for_chunks(self) -> None:
        source = builder.SourceDocument(
            path=Path("rag_documents/sample.md"),
            relative_path="rag_documents/sample.md",
            text="# Sample\nAIエージェントの説明",
            title="Sample",
        )

        chunks = builder.build_chunks([source], chunk_size=100, chunk_overlap=10)

        self.assertEqual(len(chunks), 1)
        metadata = chunks[0].metadata
        self.assertEqual(metadata["source_path"], "rag_documents/sample.md")
        self.assertEqual(metadata["file_name"], "sample.md")
        self.assertEqual(metadata["file_type"], "md")
        self.assertEqual(metadata["chunk_index"], 0)
        self.assertEqual(metadata["document_id"], chunks[0].document_id)
        self.assertEqual(metadata["title"], "Sample")

    def test_no_documents_stops_without_creating_database(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            docs = root / "rag_documents"
            docs.mkdir()
            chroma_dir = root / "chroma_db"

            summary = builder.rebuild_chroma_db(
                source_dir=docs,
                chroma_dir=chroma_dir,
                project_root=root,
            )

        self.assertEqual(summary.files_read, 0)
        self.assertEqual(summary.records_added, 0)
        self.assertTrue(summary.errors)
        self.assertFalse(chroma_dir.exists())

    def test_rejects_chroma_path_outside_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "project"
            root.mkdir()
            outside = Path(temp_dir) / "chroma_db"

            with self.assertRaises(ValueError):
                builder.ensure_valid_chroma_dir(outside, root)


class BuildChromaDbIntegrationTests(unittest.TestCase):
    def test_builds_searchable_chroma_db_and_rebuild_does_not_duplicate(self) -> None:
        try:
            import chromadb  # noqa: F401
        except ImportError:
            self.skipTest("chromadb is not installed")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            docs = root / "rag_documents"
            docs.mkdir()
            (docs / "agent.md").write_text(
                "# AIエージェント\nAIエージェントとは、目的に応じて情報を検索し、"
                "ツールを使って作業を進める仕組みです。",
                encoding="utf-8",
            )
            chroma_dir = root / "chroma_db"

            first = builder.rebuild_chroma_db(
                source_dir=docs,
                chroma_dir=chroma_dir,
                project_root=root,
            )
            second = builder.rebuild_chroma_db(
                source_dir=docs,
                chroma_dir=chroma_dir,
                project_root=root,
            )

            query = QueryFlowInput(
                user_question="AIエージェントとは何ですか？",
                primary_intent="Intent008",
            )
            plan = DataSourcePlan(
                intent_id="Intent008",
                action_name="single_stock_analysis",
                rdb_targets=[],
                rag_targets=["news"],
                next_flow="single_stock_report",
            )
            results, warnings = search_rag_context(query, plan, chroma_dir=chroma_dir)

        self.assertFalse(first.errors)
        self.assertFalse(second.errors)
        self.assertEqual(first.records_added, second.records_added)
        self.assertGreaterEqual(len(results), 1, warnings)
        self.assertIn("AIエージェント", results[0].document)


if __name__ == "__main__":
    unittest.main()
