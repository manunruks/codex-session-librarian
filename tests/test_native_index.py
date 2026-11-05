"""Keep the native resume picker in sync with files installed by CSL."""

import contextlib
import hashlib
import io
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch

import csl_codex_rpc as rpc_module
import csl_transfer as transfer


class PickerIndexTests(unittest.TestCase):
    def test_refresh_uses_scan_repair_and_paginates_all_interactive_providers(self):
        with patch.object(rpc_module, "CodexRPC") as client:
            rpc = client.return_value.__enter__.return_value
            rpc.call.side_effect = [{"data": [{"id": "one"}], "nextCursor": "next"},
                                    {"data": [{"id": "two"}], "nextCursor": None}]
            self.assertEqual(rpc_module.refresh_picker_index(Path("/unused")), 2)
            params = rpc.call.call_args_list[0].args[1]
            self.assertFalse(params["useStateDbOnly"])
            self.assertEqual(params["modelProviders"], [])
            self.assertEqual(params["sourceKinds"], ["cli", "vscode"])
            self.assertFalse(params["archived"])
            self.assertEqual(rpc.call.call_args_list[1].args[1]["cursor"], "next")

    def test_repeated_cursor_stops_refresh(self):
        with patch.object(rpc_module, "CodexRPC") as client:
            client.return_value.__enter__.return_value.call.return_value = {"data": [], "nextCursor": "same"}
            with self.assertRaises(transfer.TransferError):
                rpc_module.refresh_picker_index(Path("/unused"))

    def test_missing_or_failing_codex_does_not_make_import_a_hard_dependency(self):
        csl = type("CSL", (), {"DEFAULT_CODEX_HOME": Path("/unused")})()
        with contextlib.redirect_stdout(io.StringIO()), patch.object(transfer.shutil, "which", return_value=None):
            self.assertFalse(transfer.refresh_native_picker(csl))
        with contextlib.redirect_stderr(io.StringIO()), patch.object(transfer.shutil, "which", return_value="/fake/codex"), \
             patch.object(rpc_module, "refresh_picker_index", side_effect=ValueError("unavailable")):
            self.assertFalse(transfer.refresh_native_picker(csl))


@unittest.skipUnless(os.getenv("CSL_RUN_CODEX_NATIVE_TESTS") == "1" and shutil.which("codex"),
                     "Set CSL_RUN_CODEX_NATIVE_TESTS=1 to test a warm native picker")
class WarmPickerNativeTests(unittest.TestCase):
    def setUp(self):
        from test_clone_visibility import CloneVisibilityTests
        self.h = CloneVisibilityTests(methodName="runTest")
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        self.cli = Path(__file__).resolve().parents[1] / "codex_sessions.py"
        self.destination = self.h.root / "destination"
        self.destination.mkdir(mode=0o700)
        self.env = {**self.h.env, "CODEX_HOME": str(self.destination)}

    def native_ids(self, client):
        page = client.call("thread/list", {"limit": 100, "modelProviders": [],
            "sourceKinds": ["cli", "vscode"], "archived": False, "useStateDbOnly": True})
        return {thread["id"] for thread in page["data"]}

    def run_cli(self, *args):
        result = subprocess.run([sys.executable, str(self.cli), *map(str, args)],
            cwd=self.h.project, env=self.env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def test_import_is_visible_to_an_already_running_database_only_picker(self):
        bundle = self.h.root / "synthetic.csl.zip"
        self.h.run_cli("export", self.h.sid, "--to", bundle)
        before = self.h.source.read_bytes()
        with patch.dict(os.environ, self.env, clear=True):
            with rpc_module.CodexRPC(self.destination) as warm:
                self.assertEqual(self.native_ids(warm), set())
                result = self.run_cli("import", bundle, "--cwd", self.h.project)
                sid = re.search(r"imported: ([0-9a-f-]+)", result.stdout).group(1)
                self.assertIn("native picker index: refreshed", result.stdout)
                self.assertIn(sid, self.native_ids(warm))
        self.assertEqual(self.h.source.read_bytes(), before)

    def test_index_native_repairs_previously_installed_files_without_reimport(self):
        with patch.dict(os.environ, self.env, clear=True):
            with rpc_module.CodexRPC(self.destination) as warm:
                self.assertEqual(self.native_ids(warm), set())
                folder = self.destination / "sessions/2026/01/01"
                folder.mkdir(parents=True)
                target = folder / self.h.source.name
                shutil.copyfile(self.h.source, target)
                before = hashlib.sha256(target.read_bytes()).hexdigest()
                self.assertEqual(self.native_ids(warm), set())
                result = self.run_cli("index", "--native")
                self.assertIn("native picker index: refreshed", result.stdout)
                self.assertIn(self.h.sid, self.native_ids(warm))
                self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), before)
                self.assertEqual(len(list(self.destination.rglob("rollout-*.jsonl"))), 1)
