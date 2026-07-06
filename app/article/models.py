""" modules """
# This is an auto-generated Django model module.
# You'll have to do the following manually to clean this up:
#   * Rearrange models' order
#   * Make sure each model has one field with primary_key=True
#   * Remove `managed = False` lines if you wish to allow Django to create, modify, and delete the table
# Feel free to rename the models, but don't rename db_table values or field names.
#
# Also note: You'll have to insert the output of 'django-admin sqlcustom [app_label]'
# into your database.
from __future__ import unicode_literals
from django.db import models
from django.utils import timezone


class Config(models.Model):
    """ config from wallabag """
    id = models.IntegerField(primary_key=True)
    name = models.TextField(unique=True, blank=True, null=True)  # This field type is a guess.
    value = models.BinaryField(blank=True, null=True)

    class Meta(object):
        """ meta """
        managed = False
        db_table = 'config'

class Entries(models.Model):
    """ entries from wallabag"""
    id = models.IntegerField(primary_key=True, blank=True)  # AutoField?
    title = models.TextField(blank=True, null=True)
    url = models.TextField(blank=True, null=True)
    preview_picture = models.TextField(blank=True, null=True)    
    content = models.BinaryField(blank=True, null=True)
    user_id = models.TextField(blank=True, null=True)  # This field type is a guess.
    created_at = models.DateTimeField(blank=True, null=True)
    def __str__(self):
        return self.name.encode('utf8')

    class Meta(object):
        """ meta """
        managed = False
        db_table = 'wallabag_entry'

class Twitter(models.Model):
    """ twitter """
    id = models.AutoField(primary_key=True)
    t_id = models.BigIntegerField(default=0)
    text = models.CharField(max_length=500, blank=True, null=True)
    url = models.CharField(max_length=30, blank=True, null=True)
    created = models.CharField(max_length=30, blank=True, null=True)
    screen_name = models.CharField(max_length=30, blank=True, null=True)
    uts = models.IntegerField(default=0)
    def __unicode__(self):
        return self.name

class Articletopwords(models.Model):
    """ optwords """
    word = models.CharField(max_length=500, blank=True, null=True)
    count = models.IntegerField(blank=True, null=True)
    rank = models.IntegerField(blank=True, null=True)
    def __unicode__(self):
        return self.word

class Rankwords(models.Model):
    """ rankwords """
    word = models.CharField(max_length=500, blank=True, null=True)
    rank = models.FloatField(default=0)
    def __unicode__(self):
        return self.word

class Tsblog(models.Model):
    """ tagesspiegel blog """
    date = models.CharField(max_length=50, blank=True, null=True)
    content = models.CharField(max_length=20000, blank=True, null=True)
    uts = models.IntegerField(default=0)

class Ticker(models.Model):
    """ ticker """
    match = models.IntegerField(default=0)
    source = models.CharField(max_length=50)
    content = models.CharField(max_length=2000)
    min = models.CharField(max_length=5)
    hash = models.CharField(max_length=50)
    uts = models.IntegerField(default=0)

class Blacklist(models.Model):
    """ blacklist """
    text = models.CharField(max_length=50, blank=True, null=True)
    def __unicode__(self):
        return self.text

class Feed(models.Model):
    """ feed """
    name = models.CharField(max_length=150, blank=True, null=True)
    url = models.CharField(max_length=150, blank=True, null=True)
    def __unicode__(self):
        return self.name

class Feedlink(models.Model):
    """ feedlink """
    url = models.CharField(max_length=250, blank=True, null=True)
    date = models.DateTimeField(default=timezone.now, blank=True)
    def __unicode__(self):
        return self.url

class Tags(models.Model):
    """ tags from wallabag """
    id = models.IntegerField(primary_key=True)  # AutoField?
    value = models.TextField(blank=True, null=True)

    class Meta(object):
        """ meta """
        managed = False
        db_table = 'tags'


class TagsEntries(models.Model):
    """ tag entries from wallabag """
    id = models.IntegerField(primary_key=True)  # AutoField?
    entry_id = models.IntegerField(blank=True, null=True)
    tag = models.ForeignKey(Tags, blank=True, null=True, on_delete=models.CASCADE)

    class Meta(object):
        """ meta """
        managed = False
        db_table = 'tags_entries'

class Users(models.Model):
    """ users from wallabag"""
    id = models.IntegerField(primary_key=True, blank=True)  # AutoField?
    username = models.TextField(blank=True, null=True)
    password = models.TextField(blank=True, null=True)
    name = models.TextField(blank=True, null=True)
    email = models.TextField(blank=True, null=True)

    class Meta(object):
        """ meta """
        managed = False
        db_table = 'users'


class UsersConfig(models.Model):
    """ userconfig from wallabag"""
    id = models.IntegerField(primary_key=True, blank=True)  # AutoField?
    user_id = models.TextField(blank=True, null=True)  # This field type is a guess.
    name = models.TextField(blank=True, null=True)
    value = models.TextField(blank=True, null=True)

    class Meta(object):
        """ meta """
        managed = False
        db_table = 'users_config'
