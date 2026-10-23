"""Keep final-answer capacity separate from a bounded reasoning allowance."""
from copy import deepcopy


def allocate(request, runtime):
    if not isinstance(request, dict) or set(request) != {'system', 'data', 'schema', 'max_tokens'}:
        raise ValueError('Complete logical request required')
    answer_tokens = request['max_tokens']
    reasoning = runtime.get('reasoning')
    reasoning_tokens = runtime.get('reasoning_budget')
    context = runtime.get('context')
    if (type(answer_tokens) is not int or answer_tokens < 1
            or reasoning not in ('on', 'off') or type(reasoning_tokens) is not int
            or not 0 <= reasoning_tokens <= 2048 or type(context) is not int or context < 1):
        raise ValueError('Explicit finite answer/reasoning/context limits required')
    if reasoning == 'off' and reasoning_tokens != 0:
        raise ValueError('Disabled reasoning must reserve zero reasoning tokens')
    total = answer_tokens + reasoning_tokens
    if total >= context:
        raise ValueError('Generation allocation leaves no input context')
    result = deepcopy(request)
    result['max_tokens'] = total
    return result
