"""Shared academy e-mail shell; no delivery, credentials or token creation here."""
import os
import re
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

from jinja2 import Environment, FileSystemLoader, select_autoescape


DEFAULT_BASE = 'https://inscriptionsbts.onrender.com'
BRAND_MARKER = 'data-academy-email="v1"'
_environment = Environment(loader=FileSystemLoader(str(Path(__file__).with_name('templates'))),
                           autoescape=select_autoescape(('html', 'xml')))


def _absolute_url(value):
    value = str(value or '')
    parsed = urlsplit(value)
    if (parsed.scheme not in {'https', 'http'} or not parsed.hostname or parsed.username
            or parsed.password or any(ord(char) < 32 for char in value)):
        raise ValueError('An absolute HTTP(S) link is required.')
    return value


def academy_logo_url():
    try:
        base = _absolute_url(os.getenv('BASE_URL', DEFAULT_BASE)).rstrip('/')
    except ValueError:
        base = DEFAULT_BASE
    return base + '/static/academy-official-logo.png'


class _Fragment(HTMLParser):
    """Extract a safe legacy body without old document chrome or executable HTML."""
    VOID = {'br', 'hr', 'img', 'wbr', 'input', 'meta', 'link', 'source', 'area', 'base', 'embed', 'param', 'col'}
    BLOCKED = {'head', 'script', 'style', 'iframe', 'object', 'embed', 'form', 'button', 'input', 'textarea', 'select', 'svg'}
    ALLOWED = {'a','p','div','span','br','hr','strong','b','em','i','u','small','h1','h2','h3','h4',
               'table','tbody','thead','tfoot','tr','td','th','ul','ol','li','blockquote','img','pre','code','sup','sub'}
    STYLES = {
        'p': 'margin:0 0 18px;',
        'a': 'color:#7a5c25;text-decoration:underline;',
        'h1': 'font-family:Arial,Helvetica,sans-serif;font-size:25px;line-height:1.3;color:#29382e;margin:12px 0 20px;',
        'h2': 'font-family:Arial,Helvetica,sans-serif;font-size:22px;line-height:1.3;color:#29382e;margin:24px 0 14px;',
        'h3': 'font-family:Arial,Helvetica,sans-serif;font-size:18px;line-height:1.4;color:#29382e;margin:24px 0 12px;',
        'li': 'margin-bottom:8px;',
    }

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.stack = [], []
        self.blocked = 0

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        classes = values.get('class') or ''
        is_blocked = tag in self.BLOCKED or (tag in {'div', 'header', 'footer'} and classes in {'header', 'footer'})
        hidden = bool(self.blocked) or is_blocked
        if tag not in self.VOID:
            self.stack.append((tag, hidden, is_blocked))
        if is_blocked and tag not in self.VOID:
            self.blocked += 1
        if hidden or tag not in self.ALLOWED:
            return
        clean = []
        for key, value in attrs:
            if value is None or key.lower().startswith('on') or key not in {
                'href','src','alt','width','height','colspan','rowspan','align','valign','cellpadding','cellspacing','border','style','class','target','role'}:
                continue
            if key in {'href', 'src'}:
                compact = re.sub(r'\s+', '', value).lower()
                if compact.startswith(('javascript:', 'data:', 'vbscript:')) or value.startswith('//'):
                    continue
            if key == 'style' and re.search(r'url\s*\(|expression\s*\(|behavior\s*:', value, re.I):
                continue
            if key != 'style':
                clean.append((key, value))
        style = self.STYLES.get(tag, '') + (values.get('style') or '')
        if re.search(r'url\s*\(|expression\s*\(|behavior\s*:', style, re.I):
            style = self.STYLES.get(tag, '')
        # Retain the information hierarchy of historical cards in the academy palette.
        palette = {'#f3f7ff':'#eef2eb', '#2b6cff':'#647955', '#fef8e1':'#f4efdf',
                   '#f5dd9b':'#dfcfac', '#f4c45a':'#d6b46d'}
        style = re.sub(r'#[0-9a-fA-F]{6}', lambda match: palette.get(match.group(0).lower(), match.group(0)), style)
        if tag == 'a' and ('btn' in classes.split() or 'button' in classes.split()):
            style += ';display:inline-block;background:#d6b46d;color:#202722;text-decoration:none;font-family:Arial,Helvetica,sans-serif;font-weight:700;padding:15px 23px;border-radius:8px;margin:12px 0;mso-padding-alt:15px 23px;'
        if style:
            clean.append(('style', style))
        attributes = ''.join(f' {key}="{escape(value, quote=True)}"' for key, value in clean)
        self.parts.append('<' + tag + attributes + '>')

    def handle_endtag(self, tag):
        if tag in self.VOID:
            return
        index = next((i for i in range(len(self.stack)-1, -1, -1) if self.stack[i][0] == tag), None)
        if index is None:
            return
        for current, hidden, blocked in reversed(self.stack[index:]):
            if blocked:
                self.blocked -= 1
            if not hidden and current in self.ALLOWED:
                self.parts.append('</' + current + '>')
        del self.stack[index:]

    def handle_data(self, data):
        if not self.blocked:
            self.parts.append(escape(data))


def style_email_content(content):
    parser = _Fragment()
    parser.feed(str(content or ''))
    parser.close()
    while parser.stack:
        parser.handle_endtag(parser.stack[-1][0])
    return ''.join(parser.parts)


def render_branded_email(title, content_html, *, eyebrow='INTÉGRALE ACADEMY · À VOS CÔTÉS',
                         accent_title='À vous de jouer.', preview_text='', action_url=None,
                         action_label=None, security_note=None):
    """Content is HTML; all titles, notes and action values are escaped by Jinja."""
    if action_url:
        action_url = _absolute_url(action_url)
    return _environment.get_template('email_base.html').render(
        email_title=title, email_content=style_email_content(content_html), email_eyebrow=eyebrow,
        accent_title=accent_title, preview_text=preview_text or title, action_url=action_url,
        action_label=action_label, security_note=security_note, official_logo_url=academy_logo_url())


def brand_existing_email(subject, html):
    """Give legacy fragments a shell; already branded messages are never nested."""
    source = str(html or '')
    if re.search(r'<body\b[^>]*\bdata-academy-email=[\"\']v1[\"\']', source, re.I):
        return source
    return render_branded_email(subject, source)


class _PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.ignored, self.links = [], 0, []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag in {'head','style','script'}:
            self.ignored += 1
        if self.ignored:
            return
        if tag in {'p','div','tr','li','h1','h2','h3','br'}:
            self.parts.append('\n')
        if tag == 'a':
            self.links.append(values.get('href') or '')
        if tag == 'img' and values.get('alt'):
            self.parts.append(values['alt'])

    def handle_endtag(self, tag):
        if tag in {'head','style','script'}:
            self.ignored = max(0, self.ignored-1)
            return
        if self.ignored:
            return
        if tag == 'a' and self.links:
            link = self.links.pop()
            if link.startswith(('https://','http://')):
                self.parts.append(' (' + link + ')')
        if tag in {'p','div','tr','li','h1','h2','h3'}:
            self.parts.append('\n')

    def handle_data(self, value):
        if not self.ignored:
            self.parts.append(value)


def email_plain_text(html):
    parser = _PlainText()
    parser.feed(str(html or ''))
    parser.close()
    lines = [re.sub(r'[ \t\xa0]+', ' ', line).strip() for line in ''.join(parser.parts).splitlines()]
    return re.sub(r'\n{3,}', '\n\n', '\n'.join(lines)).strip()
