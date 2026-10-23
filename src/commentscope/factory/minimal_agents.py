"""Versioned adapter from final minimal claims to existing grounded runtime.

No legacy frame placeholders, no manual selection and no new fact semantics.
Source-specific dependencies attach to their argument, not all group members.
"""
from copy import deepcopy

from commentscope.factory import minimal_membership as mm, source_arguments as sa, fact_checks
from commentscope.factory.automatic_contract import digest
from commentscope.factory.position_frames import validate_snapshot_source
from commentscope.agents.grounded_inputs import compile_inputs
from commentscope.factory import contextual_runtime

VERSION = 'minimal-grounded-agents-20261017-v5'


def relation(claim, source, evidence, trace):
    start = min(p['start'] for p in evidence); end = max(p['end'] for p in evidence)
    span = {'start': start, 'end': end, 'text': source['text'][start:end]}
    fact_checks.bound_span(source['text'], span)
    return {'claim_id': claim['id'], 'claim_sha256': fact_checks.claim_identity(claim),
            'source_id': source['id'], 'source_sha256': digest(source['text']),
            'span': span, 'verdict': 'supported', 'trace_id': trace, 'origin': 'local_model'}


def prepare(snapshot, candidates, memberships, records, cores, audits, *, model, documents=(), checks=(), _draft_single_source=False):
    mapped = mm.assemble_map(snapshot, candidates, memberships)
    fact_checks.model_identity(model)
    members = {p['id']: p['supported_canonical_ids'] for p in mapped['opinion_map']['perspectives']}
    if type(_draft_single_source) is not bool or (_draft_single_source and
            (len(candidates)!=1 or len(members.get(candidates[0]['id'],[]))!=1)):
        raise ValueError('A private source draft requires exactly one candidate and one real source')
    membership_rows = [r for b in memberships for r in mm.validate_batch(b)]
    membership_lookup = {(r['candidate_id'], r['source_id']): r for r in membership_rows}
    cs = {c['id']: c for c in candidates}; rr = {}; cr = {}
    verdicts = sa.audit_verdicts(records, cores, audits)
    for record in records:
        sa.validate(record); sid = record['source']['id']
        validate_snapshot_source(snapshot, record['source'])
        if record['artifact_kind'] != sa.VERSION+'-linked': raise ValueError('Unassessed argument dependencies cannot compile')
        if (sid in rr or any(cid not in cs or sid not in members[cid] for cid in record['candidate_ids'])):
            raise ValueError('Arguments require unique current member originals')
        rr[sid] = record
    for core in cores:
        cid = core['candidate']['id']
        if (cid in cr or cs.get(cid) != core['candidate']
                or sa.validate_core(core) != core):
            raise ValueError('Core declaration differs from final candidate')
        cr[cid] = core
    claims = {}; relations = {}; sources = {}; prepared = []; holds = []; runtime_scopes = {}; source_contexts = {}
    for cid, candidate in cs.items():
        sids = members[cid]; reasons = []
        runtime_scope=cr.get(cid,{}).get('runtime_scope')
        if 'meaning_context' in candidate:
            if runtime_scope is None:reasons.append('contextual_runtime_adapter_unassessed')
            else:
                contextual_runtime.validate(runtime_scope,candidate)
                reasons.extend(runtime_scope['hold_reasons'])
        if len(sids) < 3 and not _draft_single_source: reasons.append('fewer_than_three_core_sources')
        if cid not in cr: reasons.append('core_type_unassessed')
        elif cr[cid]['output']['kind'] == 'uncertain': reasons.append('core_type_uncertain')
        if cid in cr: reasons.extend(cr[cid].get('hold_reasons', []))
        for sid in sids:
            record = rr.get(sid)
            if record is None or cid not in record['candidate_ids']:
                reasons.append('member_arguments_unassessed'); continue
            if record['status'] != 'complete': reasons.append('member_arguments_incomplete')
            if record['dependency_status'] != 'complete': reasons.append('member_dependencies_unresolved')
            if verdicts.get('AC'+digest(record)) != 'supported': reasons.append('member_completeness_not_verified')
            selected = [u for u in record['units'] if cid in u['candidate_ids'] and u.get('runtime_exposure')!='scope_annotation_only']
            by_local = {u['local_id']: u for u in record['units']}
            expanded = {u['local_id']: u for u in selected}
            def include(lid):
                expanded[lid] = by_local[lid]
                for dep in by_local[lid]['requires']:
                    if dep not in expanded: include(dep)
            for unit in selected: include(unit['local_id'])
            for unit in expanded.values():
                if unit['kind'] == 'uncertain': reasons.append('argument_type_uncertain')
                if verdicts.get(unit['id']) != 'supported': reasons.append('argument_not_verified')
                if unit['kind'] == 'fact' and record['source_language'] != 'en':
                    reasons.append('fact_source_language_unsupported')
                if unit['kind']=='fact' and runtime_scope and runtime_scope['interpretation_scope']['world']!='actual':
                    reasons.append('nonactual_factual_scope_unsupported')
            if cid in cr and cr[cid]['output']['kind'] == 'fact' and record['source_language'] != 'en':
                reasons.append('fact_source_language_unsupported')
        if reasons:
            holds.append({'candidate_id': cid, 'reasons': sorted(set(reasons)), 'source_ids': sids})
            continue
        core = {'id': cid+':C', 'text': candidate['text'], 'kind': cr[cid]['output']['kind'],
                'scope': deepcopy(cr[cid]['output']['scope']), 'requires': []}
        argument_ids = set(); argument_roles = {}; core_dependencies = set(); all_factual = set()
        for sid in sids:
            record = rr[sid]; source = record['source']
            sources[sid] = {'id': sid, 'text': source['text'], 'canonical_id': sid}
            if source['parent'] is not None:
                source_contexts[sid]={'source_sha256':digest(source['text']),
                    'parent_sha256':digest(source['parent']),'parent':deepcopy(source['parent'])}
            by_local = {u['local_id']: u for u in record['units']}
            def add(lid):
                unit = by_local[lid]
                claim = {'id': unit['id'], 'text': unit['text'], 'kind': unit['kind'],
                         'scope': deepcopy(unit['scope']), 'requires': [by_local[d]['id'] for d in unit['requires']]}
                if claim['id'] in claims and claims[claim['id']] != claim:
                    raise ValueError('Shared source argument changed across candidates')
                claims[claim['id']] = claim
                relations[claim['id'], sid] = relation(claim, source, unit['evidence'], digest(record))
                if claim['kind'] == 'fact': all_factual.add(claim['id'])
                for dep in unit['requires']: add(dep)
            for unit in record['units']:
                if cid not in unit['candidate_ids']: continue
                if unit.get('runtime_exposure')=='scope_annotation_only':continue
                add(unit['local_id']); argument_ids.add(unit['id'])
                argument_roles[unit['id']] = unit.get('candidate_roles', {}).get(cid, unit['role'])
                if cid in unit['core_requires_for']: core_dependencies.add(unit['id'])
        core['requires'] = sorted(core_dependencies); claims[core['id']] = core
        if core['kind'] == 'fact': all_factual.add(core['id'])
        for sid in sids:
            row = membership_lookup[cid, sid]
            relations[core['id'], sid] = relation(core, rr[sid]['source'], row['evidence'], digest(row))
        prepared.append({'id': cid, 'core_claim_id': core['id'], 'reason_claim_ids': sorted(argument_ids),
                         'major_fact_ids': sorted(all_factual), 'argument_roles': argument_roles})
        if runtime_scope is not None:
            contextual_runtime.validate_core(runtime_scope,cid,core)
            runtime_scopes[cid]=deepcopy(runtime_scope)
    bundle = {'expires_at': snapshot.usage.expires_at, 'sources': list(sources.values()), 'claims': list(claims.values()),
              'relations': list(relations.values()), 'candidates': prepared, 'documents': deepcopy(list(documents)),
              'checks': deepcopy(list(checks)), 'model': deepcopy(model)}
    if runtime_scopes:bundle['runtime_scopes']=runtime_scopes
    if source_contexts:bundle['source_contexts']=source_contexts
    compiled = compile_inputs(bundle)
    if _draft_single_source and compiled['profiles']:
        raise ValueError('A source draft must never compile into an exposed Agent')
    return {'artifact_kind': VERSION, 'map': mapped, 'bundle': bundle, 'compiled': compiled,
            'argument_holds': holds, 'source_arguments_sha256': digest(records),
            'quality_gate_passed': False, 'runtime_verified': False}
