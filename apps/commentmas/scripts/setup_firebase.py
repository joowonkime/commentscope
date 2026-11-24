"""Initialize the selected Firebase project using the active gcloud account.

OAuth tokens stay in memory. This does not configure billing or Google OAuth.
"""
import argparse
import json
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--project', required=True)
    parser.add_argument('--name', default='YJ-MAS')
    parser.add_argument('--app-name', default='CommentMAS')
    args = parser.parse_args()
    token = subprocess.check_output(['gcloud', 'auth', 'print-access-token'], text=True).strip()

    def call(method, path, value=None):
        request = urllib.request.Request('https://firebase.googleapis.com/v1beta1/'+path,
            data=json.dumps(value).encode() if value is not None else None, method=method,
            headers={'Authorization': 'Bearer '+token, 'Content-Type': 'application/json', 'x-goog-user-project': args.project})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            body = json.load(error)
            raise RuntimeError(f"Firebase {error.code}: {body.get('error', {}).get('message', 'Request failed')}") from None

    def wait(operation):
        while not operation.get('done'):
            time.sleep(2)
            operation = call('GET', operation['name'])
        if 'error' in operation:
            raise RuntimeError(operation['error'].get('message', 'Firebase setup failed.'))
        return operation.get('response', {})

    project = 'projects/'+args.project
    try:
        call('GET', project)
    except RuntimeError as error:
        if '404' not in str(error):
            raise
        wait(call('POST', project+':addFirebase', {}))
    try:
        call('PATCH', project+'?updateMask=displayName', {'displayName': args.name})
        print('Firebase display name: '+args.name, flush=True)
    except RuntimeError as error:
        print(str(error), flush=True)
    apps = call('GET', project+'/webApps').get('apps', [])
    app = next((app for app in apps if app.get('displayName') == args.app_name), None)
    if app is None:
        app = wait(call('POST', project+'/webApps', {'displayName': args.app_name}))
    config = call('GET', app['name']+'/config')
    target = Path(__file__).resolve().parents[1]/'frontend/.env.production.local'
    fields = {'VITE_FIREBASE_API_KEY': config['apiKey'], 'VITE_FIREBASE_AUTH_DOMAIN': config['authDomain'],
              'VITE_FIREBASE_PROJECT_ID': config['projectId'], 'VITE_FIREBASE_APP_ID': config['appId']}
    target.write_text(''.join(f'{key}={value}\n' for key, value in fields.items()))
    print('Firebase web app registered; frontend environment written (values hidden).', flush=True)


if __name__ == '__main__':
    main()
