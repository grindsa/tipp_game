""" ulrs """
from django.urls import re_path
from trgw import views

urlpatterns = [
    re_path(r'^$', views.index, name='index'),
    re_path(r'^credits$', views.credits, name='credits'),
]
