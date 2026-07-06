""" admin.py """
from django.contrib import admin

# Register your models here.
from trgw.models import Threemamessage, Whatsappmessage, Threemacredit

class ThreemamessageAdmin(admin.ModelAdmin):
    """ treema admin """
    fields = ['date', 'source', 'to', 'messageId', 'nonce', 'box', 'mac']
    list_display = ('date', 'source', 'to', 'messageId', 'nonce', 'box', 'mac')
    ordering = ('date', )

class WhatsappmessageAdmin(admin.ModelAdmin):
    """ wa admin """
    fields = ['date', 'source', 'sender', 'text']
    list_display = ('date', 'source', 'sender', 'text')
    ordering = ('date', )

class ThreemacreditAdmin(admin.ModelAdmin):
    """ credit """
    list_display = ('id', 'date', 'credit')
    ordering = ('id', 'date', 'credit')

admin.site.register(Whatsappmessage, WhatsappmessageAdmin)
admin.site.register(Threemamessage, ThreemamessageAdmin)
admin.site.register(Threemacredit, ThreemacreditAdmin)
