""" forms.py """
from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm
from captcha.fields import CaptchaField

class UserCreateForm(UserCreationForm):
    """ usercreate form """
    email = forms.EmailField(required=True)
    captcha = CaptchaField()

    class Meta(object):
        """ meta class """
        model = User
        fields = ("username", "email", "password1", "password2")

    def save(self, commit=True):
        """ save """
        user = super(UserCreateForm, self).save(commit=False)
        user.email = self.cleaned_data["email"]

        if commit:
            user.is_active = False # not active until he opens activation link
            user.save()
        return user

    def clean_email(self):
        """ clean email """
        email = self.cleaned_data["email"]
        try:
            User._default_manager.get(email=email)
        except User.DoesNotExist:
            return email
        raise forms.ValidationError('duplicate email')
