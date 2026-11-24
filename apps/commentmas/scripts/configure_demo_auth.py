"""Enable anonymous Firebase sessions for the demo; requires project billing."""
import argparse
import json
import subprocess
import urllib.error
import urllib.request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--project', required=True)
    args = parser.parse_args()
    token = subprocess.check_output(['gcloud', 'auth', 'print-access-token'], text=True).strip()
    headers = {'Authorization': 'Bearer '+token, 'x-goog-user-project': args.project,
               'Content-Type': 'application/json'}

    def call(method, path, body=None):
        request = urllib.request.Request('https://identitytoolkit.googleapis.com/'+path,
            method=method, headers=headers,
            data=json.dumps(body).encode() if body is not None else None)
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)

    path = 'admin/v2/projects/'+args.project+'/config'
    try:
        config = call('GET', path)
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
        call('POST', 'v2/projects/'+args.project+'/identityPlatform:initializeAuth', {})
        config = call('GET', path)
    result = call('PATCH', path+'?updateMask=signIn.anonymous.enabled', {'signIn': {'anonymous': {'enabled': True}}})
    print('Anonymous demo sessions enabled: '+str(result['signIn']['anonymous']['enabled']))


if __name__ == '__main__':
    main()
