from copy import deepcopy
from dataclasses import replace
import unittest

from commentscope.factory import raw_support as s, raw_candidates as r, grounded_core
from commentscope.factory.automatic_contract import digest
from commentscope.ingestion import load_snapshot
from experiments.raw_support_probe import assemble, may_expand, metrics, source


def score(*args):
    return {'errors': [], 'relation': 'supports', 'scores': {'entailment': .9, 'neutral': .05, 'contradiction': .05}}


def calls(system, data, schema):
    if system == s.PROPOSE: output = {'core': 'Electric buses reduce local air pollution.'}
    else: output = {'support': 'supported', 'evidence_quote': data['SOURCE'],
                   **{k: 'preserved' for k in grounded_core.FIELDS}}
    return {'errors': [], 'output': output}


class RawSupportTests(unittest.TestCase):
    def registry(self, texts):
        snap = load_snapshot('tests/fixtures/synthetic-snapshot.json').snapshot
        return r.registry(replace(snap, comments=tuple(replace(snap.comments[0], comment_id=str(i),
                           parent_id=None, text_original=t) for i,t in enumerate(texts))))

    def test_pair_has_one_proposal_and_two_independent_source_audits(self):
        value = self.registry(['Electric buses reduce local air pollution.', 'Electric buses reduce air pollution and noise.'])
        pair = r.build(value, [[1],[1]])['queue']['pairs'][0]; seen = []
        def wrapped(system, data, schema):
            seen.append((system, data)); return calls(system, data, schema)
        result = s.discover(value, pair, wrapped, score)
        self.assertIsNotNone(result['selected_core'])
        self.assertEqual(sum(system == s.PROPOSE for system,_ in seen), 1)
        for system, data in seen:
            if system != s.PROPOSE: self.assertEqual(set(data), {'SOURCE', 'TARGET'})
        self.assertEqual(len(result['checks']), 2)

    def test_nli_rejection_cannot_be_rescued_by_proposal_or_peer(self):
        def no_calls(*args): self.fail('Audit must not rescue failed NLI')
        def reject(*args): return {'errors': [], 'relation': 'not_established',
                                  'scores': {'entailment': .05,'neutral': .9,'contradiction': .05}}
        self.assertEqual(s.check(source('a','Original.'),'Claim.',no_calls,reject)['state'],'not_supported')

    def test_deferred_and_error_are_not_negative(self):
        for response, state in [({'errors':['input_budget'],'deferred_reason':'token_budget'},'unchecked'),
                                ({'errors':['RuntimeError']},'error')]:
            result=s.check(source('a','Original.'),'Claim.',calls,lambda *args:response)
            self.assertEqual(result['state'],state)

    def test_uncertain_is_separate(self):
        result=s.check(source('a','Original.'),'Claim.',calls,lambda *args:{'errors':[], 'relation':'unclear',
                       'scores':{'entailment':.4,'neutral':.3,'contradiction':.3}})
        self.assertEqual(result['state'],'uncertain')

    def test_changed_source_or_core_is_rejected(self):
        original=source('a','Original.'); original['text']='Changed.'
        with self.assertRaises(ValueError):s.check(original,'Claim.',calls,score)
        for core in ['', ' ', 'x'*250]:
            with self.assertRaises(ValueError):s.check(source('a','Original.'),core,calls,score)

    def test_foreign_quote_is_error_not_support(self):
        def bad(system,data,schema):
            return {'errors':[], 'output':{'support':'supported','evidence_quote':'invented',
                                         **{k:'preserved' for k in grounded_core.FIELDS}}}
        self.assertEqual(s.check(source('a','Original.'),'Claim.',bad,score)['state'],'error')

    def test_quote_guard_blocks_condition_loss(self):
        result=s.check(source('a','If rents rise, housing support should increase.'),
                       'Housing support should increase.',calls,score)
        self.assertEqual(result['state'],'not_supported')
        self.assertEqual(result['reason'],'qualification_guard')

    def test_unrelated_condition_not_imposed_on_separate_assertion(self):
        text='Electric buses reduce air pollution. If fares rise, subsidies should increase.'
        seen=[]
        def quote(system,data,schema):
            seen.append(data['SOURCE'])
            return {'errors':[],'output':{'support':'supported','evidence_quote':'Electric buses reduce air pollution.',
                                        **{k:'preserved' for k in grounded_core.FIELDS}}}
        row=s.check(source('a',text),'Electric buses reduce air pollution.',quote,score)
        self.assertEqual(row['state'],'support'); self.assertEqual(seen,[text])

    def test_ledger_uses_canonical_denominator_and_never_votes_for_unchecked(self):
        value=self.registry(['Electric buses reduce air pollution.','Electric buses reduce air pollution.','Other.'])
        core='Electric buses reduce air pollution.'
        decision=s.check(value['sources'][0],core,calls,score)
        ledger=s.ledger(value,core,[decision])
        self.assertEqual(ledger['canonical_denominator'],2)
        self.assertEqual(ledger['support_count'],1)
        self.assertEqual(ledger['counts']['unchecked'],1)
        self.assertEqual(sum(ledger['counts'].values()),2)
        self.assertEqual(ledger['agents'],[])
        self.assertFalse(ledger['quality_gate_passed'])
        with self.assertRaises(ValueError):s.ledger(value,core,[decision,decision])
        with self.assertRaises(ValueError):s.ledger(value,'Another claim.',[decision])

    def test_fake_vote_or_mutated_quote_is_rejected(self):
        value=self.registry(['Original.']); core='Claim.'
        decision=s.check(value['sources'][0],core,calls,score)
        for key,replacement in [('nli',None),('evidence',None),('qualification_guard',None),('source_id','alias')]:
            bad=deepcopy(decision);bad[key]=replacement
            with self.assertRaises(ValueError):s.ledger(value,core,[bad])

    def test_no_semantic_retry_or_fallback_when_no_proposal(self):
        value=self.registry(['A.','B.']); pair=r.build(value,[[1],[1]])['queue']['pairs'][0]; seen=[]
        def empty(*args):seen.append(args);return {'errors':[],'output':{'core':''}}
        result=s.discover(value,pair,empty,score)
        self.assertEqual(len(seen),1); self.assertEqual(result['status'],'no_proposal')

    def test_expansion_gate_requires_zero_false_acceptance_and_errors(self):
        self.assertTrue(may_expand({'x':{'false_accepts':[],'error_or_deferred':[]}}))
        for key in ['false_accepts','error_or_deferred']:
            row={'false_accepts':[],'error_or_deferred':[]};row[key]=['a']
            self.assertFalse(may_expand({'x':row}))

    def test_error_negative_not_counted_as_correct_rejection(self):
        result=metrics([{'id':'a','expected':False}],lambda r:False,lambda r:True)
        self.assertEqual(result['negative_blocked'],0)

    def test_same_core_duplicate_pairs_have_one_vote_per_source(self):
        value=self.registry(['A.','B.']);pair=r.build(value,[[1],[1]])['queue']['pairs'][0]
        trace=s.discover(value,pair,calls,score)
        groups=assemble(value,[{'trace':trace},{'trace':deepcopy(trace)}],calls,score,False)
        self.assertEqual(len(groups),1);self.assertEqual(groups[0]['support_count'],2)

    def test_empty_source_or_large_source_is_preserved_unchecked(self):
        for text in ['', 'a'*4001]:
            row=s.check(source('a',text),'Claim.',lambda *a:self.fail('No LLM'),lambda *a:self.fail('No NLI'))
            self.assertEqual(row['state'],'unchecked')


if __name__=='__main__':unittest.main()
