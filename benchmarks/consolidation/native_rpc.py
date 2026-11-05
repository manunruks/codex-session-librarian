"""Codex file loading via read-only app-server methods, never turn/start."""
import json
import os
from pathlib import Path
import queue
import signal
import subprocess
import tempfile
import threading


def probe(source, sid, case_id, expected):
    with tempfile.TemporaryDirectory(prefix="csl-native-read-") as tmp:
        root = Path(tmp)
        home = root / "codex"
        target = home / "sessions/2026/11/05" / ("rollout-2026-11-05T00-00-00-" + sid + ".jsonl")
        target.parent.mkdir(parents=True)
        target.write_bytes(source.read_bytes())
        env = {"PATH": os.environ["PATH"], "HOME": str(root), "CODEX_HOME": str(home), "LANG": "C.UTF-8"}
        replies = queue.Queue()
        process = subprocess.Popen(["codex", "app-server"], cwd=root, env=env, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, start_new_session=True)
        def reader():
            for line in process.stdout:
                try:
                    replies.put(json.loads(line))
                except ValueError:
                    pass
        thread = threading.Thread(target=reader, daemon=True)
        thread.start()
        def send(row):
            process.stdin.write(json.dumps(row) + "\n")
            process.stdin.flush()
        def call(number, method, params):
            assert method in ("initialize", "thread/read")
            send({"id": number, "method": method, "params": params})
            while True:
                reply = replies.get(timeout=15)
                if reply.get("id") == number:
                    return reply
        try:
            initialized = call(1, "initialize", {"clientInfo": {"name": "neutral_benchmark", "version": "1"}})
            send({"method": "initialized", "params": {}})
            reply = call(2, "thread/read", {"threadId": sid, "includeTurns": True})
            payload = json.dumps(reply.get("result", {}))
            missing = [marker for marker in expected if marker not in payload]
            result = {"case_id": case_id, "layer": "native_load", "method": "Codex app-server thread/read",
                "exact_transcript_bytes": True, "network": "disabled by outer bubblewrap namespace",
                "accepted": "result" in reply, "missing_visible_markers": missing,
                "error": reply.get("error"), "generation": "not_performed", "model_continuation": "not_tested",
                "verdict": "pass" if "result" in reply else "fail",
                "scope": "CLI file acceptance and visible history; not model request reconstruction or recall"}
            return result
        finally:
            process.stdin.close()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=3)
            process.stdout.close()
            thread.join(timeout=2)
