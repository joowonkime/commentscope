import unittest
from unittest.mock import patch

from commentscope.factory.evidence_fetch import Paragraphs, capture, kela_article


class EvidenceFetchTests(unittest.TestCase):
    def test_inline_text_and_entities_preserved_scripts_excluded(self):
        parser=Paragraphs()
        parser.feed('<h1>Report</h1><p>12 <b>devices</b> &amp; 3 tests.<script>bad()</script></p><style>bad{}</style><p>Next\nitem.</p>')
        parser.flush()
        self.assertEqual(parser.rows,['Report','12 devices & 3 tests.','Next item.'])

    def test_arbitrary_hosts_credentials_and_ports_blocked_before_network(self):
        with patch('commentscope.factory.evidence_fetch.build_opener') as opener:
            for url in ['http://tietotarjotin.fi/','https://127.0.0.1/','https://tietotarjotin.fi.evil.test/',
                        'https://user:password@tietotarjotin.fi/','https://tietotarjotin.fi:8080/',
                        'https://tietotarjotin.fi/#fragment']:
                with self.subTest(url=url), self.assertRaises(ValueError): capture(url)
            opener.assert_not_called()

    def test_public_article_identity_and_language_are_bound(self):
        article={'articleId':'123','title_en':'Synthetic','content_en':[{'components':[{'content':'<p>First</p>'},{'content':'<p>Second</p>'}]}]}
        metadata,markup=kela_article([article],'123')
        self.assertEqual(markup,'<p>First</p>\n<p>Second</p>')
        self.assertEqual(metadata['title_en'],'Synthetic')
        for payload in [[article,article],[{**article,'articleId':'other'}],[{**article,'content_en':[]}]]:
            with self.assertRaises(ValueError): kela_article(payload,'123')


if __name__ == '__main__': unittest.main()
