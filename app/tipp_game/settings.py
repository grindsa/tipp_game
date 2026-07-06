"""
Django settings for tipp_game project.
"""
# Build paths inside the project like this: os.path.join(BASE_DIR, ...)
import os
from django.core.exceptions import ImproperlyConfigured
BASE_DIR = os.path.dirname(os.path.dirname(__file__))
AUTH_LOG_DIR = os.path.join(BASE_DIR, 'logs')
AUTH_LOG_FILE = os.path.join(AUTH_LOG_DIR, 'auth.log')
AUTH_LOG_TO_FILE = True

# Try to initialize the auth log path. If host volume permissions block writes,
# fall back to console logging so the app can still boot.
try:
    os.makedirs(AUTH_LOG_DIR, exist_ok=True)
    with open(AUTH_LOG_FILE, 'a', encoding='utf-8') as auth_log_probe:
        auth_log_probe.write('')
except OSError:
    AUTH_LOG_TO_FILE = False

AUTH_FAILURE_LOGGER_HANDLERS = ['auth_failures_console']
if AUTH_LOG_TO_FILE:
    AUTH_FAILURE_LOGGER_HANDLERS.insert(0, 'auth_failures_file')


def env_bool(name, default=False):
    """Parse common boolean environment values."""
    return os.environ.get(name, str(default)).lower() in ['true', '1', 'yes', 'on']


DJANGO_ENV = os.environ.get('DJANGO_ENV', 'development').lower()
IS_PRODUCTION = DJANGO_ENV in ['prod', 'production']

# Read the secret key from environment and fail fast in production if missing.
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY')
if not SECRET_KEY:
    if IS_PRODUCTION:
        raise ImproperlyConfigured('DJANGO_SECRET_KEY must be set in production')
    SECRET_KEY = 'django-insecure-dev-only-change-me'

# Keep development convenient, but default to safe values in production.
DEBUG = env_bool('DJANGO_DEBUG', default=(not IS_PRODUCTION))

# In development/non-production allow any host.
if IS_PRODUCTION:
    ALLOWED_HOSTS = [
        host.strip()
        for host in os.environ.get('DJANGO_ALLOWED_HOSTS', '').split(',')
        if host.strip()
    ]
else:
    ALLOWED_HOSTS = ['*']

# TEMPLATE_DEBUG = True
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [
            os.path.join(BASE_DIR, 'templates'),
        ],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'django.template.context_processors.media'
            ],
        },
    },
]

TEMPLATE_CONTEXT_PROCESSORS = (
    "django.contrib.auth.context_processors.auth",
    "django.core.context_processors.debug",
    "django.core.context_processors.i18n",
    "django.core.context_processors.media",
    "django.core.context_processors.request",
    "django.core.context_processors.static",
)

# Application definition

INSTALLED_APPS = (
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django_otp',
    'django_otp.plugins.otp_totp',
    'game',
    'userauth.apps.UserauthConfig',
    'captcha',
    'article',
    'trgw',
)

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django_otp.middleware.OTPMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'mobi.middleware.MobileDetectionMiddleware',
]

ROOT_URLCONF = 'tipp_game.urls'

WSGI_APPLICATION = 'tipp_game.wsgi.application'

LOGIN_URL = '/user/login/'
LOGOUT_URL = '/user/logout/'
LOGIN_REDIRECT_URL = '/game/'


DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': os.environ.get('DB_NAME', 'my_django_db'),
        'USER': os.environ.get('DB_USER', 'django_user'),
        'PASSWORD': os.environ.get('DB_PASSWORD', ''),
        'HOST': os.environ.get('DB_HOST', 'tgdb'),
        'PORT': os.environ.get('DB_PORT', '3306'),
        'OPTIONS': {"init_command": "SET sql_mode='STRICT_TRANS_TABLES', innodb_strict_mode=1","charset": "utf8mb4", "use_unicode": True},
    },
    'wallabag': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': os.environ.get('WB_NAME', 'django_user'),
        'USER': os.environ.get('WB_USER', 'django_user'),
        'PASSWORD': os.environ.get('WB_PASSWORD', ''),
        'HOST': os.environ.get('DB_HOST', 'tgdb'),
        'OPTIONS': {"init_command": "SET sql_mode='STRICT_TRANS_TABLES', innodb_strict_mode=1","charset": "utf8mb4", "use_unicode": True},
    }
}

# Internationalization
# https://docs.djangoproject.com/en/1.7/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_L10N = True

USE_TZ = True

LOGGING = {
	'version': 1,
	'disable_existing_loggers': False,
	'filters': {
		'require_debug_false': {
			'()': 'django.utils.log.RequireDebugFalse',
		},
		'require_debug_true': {
			'()': 'django.utils.log.RequireDebugTrue',
		},
	},
	'formatters': {
		'django.server': {
			'()': 'django.utils.log.ServerFormatter',
			'format': '[%(server_time)s] %(message)s',
        },
        'auth.fail2ban': {
            'format': '%(asctime)s %(message)s',
            'datefmt': '%Y-%m-%dT%H:%M:%S%z',
        }
	},
	'handlers': {
		'console': {
			'level': 'INFO',
			'filters': ['require_debug_true'],
			'class': 'logging.StreamHandler',
		},
		'console_debug_false': {
			'level': 'ERROR',
			'filters': ['require_debug_false'],
			'class': 'logging.StreamHandler',
		},
		'django.server': {
			'level': 'INFO',
			'class': 'logging.StreamHandler',
			'formatter': 'django.server',
		},
		'mail_admins': {
			'level': 'ERROR',
			'filters': ['require_debug_false'],
			'class': 'django.utils.log.AdminEmailHandler'
        },
        'auth_failures_console': {
            'level': 'WARNING',
            'class': 'logging.StreamHandler',
            'formatter': 'auth.fail2ban',
        },
        'auth_failures_file': {
            'level': 'WARNING',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': AUTH_LOG_FILE,
            'maxBytes': 10485760,
            'backupCount': 5,
            'delay': True,
            'formatter': 'auth.fail2ban',
		}
	},
	'loggers': {
		'django': {
			'handlers': ['console', 'console_debug_false', 'mail_admins'],
			'level': 'INFO',
		},
		'django.server': {
			'handlers': ['django.server'],
			'level': 'INFO',
			'propagate': False,
        },
        'auth_failures': {
            'handlers': AUTH_FAILURE_LOGGER_HANDLERS,
            'level': 'WARNING',
            'propagate': False,
		}
	}
}

STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'static')

SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')


# email settings
EMAIL_USE_TLS = os.environ.get('EMAIL_USE_TLS', 'True').lower() in ['true', '1', 'yes']
EMAIL_HOST = os.environ.get('EMAIL_HOST', 'EMAIL_HOST')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', 587))
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', 'EMAIL_HOST_USER')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
ADMINS = os.environ.get('ADMINS', 'ADMINS,ADMINS@localhost').split(',')
MAILER_LIST = os.environ.get('MAILER_LIST', 'MAILER_LIST,MAILER_LIST@localhost').split(',')
DEFAULT_FROM_EMAIL = EMAIL_HOST_USER
SERVER_EMAIL = EMAIL_HOST_USER

# CAPTCHA_CHALLENGE_FUNCT = 'captcha.helpers.math_challenge'
CAPTCHA_LETTER_ROTATION = None

# whatsapp credentials
WA_SRV = os.environ.get('WA_SRV', 'WA_SRV')
WA_PORT = int(os.environ.get('WA_PORT', 9009))
WA_ADMIN_NUMBER = os.environ.get('WA_ADMIN_NUMBER', 'WA_ADMIN_NUMBER')

# threema credentials
TR_ID = os.environ.get('TR_ID', 'TR_ID')
TR_SECRET = os.environ.get('TR_SECRET', '')
TR_SK = os.environ.get('TR_SK', '')

# MBA location for presence check
MBA_GEO_LOCATION = '52.5060000,13.4434000'
GEO_THRESHOLD    = 0.006

OTP_TOTP_ISSUER = os.environ.get('EMAIL_HOST', 'EMAIL_HOST')

# some security settings
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_HTTPONLY = True
SECURE_HSTS_SECONDS = 31536001 if not DEBUG else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG

# Keep legacy integer primary keys during migration to newer Django.
DEFAULT_AUTO_FIELD = 'django.db.models.AutoField'
