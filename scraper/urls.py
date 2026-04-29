from django.urls import path
from . import views

app_name = 'scraper'

urlpatterns = [
    path('', views.job_list, name='job_list'),
    path('new/', views.job_create, name='job_create'),
    path('<int:pk>/', views.job_detail, name='job_detail'),
    path('<int:pk>/status/', views.job_status, name='job_status'),
    path('<int:pk>/delete/', views.job_delete, name='job_delete'),
    path('<int:pk>/rerun/', views.job_rerun, name='job_rerun'),
]
