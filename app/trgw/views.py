""" views.py """
# -*- coding: utf-8 -*-
import datetime
from pytz import timezone
from django.shortcuts import render
from django.conf import settings
from django.http import Http404, HttpResponseRedirect
from django.views.decorators.csrf import csrf_exempt
from trgw.models import Threemamessage, Threemacredit
from game.models import Usersetting, Groupsetting
from game.myfunctions import parse_message, parse_location, send_threema
from game.libthreema import tr_lookup_pubkey, decode_key, decrypt

TIMEZONE = timezone('Europe/Berlin')

@csrf_exempt
def index(request):
    """ index """
    data_dic = {}
    request_type = 'get'
    if request.method == 'POST':
        request_type = 'post'

        # get public key from user profile
        try:
            sender = request.POST['from']
            usettings = Usersetting.objects.filter(threema=sender).values('threema_pk', 'threema_reminder', 'mobile_number', 'group_id__name')
            pkey = usettings[0]['threema_pk']
            threema_reminder = bool(usettings[0]['threema_reminder'])
            mobile_number = usettings[0]['mobile_number'].replace(' ', '')
            g_name = usettings[0]['group_id__name']
            source = Groupsetting.objects.filter(group__name=g_name).values_list('number', flat=True)[0]
            source = source + '@threema'
        except BaseException:
            pkey = None
            threema_reminder = False
            mobile_number = None

        if threema_reminder:

            if(pkey == '' or pkey is None):
                # fetch pub key and update db
                pkey = tr_lookup_pubkey(sender, settings.TR_ID, settings.TR_SECRET)
                if pkey:
                    obj, _created = Usersetting.objects.update_or_create(threema=sender, defaults={'threema_pk': pkey})
                    obj.save()

            if(pkey and mobile_number):
                private_key = decode_key(settings.TR_SK)
                public_key = decode_key(pkey)
                try:
                    (mtype, text) = decrypt(private_key, public_key, request.POST['nonce'], request.POST['box'])
                    # text = 'Wer ist raus?'
                    reply = None
                    message = None
                    if(text and mtype == b'\x01'):
                        (reply, message) = parse_message(text, mobile_number, source, request.POST['date'])
                    elif(text and mtype == b'\x10'):
                        (latitude, longitude, _sinin) = text.split(',', 2)
                        (reply, message) = parse_location(latitude, longitude, mobile_number)

                except BaseException:
                    text = None
                    message = None

            if(reply and message):
                message = message.decode('utf-8').encode('utf-8')
                # print(message)
                send_threema(settings.TR_ID, settings.TR_SECRET, settings.TR_SK, sender, message)


        for postkey in request.POST:
            data_dic[postkey] = request.POST[postkey]

        try:
            obj = Threemamessage(box=request.POST['box'],
                                 nonce=request.POST['nonce'],
                                 source=request.POST['from'],
                                 to=request.POST['to'],
                                 mac=request.POST['mac'],
                                 messageId=request.POST['messageId'],
                                 date=request.POST['date'])
            # obj.save()
            return render(request, 'trgw/index.html', {'request_type': request_type, 'data_dic': data_dic,})
        except BaseException:
            raise Http404

    else:
        return render(request, 'trgw/index.html', {'request_type': request_type, 'data_dic': data_dic,})

def credits(request):
    """ credits """
    if request.user.is_authenticated():

        trc_list = Threemacredit.objects.order_by('date').values()

        # current credit saldo
        current_credits = trc_list[len(trc_list)-1]['credit']
        current_date = datetime.datetime.fromtimestamp(trc_list[len(trc_list)-1]['date'], tz=TIMEZONE).strftime('%d.%m.%Y %H:%M:%S')

        week = ['So', 'Mo.', 'Di.', 'Mi.', 'Do.', 'Fr.', 'Sa.']

        date_list = []
        delta_list = []
        credit_list = []
        list_counter = 0
        for trc in trc_list:
            trc['date_human'] = datetime.datetime.fromtimestamp(trc['date'], tz=TIMEZONE).strftime('%d.%m')
            trc['wd'] = week[int(datetime.datetime.fromtimestamp(trc['date'], tz=TIMEZONE).strftime('%w'))]
            if list_counter == 0:
                trc['delta'] = 0
            else:
                trc['delta'] = trc_list[list_counter - 1]['credit'] - trc['credit']

            list_counter = list_counter + 1
            if trc['delta'] != 0:
                date_list.append(trc['date_human'])
                delta_list.append(int(trc['delta']))
                credit_list.append(int(trc['credit']))

        # check if access comes from mobile
        mobile_browser = request.mobile

        # prepare some variables neededfor the chart
        label_size = '10px'
        show_legend = 1

        # we need to change some setting for mobile access
        if mobile_browser:
            label_size = '8px'
            show_legend = 0

        chart_options = {

            'chart': {
                'type': 'column',
            },

            'title': {
                'text': 'Threema Credits',
                'style': {'color': '#404040', 'font-size': '12px'},
            },

            'legend': {
                'enabled': show_legend,
            },

            'tooltip': {
                'shared': 1,
                'headerFormat': '<b>{point.x}:</b><br>',
                'pointFormat':  '{point.y}<br>',
            },

            'xAxis': {
                'categories': date_list,
                'title': {
                    'text': 'Spieltag',
                    'style': {'color': '#404040', 'font-size': label_size},
                },
                'crosshair': 1,
            },

            'yAxis':[{
                'title': {
                    'text': 'verbrauchte Credits',
                    'style': {'color': '#404040', 'font-size': label_size},
                },
            }, {
                'title': {
                    'text': 'Kontostand',
                    'style': {'color': '#404040', 'font-size': label_size},
                },
                'opposite': 1,
                'min': 1,
                'max': 7000,
            }],

            'series': [{
                'name': 'verbrauchte Credits',
                'data': delta_list,
                'dataLabels': {
                    'enabled': 0,
                    'style': {
                        'color': '#404040',
                    }
                },
                'tooltip': {
                    'valueSuffix': ' Credits verbraucht'
                },
                'color': '#7cb5ec',

            }, {
                'type': 'spline',
                'name': 'Kontostand',
                'data': credit_list,
                'color': '#030357',
                'yAxis': 1,
                'tooltip': {
                    'valueSuffix': ' Credits verfuegbar'
                },
            }],
        }

        return render(request, 'trgw/credits.html', {
            'title': 'Tippgame|Threemacredits',
            'current_credits': current_credits,
            'current_date': current_date,
            'trc_list': sorted(trc_list),
            'chart_options': chart_options})
    else:
        return HttpResponseRedirect('%s?next=%s' % (settings.LOGIN_URL, request.path))
