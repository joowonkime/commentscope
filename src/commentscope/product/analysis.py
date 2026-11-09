"""Register all generated profiles without promoting historical quality claims."""
from copy import deepcopy
from pathlib import Path

from commentscope.agents.grounded_inputs import compile_inputs, prompt_input
from commentscope.factory.automatic_contract import digest
from commentscope.factory.claim_clusters import read_json, sha
from commentscope.factory.framed_corpus import sources as source_registry
from commentscope.factory.fact_checks import live
from commentscope.ingestion import load_snapshot


class Analysis:
    def __init__(self, bundle, provenance):
        self.bundle = deepcopy(bundle)
        self.compiled = compile_inputs(self.bundle)
        self.provenance = deepcopy(provenance)
        self.revision = digest(self.bundle)
        self.id = 'AN'+digest([self.revision, self.provenance])[:24]

    def live(self):
        if digest(self.bundle)!=self.revision:raise ValueError('Registered analysis changed')
        live(self.bundle['expires_at'])

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
                grounds=[]
                for entry in profile['prompt_entries']:
                    role=candidate.get('argument_roles',{}).get(entry['claim_id'],'reason')
                    if entry['claim_id'] in candidate['reason_claim_ids'] and role in ('reason','essential_condition','concession'):
                        grounds.append({'claim_id':entry['claim_id'],'text':entry['text'],'kind':entry['kind'],
                                        'role':role,'source_count':entry['member_source_count']})
                for evidence in profile['citations'][candidate['core_claim_id']]['comment_evidence']:
                    memberships.setdefault(canonical[evidence['source_id']],set()).add(cid)
                perspectives.append({'id': cid, 'text': core['text'], 'kind': core['kind'],
                                     'source_count': profile['model_core_support_count'],'grounds':grounds})
        known=self.provenance.get('processing_count')
        analyzed=known if type(known) is int else len({s.get('canonical_id',s['id']) for s in self.bundle['sources']})
        composition=[{'perspective_id':p['id'],'count':sum(ids=={p['id']} for ids in memberships.values())} for p in perspectives]
        composition.extend([{'perspective_id':None,'kind':'multiple','count':sum(len(ids)>1 for ids in memberships.values())},
                            {'perspective_id':None,'kind':'other','count':max(0,analyzed-len(memberships))}])
        return {'analysis_id': self.id, 'bundle_revision': self.revision,
                'status': 'expired' if expired else 'experimental',
                'semantic_reliability': 'not_assessed', 'quality_gate_passed': False,
                'expires_at': self.bundle['expires_at'], 'perspectives': perspectives,
                'analyzed_comments':analyzed,'canonical_population':self.provenance.get('canonical_population'),
                'count_scope':'processed_comments' if known is not None else 'registered_sources',
                'composition':composition,
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
    registry = source_registry(snapshot, include_video_context=True)
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
    return Analysis(bundle, provenance)
