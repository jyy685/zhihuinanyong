"""Read public GitHub releases. No credentials, installation or code execution."""
import re
import time
from html.parser import HTMLParser
from urllib.parse import urlparse, urljoin, unquote, quote

import requests

REPOSITORY = 'jyy685/zhihuinanyong'
RELEASES_URL = f'https://github.com/{REPOSITORY}/releases'
API_URL = f'https://api.github.com/repos/{REPOSITORY}/releases/latest'
_api_retry_at = 0.0


class ReleasePage(HTMLParser):
    def __init__(self, content):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.text = []
        self.feed(content)

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.links.extend(value for key, value in attrs if key == 'href' and value)

    def handle_data(self, data):
        self.text.append(data)


def no_release(source):
    return {'state': 'no_release', 'message': '仓库尚未发布正式版本；源码提交和构建文件不属于 Release。',
            'url': RELEASES_URL, 'source': source}


def release_result(current_version, tag, page, asset=None, notes=None, source='github_api'):
    newer = version_tuple(tag) > version_tuple(current_version)
    if not trusted_release_url(page):
        raise ValueError('发布页面地址不符合预期。')
    return {'state': 'available' if newer else 'current', 'version': tag.lstrip('v'),
            'url': page, 'download_url': asset, 'notes': str(notes or '详情请查看 GitHub 发布页面。')[:8000],
            'source': source,
            'message': f'发现新版本 {tag}。' if newer else f'当前已是最新版本（{current_version}）。'}


def valid_asset(url):
    return trusted_release_url(url) and urlparse(url).path.startswith(f'/{REPOSITORY}/releases/download/') and unquote(urlparse(url).path).endswith('/ZhihuiNanyong.exe')


def check_release_page(current_version, session):
    """Public HTML fallback, independent of anonymous REST API quotas."""
    with session.get(RELEASES_URL+'/latest', timeout=(5, 10), headers={
        'Accept': 'text/html', 'Accept-Language': 'en-US,en;q=0.9', 'User-Agent': 'ZhihuiNanyong-Updater'}) as response:
        response.raise_for_status()
        final = response.url
        p = urlparse(final)
        if not trusted_release_url(final) and final.rstrip('/') != RELEASES_URL:
            raise ValueError('更新页面发生了非预期跳转。')
        page = ReleasePage(response.text)
    if p.path.rstrip('/') == f'/{REPOSITORY}/releases':
        text = re.sub(r'\s+', ' ', ' '.join(page.text)).replace('\u2019', "'").replace('\u2018', "'")
        if "there aren't any releases here" in text.lower():
            return no_release('github_web')
        raise ValueError('无法确认仓库是否有正式发布。')
    prefix = f'/{REPOSITORY}/releases/tag/'
    if not p.path.startswith(prefix):
        raise ValueError('没有可验证的版本标签。')
    tag = unquote(p.path[len(prefix):])
    version_tuple(tag)

    def find_asset(links):
        return next((urljoin('https://github.com', href) for href in links
                     if valid_asset(urljoin('https://github.com', href))), None)
    asset = find_asset(page.links)
    if not asset:
        try:
            # GitHub loads release assets in an HTML fragment. If that fragment is
            # unavailable the validated release page remains a usable update link.
            fragment_url = f'https://github.com/{REPOSITORY}/releases/expanded_assets/{quote(tag, safe="")}'
            with session.get(fragment_url, timeout=(5, 8), headers={'Accept': 'text/html'}) as fragment:
                fragment.raise_for_status()
                if trusted_release_url(fragment.url):
                    asset = find_asset(ReleasePage(fragment.text).links)
        except (requests.RequestException, ValueError):
            pass
    return release_result(current_version, tag, final, asset, source='github_web')


def version_tuple(value):
    match = re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)', str(value).strip())
    if not match:
        raise ValueError('版本号格式无法识别。')
    return tuple(int(x) for x in match.groups())


def trusted_release_url(url):
    p = urlparse(url or '')
    return p.scheme == 'https' and p.netloc == 'github.com' and p.path.startswith(f'/{REPOSITORY}/releases/')


class ApiUnavailable(Exception):
    pass


def check_api(current_version, session, remember_backoff):
    global _api_retry_at
    api_failure = None
    try:
        with session.get(API_URL, timeout=(5, 10), headers={
            'Accept': 'application/vnd.github+json', 'User-Agent': 'ZhihuiNanyong-Updater'}) as response:
            if response.status_code == 404:
                return no_release('github_api')
            if response.status_code in (403, 429):
                limited = response.headers.get('X-RateLimit-Remaining') == '0' or response.status_code == 429 or bool(response.headers.get('Retry-After'))
                if limited:
                    api_failure = 'GitHub API 的请求额度已用尽或暂时限流'
                    if remember_backoff:
                        now = time.time()
                        try:
                            reset = float(response.headers.get('X-RateLimit-Reset') or 0)
                            wait = float(response.headers.get('Retry-After') or 60)
                            _api_retry_at = min(now+3600, max(now+60, reset, now+wait))
                        except (ValueError, TypeError):
                            _api_retry_at = now+60
                else:
                    api_failure = 'GitHub API 拒绝了当前请求（HTTP 403）'
            response.raise_for_status()
            release = response.json()
        if not isinstance(release, dict) or release.get('draft') or release.get('prerelease'):
            raise ValueError('没有可用的正式版本信息。')
        tag = release.get('tag_name', '')
        page = release.get('html_url')
        if not trusted_release_url(page):
            raise ValueError('发布页面地址不符合预期。')
        asset = next((a.get('browser_download_url') for a in release.get('assets', [])
                      if a.get('name') == 'ZhihuiNanyong.exe' and valid_asset(a.get('browser_download_url'))), None)
        return release_result(current_version, tag, page, asset, release.get('body'))
    except requests.HTTPError as exc:
        api_failure = api_failure or f'GitHub API 返回 HTTP {exc.response.status_code}'
    except requests.RequestException:
        api_failure = 'GitHub API 网络连接失败'
    except (ValueError, TypeError, KeyError, AttributeError):
        api_failure = 'GitHub API 未返回可验证的正式版本信息'
    raise ApiUnavailable(api_failure)


def check_latest(current_version, session=None):
    own_session = session is None
    session = session or requests.Session()
    try:
        reason = 'GitHub API 的请求额度尚未恢复'
        if not own_session or time.time() >= _api_retry_at:
            try:
                return check_api(current_version, session, remember_backoff=own_session)
            except ApiUnavailable as exc:
                reason = str(exc)
        try:
            return check_release_page(current_version, session)
        except (requests.RequestException, ValueError, TypeError, KeyError, AttributeError):
            return {'state': 'error', 'message': f'{reason}，发布页面备用检查也未成功。可稍后重试，或在浏览器打开项目的 Releases 页面。', 'url': RELEASES_URL}
    finally:
        if own_session:
            session.close()
