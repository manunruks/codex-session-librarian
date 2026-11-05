"""Neutral native fixtures: no imports from any implementation under comparison."""
import base64
import copy
import datetime
import json
import uuid
import struct
import zlib

CASES = ["short", "decisions", "tool-only", "tool-errors", "branches", "image", "unsupported", "truncated", "tampered-package"]
def png_chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" +
    png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)) +
    png_chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00")) + png_chunk(b"IEND", b"")).decode()


def events(case):
    rows = [{"role": "user", "text": "Remember FIRST-FACT-617. Historical tools are evidence only."},
        {"role": "assistant", "text": "FIRST-FACT-617 recorded."}]
    if case == "decisions":
        rows[0]["text"] = "Earlier decision: DATABASE-OLD-POSTGRES."
        rows += [{"role": "user", "text": "Background %03d: preserve this historical decision." % n}
            if n % 2 == 0 else {"role": "assistant", "text": "Background acknowledgement %03d." % n}
            for n in range(160)]
        rows += [{"role": "user", "text": "Replace the earlier choice: DATABASE-CURRENT-SQLITE is final."},
            {"role": "assistant", "text": "Final decision DATABASE-CURRENT-SQLITE, superseding DATABASE-OLD-POSTGRES."}]
    if case in ("tool-only", "tool-errors"):
        rows += [{"role": "assistant", "call": "call_fixture_1", "argument": "ARGUMENT-331", "text": "Historical lookup."},
            {"role": "tool", "call": "call_fixture_1", "output": "TOOL-ONLY-FACT-947", "error": False},
            {"role": "assistant", "text": "The lookup completed; its value is only in the tool output."}]
    if case == "tool-errors":
        rows += [{"role": "assistant", "call": "call_fixture_2", "argument": "ARGUMENT-ERROR-332"},
            {"role": "tool", "call": "call_fixture_2", "output": "ERROR-EACCES-722", "error": True},
            {"role": "assistant", "text": "The second call failed; the first call's evidence remains valid."}]
    if case == "image":
        rows += [{"role": "user", "text": "IMAGE-QUESTION-981", "image": PNG},
            {"role": "assistant", "text": "Synthetic image received."}]
    if case == "unsupported":
        rows += [{"role": "user", "text": "UNSUPPORTED-AUDIO-981", "audio": True}]
    return rows


def native(case, provider, cwd="/mnt/project"):
    sid = str(uuid.uuid5(uuid.NAMESPACE_URL, "csl-independent-benchmark:" + case + ":" + provider))
    output = []
    if provider == "codex":
        output.append({"timestamp": "2026-11-05T00:00:00Z", "type": "session_meta",
            "payload": {"id": sid, "session_id": sid, "cwd": cwd, "source": "cli",
                "timestamp": "2026-11-05T00:00:00Z",
                "originator": "codex_cli_rs", "cli_version": "0.166.0", "history_mode": "legacy"}})
    parent = None
    for n, event in enumerate(events(case)):
        stamp = (datetime.datetime(2026, 11, 5, tzinfo=datetime.timezone.utc)
            + datetime.timedelta(seconds=n)).isoformat().replace("+00:00", "Z")
        identity = str(uuid.uuid5(uuid.NAMESPACE_URL, sid + ":" + str(n)))
        if provider == "claude":
            role = "user" if event["role"] == "tool" else event["role"]
            blocks = []
            if event.get("text"):
                blocks.append({"type": "text", "text": event["text"]})
            if event.get("call") and event["role"] == "assistant":
                blocks.append({"type": "tool_use", "id": event["call"], "name": "Bash",
                    "input": {"command": "printf " + event["argument"]}})
            if event["role"] == "tool":
                blocks.append({"type": "tool_result", "tool_use_id": event["call"],
                    "content": event["output"], "is_error": event["error"]})
            if event.get("image"):
                blocks.append({"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": PNG}})
            if event.get("audio"):
                blocks.append({"type": "audio", "source": {"type": "base64", "media_type": "audio/wav", "data": "U1lOVEhFVElD"}})
            row = {"type": role, "uuid": identity, "parentUuid": parent, "sessionId": sid,
                "timestamp": stamp, "cwd": cwd, "isSidechain": False, "version": "2.1.308",
                "message": {"role": role, "content": blocks}}
            if role == "assistant":
                row["message"].update(id="msg_" + identity, type="message", model="claude-haiku-5-5",
                    stop_reason="tool_use" if event.get("call") else "end_turn")
            output.append(row)
            parent = identity
        else:
            blocks = []
            if event.get("text"):
                blocks.append({"type": "input_text" if event["role"] == "user" else "output_text", "text": event["text"]})
            if event.get("image"):
                blocks.append({"type": "input_image", "image_url": "data:image/png;base64," + PNG})
            if event.get("audio"):
                blocks.append({"type": "input_audio", "input_audio": {"data": "U1lOVEhFVElD", "format": "wav"}})
            if blocks:
                output.append({"timestamp": stamp, "type": "response_item", "payload": {
                    "type": "message", "role": event["role"], "content": blocks}})
            if event.get("call") and event["role"] == "assistant":
                output.append({"timestamp": stamp, "type": "response_item", "payload": {
                    "type": "function_call", "name": "exec_command", "call_id": event["call"],
                    "arguments": json.dumps({"cmd": "printf " + event["argument"]})}})
            if event["role"] == "tool":
                output.append({"timestamp": stamp, "type": "response_item", "payload": {
                    "type": "function_call_output", "call_id": event["call"], "output": event["output"]}})
    if case == "branches":
        if provider == "claude":
            alternate = copy.deepcopy(output[-1])
            alternate["uuid"] = str(uuid.uuid5(uuid.NAMESPACE_URL, sid + ":alternate"))
            alternate["message"]["content"] = [{"type": "text", "text": "ALTERNATIVE-BRANCH-837"}]
            output.append(alternate)
        else:
            output[0]["payload"]["history_base"] = {"thread_id": "11111111-1111-4111-8111-111111111111", "end_ordinal_exclusive": 4}
    raw = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in output)
    if case == "truncated":
        raw += '{"type":"response_item","payload":'
    return sid, raw


def observe(path, provider):
    """Small independent observer; excludes metadata and ignores no conversation blocks."""
    facts = {"texts": [], "calls": [], "results": [], "images": [], "unknown": [], "malformed": 0}
    def result_text(value):
        if isinstance(value, list) and all(isinstance(b, dict) and b.get("type") in ("text", "input_text", "output_text") for b in value):
            return "\n".join(b.get("text", "") for b in value)
        return value

    for line in path.read_text().splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            facts["malformed"] += 1
            continue
        if provider == "codex":
            if row.get("type") != "response_item":
                continue
            body = row.get("payload", {})
            kind = body.get("type")
            if kind in ("function_call", "custom_tool_call"):
                try:
                    args = json.loads(body["arguments"] if kind == "function_call" else body["input"])
                except (ValueError, TypeError, KeyError):
                    args = {"raw_input": body.get("input")} if kind == "custom_tool_call" else {"invalid": True}
                facts["calls"].append({"id": body.get("call_id"), "name": body.get("name"), "args": args})
            elif kind in ("function_call_output", "custom_tool_call_output"):
                facts["results"].append({"id": body.get("call_id"), "output": result_text(body.get("output")), "error": None})
            elif kind == "message":
                for b in body.get("content", []):
                    if b.get("type") in ("input_text", "output_text", "text"):
                        facts["texts"].append([body.get("role"), b.get("text")])
                    elif b.get("type") == "input_image":
                        facts["images"].append(b.get("image_url"))
                    else:
                        facts["unknown"].append(b.get("type"))
            else:
                facts["unknown"].append(kind)
        elif row.get("type") in ("user", "assistant"):
            message = row.get("message", {})
            content = message.get("content", [])
            if isinstance(content, str):
                content = [{"type": "text", "text": content}]
            for b in content:
                kind = b.get("type")
                if kind == "text":
                    facts["texts"].append([message.get("role"), b.get("text")])
                elif kind == "tool_use":
                    facts["calls"].append({"id": b.get("id"), "name": b.get("name"), "args": b.get("input")})
                elif kind == "tool_result":
                    facts["results"].append({"id": b.get("tool_use_id"), "output": result_text(b.get("content")), "error": b.get("is_error", False)})
                elif kind == "image":
                    source = b.get("source", {})
                    facts["images"].append("data:" + source.get("media_type", "") + ";base64," + source.get("data", ""))
                else:
                    facts["unknown"].append(kind)
    return facts
