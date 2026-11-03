"""Bounded surface witnesses; reject recognized changes, never approve.

Not a general parser, not a multilingual semantic guarantee. Unrecognized or mixed
tense produces no mechanical verdict and still needs NLI and the relational audit.
"""
import re
from commentscope.factory.shared_core import explicit_conditions

VERSION = 'qualification-witnesses-0.1'
TIME_PATTERNS = {
    'future': r"\bwill\b|\bwon['’]t\b|\b\w+['’]ll\b",
    'present_progressive': r'\b(?:am|is|are)\s+(?:not\s+)?(?:currently\s+)?(?:being\s+)?\w+ing\b',
    'past': r'\b(?:last (?:year|month|week)|yesterday)\b',
}
APPROXIMATION_VERSION = 'approximation-witnesses-20261103-v1'
APPROXIMATION = re.compile(
    r'\b(?:essentially|basically|roughly|approximately|nearly|almost|similar|analogous|analogue)\b'
    r'|거의|대략|대체로|유사(?:한|하다|하게)?|비슷(?:한|하다|하게)?', re.I)


def approximation_loss(selected_original, target):
    """A limited lexical veto; retained words do not establish aligned meaning."""
    def operators(text):
        return [{'start': m.start(), 'end': m.end(), 'text': m.group()}
                for m in APPROXIMATION.finditer(text)]
    source, candidate = operators(selected_original), operators(target)
    return {'version': APPROXIMATION_VERSION, 'source_operators': source,
            'candidate_operators': candidate, 'blocked': bool(source) and not candidate,
            'semantic_approval': False}


def witnesses(text):
    return {kind: [{'start': m.start(), 'end': m.end(), 'text': m.group()}
                   for m in re.finditer(pattern, text, re.I)] for kind, pattern in TIME_PATTERNS.items()}


def compare(original, target):
    left, right = witnesses(original), witnesses(target)
    a, b = {k for k, v in left.items() if v}, {k for k, v in right.items() if v}
    reasons = []
    # Mixed events or reported/quoted text cannot safely be aligned by surface tense.
    complex_text = any(re.search(r'\b(?:said|says|told|quoted|would|should|ought|might|could)\b|["“”]', text, re.I)
                       for text in (original, target))
    if not complex_text and len(a) == len(b) == 1 and a != b:
        reasons.append('explicit_time_change')
    conditions = {'source': explicit_conditions(original), 'target': explicit_conditions(target)}
    # Require the shape only. Antecedent paraphrases are left to source-grounded
    # semantic comparison, not NLI of a dangling/subclausal conditional fragment.
    x, y = conditions['source'], conditions['target']
    if [c['operator'] for c in x] != [c['operator'] for c in y]:
        reasons.append('explicit_condition_change')
    return {'version': VERSION, 'time_witnesses': {'source': left, 'target': right},
            'conditions': conditions, 'time_alignment_abstained': complex_text or len(a) != 1 or len(b) != 1,
            'blocked_reasons': reasons, 'allowed': not reasons}
