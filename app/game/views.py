# -*- coding: utf-8 -*-FF
""" views.py """
# pylint: disable=C0302
from __future__ import absolute_import
import datetime
import time
from pytz import timezone
from django.shortcuts import render
from django.conf import settings
from django.http import HttpResponse, HttpResponseRedirect
from django.utils.html import strip_tags
# from django.template import RequestContext
from django.contrib.auth import models
from django.contrib.auth.models import User, Group
from django.db.models import Q
from game.models import Team, Delmatch, Match, Tip, Referee, Presence, Refpermatch, Usersetting, Season, Groupsetting, Ranking, Featurerequest, Ehcevent, Lineup
from game.myfunctions import get_u_data, get_last_match, get_next_match, check_tv_alert, get_tipstats, get_sleep_counter, get_matches, get_team_id, get_winloss, get_score, get_special_ranking
from game.myfunctions import get_ranking_per_season, create_mytip_chart, create_ranking_chart, get_match_chart, get_single_referee_stats, get_next_del_match, get_user_settings, prep_gamestats
from game.myfunctions import get_ftipstats, get_tipdistribution, get_ref_stats, get_penalties_per_match, sort_dic, get_single_user_settings, xls_to_response, ics_to_response, create_rfilter_list, get_player_info
from game.myfunctions import create_kye_charts, collect_team_statistic, shorten_lineup, get_pnaltystats, get_visitor_stats, check_for_ipv6, get_ranking, filter_ranking, validate_tip, get_game_puckpossession
from game.myfunctions import get_shots_per_match, get_shots_stats, get_game_shotzone_stats, prep_ticker, get_shots_per_player, get_player_stat_chart, get_player_stat_list, get_goalie_stat_list, get_game_toi
from game.myfunctions import add_classes_from_structure, get_pstat_table_structure, get_game_shotmap, get_goals_per_period, get_goals_per_minute, get_goals_shotmap, get_goals_zones, get_season_shotzone_stats
from game.myfunctions import get_season_shot_distribution, get_season_shot_min, get_season_shotmap, get_game_corsi, get_season_shot_result, get_playoff_list, get_game_flow, get_playernerdstats
from game.wa_hack_cli import simple_send
##  from game.libthreema import *
TIMEZONE = timezone('Europe/Berlin')

# Create your views here.
# from django.http import HttpResponse

def contact(request):
    """ contact view """
    return render(request, 'game/contact.html', {'title': 'Tippspiel|Kontakt',})

def dgsvo(request):
    """ gdpr view """
    uid = None
    uname = None
    if request.user.is_authenticated:

        # get season id, season list and primary group
        # (u_season_id, season_list, group_filter, user_groups, dsgvo_ack) = get_u_data(request)

        uid = request.user.id
        uname = User.objects.get(id=uid).username
        if request.method == 'GET':
            # this is a get request
            # try:
            #    next = request.GET['next']
            # except BaseException:
            #    next = '/game/'

            return render(request, 'game/dgsvo.html', {
                'title': 'Tippspiel|Datenschutzerklärung',
                'uid': uid,
                'uname': uname})
        else:
            # this is a post request
            result = False
            rnext = '/'
            if 'result' in request.POST:
                if request.POST['result'] == "OK":
                    result = True

            if result:
                if 'next' in request.POST:
                    rnext = request.POST['next']

                if uid:
                    datadict = {'dsgvo_ack' : result}
                    obj, _created = Usersetting.objects.update_or_create(user_id=uid, defaults=datadict)
                    obj.save()
                    return HttpResponseRedirect(request.GET.get('next', rnext))
            else:
                return HttpResponseRedirect('%s' % ('/game/matches'))
    return render(request, 'game/dgsvo.html', {'title': 'Tippspiel|Datenschutzerklärung'},)

def rules(request):
    """ rules view """
    score_list = {}
    group_filter = None
    user_groups = None
    if request.user.is_authenticated:

        # get season id, season list and primary group
        (_u_season_id, _season_list, group_filter, user_groups, _dsgvo_ack) = get_u_data(request)

        score_list = []
        tmp_list = Groupsetting.objects.filter(group__name=group_filter).values('p_winloss', 'p_diff', 'p_tipp', 'p_7vs2', 'p_notip')[:1]
        if tmp_list:
            score_list = tmp_list[0]

    return render(request, 'game/rules.html', {
        'title': 'Tippgame|Regeln',
        'score_list': score_list,
        'group': group_filter,
        'user_groups': user_groups})

def ranking(request):
    """ renking view """
    if request.user.is_authenticated:

        # get season id, season list and primary group
        (u_season_id, season_list, _group_filter, _user_groups, dsgvo_ack) = get_u_data(request)

        # unix timestamp
        uts = int(time.time())
        # get last match
        (match_id, match_date, match_day) = get_last_match(uts, u_season_id)
        # get latest ranking
        ranking_list = []

        if 'type' in request.GET:
            type_ = request.GET['type'].lower()
        else:
            type_ = 'all'

        if type_ == 'special':
            ranking_list = get_special_ranking(u_season_id, match_id, match_date, type_)
            rfilter = None
        else:
            if 'filter' in request.GET:
                try:
                    rfilter = int(request.GET['filter'].lower())
                except BaseException:
                    rfilter = 0
                ranking_list = filter_ranking(u_season_id, match_id, type_, rfilter)
            else:
                rfilter = None
                if match_id:
                    ranking_list = Ranking.objects.filter(matchday_id=match_id, season_id=u_season_id, type=type_).order_by('ranking').values('ranking', 'team__team_name', 'team__short_name', 'team__logo_url', 'match', 'won', 'score', 'match', 'goal', 'ggoal', 'penalty', 'team_id', 'wono', 'wonp', 'losto', 'lostp', 'uts', 'source')
                    if not ranking_list:
                        (nmatch_id, _nmatch_date, _nmatch_day) = get_last_match(match_date-10, u_season_id)
                        ranking_list = Ranking.objects.filter(matchday_id=nmatch_id, season_id=u_season_id, type=type_).order_by('ranking').values('ranking', 'team__team_name', 'team__short_name', 'team__logo_url', 'match', 'won', 'score', 'match', 'goal', 'ggoal', 'penalty', 'team_id', 'wono', 'wonp', 'losto', 'lostp', 'uts', 'source')

        # create filter list for form
        rfilter_list = create_rfilter_list(match_day, 2)

        p_low = 999999
        p_high = 0

        update_uts = 0
        source = None
        ebb_ranking = []
        for rank in ranking_list:
            # we need ebb-ranks to create the chart
            if rank['team__short_name'] == 'EBB':
                ebb_ranking = [rank]
            # lowest and highest penalty values
            if int(rank['penalty']) < int(p_low):
                p_low = rank['penalty']
            if int(p_high) < int(rank['penalty']):
                p_high = rank['penalty']

            # calulcate plus/minus
            rank['diff'] = rank['goal'] - rank['ggoal']
            rank['S'] = rank['won'] + rank['wono'] + rank['wonp']
            # calculate overall number of wons
            rank['lost'] = rank['match'] - rank['S']
            if update_uts == 0:
                update_uts = rank['uts']
            if not source:
                source = rank['source']

        d_update = None
        if update_uts > 0:
            try:
                d_update = datetime.datetime.fromtimestamp(int(update_uts), tz=TIMEZONE).strftime('%d.%m.%Y %H:%M:%S')
            except BaseException:
                pass

        # create dictionary for chart
        # cart_options = create_ranking_chart(request, u_season_id, type_)
        chart_options = create_ranking_chart(request, u_season_id, ebb_ranking, 'all', rfilter)

        if not dsgvo_ack:
            return HttpResponseRedirect('%s?next=%s' % ('/game/dgsvo', request.path))
        else:
            return render(request, 'game/ranking.html', {
                'u_season_id': u_season_id,
                'season_list': season_list,
                'title': 'Tippgame|Tabelle',
                'chart_options': chart_options,
                'ranking_list': ranking_list,
                'p_low': p_low,
                'p_high': p_high,
                'd_update': d_update,
                'type': type_,
                'rfilter': rfilter,
                'rfilter_list': rfilter_list,
                'source': source})
    else:
        return HttpResponseRedirect('%s?next=%s' % (settings.LOGIN_URL, request.path))

def changelog(request):
    """ changelog """
    return render(request, 'game/changelog.html', {'title': 'Tippgame|Changelog'})


def slideshow(request):
    """ slideshow """
    return render(request, 'game/slideshow.html', {'title': 'Tippgame|Slideshow'})

def index(request):
    """ index view """
    if request.user.is_authenticated:
        # get season id, season list and primary group
        (u_season_id, season_list, group_filter, user_groups, dsgvo_ack) = get_u_data(request)

        # unix timestamp
        uts = int(time.time())

        # get next match
        (match_id, _match_date, tv_team) = get_next_match(uts, u_season_id)

        # check for TV alert
        tv_team = check_tv_alert(match_id, uts)

        # get tipp statistic
        (score_dict, user_dict, sort_list) = get_tipstats(u_season_id, group_filter, match_id, False, 'EBB', True)

        # ipv6 hero
        ipv6_hero = check_for_ipv6(request.META['REMOTE_ADDR'])

        # get days till next home-match
        sleep_message = get_sleep_counter(request)
        if not dsgvo_ack:
            return HttpResponseRedirect('%s?next=%s' % ('/game/dgsvo', request.path))
        else:
            return render(request, 'game/index.html', {
                'u_season_id': u_season_id,
                'season_list': season_list,
                'score_dict': score_dict,
                'user_dict': user_dict,
                'group': group_filter,
                'user_groups': user_groups,
                'sleep_message': sleep_message,
                'tv_team': tv_team,
                'sort_list': sort_list,
                'ipv6_hero': ipv6_hero,
                'counter': 1})
    else:
        return render(request, 'game/index.html', {})

def teams(request):
    """ teams view """
    team_list = list(Team.objects.order_by('team_name').filter(del_team=True).values())
    return render(request, 'game/teams.html', {'team_list': team_list})

def matches(request):
    """ matches view """
    # get season id, season list and primary group
    (u_season_id, season_list, _group_filter, _user_groups, _dsgvo_ack) = get_u_data(request)

    match_list = get_matches(request, u_season_id)

    # whats the id of best german hockey team
    ebb_id = get_team_id('EBB')

    # data for the chart
    ebb_ranking = list(map(int, Ranking.objects.filter(team_id=ebb_id, season_id=u_season_id, type='all').order_by('match').values_list('ranking', flat=True)))

    ranking_list = []
    for rank in ebb_ranking:
        if int(rank) == 1:
            dic = {
                'y': int(rank), 'marker': {'symbol': 'url(/static/img/winner.png'}}
            ranking_list.append(dic)
        else:
            ranking_list.append(int(rank))

    mday_list = []
    goal_list = []
    ggoal_list = []
    for match in match_list:
        if(match['result'] and match['result'] != ''):
            (_result, _detail, goal, ggoal) = get_winloss(match['home_team_id'], ebb_id, match['result'])
            mday_list.append(int(match['matchday']))
            goal_list.append(int(goal))
            ggoal_list.append(int(ggoal)*-1)

    chart_options = get_match_chart(request, mday_list, goal_list, ggoal_list, ranking_list)

    # unix timestamp
    uts = int(time.time())
    # get next match
    (match_id, _match_date, _tv_team) = get_next_match(uts, u_season_id)

    sleep_message = get_sleep_counter(request)

    return render(request, 'game/matches.html', {
        'u_season_id': u_season_id,
        'season_list': season_list,
        'match_list': match_list,
        'sleep_message': sleep_message,
        'next_match': match_id-1,
        'chart_options': chart_options})

def mytips(request):
    """ mytips view """
    # get the list of teams
    team_list = list(Team.objects.order_by('team_id').values())
    tmp_team_name_list = {}
    tmp_team_logo_url_list = {}
    tmp_user_tip_list = {}
    match_list = {}
    sum_ = 0

    # unix timestamp
    uts = int(time.time())

    if request.user.is_authenticated:

        # get season id, season list and primary group
        (u_season_id, season_list, group_filter, user_groups, dsgvo_ack) = get_u_data(request)

        # my hide tip options
        mhide_tips = False
        # setting_list = Usersetting.objects.filter(user_id=uid).values_list('hide_tips',flat=True)[:1]
        try:
            mhide_tips = Usersetting.objects.filter(user_id=request.user.id).values_list('hide_tips', flat=True)[:1][0]
        except BaseException:
            mhide_tips = False

        # get group-specific scores
        score_list = Groupsetting.objects.filter(group__name=group_filter).values('p_winloss', 'p_diff', 'p_tipp', 'p_7vs2', 'p_notip')[:1]

        # identify UA to detect mobiles
        mobile_browser = request.mobile

        for team in team_list:
            # fill team dictionary depending on browser
            if mobile_browser:
                tmp_team_name_list[team['team_id']] = team['short_name']
            else:
                tmp_team_name_list[team['team_id']] = team['team_name']

            tmp_team_logo_url_list[team['team_id']] = team['logo_url']

        # check if we need to show our tips or the ones from other users
        uid = False
        hide_tips = False

        # are we asking for a specifc userid ?
        if 'uid' in request.GET:
            try:
                uid = int(request.GET['uid'])
            except BaseException:
                # someone was sending a shitty uid - taken uid from requester
                uid = request.user.id
            # query hide_tips option
            try:
                hide_tips = Usersetting.objects.filter(user_id=uid).values_list('hide_tips', flat=True)[:1][0]
            except BaseException:
                hide_tips = False

            # do not hide my own tips
            if uid == request.user.id:
                hide_tips = False
        else:
            # get userid
            uid = request.user.id

        uname = User.objects.get(id=uid).username

        # get tips per user and create a dictionary
        for tip in Tip.objects.filter(user=uid).values('user', 'match', 'tip'):
            tmp_user_tip_list[tip['match']] = tip['tip']

        match_list = list(Match.objects.filter(season_id=u_season_id).exclude(matchday=0).order_by('matchday').values())

        for match in match_list:

            # convert time to human readable format
            if mobile_browser:
                # match['date_human'] = datetime.datetime.fromtimestamp(match['date'],tz=TIMEZONE).strftime('%d.%m.%Y')
                match['date_human'] = datetime.datetime.fromtimestamp(match['date'], tz=TIMEZONE).strftime('%d.%m.')
            else:
                match['date_human'] = datetime.datetime.fromtimestamp(match['date'], tz=TIMEZONE).strftime('%d.%m.%Y %H:%M')

            # add user tip and score
            if match['id'] in tmp_user_tip_list:
                if(uts < int(match['date']) and hide_tips):
                    match['tip'] = '***'
                elif(uts < int(match['date']) and mhide_tips and not uid == request.user.id):
                    match['tip'] = 'xxx'
                else:
                    match['tip'] = tmp_user_tip_list[match['id']]
                if match['result']:
                    match['score'] = get_score(match['result'], tmp_user_tip_list[match['id']], score_list)
                    sum_ += match['score']
            else:
                if match['result']:
                    match['tip'] = '-'
                    # match['score'] = 0
                    match['score'] = int(score_list[0]['p_notip'])
                    sum_ += match['score']

            # add home team and logo
            match['home'] = tmp_team_name_list[match['home_team_id']]
            match['home_logo'] = tmp_team_logo_url_list[match['home_team_id']]

            # add guest team and logo
            match['guest'] = tmp_team_name_list[match['guest_team_id']]
            match['guest_logo'] = tmp_team_logo_url_list[match['guest_team_id']]

            if match['result'] is None:
                match['result'] = ''

            # do we need to show the edit button
            if(uts <= match['date'] and uid == request.user.id):
                match['edit'] = 1

        # prepare data for user ranking
        # this is the dict for the userranking
        ranking_dict = get_ranking_per_season(request, uid, u_season_id, season_list, group_filter, uname)

        # prepare js function for chart
        chart_options = create_mytip_chart(request, group_filter, uname, match_list, ranking_dict)
        if not dsgvo_ack:
            return HttpResponseRedirect('%s?next=%s' % ('/game/dgsvo', request.path))
        else:
            return render(request, 'game/matches.html', {
                'u_season_id': u_season_id,
                'season_list': season_list,
                'mytipps': 1,
                'match_list': match_list,
                'sum': sum_,
                'uname': uname,
                'group': group_filter,
                'user_groups': user_groups,
                'chart_options': chart_options,
                'title': 'Tippspiel|Tipp-übersicht',})
    else:
        return HttpResponseRedirect('%s?next=%s' % (settings.LOGIN_URL, request.path))

def ptip(request):
    """ ptip view """
    if request.user.is_authenticated:
        # unix timestamp
        uts = int(time.time())

        # identify UA to detect mobiles
        mobile_browser = request.mobile

        date_human = None
        matchday = None
        ht_name = None
        ht_logo = None
        gt_name = None
        gt_logo = None
        match_id = None
        kye_link = None
        ht_short = None
        gt_short = None
        tip = ''
        src = ''

        # get season id, season list and primary group
        (u_season_id, season_list, group_filter, user_groups, dsgvo_ack) = get_u_data(request)

        # get actual season_id
        season_id = len(list(Season.objects.values()))

        # whats the id of best german hockey team
        ebb_id = get_team_id('EBB')

        # special request from the dynamop folks
        sum_ = 0
        if group_filter == 'dynamop':
            # check for existing tip
            uid = request.user.id
            hm_cnt = len(Tip.objects.filter(user=uid, tip='4:2', match__home_team=ebb_id, match__season__id=season_id).values('user', 'match', 'tip', 'match__home_team'))
            gm_cnt = len(Tip.objects.filter(user=uid, tip='2:4', match__guest_team=ebb_id, match__season__id=season_id).values('user', 'match', 'tip', 'match__home_team'))
            sum_ = int(hm_cnt) + int(gm_cnt)

        # check if we need to show the form for a specific match (otherwise we choose the next one)
        if 'match_id' in request.GET:
            match_id = request.GET['match_id']

        if 'src' in request.GET:
            src_url = strip_tags(request.GET['src'])
            if src_url == '/' or src_url.startswith('/game') or src_url.startswith('/article'):
                src = src_url

        if match_id:

            match_list = Match.objects.filter(id=match_id).values('date', 'matchday', 'home_team_id', 'home_team__team_name', 'home_team__short_name', 'home_team__logo_url', 'guest_team_id', 'guest_team__team_name', 'guest_team__short_name', 'guest_team__logo_url', 'result')
            date_human = datetime.datetime.fromtimestamp(match_list[0]['date'], tz=TIMEZONE).strftime('%d.%m.%Y %H:%M')
            matchday = match_list[0]['matchday']

            if mobile_browser:
                ht_name = match_list[0]['home_team__short_name']
                gt_name = match_list[0]['guest_team__short_name']
            else:
                ht_name = match_list[0]['home_team__team_name']
                gt_name = match_list[0]['guest_team__team_name']

            # needed for ranking
            ht_short = match_list[0]['home_team__short_name']
            gt_short = match_list[0]['guest_team__short_name']

            # logos
            ht_logo = match_list[0]['home_team__logo_url']
            gt_logo = match_list[0]['guest_team__logo_url']

            # create a link to statistics
            kye_link = '/game/kye?oteam_id={0}'.format(match_list[0]['home_team_id'])
            if match_list[0]['home_team_id'] == ebb_id:
                kye_link = '/game/kye?oteam_id={0}'.format(match_list[0]['guest_team_id'])

        else:

            # choose the next free match from actual season
            match_list = Match.objects.order_by('date', 'matchday').filter(season_id=season_id, no_bet=False).values('id', 'date', 'matchday', 'home_team_id', 'home_team__team_name', 'home_team__short_name', 'home_team__logo_url', 'guest_team_id', 'guest_team__team_name', 'guest_team__short_name', 'guest_team__logo_url', 'result')
            for match in match_list:
                if uts <= match['date']:
                    date_human = datetime.datetime.fromtimestamp(match['date'], tz=TIMEZONE).strftime('%d.%m.%Y %H:%M')
                    matchday = match['matchday']
                    if mobile_browser:
                        ht_name = match['home_team__short_name']
                        gt_name = match['guest_team__short_name']
                    else:
                        ht_name = match['home_team__team_name']
                        gt_name = match['guest_team__team_name']

                    # needed for ranking
                    ht_short = match['home_team__short_name']
                    gt_short = match['guest_team__short_name']

                    # logos
                    ht_logo = match['home_team__logo_url']
                    gt_logo = match['guest_team__logo_url']
                    match_id = match['id']

                    # create a link to statistics
                    kye_link = '/game/kye?oteam_id={0}'.format(match['home_team_id'])
                    if match['home_team_id'] == ebb_id:
                        kye_link = '/game/kye?oteam_id={0}'.format(match['guest_team_id'])
                    break

        # get ranking
        (l_match_id, _l_match_date, _l_match_day) = get_last_match(uts, season_id)
        ranking_dic = get_ranking(l_match_id, ht_short, gt_short)

        if ranking_dic['ht']['ranking'] and ranking_dic['gt']['ranking']:
            ht_line = '#{0} - {1} ({2}) - {3} Pkt'.format(ranking_dic['ht']['ranking'], ht_name, ranking_dic['ht']['match'], ranking_dic['ht']['score'])
            gt_line = '#{0} - {1} ({2}) - {3} Pkt'.format(ranking_dic['gt']['ranking'], gt_name, ranking_dic['gt']['match'], ranking_dic['gt']['score'])
            if ranking_dic['ht']['ranking'] < ranking_dic['gt']['ranking']:
                f_line = ht_line
                s_line = gt_line
            else:
                f_line = gt_line
                s_line = ht_line
        else:
            f_line = None
            s_line = None

        separator = False
        try:
            if abs(ranking_dic['ht']['ranking'] - ranking_dic['gt']['ranking']) > 1:
                separator = True
        except BaseException:
            pass


        # get referees for the match
        ref_list = Refpermatch.objects.filter(match_id=match_id).values('r1__name', 'r2__name', 'r1_id', 'r2_id')[:1]
        try:
            if mobile_browser:
                r1_name = ref_list[0]['r1__name'].split(' ')[1]
                r2_name = ref_list[0]['r2__name'].split(' ')[1]
            else:
                r1_name = ref_list[0]['r1__name']
                r2_name = ref_list[0]['r2__name']

            (r1_stats, r1_details) = get_single_referee_stats(mobile_browser, ref_list[0]['r1_id'], ebb_id)
            (r2_stats, r2_details) = get_single_referee_stats(mobile_browser, ref_list[0]['r2_id'], ebb_id)

        except BaseException:
            r1_name = ''
            r2_name = ''
            r1_stats = ''
            r2_stats = ''
            r1_details = ''
            r2_details = ''

        # admins are allowed to place tips for others
        # get users member of this group
        users = {}
        try:
            adm_group = models.Group.objects.get(name=group_filter+'-adm').user_set.all()
        except BaseException:
            adm_group = []

        if request.user in adm_group:
            # get users member of this group
            group = models.Group.objects.get(name=group_filter)
            users = group.user_set.all().order_by('username').values('id', 'username')
        else:
            # check for existing tip
            uid = request.user.id
            tip_list = Tip.objects.filter(match=match_id, user=uid).values('tip')

            if tip_list:
                tip = tip_list[0]['tip']

        # check for TV alert
        tv_team = check_tv_alert(match_id, uts)
        if not dsgvo_ack:
            return HttpResponseRedirect('%s?next=%s' % ('/game/dgsvo', request.path))
        else:
            return render(request, 'game/tip.html', {
                'u_season_id': u_season_id,
                'season_list': season_list,
                'date_human': date_human,
                'matchday': matchday,
                'ht_name': ht_name,
                'ht_logo': ht_logo,
                'gt_name': gt_name,
                'gt_logo': gt_logo,
                'match_id': match_id,
                'tip': tip,
                'users': users,
                'group': group_filter,
                'user_groups': user_groups,
                'tv_team': tv_team,
                'kye': kye_link,
                'r1': r1_name,
                'r1_stats': r1_stats,
                'r1_details': r1_details,
                'r2': r2_name,
                'r2_stats': r2_stats,
                'r2_details': r2_details,
                'f_line': f_line,
                's_line': s_line,
                'separator': separator,
                'src': src,
                '42sum': sum_,})

    else:
        return HttpResponseRedirect('%s?next=%s' % (settings.LOGIN_URL, request.path))

def process_tip(request):
    """ process tip """
    if request.user.is_authenticated:

        # identify UA to detect mobiles
        mobile_browser = request.mobile

        # get season id, season list and primary group
        (u_season_id, season_list, group_filter, user_groups, dsgvo_ack) = get_u_data(request)

        # unix timestamp
        uts = int(time.time())
        date_request = datetime.datetime.fromtimestamp(uts, tz=TIMEZONE).strftime('%d.%m.%Y')
        time_request = datetime.datetime.fromtimestamp(uts, tz=TIMEZONE).strftime('%H:%M:%S')

        # get userid
        uname = request.user.username
        uid = request.user.id

        # tip is ok
        error = False

        rmatch_id = False
        rtip = False
        ruid = False
        src = ''

        # get data from http_post request
        if 'match_id' in request.POST:
            try:
                rmatch_id = int(request.POST['match_id'])
            except BaseException:
                error = "Tipp fehlerhaft. Bitte noch mal neu tippen..."
        else:
            error = "Tipp fehlerhaft. Bitte noch mal neu tippen..."

        if 'src' in request.POST:
            src_url = strip_tags(request.POST['src'])
            if src_url == '/' or src_url.startswith('/game') or src_url.startswith('/article'):
                src = src_url

        if 'tip' in request.POST:
            rtip = request.POST['tip']
            try:
                (home, guest) = rtip.split(':')
                try:
                    home = int(home)
                    guest = int(guest)
                    if home == guest:
                        error = 'Tipp "'+str(rtip)+'": Wer auf Gleichstand tippt, sollte zum Fussball gehen...'
                    elif(home < 0 or guest < 0):
                        error = 'Tipp "'+str(rtip)+'": negative Tipps sind cool aber unpassend...'
                    else:
                        rtip = '%s:%s' % (home, guest)
                except BaseException:
                    error = 'Tipp "'+str(rtip)+'" fehlerhaft. Bitte noch mal neu tippen...'
            except BaseException:
                error = 'Tipp "'+str(rtip)+'" fehlerhaft. Bitte noch mal neu tippen...'
        else:
            error = "Tipp fehlerhaft. Bitte noch mal neu tippen..."

        # for the moment we assume that the tip is for ourselves
        tid = uid

        # this is a tip for a different user check if ok
        if 'user_id' in request.POST:
            try:
                ruid = int(request.POST['user_id'])
            except BaseException:
                error = "Tipp fehlerhaft. Bitte noch mal neu tippen..."

            # check if user is allowed to place a tip for others
            if ruid and ruid != uid:
                try:
                    adm_group = models.Group.objects.get(name=group_filter+'-adm').user_set.all()
                except BaseException:
                    adm_group = []

                if request.user in adm_group:
                    # everything ok - accept the tip for a different user
                    tid = ruid
                else:
                    error = 'Tips f&uuml;r andere Spieler sind nicht erlaubt...'

        if not error:

            # do not allow tips for matches in the past
            match_list = Match.objects.filter(id=rmatch_id).values('date')
            match_date = match_list[0]['date']

            if match_date < uts:
                error = 'Tipps in f&uuml; Spiele in der Vergangeneit sind nicht erlaubt...'

        match_list = Match.objects.filter(id=rmatch_id).values('date', 'matchday', 'home_team_id', 'home_team__team_name', 'home_team__short_name', 'home_team__logo_url', 'guest_team_id', 'guest_team__team_name', 'guest_team__short_name', 'guest_team__logo_url', 'result')

        matchday = None
        date_human = None
        ht_name = None
        gt_name = None
        ht_logo = None
        gt_logo = None

        if not error:
            if match_list:
                matchday = match_list[0]['matchday']
                date_human = datetime.datetime.fromtimestamp(match_list[0]['date'], tz=TIMEZONE).strftime('%d.%m.%Y %H:%M')

                if mobile_browser:
                    ht_name = match_list[0]['home_team__short_name']
                    gt_name = match_list[0]['guest_team__short_name']
                else:
                    ht_name = match_list[0]['home_team__team_name']
                    gt_name = match_list[0]['guest_team__team_name']
                ht_logo = match_list[0]['home_team__logo_url']
                gt_logo = match_list[0]['guest_team__logo_url']
            else:
                error = 'Reload Fehler. Bitte Tipp überprüfen und ggf. noch mal neu tippen'

        if not error:

            error = validate_tip(u_season_id, rmatch_id, rtip, tid, uname, user_groups)

        if not error:

            new_entry = None
            datadict = {
                'match_id': rmatch_id,
                'tip': rtip,
                'user_id': tid,
                'date': uts,
                'luser': uname}

            obj, created = Tip.objects.update_or_create(match_id=rmatch_id, user_id=tid, defaults=datadict)
            obj.save()

            if created:
                new_entry = 1

            if not dsgvo_ack:
                return HttpResponseRedirect('%s?next=%s' % ('/game/dgsvo', request.path))
            else:
                return render(request, 'game/tip_result.html', {
                    'date_request': date_request,
                    'time_request': time_request,
                    'new_entry': new_entry,
                    'tip': rtip,
                    'date': date_human,
                    'matchday': matchday,
                    'ht_name': ht_name,
                    'ht_logo': ht_logo,
                    'gt_name': gt_name,
                    'gt_logo': gt_logo,
                    'group': group_filter,
                    'user_groups': user_groups,
                    'src': src})
        else:

            users = {}
            try:
                adm_group = models.Group.objects.get(name=group_filter+'-adm').user_set.all()
            except BaseException:
                adm_group = []

            if request.user in adm_group:
                # get users member of this group
                group = models.Group.objects.get(name=group_filter)
                users = group.user_set.all().order_by('username').values('id', 'username')
            else:
                # check for existing tip
                uid = request.user.id
                # tip_list = Tip.objects.filter(match=rmatch_id, user=uid).values('tip')
                # if tip_list:
                #    tip = tip_list[0]['tip']
            if not dsgvo_ack:
                return HttpResponseRedirect('%s?next=%s' % ('/game/dgsvo', request.path))
            else:
                return render(request, 'game/tip.html', {
                    'u_season_id': u_season_id,
                    'season_list': season_list,
                    'date_human': date_human,
                    'matchday': matchday,
                    'ht_name': ht_name,
                    'ht_logo': ht_logo,
                    'gt_name': gt_name,
                    'gt_logo': gt_logo,
                    'match_id': rmatch_id,
                    'tip': rtip,
                    'users': users,
                    'group': group_filter,
                    'user_groups': user_groups,
                    'error': error,
                    'src': src})
    else:
        return HttpResponseRedirect('%s?next=%s' % (settings.LOGIN_URL, request.path))

def tpd(request):
    """ tips per day """
    if request.user.is_authenticated:

        # get season id, season list and primary group
        (u_season_id, season_list, group_filter, user_groups, dsgvo_ack) = get_u_data(request)

        # unix timestamp
        uts = int(time.time())

        match_id = False

        if 'match_id' in request.GET:
            # get got a match_id as part of the http request
            try:
                match_id = int(request.GET['match_id'])
            except BaseException:
                pass

        if not match_id:
            # we did not get a match_id so let guess it
            # get next and last match match
            (l_match_id, l_match_date, _l_match_day) = get_last_match(uts, u_season_id)
            (n_match_id, _n_match_date, n_tv_team) = get_next_del_match(uts, u_season_id)

            # by default we are showing the next match
            match_id = n_match_id
            tv_team = n_tv_team

            if l_match_id:
                # if last match is less then 6 hours we are going to show the last match
                if abs(uts - l_match_date) < 21600:
                # if(abs(uts - l_match_date) < abs(uts - n_match_date)):
                    match_id = l_match_id
                    tv_team = None

        # get users member of this group
        group = models.Group.objects.get(name=group_filter)
        users = group.user_set.all().order_by('username')
        # users = group.user_set.all().order_by('username').values_list('username', flat=True)

        tpd_dict = {}
        match_list = get_matches(request, u_season_id)

        # get user settings
        usersetting_dict = get_user_settings(group_filter)

        # get group-specific scores
        score_list = Groupsetting.objects.filter(group__name=group_filter).values('p_winloss', 'p_diff', 'p_tipp', 'p_7vs2', 'p_notip')[:1]

        # get tips per match
        tip_list = Tip.objects.filter(user_id__in=users, match_id=match_id, match__season_id=u_season_id).values('match_id', 'match__result', 'match__date', 'user_id', 'user__username', 'tip', 'date')

        user_list = []
        for usr in users:
            # create user_list with strings instead of references
            user_list.append(str(usr))

            tpd_dict[str(usr)] = {}
            for tip in tip_list:
                if str(usr) == str(tip['user__username']):
                    # check if we need to hide the tips for a particular user
                    hide_tip = 0
                    # do not hide my tips
                    if str(usr) != str(request.user):
                        if str(usr) in usersetting_dict:
                            if usersetting_dict[str(usr)]['hide_tips']:
                                if uts < tip['match__date']:
                                    hide_tip = 1

                    # hide tips
                    if hide_tip == 1:
                        tpd_dict[str(usr)]['tip'] = '***'
                    else:
                        tpd_dict[str(usr)]['tip'] = tip['tip']

                    # convert and store tippdate
                    try:
                        date_human = datetime.datetime.fromtimestamp(tip['date'], tz=TIMEZONE).strftime('%d.%m %H:%M')
                    except BaseException:
                        date_human = ''
                    tpd_dict[str(usr)]['date'] = date_human

                    # hide all future tips for users who set the "hite-tip" options
                    if usersetting_dict[str(request.user)]['hide_tips'] and uts < tip['match__date']:
                        tpd_dict[str(usr)]['tip'] = 'xxx'

                    tpd_dict[str(usr)]['result'] = tip['match__result']
                    tpd_dict[str(usr)]['score'] = get_score(tip['match__result'], tip['tip'], score_list)

        # check for TV alert
        tv_team = check_tv_alert(match_id, uts)

        if not dsgvo_ack:
            return HttpResponseRedirect('%s?next=%s' % ('/game/dgsvo', request.path))
        else:
            return render(request, 'game/tips_per_day.html', {
                'u_season_id': u_season_id,
                'season_list': season_list,
                'match_id': match_id,
                'match_list': match_list,
                'tpd_dic': tpd_dict,
                'users': user_list,
                'title': 'Tipps pro Spieltag',
                'group': group_filter,
                'user_groups': user_groups,
                'tv_team': tv_team})
    else:
        return HttpResponseRedirect('%s?next=%s' % (settings.LOGIN_URL, request.path))

def htipstats(request):
    """ home tip statistics """
    if request.user.is_authenticated:

        # get season id, season list and primary group
        (u_season_id, season_list, group_filter, user_groups, dsgvo_ack) = get_u_data(request)

        (score_dict, user_dict) = get_ftipstats(u_season_id, group_filter, 'EBB', 'match__home_team_id')

        if not dsgvo_ack:
            return HttpResponseRedirect('%s?next=%s' % ('/game/dgsvo', request.path))
        else:
            return render(request, 'game/tip_stats.html', {
                'u_season_id': u_season_id,
                'season_list': season_list,
                'score_dict': sorted(list(score_dict.items()), key=lambda x: x[1], reverse=True),
                'user_dict': user_dict,
                'title': 'Tippgame|Heimtipps',
                'group': group_filter,
                'user_groups': user_groups})

    else:
        return HttpResponseRedirect('%s?next=%s' % (settings.LOGIN_URL, request.path))

def tipdistribution(request):
    """ tipp distribution """
    if request.user.is_authenticated:

        # get season id, season list and primary group
        (u_season_id, season_list, group_filter, user_groups, dsgvo_ack) = get_u_data(request)

        # unix timestamp
        uts = int(time.time())

        # get next match
        (match_id, _match_date, _tv_team) = get_next_match(uts, u_season_id)

        (tipd_list, tipd_dic, tipr_list, tipr_dic) = get_tipdistribution(u_season_id, group_filter, match_id, 'EBB')

        if not dsgvo_ack:
            return HttpResponseRedirect('%s?next=%s' % ('/game/dgsvo', request.path))
        else:
            return render(request, 'game/tipd_stats.html', {
                'u_season_id': u_season_id,
                'season_list': season_list,
                'title': 'Tippgame|Tippverteilung',
                'group': group_filter,
                'tipd_dic': tipd_dic,
                'tipd_list': tipd_list,
                'tipr_dic': tipr_dic,
                'tipr_list': tipr_list,
                'user_groups': user_groups})
    else:
        return HttpResponseRedirect('%s?next=%s' % (settings.LOGIN_URL, request.path))


def gtipstats(request):
    """ away tipp stats """
    if request.user.is_authenticated:

        # get season id, season list and primary group
        (u_season_id, season_list, group_filter, user_groups, dsgvo_ack) = get_u_data(request)

        (score_dict, user_dict) = get_ftipstats(u_season_id, group_filter, 'EBB', 'match__guest_team_id')

        if not dsgvo_ack:
            return HttpResponseRedirect('%s?next=%s' % ('/game/dgsvo', request.path))
        else:
            return render(request, 'game/tip_stats.html', {
                'u_season_id': u_season_id,
                'season_list': season_list,
                'score_dict': sorted(list(score_dict.items()), key=lambda x: x[1], reverse=True),
                'user_dict': user_dict,
                'title': 'Tippgame|Auswärtstipps',
                'group': group_filter,
                'user_groups': user_groups})

    else:
        return HttpResponseRedirect('%s?next=%s' % (settings.LOGIN_URL, request.path))

def tipeff(request):
    """ tipp effizienz """
    if request.user.is_authenticated:

        # get season id, season list and primary group
        (u_season_id, season_list, group_filter, user_groups, dsgvo_ack) = get_u_data(request)

        # unix timestamp
        uts = int(time.time())

        # get next match
        (match_id, _match_date, _tv_team) = get_next_match(uts, u_season_id)

        (score_dict, user_dict, _sort_list) = get_tipstats(u_season_id, group_filter, match_id, False, 'EBB')

        eff_dict = {}

        for usr in score_dict:
            if 'rt' in user_dict[usr]:
                eff_dict[usr] = round(score_dict[usr]/float(user_dict[usr]['rt']), 3)
            else:
                eff_dict[usr] = 0

        if not dsgvo_ack:
            return HttpResponseRedirect('%s?next=%s' % ('/game/dgsvo', request.path))
        else:
            return render(request, 'game/tip_eff.html', {
                'u_season_id': u_season_id,
                'season_list': season_list,
                'eff_dict': sorted(list(eff_dict.items()), key=lambda x: x[1], reverse=True),
                'score_dict': score_dict,
                'user_dict': user_dict,
                'title': 'Tipp-Effizienz',
                'group': group_filter,
                'user_groups': user_groups,})

    else:
        return HttpResponseRedirect('%s?next=%s' % (settings.LOGIN_URL, request.path))

def refstats(request):
    """ referee stats """
    if request.user.is_authenticated:

        # get season id, season list and primary group
        (u_season_id, season_list, _group_filter, _user_groups, dsgvo_ack) = get_u_data(request)

        (ref_dict, ref_pm_dict) = get_ref_stats(u_season_id, 'EBB', None)

        if not dsgvo_ack:
            return HttpResponseRedirect('%s?next=%s' % ('/game/dgsvo', request.path))
        else:
            return render(request, 'game/refstats.html', {
                'u_season_id': u_season_id,
                'season_list': season_list,
                'title': 'Schiedsrichter|Gesamtstatistik',
                'ref_pm_dict': sorted(list(ref_pm_dict.items()), key=lambda x: x[1], reverse=True),
                'ref_dict': ref_dict})
    else:
        return HttpResponseRedirect('%s?next=%s' % (settings.LOGIN_URL, request.path))

def refhstats(request):
    """ refhomestats """
    if request.user.is_authenticated:

        # get season id, season list and primary group
        (u_season_id, season_list, _group_filter, _user_groups, dsgvo_ack) = get_u_data(request)

        (ref_dict, ref_pm_dict) = get_ref_stats(u_season_id, 'EBB', None)

        if not dsgvo_ack:
            return HttpResponseRedirect('%s?next=%s' % ('/game/dgsvo', request.path))
        else:
            return render(request, 'game/refstats.html', {
                'u_season_id': u_season_id,
                'season_list': season_list,
                'title': 'Schiedsrichter|Heimstatistik',
                'ref_pm_dict': sorted(list(ref_pm_dict.items()), key=lambda x: x[1], reverse=True),
                'ref_dict': ref_dict})
    else:
        return HttpResponseRedirect('%s?next=%s' % (settings.LOGIN_URL, request.path))

def refgstats(request):
    """ ref away stats """
    if request.user.is_authenticated:

        # get season id, season list and primary group
        (u_season_id, season_list, _group_filter, _user_groups, dsgvo_ack) = get_u_data(request)

        (ref_dict, ref_pm_dict) = get_ref_stats(u_season_id, 'EBB', 'guest_team_id')
        if not dsgvo_ack:
            return HttpResponseRedirect('%s?next=%s' % ('/game/dgsvo', request.path))
        else:
            return render(request, 'game/refstats.html', {
                'u_season_id': u_season_id,
                'season_list': season_list,
                'title': 'Schiedsrichter|Auswärtstatistik',
                'ref_pm_dict': sorted(list(ref_pm_dict.items()), key=lambda x: x[1], reverse=True),
                'ref_dict': ref_dict})
    else:
        return HttpResponseRedirect('%s?next=%s' % (settings.LOGIN_URL, request.path))

def refpenalty(request):
    """ ref penalty """
    if request.user.is_authenticated:

        # get season id, season list and primary group
        (u_season_id, season_list, _group_filter, _user_groups, dsgvo_ack) = get_u_data(request)

        # unix timestamp
        uts = int(time.time())

        # whats the id of best german hockey team
        ebb_id = get_team_id('EBB')

        # get penalties per match
        (p_dic, _sinin) = get_penalties_per_match(ebb_id, u_season_id, uts)

        # get referre statistics
        (ref_dict, _ref_pm_dict) = get_ref_stats(u_season_id, 'EBB', None)

        counter = 0
        sum_ = 0

        for ref in p_dic:
            ref_dict[ref]['mavg'] = int(round(float(p_dic[ref]['mp'])/float(ref_dict[ref]['matches'])))
            ref_dict[ref]['mpmin'] = p_dic[ref]['mp']
            ref_dict[ref]['oavg'] = int(round(float(p_dic[ref]['op'])/float(ref_dict[ref]['matches'])))
            ref_dict[ref]['opmin'] = p_dic[ref]['op']
            sum_ = sum_ + p_dic[ref]['mp']

        # sort list by pmin per match
        sort_list = sort_dic(ref_dict, 'mavg', True)

        # set ranking
        for ref in sort_list:
            counter = counter + 1
            ref_dict[ref]['rank'] = counter

        # we have two referees per match, thus we are counting the minutes twice in the above calculation
        sum_ = sum_/2
        if not dsgvo_ack:
            return HttpResponseRedirect('%s?next=%s' % ('/game/dgsvo', request.path))
        else:
            return render(request, 'game/refpenalty.html', {
                'u_season_id': u_season_id,
                'season_list': season_list,
                'title': 'Schiedsrichter|Strafminuten',
                'sort_list': sort_list,
                'ref_dict': ref_dict,
                'sum': sum_})
    else:
        return HttpResponseRedirect('%s?next=%s' % (settings.LOGIN_URL, request.path))

def refdetails(request):
    """ ref details """
    if request.user.is_authenticated:

        # get season id, season list and primary group
        (u_season_id, season_list, group_filter, user_groups, dsgvo_ack) = get_u_data(request)

        # whats the id of best german hockey team
        ebb_id = get_team_id('EBB')

        # identify UA to detect mobiles
        mobile_browser = request.mobile

        # unix timestamp
        uts = int(time.time())

        # check if we need to show the form for a specific match (otherwise we choose the next one)
        r_id = None
        refname = None
        match_list = []

        if 'id' in request.GET:
            try:
                r_id = int(request.GET['id'])
            except BaseException:
                pass

        if r_id:
            try:
                refname = Referee.objects.filter(id=r_id).values_list('name', flat=True)[0]
            except BaseException:
                pass

            # get statistics per referee
            match_list = Refpermatch.objects.filter(Q(r1_id=r_id, match__season_id=u_season_id) | Q(r2_id=r_id, match__season_id=u_season_id)).order_by('match__date').values('id', 'match__date', 'r1_id', 'r2_id', 'match__matchday', 'match__result', 'match__home_team_id', 'match__home_team__team_name', 'match__guest_team__team_name', 'match__home_team__short_name', 'match__guest_team__short_name', 'match__home_team__logo_url', 'match__guest_team__logo_url')

        # get penalties per match
        (_sinin, p_min_dic) = get_penalties_per_match(ebb_id, u_season_id, uts)

        for match in match_list:
            # skip processing of matches in the future
            if int(match['match__date']) < uts:
                match['matchday'] = match['match__matchday']
                # convert the date to a human readable format
                match['date_human'] = datetime.datetime.fromtimestamp(match['match__date'], tz=TIMEZONE).strftime('%d.%m.%Y')
                match['time_human'] = datetime.datetime.fromtimestamp(match['match__date'], tz=TIMEZONE).strftime('%H:%M')

                # store result and logos
                match['result'] = match['match__result']
                match['home_logo'] = match['match__home_team__logo_url']
                match['guest_logo'] = match['match__guest_team__logo_url']

                if match['matchday'] == 1:
                    match['penalty'] = p_min_dic[match['matchday']]['penalty']
                else:
                    match['penalty'] = p_min_dic[match['matchday']]['penalty'] - p_min_dic[match['matchday']-1]['penalty']

                # store team-names
                if mobile_browser:
                    match['home'] = match['match__home_team__short_name']
                    match['guest'] = match['match__guest_team__short_name']
                else:
                    match['home'] = match['match__home_team__team_name']
                    match['guest'] = match['match__guest_team__team_name']

                # did we win or loose
                if(match['result'] is None or match['result'] == 'None'):
                    match['result'] = ''
                elif ':' in match['result']:
                    (winloss, detail, goal, ggoal) = get_winloss(match['match__home_team_id'], ebb_id, match['result'])
                    match['winloss'] = winloss
                    match['detail'] = detail
                    match['goal'] = goal
                    match['ggoal'] = ggoal

        if not dsgvo_ack:
            return HttpResponseRedirect('%s?next=%s' % ('/game/dgsvo', request.path))
        else:
            return render(request, 'game/matches.html', {
                'u_season_id': u_season_id,
                'season_list': season_list,
                'match_list': match_list,
                'group': group_filter,
                'user_groups': user_groups,
                'title': 'Schiedsrichter|Details',
                'refname': refname,
                'p_min_dic': p_min_dic})

    else:
        return HttpResponseRedirect('%s?next=%s' % (settings.LOGIN_URL, request.path))

def bad_tip(request):
    """ bad tip """
    if request.user.is_authenticated:

        # get season id, season list and primary group
        (u_season_id, season_list, group_filter, user_groups, dsgvo_ack) = get_u_data(request)

        # unix timestamp
        uts = int(time.time())

        # get next match
        (match_id, _match_date, _tv_team) = get_next_match(uts, u_season_id)

        (score_dict, user_dict, sort_list) = get_tipstats(u_season_id, group_filter, match_id, 1, 'EBB')
        sort_list = sort_dic(user_dict, 'score', True)

        if not dsgvo_ack:
            return HttpResponseRedirect('%s?next=%s' % ('/game/dgsvo', request.path))
        else:
            return render(request, 'game/tip_bad.html', {
                'u_season_id': u_season_id,
                'season_list': season_list,
                'score_dict': score_dict,
                'user_dict': user_dict,
                'title': 'Tipps gegen EBB',
                'group': group_filter,
                'sort_list': sort_list,
                'user_groups': user_groups})
    else:
        return HttpResponseRedirect('%s?next=%s' % (settings.LOGIN_URL, request.path))

def change_season(request):
    """ change season """
    if request.user.is_authenticated:

        # get userid
        uid = request.user.id

        try:
            # get data from http_post request
            u_season_id = request.POST['u_season_id']
            rnext = request.POST['next']

            datadict = {'season_id' : u_season_id,}
            obj, _created = Usersetting.objects.update_or_create(user_id=uid, defaults=datadict)
            obj.save()
            return HttpResponseRedirect(request.GET.get('next', rnext))
        except BaseException:
            return HttpResponseRedirect(request.GET.get('next', '/'))

    else:
        return HttpResponseRedirect('%s?next=%s' % (settings.LOGIN_URL, request.path))

def change_tipgroup(request):
    """ change tippgroup """
    if request.user.is_authenticated:

        # get userid
        uid = request.user.id

        # get data from http_post request
        u_group_id = request.POST['u_group_id']
        rnext = request.POST['next']
        datadict = {'group_id' : u_group_id,}
        obj, _created = Usersetting.objects.update_or_create(user_id=uid, defaults=datadict)
        obj.save()
        return HttpResponseRedirect(request.GET.get('next', rnext))

    else:
        return HttpResponseRedirect('%s?next=%s' % (settings.LOGIN_URL, request.path))

def edit_settings(request):
    """ edit settings """
    if request.user.is_authenticated:

        # get season id, season list and primary group
        (u_season_id, season_list, group_filter, user_groups, dsgvo_ack) = get_u_data(request)

        # collect all groups the user does not belong to
        group_list = Group.objects.order_by('id').values('id', 'name')
        group_list = group_list.exclude(name__endswith="-adm")
        group_list = group_list.exclude(name__endswith="default")
        group_dic = {}
        for grp in group_list:
            group_dic[grp['id']] = {}
            group_dic[grp['id']]['name'] = grp['name']
            if grp['id'] in user_groups:
                group_dic[grp['id']]['checked'] = 'checked'

        settings_list = get_single_user_settings(request.user.id)

        hide_tips = False
        threema = ''
        sleep_counter = False
        threema_reminder = False
        send_ticker = False
        dkp = 0

        if 'threema' in settings_list:
            threema = settings_list['threema']
        if 'hide_tips' in settings_list:
            hide_tips = settings_list['hide_tips']
        if 'sleep_counter' in settings_list:
            sleep_counter = settings_list['sleep_counter']
        if 'threema_reminder' in settings_list:
            threema_reminder = settings_list['threema_reminder']
        if 'send_ticker' in settings_list:
            send_ticker = settings_list['send_ticker']
        if 'dkp' in settings_list:
            dkp = settings_list['dkp']

        if not dsgvo_ack:
            return HttpResponseRedirect('%s?next=%s' % ('/game/dgsvo', request.path))
        else:
            return render(request, 'game/edit_settings.html', {
                'u_season_id': u_season_id,
                'season_list': season_list,
                'hide_tips': hide_tips,
                'title': 'Tippgame|Einstellungen',
                'user_groups': user_groups,
                'group_dic': group_dic,
                'group': group_filter,
                'threema': threema,
                'threema_reminder': threema_reminder,
                'send_ticker': send_ticker,
                'sleep_counter': sleep_counter,
                'dkp': dkp})
    else:
        return HttpResponseRedirect('%s?next=%s' % (settings.LOGIN_URL, request.path))


def change_settings(request):
    """ change settings """
    if request.user.is_authenticated:

        # get season id, season list and primary group
        (u_season_id, season_list, group_filter, user_groups, dsgvo_ack) = get_u_data(request)

        # get data from http_post request
        rhide_tips = False
        if 'hide_tips' in request.POST:
            rhide_tips = request.POST['hide_tips']

        rsleep_counter = False
        if 'sleep_counter' in request.POST:
            rsleep_counter = request.POST['sleep_counter']

        if 'send_ticker' in request.POST:
            send_ticker = request.POST['send_ticker']

        settings_list = get_single_user_settings(request.user.id)
        dhide_tips = False

        if 'hide_tips' in settings_list:
            dhide_tips = settings_list['hide_tips']

        rthreema = request.POST['threema']
        dkp = request.POST['dkp'].replace(',', '.')

        # update the database
        datadict = {
            'hide_tips': rhide_tips,
            'threema': rthreema,
            'sleep_counter': rsleep_counter,
            'send_ticker': send_ticker,
            'dkp': dkp}

        obj, _created = Usersetting.objects.update_or_create(user_id=request.user.id, defaults=datadict)
        obj.save()

        # Whatsapp message in case the hide-tip option is going to change
        if bool(rhide_tips) is not bool(dhide_tips):
            action = 'deaktiviert'
            if bool(rhide_tips) is True:
                action = 'aktiviert'

            for grp in user_groups:
                try:
                    number = Groupsetting.objects.filter(group__id=int(grp)).values_list('number', flat=True)[:1][0].lstrip('+')
                except BaseException:
                    number = None

                # send whatsapp message
                if(number and hasattr(settings, 'WA_SRV') and hasattr(settings, 'WA_SRV')):
                    # send whatsapp message to group owner indicating user add
                    lts = time.strftime("%d.%m.%Y %H:%M:%S")
                    message = lts+' %s hat die Option "Tipps verbergen" %s' % (request.user.username, action)
                    simple_send(settings.WA_SRV, settings.WA_PORT, number, message)

        # get groups from post request
        p_grp_list = request.POST.getlist('groups')

        # check if user needs to get added to groups (group-id in p_grp_list but not in user_group)
        for grp in p_grp_list:
            if int(grp) not in user_groups:
                group = Group.objects.get(id=int(grp))
                try:
                    number = Groupsetting.objects.filter(group__id=int(grp)).values_list('number', flat=True)[:1][0].lstrip('+')
                except BaseException:
                    number = None

                request.user.groups.add(group)
                # send whatsapp to group admin
                if(number and hasattr(settings, 'WA_ADMIN_NUMBER') and hasattr(settings, 'WA_SRV') and hasattr(settings, 'WA_PORT')):
                    usr = User.objects.get(username=request.user.username)
                    email = usr.email
                    # send whatsapp message to group owner indicating user add
                    lts = time.strftime("%d.%m.%Y %H:%M:%S")
                    message = lts+' user: %s <%s> hat sich in die Gruppe "%s" eingetragen' % (request.user.username, email, group)
                    simple_send(settings.WA_SRV, settings.WA_PORT, number, message)

        # check if user need to get removed from groups (group-id in user_groups but not in p_grp_list)
        for grp in user_groups:
            if str(grp) not in p_grp_list:
                group = Group.objects.get(id=grp)
                try:
                    number = Groupsetting.objects.filter(group__id=int(grp)).values_list('number', flat=True)[:1][0].lstrip('+')
                except BaseException:
                    number = None

                request.user.groups.remove(group)
                if(number and hasattr(settings, 'WA_ADMIN_NUMBER') and hasattr(settings, 'WA_SRV') and hasattr(settings, 'WA_PORT')):
                    usr = User.objects.get(username=request.user.username)
                    email = usr.email
                    # send whatsapp message to group owner indicating user add
                    lts = time.strftime("%d.%m.%Y %H:%M:%S")
                    message = lts+' user: %s <%s> hat die Gruppe "%s" verlassen' % (request.user.username, email, group)
                    simple_send(settings.WA_SRV, settings.WA_PORT, number, message)

        if not dsgvo_ack:
            return HttpResponseRedirect('%s?next=%s' % ('/game/dgsvo', request.path))
        else:
            return render(request, 'game/change_settings.html', {
                'u_season_id': u_season_id,
                'season_list': season_list,
                'title': 'Tippspiel|Einstellungen',
                'group': group_filter,
                'user_groups': user_groups})
    else:
        return HttpResponseRedirect('%s?next=%s' % (settings.LOGIN_URL, request.path))


def getreport(request):
    """ get report """
    if request.user.is_authenticated:

        # get season id, season list and primary group
        (u_season_id, _season_list, group_filter, _user_groups, dsgvo_ack) = get_u_data(request)

        if 'group' in request.GET:
            group = request.GET['group']
            match_list = get_matches(request, u_season_id)
            tip_list = list(Tip.objects.filter().values())
            group = models.Group.objects.get(name=group_filter)
            users = group.user_set.values('username', 'id')
            now_uts = int(time.time())
            if not dsgvo_ack:
                return HttpResponseRedirect('%s?next=%s' % ('/game/dgsvo', request.path))
            else:
                return xls_to_response(users, match_list, tip_list, now_uts, group_filter)
        else:
            return None
    else:
        return HttpResponseRedirect('%s?next=%s' % (settings.LOGIN_URL, request.path))

def getics(request):
    """ get calendar """
    # set season id
    u_season_id = 4
    ics_file = 'ebb.ics'

    if request.user.is_authenticated:

        # get season id, season list and primary group
        (u_season_id, _season_list, _group_filter, _user_groups, _dsgvo_ack) = get_u_data(request)

    match_list = get_matches(request, u_season_id)
    if  'match_id' in request.GET:
        try:
            match_id = int(request.GET['match_id'])
        except BaseException:
            match_id = None

        if match_id:
            for match in match_list:
                if int(match['id']) == match_id:
                    match_list = []
                    ics_file = 'day-'+str(match['matchday'])+'.ics'
                    match_list.append(match)
                    break

    return ics_to_response(match_list, ics_file)

def dcesb(request):
    """ dynamo certified heimspiel besucher """

    if request.user.is_authenticated:

        # unix timestamp
        uts = int(time.time())

        # get season id, season list and primary group
        (u_season_id, season_list, group_filter, user_groups, dsgvo_ack) = get_u_data(request)

        # get users member of this group
        group = models.Group.objects.get(name=group_filter)
        users = group.user_set.all().order_by('username')
        # print(users)

        match_list = list(Match.objects.filter(home_team__short_name='EBB', date__lte=uts, season_id=u_season_id).exclude(matchday=0).values())
        match_num = len(match_list)
        if match_num == 0:
            match_num = 1

        # get list of preople
        presence_list = Presence.objects.filter(user_id__in=users, match__date__lte=uts, geook=True, cheat=False, match__season=u_season_id).values('match_id', 'user__username', 'match__home_team__short_name', 'match__season')
        presence_dic = {}

        # check if we have entries in presence list. if not raise error message
        error = None
        if presence_list:
            for presence in presence_list:
                score = 1
                # create empty dic if not existing
                if presence['user__username'] not in presence_dic:
                    presence_dic[presence['user__username']] = {}
                    presence_dic[presence['user__username']]['hsc'] = 0
                    presence_dic[presence['user__username']]['hc'] = 0
                    presence_dic[presence['user__username']]['ac'] = 0
                # visiting a remote match will get a better score
                if presence['match__home_team__short_name'] != 'EBB':
                    score = 3
                    presence_dic[presence['user__username']]['ac'] = presence_dic[presence['user__username']]['ac'] + 1
                else:
                    # increease heimspielcounter
                    presence_dic[presence['user__username']]['hsc'] = presence_dic[presence['user__username']]['hsc'] + 1
                    presence_dic[presence['user__username']]['hc'] = presence_dic[presence['user__username']]['hc'] + 1

                # add score
                if 'score' in presence_dic[presence['user__username']]:
                    presence_dic[presence['user__username']]['score'] = presence_dic[presence['user__username']]['score'] + score
                else:
                    presence_dic[presence['user__username']]['score'] = score

                # add counter
                if 'count' in  presence_dic[presence['user__username']]:
                    presence_dic[presence['user__username']]['count'] = presence_dic[presence['user__username']]['count'] + 1
                else:
                    presence_dic[presence['user__username']]['count'] = 1
        else:
            error = 'Keine Standortdaten vorhanden. Statistik kann für diese Gruppe leider nicht erstellt werden...'

        # get dkp for all users
        user_settings_list = Usersetting.objects.filter(user_id__in=users,).values('user__username', 'dkp')
        user_setting_dic = {}
        for usr in user_settings_list:
            user_setting_dic[usr['user__username']] = usr['dkp']

        for usr in presence_dic:
            presence_dic[usr]['hsq'] = int(float(presence_dic[usr]['hsc']) / match_num * 100)
            if(usr in user_setting_dic and user_setting_dic[usr] > 0):
                presence_dic[usr]['pps'] = '{0}€'.format(("%.2f" % (user_setting_dic[usr] / presence_dic[usr]['hsc'])).replace('.', ','))
            else:
                presence_dic[usr]['pps'] = '-'

        sort_list = sort_dic(presence_dic, 'count', True)

        if not dsgvo_ack:
            return HttpResponseRedirect('%s?next=%s' % ('/game/dgsvo', request.path))
        else:
            return render(request, 'game/dcesb.html', {
                'u_season_id': u_season_id,
                'season_list': season_list,
                'title': 'Dynamop Certified Eisbärenspiel Besucher',
                'group': group_filter,
                'user_groups': user_groups,
                'sort_list': sort_list,
                'presence_dic': presence_dic,
                'error': error,
                'match_num': match_num})
    else:
        return HttpResponseRedirect('%s?next=%s' % (settings.LOGIN_URL, request.path))

def mypresence(request):
    """ match presence """
    if request.user.is_authenticated:

        # get season id, season list and primary group
        (u_season_id, season_list, group_filter, user_groups, dsgvo_ack) = get_u_data(request)

        username = None
        if 'user' in request.GET:
            username = request.GET['user']
        else:
            username = request.user.username

        # get presence information for user
        presence_list = Presence.objects.filter(user__username=username, geook=True, match__season=u_season_id).values('match_id', 'user__username', 'match__home_team__short_name', 'cheat')
        presence_dic = {}

        # check if we have entries in presence list. if not raise error message
        error = None
        if presence_list:
            error = 'Keine Geo-Daten vorhanden. Statistik kann für diese Gruppe leider nicht erstellt werden...'

        count = 0
        t_score = 0
        for presence in presence_list:
            score = 1
            if presence['match__home_team__short_name'] != 'EBB':
                score = 3
            if presence['cheat']:
                score = 0

            presence_dic[presence['match_id']] = score
            if score != 0:
                count = count + 1
            t_score = t_score + score

        # get season id, season list and primary group
        (u_season_id, season_list, group_filter, user_groups, dsgvo_ack) = get_u_data(request)

        # get matches
        match_list = get_matches(request, u_season_id)

        # seleep message
        sleep_message = get_sleep_counter(request)

        if not dsgvo_ack:
            return HttpResponseRedirect('%s?next=%s' % ('/game/dgsvo', request.path))
        else:
            return render(request, 'game/matches.html', {
                'title': 'Tippgame|Anwesenheit pro Spiel',
                'u_season_id': u_season_id,
                'season_list': season_list,
                'group': group_filter,
                'user_groups': user_groups,
                'match_list': match_list,
                'sleep_message': sleep_message,
                'mypresence': 1,
                'presence_dic': presence_dic,
                'count': count,
                'score': t_score,
                'error': error})
    else:
        return render(request, 'game/index.html')

def wonloss(request):
    """ wonloss statistic """
    if request.user.is_authenticated:

        # unix timestamp
        uts = int(time.time())

        # get season id, season list and primary group
        (u_season_id, season_list, group_filter, user_groups, dsgvo_ack) = get_u_data(request)

        # get users member of this group
        group = models.Group.objects.get(name=group_filter)
        users = group.user_set.all().order_by('username')
        # print(users)

        # get list of preople
        # presence_list = Presence.objects.filter(user_id__in=users,geook=True,cheat=False,match__season=u_season_id).values('match_id','user__username','match__home_team__short_name','match__result')
        presence_list = Presence.objects.filter(user_id__in=users, geook=True, cheat=False).values('match_id', 'user__username', 'match__home_team__short_name', 'match__result')
        presence_dic = {}

        # check if we have entries in presence list. if not raise error message
        error = None
        if presence_list:
            for presence in presence_list:
                if presence['user__username'] not in presence_dic:
                    presence_dic[presence['user__username']] = {}
                    presence_dic[presence['user__username']]['h_won'] = 0
                    presence_dic[presence['user__username']]['h_lost'] = 0
                    presence_dic[presence['user__username']]['g_won'] = 0
                    presence_dic[presence['user__username']]['g_lost'] = 0
                    presence_dic[presence['user__username']]['won'] = 0
                    presence_dic[presence['user__username']]['lost'] = 0
                    presence_dic[presence['user__username']]['count'] = 0
                try:
                    (h_result, g_result) = presence['match__result'].split(':')
                except BaseException:
                    h_result = 1
                    g_result = 0

                diff = int(h_result)-int(g_result)

                # increment counter
                presence_dic[presence['user__username']]['count'] = presence_dic[presence['user__username']]['count'] + 1

                if presence['match__home_team__short_name']:

                    if diff < 0:
                        # lost home match
                        presence_dic[presence['user__username']]['h_lost'] = presence_dic[presence['user__username']]['h_lost'] + 1
                        presence_dic[presence['user__username']]['lost'] = presence_dic[presence['user__username']]['lost'] + 1
                    elif diff > 0:
                        # won home match
                        presence_dic[presence['user__username']]['h_won'] = presence_dic[presence['user__username']]['h_won'] + 1
                        presence_dic[presence['user__username']]['won'] = presence_dic[presence['user__username']]['won'] + 1
                else:
                    if diff < 0:
                        # won foreign match
                        presence_dic[presence['user__username']]['g_won'] = presence_dic[presence['user__username']]['h_lost'] + 1
                        presence_dic[presence['user__username']]['won'] = presence_dic[presence['user__username']]['won'] + 1
                    elif diff > 0:
                        # lost foreign match
                        presence_dic[presence['user__username']]['g_lost'] = presence_dic[presence['user__username']]['h_won'] + 1
                        presence_dic[presence['user__username']]['lost'] = presence_dic[presence['user__username']]['lost'] + 1
        else:
            error = 'Keine Standortdaten vorhanden. Statistik kann für diese Gruppe leider nicht erstellt werden...'

        # calculate difference
        for presence in presence_dic:
            # print(p,presence_dic[presence]['won'],presence_dicpresencep]['lost'])
            presence_dic[presence]['karma'] = presence_dic[presence]['won'] - presence_dic[presence]['lost']
            presence_dic[presence]['percent'] = int(presence_dic[presence]['won'] * 100 / presence_dic[presence]['count'])

        sort_list = sort_dic(presence_dic, 'percent', True)

        # matchnum
        match_list = list(Match.objects.filter(home_team__short_name='EBB', date__lte=uts, season_id=u_season_id).exclude(matchday=0).values())
        match_num = len(match_list)
        if match_num == 0:
            match_num = 1


        if not dsgvo_ack:
            return HttpResponseRedirect('%s?next=%s' % ('/game/dgsvo', request.path))
        else:
            return render(request, 'game/wonloss.html', {
                'u_season_id': u_season_id,
                'season_list': season_list,
                'group': group_filter,
                'user_groups': user_groups,
                'title': 'Eisbären Karma',
                'sort_list': sort_list,
                'presence_dic': presence_dic,
                'match_num': match_num,
                'error': error})
    else:
        return HttpResponseRedirect('%s?next=%s' % (settings.LOGIN_URL, request.path))

def kye(request):
    """ know your enemy """
    if request.user.is_authenticated:

        # identify UA to detect mobiles
        mobile_browser = request.mobile

        # unix timestamp
        uts = int(time.time())

        # get season id, season list and primary group
        (u_season_id, _season_list, _group_filter, _user_groups, dsgvo_ack) = get_u_data(request)

        # get data for next match (needed for lineup
        (match_id, _match_date, _tv_team) = get_next_match(uts, u_season_id)

        # whats the id of best german hockey team
        team_id = get_team_id('EBB')

        # get the id of the other team
        oteam_id = None
        if 'oteam_id' in request.GET:
            try:
                oteam_id = int(request.GET['oteam_id'])
            except BaseException:
                pass

        if not oteam_id:
            # we did not get a team_id inside the http get, thus lets assume the next match
            match_list = Match.objects.filter(id=match_id).values('home_team_id', 'home_team__short_name', 'home_team__team_name', 'home_team__logo_url', 'guest_team_id', 'guest_team__short_name', 'guest_team__team_name', 'guest_team__logo_url')[:1][0]

            oteam_id = match_list['home_team_id']
            if match_list['home_team_id'] == team_id:
                oteam_id = match_list['guest_team_id']

        match_list = Match.objects.filter(Q(home_team_id=oteam_id, date__lte=uts) | Q(guest_team_id=oteam_id, date__lte=uts)).order_by('-date').values('date', 'home_team_id', 'home_team__short_name', 'home_team__team_name', 'home_team__logo_url', 'guest_team__short_name', 'guest_team__team_name', 'guest_team__logo_url', 'result', 'id')[:8]

        goal_dic = {}
        match_dic = {}
        sort_list = []
        for match in match_list:
            match_dic[match['id']] = {}
            goal_dic[match['id']] = {}
            sort_list.append(match['id'])

            if mobile_browser:
                date_human = datetime.datetime.fromtimestamp(match['date'], tz=TIMEZONE).strftime('%b.%y')
            else:
                date_human = datetime.datetime.fromtimestamp(match['date'], tz=TIMEZONE).strftime('%d.%m.%Y')

            match_dic[match['id']]['date_human'] = date_human
            match_dic[match['id']]['date_human_long'] = datetime.datetime.fromtimestamp(match['date'], tz=TIMEZONE).strftime('%d.%m.%Y')
            match_dic[match['id']]['date'] = match['date']
            match_dic[match['id']]['home_team__short_name'] = match['home_team__short_name']
            match_dic[match['id']]['home_team__team_name'] = match['home_team__team_name']
            match_dic[match['id']]['home_team__logo_url'] = match['home_team__logo_url']
            match_dic[match['id']]['guest_team__short_name'] = match['guest_team__short_name']
            match_dic[match['id']]['guest_team__team_name'] = match['guest_team__team_name']
            match_dic[match['id']]['guest_team__logo_url'] = match['guest_team__logo_url']
            match_dic[match['id']]['result'] = match['result']

            # get winloss status including goals and ggoals
            (winloss, detail, goal, ggoal) = get_winloss(match['home_team_id'], team_id, match['result'])
            # store winloss result in dicionary
            match_dic[match['id']]['winloss'] = winloss
            match_dic[match['id']]['detail'] = detail
            # score goals in dictionary
            match_dic[match['id']]['goal'] = goal
            match_dic[match['id']]['ggoal'] = ggoal

        (team_name, chart_options, pie_options) = create_kye_charts(request, match_dic, oteam_id)

        del_sort_list = []
        del_match_dic = {}
        article_g = None
        article_a = None
        ebb_sort_list = []
        ebb_match_dic = {}

        (_match_id, lmatch_date, _match_day) = get_last_match(uts, u_season_id)
        # get team_statisticks
        (del_sort_list, del_match_dic, article_g, article_a) = collect_team_statistic(mobile_browser, lmatch_date, oteam_id, team_name)
        (ebb_sort_list, ebb_match_dic, _ebb_article_g, _ebb_article_a) = collect_team_statistic(mobile_browser, lmatch_date, team_id, 'Eisbären Berlin')

        # width for columns in html_file
        tab_width_list = [90, 20, 170, 20, 170, 50]
        if mobile_browser:
            tab_width_list = [90, 20, 40, 20, 40, 50]

        # get lineup
        try:
            lineup_list = list(Lineup.objects.filter(match=match_id).values())[0]
        except BaseException:
            pass
        lineup_list = {}

        if(mobile_browser and lineup_list):
            # remove firstnames so fit on screen
            if 'gk' in lineup_list:
                lineup_list['gk'] = shorten_lineup(lineup_list['gk'])
            if 'r1' in lineup_list:
                lineup_list['r1'] = shorten_lineup(lineup_list['r1'])
            if 'r2' in lineup_list:
                lineup_list['r2'] = shorten_lineup(lineup_list['r2'])
            if 'r3' in lineup_list:
                lineup_list['r3'] = shorten_lineup(lineup_list['r3'])
            if 'r4' in lineup_list:
                lineup_list['r4'] = shorten_lineup(lineup_list['r4'])

        if not dsgvo_ack:
            return HttpResponseRedirect('%s?next=%s' % ('/game/dgsvo', request.path))
        else:
            return render(request, 'game/kye.html', {
                'title': 'Spielstatistik gegen %s %s' % (article_a, team_name),
                'sort_list': sort_list,
                'match_dic': match_dic,
                'chart_options': chart_options,
                'pie_options': pie_options,
                'del_sort_list': del_sort_list,
                'del_match_dic': del_match_dic,
                'team_name': team_name,
                'article_g': article_g,
                'article_a': article_a,
                'lineup_list': lineup_list,
                'ebb_sort_list': ebb_sort_list,
                'ebb_match_dic': ebb_match_dic,
                'tab_width_list': tab_width_list,
                # 'team_short_name' : team_short_name
                })
    else:
        return HttpResponseRedirect('%s?next=%s' % (settings.LOGIN_URL, request.path))

def frf(request):
    """ feature request """
    if request.user.is_authenticated:

        # get season id, season list and primary group
        (u_season_id, season_list, group_filter, user_groups, dsgvo_ack) = get_u_data(request)

        # identify UA to detect mobiles
        mobile_browser = request.mobile

        # unix timestamp
        uts = int(time.time())
        now = None

        # get userid
        uid = request.user.id
        uname = User.objects.get(id=uid).username

        # get feature request from http_post request
        if 'frf' in request.POST:
            frf_ = strip_tags(request.POST['frf'])

            # insert feature request into into database
            Featurerequest.objects.create(date=uts, text=frf_, user=request.user)

            if(hasattr(settings, 'WA_ADMIN_NUMBER') and hasattr(settings, 'WA_SRV') and hasattr(settings, 'WA_PORT')):
                # send whatsapp message to group owner indicating user add
                lts = time.strftime("%d.%m.%Y %H:%M:%S")
                message = '{0} - neuer Featurequest von {1}\n{2}:'.format(lts, uname, frf_.encode('utf8'))
                simple_send(settings.WA_SRV, settings.WA_PORT, settings.WA_ADMIN_NUMBER, message)

        # collect the data we need for the form
        area_size = 60
        now = datetime.datetime.fromtimestamp(uts, tz=TIMEZONE).strftime('%d.%m.%Y')
        if mobile_browser:
            now = datetime.datetime.fromtimestamp(uts, tz=TIMEZONE).strftime('%b.%y')
            area_size = 40

        # get list of feature requests
        fr_list = Featurerequest.objects.order_by('-id').values('date', 'text', 'version', 'user__username')

        for feature in fr_list:
            # remove html-tags
            feature['text'] = strip_tags(feature['text'])
            # create and store human readable date
            if mobile_browser:
                date_human = datetime.datetime.fromtimestamp(feature['date'], tz=TIMEZONE).strftime('%b.%y')
            else:
                date_human = datetime.datetime.fromtimestamp(feature['date'], tz=TIMEZONE).strftime('%d.%m.%Y')

            feature['date_human'] = date_human

        if not dsgvo_ack:
            return HttpResponseRedirect('%s?next=%s' % ('/game/dgsvo', request.path))
        else:
            return render(request, 'game/frf.html', {
                'u_season_id': u_season_id,
                'season_list': season_list,
                'title': 'Tippgame|Featurerequests',
                'user_groups': user_groups,
                'group': group_filter,
                'fr_list': fr_list,
                'now': now,
                'uname': uname,
                'mobile_browser': mobile_browser,
                'area_size': area_size})
    else:
        return HttpResponseRedirect('%s?next=%s' % (settings.LOGIN_URL, request.path))

def event(request):
    """ EHC events """

    # get season id, season list and primary group
    (u_season_id, season_list, group_filter, user_groups, _dsgvo_ack) = get_u_data(request)

    # unix timestamp
    uts = int(time.time())

    event_list = list(Ehcevent.objects.filter(uts__gte=uts-86400).order_by('id').values())
    lupdate = ''

    if event_list:
        event_list = list(event_list)
        lupdate = event_list[len(event_list)-1]['lupdate']
    else:
        event_list_old = list(Ehcevent.objects.order_by('id').reverse().values()[:1])
        if event_list_old:
            lupdate = event_list_old[len(event_list)-1]['lupdate']

    return render(request, 'game/event.html', {
        'u_season_id': u_season_id,
        'season_list': season_list,
        'title': 'Tippgame|Events',
        'user_groups': user_groups,
        'group': group_filter,
        'event_list': event_list,
        'lupdate': lupdate})

def playerstats(request):
    """ player statistics """

    # get season id, season list and primary group
    (u_season_id, season_list, group_filter, user_groups, dsgvo_ack) = get_u_data(request)

    # unix timestamp - TO BE MODIFIED AS ID DOES NOT MAKE SENSE
    uts = int(time.time())
    d_update = datetime.datetime.fromtimestamp(int(uts), tz=TIMEZONE).strftime('%d.%m.%Y %H:%M')

    # identify UA to detect mobiles
    mobile_browser = request.mobile

    # parse selector to select the correct graph
    if 'tab_id' in request.GET:
        try:
            tab_id = int(request.GET['tab_id'])
        except BaseException:
            tab_id = 1
    else:
        tab_id = 1

    # parse selector to select the correct graph
    if 'gtab_id' in request.GET:
        try:
            gtab_id = int(request.GET['gtab_id'])
        except BaseException:
            gtab_id = 1
    else:
        gtab_id = 1

    if tab_id == 2:
        data_dic = {'x': 'points', 'y': 'goals', 'z': 'games_played', 'x_name': 'Punkte', 'y_name': 'Tore', 'z_name': 'absolvierte Spiele', 'x_tickint': 2, 'y_tickint': 5}
    elif tab_id == 3:
        data_dic = {'x': 'shots_on_goal', 'y': 'goals', 'z': 'shot_pctg', 'x_name': 'Torschüsse', 'y_name': 'Tore', 'z_name': 'Schussquote (%)', 'x_tickint': 20, 'y_tickint': 5}
    elif tab_id == 4:
        data_dic = {'x': 'shots', 'y': 'shots_on_goal', 'z': 'goals', 'x_name': 'Schüsse', 'y_name': 'Torschüsse', 'z_name': 'Tore', 'x_tickint': 20, 'y_tickint': 50}
    elif tab_id == 5:
        data_dic = {'x': 'time_on_ice_per_game_min', 'y': 'shifts_per_game', 'z': 'points', 'x_name': 'Eiszeit pro Spiel (min)', 'y_name': 'Wechsel pro Spiel', 'z_name': 'Punkte', 'x_tickint': 2, 'y_tickint': 5}
    elif tab_id == 6:
        data_dic = {'x': 'time_on_ice_pp_min', 'y': 'time_on_ice_sh_min', 'z': 'st_points', 'x_name': 'Eiszeit Überzahl (min)', 'y_name': 'Eiszeit Unterzahl (min)', 'z_name': 'Punkte in ÜZ/UZ', 'x_tickint': 20, 'y_tickint': 20}
    elif tab_id == 7:
        data_dic = {'x': 'points', 'y': 'pim', 'z': 'penalties', 'x_name': 'Punkte', 'y_name': 'Strafminuten gesamt', 'z_name': 'Anzahl Strafen', 'x_tickint': 2, 'y_tickint': 20}
    elif tab_id == 8:
        data_dic = {'x': 'cf_shots', 'y': 'ca_shots', 'z': 'time_on_ice_min', 'x_name': 'Eigene Schüsse', 'y_name': 'Gegnerische Schüsse', 'z_name': 'Eiszeit', 'x_tickint': 100, 'y_tickint': 100}
    else:
        data_dic = {'x': 'points', 'y': 'plus_minus', 'z': 'games_played', 'x_name': 'Punkte', 'y_name': 'Plus/Minus', 'z_name': 'absolvierte Spiele', 'x_tickint': 2, 'y_tickint': 5}

    # get statistics
    (player_stat_list, player_format_dic) = get_player_stat_list(u_season_id, tab_id)
    (goalie_stat_list, goalie_format_dic) = get_goalie_stat_list(u_season_id, gtab_id)


    # create chart
    chart_options = get_player_stat_chart(player_stat_list, data_dic, mobile_browser)

    # colums to display in table
    (player_table_structure, goalie_table_structure) = get_pstat_table_structure(mobile_browser)

    # combine format classes
    player_format_dic = add_classes_from_structure(player_table_structure, player_format_dic, tab_id)
    goalie_format_dic = add_classes_from_structure(goalie_table_structure, goalie_format_dic, gtab_id)

    return render(request, 'game/playerstats.html', {
        'u_season_id': u_season_id,
        'season_list': season_list,
        'title': 'Tippgame|Spielerstatistiken',
        'user_groups': user_groups,
        'group': group_filter,
        'd_update': d_update,
        'tab_id': tab_id,
        'gtab_id': gtab_id,
        'player_table_structure': player_table_structure,
        'player_stat_list': player_stat_list,
        'player_format_dic': player_format_dic,
        'goalie_table_structure': goalie_table_structure,
        'goalie_stat_list': goalie_stat_list,
        'goalie_format_dic': goalie_format_dic,
        'chart_options': chart_options})

def goalstats(request):
    """ goalie statistics """

    # get season id, season list and primary group
    (u_season_id, season_list, _group_filter, _user_groups, dsgvo_ack) = get_u_data(request)

    # identify UA to detect mobiles
    mobile_browser = request.mobile

    # parse selector to select the correct graph
    if 'sel_id' in request.GET:
        try:
            sel_id = int(request.GET['sel_id'])
        except BaseException:
            sel_id = 1
    else:
        sel_id = 1

    if 'type' in request.GET:
        type_ = request.GET['type'].lower()
    else:
        type_ = 'all'

    if sel_id == 1:
        (stat_chart, stat_table) = get_goals_per_period(u_season_id, mobile_browser, type_)
    elif sel_id == 2:
        (stat_chart, stat_table) = get_goals_per_minute(u_season_id, mobile_browser, type_)
    elif sel_id == 3:
        (stat_chart, stat_table) = get_goals_zones(u_season_id, mobile_browser, type_)
    elif sel_id == 4:
        (stat_chart, stat_table) = get_goals_shotmap(u_season_id, mobile_browser, type_)
    elif sel_id == 5:
        (stat_chart, stat_table) = get_goals_shotmap(u_season_id, mobile_browser, type_, False)
    else:
        stat_chart = {}
        stat_table = {}

    selector_list = [
        {'name': 'Tore/Gegentore pro Drittel', 'sel_id': 1},
        {'name': 'Tore/Gegentore pro Minute', 'sel_id': 2},
        {'name': 'Tore/Gegentore pro Zone', 'sel_id': 3},
        {'name': 'Shotmap der Tore', 'sel_id': 4},
        {'name': 'Shotmap der Gegentore', 'sel_id': 5},
        ]

    title = selector_list[sel_id-1]['name']

    if mobile_browser:
        mob_prefix = '_mobile'
        img_width = '20'
    else:
        mob_prefix = ''
        img_width = '30'

    return render(request, 'game/goalstats.html', {
        'u_season_id': u_season_id,
        'season_list': season_list,
        'selector_list': selector_list,
        'title': title,
        'stat_chart': stat_chart,
        'stat_table': stat_table,
        'sel_id': sel_id,
        'mob_prefix': mob_prefix,
        'img_width': img_width,
        'type': type_,})

def shotstats(request):
    """ goal hstats """


    # get season id, season list and primary group
    (u_season_id, season_list, _group_filter, _user_groups, dsgvo_ack) = get_u_data(request)

    # identify UA to detect mobiles
    mobile_browser = request.mobile

    # parse selector to select the correct graph
    if 'sel_id' in request.GET:
        try:
            sel_id = int(request.GET['sel_id'])
        except BaseException:
            sel_id = 1
    else:
        sel_id = 1

    if 'type' in request.GET:
        type_ = request.GET['type'].lower()
    else:
        type_ = 'all'

    # get match list
    ebb_id = get_team_id('EBB')
    if type_ == 'home':
        m_list = Match.objects.filter(season=u_season_id, home_team=ebb_id).exclude(matchday=0).values('shots', 'matchday')
    elif type_ == 'away':
        m_list = Match.objects.filter(season=u_season_id, guest_team=ebb_id).exclude(matchday=0).values('shots', 'matchday')
    else:
        m_list = Match.objects.filter(season=u_season_id).exclude(matchday=0).values('shots', 'matchday')

    if sel_id == 1:
        (stat_chart, stat_table) = get_season_shot_distribution(u_season_id, mobile_browser, m_list)
    elif sel_id == 2:
        (stat_chart, stat_table) = get_season_shot_distribution(u_season_id, mobile_browser, m_list, True)
    elif sel_id == 3:
        (stat_chart, stat_table) = get_season_shot_min(u_season_id, mobile_browser, m_list)
    elif sel_id == 4:
        (stat_chart, stat_table) = get_season_shot_min(u_season_id, mobile_browser, m_list, True)
    elif sel_id == 5:
        (stat_chart, stat_table) = get_season_shot_result(u_season_id, mobile_browser, m_list)
    elif sel_id == 6:
        (stat_chart, stat_table) = get_season_shotzone_stats(u_season_id, mobile_browser, m_list)
    elif sel_id == 7:
        (stat_chart, stat_table) = get_season_shotzone_stats(u_season_id, mobile_browser, m_list, True)
    elif sel_id == 8:
        (stat_chart, stat_table) = get_season_shotmap(u_season_id, mobile_browser, m_list)
    elif sel_id == 9:
        (stat_chart, stat_table) = get_season_shotmap(u_season_id, mobile_browser, m_list, True)
    else:
        stat_chart = {}
        stat_table = {}

    selector_list = [
        {'name': 'Schussverteilung pro Drittel', 'sel_id': 1},
        {'name': 'Torschussverteilung pro Drittel', 'sel_id': 2},
        {'name': 'Schussverteilung pro Minute', 'sel_id': 3},
        {'name': 'Prozentuale Schussverteilung pro Minute', 'sel_id': 4},
        {'name': 'Schussverteilung nach Schussergebis', 'sel_id': 5},
        {'name': 'Schüsse pro Zone', 'sel_id': 6},
        {'name': 'Torschüsse pro Zone', 'sel_id': 7},
        {'name': 'Shotmap der Schüsse', 'sel_id': 8},
        {'name': 'Schotmap der Torschüsse', 'sel_id': 9},
        ]

    title = selector_list[sel_id-1]['name']

    if mobile_browser:
        mob_prefix = '_mobile'
        img_width = '20'
    else:
        mob_prefix = ''
        img_width = '30'

    # if not dsgvo_ack:
    #    return HttpResponseRedirect('%s?next=%s' % ('/game/dgsvo', request.path))
    #else:
    return render(request, 'game/shotstats.html', {
        'u_season_id': u_season_id,
        'season_list': season_list,
        'selector_list': selector_list,
        'stat_chart': stat_chart,
        'stat_table': stat_table,
        'mob_prefix': mob_prefix,
        'img_width': img_width,
        'sel_id': sel_id,
        'type': type_,
        'title': title})
    # else:
    #    return HttpResponseRedirect('%s?next=%s' % (settings.LOGIN_URL, request.path))

def goalgstats(request):
    """ goal away stats """
    if request.user.is_authenticated:

        # get season id, season list and primary group
        (u_season_id, season_list, _group_filter, _user_groups, dsgvo_ack) = get_u_data(request)

        (goal_stats, goal_pie, goal_line) = get_goalstats(u_season_id, request, 'guest')

        if not dsgvo_ack:
            return HttpResponseRedirect('%s?next=%s' % ('/game/dgsvo', request.path))
        else:
            return render(request, 'game/goalstats.html', {
                'u_season_id': u_season_id,
                'season_list': season_list,
                'title': 'Tor/Gegentorstatistik - Auswärts',
                'goal_stats': goal_stats,
                'goal_pie': goal_pie,
                'goal_line': goal_line})
    else:
        return HttpResponseRedirect('%s?next=%s' % (settings.LOGIN_URL, request.path))

def pnaltystats(request):
    """ penalty statistics """
    if request.user.is_authenticated:

        # get season id, season list and primary group
        (u_season_id, season_list, _group_filter, _user_groups, dsgvo_ack) = get_u_data(request)

        (pnalty_stats, pnalty_line, pnalty_name_dic) = get_pnaltystats(u_season_id, request, None)

        if not dsgvo_ack:
            return HttpResponseRedirect('%s?next=%s' % ('/game/dgsvo', request.path))
        else:
            return render(request, 'game/pnaltystats.html', {
                'u_season_id': u_season_id,
                'season_list': season_list,
                'title': 'Strafzeitenstatistik - Gesamt',
                'pnalty_stats': pnalty_stats,
                'pnalty_line': pnalty_line,
                'pnalty_name_dic': sorted(list(pnalty_name_dic.items()), key=lambda x: x[1], reverse=True)})
    else:
        return HttpResponseRedirect('%s?next=%s' % (settings.LOGIN_URL, request.path))

def pnaltyhstats(request):
    """ penalty home statistics """
    if request.user.is_authenticated:

        # get season id, season list and primary group
        (u_season_id, season_list, _group_filter, _user_groups, dsgvo_ack) = get_u_data(request)

        (pnalty_stats, pnalty_line, pnalty_name_dic) = get_pnaltystats(u_season_id, request, 'home')

        if not dsgvo_ack:
            return HttpResponseRedirect('%s?next=%s' % ('/game/dgsvo', request.path))
        else:
            return render(request, 'game/pnaltystats.html', {
                'u_season_id': u_season_id,
                'season_list': season_list,
                'title': 'Strafzeitenstatistik - Heim',
                'pnalty_stats': pnalty_stats,
                'pnalty_line': pnalty_line,
                'pnalty_name_dic': sorted(list(pnalty_name_dic.items()), key=lambda x: x[1], reverse=True)})
    else:
        return HttpResponseRedirect('%s?next=%s' % (settings.LOGIN_URL, request.path))

def pnaltygstats(request):
    """ penalty away statistics """
    if request.user.is_authenticated:

        # get season id, season list and primary group
        (u_season_id, season_list, _group_filter, _user_groups, dsgvo_ack) = get_u_data(request)

        (pnalty_stats, pnalty_line, pnalty_name_dic) = get_pnaltystats(u_season_id, request, 'guest')

        if not dsgvo_ack:
            return HttpResponseRedirect('%s?next=%s' % ('/game/dgsvo', request.path))
        else:
            return render(request, 'game/pnaltystats.html', {
                'u_season_id': u_season_id,
                'season_list': season_list,
                'title': 'Strafzeitenstatistik - Auswärts',
                'pnalty_stats': pnalty_stats,
                'pnalty_line': pnalty_line,
                'pnalty_name_dic': sorted(list(pnalty_name_dic.items()), key=lambda x: x[1], reverse=True)})
    else:
        return HttpResponseRedirect('%s?next=%s' % (settings.LOGIN_URL, request.path))

def visitorstats(request):
    """ visitor statistics """

    # get season id, season list and primary group
    (u_season_id, season_list, _group_filter, _user_groups, _dsgvo_ack) = get_u_data(request)

    (visitor_dic, visitor_chart) = get_visitor_stats(request, u_season_id)

    return render(request, 'game/visitorstats.html', {
        'u_season_id': u_season_id,
        'season_list': season_list,
        'title': 'Zuschauerstatistik - Heimspiele',
        'visitor_dic': sorted(visitor_dic.items()),
        'visitor_chart': visitor_chart})

def live(request):
    """ live table """
    if request.user.is_authenticated:

        # get season id, season list and primary group
        (u_season_id, season_list, _group_filter, _user_groups, dsgvo_ack) = get_u_data(request)
        # get season_id
        season_id = len(list(Season.objects.values()))

        # unix timestamp
        uts = int(time.time())

        # get last and next match
        (match_id, match_date, match_day) = get_last_match(uts, season_id)
        (n_match_id, n_match_date, _n_tv_team) = get_next_match(uts, season_id)

        # if next match is closer we are going to update the next match (sportal kicks in a bid earlier)
        if(n_match_id and abs(uts - n_match_date) < abs(uts - match_date)):
            match_id = n_match_id
            match_date = n_match_date
            match_day = match_day + 1

        del_match_list = Delmatch.objects.filter(matchday=match_day, season=season_id).order_by('-date').values('matchday', 'home_team__short_name', 'home_team__team_name', 'home_team__logo_url', 'guest_team__short_name', 'guest_team__team_name', 'guest_team__logo_url', 'result', 'status', 'update_date')

        if match_id:
            ranking_list = Ranking.objects.filter(matchday_id=match_id, season_id=u_season_id, type='all').order_by('ranking').values('ranking', 'team__team_name', 'team__short_name', 'team__logo_url', 'match', 'won', 'score', 'match', 'goal', 'ggoal', 'penalty', 'team_id', 'wono', 'wonp', 'losto', 'lostp', 'uts', 'source')
            if not ranking_list:
                # (nmatch_id, _nmatch_date, _nmatch_day) = get_last_match(match_date-10, u_season_id)
                ranking_list = Ranking.objects.filter(matchday_id=n_match_id, season_id=u_season_id, type='all').order_by('ranking').values('ranking', 'team__team_name', 'team__short_name', 'team__logo_url', 'match', 'won', 'score', 'match', 'goal', 'ggoal', 'penalty', 'team_id', 'wono', 'wonp', 'losto', 'lostp', 'uts', 'source')

            for rank in ranking_list:
                rank['diff'] = rank['goal'] - rank['ggoal']
                rank['S'] = rank['won'] + rank['wono'] + rank['wonp']
                rank['lost'] = rank['match'] - rank['S']

        d_update = None
        try:
            if uts - int(del_match_list[0]['update_date']) < 1200:
                d_update = datetime.datetime.fromtimestamp(int(del_match_list[0]['update_date']), tz=TIMEZONE).strftime('%d.%m.%Y %H:%M')
        except BaseException:
            pass

        if not dsgvo_ack:
            return HttpResponseRedirect('%s?next=%s' % ('/game/dgsvo', request.path))
        else:
            return render(request, 'game/live.html', {
                'u_season_id': u_season_id,
                'season_list': season_list,
                'title': 'Live',
                'del_match_list': del_match_list,
                'd_update': d_update,
                'ranking_list': ranking_list})
    else:
        return HttpResponseRedirect('%s?next=%s' % (settings.LOGIN_URL, request.path))

def gamestats(request):
    """ penalty away statistics """

    # get season id, season list and primary group
    (u_season_id, season_list, _group_filter, _user_groups, dsgvo_ack) = get_u_data(request)

    # unix timestamp
    uts = int(time.time())

    # identify UA to detect mobiles
    mobile_browser = request.mobile

    # check if we need to show the form for a specific match (otherwise we choose next/last one)
    if 'match_id' in request.GET:
        match_id = request.GET['match_id']
    else:
        # get last and next match
        (match_id, match_date, match_day) = get_last_match(uts, u_season_id)
        (n_match_id, n_match_date, _n_tv_team) = get_next_match(uts, u_season_id)

        # if next match is closer we are going to update the next match (sportal kicks in a bid earlier)
        if not match_date:
            match_date = 0
        if not match_day:
            match_day = 0

        if(n_match_id and abs(uts - n_match_date) < abs(uts - match_date)):
            match_id = n_match_id
            match_date = n_match_date
            match_day = match_day + 1

    # prepare gamestats
    (d_update, title, gamestat_dic) = prep_gamestats(match_id, uts, mobile_browser)

    return render(request, 'game/gamestats.html', {
        'u_season_id': u_season_id,
        'season_list': season_list,
        'title':  title,
        'gamestat_dic': gamestat_dic,
        'match_id': match_id,
        'd_update': d_update})

def nerdstats(request):
    """ nerdstats statistics """

    # get season id, season list and primary group
    (u_season_id, season_list, _group_filter, _user_groups, dsgvo_ack) = get_u_data(request)

    # unix timestamp
    uts = int(time.time())

    # identify UA to detect mobiles
    mobile_browser = request.mobile

    # parse selector to select the correct graph
    if 'sel_id' in request.GET:
        sel_id = int(request.GET['sel_id'])
    else:
        sel_id = 1

    # check if we need to show the form for a specific match (otherwise we choose next/last one)
    if 'match_id' in request.GET:
        match_id = request.GET['match_id']
    else:
        # get last and next match
        (match_id, _match_date, match_day) = get_last_match(uts, u_season_id)
        # (n_match_id, n_match_date, _n_tv_team) = get_next_match(uts, u_season_id)

        # if next match is closer we are going to update the next match (sportal kicks in a bid earlier)
        # if(n_match_id and abs(uts - n_match_date) < abs(uts - match_date)):
        #    match_id = n_match_id
        #    match_date = n_match_date
        #     match_day = match_day + 1

    if sel_id == 1:
        (stat_chart, stat_table) = get_shots_per_match(match_id, mobile_browser, False)
    elif sel_id == 2:
        # get and show shots per match
        # (stat_chart, stat_table) = get_shots_per_match(match_id, mobile_browser, True, None, True)
        (stat_chart, stat_table) = get_game_flow(match_id, mobile_browser)
    elif sel_id == 3:
        # get and show shot statistics (how many failed, how many got blocked) ....
        (stat_chart, stat_table) = get_shots_stats(match_id, mobile_browser)
    elif sel_id == 4:
         # get shot_zone stats
        (stat_chart, stat_table) = get_game_shotzone_stats(match_id, mobile_browser)
    elif sel_id == 5:
         # get shot_zone stats (sog)
        (stat_chart, stat_table) = get_game_shotzone_stats(match_id, mobile_browser, True)
    elif sel_id == 6:
        # shost per player
        (stat_chart, stat_table) = get_shots_per_player(match_id, mobile_browser)
    elif sel_id == 7:
        # create shotmap
        (stat_chart, stat_table) = get_game_shotmap(match_id, mobile_browser)
    elif sel_id == 8:
        # create shotmap
        (stat_chart, stat_table) = get_game_puckpossession(match_id, mobile_browser)
    elif sel_id == 9:
        # create shotmap
        (stat_chart, stat_table) = get_game_toi(match_id, mobile_browser)
    elif sel_id == 10:
        # create shotmap
        (stat_chart, stat_table) = get_game_corsi(match_id, mobile_browser, True, sel_id)
    elif sel_id == 11:
        # create shotmap
        (stat_chart, stat_table) = get_game_corsi(match_id, mobile_browser, True, sel_id)
    else:
        stat_chart = {}
        stat_table = {}

    # prepare gamestats
    (d_update, title, gamestat_dic) = prep_gamestats(match_id, uts, mobile_browser)

    selector_list = [
        {'name': 'Anzahl Schüsse', 'sel_id': 1},
        {'name': 'Spielfluss', 'sel_id': 2},
        {'name': 'Schuss-Statistik EBB', 'sel_id': 3},
        {'name': 'Schuss-Zonen', 'sel_id': 4},
        {'name': 'Torschuss-Zonen', 'sel_id': 5},
        {'name': 'Schussverhältnis pro Spieler bei 5 gegen 5 (CF, CA)', 'sel_id': 10},
        {'name': 'Prozentuales Schussverhältnis pro Spieler bei 5 gegen 5 (CF%)', 'sel_id': 11},
        {'name': 'Schüsse pro EBB-Spieler', 'sel_id': 6},
        {'name': 'Shot-Map EBB', 'sel_id': 7},
        {'name': 'Puckbesitz / prozentualer Spielanteil', 'sel_id': 8},
        {'name': 'Eiszeit pro Spieler', 'sel_id': 9},
        ]

    og_description = 'Spiel-Statistiken'
    for sel in selector_list:
        if sel['sel_id'] == sel_id:
            og_description = sel['name']
            break

    if mobile_browser:
        mob_prefix = '_mobile'
        img_width = '20'
    else:
        mob_prefix = ''
        img_width = '30'

    # cardlist filter
    card_list = [1, 2, 3, 4, 5, 6]

    return render(request, 'game/nerdstats.html', {
        'u_season_id': u_season_id,
        'season_list': season_list,
        'title':  title,
        'stat_chart': stat_chart,
        'gamestat_dic': gamestat_dic,
        'match_id': match_id,
        'stat_table': stat_table,
        'selector_list': selector_list,
        'sel_id': sel_id,
        'og_title': og_description,
        'mob_prefix': mob_prefix,
        'img_width': img_width,
        'card_list': card_list,
        'd_update': d_update})

def playernerdstats(request):
    """ nerdstats statistics """
    # get season id, season list and primary group
    (u_season_id, season_list, _group_filter, _user_groups, dsgvo_ack) = get_u_data(request)

    # unix timestamp
    uts = int(time.time())

    # identify UA to detect mobiles
    mobile_browser = request.mobile

    # parse selector to select the correct graph
    if 'number' in request.GET:
        number = int(request.GET['number'])
    else:
        number = 23

    # parse selector to select the correct graph
    if 'sel_id' in request.GET:
        sel_id = int(request.GET['sel_id'])
    else:
        sel_id = 1

    d_update = None

    # get chart and table
    (stat_chart, d_update) = get_playernerdstats(mobile_browser, u_season_id, sel_id, number)

    # get playerinformation
    (player_info_dic, pnumber, nnumber) = get_player_info(u_season_id, number)

    # parse selector to select the correct graph
    if 'sel_id' in request.GET:
        sel_id = int(request.GET['sel_id'])
    else:
        sel_id = 1

    selector_list = [
        {'name': 'Schüsse pro Spiel', 'sel_id': 1},
        {'name': 'Schüsse pro 60min Eiszeit (SH/60)', 'sel_id': 2},
        {'name': 'Saison Shot-Map', 'sel_id': 3},
        {'name': 'Tore und -schüsse nach Zonen', 'sel_id': 8},
        {'name': 'Corsi Werte pro Saison (CF, CA)', 'sel_id': 6},
        {'name': 'Prozentuale Corsi Werte (CF%)', 'sel_id': 7},
        {'name': 'Entwicklung Schußquote (Tore vs. Torschüsse)', 'sel_id': 4},
        {'name': 'Eiszeit pro Spiel', 'sel_id': 5},
        ]

    # title
    # title = 'Statistiken für {0} ({1})'.format(player_info_dic['full_name'], number)
    title = 'Statistiken für {0}'.format(player_info_dic['full_name'])

    for sel in selector_list:
        if sel['sel_id'] == sel_id:
            og_description = sel['name']
            break

    return render(request, 'game/playernerdstats.html', {
        'u_season_id': u_season_id,
        'season_list': season_list,
        'player_info_dic': player_info_dic,
        'pnumber': pnumber,
        'nnumber': nnumber,
        'title':  title,
        'stat_chart': stat_chart,
        'selector_list': selector_list,
        'sel_id': sel_id,
        'd_update': d_update})

def gameticker(request):
    """ penalty away statistics """

    # get season id, season list and primary group
    (u_season_id, season_list, _group_filter, _user_groups, dsgvo_ack) = get_u_data(request)

    # unix timestamp
    uts = int(time.time())

    # identify UA to detect mobiles
    mobile_browser = request.mobile

    # check if we need to show the form for a specific match (otherwise we choose next/last one)
    if 'match_id' in request.GET:
        match_id = request.GET['match_id']
    else:
        # get last and next match
        (match_id, match_date, match_day) = get_last_match(uts, u_season_id)
        (n_match_id, n_match_date, _n_tv_team) = get_next_match(uts, u_season_id)

        # if next match is closer we are going to update the next match (sportal kicks in a bid earlier)
        if(n_match_id and abs(uts - n_match_date) < abs(uts - match_date)):
            match_id = n_match_id
            match_date = n_match_date
            match_day = match_day + 1


    # prepare gamestats
    # (d_update, title, gamestat_dic, ticker_list) = prep_ticker(match_id, uts, mobile_browser)
    d_update = 'foo'
    title = 'not implemented'
    gamestat_dic = []
    ticker_list = []
    return render(request, 'game/gameticker.html', {
        'u_season_id': u_season_id,
        'season_list': season_list,
        'gamestat_dic': gamestat_dic,
        'ticker_list': ticker_list,
        'title':  title,
        'match_id': match_id,
        'd_update': d_update})

def playofftree(request):
    """ playofftree view """

    if request.user.is_authenticated:

        # get season id, season list and primary group
        (u_season_id, season_list, _group_filter, _user_groups, _dsgvo_ack) = get_u_data(request)
    else:
        u_season_id = None
        season_list = Season.objects.values()

    # parse selector to select the correct graph
    if 'season_id' in request.GET:
        try:
            season_id = int(request.GET['season_id'])
        except BaseException:
            season_id = len(season_list)
    else:
        if request.user.is_authenticated:
            season_id = u_season_id
        else:
            season_id = len(season_list)

    # previous/next arrows
    season_prev = None
    season_next = None
    if season_id > 1:
        season_prev = season_id - 1
    if season_id < len(season_list):
        season_next = season_id + 1

    # get season name and tree
    season_name = season_list[season_id-1]['name']
    playoff_series_list = get_playoff_list(season_id)

    return render(request, 'game/playofftree.html', {
        'u_season_id': u_season_id,
        'season_id': season_id,
        'season_list': season_list,
        'season_prev': season_prev,
        'season_next': season_next,
        'playoff_series_list': playoff_series_list,
        'title': 'Playoffbaum {0}'.format(season_name)})


def error_404(request, exception, _template_name='game/error_404.html'):
    """ customized 404 """
    response = render(request, 'game/error_404.html')
    response.status_code = 404
    return response

def error_500(request):
    """ customized 500 """
    response = render(request, 'game/error_500.html')
    response.status_code = 500
    return response
