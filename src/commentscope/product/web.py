"""Same-origin v1 product endpoints alongside the unchanged legacy API."""
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from commentscope.agents.grounded_web import GroundedHandler
from commentscope.agents.web import WebError


ROOT=Path(__file__).parent


class ProductHandler(GroundedHandler):
    def do_PUT(self):self._handle(True)

    def send_header(self,keyword,value):
        if keyword.lower()=='content-security-policy':
            value=("default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
                   "img-src 'self' https://i.ytimg.com; font-src 'self'; frame-src https://www.youtube-nocookie.com; "
                   "frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        super().send_header(keyword,value)

    def _guard(self,mutation=False):
        host=self.headers.get('Host');origin=self.headers.get('Origin')
        if host not in self.server.origins:raise WebError(403,'invalid_host')
        if origin is not None and origin!=self.server.origins[host] or mutation and origin is None:
            raise WebError(403,'invalid_origin')
        if self.headers.get('Sec-Fetch-Site') not in (None,'same-origin','none'):
            raise WebError(403,'cross_origin_request')

    def _handle(self,mutation=False):
        path=urlsplit(self.path).path
        assets={'/mvp':('mvp.html','text/html; charset=utf-8'),
                '/mvp/':('mvp.html','text/html; charset=utf-8'),
                '/mvp/app.js':('mvp.js','text/javascript; charset=utf-8'),
                '/mvp/app.css':('mvp.css','text/css; charset=utf-8')}
        if path.startswith('/mvp/assets/'):
            if not re.fullmatch(r'/mvp/assets/[A-Za-z0-9_-]+\.(svg|png|woff2)',path):
                return self.reply(404,{'error':{'code':'asset_not_found','retryable':False}})
            name=path.removeprefix('/mvp/')
            if not (ROOT/name).is_file():return self.reply(404,{'error':{'code':'asset_not_found','retryable':False}})
            extension=path.rsplit('.',1)[1];assets[path]=(name,{'svg':'image/svg+xml','png':'image/png','woff2':'font/woff2'}[extension])
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
    def __init__(self,product,legacy,port,*,bind_host='127.0.0.1',public_origin=None):
        if bind_host not in ('127.0.0.1','0.0.0.0'):raise ValueError('Explicit IPv4 bind required')
        external=None
        if public_origin is not None:
            parsed=urlsplit(public_origin)
            if (parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password
                    or parsed.path not in ('','/') or parsed.query or parsed.fragment):
                raise ValueError('One explicit HTTPS public origin required')
            external=parsed.netloc.lower()
        self.product=product;self.app=legacy
        super().__init__((bind_host,port),ProductHandler)
        actual=self.server_address[1]
        self.hosts={f'127.0.0.1:{actual}',f'localhost:{actual}'}
        self.origins={host:'http://'+host for host in self.hosts}
        if external:self.hosts.add(external);self.origins[external]='https://'+external
