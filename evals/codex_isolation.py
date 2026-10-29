"""Run the installed Codex binary in a fresh, explicit Bubblewrap filesystem."""
import json
import os
import subprocess
from pathlib import Path

MODEL = 'gpt-6-astra'
CONFIG = '''model = "gpt-6-astra"
model_reasoning_effort = "medium"
service_tier = "priority"
project_doc_max_bytes = 0
[plugins._default]
enabled = false
[skills.bundled]
enabled = false
[cloud.skills]
enabled = false
[features]
apps = false
remote_plugin = false
recommended_plugins = false
enable_mcp_apps = false
memories = false
[memories]
generate_memories = false
use_memories = false
'''


def installation(tool):
    # Resolve mise's installation, not its shim; never inherit the host PATH.
    return Path(subprocess.check_output(['mise', 'where', tool], text=True).strip()).resolve()


class Isolated:
    def __init__(self, root, corpus, plugin=None, cache=None):
        self.root, self.corpus, self.plugin = Path(root), Path(corpus), plugin
        self.cache = cache
        self.frozen = False
        self.home = self.root / 'home'
        self.work = self.root / 'work'
        (self.home / '.codex').mkdir(parents=True, exist_ok=True)
        self.work.mkdir(parents=True, exist_ok=True)
        self.codex = installation('codex')
        self.uv = next(installation('uv').rglob('uv')).resolve().parent

    def command(self, args):
        home = Path.home()
        dns = Path('/etc/resolv.conf').resolve()
        mounts = ['bwrap', '--ro-bind', '/usr', '/usr', '--symlink', 'usr/bin', '/bin',
                  '--symlink', 'usr/lib', '/lib', '--dir', '/etc',
                  '--ro-bind', '/etc/ssl', '/etc/ssl',
                  '--ro-bind', '/etc/passwd', '/etc/passwd',
                  '--ro-bind', '/etc/group', '/etc/group',
                  '--ro-bind', '/etc/nsswitch.conf', '/etc/nsswitch.conf',
                  '--symlink', str(dns), '/etc/resolv.conf',
                  '--ro-bind', str(dns), str(dns), '--proc', '/proc', '--dev', '/dev',
                  '--tmpfs', '/tmp', '--bind', str(self.home), str(home),
                  '--ro-bind', str(home / '.codex/auth.json'), str(home / '.codex/auth.json'),
                  '--ro-bind', str(self.codex), '/opt/codex', '--ro-bind', str(self.uv), '/opt/uv',
                  '--bind', str(self.work), '/workspace',
                  '--ro-bind', str(self.corpus), '/workspace/docs']
        if Path('/lib64').exists():
            mounts += ['--ro-bind', '/lib64', '/lib64']
        if self.frozen:
            for protected in ['plugins', 'config.toml']:
                mounts += ['--ro-bind', str(self.home / '.codex' / protected), str(home / '.codex' / protected)]
        if self.cache:
            Path(self.cache).mkdir(parents=True, exist_ok=True)
            mounts += ['--bind', str(self.cache), str(home / '.cache')]
        if self.plugin:
            mounts += ['--ro-bind', str(self.plugin), '/plugin']
        return mounts + ['--chdir', '/workspace', '--unshare-pid', '--unshare-ipc', '--unshare-uts',
                         '--die-with-parent', '/opt/codex/bin/codex', *args]

    def invoke(self, args, text=None, timeout=1200):
        return subprocess.run(self.command(args), input=text, capture_output=True, text=True, timeout=timeout,
            env={'HOME': str(Path.home()), 'PATH': '/opt/codex/bin:/opt/codex/codex-path:/opt/uv:/usr/bin:/bin',
                 'LANG': 'C.UTF-8'})

    def prepare(self):
        (self.home / '.codex/config.toml').write_text(CONFIG)
        if self.plugin:
            for args in [['plugin', 'marketplace', 'add', '/plugin', '--json'],
                         ['plugin', 'add', 'rankgrep@rankgrep', '--json']]:
                r = self.invoke(args)
                if r.returncode:
                    raise RuntimeError(r.stderr)
        (self.home / '.codex/plugins').mkdir(exist_ok=True)
        self.assert_local_plugins()
        self.frozen = True
        r = self.invoke(['--dangerously-bypass-approvals-and-sandbox', 'debug', 'prompt-input', 'ISOLATION_CHECK'])
        if r.returncode:
            raise RuntimeError(r.stderr)
        context = json.loads(r.stdout)
        texts = '\n'.join(c.get('text', '') for m in context for c in m.get('content', []))
        catalogs = texts.split('<skills_instructions>')[1:]
        entries = [line for block in catalogs for line in block.split('</skills_instructions>')[0].splitlines()
                   if line.startswith('- ') and '(file:' in line]
        if len(entries) != int(bool(self.plugin)) or any(not e.startswith('- rankgrep:rankgrep:') for e in entries):
            raise ValueError(f'unexpected skills: {entries}')
        tools = [{'tools': m['tools']} for m in context if m.get('type') == 'additional_tools']
        if any(t['name'] not in ('functions', 'clock', 'collaboration') for m in tools for t in m['tools']):
            raise ValueError('unexpected tool namespace')
        for forbidden in ['full-send', 'takeover', 't3_code', 'google-drive', 'ANTHROPIC_API_KEY']:
            if forbidden in texts:
                raise ValueError(f'host context leaked: {forbidden}')
        (self.root / 'context.json').write_text(json.dumps(context, indent=2))
        return {'skills': entries, 'tools': tools, 'config': (self.home / '.codex/config.toml').read_text()}

    def assert_local_plugins(self):
        directory = self.home / '.codex/plugins'
        if directory.exists() and {p.name for p in directory.iterdir()} - {'cache'}:
            raise ValueError('unexpected plugin staging or metadata')
        cache = directory / 'cache'
        names = {p.name for p in cache.iterdir()} if cache.exists() else set()
        if names - ({'rankgrep'} if self.plugin else set()):
            raise ValueError(f'unexpected plugin installation: {names}')
        skills = list(cache.rglob('SKILL.md')) if cache.exists() else []
        if len(skills) != int(bool(self.plugin)):
            raise ValueError('unexpected installed skills')
        if self.plugin and skills[0].read_bytes() != (Path(self.plugin) / 'skills/rankgrep/SKILL.md').read_bytes():
            raise ValueError('installed skill differs from supplied plugin')

    def execute(self, prompt):
        r = self.invoke(['exec', '--skip-git-repo-check', '--dangerously-bypass-approvals-and-sandbox',
                         '--json', '-'], prompt)
        (self.root / 'stdout.jsonl').write_text(r.stdout)
        (self.root / 'stderr.txt').write_text(r.stderr)
        events = [json.loads(l) for l in r.stdout.splitlines() if l.startswith('{')]
        rollouts = list((self.home / '.codex/sessions').rglob('*.jsonl'))
        if len(rollouts) != 1:
            raise ValueError(f'expected one fresh session, got {len(rollouts)}')
        raw = [json.loads(l) for l in rollouts[0].read_text().splitlines()]
        contexts = [e['payload'] for e in raw if e['type'] == 'turn_context']
        if not contexts or any(c['model'] != MODEL or c['effort'] != 'medium' for c in contexts):
            raise ValueError('model/effort mismatch')
        self.assert_local_plugins()
        # Inspect actual session messages too: remote synchronization can finish after preview.
        actual_entries = []
        for event in raw:
            payload = event.get('payload', {})
            if event['type'] == 'response_item' and payload.get('role') == 'developer':
                for block in payload.get('content', []):
                    text = block.get('text', '')
                    for catalog in text.split('<skills_instructions>')[1:]:
                        entries = [line for line in catalog.split('</skills_instructions>')[0].splitlines()
                                   if line.startswith('- ') and '(file:' in line]
                        actual_entries.extend(entries)
        if len(actual_entries) != int(bool(self.plugin)) or any(not e.startswith('- rankgrep:rankgrep:') for e in actual_entries):
            raise ValueError('unexpected skills in actual session')
        return r.returncode, events, raw
