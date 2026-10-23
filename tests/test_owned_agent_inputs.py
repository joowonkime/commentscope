"""Conditional speech acts versus asserted facts at the compiler boundary."""
from dataclasses import replace
from pathlib import Path
import unittest

from commentscope.factory import explicit_discourse as ed, owned_arguments as oa
from commentscope.factory import minimal_claims as mc, minimal_membership as mm, source_arguments as sa, minimal_agents as ma
from commentscope.factory import proposition_requirements as pr, qualification_ownership as qo
from commentscope.ingestion import load_snapshot
from experiments.grounding_contract_demo import MODEL
from test_minimal_factory import extraction


def qualification(source,text):
    shape=pr.bind_shape(text,{'output':{'status':'complete','qualifications':[]}})
    witnesses=[qo.bind_pair(source,text,p,{'output':{'parent_relation':'equivalent',
        'ground_relation':'equivalent','authorship':'yes'}}) for p in qo.pairs(source,text)]
    return pr.assessment(source,shape,[],qo.assessment(source,text,witnesses))


class OwnedAgentInputTests(unittest.TestCase):
    def prepare(self,conditional):
        target='Adopt P only if funding is available.' if conditional else 'Adopt P.'
        full=target if conditional else 'Adopt P because the program costs 1000 dollars.'
        sources=[{'id':f's{i}','text':full+f' Additional request {i}.','parent':None} for i in range(3)]
        candidates=mc.candidates(extraction(sources,{s['id']:[target] for s in sources}));c=candidates[0]
        cores=[oa.bind_core(c,{'output':{'kind':'value','entity':'P','time_ids':[]}})]
        memberships=[];records=[]
        for source in sources:
            pair={'source_id':source['id'],'candidate_id':c['id']}
            member=mm.bind([source],candidates,[pair],{'output':{'decisions':[{'pair_id':'P1','relation':'supported',
                'authorship':'asserted_or_endorsed','scope_preserved':'yes','evidence_segment_ids':['S000']}]}},
                [{**pair,'assessment':qualification(source,target)}])
            memberships.append(member);g=ed.parse(source);metadata=[];alignments=[]
            for n in g['nodes']:
                req=oa.metadata_request(g,n)
                values={'kind':'fact' if n['kind']=='ground' else 'value','authorship':'asserted_or_endorsed',
                    'entity':'P','time_ids':[],'source_language':'en'}
                metadata.append(oa.bind_metadata(g,n,{'output':{k:values[k] for k in req['schema']['properties']}}))
                if n['kind']=='statement':
                    relation='different' if n['span']['text'].startswith('Additional') else 'equivalent'
                    quals=[] if relation=='different' else [qualification({'id':n['id'],'text':n['span']['text'],'parent':None},target),
                        qualification({'id':c['id'],'text':target,'parent':None},n['span']['text'])]
                    alignments.append(oa.bind_alignment(g,n,c,{'output':{'relation':relation}},quals))
            record=oa.declare(g,candidates,[member],metadata,alignments)
            result=None if sa.link_request(record) is None else {'output':{'status':'complete','links':[
                {'local_id':u['local_id'],'requires':[],'core_requires_for':[]} for u in record['units']]}}
            records.append(sa.bind_links(record,result))
        tasks=sa.audit_tasks(records,cores);audits=[]
        for t in tasks:
            req=sa.audit_request(records,cores,[t])
            audits.append(sa.bind_audit(records,cores,[t],{'output':{'decisions':[
                {'task_id':req['data']['TASKS'][0]['task_id'],'verdict':'supported'}]}}))
        template=load_snapshot(Path('tests/fixtures/synthetic-snapshot.json')).snapshot
        snapshot=replace(template,usage=replace(template.usage,expires_at='2099-01-01T00:00:00Z'),
            comments=tuple(replace(template.comments[0],comment_id=s['id'],text_original=s['text'],parent_id=None) for s in sources))
        return ma.prepare(snapshot,candidates,memberships,records,cores,audits,model=MODEL),records

    def test_condition_preserved_in_core_without_asserting_antecedent_as_fact(self):
        output,records=self.prepare(True)
        self.assertEqual(len(output['compiled']['profiles']),1)
        core=next(c for c in output['bundle']['claims'] if c['id'].endswith(':C'))
        self.assertEqual(core['scope']['conditions'],'only if funding is available.')
        self.assertTrue(all(c['text']!='only if funding is available.' for c in output['bundle']['claims']))
        self.assertFalse(output['bundle']['candidates'][0]['major_fact_ids'])
        for r in records:
            annotation=next(u for u in r['units'] if u['role']=='essential_condition')
            self.assertEqual(annotation['runtime_exposure'],'scope_annotation_only')
            self.assertEqual(annotation['text'],'only if funding is available.')
            self.assertEqual(r['status'],'complete')

    def test_asserted_factual_reason_still_blocks_agent_without_external_evidence(self):
        output,records=self.prepare(False)
        self.assertFalse(output['compiled']['profiles'])
        facts=[c for c in output['bundle']['claims'] if c['kind']=='fact']
        self.assertEqual(len(facts),3)
        self.assertEqual(len(output['bundle']['candidates'][0]['major_fact_ids']),3)
        self.assertTrue(all(c['text']=='because the program costs 1000 dollars.' for c in facts))
