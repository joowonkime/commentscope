"""Model-free synthetic UI/API demo for teammates; no real quality evidence."""
import argparse
from copy import deepcopy
import json
from pathlib import Path

from commentscope.agents.grounded_web import GroundedApp, GroundedHandler, GroundedServer, ROOT
from commentscope.agents.web import WebError
from commentscope.factory.automatic_contract import digest

NOTICE='조원 연동용 합성 데모입니다. 실제 댓글·모델 추론·Factory 품질 검증 결과가 아닙니다.'
POSITION_QUESTIONS={'what is the central position represented here?', '핵심 입장은 무엇인가요?'}


def fixture_bundle():
    scope={'entity':'합성 기능 도입 예제','time':'','conditions':''}
    bundle={'expires_at':'2099-01-01T00:00:00Z',
        'model':{'name':'SYNTHETIC_STUB_NOT_A_MODEL','revision':'teammate-demo-v1',
                 'weights_sha256':'0'*64,'runtime_sha256':'0'*64},
        'sources':[],'claims':[],'relations':[],'documents':[],'checks':[],
        'candidates':[],'source_contexts':{}}
    statements=[('demo-safety','합성 예제: 새 기능은 안전 검토 후 도입해야 한다.'),
                ('demo-stages','합성 예제: 새 기능은 작은 규모부터 단계적으로 도입해야 한다.')]
    for cid,text in statements:
        core={'id':cid+':core','text':text,'kind':'value','scope':deepcopy(scope),'requires':[]}
        bundle['claims'].append(core);sources=[]
        for i in range(3):
            source={'id':cid+':source'+str(i),'canonical_id':cid+':source'+str(i),'text':text}
            sources.append(source);bundle['sources'].append(source)
            bundle['relations'].append({'claim_id':core['id'],'claim_sha256':digest(core),
                'source_id':source['id'],'source_sha256':digest(text),
                'span':{'start':0,'end':len(text),'text':text},'verdict':'supported',
                'trace_id':'synthetic-fixture:'+source['id'],'origin':'synthetic_fixture'})
        candidate={'id':cid,'core_claim_id':core['id'],'reason_claim_ids':[],
                   'major_fact_ids':[],'argument_roles':{}}
        if cid=='demo-safety':
            reason={'id':cid+':reason','text':'합성 예제: 안전을 우선하는 것이 중요하다.',
                    'kind':'value','scope':deepcopy(scope),'requires':[]}
            bundle['claims'].append(reason);candidate['reason_claim_ids']=[reason['id']]
            candidate['argument_roles'][reason['id']]='reason'
            source=sources[0];source['text']+=' '+reason['text']
            # Rebind core source hash after adding the author's own rationale.
            bundle['relations'][-3]['source_sha256']=digest(source['text'])
            start=source['text'].index(reason['text'])
            bundle['relations'].append({'claim_id':reason['id'],'claim_sha256':digest(reason),
                'source_id':source['id'],'source_sha256':digest(source['text']),
                'span':{'start':start,'end':len(source['text']),'text':reason['text']},
                'verdict':'supported','trace_id':'synthetic-fixture:reason','origin':'synthetic_fixture'})
        else:
            parent={'id':sources[0]['id'],'text':sources[0]['text']}
            bundle['source_contexts'][sources[2]['id']]={'source_sha256':digest(sources[2]['text']),
                'parent_sha256':digest(parent),'parent':parent}
        bundle['candidates'].append(candidate)
    return bundle


def fixture_provider(system,data,schema,**kwargs):
    entries=data['PERSPECTIVE']['allowed_entries'];question=data['QUESTION'].strip().lower()
    if 'QUESTION_ROLE_CONSTRAINT' in data:
        chosen=[e['claim_id'] for e in entries if e['declared_role']=='reason'][:1]
    elif question in POSITION_QUESTIONS:
        chosen=[data['PERSPECTIVE']['core_claim_id']]
    else:
        chosen=[]
    value={'answerability':'grounded' if chosen else 'not_in_evidence','claim_ids':chosen,
           'limitation':'none' if chosen else 'missing_evidence'}
    return {'choices':[{'message':{'content':json.dumps(value)},'finish_reason':'stop'}]}


class DemoHandler(GroundedHandler):
    def _handle(self,mutation=False):
        if not mutation and self.path=='/':
            try:
                self._guard(False)
                page=(ROOT/'grounded.html').read_text().replace('<h1>CommentScope</h1>',
                    '<h1>CommentScope · 합성 연동 데모</h1><p class="notice">'+NOTICE+'</p>')
                return self.reply(200,page.encode(),'text/html; charset=utf-8')
            except WebError as exc:
                return self.reply(exc.status,{'error':exc.code})
        return super()._handle(mutation)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8766)
    parser.add_argument('--session-dir',type=Path,default=Path('runs/team-demo'))
    args=parser.parse_args()
    app=GroundedApp(fixture_bundle(),args.session_dir,provider=fixture_provider)
    server=GroundedServer(app,args.port);server.RequestHandlerClass=DemoHandler
    print(NOTICE,flush=True)
    print(f'http://127.0.0.1:{server.server_address[1]}',flush=True)
    print('질문 예: 핵심 입장은 무엇인가요? / 이유와 조건은 무엇인가요? / 정확한 시행 비용은?',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()


if __name__=='__main__':main()
