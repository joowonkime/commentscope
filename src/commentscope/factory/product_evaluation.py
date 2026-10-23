"""Separate diagnostic execution from qualification and product acceptance.

No metric is erased or re-labelled. This module never approves an agent; it
only records why an experimental integration run may be prepared.
"""
from copy import deepcopy

VERSION = 'mvp-product-evaluation-0.1'
PURPOSES = ('qualified_configuration', 'product_diagnostic')


def execution_state(checkpoint, purpose):
    if purpose not in PURPOSES:
        raise ValueError('Explicit known evaluation purpose required')
    qualified = bool(checkpoint.get('development_gate_passed') and checkpoint.get('all_relations_complete'))
    if purpose == 'qualified_configuration' and not qualified:
        raise ValueError('Complete source gate must pass for a qualified configuration')
    return {'version': VERSION, 'purpose': purpose,
            'relation_target_met': bool(checkpoint.get('development_gate_passed')),
            'source_configuration_qualified': qualified,
            'source_measurement': deepcopy(checkpoint),
            'mvp_acceptance': 'not_evaluated', 'paper_validation': 'not_evaluated',
            'runtime_reference_labels': False, 'qualified_agents': 0}
