import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from http.server import ThreadingHTTPServer

from lms_app.core import Client, Cancelled, LoginExpired, parse_cookies
from lms_app.smoke import FixtureHandler


class CoreTests(unittest.TestCase):
    def test_cookie_formats(self):
        forms = [
            'session=example; role_token=role-value',
            'session\texample\tlms.nju.edu.cn\t/\nrole_token\trole-value\tlms.nju.edu.cn\t/',
            '# Netscape HTTP Cookie File\n#HttpOnly_lms.nju.edu.cn\tFALSE\t/\tTRUE\t0\tsession\texample',
            json.dumps([{'name': 'session', 'value': 'example', 'domain': 'lms.nju.edu.cn', 'path': '/'}])]
        for text in forms:
            with self.subTest(text=text):
                self.assertEqual(parse_cookies(text).get('session'), 'example')
        for invalid in ['', '_ga=only-analytics', 'session=truncated…', 'session=完整值', 'just-a-value', '{broken']:
            with self.subTest(text=invalid), self.assertRaises(ValueError):
                parse_cookies(invalid)

    def test_catalog_pagination_and_file_generator(self):
        c = Client('session=example')
        with patch.object(c, 'json', side_effect=[{'courses': [{'id': 1}], 'pages': 2}, {'courses': [{'id': 2}], 'pages': 2}]):
            self.assertEqual([r['id'] for r in c.courses()], [1, 2])
        pages = [{'activities': [{'id': 1, 'uploads': [{'id': 11, 'name': 'same.pdf'}]}], 'pages': 2},
                 {'activities': [{'id': 2, 'uploads': [{'id': 12, 'name': 'same.pdf'}]}], 'pages': 2}]
        with patch.object(c, 'json', side_effect=pages):
            self.assertEqual([r['name'] for r in c.files(1)], ['same_11.pdf', 'same_12.pdf'])
        c.close()

    def test_transfer_skip_cancel_and_preview(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), FixtureHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        c = Client('session=example')
        try:
            url = f'http://127.0.0.1:{server.server_port}/fixture.pdf'
            u = {'id': 1, 'name': '课件.pdf', 'size': len(FixtureHandler.payload), 'allow_download': False}
            with tempfile.TemporaryDirectory() as tmp:
                with patch.object(c, 'json', return_value={'url': url}):
                    self.assertEqual(c.download(u, tmp, lambda *_: None)[0], '已完成')
                    self.assertEqual(c.download(u, tmp, lambda *_: None)[0], '已跳过')
                self.assertEqual((Path(tmp) / '课件.pdf').read_bytes(), FixtureHandler.payload)
                u['name'] = 'cancel.pdf'
                with self.assertRaises(Cancelled):
                    c.transfer(url, u, tmp, lambda *_: c.stop.set(), u['size'])
                self.assertFalse((Path(tmp) / 'cancel.pdf').exists())
                self.assertFalse((Path(tmp) / 'cancel.pdf.part').exists())
                c.stop.clear()
                u['name'] = 'wrong-size.pdf'
                with self.assertRaises(ValueError):
                    c.transfer(url, u, tmp, lambda *_: None, 1)
                self.assertFalse((Path(tmp) / 'wrong-size.pdf').exists())
                self.assertFalse((Path(tmp) / 'wrong-size.pdf.part').exists())
        finally:
            c.close()
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    unittest.main()
