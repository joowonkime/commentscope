"""Deploy the demo API after the owner has connected project billing.

Uses the active gcloud identity. Model keys are read locally and sent to Secret
Manager via HTTPS, never command arguments or build uploads.
"""
import base64
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from llm_client import read_settings

PROJECT = 'review-agents-20261124'
REGION = 'asia-northeast3'
SERVICE = 'commentmas-api'
SA = f'{SERVICE}@{PROJECT}.iam.gserviceaccount.com'


def gcloud(*args, capture=False):
    command = ['gcloud', *args, '--project='+PROJECT, '--billing-project='+PROJECT, '--quiet']
    if capture:
        return subprocess.check_output(command, text=True).strip()
    subprocess.run([*command, '--format=none'], check=True, cwd=ROOT)


def main():
    if gcloud('billing', 'projects', 'describe', PROJECT, '--format=value(billingEnabled)', capture=True) != 'True':
        raise SystemExit('Connect billing to the project before deploying the API.')
    settings = read_settings()
    provider = settings.get('LLM_PROVIDER') or ('openai' if settings.get('OPENAI_API_KEY') else 'openrouter')
    key_name = 'OPENAI_API_KEY' if provider == 'openai' else 'OPENROUTER_API_KEY'
    gcloud('services', 'enable', 'run.googleapis.com', 'cloudbuild.googleapis.com',
           'artifactregistry.googleapis.com', 'secretmanager.googleapis.com', 'firebaserules.googleapis.com')
    subprocess.run([sys.executable, str(ROOT/'scripts/configure_demo_auth.py'), '--project', PROJECT], check=True)
    subprocess.run([sys.executable, str(ROOT/'scripts/prepare_deploy.py')], check=True)
    accounts = gcloud('iam', 'service-accounts', 'list', '--filter=email:'+SA, '--format=value(email)', capture=True)
    if not accounts:
        gcloud('iam', 'service-accounts', 'create', SERVICE, '--display-name=CommentMAS API')
    for role in ('roles/datastore.user', 'roles/firebaseauth.viewer'):
        gcloud('projects', 'add-iam-policy-binding', PROJECT, '--member=serviceAccount:'+SA, '--role='+role,
               '--condition=None')
    build_sa = 'commentmas-build@'+PROJECT+'.iam.gserviceaccount.com'
    if not gcloud('iam', 'service-accounts', 'list', '--filter=email:'+build_sa, '--format=value(email)', capture=True):
        gcloud('iam', 'service-accounts', 'create', 'commentmas-build', '--display-name=CommentMAS Build')
    for role in ('roles/run.builder', 'roles/serviceusage.serviceUsageConsumer'):
        gcloud('projects', 'add-iam-policy-binding', PROJECT, '--member=serviceAccount:'+build_sa, '--role='+role, '--condition=None')
    token = gcloud('auth', 'print-access-token', capture=True)

    def call(method, url, body):
        request = urllib.request.Request(url, method=method, data=json.dumps(body).encode(),
            headers={'Authorization': 'Bearer '+token, 'Content-Type': 'application/json', 'x-goog-user-project': PROJECT})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            # Error payloads may contain submitted values; do not print them.
            raise RuntimeError(f'Cloud configuration request failed with HTTP {error.code}.') from None

    model_secret = 'commentmas-'+provider+'-key'
    secrets_to_bind = []
    for name, secret in ((key_name, model_secret), ('YOUTUBE_API_KEY', 'commentmas-youtube-key')):
        exists = gcloud('secrets', 'list', '--filter=name:'+secret, '--format=value(name)', capture=True)
        value = settings.get(name)
        if not exists and not value:
            if name == key_name:
                raise SystemExit(f'Set {name} or create the server secret {secret} for the selected provider.')
            continue
        if not exists:
            gcloud('secrets', 'create', secret, '--replication-policy=automatic')
        if value:
            call('POST', f'https://secretmanager.googleapis.com/v1/projects/{PROJECT}/secrets/{secret}:addVersion',
                 {'payload': {'data': base64.b64encode(value.encode()).decode()}})
        gcloud('secrets', 'add-iam-policy-binding', secret, '--member=serviceAccount:'+SA,
               '--role=roles/secretmanager.secretAccessor', '--condition=None')
        secrets_to_bind.append(f'{name}={secret}:latest')
    ruleset = call('POST', f'https://firebaserules.googleapis.com/v1/projects/{PROJECT}/rulesets',
                  {'source': {'files': [{'name': 'firestore.rules', 'content': (ROOT/'firestore.rules').read_text()}]}})
    release = {'name': f'projects/{PROJECT}/releases/cloud.firestore', 'rulesetName': ruleset['name']}
    try:
        call('PATCH', 'https://firebaserules.googleapis.com/v1/'+release['name'], {'release': release})
    except RuntimeError:
        call('POST', f'https://firebaserules.googleapis.com/v1/projects/{PROJECT}/releases', release)
    env = {'FIREBASE_PROJECT_ID': PROJECT, 'LLM_PROVIDER': provider,
           'ALLOWED_ORIGINS': settings.get('ALLOWED_ORIGINS') or 'https://commentmas.vercel.app'}
    for key in ('OPENAI_MODEL', 'OPENAI_REASONING_EFFORT', 'OPENROUTER_MODEL', 'VIDEO_COMMENT_LIMIT'):
        if settings.get(key):
            env[key] = settings[key]
    # Hosting contains only public runtime configuration. Secrets use bindings.
    destination = ROOT/'.deploy'
    destination.mkdir(exist_ok=True)
    env_file = destination/'backend-env.json'
    env_file.write_text(json.dumps(env))
    gcloud('run', 'deploy', SERVICE, '--source=.', '--region='+REGION, '--service-account='+SA,
           '--build-service-account=projects/'+PROJECT+'/serviceAccounts/'+build_sa,
           '--allow-unauthenticated', '--no-cpu-throttling', '--min=0', '--max=1', '--concurrency=40',
           '--memory=512Mi', '--timeout=3600', '--env-vars-file='+str(env_file),
           '--update-secrets='+','.join(secrets_to_bind))
    url = gcloud('run', 'services', 'describe', SERVICE, '--region='+REGION, '--format=value(status.url)', capture=True)
    subprocess.run([sys.executable, str(ROOT/'scripts/write_vercel_config.py'), '--api-url', url], check=True)
    print('API deployed: '+url)
    print('Deploy the frontend to the Vercel origin configured in ALLOWED_ORIGINS.')


if __name__ == '__main__':
    main()
