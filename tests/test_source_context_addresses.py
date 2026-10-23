from copy import deepcopy
import json
import unittest

from commentscope.factory import source_context_addresses as addresses, contextual_dependencies as cd
from test_contextual_dependencies import fixture,scope


def select(source,text,origin='source'):
    original=addresses.origins(source)[origin];start=original.index(text);end=start+len(text)
    rows=addresses.inventory(source)
    first=next(r for r in rows if r['origin']==origin and r['span']['start']==start)
    last=next(r for r in rows if r['origin']==origin and r['span']['end']==end)
    return {'first_token':first['id'],'last_token':last['id']}


class SourceContextAddressTests(unittest.TestCase):
    def test_whole_region_contract_keeps_complete_antecedent_and_legacy_tokens(self):
        c,i=fixture('They should receive free meals.',parent={'id':'p','text':'Visiting students arrive tomorrow.'})
        source=c['meaning_context']['source']
        region=next(r for r in addresses.regions(source) if r['origin']=='parent')
        req=cd.request(c['meaning_context'],i,cd.REGIONS)
        self.assertNotIn('$defs',req['schema'])
        self.assertNotIn('CONTEXT_TOKEN_REGIONS',req['data'])
        self.assertEqual(req['data']['ASSERTION'],cd.request(c['meaning_context'],i)['data']['ASSERTION'])
        output={'links':{'R1':region['id']},'scope':'complete','speech':'literal','world':'actual','closure':'complete'}
        record=cd.bind(c['meaning_context'],i,{'output':output},cd.REGIONS)
        cd.validate(record);self.assertTrue(record['ready'])
        self.assertEqual(record['links'][0]['context']['span'],region['span'])
        self.assertEqual(cd.packet(record)['dependencies'][0]['context'],'Visiting students arrive tomorrow')
        self.assertFalse(cd.packet(record)['dependencies'][0]['asserted_separately'])
        with self.assertRaises(ValueError):cd.bind(c['meaning_context'],i,{'output':output},cd.VERSION)
        old=scope(c,i,links={'R1':select(source,'Visiting students','parent')})
        cd.validate(old);self.assertEqual(cd.packet(old)['dependencies'][0]['context'],'Visiting students')

    def test_whole_regions_cannot_crop_self_references_or_remove_nested_holds(self):
        c,i=fixture('It should be repealed.',parent={'id':'p','text':'This rule should begin tomorrow.'})
        source=c['meaning_context']['source'];regions=addresses.regions(source)
        def bind(selection,**changes):
            output={'links':{'R1':selection},'scope':'complete','speech':'literal','world':'actual','closure':'complete',**changes}
            return cd.bind(c['meaning_context'],i,{'output':output},cd.REGIONS)
        own=next(r for r in regions if r['origin']=='source' and r['span']['text']=='It')
        parent=next(r for r in regions if r['origin']=='parent' and r['reference_span'])
        for selection in (own['id'],'Z999',select(source,'rule','parent')):
            with self.assertRaises(ValueError):bind(selection)
        nested=bind(parent['id']);self.assertFalse(nested['ready'])
        self.assertEqual(nested['links'][0]['context']['span']['text'],'This rule')
        self.assertTrue(any(g.startswith('nested_dependency_unresolved') for g in nested['guards']))
        self.assertFalse(bind('unresolved')['ready'])
        self.assertFalse(bind('C1',closure='unresolved')['ready'])
        changed=deepcopy(nested);changed['links'][0]['context']['span']['text']='rule'
        with self.assertRaises(ValueError):cd.validate(changed)

    def test_wire_token_domains_are_not_repeated_for_every_reference(self):
        c,i=fixture('They keep their lunch and they carry their books.')
        request=cd.request(c['meaning_context'],i)
        encoded=json.dumps(request['schema'])
        for token in addresses.inventory(c['meaning_context']['source']):
            self.assertLessEqual(encoded.count(json.dumps(token['id'])),2)
        self.assertEqual(len(request['schema']['properties']['links']['properties']),4)

    def test_trigger_region_is_absent_and_partial_reference_cannot_be_generated(self):
        c,i=fixture('It should be repealed.',parent={'id':'p','text':'This rule should begin tomorrow.'})
        source=c['meaning_context']['source'];req=cd.request(c['meaning_context'],i)
        requirement=cd.inventory(c['meaning_context'])['requirements'][0]
        for region in addresses.regions(source):
            if region['origin']=='source' and region['span']['text']=='It':
                self.assertNotIn(region['id'],requirement['allowed_token_regions'])
            if region['origin']=='parent' and region['reference_span']:
                props=req['schema']['$defs']['context_region_'+region['id']]['properties']
                self.assertEqual(props['first_token']['const'],region['token_ids'][0])
                self.assertEqual(props['last_token']['const'],region['token_ids'][-1])
        cropped=select(source,'rule','parent')
        with self.assertRaises(ValueError):scope(c,i,links={'R1':cropped})
        # Preserve the rejected historical v5 behavior for exact artifact replay.
        old=cd.bind(c['meaning_context'],i,{'output':{'links':{'R1':cropped},'scope':'complete',
                    'speech':'literal','world':'actual','closure':'complete'}},cd.TOKENIZED)
        cd.validate(old);self.assertTrue(old['ready'])
        whole=scope(c,i,links={'R1':select(source,'This rule','parent')})
        self.assertFalse(whole['ready'])

    def test_quoted_reference_boundary_cannot_be_removed_from_an_antecedent(self):
        c,i=fixture('It should be repealed.',parent={'id':'p','text':'The mayor said "This rule begins tomorrow."'})
        source=c['meaning_context']['source']
        with self.assertRaises(ValueError):scope(c,i,links={'R1':select(source,'rule','parent')})
        record=scope(c,i,links={'R1':select(source,'This rule','parent')})
        self.assertFalse(record['ready'])

    def test_local_antecedent_is_context_only_without_rewriting_or_importing_a_fact(self):
        for text,antecedent in [('Everyone brings their own lunch.','Everyone'),
                                ('Every passenger keeps their own ticket.','Every passenger')]:
            c,i=fixture(text);source=c['meaning_context']['source']
            record=scope(c,i,links={'R1':select(source,antecedent)})
            self.assertTrue(record['ready']);cd.validate(record)
            packet=cd.packet(record)
            self.assertEqual(packet['assertion'],text)
            self.assertEqual(packet['dependencies'][0]['context'],antecedent)
            self.assertFalse(packet['dependencies'][0]['asserted_separately'])
            self.assertFalse(record['links'][0]['context']['semantic_coreference_verified'])

    def test_forward_antecedent_and_precise_parent_phrase_can_be_addressed(self):
        c,i=fixture('They should receive free meals. Visiting students arrive tomorrow.')
        source=c['meaning_context']['source']
        self.assertFalse(cd.inventory(c['meaning_context'])['choices'])
        record=scope(c,i,links={'R1':select(source,'Visiting students')})
        self.assertTrue(record['ready'])
        self.assertNotIn('arrive tomorrow',str(cd.packet(record)))
        c,i=fixture('They should receive free meals.',parent={'id':'p','text':'Visiting students arrive tomorrow.'})
        record=scope(c,i,links={'R1':select(c['meaning_context']['source'],'Visiting students','parent')})
        self.assertTrue(record['ready']);self.assertEqual(record['links'][0]['context']['origin'],'parent')

    def test_wrong_origin_sentence_order_self_reference_and_foreign_ids_are_rejected(self):
        c,i=fixture('Everyone brings their own lunch. Visitors arrive.',parent={'id':'p','text':'People arrive.'})
        source=c['meaning_context']['source'];everyone=select(source,'Everyone');visitors=select(source,'Visitors')
        parent=select(source,'People','parent');own=select(source,'their');lunch=select(source,'lunch')
        invalid=[{'first_token':everyone['first_token'],'last_token':parent['last_token']},
                 {'first_token':everyone['first_token'],'last_token':visitors['last_token']},
                 {'first_token':lunch['first_token'],'last_token':everyone['last_token']},
                 own,{'first_token':'T999','last_token':'T999'},
                 {**everyone,'new_text':'Invented people'}]
        for selected in invalid:
            with self.assertRaises(ValueError):scope(c,i,links={'R1':selected})

    def test_nested_reference_and_unresolved_scope_are_not_bypassed_by_precise_spans(self):
        c,i=fixture('It should be repealed.',parent={'id':'p','text':'This rule should begin tomorrow.'})
        record=scope(c,i,links={'R1':select(c['meaning_context']['source'],'This rule','parent')})
        self.assertFalse(record['ready'])
        self.assertTrue(any(g.startswith('nested_dependency_unresolved') for g in record['guards']))
        c,i=fixture('Everyone brings their own lunch.')
        record=scope(c,i,links={'R1':select(c['meaning_context']['source'],'Everyone')},closure='unresolved')
        self.assertFalse(record['ready'])

    def test_address_changes_and_changed_source_cannot_replay_the_old_proof(self):
        c,i=fixture('Everyone brings their own lunch.')
        record=scope(c,i,links={'R1':select(c['meaning_context']['source'],'Everyone')})
        for change in (lambda r:r['links'][0]['context']['span'].update(text='Different people'),
                       lambda r:r['output']['links']['R1'].update(last_token='T999'),
                       lambda r:r['bundle']['source'].update(text='Different original.')):
            altered=deepcopy(record);change(altered)
            with self.assertRaises(ValueError):cd.validate(altered)

    def test_old_v4_stays_replayable_and_cannot_accept_new_token_objects(self):
        c,i=fixture('A public garden opens tomorrow. It should be free.',index=1)
        output={'links':{'R1':'C1'},'scope':'complete','speech':'literal','world':'actual','closure':'complete'}
        old=cd.bind(c['meaning_context'],i,{'output':output},cd.DISCOURSE);cd.validate(old)
        self.assertNotIn('CONTEXT_TOKENS',cd.request(c['meaning_context'],i,cd.DISCOURSE)['data'])
        output['links']['R1']=select(c['meaning_context']['source'],'A public garden')
        with self.assertRaises(ValueError):cd.bind(c['meaning_context'],i,{'output':output},cd.DISCOURSE)


if __name__=='__main__':unittest.main()
