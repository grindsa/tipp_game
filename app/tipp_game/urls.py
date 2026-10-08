from django.urls import include, re_path
from django.contrib import admin
from django.conf import settings
from django.views.static import serve as static_serve
from game import views as game_views
from django_otp.admin import OTPAdminSite
admin.site.__class__ = OTPAdminSite
urlpatterns = [
    re_path(r'^$', game_views.index, name='index'),
	re_path(r'^game/',include('game.urls')),
    re_path(r'^article/',include('article.urls')),
    re_path(r'^admin/', admin.site.urls),
	re_path(r'^user/', include('userauth.urls')),
	re_path(r'^captcha/', include('captcha.urls')),
    re_path(r'^trgw/', include('trgw.urls')),
]

# Dev hack: serve STATIC_ROOT even when DEBUG=False (runserver / local).
# django.conf.urls.static.static() is a no-op unless DEBUG is True.
urlpatterns += [
    re_path(r'^static/(?P<path>.*)$', static_serve, {'document_root': settings.STATIC_ROOT}),
]

handler404 = game_views.error_404
handler500 = game_views.error_500
