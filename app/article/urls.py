""" urls """
from django.urls import re_path
from article import views, feeds

urlpatterns = [
    re_path(r'^$', views.index, name='index'),
    re_path(r'^showarticle$', views.showarticle, name='showarticle'),
    re_path(r'^statistics$', views.statistics, name='statistics'),
    re_path(r'^rss/', feeds.LatestEntries()),
    re_path(r'^ticker/', views.ticker, name='ticker'),
    ]
