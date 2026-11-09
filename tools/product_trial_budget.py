"""Link product calls to an existing Factory trial without a new money scope."""
from decimal import Decimal
from pathlib import Path

from commentscope.factory.claim_clusters import read_json, sha
from commentscope.providers.budget import BudgetExhausted
from commentscope.providers.openrouter_budget import units
from commentscope.storage import write_json_exclusive as write
from experiments.remote_factory_pipeline import SubcapLedger
from tools import shared_factory_trial as shared

VERSION='product-factory-trial-budget-20261110-v1'


def bind(factory_run,cycle_file,trial_file,money):
    factory_run=Path(factory_run);cycle_file=Path(cycle_file);trial_file=Path(trial_file)
    factory=shared.validate(factory_run);cycle=read_json(cycle_file)
    done=read_json(factory_run/'completed.json')
    if (done.get('execution_complete') is not True or done['plan_sha256']!=sha(factory_run/'plan.json')
            or done['output_sha256']!=sha(factory_run/'artifacts/output.json')
            or done['runtime_sha256']!=sha(factory_run/'artifacts/runtime.json')
            or done['compiled_agents']<2 or done['binding_errors'] or done['capacity_holds']
            or factory['trial']['sha256']!=sha(trial_file)
            or factory['trial']['authorization']!=read_json(trial_file)
            or factory['deployment']!=cycle['selected_deployment']
            or factory['spend_policy']!=read_json(cycle['shared_policy_file'])):
        raise ValueError('Completed matching Factory analysis and original product authorization required')
    shared.guard(factory)
    anchor=cycle_file.with_name(cycle_file.stem+'.factory-trial.json')
    shared_money=money.summary()
    if shared_money['reserved_calls'] or shared_money['uncertain_calls']:
        raise BudgetExhausted('Settle active Factory and product calls before linking')
    legacy=money.summary(plan_sha256=sha(cycle_file))
    if not anchor.exists():
        remaining=Decimal(cycle['maximum_additional_usd'])-Decimal(legacy['charged_usd'])
        if remaining<=0:raise BudgetExhausted('Existing product cycle has no remaining money')
        write(anchor,{'version':VERSION,'cycle_sha256':sha(cycle_file),
            'trial_sha256':sha(trial_file),'spend_scope_sha256':factory['spend_scope_sha256'],
            'opening_scope_charge_usd':money.summary(plan_sha256=factory['spend_scope_sha256'])['charged_usd'],
            'legacy_product_charge_usd':legacy['charged_usd'],'subcap_usd':str(remaining)})
    binding={'file':str(anchor.resolve()),'sha256':sha(anchor),'anchor':read_json(anchor),
             'factory_plan_file':str((factory_run/'plan.json').resolve()),
             'factory_plan_sha256':sha(factory_run/'plan.json')}
    check(binding,factory,cycle,cycle_file,money)
    return binding


def check(binding,factory,cycle,cycle_file,money=None):
    a=binding['anchor']
    if (sha(binding['file'])!=binding['sha256'] or read_json(binding['file'])!=a
            or sha(binding['factory_plan_file'])!=binding['factory_plan_sha256']
            or a['version']!=VERSION or a['cycle_sha256']!=sha(cycle_file)
            or a['trial_sha256']!=factory['trial']['sha256']
            or a['spend_scope_sha256']!=factory['spend_scope_sha256']
            or factory['deployment']!=cycle['selected_deployment']
            or factory['spend_policy']!=read_json(cycle['shared_policy_file'])
            or units(a['subcap_usd'])+units(a['legacy_product_charge_usd'])!=units(cycle['maximum_additional_usd'])
            or not 0<units(a['subcap_usd'])<=units(cycle['maximum_additional_usd'])
            or units(a['opening_scope_charge_usd'])<units(factory['opening_scope_charge_usd'])):
        raise ValueError('Frozen product/trial money binding changed')
    shared.guard(factory,allow_expired=True)
    if money is not None and money.summary(plan_sha256=sha(cycle_file))['charged_usd']!=a['legacy_product_charge_usd']:
        raise BudgetExhausted('Original independent product cycle changed; reconcile before generation')
    if money is not None and units(money.summary(plan_sha256=a['spend_scope_sha256'])['charged_usd'])<units(a['opening_scope_charge_usd']):
        raise BudgetExhausted('Original scope history cannot be reset')


def ledger(money,binding,factory):
    return SubcapLedger(SubcapLedger(money,factory),binding['anchor'])


def remaining(money,binding,factory):
    charged=Decimal(money.summary(plan_sha256=factory['spend_scope_sha256'])['charged_usd'])
    return min(Decimal(p['opening_scope_charge_usd'])+Decimal(p['subcap_usd'])-charged
               for p in (factory,binding['anchor']))
