"""Catch explicit weekly totals reused verbatim as daily amounts in generated reasoning."""
from decimal import Decimal
import re


ONES = 'one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen'.split()
TENS = 'twenty thirty forty fifty sixty seventy eighty ninety'.split()
WORD_VALUES = {**dict(zip(ONES, range(1, 20))), **dict(zip(TENS, range(20, 100, 10)))}
DIGITS = r'\d+(?:\.\d+)?'
NUMBER = rf"(?:{DIGITS}|(?:{'|'.join(TENS)})(?:[-\s]+(?:{'|'.join(ONES[:9])}))?|{'|'.join(reversed(ONES))})"
SPACE = r'[\s\-‐‑]*'
HOUR = r'(?:hours?|hrs?|h)'
WEEKLY = (
    re.compile(rf"(?<![\w.])({NUMBER}){SPACE}(?:weekly\s+{HOUR}|{HOUR}\s*(?:weekly|(?:(?:per|a|each)\s+|/\s*)week)|{HOUR}[-\s]+week)\b", re.I),
    re.compile(rf"(?:주당|주\s+|일주일에)\s*({DIGITS})\s*시간"),
)
DAILY = (
    re.compile(rf"(?<![\w.])(?:(?P<days>{NUMBER})\s+)?(?P<hours>{NUMBER}){SPACE}{HOUR}"
               r"(?:\s*(?:(?:per|a|each)\s+|/\s*)day\b|[-\s]+(?:(?:work)?days?|daily)\b)", re.I),
    re.compile(rf"(?:하루(?:에)?|일일|일당)\s*(?P<hours>{DIGITS})\s*시간"),
)
CONTRAST = re.compile(
    r'\b(?:not|rather than|instead of)\s*$|'
    r'\b(?:separate|different|alternative)\s+(?:scenario|case|schedule|example)\b|'
    r'(?:별도|다른)\s*(?:경우|시나리오)|(?:아닌|아니라)\s*$',
    re.I,
)
DIFFERENT_SCENARIO = re.compile(r'^\s*(?:is|are|would be)\s+(?:a\s+)?(?:different|separate|alternative)\s+(?:scenario|case|schedule|example)\b', re.I)


def amount(text):
    return (Decimal(text) if text[0].isdigit()
            else sum(WORD_VALUES[word] for word in re.split(r'[-\s]+', text.lower())))


def changes_weekly_hours(query, reasoning):
    """Leave unspecified or explicitly compared quantities to semantic verification."""
    weekly = {amount(m[1]) for pattern in WEEKLY for m in pattern.finditer(query)}
    if len(weekly) != 1:
        return False
    (total,) = weekly
    if any(amount(m['hours']) == total for pattern in DAILY for m in pattern.finditer(query)):
        return False
    for sentence in re.split(r'(?<=[.!?])\s+|[;\n]', reasoning):
        for pattern in DAILY:
            for m in pattern.finditer(sentence):
                days = m.groupdict().get('days')
                if (amount(m['hours']) == total and (days is None or amount(days) != 1)
                        and not CONTRAST.search(sentence[:m.start()])
                        and not DIFFERENT_SCENARIO.match(sentence[m.end():])):
                    return True
    return False
