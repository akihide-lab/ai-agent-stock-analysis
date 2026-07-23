from __future__ import annotations

import sys
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import s3_uploader


class S3UploaderTests(unittest.TestCase):
    def test_disabled_false_skips_boto3(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report = Path(temp_dir) / "stock_report_7203.html"
            report.write_text("<html></html>", encoding="utf-8")
            with patch.dict(
                "os.environ",
                {"ENABLE_S3_UPLOAD": "false", "S3_BUCKET_NAME": "bucket"},
                clear=True,
            ):
                with patch.dict("sys.modules", {"boto3": None}):
                    result = s3_uploader.upload_report_to_s3(str(report))

        self.assertIsNone(result)

    def test_unset_enable_skips_boto3(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report = Path(temp_dir) / "stock_report_7203.html"
            report.write_text("<html></html>", encoding="utf-8")
            with patch.dict("os.environ", {"S3_BUCKET_NAME": "bucket"}, clear=True):
                with patch.dict("sys.modules", {"boto3": None}):
                    result = s3_uploader.upload_report_to_s3(str(report))

        self.assertIsNone(result)

    def test_enabled_true_uploads_file_and_returns_uri(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report = Path(temp_dir) / "stock_report_7203_ec2.html"
            report.write_text("<html></html>", encoding="utf-8")
            upload_file = Mock()
            boto3_module = types.SimpleNamespace(
                client=Mock(return_value=types.SimpleNamespace(upload_file=upload_file))
            )
            with patch.dict(
                "os.environ",
                {
                    "ENABLE_S3_UPLOAD": "true",
                    "S3_BUCKET_NAME": "stock-analysis-akihide-2026",
                    "S3_REPORT_PREFIX": "reports",
                },
                clear=True,
            ):
                with patch.dict("sys.modules", {"boto3": boto3_module}):
                    result = s3_uploader.upload_report_to_s3(str(report))

        self.assertEqual(
            result,
            "s3://stock-analysis-akihide-2026/reports/stock_report_7203_ec2.html",
        )
        boto3_module.client.assert_called_once_with("s3")
        upload_file.assert_called_once_with(
            str(report),
            "stock-analysis-akihide-2026",
            "reports/stock_report_7203_ec2.html",
        )

    def test_missing_bucket_warns_and_skips_upload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report = Path(temp_dir) / "stock_report_7203.html"
            report.write_text("<html></html>", encoding="utf-8")
            stream = StringIO()
            with patch.dict("os.environ", {"ENABLE_S3_UPLOAD": "true"}, clear=True):
                with redirect_stdout(stream):
                    result = s3_uploader.upload_report_to_s3(str(report))

        self.assertIsNone(result)
        self.assertIn("[WARNING]", stream.getvalue())
        self.assertIn("S3バケット名", stream.getvalue())

    def test_missing_file_warns_and_skips_upload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report = Path(temp_dir) / "missing.html"
            stream = StringIO()
            with patch.dict(
                "os.environ",
                {"ENABLE_S3_UPLOAD": "true", "S3_BUCKET_NAME": "bucket"},
                clear=True,
            ):
                with redirect_stdout(stream):
                    result = s3_uploader.upload_report_to_s3(str(report))

        self.assertIsNone(result)
        self.assertIn("[WARNING]", stream.getvalue())
        self.assertIn(str(report), stream.getvalue())

    def test_s3_key_uses_reports_prefix_and_original_filename(self) -> None:
        report = Path("reports") / "stock_report_7203_ec2.html"

        self.assertEqual(
            s3_uploader._s3_key_for_report(report, "reports"),
            "reports/stock_report_7203_ec2.html",
        )

    def test_upload_failure_returns_none_without_raising(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report = Path(temp_dir) / "stock_report_7203.html"
            report.write_text("<html></html>", encoding="utf-8")
            upload_file = Mock(side_effect=RuntimeError("AccessDenied"))
            boto3_module = types.SimpleNamespace(
                client=Mock(return_value=types.SimpleNamespace(upload_file=upload_file))
            )
            stream = StringIO()
            with patch.dict(
                "os.environ",
                {
                    "ENABLE_S3_UPLOAD": "true",
                    "S3_BUCKET_NAME": "bucket",
                    "S3_REPORT_PREFIX": "reports",
                },
                clear=True,
            ):
                with patch.dict("sys.modules", {"boto3": boto3_module}):
                    with redirect_stdout(stream):
                        result = s3_uploader.upload_report_to_s3(str(report))

        self.assertIsNone(result)
        self.assertIn("S3アップロードに失敗しました", stream.getvalue())
        self.assertIn("AccessDenied", stream.getvalue())

    def test_enable_values_are_case_insensitive(self) -> None:
        for value in ["TRUE", "1", "yes", "on"]:
            with self.subTest(value=value):
                self.assertTrue(s3_uploader.is_s3_upload_enabled(value))


if __name__ == "__main__":
    unittest.main()
