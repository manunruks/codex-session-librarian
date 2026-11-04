"""Batch migration: loop over existing share/receive, with a small migration index."""

import json
from pathlib import Path
import re
import sys
import tempfile
from types import SimpleNamespace
import uuid
import zipfile

from csl_codex_rpc import CodexRPC
import csl_sharing as sharing
from csl_transfer import TransferError


TAG = re.compile(r"csl-migration-[0-9a-f]{12}")
ASSET = "migration.json"


def state_path(csl, tag):
    if not isinstance(tag, str) or not TAG.fullmatch(tag):
        raise TransferError("Use the csl-migration-xxxxxxxxxxxx ID printed by upload")
    return csl.DEFAULT_CODEX_HOME / "csl-migrations" / f"{tag}.json"


def visible_sessions(csl):
    sessions, seen_ids, seen_cursors = [], set(), set()
    cursor = None
    with CodexRPC(csl.DEFAULT_CODEX_HOME) as rpc:
        while True:
            # Legacy created_at cursors lose timestamp ties; recency includes the UUID tie-breaker.
            page = rpc.call("thread/list", {"limit": 100, "cursor": cursor, "archived": False,
                "modelProviders": [], "sourceKinds": ["cli", "vscode"], "sortKey": "recency_at"})
            for thread in page["data"]:
                sid = str(uuid.UUID(thread["id"]))
                path = Path(thread.get("path") or "").resolve()
                if not path.is_file() or not path.is_relative_to(csl.DEFAULT_SESSIONS_DIR.resolve()):
                    raise TransferError(f"Session {sid} has no local active history; migration stopped")
                if sid not in seen_ids:
                    seen_ids.add(sid)
                    sessions.append({"id": sid, "path": str(path)})
            cursor = page.get("nextCursor")
            if not cursor:
                return sessions
            if cursor in seen_cursors:
                raise TransferError("Codex returned a repeated migration listing cursor")
            seen_cursors.add(cursor)


def upload(args, csl):
    repo = sharing.configured_repo(csl, write=True)
    tag = args.resume or f"csl-migration-{uuid.uuid4().hex[:12]}"
    local = state_path(csl, tag)
    if args.resume:
        state = sharing.read_json(local)
        if not state or state.get("repo") != repo:
            raise TransferError("No upload state for this migration in the configured repository")
        if args.raw != state["raw"]:
            raise TransferError("Resume with the original --raw setting")
    else:
        entries = visible_sessions(csl)
        if not entries:
            raise TransferError("No interactive Codex sessions to migrate")
        state = {"id": tag, "repo": repo, "raw": args.raw, "complete": False, "sessions": entries}
    recovery = bool(getattr(args, "repair_legacy_compaction", False) or state.get("repair_legacy_compaction"))
    if recovery and args.raw:
        raise TransferError("Legacy compaction recovery requires portable mode; omit --raw")
    if recovery:
        state["repair_legacy_compaction"] = True
    print(f"migration: {tag}; {len(state['sessions'])} sessions -> {repo}")
    if args.dry_run:
        for entry in state["sessions"]:
            print(entry["id"])
        return tag
    sharing.save_json(local, state)
    for index, entry in enumerate(state["sessions"], 1):
        if entry.get("share_id"):
            continue
        source = Path(entry["path"])
        digest = sharing.file_sha256(source)
        print(f"[{index}/{len(state['sessions'])}] {entry['id']}", flush=True)
        try:
            entry["share_id"] = sharing.share(SimpleNamespace(sessions=[str(source)], title=None,
                raw=args.raw, db=args.db, provider="codex", allow_secrets=args.allow_secrets,
                scrub_secrets=args.scrub_secrets, repair_legacy_compaction=recovery, migration_batch=True), csl)
            entry["sha256"] = digest
            sharing.save_json(local, state)
            if sharing.file_sha256(source) != digest:
                raise TransferError("A source changed during upload; keep sessions idle and start a new migration")
        except (TransferError, OSError):
            options = (" --raw" if args.raw else "") + (" --repair-legacy-compaction" if recovery else "")
            options += " --scrub-secrets" if args.scrub_secrets else " --allow-secrets" if args.allow_secrets else ""
            print(f"Resume completed uploads with: csl migrate upload --resume {tag}" + options, file=sys.stderr)
            raise
    if not state["complete"]:
        for entry in state["sessions"]:
            if sharing.file_sha256(Path(entry["path"])) != entry["sha256"]:
                raise TransferError("A previously uploaded source changed; start a new migration with idle sessions")
        manifest = {"format": "csl-migration", "version": 1, "id": tag, "repo": repo,
                    "sessions": [{"id": e["id"], "share_id": e["share_id"]} for e in state["sessions"]]}
        with tempfile.TemporaryDirectory(prefix="csl-migration-") as temp:
            asset = Path(temp) / ASSET
            sharing.save_json(asset, manifest)
            if asset.stat().st_size > 8 * 1024 * 1024:
                raise TransferError("Migration index exceeds 8 MiB")
            try:
                sharing.run_gh(["release", "create", tag, str(asset), "--repo", f"github.com/{repo}",
                    "--title", f"Codex migration ({len(state['sessions'])} sessions)",
                    "--notes", "CSL migration index. Restore with csl migrate download " + tag, "--latest=false"])
            except TransferError as publication_error:
                # A lost response can leave an immutable release successfully published.
                remote = Path(temp) / "published-migration.json"
                try:
                    sharing.run_gh(["release", "download", tag, "--repo", f"github.com/{repo}",
                        "--pattern", ASSET, "--output", str(remote)])
                except TransferError:
                    raise publication_error from None
                if remote.read_bytes() != asset.read_bytes():
                    raise TransferError("Existing migration index differs; refusing to overwrite it") from None
                print("Confirmed the identical migration index is already published.")
        state["complete"] = True
        sharing.save_json(local, state)
    print(f"Migration upload complete: {tag}")
    print(f"Conversations uploaded: {len(state['sessions'])}/{len(state['sessions'])}")
    print("On the NEW computer, open a terminal in the folder where Codex should work, then run:")
    print(f"csl team connect {repo}")
    print(f"csl migrate download {tag}")
    print("Restore uses the current folder; --cwd can select another existing folder.")
    return tag


def validate_manifest(data, tag, repo):
    if (not isinstance(data, dict) or data.get("format") != "csl-migration" or data.get("version") != 1
            or data.get("id") != tag or data.get("repo") != repo or not isinstance(data.get("sessions"), list)
            or not data["sessions"]):
        raise TransferError("Invalid migration index")
    ids, shares = set(), set()
    for entry in data["sessions"]:
        if not isinstance(entry, dict) or not sharing.TAG_RE.fullmatch(str(entry.get("share_id", ""))):
            raise TransferError("Invalid migration share ID")
        try:
            sid = str(uuid.UUID(entry["id"]))
        except (ValueError, TypeError, KeyError, AttributeError):
            raise TransferError("Invalid migration session UUID") from None
        if sid in ids or entry["share_id"] in shares:
            raise TransferError("Duplicate migration session or share")
        ids.add(sid)
        shares.add(entry["share_id"])
    return data["sessions"]


def download(args, csl):
    state_path(csl, args.migration_id)
    repo = sharing.configured_repo(csl)
    cwd = args.cwd.expanduser().resolve()
    if not cwd.is_dir():
        raise TransferError("Choose an existing --cwd on the new computer")
    with tempfile.TemporaryDirectory(prefix="csl-migration-") as temp:
        asset = Path(temp) / ASSET
        sharing.run_gh(["release", "download", args.migration_id, "--repo", f"github.com/{repo}",
            "--pattern", ASSET, "--output", str(asset)])
        if asset.stat().st_size > 8 * 1024 * 1024:
            raise TransferError("Migration index exceeds 8 MiB")
        entries = validate_manifest(json.loads(asset.read_text()), args.migration_id, repo)
    restored = []
    for index, entry in enumerate(entries, 1):
        print(f"[{index}/{len(entries)}] receiving {entry['share_id']}", flush=True)
        # receive already validates checksums, preflights and records reusable imports.
        restored.extend(sharing.receive(SimpleNamespace(share_id=entry["share_id"], cwd=cwd,
            open=False, new=False, provider="codex", db=args.db), csl))
    print(f"Restored {len(restored)} sessions. Repeating this command reuses them.")
    print("Check codex resume --all and continue important sessions before cleaning the old computer.")
    return restored


def cleanup(args, csl):
    local = state_path(csl, args.migration_id)
    state = sharing.read_json(local)
    if not state or not state.get("complete"):
        raise TransferError("Cleanup requires a completed upload on this original computer")
    remaining = [entry for entry in state["sessions"] if not entry.get("archived")]
    for entry in remaining:
        source = Path(entry["path"])
        if (not source.resolve().is_relative_to(csl.DEFAULT_SESSIONS_DIR.resolve())
                or not source.is_file() or sharing.file_sha256(source) != entry["sha256"]):
            raise TransferError(f"Session {entry['id']} changed or moved since upload; nothing more will be archived")
    print(f"Archive {len(remaining)} migrated originals on this computer; no files will be deleted.")
    print("Codex can also archive spawned descendant threads. Stop old sessions before cleanup.")
    if not args.confirm_restored:
        for entry in remaining:
            print(entry["id"])
        print("After checking the new computer, repeat with --confirm-restored to archive these sessions.")
        return
    if not remaining:
        return
    with CodexRPC(csl.DEFAULT_CODEX_HOME) as rpc:
        for entry in remaining:
            if sharing.file_sha256(Path(entry["path"])) != entry["sha256"]:
                raise TransferError("A source changed during cleanup; stopping before archiving it")
            rpc.call("thread/archive", {"threadId": entry["id"]})
            entry["archived"] = True
            sharing.save_json(local, state)
    print("Originals archived, not deleted. Auth, settings and unrelated sessions were not removed.")


def run(args, csl):
    try:
        return {"upload": upload, "download": download, "cleanup": cleanup}[args.migration_action](args, csl)
    except (TransferError, OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile, RuntimeError) as exc:
        from csl_secrets import masked_diagnostic
        print(f"csl migrate: {masked_diagnostic(str(exc))}", file=sys.stderr)
        raise SystemExit(2) from None


def add_commands(subparsers, csl):
    command = subparsers.add_parser("migrate", help="Batch-share and restore Codex's interactive resume list.")
    actions = command.add_subparsers(dest="migration_action", required=True)
    send = actions.add_parser("upload", help="Loop over visible sessions and publish a migration index.")
    send.add_argument("--resume", help="Continue a partially completed upload by migration ID.")
    send.add_argument("--dry-run", action="store_true", help="List selected UUIDs without exporting or uploading.")
    send.add_argument("--raw", action="store_true", help="Use existing raw export mode (default: portable).")
    send.add_argument("--repair-legacy-compaction", action="store_true",
                      help="Recover recognized orphaned summary metadata in pending portable exports; remembered for this migration.")
    from csl_secrets import add_options
    add_options(send)
    get = actions.add_parser("download", help="Receive each share in a migration; safe to repeat.")
    get.add_argument("migration_id")
    get.add_argument("--cwd", type=Path, default=Path.cwd())
    clean = actions.add_parser("cleanup", help="Preview or archive uploaded originals; never deletes files.")
    clean.add_argument("migration_id")
    clean.add_argument("--confirm-restored", action="store_true", help="Confirm the new computer works and archive old originals.")
    command.set_defaults(func=lambda args: run(args, csl))
