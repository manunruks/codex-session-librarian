"""Opt-in real-CLI migrations between isolated Python/home environments, no network."""

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
import zipfile


REPO = Path(__file__).resolve().parents[1]
CODEX = shutil.which("codex")
BWRAP = shutil.which("bwrap")


@unittest.skipUnless(os.getenv("CSL_RUN_MIGRATION_E2E_TESTS") == "1" and CODEX and BWRAP,
                     "Opt in with CSL_RUN_MIGRATION_E2E_TESTS=1; Codex and bubblewrap required")
class MigrationE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runtime = tempfile.TemporaryDirectory(prefix="csl-migration-runtimes-")
        cls.addClassCleanup(cls.runtime.cleanup)
        cls.pythons = {}
        for machine in ("old", "new"):
            directory = Path(cls.runtime.name) / machine
            subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(directory)],
                           check=True, capture_output=True, timeout=30)
            cls.pythons[machine] = directory / "bin/python"

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="csl-migration-e2e-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.exchange = self.root / "exchange"
        self.bin = self.root / "bin"
        self.bin.mkdir()
        shutil.copyfile(REPO / "tests/fixtures/migration_gh.py", self.bin / "gh")
        (self.bin / "gh").chmod(0o700)
        (self.bin / "codex").symlink_to(CODEX)
        self.machines = {}
        for machine in ("old", "new"):
            root = self.root / machine
            project = root / "project with spaces"
            project.mkdir(parents=True)
            (root / "tmp").mkdir()
            home = root / "codex"
            home.mkdir()
            self.machines[machine] = {"root": root, "home": home, "project": project}
            self.cli(machine, "team", "connect", "team/migration-fixtures")

    def cli(self, machine, *args, ok=True, extra=None, code=None):
        item = self.machines[machine]
        env = {"PATH": str(self.bin) + os.pathsep + os.defpath, "HOME": str(item["root"]),
            "CODEX_HOME": str(item["home"]), "CLAUDE_CONFIG_DIR": str(item["root"] / "claude"),
            "TMPDIR": str(item["root"] / "tmp"), "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1",
            "CSL_FAKE_GH_ROOT": str(self.exchange), **(extra or {})}
        # Shared OS/runtime/code are read-only; only the synthetic lab is writable.
        program = (["-c", "import sys;sys.path.insert(0," + repr(str(REPO)) + ");" + code] if code
                   else [str(REPO / "codex_sessions.py"), *map(str, args)])
        command = [BWRAP, "--unshare-net", "--die-with-parent", "--ro-bind", "/", "/",
            "--bind", str(self.root), str(self.root), "--dev", "/dev", "--proc", "/proc",
            "--", str(self.pythons[machine]), *program]
        result = subprocess.run(command, env=env, cwd=item["project"], capture_output=True, text=True, timeout=180)
        self.assertEqual(result.returncode == 0, ok, result.stdout[-3000:] + result.stderr[-3000:])
        return result

    def seed(self, count=4, hidden=True):
        self.sources = {}
        self.hashes = {}
        home = self.machines["old"]["home"]
        sources = ["cli", "vscode", "cli", "cli"]
        names = []
        for number in range(count + (2 if hidden else 0)):
            sid = str(uuid.uuid4())
            archived = hidden and number == count + 1
            source = "exec" if hidden and number == count else sources[number % len(sources)]
            folder = home / ("archived_sessions" if archived else "sessions/2026/11/04")
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f"rollout-2026-11-04T00-00-00-{sid}.jsonl"
            marker = f"MIGRATION-FACT-{number:04d}"
            records = [
                {"type": "session_meta", "payload": {"id": sid, "session_id": sid, "originator": "codex_cli_rs",
                    "timestamp": "2026-11-04T00:00:00Z",
                    "cwd": str(self.machines["old"]["project"]), "source": source,
                    "cli_version": "0.166.0", "model_provider": "openai" if number % 2 else "synthetic_provider"}},
                {"type": "response_item", "payload": {"type": "message", "role": "user",
                    "content": [{"type": "input_text", "text": f"Remember {marker}; cafe and 日本語."}]}},
                {"type": "event_msg", "payload": {"type": "user_message", "message": f"Remember {marker}",
                    "images": [], "local_images": [], "text_elements": []}},
                {"type": "response_item", "payload": {"type": "function_call", "call_id": "call_fixture",
                    "name": "exec_command", "arguments": '{"cmd":"synthetic-only-never-run"}'}},
                {"type": "response_item", "payload": {"type": "function_call_output", "call_id": "call_fixture",
                    "output": f"TOOL-FACT-{number:04d}"}},
                {"type": "response_item", "payload": {"type": "message", "role": "assistant",
                    "content": [{"type": "output_text", "text": f"ANSWER-{marker}"}]}},
                {"type": "event_msg", "payload": {"type": "agent_message", "message": f"ANSWER-{marker}",
                    "phase": "final_answer"}},
            ]
            path.write_text("".join(json.dumps({"timestamp": "2026-11-04T00:00:00Z", **r}, ensure_ascii=False)
                                    + "\n" for r in records), encoding="utf-8")
            self.hashes[path] = hashlib.sha256(path.read_bytes()).hexdigest()
            if number < count:
                self.sources[sid] = {"path": path, "marker": marker}
                names.append({"id": sid, "thread_name": f"Fixture {number:04d} cafe", "updated_at": "2026-11-04T00:00:00Z"})
        (home / "session_index.jsonl").write_text("".join(json.dumps(row) + "\n" for row in names))
        return self.sources

    def upload(self, **extra):
        result = self.cli("old", "migrate", "upload", extra=extra or None)
        return re.search(r"migration: (csl-migration-[0-9a-f]+)", result.stdout).group(1)

    def download(self, tag, **kwargs):
        return self.cli("new", "migrate", "download", tag, "--cwd", self.machines["new"]["project"], **kwargs)

    def restored(self):
        return list((self.machines["new"]["home"] / "sessions").rglob("*.jsonl"))

    def manifest(self, tag):
        return json.loads((self.exchange / tag / "migration.json").read_text())

    def assert_sources_unchanged(self):
        for path, digest in self.hashes.items():
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)

    def test_125_sessions_pagination_restore_titles_content_and_cleanup(self):
        self.seed(125)
        self.cli("old", "migrate", "upload", "--dry-run")
        self.assertFalse((self.exchange / "releases.json").exists())
        tag = self.upload()
        data = self.manifest(tag)
        self.assertEqual({e["id"] for e in data["sessions"]}, set(self.sources))
        self.assertNotIn(str(self.root), json.dumps(data))
        self.download(tag)
        files = self.restored()
        self.assertEqual(len(files), 125)
        originals = set(self.sources)
        for path in files:
            text = path.read_text()
            meta = json.loads(text.splitlines()[0])["payload"]
            self.assertNotIn(meta["id"], originals)
            self.assertEqual(meta["cwd"], str(self.machines["new"]["project"]))
            self.assertIn("TOOL-FACT-", text)
            self.assertIn("日本語", text)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        all_text = "\n".join(p.read_text() for p in files)
        for source in self.sources.values():
            self.assertIn("ANSWER-" + source["marker"], all_text)
        names = [json.loads(line)["thread_name"] for line in
                 (self.machines["new"]["home"] / "session_index.jsonl").read_text().splitlines()]
        self.assertEqual(set(names), {f"Fixture {n:04d} cafe" for n in range(125)})
        preview = self.cli("new", "migrate", "upload", "--dry-run")
        visible_ids = set(re.findall(r"(?m)^[a-f0-9-]{36}$", preview.stdout))
        self.assertEqual(visible_ids, {json.loads(p.read_text().splitlines()[0])["payload"]["id"] for p in files})
        sid = json.loads(files[0].read_text().splitlines()[0])["payload"]["id"]
        code = ("sys.path.insert(0," + repr(str(REPO / "tests")) + ");"
            "import os,json,unittest;from pathlib import Path;from test_native_display import read_native_items;"
            "print(json.dumps(read_native_items(unittest.TestCase(),Path(os.environ['HOME']),dict(os.environ)," + repr(sid) + ")))" )
        loaded = self.cli("new", code=code)
        self.assertIn("ANSWER-MIGRATION-FACT-", loaded.stdout)
        asset = self.exchange / data["sessions"][0]["share_id"] / "conversation.csl.zip"
        with zipfile.ZipFile(asset) as bundle:
            self.assertTrue(all(name == "manifest.json" or name.startswith("sessions/") for name in bundle.namelist()))
        self.download(tag)
        self.assertEqual({p.name for p in self.restored()}, {p.name for p in files})
        self.assert_sources_unchanged()
        self.cli("old", "migrate", "cleanup", tag)
        self.assert_sources_unchanged()
        self.cli("old", "migrate", "cleanup", tag, "--confirm-restored")
        for sid, source in self.sources.items():
            archived = next((self.machines["old"]["home"] / "archived_sessions").glob(f"*{sid}.jsonl"))
            self.assertEqual(hashlib.sha256(archived.read_bytes()).hexdigest(), self.hashes[source["path"]])
        remaining = list((self.machines["old"]["home"] / "sessions").rglob("*.jsonl"))
        self.assertEqual(len(remaining), 1)  # Hidden exec fork was not part of the migration.
        self.cli("old", "migrate", "cleanup", tag, "--confirm-restored")

    def test_upload_interruption_resumes_across_processes(self):
        self.seed(7)
        result = self.cli("old", "migrate", "upload", ok=False, extra={"CSL_FAKE_FAIL_AFTER": "3"})
        tag = re.search(r"migration: (csl-migration-[0-9a-f]+)", result.stdout).group(1)
        self.assertFalse((self.exchange / tag).exists())
        self.cli("old", "migrate", "upload", "--resume", tag)
        self.assertEqual(len(json.loads((self.exchange / "releases.json").read_text())), 8)
        self.download(tag)
        self.assertEqual(len(self.restored()), 7)
        self.assert_sources_unchanged()

    def test_cold_257_session_listing_crosses_three_pages_without_losing_timestamp_ties(self):
        self.seed(257)
        tag = self.upload()
        self.assertEqual({e["id"] for e in self.manifest(tag)["sessions"]}, set(self.sources))
        self.assert_sources_unchanged()

    def test_secret_review_blocks_batch_and_scrubbed_retry_preserves_original(self):
        self.seed(1)
        source = next(iter(self.sources.values()))["path"]
        token = "sk-proj-" + "A" * 60  # Deliberately synthetic, never a credential.
        with source.open("a") as stream:
            stream.write(json.dumps({"type": "event_msg", "payload": {"type": "agent_message", "message": token}}) + "\n")
        result = self.cli("old", "migrate", "upload", ok=False)
        self.assertNotIn(token, result.stdout + result.stderr)
        self.assertFalse((self.exchange / "releases.json").exists())
        result = self.cli("old", "migrate", "upload", "--scrub-secrets")
        tag = re.search(r"migration: (csl-migration-[0-9a-f]+)", result.stdout).group(1)
        self.download(tag)
        self.assertIn(token, source.read_text())
        self.assertNotIn(token, self.restored()[0].read_text())
        self.assertIn("[CSL REDACTED]", self.restored()[0].read_text())

    def test_raw_and_portable_keep_existing_export_semantics(self):
        self.seed(1)
        source = next(iter(self.sources.values()))["path"]
        marker = "SYNTHETIC-ENCRYPTED-REASONING"
        with source.open("a") as stream:
            stream.write(json.dumps({"type": "response_item", "payload": {"type": "reasoning", "encrypted_content": marker}}) + "\n")
        for raw in (False, True):
            with self.subTest(raw=raw):
                result = self.cli("old", "migrate", "upload", *(["--raw"] if raw else []))
                tag = re.search(r"migration: (csl-migration-[0-9a-f]+)", result.stdout).group(1)
                share = self.manifest(tag)["sessions"][0]["share_id"]
                with zipfile.ZipFile(self.exchange / share / "conversation.csl.zip") as bundle:
                    metadata = json.loads(bundle.read("manifest.json"))
                    self.assertEqual(metadata["mode"], "raw" if raw else "portable")
                    transcript = bundle.read(metadata["sessions"][0]["file"]).decode()
                    self.assertEqual(marker in transcript, raw)

    def test_corrupt_download_installs_no_bad_session_and_retry_recovers(self):
        self.seed(5)
        tag = self.upload()
        bad = self.manifest(tag)["sessions"][2]["share_id"]
        self.download(tag, ok=False, extra={"CSL_FAKE_CORRUPT_DOWNLOAD": bad})
        self.assertEqual(len(self.restored()), 2)
        self.download(tag)
        self.assertEqual(len(self.restored()), 5)
        self.assert_sources_unchanged()

    def test_interrupted_download_and_wrong_cwd_leave_completed_imports_alone(self):
        self.seed(4)
        tag = self.upload()
        bad = self.manifest(tag)["sessions"][1]["share_id"]
        self.download(tag, ok=False, extra={"CSL_FAKE_FAIL_DOWNLOAD": bad})
        before = {p.name for p in self.restored()}
        other = self.machines["new"]["root"] / "other-project"
        other.mkdir()
        self.cli("new", "migrate", "download", tag, "--cwd", other, ok=False)
        self.assertEqual({p.name for p in self.restored()}, before)
        self.download(tag)
        self.assertEqual(len(self.restored()), 4)

    def test_changed_original_blocks_cleanup_without_archiving_any(self):
        self.seed(3)
        tag = self.upload()
        source = next(iter(self.sources.values()))["path"]
        with source.open("a") as stream:
            stream.write('{"type":"event_msg","payload":{"type":"agent_message","message":"NEW WORK"}}\n')
        self.cli("old", "migrate", "cleanup", tag, "--confirm-restored", ok=False)
        self.assertTrue(all(e["path"].exists() for e in self.sources.values()))
        self.cli("new", "migrate", "cleanup", tag, "--confirm-restored", ok=False)

    def test_public_exchange_and_no_write_permission_prevent_upload(self):
        self.seed(2)
        for extra in ({"CSL_FAKE_PUBLIC": "1"}, {"CSL_FAKE_PERMISSION": "READ"}):
            self.cli("old", "migrate", "upload", ok=False, extra=extra)
            self.assertFalse((self.exchange / "releases.json").exists())

    def test_malformed_or_cross_repo_index_cannot_restore(self):
        self.seed(2)
        tag = self.upload()
        path = self.exchange / tag / "migration.json"
        original = path.read_text()
        for value in ("{", json.dumps({**json.loads(original), "repo": "other/private"})):
            path.write_text(value)
            self.download(tag, ok=False)
            self.assertEqual(self.restored(), [])

    def test_lost_index_success_response_can_be_recovered(self):
        self.seed(2)
        result = self.cli("old", "migrate", "upload", extra={"CSL_FAKE_LOST_INDEX_RESPONSE": "1"})
        tag = re.search(r"migration: (csl-migration-[0-9a-f]+)", result.stdout).group(1)
        self.cli("old", "migrate", "upload", "--resume", tag)
        self.download(tag)
        self.assertEqual(len(self.restored()), 2)

    def test_conflicting_published_index_is_never_overwritten_on_retry(self):
        self.seed(2)
        tag = self.upload()
        local = self.machines["old"]["home"] / "csl-migrations" / f"{tag}.json"
        state = json.loads(local.read_text())
        state["complete"] = False
        local.write_text(json.dumps(state))
        remote = self.exchange / tag / "migration.json"
        remote.write_text('{"synthetic":"conflicting published content"}')
        before = remote.read_bytes()
        result = self.cli("old", "migrate", "upload", "--resume", tag, ok=False)
        self.assertIn("differs", result.stderr)
        self.assertEqual(remote.read_bytes(), before)
        self.assertFalse(json.loads(local.read_text())["complete"])
        self.assert_sources_unchanged()

    def test_resume_after_seven_shares_recovers_old_compaction_copy_and_keeps_later_work(self):
        from test_legacy_compaction_recovery import damaged_checkpoint
        self.seed(10)
        result = self.cli("old", "migrate", "upload", ok=False, extra={"CSL_FAKE_FAIL_AFTER": "7"})
        tag = re.search(r"migration: (csl-migration-[0-9a-f]+)", result.stdout).group(1)
        local = self.machines["old"]["home"] / "csl-migrations" / f"{tag}.json"
        state = json.loads(local.read_text())
        self.assertEqual(sum(bool(e.get("share_id")) for e in state["sessions"]), 7)
        source = Path(state["sessions"][7]["path"])
        records = [json.loads(line) for line in source.read_text().splitlines()]
        headers = []
        for version in ("0.160.0", "0.159.1", "0.153.4", "0.147.0", "0.139.0", "0.123.0", "0.123.0", "0.121.0", "0.121.0"):
            header = json.loads(json.dumps(records[0]))
            header["payload"]["cli_version"] = version
            headers.append(header)
        records = headers + records[1:] + [damaged_checkpoint(),
            {"type": "response_item", "timestamp": "2026-11-04T00:00:00Z", "payload": {
                "type": "message", "role": "user", "content": [{"type": "input_text", "text": "LATER-WORK-KEEP"}]}},
            {"type": "event_msg", "timestamp": "2026-11-04T00:00:00Z", "payload": {
                "type": "user_message", "message": "LATER-WORK-KEEP", "images": [], "local_images": [], "text_elements": []}}]
        source.write_text("".join(json.dumps(record) + "\n" for record in records))
        self.hashes[source] = hashlib.sha256(source.read_bytes()).hexdigest()
        self.cli("old", "migrate", "upload", "--resume", tag, "--scrub-secrets", ok=False)
        self.assertFalse((self.exchange / tag).exists())
        before = set(json.loads((self.exchange / "releases.json").read_text()))
        result = self.cli("old", "migrate", "upload", "--resume", tag, "--scrub-secrets", "--repair-legacy-compaction")
        self.assertIn("source unchanged", result.stderr)
        self.assertEqual(len(self.manifest(tag)["sessions"]), 10)
        after = set(json.loads((self.exchange / "releases.json").read_text()))
        self.assertTrue(before.issubset(after))
        self.assertEqual(len(after), 11)
        self.download(tag)
        self.assertEqual(len(self.restored()), 10)
        recovered = [p for p in self.restored() if "LATER-WORK-KEEP" in p.read_text()]
        self.assertEqual(len(recovered), 1)
        text = recovered[0].read_text()
        self.assertIn("KEPT-USER-FACT", text)
        self.assertIn("KEPT-ASSISTANT-FACT", text)
        self.assertIn('"compaction_state_removed": true', text)
        self.assertIn("legacy-orphaned-summary-metadata-v1", text)
        self.assert_sources_unchanged()
