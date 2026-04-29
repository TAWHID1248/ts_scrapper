"""Renders + sends a campaign. Wraps links and injects an open pixel."""

from __future__ import annotations

import logging
import re
import threading
from urllib.parse import quote

from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection
from django.db import close_old_connections
from django.template import Context, Template
from django.urls import reverse
from django.utils import timezone

from .models import AppSettings, Campaign, CampaignRecipient, EmailEvent


log = logging.getLogger(__name__)

BACKEND_PATHS = {
    AppSettings.BACKEND_CONSOLE: 'django.core.mail.backends.console.EmailBackend',
    AppSettings.BACKEND_SMTP: 'django.core.mail.backends.smtp.EmailBackend',
    AppSettings.BACKEND_FILE: 'django.core.mail.backends.filebased.EmailBackend',
}


def _render(tmpl_str: str, ctx: dict) -> str:
    return Template(tmpl_str).render(Context(ctx))


def _base_url() -> str:
    try:
        url = AppSettings.load().site_base_url
    except Exception:
        url = getattr(settings, 'SITE_BASE_URL', 'http://127.0.0.1:8000')
    return url.rstrip('/')


def _connection_from(app_settings: AppSettings):
    backend = BACKEND_PATHS.get(app_settings.email_backend, BACKEND_PATHS[AppSettings.BACKEND_CONSOLE])
    kwargs = {'backend': backend}
    if app_settings.email_backend == AppSettings.BACKEND_SMTP:
        kwargs.update({
            'host': app_settings.smtp_host or 'localhost',
            'port': app_settings.smtp_port or 587,
            'username': app_settings.smtp_username or '',
            'password': app_settings.smtp_password or '',
            'use_tls': app_settings.smtp_use_tls,
            'use_ssl': app_settings.smtp_use_ssl,
            'timeout': app_settings.smtp_timeout or 10,
        })
    elif app_settings.email_backend == AppSettings.BACKEND_FILE:
        kwargs['file_path'] = '/tmp/mailer-sent'
    return get_connection(**kwargs)


def get_active_connection():
    return _connection_from(AppSettings.load())


def _rewrite_links(html: str, token: str) -> str:
    """Route every http(s) <a href> through the click tracker."""
    def repl(m: re.Match) -> str:
        prefix, quote_char, url = m.group(1), m.group(2), m.group(3)
        if url.startswith(('mailto:', 'tel:', '#')):
            return m.group(0)
        tracked = f'{_base_url()}/t/c/{token}/?u={quote(url, safe="")}'
        return f'{prefix}{quote_char}{tracked}{quote_char}'
    return re.sub(r'(<a\b[^>]*\shref=)(["\'])(https?://[^"\']+)\2', repl, html, flags=re.IGNORECASE)


def _append_footer(html: str, unsub_url: str, from_name: str) -> str:
    pixel = f'<img src="{_base_url()}/t/o/_TOKEN_.gif" width="1" height="1" alt="" style="display:block" />'
    footer = (
        '<hr style="margin-top:32px;border:none;border-top:1px solid #eee" />'
        f'<p style="font-size:11px;color:#888;font-family:Arial,sans-serif">'
        f'You received this from {from_name}. '
        f'<a href="{unsub_url}" style="color:#888">Unsubscribe</a>.'
        f'</p>{pixel}'
    )
    return html + footer


def send_campaign(campaign_id: int) -> None:
    """Synchronously send the campaign. Call via threading for async."""
    try:
        campaign = Campaign.objects.select_related('template', 'contact_list').get(pk=campaign_id)
    except Campaign.DoesNotExist:
        return

    if campaign.status == Campaign.STATUS_SENT:
        return

    campaign.status = Campaign.STATUS_SENDING
    campaign.save(update_fields=['status'])

    contacts = campaign.contact_list.contacts.all()
    connection = get_active_connection()

    try:
        for contact in contacts.iterator():
            recipient, _ = CampaignRecipient.objects.get_or_create(
                campaign=campaign, contact=contact,
            )
            if recipient.status in (CampaignRecipient.STATUS_SENT, CampaignRecipient.STATUS_BOUNCED):
                continue
            if contact.is_suppressed:
                recipient.status = CampaignRecipient.STATUS_SUPPRESSED
                recipient.error = contact.suppressed_reason or 'suppressed'
                recipient.save()
                continue

            token = str(recipient.token)
            unsub_url = f'{_base_url()}{reverse("unsubscribe", args=[token])}'
            ctx = {
                'email': contact.email,
                'first_name': contact.first_name or '',
                'last_name': contact.last_name or '',
                'unsubscribe_url': unsub_url,
            }

            try:
                subject = _render(campaign.template.subject, ctx)
                html_body = _render(campaign.template.body_html, ctx)
                text_body = _render(campaign.template.body_text or '', ctx)

                html_body = _append_footer(html_body, unsub_url, campaign.from_name)
                html_body = _rewrite_links(html_body, token)
                html_body = html_body.replace('_TOKEN_', token)

                msg = EmailMultiAlternatives(
                    subject=subject,
                    body=text_body or subject,
                    from_email=f'{campaign.from_name} <{campaign.from_email}>',
                    to=[contact.email],
                    reply_to=[campaign.reply_to] if campaign.reply_to else None,
                    headers={'List-Unsubscribe': f'<{unsub_url}>'},
                    connection=connection,
                )
                msg.attach_alternative(html_body, 'text/html')
                msg.send(fail_silently=False)

                recipient.status = CampaignRecipient.STATUS_SENT
                recipient.sent_at = timezone.now()
                recipient.error = ''
                recipient.save()
                EmailEvent.objects.create(recipient=recipient, event=EmailEvent.EVENT_SENT)
            except Exception as exc:  # noqa: BLE001
                recipient.status = CampaignRecipient.STATUS_FAILED
                recipient.error = str(exc)[:500]
                recipient.save()
                EmailEvent.objects.create(recipient=recipient, event=EmailEvent.EVENT_FAILED)
                log.exception('send failed for %s', contact.email)

        campaign.status = Campaign.STATUS_SENT
        campaign.sent_at = timezone.now()
        campaign.save(update_fields=['status', 'sent_at'])
    except Exception:
        campaign.status = Campaign.STATUS_FAILED
        campaign.save(update_fields=['status'])
        raise
    finally:
        close_old_connections()


def send_campaign_async(campaign_id: int) -> None:
    t = threading.Thread(target=send_campaign, args=(campaign_id,), daemon=True)
    t.start()


def send_test_email(template_id: int, to_email: str, from_name: str, from_email: str) -> None:
    from .models import EmailTemplate
    template = EmailTemplate.objects.get(pk=template_id)
    ctx = {
        'email': to_email,
        'first_name': 'Test',
        'last_name': 'User',
        'unsubscribe_url': f'{_base_url()}/t/u/test/',
    }
    subject = _render(template.subject, ctx)
    html_body = _render(template.body_html, ctx)
    text_body = _render(template.body_text or '', ctx)
    msg = EmailMultiAlternatives(
        subject=f'[TEST] {subject}',
        body=text_body or subject,
        from_email=f'{from_name} <{from_email}>',
        to=[to_email],
        connection=get_active_connection(),
    )
    msg.attach_alternative(html_body, 'text/html')
    msg.send(fail_silently=False)


def send_settings_probe(to_email: str, from_name: str, from_email: str, app_settings: AppSettings) -> None:
    """Sends a tiny plain-text email using the given settings (useful after a config change)."""
    connection = _connection_from(app_settings)
    msg = EmailMultiAlternatives(
        subject='Mailer test email',
        body=(
            'This is a test from your Mailer app.\n\n'
            f'Backend: {app_settings.get_email_backend_display()}\n'
            f'If you received this, your email settings are working.\n'
        ),
        from_email=f'{from_name} <{from_email}>',
        to=[to_email],
        connection=connection,
    )
    msg.send(fail_silently=False)
