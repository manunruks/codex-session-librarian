"""Explicit legacy-copy recovery must never silently weaken normal validation."""

import copy
import io
import json
from pathlib import Path
import unittest
import zipfile

import csl_diagnostics
import csl_transfer as transfer
import test_migration
import test_sharing


def damaged_checkpoint():
    return {"type": "compacted", "timestamp": "2026-11-04T00:00:00Z", "payload": {
        "message": "", "replacement_history": [
            {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "KEPT-USER-FACT"}]},
            {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "KEPT-ASSISTANT-FACT"}]}],
        "replacement_history_metadata": [{"client_authored": False, "user_input_order": 1},
            {"client_authored": False, "user_input_order": 2},
            {"client_authored": False, "compaction_model_hash": "synthetic-summary-model"}]}}


class LegacyCompactionTests(unittest.TestCase):
    def test_known_orphan_is_removed_without_changing_history_or_source(self):
        record = damaged_checkpoint()
        before = copy.deepcopy(record)
        with self.assertRaises(transfer.TransferError):
            transfer.validate_compaction(record)
        fixed, changed = transfer.recover_legacy_compaction(record)
        self.assertTrue(changed)
        self.assertEqual(record, before)
        self.assertEqual(fixed["payload"]["replacement_history"], before["payload"]["replacement_history"])
        self.assertEqual(fixed["payload"]["replacement_history_metadata"], before["payload"]["replacement_history_metadata"][:-1])
        self.assertTrue(fixed["csl_portable_compaction"]["opaque_summary_removed"])
        transfer.validate_compaction(fixed)

    def test_ambiguous_patterns_fail_closed(self):
        cases = []
        def case(modify):
            record = damaged_checkpoint()
            modify(record["payload"])
            cases.append(record)
        case(lambda p: p["replacement_history_metadata"][-1].pop("compaction_model_hash"))
        case(lambda p: p["replacement_history_metadata"][0].update(compaction_model_hash="another"))
        case(lambda p: p["replacement_history_metadata"][-1].update(compaction_model_hash=""))
        case(lambda p: p["replacement_history_metadata"][-1].update(compaction_model_hash=None))
        case(lambda p: p["replacement_history_metadata"].reverse())
        case(lambda p: p["replacement_history_metadata"].append({"client_authored": False}))
        case(lambda p: p["replacement_history"][0].update(type="compaction"))
        case(lambda p: p.update(encrypted_content="still-present-summary"))
        case(lambda p: p["replacement_history_metadata"].__setitem__(0, None))
        case(lambda p: p["replacement_history"].__setitem__(0, None))
        for record in cases:
            with self.subTest(record=cases.index(record)):
                before = copy.deepcopy(record)
                with self.assertRaises(transfer.TransferError):
                    transfer.recover_legacy_compaction(record)
                self.assertEqual(record, before)

    def test_valid_and_legacy_metadata_absence_are_unchanged(self):
        for metadata in (None, [], [{"client_authored": False}] * 2):
            record = damaged_checkpoint()
            record["payload"]["replacement_history_metadata"] = metadata
            fixed, changed = transfer.recover_legacy_compaction(record)
            self.assertFalse(changed)
            self.assertIs(fixed, record)


class LegacyCompactionTransferTests(unittest.TestCase):
    def setUp(self):
        self.h = test_sharing.SharingTests(methodName="runTest")
        self.h.setUp()
        self.addCleanup(self.h.tearDown)
        self.source = next(self.h.home.rglob(f"*{self.h.sid}.jsonl"))
        with self.source.open("a") as stream:
            stream.write(json.dumps(damaged_checkpoint()) + "\n")
            stream.write(json.dumps({"type": "response_item", "payload": {"type": "message", "role": "user",
                "content": [{"type": "input_text", "text": "LATER-WORK-KEEP"}]}}) + "\n")
        self.original = self.source.read_bytes()

    def test_explicit_export_import_preserves_later_turns_and_labels_context_loss(self):
        bundle = self.h.root / "recovered.zip"
        with self.assertRaises(SystemExit):
            self.h.command("export", self.h.sid, "--to", str(bundle))
        self.assertFalse(bundle.exists())
        self.h.command("export", self.h.sid, "--to", str(bundle), "--repair-legacy-compaction")
        with zipfile.ZipFile(bundle) as archive:
            manifest = transfer.inspect_bundle(archive)
            entry = manifest["sessions"][0]
            self.assertTrue(entry["compaction_state_removed"])
            self.assertEqual(entry["legacy_compaction_checkpoints_recovered"], 1)
            content = archive.read(entry["file"]).decode()
            self.assertIn("LATER-WORK-KEEP", content)
            self.assertIn("KEPT-USER-FACT", content)
        ids = transfer.import_bundle(type("Args", (), {"bundle": bundle, "cwd": self.h.cwd,
            "list": False, "open": False, "name": None, "db": self.h.home / "index.sqlite"})(),
            test_sharing.csl)
        target = next((self.h.home / "sessions").rglob(f"*{ids[0]}.jsonl"))
        report = csl_diagnostics.analyze(target, "codex")
        self.assertEqual(report["structure"], "passed")
        self.assertNotEqual(report["active_context"], "reconstructed-statically")
        self.assertTrue(any("active_context_unavailable" in warning for warning in report["warnings"]))
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertIn("LATER-WORK-KEEP", target.read_text())

    def test_raw_cannot_be_combined_with_recovery(self):
        bundle = self.h.root / "raw.zip"
        with self.assertRaises(SystemExit):
            self.h.command("export", self.h.sid, "--to", str(bundle), "--raw", "--repair-legacy-compaction")
        self.assertFalse(bundle.exists())

    def test_share_passes_recovery_to_the_existing_exporter(self):
        self.h.connect()
        tag = self.h.command("share", self.h.sid, "--repair-legacy-compaction")
        with zipfile.ZipFile(io.BytesIO(self.h.assets[tag])) as archive:
            self.assertEqual(transfer.inspect_bundle(archive)["sessions"][0]["legacy_compaction_checkpoints_recovered"], 1)
        self.assertEqual(self.source.read_bytes(), self.original)


class LegacyCompactionMigrationTests(unittest.TestCase):
    def test_resume_reuses_finished_shares_and_preserves_original_later_work(self):
        h = test_migration.MigrationTests(methodName="runTest")
        h.setUp()
        self.addCleanup(h.doCleanups)
        source = Path(h.entries[1]["path"])
        with source.open("a") as stream:
            stream.write(json.dumps(damaged_checkpoint()) + "\n")
        original = source.read_bytes()
        with self.assertRaises(SystemExit):
            h.command("upload", "--scrub-secrets")
        state_file = next((h.h.home / "csl-migrations").glob("*.json"))
        state = json.loads(state_file.read_text())
        self.assertEqual(len(h.h.releases), 1)
        h.command("upload", "--resume", state["id"], "--scrub-secrets", "--repair-legacy-compaction")
        self.assertEqual(len(h.h.releases), 2)
        self.assertTrue(json.loads(state_file.read_text())["repair_legacy_compaction"])
        self.assertEqual(source.read_bytes(), original)
        with h.new_computer():
            self.assertEqual(len(h.command("download", state["id"], "--cwd", str(h.h.cwd))), 2)
