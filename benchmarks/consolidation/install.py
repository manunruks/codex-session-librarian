"""Install fixed competitor sources in disposable, credential-free bwrap labs."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import time
from sandbox import run

p = argparse.ArgumentParser()
p.add_argument("tool", choices=["session-porter", "sessionport", "claude-session-teleporter"])
p.add_argument("--workspace", type=Path)
a = p.parse_args()
base = a.workspace.resolve() if a.workspace else Path(__file__).resolve().parents[1]
lab = base / "benchmark/runtime" / a.tool
lab.mkdir(parents=True, exist_ok=True)
if (lab / "src").exists():
    raise SystemExit("Existing runtime; inspect its installation result before reusing")
shutil.copytree(base / "competitors" / a.tool, lab / "src",
    ignore=shutil.ignore_patterns(".git", "node_modules", "__pycache__"))
steps = []
if a.tool != "claude-session-teleporter":
    commands = [(["npm", "ci", "--ignore-scripts", "--cache", "/mnt/npm-cache", "--no-audit", "--no-fund"], True),
        (["npm", "run", "build"], False)]
else:
    commands = [(["python3", "claude_sessions.py", "--version"], False)]
for index, (argv, network) in enumerate(commands):
    start = time.monotonic()
    result = run(lab, argv, network=network, timeout=180)
    (lab / ("install-" + str(index) + ".log")).write_text(result.stdout + result.stderr)
    steps.append({"argv": argv, "network": network, "exit": result.returncode,
        "seconds": round(time.monotonic() - start, 3)})
    if result.returncode:
        break
result = {"tool": a.tool, "steps": steps, "credentials_available": False,
    "lifecycle_scripts": "disabled for dependency install; explicit build sandboxed offline"}
(lab / "installation.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result))
