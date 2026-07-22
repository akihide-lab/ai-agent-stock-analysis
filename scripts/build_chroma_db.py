"""Build the local ChromaDB used by the RAG retriever.

The builder reads Markdown and text files from ``rag_documents/`` by default,
creates deterministic chunks, and rebuilds ``chroma_db/`` atomically enough to
avoid leaving a half-written database after ingestion errors.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import stat
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

try:
    from .rag_retriever import DEFAULT_CHROMA_DIR, DEFAULT_COLLECTION_NAMES
except ImportError:
    from rag_retriever import DEFAULT_CHROMA_DIR, DEFAULT_COLLECTION_NAMES


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_DIR = PROJECT_ROOT / "rag_documents"
SUPPORTED_SUFFIXES = {".md", ".txt"}
DEFAULT_CHUNK_SIZE = 800
DEFAULT_CHUNK_OVERLAP = 120


@dataclass(frozen=True)
class SourceDocument:
    path: Path
    relative_path: str
    text: str
    title: str


@dataclass(frozen=True)
class DocumentChunk:
    document: str
    document_id: str
    chunk_id: str
    metadata: dict[str, str | int]


@dataclass
class BuildSummary:
    files_read: int = 0
    chunks_created: int = 0
    records_added: int = 0
    persist_path: Path | None = None
    collection_name: str = ""
    skipped_files: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def error_count(self) -> int:
        return len(self.errors)


def stop_chroma_client(client: object) -> None:
    system = getattr(client, "_system", None)
    stop = getattr(system, "stop", None)
    if callable(stop):
        stop()
    clear = getattr(client, "clear_system_cache", None)
    if callable(clear):
        clear()


def remove_tree(path: Path) -> None:
    def on_error(function: object, failed_path: str, exc_info: object) -> None:
        try:
            os.chmod(failed_path, stat.S_IWRITE)
            if callable(function):
                function(failed_path)
        except Exception:
            raise

    if path.exists():
        shutil.rmtree(path, onerror=on_error)


def resolve_project_path(path: Path, project_root: Path = PROJECT_ROOT) -> Path:
    if path.is_absolute():
        return path.resolve()
    return (project_root / path).resolve()


def ensure_valid_chroma_dir(chroma_dir: Path, project_root: Path = PROJECT_ROOT) -> Path:
    resolved = resolve_project_path(chroma_dir, project_root)
    resolved_root = project_root.resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"ChromaDB path must be inside the project root: {resolved}") from exc
    if resolved.name != DEFAULT_CHROMA_DIR.name:
        raise ValueError(f"ChromaDB directory must be named {DEFAULT_CHROMA_DIR.name}: {resolved}")
    return resolved


def iter_source_files(source_dir: Path) -> Iterable[Path]:
    for path in sorted(source_dir.rglob("*")):
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES:
            yield path


def read_text_file(path: Path) -> str:
    for encoding in ("utf-8", "utf-8-sig", "cp932"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError("utf-8", b"", 0, 1, "unsupported text encoding")


def extract_markdown_title(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()
    return ""


def load_source_documents(source_dir: Path, project_root: Path = PROJECT_ROOT) -> tuple[list[SourceDocument], list[str], list[str]]:
    resolved_source = resolve_project_path(source_dir, project_root)
    if not resolved_source.exists():
        return [], [], [f"Input directory does not exist: {resolved_source}"]
    if not resolved_source.is_dir():
        return [], [], [f"Input path is not a directory: {resolved_source}"]

    documents: list[SourceDocument] = []
    skipped: list[str] = []
    errors: list[str] = []
    for path in iter_source_files(resolved_source):
        try:
            text = read_text_file(path)
        except UnicodeDecodeError as exc:
            errors.append(f"{path}: {exc}")
            continue

        if not text.strip():
            skipped.append(str(path))
            continue

        relative_path = path.resolve().relative_to(project_root.resolve()).as_posix()
        title = extract_markdown_title(text) if path.suffix.lower() == ".md" else ""
        documents.append(
            SourceDocument(
                path=path.resolve(),
                relative_path=relative_path,
                text=text,
                title=title,
            )
        )
    return documents, skipped, errors


def split_text(text: str, chunk_size: int = DEFAULT_CHUNK_SIZE, chunk_overlap: int = DEFAULT_CHUNK_OVERLAP) -> list[str]:
    if chunk_size < 1:
        raise ValueError("chunk_size must be a positive integer")
    if chunk_overlap < 0:
        raise ValueError("chunk_overlap must be zero or greater")
    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be smaller than chunk_size")

    stripped = text.strip()
    if not stripped:
        return []

    chunks: list[str] = []
    start = 0
    while start < len(stripped):
        end = min(start + chunk_size, len(stripped))
        chunks.append(stripped[start:end])
        if end >= len(stripped):
            break
        start = end - chunk_overlap
    return chunks


def stable_document_id(relative_path: str) -> str:
    digest = hashlib.sha1(relative_path.encode("utf-8")).hexdigest()[:16]
    return f"doc-{digest}"


def stable_chunk_id(relative_path: str, chunk_index: int, chunk_text: str) -> str:
    digest = hashlib.sha1(
        f"{relative_path}\n{chunk_index}\n{chunk_text}".encode("utf-8")
    ).hexdigest()[:20]
    return f"{relative_path}::chunk-{chunk_index:04d}::{digest}"


def build_chunks(
    documents: Iterable[SourceDocument],
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[DocumentChunk]:
    chunks: list[DocumentChunk] = []
    for source in documents:
        document_id = stable_document_id(source.relative_path)
        for index, text_chunk in enumerate(split_text(source.text, chunk_size, chunk_overlap)):
            chunk_id = stable_chunk_id(source.relative_path, index, text_chunk)
            metadata: dict[str, str | int] = {
                "source_path": source.relative_path,
                "file_path": source.relative_path,
                "file_name": source.path.name,
                "file_type": source.path.suffix.lower().lstrip("."),
                "chunk_index": index,
                "document_id": document_id,
                "source_type": "local_document",
            }
            if source.title:
                metadata["title"] = source.title
            chunks.append(
                DocumentChunk(
                    document=text_chunk,
                    document_id=document_id,
                    chunk_id=chunk_id,
                    metadata=metadata,
                )
            )
    return chunks


def rebuild_chroma_db(
    source_dir: Path = DEFAULT_SOURCE_DIR,
    chroma_dir: Path = DEFAULT_CHROMA_DIR,
    collection_name: str = DEFAULT_COLLECTION_NAMES[0],
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    project_root: Path = PROJECT_ROOT,
) -> BuildSummary:
    chroma_path = ensure_valid_chroma_dir(chroma_dir, project_root)
    documents, skipped, load_errors = load_source_documents(source_dir, project_root)
    summary = BuildSummary(
        files_read=len(documents),
        persist_path=chroma_path,
        collection_name=collection_name,
        skipped_files=skipped,
        errors=load_errors,
    )
    if load_errors:
        return summary
    if not documents:
        summary.errors.append("No Markdown or TXT source documents were found.")
        return summary

    chunks = build_chunks(documents, chunk_size, chunk_overlap)
    summary.chunks_created = len(chunks)
    if not chunks:
        summary.errors.append("No non-empty chunks were created.")
        return summary

    tmp_path = chroma_path.with_name(f".{chroma_path.name}_build_tmp")
    if tmp_path.exists():
        remove_tree(tmp_path)

    try:
        import chromadb  # type: ignore

        client = chromadb.PersistentClient(path=str(tmp_path))
        try:
            try:
                client.delete_collection(name=collection_name)
            except Exception:
                pass
            collection = client.create_collection(name=collection_name)
            collection.add(
                ids=[chunk.chunk_id for chunk in chunks],
                documents=[chunk.document for chunk in chunks],
                metadatas=[chunk.metadata for chunk in chunks],
            )
            summary.records_added = len(chunks)
        finally:
            stop_chroma_client(client)
    except Exception as exc:
        summary.errors.append(f"ChromaDB build failed: {exc}")
        if tmp_path.exists():
            shutil.rmtree(tmp_path, ignore_errors=True)
        return summary

    try:
        if chroma_path.exists():
            remove_tree(chroma_path)
        tmp_path.rename(chroma_path)
    except Exception as exc:
        summary.errors.append(f"ChromaDB replace failed: {exc}")
        if tmp_path.exists():
            shutil.rmtree(tmp_path, ignore_errors=True)
    return summary


def print_summary(summary: BuildSummary) -> None:
    print(f"読み込んだファイル数: {summary.files_read}")
    print(f"作成したチャンク数: {summary.chunks_created}")
    print(f"登録件数: {summary.records_added}")
    print(f"保存先: {summary.persist_path}")
    print(f"コレクション名: {summary.collection_name}")
    print(f"スキップしたファイル: {len(summary.skipped_files)}")
    for path in summary.skipped_files:
        print(f"  - {path}")
    print(f"エラー件数: {summary.error_count}")
    for error in summary.errors:
        print(f"  - {error}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rebuild the local ChromaDB for RAG search.")
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--chroma-dir", type=Path, default=DEFAULT_CHROMA_DIR)
    parser.add_argument("--collection-name", default=DEFAULT_COLLECTION_NAMES[0])
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE)
    parser.add_argument("--chunk-overlap", type=int, default=DEFAULT_CHUNK_OVERLAP)
    return parser.parse_args()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = parse_args()
    try:
        summary = rebuild_chroma_db(
            source_dir=args.source_dir,
            chroma_dir=args.chroma_dir,
            collection_name=args.collection_name,
            chunk_size=args.chunk_size,
            chunk_overlap=args.chunk_overlap,
        )
    except ValueError as exc:
        summary = BuildSummary(
            persist_path=resolve_project_path(args.chroma_dir),
            collection_name=args.collection_name,
            errors=[str(exc)],
        )
    print_summary(summary)
    return 1 if summary.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
