"""Explicit, bounded product exercise; never imported or run by CI."""
import argparse
import json
from pathlib import Path
import secrets
import time
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
import uuid


def exercise(origin, directory):
    if urlsplit(origin).hostname not in ('127.0.0.1', 'localhost'):
        raise ValueError('Local preview required')
    directory.mkdir(parents=True, exist_ok=False)
    token=secrets.token_urlsafe(32)
    transcript=[]
    def request(path, method='GET', body=None):
        data=None if body is None else json.dumps(body,ensure_ascii=False).encode()
        headers={'X-Session-Token':token,'Origin':origin}
        if data is not None:headers['Content-Type']='application/json'
        req=Request(origin+'/api/v1'+path,data=data,headers=headers,method=method)
        with urlopen(req,timeout=30) as response:value=json.load(response)
        transcript.append({'method':method,'path':path,'response':value})
        (directory/'transcript.json').write_text(json.dumps(transcript,ensure_ascii=False,indent=2),encoding='utf-8')
        return value
    def mutation(path, **fields):
        return request(path,'POST',{**fields,'request_id':uuid.uuid4().hex})
    def job(value):
        deadline=time.monotonic()+240
        while time.monotonic()<deadline:
            result=request('/jobs/'+value['job_id'])
            if result['state'] not in ('queued','running'):
                if result['state']!='succeeded':raise ValueError('Product job failed: '+str(result.get('error')))
                return result
            time.sleep(.6)
        raise TimeoutError('Product job remains pending; do not replay')
    def room_wait(room_id, expected):
        deadline=time.monotonic()+900
        while time.monotonic()<deadline:
            room=request('/rooms/'+room_id)
            if room['state'] not in ('running','pausing'):
                if room['state']!='awaiting_user' or room['turn_count']!=expected:
                    raise ValueError('Room did not finish expected turns: '+room['state'])
                return room
            time.sleep(.6)
        raise TimeoutError('Room remains pending; do not replay')
    analysis=next(a for a in request('/analyses')['analyses'] if a['status']=='experimental')
    ids=[p['id'] for p in analysis['perspectives']]
    if len(ids)<2:raise ValueError('Two generated perspectives required')
    session=mutation('/sessions',analysis_id=analysis['analysis_id'],bundle_revision=analysis['bundle_revision'],
        initial_opinion='안전성 검토는 의무화해야 한다고 생각한다. 공공의 안전이 중요하기 때문이다.')
    base='/sessions/'+session['session_id']
    (directory/'session.json').write_text(json.dumps({'session_id':session['session_id'],'token':token}),encoding='utf-8')
    comparison=job(mutation(base+'/comparisons',perspective_id=ids[0],initial_revision=1))
    duplicate=mutation(base+'/comparisons',perspective_id=ids[0],initial_revision=1)
    if duplicate['job_id']!=comparison['job_id']:raise ValueError('Comparison was regenerated')
    other=job(mutation(base+'/comparisons',perspective_id=ids[1],initial_revision=1))
    group=mutation(base+'/rooms',mode='group',participant_ids=ids[:2],initial_revision=1)
    mutation('/rooms/'+group['room_id']+'/start',opening_question='이 관점의 핵심 입장과 자료에 있는 이유를 설명해 주세요.',expected_revision=group['revision'])
    group=room_wait(group['room_id'],4)
    messages=[m for m in group['messages'] if m['author_kind']=='agent']
    if len({m['agent_id'] for m in messages})!=2:raise ValueError('Missing group speaker')
    points=[p for m in messages for p in m['points']]
    if not points:raise ValueError('No published grounds to inspect')
    citation=points[0]['citations']['comment_evidence'][0]
    source=request(base+'/sources/'+citation['source_id'])
    if citation['span']['text'] not in source['text']:raise ValueError('Source mismatch')
    direct=mutation(base+'/rooms',mode='one_to_one',participant_ids=ids[:1],initial_revision=1)
    mutation('/rooms/'+direct['room_id']+'/start',opening_question='어떤 입장인지 설명해 주세요.',expected_revision=direct['revision'])
    direct=room_wait(direct['room_id'],1)
    mutation('/rooms/'+direct['room_id']+'/messages',text='그 입장을 지지하는 이유는 무엇인가요?',
        reply_to_message_id=direct['messages'][-1]['message_id'],expected_revision=direct['revision'])
    direct=room_wait(direct['room_id'],2)
    request(base+'/opinions/current','PUT',{'text':'여전히 의무화가 필요하다고 생각한다. 선택의 자유도 고려해야 할 쟁점이라고 생각한다.',
        'expected_revision':0,'request_id':uuid.uuid4().hex})
    reflection=job(mutation(base+'/reflection-analyses',initial_revision=1,current_revision=1,
        context_message_ids=[m['message_id'] for m in messages]))
    result=reflection['result'];items={}
    for category,rows in result['categories'].items():
        items[category]=[{'text':r['explanation'],**{k:r[k] for k in ('initial_span_ids','current_span_ids','related_message_ids')}} for r in rows]
    saved=mutation(base+'/reflections',initial_revision=1,current_revision=1,analysis_job_id=reflection['job_id'],
        user_items=items,expected_revision=0)
    items['worth_more_thought']=[{'text':'의무화의 범위와 비용을 더 생각해 보고 싶다.',
        'initial_span_ids':[],'current_span_ids':['C000'],'related_message_ids':[messages[-1]['message_id']]}]
    saved=request(base+'/reflections/'+saved['reflection_id'],'PUT',{'initial_revision':1,'current_revision':1,
        'analysis_job_id':reflection['job_id'],'user_items':items,'expected_revision':1,'request_id':uuid.uuid4().hex})
    reread=request(base+'/reflections/'+saved['reflection_id'])
    if reread!=dict(saved,stale=False,source_status='experimental'):raise ValueError('Saved revision mismatch')
    restored=request(base)
    if restored['reflections'][0]['revision']!=2:raise ValueError('Session did not restore reflection')
    report={'functional_flow_passed':True,'expected_model_requests_maximum':9,
        'comparison_item_counts':[len(comparison['result']['items']),len(other['result']['items'])],
        'group_turns':group['turn_count'],'one_to_one_turns':direct['turn_count'],
        'reflection_category_counts':{k:len(v) for k,v in result['categories'].items()},
        'saved_revision':2,'quality_gate_passed':False,'semantic_reliability':'not_assessed',
        'input_scope':'historical automatically generated development bundle; not a 999-comment gate'}
    (directory/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('origin');parser.add_argument('directory',type=Path)
    parser.add_argument('--live',action='store_true',required=True)
    args=parser.parse_args();exercise(args.origin,args.directory)


if __name__=='__main__':main()
