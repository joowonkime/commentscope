"""Deploy the Vercel demo using public Firebase web configuration only."""
import argparse
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--cli-path', help='Optional path to an installed Vercel dist/vc.js')
parser.add_argument('--scope', default='angelas-projects-91a6cf82')
args = parser.parse_args()
cli = ['node', args.cli_path] if args.cli_path else ['npx', '--yes', '--package=vercel@66.6.0', 'vercel']
frontend = ROOT/'frontend'
if not (frontend/'vercel.json').exists():
    raise SystemExit('Deploy the API and configure Vercel routing first.')
config = dict(line.split('=', 1) for line in (frontend/'.env.production.local').read_text().splitlines() if '=' in line)
names = ('VITE_FIREBASE_API_KEY', 'VITE_FIREBASE_AUTH_DOMAIN', 'VITE_FIREBASE_PROJECT_ID', 'VITE_FIREBASE_APP_ID')
if not all(config.get(name) for name in names):
    raise SystemExit('Firebase public web configuration is incomplete.')
command = [*cli, 'deploy', '--prod', '--yes', '--scope='+args.scope]
for name in names:
    command.extend(['--build-env', name+'='+config[name]])
subprocess.run(command, cwd=frontend, check=True)
