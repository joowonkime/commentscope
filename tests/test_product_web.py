from http.client import HTTPConnection
import json
import secrets
import threading
import unittest

from commentscope.product.web import ProductServer
from commentscope.agents.grounded_web import GroundedApp
import test_product_app as fixtures
from test_grounded_web import provider


class ProductHTTPTests(unittest.TestCase):
    def setUp(self):
        core=fixtures.ProductAppTests('runTest');core.setUp()
        self.addCleanup(core.doCleanups)
        for key in ('app','analysis','path','token','sid','base','calls'):setattr(self,key,getattr(core,key))

    def test_real_http_opinions_and_legacy_endpoints_share_server(self):
        legacy=GroundedApp(self.analysis.bundle,self.path.parent/'legacy',provider=provider)
        server=ProductServer(self.app,legacy,0)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        origin='http://127.0.0.1:'+str(server.server_address[1])
        def request(method,path,body=None,token=None,mutate_origin=True):
            connection=HTTPConnection('127.0.0.1',server.server_address[1],timeout=3)
            headers={'X-Session-Token':token or self.token}
            if body is not None:headers['Content-Type']='application/json'
            if mutate_origin:headers['Origin']=origin
            connection.request(method,path,None if body is None else json.dumps(body),headers)
            response=connection.getresponse();data=response.read();connection.close()
            return response.status,json.loads(data)
        status,state=request('GET',self.base)
        self.assertEqual(status,200);self.assertEqual(state['session_id'],self.sid)
        status,_=request('POST','/api/session',{'ids':['P1']})
        self.assertEqual(status,201)
        status,_=request('PUT',self.base+'/opinions/current',
            {'text':'My own view.','expected_revision':0,'request_id':'http1'})
        self.assertEqual(status,200)
        status,_=request('PUT',self.base+'/opinions/current',
            {'text':'Rejected.','expected_revision':1,'request_id':'http2'},mutate_origin=False)
        self.assertEqual(status,403)
        self.assertFalse(self.calls)
