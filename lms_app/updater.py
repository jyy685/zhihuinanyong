"""Read public GitHub releases. No credentials, installation or code execution."""
import re
from urllib.parse import urlparse

import requests

REPOSITORY = 'jyy685/zhihuinanyong'
RELEASES_URL = f'https://github.com/{REPOSITORY}/releases'
API_URL = f'https://api.github.com/repos/{REPOSITORY}/releases/latest'


def version_tuple(value):
    match = re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)', str(value).strip())
    if not match:
        raise ValueError('版本号格式无法识别。')
    return tuple(int(x) for x in match.groups())


def trusted_release_url(url):
    p = urlparse(url or '')
    return p.scheme == 'https' and p.netloc == 'github.com' and p.path.startswith(f'/{REPOSITORY}/releases/')


def check_latest(current_version, session=None):
    own_session = session is None
    session = session or requests.Session()
    try:
        with session.get(API_URL, timeout=(5, 10), headers={
            'Accept': 'application/vnd.github+json', 'User-Agent': 'ZhihuiNanyong-Updater'}) as response:
            if response.status_code == 404:
                return {'state': 'no_release', 'message': '仓库尚未发布正式版本。', 'url': RELEASES_URL}
            response.raise_for_status()
            release = response.json()
        if not isinstance(release, dict) or release.get('draft') or release.get('prerelease'):
            raise ValueError('没有可用的正式版本信息。')
        tag = release.get('tag_name', '')
        newer = version_tuple(tag) > version_tuple(current_version)
        page = release.get('html_url')
        if not trusted_release_url(page):
            raise ValueError('发布页面地址不符合预期。')
        asset = next((a.get('browser_download_url') for a in release.get('assets', [])
                      if a.get('name') == 'ZhihuiNanyong.exe' and trusted_release_url(a.get('browser_download_url'))
                      and urlparse(a['browser_download_url']).path.startswith(f'/{REPOSITORY}/releases/download/')), None)
        return {'state': 'available' if newer else 'current', 'version': tag.lstrip('v'),
                'url': page, 'download_url': asset,
                'notes': str(release.get('body') or '暂无更新说明。')[:8000],
                'message': f'发现新版本 {tag}。' if newer else f'当前已是最新版本（{current_version}）。'}
    except requests.HTTPError as exc:
        status = exc.response.status_code
        return {'state': 'error', 'message': 'GitHub 暂时限制了请求，请稍后手动检查。' if status in (403, 429) else '暂时无法读取版本信息，请稍后重试。'}
    except (requests.RequestException, ValueError, TypeError, KeyError, AttributeError):
        return {'state': 'error', 'message': '无法检查更新，请检查网络后重试。'}
    finally:
        if own_session:
            session.close()
