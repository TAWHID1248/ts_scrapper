from django.db import models


class ScrapeJob(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_RUNNING = 'running'
    STATUS_COMPLETED = 'completed'
    STATUS_FAILED = 'failed'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_RUNNING, 'Running'),
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_FAILED, 'Failed'),
    ]

    name = models.CharField(max_length=200, blank=True)
    sites = models.TextField(help_text='One URL per line.')
    max_pages = models.PositiveIntegerField(default=50)
    delay = models.FloatField(default=1.5)
    respect_robots = models.BooleanField(default=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    total_sites = models.PositiveIntegerField(default=0)
    sites_done = models.PositiveIntegerField(default=0)
    emails_found = models.PositiveIntegerField(default=0)
    log = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.name or f'Scrape Job #{self.pk}'

    @property
    def is_active(self) -> bool:
        return self.status in (self.STATUS_PENDING, self.STATUS_RUNNING)

    @property
    def progress_pct(self) -> int:
        if not self.total_sites:
            return 0
        return int(100 * self.sites_done / self.total_sites)
