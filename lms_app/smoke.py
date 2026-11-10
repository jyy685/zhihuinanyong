"""Offline diagnostic for the bundled GUI and its real worker/download path."""
import json
import tempfile
import threading
import time
import tkinter as tk
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import decode
from .gui import Application, resource


class FixtureHandler(BaseHTTPRequestHandler):
    payload = b'%PDF-1.7\n' + b'Offline diagnostic fixture\n' * 10000 + b'%%EOF\n'

    def log_message(self, *args):
        pass

    def do_GET(self):
        path = urlparse(self.path).path
        if path == '/api/my-courses':
            data = {'courses': [{'id': 101, 'name': '诊断课程 A', 'semester': {'name': '示例学期'}}, {'id': 102, 'name': '诊断课程 B'}], 'pages': 1}
        elif path.startswith('/api/course/'):
            cid = int(path.split('/')[3])
            data = {'activities': [{'id': cid, 'title': '诊断活动', 'uploads': [
                {'id': cid * 10, 'name': f'课件{cid}.pdf', 'size': len(self.payload), 'allow_download': False}
            ]}], 'pages': 1}
        elif path.startswith('/api/uploads/document/'):
            data = {'url': f'http://127.0.0.1:{self.server.server_port}/fixture.pdf'}
        elif path == '/fixture.pdf':
            self.send_response(200)
            self.send_header('Content-Type', 'application/pdf')
            self.send_header('Content-Length', str(len(self.payload)))
            self.end_headers()
            self.wfile.write(self.payload)
            return
        else:
            self.send_error(404)
            return
        payload = json.dumps(data).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def run(report_path):
    report = {'ok': False, 'checks': []}
    root = None
    server = ThreadingHTTPServer(('127.0.0.1', 0), FixtureHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    original_base = decode.BASE
    try:
        decode.BASE = f'http://127.0.0.1:{server.server_port}'
        with tempfile.TemporaryDirectory() as temp:
            root = tk.Tk()
            root.withdraw()
            app = Application(root, Path(temp) / 'settings')

            def wait_idle():
                deadline = time.monotonic() + 30
                while app.busy or not app.events.empty():
                    root.update()
                    if time.monotonic() > deadline:
                        raise AssertionError('GUI worker timed out')
                    time.sleep(.02)
                root.update()

            app.cookie_text.insert('1.0', 'session=offline-diagnostic')
            app.connect()
            wait_idle()
            assert app.connected and len(app.courses) == 2
            assert sum(len(c['_files']) for c in app.courses) == 2
            report['checks'].append('GUI authentication and course/file discovery with local fixture server')
            app.toggle_course('101')
            assert app.selected == {(101, 1010)}
            app.current = 102
            app.render_files()
            assert app.selected == {(101, 1010)}
            report['checks'].append('Cross-course selection remains stable')
            app.folder.set(str(Path(temp) / '中文 output'))
            app.download_selected()
            wait_idle()
            assert len(app.tasks) == 1 and app.tasks[0]['state'] == '已完成'
            target = Path(temp) / '中文 output' / '101' / '课件101.pdf'
            assert target.read_bytes() == FixtureHandler.payload
            assert not (Path(temp) / '中文 output' / '102').exists()
            report['checks'].append('Selected-only preview PDF download and Unicode output directory')
            app.retry_tasks()
            root.update()
            assert not app.busy
            app.download_selected()
            wait_idle()
            assert app.tasks[0]['state'] == '已跳过'
            report['checks'].append('Completed-file validation and skip')
            assert resource('docs/COOKIE_GUIDE.md').exists()
            app.help()
            root.update()
            guide = next(w for w in root.winfo_children() if isinstance(w, tk.Toplevel))
            text = next(w for w in guide.winfo_children() if isinstance(w, tk.Text)).get('1.0', 'end')
            assert 'Application' in text and 'Cookie Value' in text
            report['checks'].append('Bundled Application-panel Cookie help')
            settings = (Path(temp) / 'settings/settings.json').read_text(encoding='utf-8')
            task_report = (Path(temp) / 'settings/last_download.json').read_text(encoding='utf-8')
            assert 'offline-diagnostic' not in settings + task_report
            report['checks'].append('Settings and task records exclude credentials')
            report['ok'] = True
    except Exception as exc:
        report['error'] = type(exc).__name__ + ': ' + str(exc)
    finally:
        decode.BASE = original_base
        if root is not None:
            root.destroy()
        server.shutdown()
        server.server_close()
        Path(report_path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    if not report['ok']:
        raise SystemExit(1)
