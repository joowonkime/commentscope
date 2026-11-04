"""Same-origin v1 product endpoints alongside the unchanged legacy API."""
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import urlsplit

from commentscope.agents.grounded_web import GroundedHandler
from commentscope.agents.web import WebError


ROOT=Path(__file__).parent


class ProductHandler(GroundedHandler):
    def do_PUT(self):self._handle(True)

    def _handle(self,mutation=False):
        path=urlsplit(self.path).path
        assets={'/mvp':('mvp.html','text/html; charset=utf-8'),
                '/mvp/':('mvp.html','text/html; charset=utf-8'),
                '/mvp/app.js':('mvp.js','text/javascript; charset=utf-8'),
                '/mvp/app.css':('mvp.css','text/css; charset=utf-8')}
        if not path.startswith('/api/v1/') and path not in assets:
            return super()._handle(mutation)
        try:
            self._guard(mutation)
            if not mutation and path in assets:
                name,kind=assets[path];return self.reply(200,(ROOT/name).read_bytes(),kind)
            body=None
            if mutation:
                if self.headers.get('Transfer-Encoding') or self.headers.get('Content-Type')!='application/json':
                    raise WebError(415,'json_required')
                try:
                    size=int(self.headers.get('Content-Length','-1'))
                    if not 0<size<=65536:raise ValueError()
                    body=json.loads(self.rfile.read(size))
                    if not isinstance(body,dict):raise ValueError()
                except (ValueError,UnicodeError):raise WebError(400,'invalid_body') from None
            status,result=self.server.product.handle(self.command,self.path,
                self.headers.get('X-Session-Token',''),body)
            return self.reply(status,result)
        except WebError as exc:
            self.reply(exc.status,{'error':{'code':exc.code,'retryable':False}})
        except (BrokenPipeError,ConnectionResetError,TimeoutError):pass
        except Exception:self.reply(500,{'error':{'code':'server_error','retryable':False}})


class ProductServer(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self,product,legacy,port):
        self.product=product;self.app=legacy
        super().__init__(('127.0.0.1',port),ProductHandler)
        actual=self.server_address[1]
        self.hosts={f'127.0.0.1:{actual}',f'localhost:{actual}'}
