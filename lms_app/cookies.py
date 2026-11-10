"""Conservative extraction of Cookie exports embedded in copied page text."""
import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urlparse
import requests

LOGIN = {'session', 'role_token'}
NAME = re.compile(r"[!#$%&'*+.^_`|~0-9a-zA-Z-]+\Z")
DOMAIN = re.compile(r'\.?[\w.-]+\.[a-zA-Z]{2,}\Z')


@dataclass(repr=False)
class CookieResult:
    jar: requests.cookies.RequestsCookieJar
    format: str
    names: tuple

    def normalized(self):
        return json.dumps({'cookies': [{'name': c.name, 'value': c.value, 'domain': c.domain, 'path': c.path} for c in self.jar]})

    @property
    def summary(self):
        return f'已识别：{self.format}；登录项 '+ '、'.join(n for n in self.names if n in LOGIN)+'。尚需服务器验证。'


class VisibleText(HTMLParser):
    def __init__(self, raw):
        super().__init__(convert_charrefs=True)
        self.parts, self.skip = [], 0
        self.feed(raw)

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.skip += 1
        if not self.skip and tag in ('tr', 'div', 'p', 'br', 'li'):
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.skip = max(0, self.skip-1)
        if not self.skip:
            if tag in ('td', 'th'):
                self.parts.append('\t')
            elif tag in ('tr', 'div', 'p', 'li'):
                self.parts.append('\n')

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def extract_cookies(raw):
    raw = raw.strip().lstrip('\ufeff')
    if not raw:
        raise ValueError('请粘贴 Cookie，或粘贴包含 Cookie 表格/请求头的整段文本。')
    if len(raw) > 2_000_000:
        raise ValueError('文本过大，请仅复制 Cookie 表格或请求头。')
    hosts = re.findall(r'(?im)^\s*(?:Host|:authority)\s*:\s*([\w.-]+)(?::\d+)?\s*$',raw)
    request_urls = re.findall(r'''(?im)(?:^\s*(?:Request URL|请求网址|请求 URL)\s*:\s*|\bcurl\s+['"]?)(https?://[^\s'"<>]+)''',raw)
    hosts.extend(urlparse(u).hostname for u in request_urls)
    if any(host and host.lower()!='lms.nju.edu.cn' for host in hosts):
        raise ValueError('请求来自其他网站，请复制 lms.nju.edu.cn 的 Cookie。')
    html = bool(re.search(r'<(?:html|body|table|tr|td|div|span|p)\b', raw, re.I))
    text = ''.join(VisibleText(raw).parts) if html else raw
    candidates, blocked, invalid = {}, set(), set()

    def add(name, value, domain='lms.nju.edu.cn', path='/'):
        if not isinstance(name, str) or not isinstance(value, str) or not NAME.fullmatch(name.strip()):
            return
        name, value = name.strip(), value.strip().strip('"\'')
        if not re.fullmatch(r'(?:[a-z0-9-]+\.)*nju\.edu\.cn', str(domain).lower().lstrip('.')):
            if name in LOGIN:
                blocked.add(name)
            return
        if not value or any(c in value for c in ('…', '...', '示例', '完整值', '这里替换', '你的完整')) or not re.fullmatch(r'[\x21-\x7e]+', value) or any(c in value for c in ';"\\'):
            if name in LOGIN:
                invalid.add(name)
            return
        key = (name, str(domain).lower(), str(path or '/'))
        if key in candidates and candidates[key] != value:
            raise ValueError(f'发现多份不同的 {name} 值，请仅保留当前学校登录的那一份。')
        candidates[key] = value

    def done(fmt):
        if invalid:
            raise ValueError('登录项 '+ '、'.join(sorted(invalid))+' 含省略号、示例文字或不完整内容，请从 Cookie Value 复制完整值。')
        if not any(k[0] in LOGIN for k in candidates):
            return None
        jar = requests.cookies.RequestsCookieJar()
        for (name, domain, path), value in candidates.items():
            jar.set(name, value, domain=domain, path=path)
        return CookieResult(jar, fmt, tuple(sorted({c.name for c in jar})))

    def json_cookies(obj, depth=0):
        if depth > 5:
            return
        if isinstance(obj, list):
            for item in obj:
                json_cookies(item, depth+1)
        elif isinstance(obj, dict):
            if 'name' in obj and 'value' in obj:
                add(obj['name'], obj['value'], obj.get('domain', 'lms.nju.edu.cn'), obj.get('path', '/'))
            elif any(n in obj for n in LOGIN):
                for name in LOGIN & obj.keys():
                    add(name, obj[name], obj.get('domain', 'lms.nju.edu.cn'))
            elif 'cookies' in obj:
                json_cookies(obj['cookies'], depth+1)
    try:
        json_cookies(json.loads(text))
    except (json.JSONDecodeError, TypeError):
        decoder = json.JSONDecoder()
        for match in list(re.finditer(r'[\[{]', text))[:40]:
            try:
                obj, _ = decoder.raw_decode(text, match.start())
                json_cookies(obj)
            except (json.JSONDecodeError, TypeError):
                continue
    result = done('JSON / 文本中的 Cookie JSON')
    if result:
        return result
    if blocked:
        raise ValueError('找到的登录项属于其他网站，请选择 lms.nju.edu.cn 的 Cookie。')
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in lines:
        if line.startswith('#HttpOnly_'):
            line = line[len('#HttpOnly_'):]
        elif line.startswith('#'):
            continue
        fields = line.split('\t')
        if len(fields) == 7 and fields[1] in ('TRUE', 'FALSE'):
            add(fields[5], fields[6], fields[0], fields[2])
        elif len(fields) >= 3 and DOMAIN.fullmatch(fields[2].strip()):
            add(fields[0], fields[1], fields[2].strip(), fields[3] if len(fields)>3 else '/')
        elif re.match(r'^(session|role_token)\s+', line):
            fields = re.split(r'\s+', line)
            if len(fields) >= 3 and DOMAIN.fullmatch(fields[2]):
                add(fields[0], fields[1], fields[2], fields[3] if len(fields)>3 and fields[3].startswith('/') else '/')
    result = done('Cookie 表格 / Netscape'+('（从 HTML 提取）' if html else ''))
    if result:
        return result
    if blocked:
        raise ValueError('找到的登录项属于其他网站，请选择 lms.nju.edu.cn 的 Cookie。')
    pattern = r'''(?<![\w-])["']?(session|role_token)["']?\s*[:=]\s*(?:"([^"\r\n]*)"|'([^'\r\n]*)'|([^\s;<>"']+))'''
    for match in re.finditer(pattern, text):
        add(match[1], next(v for v in match.groups()[1:] if v is not None))
    result = done('Cookie 请求头 / 混合文本')
    if result:
        return result
    for i, line in enumerate(lines):
        if line in LOGIN and i+1 < len(lines):
            domain = next((s for s in lines[i+2:i+6] if DOMAIN.fullmatch(s)), None)
            if domain:
                add(line, lines[i+1], domain)
    result = done('按行复制的 Cookie 表格')
    if result:
        return result
    if blocked:
        raise ValueError('找到的登录项属于其他网站，请复制学校域名的 Cookie。')
    raise ValueError('未找到完整的 session 或 role_token。请复制 Cookie 表格或“名称=值”；仅有页面正文、Cookie Value 单值或截图不能识别。')
