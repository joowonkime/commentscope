"""Settle one proven, terminal product HTTP failure at its full reservation offline."""
import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT)]

from commentscope.factory.claim_clusters import read_json, sha
from commentscope.providers.execution_lock import experiment_lock
from commentscope.providers.openrouter_budget import SpendLedger, dollars
from experiments.openrouter_factory_probe import private
from tools import launch_mvp, serve_mvp
from tools.wide_mining_recovery import database, terminal_evidence


def review(state):
    state = Path(state).resolve()
    private(state)
    with experiment_lock(state):
        directory = state / 'server'
        plan = serve_mvp.validate(directory)
        policy = read_json(state / 'authorization.json')['policy']
        if ('factory_trial' in plan or plan['spend_policy'] != policy
                or Path(policy['ledger']).resolve() != state / 'spend.sqlite'):
            raise ValueError('The original standalone product server and its ledger are required.')
        ledger = SpendLedger(policy['ledger'], policy['account_id'], maximum_usd=policy['maximum_usd'],
                             opening_charge_usd=policy['opening_charge_usd'])
        with database(ledger.path) as db:
            pending = db.execute("SELECT id,plan_sha,request_sha,state FROM calls "
                                 "WHERE state IN ('reserved','unknown','over_ceiling')").fetchall()
        if not pending:
            return 'No uncertain charge in this ledger.'
        if len(pending) != 1 or pending[0][1] != plan['spend_scope_sha256'] or pending[0][3] != 'unknown':
            raise ValueError('An active, foreign or over-ceiling entry needs individual review.')
        call_id, scope, request, _ = pending[0]
        matches = [p for p in (directory / 'calls').glob('*-product-*.request.json')
                   if read_json(p).get('request_sha256') == request]
        if len(matches) != 1:
            raise ValueError('One completed product generation request is required.')
        proof = terminal_evidence(directory, plan, matches[0])
        if proof['ledger_call_id'] != call_id:
            raise ValueError('The failure and money entry differ.')
        path = directory / 'host-review' / f'http-error-{call_id}.json'
        launch_mvp.write_matching(path, proof)
        ledger.resolve_conservatively(call_id, plan_sha256=scope, request_sha256=request,
                                      evidence_sha256=sha(path), reason='Host reviewed the terminal provider HTTP '
                                      'failure and completed error checkpoint. Retain the entire reservation.')
        return (f"Reviewed HTTP {proof['http_status']}. Retained USD {dollars(proof['retained_units'])}. "
                'Restart the same server to continue with another question.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, default=Path('runs/qa-server'))
    args = parser.parse_args()
    os.chdir(ROOT)
    try:
        print(review(args.state))
    except (OSError, ValueError, RuntimeError) as error:
        sys.exit(str(error))
