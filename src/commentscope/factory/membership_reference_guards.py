"""Bounded absence/ownership vetoes, never positive semantic approval.

A timecode can introduce a cited argument without establishing the author's
stance. A generic topic title cannot supply an absent compared payment amount.
These rules retain the original text and do not decide irony or factual truth.
"""
import re

from commentscope.factory import explicit_discourse as discourse

TIMECODE = re.compile(r'(?m)^[ \t]*(?:\d{1,2}:)?\d{1,2}:\d{2}(?!\d)[ \t]+')
OWN_STANCE = re.compile(r"\bI\s+(?:personally\s+)?(?:(?:do\s+not|don't)\s+)?(?:agree|disagree|believe|think|support|oppose|prefer|recommend)\b", re.I)
COMPARATOR = re.compile(r'\b(?:more|less|higher|lower)\s+than\s+(?:this|that)\b', re.I)
PAYMENT = re.compile(r'\b(?:pay|pays|paid|paying|cost|costs|costing|earn|earns|earned|earning|spend|spends|spent|spending|charge|charges|charged|charging)\b', re.I)
QUANTITY = re.compile(r'[$€£¥₩]|\b\d+(?:[.,]\d+)*\b|\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|twenty|thirty|forty|fifty|hundred|thousand|million|billion|rent|salary|wage|wages|budget|allowance)\b', re.I)
VOCATIVE = re.compile(r'^\s*@?[\w-]+(?:[ \t]+[\w-]+){0,2}\s*,\s*(?=you(?:r)?\b)', re.I)


def assertion_spans(candidate, origin):
    context = candidate.get('meaning_context')
    if context is not None:
        return [context['assertion']]
    pattern = r'\s+'.join(re.escape(w) for w in candidate['text'].split())
    return [{'start': m.start(), 'end': m.end(), 'text': m.group()}
            for m in re.finditer(pattern, origin['text'])] if pattern else []


def citation_guards(source, spans):
    text = source['text']; citations = list(TIMECODE.finditer(text))
    if not citations: return []
    # An unaligned generated candidate cannot establish which cited words it
    # represents. This is a hold, not a substitution of the complete source.
    if not spans: return ['timestamp_origin_assertion_unaligned']
    quotes = discourse.parse(source)['quotation_ranges']
    for index, cue in enumerate(citations):
        blank = re.search(r'\n\s*\n', text[cue.end():])
        end = cue.end()+blank.start() if blank else len(text)
        if index+1 < len(citations): end = min(end, citations[index+1].start())
        for span in spans:
            if span['end'] <= cue.start() or span['start'] >= end: continue
            # Only a stance in this assertion's own sentence can discharge
            # this bounded hold; another sentence/paragraph cannot lend it.
            left = max(cue.start(), max((text.rfind(c, cue.start(), span['start'])+1
                                       for c in '.!?\n'), default=cue.start()))
            markers = OWN_STANCE.finditer(text, left, min(span['end'], end))
            if not any(not any(q['start'] <= m.start() < q['end'] for q in quotes) for m in markers):
                return ['timestamp_citation_without_local_own_stance']
    return []


def quantity_guards(source, spans):
    text = source['text']
    for span in spans:
        selected = text[span['start']:span['end']]
        if not COMPARATOR.search(selected) or not PAYMENT.search(selected): continue
        # This narrow absence proof only covers a comparison introduced with
        # no earlier source context and no parent. Context, if present, still
        # needs independent semantic verification; it never approves a vote.
        if text[:span['start']].strip() or source['parent'] is not None: continue
        title = source.get('video_context', {}).get('title', '')
        if not QUANTITY.search(text) and not QUANTITY.search(title):
            return ['payment_comparator_without_supplied_quantity']
    return []


def source_guards(source, spans):
    return citation_guards(source, spans) + quantity_guards(source, spans)


def candidate_guards(candidate, origin):
    return source_guards(origin, assertion_spans(candidate, origin))


def focus_tokens(tokens, text):
    match = VOCATIVE.match(text)
    return [t for t in tokens if not match or t['start'] >= match.end()]
