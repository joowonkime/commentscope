from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
import json

from commentscope.factory import observation_reuse as reuse
from commentscope.factory.shared_admission import PriorRequestUnavailable
import test_source_role_replay as fixture


class ObservationReuseTests(TestCase):
    def original(self,root):
        plan,request,output,call,result=fixture.SourceRoleReplayTests().original(root)
        (root/'completed.json').write_text(json.dumps({'plan_sha256':reuse.file_sha(root/'plan.json')}),encoding='utf-8')
        return plan,request,output,call,result

    def test_streaming_preserves_exact_object_content_unicode_and_order(self):
        with TemporaryDirectory() as temp:
            path=Path(temp)/'array.json';value=[{'n':i,'text':'🙂한글 " [ ] } \\ '+str(i),'nested':[{'x':True}]} for i in range(8)]
            path.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8')
            for size in (1,7,64):self.assertEqual(list(reuse.object_array(path,chunk_size=size)),value)
            path.write_text('[]',encoding='utf-8');self.assertEqual(list(reuse.object_array(path)),[])

    def test_invalid_truncated_or_nonobject_arrays_are_rejected(self):
        with TemporaryDirectory() as temp:
            path=Path(temp)/'array.json'
            for text in ('{}','[1]','[{},]','[{}] true','[{"x":','[{}'):
                path.write_text(text,encoding='utf-8')
                with self.subTest(text=text),self.assertRaises(ValueError):list(reuse.object_array(path,chunk_size=3))

    def test_exact_original_response_is_reused_without_changing_its_provenance(self):
        with TemporaryDirectory() as temp:
            root=Path(temp);plan,request,_,_,result=self.original(root);before=result.read_bytes();saved={}
            index=reuse.build_index([(root,{'source-evidence-proposal'})])
            cache=reuse.OriginalObservations(index,lambda k,v:saved.setdefault(k,v))
            response=cache.lookup('source-evidence-proposal',request,plan['deployment'])
            self.assertEqual(response,json.loads(before));response['output']={}
            self.assertEqual(result.read_bytes(),before);self.assertEqual(len(cache.reused),1)
            self.assertEqual(len(saved),1)

    def test_different_input_or_deployment_is_never_reused(self):
        with TemporaryDirectory() as temp:
            root=Path(temp);plan,request,_,_,_=self.original(root)
            cache=reuse.OriginalObservations(reuse.build_index([(root,{'source-evidence-proposal'})]),lambda k,v:None)
            changed={**request,'system':request['system']+' changed'}
            self.assertIsNone(cache.lookup('source-evidence-proposal',changed,plan['deployment']))
            deployment={**plan['deployment'],'model':'openai/gpt-5.2'}
            self.assertIsNone(cache.lookup('source-evidence-proposal',request,deployment))

    def test_failed_and_pending_originals_are_holds_not_fresh_call_permission(self):
        with TemporaryDirectory() as temp:
            root=Path(temp);plan,request,_,_,result=self.original(root)
            value=json.loads(result.read_text(encoding='utf-8'));value['errors']=['incomplete_generation'];result.write_text(json.dumps(value),encoding='utf-8')
            index=reuse.build_index([(root,{'source-evidence-proposal'})]);cache=reuse.OriginalObservations(index,lambda k,v:None)
            with self.assertRaises(PriorRequestUnavailable):cache.lookup('source-evidence-proposal',request,plan['deployment'])
            result.unlink();cache=reuse.OriginalObservations(reuse.build_index([(root,{'source-evidence-proposal'})]),lambda k,v:None)
            with self.assertRaises(PriorRequestUnavailable):cache.lookup('source-evidence-proposal',request,plan['deployment'])

    def test_changed_original_file_and_duplicate_attempts_are_rejected(self):
        with TemporaryDirectory() as temp:
            root=Path(temp);plan,request,_,call,result=self.original(root)
            index=reuse.build_index([(root,{'source-evidence-proposal'})]);result.write_bytes(result.read_bytes()+b' ')
            cache=reuse.OriginalObservations(index,lambda k,v:None)
            with self.assertRaises(ValueError):cache.lookup('source-evidence-proposal',request,plan['deployment'])
            other=call.with_name(call.name.replace('0001','0002'));other.write_bytes(call.read_bytes())
            cache=reuse.OriginalObservations(reuse.build_index([(root,{'source-evidence-proposal'})]),lambda k,v:None)
            with self.assertRaises(PriorRequestUnavailable):cache.lookup('source-evidence-proposal',request,plan['deployment'])
