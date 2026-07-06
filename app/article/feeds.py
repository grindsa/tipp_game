""" feeds """
# -*- coding: utf-8 -*-
from __future__ import absolute_import
from urllib.parse import urlparse
from django.contrib.syndication.views import Feed
from article.models import Entries

class LatestEntries(Feed):
    """ feeds """
    title = "Dynamop Presseschau - letze Artikel"
    link = "/"

    @staticmethod
    def items():
        """ items """
        return list(Entries.objects.using('wallabag').order_by('-id').values())[:50]

    def item_title(self, item):
        """ item title """
        source = urlparse(item['url']).hostname
        source = source.replace('www.', '')
        source = source.replace('m.', '')
        source = source.replace('mobil.', '')
        return source+' - '+item['title']

    def item_link(self, item):
        """ link """
        return '/article/showarticle?id={0}'.format(item['id'])

    def item_description(self, item):
        """ description """
        return item['content']
