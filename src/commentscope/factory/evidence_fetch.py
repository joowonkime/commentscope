"""Bounded public document capture; no search, source ranking, or truth approval."""
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
import re
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, ProxyHandler

from commentscope.providers.local_llama import NoRedirect

ALLOWED_HOSTS = frozenset({'tietotarjotin.fi','valtioneuvosto.fi'})
MAX_BYTES = 2_000_000


class Paragraphs(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ignored = 0
        self.tag = None
        self.parts = []
        self.rows = []

    def handle_starttag(self, tag, attrs):
        if tag in {'script','style','noscript'}:
            self.ignored += 1
        if not self.ignored and tag in {'p','h1','h2','h3'}:
            self.flush()
            self.tag = tag

    def handle_endtag(self, tag):
        if tag in {'script','style','noscript'} and self.ignored:
            self.ignored -= 1
        if not self.ignored and tag == self.tag:
            self.flush()

    def handle_data(self, data):
        if self.tag and not self.ignored:
            self.parts.append(data)

    def flush(self):
        text = re.sub(r'\s+', ' ', ''.join(self.parts)).strip()
        if text:
            self.rows.append(text)
        self.parts = []; self.tag = None


def fetch(url, media_type):
    request = Request(url, headers={'User-Agent':'CommentScope research prototype/0.1'})
    opener = build_opener(ProxyHandler({}), NoRedirect())
    with opener.open(request, timeout=30) as response:
        if response.headers.get_content_type() != media_type:
            raise ValueError('Unexpected public document content type')
        raw = response.read(MAX_BYTES+1)
        if len(raw) > MAX_BYTES:
            raise ValueError('Document exceeds capture budget')
        charset = response.headers.get_content_charset() or 'utf-8'
        body = raw.decode(charset, errors='strict')
    return raw, charset, body


def kela_article(payload, article_id):
    if not isinstance(payload,list) or len(payload)!=1 or payload[0].get('articleId')!=article_id:
        raise ValueError('Unexpected Kela article identity')
    article = payload[0]
    if not article.get('content_en') or not article.get('title_en'):
        raise ValueError('No English article content')
    fragments=[]
    def visit(value):
        if isinstance(value,list):
            for child in value: visit(child)
        elif isinstance(value,dict):
            for key,child in value.items():
                if key=='content' and isinstance(child,str): fragments.append(child)
                else: visit(child)
    visit(article['content_en'])
    if not fragments: raise ValueError('No public article content fragments')
    return article, '\n'.join(fragments)


def capture(url):
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.hostname not in ALLOWED_HOSTS or parsed.port not in (None,443) or parsed.username or parsed.password or parsed.fragment:
        raise ValueError('URL must be an explicitly allowed public HTTPS source')
    raw,charset,body=fetch(url,'text/html')
    parser = Paragraphs(); parser.feed(body); parser.close(); parser.flush()
    request_url=url; mode='all_server_rendered_headings_and_paragraphs'; metadata={}
    article_match=re.fullmatch(r'/en/information-package/([0-9]+)/[a-z0-9-]+/?',parsed.path)
    if not parser.rows and parsed.hostname=='tietotarjotin.fi' and article_match:
        # Public endpoint used by this site's frontend, no credentials or browser bypass.
        request_url='https://tietotarjotin.fi/api/node-cache/articles/'+article_match[1]
        raw,charset,body=fetch(request_url,'application/json')
        article,fragment=kela_article(json.loads(body),article_match[1])
        parser=Paragraphs();parser.feed(fragment);parser.close();parser.flush()
        mode='public_kela_article_content_html_fields'
        metadata={'title':article['title_en'],'published_at':article['publishDate'],'modified_at':article['modifyDate']}
    if not parser.rows:
        raise ValueError('No server-rendered document paragraphs')
    return {'url':url,'retrieved_at':datetime.now(timezone.utc).isoformat(),
            'raw_sha256':hashlib.sha256(raw).hexdigest(),'encoding':charset,
            'raw_body':body,'request_url':request_url,'metadata':metadata,
            'paragraphs':parser.rows,'text':'\n\n'.join(parser.rows),'selection':mode,
            'limitations':'Allowed publisher host is not a semantic accuracy certificate; no automatic search performed.'}
