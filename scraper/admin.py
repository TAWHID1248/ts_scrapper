from django.contrib import admin
from .models import ScrapeJob


@admin.register(ScrapeJob)
class ScrapeJobAdmin(admin.ModelAdmin):
    list_display = ('name', 'status', 'sites_done', 'total_sites', 'emails_found', 'created_at')
    list_filter = ('status',)
