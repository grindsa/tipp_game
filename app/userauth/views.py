""" views.py """
# -*- coding: utf-8 -*-
from __future__ import absolute_import
import json
import time
import hashlib
import random
from datetime import datetime, timedelta
from django.shortcuts import render
# from django.contrib.auth.views import password_reset, password_reset_confirm
from django.http import HttpResponseRedirect, HttpResponse
from django.shortcuts import get_object_or_404
# from django import forms
# from models import *
# from django.contrib.auth.forms import UserCreationForm
from django.conf import settings
# from django.template import RequestContext
from django.core.mail import send_mail
from django.utils import timezone
from django.contrib.auth.models import User
from captcha.models import CaptchaStore
from captcha.helpers import captcha_image_url
from userauth.models import UserProfile
from .forms import UserCreateForm

try:
    from game.wa_hack_cli import simple_send
except ImportError:
    pass

def logout_page(request):
    """ logout """
    logout(request)
    return HttpResponseRedirect(request.GET.get('next', '/'))

def register(request):
    """ register """
    # get host
    host = request.META['HTTP_HOST']
    # form = UserCreateForm()
    if request.GET and 'refresh_captcha' in request.GET:
        to_json_responce = dict()
        to_json_responce['new_cptch_key'] = CaptchaStore.generate_key()
        to_json_responce['new_cptch_image'] = captcha_image_url(to_json_responce['new_cptch_key'])
        return HttpResponse(json.dumps(to_json_responce), content_type='application/json')

    if request.method == 'POST':
        form = UserCreateForm(request.POST)
        if form.is_valid():
            form.save()  # save user to database if form is valid

            username = form.cleaned_data['username']
            email = form.cleaned_data['email']
            salt = hashlib.sha1(str(random.random()).encode()).hexdigest()[:5]
            activation_key = hashlib.sha1(salt.encode()+email.encode()).hexdigest()
            key_expires = datetime.today()  + timedelta(2)

            #Get user by username
            user = User.objects.get(username=username)

            # Create and save user profile
            new_profile = UserProfile(user=user, activation_key=activation_key, key_expires=key_expires)
            new_profile.save()

            # Send email with activation key
            email_subject = u'Restrierungsbestätigung'
            email_body = u'Hallo %s, Danke für deine Registrierung. Um deinen Account zu aktivieren, rufe bitte in den nächsten 48 Stunden diesen Link auf http://%s/user/confirm/%s/' % (username, host, activation_key)
            send_mail(email_subject, email_body, 'myemail@example.com', [email], fail_silently=False)

            if(hasattr(settings, 'WA_ADMIN_NUMBER') and hasattr(settings, 'WA_SRV') and hasattr(settings, 'WA_PORT')):
                # send whatsapp message to admin number indicating user registration
                lti = time.strftime("%d.%m.%Y %H:%M:%S")
                message = lti+' user registration: '+username+' email:'+email
                simple_send(settings.WA_SRV, settings.WA_PORT, settings.WA_ADMIN_NUMBER, message)

            return render(request, "userauth/registration_done.html", {'username': username, 'email': email})

        else:
            username = None
            email = None
            if 'username' in request.POST:
                username = request.POST['username']
            if 'email' in request.POST:
                email = request.POST['email']
            error = form.errors
            error_txt = form.errors.as_text
            form = UserCreateForm()

            if(hasattr(settings, 'WA_ADMIN_NUMBER') and hasattr(settings, 'WA_SRV') and hasattr(settings, 'WA_PORT')):
                # send whatsapp message to admin number indicating a problem
                lti = time.strftime("%d.%m.%Y %H:%M:%S")
                message = lti +' user registration failed: '+str(username)+" email: "+email+" error:"+str(error_txt)
                simple_send(settings.WA_SRV, settings.WA_PORT, settings.WA_ADMIN_NUMBER, message)

            return render(request, "userauth/register.html", {
                'username': username,
                'email': email,
                'error': error,
                'form' : form})
    else:
        form = UserCreateForm()
        return render(request, "userauth/register.html", {'form': form})

def register_confirm(request, activation_key):
    """ register confirm """
    #check if user is already logged in and if he is redirect him to '/'
    if request.user.is_authenticated:
        return HttpResponseRedirect('/')
    else:
        # check if there is UserProfile which matches the activation key (if not then display 404)
        user_profile = get_object_or_404(UserProfile, activation_key=activation_key)

        #check if the activation key has expired, if it hase then render confirm_expired.html
        if user_profile.key_expires < timezone.now():
            return render('user/confirm_expired.html')

        else:
            #if the key hasn't expired save user and set him as active and render some template to confirm activation
            user = user_profile.user
            user.is_active = True
            user.save()

            if(hasattr(settings, 'WA_ADMIN_NUMBER') and hasattr(settings, 'WA_SRV') and hasattr(settings, 'WA_PORT')):
                usr = User.objects.get(username=user)
                email = usr.email

                # send whatsapp message to admin number indicating user registration
                lti = time.strftime("%d.%m.%Y %H:%M:%S")
                message = lti +' user activation: '+str(user)+' '+email
                simple_send(settings.WA_SRV, settings.WA_PORT, settings.WA_ADMIN_NUMBER, message)

            # after user activation remove entry from UserProfile table
            UserProfile.objects.filter(activation_key=activation_key).delete()

            return render(request, "userauth/account_activated.html", {
                'user': str(user)})
