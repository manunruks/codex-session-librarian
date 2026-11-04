#!/usr/bin/env python3
"""Reproducible synthetic CSL demo. Offline by default; never reads personal histories."""

import argparse
from decimal import Decimal
import datetime as dt
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

SOURCE_ID = '11111111-1111-4111-8111-111111111111'
CLAUDE_ID = '22222222-2222-4222-8222-222222222222'
STAMP = '2026-11-02T12:00:00Z'
FACTS = {'release': 'amber42', 'database': 'SQLite', 'fixture_serial': 'DEMO-617'}
PROMPT = ('Using only the installed conversation history, return a JSON object with fields '
          'release, database, fixture_serial. Report the latest decisions rather than superseded values. '
          'Do not use tools. No markdown or explanations.')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_jsonl(path, records):
    path.write_text(''.join(json.dumps(record, ensure_ascii=False) + '\n' for record in records))
    path.chmod(0o600)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True, help='Local CSL checkout; no download/install is performed.')
    parser.add_argument('--out', type=Path, default=Path(__file__).resolve().parent/'demo.json')
    parser.add_argument('--allow-paid', action='store_true')
    parser.add_argument('--live-codex-home', type=Path, help='Existing separately authenticated synthetic test home; never a personal home.')
    args = parser.parse_args()
    repo = args.repo.resolve()
    entry = repo/'codex_sessions.py'
    if not entry.is_file():
        parser.error('--repo must contain codex_sessions.py')
    if bool(args.live_codex_home) != args.allow_paid:
        parser.error('Live checks require both --allow-paid and --live-codex-home; offline is the default.')
    sys.path.insert(0, str(repo))
    canonical = importlib.import_module('csl_canonical')
    report = {'schema_version': 1, 'kind': 'synthetic', 'generated_at': dt.datetime.now(dt.UTC).isoformat(timespec='seconds'), 'label': 'Synthetic demo fixture — not a real user or testimonial',
        'language': 'en', 'offline': {'status': 'in-progress'}, 'steps': [],
        'fixture': {'initial_decision': 'cobalt with Postgres', 'corrected_decision': 'amber42 with SQLite',
                    'tool_only_fact': 'DEMO-617', 'contains_real_user_data': False},
        'provenance': {'runner_sha256': digest(Path(__file__)),
            'adapter_sha256': {name: digest(repo/name) for name in ('csl_transfer.py', 'csl_canonical.py', 'csl_conversion.py', 'csl_secrets.py')}},
        'live': {'status': 'not-tested', 'calls_attempted': 0},
        'limits': ['Synthetic bounded fixture; not universal compatibility.',
            'Offline import/conversion verifies structure and historical content, not model recall.',
            'A package does not include repositories, credentials or unembedded external attachments.',
            'Imported history is context, not authorization to execute prior tasks.',
            'Secret scanning is partial; opaque attachments remain outside its coverage.']}
    with tempfile.TemporaryDirectory(prefix='csl-public-demo-') as temporary:
        root = Path(temporary)
        root.chmod(0o700)
        project = root/'project'
        project.mkdir()
        env = {'PATH': os.environ['PATH'], 'HOME': str(root), 'CODEX_HOME': str(root/'codex'),
               'CLAUDE_CONFIG_DIR': str(root/'claude'), 'LANG': 'C.UTF-8'}
        def cli(arguments, *, home=None):
            child = {**env, **({'CODEX_HOME': str(home)} if home else {})}
            result = subprocess.run([sys.executable, str(entry), *map(str, arguments)], cwd=project,
                env=child, capture_output=True, text=True, timeout=60)
            if result.returncode:
                # Do not publish raw logs, paths, account details or provider output.
                raise RuntimeError('Synthetic CSL demo command failed; no private logs were published')
            return result.stdout

        def installed(output, home=None):
            match = re.search(r'imported: ([0-9a-f-]{36})', output)
            if not match:
                raise RuntimeError('Synthetic import did not report a new identity')
            paths = list((home or root/'codex').joinpath('sessions').rglob('*'+match.group(1)+'.jsonl'))
            if len(paths) != 1:
                raise RuntimeError('Synthetic installed session could not be located uniquely')
            return match.group(1), paths[0]

        def message(role, value):
            return {'type': 'response_item', 'timestamp': STAMP, 'payload': {'type': 'message', 'role': role,
                'content': [{'type': 'input_text' if role == 'user' else 'output_text', 'text': value}]}}
        source = root/'source.jsonl'
        write_jsonl(source, [
            {'type': 'session_meta', 'timestamp': STAMP, 'payload': {'id': SOURCE_ID, 'timestamp': STAMP,
                'cwd': '/synthetic/project', 'source': 'cli', 'originator': 'csl_synthetic_public_demo',
                'cli_version': '0.166.0', 'model_provider': 'openai'}},
            message('user', 'Initial draft: release cobalt with Postgres.'),
            message('assistant', 'Draft recorded.'),
            message('user', 'Correction: release amber42 with SQLite. The earlier draft is superseded.'),
            {'type': 'response_item', 'timestamp': STAMP, 'payload': {'type': 'function_call', 'call_id': 'demo-read',
                'name': 'Read', 'arguments': '{"file_path":"synthetic-fixture.txt"}'}},
            {'type': 'response_item', 'timestamp': STAMP, 'payload': {'type': 'function_call_output', 'call_id': 'demo-read',
                'output': 'fixture_serial: DEMO-617', 'csl_is_error': False}},
            message('assistant', 'Latest decisions and the historical fixture lookup recorded.')])
        original_hash = digest(source)
        expected = canonical.semantic_events(canonical.from_codex(source))
        bundle = root/'handoff.csl.zip'
        cli(['export', source, '--to', bundle])
        import zipfile
        with zipfile.ZipFile(bundle) as archive:
            manifest = json.loads(archive.read('manifest.json'))
            member = manifest['sessions'][0]
            exported = archive.read(member['file'])
            assert hashlib.sha256(exported).hexdigest() == member['sha256']
        report['steps'].append({'id': 'export', 'command': 'csl export "$WORK/source.jsonl" --to "$WORK/handoff.csl.zip"',
            'result': 'ZIP created from a synthetic native Codex session', 'passed': True,
            'evidence': {'manifest_checksum_valid': True, 'sessions': len(manifest['sessions']), 'original_source_unchanged': digest(source)==original_hash}})
        listing = cli(['import', bundle, '--list'])
        assert 'no sessions installed' in listing
        report['steps'].append({'id': 'inspect', 'command': 'csl import "$WORK/handoff.csl.zip" --list',
            'result': 'Package validated; no sessions installed', 'passed': True})
        new_id, imported = installed(cli(['import', bundle, '--cwd', project]))
        assert new_id != SOURCE_ID
        assert canonical.semantic_events(canonical.from_codex(imported)) == expected
        report['steps'].append({'id': 'import', 'command': 'csl import "$WORK/handoff.csl.zip" --cwd "$WORK/project"',
            'result': 'New native session identity; original historical messages and tool result retained', 'passed': True,
            'evidence': {'new_identity': True, 'normalized_history_equal': True, 'expected_historical_facts': FACTS}})

        claude_source = root/'claude-source.jsonl'
        # Fixed graph identities are fixture-only and never sourced from an account.
        write_jsonl(claude_source, [
            {'type':'user', 'uuid':'33333333-3333-4333-8333-333333333333', 'parentUuid':None,
             'sessionId':CLAUDE_ID, 'timestamp':STAMP, 'message':{'role':'user','content':'Initial draft: release cobalt with Postgres.'}},
            {'type':'assistant','uuid':'44444444-4444-4444-8444-444444444444','parentUuid':'33333333-3333-4333-8333-333333333333',
             'sessionId':CLAUDE_ID,'timestamp':STAMP,'message':{'role':'assistant','content':[{'type':'text','text':'Draft recorded.'}]}},
            {'type':'user','uuid':'55555555-5555-4555-8555-555555555555','parentUuid':'44444444-4444-4444-8444-444444444444',
             'sessionId':CLAUDE_ID,'timestamp':STAMP,'message':{'role':'user','content':'Correction: release amber42 with SQLite. The earlier draft is superseded.'}},
            {'type':'assistant','uuid':'66666666-6666-4666-8666-666666666666','parentUuid':'55555555-5555-4555-8555-555555555555',
             'sessionId':CLAUDE_ID,'timestamp':STAMP,'portability_phase':'commentary','message':{'role':'assistant','content':[
                {'type':'text','text':'Checking the synthetic historical fixture.'},
                {'type':'tool_use','id':'demo-read','name':'Read','input':{'file_path':'synthetic-fixture.txt'}}]}},
            {'type':'user','uuid':'77777777-7777-4777-8777-777777777777','parentUuid':'66666666-6666-4666-8666-666666666666',
             'sessionId':CLAUDE_ID,'timestamp':STAMP,'message':{'role':'user','content':[{'type':'tool_result','tool_use_id':'demo-read','content':'fixture_serial: DEMO-617','is_error':False}]}},
            {'type':'assistant','uuid':'88888888-8888-4888-8888-888888888888','parentUuid':'77777777-7777-4777-8777-777777777777',
             'sessionId':CLAUDE_ID,'timestamp':STAMP,'message':{'role':'assistant','content':'Latest decisions and historical lookup recorded.'}},
            {'type':'last-prompt','sessionId':CLAUDE_ID,'leafUuid':'88888888-8888-4888-8888-888888888888'}])
        claude_hash = digest(claude_source)
        converted_id, converted = installed(cli(['convert', claude_source, '--to', 'codex', '--cwd', project]))
        actual = canonical.from_codex(converted)
        assert canonical.semantic_events(actual) == canonical.semantic_events(canonical.from_claude(claude_source))
        phases = [event.get('phase') for event in actual['events'] for block in event['blocks'] if block['type']=='tool_call']
        assert phases == ['commentary']
        report['steps'].append({'id':'convert', 'command':'csl convert "$WORK/claude-source.jsonl" --to codex --cwd "$WORK/project"',
            'result':'Experimental Claude → Codex conversion retained the selected synthetic history and tool phase', 'passed':True,
            'evidence':{'new_identity':converted_id != CLAUDE_ID, 'normalized_history_equal':True,'tool_phase_retained':True}})
        assert digest(source) == original_hash and digest(claude_source) == claude_hash
        report['offline']={'status':'passed','source_hashes_unchanged':True,'fixtures_deterministic':True,
            'native_import_identity_is_fresh':True, 'source_sha256':original_hash,'claude_source_sha256':claude_hash,
            'native_cli_required':False, 'inference_performed':False,'temporary_homes':True}

        if args.allow_paid:
            home = args.live_codex_home.expanduser().resolve()
            if home in ((Path.home()/'.codex').resolve(), (Path.home()/'.claude').resolve()):
                raise RuntimeError('Personal default homes are forbidden for the synthetic live demo')
            ready = subprocess.run(['codex','login','status'],env={'PATH':os.environ['PATH'],'CODEX_HOME':str(home)},capture_output=True,text=True,timeout=20)
            if ready.returncode or 'ChatGPT' not in ready.stdout+ready.stderr:
                raise RuntimeError('Dedicated ChatGPT test authentication unavailable; no login was attempted')
            live = importlib.import_module('csl_live')
            version = subprocess.run(['codex','--version'],capture_output=True,text=True,timeout=10).stdout.strip()
            report['live']={'status':'in-progress','calls_attempted':0,'cli_version':version,'model_requested':'gpt-6.1-sol',
                'cost_basis':'Existing ChatGPT plan usage; no invented dollar price','results':[]}
            converted_bundle=root/'converted.csl.zip'
            cli(['export',converted,'--to',converted_bundle])
            for name, package in [('native-zip-handoff',bundle),('claude-to-codex-handoff',converted_bundle)]:
                sid,path=installed(cli(['import',package,'--cwd',project],home=home),home)
                calls_before=sum(block['type']=='tool_call' for event in canonical.from_codex(path)['events'] for block in event['blocks'])
                report['live']['calls_attempted']+=1
                result=live.live_call('codex',sid,home,project,env,'gpt-6.1-sol',Decimal('0.05'),PROMPT)
                fields=live.checks(result['answer'],FACTS) if not result['provider_failure'] else list(FACTS)
                after=canonical.from_codex(path)
                calls_after=sum(block['type']=='tool_call' for event in after['events'] for block in event['blocks'])
                models=sorted({record['payload']['model'] for record in canonical.read_jsonl(path)
                    if record.get('type')=='turn_context' and isinstance(record.get('payload',{}).get('model'),str)})
                safe={'case':name,'passed':not(result['provider_failure'] or fields or result['tool_calls'] or calls_after!=calls_before),
                    'fields_checked':list(FACTS),'failed_fields':fields,'tools_executed':result['tool_calls']+max(0,calls_after-calls_before),
                    'answer':live.answer_json(result['answer']) if not fields else None,'usage':result['usage'],'observed_models':models}
                report['live']['results'].append(safe)
                if result['provider_failure']:
                    break  # No retry loops.
            report['live']['status']='passed' if len(report['live']['results'])==2 and all(item['passed'] for item in report['live']['results']) else 'failed'
            assert digest(source)==original_hash and digest(claude_source)==claude_hash
    titles = {'export':'Export a synthetic Codex conversation', 'inspect':'Inspect before installing',
              'import':'Continue from a new native identity', 'convert':'Bring supported Claude history into Codex'}
    for step in report['steps']:
        step['title']=titles[step['id']]
        step['verified']=step['passed']
        step['output']=[step['result']]
    report['checks']={'source_unchanged':report['offline']['source_hashes_unchanged'],
        'zip_checksum_valid':report['steps'][0]['evidence']['manifest_checksum_valid'],
        'inspection_did_not_install':True, 'new_identity':True, 'historical_facts_preserved':True,
        'claude_to_codex_history_preserved':True,'tool_phase_retained':True,
        'isolated_homes':True,'synthetic_only':True}
    if report['live'].get('results'):
        report['live']['model']='gpt-6.1-sol'
        report['live']['routes']=[item['case'] for item in report['live']['results']]
        report['live']['input_tokens']=sum(item['usage'].get('input_tokens',0) for item in report['live']['results'])
        report['live']['output_tokens']=sum(item['usage'].get('output_tokens',0) for item in report['live']['results'])
        report['live']['answer']=report['live']['results'][-1]['answer']
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'offline':report['offline']['status'],'steps':len(report['steps']),
                      'live':report['live']['status'],'live_attempts':report['live']['calls_attempted']}))
    if report['live']['status']=='failed':
        raise SystemExit(1)


if __name__=='__main__':
    main()
