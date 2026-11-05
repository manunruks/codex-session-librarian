"""Bounded local-library timing with fixed synthetic volume; no SLA inference."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import uuid

p = argparse.ArgumentParser()
p.add_argument("--repo", type=Path, required=True)
p.add_argument("--out", type=Path, required=True)
a = p.parse_args()
measurements = []
with tempfile.TemporaryDirectory(prefix="csl-library-perf-") as tmp:
    root = Path(tmp)
    for count, turns in [(10, 40), (500, 40), (1, 20000)]:
        home = root / (str(count) + "-" + str(turns))
        sessions = home / ".codex/sessions/2026/11/05"
        sessions.mkdir(parents=True)
        byte_count = 0
        for n in range(count):
            sid = str(uuid.uuid5(uuid.NAMESPACE_URL, "csl-perf:" + str(n)))
            rows = [{"type": "session_meta", "payload": {"id": sid, "session_id": sid,
                "cwd": str(root), "source": "cli", "timestamp": "2026-11-05T00:00:00Z"}}]
            for turn in range(turns):
                rows.append({"type": "response_item", "payload": {"type": "message",
                    "role": "user" if turn % 2 == 0 else "assistant", "content": [{
                        "type": "input_text" if turn % 2 == 0 else "output_text",
                        "text": "EVIDENCE-NEEDLE-617 synthetic design decision %d %d. " % (n, turn) + "Local continuity context. " * 8}]}})
            raw = "".join(json.dumps(r) + "\n" for r in rows).encode()
            byte_count += len(raw)
            (sessions / ("rollout-2026-11-05T00-00-00-" + sid + ".jsonl")).write_bytes(raw)
        env = {"PATH": os.environ["PATH"], "HOME": str(home), "CODEX_HOME": str(home / ".codex"),
            "CLAUDE_CONFIG_DIR": str(home / ".claude"), "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1"}
        corpus_hash_before = hashlib.sha256(b"".join(p.read_bytes() for p in sorted(sessions.glob("*.jsonl")))).hexdigest()
        for operation, args in [("index-cold", ["index", "--prune"]), ("index-warm", ["index", "--prune"]),
                ("search", ["search", "EVIDENCE-NEEDLE-617", "--limit", "5"]),
                ("recall", ["recall", "EVIDENCE-NEEDLE-617", "--limit", "5"])]:
            repeats = 1 if operation == "index-cold" else 3
            for repeat in range(repeats):
                start = time.monotonic()
                result = subprocess.run(["/usr/bin/time", "-f", "BENCH_RSS_KB=%M", "python3",
                    str(a.repo.resolve() / "codex_sessions.py"), *args], env=env, cwd=root,
                    capture_output=True, text=True, timeout=120)
                rss = re.search(r"BENCH_RSS_KB=(\d+)", result.stderr)
                measurements.append({"sessions": count, "messages_per_session": turns, "bytes": byte_count,
                    "operation": operation, "repeat": repeat, "exit": result.returncode,
                    "seconds": round(time.monotonic() - start, 6),
                    "peak_rss_kb": int(rss.group(1)) if rss else None,
                    "needle_visible": "EVIDENCE-NEEDLE-617" in result.stdout if operation in ("search", "recall") else None,
                    "stdout_tail": result.stdout[-1200:], "stderr": result.stderr})
        after = hashlib.sha256(b"".join(p.read_bytes() for p in sorted(sessions.glob("*.jsonl")))).hexdigest()
        assert after == corpus_hash_before, "Measured library operation changed synthetic originals"
a.out.write_text(json.dumps({"measurements": measurements, "source_unchanged": True,
    "conditions": "OS page cache not flushed; cold means empty CSL DB only; warm repeat=3"}, indent=2) + "\n")
print(json.dumps({"rows": len(measurements), "failures": sum(r["exit"] != 0 for r in measurements)}))
