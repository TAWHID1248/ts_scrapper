"""Crawling + email extraction. Adapted from email_scraper.py for in-process use."""

from __future__ import annotations

import logging
import re
import time
from collections import deque
from typing import Callable
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup


DEFAULT_USER_AGENT = (
    'Mozilla/5.0 (compatible; EmailScraperBot/1.0; +https://example.com/bot)'
)

EMAIL_RE = re.compile(
    r'(?<![A-Za-z0-9._%+\-])'
    r'([A-Za-z0-9][A-Za-z0-9._%+\-]*'
    r'@'
    r'[A-Za-z0-9][A-Za-z0-9.\-]*'
    r'\.[A-Za-z]{2,24})'
    r'(?![A-Za-z0-9._%+\-])'
)

OBFUSCATED_RE = re.compile(
    r'([A-Za-z0-9][A-Za-z0-9._%+\-]*)\s*'
    r'(?:\[at\]|\(at\)|\{at\}|\s+at\s+|&#64;)\s*'
    r'([A-Za-z0-9][A-Za-z0-9.\-]*)\s*'
    r'(?:\[dot\]|\(dot\)|\{dot\}|\s+dot\s+)\s*'
    r'([A-Za-z]{2,24})',
    re.IGNORECASE,
)

BAD_SUFFIXES = (
    '.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.ico',
    '.css', '.js', '.woff', '.woff2', '.ttf', '.otf', '.eot',
    '.pdf', '.zip', '.mp4', '.webm',
)

BAD_DOMAINS = {
    'example.com', 'example.org', 'example.net',
    'domain.com', 'yourdomain.com', 'mail.com',
    'test.com', 'foo.com', 'bar.com',
    'sentry.io', 'wixpress.com', 'u.nu',
    'email.com', 'yoursite.com', 'site.com',
}
BAD_LOCAL_PREFIXES = ('noreply', 'no-reply', 'donotreply', 'do-not-reply')

PRIORITY_PATH_HINTS = (
    'contact', 'about', 'team', 'staff', 'impressum', 'imprint',
    'legal', 'privacy', 'support', 'help', 'reach', 'connect',
)

SKIP_PATH_HINTS = (
    '/wp-content/', '/wp-includes/', '/assets/', '/static/',
    '/cdn-cgi/', '/feed/', '/rss', '.xml',
)

log = logging.getLogger(__name__)


def normalize_url(url: str) -> str:
    url = (url or '').strip()
    if not url:
        return ''
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    return url


def same_domain(url: str, root_netloc: str) -> bool:
    try:
        net = urlparse(url).netloc.lower()
    except ValueError:
        return False
    if not net:
        return False
    if net.startswith('www.'):
        net = net[4:]
    return net == root_netloc or net.endswith('.' + root_netloc)


def clean_email(raw: str) -> str | None:
    if not raw:
        return None
    email = raw.strip().strip('.,;:()[]<>"\'').lower()
    email = email.replace('%40', '@').replace('&#64;', '@')
    if email.count('@') != 1:
        return None
    local, _, domain = email.partition('@')
    if not local or not domain:
        return None
    if email.endswith(BAD_SUFFIXES):
        return None
    if any(c in local for c in (' ', '\t', '\n', '/')):
        return None
    if domain in BAD_DOMAINS:
        return None
    if re.fullmatch(r'\d+x', local):
        return None
    if '.' not in domain:
        return None
    tld = domain.rsplit('.', 1)[-1]
    if not (2 <= len(tld) <= 24) or not tld.isalpha():
        return None
    return email


def extract_emails_from_html(html: str) -> set[str]:
    found: set[str] = set()
    soup = BeautifulSoup(html, 'html.parser')

    for a in soup.find_all('a', href=True):
        href = a['href']
        if href.lower().startswith('mailto:'):
            raw = href[7:].split('?', 1)[0]
            for piece in re.split(r'[,;]', raw):
                cleaned = clean_email(piece)
                if cleaned:
                    found.add(cleaned)

    for tag in soup(['script', 'style', 'noscript']):
        tag.decompose()
    text = soup.get_text(separator=' ')

    for m in EMAIL_RE.finditer(text):
        cleaned = clean_email(m.group(1))
        if cleaned:
            found.add(cleaned)

    for m in OBFUSCATED_RE.finditer(text):
        rebuilt = f'{m.group(1)}@{m.group(2)}.{m.group(3)}'
        cleaned = clean_email(rebuilt)
        if cleaned:
            found.add(cleaned)

    return {e for e in found if not e.split('@', 1)[0].startswith(BAD_LOCAL_PREFIXES)}


def extract_links(html: str, base_url: str, root_netloc: str) -> list[str]:
    soup = BeautifulSoup(html, 'html.parser')
    out: list[str] = []
    for a in soup.find_all('a', href=True):
        href = a['href'].strip()
        if not href or href.startswith(('mailto:', 'tel:', 'javascript:', '#')):
            continue
        full = urljoin(base_url, href).split('#', 1)[0]
        if not full.startswith(('http://', 'https://')):
            continue
        if not same_domain(full, root_netloc):
            continue
        if any(skip in full.lower() for skip in SKIP_PATH_HINTS):
            continue
        out.append(full)
    return out


def sort_queue_by_priority(urls: list[str]) -> list[str]:
    def score(u: str) -> int:
        low = u.lower()
        for i, hint in enumerate(PRIORITY_PATH_HINTS):
            if hint in low:
                return i
        return len(PRIORITY_PATH_HINTS)
    return sorted(urls, key=score)


class SiteCrawler:
    def __init__(
        self,
        session: requests.Session,
        max_pages: int = 50,
        delay: float = 1.5,
        timeout: float = 10.0,
        respect_robots: bool = True,
    ):
        self.session = session
        self.max_pages = max_pages
        self.delay = delay
        self.timeout = timeout
        self.respect_robots = respect_robots

    def _robots(self, root_url: str) -> RobotFileParser | None:
        if not self.respect_robots:
            return None
        parsed = urlparse(root_url)
        rp = RobotFileParser()
        rp.set_url(f'{parsed.scheme}://{parsed.netloc}/robots.txt')
        try:
            rp.read()
        except Exception:
            return None
        return rp

    def crawl(
        self,
        root_url: str,
        on_log: Callable[[str], None] | None = None,
    ) -> list[tuple[str, str]]:
        def note(msg: str) -> None:
            if on_log:
                on_log(msg)

        root_url = normalize_url(root_url)
        parsed = urlparse(root_url)
        if not parsed.netloc:
            note(f'skip invalid url: {root_url}')
            return []
        root_netloc = parsed.netloc.lower()
        if root_netloc.startswith('www.'):
            root_netloc = root_netloc[4:]

        rp = self._robots(root_url)
        visited: set[str] = set()
        queue: deque[str] = deque([root_url])
        results: list[tuple[str, str]] = []
        pages_fetched = 0

        while queue and pages_fetched < self.max_pages:
            url = queue.popleft()
            if url in visited:
                continue
            visited.add(url)

            if rp is not None and not rp.can_fetch(
                self.session.headers.get('User-Agent', '*'), url
            ):
                continue

            try:
                resp = self.session.get(url, timeout=self.timeout, allow_redirects=True)
            except requests.RequestException as exc:
                note(f'  fetch failed {url}: {exc}')
                continue

            pages_fetched += 1
            ctype = resp.headers.get('Content-Type', '')
            if 'text/html' not in ctype and 'application/xhtml' not in ctype:
                continue
            if resp.status_code >= 400:
                continue

            emails = extract_emails_from_html(resp.text)
            for email in emails:
                results.append((email, url))
            if emails:
                note(f'  [{pages_fetched}/{self.max_pages}] {url} -> {len(emails)} email(s)')
            else:
                note(f'  [{pages_fetched}/{self.max_pages}] {url}')

            new_links = extract_links(resp.text, url, root_netloc)
            for link in sort_queue_by_priority(new_links):
                if link not in visited and link not in queue:
                    queue.append(link)

            time.sleep(self.delay)

        note(f'  crawled {pages_fetched} page(s), {len(results)} email hit(s)')
        return results


def build_session(user_agent: str = DEFAULT_USER_AGENT) -> requests.Session:
    s = requests.Session()
    s.headers.update({
        'User-Agent': user_agent,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
    })
    return s
