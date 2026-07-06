"""
WSGI config for tipp_game project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/1.7/howto/deployment/wsgi/
"""

import os
import sys

project_home = '/var/www/tipp_game'

if project_home not in sys.path:
    sys.path.append(project_home)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tipp_game.settings")
# os.environ["DJANGO_SETTINGS_MODULE"] = "{{ tipp_game }}.settings"

from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
