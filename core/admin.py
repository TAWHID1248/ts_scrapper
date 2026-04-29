from django.contrib import admin
from .models import Campaign, CampaignRecipient, Contact, ContactList, EmailEvent, EmailTemplate


@admin.register(ContactList)
class ContactListAdmin(admin.ModelAdmin):
    list_display = ('name', 'active_count', 'created_at')


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = ('email', 'first_name', 'last_name', 'is_suppressed', 'source_site', 'created_at')
    list_filter = ('is_suppressed', 'lists')
    search_fields = ('email', 'first_name', 'last_name')
    filter_horizontal = ('lists',)


@admin.register(EmailTemplate)
class EmailTemplateAdmin(admin.ModelAdmin):
    list_display = ('name', 'subject', 'updated_at')


@admin.register(Campaign)
class CampaignAdmin(admin.ModelAdmin):
    list_display = ('name', 'status', 'template', 'contact_list', 'sent_at', 'created_at')
    list_filter = ('status',)


@admin.register(CampaignRecipient)
class CampaignRecipientAdmin(admin.ModelAdmin):
    list_display = ('campaign', 'contact', 'status', 'sent_at', 'opened_at', 'clicked_at', 'unsubscribed_at')
    list_filter = ('status', 'campaign')


@admin.register(EmailEvent)
class EmailEventAdmin(admin.ModelAdmin):
    list_display = ('recipient', 'event', 'created_at')
    list_filter = ('event',)
