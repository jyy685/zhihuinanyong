import json
import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

from lms_app.cookies import extract_cookies
from lms_app.gui import Application
from lms_app.ui_support import bounded_geometry


def settle(root):
    for _ in range(5):
        root.update()
        time.sleep(.012)


def cleanup(root):
    for token in root.tk.call('after','info'):
        root.after_cancel(token)
    root.destroy()


class CookieExtractionTests(unittest.TestCase):
    def test_surrounding_page_text_formats(self):
        inputs = [
            '页面说明\n名称\t值\t域\t路径\n_ga\tabc\t.nju.edu.cn\t/\nsession\tfull-token-123\tlms.nju.edu.cn\t/\nCookie Value\n其他内容',
            '开发者工具\nRequest URL: https://lms.nju.edu.cn/api/my-courses\nHost: lms.nju.edu.cn\nCookie: _ga=abc; session=full-token-123; role_token=role-token-xyz\nUser-Agent: browser',
            '页面内容\nsession\nfull-token-123\nlms.nju.edu.cn\n/\n2027\nCookie Value\n其他内容',
            '页面内容\nsession  full-token-123  lms.nju.edu.cn  /\n其他内容',
            '<html><body><h1>Cookie</h1><table><tr><td>session</td><td>full-token-123</td><td>lms.nju.edu.cn</td><td>/</td></tr></table></body></html>',
            '导出内容\n'+json.dumps({'cookies':[{'name':'session','value':'full-token-123','domain':'lms.nju.edu.cn'}]})+'\n导出结束',
            "curl 'https://lms.nju.edu.cn/api/my-courses' -H 'Cookie: session=full-token-123; role_token=role-token-xyz'",
        ]
        for raw in inputs:
            with self.subTest(format=raw[:20]):
                result = extract_cookies(raw)
                self.assertEqual(result.jar.get('session'),'full-token-123')
                self.assertNotIn('full-token-123',result.summary)
                self.assertEqual(extract_cookies(result.normalized()).jar.get('session'),'full-token-123')

    def test_rejects_ambiguous_foreign_and_incomplete_values(self):
        inputs = [
            'session=abc…', 'session=abc...', 'Cookie Value\nvalue-with-no-name',
            'session=one; session=two', 'session\tsecret\texample.com\t/',
            json.dumps([{'name':'session','value':'secret','domain':'example.com'}]),
            'Host: example.com\nCookie: session=secret',
            'session=full-token-123; role_token=truncated…',
            '<html><script>var data={"session":"not-a-cookie"};</script><p>只有正文</p></html>'
        ]
        for raw in inputs:
            with self.subTest(raw=raw[:20]),self.assertRaises(ValueError):
                extract_cookies(raw)


class UsabilityTests(unittest.TestCase):
    def assert_inside(self,widget,root):
        x = widget.winfo_rootx()-root.winfo_rootx()
        y = widget.winfo_rooty()-root.winfo_rooty()
        self.assertTrue(widget.winfo_ismapped(),str(widget))
        self.assertGreaterEqual(x,0)
        self.assertGreaterEqual(y,0)
        self.assertLessEqual(x+widget.winfo_width(),root.winfo_width()+1)
        self.assertLessEqual(y+widget.winfo_height(),root.winfo_height()+1)

    def test_window_matrix_keeps_key_controls_visible(self):
        for scale in (1,1.25,1.5,2):
            with tempfile.TemporaryDirectory() as temp:
                root=tk.Tk();root.attributes('-alpha',0)
                root.tk.call('tk','scaling',scale*96/72)
                app=Application(root,temp,enable_updates=False)
                try:
                    for width,height in ((640,480),(900,600),(1024,680),(1180,720)):
                        with self.subTest(scale=scale,size=(width,height)):
                            root.geometry(f'{width}x{height}+3000+30');settle(root)
                            for page in range(3):
                                app.tabs.select(page);settle(root)
                                for control in (app.download_button,app.stop_button,app.folder_button,app.folder_entry,app.update_button):
                                    self.assert_inside(control,root)
                                self.assertGreater(app.tabs.winfo_height(),50)
                    guide=app.help();guide.attributes('-alpha',0);guide.geometry('900x600+3000+30');settle(root)
                    self.assert_inside(guide.previous,guide)
                    self.assert_inside(guide.next_button,guide)
                    guide.show_step(1);settle(root)
                    self.assertLessEqual(guide.thumbnail.width(),guide.canvas.winfo_width())
                    guide.destroy()
                    dialog=app.details('长内容','测试说明\n'*200);dialog.attributes('-alpha',0);dialog.geometry('700x480+3000+30');settle(root)
                    dialog.destroy()
                finally:
                    cleanup(root)

    def test_sort_filter_selection_cookie_normalization_and_settings(self):
        with tempfile.TemporaryDirectory() as temp:
            root=tk.Tk();root.attributes('-alpha',0)
            app=Application(root,temp,enable_updates=False)
            try:
                app.events.put(('courses',[{'id':1,'name':'课程 A'}]))
                app.events.put(('files',1,[{'id':11,'name':'第10讲.pdf','size':20,'allow_download':True},
                                          {'id':12,'name':'第2讲.pdf','size':10,'allow_download':True}]))
                app.poll();settle(root)
                app.toggle_course('1');app.sort_by('file','name')
                self.assertEqual([f['id'] for f in app.visible_files()],[12,11])
                app.file_query.set('第2');app.select_visible(False)
                self.assertEqual(app.selected,{(1,11)})
                self.assertIn('已选 1/2',app.title.cget('text'))
                app.file_query.set('');self.assertEqual(len(app.visible_files()),2)
                app.cookie_text.insert('1.0','页面正文\nCookie: session=full-test-value\n其他内容')
                with patch.object(app,'start'):
                    app.connect()
                self.assertNotIn('页面正文',app.raw_cookie)
                self.assertEqual(extract_cookies(app.raw_cookie).jar.get('session'),'full-test-value')
                root.geometry('900x600+25+35');settle(root)
                app._pane_ratio=.32;app.save_settings()
                settings=json.loads((Path(temp)/'settings.json').read_text(encoding='utf-8'))
                self.assertIn('geometry',settings)
                self.assertEqual(settings['pane_ratio'],.32)
                self.assertNotIn('full-test-value',json.dumps(settings))
                self.assertEqual(bounded_geometry('2000x2000+9000+9000',(0,0,1024,728))[:2],(996,648))
            finally:
                cleanup(root)
            restored_root=tk.Tk();restored_root.attributes('-alpha',0)
            try:
                restored=Application(restored_root,temp,enable_updates=False)
                settle(restored_root)
                self.assertEqual((restored_root.winfo_width(),restored_root.winfo_height()),(900,600))
                self.assertEqual(restored._pane_ratio,.32)
            finally:
                cleanup(restored_root)


if __name__=='__main__':
    unittest.main()
