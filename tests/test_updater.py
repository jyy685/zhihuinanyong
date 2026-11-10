import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import MagicMock, patch

import requests
from lms_app.updater import check_latest, version_tuple, API_URL, RELEASES_URL
from lms_app.gui import Application


def response_session(data=None, status=200):
    response = MagicMock()
    response.status_code = status
    response.headers = {}
    response.url = API_URL
    response.text = ''
    response.json.return_value = data
    if status >= 400:
        response.raise_for_status.side_effect = requests.HTTPError(response=response)
    response.__enter__.return_value = response
    session = MagicMock()
    session.get.return_value = response
    return session


def release(tag='v1.2.0'):
    page = 'https://github.com/jyy685/zhihuinanyong/releases'
    return {'tag_name': tag, 'html_url': page+'/tag/'+tag, 'body': '更新说明',
            'assets': [{'name': 'ZhihuiNanyong.exe', 'browser_download_url': page+'/download/'+tag+'/ZhihuiNanyong.exe'}]}


class UpdateServiceTests(unittest.TestCase):
    def test_rate_limited_api_falls_back_to_empty_release_page(self):
        limited = response_session(status=403).get.return_value
        limited.headers = {'X-RateLimit-Remaining': '0'}
        page = response_session().get.return_value
        page.url = RELEASES_URL
        page.text = '<h2>There aren&#39;t any releases here</h2>'
        session = MagicMock()
        session.get.side_effect = [limited, page]
        result = check_latest('1.1.0', session)
        self.assertEqual(result['state'], 'no_release')
        self.assertEqual(result['source'], 'github_web')
        self.assertEqual(session.get.call_count, 2)

    def test_web_release_and_lazy_asset_fragment(self):
        limited = response_session(status=429).get.return_value
        page = response_session().get.return_value
        page.url = RELEASES_URL+'/tag/v1.2.0'
        page.text = '<div>Release notes</div>'
        fragment = response_session().get.return_value
        fragment.url = RELEASES_URL+'/expanded_assets/v1.2.0'
        fragment.text = '<a href="/jyy685/zhihuinanyong/releases/download/v1.2.0/ZhihuiNanyong.exe">Download</a>'
        session = MagicMock()
        session.get.side_effect = [limited, page, fragment]
        result = check_latest('1.1.0', session)
        self.assertEqual(result['state'], 'available')
        self.assertEqual(result['source'], 'github_web')
        self.assertTrue(result['download_url'].endswith('/ZhihuiNanyong.exe'))

    def test_web_failure_does_not_claim_no_release(self):
        forbidden = response_session(status=403).get.return_value
        page = response_session().get.return_value
        page.url = RELEASES_URL
        page.text = '<h1>Access denied</h1>'
        session = MagicMock()
        session.get.side_effect = [forbidden, page]
        result = check_latest('1.1.0', session)
        self.assertEqual(result['state'], 'error')
        self.assertIn('HTTP 403', result['message'])
        self.assertNotIn('额度已用尽', result['message'])

    def test_rate_limit_backoff_avoids_repeated_api_requests(self):
        page = response_session().get.return_value
        page.url = RELEASES_URL
        page.text = '<h2>There aren’t any releases here</h2>'
        session = MagicMock()
        session.get.return_value = page
        with patch('lms_app.updater._api_retry_at', time.time()+60), patch('lms_app.updater.requests.Session', return_value=session):
            result = check_latest('1.1.0')
        self.assertEqual(result['state'], 'no_release')
        session.get.assert_called_once()
        self.assertEqual(session.get.call_args.args[0], RELEASES_URL+'/latest')
        session.close.assert_called_once()

    def test_numeric_versions_and_assets(self):
        self.assertGreater(version_tuple('v1.10.0'), version_tuple('1.9.9'))
        result = check_latest('1.1.0', response_session(release()))
        self.assertEqual(result['state'], 'available')
        self.assertTrue(result['download_url'].endswith('/ZhihuiNanyong.exe'))
        self.assertEqual(check_latest('1.2.0', response_session(release()))['state'], 'current')
        self.assertEqual(check_latest('2.0.0', response_session(release()))['state'], 'current')

    def test_no_release_rate_limit_and_untrusted_links(self):
        self.assertEqual(check_latest('1.1.0', response_session(status=404))['state'], 'no_release')
        self.assertEqual(check_latest('1.1.0', response_session(status=403))['state'], 'error')
        bad = release()
        bad['html_url'] = 'https://github.com.evil.example/releases'
        self.assertEqual(check_latest('1.1.0', response_session(bad))['state'], 'error')
        bad = release('v2.0.0-beta')
        self.assertEqual(check_latest('1.1.0', response_session(bad))['state'], 'error')
        bad = release()
        bad['assets'][0]['browser_download_url'] = 'file:///C:/untrusted.exe'
        self.assertIsNone(check_latest('1.1.0', response_session(bad))['download_url'])


class UpdateGuiTests(unittest.TestCase):
    def test_automatic_silence_manual_check_and_marker(self):
        with tempfile.TemporaryDirectory() as folder:
            root = tk.Tk()
            root.withdraw()
            app = Application(root, folder, enable_updates=False)
            try:
                with patch('lms_app.gui.messagebox.showwarning') as warning, patch('lms_app.gui.messagebox.showinfo') as info:
                    app.events.put(('update', {'state': 'error', 'message': 'offline'}))
                    app.poll()
                    warning.assert_not_called()
                    info.assert_not_called()
                    app.events.put(('update', dict(state='available', version='2.0.0', url=release()['html_url'])))
                    app.poll()
                    self.assertEqual(app.update_dot.cget('text'), '●')
                    app.events.put(('update', {'state': 'error', 'message': 'offline'}))
                    app.poll()
                    self.assertEqual(app.update_dot.cget('text'), '●')
                    warning.assert_not_called()
                    with patch('lms_app.gui.check_latest', return_value={'state': 'current', 'message': 'latest'}) as service:
                        app.check_updates(manual=True)
                        deadline = time.monotonic()+3
                        while app.events.empty() and time.monotonic()<deadline:
                            time.sleep(.01)
                        app.poll()
                        service.assert_called_once()
                    info.assert_called_once()
                    self.assertEqual(app.update_dot.cget('text'), '')
                    self.assertFalse(app.busy)
            finally:
                root.destroy()


if __name__ == '__main__':
    unittest.main()
