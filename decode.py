"""智慧南雍课件下载工具：自动探测课程，按课程和课件编号选择下载。"""
import argparse
import http.cookiejar
import json
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse
import requests

ROOT = Path(__file__).resolve().parent
BASE = 'https://lms.nju.edu.cn'
DOWNLOAD_DIR = ROOT / 'downloads'
HEADERS = {'User-Agent': 'Mozilla/5.0', 'Referer': BASE + '/'}


def load_cookies(session, filename):
    path = Path(filename)
    if not path.exists():
        return
    raw = path.read_text(encoding='utf-8-sig').strip()
    if raw.startswith(('[', '{')):
        data = json.loads(raw)
        if isinstance(data, dict):
            data = data.get('cookies', data)
        if isinstance(data, dict):
            data = [dict(name=k, value=v) for k, v in data.items()]
        for c in data:
            session.cookies.set(c['name'], c['value'], domain=c.get('domain', 'lms.nju.edu.cn'), path=c.get('path', '/'))
    elif 'Netscape HTTP Cookie File' in raw or any(
        len(line.split('\t')) == 7 and line.split('\t')[1] in ('TRUE', 'FALSE')
        for line in raw.splitlines() if not line.startswith('#')
    ):
        jar = http.cookiejar.MozillaCookieJar(str(path))
        jar.load(ignore_discard=True, ignore_expires=True)
        session.cookies.update(jar)
    elif '\t' in raw:
        for line in raw.splitlines():
            c = line.split('\t')
            if len(c) >= 4 and (c[2].lstrip('.') == 'nju.edu.cn' or c[2].endswith('.nju.edu.cn')):
                session.cookies.set(c[0], c[1], domain=c[2], path=c[3] or '/')
    else:
        for item in re.sub(r'^Cookie:\s*', '', raw, flags=re.I).split(';'):
            if '=' in item:
                k, v = item.strip().split('=', 1)
                session.cookies.set(k, v, domain='lms.nju.edu.cn', path='/')


def decode_lms_url(url):
    # parse_qs 已完成一层解码，避免再解码导致签名损坏。
    return parse_qs(urlparse(url).query).get('file', [None])[0]


def get_original_filename(url):
    p = urlparse(url)
    return parse_qs(p.query).get('name', [None])[0] or unquote(p.path.rsplit('/', 1)[-1]) or 'document.pdf'


def safe_filename(name):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name).strip().rstrip('. ') or 'document.pdf'
    if re.fullmatch(r'CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9]', name.split('.')[0], re.I):
        name = '_' + name
    return name


def api_json(session, path, **kwargs):
    r = session.get(BASE + path, timeout=30, **kwargs)
    r.raise_for_status()
    try:
        return r.json()
    except ValueError:
        raise RuntimeError('接口未返回数据，请更新 cookie.txt 中的登录状态。') from None


def course_files(session, course_id, pdf_only=True):
    seen, seen_activities = set(), set()
    page = 1
    conditions = {'category': None, 'class_ids': [], 'itemsSortBy': {'predicate': 'chapter', 'reverse': False}, 'ignore_activity_types': ['lesson']}
    while True:
        data = api_json(session, f'/api/course/{course_id}/coursewares', params={
            'conditions': json.dumps(conditions), 'page': page, 'page_size': 20})
        activities = data.get('activities')
        if not isinstance(activities, list):
            raise RuntimeError('课件列表不可用，请确认登录状态和课程访问权限。')
        new = {a['id'] for a in activities} - seen_activities
        if activities and not new:
            raise RuntimeError('分页没有返回新内容，已停止重复请求。')
        seen_activities.update(new)
        for a in activities:
            for u in a.get('uploads', []):
                if u['id'] not in seen and not u.get('deleted') and (not pdf_only or u.get('name', '').lower().endswith('.pdf')):
                    seen.add(u['id'])
                    yield dict(u, activity_title=a.get('title', ''))
        if not activities or page >= int(data.get('pages') or page):
            break
        page += 1


def download_pdf(real_url, save_dir, session=None, filename=None, expected_size=None, expect_pdf=True):
    session = session or requests.Session()
    target = Path(save_dir) / safe_filename(filename or get_original_filename(real_url))
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        with target.open('rb') as f:
            valid = f.read(5) == b'%PDF-' if expect_pdf else target.stat().st_size > 0
        if valid and (expected_size is None or target.stat().st_size == expected_size):
            print(f'已存在：{target.name}', flush=True)
            return target
        raise RuntimeError(f'已有文件不完整或大小不同，请先移走：{target.name}')
    partial = target.with_name(target.name + '.part')
    try:
        with session.get(real_url, headers=HEADERS, stream=True, timeout=(15, 90)) as r:
            r.raise_for_status()
            chunks = r.iter_content(1024 * 1024)
            first = next(chunks, b'')
            if expect_pdf and not first.startswith(b'%PDF-'):
                raise RuntimeError('服务器没有返回 PDF，请检查登录状态和文件权限。')
            if not expect_pdf and ('text/html' in r.headers.get('Content-Type', '') or not first):
                raise RuntimeError('服务器返回了网页或空文件，未保存。')
            with partial.open('wb') as f:
                f.write(first)
                for chunk in chunks:
                    f.write(chunk)
            length = r.headers.get('Content-Length')
            size = partial.stat().st_size
            if expected_size is not None and size != expected_size:
                raise RuntimeError('下载大小与课件列表不一致。')
            if length and not r.headers.get('Content-Encoding') and size != int(length):
                raise RuntimeError('文件下载不完整。')
        partial.replace(target)
        print(f'下载完成：{target.name}（{size:,} 字节）', flush=True)
        return target
    finally:
        partial.unlink(missing_ok=True)


def download_upload(session, upload, directory):
    # 允许下载的课件先走原件接口；其他课件使用当前账号可访问的预览 PDF。
    if upload.get('allow_download'):
        try:
            return download_pdf(f"{BASE}/api/uploads/{upload['id']}/blob", directory, session, upload['name'], upload.get('size'),
                                expect_pdf=upload['name'].lower().endswith('.pdf'))
        except requests.HTTPError as exc:
            if exc.response.status_code not in (403, 404):
                raise
    if not upload['name'].lower().endswith('.pdf'):
        raise RuntimeError('非 PDF 课件当前无法下载原件。')
    data = api_json(session, f"/api/uploads/document/{upload['id']}/url", params={'preview': 'true'})
    url = data.get('url')
    if not url or urlparse(url).scheme not in ('http', 'https'):
        raise RuntimeError('当前账号无法取得预览 PDF。')
    # 预览可能为转换版本，不能用原件大小判断；仍验证响应长度和 PDF 文件头。
    return download_pdf(url, directory, session, upload['name'])


def my_courses(session):
    page, seen = 1, set()
    while True:
        data = api_json(session, '/api/my-courses', params={'page': page, 'page_size': 20})
        courses = data.get('courses')
        if not isinstance(courses, list):
            raise RuntimeError('无法读取课程列表，请更新 cookie.txt。')
        new = [c for c in courses if c['id'] not in seen]
        if courses and not new:
            raise RuntimeError('课程分页重复，已停止探测。')
        for c in new:
            seen.add(c['id'])
            yield c
        if not courses or page >= int(data.get('pages') or page):
            return
        page += 1


def parse_selection(text, count):
    """把 1,3-5 / all 转换为去重且保持显示顺序的零基索引。"""
    text = text.strip().lower()
    if text in ('q', 'quit', '退出', ''):
        return []
    if text in ('all', 'a', '*', '全部'):
        return list(range(count))
    selected = set()
    for part in re.split(r'[,，\s]+', text):
        if not re.fullmatch(r'\d+(?:-\d+)?', part):
            raise ValueError('请输入编号、范围（如 1,3-5）、all 或 q。')
        ends = [int(x) for x in part.split('-')]
        start, end = ends[0], ends[-1]
        if start < 1 or end > count or start > end:
            raise ValueError(f'编号需在 1–{count} 内，范围起点不能大于终点。')
        selected.update(range(start - 1, end))
    return sorted(selected)


def ask_selection(prompt, count):
    while True:
        try:
            return parse_selection(input(prompt), count)
        except EOFError:
            return []
        except ValueError as exc:
            print(exc)


def unique_uploads(files):
    files = list(files)
    names = [safe_filename(u['name']).casefold() for u in files]
    for i, original in enumerate(files):
        u = dict(original)
        if names.count(names[i]) > 1:
            p = Path(u['name'])
            u['name'] = f"{p.stem}_{u['id']}{p.suffix}"
        yield u


def browse_courses(session, args):
    # 访问与浏览器相同的课程入口，再读取该页面使用的分页接口。
    response = session.get(BASE + '/user/courses', timeout=30)
    response.raise_for_status()
    courses = list(my_courses(session))
    print(f'发现 {len(courses)} 门课程，正在探测课件……', flush=True)
    catalog = []
    for i, course in enumerate(courses, 1):
        entry = {'number': i, 'id': course['id'], 'name': course['name'], 'files': [], 'error': None}
        print(f"\n[{i}] {course['name']}（课程 ID：{course['id']}）", flush=True)
        try:
            entry['files'] = list(unique_uploads(course_files(session, course['id'], pdf_only=False)))
            for j, u in enumerate(entry['files'], 1):
                mode = '原件' if u.get('allow_download') else ('预览 PDF' if u['name'].lower().endswith('.pdf') else '原件不可下载')
                print(f"  {j}. {u['name']} [{mode}] [{u.get('activity_title', '')}]", flush=True)
            if not entry['files']:
                print('  未探测到附件课件。')
        except (requests.RequestException, RuntimeError, ValueError):
            entry['error'] = '探测失败，请检查登录状态和课程权限后重试'
            print('  ' + entry['error'])
        catalog.append(entry)
    args.output.mkdir(parents=True, exist_ok=True)
    # 仅保存选择所需的信息，排除签名链接、Cookie 以及与下载无关的个人信息。
    report = [{**e, 'files': [{k: u.get(k) for k in ('id', 'name', 'size', 'allow_download', 'activity_title')} for u in e['files']]} for e in catalog]
    (args.output / 'catalog.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"\n探测结果：{args.output / 'catalog.json'}", flush=True)
    if args.list or not catalog:
        return int(any(e['error'] for e in catalog))
    print('选择支持：1,3-5；all 表示全部；q 或空行表示退出/跳过。')
    chosen = ask_selection('选择课程编号：', len(catalog))
    plan = []
    for index in chosen:
        course = catalog[index]
        if course['error'] or not course['files']:
            print(f"跳过：{course['name']}（无可选课件或探测失败）")
            continue
        print(f"\n{course['name']}：")
        for j, u in enumerate(course['files'], 1):
            print(f"  {j}. {u['name']}")
        selection = ask_selection('选择课件编号（all 下载此课程全部）：', len(course['files']))
        if args.limit:
            selection = selection[:args.limit]
        plan.extend((course, course['files'][j]) for j in selection)
    if not plan:
        print('未选择下载文件，已退出。')
        return 0
    success, failures = 0, []
    for course, upload in plan:
        print(f"下载 [{course['name']}] {upload['name']}", flush=True)
        try:
            download_upload(session, upload, args.output / str(course['id']))
            success += 1
        except (requests.RequestException, RuntimeError, OSError):
            failures.append({'course_id': course['id'], 'id': upload['id'], 'name': upload['name']})
            print('下载失败，已记录；继续处理下一份。', flush=True)
    (args.output / 'failed.json').write_text(json.dumps(failures, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'完成：成功/已存在 {success}，失败 {len(failures)}。')
    return int(bool(failures))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('urls', nargs='*', help='课程列表网址（默认）、单个课程网址、旧预览链接或 PDF 直链')
    parser.add_argument('--cookie', type=Path, default=ROOT / 'cookie.txt')
    parser.add_argument('--output', type=Path, default=DOWNLOAD_DIR)
    parser.add_argument('--list', action='store_true', help='仅探测并列出课件，不下载')
    parser.add_argument('--limit', type=int, default=0, help='最多处理几个文件；0 为全部')
    args = parser.parse_args()
    if args.limit < 0:
        parser.error('--limit 不能为负数')
    urls = args.urls
    if not urls:
        urls = [BASE + '/user/courses#/']
    failures, success = [], 0
    with requests.Session() as session:
        session.headers.update(HEADERS)
        load_cookies(session, args.cookie)
        if any(urlparse(u).hostname == 'lms.nju.edu.cn' and urlparse(u).path.rstrip('/') == '/user/courses' for u in urls):
            if len(urls) != 1:
                parser.error('课程选择模式请单独使用课程列表网址。')
            try:
                return browse_courses(session, args)
            except (requests.RequestException, RuntimeError, OSError, ValueError):
                print('无法探测课程，请检查网络和 cookie.txt 中的登录状态。')
                return 1
        for url in urls:
            course = re.search(r'/course/(\d+)(?:/|$)', urlparse(url).path)
            try:
                if course and urlparse(url).hostname == 'lms.nju.edu.cn':
                    files = list(course_files(session, course[1]))
                    # 避免同名课件覆盖。
                    names = [safe_filename(u['name']).casefold() for u in files]
                    for index, original in enumerate(files):
                        if args.limit and index >= args.limit:
                            break
                        u = dict(original)
                        if names.count(names[index]) > 1:
                            u['name'] = f"{Path(u['name']).stem}_{u['id']}.pdf"
                        mode = '原件' if u.get('allow_download') else '预览 PDF'
                        print(f"[{index + 1}/{len(files)}] [{mode}] {u['name']}", flush=True)
                        if args.list:
                            continue
                        try:
                            download_upload(session, u, args.output / course[1])
                            success += 1
                        except (requests.RequestException, RuntimeError, OSError):
                            failures.append({'id': u['id'], 'name': u['name']})
                            print('下载失败：请检查网络、登录状态或课件权限。', flush=True)
                elif not args.list:
                    real = decode_lms_url(url) or url
                    if urlparse(real).scheme not in ('http', 'https'):
                        raise RuntimeError('请输入完整的 http/https 网址。')
                    download_pdf(real, args.output, session)
                    success += 1
            except (requests.RequestException, RuntimeError, OSError, ValueError):
                failures.append({'course_id': course[1] if course else None})
                print('请求失败，请检查网络、cookie.txt 和课程权限。', flush=True)
    if not args.list:
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / 'failed.json').write_text(json.dumps(failures, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'完成：成功/已存在 {success}，失败 {len(failures)}。保存位置：{args.output.resolve()}')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
