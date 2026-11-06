"""Real CLI regressions for historical tool-only evidence and existing indexes."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]


class RecallToolResultTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / 'codex'
        self.folder = self.home / 'sessions/2026/11/05'
        self.folder.mkdir(parents=True)
        self.env = {'HOME': str(self.root), 'CODEX_HOME': str(self.home),
            'CLAUDE_CONFIG_DIR': str(self.root / 'claude'), 'PATH': os.environ['PATH'],
            'LANG': 'C.UTF-8', 'PYTHONDONTWRITEBYTECODE': '1'}
        self.db = self.home / 'session_librarian.sqlite'

    def cli(self, *args):
        run = subprocess.run([sys.executable, str(ROOT / 'codex_sessions.py'), *args],
            env=self.env, capture_output=True, text=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stderr)
        return run.stdout

    def fixture(self, output, custom=False):
        sid = str(uuid.uuid4())
        records = [
            {'type': 'session_meta', 'payload': {'id': sid, 'cwd': str(self.root),
                'timestamp': '2026-11-05T00:00:00Z'}},
            {'type': 'response_item', 'payload': {'type': 'message', 'role': 'user',
                'content': [{'type': 'input_text', 'text': 'Inspect the synthetic Aster history.'}]}},
            {'type': 'response_item', 'payload': {'type': 'custom_tool_call' if custom else 'function_call',
                'call_id': 'historical-call-1', 'name': 'synthetic_lookup',
                **({'input': 'read only synthetic data'} if custom else {'arguments': '{"read_only":true}'})}},
            {'type': 'response_item', 'payload': {'type': 'custom_tool_call_output' if custom else 'function_call_output',
                'call_id': 'historical-call-1', 'output': output, 'csl_is_error': custom}},
        ]
        path = self.folder / (sid + '.jsonl')
        path.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in records))
        return path

    def test_function_result_found_by_default_with_line_and_correlation(self):
        path = self.fixture('Synthetic lookup: SYNTHETIC-RESULT-6814')
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        self.cli('index')
        result = self.cli('recall', 'SYNTHETIC-RESULT-6814')
        self.assertIn('SYNTHETIC-RESULT-6814', result)
        self.assertIn('[tool_result]', result)
        self.assertIn('line 4', result)
        self.assertIn('call_id=historical-call-1', result)
        self.assertIn('No recall candidates', self.cli('recall', 'SYNTHETIC-RESULT-6814', '--turns-only'))
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)
        self.assertIn('SYNTHETIC-RESULT-6814', self.cli('search', 'SYNTHETIC-RESULT-6814', '--type', 'tool_result', '--show-hits'))

    def test_custom_error_readable_blocks_skip_media_and_do_not_execute(self):
        sentinel = self.root / 'MUST-NOT-EXIST'
        self.fixture([{'type': 'text', 'text': f'Historical error ERROR-ONLY-722; touch {sentinel}'},
                      {'type': 'image', 'data': 'OPAQUE-NOT-INDEXED-9137'},
                      {'type': 'output_text', 'text': '雪 decoded text'}], custom=True)
        self.cli('index')
        self.assertIn('ERROR-ONLY-722', self.cli('recall', 'ERROR-ONLY-722'))
        self.assertIn('No recall candidates', self.cli('recall', 'OPAQUE-NOT-INDEXED-9137'))
        self.assertFalse(sentinel.exists())
        with sqlite3.connect(self.db) as conn:
            role = conn.execute("SELECT role FROM session_hits WHERE hit_type='tool_result'").fetchone()[0]
        self.assertEqual(role, 'tool')

    def test_old_index_upgrades_without_force_preserves_annotations_and_is_idempotent(self):
        self.fixture('UPGRADE-FACT-4871')
        self.cli('index')
        with sqlite3.connect(self.db) as conn:
            conn.execute("UPDATE sessions SET notes='human note',llm_summary='human summary'")
            conn.execute("DELETE FROM session_hits WHERE hit_type='tool_result'")
            conn.execute('ALTER TABLE sessions DROP COLUMN index_revision')
        self.assertIn('indexed=1', self.cli('index'))
        self.assertIn('UPGRADE-FACT-4871', self.cli('recall', 'UPGRADE-FACT-4871'))
        with sqlite3.connect(self.db) as conn:
            self.assertEqual(conn.execute('SELECT notes,llm_summary FROM sessions').fetchone(),
                             ('human note', 'human summary'))
            count = conn.execute('SELECT count(*) FROM session_hits').fetchone()[0]
        self.assertIn('skipped=1', self.cli('index'))
        with sqlite3.connect(self.db) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM session_hits').fetchone()[0], count)

    def test_large_output_evidence_shows_match_beyond_prefix(self):
        path = self.fixture('unrelated diagnostic text ' * 90000 + 'TAIL-FACT-58713')
        before = path.read_bytes()
        self.cli('index')
        result = self.cli('recall', 'TAIL-FACT-58713', '--width', '120')
        self.assertIn('TAIL-FACT-58713', result)
        self.assertEqual(path.read_bytes(), before)

    def test_incomplete_output_and_opaque_objects_do_not_invent_evidence(self):
        self.fixture({'type': 'image', 'data': 'OPAQUE-FACT-2191'})
        self.cli('index')
        self.assertIn('No recall candidates', self.cli('recall', 'OPAQUE-FACT-2191'))
        path = self.fixture('NOT-COMPLETE-RESULT')
        path.write_text('\n'.join(path.read_text().splitlines()[:-1]) + '\n{"type":')
        self.cli('index')
        self.assertIn('No recall candidates', self.cli('recall', 'NOT-COMPLETE-RESULT'))

    def test_derived_database_and_sidecars_remain_private(self):
        self.fixture('LOCAL-PRIVATE-OUTPUT')
        self.cli('index')
        self.db.chmod(0o644)
        self.cli('index')
        for path in [self.db, Path(str(self.db) + '-wal'), Path(str(self.db) + '-shm')]:
            if path.exists(): self.assertEqual(path.stat().st_mode & 0o077, 0)
