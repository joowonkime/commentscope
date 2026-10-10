"""Generation grammar revision; emitted objects still use claims-0.2."""
from copy import deepcopy

from commentscope.contracts.claims import SCHEMA, ELIGIBILITY

VERSION = 'claim-generation-0.3'


def constrained_schema():
    substantive = deepcopy(SCHEMA)
    substantive['properties']['eligibility']['enum'] = ['argument_or_experience']
    substantive['properties']['claims']['minItems'] = 1
    other = deepcopy(SCHEMA)
    other['properties']['eligibility']['enum'] = ELIGIBILITY[1:]
    other['properties']['claims']['maxItems'] = 0
    return {'anyOf': [substantive, other]}
