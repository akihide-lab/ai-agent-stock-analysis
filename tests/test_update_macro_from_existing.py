from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import update_macro_from_existing


class UpdateMacroFromExistingPathTests(unittest.TestCase):
    def test_default_source_data_is_repo_relative(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                update_macro_from_existing.default_source_data(),
                PROJECT_ROOT / "data" / "import",
            )

    def test_source_data_environment_variable_overrides_default(self) -> None:
        env_path = Path("custom") / "macro-data"
        with mock.patch.dict(
            os.environ,
            {update_macro_from_existing.SOURCE_DATA_ENV: str(env_path)},
            clear=True,
        ):
            self.assertEqual(update_macro_from_existing.default_source_data(), env_path)

    def test_cli_source_data_overrides_environment_variable(self) -> None:
        cli_path = Path("cli") / "macro-data"
        with mock.patch.dict(
            os.environ,
            {update_macro_from_existing.SOURCE_DATA_ENV: "env-macro-data"},
            clear=True,
        ):
            with mock.patch.object(
                sys,
                "argv",
                [
                    "update_macro_from_existing.py",
                    "--source-data",
                    str(cli_path),
                ],
            ):
                args = update_macro_from_existing.parse_args()

        self.assertEqual(args.source_data, cli_path)


if __name__ == "__main__":
    unittest.main()
