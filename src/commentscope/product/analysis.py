"""Register all generated profiles without promoting historical quality claims."""
from copy import deepcopy
from pathlib import Path

from commentscope.agents import seed_policy
from commentscope.agents.grounded_inputs import compile_inputs, prompt_input
from commentscope.factory import perspective_mining
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.factory.framed_corpus import sources as source_registry
from commentscope.factory.fact_checks import live
from commentscope.ingestion import load_snapshot


class Analysis:
    def __init__(self, bundle, provenance, presentation=None):
        self.bundle = deepcopy(bundle)
        self.compiled = compile_inputs(self.bundle)
        self.provenance = deepcopy(provenance)
        self.presentation = deepcopy(presentation or {})
        self.revision = digest(self.bundle)
        self.id = 'AN'+digest([self.revision, self.provenance])[:24]

    def live(self):
        if digest(self.bundle)!=self.revision:raise ValueError('Registered analysis changed')
        live(self.bundle['expires_at'])
        seed_policy.references(self.bundle)

    def public(self):
        expired = False
        try: self.live()
        except ValueError: expired = True
        claims = {c['id']: c for c in self.bundle['claims']}
        candidates = {c['id']: c for c in self.bundle['candidates']}
        perspectives = []
        memberships={};canonical={s['id']:s.get('canonical_id',s['id']) for s in self.bundle['sources']}
        if not expired:
            for profile in self.compiled['profiles']:
                cid = profile['candidate_id']; candidate=candidates[cid];core = claims[candidate['core_claim_id']]
                citations = profile['citations']

                def source_ids(claim_id):
                    return list(dict.fromkeys(e['source_id'] for e in citations[claim_id]['comment_evidence']))

                grounds=[]
                for entry in profile['prompt_entries']:
                    claim_id = entry['claim_id']
                    role=candidate.get('argument_roles',{}).get(claim_id,'reason')
                    if claim_id in candidate['reason_claim_ids'] and role in ('reason','essential_condition','concession'):
                        grounds.append({'claim_id':claim_id,'text':entry['text'],'kind':entry['kind'],
                                        'role':role,'source_count':entry['member_source_count'],
                                        'source_ids':source_ids(claim_id)})
                core_sources = source_ids(core['id'])
                for source_id in core_sources:
                    memberships.setdefault(canonical[source_id],set()).add(cid)
                perspectives.append({'id': cid, 'core_claim_id': core['id'],
                                     'display_name': self.presentation.get('names', {}).get(cid) or core['text'],
                                     'text': core['text'], 'kind': core['kind'],
                                     'source_count': profile['model_core_support_count'],
                                     'source_ids':core_sources,'grounds':grounds})
        if seed_policy.seeded(self.bundle):
            for perspective in perspectives:
                perspective['admission_policy']=seed_policy.VERSION
                perspective['support_scope']='verified_comment_sources_not_population_share'
        known=self.provenance.get('processing_count')
        analyzed=known if type(known) is int else len({s.get('canonical_id',s['id']) for s in self.bundle['sources']})
        composition=[{'perspective_id':p['id'],'count':sum(ids=={p['id']} for ids in memberships.values())} for p in perspectives]
        composition.extend([{'perspective_id':None,'kind':'multiple','count':sum(len(ids)>1 for ids in memberships.values())},
                            {'perspective_id':None,'kind':'other','count':max(0,analyzed-len(memberships))}])
        likes = {} if expired else self.presentation.get('likes_by_source', {})
        known_likes = {cid: n for cid, n in likes.items() if type(n) is int and n >= 0}
        complete = bool(analyzed) and len(known_likes) == analyzed and memberships.keys() <= known_likes.keys()
        if complete:
            totals = {p['id']: 0 for p in perspectives}
            totals.update(multiple=0, other=0)
            for cid, likes_count in known_likes.items():
                owners = memberships.get(cid, set())
                group = next(iter(owners)) if len(owners) == 1 else 'multiple' if owners else 'other'
                totals[group] += likes_count
            for item in composition:
                item['likes'] = totals[item['perspective_id'] or item['kind']]
        engagement = {'available': complete, 'comments_with_likes': len(known_likes),
                      'total_likes': sum(known_likes.values()) if complete else None}
        return {'analysis_id': self.id, 'bundle_revision': self.revision,
                'status': 'expired' if expired else 'experimental',
                'semantic_reliability': 'not_assessed', 'quality_gate_passed': False,
                'expires_at': self.bundle['expires_at'], 'perspectives': perspectives,
                'analyzed_comments':analyzed,'canonical_population':self.provenance.get('canonical_population'),
                'count_scope':'processed_comments' if known is not None else 'registered_sources',
                'composition':composition,'engagement':engagement,
                'video': deepcopy(self.provenance.get('video', {}))}

    def allowed(self, candidate_id):
        self.live()
        value=prompt_input(self.compiled, candidate_id, bundle=self.bundle)
        profile=next(p for p in self.compiled['profiles'] if p['candidate_id']==candidate_id)
        candidate=next(c for c in self.bundle['candidates'] if c['id']==candidate_id)
        for entry in value['allowed_entries']:
            entry['citations']=deepcopy(profile['citations'][entry['claim_id']])
            cid=entry['claim_id']
            entry['role']=('core' if cid==candidate['core_claim_id'] else
                candidate.get('argument_roles',{}).get(cid,'reason') if cid in candidate['reason_claim_ids'] else 'prerequisite')
        return value

    def source(self, source_id):
        self.live()
        found = next((s for s in self.bundle['sources'] if s['id'] == source_id), None)
        if found is None: raise ValueError('Unknown analysis source')
        value = deepcopy(found)
        parent = self.bundle.get('source_contexts', {}).get(source_id)
        if parent is not None: value['PARENT_CONTEXT_ONLY'] = deepcopy(parent['parent'])
        return value


def from_factory(directory):
    directory = Path(directory)
    plan_path = directory/'plan.json'; inputs_path = directory/'artifacts/agent-inputs.json'
    output_path = directory/'artifacts/output.json'
    plan = read_json(plan_path); generated = read_json(inputs_path); output = read_json(output_path)
    if output.get('agent_inputs') != generated:
        raise ValueError('Factory output and generated agent inputs changed')
    snapshot_path = Path(plan['snapshot'])
    if sha(snapshot_path) != plan['snapshot_sha256']:
        raise ValueError('Factory snapshot changed')
    snapshot = load_snapshot(snapshot_path).snapshot
    search = output.get('membership_search_policy', plan.get('membership_search_policy'))
    if plan.get('membership_search_policy', search) != search:
        raise ValueError('Registered mining policy differs from Factory output')
    maximum = perspective_mining.policy(search)['maximum_snapshot_comments'] if search is not None else 1000
    registry = source_registry(snapshot, include_video_context=True, maximum_comments=maximum)
    bundle = generated['bundle']
    for source in bundle['sources']:
        original = registry.get(source['id'])
        if original is None or original['text'] != source['text']:
            raise ValueError('Generated source does not match original snapshot')
        context = bundle.get('source_contexts', {}).get(source['id'])
        if context is not None and context['parent'] != original.get('parent'):
            raise ValueError('Generated parent context differs from original snapshot')
    video = next((s['video_context'] for s in registry.values() if s.get('video_context')), {})
    provenance = {'automatically_generated': True, 'factory_plan_sha256': sha(plan_path),
                  'factory_output_sha256': sha(output_path), 'agent_inputs_sha256': sha(inputs_path),
                  'snapshot_sha256': plan['snapshot_sha256'],
                  'historical_quality_gate_passed': generated.get('quality_gate_passed', False),
                  'current_quality_qualified': False, 'video': video,
                  'processing_count':len(plan.get('scope_ids',[])) if 'scope_ids' in plan else None,
                  'canonical_population':plan.get('canonical_population')}
    scope = set(plan['scope_ids']) if 'scope_ids' in plan else {s['id'] for s in bundle['sources']}
    presentation = {'likes_by_source': {c.comment_id: c.likes for c in snapshot.comments
                                        if c.comment_id in scope and c.comment_id in registry}}
    names_path = directory/'perspective-names.json'
    if names_path.is_file():
        names = read_json(names_path)
        profiles = {p['candidate_id'] for p in compile_inputs(bundle)['profiles']}
        if not isinstance(names, dict) or not names.keys() <= profiles or any(
                not isinstance(n, str) or not n.strip() or len(n) > 80 for n in names.values()):
            raise ValueError('Expected display names for registered perspectives')
        presentation['names'] = {cid: name.strip() for cid, name in names.items()}
    return Analysis(bundle, provenance, presentation)
