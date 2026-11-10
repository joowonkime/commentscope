"""One pinned typed transport; callers retain financial/time/dispatch guards."""
from copy import deepcopy
from pathlib import Path
from commentscope.factory.claim_clusters import sha

from commentscope.providers import openrouter_decisions as decisions
from commentscope.providers.runtime_runner import RuntimeRunner
from commentscope.providers.checkpoint_calls import CheckpointRunner


def build(directory,plan,inference,money,key_metadata):
    directory=Path(directory)
    if plan.get('membership_deployment')!=decisions.DEPLOYMENT:
        raise ValueError('Pinned typed membership deployment required')
    client=decisions.Client(plan['membership_deployment'])
    paid=decisions.DecisionsBudget(inference,money,
        plan_sha256=sha(directory/'plan.json'),
        deployment=plan['membership_deployment'],spend_scope_sha256=plan['spend_scope_sha256'],
        parent_limit_usd=plan['maximum_cost_usd'],opening_scope_charge_usd=plan['opening_scope_charge_usd'],
        additional_limit_usd=plan['subcap_usd'],paid_provider=client.generate,key_metadata=key_metadata)
    # RuntimeRunner supports its existing decisions key. The alias is an
    # explicit derivation of the frozen membership deployment, never a new plan.
    alias=deepcopy(plan);alias['decisions_deployment']=deepcopy(plan['membership_deployment'])
    alias['limits']=deepcopy(plan['limits']);alias['limits']['call_seconds']=decisions.DEPLOYMENT['call_seconds']
    base=RuntimeRunner(directory,alias,paid,client,deployment_key='decisions_deployment')
    return client,CheckpointRunner(base,{})
