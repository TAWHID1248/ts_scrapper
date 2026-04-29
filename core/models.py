import uuid
from django.db import models


class AppSettings(models.Model):
    BACKEND_CONSOLE = 'console'
    BACKEND_SMTP = 'smtp'
    BACKEND_FILE = 'file'
    BACKEND_CHOICES = [
        (BACKEND_CONSOLE, 'Console (print to server log)'),
        (BACKEND_SMTP, 'SMTP (real delivery)'),
        (BACKEND_FILE, 'File (save to /tmp)'),
    ]

    site_base_url = models.URLField(default='http://127.0.0.1:8000')
    default_from_name = models.CharField(max_length=100, blank=True)
    default_from_email = models.EmailField(blank=True)
    default_reply_to = models.EmailField(blank=True)

    email_backend = models.CharField(max_length=20, choices=BACKEND_CHOICES, default=BACKEND_CONSOLE)
    smtp_host = models.CharField(max_length=200, blank=True)
    smtp_port = models.PositiveIntegerField(default=587)
    smtp_username = models.CharField(max_length=200, blank=True)
    smtp_password = models.CharField(max_length=200, blank=True)
    smtp_use_tls = models.BooleanField(default=True)
    smtp_use_ssl = models.BooleanField(default=False)
    smtp_timeout = models.PositiveIntegerField(default=10)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'App settings'
        verbose_name_plural = 'App settings'

    def __str__(self):
        return 'Application settings'

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls) -> 'AppSettings':
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class ContactList(models.Model):
    name = models.CharField(max_length=200, unique=True)
    description = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def active_count(self) -> int:
        return self.contacts.filter(is_suppressed=False).count()


class Contact(models.Model):
    email = models.EmailField(unique=True)
    first_name = models.CharField(max_length=100, blank=True)
    last_name = models.CharField(max_length=100, blank=True)
    source_site = models.URLField(max_length=500, blank=True)
    source_page = models.URLField(max_length=500, blank=True)
    tags = models.CharField(max_length=500, blank=True, help_text='Comma-separated.')
    lists = models.ManyToManyField(ContactList, related_name='contacts', blank=True)
    is_suppressed = models.BooleanField(default=False, db_index=True)
    suppressed_reason = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.email

    @property
    def domain(self) -> str:
        return self.email.split('@', 1)[1] if '@' in self.email else ''


class EmailTemplate(models.Model):
    name = models.CharField(max_length=200)
    subject = models.CharField(max_length=300)
    body_html = models.TextField(
        help_text='HTML. Use {{ first_name }}, {{ email }}, {{ unsubscribe_url }}.'
    )
    body_text = models.TextField(blank=True, help_text='Plain-text fallback (optional).')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return self.name


class Campaign(models.Model):
    STATUS_DRAFT = 'draft'
    STATUS_SENDING = 'sending'
    STATUS_SENT = 'sent'
    STATUS_FAILED = 'failed'
    STATUS_CHOICES = [
        (STATUS_DRAFT, 'Draft'),
        (STATUS_SENDING, 'Sending'),
        (STATUS_SENT, 'Sent'),
        (STATUS_FAILED, 'Failed'),
    ]

    name = models.CharField(max_length=200)
    template = models.ForeignKey(EmailTemplate, on_delete=models.PROTECT, related_name='campaigns')
    contact_list = models.ForeignKey(ContactList, on_delete=models.PROTECT, related_name='campaigns')
    from_name = models.CharField(max_length=100)
    from_email = models.EmailField()
    reply_to = models.EmailField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.name

    def stats(self) -> dict:
        rs = self.recipients.all()
        total = rs.count()
        sent = rs.filter(status=CampaignRecipient.STATUS_SENT).count()
        opened = rs.exclude(opened_at=None).count()
        clicked = rs.exclude(clicked_at=None).count()
        bounced = rs.filter(status=CampaignRecipient.STATUS_BOUNCED).count()
        failed = rs.filter(status=CampaignRecipient.STATUS_FAILED).count()
        unsubscribed = rs.exclude(unsubscribed_at=None).count()

        def pct(n):
            return round(100 * n / sent, 1) if sent else 0.0

        return {
            'total': total,
            'sent': sent,
            'opened': opened,
            'clicked': clicked,
            'bounced': bounced,
            'failed': failed,
            'unsubscribed': unsubscribed,
            'open_rate': pct(opened),
            'click_rate': pct(clicked),
            'bounce_rate': pct(bounced),
            'unsub_rate': pct(unsubscribed),
        }


class CampaignRecipient(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_SENT = 'sent'
    STATUS_BOUNCED = 'bounced'
    STATUS_FAILED = 'failed'
    STATUS_SUPPRESSED = 'suppressed'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_SENT, 'Sent'),
        (STATUS_BOUNCED, 'Bounced'),
        (STATUS_FAILED, 'Failed'),
        (STATUS_SUPPRESSED, 'Suppressed'),
    ]

    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name='recipients')
    contact = models.ForeignKey(Contact, on_delete=models.CASCADE, related_name='campaign_recipients')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    error = models.CharField(max_length=500, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    opened_at = models.DateTimeField(null=True, blank=True)
    open_count = models.PositiveIntegerField(default=0)
    clicked_at = models.DateTimeField(null=True, blank=True)
    click_count = models.PositiveIntegerField(default=0)
    unsubscribed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ('campaign', 'contact')
        ordering = ['-sent_at', 'id']

    def __str__(self):
        return f'{self.campaign_id}:{self.contact.email}'


class EmailEvent(models.Model):
    EVENT_SENT = 'sent'
    EVENT_OPEN = 'open'
    EVENT_CLICK = 'click'
    EVENT_BOUNCE = 'bounce'
    EVENT_UNSUB = 'unsubscribe'
    EVENT_FAILED = 'failed'
    EVENT_CHOICES = [
        (EVENT_SENT, 'Sent'),
        (EVENT_OPEN, 'Opened'),
        (EVENT_CLICK, 'Clicked'),
        (EVENT_BOUNCE, 'Bounced'),
        (EVENT_UNSUB, 'Unsubscribed'),
        (EVENT_FAILED, 'Failed'),
    ]

    recipient = models.ForeignKey(CampaignRecipient, on_delete=models.CASCADE, related_name='events')
    event = models.CharField(max_length=20, choices=EVENT_CHOICES)
    url = models.URLField(max_length=1000, blank=True)
    user_agent = models.CharField(max_length=500, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
