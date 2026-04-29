"""Open pixel, click redirect, unsubscribe."""

from django.contrib import messages
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .models import CampaignRecipient, EmailEvent


TRANSPARENT_GIF = (
    b'GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00'
    b'!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01'
    b'\x00\x00\x02\x02D\x01\x00;'
)


def _client_meta(request):
    return {
        'user_agent': request.META.get('HTTP_USER_AGENT', '')[:500],
        'ip': request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip()
              or request.META.get('REMOTE_ADDR') or None,
    }


def open_pixel(request, token):
    try:
        recipient = CampaignRecipient.objects.get(token=token)
    except (CampaignRecipient.DoesNotExist, ValueError):
        return HttpResponse(TRANSPARENT_GIF, content_type='image/gif')

    recipient.open_count += 1
    if not recipient.opened_at:
        recipient.opened_at = timezone.now()
    recipient.save(update_fields=['open_count', 'opened_at'])

    meta = _client_meta(request)
    EmailEvent.objects.create(
        recipient=recipient,
        event=EmailEvent.EVENT_OPEN,
        user_agent=meta['user_agent'],
        ip=meta['ip'],
    )
    resp = HttpResponse(TRANSPARENT_GIF, content_type='image/gif')
    resp['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    return resp


def click_redirect(request, token):
    target = request.GET.get('u', '')
    if not target.startswith(('http://', 'https://')):
        target = '/'

    try:
        recipient = CampaignRecipient.objects.get(token=token)
    except (CampaignRecipient.DoesNotExist, ValueError):
        return HttpResponseRedirect(target)

    recipient.click_count += 1
    if not recipient.clicked_at:
        recipient.clicked_at = timezone.now()
    recipient.save(update_fields=['click_count', 'clicked_at'])

    meta = _client_meta(request)
    EmailEvent.objects.create(
        recipient=recipient,
        event=EmailEvent.EVENT_CLICK,
        url=target[:1000],
        user_agent=meta['user_agent'],
        ip=meta['ip'],
    )
    return HttpResponseRedirect(target)


@csrf_exempt
@require_http_methods(['GET', 'POST'])
def unsubscribe(request, token):
    if token == 'test':
        return render(request, 'core/unsubscribe_done.html', {'test': True})

    try:
        recipient = CampaignRecipient.objects.select_related('contact', 'campaign').get(token=token)
    except (CampaignRecipient.DoesNotExist, ValueError):
        return render(request, 'core/unsubscribe_invalid.html', status=404)

    if request.method == 'POST':
        if not recipient.unsubscribed_at:
            recipient.unsubscribed_at = timezone.now()
            recipient.save(update_fields=['unsubscribed_at'])
            contact = recipient.contact
            contact.is_suppressed = True
            contact.suppressed_reason = 'unsubscribed'
            contact.save(update_fields=['is_suppressed', 'suppressed_reason'])
            meta = _client_meta(request)
            EmailEvent.objects.create(
                recipient=recipient,
                event=EmailEvent.EVENT_UNSUB,
                user_agent=meta['user_agent'],
                ip=meta['ip'],
            )
        return render(request, 'core/unsubscribe_done.html', {'recipient': recipient})

    return render(request, 'core/unsubscribe_confirm.html', {'recipient': recipient})
