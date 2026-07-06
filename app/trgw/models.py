""" models """
from django.db import models

# Create your models here.
class Threemamessage(models.Model):
    """ threema """
    source = models.CharField(max_length=8, blank=True, null=True)
    to = models.CharField(max_length=8, blank=True, null=True)
    messageId = models.CharField(max_length=16, blank=True, null=True)
    date = models.CharField(max_length=16, blank=True, null=True)
    nonce = models.CharField(max_length=100, blank=True, null=True)
    box = models.CharField(max_length=8000, blank=True, null=True)
    mac = models.CharField(max_length=100, blank=True, null=True)

class Whatsappmessage(models.Model):
    """ wa """
    source = models.CharField(max_length=50, blank=True, null=True)
    sender = models.CharField(max_length=50, blank=True, null=True)
    date = models.CharField(max_length=16, blank=True, null=True)
    text = models.CharField(max_length=250, blank=True, null=True)

class Threemacredit(models.Model):
    """ credits """
    date = models.IntegerField()
    credit = models.IntegerField()
