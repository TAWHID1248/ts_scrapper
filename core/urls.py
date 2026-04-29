from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('settings/', views.settings_view, name='settings'),

    path('contacts/', views.contact_list, name='contact_list'),
    path('contacts/<int:pk>/edit/', views.contact_edit, name='contact_edit'),
    path('contacts/<int:pk>/delete/', views.contact_delete, name='contact_delete'),

    path('lists/', views.list_list, name='list_list'),
    path('lists/new/', views.list_create, name='list_create'),
    path('lists/import/', views.list_import, name='list_import'),
    path('lists/<int:pk>/edit/', views.list_edit, name='list_edit'),
    path('lists/<int:pk>/delete/', views.list_delete, name='list_delete'),

    path('templates/', views.template_list, name='template_list'),
    path('templates/new/', views.template_create, name='template_create'),
    path('templates/<int:pk>/edit/', views.template_edit, name='template_edit'),
    path('templates/<int:pk>/delete/', views.template_delete, name='template_delete'),
    path('templates/<int:pk>/test/', views.template_test_send, name='template_test_send'),

    path('campaigns/', views.campaign_list, name='campaign_list'),
    path('campaigns/new/', views.campaign_create, name='campaign_create'),
    path('campaigns/<int:pk>/', views.campaign_detail, name='campaign_detail'),
    path('campaigns/<int:pk>/edit/', views.campaign_edit, name='campaign_edit'),
    path('campaigns/<int:pk>/delete/', views.campaign_delete, name='campaign_delete'),
    path('campaigns/<int:pk>/send/', views.campaign_send, name='campaign_send'),
]
