"""Background scrape runner (threaded — fine for single-worker dev, not production)."""

from __future__ import annotations

import threading
from django.db import close_old_connections
from django.utils import timezone

from core.models import Contact, ContactList
from .engine import SiteCrawler, build_session, normalize_url
from .models import ScrapeJob


LOG_LINE_CAP = 300


def _append_log(job: ScrapeJob, line: str) -> None:
    lines = job.log.splitlines() if job.log else []
    lines.append(line)
    if len(lines) > LOG_LINE_CAP:
        lines = lines[-LOG_LINE_CAP:]
    job.log = '\n'.join(lines)


def run_scrape_job(job_id: int) -> None:
    try:
        job = ScrapeJob.objects.get(pk=job_id)
    except ScrapeJob.DoesNotExist:
        return

    sites = [normalize_url(s) for s in job.sites.splitlines() if s.strip()]
    sites = [s for s in sites if s]

    job.status = ScrapeJob.STATUS_RUNNING
    job.started_at = timezone.now()
    job.total_sites = len(sites)
    job.sites_done = 0
    job.emails_found = 0
    job.log = ''
    _append_log(job, f'Starting scrape: {len(sites)} site(s).')
    job.save()

    list_name = job.name or f'Scrape Job #{job.pk}'
    contact_list, _ = ContactList.objects.get_or_create(name=list_name)

    session = build_session()
    crawler = SiteCrawler(
        session=session,
        max_pages=job.max_pages,
        delay=job.delay,
        timeout=10.0,
        respect_robots=job.respect_robots,
    )

    try:
        new_emails = 0
        for i, site in enumerate(sites, 1):
            _append_log(job, f'[{i}/{len(sites)}] {site}')
            job.save(update_fields=['log'])
            hits = crawler.crawl(site, on_log=lambda m, j=job: _persist_log(j, m))
            seen: dict[str, str] = {}
            for email, page in hits:
                if email not in seen:
                    seen[email] = page
            for email, page in seen.items():
                contact, created = Contact.objects.get_or_create(
                    email=email,
                    defaults={'source_site': site, 'source_page': page},
                )
                contact.lists.add(contact_list)
                if created:
                    new_emails += 1
            job.sites_done = i
            job.emails_found = new_emails
            job.save(update_fields=['sites_done', 'emails_found', 'log'])
        job.status = ScrapeJob.STATUS_COMPLETED
        _append_log(job, f'Done. {new_emails} new contact(s) added to list "{list_name}".')
    except Exception as exc:  # noqa: BLE001
        job.status = ScrapeJob.STATUS_FAILED
        _append_log(job, f'ERROR: {exc!r}')
    finally:
        job.finished_at = timezone.now()
        job.save()
        close_old_connections()


def _persist_log(job: ScrapeJob, line: str) -> None:
    _append_log(job, line)
    job.save(update_fields=['log'])


def start_scrape_job(job_id: int) -> None:
    t = threading.Thread(target=run_scrape_job, args=(job_id,), daemon=True)
    t.start()
