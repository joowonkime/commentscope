"""Product state machine for a sealed automatic debate and its follow-up room."""
from copy import deepcopy

from commentscope.agents import debate_synthesis as agreement, seed_policy
from commentscope.agents.debate_contracts import MAX_GENERATION_TOKENS, VERSION
from commentscope.agents.synthesis_agent import compile_agent
from commentscope.agents.structured_debate_runtime import opening_context, turn
from commentscope.agents.web import WebError
from commentscope.factory.automatic_contract import digest
from commentscope.factory.fact_checks import live
from commentscope.product import debate_store
from commentscope.product.debate_execution import Execution, Interrupted, amount, check_active, room_at
from commentscope.product.input import cursor, integer, text, uid
from commentscope.product.store import decode, encode

ACTIVE = {'opening', 'replying', 'synthesizing'}
FINAL = {
    'consensus_ready': 'completed', 'no_consensus': 'completed_no_consensus',
    'no_proposal': 'completed_no_proposal', 'verification_hold': 'verification_hold',
}
MAX_ROOM_TURNS = 18


class DebateService:
    def __init__(self, app, execution_binding):
        self.app = app
        # Hash the operator's pinned configuration with the protocol. The existing
        # provider gateway still enforces the spending owner and execution plan.
        self.binding = digest([VERSION, execution_binding]) if execution_binding is not None else None

    def available(self, analysis):
        return self.binding is not None and seed_policy.seeded(analysis.bundle)

    def create(self, db, session, body):
        app = self.app
        app._fields(body, 'analysis_revision participant_ids question initial_revision request_id')

        def create():
            analysis = app._analysis(session)
            if not self.available(analysis):
                raise WebError(422, 'unsupported_admission_policy')
            if body['analysis_revision'] != analysis.revision:
                raise WebError(409, 'analysis_revision_conflict')
            app._opinion(db, session['session_id'], 'initial', body['initial_revision'])
            selected = body['participant_ids']
            available = {p['candidate_id'] for p in analysis.compiled['profiles']}
            if (not isinstance(selected, list) or not 2 <= len(selected) <= 3
                    or any(not isinstance(i, str) or i not in available for i in selected)
                    or len(set(selected)) != len(selected)):
                raise WebError(422, 'invalid_participants')
            query = text(body['question'], 1000, empty=False)
            n = len(selected)
            did = uid('D')
            room = app._new_room(db, session, analysis, 'group', selected, body['initial_revision'],
                                 kind='structured_debate', debate_id=did)
            plan = {'protocol': VERSION, 'analysis_id': analysis.id, 'analysis_revision': analysis.revision,
                    'expires_at': analysis.bundle['expires_at'], 'participant_ids': selected,
                    'question': query, 'initial_revision': body['initial_revision'],
                    'max_turns': 2*n, 'max_synthesis_candidates': 3, 'max_physical_calls': 6*n+2,
                    'generation_max_tokens': MAX_GENERATION_TOKENS, 'execution_sha256': self.binding,
                    'maximum_cost_usd': room['maximum_cost_usd']}
            debate = {'debate_id': did, 'plan': plan, 'plan_sha256': digest(plan)}
            db.execute('INSERT INTO debates VALUES(?,?,?,?,?,?,?)',
                       (debate['debate_id'], room['room_id'], VERSION, debate['plan_sha256'], 1, 'idle', encode(debate)))
            return 201, self.public(db, debate, room, analysis)

        return app._mutate(db, session['session_id'], 'create-debate', body, create)

    def route(self, db, method, resource, rid, tail, token, body, query):
        app = self.app
        if resource == 'debates':
            room_id, debate = debate_store.load_debate(db, rid)
            if debate is None:
                raise WebError(404, 'resource_missing')
            session, room = app._room(db, token, room_id)
            analysis = app._analysis(session, live=False)
            if method == 'GET' and not tail:
                return 200, self.public(db, debate, room, analysis, cursor(query))
            if method == 'POST' and tail in (['start'], ['control']):
                return self.control(db, debate, session, room, analysis, tail[0], body)
        if resource == 'syntheses' and method == 'GET' and not tail:
            row = db.execute('SELECT s.data,d.room_id FROM syntheses s JOIN debates d ON d.id=s.debate_id WHERE s.id=?',
                             (rid,)).fetchone()
            if row is None:
                raise WebError(404, 'resource_missing')
            session, _ = app._room(db, token, row['room_id'])
            app._analysis(session)
            return 200, decode(row)['report']
        if resource == 'synthesis-agents':
            row = db.execute('SELECT session_id FROM synthesis_agents WHERE id=?', (rid,)).fetchone()
            if row is None:
                raise WebError(404, 'resource_missing')
            session = app._session(db, token, row['session_id'])
            return self.agent_route(db, method, rid, tail, session, body)
        raise WebError(404, 'not_found')

    def public(self, db, debate, room, analysis, after=0):
        value = self.app._room_public(db, room, analysis, after)
        state = room['state']
        expired = analysis.public()['status'] == 'expired'
        usable = self.available(analysis) and not expired
        conclusion = deepcopy(room.get('conclusion'))
        if conclusion and expired:
            conclusion = {**conclusion, 'shared_claims': [], 'conditions': {}, 'disagreements': [],
                          'root_source_ids': [], 'evidence_scope': 'expired'}
        return {**value, **deepcopy(debate), 'can_ask': False, 'turn_limit': debate['plan']['max_turns'],
                'phase': room.get('resume_phase') if state in ('paused', 'pausing') else state,
                'cursor': room['cursor'], 'job_id': room['job_id'],
                'error_acknowledged': room.get('error_acknowledged', False),
                'opening_cutoff_seq': room.get('opening_cutoff_seq'),
                'conclusion': conclusion,
                'synthesis_agent': deepcopy(room.get('synthesis_agent')) if usable else None,
                'can_start': usable and state == 'idle', 'can_pause': state in ACTIVE,
                'can_resume': usable and state == 'paused', 'can_close': state not in ('closed', 'closing')}

    def preflight(self, room, plan, *, starting=False):
        if plan['execution_sha256'] != self.binding or digest(plan) != room['plan_sha256']:
            raise WebError(409, 'execution_binding_conflict')
        if starting:
            # Include the output allowance and verifier for every possible pair.
            # Execution checks the actual input payload separately at each stage.
            estimate = amount(self.app.reservation({
                'system': '', 'data': {}, 'max_tokens': MAX_GENERATION_TOKENS,
                'schema': {'type': 'object', 'properties': {}, 'additionalProperties': False},
            })) + amount(self.app.decision_reservation())
            maximum = (plan['max_physical_calls']//2)*estimate
            available = amount(room['maximum_cost_usd'])
            if self.app.debate_balance is not None:
                available = min(available, amount(self.app.debate_balance()))
            if maximum > available:
                raise WebError(409, 'budget_exhausted')

    def control(self, db, debate, session, room, analysis, action, body):
        app = self.app
        app._fields(body, 'expected_revision request_id' + (' action' if action == 'control' else ''))

        def apply():
            if integer(body['expected_revision'], 1) != room['revision']:
                raise WebError(409, 'revision_conflict')
            command = body.get('action', 'start')
            if action == 'control' and command not in ('pause', 'resume', 'close', 'acknowledge_error'):
                raise WebError(400, 'invalid_control')
            state = room['state']
            if command in ('start', 'resume'):
                app._analysis(session)
                if not self.available(analysis):
                    raise WebError(422, 'unsupported_admission_policy')
                if command == 'start' and state == 'idle':
                    plan = debate['plan']
                    selected = plan['participant_ids']
                    room.update(plan_sha256=debate['plan_sha256'], epoch=room['epoch']+1, state='opening',
                                round_id=1, question=plan['question'],
                                schedule=[{'phase': phase, 'agent_id': aid} for phase in ('opening', 'reply')
                                          for aid in selected])
                    self.preflight(room, plan, starting=True)
                    first = app._append_message(db, room, 'user', body=plan['question'])
                    room['user_message_id'] = first['message_id']
                elif command == 'resume' and state == 'paused':
                    self.preflight(room, debate['plan'])
                    room['state'] = room.pop('resume_phase')
                else:
                    raise WebError(409, 'resource_busy' if state in ACTIVE or state == 'pausing' else 'debate_not_ready')
                room['revision'] += 1
                return app._job(db, session, 'debate', {'epoch': room['epoch'], 'debate_id': debate['debate_id']}, room)
            if command == 'pause' and state in ACTIVE:
                room.update(resume_phase=state, state='pausing')
            elif command == 'close' and state not in ('closed', 'closing'):
                running = state in ACTIVE or state == 'pausing'
                room.update(state='closing' if running else 'closed', epoch=room['epoch']+1)
                if not running and state != 'needs_reconciliation':
                    room.pop('_stages', None)
            elif command == 'acknowledge_error' and state in ('failed', 'exhausted', 'cancelled'):
                room['error_acknowledged'] = True
            else:
                raise WebError(409, 'debate_not_ready')
            room['revision'] += 1
            app._save_room(db, room)
            return 200, self.public(db, debate, room, analysis)

        return app._mutate(db, session['session_id'], f'{action}-{debate["debate_id"]}', body, apply)

    def _current(self, db, job, session):
        room = room_at(db, job['room_id'])
        check_active(room, job)
        self.app._internal_session(db, session['session_id'])
        self.app._analysis(session)
        return room

    def _stopped(self, job):
        app = self.app
        with app.store.transaction() as db:
            room = room_at(db, job['room_id'])
            closed = room['state'] in ('closing', 'closed') or room['epoch'] != job['args']['epoch']
            room['state'] = 'closed' if closed else 'paused'
            if closed:
                room.pop('_stages', None)
            room['revision'] += 1
            app._save_room(db, room)
            app._finish_job(db, job, 'cancelled' if closed else 'succeeded', self.result(job, room))

    def result(self, job, room):
        if job['operation'] == 'debate':
            return {'resource_kind': 'debate', 'resource_id': job['args']['debate_id'],
                    'resource_revision': room['revision']}
        return {'room_id': room['room_id'], 'completed': room['cursor'] == len(room['schedule'])}

    def run(self, job, session, analysis):
        try:
            if job['operation'] == 'debate':
                self._debate(job, session, analysis)
            else:
                self._followup(job, session, analysis)
        except Interrupted:
            self._stopped(job)

    def _debate(self, job, session, analysis):
        app = self.app
        did, rid = job['args']['debate_id'], job['room_id']
        with app.store.transaction() as db:
            initial = self._current(db, job, session)
            _, debate = debate_store.load_debate(db, did)
            plan, plan_sha = debate['plan'], debate['plan_sha256']
            self.preflight(initial, plan)
        participants, query = plan['participant_ids'], plan['question']
        limit = plan['max_physical_calls']
        while True:
            with app.store.transaction() as db:
                room = self._current(db, job, session)
                pos = room['cursor']
                messages = app._messages(db, rid)
                if pos == len(room['schedule']):
                    break
                task = room['schedule'][pos]
                aid, phase = task['agent_id'], task['phase']
                openings = [m for m in messages if m.get('phase') == 'opening'
                            and m['seq'] <= room.get('opening_cutoff_seq', 0)]
            scope = {'debate_id': did, 'plan_sha256': plan_sha, 'epoch': room['epoch'],
                     'position': pos, 'agent_id': aid, 'phase': phase}
            execution = Execution(app, job, session, scope, limit)
            response = turn(analysis, aid, query, scope, phase, openings, execution)
            with app.store.transaction() as db:
                current = self._current(db, job, session)
                _, _, targets = opening_context(openings, aid)
                missing = {t['target_id'] for t in response.get('missing_targets', [])}
                message = app._append_message(db, current, 'agent', agent_id=aid, turn=response,
                    reply_to=current['user_message_id'] if phase == 'opening' else None, phase=phase)
                execution.clear(current)
                current['cursor'] += 1
                current['turn_count'] += 1
                if response['coverage'] != 'complete' or phase == 'reply' and len(targets) != len(participants)-1:
                    current.setdefault('unanswered', []).append({
                        'agent_id': aid, 'phase': phase, 'message_id': message['message_id'],
                        'targets': [row for key, row in targets.items() if key in missing]})
                if current['cursor'] == len(participants):
                    current['opening_cutoff_seq'] = message['seq']
                    if not current.get('unanswered'):
                        current['state'] = 'replying'
                if (current['cursor'] in (len(participants), len(current['schedule']))
                        and current.get('unanswered')):
                    self._finish(db, job, current, 'incomplete')
                    return
                if current['cursor'] == len(current['schedule']):
                    current['state'] = 'synthesizing'
                app._save_room(db, current)
        frozen = agreement.snapshot(did, plan_sha, messages)
        points = agreement.transcript(messages)
        scope = {**frozen, 'epoch': room['epoch'], 'phase': 'synthesizing'}
        draft_run = Execution(app, job, session, scope, limit)
        sealed = agreement.draft(analysis, participants, points, query, frozen, scope, draft_run)
        votes = []
        if sealed['candidates']:
            for aid in participants:
                ratification = {**scope, 'agent_id': aid, 'draft_sha256': sealed['draft_sha256']}
                votes.extend(agreement.ratify(analysis, aid, points, query, sealed, ratification,
                                             Execution(app, job, session, ratification, limit)))
        with app.store.transaction() as db:
            current = self._current(db, job, session)
            if digest(app._messages(db, rid)) != frozen['transcript_sha256']:
                raise ValueError('Published debate changed after the cutoff')
            report, shared = agreement.conclude(analysis, participants, points, frozen, sealed, votes)
            agent = compile_agent(analysis, session['session_id'], participants, points, report, shared) if shared else None
            debate_store.finish(db, debate, report, sealed, votes, agent)
            self._finish(db, job, current, FINAL[report['outcome']], report, agent)

    def _finish(self, db, job, room, state, report=None, agent=None):
        room['state'] = state
        room['revision'] += 1
        room.pop('_stages', None)
        room['synthesis_agent'] = {'agent_id': agent['agent_id'], 'revision': agent['revision']} if agent else None
        room['conclusion'] = {'status': state, 'unanswered': room.get('unanswered', []),
                              'synthesis_id': report['synthesis_id'] if report else None,
                              'report_sha256': digest(report) if report else None,
                              'agent_id': report['agent_id'] if report else None,
                              'final_seq': room['last_seq'],
                              **{key: report[key] if report else default for key, default in (
                                  ('shared_claims', []), ('conditions', {}), ('disagreements', []), ('root_source_ids', []))}}
        room['round_failed'] = state == 'incomplete'
        self.app._save_room(db, room)
        self.app._finish_job(db, job, 'succeeded', self.result(job, room))

    def failure(self, room, code):
        room['conclusion'] = {'status': room['state'], 'reason': code, 'final_seq': room['last_seq'],
                              'agent_id': None, 'unanswered': room.get('unanswered', []),
                              'shared_claims': [], 'conditions': {}, 'disagreements': [], 'root_source_ids': []}
        if code != 'reconcile_required':
            room.pop('_stages', None)

    def _agent(self, db, aid, session):
        row = db.execute('SELECT * FROM synthesis_agents WHERE id=? AND session_id=?',
                         (aid, session['session_id'])).fetchone()
        if row is None:
            raise WebError(404, 'resource_missing')
        analysis = self.app._analysis(session)
        agent = decode(row)
        signature = agent['artifact_sha256']
        if (signature != row['artifact_sha256'] or digest({k:v for k,v in agent.items() if k != 'artifact_sha256'}) != signature
                or agent['analysis_revision'] != analysis.revision):
            raise WebError(409, 'analysis_revision_conflict')
        try:
            live(agent['expires_at'])
        except ValueError:
            raise WebError(410, 'source_expired') from None
        return analysis, agent

    def agent_route(self, db, method, aid, tail, session, body):
        app = self.app
        analysis, agent = self._agent(db, aid, session)
        if method == 'GET' and not tail:
            info = deepcopy(agent)
            info.pop('session_id')
            for claim in info['accepted_claims']:
                claim.pop('_lineage_sources')
                claim.pop('_references')
            return 200, {**info, 'can_ask': self.available(analysis),
                         'semantic_reliability': 'not_assessed', 'quality_gate_passed': False}
        if method == 'GET' and len(tail) == 2 and tail[0] == 'sources':
            if tail[1] not in agent['root_source_ids']:
                raise WebError(404, 'source_missing')
            return 200, analysis.source(tail[1])
        if method == 'POST' and tail == ['rooms']:
            app._fields(body, 'agent_revision initial_revision request_id')
            def create():
                if integer(body['agent_revision'], 1) != agent['revision']:
                    raise WebError(409, 'revision_conflict')
                if not self.available(analysis):
                    raise WebError(422, 'unsupported_admission_policy')
                app._opinion(db, session['session_id'], 'initial', body['initial_revision'])
                room = app._new_room(db, session, analysis, 'one_to_one', [aid], body['initial_revision'],
                                     kind='synthesis_chat', synthesis_agent_sha256=agent['artifact_sha256'],
                                     execution_sha256=self.binding)
                return 201, app._room_public(db, room, analysis)
            return app._mutate(db, session['session_id'], f'agent-room-{aid}', body, create)
        raise WebError(404, 'not_found')

    def _followup(self, job, session, analysis):
        app = self.app
        with app.store.transaction() as db:
            room = self._current(db, job, session)
            aid = room['participant_ids'][0]
            _, agent = self._agent(db, aid, session)
            if (not self.available(analysis) or room['execution_sha256'] != self.binding
                    or room['synthesis_agent_sha256'] != agent['artifact_sha256']):
                raise WebError(409, 'execution_binding_conflict')
            if room['cursor'] >= len(room['schedule']):
                room['state'] = 'awaiting_user'
                room['revision'] += 1
                app._save_room(db, room)
                app._finish_job(db, job, 'succeeded', self.result(job, room))
                return
            messages = app._messages(db, room['room_id'])
        scope = {'room_id': room['room_id'], 'epoch': room['epoch'], 'phase': 'followup', 'agent_id': aid,
                 'artifact_sha256': agent['artifact_sha256'], 'execution_sha256': self.binding}
        run = Execution(app, job, session, scope, 2*MAX_ROOM_TURNS)
        response = turn(analysis, aid, room['question'], scope, 'followup', messages, run, derived=agent)
        with app.store.transaction() as db:
            current = self._current(db, job, session)
            self._agent(db, aid, session)
            app._append_message(db, current, 'agent', agent_id=aid, turn=response,
                                reply_to=current['user_message_id'], phase='followup')
            run.clear(current)
            current['turn_count'] += 1
            current['cursor'] += 1
            current['state'] = 'exhausted' if current['turn_count'] >= MAX_ROOM_TURNS else 'awaiting_user'
            app._save_room(db, current)
            app._finish_job(db, job, 'succeeded', self.result(job, current))
