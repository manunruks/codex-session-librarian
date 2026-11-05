"""Synthetic batch migrations using the existing sharing/import implementation."""

from contextlib import ExitStack, contextmanager
import json
import os
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch

import codex_sessions as csl
import csl_migration as migration
import csl_sharing as sharing
from csl_transfer import TransferError
import test_sharing


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.h = test_sharing.SharingTests(methodName="runTest")
        self.h.setUp()
        self.addCleanup(self.h.tearDown)
        self.second = self.h.make_session()
        self.entries = [{"id": sid, "path": str(next(self.h.home.rglob(f"*{sid}.jsonl")))}
                        for sid in (self.h.sid, self.second)]
        self.indexes = {}
        self.real_fake = self.h.fake_gh
        self.patchers = [patch.object(sharing, "run_gh", side_effect=self.fake_gh),
                         patch.object(migration, "visible_sessions", return_value=self.entries)]
        for p in self.patchers:
            p.start()
            self.addCleanup(p.stop)
        self.h.connect()

    def fake_gh(self, args):
        if args[:2] == ["release", "create"] and args[2].startswith("csl-migration-"):
            if args[2] in self.indexes:
                raise TransferError("Release exists")
            self.indexes[args[2]] = Path(args[3]).read_bytes()
            return ""
        if args[:2] == ["release", "download"] and args[2].startswith("csl-migration-"):
            Path(args[args.index("--output") + 1]).write_bytes(self.indexes[args[2]])
            return ""
        return self.real_fake(args)

    def command(self, *args):
        return self.h.command("migrate", *args)

    @contextmanager
    def new_computer(self):
        home = self.h.root / "new-codex"
        with ExitStack() as stack:
            for name, value in (("DEFAULT_CODEX_HOME", home), ("DEFAULT_SESSIONS_DIR", home / "sessions"),
                ("DEFAULT_SESSION_INDEX", home / "session_index.jsonl"), ("DEFAULT_DB", home / "index.sqlite")):
                stack.enter_context(patch.object(csl, name, value))
            self.h.connect()
            yield home

    def test_upload_restore_all_to_another_home_and_repeat_without_duplicates(self):
        tag = self.command("upload")
        manifest = json.loads(self.indexes[tag])
        self.assertEqual(len(manifest["sessions"]), 2)
        self.assertEqual(len(self.h.releases), 2)
        self.assertNotIn(str(self.h.home), self.indexes[tag].decode())
        self.assertNotIn("path", self.indexes[tag].decode())
        self.assertTrue(all(Path(e["path"]).exists() for e in self.entries))
        with self.new_computer() as home:
            ids = self.command("download", tag, "--cwd", str(self.h.cwd))
            self.assertEqual(len(ids), 2)
            self.assertTrue(set(ids).isdisjoint({self.h.sid, self.second}))
            self.assertEqual(self.command("download", tag, "--cwd", str(self.h.cwd)), ids)
            files = list((home / "sessions").rglob("*.jsonl"))
            self.assertEqual(len(files), 2)
            self.assertTrue(all("Cobalt 73 remembered" in p.read_text() for p in files))

    def test_dry_run_does_not_upload_or_create_migration_state(self):
        self.command("upload", "--dry-run")
        self.assertEqual(self.indexes, {})
        self.assertEqual(self.h.releases, {})
        self.assertFalse((self.h.home / "csl-migrations").exists())

    def test_failed_upload_can_resume_without_resharing_successes(self):
        original = sharing.share
        count = 0
        def flaky(args, csl):
            nonlocal count
            count += 1
            if count == 2:
                raise TransferError("Synthetic interrupted upload")
            return original(args, csl)
        with patch.object(sharing, "share", side_effect=flaky):
            with self.assertRaises(SystemExit):
                self.command("upload")
        state = json.loads(next((self.h.home / "csl-migrations").glob("*.json")).read_text())
        self.assertFalse(state["complete"])
        self.assertEqual(len(self.h.releases), 1)
        self.command("upload", "--resume", state["id"])
        self.assertEqual(len(self.h.releases), 2)
        self.command("upload", "--resume", state["id"])
        self.assertEqual(len(self.h.releases), 2)

    def test_cleanup_requires_confirmation_and_only_archives_uploaded_originals(self):
        tag = self.command("upload")
        unrelated = self.h.make_session()
        auth = self.h.home / "auth.json"
        auth.write_text("SYNTHETIC-DO-NOT-TOUCH")
        with patch.object(migration, "CodexRPC") as client:
            self.command("cleanup", tag)
            client.assert_not_called()
            def archive(method, params):
                self.assertEqual(method, "thread/archive")
                source = next((self.h.home / "sessions").rglob(f"*{params['threadId']}.jsonl"))
                target = self.h.home / "archived_sessions" / source.name
                target.parent.mkdir(exist_ok=True)
                source.rename(target)
                return {}
            rpc = client.return_value.__enter__.return_value
            rpc.call.side_effect = archive
            self.command("cleanup", tag, "--confirm-restored")
            self.assertEqual(rpc.call.call_count, 2)
            self.command("cleanup", tag, "--confirm-restored")
            self.assertEqual(rpc.call.call_count, 2)
        self.assertEqual(len(list((self.h.home / "archived_sessions").glob("*.jsonl"))), 2)
        self.assertTrue(list((self.h.home / "sessions").rglob(f"*{unrelated}.jsonl")))
        self.assertEqual(auth.read_text(), "SYNTHETIC-DO-NOT-TOUCH")

    def test_cleanup_refuses_changed_source_before_archiving_any(self):
        tag = self.command("upload")
        with Path(self.entries[1]["path"]).open("a") as stream:
            stream.write('{}\n')
        with patch.object(migration, "CodexRPC") as client:
            with self.assertRaises(SystemExit):
                self.command("cleanup", tag, "--confirm-restored")
            client.assert_not_called()

    def test_cleanup_without_completed_upload_is_refused(self):
        with patch.object(migration, "CodexRPC") as client:
            with self.assertRaises(SystemExit):
                self.command("cleanup", "csl-migration-0123456789ab", "--confirm-restored")
            client.assert_not_called()

    def test_interrupted_download_resumes_using_existing_receive_receipts(self):
        tag = self.command("upload")
        original = sharing.receive
        count = 0
        def flaky(args, csl):
            nonlocal count
            count += 1
            if count == 2:
                raise TransferError("Synthetic download interruption")
            return original(args, csl)
        with self.new_computer() as home:
            with patch.object(sharing, "receive", side_effect=flaky):
                with self.assertRaises(SystemExit):
                    self.command("download", tag, "--cwd", str(self.h.cwd))
            self.assertEqual(len(list((home / "sessions").rglob("*.jsonl"))), 1)
            self.assertEqual(len(self.command("download", tag, "--cwd", str(self.h.cwd))), 2)
            self.assertEqual(len(list((home / "sessions").rglob("*.jsonl"))), 2)

    def test_batch_refreshes_native_picker_once_not_once_per_session(self):
        import csl_transfer
        tag = self.command("upload")
        with self.new_computer(), patch.object(migration, "refresh_native_picker", return_value=True) as batch, \
             patch.object(csl_transfer, "refresh_native_picker", return_value=True) as individual:
            self.command("download", tag, "--cwd", str(self.h.cwd))
            batch.assert_called_once_with(csl)
            individual.assert_not_called()

    def test_partial_batch_also_refreshes_the_completed_imports(self):
        tag = self.command("upload")
        original = sharing.receive
        count = 0
        def flaky(args, csl):
            nonlocal count
            count += 1
            if count == 2:
                raise TransferError("Synthetic interrupted download")
            return original(args, csl)
        with self.new_computer(), patch.object(sharing, "receive", side_effect=flaky), \
             patch.object(migration, "refresh_native_picker", return_value=True) as refresh:
            with self.assertRaises(SystemExit):
                self.command("download", tag, "--cwd", str(self.h.cwd))
            refresh.assert_called_once_with(csl)

    def test_changed_previously_uploaded_source_blocks_resume_publication(self):
        original = sharing.share
        count = 0
        def flaky(args, csl):
            nonlocal count
            count += 1
            if count == 2:
                raise TransferError("Synthetic interrupted upload")
            return original(args, csl)
        with patch.object(sharing, "share", side_effect=flaky):
            with self.assertRaises(SystemExit):
                self.command("upload")
        state = json.loads(next((self.h.home / "csl-migrations").glob("*.json")).read_text())
        with Path(self.entries[0]["path"]).open("a") as stream:
            stream.write('{}\n')
        with self.assertRaises(SystemExit):
            self.command("upload", "--resume", state["id"])
        self.assertEqual(self.indexes, {})

    def test_invalid_manifest_is_rejected_before_any_receive(self):
        tag = self.command("upload")
        data = json.loads(self.indexes[tag])
        for modify in (lambda d: d.update(repo="other/repo"),
                       lambda d: d["sessions"].append(d["sessions"][0]),
                       lambda d: d["sessions"][0].update(share_id="../bad")):
            sample = json.loads(json.dumps(data))
            modify(sample)
            self.indexes[tag] = json.dumps(sample).encode()
            with patch.object(sharing, "receive") as receive:
                with self.assertRaises(SystemExit):
                    self.command("download", tag, "--cwd", str(self.h.cwd))
                receive.assert_not_called()

    def test_public_exchange_blocks_upload(self):
        self.h.repo["isPrivate"] = False
        with self.assertRaises(SystemExit):
            self.command("upload")
        self.assertEqual(self.h.releases, {})


class MigrationListingTests(unittest.TestCase):
    def test_rpc_never_allows_model_turns_or_deletion(self):
        from csl_codex_rpc import CodexRPC
        rpc = CodexRPC(Path("/unused"))
        for method in ("turn/start", "thread/delete", "thread/resume"):
            with self.assertRaises(TransferError):
                rpc.call(method, {})

    def test_listing_uses_interactive_sources_and_paginates(self):
        with patch.object(migration, "CodexRPC") as client:
            rpc = client.return_value.__enter__.return_value
            rpc.call.side_effect = [{"data": [], "nextCursor": "next"}, {"data": [], "nextCursor": None}]
            self.assertEqual(migration.visible_sessions(csl), [])
            params = rpc.call.call_args_list[0].args[1]
            self.assertEqual(params["sourceKinds"], ["cli", "vscode"])
            self.assertFalse(params["archived"])
            self.assertEqual(params["modelProviders"], [])
            self.assertEqual(params["sortKey"], "recency_at")
            self.assertEqual(rpc.call.call_args_list[1].args[1]["cursor"], "next")

    def test_repeated_cursor_is_rejected(self):
        with patch.object(migration, "CodexRPC") as client:
            client.return_value.__enter__.return_value.call.return_value = {"data": [], "nextCursor": "same"}
            with self.assertRaises(TransferError):
                migration.visible_sessions(csl)


@unittest.skipUnless(os.environ.get("CSL_RUN_CODEX_NATIVE_TESTS") == "1" and shutil.which("codex"),
                     "Set CSL_RUN_CODEX_NATIVE_TESTS=1 for native migration listing/archive checks")
class MigrationNativeTests(unittest.TestCase):
    def test_real_list_and_cleanup_leave_agent_fork_untouched(self):
        from test_clone_visibility import CloneVisibilityTests
        harness = CloneVisibilityTests(methodName="runTest")
        harness.setUp()
        self.addCleanup(harness.doCleanups)
        agent, agent_path, _ = harness.clone("agent")
        archived, _, _ = harness.clone("archived")
        with patch.object(csl, "DEFAULT_CODEX_HOME", harness.home), \
             patch.object(csl, "DEFAULT_SESSIONS_DIR", harness.home / "sessions"):
            entries = migration.visible_sessions(csl)
            self.assertEqual({e["id"] for e in entries}, {harness.sid})
            tag = "csl-migration-0123456789ab"
            for entry in entries:
                entry["sha256"] = sharing.file_sha256(Path(entry["path"]))
            sharing.save_json(migration.state_path(csl, tag), {"complete": True, "sessions": entries})
            args = type("Args", (), {"migration_id": tag, "confirm_restored": True})()
            migration.cleanup(args, csl)
            self.assertTrue(agent_path.exists())
            self.assertFalse(harness.source.exists())
            archive = next((harness.home / "archived_sessions").glob(f"*{harness.sid}.jsonl"))
            self.assertEqual(archive.read_bytes(), harness.before)
            self.assertEqual(migration.visible_sessions(csl), [])
