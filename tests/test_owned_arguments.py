from copy import deepcopy
import unittest
from commentscope.factory import owned_arguments as oa, explicit_discourse as ed
from commentscope.factory import minimal_claims as mc, proposition_requirements as pr
from commentscope.factory import source_arguments as sa
from test_minimal_factory import extraction, membership


class OwnedArgumentTests(unittest.TestCase):
    def setUp(self):
        self.source={'id':'s','text':'Adopt P. Start immediately because fairness matters.','parent':None}
        self.graph=ed.parse(self.source)
        self.candidates=mc.candidates(extraction([self.source],{'s':['Adopt P.']}))
        self.candidate=self.candidates[0];self.cid=self.candidate['id']
        self.members=[membership([self.source],self.candidates,[{'source_id':'s','candidate_id':self.cid}])]

    def metadata(self,**changes):
        result=[]
        for node in self.graph['nodes']:
            values={'authorship':'asserted_or_endorsed','kind':'value','entity':'P',
                    'time_ids':[a['id'] for a in oa.temporal_anchors(node['span']['text'])],
                    'source_language':'en',**changes}
            req=oa.metadata_request(self.graph,node)
            result.append(oa.bind_metadata(self.graph,node,{'output':{
                key:values[key] for key in req['schema']['properties']}}))
        return result

    def alignment(self,node,relation):
        quals=[]
        if relation=='equivalent':
            for source,text in (({'id':node['id'],'text':node['span']['text'],'parent':None},self.candidate['text']),
                ({'id':self.cid,'text':self.candidate['text'],'parent':None},node['span']['text'])):
                shape=pr.bind_shape(text,{'output':{'status':'complete','qualifications':[]}})
                quals.append(pr.assessment(source,shape,[]))
        return oa.bind_alignment(self.graph,node,self.candidate,{'output':{'relation':relation}},quals)

    def record(self):
        roots=[n for n in self.graph['nodes'] if n['kind']=='statement']
        aligns=[self.alignment(n,'equivalent' if i==0 else 'different') for i,n in enumerate(roots)]
        return oa.declare(self.graph,self.candidates,self.members,self.metadata(),aligns)

    def test_extra_request_and_reason_retained_but_cannot_become_core_reason(self):
        record=self.record();oa.validate(record)
        self.assertEqual(record['status'],'complete')
        self.assertEqual(record['units'][0]['candidate_roles'],{self.cid:'core_restatement'})
        self.assertEqual([u['candidate_ids'] for u in record['units'][1:]],[[],[]])
        self.assertEqual(record['units'][2]['text'],'because fairness matters.')
        self.assertEqual(record['ownership_proofs'][0]['position']['span']['text'],'Start immediately')
        for mutate in (lambda r:r['units'][2].update(candidate_ids=[self.cid]),
                       lambda r:r['units'][2].update(text='Invented motive.'),
                       lambda r:r['units'][2].update(ownership_family=r['units'][0]['source_node_id'])):
            changed=deepcopy(record);mutate(changed)
            with self.assertRaises(ValueError):oa.validate(changed)

    def test_metadata_cannot_write_text_role_conditions_or_free_time(self):
        root=self.graph['nodes'][0];req=oa.metadata_request(self.graph,root)
        props=req['schema']['properties']
        self.assertFalse({'text','role','parent','conditions','time'}&set(props))
        self.assertEqual(req['data']['TEMPORAL_ANCHORS'],[])
        value={'authorship':'asserted_or_endorsed','kind':'value','entity':'P','time_ids':['T1'],'source_language':'en'}
        with self.assertRaises(ValueError):oa.bind_metadata(self.graph,root,{'output':value})
        candidate=mc.candidates(extraction([self.source],{'s':['Adopt P only if funded.']}))[0]
        core=oa.bind_core(candidate,{'output':{'kind':'value','entity':'P','time_ids':[]}})
        self.assertEqual(core['output']['scope']['conditions'],'only if funded.')
        changed=deepcopy(core);changed['output']['scope']['conditions']=''
        with self.assertRaises(ValueError):oa.validate_core(changed)

    def test_unqualified_equivalent_is_unknown_not_approved(self):
        root=self.graph['nodes'][0]
        row=oa.bind_alignment(self.graph,root,self.candidate,{'output':{'relation':'equivalent'}})
        self.assertEqual(row['relation'],'uncertain')
        roots=[n for n in self.graph['nodes'] if n['kind']=='statement']
        record=oa.declare(self.graph,self.candidates,self.members,self.metadata(),[row,self.alignment(roots[1],'different')])
        self.assertEqual(record['status'],'unresolved')

    def test_missing_nodes_alignments_or_unknown_authorship_hold_or_reject(self):
        record=self.record()
        with self.assertRaises(ValueError):oa.declare(self.graph,self.candidates,self.members,self.metadata()[:-1],record['alignments'])
        with self.assertRaises(ValueError):oa.declare(self.graph,self.candidates,self.members,self.metadata(),record['alignments'][:-1])
        meta=self.metadata()
        with self.assertRaises(ValueError):
            oa.bind_metadata(self.graph,self.graph['nodes'][-1],{'output':{**meta[-1]['output'],'authorship':'unclear'}})
        # A linked ground must not turn an unresolved parent into an own claim.
        index=next(i for i,n in enumerate(self.graph['nodes']) if n['id']==self.graph['edges'][0]['parent_id'])
        meta[index]=oa.bind_metadata(self.graph,self.graph['nodes'][index],{'output':{**meta[index]['output'],'authorship':'unclear'}})
        alignments=[a for a in record['alignments'] if a['node_id']!=self.graph['nodes'][index]['id']]
        held=oa.declare(self.graph,self.candidates,self.members,meta,alignments)
        self.assertEqual(held['status'],'unresolved')
        self.assertEqual(held['units'][-1]['authorship'],'unclear')

    def test_factual_type_preserved_and_compound_core_held_without_reclassification(self):
        meta=self.metadata(kind='fact');record=self.record()
        factual=oa.declare(self.graph,self.candidates,self.members,meta,record['alignments'])
        self.assertTrue(all(u['kind']=='fact' for u in factual['units']))
        candidate=mc.candidates(extraction([self.source],{'s':['Adopt P because it costs less.']}))[0]
        core=oa.bind_core(candidate,{'output':{'kind':'fact','entity':'P','time_ids':[]}})
        self.assertEqual(core['output']['kind'],'fact')
        self.assertIn('compound_core_requires_separate_interpretation',core['hold_reasons'])

    def test_dependency_cannot_cross_fixed_parent_or_promote_personal_ground(self):
        record=self.record()
        meta=self.metadata(kind='fact')
        record=oa.declare(self.graph,self.candidates,self.members,meta,record['alignments'])
        rows=[{'local_id':u['local_id'],'requires':[],'core_requires_for':[]} for u in record['units']]
        linked=sa.bind_links(record,{'output':{'status':'complete','links':rows}})
        sa.validate(linked)
        changed=deepcopy(rows);changed[0]['requires']=['U3']
        with self.assertRaises(ValueError):sa.bind_links(record,{'output':{'status':'complete','links':changed}})
        changed=deepcopy(rows);changed[2]['core_requires_for']=[self.cid]
        with self.assertRaises(ValueError):sa.bind_links(record,{'output':{'status':'complete','links':changed}})
        changed=deepcopy(rows);changed[1]['requires']=['U3']
        self.assertEqual(sa.bind_links(record,{'output':{'status':'complete','links':changed}})['units'][1]['requires'],['U3'])

    def test_temporal_loss_rejected_even_when_model_and_empty_inventory_agree(self):
        root=next(n for n in self.graph['nodes'] if n['span']['text']=='Start immediately')
        row=self.alignment(root,'equivalent')
        self.assertEqual(row['output']['relation'],'equivalent')
        self.assertEqual(row['relation'],'uncertain')

    def test_owned_audit_aliases_rebind_to_exact_unit_and_core(self):
        record=sa.bind_links(self.record());records=[record]
        core=oa.bind_core(self.candidate,{'output':{'kind':'value','entity':'P','time_ids':[]}})
        tasks=sa.audit_tasks(records,[core]);req=sa.audit_request(records,[core],tasks)
        self.assertEqual([t['task_id'] for t in req['data']['TASKS']],['T1','T2','T3','T4'])
        audit=sa.bind_audit(records,[core],tasks,{'output':{'decisions':[
            {'task_id':t['task_id'],'verdict':'supported'} for t in req['data']['TASKS']]}})
        self.assertEqual(set(sa.audit_verdicts(records,[core],[audit])),{t['task_id'] for t in tasks})
        audit['output']['decisions'][0]['task_id']='foreign'
        with self.assertRaises(ValueError):sa.audit_verdicts(records,[core],[audit])
