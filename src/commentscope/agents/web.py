"""Loopback-only, single-inference-lane comparison UI. Not a hosted service."""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import threading
import time
from uuid import uuid4

from commentscope.agents.demo import render
from commentscope.agents.profiles import load_bundle, require_live
from commentscope.agents.runtime import AgentSession, local_generate, prompt_metadata, schema, AUDIT_SCHEMA, AUDIT_SYSTEM
from commentscope.factory.claim_clusters import sha
from commentscope.storage import write_json_exclusive

ROOT = Path(__file__).parent
SESSION_TTL = 3600
MAX_SESSIONS = 8


class WebError(Exception):
    def __init__(self, status, code):
        self.status, self.code = status, code


def public_turn(turn):
    """Never send rejected drafts, raw auditor text or unaudited limits to the live UI."""
    return {key: deepcopy(turn[key]) for key in
            ('agent_id', 'status', 'reason', 'answerability', 'points', 'human_approved', 'semantic_guarantee')} | {
        'generation_attempts': len(turn['attempts']),
        'audit_requests': sum(len(a['audit']) for a in turn['attempts'])}


class ComparisonApp:
    def __init__(self, bundle, bundle_hash, session_dir, metadata, *, provider=local_generate, revalidate=None):
        self.bundle = deepcopy(bundle)
        require_live(bundle['expires_at'])
        self.bundle_hash = bundle_hash
        self.session_dir = Path(session_dir)
        self.metadata = metadata
        self.provider = provider
        self.revalidate = revalidate or (lambda: require_live(self.bundle['expires_at']))
        self.lock = threading.RLock()
        self.sessions = {}
        self.busy = False

    def _report(self):
        return {'artifact_kind': 'development-agent-comparison-0.1',
                'created_at': datetime.now(timezone.utc).isoformat(), 'bundle': deepcopy(self.bundle),
                'bundle_sha256': self.bundle_hash, 'expires_at': self.bundle['expires_at'],
                'runtime': {**self.metadata, 'metadata_source': 'operator_supplied_not_attested',
                            'temperature': 0, 'seed': 407, 'max_tokens': 1200,
                            'max_generation_attempts': 2, 'max_session_questions': 6},
                'prompts': prompt_metadata(), 'code_sha256': sha(ROOT / 'runtime.py'),
                'web_code_sha256': sha(Path(__file__)),
                'generation_schemas': {a['agent_id']: schema([c['evidence_id'] for c in a['evidence']])
                                       for a in self.bundle['agents']},
                'auditor_schema': AUDIT_SCHEMA, 'generation_contract': 'answerability-branches-0.2',
                'human_approved': False, 'accepted_perspectives': 0, 'rounds': []}

    def _live(self):
        try:
            require_live(self.bundle['expires_at'])
        except ValueError:
            raise WebError(410, 'dataset_expired') from None

    def _get(self, token):
        self._live()
        s = self.sessions.get(token)
        if s is None:
            raise WebError(401, 'session_missing')
        if time.monotonic() - s['touched'] > SESSION_TTL and s['job']['status'] != 'running':
            del self.sessions[token]
            raise WebError(401, 'session_expired')
        s['touched'] = time.monotonic()
        return s

    def create(self):
        with self.lock:
            self._live()
            self.sessions = {k: s for k, s in self.sessions.items()
                             if s['job']['status'] == 'running' or time.monotonic() - s['touched'] <= SESSION_TTL}
            if len(self.sessions) >= MAX_SESSIONS:
                raise WebError(429, 'session_capacity')
            token = secrets.token_urlsafe(32)
            report = self._report()
            run_dir = self.session_dir / str(uuid4())
            write_json_exclusive(run_dir / 'manifest.json', report)
            self.sessions[token] = {'report': report, 'run_dir': run_dir,
                                    'agents': [AgentSession(a) for a in self.bundle['agents']],
                                    'job': {'status': 'idle'}, 'requests': {}, 'touched': time.monotonic()}
            return {'token': token, **self._state(self.sessions[token])}

    def _state(self, s):
        report = s['report']
        return {'bundle': deepcopy(self.bundle), 'runtime': deepcopy(report['runtime']),
                'rounds': [{'question': r['question'], 'answers': [public_turn(t) for t in r['answers']]}
                           for r in report['rounds']],
                'job': deepcopy(s['job']), 'remaining_questions': 6 - len(report['rounds']),
                'can_ask': bool(self.bundle['agents']) and not self.busy and len(report['rounds']) < 6,
                'human_approved': False, 'accepted_perspectives': 0}

    def state(self, token):
        with self.lock:
            return self._state(self._get(token))

    def reset(self, token):
        with self.lock:
            s = self._get(token)
            if s['job']['status'] == 'running':
                raise WebError(409, 'inference_busy')
            # Persisted research logs are deliberately not deleted by a UI reset.
            del self.sessions[token]
            try:
                return self.create()
            except Exception:
                self.sessions[token] = s
                raise

    def ask(self, token, question, request_id):
        if not isinstance(question, str) or not question.strip() or len(question) > 1000:
            raise WebError(400, 'invalid_question')
        if not isinstance(request_id, str) or not 1 <= len(request_id) <= 80 or not request_id.isascii() or not all(c.isalnum() or c == '-' for c in request_id):
            raise WebError(400, 'invalid_request_id')
        with self.lock:
            s = self._get(token)
            if not self.bundle['agents']:
                raise WebError(409, 'no_agents')
            if request_id in s['requests']:
                if s['requests'][request_id] != question:
                    raise WebError(409, 'request_id_conflict')
                return self._state(s)
            if self.busy:
                raise WebError(409, 'inference_busy')
            if len(s['report']['rounds']) >= 6 or len(s['requests']) >= 12:
                raise WebError(409, 'question_limit')
            try:
                self.revalidate()
            except Exception:
                raise WebError(409, 'source_validation_failed') from None
            job_id = str(uuid4())
            write_json_exclusive(s['run_dir'] / (job_id + '.request.json'),
                                 {'request_id': request_id, 'question': question,
                                  'bundle_sha256': self.bundle_hash, 'expires_at': self.bundle['expires_at']})
            s['requests'][request_id] = question
            s['job'] = {'status': 'running', 'request_id': request_id,
                        'agent_id': None, 'stage': 'starting', 'model_calls': 0}
            self.busy = True
            threading.Thread(target=self._run, args=(s, question, job_id), daemon=True).start()
            return self._state(s)

    def _run(self, s, question, job_id):
        histories = [deepcopy(a.history) for a in s['agents']]
        round_ = {'question': question, 'answers': []}
        try:
            for agent in s['agents']:
                require_live(self.bundle['expires_at'])

                def tracked(system, data, response_schema):
                    require_live(self.bundle['expires_at'])
                    with self.lock:
                        s['job'].update(agent_id=agent.profile['agent_id'],
                                        stage='auditing' if system.startswith(AUDIT_SYSTEM) else 'generating')
                        s['job']['model_calls'] += 1
                    return self.provider(system, data, response_schema)

                agent.provider = tracked
                turn = agent.ask(question)
                round_['answers'].append(turn)
                write_json_exclusive(s['run_dir'] / (job_id + '.' + agent.profile['agent_id'] + '.json'),
                                     {'turn': turn, 'bundle_sha256': self.bundle_hash,
                                      'expires_at': self.bundle['expires_at']})
            require_live(self.bundle['expires_at'])
            self.revalidate()
            write_json_exclusive(s['run_dir'] / (job_id + '.round.json'), round_)
            with self.lock:
                s['report']['rounds'].append(round_)
                s['job'].update(status='done', stage='complete')
        except Exception:
            # Preserve source/audit checkpoints; never publish a partial/inconsistent round.
            try:
                write_json_exclusive(s['run_dir'] / (job_id + '.failure.json'),
                                     {'status': 'error', 'question': question,
                                      'completed_agents': [t['agent_id'] for t in round_['answers']],
                                      'bundle_sha256': self.bundle_hash, 'expires_at': self.bundle['expires_at'],
                                      'error': 'round_failed_check_local_inputs_or_storage'})
            except Exception:
                pass  # Storage failure cannot be repaired by inventing a successful record.
            with self.lock:
                for a, history in zip(s['agents'], histories):
                    a.history = history
                s['job'].update(status='error', stage='failed', error='round_failed_check_local_inputs_or_storage')
        finally:
            with self.lock:
                self.busy = False
                s['touched'] = time.monotonic()

    def export(self, token, kind):
        with self.lock:
            s = self._get(token)
            if s['job']['status'] == 'running':
                raise WebError(409, 'inference_busy')
            report = deepcopy(s['report'])
        if kind == 'html':
            return render(report).encode('utf-8')
        return json.dumps(report, ensure_ascii=False, indent=2).encode('utf-8')


class ComparisonServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, app, port):
        self.app = app
        super().__init__(('127.0.0.1', port), ComparisonHandler)
        actual = self.server_address[1]
        self.hosts = {f'127.0.0.1:{actual}', f'localhost:{actual}'}


class ComparisonHandler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass  # Questions, session tokens and source text must not enter access logs.

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def reply(self, status, content, content_type='application/json; charset=utf-8', filename=None):
        data = content if isinstance(content, bytes) else json.dumps(content, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        if filename:
            self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(data)

    def _guard(self, mutation=False):
        host = self.headers.get('Host')
        if host not in self.server.hosts:
            raise WebError(403, 'invalid_host')
        origin = self.headers.get('Origin')
        if (origin is not None and origin != 'http://' + host) or (mutation and origin is None):
            raise WebError(403, 'invalid_origin')
        if self.headers.get('Sec-Fetch-Site') not in (None, 'same-origin', 'none'):
            raise WebError(403, 'cross_origin_request')

    def _handle(self, mutation=False):
        try:
            self._guard(mutation)
            token = self.headers.get('X-Session-Token', '')
            app = self.server.app
            if not mutation:
                assets = {'/': ('comparison.html', 'text/html; charset=utf-8'),
                          '/app.js': ('comparison.js', 'text/javascript; charset=utf-8'),
                          '/app.css': ('comparison.css', 'text/css; charset=utf-8')}
                if self.path in assets:
                    name, kind = assets[self.path]
                    return self.reply(200, (ROOT / name).read_bytes(), kind)
                if self.path == '/api/state':
                    return self.reply(200, app.state(token))
                if self.path in ('/api/export.json', '/api/export.html'):
                    kind = self.path.rsplit('.', 1)[1]
                    return self.reply(200, app.export(token, kind),
                                      'text/html; charset=utf-8' if kind == 'html' else 'application/json; charset=utf-8',
                                      'commentscope-private-session.' + kind)
                raise WebError(404, 'not_found')
            if self.headers.get('Transfer-Encoding') or self.headers.get('Content-Type') != 'application/json':
                raise WebError(415, 'json_required')
            try:
                size = int(self.headers.get('Content-Length', '-1'))
                if not 0 < size <= 8192:
                    raise ValueError()
                body = json.loads(self.rfile.read(size))
                if not isinstance(body, dict):
                    raise ValueError()
            except (ValueError, UnicodeError):
                raise WebError(400, 'invalid_body') from None
            if self.path == '/api/session' and body == {}:
                return self.reply(201, app.create())
            if self.path == '/api/reset' and body == {}:
                return self.reply(201, app.reset(token))
            if self.path == '/api/ask' and set(body) == {'question', 'request_id'}:
                return self.reply(202, app.ask(token, body['question'], body['request_id']))
            raise WebError(400, 'invalid_request')
        except WebError as exc:
            self.reply(exc.status, {'error': exc.code})
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass
        except Exception:
            self.reply(500, {'error': 'local_server_error'})

    def do_GET(self):
        self._handle()

    def do_POST(self):
        self._handle(mutation=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('snapshot', 'reviewed', 'bundle'):
        parser.add_argument(name)
    parser.add_argument('--allow-unapproved', action='store_true')
    parser.add_argument('--automatic', action='store_true', help='Second input is automatic factory report, not reviewed input')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--session-dir', type=Path, default=Path('runs/agent-ui'))
    for name in ('model-label', 'model-revision', 'runtime'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error('Invalid port')

    def read_bundle():
        if args.automatic:
            from commentscope.factory.automatic import load_bundle as load_automatic
            return load_automatic(args.snapshot, args.reviewed, args.bundle)
        return load_bundle(args.snapshot, args.reviewed, args.bundle, allow_unapproved=args.allow_unapproved)

    def verified():
        current = read_bundle()
        if current != bundle or sha(args.bundle) != bundle_hash:
            raise ValueError('Input changed; restart with the new bundle')

    bundle = read_bundle()
    bundle_hash = sha(args.bundle)
    app = ComparisonApp(bundle, bundle_hash, args.session_dir,
                        {'model': args.model_label, 'model_revision': args.model_revision, 'runtime': args.runtime},
                        revalidate=verified)
    server = ComparisonServer(app, args.port)
    print(f'CommentScope local UI: http://127.0.0.1:{server.server_address[1]}', flush=True)
    print('Development only. Private source/audit logs: ' + str(args.session_dir.resolve()), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
