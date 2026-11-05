"""Fault injection at the validated-history publication boundary."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import uuid
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import csl_transfer as transfer


class ImportPublicationTests(unittest.TestCase):
    def test_failed_copy_never_exposes_a_partial_native_session(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sid = str(uuid.uuid4())
            records = [
                {"type": "session_meta", "payload": {"id": sid, "cwd": str(root)}},
                {"type": "response_item", "payload": {"type": "message", "role": "user",
                    "content": [{"type": "input_text", "text": "Synthetic publication fixture"}]}},
            ]
            raw = b"".join((json.dumps(row) + "\n").encode() for row in records)
            member = "sessions/" + sid + ".jsonl"
            manifest = {"format": transfer.FORMAT, "version": 1, "mode": "portable",
                "sessions": [{"id": sid, "provider": "codex", "title": "Synthetic",
                    "file": member, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}]}
            bundle = root / "fixture.zip"
            with zipfile.ZipFile(bundle, "w") as archive:
                archive.writestr(member, raw)
                archive.writestr("manifest.json", json.dumps(manifest))
            before = hashlib.sha256(bundle.read_bytes()).hexdigest()
            sessions = root / "destination"
            registered = Mock()
            fake_csl = SimpleNamespace(session_id_exists=lambda _: False,
                utc_now=lambda: "2026-11-05T00:00:00Z", init_db=lambda _: Mock(),
                register_native_session=registered,
                target_session_path=lambda identity, _: sessions / (identity + ".jsonl"))
            args = SimpleNamespace(cwd=root, bundle=bundle, list=False, open=False,
                name=None, db=root / "index.sqlite", refresh_native_index=False)

            def interrupted_copy(source, destination, *unused):
                destination.write(source.read(16))
                raise OSError("Synthetic interrupted write")

            with patch.object(transfer.shutil, "copyfileobj", side_effect=interrupted_copy), \
                    contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(OSError):
                    transfer.import_bundle(args, fake_csl)
            self.assertEqual(list(sessions.glob("*.jsonl")), [],
                "A failed copy must not leave a visible partial native history")
            registered.assert_not_called()
            self.assertEqual(hashlib.sha256(bundle.read_bytes()).hexdigest(), before)

    def test_partial_batch_keeps_complete_first_session_and_reports_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sessions = root/'destination'
            entries, contents = [], {}
            for _ in range(2):
                identity = str(uuid.uuid4())
                records = [{'type':'session_meta','payload':{'id':identity}},
                           {'type':'response_item','payload':{'type':'message','role':'user',
                            'content':[{'type':'input_text','text':'Synthetic batch fixture'}]}}]
                raw = b''.join((json.dumps(row)+'\n').encode() for row in records)
                member = 'sessions/'+identity+'.jsonl'
                entries.append({'id':identity,'provider':'codex','title':'Synthetic','file':member,
                                'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()})
                contents[member] = raw
            bundle = root/'batch.zip'
            with zipfile.ZipFile(bundle,'w') as archive:
                archive.writestr('manifest.json',json.dumps({'format':transfer.FORMAT,'version':1,
                    'mode':'portable','sessions':entries}))
                for member, raw in contents.items():
                    archive.writestr(member,raw)
            registered = Mock()
            fake_csl = SimpleNamespace(session_id_exists=lambda _:False,utc_now=lambda:'2026-11-05T00:00:00Z',
                init_db=lambda _:Mock(),register_native_session=registered,
                target_session_path=lambda identity,_:sessions/(identity+'.jsonl'))
            args = SimpleNamespace(cwd=root,bundle=bundle,list=False,open=False,name=None,
                                   db=root/'index.sqlite',refresh_native_index=False)
            original_copy = transfer.shutil.copyfileobj
            calls = 0
            def fail_second(source,destination):
                nonlocal calls
                calls += 1
                if calls == 2:
                    destination.write(source.read(16))
                    raise OSError('Synthetic interrupted second copy')
                return original_copy(source,destination)
            out, err = io.StringIO(), io.StringIO()
            with patch.object(transfer.shutil,'copyfileobj',side_effect=fail_second), \
                 contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                with self.assertRaises(OSError):
                    transfer.import_bundle(args,fake_csl)
            installed = list(sessions.glob('*.jsonl'))
            self.assertEqual(len(installed),1)
            rows = [json.loads(line) for line in installed[0].read_text().splitlines()]
            self.assertTrue(any(row.get('payload',{}).get('type')=='message' for row in rows))
            self.assertEqual(registered.call_count,1)
            self.assertIn('after 1 complete sessions',err.getvalue())
            self.assertEqual(list(sessions.glob('.csl-import-*')),[])

    def test_interrupted_staging_cleans_up_for_oserror_and_keyboard_interrupt(self):
        for error in (OSError('Synthetic copy failure'), KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = root/'source'
                source.write_bytes(b'synthetic complete history')
                target = root/'sessions'/'new.jsonl'
                def interrupt(input_file, output_file):
                    output_file.write(input_file.read(5))
                    raise error
                with patch.object(transfer.shutil, 'copyfileobj', side_effect=interrupt):
                    with self.assertRaises(type(error)):
                        transfer.publish_session_file(source, target)
                self.assertFalse(target.exists())
                self.assertEqual(list(target.parent.iterdir()), [])
                self.assertEqual(source.read_bytes(), b'synthetic complete history')

    def test_publish_collision_never_overwrites_concurrent_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root/'source'
            source.write_bytes(b'synthetic complete history')
            target = root/'sessions'/'new.jsonl'
            original_link = transfer.os.link
            def competing_publish(staged, destination, **kwargs):
                destination.write_bytes(b'other complete history')
                return original_link(staged, destination, **kwargs)
            with patch.object(transfer.os, 'link', side_effect=competing_publish):
                with self.assertRaises(FileExistsError):
                    transfer.publish_session_file(source, target)
            self.assertEqual(target.read_bytes(), b'other complete history')
            self.assertEqual(list(target.parent.iterdir()), [target])

    def test_successful_publication_is_complete_and_private(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root/'source'
            source.write_bytes(b'synthetic complete history')
            target = root/'sessions'/'new.jsonl'
            transfer.publish_session_file(source, target)
            self.assertEqual(target.read_bytes(), source.read_bytes())
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            self.assertEqual(list(target.parent.iterdir()), [target])


if __name__ == "__main__":
    unittest.main()
