"""Explicit credit increase preserves historical money and old run ceilings."""
from pathlib import Path
from contextlib import closing
import sqlite3
import tempfile
from unittest import TestCase

from commentscope.providers.openrouter_budget import SpendLedger
from commentscope.providers.budget import BudgetExhausted


class BudgetRevisionTests(TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'money.sqlite'
        self.ledger=SpendLedger(self.path,'synthetic-team',maximum_usd='50',opening_charge_usd='1')
        first=self.ledger.reserve('a'*64,'b'*64,'0.2',run_limit_usd='5',key_remaining_usd='140')
        self.ledger.finish(first,'0.2')
        second=self.ledger.reserve('a'*64,'c'*64,'0.3',run_limit_usd='5',key_remaining_usd='140')
        self.ledger.finish(second,None)
        self.ledger.resolve_conservatively(second,plan_sha256='a'*64,request_sha256='c'*64,evidence_sha256='d'*64,reason='Authored terminal loss; retain entire reservation.')

    def history(self):
        with closing(sqlite3.connect(self.path)) as db:
            return {t:db.execute('SELECT * FROM '+t+' ORDER BY 1').fetchall() for t in ('plans','calls','resolutions')}

    def increase(self,**kwargs):
        return self.ledger.increase_limit(maximum_usd=kwargs.pop('maximum_usd','150'),
            observed_key_limit_usd=kwargs.pop('observed_key_limit_usd','150'),
            authorization_sha256=kwargs.pop('authorization_sha256','e'*64),
            user_request=kwargs.pop('user_request','Use the extended team credit cumulatively; preserve prior spending.'),**kwargs)

    def test_explicit_revision_preserves_every_call_resolution_opening_and_old_run_limit(self):
        before=self.history();record=self.increase()
        self.assertEqual(self.history(),before)
        self.assertEqual(record['old_maximum_usd'],'50');self.assertEqual(record['new_maximum_usd'],'150')
        summary=self.ledger.summary();self.assertEqual(summary['charged_usd'],'1.5')
        self.assertEqual(summary['conservative_usd'],'0.3');self.assertEqual(summary['remaining_usd'],'148.5')
        self.assertEqual(self.ledger.summary(plan_sha256='a'*64)['maximum_usd'],'5')
        with self.assertRaises(ValueError):self.ledger.reserve('a'*64,'f'*64,'0.1',run_limit_usd='150',key_remaining_usd='140')
        with self.assertRaises(BudgetExhausted):self.ledger.reserve('f'*64,'f'*64,'149',run_limit_usd='150',key_remaining_usd='150')

    def test_resume_cannot_increase_and_revision_cannot_exceed_observed_credit_or_omit_evidence(self):
        with self.assertRaises(ValueError):SpendLedger(self.path,'synthetic-team',maximum_usd='150',opening_charge_usd='1')
        for values in (dict(maximum_usd='151'),dict(user_request=''),dict(authorization_sha256='invalid'),dict(maximum_usd='49')):
            with self.subTest(values=values),self.assertRaises(ValueError):self.increase(**values)
        self.assertEqual(self.ledger.summary()['maximum_usd'],'50')

    def test_active_or_unknown_money_blocks_revision_without_refunding_it(self):
        cid=self.ledger.reserve('a'*64,'f'*64,'0.4',run_limit_usd='5',key_remaining_usd='140')
        with self.assertRaises(BudgetExhausted):self.increase()
        self.ledger.finish(cid,None)
        with self.assertRaises(BudgetExhausted):self.increase()
        self.assertEqual(self.ledger.summary()['charged_usd'],'1.9')
        self.assertEqual(self.ledger.summary()['maximum_usd'],'50')

    def test_revision_replay_is_idempotent_and_stale_instances_cannot_report_or_reserve(self):
        stale=SpendLedger(self.path,'synthetic-team',maximum_usd='50',opening_charge_usd='1')
        first=self.increase();second=self.increase();self.assertEqual(first,second)
        with closing(sqlite3.connect(self.path)) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM limit_revisions').fetchone()[0],1)
        with self.assertRaises(ValueError):stale.summary()
        with self.assertRaises(ValueError):stale.reserve('f'*64,'f'*64,'0.1',run_limit_usd='5',key_remaining_usd='140')
        current=SpendLedger(self.path,'synthetic-team',maximum_usd='150',opening_charge_usd='1')
        self.assertEqual(current.summary()['charged_usd'],'1.5')
