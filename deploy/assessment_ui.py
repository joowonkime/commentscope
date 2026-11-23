"""Package a committed assessment UI or activate it in nginx's public-only directory."""
import argparse
from http.client import HTTPSConnection
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from urllib.parse import quote, urlsplit

ASSETS = ('mvp.html', 'mvp.js', 'mvp.css')
SAMPLE = 'opinion-samples.json'
PUBLIC_ROOT = Path('/srv/commentscope-ui')
PRODUCT = 'src/commentscope/product/'


def package(revision, destination):
    repo = Path(__file__).resolve().parents[1]
    commit = subprocess.check_output(
        ['git', 'rev-parse', '--verify', '--end-of-options', revision + '^{commit}'], cwd=repo, text=True
    ).strip()
    destination.mkdir(parents=True, exist_ok=False)
    checksums = {}
    reports = subprocess.check_output(['git', 'ls-tree', '--name-only', commit, '--', PRODUCT + SAMPLE], cwd=repo)
    for name in (*ASSETS, SAMPLE) if reports else ASSETS:
        data = subprocess.check_output(['git', 'show', commit + ':' + PRODUCT + name], cwd=repo)
        (destination / name).write_bytes(data)
        checksums[name] = {'after': sha256(data).hexdigest()}
    (destination / 'static-manifest.json').write_text(
        json.dumps({'commit': commit, 'files': checksums}, indent=2) + '\n', encoding='utf-8'
    )
    return commit


def activate(source, root=PUBLIC_ROOT):
    import fcntl  # The nginx evaluation host runs Linux.
    manifest = json.loads((source / 'static-manifest.json').read_text(encoding='utf-8'))
    commit = manifest['commit']
    names = set(manifest['files'])
    if not re.fullmatch('[0-9a-f]{40}', commit) or names not in (set(ASSETS), {*ASSETS, SAMPLE}):
        raise ValueError('Expected a Git commit and known public UI assets')
    files = {name: (source / name).read_bytes() for name in names}
    for name, data in files.items():
        if sha256(data).hexdigest() != manifest['files'][name]['after']:
            raise ValueError('UI checksum mismatch for ' + name)
    releases = root / 'releases'
    releases.mkdir(parents=True, exist_ok=True)
    with (root / '.publish.lock').open('a') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        target = releases / commit
        if target.exists():
            if any((target / name).read_bytes() != data for name, data in files.items()):
                raise ValueError('Existing release contents differ from the requested commit')
        else:
            stage = Path(tempfile.mkdtemp(dir=releases))
            try:
                for name, data in files.items():
                    (stage / name).write_bytes(data)
                    (stage / name).chmod(0o644)
                (stage / 'release.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
                stage.chmod(0o755)
                os.rename(stage, target)
            finally:
                if stage.exists():
                    shutil.rmtree(stage)
        pending = root / '.current-next'
        pending.unlink(missing_ok=True)
        pending.symlink_to(Path('releases') / commit)
        os.replace(pending, root / 'current')
    return commit



def verify(origin, package_directory, browser_state):
    url = urlsplit(origin)
    if url.scheme != 'https' or not url.hostname or url.username or url.password or url.path or url.query or url.fragment:
        raise ValueError('Supply the exact public HTTPS origin')
    saved = json.loads(browser_state.read_text(encoding='utf-8'))
    storage = next((o['localStorage'] for o in saved['origins'] if o['origin'] == origin), [])
    credential = next((item for item in storage if item['name'] == 'commentscope-mvp-session'), None)
    if not credential:
        raise ValueError('Provide the private browser state for an existing QA session on this origin')
    access = json.loads(credential['value'])
    manifest = json.loads((package_directory / 'static-manifest.json').read_text(encoding='utf-8'))
    routes = {'mvp.html': '/mvp', 'mvp.js': '/mvp/app.js', 'mvp.css': '/mvp/app.css'}
    if SAMPLE in manifest['files']:
        routes[SAMPLE] = '/mvp/opinion-samples.json'
    connection = HTTPSConnection(url.hostname, url.port or 443, timeout=15)
    def get(path, *, session=False):
        headers = {'X-Session-Token': access['token']} if session else {}
        connection.request('GET', path, headers=headers)
        response = connection.getresponse()
        body = response.read()
        if response.status != 200:
            raise ValueError(f'Public release verification returned HTTP {response.status}')
        return body
    try:
        for asset, route in routes.items():
            if sha256(get(route)).hexdigest() != manifest['files'][asset]['after']:
                raise ValueError('Public UI checksum mismatch for ' + asset)
        status = json.loads(get('/api/v1/analyses'))['generation_status']
        base = '/api/v1/sessions/' + quote(access['session_id'], safe='')
        review = json.loads(get(base, session=True))
        sources = (source for p in review['analysis']['perspectives'] for source in p['source_ids'])
        source = next(sources, None)
        if not source:
            raise ValueError('Select a registered QA analysis that has an original comment')
        evidence = json.loads(get(base + '/sources/' + quote(source, safe=''), session=True))
        if evidence.get('id') != source or not evidence.get('text', '').strip():
            raise ValueError('Public original-comment lookup did not return the cited evidence')
    finally:
        connection.close()
    return f"UI {manifest['commit']} verified; existing session and original comment readable; generation {status}"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    pack = commands.add_parser('package')
    pack.add_argument('revision')
    pack.add_argument('destination', type=Path)
    publish = commands.add_parser('activate')
    publish.add_argument('source', type=Path)
    check = commands.add_parser('verify')
    check.add_argument('origin')
    check.add_argument('package_directory', type=Path)
    check.add_argument('browser_state', type=Path)
    args = parser.parse_args()
    if args.command == 'package':
        print(package(args.revision, args.destination))
    elif args.command == 'activate':
        print(activate(args.source))
    else:
        print(verify(args.origin, args.package_directory, args.browser_state))


if __name__ == '__main__':
    main()
