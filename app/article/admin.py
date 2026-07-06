""" admin view """
from django.contrib import admin
from article.models import Blacklist, Feed, Feedlink, Rankwords, Articletopwords, Ticker, Twitter

class BlacklistAdmin(admin.ModelAdmin):
    """ blacklists """
    fields = ['text']
    list_display = ['text']  

class RankwordsAdmin(admin.ModelAdmin):
    """ ranking words """
    fields = ['word', 'rank']
    ordering = ('rank', 'word')

class ArticletopwordsAdmin(admin.ModelAdmin):
    """ optwords """
    fields = ['word', 'count', 'rank']
    list_display = ('rank', 'count', 'word')    
    ordering = ('rank', 'count', 'word')

class FeedAdmin(admin.ModelAdmin):
    """ rss feeds """
    fields = ['name', 'url']
    list_display = ('name', 'url')
    ordering = ('name', 'url')

class FeedlinkAdmin(admin.ModelAdmin):
    """ feedlink """
    fields = ['url', 'date']
    list_display = ('id', 'url', 'date')
    ordering = ('id', 'date', 'url')

class TickerAdmin(admin.ModelAdmin):
    """ ticker """
    fields = ['match', 'min', 'content', 'uts', 'hash']
    list_display = ('match', 'min', 'uts', 'content', 'hash')
    ordering = ('match', 'id', 'min', 'uts', 'content', 'hash')

class TwitterAdmin(admin.ModelAdmin):
    """ twitter """
    fields = ['t_id', 'text', 'url', 'created', 'screen_name']
    list_display = ('t_id', 'text', 'url', 'created', 'screen_name')
    ordering = ('t_id', 'text', 'url', 'created', 'screen_name')

admin.site.register(Blacklist, BlacklistAdmin)
admin.site.register(Feed, FeedAdmin)
admin.site.register(Feedlink, FeedlinkAdmin)
admin.site.register(Rankwords, RankwordsAdmin)
admin.site.register(Articletopwords, ArticletopwordsAdmin)
admin.site.register(Ticker, TickerAdmin)
admin.site.register(Twitter, TwitterAdmin)
