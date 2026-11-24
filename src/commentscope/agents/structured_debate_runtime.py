"""Grounded turn generation, independent decisions, and binding of published points."""
from commentscope.agents import seed_policy
from commentscope.agents.debate_contracts import (
    ORIGINS, QUESTION_SCOPE, VERSION, addressed, array, choice, compact, generate, ids, obj, observe,
    question, require_ids, short_citations, supported, unique_rows,
)
from commentscope.agents.debate_quantities import changes_weekly_hours
from commentscope.factory.automatic_contract import digest

TURN_CHECKS = {
    'kind': ('Does the text match the claimed origin? AI reasoning is conditional or normative '
             'and cannot contain new empirical assertions.', 'matches_origin'),
    'attribution': ('The speaker of a new proposal is the AI participant. Does it speak for itself or accurately attribute a source, without inventing personal history or endorsement by a commenter, another speaker or the group?', 'faithful'),
    'scope': ('Compare this point with QUESTION as well as the source anchors and applicable CONDITIONS. '
              'Reject a changed user scenario even if the source stance is faithfully represented. A participant can offer its own option when the user asks for a group conclusion. Check substantive restrictions here. PHASE_TASK governs which part of the question is due now. '
              'Keep the stance, required conditions and uncertainty. '+QUESTION_SCOPE, 'preserved'),
    'basis': ('Is the point grounded in the cited anchors and any exact reference? Preserve hypothetical worlds. Peer speech and model memory '
              'are not factual evidence. A quote selected by the host must fit its use here. An AI proposal or value judgment '
              'may extend the anchor explicitly as reasoning. It may not add a fact or a claim about the source author.', 'supported'),
}
TURN_TASKS = {
    'opening': 'State this perspective’s own question-specific reason or evidence limitation. '
               'Leave peer responses and joint conclusions to later phases, including when the question requests them. For a group conclusion request, offer one option this speaker would put on the table and why or under what condition.',
    'reply': 'Address each supplied peer target with an explicit relation and a question-specific reason or evidence limitation.',
    'followup': 'Address the new question using the accepted claims and their limitations. These claims record agreement '
                'among selected AI participants. Retain conditions and unresolved differences, and do not infer commenter agreement.',
}
POINT_SLOTS = ('P1', 'P2', 'P3')


def perspective(analysis, agent_id):
    profile = analysis.allowed(agent_id)
    entries = {}
    for entry in profile['allowed_entries']:
        entries[entry['claim_id']] = {**entry, 'origin': 'original_comment'}
    return entries, profile['core_claim_id']


def conditions(agent_id, entries, core_id):
    # Embedded conditional scopes remain attached to the core. Explicit condition
    # claims get their own identifiers and reappear unchanged in the report.
    required = [cid for cid, entry in entries.items() if entry['role'] == 'essential_condition']
    core = entries[core_id]
    if core.get('scope', {}).get('conditions'):
        required.insert(0, core_id)
    return {f'{agent_id}/condition/{i}': {'text': entries[cid]['text'],
                'scope': entries[cid].get('scope'), 'claim_id': cid, 'agent_id': agent_id}
            for i, cid in enumerate(required, 1)}


def closure(entries, selected):
    result = {}
    pending = list(selected)
    while pending:
        cid = pending.pop(0)
        if cid not in result:
            entry = entries[cid]
            result[cid] = entry
            pending.extend(entry.get('requires', ()))
    return result


def opening_context(messages, speaker):
    """Later replies see the same published opening snapshot as earlier replies."""
    own, peers, targets = [], [], {}
    for message in messages:
        if message.get('phase') != 'opening':
            continue
        points = [{'point_id': p['point_id'], 'text': p['text'], 'origin': p['origin']}
                  for p in message['points']]
        row = {'agent_id': message['agent_id'], 'message_id': message['message_id'], 'points': points}
        if row['agent_id'] == speaker:
            own.append(row)
        else:
            peers.append(row)
            for index, point in enumerate(message['points']):
                if point['task_fit'] == 'responsive':
                    target = f'T{len(targets)+1}'
                    targets[target] = {**points[index], 'agent_id': row['agent_id'],
                                       'message_id': row['message_id']}
                    break
    return own, peers, targets


def turn(analysis, speaker, query, scope, phase, messages, run, *, derived=None, prior_discussion=None):
    if derived is None:
        entries, core_id = perspective(analysis, speaker)
        required_conditions = conditions(speaker, entries, core_id)
        refs = seed_policy.references(analysis.bundle)
        inventory = {f'D{i}': ref for i, ref in enumerate(refs, 1)}
        own, peers, targets = opening_context(messages, speaker) if phase == 'reply' else ([], [], {})
    else:
        entries = {c['claim_id']: c for c in derived['accepted_claims']}
        core_id = None
        required_conditions = derived['conditions']
        inventory = {f'D{i}': ref for i, ref in enumerate(derived['references'], 1)}
        own = [{'text': p['text'], 'origin': p['origin']} for m in messages[-4:]
               for p in m.get('points', [])]
        peers, targets = derived['disagreements'], {}
    aliases = {f'E{i}': key for i, key in enumerate(entries, 1)}
    by_id = {key: alias for alias, key in aliases.items()}
    alias_rows = {alias: {**compact(entries[key]),
                         'requires': [by_id[cid] for cid in entries[key].get('requires', [])]}
                  for alias, key in aliases.items()}
    edge = obj({'target_id': choice(targets) if targets else {'type': 'string'},
                'relation': choice(('agree', 'disagree', 'conditional', 'uncertain'))})
    point = obj({'origin': choice(ORIGINS if derived is None else ORIGINS[1:]),
                 'text': {'type': 'string', 'maxLength': 600},
                 'anchor_ids': ids(aliases, minimum=1),
                 'reference_ids': ids(inventory),
                 'targets': array(edge, maximum=len(targets))})
    schema = obj({'points': obj(dict.fromkeys(POINT_SLOTS, {'anyOf': [point, {'type': 'null'}]})),
                  'answerability': choice(('answered', 'partial', 'abstain'))})
    phase_task = TURN_TASKS[phase]
    data = {'PHASE': phase, 'PHASE_TASK': phase_task, 'QUESTION': query, 'CLAIMS': alias_rows,
            'CORE': next((a for a, key in aliases.items() if key == core_id), None),
            'CONDITIONS': required_conditions, 'REFERENCES': inventory, 'TARGETS': targets,
            'OWN_CONTEXT': own, 'OTHER_CONTEXT_ONLY': peers}
    if prior_discussion is not None:
        data['PRIOR_DISCUSSION_CONTEXT_ONLY'] = prior_discussion
    value = generate(run, 'turn-generate', scope, '''
Address the original QUESTION from this perspective's CLAIMS, respecting CONDITIONS and PHASE_TASK.
Give the reader your position or a concrete proposal first, followed by its reason or decisive condition.
Use the language of QUESTION for each new sentence. Speak in a concise conversational voice.
For a decision, explain what you would do next or which trade-off you would accept. Keep a proposed
action and any cited empirical result in separate points. Reserve statements of collective agreement for ratification.
If PRIOR_DISCUSSION_CONTEXT_ONLY is present, use the user's earlier questions and previous public
ideas to resolve references to this discussion. Ground any new point in your own available CLAIMS.
In a reply, use the supplied TARGETS and your own grounds.
Other speakers are context. Their statements are not your evidence or proof.
Keep fictional claims within their fictional world. A derived perspective may cite other speakers
only as attributed disagreement, and may not treat their disagreement as an accepted claim or a fact.
For original_comment select exactly one anchor and supply empty text. The host restores the verified claim.
For ai_reasoning use only conditional/value reasoning anchored in claims and supply no references.
For external_evidence cite exact supplied passages for every empirical assertion.
Keep each free-text point short and complete, with its essential qualifiers. Aim for at most 350 characters.
Fill P1 through P3 in order and use null for every unused slot.
An abstention may have a grounded explanation. Never claim agreement, public consensus,
invented sources, or knowledge beyond the allowed scope. Use the user's language.
''' + QUESTION_SCOPE, data, schema)
    proposed, evidence = {}, {}
    scope_hold = False
    for alias in POINT_SLOTS:
        row = value['points'][alias]
        if row is None:
            continue
        require_ids(row['anchor_ids'], aliases)
        require_ids(row['reference_ids'], inventory)
        require_ids([e['target_id'] for e in row['targets']], targets)
        original = row['origin'] == 'original_comment'
        if original and (row['text'] or len(row['anchor_ids']) != 1):
            raise ValueError('Original comments must be bound by the host')
        if not original and not row['text'].strip():
            raise ValueError('Empty proposed debate point')
        if bool(row['reference_ids']) != (row['origin'] == 'external_evidence'):
            raise ValueError('Point origin and supplied passages disagree')
        if row['origin'] == 'ai_reasoning' and changes_weekly_hours(query, row['text']):
            scope_hold = True
            continue
        anchor_ids = [aliases[a] for a in row['anchor_ids']]
        selected = entries[anchor_ids[0]]
        resolved = closure(entries, anchor_ids + ([core_id] if core_id else []))
        exact = [inventory[r] for r in row['reference_ids']]
        proposed[alias] = {**row, 'text': selected['text'] if original else row['text']}
        evidence[alias] = (anchor_ids, resolved, exact)
    if not proposed:
        return {**build_turn([], [], value['answerability'], False, {}),
                'missing_targets': [dict(row, target_id=key) for key, row in targets.items()]}
    checks = {'answer': question('Does the whole proposed response meet PHASE_TASK for this question without unsupported '
                                 'certainty, possibly with an explicit and justified evidence limitation?', 'appropriate')}
    point_checks = {**TURN_CHECKS, 'task_fit': ('Does the point substantively address PHASE_TASK and every target it lists? '
                                               'Repetition and loose topical similarity do not count.', 'responsive')}
    used = {}
    for alias, (_, resolved, exact) in evidence.items():
        used[alias] = {'anchors': {key: {**compact(entry), **short_citations(entry)}
                                   for key, entry in resolved.items()}, 'passages': exact}
        checks.update(addressed(alias, 'PROPOSED_POINTS', point_checks))
    answers, receipt = observe(run, 'turn-verify', scope,
        {'QUESTION': query, 'PHASE_TASK': phase_task, 'TARGETS': targets, 'CONDITIONS': required_conditions,
         **({'PRIOR_DISCUSSION_CONTEXT_ONLY': prior_discussion} if prior_discussion else {}),
         'ATTRIBUTED_DISAGREEMENT_ONLY': peers if derived is not None else [],
         'PROPOSED_POINTS': proposed, 'EVIDENCE': used, 'ANSWERABILITY': value['answerability']}, checks)
    surviving = {alias: row for alias, row in proposed.items() if supported(answers, alias, TURN_CHECKS)}
    verification_hold = len(surviving) != len(proposed)
    # A verdict on the entire draft only applies when that draft will be posted.
    # After a hold, each surviving point must earn credit on its own.
    draft_fit = verification_hold or answers['answer'] == 'appropriate'
    points, premises, covered = [], {}, set()
    for alias, row in surviving.items():
        anchor_ids, resolved, exact = evidence[alias]
        original = row['origin'] == 'original_comment'
        selected = entries[anchor_ids[0]]
        if original:
            citation = short_citations(selected)
            resolved.pop(anchor_ids[0])
        else:
            citation = {'comment_evidence': [], 'external_evidence': exact, 'anchor_claim_ids': anchor_ids}
        for cid, item in resolved.items():
            premises[cid] = {**item, 'claim_id': cid}
        fit = draft_fit and answers[f'{alias}_task_fit'] == 'responsive'
        edges = [{**targets[e['target_id']], 'relation': e['relation']} for e in row['targets']] if fit else []
        if fit:
            covered.update(e['target_id'] for e in row['targets'])
        points.append({
            **({key: selected[key] for key in ('scope', 'kind', 'interpretation_scope', 'epistemic_status')
                if key in selected} if original else {}),
            'claim_id': anchor_ids[0] if original else 'DC'+digest([scope, alias, row]),
            'text': row['text'], 'origin': row['origin'], 'citations': citation,
            'member_source_count': selected['member_source_count'] if original else 0,
            'condition_ids': list(required_conditions), 'target_edges': edges,
            'task_fit': 'responsive' if fit else 'background',
            '_lineage_sources': unique_rows([
                *citation['comment_evidence'], *(s for entry in resolved.values()
                for s in entry.get('_lineage_sources', short_citations(entry)['comment_evidence']))]),
            '_references': unique_rows([
                *citation['external_evidence'], *citation.get('verification_evidence', []),
                *(s for entry in resolved.values() for s in entry.get('_references', [
                    *short_citations(entry)['external_evidence'], *short_citations(entry)['verification_evidence']
                ]))]),
        })
    fits = any(p['task_fit'] == 'responsive' for p in points) and set(targets) <= covered
    kind = value['answerability'] if fits else ('partial' if points else 'abstain')
    if (scope_hold or verification_hold) and kind == 'answered':
        kind = 'partial'
    return {**build_turn(points, list(premises.values()), kind, fits, receipt),
            'missing_targets': [dict(row, target_id=key) for key, row in targets.items() if key not in covered]}


def build_turn(points, premises, kind, fits, receipt):
    if not points:
        kind = 'abstain'
    return {'artifact_kind': VERSION, 'answer_mode': 'seeded_provenance', 'points': points,
            'required_premises': premises, 'answerability': kind, 'status': kind,
            'limitation': None if fits else 'insufficient_verified_response',
            'coverage': 'complete' if fits else 'incomplete', '_observation': receipt}
