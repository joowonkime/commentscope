"""One raw-pair proposal, independent source decisions and immutable support ledger.

No transitive membership, peer evidence, automatic self vote or agent approval.
"""
from collections import Counter
import math

from commentscope.factory import grounded_core as audit, qualification_guards, raw_candidates
from commentscope.factory.automatic import checked_call
from commentscope.factory.automatic_contract import digest
from commentscope.factory.shared_core import SCHEMA, validate_proposal, supported

VERSION = 'raw-support-0.1'
STATES = ('support', 'not_supported', 'uncertain', 'error', 'unchecked')
PROPOSE = audit.PROPOSE_SYSTEM.replace('untrusted candidate statements', 'untrusted original comments')


def validate_source(source):
    if source['source_digest'] != digest(source['text']):
        raise ValueError('Source changed')


def base_decision(source, core, state, reason):
    validate_source(source)
    if validate_proposal({'core': core}) or not core:
        raise ValueError('Invalid fixed core')
    return {'version': VERSION, 'source_id': source['source_id'],
            'source_digest': source['source_digest'], 'core_digest': digest(core),
            'state': state, 'reason': reason, 'nli': None, 'audit': None,
            'qualification_guard': None, 'evidence': None}


def check(source, core, calls, score):
    result = base_decision(source, core, 'unchecked', 'not_started')
    original = source['text']
    if not original.strip() or len(original) > 4000:
        result['reason'] = 'empty_or_character_budget'; return result
    nli = score(original, core); result['nli'] = nli
    if nli['errors']:
        result.update(state='unchecked' if nli.get('deferred_reason') else 'error',
                      reason=nli.get('deferred_reason') or 'nli_error')
        return result
    if not supported(nli):
        result.update(state='uncertain' if nli['relation'] == 'unclear' else 'not_supported',
                      reason='nli_'+nli['relation'])
        return result
    checked = checked_call(calls, audit.AUDIT_SYSTEM, {'SOURCE': original, 'TARGET': core},
                           audit.AUDIT_SCHEMA, lambda value: audit.validate_audit(value, original))
    result['audit'] = checked
    if checked['errors']:
        result.update(state='error', reason='audit_error'); return result
    value = checked['output']
    if value['support'] != 'supported' or any(value[f] != 'preserved' for f in audit.FIELDS):
        result.update(state='uncertain' if value['support'] == 'unclear' or any(value[f] == 'unclear' for f in audit.FIELDS)
                      else 'not_supported', reason='relational_audit')
        return result
    quote = value['evidence_quote']
    # Compare the selected supporting assertion, not unrelated conditions elsewhere
    # in a multi-claim comment. Full SOURCE remains the NLI/auditor's evidence.
    guard = qualification_guards.compare(quote, core); result['qualification_guard'] = guard
    starts = [i for i in range(len(original)) if original.startswith(quote, i)]
    result['evidence'] = {'quote': quote, 'occurrences': [{'start': i, 'end': i+len(quote)} for i in starts]}
    result.update(state='support' if guard['allowed'] else 'not_supported',
                  reason='model_agreement' if guard['allowed'] else 'qualification_guard')
    return result


def discover(registry, pair, calls, score):
    packet = raw_candidates.source_packet(registry, pair)
    sources = packet['sources']
    result = {'version': VERSION, 'pair_id': pair['pair_id'], 'source_ids': pair['source_ids'],
              'input_digest': digest(packet), 'proposal': None, 'checks': [],
              'selected_core': None, 'status': 'unchecked'}
    if any(not s['text'].strip() or len(s['text']) > 4000 for s in sources):
        result['reason'] = 'source_budget'; return result
    proposal = checked_call(calls, PROPOSE, {'LEFT': sources[0]['text'], 'RIGHT': sources[1]['text']},
                            SCHEMA, validate_proposal)
    result['proposal'] = proposal
    if proposal['errors']:
        result['status'] = 'error'; return result
    core = proposal['output']['core']
    if not core:
        result['status'] = 'no_proposal'; return result
    result['checks'] = [check(s, core, calls, score) for s in sources]
    if all(c['state'] == 'support' for c in result['checks']):
        result.update(selected_core=core, status='pair_supported_unvalidated')
    else:
        result['status'] = 'not_pair_supported'
    return result


def ledger(registry, core, decisions):
    sources = {s['source_id']: s for s in registry['sources']}
    if len(sources) != len(registry['sources']): raise ValueError('Duplicate canonical sources')
    rows = {sid: base_decision(s, core, 'unchecked', 'not_scheduled') for sid, s in sources.items()}
    seen = set()
    for row in decisions:
        sid = row['source_id']
        if (sid not in sources or sid in seen or row['core_digest'] != digest(core)
                or row['source_digest'] != sources[sid]['source_digest'] or row['state'] not in STATES):
            raise ValueError('Decision source/core/state changed or duplicate vote')
        # Ledger is a projection of trusted check() traces, never a manual approval API.
        if row['state'] == 'support':
            checked = row['audit']
            if (not row['nli'] or not supported(row['nli']) or not checked or checked['errors']
                    or audit.validate_audit(checked['output'], sources[sid]['text'])
                    or checked['output']['support'] != 'supported'):
                raise ValueError('Support without valid model traces')
            quote = checked['output']['evidence_quote']
            guard = qualification_guards.compare(quote, core)
            evidence = {'quote': quote, 'occurrences': [{'start': i, 'end': i+len(quote)}
                        for i in range(len(sources[sid]['text'])) if sources[sid]['text'].startswith(quote, i)]}
            if not guard['allowed'] or row['qualification_guard'] != guard or row['evidence'] != evidence:
                raise ValueError('Support evidence/guard changed')
        rows[sid] = row; seen.add(sid)
    counts = Counter(r['state'] for r in rows.values()); n = len(sources); s = counts['support']
    major = max(10, math.ceil(.05*n))
    tier = 'major_candidate' if s >= major else 'limited' if s >= 3 else 'rare' if s else 'none'
    return {'version': VERSION, 'core': core, 'core_digest': digest(core), 'registry_digest': digest(registry),
            'source_decisions': list(rows.values()), 'counts': {k: counts[k] for k in STATES},
            'canonical_denominator': n, 'support_count': s, 'completed_count': s+counts['not_supported'],
            'provisional_tier': tier, 'major_threshold': major, 'quality_gate_passed': False,
            'agents': [], 'status': 'model_counts_unvalidated'}
