import logging

from django.contrib.auth.signals import user_login_failed
from django.dispatch import receiver


auth_logger = logging.getLogger('auth_failures')


def _safe_value(value):
    if value is None:
        return 'unknown'
    return str(value).replace('\n', ' ').replace('\r', ' ').strip()


def _client_ip(request):
    if request is None:
        return 'unknown'

    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()

    return request.META.get('REMOTE_ADDR', 'unknown')


@receiver(user_login_failed)
def log_user_login_failed(sender, credentials, request=None, **kwargs):
    username = (
        credentials.get('username')
        or credentials.get('email')
        or credentials.get('userid')
        or 'unknown'
    )

    auth_logger.warning(
        'LOGIN_FAILED ip=%s username=%s path=%s',
        _safe_value(_client_ip(request)),
        _safe_value(username),
        _safe_value(getattr(request, 'path', 'unknown')),
    )
