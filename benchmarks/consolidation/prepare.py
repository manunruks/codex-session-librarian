"""Prepare fixed public sources; does not execute third-party installers."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

PINS = {
    "session-porter": ("liwala/session-porter", "c973b70d3384e7676375f1186187c4549f172279"),
    "sessionport": ("azizmass/sessionport", "0c8149a14d47ad6ac1170b5976aa624d93bdb537"),
    "claude-session-teleporter": ("aviadr1/claude-session-teleporter", "3cd341d49c492217d15cc022461a4cb1d0b9da7c"),
}
p = argparse.ArgumentParser()
p.add_argument("--workspace", type=Path, required=True)
p.add_argument("--csl-repo", type=Path, required=True)
a = p.parse_args()
workspace = a.workspace.resolve()
(workspace / "competitors").mkdir(parents=True, exist_ok=True)
scripts = workspace / "benchmark"
scripts.mkdir(exist_ok=True)
for helper in Path(__file__).resolve().parent.glob("*.py"):
    if helper.resolve() != (scripts / helper.name).resolve():
        shutil.copyfile(helper, scripts / helper.name)
with tempfile.TemporaryDirectory(prefix="csl-public-clone-") as home:
    env = {"PATH": os.environ["PATH"], "HOME": home, "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0"}
    for name, (repo, revision) in PINS.items():
        target = workspace / "competitors" / name
        if not target.exists():
            subprocess.run(["git", "-c", "credential.helper=", "clone", "--no-checkout",
                "https://github.com/" + repo + ".git", str(target)], env=env, check=True)
            subprocess.run(["git", "checkout", "--detach", revision], cwd=target, env=env, check=True)
        observed = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=target, env=env, text=True).strip()
        if observed != revision:
            raise SystemExit("Existing competitor checkout differs from fixed revision: " + name)
    source = a.csl_repo.resolve()
    destination = workspace / "benchmark/runtime/csl/src"
    destination.mkdir(parents=True)
    # Only Git-tracked product files, never local histories, runtime or credentials.
    files = subprocess.check_output(["git", "ls-files", "-z"], cwd=source, env=env).decode().split("\0")
    for name in filter(None, files):
        src = source / name
        if src.is_symlink():
            raise SystemExit("Review tracked symlink before preparing benchmark: " + name)
        dst = destination / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
    (workspace / "pins.json").write_text(json.dumps({name: {"repo": repo, "sha": revision}
        for name, (repo, revision) in PINS.items()}, indent=2) + "\n")
print("Prepared fixed sources; review and install competitors separately before running the benchmark.")
