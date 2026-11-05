"""Load exact generated transcripts in real CLIs against a rejecting localhost server.

No canonical parser/rewriter from any compared project is used. No model generation.
"""
import concurrent.futures
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import threading
import uuid

from run import identity


def probe(directory, row):
    provider = row["target_provider"]
    source = directory / "target.jsonl"
    sid = identity(source, provider)
    captures = []
    expected = ["FIRST-FACT-617"]
    if row["case"] in ("tool-only", "tool-errors"):
        expected += ["ARGUMENT-331", "TOOL-ONLY-FACT-947"]
    if row["case"] == "tool-errors":
        expected += ["ARGUMENT-ERROR-332", "ERROR-EACCES-722"]
    if provider == "codex":
        from native_rpc import probe as read_native
        return read_native(source, sid, row["case_id"], expected)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            size = int(self.headers.get("Content-Length", "0"))
            if 0 < size <= 8 * 1024 * 1024:
                data = json.loads(self.rfile.read(size))
                items = data.get("input" if provider == "codex" else "messages")
                if isinstance(items, list):
                    text = json.dumps(items)
                    captures.append({"request_path": self.path, "item_count": len(items),
                        "missing_markers": [m for m in expected if m not in text],
                        "native_tool_call_present": '"tool_use"' in text or '"function_call"' in text,
                        "native_tool_result_present": '"tool_result"' in text or '"function_call_output"' in text,
                        "image_present": '"image"' in text or '"input_image"' in text})
            body = json.dumps({"type": "error", "error": {"type": "invalid_request_error",
                "message": "Synthetic benchmark stops before model generation"}}).encode()
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    with tempfile.TemporaryDirectory(prefix="csl-competitor-native-") as tmp:
        root = Path(tmp)
        project = root / "project"
        project.mkdir()
        home = root / ("codex" if provider == "codex" else "claude")
        if provider == "codex":
            destination = home / "sessions/2026/11/05" / ("rollout-2026-11-05T00-00-00-" + sid + ".jsonl")
        else:
            slug = "".join(c if c.isascii() and c.isalnum() else "-" for c in str(project))
            destination = home / "projects" / slug / (sid + ".jsonl")
        destination.parent.mkdir(parents=True)
        shutil.copyfile(source, destination)  # Exact bytes, including IDs and metadata.
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = "http://127.0.0.1:" + str(server.server_port)
        env = {"PATH": os.environ["PATH"], "HOME": str(root), "LANG": "C.UTF-8",
            "CODEX_HOME": str(root / "codex"), "CLAUDE_CONFIG_DIR": str(root / "claude"),
            "OPENAI_API_KEY": "synthetic-localhost-no-real-key", "OPENAI_BASE_URL": base + "/v1",
            "ANTHROPIC_API_KEY": "synthetic-localhost-no-real-key", "ANTHROPIC_BASE_URL": base,
            "DISABLE_TELEMETRY": "1", "DISABLE_ERROR_REPORTING": "1", "DISABLE_AUTOUPDATER": "1",
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1", "NO_PROXY": "localhost,127.0.0.1"}
        argv = ["claude", "--bare", "--strict-mcp-config", "--setting-sources", "", "--tools", "",
            "--model", "claude-haiku-5-5", "--resume", sid, "--max-turns", "1", "--print",
            "--output-format", "json", "Do not use tools. Reply ACK only."]
        prompt = None
        process = None
        timed_out = False
        try:
            process = subprocess.Popen(argv, env=env, cwd=project, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
            try:
                stdout, stderr = process.communicate(prompt, timeout=35)
            except subprocess.TimeoutExpired:
                timed_out = True
                os.killpg(process.pid, signal.SIGTERM)
                stdout, stderr = process.communicate(timeout=5)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
        result = {"case_id": row["case_id"], "layer": "native_load", "exact_transcript_bytes": True,
            "cwd_override": "fresh project; native transcript metadata unchanged",
            "capture": captures[-1] if captures else None, "timed_out": timed_out,
            "exit": process.returncode, "generation": "not_performed", "model_continuation": "not_tested",
            "stdout_tail": stdout[-1500:], "stderr_tail": stderr[-1500:]}
        result["verdict"] = "pass" if captures and not captures[-1]["missing_markers"] else "fail"
        if row["case"] in ("tool-only", "tool-errors") and captures:
            if not captures[-1]["native_tool_call_present"] or not captures[-1]["native_tool_result_present"]:
                result["verdict"] = "fail"
        if row["case"] == "image" and captures and not captures[-1]["image_present"]:
            result["verdict"] = "fail"
        return result


if __name__ == "__main__":
    if os.environ.get("CSL_BENCH_NETWORK_DISABLED") != "1":
        raise SystemExit("Use native_isolated.py to enforce the model-free network boundary")
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, required=True)
    args = parser.parse_args()
    rows = json.loads((args.results / "results.json").read_text())
    selected = [row for row in rows if row["case"] in ("short", "tool-only", "tool-errors", "image")
        and (args.results / row["case_id"] / "target.jsonl").exists()]
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(probe, args.results / row["case_id"], row) for row in selected]
        for future in concurrent.futures.as_completed(futures):
            item = future.result()
            results.append(item)
            (args.results / item["case_id"] / "native-result.json").write_text(json.dumps(item, indent=2) + "\n")
            print(item["case_id"], item["verdict"], flush=True)
    (args.results / "native-results.json").write_text(json.dumps(results, indent=2) + "\n")
