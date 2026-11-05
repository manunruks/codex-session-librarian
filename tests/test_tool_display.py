"""Historical tool display is distinct from canonical/model tool history."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import csl_canonical as bridge
from csl_secrets import SecretReview
from test_canonical import sample
from test_native_display import read_native_items

REPO = Path(__file__).resolve().parents[1]


def display_rows(path):
    return [row for row in bridge.read_jsonl(path)
            if row.get('csl_display_projection', {}).get('kind') == 'historical_tool']


def parallel_sample():
    data = sample()
    data['events'][1]['phase'] = 'commentary'
    data['events'][1]['blocks'].append({'type': 'tool_call', 'call_id': 'call-2',
        'name': 'custom_synthetic', 'arguments': 'RAW-UNICODE-雪\\n"quoted"', 'argument_format': 'text'})
    data['events'][2]['blocks'].insert(0, {'type': 'tool_result', 'call_id': 'call-2',
        'content': [{'type': 'text', 'text': 'ERROR-UNICODE-雪\\n"quoted"'}], 'is_error': True})
    return data


class ToolDisplayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_parallel_function_custom_errors_and_phases_remain_history(self):
        data = parallel_sample()
        path = self.root/'codex.jsonl'
        bridge.restore_codex(data, path, self.root)
        projected = display_rows(path)
        self.assertEqual(len(projected), 4)
        self.assertEqual([r['payload']['call_id'] for r in projected],
                         ['call-1', 'call-2', 'call-2', 'call-1'])
        for row in projected:
            self.assertTrue(row['csl_display_projection']['history_only'])
            self.assertEqual(row['payload']['invocation']['server'], 'csl_imported_history')
        custom = projected[1]['payload']['invocation']
        self.assertEqual(custom['arguments'], data['events'][1]['blocks'][1]['arguments'])
        error = projected[2]
        self.assertTrue(error['payload']['result']['Ok']['isError'])
        self.assertIn('unknown', error['csl_display_projection']['duration'])
        self.assertEqual(bridge.semantic_events(data), bridge.semantic_events(bridge.from_codex(path)))
        self.assertEqual([e.get('phase') for e in bridge.from_codex(path)['events'] if e['role']=='assistant'][0],
                         'commentary')

    def test_repeated_conversion_does_not_accumulate_display_or_model_items(self):
        data = parallel_sample()
        expected = bridge.semantic_events(data)
        for index in range(3):
            path = self.root/f'codex-{index}.jsonl'
            bridge.restore_codex(data, path, self.root)
            self.assertEqual(len(display_rows(path)), 4)
            data = bridge.from_codex(path)
            self.assertEqual(bridge.semantic_events(data), expected)

    def test_secret_scrub_cleans_display_arguments_even_business_metadata_names(self):
        data=sample()
        secret='sk-proj-'+'Z'*40
        data['events'][1]['blocks'][0]['arguments']={'id':secret,'signature':secret}
        path=self.root/'sensitive.jsonl'
        bridge.restore_codex(data,path,self.root)
        rows=bridge.read_jsonl(path)
        review=SecretReview(SimpleNamespace(scrub_secrets=True))
        for index,row in enumerate(rows):review.scan(row,str(index))
        review.resolve(announce=False)
        cleaned=[review.cleaned(row) for row in rows]
        self.assertNotIn(secret,json.dumps(cleaned))
        self.assertEqual(len(display_rows(path)),2)
        # Exercise real ZIP publication too: both authoritative and projected
        # copies must be scrubbed, and the rebuilt manifest must validate.
        env={'PATH':os.environ['PATH'],'HOME':str(self.root),
             'CODEX_HOME':str(self.root/'codex'),'CLAUDE_CONFIG_DIR':str(self.root/'claude')}
        cli=[sys.executable,str(REPO/'codex_sessions.py')]
        bundle=self.root/'scrubbed.zip'
        subprocess.run(cli+['export',str(path),'--to',str(bundle),'--scrub-secrets'],
                       env=env,check=True,capture_output=True)
        with zipfile.ZipFile(bundle) as archive:
            for name in archive.namelist():self.assertNotIn(secret.encode(),archive.read(name))
        subprocess.run(cli+['import',str(bundle),'--list'],env=env,check=True,capture_output=True)

    def test_unknown_and_incomplete_states_reject_without_destination(self):
        for kind in ('unknown', 'incomplete'):
            data = sample()
            if kind == 'unknown': data['events'][1]['blocks'][0]['type'] = 'future_tool_call'
            else: del data['events'][2]
            target = self.root/(kind+'.jsonl')
            with self.assertRaises(ValueError): bridge.restore_codex(data,target,self.root)
            self.assertFalse(target.exists())

    def test_frozen_benchmark_pairs_preserve_origin_and_canonical_history(self):
        for case, count in [('tool-only', 2), ('tool-errors', 4)]:
            source = REPO/'tests/fixtures'/('benchmark-'+case+'-claude.jsonl')
            before = hashlib.sha256(source.read_bytes()).hexdigest()
            data = bridge.from_claude(source)
            target, back = self.root/(case+'.jsonl'), self.root/(case+'-back.jsonl')
            bridge.restore_codex(data,target,self.root)
            restored = bridge.from_codex(target)
            bridge.restore_claude(restored,back,self.root)
            self.assertEqual(bridge.semantic_events(data), bridge.semantic_events(bridge.from_claude(back)))
            self.assertEqual(len(display_rows(target)), count)
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)

    def test_repeated_same_cli_import_keeps_one_projection_per_call(self):
        target = self.root/'source.jsonl'
        bridge.restore_codex(parallel_sample(),target,self.root)
        original = target.read_bytes()
        env = {'PATH':os.environ['PATH'], 'HOME':str(self.root),
               'CODEX_HOME':str(self.root/'codex'), 'CLAUDE_CONFIG_DIR':str(self.root/'claude'),
               'LANG':'C.UTF-8'}
        cli = [sys.executable,str(REPO/'codex_sessions.py')]
        bundle=self.root/'fixture.zip'
        subprocess.run(cli+['export',str(target),'--to',str(bundle)],env=env,check=True,capture_output=True)
        for _ in range(2):
            result=subprocess.run(cli+['import',str(bundle),'--cwd',str(self.root)],env=env,
                                  check=True,capture_output=True,text=True)
            imported=re.search(r'imported: ([0-9a-f-]+)',result.stdout).group(1)
            paths=list((self.root/'codex/sessions').rglob('*'+imported+'.jsonl'))
            self.assertEqual(len(paths),1)
            self.assertEqual(len(display_rows(paths[0])),4)
            self.assertEqual(bridge.semantic_events(bridge.from_codex(paths[0])),
                             bridge.semantic_events(parallel_sample()))
        self.assertEqual(target.read_bytes(),original)


@unittest.skipUnless(os.environ.get('CSL_RUN_CODEX_NATIVE_TESTS')=='1' and shutil.which('codex'),
                     'Enable CSL_RUN_CODEX_NATIVE_TESTS=1 for native display verification')
class NativeToolDisplayTests(unittest.TestCase):
    def test_native_tool_items_show_benchmark_markers_and_correct_error(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); home=root/'codex'
            for case, count in [('tool-only',1),('tool-errors',2),('parallel',2)]:
                data = parallel_sample() if case=='parallel' else bridge.from_claude(
                    REPO/'tests/fixtures'/('benchmark-'+case+'-claude.jsonl'))
                target=home/'sessions/2026/11/05'/(case+'.jsonl')
                target.parent.mkdir(parents=True,exist_ok=True)
                info=bridge.restore_codex(data,target,root)
                renamed=target.with_name('rollout-2026-11-05T00-00-00-'+info['id']+'.jsonl')
                target.rename(renamed)
                before=renamed.read_bytes()
                env={'PATH':os.environ['PATH'],'CODEX_HOME':str(home),
                     'CLAUDE_CONFIG_DIR':str(root/'claude')}
                items=read_native_items(self,root,env,info['id'])
                tools=[item for item in items if item['type']=='mcpToolCall']
                self.assertEqual(len(tools),count)
                text=json.dumps(tools,ensure_ascii=False)
                markers=['RAW-UNICODE-雪','ERROR-UNICODE-雪'] if case=='parallel' else [
                    'ARGUMENT-331','TOOL-ONLY-FACT-947']
                if case=='tool-errors':markers+=['ARGUMENT-ERROR-332','ERROR-EACCES-722']
                for marker in markers:self.assertIn(marker,text)
                for tool in tools:self.assertEqual(tool['server'],'csl_imported_history')
                expected_status = {'call_fixture_1': 'completed', 'call_fixture_2': 'failed',
                                   'call-1': 'completed', 'call-2': 'failed'}
                for tool in tools:
                    self.assertEqual(tool['status'],expected_status[tool['id']])
                self.assertEqual(renamed.read_bytes(),before)
