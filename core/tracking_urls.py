from django.urls import path
from . import tracking_views

urlpatterns = [
    path('o/<uuid:token>.gif', tracking_views.open_pixel, name='open_pixel'),
    path('c/<uuid:token>/', tracking_views.click_redirect, name='click_redirect'),
    path('u/<str:token>/', tracking_views.unsubscribe, name='unsubscribe'),
]
