"""Explicit product admission; legacy Factory evidence keeps its own policy."""
from copy import deepcopy

VERSION = 'comment-seeded-perspective-20261113-v1'
POLICY = {'version': VERSION, 'minimum_core_sources': 1,
          'argument_expansion': True, 'formal_factory_eligible': False}


def minimum(policy=None):
    if policy is None:
        return 3
    if not isinstance(policy, dict) or policy != POLICY:
        raise ValueError('Unknown perspective admission policy')
    return 1


def seeded(bundle):
    policy = bundle.get('admission_policy')
    minimum(policy)
    return policy is not None


def references(bundle):
    """Bind prepared passages; this does not assert that any new claim is true."""
    from commentscope.factory import fact_checks
    if not seeded(bundle):
        if 'reference_selections' in bundle:
            raise ValueError('Prepared runtime references require the seeded policy')
        return []
    probe = {'id': 'reference-inventory', 'text': 'Prepared reference inventory',
             'kind': 'fact', 'scope': {'entity': '', 'time': '', 'conditions': ''},
             'requires': []}
    packet = fact_checks.packet(probe, bundle['documents'],
                               bundle.get('reference_selections', []), bundle['expires_at'])
    return deepcopy(packet['evidence'])
