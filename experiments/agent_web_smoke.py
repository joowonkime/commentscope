"""Exercise the real local UI HTTP API; preserve private comparison outputs."""
import argparse
import json
from pathlib import Path
import time
from urllib.request import Request, build_opener, ProxyHandler

from commentscope.providers.local_llama import NoRedirect
from commentscope.storage import write_json_exclusive


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--question', action='append', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= len(args.question) <= 6:
        parser.error('Use 1..6 questions')
    page = Path(str(args.output) + '.html')
    if args.output.exists() or page.exists():
        parser.error('Choose a new output path')
    origin = 'http://127.0.0.1:' + str(args.port)
    opener = build_opener(ProxyHandler({}), NoRedirect())
    token = None

    def call(path, body=None):
        headers = {'Origin': origin}
        if token:
            headers['X-Session-Token'] = token
        if body is not None:
            headers['Content-Type'] = 'application/json'
        request = Request(origin + path, headers=headers,
                          data=None if body is None else json.dumps(body).encode())
        with opener.open(request, timeout=10) as response:
            return response.read()

    state = json.loads(call('/api/session', {}))
    token = state['token']
    for i, question in enumerate(args.question, 1):
        state = json.loads(call('/api/ask', {'question': question, 'request_id': f'smoke-{i}'}))
        deadline = time.monotonic() + 1800
        previous = None
        while state['job']['status'] == 'running':
            progress = {k: state['job'][k] for k in ['status', 'agent_id', 'stage', 'model_calls']}
            if progress != previous:
                print(json.dumps({'question': i, **progress}), flush=True)
                previous = progress
            if time.monotonic() > deadline:
                raise TimeoutError('Round timeout; partial private checkpoints remain in runs/agent-ui')
            time.sleep(1)
            state = json.loads(call('/api/state'))
        if state['job']['status'] != 'done':
            raise RuntimeError('Round failed: ' + state['job']['status'])
        print(json.dumps({'question': i, 'answers': [{'agent': t['agent_id'], 'status': t['status'],
              'citations': [p['evidence_id'] for p in t['points']]} for t in state['rounds'][-1]['answers']]}), flush=True)
    report = json.loads(call('/api/export.json'))
    write_json_exclusive(args.output, report)
    with page.open('xb') as stream:
        stream.write(call('/api/export.html'))
    print('Private outputs: ' + str(args.output) + ' and ' + str(page), flush=True)


if __name__ == '__main__':
    main()
