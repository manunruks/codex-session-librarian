"""Enforce no external network/private home access around native CLI checks."""
import argparse
from pathlib import Path
from sandbox import run

p = argparse.ArgumentParser()
p.add_argument("--workspace", type=Path, required=True)
p.add_argument("--codex-bin", type=Path, required=True, help="Installed Linux Codex ELF, not npm JS wrapper")
p.add_argument("--claude-bin", type=Path, required=True, help="Installed Linux Claude ELF")
a = p.parse_args()
root = a.workspace.resolve()
bindir = root / "cli-bin"
bindir.mkdir(exist_ok=True)
bindings = []
for name, path in (("codex", a.codex_bin.resolve()), ("claude", a.claude_bin.resolve())):
    with path.open("rb") as stream:
        if stream.read(4) != b"\x7fELF":
            raise SystemExit("Provide the native Linux executable for " + name)
    (bindir / name).touch(exist_ok=True)
    bindings.append((path, "/mnt/cli-bin/" + name))
result = run(root, ["python3", "/mnt/benchmark/native.py", "--results", "/mnt/benchmark/results"],
    cwd="/mnt", extra_env={"PATH": "/mnt/cli-bin:/usr/bin:/bin", "CSL_BENCH_NETWORK_DISABLED": "1"},
    readonly_binds=bindings, timeout=180)
(root / "benchmark/native-final-run.log").write_text(result.stdout + result.stderr)
print(result.stdout)
raise SystemExit(result.returncode)
