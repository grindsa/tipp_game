#!/usr/bin/python3
# -*- coding: utf-8 -*-
""" check threema credits and
 - send warning via WA if remaining credits are less than 10
 - upadte table threma_credit """
from __future__ import absolute_import
import os
import sys
import time
import six.moves.urllib.request
import six.moves.urllib.parse
import six.moves.urllib.error
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir)))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tipp_game.settings")
import django
django.setup()
from django.conf import settings
from wa_hack_cli import simple_send
from trgw.models import Threemacredit

if __name__ == "__main__":

    # unix timestamp
    UTS = int(time.time())
    URL = 'https://msgapi.threema.ch/credits?from={0}&secret={1}'.format(settings.TR_ID, settings.TR_SECRET)
    THRESHOLD = 10

    FSO = six.moves.urllib.request.urlopen(URL)
    NUM = int(FSO.read())
    OBJ = Threemacredit(date=UTS, credit=NUM)
    OBJ.save()

    if(NUM < THRESHOLD and hasattr(settings, 'WA_ADMIN_NUMBER') and hasattr(settings, 'WA_SRV') and hasattr(settings, 'WA_PORT')):
        # send whatsapp message to group owner indicating user add
        LTS = time.strftime("%d.%m.%Y %H:%M:%S")
        MESSAGE = LTS+' Achtung: nur noch {0} Threema-Credits übrig...'.format(NUM)
        simple_send(settings.WA_SRV, settings.WA_PORT, settings.WA_ADMIN_NUMBER, MESSAGE)
