"""Wire the same registered analyses and state into each product server."""
import os
from pathlib import Path

from commentscope.agents.grounded_web import GroundedApp
from commentscope.factory.claim_clusters import sha
from commentscope.product.analysis import Analysis
from commentscope.product.app import ProductApp
from commentscope.providers import openrouter_decisions as decisions


def build(directory, *, validate, broker_factory, provider_preflight):
    directory = Path(directory)
    plan = validate(directory)
    if not os.environ.get('OPENROUTER_API_KEY', '').strip():
        raise ValueError('OPENROUTER_API_KEY required')
    provider_preflight(plan['deployment'])
    if 'seeded_verifier_deployment' in plan:
        decisions.preflight(plan['seeded_verifier_deployment'])

    catalog = []
    for record in [plan['analysis'], *plan.get('additional_analyses', [])]:
        analysis = Analysis(record['bundle'], record['provenance'], record.get('presentation'))
        if analysis.id != record['analysis_id'] or analysis.revision != record['bundle_revision']:
            raise ValueError('Registered product analysis changed')
        catalog.append(analysis)
    if len(catalog) != len({item.id for item in catalog}):
        raise ValueError('Duplicate registered analysis')

    broker = broker_factory(directory, plan)
    debate_enabled = 'debate_protocol' in plan

    def revalidate():
        return validate(directory)

    product = ProductApp(
        directory / 'app.sqlite', catalog, broker.model,
        session_ttl_seconds=plan['session_ttl_seconds'], room_maximum_usd=plan['room_maximum_usd'],
        active_session_limit=plan.get('active_session_limit', 8),
        reservation=broker.reservation, revalidate=revalidate, generation_status=broker.status,
        decision=broker.verify if broker.typed_client is not None else None,
        decision_reservation=broker.decision_reservation if broker.typed_client is not None else None,
        debate_execution_binding=sha(directory / 'plan.json') if debate_enabled else None,
        debate_balance=broker.debate_balance if debate_enabled else None,
    )

    class Legacy(GroundedApp):
        def public(self, item):
            value = super().public(item)
            value['remote_status'] = broker.status()
            if value['remote_status'] != 'ready':
                value['can_ask'] = False
            return value

    legacy = Legacy(catalog[0].bundle, directory / 'legacy-sessions',
                    provider=broker.legacy_provider, revalidate=revalidate)
    return product, legacy, broker
