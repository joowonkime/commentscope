from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from commentscope.factory import literal_discovery as ld, explicit_discourse as ed, minimal_claims as mc, source_scope as ss
from commentscope.factory.automatic_contract import digest
from experiments.minimal_discovery_probe import extract


def graph(text, parent=None):
    return ed.parse({'id':'s','text':text,'parent':parent})


def response(req, **changes):
    return {t['id']:{'role':'topic_position','speaker':'comment_author',
                     **changes} for t in req['data']['TARGETS']}


def select(g, changes=None, certificates=()):
    ids=[n['id'] for n in ld.roots(g)];req=ld.selection_request(g,ids);value=response(req)
    for k,v in (changes or {}).items():
        v=deepcopy(v)
        if 'authorship' in v:
            author=v.pop('authorship');v['speaker']={value:key for key,value in ld.SPEAKERS.items()}[author]
        value[k].update(v)
    return ld.assemble(g,[ld.bind_selection(g,ids,{'output':value})],certificates)


class LiteralDiscoveryTests(unittest.TestCase):
    def test_false_model_cannot_generate_parent_statistic_or_rewrite_typo(self):
        g=graph('Deal with it',{'id':'parent','text':'42 percent are unhappy.'})
        record=select(g);self.assertFalse(record['claims'])
        self.assertIn('unresolved_reference:R1',record['holds'][0]['scope_projection']['holds'])
        self.assertNotIn('42 percent',str(record['claims']))
        ids=[n['id'] for n in ld.roots(g)];req=ld.selection_request(g,ids);value=response(req)
        value['N1']['text']='42 percent are unhappy.'
        with self.assertRaises(ValueError):ld.bind_selection(g,ids,{'output':value})
        self.assertEqual(select(graph('Honestly i cant do nothing all day lol'))['claims'][0]['text'],
                         'Honestly i cant do nothing all day lol')

    def test_topic_transfer_preserves_literal_negation_and_complete_conditions(self):
        for topic in ('school meals','park access','road pricing','film ratings','tax reform','lab reviews'):
            for prefix in ('Adopt','Do not adopt'):
                text=f'{prefix} {topic} only if funding is available.'
                record=select(graph(text));self.assertEqual(record['claims'][0]['text'],text)
                self.assertEqual(record['claims'][0]['essential_conditions'][0]['text'],'only if funding is available.')
                ld.validate(record);mc.validate(record)
        text='추가 비용이 없을 때만 이 계획에 찬성합니다.'
        self.assertEqual(select(graph(text))['claims'][0]['text'],text)

    def test_reason_stays_under_own_parent_and_is_retained_without_rewriting(self):
        g=graph('Preserve the archive. Open on Sunday because weekdays are busy.')
        record=select(g);self.assertEqual([c['text'] for c in record['claims']],['Preserve the archive.','Open on Sunday'])
        self.assertEqual(record['retained_ground_ids'],[g['edges'][0]['ground_id']])
        self.assertFalse(any('weekdays' in c['text'] for c in record['claims']))
        self.assertEqual(g['nodes'][-1]['span']['text'],'because weekdays are busy.')

    def test_frame_context_is_bound_without_importing_independent_claims(self):
        g=graph('In a fictional city. Everyone receives a grant. Housing costs fall.')
        record=select(g,{'N1':{'role':'framing_context'}})
        self.assertEqual([c['text'] for c in record['claims']],
                         ['In a fictional city. Everyone receives a grant.',
                          'In a fictional city. Housing costs fall.'])
        self.assertEqual(record['claims'][1]['evidence'][0]['text'],'Housing costs fall.')
        ld.validate(record)
        ids=[n['id'] for n in ld.roots(g)];req=ld.selection_request(g,ids)
        for invalid in ('PARENT_CONTEXT_ONLY','S3','self_contained'):
            value=response(req);value['N2'].update(scope=invalid)
            with self.assertRaises(ValueError):ld.bind_selection(g,ids,{'output':value})
        # A title-case imperative is still a position unless the role decision
        # explicitly proposes a frame; code does not pretend to prove that role.
        self.assertEqual(select(graph('Ban Cars! Build Trams.'))['claims'][0]['text'],'Ban Cars!')
        record=select(graph('Build a bridge. Reduce fares.'),{'N2':{'role':'framing_context'}})
        self.assertEqual(len(record['claims']),1);self.assertTrue(record['holds'])

    def test_unknown_or_outside_context_keeps_original_and_has_no_nomination(self):
        record=select(graph('That did not work.'))
        self.assertEqual(record['status'],'unresolved');self.assertFalse(record['claims'])
        self.assertEqual(record['source']['text'],'That did not work.')
        self.assertFalse(mc.candidates([record]));self.assertTrue(record['holds'])

    def test_reported_question_and_quoted_text_cannot_become_votes_by_default(self):
        for text,expected in (('"Adopt P."','reported'),('Should we adopt P?','uncertain')):
            record=select(graph(text));self.assertEqual(record['claims'][0]['authorship'],expected)
            self.assertFalse(mc.candidates([record]))
        record=select(graph('Some people say adopt P.'),{'N1':{'authorship':'reported'}})
        self.assertEqual(record['claims'][0]['authorship'],'reported');self.assertFalse(mc.candidates([record]))
        record=select(graph('30% "Adopt P!"'))
        self.assertEqual(record['claims'][0]['authorship'],'reported');self.assertFalse(mc.candidates([record]))

    def test_every_address_once_and_provenance_replayed(self):
        g=graph('Adopt P. Retain Q.');ids=[n['id'] for n in ld.roots(g)]
        req=ld.selection_request(g,ids);value=response(req)
        for bad in ({'N1':value['N1']},{**value,'N3':value['N1']}):
            with self.assertRaises(ValueError):ld.bind_selection(g,ids,{'output':bad})
        b=ld.bind_selection(g,ids,{'output':value})
        with self.assertRaises(ValueError):ld.assemble(g,[b,b])
        record=ld.assemble(g,[b]);self.assertFalse(record['generated_assertion_text'])
        for mutate in (lambda r:r['claims'][0].update(text='Other claim.'),
                       lambda r:r['claims'][0]['evidence'][0].update(start=4),
                       lambda r:r['selection_batches'][0]['selections'][0].update(authorship='reported'),
                       lambda r:r['source'].update(parent={'id':'x','text':'New context.'})):
            changed=deepcopy(record);mutate(changed)
            with self.assertRaises(ValueError):mc.validate(changed)

    def test_same_literal_is_one_nomination_and_capacity_never_truncates(self):
        record=select(graph('Adopt P. Adopt P.'));self.assertEqual(len(record['claims']),1)
        self.assertEqual(len(record['claims'][0]['source_selections']),2)
        self.assertEqual(len(mc.candidates([record])),1)
        record=select(graph('a'*601));self.assertFalse(record['claims'])
        self.assertEqual(record['holds'][0]['reason'],'literal_claim_capacity')
        with self.assertRaises(ValueError):mc.extraction_request([record['source']],[record])

    def test_partial_failure_preserves_classified_nodes_without_retry(self):
        originals=[{'id':'first','text':' '.join(f'Item {i} matters.' for i in range(18)),'parent':None},
                   {'id':'second','text':'Adopt R.','parent':None}]
        class Runner:
            def __init__(self):self.calls=0
            def call(self,stage,req):
                self.calls+=1;value=response(req)
                if self.calls==2:value={}
                return {'output':value,'raw':'scripted','errors':[]}
        runner=Runner()
        with TemporaryDirectory() as tmp:
            result=extract(Path(tmp),runner,originals,
                inspect=lambda req:{'request_sha256':digest(req),'fits':True},mode='literal')
        self.assertEqual(runner.calls,4);self.assertEqual(len(result['errors']),1)
        self.assertEqual(len(result['extractions'][0]['claims']),10)
        self.assertEqual(result['extractions'][0]['status'],'partial')
        self.assertEqual(result['extractions'][1]['status'],'covered')
        self.assertFalse(result['quality_gate_passed'])


if __name__=='__main__':unittest.main()
