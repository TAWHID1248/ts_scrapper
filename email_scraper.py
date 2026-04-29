#!/usr/bin/env python3
"""
Email Scraper
-------------
Crawls a list of websites provided in a CSV file and extracts email addresses.

Features:
  * Full-site crawl (same-domain only), with a configurable page cap.
  * Pulls emails from `mailto:` links first, then falls back to regex on the
    visible text.
  * Deobfuscates common patterns: "name [at] domain [dot] com",
    "name (at) domain (dot) com", etc.
  * Filters false positives (image filenames, placeholders like
    example@example.com, tracking pixels, etc.).
  * Respects robots.txt (can be disabled with --ignore-robots).
  * Polite by default: custom User-Agent, 1.5s delay between requests,
    10s timeout.
  * Outputs a clean CSV: source_site,email,page_found_on

Usage:
  python email_scraper.py --input sites.csv --output emails.csv
  python email_scraper.py --input sites.csv --output emails.csv --max-pages 200 --delay 2.0

Input CSV format:
  Either a single column of URLs (with or without a header), or a column
  named `url` / `website` / `site` / `domain`.

Dependencies:
  pip install requests beautifulsoup4
"""

from __future__ import annotations

import argparse
import csv
import logging
import re
import sys
import time
from collections import deque
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Config & constants
# ---------------------------------------------------------------------------

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (compatible; EmailScraperBot/1.0; +https://example.com/bot)"
)

# Core RFC-ish email regex. Deliberately slightly stricter than RFC 5322 to
# cut down on false positives in messy HTML.
EMAIL_RE = re.compile(
    r"(?<![A-Za-z0-9._%+\-])"          # left boundary (not part of identifier)
    r"([A-Za-z0-9][A-Za-z0-9._%+\-]*"  # local part
    r"@"
    r"[A-Za-z0-9][A-Za-z0-9.\-]*"      # domain
    r"\.[A-Za-z]{2,24})"               # TLD
    r"(?![A-Za-z0-9._%+\-])"           # right boundary
)

# Obfuscated patterns: foo [at] bar [dot] com, foo(at)bar(dot)com, etc.
OBFUSCATED_RE = re.compile(
    r"([A-Za-z0-9][A-Za-z0-9._%+\-]*)\s*"
    r"(?:\[at\]|\(at\)|\{at\}|\s+at\s+|&#64;)\s*"
    r"([A-Za-z0-9][A-Za-z0-9.\-]*)\s*"
    r"(?:\[dot\]|\(dot\)|\{dot\}|\s+dot\s+)\s*"
    r"([A-Za-z]{2,24})",
    re.IGNORECASE,
)

# Extensions that look like emails in regex but are actually image/file
# references hiding @ symbols (e.g. "logo@2x.png").
BAD_SUFFIXES = (
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico",
    ".css", ".js", ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".pdf", ".zip", ".mp4", ".webm",
)

# Known placeholder / garbage local parts and domains.
BAD_DOMAINS = {
    "example.com", "example.org", "example.net",
    "domain.com", "yourdomain.com", "mail.com",
    "test.com", "foo.com", "bar.com",
    "sentry.io", "wixpress.com", "u.nu",
    "email.com", "yoursite.com", "site.com",
}
BAD_LOCAL_PREFIXES = ("noreply", "no-reply", "donotreply", "do-not-reply")

# Prioritize these path hints when crawling — emails usually live here.
PRIORITY_PATH_HINTS = (
    "contact", "about", "team", "staff", "impressum", "imprint",
    "legal", "privacy", "support", "help", "reach", "connect",
)

# Skip URLs that are almost always useless for email discovery.
SKIP_PATH_HINTS = (
    "/wp-content/", "/wp-includes/", "/assets/", "/static/",
    "/cdn-cgi/", "/feed/", "/rss", ".xml",
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("scraper")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def normalize_url(url: str) -> str:
    """Ensure the URL has a scheme and strip whitespace."""
    url = url.strip()
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


def same_domain(url: str, root_netloc: str) -> bool:
    """Check if url belongs to the same registrable host as root_netloc."""
    try:
        net = urlparse(url).netloc.lower()
    except ValueError:
        return False
    if not net:
        return False
    # Accept subdomains: foo.example.com matches example.com
    return net == root_netloc or net.endswith("." + root_netloc)


def clean_email(raw: str) -> str | None:
    """Normalize an email and filter out obvious junk. Returns None if bad."""
    if not raw:
        return None
    email = raw.strip().strip(".,;:()[]<>\"'").lower()

    # Strip common URL-encoded artifacts.
    email = email.replace("%40", "@").replace("&#64;", "@")

    if email.count("@") != 1:
        return None
    local, _, domain = email.partition("@")
    if not local or not domain:
        return None

    # Reject image-filename-ish emails: anything ending in a media extension.
    if email.endswith(BAD_SUFFIXES):
        return None

    # Reject if the local part or domain contains characters that survived
    # regex but aren't valid in practice.
    if any(c in local for c in (" ", "\t", "\n", "/")):
        return None

    if domain in BAD_DOMAINS:
        return None

    # Reject "name@2x" style sprite references.
    if re.fullmatch(r"\d+x", local):
        return None

    # Domain must have at least one dot and a plausible TLD.
    if "." not in domain:
        return None
    tld = domain.rsplit(".", 1)[-1]
    if not (2 <= len(tld) <= 24) or not tld.isalpha():
        return None

    return email


def extract_emails_from_html(html: str, base_url: str) -> set[str]:
    """Find emails via mailto links, plain text, and obfuscated patterns."""
    found: set[str] = set()
    soup = BeautifulSoup(html, "html.parser")

    # 1. mailto: links — highest signal.
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.lower().startswith("mailto:"):
            raw = href[7:].split("?", 1)[0]  # strip ?subject=... etc.
            for piece in re.split(r"[,;]", raw):
                cleaned = clean_email(piece)
                if cleaned:
                    found.add(cleaned)

    # 2. Get visible text (drop script/style noise).
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text(separator=" ")

    # 3. Plain regex pass on visible text.
    for m in EMAIL_RE.finditer(text):
        cleaned = clean_email(m.group(1))
        if cleaned:
            found.add(cleaned)

    # 4. Obfuscated "foo [at] bar [dot] com".
    for m in OBFUSCATED_RE.finditer(text):
        rebuilt = f"{m.group(1)}@{m.group(2)}.{m.group(3)}"
        cleaned = clean_email(rebuilt)
        if cleaned:
            found.add(cleaned)

    # Drop noreply-style addresses at the end — keep them optionally? For now,
    # drop, since they're rarely what the user wants.
    return {e for e in found if not e.split("@", 1)[0].startswith(BAD_LOCAL_PREFIXES)}


def extract_links(html: str, base_url: str, root_netloc: str) -> list[str]:
    """Pull internal links out of a page for the crawl queue."""
    soup = BeautifulSoup(html, "html.parser")
    out: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        full = urljoin(base_url, href)
        # Drop fragments.
        full = full.split("#", 1)[0]
        if not full.startswith(("http://", "https://")):
            continue
        if not same_domain(full, root_netloc):
            continue
        if any(skip in full.lower() for skip in SKIP_PATH_HINTS):
            continue
        out.append(full)
    return out


def sort_queue_by_priority(urls: list[str]) -> list[str]:
    """Put contact/about-type pages first — emails live there."""
    def score(u: str) -> int:
        low = u.lower()
        for i, hint in enumerate(PRIORITY_PATH_HINTS):
            if hint in low:
                return i
        return len(PRIORITY_PATH_HINTS)
    return sorted(urls, key=score)


def load_sites_from_csv(path: Path) -> list[str]:
    """Read URLs from a CSV. Supports header row or single-column files."""
    sites: list[str] = []
    with path.open(newline="", encoding="utf-8-sig") as f:
        sample = f.read(2048)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        KNOWN_HEADERS = {"url", "website", "site", "domain", "link"}
        # sniffer.has_header() is unreliable for single-column files (returns True
        # for bare URLs, False for "url" header rows). Use label-based detection
        # instead: treat the first row as a header only if a cell matches a known label.
        try:
            first_row_cells = next(csv.reader([sample.splitlines()[0]], dialect))
        except (StopIteration, csv.Error):
            first_row_cells = [sample.splitlines()[0]] if sample.strip() else []
        has_header = any(c.strip().lower() in KNOWN_HEADERS for c in first_row_cells)

        reader = csv.reader(f, dialect)
        rows = list(reader)
        if not rows:
            return []

        url_col = 0
        if has_header:
            header = [h.strip().lower() for h in rows[0]]
            for candidate in ("url", "website", "site", "domain", "link"):
                if candidate in header:
                    url_col = header.index(candidate)
                    break
            data_rows = rows[1:]
        else:
            data_rows = rows

        for row in data_rows:
            if not row or url_col >= len(row):
                continue
            url = normalize_url(row[url_col])
            if url:
                sites.append(url)
    # Dedupe, preserve order.
    seen: set[str] = set()
    unique: list[str] = []
    for u in sites:
        if u not in seen:
            seen.add(u)
            unique.append(u)
    return unique


# ---------------------------------------------------------------------------
# Crawler
# ---------------------------------------------------------------------------

class SiteCrawler:
    def __init__(
        self,
        session: requests.Session,
        max_pages: int,
        delay: float,
        timeout: float,
        respect_robots: bool,
    ):
        self.session = session
        self.max_pages = max_pages
        self.delay = delay
        self.timeout = timeout
        self.respect_robots = respect_robots

    def _robots_ok(self, root_url: str) -> RobotFileParser | None:
        """Fetch and parse robots.txt. Returns None if we should not check."""
        if not self.respect_robots:
            return None
        parsed = urlparse(root_url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        rp = RobotFileParser()
        rp.set_url(robots_url)
        try:
            rp.read()
        except Exception as exc:
            log.debug("robots.txt fetch failed for %s: %s", robots_url, exc)
            return None
        return rp

    def crawl(self, root_url: str) -> list[tuple[str, str]]:
        """Crawl one site. Returns list of (email, page_url) pairs."""
        root_url = normalize_url(root_url)
        parsed = urlparse(root_url)
        if not parsed.netloc:
            log.warning("Skipping invalid URL: %s", root_url)
            return []
        root_netloc = parsed.netloc.lower()
        # strip leading "www." for subdomain matching
        if root_netloc.startswith("www."):
            root_netloc = root_netloc[4:]

        rp = self._robots_ok(root_url)

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
                self.session.headers.get("User-Agent", "*"), url
            ):
                log.debug("robots.txt disallows %s", url)
                continue

            try:
                resp = self.session.get(
                    url, timeout=self.timeout, allow_redirects=True
                )
            except requests.RequestException as exc:
                log.warning("  fetch failed %s: %s", url, exc)
                continue

            pages_fetched += 1

            ctype = resp.headers.get("Content-Type", "")
            if "text/html" not in ctype and "application/xhtml" not in ctype:
                log.debug("  skip non-HTML %s (%s)", url, ctype)
                continue
            if resp.status_code >= 400:
                log.debug("  HTTP %s on %s", resp.status_code, url)
                continue

            html = resp.text

            # Extract emails.
            emails = extract_emails_from_html(html, url)
            for email in emails:
                results.append((email, url))
            if emails:
                log.info("  [%d/%d] %s -> %d email(s)",
                         pages_fetched, self.max_pages, url, len(emails))
            else:
                log.info("  [%d/%d] %s", pages_fetched, self.max_pages, url)

            # Enqueue more links, priority-sorted.
            new_links = extract_links(html, url, root_netloc)
            for link in sort_queue_by_priority(new_links):
                if link not in visited and link not in queue:
                    queue.append(link)

            time.sleep(self.delay)

        log.info("  crawled %d page(s), found %d email hit(s)",
                 pages_fetched, len(results))
        return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Scrape email addresses from a list of websites.")
    p.add_argument("--input", "-i", required=True, type=Path,
                   help="Input CSV file with one URL per row.")
    p.add_argument("--output", "-o", required=True, type=Path,
                   help="Output CSV file (source_site,email,page_found_on).")
    p.add_argument("--max-pages", type=int, default=100,
                   help="Max pages to crawl per site. Default: 100.")
    p.add_argument("--delay", type=float, default=1.5,
                   help="Seconds between requests to the same site. Default: 1.5.")
    p.add_argument("--timeout", type=float, default=10.0,
                   help="Per-request timeout in seconds. Default: 10.")
    p.add_argument("--user-agent", default=DEFAULT_USER_AGENT,
                   help="User-Agent header to send.")
    p.add_argument("--ignore-robots", action="store_true",
                   help="Ignore robots.txt (not recommended).")
    p.add_argument("--dry-run", action="store_true",
                   help="Only crawl the first site (useful for testing).")
    args = p.parse_args(argv)

    if not args.input.exists():
        log.error("Input file not found: %s", args.input)
        return 1

    sites = load_sites_from_csv(args.input)
    if not sites:
        log.error("No URLs found in %s", args.input)
        return 1

    if args.dry_run:
        sites = sites[:1]
        log.info("DRY RUN: only crawling %s", sites[0])

    log.info("Loaded %d site(s) from %s", len(sites), args.input)

    session = requests.Session()
    session.headers.update({
        "User-Agent": args.user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })

    crawler = SiteCrawler(
        session=session,
        max_pages=args.max_pages,
        delay=args.delay,
        timeout=args.timeout,
        respect_robots=not args.ignore_robots,
    )

    # Write output as we go so a crash doesn't lose everything.
    args.output.parent.mkdir(parents=True, exist_ok=True)
    total_unique = 0
    with args.output.open("w", newline="", encoding="utf-8") as out_f:
        writer = csv.writer(out_f)
        writer.writerow(["source_site", "email", "page_found_on"])

        for i, site in enumerate(sites, 1):
            log.info("[%d/%d] Crawling %s", i, len(sites), site)
            try:
                hits = crawler.crawl(site)
            except KeyboardInterrupt:
                log.warning("Interrupted by user; writing what we have.")
                break
            except Exception as exc:
                log.error("  unrecoverable error on %s: %s", site, exc)
                continue

            # Dedupe within a site, keep first page where each email was seen.
            seen_here: dict[str, str] = {}
            for email, page in hits:
                if email not in seen_here:
                    seen_here[email] = page
            for email, page in seen_here.items():
                writer.writerow([site, email, page])
                total_unique += 1
            out_f.flush()

    log.info("Done. Wrote %d unique (site, email) pair(s) to %s",
             total_unique, args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())