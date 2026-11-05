"""Explicit review rules for the frozen synthetic corpus; not a ranking algorithm."""
import argparse
import json
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("--results", type=Path, required=True)
a = p.parse_args()
rows = json.loads((a.results / "results.json").read_text())
for row in rows:
    folder = a.results / row["case_id"]
    stdout = (folder / "stdout.log").read_text() if (folder / "stdout.log").exists() else ""
    stderr = (folder / "stderr.log").read_text() if (folder / "stderr.log").exists() else ""
    reviewed = {"comparison_status": row["verdict"], "fidelity": row.get("fidelity", "unknown"),
        "scope": "Only the observer's explicit text/tool/image checks; unmeasured fields remain unproved"}
    case = row["case"]
    if case == "branches":
        reviewed.update(comparison_status="not_applicable", fidelity="rejected" if row.get("exit", 0) else "unknown",
            reason="No common explicit-leaf selection requested: compare policy, not preservation of both alternative branches")
    elif case == "unsupported":
        reviewed.update(comparison_status="not_applicable", fidelity="rejected" if row.get("exit", 0) else "unknown",
            reason="Audio/foreign content is outside this portable native profile; record reject/placeholder/omission without scoring universal support")
    elif case == "truncated":
        if row.get("exit", 0) and ("Invalid JSONL" in stderr or "invalid JSON" in stderr or "JSON" in stderr):
            reviewed.update(comparison_status="pass", fidelity="rejected", reason="Malformed-tail conversion rejected diagnostically")
        else:
            reviewed.update(comparison_status="manual_review", fidelity="unknown",
                reason="Valid prefix recovered; no complete continuity claim or winner assigned for the truncated tail")
    elif case == "image" and row["tool"] != "csl":
        target = (folder / "target.jsonl").read_text() if (folder / "target.jsonl").exists() else ""
        placeholder = "Imported image content unavailable" in target
        reviewed.update(comparison_status="not_applicable", fidelity="acknowledged_loss" if placeholder else "unknown",
            reason="Native image absent in exercised route; not an equivalent implemented media operation. " +
                ("Explicit placeholder observed." if placeholder else "Media support contract not established; omission remains visible in raw evidence."))
    elif case == "tampered-package":
        reviewed["reason"] = row.get("reason")
    elif row.get("exit", 0):
        reviewed.update(comparison_status="blocked", reason="Inspect concrete runtime/installation cause, not an inferred product weakness")
    if not row.get("source_unchanged", True):
        reviewed.update(comparison_status="fail", reason="Original source changed")
    row["reviewed"] = reviewed
(a.results / "adjudicated-results.json").write_text(json.dumps(rows, indent=2) + "\n")
print("Reviewed", len(rows), "rows; no aggregate winner or numerical score")
