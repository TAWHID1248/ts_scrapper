from django.contrib import messages
from django.db.models import Count, Q
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render

from scraper.models import ScrapeJob

from .forms import (
    AppSettingsForm,
    CampaignForm,
    ContactForm,
    ContactListForm,
    EmailTemplateForm,
    ImportContactsForm,
    SendTestForm,
    SettingsTestForm,
)
from .models import AppSettings, Campaign, CampaignRecipient, Contact, ContactList, EmailEvent, EmailTemplate
from .sender import send_campaign_async, send_settings_probe, send_test_email


# --- Settings ---------------------------------------------------------------

def settings_view(request):
    app_settings = AppSettings.load()
    form = AppSettingsForm(instance=app_settings)
    test_form = SettingsTestForm(initial={'to_email': app_settings.default_from_email or ''})

    if request.method == 'POST':
        if 'save_settings' in request.POST:
            form = AppSettingsForm(request.POST, instance=app_settings)
            if form.is_valid():
                form.save()
                messages.success(request, 'Settings saved.')
                return redirect('settings')
        elif 'send_test' in request.POST:
            test_form = SettingsTestForm(request.POST)
            if test_form.is_valid():
                try:
                    send_settings_probe(
                        to_email=test_form.cleaned_data['to_email'],
                        from_name=app_settings.default_from_name or 'Mailer',
                        from_email=app_settings.default_from_email or 'noreply@example.com',
                        app_settings=app_settings,
                    )
                    messages.success(request, f'Test email sent to {test_form.cleaned_data["to_email"]}.')
                except Exception as exc:  # noqa: BLE001
                    messages.error(request, f'Send failed: {exc}')
                return redirect('settings')

    return render(request, 'core/settings.html', {
        'form': form,
        'test_form': test_form,
        'app_settings': app_settings,
    })


# --- Dashboard ---------------------------------------------------------------

def dashboard(request):
    total_contacts = Contact.objects.count()
    active_contacts = Contact.objects.filter(is_suppressed=False).count()
    suppressed_contacts = total_contacts - active_contacts
    total_lists = ContactList.objects.count()
    total_templates = EmailTemplate.objects.count()
    total_campaigns = Campaign.objects.count()
    scrape_jobs = ScrapeJob.objects.count()

    sent = CampaignRecipient.objects.filter(status=CampaignRecipient.STATUS_SENT).count()
    opened = CampaignRecipient.objects.exclude(opened_at=None).count()
    clicked = CampaignRecipient.objects.exclude(clicked_at=None).count()
    bounced = CampaignRecipient.objects.filter(status=CampaignRecipient.STATUS_BOUNCED).count()
    unsubscribed = CampaignRecipient.objects.exclude(unsubscribed_at=None).count()

    def pct(n):
        return round(100 * n / sent, 1) if sent else 0.0

    recent_campaigns = Campaign.objects.order_by('-created_at')[:5]
    recent_jobs = ScrapeJob.objects.order_by('-created_at')[:5]

    return render(request, 'core/dashboard.html', {
        'stats': {
            'total_contacts': total_contacts,
            'active_contacts': active_contacts,
            'suppressed_contacts': suppressed_contacts,
            'total_lists': total_lists,
            'total_templates': total_templates,
            'total_campaigns': total_campaigns,
            'scrape_jobs': scrape_jobs,
            'sent': sent,
            'opened': opened,
            'clicked': clicked,
            'bounced': bounced,
            'unsubscribed': unsubscribed,
            'open_rate': pct(opened),
            'click_rate': pct(clicked),
            'bounce_rate': pct(bounced),
            'unsub_rate': pct(unsubscribed),
        },
        'recent_campaigns': recent_campaigns,
        'recent_jobs': recent_jobs,
    })


# --- Contacts ---------------------------------------------------------------

def contact_list(request):
    q = request.GET.get('q', '').strip()
    list_id = request.GET.get('list', '').strip()
    suppressed = request.GET.get('suppressed', '').strip()

    contacts = Contact.objects.all()
    if q:
        contacts = contacts.filter(Q(email__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q))
    if list_id.isdigit():
        contacts = contacts.filter(lists__id=int(list_id))
    if suppressed == '1':
        contacts = contacts.filter(is_suppressed=True)
    elif suppressed == '0':
        contacts = contacts.filter(is_suppressed=False)

    contacts = contacts.prefetch_related('lists')[:500]
    return render(request, 'core/contact_list.html', {
        'contacts': contacts,
        'lists': ContactList.objects.all(),
        'q': q,
        'selected_list': list_id,
        'suppressed': suppressed,
    })


def contact_delete(request, pk):
    if request.method != 'POST':
        return HttpResponseBadRequest()
    Contact.objects.filter(pk=pk).delete()
    messages.success(request, 'Contact deleted.')
    return redirect('contact_list')


def contact_edit(request, pk):
    contact = get_object_or_404(Contact, pk=pk)
    if request.method == 'POST':
        form = ContactForm(request.POST, instance=contact)
        if form.is_valid():
            form.save()
            messages.success(request, 'Contact saved.')
            return redirect('contact_list')
    else:
        form = ContactForm(instance=contact)
    return render(request, 'core/contact_form.html', {'form': form, 'contact': contact})


# --- Lists ------------------------------------------------------------------

def list_list(request):
    lists = ContactList.objects.annotate(count=Count('contacts')).order_by('name')
    return render(request, 'core/list_list.html', {'lists': lists})


def list_create(request):
    if request.method == 'POST':
        form = ContactListForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'List created.')
            return redirect('list_list')
    else:
        form = ContactListForm()
    return render(request, 'core/list_form.html', {'form': form, 'title': 'New list'})


def list_edit(request, pk):
    obj = get_object_or_404(ContactList, pk=pk)
    if request.method == 'POST':
        form = ContactListForm(request.POST, instance=obj)
        if form.is_valid():
            form.save()
            messages.success(request, 'List saved.')
            return redirect('list_list')
    else:
        form = ContactListForm(instance=obj)
    return render(request, 'core/list_form.html', {'form': form, 'title': f'Edit list: {obj.name}'})


def list_delete(request, pk):
    if request.method != 'POST':
        return HttpResponseBadRequest()
    obj = get_object_or_404(ContactList, pk=pk)
    name = obj.name
    obj.delete()
    messages.success(request, f'List "{name}" deleted.')
    return redirect('list_list')


def list_import(request):
    if request.method == 'POST':
        form = ImportContactsForm(request.POST)
        if form.is_valid():
            name = form.cleaned_data['list_name'].strip()
            emails_raw = form.cleaned_data['emails']
            contact_list_obj, _ = ContactList.objects.get_or_create(name=name)
            added = 0
            for line in emails_raw.splitlines():
                email = line.strip().lower()
                if not email or '@' not in email:
                    continue
                contact, created = Contact.objects.get_or_create(email=email)
                contact.lists.add(contact_list_obj)
                if created:
                    added += 1
            messages.success(request, f'Imported {added} new contact(s) into "{name}".')
            return redirect('list_list')
    else:
        form = ImportContactsForm()
    return render(request, 'core/list_form.html', {'form': form, 'title': 'Import contacts'})


# --- Templates --------------------------------------------------------------

def template_list(request):
    templates = EmailTemplate.objects.all()
    return render(request, 'core/template_list.html', {'templates': templates})


def template_create(request):
    if request.method == 'POST':
        form = EmailTemplateForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Template saved.')
            return redirect('template_list')
    else:
        form = EmailTemplateForm(initial={
            'subject': 'Hi {{ first_name|default:"there" }}!',
            'body_html': (
                '<p>Hi {{ first_name|default:"there" }},</p>\n'
                '<p>I run <a href="https://example.com">Example Co</a> and wanted to reach out.</p>\n'
                '<p>Would you have 15 minutes next week for a quick chat?</p>\n'
                '<p>Best,<br/>Your name</p>\n'
            ),
        })
    return render(request, 'core/template_form.html', {'form': form, 'title': 'New template'})


def template_edit(request, pk):
    template = get_object_or_404(EmailTemplate, pk=pk)
    if request.method == 'POST':
        form = EmailTemplateForm(request.POST, instance=template)
        if form.is_valid():
            form.save()
            messages.success(request, 'Template saved.')
            return redirect('template_list')
    else:
        form = EmailTemplateForm(instance=template)
    return render(request, 'core/template_form.html', {
        'form': form, 'title': f'Edit: {template.name}', 'template': template,
    })


def template_delete(request, pk):
    if request.method != 'POST':
        return HttpResponseBadRequest()
    tpl = get_object_or_404(EmailTemplate, pk=pk)
    try:
        name = tpl.name
        tpl.delete()
        messages.success(request, f'Template "{name}" deleted.')
    except Exception as exc:  # PROTECT on Campaign
        messages.error(request, f"Can't delete: {exc}")
    return redirect('template_list')


def template_test_send(request, pk):
    template = get_object_or_404(EmailTemplate, pk=pk)
    if request.method == 'POST':
        form = SendTestForm(request.POST)
        if form.is_valid():
            try:
                send_test_email(
                    template_id=template.pk,
                    to_email=form.cleaned_data['to_email'],
                    from_name=form.cleaned_data['from_name'],
                    from_email=form.cleaned_data['from_email'],
                )
                messages.success(request, f'Test email sent to {form.cleaned_data["to_email"]} (check server console if using the console backend).')
            except Exception as exc:  # noqa: BLE001
                messages.error(request, f'Send failed: {exc}')
            return redirect('template_edit', pk=template.pk)
    else:
        form = SendTestForm()
    return render(request, 'core/template_test.html', {'form': form, 'template': template})


# --- Campaigns --------------------------------------------------------------

def campaign_list(request):
    campaigns = Campaign.objects.select_related('template', 'contact_list').all()
    return render(request, 'core/campaign_list.html', {'campaigns': campaigns})


def campaign_create(request):
    if not EmailTemplate.objects.exists():
        messages.warning(request, 'Create an email template first.')
        return redirect('template_create')
    if not ContactList.objects.exists():
        messages.warning(request, 'Create or import a contact list first.')
        return redirect('list_list')

    if request.method == 'POST':
        form = CampaignForm(request.POST)
        if form.is_valid():
            campaign = form.save()
            messages.success(request, f'Campaign "{campaign.name}" saved as draft.')
            return redirect('campaign_detail', pk=campaign.pk)
    else:
        form = CampaignForm()
    return render(request, 'core/campaign_form.html', {'form': form, 'title': 'New campaign'})


def campaign_edit(request, pk):
    campaign = get_object_or_404(Campaign, pk=pk)
    if campaign.status != Campaign.STATUS_DRAFT:
        messages.info(request, 'Only draft campaigns can be edited.')
        return redirect('campaign_detail', pk=pk)
    if request.method == 'POST':
        form = CampaignForm(request.POST, instance=campaign)
        if form.is_valid():
            form.save()
            messages.success(request, 'Campaign saved.')
            return redirect('campaign_detail', pk=campaign.pk)
    else:
        form = CampaignForm(instance=campaign)
    return render(request, 'core/campaign_form.html', {'form': form, 'title': f'Edit: {campaign.name}'})


def campaign_delete(request, pk):
    if request.method != 'POST':
        return HttpResponseBadRequest()
    campaign = get_object_or_404(Campaign, pk=pk)
    name = campaign.name
    campaign.delete()
    messages.success(request, f'Campaign "{name}" deleted.')
    return redirect('campaign_list')


def campaign_detail(request, pk):
    campaign = get_object_or_404(
        Campaign.objects.select_related('template', 'contact_list'), pk=pk,
    )
    stats = campaign.stats()
    recipients = (campaign.recipients
                  .select_related('contact')
                  .order_by('-sent_at', '-id')[:200])
    events = (EmailEvent.objects
              .filter(recipient__campaign=campaign)
              .select_related('recipient__contact')
              .order_by('-created_at')[:50])
    return render(request, 'core/campaign_detail.html', {
        'campaign': campaign,
        'stats': stats,
        'recipients': recipients,
        'events': events,
    })


def campaign_send(request, pk):
    if request.method != 'POST':
        return HttpResponseBadRequest()
    campaign = get_object_or_404(Campaign, pk=pk)
    if campaign.status == Campaign.STATUS_SENT:
        messages.info(request, 'Campaign already sent.')
    else:
        send_campaign_async(campaign.pk)
        messages.success(
            request,
            f'Sending "{campaign.name}" in the background. '
            f'Check email backend in Settings if messages don\'t arrive.',
        )
    return redirect('campaign_detail', pk=campaign.pk)
