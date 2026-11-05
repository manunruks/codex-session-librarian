"""Pinned, synthetic, model-free comparison. Run only after technical gate review."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import time
import zipfile
from fixtures import CASES, native, observe
from sandbox import run

BASE = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def identity(path, provider):
    for line in path.read_text().splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if provider == "claude" and row.get("sessionId"):
            return row["sessionId"]
        if provider == "codex" and row.get("type") == "session_meta":
            return row["payload"]["id"]
    raise ValueError("Output has no native session identity")


def paths(lab, provider):
    directory = lab / "home" / (".codex/sessions" if provider == "codex" else ".claude/projects")
    return set(directory.rglob("*.jsonl")) if directory.exists() else set()


def transfer(tool, source, sid, provider, target):
    if tool == "csl":
        return ["python3", "codex_sessions.py", "convert", source, "--provider", provider,
            "--to", target, "--cwd", "/mnt/project"]
    if tool == "session-porter":
        return ["node", "dist/index.js", "transfer", sid, "--from", provider, "--to", target, "--mode", "raw"]
    if tool == "sessionport":
        return ["node", "dist/cli/index.js", "import", provider, sid, target, "--mode", "as-is"]
    return ["python3", "claude_sessions.py", "teleport", source, "--to", target,
        "--cwd", "/mnt/project", *(["--codex-project", "none"] if target == "codex" else []), "--apply"]


def compare(expected, observed):
    losses = []
    cursor = 0
    for role, text in expected["texts"]:
        match = next((n for n in range(cursor, len(observed["texts"]))
            if observed["texts"][n][0] == role and text in observed["texts"][n][1]), None)
        if match is None:
            losses.append("text_role_or_order:" + text[:70])
        else:
            cursor = match + 1
    for family in ("calls", "results"):
        if len(observed[family]) < len(expected[family]):
            losses.append(family + ":missing_native_items")
    for n, call in enumerate(expected["calls"]):
        if n >= len(observed["calls"]):
            continue
        original = call["args"]
        target = observed["calls"][n]
        normalized_original = {"command" if k == "cmd" else k: v for k, v in original.items()}
        normalized_target = {"command" if k == "cmd" else k: v for k, v in target["args"].items()} if isinstance(target["args"], dict) else None
        if normalized_target is None or any(normalized_target.get(k) != v for k, v in normalized_original.items()):
            losses.append("call_arguments:" + str(n))
        normalize_name = lambda name: "shell.exec" if name in ("Bash", "exec_command") else name
        if normalize_name(call["name"]) != normalize_name(target["name"]):
            losses.append("tool_name:" + str(n))
        original_results = [r for r in expected["results"] if r["id"] == call["id"]]
        target_results = [r for r in observed["results"] if r["id"] == target["id"]]
        for result in original_results:
            if not any(item["output"] == result["output"] or (result["error"] is True and
                    item["output"] == "[Tool error]\n" + result["output"]) for item in target_results):
                losses.append("tool_result_or_correlation:" + str(n))
    if len(observed["images"]) < len(expected["images"]):
        losses.append("embedded_image_missing")
    if expected["unknown"] and expected["unknown"] != observed["unknown"]:
        losses.append("unknown_content:" + ",".join(expected["unknown"]))
    return losses


def main():
    global BASE
    parser = argparse.ArgumentParser()
    parser.add_argument("--gate-reviewed", action="store_true", required=True)
    parser.add_argument("--tool", action="append", choices=["csl", "session-porter", "sessionport", "claude-session-teleporter"])
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--media-venv", type=Path)
    parser.add_argument("--case", action="append", choices=CASES)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    if args.workspace:
        BASE = args.workspace.resolve()
    out = args.output_dir.resolve() if args.output_dir else BASE / "benchmark/results"
    out.mkdir(parents=True, exist_ok=True)
    results = []
    tools = args.tool or ["csl", "session-porter", "sessionport", "claude-session-teleporter"]
    for tool in tools:
        lab = BASE / "benchmark/runtime" / tool
        for case in args.case or CASES:
            for provider in ("claude", "codex"):
                target = "codex" if provider == "claude" else "claude"
                case_id = tool + "__" + case + "__" + provider + "-" + target
                if case == "tampered-package":
                    case_id = tool + "__" + case + "__" + provider
                output = out / case_id
                output.mkdir(exist_ok=True)
                # Only this harness's synthetic home is cleared between cases.
                home = lab / "home"
                if home.exists():
                    shutil.rmtree(home)
                home.mkdir()
                (lab / "project").mkdir(exist_ok=True)
                sid, raw = native(case, provider)
                if provider == "claude":
                    source = home / ".claude/projects/-mnt-project" / (sid + ".jsonl")
                else:
                    source = home / ".codex/sessions/2026/11/05" / ("rollout-2026-11-05T00-00-00-" + sid + ".jsonl")
                    index = home / ".codex/session_index.jsonl"
                    index.parent.mkdir(parents=True, exist_ok=True)
                    index.write_text(json.dumps({"id": sid, "thread_name": "Synthetic " + case, "updated_at": "2026-11-05T00:00:00Z"}) + "\n")
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_text(raw)
                shutil.copyfile(source, output / "source.jsonl")
                expected = observe(source, provider)
                before = sha(source)
                if case == "tampered-package":
                    row = {"case_id": case_id, "tool": tool, "case": case,
                        "source_provider": provider, "target_provider": provider,
                        "layer": "structural_semantic", "fixture_sha256": before,
                        "source_unchanged": True, "fidelity": "unknown", "verdict": "not_applicable",
                        "reason": "No matching CLI JSONL package-receive operation under this benchmark; desktop packages are a different scope"}
                    if tool == "csl":
                        exported = run(lab, ["python3", "codex_sessions.py", "export",
                            "/mnt/" + str(source.relative_to(lab)), "--to", "/mnt/home/tampered.zip"])
                        assert exported.returncode == 0, exported.stderr
                        package = home / "tampered.zip"
                        with zipfile.ZipFile(package) as archive:
                            contents = {name: archive.read(name) for name in archive.namelist()}
                        member = next(name for name in contents if name.startswith("sessions/"))
                        contents[member] = contents[member].replace(b"FIRST-FACT-617", b"ALTER-FACT-618")
                        with zipfile.ZipFile(package, "w") as archive:
                            for name, raw in contents.items():
                                archive.writestr(name, raw)
                        existing = paths(lab, provider)
                        argv = ["python3", "codex_sessions.py", "import", "/mnt/home/tampered.zip", "--cwd", "/mnt/project"]
                        imported = run(lab, argv)
                        (output / "stdout.log").write_text(imported.stdout)
                        (output / "stderr.log").write_text(imported.stderr)
                        unchanged = sha(source) == before
                        no_install = paths(lab, provider) == existing
                        row.update(command=argv, exit=imported.returncode, source_unchanged=unchanged,
                            no_install=no_install, fidelity="rejected",
                            verdict="pass" if imported.returncode != 0 and no_install and unchanged else "fail",
                            reason="Altered package retains stale checksum; must reject before installing")
                    (output / "result.json").write_text(json.dumps(row, indent=2) + "\n")
                    results.append(row)
                    print(case_id, row["verdict"], flush=True)
                    continue
                existing = paths(lab, target)
                argv = transfer(tool, "/mnt/" + str(source.relative_to(lab)), sid, provider, target)
                start = time.monotonic()
                runtime = {}
                if tool == "csl" and args.media_venv:
                    (lab / "media").mkdir(exist_ok=True)
                    runtime = {"extra_env": {"CSL_MEDIA_PYTHON": "/mnt/media/bin/python", "CSL_MEDIA_SANDBOX": "required"},
                        "readonly_binds": [(args.media_venv.resolve(), "/mnt/media")]}
                result = run(lab, ["/usr/bin/time", "-f", "BENCH_RSS_KB=%M", *argv], timeout=60, **runtime)
                elapsed = time.monotonic() - start
                (output / "stdout.log").write_text(result.stdout)
                (output / "stderr.log").write_text(result.stderr)
                targets = sorted(paths(lab, target) - existing)
                rss = re.search(r"BENCH_RSS_KB=(\d+)", result.stderr)
                row = {"case_id": case_id, "tool": tool, "case": case, "source_provider": provider,
                    "target_provider": target, "layer": "structural_semantic", "command": argv,
                    "exit": result.returncode, "elapsed_seconds": round(elapsed, 6),
                    "peak_rss_kb": int(rss.group(1)) if rss else None,
                    "fixture_sha256": before, "source_unchanged": sha(source) == before,
                    "target_count": len(targets), "native_load": "not_tested", "model_continuation": "not_tested"}
                if result.returncode == 0 and len(targets) == 1:
                    artifact = output / "target.jsonl"
                    shutil.copyfile(targets[0], artifact)
                    observed = observe(artifact, target)
                    losses = compare(expected, observed)
                    row.update(observed=observed, losses=losses, fidelity="unknown" if losses else "documented_transform",
                        verdict="fail" if losses else "pass", fresh_identity=identity(artifact, target) != sid,
                        loss_disclosure="manual_review_required" if losses else "not_applicable")
                    row["image_bytes_equal"] = observed["images"] == expected["images"]
                    row["unmeasured"] = ["all timestamps", "all metadata", "references", "assistant phases", "pixel equivalence after image re-encoding"]
                    # Incomplete JSONL is adversarial even if a tolerant parser recovered a prefix.
                    if case == "truncated":
                        row["verdict"] = "manual_review"
                        row["reason"] = "Recovered valid prefix; inspect whether user was told about truncation"
                    if case == "branches":
                        row["verdict"] = "manual_review"
                        row["reason"] = "Branch selection/partial ancestor contract requires manual review; all rows are not a valid active-chain oracle"
                    row["identity_note"] = "Cross-provider namespaces may preserve UUID by design; difference recorded, not scored as corruption"
                    if not row["source_unchanged"]:
                        row["verdict"] = "fail"
                        row["reason"] = "Origin changed"
                    # A second generation is measured without using any tool's IR as oracle.
                    existing_return = paths(lab, provider)
                    return_argv = transfer(tool, "/mnt/" + str(targets[0].relative_to(lab)),
                        identity(artifact, target), target, provider)
                    second = run(lab, return_argv, timeout=60, **runtime)
                    (output / "roundtrip-stdout.log").write_text(second.stdout)
                    (output / "roundtrip-stderr.log").write_text(second.stderr)
                    return_targets = sorted(paths(lab, provider) - existing_return)
                    rt = {"command": return_argv, "exit": second.returncode, "target_count": len(return_targets)}
                    if second.returncode == 0 and len(return_targets) == 1:
                        returned = output / "roundtrip.jsonl"
                        shutil.copyfile(return_targets[0], returned)
                        returned_facts = observe(returned, provider)
                        rt["losses"] = compare(expected, returned_facts)
                        if provider == "claude":
                            for original_result in expected["results"]:
                                if not any(item["output"] == original_result["output"] and item["error"] == original_result["error"] for item in returned_facts["results"]):
                                    rt["losses"].append("roundtrip_tool_error_flag_or_result")
                        rt["fresh_identity"] = identity(returned, provider) != sid
                        rt["verdict"] = "fail" if rt["losses"] or not rt["fresh_identity"] else "pass"
                        if case in ("branches", "truncated"):
                            rt["verdict"] = "manual_review"
                    else:
                        rt["verdict"] = "blocked"
                    row["roundtrip"] = rt
                    row["source_unchanged_after_roundtrip"] = sha(source) == before
                    if not row["source_unchanged_after_roundtrip"]:
                        row["verdict"] = "fail"
                        row["reason"] = "Roundtrip modified original source"
                elif result.returncode != 0:
                    unsupported = bool(re.search(r"unsupported|not supported|incompatible|ambiguous|multiple.*lea|unknown.*block", result.stderr + result.stdout, re.I))
                    row.update(fidelity="rejected", verdict="manual_review" if unsupported else "blocked",
                        reason="unsupported/rejection wording observed; verify contract manually" if unsupported else "command failed; inspect log before attribution")
                else:
                    row.update(fidelity="unknown", verdict="blocked", reason="success without exactly one native target")
                (output / "result.json").write_text(json.dumps(row, indent=2) + "\n")
                results.append(row)
                print(case_id, row["verdict"], flush=True)
    (out / "results.json").write_text(json.dumps(results, indent=2) + "\n")


if __name__ == "__main__":
    main()
