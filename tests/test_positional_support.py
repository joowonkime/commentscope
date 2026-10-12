import unittest
from copy import deepcopy

from commentscope.factory import positional_support as p
from commentscope.factory.automatic_contract import digest
from experiments.raw_support_probe import source
from tests.test_raw_support import score


def value(**changes):
    return {'assertion':'affirmed','eligibility':'substantive',**{f:'preserved' for f in p.FIELDS},
            'evidence':[{'first':'S000','last':'S000'}],**changes}


class PositionalSupportTests(unittest.TestCase):
    def test_source_positions_copy_exact_unicode_and_repeated_occurrence(self):
        text='조건이 중요하다. Other. 조건이 중요하다.'
        span=p.bind(text,[{'first':'S002','last':'S002'}])
        self.assertEqual(span['text'],'조건이 중요하다.')
        self.assertEqual(text[span['start']:span['end']],span['text'])
        self.assertEqual(span['source_digest'],digest(text))
        self.assertGreater(span['start'],0)

    def test_invalid_foreign_reversed_or_free_text_positions_rejected(self):
        for ranges in [[{'first':'S001','last':'S000'}],[{'first':'L000','last':'L000'}],
                       [{'first':'S000','last':'S999'}],[{'first':'S000','last':'S000','text':'invented'}]]:
            with self.assertRaises(ValueError):p.bind('One. Two.',ranges)

    def test_no_short_quote_limit_or_silent_clipping(self):
        text='x'*900
        self.assertEqual(p.bind(text,[{'first':'S000','last':'S000'}])['text'],text)

    def test_semantic_contradiction_is_valid_contract_and_host_rejects(self):
        v=value(conditions='changed')
        self.assertEqual(p.validate_audit(v,'Source.'),[])
        self.assertEqual(p.project(v),'not_supported')
        self.assertEqual(p.project(value(presuppositions='unclear')),'uncertain')
        self.assertEqual(p.project(value(evidence=[])),'uncertain')

    def test_non_substantive_and_unresolved_referents_do_not_pass(self):
        self.assertEqual(p.project(value(eligibility='non_substantive')),'not_supported')
        self.assertEqual(p.project(value(eligibility='context_dependent')),'uncertain')

    def test_extra_verdict_or_bad_enum_rejected(self):
        for patch in [{'support':'supported'},{'scope':'similar'},{'assertion':[]}]:
            self.assertTrue(p.validate_audit(value(**patch),'Source.'))

    def test_semantic_rejection_gets_no_format_retry(self):
        seen=[]
        def calls(*args):seen.append(args);return {'errors':[],'output':value(modality='changed')}
        d=p.check(source('a','Source.'),'Claim.',calls,score)
        self.assertEqual(len(seen),1);self.assertEqual(d['state'],'not_supported')

    def test_full_source_and_saved_evidence_are_both_scored(self):
        seen=[];original='Source. Unrelated.'
        def scoring(a,b):seen.append(a);return score(a,b)
        d=p.check(source('a',original),'Claim.',lambda *a:{'errors':[],'output':value()},scoring)
        self.assertEqual(seen,[original,'Source. ']);self.assertEqual(d['state'],'support')

    def test_saved_evidence_cannot_borrow_support_from_full_source(self):
        def scoring(a,b):
            if a=='Source. ':return {'errors':[],'relation':'not_established','scores':{'entailment':.05,'neutral':.9,'contradiction':.05}}
            return score(a,b)
        d=p.check(source('a','Source. Unrelated.'),'Claim.',lambda *a:{'errors':[],'output':value()},scoring)
        self.assertEqual(d['state'],'not_supported')

    def test_audit_sees_only_one_original_and_target(self):
        def calls(system,data,schema):
            self.assertEqual(set(data),{'SOURCE','TARGET'})
            self.assertEqual(''.join(x['text'] for x in data['SOURCE']),'Original.')
            return {'errors':[],'output':value()}
        p.check(source('a','Original.'),'Claim.',calls,score)

    def test_empty_alignment_does_not_modify_registry_or_generate_core(self):
        sources=[source('a','Left.'),source('b','Right.')];registry={'sources':sources}
        pair={'source_ids':['a','b'],'pair_id':'R'+digest([[s['source_id'],s['source_digest']] for s in sources])[:20]}
        before=deepcopy(registry);seen=[]
        def calls(system,data,schema):seen.append(system);return {'errors':[],'output':{'left':[],'right':[]}}
        result=p.discover(registry,pair,calls,score)
        self.assertEqual(result['status'],'no_alignment');self.assertEqual(seen,[p.ALIGN]);self.assertEqual(registry,before)

    def test_alignment_prefixes_prevent_cross_source_ids(self):
        self.assertTrue(p.validate_alignment({'left':[{'first':'R000','last':'R000'}],'right':[]},'Left.','Right.'))


if __name__=='__main__':unittest.main()
