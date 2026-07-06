""" userauth """
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone

class UserProfile(models.Model):
    """ user profile class """
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    activation_key = models.CharField(max_length=40, blank=True)
    # key_expires = models.DateTimeField(default=datetime.date.today())
    key_expires = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return self.user.username

    class Meta(object):
        """ meta class """
        verbose_name_plural = u'User profiles'
