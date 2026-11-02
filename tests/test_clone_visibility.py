"""Visibility regression tests; optional native checks never request inference."""

from contextlib import contextmanager
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import uuid


CLI = Path(__file__).resolve().parents[1] / "codex_sessions.py"


@contextmanager
def app_server(root, env):
    responses = queue.Queue()
    with (root / "server-errors.log").open("w") as errors:
        process = subprocess.Popen(["codex", "app-server", "-c", 'model_provider="csl_visibility"',
            "-c", 'model_providers.csl_visibility.name="CSL offline test"',
            "-c", 'model_providers.csl_visibility.base_url="http://127.0.0.1:1/v1"',
            "-c", 'model_providers.csl_visibility.wire_api="responses"',
            "-c", "model_providers.csl_visibility.requires_openai_auth=false"],
            env=env, cwd=root, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=errors, text=True)
        def reader():
            for line in process.stdout:
                try:
                    responses.put(json.loads(line))
                except ValueError:
                    pass
            responses.put({"closed": True})
        thread = threading.Thread(target=reader, daemon=True)
        thread.start()
        number = 0
        def call(method, params):
            nonlocal number
            number += 1
            process.stdin.write(json.dumps({"id": number, "method": method, "params": params}) + "\n")
            process.stdin.flush()
            while True:
                reply = responses.get(timeout=20)
                if reply.get("closed"):
                    raise AssertionError("app-server closed: " + (root / "server-errors.log").read_text()[-1000:])
                if reply.get("id") == number:
                    if "error" in reply:
                        raise AssertionError(reply["error"])
                    return reply["result"]
        try:
            call("initialize", {"clientInfo": {"name": "csl_visibility_test", "version": "1.0"}})
            process.stdin.write('{"method":"initialized","params":{}}\n')
            process.stdin.flush()
            yield call
        finally:
            process.stdin.close()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            thread.join(timeout=5)
            process.stdout.close()


def offline_continuation(test, env, project, sid):
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            item = {"id": "msg_visibility", "type": "message", "role": "assistant", "status": "completed",
                    "content": [{"type": "output_text", "text": "LOCAL-CONTINUATION-OK", "annotations": []}]}
            events = [
                {"type": "response.output_item.added", "output_index": 0,
                 "item": {**item, "status": "in_progress", "content": []}},
                {"type": "response.output_item.done", "output_index": 0, "item": item},
                {"type": "response.completed", "response": {"id": "resp_visibility", "status": "completed",
                    "output": [item], "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}}},
            ]
            body = "".join("event: " + event["type"] + "\ndata: " + json.dumps(event) + "\n\n" for event in events).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        command = ["codex", "exec", "--ignore-user-config", "--ignore-rules", "-s", "read-only",
            "-c", 'model_provider="csl_visibility"', "-c", 'model_providers.csl_visibility.name="CSL offline test"',
            "-c", f'model_providers.csl_visibility.base_url="http://127.0.0.1:{server.server_port}/v1"',
            "-c", 'model_providers.csl_visibility.wire_api="responses"',
            "-c", "model_providers.csl_visibility.requires_openai_auth=false", "-c", 'web_search="disabled"',
            "-c", "project_doc_max_bytes=0", "--model", "csl-offline-test", "--disable", "shell_tool",
            "resume", "--all", "--skip-git-repo-check", "--json", sid, "LOCAL-USER-CONTINUATION"]
        result = subprocess.run(command, cwd=project, env=env, capture_output=True, text=True, timeout=30)
        test.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        test.assertIn("LOCAL-CONTINUATION-OK", result.stdout)
        test.assertEqual(len(requests), 1)
        test.assertIn("SYNTHETIC-ANSWER-MARKER", json.dumps(requests))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class CloneVisibilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="csl-visibility-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / "codex"
        self.project = self.root / "project"
        self.project.mkdir()
        self.env = {"PATH": os.environ["PATH"], "HOME": str(self.root),
                    "CODEX_HOME": str(self.home), "LANG": "C.UTF-8"}
        self.sid = str(uuid.uuid4())
        folder = self.home / "sessions/2026/01/01"
        folder.mkdir(parents=True)
        self.source = folder / f"rollout-2026-01-01T00-00-00-{self.sid}.jsonl"
        stamp = "2026-01-01T00:00:00Z"
        records = [
            {"type": "session_meta", "payload": {"id": self.sid, "session_id": self.sid,
                "timestamp": stamp, "cwd": str(self.project), "originator": "codex_cli_rs",
                "cli_version": "0.166.0", "source": "cli", "model_provider": "csl_visibility"}},
            {"type": "response_item", "payload": {"type": "message", "role": "user",
                "content": [{"type": "input_text", "text": "SYNTHETIC-USER-MARKER"}]}},
            {"type": "event_msg", "payload": {"type": "user_message", "message": "SYNTHETIC-USER-MARKER",
                "images": [], "local_images": [], "text_elements": []}},
            {"type": "response_item", "payload": {"type": "message", "role": "assistant",
                "content": [{"type": "output_text", "text": "SYNTHETIC-ANSWER-MARKER"}]}},
            {"type": "event_msg", "payload": {"type": "agent_message", "message": "SYNTHETIC-ANSWER-MARKER",
                "phase": "final_answer"}},
        ]
        self.source.write_text("".join(json.dumps({"timestamp": stamp, **r}) + "\n" for r in records))
        self.before = self.source.read_bytes()
        self.run_cli("index")

    def run_cli(self, *args, success=True):
        result = subprocess.run([sys.executable, str(CLI), *map(str, args)],
            env=self.env, cwd=self.project, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
        return result

    def clone(self, visibility):
        result = self.run_cli("native-clone", self.sid, "--visibility", visibility, "--name", "Synthetic fork")
        sid = re.search(r"created native clone session: ([0-9a-f-]+)", result.stdout).group(1)
        path = Path(re.search(r"^path: (.+)$", result.stdout, re.M).group(1))
        self.assertEqual(self.source.read_bytes(), self.before)
        self.assertNotEqual(sid, self.sid)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        records = [json.loads(line) for line in path.read_text().splitlines()]
        self.assertEqual(records[0]["payload"]["id"], sid)
        self.assertEqual(records[0]["payload"]["session_id"], sid)
        self.assertEqual(records[0]["payload"]["forked_from_id"], self.sid)
        self.assertIn("SYNTHETIC-ANSWER-MARKER", path.read_text())
        sessions = json.loads(self.run_cli("sessions", "--json").stdout)["sessions"]
        self.assertIn(sid, [row["id"] for row in sessions])
        return sid, path, records

    def test_modes_preserve_source_and_register_private_new_sessions(self):
        for visibility in ("interactive", "agent", "archived"):
            with self.subTest(visibility=visibility):
                _, path, records = self.clone(visibility)
                self.assertEqual(records[0]["payload"]["source"], "exec" if visibility == "agent" else "cli")
                self.assertEqual("archived_sessions" in path.parts, visibility == "archived")

    def test_archived_uuid_is_not_reused_without_index_entry(self):
        sid, path, _ = self.clone("archived")
        (self.home / "session_index.jsonl").unlink()
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        result = self.run_cli("native-clone", self.sid, "--new-id", sid, success=False)
        self.assertIn("Refusing to reuse", result.stderr)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)

    def test_invalid_visibility_does_not_create_clone(self):
        self.run_cli("native-clone", self.sid, "--visibility", "invisible", success=False)
        self.assertEqual(len(list(self.home.rglob("rollout-*.jsonl"))), 1)

    def test_default_is_interactive_and_agent_prints_noninteractive_command(self):
        result = self.run_cli("native-clone", self.sid)
        path = Path(re.search(r"^path: (.+)$", result.stdout, re.M).group(1))
        self.assertEqual(json.loads(path.read_text().splitlines()[0])["payload"]["source"], "cli")
        self.assertIn("visibility: interactive", result.stdout)
        result = self.run_cli("native-clone", self.sid, "--visibility", "agent")
        self.assertIn("codex exec resume --all", result.stdout)
        self.assertNotIn("codex resume --all", result.stdout)

    def test_only_metadata_changes_and_interactive_mode_resets_exec_source(self):
        sid, path, records = self.clone("agent")
        original = [json.loads(line) for line in self.before.decode().splitlines()]
        self.assertEqual(records[1:], original[1:])
        result = self.run_cli("native-clone", sid, "--visibility", "interactive")
        target = Path(re.search(r"^path: (.+)$", result.stdout, re.M).group(1))
        self.assertEqual(json.loads(target.read_text().splitlines()[0])["payload"]["source"], "cli")

    def test_archived_clone_can_be_recovered_as_an_independent_interactive_clone(self):
        sid, path, _ = self.clone("archived")
        before = path.read_bytes()
        self.run_cli("index", "--prune")
        result = self.run_cli("native-clone", sid, "--visibility", "interactive")
        target = Path(re.search(r"^path: (.+)$", result.stdout, re.M).group(1))
        self.assertNotIn("archived_sessions", target.parts)
        self.assertEqual(path.read_bytes(), before)
        self.assertIn("SYNTHETIC-ANSWER-MARKER", target.read_text())

    def test_missing_metadata_is_rejected(self):
        self.source.write_text('\n'.join(self.source.read_text().splitlines()[1:]) + '\n')
        self.run_cli("native-clone", self.sid, "--visibility", "agent", success=False)
        self.assertEqual(len(list(self.home.rglob("rollout-*.jsonl"))), 1)

    def test_stale_index_entry_fails_without_creating_a_clone(self):
        self.source.unlink()
        result = self.run_cli("native-clone", self.sid, "--visibility", "agent", success=False)
        self.assertIn("No session matched", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(len(list(self.home.rglob("rollout-*.jsonl"))), 0)

    @unittest.skipUnless(os.environ.get("CSL_RUN_CODEX_NATIVE_TESTS") == "1" and shutil.which("codex"),
                         "Set CSL_RUN_CODEX_NATIVE_TESTS=1 for offline native lifecycle checks")
    def test_native_lists_resume_and_restart(self):
        normal, _, _ = self.clone("interactive")
        agent, agent_path, _ = self.clone("agent")
        archived, _, _ = self.clone("archived")
        def ids(call, **params):
            return {r["id"] for r in call("thread/list", {"limit": 100, "modelProviders": [], **params})["data"]}
        with app_server(self.root, self.env) as call:
            visible = ids(call)
            self.assertIn(normal, visible)
            self.assertNotIn(agent, visible)
            self.assertNotIn(archived, visible)
            self.assertIn(agent, ids(call, sourceKinds=["exec"]))
            self.assertIn(archived, ids(call, archived=True))
            thread = call("thread/resume", {"threadId": agent})["thread"]
            self.assertEqual(thread["id"], agent)
            self.assertIn("SYNTHETIC-ANSWER-MARKER", json.dumps(thread))
            self.assertNotIn(agent, ids(call))
            self.assertIn(agent, ids(call, sourceKinds=["exec"]))
            call("thread/read", {"threadId": archived, "includeTurns": True})
            self.assertIn(archived, ids(call, archived=True))
        offline_continuation(self, self.env, self.project, agent)
        self.assertIn("LOCAL-CONTINUATION-OK", agent_path.read_text())
        with app_server(self.root, self.env) as call:
            self.assertNotIn(agent, ids(call))
            self.assertIn(agent, ids(call, sourceKinds=["exec"]))
            self.assertIn(archived, ids(call, archived=True))
            loaded = call("thread/resume", {"threadId": agent})["thread"]
            self.assertIn("LOCAL-CONTINUATION-OK", json.dumps(loaded))
        self.assertEqual(self.source.read_bytes(), self.before)
