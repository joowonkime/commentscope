"""Exact potential attribution cues, never a generated speaker or endorsement."""
import re
from commentscope.factory import explicit_discourse as ed, literal_discovery as ld

VERSION='source-attribution-addresses-20261017-v1'
REPORT=re.compile(r'\b(?:say|says|said|claim|claims|claimed|argue|argues|argued|'
                  r'believe|believes|believed|according\s+to|reportedly|allegedly|'
                  r'rumou?r\s+has\s+it|told|wrote|writes)\b|'
                  r'말(?:했|하|한)|주장(?:했|하|한)|라고\s*(?:했|하)|에\s*따르면',re.I)


def cues(graph,node):
    ed.validate(graph)
    if node not in ld.roots(graph):raise ValueError('Original root position required')
    text=graph['source']['text'];span=node['span'];found=[]
    for q in graph['quotation_ranges']:
        a=max(q['start'],span['start']);b=min(q['end'],span['end'])
        if a<b:found.append({'kind':'quotation','span':ed.span(text,a,b)})
    for m in REPORT.finditer(span['text']):
        a=span['start']+m.start();b=span['start']+m.end()
        if not any(q['start']<=a and b<=q['end'] for q in graph['quotation_ranges']):
            found.append({'kind':'possible_reporting_expression','span':ed.span(text,a,b)})
    return [{'id':f'A{i}',**row} for i,row in enumerate(sorted(found,key=lambda r:(r['span']['start'],r['span']['end'],r['kind'])),1)]
