"""Serve a registered evaluation with the team key as its shared AI spending limit."""
import argparse
from decimal import Decimal
from hashlib import sha256
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT)]

from commentscope.agents.web import WebError
from commentscope.factory.automatic_contract import digest
from commentscope.product.web import ProductServer
from commentscope.providers.execution_cycle import EVALUATION_CYCLE_VERSION
from commentscope.providers.execution_lock import experiment_lock
from commentscope.providers.openrouter_budget import dollars, units
from tools import product_server_app, serve_mvp


def key_credit_plan(plan, api_key):
    if plan['cycle']['version'] != EVALUATION_CYCLE_VERSION or 'factory_trial' in plan:
        raise ValueError('Team key credit requires a registered hosted evaluation.')
    account = 'product-' + sha256(api_key.encode()).hexdigest()[:16]
    policy = plan['spend_policy']
    if policy['account_id'] != account:
        raise ValueError('Use the team key bound to this evaluation.')
    # The account ledger includes the opening charge and every old and new scope.
    # A scope as large as the opening balance cannot impose a lower shared cap.
    allowance = units(policy['maximum_usd']) - units(policy['opening_charge_usd'])
    if allowance <= 0:
        raise ValueError('The evaluation account has no opening credit.')
    return {
        **plan,
        'spend_scope_sha256': digest(['assessment-team-key-credit-v1', plan['spend_scope_sha256']]),
        'money_owner_limit_usd': dollars(allowance),
    }


class TeamCreditBroker(serve_mvp.Broker):
    def __init__(self, directory, plan):
        effective = key_credit_plan(plan, os.environ['OPENROUTER_API_KEY'].strip())
        super().__init__(directory, effective)

    def status(self):
        status = super().status()
        if status == 'ready' and Decimal(self.ledger.summary()['remaining_usd']) <= 0:
            return 'budget_exhausted'
        return status

    def debate_balance(self):
        # Other team tools can spend the same key without appearing in this ledger.
        try:
            remaining = units(serve_mvp.key_metadata()['limit_remaining'])
        except (OSError, KeyError, ValueError, TypeError) as error:
            raise WebError(503, 'model_or_validation_failed') from error
        return min(super().debate_balance(), Decimal(dollars(remaining)))


def build(directory):
    return product_server_app.build(directory, validate=serve_mvp.validate,
                                    broker_factory=TeamCreditBroker,
                                    provider_preflight=serve_mvp.provider_preflight)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path, help='Existing prepared assessment directory')
    parser.add_argument('--public-origin', required=True)
    parser.add_argument('--port', type=int, default=8080)
    args = parser.parse_args()
    os.chdir(ROOT)
    directory = args.directory.resolve()
    with experiment_lock(directory):
        product, legacy, broker = build(directory)
        try:
            with ProductServer(product, legacy, args.port, public_origin=args.public_origin) as server:
                print('Assessment uses team key credit | ' + broker.status(), flush=True)
                server.serve_forever()
        finally:
            product.close()


if __name__ == '__main__':
    main()
