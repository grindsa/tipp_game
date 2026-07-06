""" urls """
from django.urls import re_path
from django.contrib.auth import views as auth_views
from userauth import views

urlpatterns = [
    re_path(r'^login',auth_views.LoginView.as_view(template_name='userauth/login.html'), name='userauth_login'),     
    re_path(r'^logout/$', auth_views.LogoutView.as_view(),name='userauth_logout'),    
    re_path(r'^change-password/$', auth_views.PasswordChangeView.as_view(template_name='userauth/password_change_form.html'), name='userauth_password_change'),    
    re_path(r'^password-changed/$', auth_views.PasswordChangeDoneView.as_view(template_name='userauth/password_change_done.html'), name='password_change_done'),
    # re_path(r'^register/$', views.register, name='register'),
    # re_path(r'^confirm/(?P<activation_key>\w+)/', views.register_confirm, name='register_confirm'),
]
