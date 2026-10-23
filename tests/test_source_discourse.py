from copy import deepcopy
import unittest
from commentscope.factory import source_discourse as sd,explicit_discourse as ed
from commentscope.factory.automatic_contract import digest
from commentscope.factory import owned_arguments as oa,owned_node_entailment as own,minimal_claims as mc
from test_minimal_factory import membership
from test_source_entailment import nli_response


class SourceDiscourseTests(unittest.TestCase):
    def graph(self,text='I hope P is introduced. Would make stressed people more relaxed.'):
        return ed.parse({'id':'own','text':text,'parent':{'id':'parent','text':'A different author offers a different rationale.'}})
    def bind(self,graph,relations):
        aliases={n['id']:f'N{i}' for i,n in enumerate(graph['nodes'],1)};rows=[]
        for p,r in zip(sd.tasks(graph),relations,strict=True):
            if r in ('independent','uncertain'):kind=r;parent=child='none'
            else:
                parent,child=(p['first'],p['second']) if r.startswith('second_') else (p['second'],p['first'])
                parent,child=aliases[parent],aliases[child]
                kind='essential_condition' if 'condition' in r else 'concession' if 'concession' in r else 'reason'
            rows.append({'pair_id':p['id'],'relation':kind,'position_node_id':parent,'ground_node_id':child})
        return sd.bind(graph,{'output':{'decisions':rows}})

    def test_owned_consequence_keeps_exact_parent_ground_without_text_generation(self):
        graph=self.graph();before=digest(graph);record=self.bind(graph,['second_reason_for_first'])
        edge=sd.usable_edges(graph,record)[0];proof=sd.ownership(graph,edge,record)
        self.assertEqual(proof['position']['span']['text'],'I hope P is introduced.')
        self.assertEqual(proof['ground']['span']['text'],'Would make stressed people more relaxed.')
        self.assertEqual(digest(graph),before);self.assertFalse(proof['factual_verification'])
        self.assertNotIn('CANDIDATE',sd.request(graph)['data'])

    def test_explicit_role_ids_preserve_direction_in_either_sentence_order(self):
        cases=[('Adopt P. This would improve access.','N1','N2'),
            ('This would improve access. Adopt P.','N2','N1')]
        for text,position,ground in cases:
            graph=self.graph(text);record=sd.bind(graph,{'output':{'decisions':[{
                'pair_id':'L1','relation':'reason','position_node_id':position,'ground_node_id':ground}]}})
            proof=sd.ownership(graph,record['edges'][0],record)
            self.assertEqual(proof['position']['span']['text'],'Adopt P.')
            self.assertEqual(proof['ground']['span']['text'],'This would improve access.')

    def test_same_foreign_or_unrelated_role_ids_and_independent_ownership_are_rejected(self):
        graph=self.graph('Adopt P. This would improve access. Other matters differ.')
        for relation,position,ground in [('reason','N1','N1'),('reason','N1','parent'),
                ('reason','N3','N2'),('independent','N1','N2')]:
            rows=[{'pair_id':'L1','relation':relation,'position_node_id':position,'ground_node_id':ground},
                {'pair_id':'L2','relation':'independent','position_node_id':'none','ground_node_id':'none'}]
            with self.assertRaises(ValueError):sd.bind(graph,{'output':{'decisions':rows}})
    def test_independent_or_uncertain_does_not_invent_a_reason(self):
        graph=self.graph();record=self.bind(graph,['independent']);self.assertFalse(sd.usable_edges(graph,record))
        record=self.bind(graph,['uncertain'])
        with self.assertRaises(ValueError):sd.usable_edges(graph,record)
    def test_inferred_conditions_cannot_be_erased_into_optional_reasons(self):
        graph=self.graph();record=self.bind(graph,['second_condition_for_first'])
        self.assertIn('inferred_condition_requires_complete_scope_interpretation',record['hold_reasons'])
        with self.assertRaises(ValueError):sd.usable_edges(graph,record)
    def test_nested_or_multiple_parent_ownership_stays_held(self):
        graph=self.graph('Adopt P. Costs are low. Access improves.')
        record=self.bind(graph,['second_reason_for_first','second_reason_for_first'])
        self.assertIn('nested_or_cyclic_discourse_requires_interpretation',record['hold_reasons'])
        record=self.bind(graph,['second_reason_for_first','first_reason_for_second'])
        self.assertIn('source_discourse_multiple_parents',record['hold_reasons'])
    def test_context_is_bound_to_actual_source_interpretation_and_literal_parent(self):
        graph=self.graph();record=self.bind(graph,['second_reason_for_first']);child=graph['nodes'][1]
        context=sd.metadata_context(graph,child,record);wire=sd.context_wire(graph,child,context)
        self.assertEqual(wire['relation'],'reason');self.assertEqual(wire['PARENT_LITERAL']['text'],'I hope P is introduced.')
        context['parent_span']['text']='Invented reason from parent author.'
        with self.assertRaises(ValueError):sd.context_wire(graph,child,context)
    def test_mutated_missing_or_unknown_pair_bindings_fail_closed(self):
        graph=self.graph();record=self.bind(graph,['second_reason_for_first'])
        changed=deepcopy(record);changed['edges'][0]['parent_id']='outside-author'
        with self.assertRaises(ValueError):sd.validate(graph,changed)
        for decisions in [[],[{'pair_id':'outside','relation':'independent'}]]:
            with self.assertRaises(ValueError):sd.bind(graph,{'output':{'decisions':decisions}})
        self.assertIsNone(sd.request(self.graph('Adopt P.')))
        with self.assertRaises(ValueError):sd.request(self.graph('Adopt P only if costs fall. Why?'))

    def test_declaration_cannot_borrow_typing_from_another_discourse_interpretation(self):
        graph=self.graph();root,child=graph['nodes'];record=self.bind(graph,['second_reason_for_first'])
        text='P can be desirable.';cid=mc.claim_id(text)
        candidate={'id':cid,'text':text,'aliases':[cid],'nominees':{'own':digest(graph['source'])},
            'extraction_refs':[digest(['controller fixture',graph])],'equivalence_refs':[]}
        def metadata(node,kind,interpretation=None):
            context=sd.metadata_context(graph,node,interpretation) if interpretation else None
            values={'authorship':'asserted_or_endorsed','kind':kind,'entity':'P','time_ids':[],'source_language':'en'}
            req=oa.metadata_request(graph,node,context)
            return oa.bind_metadata(graph,node,{'output':{k:values[k] for k in req['schema']['properties']}},context)
        typed=[metadata(root,'value'),metadata(child,'prediction',record)]
        jobs=[{'graph':graph,'node':root,'candidate':candidate,'metadata':typed[0]}]
        proofs=own.records(jobs,nli_response(own.invocation(jobs)))
        batches=[membership([graph['source']],[candidate],[{'source_id':'own','candidate_id':cid}])]
        declared=oa.declare(graph,[candidate],batches,typed,proofs,discourse=record)
        oa.validate(declared);self.assertEqual(declared['status'],'complete')
        self.assertEqual(next(u for u in declared['units'] if u['role']=='reason')['kind'],'prediction')
        other=self.bind(graph,['second_concession_to_first'])
        for wrong in [metadata(child,'prediction'),metadata(child,'prediction',other)]:
            with self.assertRaises(ValueError):
                oa.declare(graph,[candidate],batches,[typed[0],wrong],proofs,discourse=record)
        unasserted=oa.bind_metadata(graph,root,{'output':{'authorship':'not_asserted','kind':'value',
            'entity':'P','time_ids':[],'source_language':'en'}})
        held=oa.declare(graph,[candidate],batches,[unasserted,typed[1]],[],discourse=record)
        self.assertEqual(held['status'],'unresolved')
        self.assertEqual(next(u for u in held['units'] if u['role']=='reason')['authorship'],'not_asserted')
