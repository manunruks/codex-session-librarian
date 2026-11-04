#!/usr/bin/env python3
"""Filesystem GitHub stand-in for isolated migration subprocess tests only."""

import json
import os
from pathlib import Path
import shutil
import sys


def main(args):
    root = Path(os.environ["CSL_FAKE_GH_ROOT"])
    root.mkdir(parents=True, exist_ok=True)
    with (root / "calls.jsonl").open("a") as stream:
        stream.write(json.dumps(args) + "\n")
    state_path = root / "releases.json"
    releases = json.loads(state_path.read_text()) if state_path.exists() else {}
    if args[:2] == ["repo", "view"]:
        print(json.dumps({"nameWithOwner": "team/migration-fixtures", "isPrivate": not os.getenv("CSL_FAKE_PUBLIC"),
                          "viewerPermission": os.getenv("CSL_FAKE_PERMISSION", "ADMIN")}))
    elif args[:2] == ["release", "create"]:
        tag = args[2]
        if tag in releases:
            raise ValueError("Release already exists")
        shares = sum(name.startswith("csl-") and not name.startswith("csl-migration-") for name in releases)
        if not tag.startswith("csl-migration-") and shares >= int(os.getenv("CSL_FAKE_FAIL_AFTER", "999999")):
            raise ValueError("Synthetic interrupted upload")
        asset = Path(args[3])
        directory = root / tag
        directory.mkdir()
        shutil.copyfile(asset, directory / asset.name)
        notes = (Path(args[args.index("--notes-file") + 1]).read_text() if "--notes-file" in args
                 else args[args.index("--notes") + 1])
        rid = len(releases) + 1
        releases[tag] = {"id": rid, "tag_name": tag, "draft": False, "body": notes,
            "name": args[args.index("--title") + 1], "author": {"login": "synthetic"},
            "published_at": "2026-11-04T00:00:00Z",
            "assets": [{"id": rid * 100, "name": asset.name, "size": asset.stat().st_size}]}
        state_path.write_text(json.dumps(releases))
        if tag.startswith("csl-migration-") and os.getenv("CSL_FAKE_LOST_INDEX_RESPONSE"):
            raise ValueError("Synthetic lost success response after publishing index")
    elif args[:2] == ["release", "download"]:
        tag = args[2]
        if tag == os.getenv("CSL_FAKE_FAIL_DOWNLOAD"):
            raise ValueError("Synthetic interrupted download")
        asset = args[args.index("--pattern") + 1]
        data = (root / tag / asset).read_bytes()
        if tag == os.getenv("CSL_FAKE_CORRUPT_DOWNLOAD"):
            data += b"CORRUPTION"
        Path(args[args.index("--output") + 1]).write_bytes(data)
    elif args[0] == "api" and "/releases/tags/" in args[-1]:
        print(json.dumps(releases[args[-1].rsplit("/", 1)[1]]))
    else:
        raise ValueError("Unsupported simulated GitHub operation")


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except (OSError, ValueError, KeyError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
