"""Explicitly paid synthetic continuation checks for frozen benchmark outputs.

Credentials are supplied by the caller's private helper/environment, never loaded
from the repository, copied from normal user homes or written into evidence.
"""
import argparse
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

from fixtures import native
from run import identity

p = argparse.ArgumentParser()
p.add_argument("--workspace", type=Path, required=True)
p.add_argument("--csl-repo", type=Path, required=True)
p.add_argument("--allow-paid", action="store_true", required=True)
p.add_argument("--codex-home", type=Path)
p.add_argument("--targets", choices=["codex", "claude", "both"], default="both")
p.add_argument("--codex-model", default="gpt-6.1-sol")
p.add_argument("--claude-model", default="claude-haiku-5-5")
p.add_argument("--claude-budget-usd", type=Decimal, default=Decimal("0.10"))
p.add_argument("--max-calls", type=int, default=16)
p.add_argument("--out", type=Path, required=True)
a = p.parse_args()
if not 1 <= a.max_calls <= 24 or not Decimal("0") < a.claude_budget_usd <= Decimal("0.10"):
    raise SystemExit("Use 1–24 attempts and a positive per-call Claude threshold <= USD 0.10")
if a.targets != "claude" and (not a.codex_home or a.codex_home.expanduser().resolve() == (Path.home() / ".codex").resolve()):
    raise SystemExit("Use a separately authenticated Codex test home; normal ~/.codex is refused")
sys.path.insert(0, str(a.csl_repo.resolve()))
import csl_live

a.out.mkdir(mode=0o700, parents=True)  # New output only, no automatic retries/resume.
rows = json.loads((a.workspace / "benchmark/results/results.json").read_text())
env = {key: os.environ[key] for key in ("PATH", "ANTHROPIC_API_KEY", "ANTHROPIC_CUSTOM_HEADERS") if key in os.environ}
private_values = [env.get("ANTHROPIC_API_KEY", ""), env.get("ANTHROPIC_CUSTOM_HEADERS", "")]
private_values += [line.partition(":")[2].strip() for line in env.get("ANTHROPIC_CUSTOM_HEADERS", "").splitlines()]
report = {"calls": [], "synthetic_only": True, "paid_authorization": "explicit --allow-paid from operator",
    "limitations": "One trial/case; CLI cost is an estimate, not invoice; Codex consumes the authenticated plan"}


def save():
    text = json.dumps(report, indent=2)
    for value in filter(None, private_values):
        text = text.replace(value, "[REDACTED]")
    path = a.out / "report.json"
    with path.open("w") as handle:
        path.chmod(0o600)
        handle.write(text + "\n")


def count_tools(path, provider):
    result = 0
    for line in path.read_text().splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if provider == "codex":
            result += row.get("type") == "response_item" and row.get("payload", {}).get("type") in ("function_call", "custom_tool_call")
        else:
            blocks = row.get("message", {}).get("content", [])
            if isinstance(blocks, list):
                result += sum(isinstance(block, dict) and block.get("type") == "tool_use" for block in blocks)
    return result


for row in rows:
    provider = row.get("target_provider")
    if row["case"] not in ("decisions", "tool-errors") or a.targets not in ("both", provider):
        continue
    if len(report["calls"]) >= a.max_calls:
        break
    directory = a.workspace / "benchmark/results" / row["case_id"]
    source = directory / "target.jsonl"
    if not source.exists():
        continue
    _, generated = native(row["case"], row["source_provider"])
    if hashlib.sha256(generated.encode()).hexdigest() != row["fixture_sha256"]:
        raise SystemExit("Fixture differs from this synthetic corpus: " + row["case_id"])
    if provider == "claude" and not env.get("ANTHROPIC_API_KEY"):
        report["calls"].append({"case_id": row["case_id"], "status": "blocked", "reason": "No authorized API key in memory"})
        save()
        continue
    original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    sid = identity(source, provider)
    with tempfile.TemporaryDirectory(prefix="csl-benchmark-live-") as tmp:
        root = Path(tmp)
        project = root / "project"
        project.mkdir()
        home = a.codex_home.expanduser().resolve() if provider == "codex" else root / "claude"
        if provider == "codex":
            destination = home / "sessions/2026/11/05" / ("rollout-2026-11-05T00-00-00-" + sid + ".jsonl")
        else:
            slug = "".join(c if c.isascii() and c.isalnum() else "-" for c in str(project))
            destination = home / "projects" / slug / (sid + ".jsonl")
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if destination.exists():
            report["calls"].append({"case_id": row["case_id"], "status": "blocked", "reason": "Existing destination, no overwrite"})
            save()
            continue
        with destination.open("xb") as handle:
            destination.chmod(0o600)
            handle.write(source.read_bytes())
        before = count_tools(destination, provider)
        if row["case"] == "decisions":
            prompt = "Using only the imported history, return JSON with keys current_database and previous_database, containing the exact database decision marker codes. The latest explicit decision supersedes earlier choices. Do not run tools. Use null if absent."
            expected = {"current_database": "DATABASE-CURRENT-SQLITE", "previous_database": "DATABASE-OLD-POSTGRES"}
        else:
            prompt = "Using only the imported history, return JSON with keys first_fact (remembered fact code), tool_fact (the exact value returned by the first completed historical lookup) and failure_marker (the exact error marker from the second lookup). Do not run tools or infer missing values. Use null if absent."
            expected = {"first_fact": "FIRST-FACT-617", "tool_fact": "TOOL-ONLY-FACT-947", "failure_marker": "ERROR-EACCES-722"}
        model = a.codex_model if provider == "codex" else a.claude_model
        result = csl_live.live_call(provider, sid, home, project, env, model, a.claude_budget_usd, prompt)
        try:
            missing = csl_live.checks(result["answer"], expected)
        except ValueError:
            missing = list(expected)
        new_tools = count_tools(destination, provider) - before
        unchanged = hashlib.sha256(source.read_bytes()).hexdigest() == original_hash
        passed = not result["provider_failure"] and not missing and not result["tool_calls"] and not new_tools and unchanged
        report["calls"].append({"case_id": row["case_id"], "provider": provider, "model": model,
            "status": "pass" if passed else "fail", "missing_fields": missing, "source_unchanged": unchanged,
            "new_historical_tool_calls": new_tools, **result})
        save()
        print(row["case_id"], "pass" if passed else "fail", flush=True)
save()
