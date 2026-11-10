"""Desktop service layer. Credentials and signed URLs remain in memory."""
import json
import re
import threading
from pathlib import Path
from urllib.parse import urlparse

import requests
import decode


class Cancelled(Exception):
    pass


class LoginExpired(Exception):
    pass


def check_cancel(stop):
    if stop.is_set():
        raise Cancelled()


def parse_cookies(raw):
    from .cookies import extract_cookies
    return extract_cookies(raw).jar


class Client:
    def __init__(self, raw, stop=None):
        self.stop = stop or threading.Event()
        self.session = requests.Session()
        self.session.headers.update(decode.HEADERS)
        self.session.cookies.update(parse_cookies(raw))

    def close(self):
        self.session.close()

    def json(self, path, **kwargs):
        check_cancel(self.stop)
        with self.session.get(decode.BASE + path, timeout=(10, 20), **kwargs) as r:
            if r.status_code == 401 or '/login' in r.url:
                raise LoginExpired('登录已失效，请更新 Cookie 后重试未完成任务。')
            r.raise_for_status()
            if 'text/html' in r.headers.get('Content-Type', ''):
                raise LoginExpired('接口返回登录页面，请重新复制 Cookie。')
            data = r.json()
            if not isinstance(data, dict):
                raise ValueError('服务器数据格式发生变化。')
            return data

    def courses(self):
        result, seen, page = [], set(), 1
        while True:
            data = self.json('/api/my-courses', params={'page': page, 'page_size': 20})
            rows = data.get('courses')
            if not isinstance(rows, list):
                raise LoginExpired('无法取得课程列表，请检查 Cookie。')
            new = [c for c in rows if c['id'] not in seen]
            if rows and not new:
                raise ValueError('课程分页返回重复内容。')
            result.extend(new)
            seen.update(c['id'] for c in new)
            if not rows or page >= int(data.get('pages') or page):
                return result
            page += 1

    def files(self, course_id):
        rows, seen, page, activity_ids = [], set(), 1, set()
        conditions = {'category': None, 'class_ids': [], 'itemsSortBy': {'predicate': 'chapter', 'reverse': False}, 'ignore_activity_types': ['lesson']}
        while True:
            data = self.json(f'/api/course/{course_id}/coursewares', params={
                'conditions': json.dumps(conditions), 'page': page, 'page_size': 20})
            activities = data.get('activities')
            if not isinstance(activities, list):
                raise ValueError('无法读取课件列表。')
            new = {a['id'] for a in activities} - activity_ids
            if activities and not new:
                raise ValueError('课件分页返回重复内容。')
            activity_ids.update(new)
            for a in activities:
                for u in a.get('uploads', []):
                    if u['id'] not in seen and not u.get('deleted'):
                        seen.add(u['id'])
                        rows.append(dict(u, activity_title=a.get('title', '')))
            if not activities or page >= int(data.get('pages') or page):
                return list(decode.unique_uploads(rows))
            page += 1

    def download(self, upload, folder, progress):
        pdf = upload['name'].lower().endswith('.pdf')
        if upload.get('allow_download'):
            try:
                return self.transfer(f"{decode.BASE}/api/uploads/{upload['id']}/blob", upload, folder, progress, upload.get('size'))
            except requests.HTTPError as exc:
                if exc.response.status_code not in (403, 404) or not pdf:
                    raise
        if not pdf:
            raise ValueError('当前账号无法下载此附件原件。')
        data = self.json(f"/api/uploads/document/{upload['id']}/url", params={'preview': 'true'})
        url = data.get('url')
        if not url or urlparse(url).scheme not in ('http', 'https'):
            raise ValueError('当前账号无法取得预览 PDF。')
        return self.transfer(url, upload, folder, progress, None)

    def transfer(self, url, upload, folder, progress, expected_size):
        check_cancel(self.stop)
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / decode.safe_filename(upload['name'])
        pdf = target.suffix.lower() == '.pdf'
        if target.exists():
            with target.open('rb') as f:
                valid = f.read(5) == b'%PDF-' if pdf else target.stat().st_size > 0
            # Original metadata is available even for most preview PDFs. A converted
            # preview of another size is conservatively left for manual resolution.
            known_size = expected_size if expected_size is not None else upload.get('size')
            if valid and known_size and target.stat().st_size == known_size:
                return '已跳过', target
            raise ValueError('同名文件已存在但无法确认完整，请移走该文件后重试。')
        part = target.with_name(target.name + '.part')
        if part.exists():
            raise ValueError('发现同名临时文件，请确认没有其他下载程序运行后移走它。')
        created = False
        try:
            with self.session.get(url, stream=True, timeout=(10, 15)) as r:
                if r.status_code == 401 or '/login' in r.url:
                    raise LoginExpired('登录已失效，请更新 Cookie。')
                r.raise_for_status()
                content_type = r.headers.get('Content-Type', '').lower()
                if 'text/html' in content_type:
                    raise ValueError('服务器返回网页，未保存为课件。')
                length = int(r.headers.get('Content-Length') or 0)
                total = length if not r.headers.get('Content-Encoding') else 0
                received = 0
                with part.open('xb') as f:
                    created = True
                    for chunk in r.iter_content(128 * 1024):
                        check_cancel(self.stop)
                        if not chunk:
                            continue
                        if received == 0 and pdf and not chunk.startswith(b'%PDF-'):
                            raise ValueError('返回的内容不是 PDF 文件。')
                        f.write(chunk)
                        received += len(chunk)
                        progress(received, total)
                check_cancel(self.stop)
                if received == 0 or (total and received != total) or (expected_size is not None and received != expected_size):
                    raise ValueError('文件大小校验失败，请重试。')
                # Path.rename does not overwrite an existing target on Windows.
                part.rename(target)
                return '已完成', target
        finally:
            if created:
                part.unlink(missing_ok=True)


def friendly_error(exc):
    if isinstance(exc, LoginExpired):
        return str(exc)
    if isinstance(exc, requests.Timeout):
        return '网络请求超时，请检查网络后重试。'
    if isinstance(exc, requests.ConnectionError):
        return '无法连接服务器，请检查网络或校园访问条件。'
    if isinstance(exc, requests.HTTPError):
        return f'服务器拒绝请求或暂不可用（HTTP {exc.response.status_code}）。'
    if isinstance(exc, OSError):
        return '无法写入文件，请检查目录权限、磁盘空间或文件是否被占用。'
    if isinstance(exc, requests.RequestException):
        return '下载请求无法完成，请重新连接后重试。'
    if isinstance(exc, ValueError):
        return str(exc) if not isinstance(exc, requests.exceptions.JSONDecodeError) else '服务器返回了无法解析的数据。'
    return '操作未完成，请重试或重新连接。'
