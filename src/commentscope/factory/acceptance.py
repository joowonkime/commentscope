"""Explicit acceptance selection; frozen r4 references retain their identity.

Acceptance is evaluation metadata, never semantic labels for the runtime.
Only the approved r5 profile is accepted; a caller cannot tune its thresholds.
Missing profiles are supported solely for historical r4 artifacts.
"""
from copy import deepcopy

from commentscope.factory.automatic_contract import digest

R4 = 'factory-goal-20261014-r4'
R5 = 'factory-goal-20261017-r5'
R5_DIGEST = 'a4fafae58e462ee4ab3fad41f6bf03fa7f10a08218fb2106398df4f0feea81b2'


def validate(profile, expected_sha256):
    if (not isinstance(profile, dict) or digest(profile) != R5_DIGEST
            or expected_sha256 != R5_DIGEST):
        raise ValueError('Exact approved, pre-run pinned r5 acceptance profile required')
    return profile


def from_plan(plan):
    profile = plan.get('acceptance_profile')
    if profile is None:
        if plan.get('goal_revision', R4) != R4 or 'acceptance_profile_sha256' in plan:
            raise ValueError('Goal requires an explicit acceptance profile')
        return None
    validate(profile, plan.get('acceptance_profile_sha256'))
    if plan.get('goal_revision') != profile['goal_revision']:
        raise ValueError('Plan goal and acceptance revision differ')
    return deepcopy(profile)


def ratio(profile=None):
    return (4, 5) if profile is None else (3, 5)


def minimum(profile=None):
    return 604 if profile is None else 453


def check_scope(profile, gate, source_count, meaningful_count):
    if profile is None:
        return
    validate(profile, digest(profile))
    spec = profile['gates'][gate]
    if (source_count != spec.get('sources', spec.get('synthetic_sources'))
            or gate != 'G1' and meaningful_count != spec['meaningful_denominator']):
        raise ValueError('Fixed r5 source scope or meaningful denominator changed')
