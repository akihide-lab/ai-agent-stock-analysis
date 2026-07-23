"""Optional S3 upload helper for generated HTML reports."""

from __future__ import annotations

import os
from pathlib import Path


ENABLED_VALUES = {"true", "1", "yes", "on"}
DEFAULT_REPORT_PREFIX = "reports"


def is_s3_upload_enabled(value: str | None = None) -> bool:
    """Return whether S3 uploads are enabled by environment-style text."""
    raw_value = os.getenv("ENABLE_S3_UPLOAD") if value is None else value
    return str(raw_value or "").strip().lower() in ENABLED_VALUES


def _warning(message: str, report_path: Path | None = None, reason: object | None = None) -> None:
    print(f"[WARNING] {message}")
    if report_path is not None:
        print(f"対象: {report_path}")
    if reason is not None:
        print(f"理由: {reason}")


def _s3_key_for_report(report_path: Path, prefix: str) -> str:
    normalized_prefix = prefix.strip().strip("/")
    filename = report_path.name
    if not normalized_prefix:
        return filename
    return f"{normalized_prefix}/{filename}"


def upload_report_to_s3(report_path: str) -> str | None:
    """
    設定が有効な場合のみ、レポートをS3へアップロードする。

    Returns:
        S3 URI。アップロード無効時または失敗時はNone。
    """
    path = Path(report_path)
    if not is_s3_upload_enabled():
        return None

    bucket_name = os.getenv("S3_BUCKET_NAME", "").strip()
    if not bucket_name:
        _warning("S3バケット名が設定されていないためアップロードをスキップしました", path)
        return None

    if not path.is_file():
        _warning("S3アップロード対象ファイルが存在しません", path)
        return None

    prefix = os.getenv("S3_REPORT_PREFIX", DEFAULT_REPORT_PREFIX)
    s3_key = _s3_key_for_report(path, prefix)

    try:
        import boto3

        boto3.client("s3").upload_file(str(path), bucket_name, s3_key)
    except Exception as exc:
        _warning("S3アップロードに失敗しました", path, exc)
        return None

    s3_uri = f"s3://{bucket_name}/{s3_key}"
    print(f"S3アップロード完了: {s3_uri}")
    return s3_uri
