"""Point the Vercel frontend at its deployed Python API."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit

parser = argparse.ArgumentParser()
parser.add_argument('--api-url', required=True)
args = parser.parse_args()
url = urlsplit(args.api_url)
if url.scheme != 'https' or not url.hostname or url.path not in ('', '/') or url.query or url.fragment or url.username:
    raise SystemExit('Provide the HTTPS origin of the deployed API.')
config = {
    'framework': 'vite', 'buildCommand': 'npm run build', 'outputDirectory': 'dist',
    'rewrites': [
        {'source': '/api/:path*', 'destination': args.api_url.rstrip('/')+'/api/:path*'},
        {'source': '/((?!api/).*)', 'destination': '/index.html'},
    ],
    'headers': [{'source': '/(.*)', 'headers': [
        {'key': 'X-Content-Type-Options', 'value': 'nosniff'},
        {'key': 'Referrer-Policy', 'value': 'strict-origin-when-cross-origin'},
    ]}],
}
target = Path(__file__).resolve().parents[1]/'frontend/vercel.json'
target.write_text(json.dumps(config, indent=2)+'\n')
print('Vercel routing configured for the deployed API.')
