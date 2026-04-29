from django.contrib import messages
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from .forms import ScrapeJobForm
from .models import ScrapeJob
from .tasks import start_scrape_job


def job_list(request):
    jobs = ScrapeJob.objects.all()[:100]
    return render(request, 'scraper/job_list.html', {'jobs': jobs})


def job_create(request):
    if request.method == 'POST':
        form = ScrapeJobForm(request.POST)
        if form.is_valid():
            job = form.save()
            start_scrape_job(job.pk)
            messages.success(request, f'Scrape job "{job}" started.')
            return redirect('scraper:job_detail', pk=job.pk)
    else:
        form = ScrapeJobForm(initial={'max_pages': 50, 'delay': 1.5, 'respect_robots': True})
    return render(request, 'scraper/job_form.html', {'form': form})


def job_detail(request, pk):
    job = get_object_or_404(ScrapeJob, pk=pk)
    return render(request, 'scraper/job_detail.html', {'job': job})


def job_delete(request, pk):
    if request.method != 'POST':
        return HttpResponseBadRequest()
    job = get_object_or_404(ScrapeJob, pk=pk)
    if job.is_active:
        messages.error(request, "Can't delete a running job. Wait for it to finish.")
        return redirect('scraper:job_detail', pk=pk)
    job.delete()
    messages.success(request, 'Scrape job deleted.')
    return redirect('scraper:job_list')


def job_rerun(request, pk):
    if request.method != 'POST':
        return HttpResponseBadRequest()
    old = get_object_or_404(ScrapeJob, pk=pk)
    new_job = ScrapeJob.objects.create(
        name=old.name,
        sites=old.sites,
        max_pages=old.max_pages,
        delay=old.delay,
        respect_robots=old.respect_robots,
    )
    start_scrape_job(new_job.pk)
    messages.success(request, f'Restarted as job #{new_job.pk}.')
    return redirect('scraper:job_detail', pk=new_job.pk)


def job_status(request, pk):
    job = get_object_or_404(ScrapeJob, pk=pk)
    return JsonResponse({
        'status': job.status,
        'sites_done': job.sites_done,
        'total_sites': job.total_sites,
        'emails_found': job.emails_found,
        'progress_pct': job.progress_pct,
        'log': job.log,
        'is_active': job.is_active,
    })
