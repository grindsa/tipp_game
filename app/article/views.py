# -*- coding: utf-8 -*-
""" views.py """
from __future__ import absolute_import
import datetime
import time
import textwrap
from urllib.parse import urlparse
from pytz import timezone
from django.shortcuts import render
from django.shortcuts import redirect
from django.http import HttpResponseRedirect
from django.conf import settings
from article.models import Entries, Twitter, Ticker
from article.myfunctions import get_month_name, get_next_previous_month_strings, strip_tags, get_month_string, get_week_dates, get_date_range, get_wordcloud_data, get_word_chart_data, get_twittercloud_data, create_cw_chart, create_source_chart
from game.models import Lineup, Match
from game.myfunctions import get_u_data, get_sleep_counter, shorten_lineup, get_last_match

# reload(sys)
# sys.setdefaultencoding('utf8')

TIMEZONE = timezone('Europe/Berlin')

def index(request):
    """ index """
    if request.user.is_authenticated:
        twitter = None
        news = None
        tweet_filter = None
        afilter = None

        # get season id, season list and primary group
        (u_season_id, season_list, _group_filter, _user_groups, dsgvo_ack) = get_u_data(request)

        # identify UA to detect mobiles
        if request.mobile:
            if 'twitter' in request.GET:
                twitter = request.GET['twitter']
            if not twitter:
                news = 1
        else:
            twitter = 1
            news = 1

        if 'tweet_filter' in request.GET:
            tweet_filter = request.GET['tweet_filter']

        if 'afilter' in request.GET:
            afilter = request.GET['afilter']

        # get acutal month string
        actual_month_string = datetime.datetime.now().strftime("%y-%m")

        # get month string and month_name
        if 'month' in request.GET:
            month_string = request.GET['month']
        else:
            month_string = actual_month_string

        try:
            month_name = get_month_name(month_string)
        except BaseException:
            month_string = actual_month_string
            month_name = get_month_name(actual_month_string)

        (next_month_str, prev_month_str) = get_next_previous_month_strings(month_string)

        # get first and last day of month
        (first_day_of_month, last_day_of_month) = get_date_range(month_string)

        entry_list = []
        if afilter:
            entry_list = list(Entries.objects.using('wallabag').filter(content__icontains=afilter, created_at__range=(first_day_of_month, last_day_of_month)).order_by('-id').values())
        else:
            entry_list = list(Entries.objects.using('wallabag').filter(created_at__range=(first_day_of_month, last_day_of_month)).order_by('-id').values())

        entry_dic = {}
        uts_dic = {}
        sort_dic = {}
        sort_week_list = []

        next_mon_counter = 0
        prev_mon_counter = 0

        for entry in entry_list:
            entry_dic[entry['id']] = {}
            entry_dic[entry['id']]['title'] = textwrap.shorten(entry['title'], width=60)
            if entry['preview_picture']:
                entry_dic[entry['id']]['preview_picture'] = entry['preview_picture']
                content = textwrap.shorten(strip_tags(entry['content']), width=130)
            else:
                content = textwrap.shorten(strip_tags(entry['content']), width=420)

            try:
                entry_dic[entry['id']]['content'] = content
            except BaseException:
                entry_dic[entry['id']]['content'] = ''

            entry_dic[entry['id']]['source'] = '{uri.scheme}://{uri.netloc}/'.format(uri=urlparse(entry['url']))
            if entry['created_at']:
                # get ariticle date and store it in hash
                (a_date, _time) = str(entry['created_at']).split()
                (a_year, a_mon, a_day) = a_date.split('-')
                # change date
                entry_dic[entry['id']]['date'] = '{0}.{1}.{2}'.format(a_day, a_mon, a_year)

                # get month string
                e_month_string = get_month_string(entry['created_at'])

                if e_month_string == next_month_str:
                    next_mon_counter = next_mon_counter + 1
                elif e_month_string == prev_month_str:
                    prev_mon_counter = prev_mon_counter + 1

                # get calendar week
                cweek = datetime.date(entry['created_at'].year, entry['created_at'].month, entry['created_at'].day).isocalendar()[1]

                # get week-days based on calendar week
                (fday, lday) = get_week_dates(entry['created_at'])
                (fyear, fmonth, fday) = str(fday).split('-')
                (lyear, lmonth, lday) = str(lday).split('-')
                week = '%s.%s.%s - %s.%s.%s' % (fday, fmonth, fyear, lday, lmonth, lyear)

                # generate week-days from weeknumbers
                if cweek not in uts_dic:
                    # get days per week
                    uts_dic[cweek] = week

                if week not in sort_dic:
                    sort_dic[week] = []

                if week not in sort_week_list:
                    sort_week_list.append(week)

                sort_dic[week].append(entry['id'])

        # unix timestamp
        uts = int(time.time())
        # time-threshold to show tweets (filter to last two weeks)
        timeframe = 14 * 86400
        threshold = uts - timeframe

        # get twitter feeds
        if tweet_filter:
            tweet_list = list(Twitter.objects.filter(uts__gte=threshold, text__icontains=tweet_filter).order_by('-uts').values())
        else:
            tweet_list = list(Twitter.objects.filter(uts__gte=threshold).order_by('-uts').values())

        # collect input for bubble map
        top_tweet_list = list(Twitter.objects.filter(uts__gte=threshold).order_by('-uts').values())
        bubble_data = get_word_chart_data(top_tweet_list, twitter, 'text')
        twittercloud_data = get_twittercloud_data(top_tweet_list, twitter, 'text')

        # get days till next home-match
        sleep_message = get_sleep_counter(request)

        # get data for word cloud list
        wordcloud_list = get_wordcloud_data(request, afilter)

        if actual_month_string == month_string:
            next_month_str = None

        if not dsgvo_ack:
            return HttpResponseRedirect('%s?next=%s' % ('/game/dgsvo', request.path))
        else:
            return render(request, 'article/index.html', {
                'title': 'EBB-Archiv|Presseschau',
                'entry_dic': entry_dic,
                'tweet_list': tweet_list,
                'twitter': twitter,
                'news': news,
                'sort_dic': sort_dic,
                'sort_week_list': sort_week_list,
                'sleep_message': sleep_message,
                'next_month_string': next_month_str,
                'previous_month_string': prev_month_str,
                'month_string': month_string,
                'month_name': month_name,
                'bubble_data': bubble_data,
                'wordcloud_list': wordcloud_list,
                'twittercloud_data': twittercloud_data,
                'afilter': afilter,
                'u_season_id': u_season_id,
                'season_list': season_list})
    else:
        return HttpResponseRedirect('%s?next=%s' % (settings.LOGIN_URL, request.path))

def showarticle(request):
    """ show article """
    if request.user.is_authenticated:

        # get season id, season list and primary group
        (u_season_id, season_list, _group_filter, _user_groups, dsgvo_ack) = get_u_data(request)

        aid = None
        if 'id' in request.GET:
            aid = request.GET['id']
            error = None
            entry_dic = {}
            try:
                entry_dic = list(Entries.objects.using('wallabag').filter(id=aid).values())[:1][0]
                entry_dic['domain'] = '{uri.scheme}://{uri.netloc}/'.format(uri=urlparse(entry_dic['url']))
                entry_dic['date'] = entry_dic['created_at'].strftime("%d.%m.%Y %H:%M:%S")
            except BaseException:
                error = 'Artikel nicht vorhanden'

            # get days till next home-match
            sleep_message = get_sleep_counter(request)
            if not dsgvo_ack:
                return HttpResponseRedirect('%s?next=%s' % ('/game/dgsvo', request.path))
            else:
                return render(request, 'article/showarticle.html', {
                    'title': 'EBB-Archiv|Artikel anzeigen',
                    'dic': entry_dic,
                    'sleep_message': sleep_message,
                    'error': error,
                    'u_season_id': u_season_id,
                    'season_list': season_list})
        else:
            if not dsgvo_ack:
                return HttpResponseRedirect('%s?next=%s' % ('/game/dgsvo', request.path))
            else:
                return redirect('/article/')

    else:
        return HttpResponseRedirect('%s?next=%s' % (settings.LOGIN_URL, request.path))

def ticker(request):
    """ ticker """

    # identify UA to detect mobiles
    mobile_browser = request.mobile

    # get season id, season list and primary group
    (u_season_id, season_list, _group_filter, _user_groups, dsgvo_ack) = get_u_data(request)

    # get days till next home-match
    sleep_message = get_sleep_counter(request)

    # unix timestamp
    uts = int(time.time())

    match_id = None
    if 'matchid' in request.GET:
        try:
            match_id = int(request.GET['matchid'])
        except BaseException:
            # unix timestamp
            uts = int(time.time())
            (match_id, _match_date, _l_match_day) = get_last_match(uts, u_season_id)

    tweet_list = Ticker.objects.filter(match=match_id).values('id', 'source', 'min', 'content')
    match_details = Match.objects.filter(id=match_id).values('date', 'matchday', 'home_team__team_name', 'home_team__short_name', 'home_team__logo_url', 'guest_team__team_name', 'guest_team__short_name', 'guest_team__logo_url', 'result', 'del_url')[:1]
    try:
        date = match_details[0]['date']
        matchday = match_details[0]['matchday']
        ticker_url = match_details[0]['del_url']
        if mobile_browser:
            home_team = match_details[0]['home_team__short_name']
            guest_team = match_details[0]['guest_team__short_name']
        else:
            home_team = match_details[0]['home_team__team_name']
            guest_team = match_details[0]['guest_team__team_name']
        home_logo = match_details[0]['home_team__logo_url']
        guest_logo = match_details[0]['guest_team__logo_url']
        result = match_details[0]['result']

    except BaseException:
        date = 0
        home_team = ''
        guest_team = ''
        home_logo = ''
        guest_logo = ''
        result = ''
        ticker_url = None

    date_human = datetime.datetime.fromtimestamp(date, tz=TIMEZONE).strftime('%d.%m.%Y')

    # get lineup
    try:
        lineup_list = list(Lineup.objects.filter(match=match_id).values())[0]
    except BaseException:
        lineup_list = []

    d_update = 'not implemented'
    title = 'not implemented'
    gamestat_dic = []


    return render(request, 'article/ticker.html', {
        'title': title,
        # 'sleep_message': sleep_message,
        'u_season_id': u_season_id,
        'season_list': season_list,
        'tweet_list': reversed(tweet_list),
        'home_team': home_team,
        'guest_team': guest_team,
        'home_logo': home_logo,
        'guest_logo': guest_logo,
        'date_human': date_human,
        'result': result,
        'lineup_list': lineup_list,
        'gamestat_dic': gamestat_dic,
        'd_update': d_update,
        'ticker_url': ticker_url,
        'match_id': match_id})

def statistics(request):
    """ statistics """
    if request.user.is_authenticated:

        # get season id, season list and primary group
        (u_season_id, season_list, _group_filter, _user_groups, dsgvo_ack) = get_u_data(request)

        season = '2010/2011'
        for season_ in season_list:
            if season_['id'] == u_season_id:
                season = season_['name']

        try:
            (fsy, _lsy) = season.split('/')
            fsy = int(fsy)
        except BaseException:
            fsy = '2010'
            _lsy = '2011'

        # query all articles
        entry_list = Entries.objects.using('wallabag').filter(created_at__gte=datetime.date(fsy, 0o7, 0o1)).order_by('created_at').values('url', 'title', 'created_at')

        # check if access comes from mobile
        mobile_browser = request.mobile

        cw_dic = {}
        cw_list = []
        source_dic = {}

        for article in entry_list:
            # get source
            source = urlparse(article['url']).hostname
            source = source.replace('www.', '')
            source = source.replace('m.', '')
            source = source.replace('mobil.', '')

            # split date to get calendar week
            (date_, _time) = str(article['created_at']).split(' ')
            (year, month, day) = date_.split('-')

            # get calendar week
            cweek = datetime.date(int(year), int(month), int(day)).isocalendar()[1]

            # create structure in calendar week hash
            if cweek not in cw_dic:
                cw_dic[cweek] = {}
                cw_dic[cweek]['count'] = 0
                cw_list.append(cweek)

            # create structure in source hash
            if source not in source_dic:
                source_dic[source] = {}
                source_dic[source]['count'] = 0
                source_dic[source]['cw'] = {}

            if cweek not in source_dic[source]['cw']:
                source_dic[source]['cw'][cweek] = 0

            # store values in source hash
            source_dic[source]['count'] = source_dic[source]['count'] + 1
            source_dic[source]['cw'][cweek] = source_dic[source]['cw'][cweek] + 1

            # general counter to count articles per week
            cw_dic[cweek]['count'] = cw_dic[cweek]['count'] + 1
            if source not in cw_dic[cweek]:
                cw_dic[cweek][source] = 0

            # individual counter per source
            cw_dic[cweek][source] = cw_dic[cweek][source] + 1

        # create chart
        cw_chart = create_cw_chart(cw_dic, cw_list, mobile_browser, season)

        # source chart
        source_chart = create_source_chart(source_dic, cw_list, mobile_browser, season)

        # get days till next home-match
        sleep_message = get_sleep_counter(request)

        if not dsgvo_ack:
            return HttpResponseRedirect('%s?next=%s' % ('/game/dgsvo', request.path))
        else:
            return render(request, 'article/statistics.html', {
                'title': 'EBB-Archiv|Statistiken',
                'sleep_message': sleep_message,
                'cw_chart': cw_chart,
                'source_chart': source_chart,
                'u_season_id': u_season_id,
                'season_list': season_list})

    else:
        return HttpResponseRedirect('%s?next=%s' % (settings.LOGIN_URL, request.path))
