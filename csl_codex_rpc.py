"""Small metadata-only Codex app-server client for migration listing/archiving."""

import json
import os
import queue
import shutil
import subprocess
import threading
import time

from csl_transfer import TransferError


class CodexRPC:
    def __init__(self, home):
        self.home = home
        self.number = 0
        self.responses = queue.Queue()

    def __enter__(self):
        if not shutil.which("codex"):
            raise TransferError("Codex is required to enumerate its resume list and archive sessions")
        self.process = subprocess.Popen(["codex", "app-server"],
            env={**os.environ, "CODEX_HOME": str(self.home)}, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        def read():
            try:
                for line in self.process.stdout:
                    try:
                        self.responses.put(json.loads(line))
                    except ValueError:
                        continue
            finally:
                self.responses.put(None)
        self.reader = threading.Thread(target=read, daemon=True)
        self.reader.start()
        try:
            self.call("initialize", {"clientInfo": {"name": "csl_migration", "version": "1"}})
            self.process.stdin.write('{"method":"initialized","params":{}}\n')
            self.process.stdin.flush()
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def call(self, method, params):
        if method not in ("initialize", "thread/list", "thread/archive"):
            raise TransferError("Migration RPC only permits metadata listing and archiving")
        self.number += 1
        self.process.stdin.write(json.dumps({"id": self.number, "method": method, "params": params}) + "\n")
        self.process.stdin.flush()
        deadline = time.monotonic() + 30
        while True:
            try:
                reply = self.responses.get(timeout=max(0, deadline - time.monotonic()))
            except queue.Empty:
                raise TransferError("Codex metadata request timed out") from None
            if reply is None:
                raise TransferError("Codex app-server closed before completing migration metadata request")
            if reply.get("id") == self.number:
                if "error" in reply:
                    raise TransferError(f"Codex rejected {method}; update Codex and retry (no model call was made)")
                return reply["result"]

    def __exit__(self, *_):
        self.process.stdin.close()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.reader.join(timeout=5)
        self.process.stdout.close()
