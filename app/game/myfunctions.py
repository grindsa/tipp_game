# -*- coding: utf-8 -*-
""" functions for tippgame """
# pylint: disable=C0302
from __future__ import print_function
from __future__ import absolute_import
import datetime
import time
import random
from functools import reduce
import urllib
from urllib.request import urlopen
import math
import binascii
import urllib3
import requests
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
import xlsxwriter
from xlsxwriter.utility import xl_rowcol_to_cell
try:
    from ics import Calendar, Event
except BaseException:
    from icalendar import Calendar, Event
from bs4 import BeautifulSoup
from pytz import timezone
from django.contrib.auth import models
from django.contrib.auth.models import Group, User
from django.http import HttpResponse
from django.conf import settings
from django.db.models import Q
from game.models import Team, Match, Tip, Referee, Usersetting, Groupsetting, Season, Presence, Yowsupd, Ranking, Delmatch, Refpermatch, Goal, Pnalty, Visitor, Playerstataggr, Goaliestataggr, Lineup, Playofftree, Playerstatpermatch
from game.libthreema import decode_key, tr_get_credits, encrypt, send_e2e, tr_lookup_pubkey, convert_byte_to_string
import game.rink_dimensions as rd
from trgw.models import Whatsappmessage
from trgw.models import Threemacredit
from game.chartgen import create_player_toi_chart, create_player_scoringpctg_chart, create_player_shot_chart, create_player_corsi_chart, create_player_corsipctg_chart
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

TIMEZONE = timezone('Europe/Berlin')

# get season
def get_u_data(request):
    """ get various usersettings we need here and there """
    # query user settings
    setting_list = Usersetting.objects.filter(user_id=request.user.id).values('group_id', 'user_id', 'season_id', 'group__name', 'dsgvo_ack')[:1]

    # query groups for user and filter -adm out
    group_list = request.user.groups.order_by('id').values('id', 'name')
    group_list = group_list.exclude(name__endswith="-adm")

    group_dic = {}
    for grp in group_list:
        group_dic[grp['id']] = grp['name']

    # query seasons
    season_list = list(Season.objects.order_by('id').values())
    # season id is the last element in list
    season_id = len(season_list)

    # reduce season id by one if there no matches
    m_list = Match.objects.filter(season=season_id).exclude(matchday=0).values('shots')
    if not m_list:
        season_id = season_id - 1

    group = 'default'
    group_id = '1'
    dsgvo_ack = False

    # we have an entry in the user-settings file
    if setting_list:
        # get status of dsgvo acknowledgement
        dsgvo_ack = setting_list[0]['dsgvo_ack']
        # get group name
        # check if user is member of the primary group he has configured in its settings
        if setting_list[0]['group_id'] in group_dic:
            group = setting_list[0]['group__name']
        else:
            # stored group needs to be corrected (set id from first group in list)
            try:
                group_id = group_list[0]['id']
                group = group_list[0]['name']
                obj, _created = Usersetting.objects.update_or_create(user_id=request.user.id, defaults={'group_id': group_id})
                obj.save()
            except BaseException:
                pass

        if ('season_id' in setting_list[0] and setting_list[0]['season_id'] > 0):
            season_id = setting_list[0]['season_id']

        # if default group is stored (group_id 1) and user has groups assigned update settings with the first group-id
        if (setting_list[0]['group_id'] == 1 and group_list):
            group = group_list[0]['name']
            group_id = group_list[0]['id']
            obj, _created = Usersetting.objects.update_or_create(user_id=request.user.id, defaults={'group_id': group_id})
            obj.save()

    # create a new entry
    elif group_list:
        group = group_list[0]['name']
        group_id = group_list[0]['id']
        obj, _created = Usersetting.objects.update_or_create(user_id=request.user.id, defaults={'season_id' : season_id, 'group_id': group_id})
        obj.save()
    elif request.user.id:
        obj, _created = Usersetting.objects.update_or_create(user_id=request.user.id, defaults={'season_id' : season_id})
        obj.save()

    return(season_id, season_list, group, group_dic, dsgvo_ack)

def get_score(result, tip, score_list):
    """ calculate score """
    # initialize score
    score = 0

    if(result and tip):

        # split score
        (result_1, result_2) = result.split(':')
        # split tip
        (tip_1, tip_2) = tip.split(':')

        # calculate goal difference
        result_difference = int(result_1) - int(result_2)
        tip_difference = int(tip_1) - int(tip_2)

        # win/loose correct
        if(result_difference > 0 and tip_difference > 0):
            score = int(score_list[0]['p_winloss'])
        elif(result_difference < 0 and tip_difference < 0):
            score = int(score_list[0]['p_winloss'])

        # goal difference correct
        if result_difference == tip_difference:
            score = int(score_list[0]['p_diff'])

        # game tip correct
        if result == tip:
            score = int(score_list[0]['p_tipp'])

        # 7:2 correct
        if result == '7:2' and tip == '7:2':
            score = int(score_list[0]['p_7vs2'])
        elif result == '2:7' and tip == '2:7':
            score = int(score_list[0]['p_7vs2'])
    elif not tip:
        score = score_list[0]['p_notip']

    return score

# get next match
def get_next_match(uts, season_id):
    """ get next match from database """
    match_list = Match.objects.filter(season_id=season_id).order_by('date', 'matchday').values('id', 'date', 'matchday', 'tv')

    # default value
    match_id = match_list[0]['id']
    tvm = False
    mdate = None
    for match in match_list:
        if uts <= match['date']:
            match_id = match['id']
            tvm = match['tv']
            mdate = match['date']
            break

    if mdate is None:
        tvm = 0
        (match_id, mdate, _mday) = get_last_match(uts, season_id)

    return(match_id, mdate, tvm)


# get next match
def get_next_del_match(uts, season_id):
    """ get next del match """
    match_list = Match.objects.filter(season_id=season_id, no_bet=False).order_by('date', 'matchday').values('id', 'date', 'matchday', 'tv')

    # default value
    match_id = match_list[0]['id']
    tvm = False
    mdate = None
    for match in match_list:
        if uts <= match['date']:
            match_id = match['id']
            tvm = match['tv']
            mdate = match['date']
            break

    if mdate is None:
        tvm = 0
        (match_id, mdate, _mday) = get_last_match(uts, season_id)

    return(match_id, mdate, tvm)

def get_next_home_match(uts, season_id):
    """ get next home match """
    match_list = Match.objects.filter(season_id=season_id).order_by('date', 'matchday').values('id', 'date', 'matchday', 'home_team__short_name', 'guest_team__short_name')

    # default value
    guest_team = None
    match_id = match_list[0]['id']
    mdate = 0
    for match in match_list:
        if uts <= match['date']:
            if match['home_team__short_name'] == 'EBB':
                match_id = match['id']
                guest_team = match['guest_team__short_name']
                mdate = match['date']
                break

    return(match_id, mdate, guest_team)

def get_sleep_counter(request):
    """ get times you need to sleep till next match """
    # query user settings
    try:
        sleep_counter = Usersetting.objects.filter(user_id=request.user.id, sleep_counter=True).values('sleep_counter')[:1][0]
    except BaseException:
        sleep_counter = None

    h_days = None
    team = None
    message = None
    # get days till next home-match
    uts = int(time.time())
    season_id = len(list(Season.objects.order_by('id').values()))
    (_h_id, h_date, team) = get_next_home_match(uts, season_id)

    if sleep_counter:
        now = datetime.datetime.fromtimestamp(int(uts)).strftime('%Y-%m-%d')
        game = datetime.datetime.fromtimestamp(int(h_date)).strftime('%Y-%m-%d')
        t_now = time.mktime(datetime.datetime.strptime(now+' 07:00', '%Y-%m-%d %H:%M').timetuple())
        t_game = time.mktime(datetime.datetime.strptime(game+' 07:00', '%Y-%m-%d %H:%M').timetuple())
        h_days = int((t_game-t_now)/float(86400.0))

        # special case - no next match
        if uts > h_date:
            message = None
        elif(h_days > 0 and team):
            message = 'Noch {0}-mal schlafen bis zum nächsten Heimspiel gegen {1}...'.format(str(h_days), team)
        elif(h_days == 0 and team):
            message = 'Achtung: Heute Heimspiel gegen {0}!'.format(team)

    return message

def get_last_match(uts, season_id):
    """ get last match from database """
    match_list = Match.objects.filter(season_id=season_id).order_by('date', 'matchday').values('id', 'date', 'matchday', 'result')

    # default value
    match_id = None
    match_day = None
    match_date = None
    for match in match_list:
        if int(match['date']) <= int(uts):
            match_id = match['id']
            match_day = match['matchday']
            match_date = match['date']

    return(match_id, match_date, match_day)

def get_matches(request, u_season_id):
    """ get list of matches """
    team_list = list(Team.objects.order_by('team_id').values())
    tmp_team_name_list = {}
    tmp_team_logo_url_list = {}

    # identify UA to detect mobiles
    mobile_browser = request.mobile

    ebb_id = None
    ebb_sn = 'EBB'

    for team in team_list:
       # fill dictionary depending on browser
        if mobile_browser:
            tmp_team_name_list[team['team_id']] = team['short_name']
        else:
            tmp_team_name_list[team['team_id']] = team['team_name']

        tmp_team_logo_url_list[team['team_id']] = team['logo_url']

        if team['short_name'] == ebb_sn:
            ebb_id = team['team_id']

    match_list = list(Match.objects.filter(season_id=u_season_id, no_bet=False).order_by('date', 'matchday').values())

    for match in match_list:

        match['date_human'] = datetime.datetime.fromtimestamp(match['date'], tz=TIMEZONE).strftime('%d.%m.%Y')
        match['time_human'] = datetime.datetime.fromtimestamp(match['date'], tz=TIMEZONE).strftime('%H:%M')

        if match['home_team_id'] == ebb_id:
            # homematch
            match['guest_kye'] = '/game/kye?oteam_id={0}'.format(match['guest_team_id'])
        else:
            match['home_kye'] = '/game/kye?oteam_id={0}'.format(match['home_team_id'])

        # add home team and logo
        match['home'] = tmp_team_name_list[match['home_team_id']]
        match['home_logo'] = tmp_team_logo_url_list[match['home_team_id']]

        # add guest team and logo
        match['guest'] = tmp_team_name_list[match['guest_team_id']]
        match['guest_logo'] = tmp_team_logo_url_list[match['guest_team_id']]

        if match['result'] is None:
            match['result'] = ''
        elif ':' in match['result']:
            (winloss, detail, goal, ggoal) = get_winloss(match['home_team_id'], ebb_id, match['result'])
            match['winloss'] = winloss
            match['detail'] = detail
            match['goal'] = goal
            match['ggoal'] = ggoal

        # add radio link
        rl_url = add_rl_url(int(match['guest_team_id']), team_list, ebb_id)
        if rl_url:
            match['url'] = rl_url

    return match_list

def add_rl_url(rl_id, team_list, _ebb_id):
    """ add r 1 rul """
    url = None
    for team in team_list:
        if rl_id == int(team['team_id']):
            url = team['radio_url']
    return url

def get_ftipstats(u_season_id, group_filter, team_filter, query_filter):
    """ get ftipstats """
    # get teamid of ebb)
    team_list = Team.objects.filter(short_name=team_filter).values('team_id')
    ebb_id = team_list[0]['team_id']

    # get users member of this group
    group = models.Group.objects.get(name=group_filter)
    users = group.user_set.all()

    # get group-specific scores
    score_list = Groupsetting.objects.filter(group__name=group_filter).values('p_winloss', 'p_diff', 'p_tipp', 'p_7vs2', 'p_notip')[:1]

    # get list of tips
    score_dict = {}
    user_dict = {}

    # get all tips for the group
    tip_list = Tip.objects.filter(user_id__in=users, match__season_id=u_season_id).values('match_id', 'match__result', 'match__home_team_id', 'match__guest_team_id', 'user_id', 'user__username', 'tip')
    for tip in tip_list:
        if tip[query_filter] == ebb_id:

            # create tip dictionary
            score = get_score(tip['match__result'], tip['tip'], score_list)

            if tip['user_id'] in score_dict:
                score_dict[tip['user_id']] += score
            else:
                score_dict[tip['user_id']] = score

            # create user dictionary if not available
            if tip['user_id'] not in user_dict:
                user_dict[tip['user_id']] = {}
            user_dict[tip['user_id']]['username'] = tip['user__username']

            # count the number of full scores
            if score == 4:
                if 'vt' in user_dict[tip['user_id']]:
                    user_dict[tip['user_id']]['vt'] += 1
                else:
                    user_dict[tip['user_id']]['vt'] = 1

            # count the number of correct tips
            if score > 0:
                if 'rt' in user_dict[tip['user_id']]:
                    user_dict[tip['user_id']]['rt'] += 1
                else:
                    user_dict[tip['user_id']]['rt'] = 1

    return(score_dict, user_dict)

def get_tipdistribution(u_season_id, group_filter, match_id, team_filter):
    """ get tipdistribution """
    # get users member of this group
    group = models.Group.objects.get(name=group_filter)
    users = group.user_set.all()

    # get EBB ID
    team_list = Team.objects.filter(short_name=team_filter).values('team_id')
    ebb_id = team_list[0]['team_id']

    # get score_list
    score_list = Groupsetting.objects.filter(group__name=group_filter).values('p_winloss', 'p_diff', 'p_tipp', 'p_7vs2', 'p_notip')[:1]

    tipd_dic = {}
    tipr_dic = {}
    # get all tips for the group
    tip_list = Tip.objects.filter(user_id__in=users, match__season_id=u_season_id, match_id__lte=match_id).values('match_id', 'match__home_team_id', 'match__result', 'user_id', 'user__username', 'tip')
    for tip_ in tip_list:
        tip = None
        if tip_['match__home_team_id'] == ebb_id:
            tip = tip_['tip']
        else:
            (htip, gtip) = tip_['tip'].split(':')
            tip = '{0}:{1}'.format(gtip, htip)

        if tip not in tipd_dic:
            tipd_dic[tip] = 1
        else:
            tipd_dic[tip] = tipd_dic[tip] + 1

    count = 0
    tipd_list = []
    for tip_, _num in sorted(list(tipd_dic.items()), key=lambda x: x[1], reverse=True):
        count = count + 1
        if count <= 10:
            tipd_list.append(tip_)

    # get results from all matches this season
    match_list = Match.objects.filter(season_id=u_season_id, id__lte=match_id).exclude(result=None).values('id', 'home_team_id', 'result')
    for match in match_list:
        result = None
        if match['home_team_id'] == ebb_id:
            result = '{0}'.format(match['result'])
        else:
            try:
                (htip, gtip) = match['result'].split(':')
                result = '{0}:{1}'.format(gtip, htip)
            except BaseException:
                result = '0:0'

        for tip_ in tipd_dic:
            score = get_score(result, tip_, score_list)
            if tip_ not in tipr_dic:
                tipr_dic[tip_] = {}
                tipr_dic[tip_]['s'] = score
                if match['home_team_id'] == ebb_id:
                    tipr_dic[tip_]['h'] = score
                    tipr_dic[tip_]['g'] = 0
                else:
                    tipr_dic[tip_]['g'] = score
                    tipr_dic[tip_]['h'] = 0
            else:
                tipr_dic[tip_]['s'] = tipr_dic[tip_]['s'] + score
                if match['home_team_id'] == ebb_id:
                    tipr_dic[tip_]['h'] = tipr_dic[tip_]['h'] + score
                else:
                    tipr_dic[tip_]['g'] = tipr_dic[tip_]['g'] + score

    tipr_list = sort_dic(tipr_dic, 's', True)

    if len(tipr_list) > 10:
        tipr_list = tipr_list[:10]

    return(tipd_list, tipd_dic, tipr_list, tipr_dic)

def get_tipstats(u_season_id, group_filter, match_id, bad_tip, team_filter, delta=False):
    """ get tipstats """

    # get users member of this group
    group = models.Group.objects.get(name=group_filter)
    users = group.user_set.all()

    score_list = Groupsetting.objects.filter(group__name=group_filter).values('p_winloss', 'p_diff', 'p_tipp', 'p_7vs2', 'p_notip', 'rl_number')[:1]

    # get list of tips
    score_dict = {}
    o_score_dict = {}
    user_dict = {}

    # get teamid of ebb)
    team_list = Team.objects.filter(short_name=team_filter).values('team_id')
    ebb_id = team_list[0]['team_id']

    # get all tips for the group
    tip_list = Tip.objects.filter(user_id__in=users, match__season_id=u_season_id, match_id__lte=match_id).values('match_id', 'match__home_team_id', 'match__result', 'user_id', 'user__username', 'tip')
    full_score = int(score_list[0]['p_tipp'])

    for tip in tip_list:
        # create user dictionary if not available
        if tip['user_id'] not in user_dict:
            user_dict[tip['user_id']] = {}

        user_dict[tip['user_id']]['username'] = tip['user__username']

        # create tip dictionary
        score = get_score(tip['match__result'], tip['tip'], score_list)

        if bad_tip:
            # detect tip against the team
            (atip, btip) = tip['tip'].split(':')
            if tip['match__home_team_id'] == ebb_id:
                # home match
                if atip < btip:
                    # this is a tip against us
                    if tip['user_id'] in score_dict:
                        score_dict[tip['user_id']] += 1
                    else:
                        score_dict[tip['user_id']] = 1
            else:
                # on the road
                if btip < atip:
                    # this is a top against us
                    if tip['user_id'] in score_dict:
                        score_dict[tip['user_id']] += 1
                    else:
                        score_dict[tip['user_id']] = 1

            # check score
            diff = 0
            if(tip['match__result'] and ':' in tip['match__result']):
                (atip, btip) = tip['match__result'].split(':')
                diff = int(atip)-int(btip)

            # win or loose
            outcome = None

            # home or on-the-road
            if tip['match__home_team_id'] == ebb_id:
                if diff > 0:
                    outcome = "W"
                else:
                    outcome = "L"
            else:
                if diff > 0:
                    outcome = "L"
                else:
                    outcome = "W"

            # dont know why id did this but lets not interfer
            if outcome == "L":
                if score > 0:
                    # count the number of correct tips
                    if 'rt' in user_dict[tip['user_id']]:
                        user_dict[tip['user_id']]['rt'] += 1
                    else:
                        user_dict[tip['user_id']]['rt'] = 1

                    # count the score
                    if 'score' in user_dict[tip['user_id']]:
                        user_dict[tip['user_id']]['score'] += score
                    else:
                        user_dict[tip['user_id']]['score'] = score

                # count the number of full scores
                if score == int(score_list[0]['p_tipp']):
                    if 'vt' in user_dict[tip['user_id']]:
                        user_dict[tip['user_id']]['vt'] += 1
                    else:
                        user_dict[tip['user_id']]['vt'] = 1
        else:
            if tip['user_id'] in score_dict:
                score_dict[tip['user_id']] += score
            else:
                score_dict[tip['user_id']] = score

            if delta:
                # we count the score till previous match
                if tip['match_id'] < match_id - 1:
                    if tip['user_id'] in o_score_dict:
                        o_score_dict[tip['user_id']] += score
                    else:
                        o_score_dict[tip['user_id']] = score

            # count the number of full scores
            # if score == int(score_list[0]['p_tipp']):
            if score == full_score:
                if 'vt' in user_dict[tip['user_id']]:
                    user_dict[tip['user_id']]['vt'] += 1
                else:
                    user_dict[tip['user_id']]['vt'] = 1

            # count the number of correct tips
            if score > 0:
                if 'rt' in user_dict[tip['user_id']]:
                    user_dict[tip['user_id']]['rt'] += 1
                else:
                    user_dict[tip['user_id']]['rt'] = 1

            # detect tip against the team
            (atip, btip) = tip['tip'].split(':')
            if tip['match__home_team_id'] == ebb_id:
                # home match
                if atip < btip:
                    # this is a tip against us
                    user_dict[tip['user_id']]['pg'] = 1

            else:
                # on the road
                if btip < atip:
                    # this is a tip against us
                    user_dict[tip['user_id']]['pg'] = 1

    # red lantern hack
    try:
        rl_number = score_list[0]['rl_number']
    except BaseException:
        rl_number = 1

    # sort score_dic
    score_list = sort_score(score_dict, user_dict)

    # flag user with red lantern if we need to do so
    if  rl_number != 0:
        rl_list = score_list[rl_number*(-1):]

        for rlt in rl_list:
            user_dict[rlt]['rl'] = True

    # some delta stuff (in case it is required)
    if delta:
        # o_score_list = []
        # for key, _val in sorted(list(o_score_dict.items()), key=lambda x: x[1], reverse=True):
        #     o_score_list.append(key)
        o_score_list = sort_score(o_score_dict, user_dict)

        count = 0
        for ele in score_list:
            count = count + 1
            if ele in o_score_list:
                user_dict[ele]['lw'] = o_score_list.index(ele) + 1
                user_dict[ele]['lwd'] = o_score_list.index(ele) + 1 - count

            if 'lwd' in user_dict[ele]:
                if user_dict[ele]['lwd'] <= 0:
                    user_dict[ele]['alwd'] = (o_score_list.index(ele) + 1 - count)
    return(score_dict, user_dict, score_list)

def sort_score(score_dict, new_user_dict):
    """ sort score """
    # copy user_dict (just to be save)
    # new_user_dict = user_dict.copy()

    # enrich new_user_dict with vt and score
    for user in new_user_dict:
        if 'vt' not in new_user_dict[user]:
            new_user_dict[user]['vt'] = 0
        if user in score_dict:
            new_user_dict[user]['score'] = score_dict[user]
        else:
            new_user_dict[user]['score'] = 0

    # sort user_dict by score, vt, name
    nnew_user_dict = list(new_user_dict.items())
    nnew_user_dict.sort(key=lambda k_d: (-k_d[1]['score'], k_d[1]['username']))

    # create and output list to be backward compatible to old implementation
    out_list = []
    for user in nnew_user_dict:
        out_list.append(user[0])

    # return list
    return out_list

def get_ref_stats(u_season_id, team_filter, filter_):
    """ get ref stats """
    # get teamid of ebb)
    team_list = Team.objects.filter(short_name=team_filter).values('team_id')
    ebb_id = team_list[0]['team_id']

    # unix timestamp
    uts = int(time.time())

    match_list = {}

    if filter_:
        match_list = Match.objects.filter(**{filter_: ebb_id}).filter(season_id=u_season_id, date__lt=uts).exclude(matchday=0).order_by('matchday').values('id', 'date', 'matchday', 'home_team_id', 'result', 'refpermatch__r1_id', 'refpermatch__r2_id')
    else:
        match_list = Match.objects.filter(season_id=u_season_id, date__lt=uts).order_by('matchday').exclude(matchday=0).values('id', 'date', 'matchday', 'home_team_id', 'result', 'refpermatch__r1_id', 'refpermatch__r2_id')

    # build dict for ref-names
    ref_name_dict = {}
    ref_name_list = Referee.objects.values('id', 'name')
    for ref in ref_name_list:
        ref_name_dict[ref['id']] = ref['name']

    ref_dict = {}
    ref_pm_dict = {}

    for match in match_list:
        if match['result']:
            # create ref dictionary structure if not available
            if match['refpermatch__r1_id'] not in ref_dict:
                ref_dict[match['refpermatch__r1_id']] = {}
            if match['refpermatch__r2_id'] not in ref_dict:
                ref_dict[match['refpermatch__r2_id']] = {}

            # store names in hash
            if match['refpermatch__r1_id']:
                ref_dict[match['refpermatch__r1_id']]['name'] = ref_name_dict[match['refpermatch__r1_id']]
            if match['refpermatch__r2_id']:
                ref_dict[match['refpermatch__r2_id']]['name'] = ref_name_dict[match['refpermatch__r2_id']]

            if 'W' not in ref_dict[match['refpermatch__r1_id']]:
                ref_dict[match['refpermatch__r1_id']]['W'] = 0
            if 'L' not in ref_dict[match['refpermatch__r1_id']]:
                ref_dict[match['refpermatch__r1_id']]['L'] = 0
            if 'W' not in ref_dict[match['refpermatch__r2_id']]:
                ref_dict[match['refpermatch__r2_id']]['W'] = 0
            if 'L' not in ref_dict[match['refpermatch__r2_id']]:
                ref_dict[match['refpermatch__r2_id']]['L'] = 0

            # check score
            try:
                (amatch, bmatch) = match['result'].split(':')
                diff = int(amatch)-int(bmatch)
            except BaseException:
                diff = 0

            # win or loose
            outcome = None
            # home or on-the-road
            if match['home_team_id'] == ebb_id:
                if diff > 0:
                    outcome = "W"
                else:
                    outcome = "L"
            else:
                if diff > 0:
                    outcome = "L"
                else:
                    outcome = "W"

            # count matches per ref
            if 'matches' in ref_dict[match['refpermatch__r1_id']]:
                ref_dict[match['refpermatch__r1_id']]['matches'] += 1
            else:
                ref_dict[match['refpermatch__r1_id']]['matches'] = 1

            if 'matches' in ref_dict[match['refpermatch__r2_id']]:
                ref_dict[match['refpermatch__r2_id']]['matches'] += 1
            else:
                ref_dict[match['refpermatch__r2_id']]['matches'] = 1

            # count win/loose per ref
            ref_dict[match['refpermatch__r1_id']][outcome] += 1
            ref_dict[match['refpermatch__r2_id']][outcome] += 1

            # count plus/minus
            if not match['refpermatch__r1_id'] in ref_pm_dict:
                ref_pm_dict[match['refpermatch__r1_id']] = 0
            if not match['refpermatch__r2_id'] in ref_pm_dict:
                ref_pm_dict[match['refpermatch__r2_id']] = 0

            if outcome == "W":
                ref_pm_dict[match['refpermatch__r1_id']] += 1
                ref_pm_dict[match['refpermatch__r2_id']] += 1
            else:
                ref_pm_dict[match['refpermatch__r1_id']] -= 1
                ref_pm_dict[match['refpermatch__r2_id']] -= 1


    return(ref_dict, ref_pm_dict)

def get_user_settings(group_filter):
    """ get user settings """
    group = models.Group.objects.get(name=group_filter)
    users = group.user_set.all().order_by('username')

    setting_list = Usersetting.objects.filter(user_id__in=users).order_by('user').values('user', 'user__username', 'hide_tips', 'season')

    setting_dict = {}
    for setting in setting_list:
        setting_dict[setting['user__username']] = {}
        setting_dict[setting['user__username']]['hide_tips'] = setting['hide_tips']
        setting_dict[setting['user__username']]['season'] = setting['season']

    return setting_dict

def get_single_user_settings(uid):
    """ get settings for a single user """
    setting_list = Usersetting.objects.filter(user=uid).order_by('user').values('user', 'user__username', 'hide_tips', 'season', 'threema', 'sleep_counter', 'threema_reminder', 'threema_pk', 'dkp', 'send_ticker')
    setting_dict = {}
    if setting_list:
        setting_dict['hide_tips'] = setting_list[0]['hide_tips']
        setting_dict['season'] = setting_list[0]['season']
        setting_dict['threema'] = setting_list[0]['threema']
        setting_dict['threema_pk'] = setting_list[0]['threema_pk']
        setting_dict['sleep_counter'] = setting_list[0]['sleep_counter']
        setting_dict['threema_reminder'] = setting_list[0]['threema_reminder']
        setting_dict['send_ticker'] = setting_list[0]['send_ticker']
        setting_dict['dkp'] = setting_list[0]['dkp']

    return setting_dict

def xls_to_response(users, match_list, tip_list, uts, group_filter):
    """ create excel file """
    # create user_dic from users (for faster lookups)
    user_dic = {}
    userlist = []

    # get group-specific scores
    score_list = Groupsetting.objects.filter(group__name=group_filter).values('p_winloss', 'p_diff', 'p_tipp', 'p_7vs2', 'p_notip')[:1]

    for usr in users:
        user_dic[usr['id']] = usr['username']
        userlist.append(usr['username'])

    # create match_dic from match_list (for faster lookups)
    match_dic = {}
    for match in match_list:
        # print(m['id'])
        if match['result']:
            match_dic[match['id']] = {}
            match_dic[match['id']]['matchday'] = match['matchday']
            match_dic[match['id']]['date'] = match['date_human']
            match_dic[match['id']]['home'] = match['home']
            match_dic[match['id']]['guest'] = match['guest']
            match_dic[match['id']]['result'] = match['result']

    # create structured dic for tips
    tip_dic = {}
    for tip in tip_list:
        if tip['user_id'] in user_dic:
            if tip['match_id'] not in tip_dic:
                tip_dic[tip['match_id']] = {}
            tip_dic[tip['match_id']][user_dic[tip['user_id']]] = tip['tip']

    # create a workbook in memory
    output = BytesIO()

    workbook = xlsxwriter.Workbook(output)
    sheet = workbook.add_worksheet(datetime.datetime.fromtimestamp(uts, tz=TIMEZONE).strftime('%d.%m.%Y'))
    f_head = workbook.add_format({'bold': True, 'bg_color': '#cc0000', 'font_size': 14, 'font_color': '#ffffff'})
    f_tabhead = workbook.add_format({'bold': True, 'bg_color': '#030357', 'font_color': '#ffffff'})
    f_tabheadc = workbook.add_format({'bold': True, 'bg_color': '#030357', 'align': 'center', 'font_color': '#ffffff'})
    f_tabhead2 = workbook.add_format({'bold': True, 'bg_color': '#7f7f7f', 'font_color': '#ffffff'})
    f_tabhead2c = workbook.add_format({'bold': True, 'bg_color': '#7f7f7f', 'align': 'center', 'font_color': '#ffffff'})
    f_uneven = workbook.add_format({'font_color': '#404040'})
    f_unevenc = workbook.add_format({'font_color': '#404040', 'align': 'center'})
    f_even = workbook.add_format({'bg_color': '#f1f1f1', 'font_color': '#404040'})
    f_evenc = workbook.add_format({'bg_color': '#f1f1f1', 'font_color': '#404040', 'align': 'center'})

    # width for the first 5 columns
    sheet.set_column(0, 0, 5)
    sheet.set_column(1, 1, 15)
    sheet.set_column(2, 3, 25)
    sheet.set_column(4, 4, 8)

    # headline
    cell1 = xl_rowcol_to_cell(0, 0)
    cell2 = xl_rowcol_to_cell(0, 4)
    # cell2 = xl_rowcol_to_cell(0,4+len(userlist)*2)
    sheet.merge_range(cell1+':'+cell2, 'Tippspiel: Auswertung zum Nachrechnen', f_head)

    cell1 = xl_rowcol_to_cell(0, 5)
    cell2 = xl_rowcol_to_cell(0, 4+len(userlist)*2)
    sheet.merge_range(cell1+':'+cell2, 'Gruppe: '+group_filter, f_head)

    # headline1
    row = 1
    sheet.write(row, 0, '#', f_tabheadc)
    sheet.write(row, 1, 'Datum', f_tabhead)
    sheet.write(row, 2, 'Heim', f_tabhead)
    sheet.write(row, 3, 'Gast', f_tabhead)
    sheet.write(row, 4, 'Ergebnis', f_tabhead)
    col = 5

    for usr in sorted(userlist):
        cell1 = xl_rowcol_to_cell(1, col)
        col = col + 1
        cell2 = xl_rowcol_to_cell(1, col)
        col = col + 1
        # merge cells for user
        sheet.merge_range(cell1+':'+cell2, usr, f_tabheadc)

    # headline 2
    row = row + 1
    cell1 = xl_rowcol_to_cell(row, 0)
    cell2 = xl_rowcol_to_cell(row, 4)
    sheet.merge_range(cell1+':'+cell2, '', f_tabhead2)
    col = 5
    for usr in sorted(userlist):
        sheet.write(row, col, 'Tip', f_tabhead2)
        sheet.set_column(col, col+1, 5)
        col = col + 1
        sheet.write(row, col, 'Pkt', f_tabhead2)
        col = col + 1

    # matches + tops per user
    row = row + 1
    score_dic = {}
    for match in sorted(match_dic):
        _format = f_uneven
        _formatc = f_unevenc
        if row % 2 == 0:
            _format = f_even
            _formatc = f_evenc
        sheet.write(row, 0, match_dic[match]['matchday'], _format)
        sheet.write(row, 1, match_dic[match]['date'], _format)
        sheet.write(row, 2, match_dic[match]['home'], _format)
        sheet.write(row, 3, match_dic[match]['guest'], _format)
        sheet.write(row, 4, match_dic[match]['result'], _format)
        col = 5
        for usr in sorted(userlist):
            tip = '  -'
            pkt = 0
            if match in tip_dic:
                if usr in tip_dic[match]:
                    tip = tip_dic[match][usr]
                    pkt = get_score(match_dic[match]['result'], tip, score_list)
            sheet.write(row, col, tip, _format)
            col = col + 1
            if usr in score_dic:
                score_dic[usr] = score_dic[usr] + pkt
            else:
                score_dic[usr] = pkt
            sheet.write(row, col, pkt, _formatc)
            col = col + 1

        row = row + 1

    # summary
    cell1 = xl_rowcol_to_cell(row, 0)
    cell2 = xl_rowcol_to_cell(row, 4)
    sheet.merge_range(cell1+':'+cell2, 'Summe', f_tabhead2)
    col = 5
    for usr in sorted(userlist):
        sheet.write(row, col, '', f_tabhead2)
        col = col + 1
        if usr in score_dic:
            sheet.write(row, col, score_dic[usr], f_tabhead2c)
        else:
            sheet.write(row, col, '0', f_tabhead2c)
        col = col + 1
    workbook.close()

    # construct response
    output.seek(0)

    response = HttpResponse(output.read(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = 'attachment; filename=%s' % 'report-'+datetime.datetime.fromtimestamp(uts, tz=TIMEZONE).strftime('%Y-%m-%d')+'.xlsx'

    return response

def ics_to_response(match_list, filename):
    """ return calendar file """
    cal = Calendar()
    cal.add('version', '2.0')
    cal.add('prodid', '-//tipp_game//dynamop//')
    cal.add('X-WR-CALNAME', 'EBB Spielplan')
    cal.add('TZID', TIMEZONE)
    if len(match_list) > 1:
        # multiple events (create full calendar)
        for match in match_list:
            event = Event()
            event.add('summary', str(match['matchday'])+'. Spieltag: '+match['home']+' vs. '+ match['guest'])
            event.add('dtstart', datetime.datetime.fromtimestamp(match['date'], tz=TIMEZONE))
            event.add('dtend', datetime.datetime.fromtimestamp(match['date']+9000, tz=TIMEZONE))
            event.add('priority', 5)
            event['uid'] = str(match['matchday'])+'@dynamop'
            cal.add_component(event)
    else:
        # single event
        cal.add('method', 'REQUEST')
        event = Event()
        event.add('summary', str(match_list[0]['matchday'])+'. Spieltag: '+match_list[0]['home']+' vs. '+ match_list[0]['guest'])
        event.add('dtstart', datetime.datetime.fromtimestamp(match_list[0]['date']-3600, tz=TIMEZONE))
        event.add('dtend', datetime.datetime.fromtimestamp(match_list[0]['date']+9000-3600, tz=TIMEZONE))
        event.add('priority', 5)
        event['uid'] = str(match_list[0]['matchday'])+'@dynamop'
        cal.add_component(event)

    response = HttpResponse(cal.to_ical(), content_type='text/calendar')
    response['Content-Disposition'] = 'attachment; filename=%s' % filename
    return response

def send_threema(tid, secret, ske, receiver, text):
    """ send threema session """
    # get public key from user profile
    try:
        pke = Usersetting.objects.filter(threema=receiver).values_list('threema_pk', flat=True)
        user_exist = len(pke)
        pke = pke[0]
    except BaseException:
        pke = ''
        user_exist = None

    text = convert_byte_to_string(text)

    # add remaining threema credits if needed
    tr_sponsors = ['eszuspde', 'dbuf47v8']
    if receiver.lower() in tr_sponsors:
        trc = tr_get_credits(settings.TR_ID, settings.TR_SECRET)
        if trc:
            text = '{0}\nThreema-credits: {1}'.format(text, trc)

    # we have the user but missing the pub key
    if user_exist:
        if pke == '' or pke is None:
            # fetch pub key and update db
            pke = tr_lookup_pubkey(receiver, tid, secret)
            if pke:
                # Usersetting.objects.filter(threema = 'gna').update('threema_pk' = 'gna')
                obj, _created = Usersetting.objects.update_or_create(threema=receiver, defaults={'threema_pk' : pke})
                obj.save()

    # decode keys and define message type (threema prerequisite)
    private_key = decode_key(ske)
    public_key = decode_key(pke)
    text_message_type = b'\x01'

    # encrypt the message
    (nonce, message) = encrypt(private_key, public_key, text_message_type + text.encode('utf-8'))

    # send message
    # print(receiver,text,message)
    _rc = send_e2e(tid, receiver, message, nonce, secret)

def lookup_sender(snd_string):
    """ carve out sender """
    snd_string
    source, sender, = snd_string.split(' ')
    sender = sender.lstrip('[')
    sender = sender.rstrip(']')
    sender = sender.lstrip('+')
    return source, sender

def lookup_user_by_mobilenumber(sender):
    """ lookup user by mobile phone number """
    uid = None
    username = None

    # _source, sender = lookup_sender(sender)

    number_list = Usersetting.objects.filter(mobile_number__isnull=False).exclude(mobile_number='').values('user_id', 'user__username', 'mobile_number')

    for num in number_list:
        try:
            number = ''.join(list(filter(str.isdigit, str(num['mobile_number']))))
        except BaseException:
            number = 0

        if int(number) == int(sender):
            username = num['user__username']
            uid = num['user_id']
            break

    return(uid, username)

def parse_message(body, sender, source, message_uts):
    """ parse message """
    reply = False
    message = None

    # get matchnumber
    # unix timestamp
    uts = int(time.time())
    season_id = len(list(Season.objects.values()))
    (match_id, match_uts, _sinin) = get_last_match(uts, season_id)
    result = Match.objects.filter(id=match_id).values_list('result', flat=True)[:1]

    # get the first word
    try:
        fword = body.split()[0]
    except BaseException:
        fword = ''

    # store message in database
    datadict = {
        'source' : source,
        'sender' : sender,
        'date' : message_uts,
        'text' : binascii.hexlify(body.encode()),
    }

    # something strange over there
    obj, _created = Whatsappmessage.objects.update_or_create(date=message_uts, defaults=datadict)
    obj.save()

    # this is the echo test of or daemon
    if fword.lower() == 'echo':
        reply = True
        message = 'ich reagiere auf "echo"'
    elif 'tüdelü' in body.lower():
        reply = True
        message = 'tüdelü...'.encode() + b'\xF0\x9F\x98\x8A'
    elif 'was essen die studenten' in body.lower():
        reply = True
        message = b'Enten...\xF0\x9F\x98\x8A'
    elif('wischenstand' in fword or body.startswith('wie steht') or body.startswith('Wie steht') or body.startswith('Wer liegt vorn')):
        reply = True
        # answer only if message comes in during a match (matchdate + 10800 seconds)
        if(int(match_uts) < int(message_uts) and uts-match_uts < 10800):
            message = 'Es steht momentan %s' % (result[0])
        else:
            message = 'Es läuft gerade kein Spiel...'
    elif 'yeah' in body.lower():
        reply = True
        message = b'\xF0\x9F\x91\x8D'
    elif 'bump' in body.lower():
        reply = True
        message = b'\xF0\x9F\xA4\x9c\xF0\x9F\xA4\x9B'
    elif 'boom' in body.lower():
        reply = True
        message = b'\xF0\x9F\x91\x8A'
    elif('Wer ist raus' in body or 'wer ist raus' in body):
        reply = True
        # answer only if message comes in during a match (matchdate + 10800 seconds)
        if(int(match_uts) < int(message_uts) and uts-match_uts < 10800):
            # loockup group-name
            (number, _sinin) = source.split('@')
            group = Groupsetting.objects.filter(yao_message=True, number=number).values_list('group__name', flat=True)[:1]
            if(group and result):
                try:
                    (hscore, gscore) = result[0].split(':')
                except BaseException:
                    hscore = None
                    gscore = None
                if hscore and gscore:
                    message = yao_send(hscore, gscore, match_id, group[0])
        else:
            message = 'Es läuft gerade kein Spiel...'
    elif('estzeit' in fword or 'ie lange' in body or fword == 'Dauer?' or fword == 'dauer?'):

        reply = True
        # check if the match is already over
        try:
            done = Match.objects.filter(id=match_id).values_list('done', flat=True)[0]
            done = bool(done)
        except BaseException:
            done = True

        # do not execute the script if the match is over
        if done:
            message = 'Spiel ist beendet'
        else:
            message = Match.objects.filter(id=match_id).values_list('remaining', flat=True)[:1][0]

    elif(fword == 'whoami' or fword == 'Whoami' or 'er bin ich' in body):
        reply = True
        (user_id, username) = lookup_user_by_mobilenumber(sender)
        if user_id:
            message = 'Hallo. Du bist "%s"...' % (username)
        else:
            message = 'Benutzer konnte nicht identifiziert werden'

    elif('hallo boot' in body.lower() or 'hallo bot' in body.lower()):
        reply = True
        (user_id, username) = lookup_user_by_mobilenumber(sender)
        if user_id:
            message = 'Hallo {0}... '.format(username).encode() + b'\xF0\x9F\x98\x98'
        else:
            message = 'Hallo... Bin leicht verwirrt und weiss nicht wer du bist. hicks'

    elif(fword.lower() == 'tipptabelle' or fword.lower() == 'tipp-tabelle' or fword.lower() == 'tipptabelle?' or fword.lower() == 'tipp-tabelle?'):
        # filter source
        try:
            (f_source, _sinin) = source.split('@')
        except BaseException:
            f_source = source

        # lookup whatsappgroup
        try:
            group_filter = Group.objects.filter(groupsetting__number=f_source).values_list('name', flat=True)[0]
        except BaseException:
            group_filter = None

        if group_filter:
            reply = True
            message = 'Hier die aktuelle Tipptabelle der Gruppe "{0}":'.format(group_filter)
            # get score
            (score_dict, user_dict, _sort_list) = get_tipstats(season_id, group_filter, match_id, False, 'EBB')
            rank = 0
            for score in sorted(list(score_dict.items()), key=lambda x: x[1], reverse=True):
                rank = rank + 1
                message = '{0}\n{1}. {2} - {3}'.format(message, rank, user_dict[score[0]]['username'], score[1])

    elif('wer führt' in body.lower() or 'wer ist erster' in body.lower() or fword == 'Spitzenreiter?' or fword == 'spitzenreiter?'):
        try:
            (f_source, _sinin) = source.split('@')
        except BaseException:
            f_source = source

        # lookup whatsappgroup
        try:
            group_filter = Group.objects.filter(groupsetting__number=f_source).values_list('name', flat=True)[0]
        except BaseException:
            group_filter = None

        if group_filter:
            reply = True
            # get score
            (score_dict, user_dict, sort_list) = get_tipstats(season_id, group_filter, match_id, False, 'EBB')
            message = 'Stand heute kriegt {0} den Pott...'.format(user_dict[sort_list[0]]['username'])

    elif('trcredit' in fword.lower() or fword.lower == 'threemacredits'):

        try:
            # get threema credits
            url = 'https://msgapi.threema.ch/credits?from={0}&secret={1}'.format(settings.TR_ID, settings.TR_SECRET)
            fso = urlopen(url)
            num = int(fso.read())

            # store value in database
            obj = Threemacredit(date=uts, credit=num)
            obj.save()

            # prepare reply
            reply = True
            message = 'noch vorhandene Threemacredits: {0}'.format(str(num))
        except BaseException:
            reply = False
            message = None

    elif('Bin ich Erster' in body or 'Bin ich erster' in body):

        (user_id, username) = lookup_user_by_mobilenumber(sender)
        # filter source
        try:
            (f_source, _sinin) = source.split('@')
        except BaseException:
            f_source = source

        # lookup whatsappgroup
        try:
            group_filter = Group.objects.filter(groupsetting__number=f_source).values_list('name', flat=True)[0]
        except BaseException:
            group_filter = None

        if group_filter:
            looser_list = [
                'http://data.whicdn.com/images/16254825/large.jpg',
                'http://2.bp.blogspot.com/_uryklxaJbfs/TKPiWZ-wG1I/AAAAAAAACtM/OB3djNk27Ow/s1600/looser.jpg',
                'https://s-media-cache-ak0.pinimg.com/736x/e8/43/12/e843122307f6b2f794614ff896d215ed.jpg',
                'https://images.gutefrage.net/media/fragen-antworten/bilder/122506702/0_big.jpg?v=1399029738000',
                'http://www.quotationof.com/images/looser-quotes-1.jpg',
                'http://2.bp.blogspot.com/_gCGdjdx5zIE/TEESajoUZcI/AAAAAAAAADU/JI2F9kWmhsw/s1600/looser.gif',
                'https://thumbs.dreamstime.com/z/looser-man-7810226.jpg']

            reply = True
            # get score
            (score_dict, user_dict, _sort_list) = get_tipstats(season_id, group_filter, match_id, False, 'EBB')
            if (sorted(list(score_dict.items()), key=lambda x: x[1], reverse=True)[0][0]) == user_id:
                message = 'Glückwunsch {0}. Die bist Spitzenreiter.... {1}'.format(username, 'https://www.youtube.com/watch?v=Y_togxFhNJs')
            else:
                message = '{0}. Leider führst du nicht und ich habe heute auch kein Foto für dich. Oder doch warte mal... {1} .'.format(username, random.choice(looser_list)).encode() + b'\xF0\x9F\x98\x82'

    elif fword in ('schummel', 'Schummel'):

        reply = True
        # identify user based on mobile number and check if he is allowed to report cheating
        (user_id, username) = lookup_user_by_mobilenumber(sender)
        try:
            cheat_detector = Usersetting.objects.filter(user_id=user_id).values_list('cheat_detector', flat=True)[:1][0]
        except BaseException:
            cheat_detector = False

        # yes he is allowed to report cheating
        if cheat_detector is True:

            # get userid
            user_dic = {}
            user_list = User.objects.values('id', 'username')
            for usr in user_list:
                user_dic[usr['username'].lower()] = usr['id']

            # try to get the users which are cheating
            split_string = ' '
            if '-' in body:
                split_string = '-'
            # get users from cheat message
            try:
                s_list = body.split(split_string)[1:]
            except BaseException:
                s_list = []

            # for the cheated users
            if s_list > 0:

                # get last and next match
                (l_match_id, l_match_date, _l_match_day) = get_last_match(uts, season_id)
                (n_match_id, n_match_date, _tv_team) = get_next_match(uts, season_id)

                # by default we are updating the next match
                upd_match_id = n_match_id
                # if last match is closer we are going to update the last match (maybe someone arrives late
                if abs(uts - l_match_date) < abs(uts - n_match_date):
                    upd_match_id = l_match_id

                # try to identify the users and get the uids
                message = ''
                for usr in s_list:
                    if usr.lower() in user_dic:
                        # user lookup lookup for entry in presence-table to identify the entry to be disabled
                        try:
                            presence_id = Presence.objects.filter(match_id=upd_match_id, user_id=user_dic[usr.lower()]).values_list('id', flat=True)[:1][0]
                        except BaseException:
                            presence_id = None

                        # we found an entry - update the datebase table
                        if presence_id:
                            try:
                                obj, _created = Presence.objects.update_or_create(id=presence_id, defaults={'cheat' : True})
                                obj.save()
                                message = message + 'Der Schummelversuch von "{0}" wurde protokolliert...\n'.format(usr)
                            except BaseException:
                                message = message + 'Der Schummelversuch von "{0}" konnte nicht protokolliert werden. Bitte Joern Bescheid sagen...\n'.format(usr)
                        else:
                            message = message + 'Ich konnte leider keinen Eintrag in der Datenbank für "{0}" finden...\n'.format(usr)

                    else:
                        message = '{0}Sorry. Ich konnte nicht herausfinden, wer der User "{1}" ist. Bitte noch einmal...\n'.format(message, usr)

            else:
                message = 'Sorry. Ich konnte nicht herausfinden, wer schummelt. Bitte noch mal petzen....'

        # no he is not allowed to report cheating
        else:
            message = 'Netter Versuch {0} aber DU darfst keine Schummler melden. {1}'.format(username, '\xF0\x9F\x98\x84')

    # random fun check
    if(message and 'chummel' not in body):
        num = random.randrange(5) +  1
        # print(num)
        if num == 2:
            statement_list = list(Yowsupd.objects.values())
            rand_statement = random.randrange(len(statement_list))
            message = statement_list[rand_statement]['statement']

    return(reply, message)

def parse_location(user_latitude, user_longitude, sender):
    """ parse location """
    reply = False
    message = None

    # FOR DEBUG ONLY
    # user_latitude  = '52.5060052'
    # user_longitude = '13.4434437'

    # get season id
    season_id = len(list(Season.objects.values()))
    # unix timestamp
    uts = int(time.time())
    # get last and next match
    (l_match_id, l_match_date, _l_match_day) = get_last_match(uts, season_id)
    (n_match_id, n_match_date, _tv_team) = get_next_match(uts, season_id)

    # by default we are updating the next match
    match_id = n_match_id
    match_date = n_match_date
    # if last match is closer we are going to update the last match (maybe someone arrives late
    if(l_match_id and abs(uts - l_match_date) < abs(uts - n_match_date)):
        match_id = l_match_id
        match_date = l_match_date

    try:
        m_list = Match.objects.filter(id=match_id).values('home_team__latitude', 'home_team__longitude')[:1][0]
        hl_latitude = m_list['home_team__latitude']
        hl_longitude = m_list['home_team__longitude']
        geo_threshold = settings.GEO_THRESHOLD
    except BaseException:
        hl_latitude = None
        hl_longitude = None
        geo_threshold = 0

    if(hl_latitude and hl_longitude and geo_threshold and user_latitude and user_longitude):

        # whats the difference till the next match
        time_to_match = abs(uts - match_date)
        time_to_match_threshold = 10800

        # check if we have a user having this phone number
        (user_id, username) = lookup_user_by_mobilenumber(sender)
        if user_id:
            # caluclate differences between mba-geo-location and submitted geo-location
            diff_latitude = abs(float(hl_latitude) - float(user_latitude))
            diff_longitude = abs(float(hl_longitude) - float(user_longitude))
            # print(diff_latitude,diff_longitude)
            geo_ok = False

            if time_to_match > time_to_match_threshold:
                # time difference to high
                reply = True
                message = 'Hallo {0}, netter Versuch. Du bist entweder viel zu früh oder viel zu spät. Der Schummelversuch wird protokolliert... '.format(username).encode() + b'\xF0\x9F\x98\x9C'
            elif (diff_latitude > geo_threshold or diff_longitude > geo_threshold):
                # geo-location are incorrect
                reply = True
                message = 'Hallo {0}, netter Versuch aber du bist nicht da, wo du sein solltest. Der Schummelversuch wird protokolliert... '.format(username).encode() + b'\xF0\x9F\x98\x9C'
            elif (diff_latitude < geo_threshold or diff_longitude < geo_threshold):
                reply = True
                message = 'Hallo {0}, Dein Standort wurde eingetragen. Alles ok. Viel Spass beim Spiel... '.format(username).encode() + b'\xF0\x9F\x91\x8D'
                geo_ok = True

            datadict = {
                'match_id' : match_id,
                'user_id' : user_id,
                'latitude' : float(user_latitude),
                'longitude' : float(user_longitude),
                'date' : uts,
                'geook' : geo_ok}

            obj, _created = Presence.objects.update_or_create(match_id=match_id, user_id=user_id, defaults=datadict)
            obj.save()

        else:
            reply = True
            message = 'Tut mir leid. User %s konnte nicht identifiziert werden...' % (sender)
    else:
        reply = True
        message = 'keine Geo-Daten eingetragen...'

    return(reply, message)

def yao_send(h_score, g_score, match_id, g_name):
    """ you are out message """
    # get users per group
    user_dic = {}
    user_list = User.objects.filter(groups__name=g_name).values('username', 'id')
    for usr in user_list:
        user_dic[usr['id']] = usr['username']

    # get tips for this particular group
    tip_list = Tip.objects.filter(match_id=match_id, user_id__in=list(user_dic.keys())).values('user_id', 'user__username', 'tip')

    yao_dic = {}
    # parse and split tips
    for tip in tip_list:
        try:
            (t_h, t_g) = tip['tip'].split(':')
        except BaseException:
            t_h = None
            t_g = None
        if t_h and t_g:
            # check if the user is out (his tip must be higher than score of either home or guest team)
            if(int(t_h) < int(h_score) or int(t_g) < int(g_score)):
                yao_dic[tip['user__username']] = tip['tip']

    # create text for message
    if yao_dic > 0:
        message = 'aktueller Stand!: %s:%s\nDie folgenden Tipper sind bereits raus:\n' % (str(h_score), str(g_score))
        for usr in sorted(yao_dic):
            message = message + ' - %s: %s\n' % (usr, yao_dic[usr])
    else:
        message = 'Niemand ist bis jetzt raus...'

    return message

def check_tv_alert(match_id, uts):
    """ check for TV alert """
    try:
        tv_team = Match.objects.filter(id=match_id).order_by('matchday').values_list('tv', flat=True)[:1][0]
    except BaseException:
        tv_team = False

    if tv_team:
        match_list = Match.objects.filter(id=match_id).values('home_team__short_name', 'guest_team__short_name', 'date')[:1]
        if match_list:
            if uts < match_list[0]['date']:
                tv_team = match_list[0]['home_team__short_name']
                if match_list[0]['home_team__short_name'] == 'EBB':
                    tv_team = match_list[0]['guest_team__short_name']
            else:
                tv_team = False
        else:
            tv_team = False

    return tv_team

def sort_dic(dic, value, reverse):
    """ sort dictionry by a value """
    tmp_dic = {}

    for svl in dic:
        try:
            tmp_dic[svl] = dic[svl][value]
        except BaseException:
            tmp_dic[svl] = 0

    # sorted(score_dict.items(),key=lambda x: x[1], reverse=True)
    sort_list = []
    for key, _val in sorted(list(tmp_dic.items()), key=lambda x: x[1], reverse=reverse):
        # print "%s: %s" % (key, tmp_dic[key])
        sort_list.append(key)

    return sort_list

def create_ranking_chart(request, season_id, pie_ranking, type_='all', rfilter=None):
    """ create ranking chart """

    # we need some basing stats (won, loss from upper function from pie chart
    # these are stored in pie_ranking[]

    # whats the id of best german hockey team
    ebb_id = get_team_id('EBB')

    # we further need data for the line-chart to be fetched from database
    ebb_ranking = list(Ranking.objects.filter(team_id=ebb_id, season_id=season_id, type=type_).order_by('match').values('ranking', 'match', 'won', 'wono', 'wonp', 'losto', 'lostp'))
    ebb_ranking_old = Ranking.objects.filter(team_id=ebb_id, season_id=season_id-1, type=type_).order_by('match').values('ranking', 'match', 'won', 'wono', 'wonp', 'losto', 'lostp')

    if rfilter:
        neg_rfilter = rfilter * -1
        ebb_ranking = ebb_ranking[neg_rfilter:]

    x_data = []
    y_data = []
    y2_data = []

    if ebb_ranking:
        _match = int(pie_ranking[len(pie_ranking)-1]['match'])
        won = int(pie_ranking[len(pie_ranking)-1]['won'])
        wono = int(pie_ranking[len(pie_ranking)-1]['wono'])
        wonp = int(pie_ranking[len(pie_ranking)-1]['wonp'])
        losto = int(pie_ranking[len(pie_ranking)-1]['losto'])
        lostp = int(pie_ranking[len(pie_ranking)-1]['lostp'])
        lost = int(pie_ranking[len(pie_ranking)-1]['match']) - int(pie_ranking[len(pie_ranking)-1]['won']) - int(pie_ranking[len(pie_ranking)-1]['wono']) - int(pie_ranking[len(pie_ranking)-1]['wonp']) - losto - lostp

        pie_data = [
            {
                'name' : 'Siege in der regulaeren Spielzeit',
                'y' : won,
                'color' : '#030357',
            }, {
                'name'  : 'Siege in Overtime',
                'y'     : wono,
                'color' : '#346DA4'
            }, {
                'name'  : 'Siege in nach PP.',
                'y'     : wonp,
                'color' : '#7cb5ec'
            }, {
                'name'  : 'Niederlagen in der regulaeren Spielzeit',
                'y'     : lost,
                'color' : '#68717a'
            }, {
                'name'  : 'Niederlagen in Overtime',
                'y'     : losto,
                'color' : '#a8bbc0'
            }, {
                'name'  : 'Niederlagen in nach PP',
                'y'     : lostp,
                'color' : '#d8d9da'}]
    else:
        pie_data = []

    for rank in ebb_ranking:

        if rank['match'] > 0:
            x_data.append(int(rank['match']))

            if int(rank['ranking']) == 1:
                dic = {
                    'y' : int(rank['ranking']),
                    'marker' : {
                        'symbol': 'url(/static/img/winner.png)'
                    }
                }
                y_data.append(dic)
            else:
                y_data.append(int(rank['ranking']))


            # collect ranking from former season
            old_ranking = 0
            for old_day in ebb_ranking_old:
                if old_day['match'] == rank['match']:
                    old_ranking = int(old_day['ranking'])
                    break
            y2_data.append(old_ranking)

    # identify UA to detect mobiles
    mobile_browser = request.mobile

    size = 90
    pie_position = [60, 130]
    label_size = '10px'
    label_left = '20px'
    label_top = '85px'
    label_text = 'Spiele gewonnen/verloren'
    show_legend = 1
    title = 'Tabellenplatz pro Spieltag'
    v_align = 'bottom'

    # we need to change some setting for mobile access
    if mobile_browser:
        size = 40
        pie_position = [5, 65]
        label_size = '8px'
        label_left = '5px'
        label_top = '50px'
        label_text = 'Spielstatistik'
        # show_legend = 0
        title = ''
        v_align = 'top'

    chart_options = {
        'chart': {
            'type' : 'line',
        },
        'title': {
            'text' : title,
            'style' : {'color': '#404040', 'font-size': '12px'},
        },

        'exporting': {
            'chartOptions': {
                'plotOptions': {
                    'series': {
                        'dataLabels': {
                            'enabled': 0,
                        },
                    },
                },
            },
            'fallbackToExportServer': 0,
        },

        'labels': {
            'items': [{
                'html' : label_text,
                'style': {
                    'left' : label_left,
                    'top' : label_top,
                    'font-size' : label_size,
                    'color' : '#404040',
                }
            }]
        },

        'tooltip': {
            'shared': 0,
        },

        'legend': {
            'enabled': show_legend,
            'itemStyle': {'color': '#404040', 'font-size': label_size},
            'verticalAlign': v_align,
        },

        'plotOptions': {
            'area': {
                'fillColor': {
                    'linearGradient': {
                        'x1': 0,
                        'y1': 0,
                        'x2': 0,
                        'y2': 1,
                    },
                    'stops': [
                        [0, '#030357'],
                        [1, '#ffffff'],
                    ]
                },
                'marker': {
                    'radius': 2,
                },
                'lineWidth': 1,
                'states': {
                    'hover': {
                        'lineWidth': 1,
                    }
                },
                'threshold': 0,
            },
        },

        'colors': ['#030357'],

        'xAxis': {
            'categories': x_data,
            'title': {
                'text': 'Spieltag',
                'style' : {'color': '#404040', 'font-size': label_size},
            }
        },

        'yAxis': {
            'title': {
                'text': 'Platzierung',
                'style'  : {'color': '#404040', 'font-size': label_size},
            },
            'max': 14,
            'tickInterval': 2,
            'plotBands': [{
                'from': 0,
                'to': 6,
                'color': 'rgba(104, 111, 122, 0.1)',
                'label': {
                    'style' : {
                        'color': '#606060',
                    },
                },
            }, {
                'from' : 6,
                'to' : 10,
                'color': 'rgba(216, 217, 218, 0.1)',
                'label': {
                    'style' : {
                        'color': '#606060',
                    }
                }
            }],
            'reversed': 1,
            'showFirstLabel': 0,
            'showLastLabel': 1
        },

        'series': [{
            'name': 'Platzierung aktuelle Saison',
            'data': y_data,
            'tooltip': {
                'headerFormat': '<b>{point.x}.Spieltag</b> - Platz: {point.y}',
                'pointFormat':  '',
            },
            'color' : '#030357',
        }, {
            'name': 'Platzierung letze Saison',
            'data': y2_data,
            'tooltip': {
                'headerFormat': '<b>{point.x}.Spieltag</b> - Platz: {point.y}',
                'pointFormat':  '',
            },
            'color': '#68717a',
        }, {
            'type': 'pie',
            'name': 'Spielstatistik',
            'data': pie_data,
            'center' : pie_position,
            'size': size,
            'showInLegend': 0,
            'dataLabels': {
                'enabled': 0,
            },
            'tooltip': {
                'headerFormat': '',
                'pointFormat':  '{point.y} {point.name}',
                },
        }]
    }
    return chart_options

def get_team_id(name):
    """ get team id """
    try:
        team_id = Team.objects.filter(short_name=name).values_list('team_id', flat=True)[:1][0]
    except BaseException:
        team_id = None

    return team_id

def get_winloss(home_team_id, team_id, result):
    """ get winloss """
    try:
        (h_score, g_score) = result.split(':')
        diff = int(h_score) - int(g_score)
    except BaseException:
        h_score = 0
        g_score = 0
        diff = 0

    result = None
    detail = None
    goal = None
    ggoal = None

    if home_team_id == team_id:
        # homematch
        goal = h_score
        ggoal = g_score
        if diff < 0:
            # lost home match
            result = 'loss'
            detail = 'hl'
        else:
            # won home match
            result = 'win'
            detail = 'hs'
    else:
        # we are guest
        goal = g_score
        ggoal = h_score
        if diff < 0:
            # won
            result = 'win'
            detail = 'gs'
        else:
            # lost
            result = 'loss'
            detail = 'gl'

    return(result, detail, goal, ggoal)

def avg_list_calculate(_list):
    """ calculate avg list """
    avg_list = []
    for ele in range(1, len(_list)+1):
        tmp_list = []
        for lel in range(0, ele):
            tmp_list.append(_list[lel])

        avg_list.append(round(reduce(lambda x, y: float(x) + float(y), tmp_list) / len(tmp_list)))

    return avg_list

def create_kye_charts(request, match_dic, oteam_id):
    """ create know your enemy chart """
    # check if access comes from mobile
    mobile_browser = request.mobile

    sort_list = sort_dic(match_dic, 'date', False)

    # create empty variables
    goal_list = []
    ggoal_list = []
    categories = []

    try:
        team_list = list(Team.objects.filter(team_id=oteam_id).values())
        team_name = team_list[0]['short_name']
        team_name_long = team_list[0]['team_name']
    except BaseException:
        team_name = None
        team_name_long = None

    hsg = 0
    hlg = 0
    gsg = 0
    glg = 0

    show_legend = 1
    if mobile_browser:
        show_legend = 0

    # enumerate matches
    for match in sort_list:
        categories.append(match_dic[match]['date_human'])
        goal_list.append(int(match_dic[match]['goal']))
        ggoal_list.append(float(match_dic[match]['ggoal']) * -1)
        if mobile_browser:
            if match_dic[match]['detail'] == 'hs':
                team_name = match_dic[match]['guest_team__short_name']
                team_name_long = match_dic[match]['guest_team__team_name']
                hsg = hsg + 1
            elif match_dic[match]['detail'] == 'hl':
                team_name = match_dic[match]['guest_team__short_name']
                team_name_long = match_dic[match]['guest_team__team_name']
                hlg = hlg + 1
            elif match_dic[match]['detail'] == 'gs':
                team_name = match_dic[match]['home_team__short_name']
                team_name_long = match_dic[match]['home_team__team_name']
                gsg = gsg + 1
            elif match_dic[match]['detail'] == 'gl':
                team_name = match_dic[match]['home_team__short_name']
                team_name_long = match_dic[match]['home_team__team_name']
                glg = glg + 1
        else:
            if match_dic[match]['detail'] == 'hs':
                team_name = match_dic[match]['guest_team__short_name']
                team_name_long = match_dic[match]['guest_team__team_name']
                hsg = hsg + 1
            elif match_dic[match]['detail'] == 'hl':
                team_name = match_dic[match]['guest_team__short_name']
                team_name_long = match_dic[match]['guest_team__team_name']
                hlg = hlg + 1
            elif match_dic[match]['detail'] == 'gs':
                team_name = match_dic[match]['home_team__short_name']
                team_name_long = match_dic[match]['home_team__team_name']
                gsg = gsg + 1
            elif match_dic[match]['detail'] == 'gl':
                team_name = match_dic[match]['home_team__short_name']
                team_name_long = match_dic[match]['home_team__team_name']
                glg = glg + 1

    avg_goal_list = avg_list_calculate(goal_list)
    avg_ggoal_list = avg_list_calculate(ggoal_list)

    pie_data = [
        {
            'name' : 'Heimsiege',
            'y' : hsg,
            'color' : '#030357',
        }, {
            'name' : 'Auswärtssiege',
            'y' : gsg,
            'color' : '#346DA4'
        }, {
            'name' : 'Heimnniederlagen',
            'y' : hlg,
            'color' : '#68717a'
        }, {
            'name' : 'Auswärtsniederlagen',
            'y' : glg,
            'color' : '#d8d9da'
        },]

    # default values
    # team_name = team_name.encode('ascii')
    if team_name:
        team_name = team_name.encode('utf8')

    title = 'Spiele gegen {0}'.format(team_name)

    _size = 70
    _pie_position = [50, 40]
    label_size = '10px'
    _label_left = '20px'
    _label_top = '5px'
    _label_text = 'Spiele gewonnen/verloren'

    # we need to change some setting for mobile access
    if mobile_browser:
        _size = 40
        _pie_position = [25, 15]
        label_size = '8px'
        _label_left = '20px'
        _label_top = '-5px'
        _label_text = 'Spielstatistik'

    chart_options = {

        'chart': {
            'type': 'area',
        },

        'exporting': {
            'chartOptions': {
                'plotOptions': {
                    'series': {
                        'dataLabels': {
                            'enabled': 0,
                        },
                    },
                },
            },
            'fallbackToExportServer': 0,
        },

        'title': {
            'text' : title,
            'style' : {'color': '#404040', 'font-size': '12px'},
        },

        'xAxis': {
            'categories': categories,

        },

        'legend': {
            'enabled': show_legend,
        },

        'yAxis': {
            'title': {
                'text': 'Gegentore | Tore',
                'style': {'color': '#404040', 'font-size': label_size},
            },
        },

        'series': [{
            'name': 'Tore',
            'data': goal_list,
            'color': '#7cb5ec',
            'tooltip': {
                'headerFormat': '<b>{point.x}:</b> {point.y} Tore',
                'pointFormat':  '',
            },
        }, {
            'type': 'spline',
            'name': 'Torquote',
            'data': avg_goal_list,
            'color': '#030357',
            'tooltip': {
                'headerFormat': '<b>{point.x}</b> Torquote: {point.y}',
                'pointFormat':  '',
            },
        }, {
            'name': 'Gegentore',
            'data': ggoal_list,
            'color': '#d8d9da',
            'tooltip': {
                'headerFormat': '<b>{point.x}:</b> {point.y} Gegentore',
                'pointFormat': '',
            },
        }, {
            'type': 'spline',
            'name': 'Gegentorquote',
            'data': avg_ggoal_list,
            'color': '#68717a',
            'tooltip': {
                'headerFormat': '<b>{point.x}</b> Gegentorquote: {point.y}',
                'pointFormat':  '',
            },
        }]

    }

    pie_options = {

        'chart': {
            'type': 'pie',
        },

        'exporting': {
            'chartOptions': {
                'plotOptions': {
                    'series': {
                        'dataLabels': {
                            'enabled': 0,
                        },
                    },
                },
            },
            'fallbackToExportServer': 0,
        },

        'title': {
            'text': 'Spielstatistik',
            'style': {'color': '#404040', 'font-size': '12px'},
        },

        'legend': {
            'enabled': show_legend,
        },

        'series': [{
            'name'  : 'blubb',
            'data'  : pie_data,
            'color' : '#7cb5ec',
            'showInLegend': 0,
            'dataLabels'  : {
                'enabled': 0,
            },
            'tooltip': {
                'headerFormat': '',
                'pointFormat':  '{point.y} {point.name}',
            }}]
    }

    return(team_name_long, chart_options, pie_options)


def create_mytip_chart(request, group_filter, _username, match_list, ranking_dict):
    """ create mytip chart """
    # check if access comes from mobile
    mobile_browser = request.mobile

    # get users member of this group
    group = models.Group.objects.get(name=group_filter)
    users = group.user_set.all()

    # title = 'Tips von {0}'.format(username)
    title = ''
    bar_data = []
    categories = []
    ranking_data = []

    for match in match_list:
        if 'score' in match:
            # print(m['matchday'],m['score'])
            bar_data.append(int(match['score']))
            categories.append(int(match['matchday']))
            try:
                ranking_data.append(int(ranking_dict[match['matchday']]))
            except BaseException:
                ranking_data.append(len(users))

    label_size = '10px'
    show_legend = 1
    y2_max = len(users)
    v_align = 'bottom'

    # we need to change some setting for mobile access
    if mobile_browser:
        label_size = '8px'
        v_align = 'top'

    chart_options = {

        'chart': {
            'type': 'column',
        },

        'title': {
            'text'    : title,
            'style'   : {'color': '#404040', 'font-size': '12px'},
        },

        'exporting': {
            'chartOptions': {
                'plotOptions': {
                    'series': {
                        'dataLabels': {
                            'enabled': 0,
                        },
                    },
                },
            },
            'fallbackToExportServer': 0,
        },

        'legend': {
            'enabled': show_legend,
            'itemStyle': {'color': '#404040', 'font-size': label_size},
            'verticalAlign': v_align,
        },

        'tooltip': {
            'shared': 1,
            'headerFormat': '<b>{point.x}. Spieltag:</b><br>',
            'pointFormat':  '{point.y}<br>',
        },

        'xAxis': {
            'categories': categories,
            'title': {
                'text': 'Spieltag',
                'style'  : {'color': '#404040', 'font-size': label_size},
            },
            'crosshair' : 1,
        },

        'yAxis':[{
            'title': {
                'text': 'Punkte',
                'style'  : {'color': '#404040', 'font-size': label_size},
            },
            'max': 5,
            'tickInterval': 1,
        }, {
            'title': {
                'text': 'Tabellenplatz',
                'style'  : {'color': '#404040', 'font-size': label_size},
            },
            'max': y2_max,
            'min': 1,
            'opposite': 1,
            'reversed': 1,
            'showFirstLabel': 1,
            'showLastLabel': 1
        }],

        'series': [{
            'name': 'Punkte',
            'data': bar_data,
            'dataLabels': {
                'enabled': 0,
                'style': {
                    'color': '#404040',
                }
            },
            'color': '#7cb5ec',
            'tooltip': {
                'valueSuffix': ' Punkte'
            },
        }, {
            'type': 'spline',
            'name': 'Platz',
            'data': ranking_data,
            'color': '#030357',
            'yAxis': 1,
            'tooltip': {
                'valueSuffix': '. Platz'
            },
        }],
    }
    return chart_options

def get_ranking_per_season(_request, _uid, u_season_id, _season_list, group_filter, uname):
    """ get ranking per season """
    # get match_id and matchday
    uts = int(time.time())
    (match_id, _match_date, _tv_team) = get_next_match(uts, u_season_id)
    # f_match_id = Match.objects.filter(season_id=u_season_id, matchday=1).values_list('id', flat=True)[:1][0]

    # get users member of this group
    group = models.Group.objects.get(name=group_filter)
    users = group.user_set.all()

    # get group-specific scores
    score_list = Groupsetting.objects.filter(group__name=group_filter).values('p_winloss', 'p_diff', 'p_tipp', 'p_7vs2', 'p_notip')[:1]

    # get all tips for the group
    tip_list = Tip.objects.filter(user_id__in=users, match__season_id=u_season_id, match_id__lte=match_id).values('match_id', 'match__home_team_id', 'match__result', 'user_id', 'user__username', 'tip', 'match__matchday')

    tmp_score_dic = {}
    for tip in tip_list:
        matchday = tip['match__matchday']
        score = get_score(tip['match__result'], tip['tip'], score_list)

        # create hive for matchday if not existing
        if matchday not in tmp_score_dic:
            tmp_score_dic[matchday] = {}

        # store score per matchday per user
        tmp_score_dic[matchday][tip['user__username']] = score

    # dirty hack
    # matchday of the next match
    mday = Match.objects.filter(id=match_id).values_list('matchday', flat=True)[:1][0]
    for tip in range(1, mday):
        if tip not in tmp_score_dic:
            tmp_score_dic[tip] = {}
        if uname not in tmp_score_dic[tip]:
            tmp_score_dic[tip][uname] = 0


    # comulated figures
    cumulated_dic = {}
    # look into the temporary hash
    for mday in tmp_score_dic:
        # create an entry per matchday
        if mday not in cumulated_dic:
            cumulated_dic[mday] = {}
        # for each matchday from 1 till matchday
        for tip in range(1, mday+1):
            if tip in tmp_score_dic:
                # check for all users of this day
                for usr in tmp_score_dic[tip]:
                    # cumulate the score
                    if usr not in cumulated_dic[mday]:
                        # print(mday,usr,tmp_score_dic[tip][usr],' angelegt')
                        cumulated_dic[mday][usr] = tmp_score_dic[tip][usr]
                    else:
                        # print(mday,u,tmp_score_dic[tip][u],' addiert')
                        cumulated_dic[mday][usr] = cumulated_dic[mday][usr] + tmp_score_dic[tip][usr]

    ranking_dict = {}
    for mday in cumulated_dic:
        tmp_day = sorted(list(cumulated_dic[mday].items()), key=lambda x: (-x[1], x[0]))

        for index, usr in enumerate(tmp_day):
            if usr[0] == uname:
                ranking_dict[mday] = index+1
    return ranking_dict

def collect_team_statistic(mobile_browser, uts, oteam_id, team_name):
    """ collect team statistics """
    # get last matches from other team
    del_match_dic = {}
    del_sort_list = []
    del_match_list = Delmatch.objects.filter(Q(home_team_id=oteam_id, date__lte=uts, update_date__gte=1) | Q(guest_team_id=oteam_id, date__lte=uts, update_date__gte=1)).order_by('-date').values('date', 'season_id', 'home_team_id', 'home_team__short_name', 'home_team__team_name', 'home_team__logo_url', 'guest_team__short_name', 'guest_team__team_name', 'guest_team__logo_url', 'result', 'id')[:6]

    for match in del_match_list:
        # skip blank matches
        if match['result'] != '-:-':
            del_match_dic[match['id']] = {}
            del_sort_list.append(match['id'])
            if mobile_browser:
                date_human = datetime.datetime.fromtimestamp(match['date'], tz=TIMEZONE).strftime('%b.%y')
            else:
                date_human = datetime.datetime.fromtimestamp(match['date'], tz=TIMEZONE).strftime('%d.%m.%Y')
            del_match_dic[match['id']]['date_human'] = date_human
            del_match_dic[match['id']]['date_human_long'] = datetime.datetime.fromtimestamp(match['date'], tz=TIMEZONE).strftime('%d.%m.%Y')
            del_match_dic[match['id']]['date'] = match['date']
            del_match_dic[match['id']]['home_team__short_name'] = match['home_team__short_name']
            del_match_dic[match['id']]['home_team__team_name'] = match['home_team__team_name']
            del_match_dic[match['id']]['home_team__logo_url'] = match['home_team__logo_url']
            del_match_dic[match['id']]['guest_team__short_name'] = match['guest_team__short_name']
            del_match_dic[match['id']]['guest_team__team_name'] = match['guest_team__team_name']
            del_match_dic[match['id']]['guest_team__logo_url'] = match['guest_team__logo_url']
            del_match_dic[match['id']]['result'] = match['result']
            del_match_dic[match['id']]['season_id'] = match['season_id']

            # get winloss status including goals and ggoals
            (winloss, _detail, _goal, _ggoal) = get_winloss(int(match['home_team_id']), int(oteam_id), match['result'])

            # store winloss result in dicionary
            del_match_dic[match['id']]['winloss'] = winloss

    article_g = 'der'
    article_a = 'die'

    if('ngolstadt' in team_name or 'Bull' in team_name):
        article_g = 'des'
        article_a = 'den'

    return(del_sort_list, del_match_dic, article_g, article_a)

def get_single_referee_stats(mobile_browser, r_id, ebb_id):
    """ get referee stats """
    # get season_id
    season_id = len(list(Season.objects.values()))

    # get statistics per referee
    match_list = Refpermatch.objects.filter(Q(r1_id=r_id, match__season_id=season_id) | Q(r2_id=r_id, match__season_id=season_id)).values('r1_id', 'r2_id', 'match__matchday', 'match__result', 'match__home_team_id')

    # initiliaze counters
    match_counter = 0
    w_counter = 0
    l_counter = 0

    # for all matches
    for match in match_list:
        if match['match__result']:
            # print(match['match__matchday'],match['match__result'],match['match__home_team_id'])
            (winloss, _detail, _goal, _ggoal) = get_winloss(match['match__home_team_id'], ebb_id, match['match__result'])
            match_counter = match_counter + 1
            # print(winloss)
            if winloss == 'win':
                w_counter = w_counter + 1
            elif winloss == 'loss':
                l_counter = l_counter + 1

    game = 'Spiele'
    if match_counter == 1:
        game = ' Spiel'
    if mobile_browser:
        game = ' Sp'

    return('{0} {1}'.format(match_counter, game), 'S:{0}, N:{1}, P/M:{2}'.format(w_counter, l_counter, w_counter-l_counter))

def get_match_chart(request, mday_list, goal_list, ggoal_list, ranking_list):
    """ get chart of matches """
    # identify UA to detect mobiles
    mobile_browser = request.mobile

    title = ''
    label_size = '10px'
    show_legend = 1
    v_align = 'bottom'

    # we need to change some setting for mobile access
    if mobile_browser:
        label_size = '8px'
        # show_legend = 1
        v_align = 'top'

    chart_options = {

        'chart': {
            'type': 'area',
        },

        'exporting': {
            'chartOptions': {
                'plotOptions': {
                    'series': {
                        'dataLabels': {
                            'enabled': 0,
                        },
                    },
                },
            },
            'fallbackToExportServer': 0,
        },

        'title': {
            'text': title,
            'style': {'color': '#404040', 'font-size': '12px'},
        },

        'legend': {
            'enabled': show_legend,
            'itemStyle': {'color': '#404040', 'font-size': label_size},
            'verticalAlign': v_align,
        },

        'tooltip': {
            'shared': 1,
            'headerFormat': '<b>{point.x}.Spieltag</b><br>',
        },

        'xAxis': {
            'categories': mday_list,
            'title': {
                'text': 'Spieltag',
                'style': {'color': '#404040', 'font-size': label_size},
            },
            'crosshair': 1,
        },

        'yAxis': [{
            'title': {
                'text': 'Gegentore | Tore',
                'style': {'color': '#404040', 'font-size': label_size},
            },
            }, {
                'title': {
                    'text': 'Tabellenplatz',
                    'style': {'color': '#404040', 'font-size': label_size},
                },
                'min': 1,
                'opposite': 1,
                'reversed': 1,
                'showFirstLabel': 1,
                'showLastLabel': 1}],

        'series': [{
            'name': 'Tore',
            'data': goal_list,
            'color': '#7cb5ec',
        }, {
            'name': 'Gegentore',
            'data': ggoal_list,
            'color': '#d8d9da',
        }, {
            'type': 'spline',
            'name': 'Platz',
            'data': ranking_list,
            'color': '#030357',
            'yAxis': 1,
        }]
    }
    return chart_options

def get_penalties_per_match(ebb_id, season_id, uts):
    """ get penalties per match """
    p_tmp_dic = {}
    p_dic = {}
    p_ref_dic = {}
    # get penalties per match including referre
    penalty_list = Ranking.objects.filter(team_id=ebb_id).values('matchday_id', 'match', 'matchday__matchday', 'penalty', 'matchday__refpermatch__r1_id', 'matchday__refpermatch__r2_id')

    # temporary dictionary including the penanlty minutes
    for match in penalty_list:
        p_tmp_dic[int(match['matchday__matchday'])] = {}
        p_tmp_dic[int(match['matchday__matchday'])]['penalty'] = int(match['penalty'])
        p_tmp_dic[int(match['matchday__matchday'])]['r1'] = match['matchday__refpermatch__r1_id']
        p_tmp_dic[int(match['matchday__matchday'])]['r2'] = match['matchday__refpermatch__r2_id']

    match_list = Match.objects.filter(season=season_id, date__lte=uts, no_bet=False).values('id', 'penalty', 'matchday', 'home_team_id')
    for match in match_list:
        if(match['matchday'] in p_tmp_dic and bool(match['penalty'])):
            mpenalty = None
            openalty = None
            if match['home_team_id'] == ebb_id:
                try:
                    (mpenalty, openalty) = match['penalty'].split(':')
                except BaseException:
                    mpenalty = 0
                    openalty = 0
            else:
                try:
                    (openalty, mpenalty) = match['penalty'].split(':')
                except BaseException:
                    mpenalty = 0
                    openalty = 0
            if p_tmp_dic[match['matchday']]['r1'] not in p_ref_dic:
                p_ref_dic[p_tmp_dic[match['matchday']]['r1']] = {}
                p_ref_dic[p_tmp_dic[match['matchday']]['r1']]['mp'] = 0
                p_ref_dic[p_tmp_dic[match['matchday']]['r1']]['op'] = 0
            if p_tmp_dic[match['matchday']]['r2'] not in p_ref_dic:
                p_ref_dic[p_tmp_dic[match['matchday']]['r2']] = {}
                p_ref_dic[p_tmp_dic[match['matchday']]['r2']]['mp'] = 0
                p_ref_dic[p_tmp_dic[match['matchday']]['r2']]['op'] = 0

            p_ref_dic[p_tmp_dic[match['matchday']]['r1']]['mp'] = p_ref_dic[p_tmp_dic[match['matchday']]['r1']]['mp'] + int(mpenalty)
            p_ref_dic[p_tmp_dic[match['matchday']]['r1']]['op'] = p_ref_dic[p_tmp_dic[match['matchday']]['r1']]['op'] + int(openalty)
            p_ref_dic[p_tmp_dic[match['matchday']]['r2']]['mp'] = p_ref_dic[p_tmp_dic[match['matchday']]['r2']]['mp'] + int(mpenalty)
            p_ref_dic[p_tmp_dic[match['matchday']]['r2']]['op'] = p_ref_dic[p_tmp_dic[match['matchday']]['r2']]['op'] + int(openalty)

    # dictionary including penalties per refery
    # this code is not needed anymore (to be removed after final check)
    for match in p_tmp_dic:

        # create sub structure if not existing
        if p_tmp_dic[match]['r1'] not in p_dic:
            p_dic[p_tmp_dic[match]['r1']] = 0
        if p_tmp_dic[match]['r2'] not in p_dic:
            p_dic[p_tmp_dic[match]['r2']] = 0

        # store data
        if match == 1:
            p_dic[p_tmp_dic[match]['r1']] = p_dic[p_tmp_dic[match]['r1']] + p_tmp_dic[match]['penalty']
            p_dic[p_tmp_dic[match]['r2']] = p_dic[p_tmp_dic[match]['r2']] + p_tmp_dic[match]['penalty']
        else:
            try:
                p_dic[p_tmp_dic[match]['r1']] = p_dic[p_tmp_dic[match]['r1']] + (p_tmp_dic[match]['penalty'] - p_tmp_dic[match-1]['penalty'])
                p_dic[p_tmp_dic[match]['r2']] = p_dic[p_tmp_dic[match]['r2']] + (p_tmp_dic[match]['penalty'] - p_tmp_dic[match-1]['penalty'])
            except BaseException:
                pass

    return(p_ref_dic, p_tmp_dic)

def shorten_lineup(string):
    """ shorten lineup """
    player_list = string.split(' - ')
    tmp_list = []
    for player in player_list:
        (name, _fname) = player.split(',')
        tmp_list.append(name)

    return ' - '.join(tmp_list)

def modify_umlaut(string):
    """ modify umlaut to html """
    string.replace('&auml;', 'ä')
    string = string.replace('&ouml;', 'ö')
    string = string.replace('&uuml;', 'ü')
    string = string.replace('&szlig;', 'ß')
    return string

def get_goals_per_period(season_id, mobile_browser, type_='all'):
    """ get goals per period """
    # whats the id of best german hockey team
    ebb_id = get_team_id('EBB')

    # get match list
    if type_ == 'home':
        m_list = list(Match.objects.filter(season=season_id, home_team=ebb_id).exclude(matchday=0).values_list('id', flat=True))
    elif type_ == 'guest':
        m_list = list(Match.objects.filter(season=season_id, guest_team=ebb_id).exclude(matchday=0).values_list('id', flat=True))
    else:
        m_list = list(Match.objects.filter(season=season_id).exclude(matchday=0).values_list('id', flat=True))

    # get goals based on match list
    goal_list = Goal.objects.filter(match__in=m_list).exclude(time_second=0).values('match', 'time_second', 'period', 'ebb', 'score')
    goal_stat_dic = {'goal': {1: 0, 2: 0, 3: 0, 4: 0, 'sum': 0}, 'ggoal': {1: 0, 2: 0, 3: 0, 4: 0, 'sum': 0}}

    for goal in goal_list:
        if goal['match'] in m_list:
            period = math.ceil(goal['time_second']/1200)
            if goal['ebb']:
                goal_stat_dic['goal'][period] += 1
                goal_stat_dic['goal']['sum'] += 1
            else:
                goal_stat_dic['ggoal'][period] += 1
                goal_stat_dic['ggoal']['sum'] += 1

    goal_pie = create_goal_period_pie(goal_stat_dic, '#000034', '#00008f', '#4747ff', '#e3e3ff', '#404040', '#666666', '#b3b3b3', '#f4f4f4', mobile_browser)
    goal_table = create_goal_period_table(goal_stat_dic, mobile_browser)

    return(goal_pie, goal_table)

def create_goal_period_table(goal_stat_dic, _mobile_browser):
    """ create table for goals per period """

    goal_dic = goal_stat_dic['goal']
    ggoal_dic = goal_stat_dic['ggoal']

    table_dic = {
        'th': ['Pro Drittel', '1st', '2nd', '3rd', 'OT', 'Summe'], 'align': ['left', None, None, None, None, None],
        'td': [
            ['Tore', goal_dic[1], goal_dic[2], goal_dic[3], goal_dic[4], goal_dic['sum']],
            ['Gegentore', ggoal_dic[1], ggoal_dic[2], ggoal_dic[3], ggoal_dic[4], ggoal_dic['sum']]
        ]}

    return table_dic

def get_goals_per_minute(season_id, mobile_browser, type_):
    """ get goals per minute """
    # whats the id of best german hockey team
    ebb_id = get_team_id('EBB')

    # get match list
    if type_ == 'home':
        m_list = list(Match.objects.filter(season=season_id, home_team=ebb_id).exclude(matchday=0).values_list('id', flat=True))
    elif type_ == 'away':
        m_list = list(Match.objects.filter(season=season_id, guest_team=ebb_id).exclude(matchday=0).values_list('id', flat=True))
    else:
        m_list = list(Match.objects.filter(season=season_id).exclude(matchday=0).values_list('id', flat=True))

    # get goals based on match list
    goal_list = Goal.objects.filter(match__in=m_list).exclude(time_second=0).values('match', 'time_second', 'period', 'ebb', 'score')

    goal_time_dic = {'goal': {'sum': 0}, 'ggoal':{'sum': 0}}
    for ele in range(1, 66):
        goal_time_dic['goal'][ele] = 0
        goal_time_dic['ggoal'][ele] = 0

    for goal in goal_list:
        if goal['match'] in m_list:
            # calculate match minute
            min_ = math.ceil(goal['time_second']/60)
            if goal['ebb']:
                # if min_ not in goal_time_dic['goal']:
                #    goal_time_dic['goal'][min_] = 0
                goal_time_dic['goal'][min_] += 1
                goal_time_dic['goal']['sum'] += 1
            else:
                # if min_ not in goal_time_dic['ggoal']:
                #    goal_time_dic['ggoal'][min_] = 0
                goal_time_dic['ggoal'][min_] += 1
                goal_time_dic['ggoal']['sum'] += 1

    goal_line = create_goal_line(goal_time_dic, mobile_browser)
    goal_table = create_goal_min_table(goal_time_dic, mobile_browser)

    return(goal_line, goal_table)

def get_goals_shotmap(season_id, mobile_browser, type_, show_ebb=True):
    """ create shotmap """

    # whats the id of best german hockey team
    ebb_id = get_team_id('EBB')

    # get match list
    if type_ == 'home':
        m_list = list(Match.objects.filter(season=season_id, home_team=ebb_id).exclude(matchday=0).values_list('id', flat=True))
    elif type_ == 'away':
        m_list = list(Match.objects.filter(season=season_id, guest_team=ebb_id).exclude(matchday=0).values_list('id', flat=True))
    else:
        m_list = list(Match.objects.filter(season=season_id).exclude(matchday=0).values_list('id', flat=True))

    # get goals based on match list
    goal_list = Goal.objects.filter(match__in=m_list).exclude(period='Shootout').values('period', 'match__matchday', 'match__home_team__short_name', 'ebb', 'coordinate_x', 'coordinate_y', 'name', 'time', 'number')

    for goal in goal_list:
        if show_ebb:
            if goal['match__home_team__short_name'] == 'EBB':
                # flip counter clockwise for home
                goal['x'] = goal['coordinate_y'] * -1
                goal['y'] = goal['coordinate_x']
            else:
                # flip clockwise for road_game
                goal['x'] = goal['coordinate_y']
                goal['y'] = goal['coordinate_x'] * -1
        else:
            if goal['match__home_team__short_name'] == 'EBB':
                # flip clockwise for home_game
                goal['x'] = goal['coordinate_y']
                goal['y'] = goal['coordinate_x'] * -1
            else:
                # flip counter clockwise for road_game
                goal['x'] = goal['coordinate_y'] * -1
                goal['y'] = goal['coordinate_x']

    shot_map = create_goals_shotmap_chart(goal_list, mobile_browser, show_ebb)

    return(shot_map, {})

def create_goals_shotmap_chart(goal_list, mobile_browser, show_ebb):
    """ create shotmap chart """

    data_dic = []

    for goal in goal_list:
        if (show_ebb and goal['ebb']) or (not show_ebb and not goal['ebb']):
            tmp_dic = {
                'x': goal['x'],
                'y': goal['y'],
                'z': 2,
                'mday': goal['match__matchday'],
                'number': goal['number'],
                'name': goal['name'],
                'labelrank': 2,
                'minute': goal['time'],
                }

            data_dic.append(tmp_dic)

    # we need to change some setting for mobile access
    if mobile_browser:
        label_size = '8px'
        # show_legend = 1
        v_align = 'top'
        marker_size = 5
        # label_offset = 11
    else:
        label_size = '10px'
        v_align = 'bottom'
        # show_legend = 1
        marker_size = 8
        # label_offset = 13

    # define some colors for the chart
    if show_ebb:
        scatter_color = '#7cb5ec'
        marker_linecolor = '#e3e3ff'
    else:
        scatter_color = '#bdbfc1'
        marker_linecolor = '#d8d9da'

    # we do not want to have a title
    title = ''
    chart_options = {

        'chart': {
            'type': 'scatter',
            'plotBorderWidth': 0,
            'plotBackgroundImage': '/static/img/shotmap.svg',
            'zoomType': 'xy',
            'height': '103%',
        },

        'exporting': {
            'chartOptions': {
                'plotOptions': {
                    'series': {
                        'dataLabels': {
                            'enabled': 0,
                        },
                    },
                },
            },
            'fallbackToExportServer': 0,
        },

        'legend': {
            'enabled': 0,
            'itemStyle': {'color': '#404040', 'font-size': label_size},
            'verticalAlign': v_align,
            'squareSymbol': 1,
        },

        'title': {
            'text': title,
        },

        'tooltip': {
            'useHTML': 1,
            'headerFormat': '<table class="w3-tiny">',
            'pointFormat': '<tr><td><b>{point.name} ({point.number})<b></td></tr>' +
                           '<tr><td>{point.mday}. Spieltag</td></tr>' +
                           '<tr><td>Zeit: {point.minute}</td></tr>',
            'footerFormat': '</table>',
            'followPointer': 1,
        },

        'plotOptions': {
            'scatter': {
                'marker': {'lineColor': marker_linecolor, 'lineWidth': 1}
            },
            'series': {
                'color': scatter_color,
                'borderWidth': 0,
                'lineColor': '#c00c18',
            },
        },

        'xAxis': {
            'visible': 0,
            'labels': {'enabled': 0},
            'min': -100,
            'max': 100,
            'tickInterval': 0,
        },

        'yAxis': {
            'visible': 0,
            'gridLineWidth': 0,
            'title': {
                'text': '',
            },
            'labels': {'enabled': 0},
            'min': 0,
            'max': 105,
            'tickInterval': 0,
        },

        'series': [
            {'name': 'Gehalten', 'data': data_dic, 'marker': {'radius': marker_size, 'symbol': 'circle'}},
        ],
    }

    return chart_options

def create_goal_min_table(goal_time_dic, _mobile_browser):
    """ create table for goals per period """

    table_dic = {
        'th': ['Pro Minute', 'Tore', 'Gegentore'], 'align': [None, None, None],
        'td': []}

    for min_ in range(1, 66):
        table_dic['td'].append([min_, goal_time_dic['goal'][min_], goal_time_dic['ggoal'][min_]])

    return table_dic

def create_goal_line(goal_time_dic, mobile_browser):
    """ greate line values and goal line graph """

    min_list = list(range(1, 66))
    goal_list = []
    ggoal_list = []

    for min_ in min_list:
        if min_ in goal_time_dic['goal']:
            goal_list.append(goal_time_dic['goal'][min_])
        else:
            goal_list.append(0)

        if min_ in goal_time_dic['ggoal']:
            ggoal_list.append(goal_time_dic['ggoal'][min_] * -1)
        else:
            ggoal_list.append(0)

    title = ''

    label_size = '10px'
    show_legend = 1

    # we need to change some setting for mobile access
    if mobile_browser:
        label_size = '8px'
        show_legend = 0

    chart_options = {

        'chart': {
            'type': 'area',
            'height': '60%',
        },

        'exporting': {
            'chartOptions': {
                'plotOptions': {
                    'series': {
                        'dataLabels': {
                            'enabled': 0,
                        },
                    },
                },
            },
            'fallbackToExportServer': 0,
        },

        'title': {
            'text': title,
            'style': {'color': '#404040', 'font-size': '12px'},
        },

        'legend': {
            'enabled': show_legend,
        },

        'tooltip': {
            'shared': 1,
            'headerFormat': '<b>{point.x}.Spielminute</b><br>',
        },

        'xAxis': {
            'gridLineWidth': 1,
            'minTickInterval': 20,
            'min': 0,
            'max': 60,
            'endOnTick': 1,

            'categories': min_list,
            'title': {
                'text': 'Zeit',
                'style': {'color': '#404040', 'font-size': label_size},
            },
            'crosshair': 1,
        },

        'yAxis': [{
            'title': {
                'text': 'Gegentore | Tore',
                'style': {'color': '#404040', 'font-size': label_size},
            },
            'tickInterval': 2,
            }],

        'series': [{
            'name': 'Tore',
            'data': goal_list,
            'color': '#7cb5ec',
        }, {
            'name': 'Gegentore',
            'data': ggoal_list,
            'color': '#d8d9da',
        }]
    }
    return chart_options

def classify_goal(score, result, home_match):
    """ classify goal as own goal or not """
    own_goal = False

    try:
        (h_result, g_result) = result.split(':')
        (h_score, g_score) = score.split(':')
    except BaseException:
        h_result = 0
        g_result = 0
        h_score = 0
        g_score = 0

    # create difference to check who scored
    try:
        h_diff = int(h_result) - int(h_score)
        g_diff = int(g_result) - int(g_score)
    except BaseException:
        h_diff = 0
        g_diff = 0

    if h_diff == -1:
        #home team scored
        if home_match:
            own_goal = True

    elif g_diff == -1:
        if not home_match:
            own_goal = True

    return own_goal

def create_goal_period_pie(goal_stat_dic, color_1, color_2, color_3, _color_4, color_5, color_6, color_7, _color_8, mobile_browser):
    """ create pie chart about goals per period """

    title = ''

    _label_size = '10px'
    _show_legend = 1
    distance = -30

    # we need to change some setting for mobile access
    if mobile_browser:
        _label_size = '8px'
        _show_legend = 0
        distance = -2

    chart_options = {
        'chart': {
            'plotBackgroundColor': 0,
            'plotBorderWidth': 0,
            'plotShadow': 0,
            'type': 'pie',
            'height': '50%',
        },

        'exporting': {
            'chartOptions': {
                'plotOptions': {
                    'series': {
                        'dataLabels': {
                            'enabled': 0,
                        },
                    },
                },
            },
            'fallbackToExportServer': 0,
        },

        'title': {
            'text': title,
            'style': {'color': '#404040', 'font-size': '12px'},
        },

        'plotOptions': {
            'pie': {
                'dataLabels': {
                    'distance': distance,
                }
            }
        },

        'series': [{
            'name': 'Tore',
            'center': ['25%'],
            'innerSize': '40%',
            'data': [{
                'name': '1. Drittel',
                'y': goal_stat_dic['goal'][1],
                'color'  : color_1,
                }, {
                    'name': '2. Drittel',
                    'y': goal_stat_dic['goal'][2],
                    'color' : color_2,
                }, {
                    'name': '3. Drittel',
                    'y': goal_stat_dic['goal'][3],
                    'color' : color_3,
                },]
        }, {
            'name': 'Gegentore',
            'center': ['75%'],
            'innerSize': '40%',
            'data': [{
                'name': '1. Drittel',
                'y': goal_stat_dic['ggoal'][1],
                'color'  : color_5,
            }, {
                'name': '2. Drittel',
                'y': goal_stat_dic['ggoal'][2],
                'color' : color_6,
            }, {
                'name': '3. Drittel',
                'y': goal_stat_dic['ggoal'][3],
                'color' : color_7,
            }]
        }]
    }
    # print(goal_stat_dic)
    return chart_options

def get_goals_zones(season_id, _mobile_browser, type_):
    """ get goals per minute """
    # whats the id of best german hockey team
    ebb_id = get_team_id('EBB')

    # get match list
    if type_ == 'home':
        m_list = list(Match.objects.filter(season=season_id, home_team=ebb_id).exclude(matchday=0).values_list('id', flat=True))
    elif type_ == 'away':
        m_list = list(Match.objects.filter(season=season_id, guest_team=ebb_id).exclude(matchday=0).values_list('id', flat=True))
    else:
        m_list = list(Match.objects.filter(season=season_id).exclude(matchday=0).values_list('id', flat=True))

    # get goals based on match list
    goal_list = Goal.objects.filter(match__in=m_list).exclude(time_second=0).values('match', 'time_second', 'period', 'ebb', 'coordinate_x', 'coordinate_y')

    goal_zone_dic = {
        'goals': {'slot': {'count': 0}, 'left': {'count': 0}, 'right': {'count': 0}, 'blue_line': {'count': 0}, 'neutral_zone': {'count': 0}, 'sum': {'count': 0}},
        'ggoals': {'slot': {'count': 0}, 'left': {'count': 0}, 'right': {'count': 0}, 'blue_line': {'count': 0}, 'neutral_zone': {'count': 0}, 'sum': {'count': 0}}}

    for goal in goal_list:
        zone = get_zone_name(goal['coordinate_x'], goal['coordinate_y'])
        if goal['ebb']:
            goal_zone_dic['goals'][zone]['count'] += 1
            goal_zone_dic['goals']['sum']['count'] += 1
        else:
            goal_zone_dic['ggoals'][zone]['count'] += 1
            goal_zone_dic['ggoals']['sum']['count'] += 1

    for zone in goal_zone_dic['goals']:
        goal_zone_dic['goals'][zone]['roundpercent'] = round(goal_zone_dic['goals'][zone]['count'] / goal_zone_dic['goals']['sum']['count'] * 100)
        goal_zone_dic['ggoals'][zone]['roundpercent'] = round(goal_zone_dic['ggoals'][zone]['count'] / goal_zone_dic['ggoals']['sum']['count'] * 100)

    goal_zone_table = create_goal_zone_table(goal_zone_dic)

    return(goal_zone_dic, goal_zone_table)

def create_goal_zone_table(goal_time_dic):
    """ create table for goals per period """

    slot_dic = {'behind_goal': 'Hinterm Tor',
                'left': 'Linker Flügel',
                'slot': 'Slot',
                'blue_line': 'Blaue Linie',
                'right': 'Rechter Flügel',
                'neutral_zone': 'Neutrale Zone'}

    slot_list = ('slot', 'left', 'right', 'blue_line', 'neutral_zone')

    table_dic = {
        'th': ['Zone', 'Tore', '%', 'Gegentore', '%'], 'align': ['left', None, None, None, None],
        'td': []}

    for slot in slot_list:
        table_dic['td'].append([slot_dic[slot], goal_time_dic['goals'][slot]['count'], goal_time_dic['goals'][slot]['roundpercent'], goal_time_dic['ggoals'][slot]['count'], goal_time_dic['ggoals'][slot]['roundpercent']])

    return table_dic

def get_pnaltystats(season_id, request, _filter):
    """ get penalty staticsts """
    # whats the id of best german hockey team
    ebb_id = get_team_id('EBB')

    m_list = []
    # get match list
    if _filter == 'home':
        m_list = Match.objects.filter(season=season_id, home_team=ebb_id).exclude(matchday=0).values('id', 'home_team')
    elif _filter == 'guest':
        m_list = Match.objects.filter(season=season_id, guest_team=ebb_id).exclude(matchday=0).values('id', 'home_team')
    else:
        m_list = Match.objects.filter(season=season_id).exclude(matchday=0).values('id', 'home_team')

    # create list of match_ids and a dictinaliry of home_matches
    match_list = []
    home_match_dic = {}
    for match in m_list:
        match_list.append(match['id'])
        # if match['home_team'] == ebb_id:
        #    home_match_dic[match['id']] = True
        #else:
        #    home_match_dic[match['id']] = False
        home_match_dic[match['id']] = bool(match['home_team'] == ebb_id)

    # get goals based on match list
    pnalty_list = Pnalty.objects.filter(match__in=match_list).values('match', 'time', 'ebb', 'name', 'duration')
    pnalty_time_dic = {}
    pnalty_time_dic['ebb'] = {}
    pnalty_time_dic['other'] = {}

    pnalty_name_dic = {}
    pnalty_stat_dic = {}
    pnalty_stat_dic['ebb'] = {}
    pnalty_stat_dic['ebb'][1] = 0
    pnalty_stat_dic['ebb'][2] = 0
    pnalty_stat_dic['ebb'][3] = 0
    pnalty_stat_dic['ebb'][4] = 0
    pnalty_stat_dic['ebb']['sum'] = 0

    pnalty_stat_dic['other'] = {}
    pnalty_stat_dic['other'][1] = 0
    pnalty_stat_dic['other'][2] = 0
    pnalty_stat_dic['other'][3] = 0
    pnalty_stat_dic['other'][4] = 0
    pnalty_stat_dic['other']['sum'] = 0

    for penalty in pnalty_list:
        selector = 'other'
        if penalty['ebb']:
            selector = 'ebb'
            try:
                (pname, _sinin) = penalty['name'].split(',', 1)
            except BaseException:
                pname = penalty['name']
            if pname not in pnalty_name_dic:
                pnalty_name_dic[pname] = 0

            if penalty['duration'] == 1:
                # two min penalty
                pnalty_name_dic[pname] += 2
            elif penalty['duration'] == 2:
                # 5 min penalty
                pnalty_name_dic[pname] += 4
            elif penalty['duration'] == 6:
                # match out
                (_min, _sec) = penalty['time'].split(':')
                pnalty = 60 - int(_min) + 1
                pnalty_name_dic[pname] += pnalty

        # get period
        try:
            (_min, _sec) = penalty['time'].split(':')
        except BaseException:
            _min = None
            _sec = None

        if _min:
            _min = int(_min) + 1
            # check period
            period = 4
            # print(_min)
            if _min <= 20:
                period = 1
            elif _min <= 40:
                period = 2
            elif _min <= 60:
                period = 3

            # store data
            if _min not in pnalty_time_dic[selector]:
                pnalty_time_dic[selector][_min] = 0
            if selector == 'ebb':
                pnalty_time_dic[selector][_min] += 1
            else:
                pnalty_time_dic[selector][_min] -= 1

            pnalty_stat_dic[selector][period] += 1
            pnalty_stat_dic[selector]['sum'] += 1

    pnalty_line = create_pnalty_line(pnalty_time_dic, request)

    return(pnalty_stat_dic, pnalty_line, pnalty_name_dic)


def create_pnalty_line(pnalty_time_dic, request):
    """ create pnalty line """
    min_list = list(range(1, 61))
    pnalty_list = []
    opnalty_list = []

    for match in min_list:
        if match in pnalty_time_dic['ebb']:
            pnalty_list.append(pnalty_time_dic['ebb'][match])
        else:
            pnalty_list.append(0)

        if match in pnalty_time_dic['other']:
            opnalty_list.append(pnalty_time_dic['other'][match])
        else:
            opnalty_list.append(0)


    # identify UA to detect mobiles
    mobile_browser = request.mobile

    title = 'Anzahl Strafzeiten pro Spielminute'

    label_size = '10px'
    show_legend = 1

    # we need to change some setting for mobile access
    if mobile_browser:
        label_size = '8px'
        show_legend = 0

    chart_options = {

        'chart': {
            'type': 'area',
        },

        'exporting': {
            'chartOptions': {
                'plotOptions': {
                    'series': {
                        'dataLabels': {
                            'enabled': 0,
                        },
                    },
                },
            },
            'fallbackToExportServer': 0,
        },

        'title': {
            'text': title,
            'style': {'color': '#404040', 'font-size': '12px'},
        },

        'legend': {
            'enabled': show_legend,
        },

        'tooltip': {
            'shared': 1,
            'headerFormat': '<b>{point.x}.Spielminute</b><br>',
        },

        'xAxis': {
            'gridLineWidth': 1,
            'minTickInterval': 20,
            'min': 0,
            'max' : 60,
            'endOnTick': 1,

            'categories': min_list,
            'title': {
                'text': 'Zeit',
                'style': {'color': '#404040', 'font-size': label_size},
            },
            'crosshair': 1,
        },

        'yAxis': [{
            'title': {
                'text': 'Anzahl Strafzeiten',
                'style': {'color': '#404040', 'font-size': label_size},
            },
            }],

        'series': [{
            'name': 'Eigene Strafzeiten',
            'data': pnalty_list,
            'color': '#7cb5ec',
        }, {
            'name': 'Strafzeiten Gegner',
            'data': opnalty_list,
            'color': '#d8d9da',
        }]
    }
    return chart_options


def get_visitor_stats(request, season_id):
    """ get visitor stats """
    # whats the id of best german hockey team
    ebb_id = get_team_id('EBB')

    m_list = []

    # get match list and the matchid from former season
    m_list = Match.objects.filter(season=season_id, home_team=ebb_id).exclude(matchday=0).values('id', 'matchday', 'home_team', 'guest_team', 'guest_team__team_name', 'guest_team__short_name')
    om_list = Match.objects.filter(season=season_id-1, home_team=ebb_id).exclude(matchday=0).values_list('id', flat=True)

    # create list of match_ids and a dictinaliry of home_matches
    match_list = []
    match_dic = {}

    season_name = 'aktuelle Saison'
    oseason_name = 'Vorsaison'
    average = 'Durschnitt'
    oaverage = 'Durschnitt'
    try:
        s_list = [season_id, season_id - 1]
        season_list = Season.objects.filter(id__in=s_list).values('id', 'name')
        for season in season_list:
            if int(season['id']) == season_id:
                if request.mobile:
                    season_name = 'Saison {0}'.format(season['name'])
                    season_name = season_name.replace('202', '2')
                    season_name = season_name.replace('201', '1')
                    average = '&Oslash;: {0}'.format(season['name'])
                    average = average.replace('202', '2')
                    average = average.replace('201', '1')
                else:
                    season_name = 'Saison: {0}'.format(season['name'])
                    average = 'Durchschnitt {0}'.format(season['name'])
            elif int(season['id']) == season_id - 1:
                if request.mobile:
                    oseason_name = 'Saison {0}'.format(season['name'])
                    oseason_name = oseason_name.replace('202', '2')
                    oseason_name = oseason_name.replace('201', '1')
                    oaverage = '&Oslash;: {0}'.format(season['name'])
                    oaverage = oaverage.replace('202', '2')
                    oaverage = oaverage.replace('201', '1')
                else:
                    oaverage = 'Durchschnitt {0}'.format(season['name'])
    except BaseException:
        pass

    for match in m_list:
        match_list.append(match['id'])
        match_dic[match['id']] = {}
        match_dic[match['id']]['matchday'] = match['matchday']
        match_dic[match['id']]['name'] = match['guest_team__team_name']
        match_dic[match['id']]['short_name'] = match['guest_team__short_name']

    # get visitors per match
    visitor_dic = {}
    visitor_list = Visitor.objects.filter(match__in=match_list).values('match', 'number')
    # get visitors from last season
    o_visitor_list = Visitor.objects.filter(match__in=om_list).values_list('number', flat=True)

    cnt = 0
    _sum = 0
    _osum = 0
    for visitor in visitor_list:
        if visitor['match'] in match_dic:
            visitor_dic[visitor['match']] = {}
            visitor_dic[visitor['match']]['matchday'] = match_dic[visitor['match']]['matchday']
            if request.mobile:
                visitor_dic[visitor['match']]['name'] = match_dic[visitor['match']]['short_name']
            else:
                visitor_dic[visitor['match']]['name'] = match_dic[visitor['match']]['name']

            visitor_dic[visitor['match']]['number'] = visitor['number']
            if cnt+1 <= len(o_visitor_list):
                visitor_dic[visitor['match']]['onumber'] = o_visitor_list[cnt]
                _osum += o_visitor_list[cnt]
                visitor_dic[visitor['match']]['delta'] = round((float(visitor_dic[visitor['match']]['number'])/o_visitor_list[cnt]-1)*100, 1)
                visitor_dic[visitor['match']]['oavg'] = int(_osum/(cnt+1))

            cnt += 1
            _sum += visitor['number']
            visitor_dic[visitor['match']]['avg'] = int(_sum/cnt)

    visitor_chart = get_visitor_chart(request, visitor_dic, season_name, oseason_name, average, oaverage)

    return(visitor_dic, visitor_chart)

def get_visitor_chart(request, visitor_dic, season_name, oseason_name, average, oaverage):
    """ get visitor chart """
    mday_list = []
    visitor_list = []
    ovisitor_list = []
    avg_list = []
    oavg_list = []

    for visitor in sorted(visitor_dic):
        mday_list.append(int(visitor_dic[visitor]['matchday']))
        visitor_list.append(int(visitor_dic[visitor]['number']))
        if 'onumber' in visitor_dic[visitor]:
            ovisitor_list.append(int(visitor_dic[visitor]['onumber']))
        else:
            ovisitor_list.append(0)
        avg_list.append(int(visitor_dic[visitor]['avg']))
        if 'oavg' in visitor_dic[visitor]:
            oavg_list.append(int(visitor_dic[visitor]['oavg']))
        else:
            oavg_list.append(0)

    # identify UA to detect mobiles
    mobile_browser = request.mobile

    title = ''

    label_size = '10px'
    show_legend = 1
    v_align = 'bottom'

    # we need to change some setting for mobile access
    if mobile_browser:
        label_size = '8px'
        show_legend = 1
        v_align = 'top'

    chart_options = {

        'chart': {
            'type': 'column',
        },

        'exporting': {
            'chartOptions': {
                'plotOptions': {
                    'series': {
                        'dataLabels': {
                            'enabled': 0,
                        },
                    },
                },
            },
            'fallbackToExportServer': 0,
        },

        'title': {
            'text': title,
            'style': {'color': '#404040', 'font-size': '12px'},
        },

        'legend': {
            'enabled': show_legend,
            'useHTML': 1,
            'itemStyle': {'color': '#404040', 'font-size': label_size},
            'verticalAlign': v_align,
        },

        'tooltip': {
            'shared': 1,
            'useHTML': 1,
            'headerFormat': '<b>{point.x}.Spieltag</b><br>',
        },

        'xAxis': {
            'categories': mday_list,
            'title': {
                'text': 'Spieltag',
                'style': {'color': '#404040', 'font-size': label_size},
            },
            'crosshair': 1,
        },

        'yAxis': [{
            'title': {
                'text': 'Anzahl Zuschauer',
                'style': {'color': '#404040', 'font-size': label_size},
            },
            },],

        'series': [{
            'name': season_name,
            'data': visitor_list,
            'color': '#7cb5ec',
        }, {
            'name': oseason_name,
            'data': ovisitor_list,
            'color': '#d8d9da',
        }, {
            'type': 'spline',
            'name': average,
            'data': avg_list,
            'color': '#030357',
        }, {
            'type': 'spline',
            'name': oaverage,
            'data': oavg_list,
            'color': '#68717a',
        }]
    }
    return chart_options

def lookup_team(team_list, team):
    """ lookup team """
    team_id = None
    team_name = None
    short_name = None

    # now guess the home-team
    for _team in team_list:

        if _team['team_name'] == team:
            team_id = _team['team_id']
            team_name = _team['team_name']
            short_name = _team['short_name']
            break
        else:
            _list = _team['team_name'].split()
            for ele in _list:
                if(ele in team or team in ele):
                    team_id = _team['team_id']
                    team_name = _team['team_name']
                    short_name = _team['short_name']
                    break

    return(team_id, team_name, short_name)

def check_live_link(_value):
    """ check live link """
    # get season_id
    season_id = len(list(Season.objects.values()))

    # from datetime import datetime, date, time
    # unix timestamp
    uts = int(time.time())
    # day of the week (mon 0 - sun 6)
    now_dow = int(datetime.datetime.today().weekday())
    # get actual hour and day
    now_hour = int(datetime.datetime.now().hour)
    now_day = int(datetime.datetime.now().day)

    # get last and next match
    (match_id, match_date, match_day) = get_last_match(uts, season_id)
    (n_match_id, n_match_date, _n_tv_team) = get_next_match(uts, season_id)

    # if next match is closer we are going to update the next match (sportal kicks in a bid earlier)
    if(n_match_id and abs(uts - n_match_date) < abs(uts - match_date)):
        match_id = n_match_id
        match_date = n_match_date
        match_day = match_day + 1

    try:
        no_bet = Match.objects.filter(id=match_id).values_list('no_bet', flat=True)[0]
    except BaseException:
        no_bet = False

    if not no_bet:
        # get day from match
        match_day = int(datetime.datetime.fromtimestamp(match_date).strftime('%d'))

        # fake variables for testing
        # now_hour = 19
        # now_dow  = 6

        # now the secret souce
        # are we on matchday
        if now_day == match_day:
            # sunday between 1pm and 11pm (CET!!!)
            if(now_dow == 6 and now_hour >= 12 and now_hour <= 22):
                return 1
            # all other days between 7 and 11 (again CET!!!)
            elif(now_hour >= 16 and now_hour <= 22):
                return 1
            else:
                return 0
        else:
            return 0
    else:
        return 0

def get_h2h_statistics(team_filter):
    """ get h2h statistics for a team """

    matches = 0
    wins = 0
    losses = 0
    ot_wins = 0
    ot_losses = 0
    ps_wins = 0
    ps_losses = 0

    # get teamid of ebb)
    team_list = Team.objects.filter(short_name=team_filter).values('short_name', 'matches', 'ebb_wins', 'ebb_losses', 'ebb_ot_wins', 'ebb_ot_losses', 'ebb_ps_wins', 'ebb_ps_losses')[:1]

    try:
        matches = team_list[0]['matches']
        wins = team_list[0]['ebb_wins']
        losses = team_list[0]['ebb_losses']
        ot_wins = team_list[0]['ebb_ot_wins']
        ot_losses = team_list[0]['ebb_ot_losses']
        ps_wins = team_list[0]['ebb_ps_wins']
        ps_losses = team_list[0]['ebb_ps_losses']
    except IndexError:
        pass

    return(matches, wins, losses, ot_wins, ot_losses, ps_wins, ps_losses)

def get_te_stats(url):
    """ get player and team statistics from DEL page """

    print(url)
    player_stat_dic = {}

    fobj = urlopen(url)
    html = fobj.read()
    soup = BeautifulSoup(html, 'lxml')



    return(player_stat_dic)

def print_debug(debug, text):
    """ little helper to print debug messages
        args:
            debug = debug flag
            text  = text to print
        returns:
            (text)
    """
    if debug:
        print('{0}: {1}'.format(datetime.datetime.now(), text))

def check_for_ipv6(ip_addr):
    """ get check for ipv6-addr """
    if ':' in ip_addr:
        return ip_addr
    else:
        return None

def get_ranking(match_id, h_name, g_name, type_='all'):
    """ get ranking of the different teams """

    # get ranking
    ranking_list = Ranking.objects.filter(matchday__id=match_id, type=type_).order_by('ranking').values('ranking', 'team__short_name', 'match', 'score')

    o_dic = {'ht': {'ranking': None, 'score': None, 'match': None, 'name': None}, 'gt': {'ranking': None, 'score': None, 'match': None, 'name': None}}

    # get ranking
    for rank in ranking_list:
        if rank['team__short_name'] == h_name:
            o_dic['ht']['ranking'] = rank['ranking']
            o_dic['ht']['score'] = rank['score']
            o_dic['ht']['match'] = rank['match']
            o_dic['ht']['name'] = h_name
        elif rank['team__short_name'] == g_name:
            o_dic['gt']['ranking'] = rank['ranking']
            o_dic['gt']['score'] = rank['score']
            o_dic['gt']['match'] = rank['match']
            o_dic['gt']['name'] = g_name

    return o_dic

def filter_ranking(season_id, match_id, type_, rfilter):
    """ filter ranking list """

    new_ranking_list = []

    # get last match ranking
    tmp_lranking_list = Ranking.objects.filter(matchday_id=match_id, season_id=season_id, type=type_).order_by('ranking').values('ranking', 'team__team_name', 'team__short_name', 'team__logo_url', 'match', 'won', 'score', 'match', 'goal', 'ggoal', 'penalty', 'team_id', 'wono', 'wonp', 'losto', 'lostp', 'uts', 'source')

    if rfilter > 0:

        # needed have to check why
        rfilter = rfilter + 1

        # convert to dic for faster lookup
        l_ranking_dic = {}
        for ranking in tmp_lranking_list:
            l_ranking_dic[ranking['team_id']] = ranking

        # get last rfilter matches and filter match-id from first entry
        match_list = Match.objects.filter(season_id=season_id, id__lte=match_id, no_bet=False).order_by('-date', '-id').values('id', 'date', 'matchday', 'tv')[:rfilter]
        f_match_id = match_list[len(match_list)-1]['id']

        # get first match ranking
        tmp_franking_list = Ranking.objects.filter(matchday_id=f_match_id, season_id=season_id, type=type_).order_by('ranking').values('ranking', 'team__team_name', 'team__short_name', 'team__logo_url', 'match', 'won', 'score', 'match', 'goal', 'ggoal', 'penalty', 'team_id', 'wono', 'wonp', 'losto', 'lostp', 'uts', 'source')
        # convert to dic for faster lookup
        f_ranking_dic = {}
        for ranking in tmp_franking_list:
            f_ranking_dic[ranking['team_id']] = ranking

        # create dictionary containg the virtual figures
        new_ranking_dic = {}
        if f_ranking_dic and l_ranking_dic:
            for team_id in l_ranking_dic:
                if team_id in f_ranking_dic:
                    new_ranking_dic[team_id] = {}
                    new_ranking_dic[team_id]['score'] = l_ranking_dic[team_id]['score'] - f_ranking_dic[team_id]['score']
                    new_ranking_dic[team_id]['won'] = l_ranking_dic[team_id]['won'] - f_ranking_dic[team_id]['won']
                    new_ranking_dic[team_id]['wono'] = l_ranking_dic[team_id]['wono'] - f_ranking_dic[team_id]['wono']
                    new_ranking_dic[team_id]['wonp'] = l_ranking_dic[team_id]['wonp'] - f_ranking_dic[team_id]['wonp']
                    new_ranking_dic[team_id]['losto'] = l_ranking_dic[team_id]['losto'] - f_ranking_dic[team_id]['losto']
                    new_ranking_dic[team_id]['lostp'] = l_ranking_dic[team_id]['lostp'] - f_ranking_dic[team_id]['lostp']
                    new_ranking_dic[team_id]['goal'] = l_ranking_dic[team_id]['goal'] - f_ranking_dic[team_id]['goal']
                    new_ranking_dic[team_id]['ggoal'] = l_ranking_dic[team_id]['ggoal'] - f_ranking_dic[team_id]['ggoal']
                    new_ranking_dic[team_id]['match'] = l_ranking_dic[team_id]['match'] - f_ranking_dic[team_id]['match']
                    new_ranking_dic[team_id]['penalty'] = l_ranking_dic[team_id]['penalty'] - f_ranking_dic[team_id]['penalty']
                    #  calculate artificial plus/minus
                    new_ranking_dic[team_id]['pm'] = new_ranking_dic[team_id]['goal'] - new_ranking_dic[team_id]['ggoal']

                    # take rest of values from l_ranking_dic
                    new_ranking_dic[team_id]['team__team_name'] = l_ranking_dic[team_id]['team__team_name']
                    new_ranking_dic[team_id]['team__short_name'] = l_ranking_dic[team_id]['team__short_name']
                    new_ranking_dic[team_id]['team__logo_url'] = l_ranking_dic[team_id]['team__logo_url']
                    new_ranking_dic[team_id]['team_id'] = l_ranking_dic[team_id]['team_id']
                    new_ranking_dic[team_id]['uts'] = l_ranking_dic[team_id]['uts']
                    new_ranking_dic[team_id]['source'] = 'filter_ranking()'

        # sort
        tmp_new_ranking_dic = list(new_ranking_dic.items())
        tmp_new_ranking_dic.sort(key=lambda k_d: (-k_d[1]['score'], -k_d[1]['pm']))

        vrank = 1
        for rank in tmp_new_ranking_dic:
            new_ranking_dic[rank[0]]['ranking'] = vrank
            vrank = vrank + 1
            new_ranking_list.append(new_ranking_dic[rank[0]])
    else:
        new_ranking_list = tmp_lranking_list

    return new_ranking_list

def get_special_ranking(season_id, match_id, match_date, _type):
    """ filter ranking list """
    # get last match ranking
    tmp_ranking_list = Ranking.objects.filter(matchday_id=match_id, season_id=season_id, type='all').order_by('ranking').values('team_id', 'team__team_name', 'team__short_name', 'team__logo_url', 'match', 'ppg', 'pps', 'ppp', 'shga', 'ppga', 'shs', 'shp', 'shg', 'penalty', 'goal', 'ggoal', 'won', 'wono', 'wonp', 'losto', 'lostp', 'uts', 'source')

    if tmp_ranking_list[0]['pps'] == 0 and tmp_ranking_list[0]['shs'] == 0 and tmp_ranking_list[0]['match'] != 1:
        (nmatch_id, _nmatch_date, _nmatch_day) = get_last_match(match_date-10, season_id)
        tmp_ranking_list = Ranking.objects.filter(matchday_id=nmatch_id, season_id=season_id, type='all').order_by('ranking').values('team_id', 'team__team_name', 'team__short_name', 'team__logo_url', 'match', 'ppg', 'pps', 'ppp', 'shga', 'ppga', 'shs', 'shp', 'shg', 'penalty', 'goal', 'ggoal', 'won', 'wono', 'wonp', 'losto', 'lostp', 'uts', 'source')

    tmp_ranking_dic = {}
    for ranking in tmp_ranking_list:
        tmp_ranking_dic[ranking['team_id']] = ranking

    tmp_ranking_list = list(tmp_ranking_dic.items())
    tmp_ranking_list.sort(key=lambda k_d: (-k_d[1]['ppp'], -k_d[1]['match']))

    new_ranking_list = []
    vrank = 1
    for rank in tmp_ranking_list:
        tmp_ranking_dic[rank[0]]['ranking'] = vrank
        tmp_ranking_dic[rank[0]]['ppp'] = str(tmp_ranking_dic[rank[0]]['ppp']).replace('.', ',')
        tmp_ranking_dic[rank[0]]['shp'] = str(tmp_ranking_dic[rank[0]]['shp']).replace('.', ',')
        vrank = vrank + 1
        new_ranking_list.append(tmp_ranking_dic[rank[0]])

    return new_ranking_list

def create_rfilter_list(match_day, step=2):
    """ create rfilter list """

    # small hack to avoid user confusion
    if match_day > 0:
        match_day = match_day - 1

    ele_num = int(match_day/step)

    rfilter_list = []
    for cnt in range(1, ele_num+1, 1):
        id_ = cnt * step
        rfilter_list.append({'id': id_, 'text': 'Nur die letzten {0} Spiele'.format(id_)})

    return rfilter_list

def get_gamestats(match_id, mobile_browser=None, period_filter=None):
    """ get gamestats """

    gamestat_dic = default_gamestat_dic()

    # get last rfilter matches and filter match-id from first entry
    match_list = Match.objects.filter(id=match_id, no_bet=False).values('id', 'date', 'matchday', 'home_team__short_name', 'home_team__team_name', 'home_team__logo_url', 'guest_team__short_name', 'guest_team__team_name', 'guest_team__logo_url', 'scorebyperiod', 'gameresult', 'shots', 'del_date')[:1]

    if match_list:

        if 'gameresult' in match_list[0]:
            period_counter = 0
            # check different periods and get statistics
            for period in match_list[0]['gameresult']:
                period_counter = period_counter + 1
                # filter periods if required
                if period_filter and period_counter > period_filter:
                    break
                for param in period:
                    if param in gamestat_dic:
                        if param in ('homeScore', 'guestScore', 'period', 'uniqueID', 'gameNumber', 'homeTpp', 'guestTpp'):
                            gamestat_dic[param] = period[param]
                        else:
                            gamestat_dic[param] = gamestat_dic[param] + period[param]
                    else:
                        # create parameter
                        gamestat_dic[param] = period[param]

                # sort scores in
                if 'homeScoredic' not in gamestat_dic:
                    gamestat_dic['homeScoredic'] = {}
                if 'guestScoredic' not in gamestat_dic:
                    gamestat_dic['guestScoredic'] = {}
                gamestat_dic['guestScoredic'][period['period']] = period['guestScore']
                gamestat_dic['homeScoredic'][period['period']] = period['homeScore']

        # calulcate corsi from shot-stat
        shots_dic = match_list[0]['shots']
        (gamestat_dic['homeshots'], gamestat_dic['guestshots']) = get_corsi(shots_dic)

        # calculate percentage values to show bars
        gamestat_dic = enrich_gamestat_dic(gamestat_dic)

        # enrich further with gamedate from db
        if match_list[0]['del_date'] != 0:
            gamestat_dic['update_human'] = datetime.datetime.fromtimestamp(match_list[0]['del_date'], tz=TIMEZONE).strftime('%d.%m.%y %H:%M')
            gamestat_dic['update'] = match_list[0]['del_date']

        if mobile_browser:
            gamestat_dic['homeTeam'] = match_list[0]['home_team__short_name']
            gamestat_dic['guestTeam'] = match_list[0]['guest_team__short_name']
        else:
            gamestat_dic['homeTeam'] = match_list[0]['home_team__team_name']
            gamestat_dic['guestTeam'] = match_list[0]['guest_team__team_name']

        gamestat_dic['matchday'] = match_list[0]['matchday']
        gamestat_dic['homeLogo'] = match_list[0]['home_team__logo_url']
        gamestat_dic['guestLogo'] = match_list[0]['guest_team__logo_url']
        gamestat_dic['date_human'] = datetime.datetime.fromtimestamp(match_list[0]['date'], tz=TIMEZONE).strftime('%d.%m.%y %H:%M')

    return gamestat_dic

def get_corsi(shots_dic):
    """ get corsi out of shot-stats """

    if shots_dic:

        # count shots per team
        shot_sum_dic = count_shots(shots_dic)

        # home-corsi is caluclated based on saves (1), missed (2), goal (4) and blockeds shots by other team
        return (shot_sum_dic['home']['sum'], shot_sum_dic['visitor']['sum'])

    else:
        return (0, 0)


def count_shots(shots_dic):
    """ count shoots for corsi """
    home_id = shots_dic['match']['home_id']
    _visitor_id = shots_dic['match']['visitor_id']

    # 1: gehalten
    # 2: vorbei
    # 3: geblocked
    # 4: TOR

    shot_sum_dic = {'home': {'sum': 0, 0: 0, 1: 0, 2: 0, 3: 0, 4:0, 5: 0}, 'visitor': {'sum': 0, 0: 0, 1: 0, 2: 0, 3: 0, 4:0, 5: 0}}

    for shot in shots_dic['match']['shots']:
        if shot['team_id'] == home_id:
            team = 'home'
        else:
            team = 'visitor'
        shot_sum_dic[team][shot['match_shot_resutl_id']] += 1
        shot_sum_dic[team]['sum'] += 1

    return shot_sum_dic

def enrich_gamestat_dic(gstat_dic):
    """ calc statistics from camestat """

    # goal percentage
    (gstat_dic['homeScorep'], gstat_dic['guestScorep'], gstat_dic['homeScorec'], gstat_dic['guestScorec']) = percentage_and_bars(gstat_dic['homeScore'], gstat_dic['guestScore'])

    # ppgoal percentage and bars
    (gstat_dic['homePpgp'], gstat_dic['guestPpgp'], gstat_dic['homePpgc'], gstat_dic['guestPpgc']) = percentage_and_bars(gstat_dic['homePpg'], gstat_dic['guestPpg'])

    # shorthanded goals percentage
    (gstat_dic['homeShgp'], gstat_dic['guestShgp'], gstat_dic['homeShgc'], gstat_dic['guestShgc']) = percentage_and_bars(gstat_dic['homeShg'], gstat_dic['guestShg'])

    # shots on goal percentage
    (gstat_dic['homeSogp'], gstat_dic['guestSogp'], gstat_dic['homeSogc'], gstat_dic['guestSogc']) = percentage_and_bars(gstat_dic['homeSog'], gstat_dic['guestSog'])

    # saves
    (gstat_dic['homeSsgp'], gstat_dic['guestSsgp'], gstat_dic['homeSsgc'], gstat_dic['guestSsgc']) = percentage_and_bars(gstat_dic['homeSsg'], gstat_dic['guestSsg'])

    # penalty minutes
    (gstat_dic['homePimp'], gstat_dic['guestPimp'], gstat_dic['homePimc'], gstat_dic['guestPimc']) = percentage_and_bars(gstat_dic['homePim'], gstat_dic['guestPim'])

    # faceoffs minutes
    (gstat_dic['homeBullyp'], gstat_dic['guestBullyp'], gstat_dic['homeBullyc'], gstat_dic['guestBullyc']) = percentage_and_bars(gstat_dic['homeBully'], gstat_dic['guestBully'])

    # corsi percentage
    (gstat_dic['homeshotsp'], gstat_dic['guestshotsp'], gstat_dic['homeshotsc'], gstat_dic['guestshotsc']) = percentage_and_bars(gstat_dic['homeshots'], gstat_dic['guestshots'])

    # time in powerplay
    (hometpp, _sinin) = gstat_dic['homeTpp'].split(':')
    (guesttpp, _sinin) = gstat_dic['guestTpp'].split(':')
    (gstat_dic['homeTppp'], gstat_dic['guestTppp'], gstat_dic['homeTppc'], gstat_dic['guestTppc']) = percentage_and_bars(int(hometpp), int(guesttpp))

    return gstat_dic

def percentage_and_bars(val1, val2):
    """ claculate percentage und bars """
    g_all = val1 + val2
    if g_all == 0:
        val1p = 0
        val2p = 0
    else:
        val1p = round(val1/g_all * 100)
        val2p = round(val2/g_all * 100)
    (val1c, val2c) = color_bars(val1, val2)

    return(val1p, val2p, val1c, val2c)

def color_bars(val1, val2):
    """ color the bars depending on value"""

    color_lead = 'ehc-red-2'
    color_behind = 'ehc-blue-2'
    color_zero = 'w3-light-grey'

    if val1 == 0:
        val1c = color_zero
    else:
        val1c = color_behind
    if val2 == 0:
        val2c = color_zero
    else:
        val2c = color_behind

    if val1 > val2:
        val1c = color_lead
    elif val2 > val1:
        val2c = color_lead

    return (val1c, val2c)

def default_gamestat_dic():
    """ set defaults for statistics dictionary """
    gamestat_dic = {
        'homeScore': 0,
        'guestScore': 0,
        'homePpg': 0,
        'guestPpg': 0,
        'homeShg': 0,
        'guestShg': 0,
        'homeSog': 0,
        'guestSog': 0,
        'homeSsg': 0,
        'guestSsg': 0,
        'homePim': 0,
        'guestPim': 0,
        'homeBully': 0,
        'guestBully': 0,
        'homeTpp': '0:00',
        'guestTpp': '0:00',
        'homeScoredic': {1: '-', 2: '-', 3: '-', 'OT': '-', 'GWS': '-'},
        'guestScoredic': {1: '-', 2: '-', 3: '-', 'OT': '-', 'GWS': '-'}
    }

    return gamestat_dic

def prep_gamestats(match_id, uts, mobile_browser):
    """ prepare gamestats """

    # get gamestatistics
    gamestat_dic = get_gamestats(match_id, mobile_browser)

    # set update date
    d_update = None
    if 'update_human' in gamestat_dic and 'update' in gamestat_dic:
        if abs(uts - gamestat_dic['update']) < 7200:
            d_update = gamestat_dic['update_human']

    if 'homeTeam' in gamestat_dic and 'guestTeam' in gamestat_dic and 'matchday' in gamestat_dic:
        title = '{2}. Spieltag: {0} vs. {1}'.format(gamestat_dic['homeTeam'], gamestat_dic['guestTeam'], gamestat_dic['matchday'])
    else:
        title = None

    return(d_update, title, gamestat_dic)

def prep_shotstats(match_list, group_by=False, x_max=61):
    """ prepare shot stats """

    if match_list[0]['home_team__short_name'] == 'EBB':
        ebb_logo = match_list[0]['home_team__logo_url']
        o_team = match_list[0]['guest_team__short_name']
        o_team_name = match_list[0]['guest_team__team_name']
        o_team_logo = match_list[0]['guest_team__logo_url']
        home_match = True
        # ebb_zone = ('home_bottom_polygon', 'home_center_polygon', 'home_defense_polygon', 'home_top_polygon', False)
        # o_team_zone = ('away_bottom_polygon', 'away_center_polygon', 'away_defense_polygon', 'away_top_polygon', False)
    else:
        o_team = match_list[0]['home_team__short_name']
        o_team_name = match_list[0]['home_team__team_name']
        o_team_logo = match_list[0]['home_team__logo_url']
        ebb_logo = match_list[0]['guest_team__logo_url']
        home_match = False
        # o_team_zone = ('home_bottom_polygon', 'home_center_polygon', 'home_defense_polygon', 'home_top_polygon', False)
        # ebb_zone = ('away_bottom_polygon', 'away_center_polygon', 'away_defense_polygon', 'away_top_polygon', False)

    ebb_zone = ('slot', 'left', 'right', 'blue_line', 'neutral_zone', 'behind_goal')
    o_team_zone = ('slot', 'left', 'right', 'blue_line', 'neutral_zone', 'behind_goal')

    # initialize dicionaries
    shot_min_dic = {'EBB': {}, o_team: {}}
    goal_dic = {'EBB': {}, o_team: {}}

    # initialize the different minutes)
    if group_by == 'match_shot_resutl_id':
        for ele in range(1, 6):
            shot_min_dic['EBB'][ele] = {}
            shot_min_dic[o_team][ele] = {}

    for min_ in range(0, x_max):
        if group_by == 'match_shot_resutl_id':
            for ele in range(1, 6):
                shot_min_dic['EBB'][ele][min_] = 0
                shot_min_dic[o_team][ele][min_] = 0

        elif group_by == 'pos_period':
            for pos in ebb_zone:
                shot_min_dic['EBB'][pos] = {}
                for period in (1, 2, 3, 4, 5):
                    shot_min_dic['EBB'][pos][period] = 0
            for pos in o_team_zone:
                shot_min_dic[o_team][pos] = {}
                for period in (1, 2, 3, 4, 5):
                    shot_min_dic[o_team][pos][period] = 0
        elif group_by == 'min':
            shot_min_dic['EBB'][min_] = 0
            shot_min_dic[o_team][min_] = 0

    return (ebb_logo, o_team, o_team_name, o_team_logo, shot_min_dic, goal_dic, home_match)

def get_game_puckpossession(match_id, mobile_browser, sog_filter=False, marker_prefix=None):
    """ get shots per match dictionary and graph """

    # get last rfilter matches and filter match-id from first entry
    match_list = Match.objects.filter(id=match_id, no_bet=False).values('id', 'date', 'matchday', 'home_team__short_name', 'home_team__team_name', 'home_team__logo_url', 'guest_team__short_name', 'guest_team__team_name', 'guest_team__logo_url', 'shots', 'del_date')[:1]

    shot_chart = {}
    shot_table = {}

    if match_list:

        shot_dic = match_list[0]['shots']

        # maximum x value
        try:
            x_max = math.ceil(sorted(shot_dic['match']['shots'], key=lambda x: x['time'])[-1]['time']/60) + 1
        except BaseException:
            x_max = 61

        # get some figures we need later
        (ebb_logo, o_team, o_team_name, o_team_logo, shot_min_dic, goal_dic, _home_match) = prep_shotstats(match_list, 'min', x_max)

        if shot_dic:
            # we did not register OT
            ot_reg = None
            for shot in shot_dic['match']['shots']:
                # get min out of seconds
                min_ = math.ceil(shot['time']/60)
                # create additional entries if we are running overtime
                if min_ > 60 and ot_reg is None:
                    # now we registered OT
                    ot_reg = True
                    for val in range(61, 66):
                        shot_min_dic['EBB'][val] = 0
                        shot_min_dic[o_team][val] = 0
                # these are shots from EBB
                if shot['team_id'] == 3:
                    shot_min_dic['EBB'][min_] += 1
                    if shot['match_shot_resutl_id'] == 4:
                        goal_dic['EBB'][min_] = shot['last_name']
                else:
                    shot_min_dic[o_team][min_] += 1
                    if shot['match_shot_resutl_id'] == 4:
                        goal_dic[o_team][min_] = shot['last_name']

            # aggregate shots per min
            shot_sum_dic = {'EBB': {}, o_team: {}}
            ebb_min_values = list(shot_min_dic['EBB'].values())
            o_team_min_values = list(shot_min_dic[o_team].values())

            for min_ in shot_min_dic['EBB']:
                shot_sum_dic['EBB'][min_] = sum(ebb_min_values[:min_])
            for min_ in shot_min_dic[o_team]:
                shot_sum_dic[o_team][min_] = sum(o_team_min_values[:min_])

            # create chart
            shot_chart = create_puckpossession_chart(shot_sum_dic, goal_dic, o_team, ebb_logo, o_team_logo, mobile_browser)
            shot_table = create_shotperiod_table(shot_min_dic, ebb_logo, o_team_logo, o_team, o_team_name, sog_filter)

    return (shot_chart, shot_table)

def create_puckpossession_chart(shots_sum_dic, goal_dic, o_team, ebb_logo, o_team_logo, mobile_browser):
    """  create chart for the shots """

    # we need to change some setting for mobile access
    if mobile_browser:
        marker_width = 15
        marker_height = 15
        label_size = '8px'
        show_legend = 1
        v_align = 'top'
    else:
        marker_width = 22
        marker_height = 22
        label_size = '10px'
        v_align = 'bottom'
        show_legend = 1


    min_list = list(shots_sum_dic['EBB'].keys())
    # y1_list = list(shots_sum_dic['EBB'].values())
    y1_list = []
    for min_, value in shots_sum_dic['EBB'].items():
        # set marker on graph if there was a goal in this min
        if min_ in goal_dic['EBB']:
            y1_list.append({'y' : value, 'marker' : {'enabled': 1, 'width': marker_width, 'height': marker_height, 'symbol': 'url({0})'.format(ebb_logo),}})
        elif min_ in goal_dic[o_team]:
            y1_list.append({'y' : value, 'marker' : {'enabled': 1, 'width': marker_width, 'height': marker_height, 'symbol': 'url({0})'.format(o_team_logo),}})
        else:
            y1_list.append(value)

    y2_list = list(shots_sum_dic[o_team].values())

    title = ''

    chart_options = {

        'chart': {
            'type': 'area',
            'height': '70%'
        },

        'exporting': {
            'chartOptions': {
                'plotOptions': {
                    'series': {
                        'dataLabels': {
                            'enabled': 0,
                        },
                    },
                },
            },
            'fallbackToExportServer': 0,
        },

        'title': {
            'text': title,
            'style': {'color': '#404040', 'font-size': '12px'},
        },

        'credits': {
            'text': 'Nach einer Idee von @h_modes',
            'href': 'https://twitter.com/h_modes'
        },

        'legend': {
            'enabled': show_legend,
            'useHTML': 1,
            'itemStyle': {'color': '#404040', 'font-size': label_size},
            'verticalAlign': v_align,
            'symbolRadius': 0
        },

        'tooltip': {
            'pointFormat': '<span style="color:{series.color}">{series.name}</span>: <b>{point.percentage:.1f}%</b> ({point.y:,.0f} shots)<br/>',
            'split': 1,
        },

        'plotOptions': {
            'area': {
                'stacking': 'percent',
                'lineColor': '#ffffff',
                'lineWidth': 2,
                'marker': {
                    'enabled': 0,
                    'symbol': 'diamond'},
                },
            },
        'xAxis': {
            'categories': min_list,
            'title': {
                'text': 'Spielminute',
                'style': {'color': '#404040', 'font-size': label_size},
            },
            'labels': {'style': {'fontSize': label_size},},
            'tickInterval': 5,
            'showFirstLabel': 1,
            'showLastLabel': 1,
            'plotLines': [{
                'color': '#d8d9da',
                'width': 2,
                'value': 20,
            }, {
                'color': '#d8d9da',
                'width': 2,
                'value': 40,
            }, {
                'color': '#d8d9da',
                'width': 2,
                'value': 60,
            }],
        },

        'yAxis': [
            {
                'title': {
                    'text': 'Puckbesitz in %',
                    'style': {'color': '#404040', 'font-size': label_size},
                },
                'plotLines': [{
                    'color': '#d8d9da',
                    'width': 2,
                    'value': 50,
                }],
                'tickInterval': 25,
                'maxPadding': 0.1,
                'labels': {'style': {'fontSize': label_size},},
                'reversedStacks': 0,
            }],
        'series': [{
            'name': 'EBB',
            'data': y1_list,
            'color': '#7cb5ec',
            'zIndex': 2,
        }, {
            'name': '{0}'.format(o_team),
            'data': y2_list,
            'color': '#b0b3b5',
            'zIndex': 1,
        }]
    }
    return chart_options

def get_shots_per_match(match_id, mobile_browser, sog_filter=False, marker_prefix=None, shotflow_chart=False):
    """ get shots per match dictionary and graph """

    # get last rfilter matches and filter match-id from first entry
    match_list = Match.objects.filter(id=match_id, no_bet=False).values('id', 'date', 'matchday', 'home_team__short_name', 'home_team__team_name', 'home_team__logo_url', 'guest_team__short_name', 'guest_team__team_name', 'guest_team__logo_url', 'shots', 'period_events', 'del_date')[:1]

    shot_chart = {}
    shot_table = {}

    if match_list:

        shot_dic = match_list[0]['shots']

        try:
            x_max = math.ceil(sorted(shot_dic['match']['shots'], key=lambda x: x['time'])[-1]['time']/60) + 1
        except BaseException:
            x_max = 61

        # get some figures we need later
        (ebb_logo, o_team, o_team_name, o_team_logo, shot_min_dic, goal_dic, home_match) = prep_shotstats(match_list, 'min', x_max)
        if marker_prefix:
            mebb_logo = marker_prefix + ebb_logo
            mo_team_logo = marker_prefix + o_team_logo
        else:
            mebb_logo = ebb_logo
            mo_team_logo = o_team_logo

        if shot_dic:
            # we did not register OT
            ot_reg = None
            for shot in shot_dic['match']['shots']:
                # get min out of seconds
                min_ = math.ceil(shot['time']/60)
                # create additional entries if we are running overtime
                if min_ > 60 and ot_reg is None:
                    # now we registered OT
                    ot_reg = True
                    for val in range(61, 66):
                        shot_min_dic['EBB'][val] = 0
                        shot_min_dic[o_team][val] = 0
                # these are shots from EBB
                if shot['team_id'] == 3:
                    if sog_filter:
                        # filter on block (1) and goal(4)
                        if shot['match_shot_resutl_id'] in (1, 4):
                            shot_min_dic['EBB'][min_] += 1
                            if shot['match_shot_resutl_id'] == 4:
                                goal_dic['EBB'][min_] = shot['last_name']
                    else:
                        shot_min_dic['EBB'][min_] += 1
                        if shot['match_shot_resutl_id'] == 4:
                            goal_dic['EBB'][min_] = shot['last_name']
                else:
                    if sog_filter:
                        # these are ghe shots from the f*****
                        if shot['match_shot_resutl_id'] in (1, 4):
                            # filter block(1) hehe and goal (4) shit
                            shot_min_dic[o_team][min_] += 1
                            if shot['match_shot_resutl_id'] == 4:
                                goal_dic[o_team][min_] = shot['last_name']
                    else:
                        shot_min_dic[o_team][min_] += 1
                        if shot['match_shot_resutl_id'] == 4:
                            goal_dic[o_team][min_] = shot['last_name']

            # aggregate shots per min
            shot_sum_dic = {'EBB': {}, o_team: {}}
            ebb_min_values = list(shot_min_dic['EBB'].values())
            o_team_min_values = list(shot_min_dic[o_team].values())

            for min_ in shot_min_dic['EBB']:
                shot_sum_dic['EBB'][min_] = sum(ebb_min_values[:min_])
            for min_ in shot_min_dic[o_team]:
                shot_sum_dic[o_team][min_] = sum(o_team_min_values[:min_])

            if shotflow_chart:
                # get penalty_plotlines
                plotline_list = get_penalty_plotlines(match_list[0]['period_events'], home_match, '#e9f3fc')
                shot_chart = create_shotflow_chart(shot_min_dic, goal_dic, o_team, mebb_logo, mo_team_logo, mobile_browser, sog_filter, marker_prefix, plotline_list, home_match)
            else:
                # get penalty_plotlines
                plotline_list = get_penalty_plotlines(match_list[0]['period_events'], home_match)
                shot_chart = create_shotsum_chart(shot_sum_dic, shot_min_dic, goal_dic, o_team, mebb_logo, mo_team_logo, mobile_browser, sog_filter, marker_prefix, plotline_list)

            shot_table = create_shotperiod_table(shot_min_dic, ebb_logo, o_team_logo, o_team, o_team_name, sog_filter)

    return (shot_chart, shot_table)

def get_game_flow(match_id, mobile_browser, marker_prefix=None):
    """ get shots per match dictionary and graph """

    # get last rfilter matches and filter match-id from first entry
    match_list = Match.objects.filter(id=match_id, no_bet=False).values('id', 'date', 'matchday', 'home_team__short_name', 'home_team__team_name', 'home_team__logo_url', 'guest_team__short_name', 'guest_team__team_name', 'guest_team__logo_url', 'shots', 'period_events', 'del_date')[:1]

    shot_chart = {}
    shot_table = {}

    if match_list:

        shot_dic = match_list[0]['shots']

        if shot_dic:
            # get the timestamp of last shot of the match (default 3600)
            try:
                x_max = sorted(shot_dic['match']['shots'], key=lambda x: x['time'])[-1]['time'] + 1
            except BaseException:
                x_max = 3600 + 1

            # get some figures we max need later
            (ebb_logo, o_team, o_team_name, o_team_logo, shot_min_dic, goal_dic, home_match) = prep_shotstats(match_list, 'sec', x_max)

            tmp_dic = {'EBB': {}, o_team: {}}

            # itereate of the shot dictionary
            if shot_dic:
                for shot in shot_dic['match']['shots']:

                    # timestamp of shot
                    sec_ = shot['time']
                    min_ = math.ceil(shot['time']/60)

                    # these are shots from EBB
                    if shot['team_id'] == 3:
                        tmp_dic['EBB'][sec_] = 1
                        if shot['match_shot_resutl_id'] == 4:
                            goal_dic['EBB'][min_] = shot['last_name']
                    else:
                        tmp_dic[o_team][sec_] = 1
                        if shot['match_shot_resutl_id'] == 4:
                            goal_dic[o_team][min_] = shot['last_name']

            shot_flow_dic = {'EBB': {}, o_team: {}}

            divisor = 0
            ebb_cnt = 0
            oteam_cnt = 0

            for sec_ in range(0, x_max):

                # reset counter during period start
                if sec_ in [1201, 2401, 3601]:
                    ebb_cnt = 0
                    oteam_cnt = 0
                    divisor = 0

                # increase divisor
                divisor += 1

                # increase counter in case there is a shot
                if sec_ in tmp_dic['EBB']:
                    ebb_cnt += 1
                if sec_ in tmp_dic[o_team]:
                    oteam_cnt += 1

                # store counters but only the minute interval
                if sec_ % 60 == 0:
                    min_ = sec_/60
                    div_ = divisor/60
                    shot_flow_dic['EBB'][min_] = round(ebb_cnt * 60/div_, 0)
                    shot_flow_dic[o_team][min_] = round(oteam_cnt * 60/div_, 0)
                    # else:


            shot_flow_dic['EBB'][math.ceil(x_max/60)] = round(ebb_cnt * 60/div_, 0)
            shot_flow_dic[o_team][math.ceil(x_max/60)] = round(oteam_cnt * 60/div_, 0)

            # get penalty_plotlines
            plotline_list = get_penalty_plotlines(match_list[0]['period_events'], home_match, '#e9f3fc')
            # create chart
            shot_chart = create_shotflow_chart(shot_flow_dic, goal_dic, o_team, ebb_logo, o_team_logo, mobile_browser, marker_prefix, plotline_list, home_match)

    return (shot_chart, shot_table)

def create_shotflow_chart(shot_flow_dic, goal_dic, o_team, ebb_logo, o_team_logo, mobile_browser, marker_prefix, plotband_list, home_match):
    """  create chart for the shots """

    # we need to change some setting for mobile access
    if mobile_browser:
        marker_width = 15
        marker_height = 15
        marker_radius = 5
        label_size = '8px'
        show_legend = 0
        v_align = 'top'
        title_x = 60
        title_y = 40
        subt_x = -10
        subt_y = 40
        logo_width = 35
    else:
        marker_width = 22
        marker_height = 22
        marker_radius = 5
        label_size = '10px'
        v_align = 'bottom'
        show_legend = 0
        title_x = 100
        title_y = 80
        subt_x = -50
        subt_y = 80
        logo_width = 55

    # calculate max val to keep axis centered
    y_max = max(list(shot_flow_dic['EBB'].values()))
    if y_max < max(list(shot_flow_dic[o_team].values())):
        y_max = max(list(shot_flow_dic[o_team].values()))
    y_min = y_max * -1

    # hack
    # shot_flow_dic['EBB'][0] = ''
    # shot_flow_dic[o_team][0] = ''

    x_list = list(shot_flow_dic['EBB'].keys())

    left_list = []
    right_list = []
    if home_match:

        for min_, value in shot_flow_dic['EBB'].items():
            # set marker on graph if there was a goal in this min
            if min_ in goal_dic['EBB'].keys():
                left_list.append({'y' : value * -1, 'marker' : {'fillColor': '#000052', 'enabled': 1, 'radius': marker_radius, 'symbol': 'circle'}, 'dataLabels': {'enabled': 1, 'useHTML': 1, 'color': '#000052', 'format': '{0}'.format(goal_dic['EBB'][min_])}})
            else:
                left_list.append(value * -1)

        left_team = 'EBB'
        left_logo = ebb_logo
        left_color = '#7cb5ec'

        for min_, value in shot_flow_dic[o_team].items():
            # set marker on graph if there was a goal in this min
            if min_ in goal_dic[o_team].keys():
                right_list.append({'y' : value, 'marker' : {'fillColor': '#525960', 'enabled': 1, 'radius': marker_radius, 'symbol': 'circle'}, 'dataLabels': {'y': 25, 'enabled': 1, 'useHTML': 1, 'color': '#525960', 'format': '{0}'.format(goal_dic[o_team][min_])}})
            else:
                right_list.append(value)

        right_team = o_team
        right_logo = o_team_logo
        right_color = '#b0b3b5'

    else:

        for min_, value in shot_flow_dic[o_team].items():
            # set marker on graph if there was a goal in this min
            if min_ in goal_dic[o_team].keys():
                left_list.append({'y' : value * -1, 'marker' : {'fillColor': '#525960', 'enabled': 1, 'radius': marker_radius, 'symbol': 'circle'}, 'dataLabels': {'y': 25, 'useHTML': 1, 'enabled': 1, 'color': '#525960', 'format': '{0}'.format(goal_dic[o_team][min_])}})
            else:
                left_list.append(value * -1)

        left_team = o_team
        left_logo = o_team_logo
        left_color = '#b0b3b5'

        for min_, value in shot_flow_dic['EBB'].items():
            # set marker on graph if there was a goal in this min
            if min_ in goal_dic['EBB'].keys():
                right_list.append({'y' : value, 'marker' : {'fillColor': '#000052', 'enabled': 1, 'radius': marker_radius, 'symbol': 'circle'}, 'dataLabels': {'enabled': 1, 'useHTML': 1, 'color': '#000052', 'format': '{0}'.format(goal_dic['EBB'][min_])}})
            else:
                right_list.append(value)

        right_team = 'EBB'
        right_logo = ebb_logo
        right_color = '#7cb5ec'

    chart_options = {

        'chart': {
            'type': 'areaspline',
            'inverted': 1,
            'height': '100%',
            'alignTicks': 0,
        },

        'exporting': {
            'chartOptions': {
                'plotOptions': {
                    'series': {
                        'dataLabels': {
                            'enabled': 0,
                        },
                    },
                },
            },
            'fallbackToExportServer': 0,
        },

        'title': {
            'useHTML': 1,
            'text': '<img src="{0}" width="{1}">'.format(left_logo, logo_width),
            'floating': 1,
            'align': 'left',
            'x': title_x,
            'y': title_y,
        },

        'subtitle': {
            'useHTML': 1,
            'text': '<img src="{0}" width="{1}">'.format(right_logo, logo_width),
            'floating': 1,
            'align': 'right',
            'x': subt_x,
            'y': subt_y,
        },

        'credits': {
            'text': 'Nach einer Idee von @DanielT_W',
            'href': 'https://twitter.com/danielt_w'
        },

        'legend': {
            'enabled': show_legend,
            'useHTML': 1,
            'itemStyle': {'color': '#404040', 'font-size': label_size},
            'verticalAlign': v_align,
            'symbolRadius': 0,
        },

        'tooltip': {
            'shared': 1,
            'useHTML': 1,
            'headerFormat': '<b>{point.x}.Minute</b><br>',
        },

        'plotOptions': {
            'areaspline': {
                'marker': {
                    'enabled': 0,
                },
            },
        },

        'xAxis': {
            'categories': x_list,
            'title': {
                'text': 'Spielminute',
                'style': {'color': '#404040', 'font-size': label_size},
            },
            'labels': {'style': {'fontSize': label_size},},
            'tickInterval': 5,
            'showFirstLabel': 1,
            'showLastLabel': 1,
            'breaks': [{'from': 0, 'to': 1, 'breakSize': 0}, {'from': 20, 'to': 21, 'breakSize': 0}, {'from': 40, 'to': 41, 'breakSize': 0}, {'from': 60, 'to': 61, 'breakSize': 0}],
            'plotLines': [{
                'color': '#d8d9da',
                'width': 2,
                'value': 20,
            }, {
                'color': '#d8d9da',
                'width': 2,
                'value': 40,
            }, {
                'color': '#d8d9da',
                'width': 2,
                'value': 60,
            }],
            'plotBands': plotband_list,

        },
        'yAxis': [
            {
                'title': {
                    'text': 'Schüsse pro 60min',
                    'style': {'color': '#404040', 'font-size': label_size},
                },
                'tickInterval': 100,
                'maxPadding': 0.1,
                'labels': {'style': {'fontSize': label_size},},
                'min': y_min,
                'max': y_max,
            }],

        'series': [{
            'name': left_team,
            'data': left_list,
            'color': left_color,
            # 'fillOpacity': 1,
        }, {
            'name': right_team,
            'data': right_list,
            'color': right_color,
            # 'fillOpacity': 1,
        }]
    }

    return chart_options

def get_penalty_plotlines(event_list, home_match, ebb_color='#e6e6ff', o_team_color='#f1f2f3'):
    """ create plotlines for penalites """

    # define colors for penalty
    # ebb_color = '#d6e0f5'
    # ebb_color = '#e6e6ff'
    # o_team_color = '#f1f2f3'
    plotline_list = []

    for period in event_list:
        for event in event_list[period]:

            # filter penalties
            if event['type'] == 'penalty':
                # convert time to minute
                min_from = math.ceil(event['data']['time']['from']['scoreboardTime']/60)
                min_to = math.ceil(event['data']['time']['to']['scoreboardTime']/60)
                # print(event['data']['codename'], event['data']['team'], event['data']['shooting'], event['data']['duration'], event['data']['disciplinedPlayer']['surname'], event['data']['disciplinedPlayer']['jersey'], min_from, min_to)
                # create dictionary
                tmp_dic = {'from': min_from, 'to': min_to}

                # set color
                if home_match:
                    if event['data']['team'] == 'home':
                        tmp_dic['color'] = ebb_color
                    elif event['data']['team'] == 'visitor':
                        tmp_dic['color'] = o_team_color
                else:
                    if event['data']['team'] == 'home':
                        tmp_dic['color'] = o_team_color
                    elif event['data']['team'] == 'visitor':
                        tmp_dic['color'] = ebb_color
                # append dictionary to list
                plotline_list.append(tmp_dic)

    return plotline_list

def create_shotperiod_table(shot_min_dic, ebb_logo, o_team_logo, o_team, o_team_name, sog_filter):
    """ create table including shots per persiod """

    if sog_filter:
        title = 'Torschüsse pro Drittel'
    else:
        title = 'Schüsse pro Drittel'

    tmp_name_dic = {'EBB': {'name': 'Eisbären Berlin', 'logo': ebb_logo}, o_team: {'name': o_team_name, 'logo': o_team_logo}}
    table_dic = {'th': ['', title, '1st', '2nd', '3rd', 'OT', 'Summe'], 'align': [None, 'left', None, None, None, None, None], 'td': []}

    for ele in ('EBB', o_team):
        sp1 = 0
        sp2 = 0
        sp3 = 0
        sot = 0
        for min_ in shot_min_dic[ele]:
            if min_ < 21:
                sp1 += shot_min_dic[ele][min_]
            elif min_ < 41:
                sp2 += shot_min_dic[ele][min_]
            elif min_ < 61:
                sp3 += shot_min_dic[ele][min_]
            else:
                sot += shot_min_dic[ele][min_]
        table_dic['td'].append([tmp_name_dic[ele]['logo'], tmp_name_dic[ele]['name'], sp1, sp2, sp3, sot, sp1+sp2+sp3+sot])

    return table_dic

def create_shotsum_chart(shots_sum_dic, shot_min_dic, goal_dic, o_team, ebb_logo, o_team_logo, mobile_browser, sog_filter, marker_prefix, plotband_list):
    """  create chart for the shots """

    # we need to change some setting for mobile access
    if mobile_browser:
        marker_width = 15
        marker_height = 15
        marker_radius = 5
        label_size = '8px'
        show_legend = 1
        v_align = 'top'
    else:
        marker_width = 22
        marker_height = 22
        marker_radius = 5
        label_size = '10px'
        v_align = 'bottom'
        show_legend = 1

    min_list = list(shots_sum_dic['EBB'].keys())
    bar1_list = list(shot_min_dic['EBB'].values())
    bar2_list = list(shot_min_dic[o_team].values())
    # spline1_list = list(shots_sum_dic['EBB'].values())
    # spline2_list = list(shots_sum_dic[o_team].values())
    spline1_list = []
    for min_, value in shots_sum_dic['EBB'].items():
        # set marker on graph if there was a goal in this min
        if min_ in goal_dic['EBB'].keys():
            if marker_prefix:
                # add bullet with number and player name
                # add logo
                spline1_list.append({'y' : value, 'marker' : {'enabled': 1, 'radius': marker_radius, 'symbol': 'circle'}, 'dataLabels': {'enabled': 1, 'color': '#030357', 'format': '{0}'.format(goal_dic['EBB'][min_])}})
            else:
                # add logo
                # spline1_list.append({'y' : value, 'marker' : {'enabled': 1, 'width': marker_width, 'height': marker_height, 'symbol': 'url({0})'.format(ebb_logo)}, 'dataLabels': {'y': -5, 'enabled': 1, 'color': '#030357', 'format': '{0}'.format(goal_dic['EBB'][min_])}})
                spline1_list.append({'y' : value, 'marker' : {'enabled': 1, 'width': marker_width, 'height': marker_height, 'symbol': 'url({0})'.format(ebb_logo)}})
        else:
            spline1_list.append(value)

    spline2_list = []
    for min_, value in shots_sum_dic[o_team].items():
        # set marker on graph if there was a goal in this min
        if min_ in goal_dic[o_team].keys():
            if marker_prefix:
                # add bullet with number and player name
                spline2_list.append({'y' : value, 'marker' : {'enabled': 1, 'radius': marker_radius, 'symbol': 'circle'}, 'dataLabels': {'y': 25, 'enabled': 1, 'color': '#68717a', 'format': '{0}'.format(goal_dic[o_team][min_])}})
            else:
                # add logo
                spline2_list.append({'y' : value, 'marker' : {'enabled': 1, 'width': marker_width, 'height': marker_height, 'symbol': 'url({0})'.format(o_team_logo)}})
        else:
            spline2_list.append(value)

    # max value for left y axis
    y1_max = max(bar1_list)
    if y1_max < max(bar2_list):
        y1_max = max(bar2_list)

    y2_max = max(list(shots_sum_dic['EBB'].values()))
    if y2_max < max(list(shots_sum_dic[o_team].values())):
        y2_max = max(list(shots_sum_dic[o_team].values()))

    if sog_filter:
        y1_text = 'Torschüsse pro Minute'
        y2_text = 'Torschüsse gesamt'
    else:
        y1_text = 'Schüsse pro Minute'
        y2_text = 'Schüsse gesamt'

    # calculate y2 maxium value
    y2_tick_interval = 20
    y2_max = math.ceil(y2_max/y2_tick_interval) * y2_tick_interval

    title = ''
    chart_options = {

        'chart': {
            'type': 'column',
            'height': '60%',
            'alignTicks': 0,
        },

        'exporting': {
            'chartOptions': {
                'plotOptions': {
                    'series': {
                        'dataLabels': {
                            'enabled': 0,
                        },
                    },
                },
            },
            'fallbackToExportServer': 0,
        },

        'title': {
            'text': title,
            'style': {'color': '#404040', 'font-size': '12px'},
        },

        'legend': {
            'enabled': show_legend,
            'useHTML': 1,
            'itemStyle': {'color': '#404040', 'font-size': label_size},
            'verticalAlign': v_align,
            'symbolRadius': 0,
        },

        'tooltip': {
            'shared': 1,
            'useHTML': 1,
            'headerFormat': '<b>{point.x}.Minute</b><br>',
        },

        'plotOptions': {
            'spline': {
                'marker': {
                    'enabled': 0,
                },
            },
        },

        'xAxis': {
            'categories': min_list,
            'title': {
                'text': 'Minute',
                'style': {'color': '#404040', 'font-size': label_size},
            },
            'labels': {'style': {'fontSize': label_size},},
            'tickInterval': 5,
            'showFirstLabel': 1,
            'showLastLabel': 1,
            'plotLines': [{
                'color': '#d8d9da',
                'width': 2,
                'value': 20,
            }, {
                'color': '#d8d9da',
                'width': 2,
                'value': 40,
            }, {
                'color': '#d8d9da',
                'width': 2,
                'value': 60,
            }],
            'plotBands': plotband_list,
        },

        'yAxis': [
            {
                'title': {
                    'text': y1_text,
                    'style': {'color': '#404040', 'font-size': label_size},
                },
                #'max': y1_max,
                'tickInterval': 1,
                'maxPadding': 0.1,
                'labels': {'style': {'fontSize': label_size},},
            }, {
                'title': {
                    'text': y2_text,
                    'style': {'color': '#030357', 'font-size': label_size},
                },
                'opposite': 1,
                # 'tickInterval': y2_tick_interval,
                'max': y2_max,
                # 'maxPadding': 0.1,
                'labels': {'style': {'fontSize': label_size},},},],

        'series': [{
            'name': 'EBB pro min',
            'data': bar1_list,
            'color': '#7cb5ec',
        }, {
            'name': '{0} pro min'.format(o_team),
            'data': bar2_list,
            'color': '#b0b3b5',
        }, {
            'type': 'spline',
            'name': 'EBB Sum',
            'data': spline1_list,
            'color': '#030357',
            'yAxis': 1,
            'zIndex': 3,
        }, {
            'type': 'spline',
            'name': '{0} Sum'.format(o_team),
            'data': spline2_list,
            'color': '#68717a',
            'yAxis': 1,
            'zIndex': 2,
        }, {
            'name': 'PP EBB',
            'color': '#e6e6fe',
            'marker': {'symbol': 'square'},
        }, {
            'name': 'EBB {0}'.format(o_team),
            'color': '#f1f2f3',
            'marker': {'symbol': 'square'},
        }]
    }

    return chart_options

def get_shots_stats(match_id, mobile_browser, marker_prefix=None):
    """ get shots statistics (blocked, missed, goal)  """

    # get last rfilter matches and filter match-id from first entry
    match_list = Match.objects.filter(id=match_id, no_bet=False).values('id', 'date', 'matchday', 'home_team__short_name', 'home_team__team_name', 'home_team__logo_url', 'guest_team__short_name', 'guest_team__team_name', 'guest_team__logo_url', 'shots', 'del_date')[:1]

    shot_chart = {}
    shot_table = {}

    if match_list:

        shot_dic = match_list[0]['shots']
        try:
            x_max = math.ceil(sorted(shot_dic['match']['shots'], key=lambda x: x['time'])[-1]['time']/60) + 1
        except BaseException:
            x_max = 61

        # get some figures we need later
        (ebb_logo, o_team, _o_team_name, o_team_logo, shot_min_dic, goal_dic, _home_match) = prep_shotstats(match_list, 'match_shot_resutl_id', x_max)
        if marker_prefix:
            mebb_logo = marker_prefix + ebb_logo
            mo_team_logo = marker_prefix + o_team_logo
        else:
            mebb_logo = ebb_logo
            mo_team_logo = o_team_logo

        if shot_dic:
            # we did not register OT
            ot_reg = None
            for shot in shot_dic['match']['shots']:
                # get min out of seconds
                min_ = math.ceil(shot['time']/60)
                # create additional entries if we are running overtime
                if min_ > 60 and ot_reg is None:
                    # now we registered OT
                    ot_reg = True
                    for val in range(61, 66):
                        for ele in range(1, 6):
                            shot_min_dic['EBB'][ele][val] = 0
                            shot_min_dic[o_team][ele][val] = 0

                # these are shots from EBB
                if shot['team_id'] == 3:
                    try:
                        shot_min_dic['EBB'][shot['match_shot_resutl_id']][min_] += 1
                    except BaseException:
                        pass
                    if shot['match_shot_resutl_id'] == 4:
                        goal_dic['EBB'][min_] = shot['last_name']
                else:
                    # these are ghe shots from the f*****
                    try:
                        shot_min_dic[o_team][shot['match_shot_resutl_id']][min_] += 1
                    except BaseException:
                        pass
                    if shot['match_shot_resutl_id'] == 4:
                        goal_dic[o_team][min_] = shot['last_name']

            # aggregate shots per min
            shot_sum_dic = {'EBB': {1:{}, 2:{}, 3:{}, 4:{}, 5:{}}, o_team: {1:{}, 2:{}, 3:{}, 4:{}, 5:{}}}

            for ele in range(1, 5):
                ebb_min_values = list(shot_min_dic['EBB'][ele].values())
                o_team_min_values = list(shot_min_dic[o_team][ele].values())
                for min_ in shot_min_dic['EBB'][ele]:
                    shot_sum_dic['EBB'][ele][min_] = sum(ebb_min_values[:min_])
                for min_ in shot_min_dic[o_team][ele]:
                    shot_sum_dic[o_team][ele][min_] = sum(o_team_min_values[:min_])

            # create chart
            shot_chart = create_shotstat_chart(shot_sum_dic, shot_min_dic, goal_dic, o_team, mebb_logo, mo_team_logo, mobile_browser)
            shot_table = create_shotstat_table(shot_min_dic)

    return(shot_chart, shot_table)

def create_shotstat_table(shot_min_dic):
    """ create shotstat table """

    table_dic = {'th': ['Schüsse p. Drittel', '1st', '2nd', '3rd', 'OT', 'Summe'], 'align': ['left', None, None, None, None, None], 'td': []}

    status_dic = {1: 'gehalten', 2: 'vorbei', 3: 'geblockt', 4: 'Tor'}
    # 1 - gehalten
    # 2 - vorbei
    # 3 - geblockt
    # 4 - goal

    for ele in (2, 3, 1, 4):
        sp1 = 0
        sp2 = 0
        sp3 = 0
        sot = 0
        for min_ in shot_min_dic['EBB'][ele]:
            if min_ < 21:
                sp1 += shot_min_dic['EBB'][ele][min_]
            elif min_ < 41:
                sp2 += shot_min_dic['EBB'][ele][min_]
            elif min_ < 61:
                sp3 += shot_min_dic['EBB'][ele][min_]
            else:
                sot += shot_min_dic['EBB'][ele][min_]
        table_dic['td'].append([status_dic[ele], sp1, sp2, sp3, sot, sp1+sp2+sp3+sot])

    return table_dic

def create_shotstat_chart(shots_sum_dic, _shot_min_dic, goal_dic, o_team, ebb_logo, o_team_logo, mobile_browser):
    """ create shotstat table """

    # we need to change some setting for mobile access
    if mobile_browser:
        marker_width = 15
        marker_height = 15
        label_size = '8px'
        show_legend = 1
        v_align = 'top'
    else:
        marker_width = 22
        marker_height = 22
        label_size = '10px'
        v_align = 'bottom'
        show_legend = 1

    min_list = list(shots_sum_dic['EBB'][1].keys())
    stack1_list = list(shots_sum_dic['EBB'][1].values())
    stack2_list = list(shots_sum_dic['EBB'][2].values())
    stack3_list = list(shots_sum_dic['EBB'][3].values())
    # stack4_list = list(shots_sum_dic['EBB'][4].values())
    stack4_list = []
    for min_, value in shots_sum_dic['EBB'][4].items():
        # set marker on graph if there was a goal in this min
        if min_ in goal_dic['EBB'].keys():
            stack4_list.append({'y' : value, 'marker' : {'enabled': 1, 'width': marker_width, 'height': marker_height, 'symbol': 'url({0})'.format(ebb_logo),}})
        elif min_ in goal_dic[o_team].keys():
            stack4_list.append({'y' : value, 'marker' : {'enabled': 1, 'width': marker_width, 'height': marker_height, 'symbol': 'url({0})'.format(o_team_logo),}})
        else:
            stack4_list.append(value)

    title = ''
    chart_options = {

        'chart': {
            'type': 'area',
            'height': '60%'
        },

        'exporting': {
            'chartOptions': {
                'plotOptions': {
                    'series': {
                        'dataLabels': {
                            'enabled': 0,
                        },
                    },
                },
            },
            'fallbackToExportServer': 0,
        },

        'title': {
            'text': title,
            'style': {'color': '#404040', 'font-size': '12px'},
        },

        'legend': {
            'enabled': show_legend,
            'useHTML': 1,
            'itemStyle': {'color': '#404040', 'font-size': label_size},
            'verticalAlign': v_align,
        },

        'tooltip': {
            'shared': 1,
            'useHTML': 1,
            'headerFormat': '<b>{point.x}.Minute</b><br>',
        },

        'plotOptions': {
            'area': {
                'marker': {
                    'enabled': 0,
                },
                'stacking': 'normal',
            },
        },

        'xAxis': {
            'categories': min_list,
            'title': {
                'text': 'Minute',
                'style': {'color': '#404040', 'font-size': label_size},
            },
            'labels': {'style': {'fontSize': label_size},},
            'tickInterval': 5,
            'showFirstLabel': 1,
            'showLastLabel': 1,
            'plotLines': [{
                'color': '#d8d9da',
                'width': 2,
                'value': 20,
            }, {
                'color': '#d8d9da',
                'width': 2,
                'value': 40,
            }, {
                'color': '#d8d9da',
                'width': 2,
                'value': 60,
            }],
        },

        'yAxis': [
            {
                'title': {
                    'text': 'Schüsse gesamt',
                    'style': {'color': '#404040', 'font-size': label_size},
                },
                'labels': {'style': {'fontSize': label_size},},
            },],

        'series': [{
            'name': 'vorbei',
            'data': stack2_list,
            'color': '#d8d9da',
        }, {
            'name': 'geblockt',
            'data': stack3_list,
            'color': '#000052',
        }, {
            'name': 'Tor',
            'data': stack4_list,
            'color': '#f01a29',
            'zIndex': 2,
        }, {
            'name': 'gehalten',
            'data': stack1_list,
            'color': '#7cb5ec',
        },]
    }
    return chart_options

def get_game_shotzone_stats(match_id, _mobile_browser, filter_goals=False):
    """ get shotzone statistics """

    # get last rfilter matches and filter match-id from first entry
    match_list = Match.objects.filter(id=match_id, no_bet=False).values('id', 'date', 'matchday', 'home_team__short_name', 'home_team__team_name', 'home_team__logo_url', 'guest_team__short_name', 'guest_team__team_name', 'guest_team__logo_url', 'shots', 'del_date')[:1]

    shot_zonesum_dic = {}
    shot_table = {}

    if match_list:

        # these are the shots
        shot_dic = match_list[0]['shots']

        if shot_dic:
            # get some figures we need later
            (ebb_logo, o_team, _o_team_name, o_team_logo, shot_zone_dic, _goal_dic, home_match) = prep_shotstats(match_list, 'pos_period')

            for shot in shot_dic['match']['shots']:
                # get min out of seconds
                min_ = math.ceil(shot['time']/60)
                # cornercase handling
                if min_ == 0:
                    min_ = 1
                period = math.ceil(min_/20)

                # currently under development
                z_name = get_zone_name(shot['coordinate_x'], shot['coordinate_y'])

                if shot['team_id'] == 3:
                    if filter_goals:
                        # filter goalshots
                        if shot['match_shot_resutl_id'] in (1, 4):
                            shot_zone_dic['EBB'][z_name][period] += 1
                    else:
                        shot_zone_dic['EBB'][z_name][period] += 1
                else:
                    if filter_goals:
                        # filter goalshots
                        if shot['match_shot_resutl_id'] in (1, 4):
                            shot_zone_dic[o_team][z_name][period] += 1
                    else:
                        shot_zone_dic[o_team][z_name][period] += 1

            # we already have the summary we need for the graph
            shot_zonesum_dic = prep_shotzone_sum(home_match, shot_zone_dic, shot_dic['match']['polygons'], ebb_logo, o_team, o_team_logo, filter_goals)
            shot_table = create_shotzone_table(shot_zone_dic, home_match)

    return(shot_zonesum_dic, shot_table)

def get_season_shotzone_stats(_match_id, _mobile_browser, match_list, filter_sog=False):
    """ get shotszone stats """

    shot_zone_dic = {
        'ebb': {'slot': {'count': 0}, 'left': {'count': 0}, 'right': {'count': 0}, 'blue_line': {'count': 0}, 'neutral_zone': {'count': 0}, 'behind_goal': {'count': 0}, 'sum': {'count': 0}},
        'others': {'slot': {'count': 0}, 'left': {'count': 0}, 'right': {'count': 0}, 'blue_line': {'count': 0}, 'neutral_zone': {'count': 0}, 'behind_goal': {'count': 0}, 'sum': {'count': 0}}
        }

    for match in match_list:
        if match['shots']:
            for shot in match['shots']['match']['shots']:
                # currently under development
                z_name = get_zone_name(shot['coordinate_x'], shot['coordinate_y'])

                if shot['team_id'] == 3:
                    if filter_sog:
                        # filter goalshots
                        if shot['match_shot_resutl_id'] in (1, 4):
                            shot_zone_dic['ebb'][z_name]['count'] += 1
                            shot_zone_dic['ebb']['sum']['count'] += 1
                    else:
                        shot_zone_dic['ebb'][z_name]['count'] += 1
                        shot_zone_dic['ebb']['sum']['count'] += 1
                else:
                    if filter_sog:
                        # filter goalshots
                        if shot['match_shot_resutl_id'] in (1, 4):
                            shot_zone_dic['others'][z_name]['count'] += 1
                            shot_zone_dic['others']['sum']['count'] += 1
                    else:
                        shot_zone_dic['others'][z_name]['count'] += 1
                        shot_zone_dic['others']['sum']['count'] += 1

    for team in shot_zone_dic:
        for zone in shot_zone_dic[team]:
            if shot_zone_dic[team]['sum']['count'] > 0:
                shot_zone_dic[team][zone]['roundpercent'] = round(shot_zone_dic[team][zone]['count'] / shot_zone_dic[team]['sum']['count'] * 100)
                # shot_zone_dic[team][zone]['roundpercent'] = round(shot_zone_dic[team][zone]['count'] / shot_zone_dic[team]['sum']['count'] * 100)
            else:
                shot_zone_dic[team][zone]['roundpercent'] = 0

    shot_zone_table = create_season_shotzone_table(shot_zone_dic)

    return (shot_zone_dic, shot_zone_table)

def create_season_shotzone_table(shot_zone_dic):
    """ create shotzone table """

    table_dic = {'th': ['Schuss-Zonen', 'EBB', '%', 'Others', '%'], 'align': ['left', None, None, None, None], 'td': []}

    slot_dic = {'behind_goal': 'Hinterm Tor',
                'left': 'Linker Flügel',
                'slot': 'Slot',
                'blue_line': 'Blaue Linie',
                'right': 'Rechter Flügel',
                'neutral_zone': 'Neutrale Zone'}

    slot_list = ('left', 'right', 'slot', 'blue_line', 'neutral_zone')

    for zone in slot_list:
        table_dic['td'].append([slot_dic[zone], shot_zone_dic['ebb'][zone]['count'], shot_zone_dic['ebb'][zone]['roundpercent'], shot_zone_dic['others'][zone]['count'], shot_zone_dic['others'][zone]['roundpercent']])

    return table_dic

def prep_shotzone_sum(_home_match, shot_zone_dic, _zone_dic, ebb_logo, _o_team, o_team_logo, _filter_goals):
    """ reformat zone statistics for template processing """

    shot_zonesum_dic = {'ebb': {'logo': ebb_logo}, 'oteam': {'logo': o_team_logo}}

    for team in shot_zone_dic:
        for zname in shot_zone_dic[team]:

            if team == 'EBB':
                tname = 'ebb'
            else:
                tname = 'oteam'

            if 'sum' not in shot_zonesum_dic[tname]:
                shot_zonesum_dic[tname]['sum'] = {}
                shot_zonesum_dic[tname]['sum']['count'] = 0
            if zname not in shot_zonesum_dic[tname]:
                shot_zonesum_dic[tname][zname] = {}
                shot_zonesum_dic[tname][zname]['count'] = 0
            for period in shot_zone_dic[team][zname]:
                shot_zonesum_dic[tname][zname]['count'] += shot_zone_dic[team][zname][period]
                shot_zonesum_dic[tname]['sum']['count'] += shot_zone_dic[team][zname][period]

    for team in shot_zonesum_dic:
        for zone in shot_zonesum_dic[team]:
            if zone != 'logo':
                # print(zone, shot_zonesum_dic[team][zone]['count'], shot_zonesum_dic[tname]['sum']['count'])
                if shot_zonesum_dic[team]['sum']['count'] > 0:
                    shot_zonesum_dic[team][zone]['roundpercent'] = round(shot_zonesum_dic[team][zone]['count'] / shot_zonesum_dic[team]['sum']['count'] * 100)
                else:
                    shot_zonesum_dic[team][zone]['roundpercent'] = 0

    # from pprint import pprint
    # pprint(shot_zonesum_dic)

    return shot_zonesum_dic

def prep_ticker(match_id, uts, mobile_browser):
    """ prepare ticker data """

    # get gamestatistics
    gamestat_dic = get_gamestats(match_id, mobile_browser)

    (update_date, title, ticker_list) = get_tickerstats(match_id, mobile_browser)

    # set update date
    d_update = None
    if update_date:
        if abs(uts - update_date) < 7200:
            d_update = datetime.datetime.fromtimestamp(update_date, tz=TIMEZONE).strftime('%d.%m.%y %H:%M')

    return(d_update, title, gamestat_dic, ticker_list)

def get_tickerstats(match_id, mobile_browser):
    """ get ticker data form DB """

    type_dic = {'periodStart': '{0}. Drittel beginnt', 'periodEnd': '{0}. Drittel beendet', 'penalty': 'Strafe', 'goal': 'Tor', 'goalkeeperChange': 'Torwartwechsel', 'timeout': 'Auszeit'}

    # get last rfilter matches and filter match-id from first entry
    match_list = Match.objects.filter(id=match_id, no_bet=False).values('id', 'date', 'matchday', 'home_team__short_name', 'home_team__team_name', 'home_team__logo_url', 'guest_team__short_name', 'guest_team__team_name', 'guest_team__logo_url', 'period_events', 'del_date')[:1]

    event_list = []
    d_update = None
    title = None

    if match_list:

        if mobile_browser:
            title = '{2}. Spieltag: {0} vs. {1}'.format(match_list[0]['home_team__short_name'], match_list[0]['guest_team__short_name'], match_list[0]['matchday'])
            home_team = match_list[0]['home_team__short_name']
            guest_team = match_list[0]['guest_team__short_name']
        else:
            title = '{2}. Spieltag: {0} vs. {1}'.format(match_list[0]['home_team__team_name'], match_list[0]['guest_team__team_name'], match_list[0]['matchday'])
            home_team = match_list[0]['home_team__team_name']
            guest_team = match_list[0]['guest_team__team_name']

        # team logos
        home_logo = match_list[0]['home_team__logo_url']

        guest_logo = match_list[0]['guest_team__logo_url']
        d_update = match_list[0]['del_date']

        # these are the shots
        event_dic = match_list[0]['period_events']

        for period in sorted(event_dic, reverse=True):

            if period == 'shootout':

                if event_dic[period]:
                    # virtual entry for penality shooting
                    evt = {}
                    evt['mtime'] = 65
                    evt['mtitle'] = 'Penaltyschiessen beendet'
                    evt['mcolor'] = 'ehc-grey-1'
                    # store event in list
                    event_list.append(evt)

                for event in sorted(event_dic[period], key=lambda x: x['data']['id'], reverse=True):
                    if event['type'] == 'shootout':
                        event['mtime'] = 65
                        if event['data']['scored']:
                            event['mtitle'] = 'Tor'
                            event['mcolor'] = 'ehc-red'
                        else:
                            event['mtitle'] = 'Verpasst'
                            event['mcolor'] = 'ehc-grey-1'
                        event['mspan'] = 'timelinebold'
                        event['minfo'] = event['data']['currentScore']
                        event['mdetail'] = '{0} {1} ({2})'.format(event['data']['scorer']['name'], event['data']['scorer']['surname'], event['data']['scorer']['jersey'])

                        if 'data' in event:
                            if 'team' in event['data']:
                                if event['data']['team'] == 'home':
                                    event['mlogo'] = home_logo
                                elif event['data']['team'] == 'visitor':
                                    event['mlogo'] = guest_logo

                        # store event in list
                        event_list.append(event)

                if event_dic[period]:
                    # virtual entry for penality shooting
                    evt = {}
                    evt['mtime'] = 65
                    evt['mtitle'] = 'Penaltyschiessen beginnt'
                    evt['mcolor'] = 'ehc-grey-1'
                    # store event in list
                    event_list.append(evt)

            elif event_dic[period]:
                for event in event_dic[period][::-1]:
                    event['mtime'] = math.ceil(event['time']/60)
                    event['mtitle'] = type_dic[event['type']].format(period)
                    if event['type'] == 'goal':
                        event['mcolor'] = 'ehc-red'
                        event['mspan'] = 'timelinebold'
                        event['minfo'] = event['data']['currentScore']
                        event['mdetail'] = '{0} {1} ({2})'.format(event['data']['scorer']['name'], event['data']['scorer']['surname'], event['data']['scorer']['jersey'])
                        event['mdetailinfo'] = []
                        for player in event['data']['assistants']:
                            event['mdetailinfo'].append('{0} {1} ({2})'.format(player['name'], player['surname'], player['jersey']))
                        # additional-details for goalchange
                        event['adddetailinfo_id'] = 't_{0}'.format(event['data']['id'])
                        event['adddetailinfo'] = get_goal_detailinfo(event, home_team, guest_team)

                    elif event['type'] == 'goalkeeperChange':
                        # thats complex stuff
                        event['mcolor'] = 'ehc-blue-1'
                        event['mspan'] = 'timelinebold'
                        if event['data']['player'] and event['data']['outgoingGoalkeeper']:
                            key_ = 'player'
                            event['mtitle'] = 'Torwartwechsel'
                        elif event['data']['player']:
                            key_ = 'player'
                            event['mtitle'] = 'Torwart'
                        elif event['data']['outgoingGoalkeeper']:
                            key_ = 'outgoingGoalkeeper'
                            event['mtitle'] = 'Torwart raus'
                        if key_:
                            event['mdetail'] = '{0} {1} ({2})'.format(event['data'][key_]['name'], event['data'][key_]['surname'], event['data'][key_]['jersey'])

                    elif event['type'] == 'penalty':
                        event['mcolor'] = 'ehc-grey-1'
                        event['mspan'] = 'timelinebold'
                        event['minfo'] = event['data']['codename']
                        if bool(event['data']['disciplined_bm']):
                            key_ = 'replacedPlayer'
                        else:
                            key_ = 'disciplinedPlayer'
                        event['mdetail'] = '{0} {1} ({2})'.format(event['data'][key_]['name'], event['data'][key_]['surname'], event['data'][key_]['jersey'])
                        event['mdetailinfo'] = []
                        event['mdetailinfo'].append('{0}min'.format(math.ceil(event['data']['duration']/60)))

                    elif event['type'] == 'periodStart' or  event['type'] == 'periodEnd':
                        event['mcolor'] = 'ehc-grey-1'
                        if period == 'overtime':
                            event['mtitle'] = event['mtitle'].replace('overtime. Drittel', 'Overtime')

                    elif event['type'] == 'timeout':
                        event['mspan'] = 'timelinebold'

                    else:
                        event['mcolor'] = 'ehc-grey-1'

                    if 'data' in event:
                        if 'team' in event['data']:
                            if event['data']['team'] == 'home':
                                event['mlogo'] = home_logo
                            elif event['data']['team'] == 'visitor':
                                event['mlogo'] = guest_logo

                    # store event in list
                    event_list.append(event)

    return (d_update, title, event_list)

def create_shotzone_table(shot_zone_dic, _home_match):
    """ create shotzone table """

    table_dic = {'th': ['Schuss-Zonen EBB', '1st', '2nd', '3rd', 'OT', 'Summe'], 'align': ['left', None, None, None, None, None], 'td': []}

    slot_dic = {'behind_goal': 'Hinterm Tor',
                'left': 'Linker Flügel',
                'slot': 'Slot',
                'blue_line': 'Blaue Linie',
                'right': 'Rechter Flügel',
                'neutral_zone': 'Neutrale Zone'}

    slot_list = ('left', 'right', 'slot', 'blue_line', 'neutral_zone')

    for pos in slot_list:
        tmp_list = [slot_dic[pos]]
        sum_ = 0
        for ele in (1, 2, 3, 4):
            tmp_list.append(shot_zone_dic['EBB'][pos][ele])
            sum_ += shot_zone_dic['EBB'][pos][ele]
        tmp_list.append(sum_)
        table_dic['td'].append(tmp_list)

    return table_dic

def get_goal_detailinfo(event, home_team, guest_team):
    """ addtional infos for goal """

    addinfo_list = []
    # addinfo_list.append({'data': event['data']['id']})

    if event['data']['team'] == 'home':
        _positive = home_team
        negative = guest_team
    else:
        _positive = guest_team
        negative = home_team

    # reverse list to have goalie at last
    for player in event['data']['attendants']['positive'][::-1]:

        pname = '{0} {1} ({2})'.format(player['name'], player['surname'], player['jersey'])

        show_ = True
        if pname == event['mdetail']:
            show_ = False
        elif pname in event['mdetailinfo']:
            show_ = False
        if show_:
            addinfo_list.append({'data': pname})
        # addinfo_list.append({'data': '{0} {1} ({2})'.format(player['name'], player['surname'], player['jersey'])})

    addinfo_list.append({'data': ''})

    # nagvite scores
    addinfo_list.append({'class': 'adddetailinfo', 'data': 'Spieler {0}'.format(negative)})
    # reverse list to have goalie at last
    for player in event['data']['attendants']['negative'][::-1]:
        addinfo_list.append({'data': '{0} {1} ({2})'.format(player['name'], player['surname'], player['jersey'])})

    return addinfo_list

def get_shots_per_player(match_id, mobile_browser):
    """ get shots per match per player """
    # get last rfilter matches and filter match-id from first entry
    match_list = Match.objects.filter(id=match_id, no_bet=False).values('id', 'date', 'matchday', 'home_team__short_name', 'home_team__team_name', 'home_team__logo_url', 'guest_team__short_name', 'guest_team__team_name', 'guest_team__logo_url', 'shots', 'top_scorers', 'del_date', 'roster')[:1]

    shot_table = {}
    shot_chart = {}

    if match_list:

        # these are the shots
        shot_dic = match_list[0]['shots']
        # these playerstats
        player_dic = match_list[0]['top_scorers']
        # roster information
        roster_list = match_list[0]['roster']
        home_team = match_list[0]['home_team__short_name']
        roster_dic = {}
        if home_team == 'EBB':
            key_ = 'home'
        else:
            key_ = 'visitor'

        if key_ in roster_list:
            for roster in roster_list[key_]:
                roster_dic[roster_list[key_][roster]['playerId']] = roster_list[key_][roster]['jersey']

        shots_per_payer_dic = {}
        if shot_dic and player_dic:
            # get some figures we need later
            # (ebb_logo, o_team, _o_team_name, o_team_logo, shot_player_dic, _goal_dic, home_match) = prep_shotstats(match_list, None)

            # lets go over the different players in dictionary
            for player in player_dic:
                if 'teamShortcut' in player:
                    # filter for EBB players with time on ICE
                    if player['teamShortcut'] == 'EBB' and player['timeOnIce'] > 0:
                        if player['playerId'] not in shots_per_payer_dic:
                            shots_per_payer_dic[player['playerId']] = {}
                        # store some data we need for later usage
                        shots_per_payer_dic[player['playerId']]['name'] = '{0} {1}'.format(player['name'], player['surname'])
                        # shorten name
                        shots_per_payer_dic[player['playerId']]['abbrname'] = '{0}. {1}'.format(player['name'][0], player['surname'])
                        shots_per_payer_dic[player['playerId']]['timeonice'] = player['timeOnIce']
                        # convert time on ice to mm:SS
                        shots_per_payer_dic[player['playerId']]['mmin'] = math.floor(player['timeOnIce']/60)
                        shots_per_payer_dic[player['playerId']]['mtimeonice'] = '{0}:{1}'.format(math.floor(player['timeOnIce']/60), player['timeOnIce'] % 60)
                        shots_per_payer_dic[player['playerId']]['goals'] = player['goals']
                        shots_per_payer_dic[player['playerId']]['shots'] = player['shots']
                        shots_per_payer_dic[player['playerId']]['assists'] = player['assists']
                        # store number from roster dic
                        shots_per_payer_dic[player['playerId']]['jersey'] = roster_dic[player['playerId']]
                        # initialize values we will get show from below interation (but if a player is not shooting it could fail
                        shots_per_payer_dic[player['playerId']]['sog'] = 0
                        shots_per_payer_dic[player['playerId']]['mshots'] = 0

            # check shots
            for shot in shot_dic['match']['shots']:
                # consider  shots from EBB players only
                if shot['player_id'] in shots_per_payer_dic:
                    if 'mshots' not in shots_per_payer_dic[shot['player_id']]:
                        shots_per_payer_dic[shot['player_id']]['mshots'] = 0
                        shots_per_payer_dic[shot['player_id']]['sog'] = 0
                    shots_per_payer_dic[shot['player_id']]['mshots'] += 1
                    if shot['match_shot_resutl_id'] in (1, 4):
                        shots_per_payer_dic[shot['player_id']]['sog'] += 1

            shot_chart = create_shosts_per_players_chart(shots_per_payer_dic, mobile_browser)
            shot_table = create_shots_per_player_table(shots_per_payer_dic, mobile_browser)
        else:
            shot_chart = {}
            shot_table = None

    return(shot_chart, shot_table)

def create_shosts_per_players_chart(shots_per_payer_dic, mobile_browser):
    """ create bubble chart for shots per player """

    # format data series in a way we need it
    data_list = {'shot': [], 'goal': [], 'assist': []}
    tmp_pos_dic = {}
    for player in sorted(shots_per_payer_dic.values(), key=lambda x: (x['goals'], x['assists'], -x['timeonice'])):
        tmp_dic = {
            'x': player['shots'],
            'y': player['sog'],
            'mx': player['shots'],
            'my': player['sog'],
            'z': player['mmin'],
            'name': player['abbrname'],
            'mtoi': player['mtimeonice'],
            'jersey': player['jersey'],
            'labelrank': 1,
            }

        # hack to fix bubble overlaps
        pos = '{0}:{1} '.format(player['shots'], player['sog'])
        if pos in tmp_pos_dic:
            tmp_dic['x'] += 0.5
            tmp_dic['y'] += 0.5
            tmp_pos_dic[pos] = '{0}:{1} '.format(tmp_dic['x'], tmp_dic['y'])
        else:
            tmp_pos_dic[pos] = 1

        if player['goals'] > 0:
            data_list['goal'].append(tmp_dic)
        elif player['assists'] > 0:
            data_list['assist'].append(tmp_dic)
        else:
            data_list['shot'].append(tmp_dic)

    # we need to change some setting for mobile access
    if mobile_browser:
        label_size = '8px'
        # show_legend = 1
        v_align = 'top'
    else:
        label_size = '10px'
        v_align = 'bottom'
        # show_legend = 1

    title = ''

    chart_options = {

        'chart': {
            'type': 'bubble',
            'plotBorderWidth': 1,
            'zoomType': 'xy',
            'height': '60%',
        },

        'exporting': {
            'chartOptions': {
                'plotOptions': {
                    'series': {
                        'dataLabels': {
                            'enabled': 0,
                        },
                    },
                },
            },
            'fallbackToExportServer': 0,
        },

        'legend': {
            'enabled': 1,
            'itemStyle': {'color': '#404040', 'font-size': label_size},
            'verticalAlign': v_align,
            'squareSymbol': 1,
        },

        'title': {
            'text': title,
        },

        'tooltip': {
            'useHTML': 1,
            'headerFormat': '<table class="w3-tiny">',
            'pointFormat': '<tr><td colspan="3"><b>{point.name} ({point.jersey})<b></td></tr>' +
                           '<tr><td>Schüsse:</td><td>{point.mx}</td></tr>' +
                           '<tr><td>Torschüsse:</td><td>{point.my}</td></tr>' +
                           '<tr><td>Eiszeit:</td><td>{point.mtoi}m</td></tr>',
            'footerFormat': '</table>',
            'followPointer': 1,
        },

        'plotOptions': {
            'series': {
                'dataLabels': {
                    'enabled': 1,
                    'color': '#000000',
                    'style': {'textShadow': 0, 'textOutline': 0, 'fontSize': label_size},
                    'format': '{point.jersey}',
                },
                # 'color': 'rgba(216, 217, 218, 6)',
                # 'borderWidth': 0,
                'color': 'rgba(189, 191, 193, 6)',
                'lineColor': '#c00c18',
            },
        },

        'xAxis': {
            'gridLineWidth': 1,
            'title': {
                'text': 'Anzahl Schüsse',
                'style': {'color': '#404040', 'font-size': label_size},
            },
            'labels': {'style': {'fontSize': label_size},},
            'min': 0,
            'tickInterval': 1,
            'showFirstLabel': 1,
            'showLastLabel': 1,
        },
        'yAxis': {
            'title': {
                'text': 'Anzahl Torschüsse',
                'style': {'color': '#404040', 'font-size': label_size},
            },
            'labels': {'style': {'fontSize': label_size},},
            'min': 0,
            'tickInterval': 2,
            'showFirstLabel': 1,
            'showLastLabel': 1,
        },

        'series': [
            {'name': 'Eiszeit', 'data': data_list['shot'], 'zIndex': 1},
            {'name': 'Torschütze', 'data': data_list['goal'], 'color': '#f01a29', 'zIndex': 4, 'marker': {'fillOpacity': 0.8}},
            {'name': 'Assist', 'data': data_list['assist'], 'color': '#7cb5ec', 'zIndex': 2, 'marker': {'fillOpacity': 0.8}}
            ],
    }
    return chart_options

def create_shots_per_player_table(shots_per_payer_dic, mobile_browser):
    """ create shotstat table """

    if mobile_browser:
        table_dic = {'th': ['Spieler', '#', 'Schüsse', 'Torsch.', 'Tore', 'A', 'Eiszeit'], 'align': ['left', None, None, None, None, None, None], 'td': []}
    else:
        table_dic = {'th': ['Spieler', 'Nummer', 'Schüsse', 'Torschüsse', 'Tore', 'Assists', 'Eiszeit'], 'align': ['left', None, None, None, None, None, None], 'td': []}

    for player in sorted(shots_per_payer_dic.values(), key=lambda x: x['shots'], reverse=True):
        table_dic['td'].append([player['name'], player['jersey'], player['shots'], player['sog'], player['goals'], player['assists'], player['mtimeonice']])
    return table_dic

def get_player_stat_chart(player_stat_list, data_dic, mobile_browser):
    """ create bubble chart for player stats """

    data_list = []
    tmp_pos_dic = {}
    for player in sorted(player_stat_list, key=lambda x: (x['points'], x['goals'])):
        if player['games_played'] > 0:
            # print(player['games_played'])
            tmp_dic = {
                'x': int(player[data_dic['x']]),
                'y': float(player[data_dic['y']]),
                'mx': int(player[data_dic['x']]),
                'my': float(player[data_dic['y']]),
                'z': int(player[data_dic['z']]),
                # 'z': int(player['goals']),
                'name': player['full_name'],
                'jersey': player['number'],
                'labelrank': 1,
                }
            # hack to fix bubble overlaps
            pos = '{0}:{1} '.format(tmp_dic['x'], tmp_dic['y'])
            if pos in tmp_pos_dic:
                tmp_dic['x'] += 0.5
                tmp_dic['y'] += 0.5
                tmp_pos_dic[pos] = '{0}:{1} '.format(tmp_dic['x'], tmp_dic['y'])
            else:
                tmp_pos_dic[pos] = 1

            data_list.append(tmp_dic)

    # we need to change some setting for mobile access
    if mobile_browser:
        label_size = '8px'
        # show_legend = 1
        v_align = 'top'
        min_size = 3
        max_size = 35
    else:
        label_size = '10px'
        v_align = 'bottom'
        min_size = 3
        max_size = 50
        # show_legend = 1

    title = ''

    chart_options = {

        'chart': {
            'type': 'bubble',
            'plotBorderWidth': 1,
            'zoomType': 'xy',
            'height': '60%',
        },

        'legend': {
            'enabled': 1,
            'itemStyle': {'color': '#404040', 'font-size': label_size},
            'verticalAlign': v_align,
            'squareSymbol': 1,
        },

        'title': {
            'text': title,
        },

        'exporting': {
            'chartOptions': {
                'plotOptions': {
                    'series': {
                        'dataLabels': {
                            'enabled': 0,
                        },
                    },
                },
            },
            'fallbackToExportServer': 0,
        },

        'tooltip': {
            'useHTML': 1,
            'headerFormat': '<table class="w3-tiny">',
            'pointFormat': '<tr><td colspan="3"><b>{point.name} ({point.jersey})<b></td></tr>' +
                           '<tr><td>' + data_dic['x_name'] + ':</td><td>{point.mx}</td></tr>' +
                           '<tr><td>' + data_dic['y_name'] + ':</td><td>{point.my}</td></tr>' +
                           '<tr><td>' + data_dic['z_name'] + ':</td><td>{point.z}</td></tr>',
            'footerFormat': '</table>',
            'followPointer': 1,
        },

        'plotOptions': {
            'series': {
                'dataLabels': {
                    'enabled': 1,
                    'color': '#000000',
                    'style': {'textShadow': 0, 'textOutline': 0, 'fontSize': label_size},
                    'format': '{point.jersey}',
                },
                'color': 'rgba(189, 191, 193, 6)',
                'lineColor': '#c00c18',
                # 'color': 'rgba(124, 181, 236, 6)',
                'borderWidth': 1,
            },
            'bubble': {
                'minSize': min_size,
                'maxSize': max_size,
            }
        },

        'xAxis': {
            'gridLineWidth': 1,
            'title': {
                'text': data_dic['x_name'],
                'style': {'color': '#404040', 'font-size': label_size},
            },
            'labels': {'style': {'fontSize': label_size},},
            'min': 0,
            'tickInterval': data_dic['x_tickint'],
            'showFirstLabel': 1,
            'showLastLabel': 1,
        },

        'yAxis': {
            'title': {
                'text': data_dic['y_name'],
                'style': {'color': '#404040', 'font-size': label_size},
            },
            'labels': {'style': {'fontSize': label_size},},
            # 'min': 0,
            'tickInterval': data_dic['y_tickint'],
            'showFirstLabel': 1,
            'showLastLabel': 1,
        },

        'series': [{
            'name': data_dic['z_name'],
            'data': data_list,
        },],
    }

    # a little bid of finetuning
    if data_dic['y'] == 'plus_minus':
        chart_options['yAxis']['plotLines'] = [{'color': '#d8d9da', 'width': 2, 'value': 0}]
    else:
        chart_options['yAxis']['min'] = 0

    return chart_options

def get_player_stat_list(u_season_id, tab_id=1):
    """ reformat playerstat list """

    tmp_player_stat_list = list(Playerstataggr.objects.filter(season_id=u_season_id).exclude(position__in=['GK', 'T']).values())

    # main sort criterias for list
    if tab_id == 2:
        prim_sort = 'goals'
    elif tab_id == 3:
        prim_sort = 'shots_on_goal'
    elif tab_id == 4:
        prim_sort = 'shots'
    elif tab_id == 5:
        prim_sort = 'time_on_ice_per_game_seconds'
    elif tab_id == 7:
        prim_sort = 'pim'
    elif tab_id == 8:
        prim_sort = 'time_on_ice_per_game_seconds'
    else:
        prim_sort = 'points'

    player_format_dic = {}
    player_stat_list = []

    pm_min = 0
    pm_max = 0

    season_player_corsi = {}
    if tab_id == 8:
        season_player_corsi = get_season_player_corsi(u_season_id)

    for player in sorted(tmp_player_stat_list, key=lambda x: (-x[prim_sort], -x['goals'])):

        # skip goalies / rewrite position
        if player['position'] in ('T', 'GK'):
            continue
        elif player['position'] == 'FO':
            player['position'] = 'S'
        elif player['position'] == 'DE':
            player['position'] = 'V'
        if player['shoots'] == 'left':
            player['shoots'] = 'L'
        else:
            player['shoots'] = 'R'

        # split flag strings
        img = player['flag'].split(';')
        del img[-1]
        player['flag'] = img

        # reformat plusminus
        player['plus_minus'] = '%.0f' % float(player['plus_minus'])

        # round some values
        player['shots_per_game'] = round(player['shots_per_game'], 1)
        player['shots_on_goal_per_game'] = round(player['shots_on_goal_per_game'], 1)
        player['time_on_ice_min'] = round(player['time_on_ice_seconds']/60, 0)
        player['time_on_ice_per_game_min'] = round(player['time_on_ice_per_game_seconds']/60, 0)
        player['time_on_ice_st_min'] = round((player['time_on_ice_pp_seconds'] + player['time_on_ice_sh_seconds'])/60, 0)
        player['time_on_ice_pp_min'] = round(player['time_on_ice_pp_seconds']/60, 0)
        player['time_on_ice_sh_min'] = round(player['time_on_ice_sh_seconds']/60, 0)
        player['st_points'] = player['pp_points'] + player['sh_points']

        # round percentage
        player['slot_on_goal_pctg'] = round(player['slot_on_goal_pctg'], 1)
        player['left_on_goal_pctg'] = round(player['left_on_goal_pctg'], 1)
        player['right_on_goal_pctg'] = round(player['right_on_goal_pctg'], 1)
        player['blue_line_on_goal_pctg'] = round(player['blue_line_on_goal_pctg'], 1)
        player['neutral_zone_on_goal_pctg'] = round(player['neutral_zone_on_goal_pctg'], 1)
        player['slot_shot_pctg'] = round(player['slot_shot_pctg'], 1)
        player['left_shot_pctg'] = round(player['left_shot_pctg'], 1)
        player['right_shot_pctg'] = round(player['right_shot_pctg'], 1)
        player['blue_line_shot_pctg'] = round(player['blue_line_shot_pctg'], 1)
        player['neutral_zone_shot_pctg'] = round(player['neutral_zone_shot_pctg'], 1)

        # add corsi informaition if available
        if player['player_id'] in season_player_corsi:
            player['cf_shots'] = season_player_corsi[player['player_id']]['cf_shots']
            player['ca_shots'] = season_player_corsi[player['player_id']]['ca_shots']
            player['cf_toi'] = season_player_corsi[player['player_id']]['cf_toi']
            player['cf_pctg'] = season_player_corsi[player['player_id']]['cf_pctg']
            player['cf_corsi'] = season_player_corsi[player['player_id']]['cf_corsi']

        # calculate min max
        if pm_max < float(player['plus_minus']):
            pm_max = float(player['plus_minus'])
        if pm_min > float(player['plus_minus']):
            pm_min = float(player['plus_minus'])

        # create entry in format dic to store html classes
        player_format_dic[player['number']] = {}
        for ele in player:
            # linethrough for players who are not active anymore
            if not player['active']:
                if ele not in player_format_dic[player['number']]:
                    player_format_dic[player['number']][ele] = 'linethrough'
                else:
                    player_format_dic[player['number']][ele] = '{0} linethrough'.format(player_format_dic[player['number']][ele])

        # put it into list
        player_stat_list.append(player)

    # color plus minus
    for player in player_stat_list:
        if float(player['plus_minus']) != 0:
            if float(player['plus_minus']) == pm_min:
                if 'plus_minus' not in player_format_dic[player['number']]:
                    player_format_dic[player['number']]['plus_minus'] = 'bgerror'
                else:
                    player_format_dic[player['number']]['plus_minus'] = '{0} bgerror'.format(player_format_dic[player['number']]['plus_minus'])
            elif float(player['plus_minus']) == pm_max:
                if 'plus_minus' not in player_format_dic[player['number']]:
                    player_format_dic[player['number']]['plus_minus'] = 'bgok'
                else:
                    player_format_dic[player['number']]['plus_minus'] = '{0} bgok'.format(player_format_dic[player['number']]['plus_minus'])

    pm_min = '%.0f' % pm_min
    pm_max = '%.0f' % pm_max

    return (player_stat_list, player_format_dic)

def get_goalie_stat_list(u_season_id, _tab_id=1):
    """ reformat goalie list """

    tmp_goalie_stat_list = list(Goaliestataggr.objects.filter(season_id=u_season_id).values())
    goalie_stat_list = []
    goalie_format_dic = {}

    for player in sorted(tmp_goalie_stat_list, key=lambda x: (-x['games_played'], -x['goals_against'])):

        # split flags
        img = player['flag'].split(';')
        del img[-1]
        player['flag'] = img

        # create entry in format dic to store html classes
        goalie_format_dic[player['number']] = {}

        for ele in player:
            # linethrough for players who are not active anymore
            if not player['active']:
                if ele not in goalie_format_dic[player['number']]:
                    goalie_format_dic[player['number']][ele] = 'linethrough'
                else:
                    goalie_format_dic[player['number']][ele] = '{0} linethrough'.format(goalie_format_dic[player['number']][ele])

            # round some values
            if ele.startswith('save_pctg_'):
                player[ele] = round(player[ele], 1)
                # highlight deviations
                add_class = compare_pctg(player[ele], player['save_pctg'])
                if add_class:
                    if ele not in goalie_format_dic[player['number']]:
                        goalie_format_dic[player['number']][ele] = add_class
                    else:
                        goalie_format_dic[player['number']][ele] = '{0} {1}'.format(goalie_format_dic[player['number']][ele], add_class)

        goalie_stat_list.append(player)

    return (goalie_stat_list, goalie_format_dic)

def compare_pctg(val_pctg, save_pctg):
    """ compare percentage and set flag in case of deviations """

    format_class = None
    threshold = 0.1

    if val_pctg and save_pctg:
        deviation = val_pctg/save_pctg - 1
        if deviation > threshold:
            format_class = 'bgok'
        elif deviation < threshold * -1:
            format_class = 'bgerror'

    return format_class

def add_classes_from_structure(table_structure, format_dic, tab_id):
    """ add formats from stat_structure into format dictionary """

    for player in table_structure:
        if tab_id == player['id']:
            for tr_ in player['structure']:
                if 'classtd' in tr_:
                    for number in format_dic:
                        if tr_['field'] in format_dic[number]:
                            format_dic[number][tr_['field']] = '{0} {1}'.format(format_dic[number][tr_['field']], tr_['classtd'])
                        else:
                            format_dic[number][tr_['field']] = tr_['classtd']

    return format_dic

def get_pstat_table_structure(mobile_browser):
    """ create table structure """
    # columns to display
    if mobile_browser:
        player_table_structure = [
            {
                'id': 1,
                'name': '# ',
                'icon': 'fa fa-lg fa-id-card',
                'structure': [
                    {'name': 'Name', 'field': 'full_name', 'classth': 'left', 'classtd': 'left'},
                    {'name': '', 'field': 'flag', 'type': 'imgflag',},
                    {'name': '#', 'field': 'number', 'tooltip': 'Nummer'},
                    {'name': '', 'field': 'contract_due', 'tooltip': 'Vertrag bis', 'img': {'src': '/static/img/money-w.png', 'width': 15, 'alt':'CONTRACT'}},
                    {'name': '', 'field': 'games_played', 'tooltip': 'Spiele', 'img': {'src': '/static/img/hockey.png', 'width': 15, 'alt':'GAMES'}},
                    {'name': '', 'field': 'goals', 'tooltip': 'Tore', 'img': {'src': '/static/img/goal.png', 'width': 15, 'alt':'TORE'}},
                    {'name': 'Pkt', 'field': 'points', 'tooltip': 'Punkte', 'classtd': 'score'},
                    {'name': '+/-', 'field': 'plus_minus', 'tooltip': 'Plus/Minus'}]},
            {
                'id': 2,
                'name': 'G',
                # 'img': {'src': '/static/img/goal.png', 'width': 18, 'alt':'TORE'},
                'structure': [
                    {'name': 'Name', 'field': 'full_name', 'classth': 'left', 'classtd': 'left'},
                    # {'name': '', 'field': 'flag', 'type': 'imgflag',},
                    {'name': '#', 'field': 'number', 'tooltip': 'Nummer'},
                    {'name': '', 'field': 'goals', 'tooltip': 'Tore', 'img': {'src': '/static/img/goal.png', 'width': 20, 'alt':'TORE'}, 'classtd': 'score'},
                    {'name': '', 'field': 'slot_goals', 'tooltip': 'aus dem Slot', 'icon': 'fa fa-lg fa-dot-circle-o'},
                    {'name': '', 'field': 'left_goals', 'tooltip': 'von Links', 'icon': 'fa fa-lg fa-arrow-circle-left'},
                    {'name': '', 'field': 'right_goals', 'tooltip': 'von Rechts', 'icon': 'fa fa-lg fa-arrow-circle-right'},
                    {'name': '-', 'field': 'blue_line_goals', 'tooltip': 'von der Blaue Linie'},
                    {'name': '', 'field': 'neutral_zone_goals', 'tooltip': 'aus der Neutrale Zone', 'icon': 'fa fa-lg fa-arrow-circle-down'},
                    {'name': 'GW', 'field': 'gw_goals', 'tooltip': 'Golden Goals'},
                    {'name': '', 'field': 'plus', 'tooltip': 'Plus', 'icon': 'fa fa-lg fa-plus-circle'},
                    {'name': '', 'field': 'minus', 'tooltip': 'Minus', 'icon': 'fa fa-lg fa-minus-circle'}]},
            {
                'id': 3,
                'name': 'SOG',
                'structure': [
                    {'name': 'Name', 'field': 'full_name', 'classth': 'left', 'classtd': 'left'},
                    # {'name': '', 'field': 'flag', 'type': 'imgflag',},
                    {'name': '#', 'field': 'number', 'tooltip': 'Nummer'},
                    {'name': 'SH%', 'field': 'shot_pctg', 'tooltip': 'Schussquote'},
                    {'name': 'SOG', 'field': 'shots_on_goal', 'tooltip': 'Torschüsse gesamt', 'classtd': 'score'},
                    {'name': '', 'field': 'slot_on_goal_pctg', 'tooltip': 'aus dem Slot %', 'icon': 'fa fa-lg fa-dot-circle-o'},
                    {'name': '', 'field': 'left_on_goal_pctg', 'tooltip': 'von Links %', 'icon': 'fa fa-lg fa-arrow-circle-left'},
                    {'name': '', 'field': 'right_on_goal_pctg', 'tooltip': 'von Rechts %', 'icon': 'fa fa-lg fa-arrow-circle-right'},
                    {'name': '-', 'field': 'blue_line_on_goal_pctg', 'tooltip': 'von der Blaue Linie %'},
                    {'name': '', 'field': 'neutral_zone_on_goal_pctg', 'tooltip': 'aus der Neutrale Zone %', 'icon': 'fa fa-lg fa-arrow-circle-down'}]},
            # {
            #    'id': 4,
            #    'name': 'S',
            #    'structure': [
            #        {'name': 'Name', 'field': 'full_name', 'classth': 'left', 'classtd': 'left'},
            #        # {'name': '', 'field': 'flag', 'type': 'imgflag',},
            #        {'name': '#', 'field': 'number', 'tooltip': 'Nummer'},
            #        {'name': 'S', 'field': 'shots', 'tooltip': 'Schüsse gesamt', 'classtd': 'score'},
            #        {'name': 'SPG', 'field': 'shots_per_game', 'tooltip': 'Schüsse pro Spiel'},
            #        {'name': '', 'field': 'slot_shot_pctg', 'tooltip': 'aus dem Slot %', 'icon': 'fa fa-lg fa-dot-circle-o'},
            #        {'name': '', 'field': 'left_shot_pctg', 'tooltip': 'von Links %', 'icon': 'fa fa-lg fa-arrow-circle-left'},
            #        {'name': '', 'field': 'right_shot_pctg', 'tooltip': 'von Rechts %', 'icon': 'fa fa-lg fa-arrow-circle-right'},
            #        {'name': '-', 'field': 'blue_line_shot_pctg', 'tooltip': 'von der Blaue Linie %'},
            #        {'name': '', 'field': 'neutral_zone_shot_pctg', 'tooltip': 'aus der Neutrale Zone %', 'icon': 'fa fa-lg fa-arrow-circle-down'}]},
            {
                'id': 5,
                'name': 'TOI',
                'icon': 'fa fa-lg fa-clock-o',
                'structure': [
                    {'name': 'Name', 'field': 'full_name', 'classth': 'left', 'classtd': 'left'},
                    # {'name': '', 'field': 'flag', 'type': 'imgflag',},
                    {'name': '#', 'field': 'number', 'tooltip': 'Nummer'},
                    {'name': 'TOI', 'field': 'time_on_ice', 'tooltip': 'Eiszeit gesamt'},
                    {'name': 'SHF', 'field': 'shifts', 'tooltip': 'Anzahl Wechsel'},
                    {'name': 'TOI/G', 'field': 'time_on_ice_per_game', 'tooltip': 'Eiszeit pro Spiel', 'classtd': 'score'},
                    {'name': 'SHF/G', 'field': 'shifts_per_game', 'tooltip': 'Wechsel pro Spiel'},
                    {'name': 'TPS', 'field': 'time_on_ice_per_shift', 'tooltip': 'Eiszeit pro Wechsel in s'}]},
            {
                'id': 6,
                'name': 'ST',
                'structure': [
                    {'name': 'Name', 'field': 'full_name', 'classth': 'left', 'classtd': 'left'},
                    # {'name': '', 'field': 'flag', 'type': 'imgflag',},
                    {'name': '#', 'field': 'number', 'tooltip': 'Nummer'},
                    {'name': 'PPG', 'field': 'pp_goals', 'tooltip': 'Powerplay Tore'},
                    {'name': 'PPA', 'field': 'pp_assists', 'tooltip': 'Powerplay Assists'},
                    {'name': 'PPP', 'field': 'pp_points', 'tooltip': 'Punkte im Powerplay'},
                    {'name': 'SHG', 'field': 'sh_goals', 'tooltip': 'Unterzahl Tore'},
                    {'name': 'SHA', 'field': 'sh_assists', 'tooltip': 'Unterzahl Assists'},
                    {'name': 'SHP', 'field': 'sh_points', 'tooltip': 'Punkte in Unterzahl'}]},
            {
                'id': 7,
                'name': 'PIM',
                'img': {'src': '/static/img/fist.png', 'width': 18, 'alt':'P'},
                'structure': [
                    {'name': 'Name', 'field': 'full_name', 'classth': 'left', 'classtd': 'left'},
                    # {'name': '', 'field': 'flag', 'type': 'imgflag',},
                    {'name': '#', 'field': 'number', 'tooltip': 'Nummer'},
                    {'name': 'P', 'field': 'penalties', 'tooltip': 'Anzahl Strafen'},
                    {'name': 'PIM', 'field': 'pim', 'tooltip': 'Strafminuten Gesamt', 'classtd': 'score'},
                    {'name': '2', 'field': '_2min', 'tooltip': 'Anzahl 2min Strafen'},
                    {'name': '5', 'field': '_5min', 'tooltip': 'Anzahl 5min Strafen'},
                    {'name': '10', 'field': '_10min', 'tooltip': 'Anzahl 10min Strafen'},
                    {'name': '20', 'field': '_20min', 'tooltip': 'Anzahl 20min Strafen'},
                    {'name': 'F', 'field': 'lazy', 'tooltip': 'wg. Faulheit (Beinstellen, Halten, Haken, Halten des Stocks, Behinderung, Stockschlag)'},
                    {'name': 'G', 'field': 'roughing', 'tooltip': 'wg. Härte (Übertriebene Härte, Unkorrekter Körperangriff, Bandencheck, Stockcheck, Faustkampf)'},
                    {'name': 'D', 'field': 'reckless', 'tooltip': 'wg. Dummheit (Hoher Stock, Ellbogencheck, Später Check, Check gegen den Kopf, Kniecheck, Check von hinten)'},
                    {'name': 'A', 'field': 'other', 'tooltip': 'andere (Werfen des Stocks, Unsportliches Verhalten, Spielverzögerung, Beschimpfung von Offiziellen, Verlassen der Strafbank, Schwalbe)'}]},
            {
                'id': 8,
                'name': 'CF',
                'structure': [
                    {'name': 'Name', 'field': 'full_name', 'classth': 'left', 'classtd': 'left'},
                    {'name': '', 'field': 'flag', 'type': 'imgflag',},
                    {'name': '#', 'field': 'number', 'tooltip': 'Nummer'},
                    {'name': 'CF 5v5', 'field': 'cf_shots', 'tooltip': 'Schüsse der Eisbären bei Spieler auf dem Eis'},
                    {'name': 'CA 5v5', 'field': 'ca_shots', 'tooltip': 'Schüsse der Gegner bei Spieler auf dem Eis'},
                    {'name': 'Corsi', 'field': 'cf_corsi', 'tooltip': 'Plus-/Minus-Bilanz aller Schüsse'},
                    {'name': 'CF% 5v5', 'field': 'cf_pctg', 'tooltip': 'Prozentuale Plus-/Minus-Bilanz aller Schüsse'},
                    {'name': 'TOI', 'field': 'time_on_ice', 'tooltip': 'Eiszeit', 'classtd': 'score'},
                    ]}
            ]

        goalie_table_structure = [
            {
                'id': 1,
                'name': 'Allgemein',
                'icon': 'fa fa-lg fa-id-card',
                'structure': [
                    {'name': 'Name', 'field': 'full_name', 'classth': 'left', 'classtd': 'left'},
                    {'name': '', 'field': 'flag', 'type': 'imgflag',},
                    {'name': '#', 'field': 'number', 'tooltip': 'Nummer'},
                    {'name': '', 'field': 'weight', 'tooltip': 'Gewicht', 'icon': 'fa fa-lg fa-balance-scale'},
                    {'name': '', 'field': 'contract_due', 'tooltip': 'Vertrag bis', 'img': {'src': '/static/img/money-w.png', 'width': 20, 'alt':'CONTRACT'}},
                    {'name': '', 'field': 'games_played', 'tooltip': 'Spiele', 'img': {'src': '/static/img/hockey.png', 'width': 20, 'alt':'GAMES'}},
                    {'name': '', 'field': 'goals_against', 'tooltip': 'Gegentore', 'img': {'src': '/static/img/goal.png', 'width': 15, 'alt':'TORE'}},
                    {'name': 'GAA', 'field': 'gaa', 'tooltip': 'Gegentorschnitt pro Spiel'},
                    {'name': 'SV%', 'field': 'save_pctg', 'tooltip': 'Fangquote in %', 'classtd': 'score'},
                    {'name': 'SO', 'field': 'so', 'tooltip': 'Shotouts'}]},
            {
                'id': 2,
                'name': 'Gegentore pro Zone',
                'img': {'src': '/static/img/goal.png', 'width': 18, 'alt':'TORE'},
                'structure': [
                    {'name': 'Name', 'field': 'full_name', 'classth': 'left', 'classtd': 'left'},
                    {'name': '#', 'field': 'number', 'tooltip': 'Nummer'},
                    {'name': '', 'field': 'goals_against', 'tooltip': 'Gegentore', 'img': {'src': '/static/img/goal.png', 'width': 15, 'alt':'TORE'}, 'classtd': 'score'},
                    {'name': '', 'field': 'ga_slot', 'tooltip': 'aus dem Slot', 'icon': 'fa fa-lg fa-dot-circle-o'},
                    {'name': '', 'field': 'ga_left', 'tooltip': 'von Links', 'icon': 'fa fa-lg fa-arrow-circle-left'},
                    {'name': '', 'field': 'ga_right', 'tooltip': 'von Rechts', 'icon': 'fa fa-lg fa-arrow-circle-right'},
                    {'name': '-', 'field': 'ga_blue_line', 'tooltip': 'von der Blaue Linie'},
                    {'name': '', 'field': 'ga_neutral_zone', 'tooltip': 'aus der Neutrale Zone', 'icon': 'fa fa-lg fa-arrow-circle-down'},
                    {'name': 'GAA', 'field': 'gaa', 'tooltip': 'Gegentorschnitt pro Spiel'}]},
            {
                'id': 3,
                'name': 'Saves pro Zone',
                'img': {'src': '/static/img/goalie.png', 'width': 18, 'alt':'TORE'},
                'structure': [
                    {'name': 'Name', 'field': 'full_name', 'classth': 'left', 'classtd': 'left'},
                    {'name': '#', 'field': 'number', 'tooltip': 'Nummer'},
                    {'name': 'SV%', 'field': 'save_pctg', 'tooltip': 'Fangquote in %', 'classtd': 'score'},
                    {'name': 'S%', 'field': 'save_pctg_slot', 'tooltip': 'SV Slot %'},
                    {'name': 'L%', 'field': 'save_pctg_left', 'tooltip': 'SV Links %'},
                    {'name': 'R%', 'field': 'save_pctg_right', 'tooltip': 'SV Rechts %'},
                    {'name': 'B%', 'field': 'save_pctg_blue_line', 'tooltip': 'SV BL %'},
                    {'name': 'N%', 'field': 'save_pctg_neutral_zone', 'tooltip': 'SV Rückraum %'}]},
            {
                'id': 4,
                'name': 'SV',
                'structure': [
                    {'name': 'Name', 'field': 'full_name', 'classth': 'left', 'classtd': 'left'},
                    {'name': '#', 'field': 'number', 'tooltip': 'Nummer'},
                    {'name': 'SV%', 'field': 'save_pctg', 'tooltip': 'Fangquote in %', 'classtd': 'score'},
                    {'name': 'S5v5', 'field': 'sa_5v5', 'tooltip': 'Torschüsse 5 gegen 5'},
                    {'name': '%', 'field': 'save_pctg_5v5', 'tooltip': 'Fangquote 5v5 %'},
                    {'name': 'S4v4', 'field': 'sa_4v4', 'tooltip': 'Torschüsse 4 gegen 4'},
                    {'name': '%', 'field': 'save_pctg_4v4', 'tooltip': 'Fangquote 4v4 %'},
                    {'name': 'S3v3', 'field': 'sa_3v3', 'tooltip': 'Torschüsse 3 gegen 3'},
                    {'name': '%', 'field': 'save_pctg_3v3', 'tooltip': 'Fangquote 3v3 %'}]},
            {
                'id': 5,
                'name': 'SV UZ',
                'structure': [
                    {'name': 'Name', 'field': 'full_name', 'classth': 'left', 'classtd': 'left'},
                    {'name': '#', 'field': 'number', 'tooltip': 'Nummer'},
                    {'name': 'SV%', 'field': 'save_pctg', 'tooltip': 'Fangquote in %', 'classtd': 'score'},
                    {'name': '4v5', 'field': 'sa_4v5', 'tooltip': 'Torschüsse 4 gegen 5'},
                    {'name': '%', 'field': 'save_pctg_4v5', 'tooltip': 'Fangquote 4v5 %'},
                    {'name': '3v5', 'field': 'sa_3v5', 'tooltip': 'Torschüsse 3 gegen 5'},
                    {'name': '%', 'field': 'save_pctg_3v5', 'tooltip': 'Fangquote 3v5 %'},
                    {'name': '3v4', 'field': 'sa_3v4', 'tooltip': 'Torschüsse 3 gegen 4'},
                    {'name': '%', 'field': 'save_pctg_3v4', 'tooltip': 'Fangquote 3v4 %'}]},
            {
                'id': 6,
                'name': 'SV ÜZ',
                'structure': [
                    {'name': 'Name', 'field': 'full_name', 'classth': 'left', 'classtd': 'left'},
                    {'name': '#', 'field': 'number', 'tooltip': 'Nummer'},
                    {'name': 'SV%', 'field': 'save_pctg', 'tooltip': 'Fangquote in %', 'classtd': 'score'},
                    {'name': '5v4', 'field': 'sa_5v4', 'tooltip': 'Torschüsse 5 gegen 4'},
                    {'name': '%', 'field': 'save_pctg_5v4', 'tooltip': 'Fangquote 5v4 %'},
                    {'name': '5v3', 'field': 'sa_5v3', 'tooltip': 'Torschüsse 5 gegen 3'},
                    {'name': '%', 'field': 'save_pctg_5v3', 'tooltip': 'Fangquote 5v3 %'},
                    {'name': '4v3', 'field': 'sa_4v3', 'tooltip': 'Torschüsse 4 gegen 3'},
                    {'name': '%', 'field': 'save_pctg_4v3', 'tooltip': 'Fangquote 4v3 %'}]}]

    else:
        player_table_structure = [
            {
                'id': 1,
                'name': 'Allgemein',
                'structure': [
                    {'name': 'Name', 'field': 'full_name', 'classth': 'left', 'classtd': 'left'},
                    {'name': '', 'field': 'flag', 'type': 'imgflag',},
                    {'name': '#', 'field': 'number', 'tooltip': 'Nummer'},
                    {'name': '', 'field': 'weight', 'tooltip': 'Gewicht', 'icon': 'fa fa-lg fa-balance-scale'},
                    {'name': '', 'field': 'contract_due', 'tooltip': 'Vertrag bis', 'img': {'src': '/static/img/money-w.png', 'width': 20, 'alt':'CONTRACT'}},
                    {'name': 'POS', 'field': 'position', 'tooltip': 'Position'},
                    {'name': 'SH', 'field': 'shoots', 'tooltip': 'Links/Rechts'},
                    {'name': '', 'field': 'games_played', 'tooltip': 'Spiele', 'img': {'src': '/static/img/hockey.png', 'width': 20, 'alt':'GAMES'}},
                    {'name': '', 'field': 'goals', 'tooltip': 'Tore', 'img': {'src': '/static/img/goal.png', 'width': 20, 'alt':'TORE'}},
                    {'name': 'A', 'field': 'assists', 'tooltip': 'Assists'},
                    {'name': 'Pkt', 'field': 'points', 'tooltip': 'Punkte', 'classtd': 'score'},
                    {'name': '', 'field': 'pim', 'tooltip': 'Strafminuten', 'img': {'src': '/static/img/fist.png', 'width': 20, 'alt':'P'}},
                    {'name': 'SOG', 'field': 'shots_on_goal', 'tooltip': 'Torschüsse'},
                    {'name': 'TOI', 'field': 'time_on_ice', 'tooltip': 'Eiszeit'},
                    {'name': '+/-', 'field': 'plus_minus', 'tooltip': 'Plus/Minus', 'classtd': 'right'}]},
            {
                'id': 2,
                'name': 'Tore',
                'structure': [
                    {'name': 'Name', 'field': 'full_name', 'classth': 'left', 'classtd': 'left'},
                    {'name': '', 'field': 'flag', 'type': 'imgflag',},
                    {'name': '#', 'field': 'number', 'tooltip': 'Nummer'},
                    {'name': '', 'field': 'goals', 'tooltip': 'Tore gesamt', 'img': {'src': '/static/img/goal.png', 'width': 20, 'alt':'TORE'}, 'classtd': 'score'},
                    {'name': '', 'field': 'slot_goals', 'tooltip': 'aus dem Slot', 'icon': 'fa fa-lg fa-dot-circle-o'},
                    {'name': '', 'field': 'left_goals', 'tooltip': 'von Links', 'icon': 'fa fa-lg fa-arrow-circle-left'},
                    {'name': '', 'field': 'right_goals', 'tooltip': 'von Rechts', 'icon': 'fa fa-lg fa-arrow-circle-right'},
                    {'name': '-', 'field': 'blue_line_goals', 'tooltip': 'von der Blaue Linie'},
                    {'name': '', 'field': 'neutral_zone_goals', 'tooltip': 'aus der Neutrale Zone', 'icon': 'fa fa-lg fa-arrow-circle-down'},
                    {'name': 'GWG', 'field': 'gw_goals', 'tooltip': 'Golden Goals'},
                    {'name': '', 'field': 'plus', 'tooltip': 'Plus', 'icon': 'fa fa-lg fa-plus-circle'},
                    {'name': '', 'field': 'minus', 'tooltip': 'Minus', 'icon': 'fa fa-lg fa-minus-circle'},
                    {'name': '+/-', 'field': 'plus_minus', 'tooltip': 'Plus/Minus', 'classtd': 'right'}]},
            {
                'id': 3,
                'name': 'Torschüsse',
                'structure': [
                    {'name': 'Name', 'field': 'full_name', 'classth': 'left', 'classtd': 'left'},
                    {'name': '', 'field': 'flag', 'type': 'imgflag',},
                    {'name': '#', 'field': 'number', 'tooltip': 'Nummer'},
                    {'name': 'SOG', 'field': 'shots_on_goal', 'tooltip': 'Torschüsse gesamt', 'classtd': 'score'},
                    {'name': 'SH%', 'field': 'shot_pctg', 'tooltip': 'Schussquote'},
                    {'name': '', 'field': 'slot_on_goal', 'tooltip': 'aus dem Slot', 'icon': 'fa fa-lg fa-dot-circle-o'},
                    {'name': '%', 'field': 'slot_on_goal_pctg', 'tooltip': 'Slot Prozent'},
                    {'name': '', 'field': 'left_on_goal', 'tooltip': 'von Links', 'icon': 'fa fa-lg fa-arrow-circle-left'},
                    {'name': '%', 'field': 'left_on_goal_pctg', 'tooltip': 'Links Prozent'},
                    {'name': '', 'field': 'right_on_goal', 'tooltip': 'von Rechts', 'icon': 'fa fa-lg fa-arrow-circle-right'},
                    {'name': '%', 'field': 'right_on_goal_pctg', 'tooltip': 'Rechts Prozent'},
                    {'name': '-', 'field': 'blue_line_on_goal', 'tooltip': 'von der Blaue Linie'},
                    {'name': '%', 'field': 'blue_line_on_goal_pctg', 'tooltip': 'BL Prozent'},
                    {'name': '', 'field': 'neutral_zone_on_goal', 'tooltip': 'aus der Neutrale Zone', 'icon': 'fa fa-lg fa-arrow-circle-down'},
                    {'name': '%', 'field': 'neutral_zone_on_goal_pctg', 'tooltip': 'Rückraum Prozent'}]},
            {
                'id': 4,
                'name': 'Schüsse',
                'structure': [
                    {'name': 'Name', 'field': 'full_name', 'classth': 'left', 'classtd': 'left'},
                    {'name': '', 'field': 'flag', 'type': 'imgflag',},
                    {'name': '#', 'field': 'number', 'tooltip': 'Nummer'},
                    {'name': 'S', 'field': 'shots', 'tooltip': 'Schüsse gesamt', 'classtd': 'score'},
                    {'name': 'SPG', 'field': 'shots_per_game', 'tooltip': 'Schüsse pro Spiel'},
                    {'name': '', 'field': 'slot_shots', 'tooltip': 'aus dem Slot', 'icon': 'fa fa-lg fa-dot-circle-o'},
                    {'name': '%', 'field': 'slot_shot_pctg', 'tooltip': 'Slot Prozent'},
                    {'name': '', 'field': 'left_shots', 'tooltip': 'von Links', 'icon': 'fa fa-lg fa-arrow-circle-left'},
                    {'name': '%', 'field': 'left_shot_pctg', 'tooltip': 'Links Prozent'},
                    {'name': '', 'field': 'right_shots', 'tooltip': 'von Rechts', 'icon': 'fa fa-lg fa-arrow-circle-right'},
                    {'name': '%', 'field': 'right_shot_pctg', 'tooltip': 'Rechts Prozent'},
                    {'name': '-', 'field': 'blue_line_shots', 'tooltip': 'von der Blaue Linie'},
                    {'name': '%', 'field': 'blue_line_shot_pctg', 'tooltip': 'BL Prozent'},
                    {'name': '', 'field': 'neutral_zone_shots', 'tooltip': 'aus der Neutrale Zone', 'icon': 'fa fa-lg fa-arrow-circle-down'},
                    {'name': '%', 'field': 'neutral_zone_shot_pctg', 'tooltip': 'Rückraum Prozent'}]},
            {
                'id': 5,
                'name': 'Eiszeit',
                'structure': [
                    {'name': 'Name', 'field': 'full_name', 'classth': 'left', 'classtd': 'left'},
                    {'name': '', 'field': 'flag', 'type': 'imgflag',},
                    {'name': '#', 'field': 'number', 'tooltip': 'Nummer'},
                    {'name': 'TOI', 'field': 'time_on_ice', 'tooltip': 'Eiszeit gesamt'},
                    {'name': 'TOIPP', 'field': 'time_on_ice_pp', 'tooltip': 'Eiszeit Powerplay'},
                    {'name': 'TOISH', 'field': 'time_on_ice_sh', 'tooltip': 'Eiszeit Unterzahl'},
                    {'name': 'SHF', 'field': 'shifts', 'tooltip': 'Anzahl Wechsel'},
                    {'name': 'TOI/G', 'field': 'time_on_ice_per_game', 'tooltip': 'Eiszeit pro Spiel', 'classtd': 'score'},
                    {'name': 'TOIPP/G', 'field': 'time_on_ice_pp_per_game', 'tooltip': 'Eiszeit Powerplay pro Spiel'},
                    {'name': 'TOISH/G', 'field': 'time_on_ice_sh_per_game', 'tooltip': 'Eiszeit Unterzahl pro Spiel'},
                    {'name': 'SHF/G', 'field': 'shifts_per_game', 'tooltip': 'Wechsel pro Spiel'},
                    {'name': 'TPS', 'field': 'time_on_ice_per_shift', 'tooltip': 'Eiszeit pro Wechsel in s'}]},
            {
                'id': 6,
                'name': 'ÜZ/UZ',
                'structure': [
                    {'name': 'Name', 'field': 'full_name', 'classth': 'left', 'classtd': 'left'},
                    {'name': '', 'field': 'flag', 'type': 'imgflag',},
                    {'name': '#', 'field': 'number', 'tooltip': 'Nummer'},
                    {'name': 'TOIPP', 'field': 'time_on_ice_pp', 'tooltip': 'Eiszeit Powerplay'},
                    {'name': 'PPG', 'field': 'pp_goals', 'tooltip': 'Powerplay Tore'},
                    {'name': 'PPA', 'field': 'pp_assists', 'tooltip': 'Powerplay Assists'},
                    {'name': 'PPP', 'field': 'pp_points', 'tooltip': 'Punkte im Powerplay'},
                    {'name': 'TOISH', 'field': 'time_on_ice_sh', 'tooltip': 'Eiszeit Unterzahl'},
                    {'name': 'SHG', 'field': 'sh_goals', 'tooltip': 'Unterzahl Tore'},
                    {'name': 'SHA', 'field': 'sh_assists', 'tooltip': 'Unterzahl Assists'},
                    {'name': 'SHP', 'field': 'sh_points', 'tooltip': 'Punkte in Unterzahl'},
                    {'name': 'GWG', 'field': 'gw_goals', 'tooltip': 'Golden Goals'}]},
            {
                'id': 7,
                'name': 'Strafen',
                'structure': [
                    {'name': 'Name', 'field': 'full_name', 'classth': 'left', 'classtd': 'left'},
                    {'name': '', 'field': 'flag', 'type': 'imgflag',},
                    {'name': '#', 'field': 'number', 'tooltip': 'Nummer'},
                    {'name': 'P', 'field': 'penalties', 'tooltip': 'Anzahl Strafen'},
                    {'name': 'PIM', 'field': 'pim', 'tooltip': 'Strafminuten Gesamt', 'classtd': 'score'},
                    {'name': '2min', 'field': '_2min', 'tooltip': 'Anzahl 2min Strafen'},
                    {'name': '5min', 'field': '_5min', 'tooltip': 'Anzahl 5min Strafen'},
                    {'name': '10min', 'field': '_10min', 'tooltip': 'Anzahl 10min Strafen'},
                    {'name': '20min', 'field': '_20min', 'tooltip': 'Anzahl 20min Strafen'},
                    {'name': 'Faul', 'field': 'lazy', 'tooltip': 'Beinstellen, Halten, Haken, Halten des Stocks, Behinderung, Stockschlag'},
                    {'name': 'Grob', 'field': 'roughing', 'tooltip': 'Übertriebene Härte, Unkorrekter Körperangriff, Bandencheck, Stockcheck, Faustkampf'},
                    {'name': 'Dumm', 'field': 'reckless', 'tooltip': 'Hoher Stock, Ellbogencheck, Später Check, Check gegen den Kopf, Kniecheck, Check von hinten'},
                    {'name': 'Andere', 'field': 'other', 'tooltip': 'Werfen des Stocks, Unsportliches Verhalten, Spielverzögerung, Beschimpfung von Offiziellen, Verlassen der Strafbank, Schwalbe'}]},
            {
                'id': 8,
                'name': 'Corsi',
                'structure': [
                    {'name': 'Name', 'field': 'full_name', 'classth': 'left', 'classtd': 'left'},
                    {'name': '', 'field': 'flag', 'type': 'imgflag',},
                    {'name': '#', 'field': 'number', 'tooltip': 'Nummer'},
                    {'name': 'CF 5v5', 'field': 'cf_shots', 'tooltip': 'Schüsse der Eisbären bei Spieler auf dem Eis'},
                    {'name': 'CA 5v5', 'field': 'ca_shots', 'tooltip': 'Schüsse der Gegner bei Spieler auf dem Eis'},
                    {'name': 'Corsi', 'field': 'cf_corsi', 'tooltip': 'Plus-/Minus-Bilanz aller Schüsse'},
                    {'name': 'CF% 5v5', 'field': 'cf_pctg', 'tooltip': 'Prozentuale Plus-/Minus-Bilanz aller Schüsse'},
                    {'name': 'TOI', 'field': 'time_on_ice', 'tooltip': 'Eiszeit', 'classtd': 'score'},
                    ]
            }]

        goalie_table_structure = [
            {
                'id': 1,
                'name': 'Allgemein',
                'structure': [
                    {'name': 'Name', 'field': 'full_name', 'classth': 'left', 'classtd': 'left'},
                    {'name': '', 'field': 'flag', 'type': 'imgflag',},
                    {'name': '#', 'field': 'number', 'tooltip': 'Nummer'},
                    {'name': '', 'field': 'weight', 'tooltip': 'Gewicht', 'icon': 'fa fa-lg fa-balance-scale'},
                    {'name': '', 'field': 'contract_due', 'tooltip': 'Vertrag bis', 'img': {'src': '/static/img/money-w.png', 'width': 20, 'alt':'CONTRACT'}},
                    {'name': '', 'field': 'games_played', 'tooltip': 'Spiele', 'img': {'src': '/static/img/hockey.png', 'width': 20, 'alt':'GAMES'}},
                    {'name': 'MIP', 'field': 'mip', 'tooltip': 'Spielminuten'},
                    {'name': 'MIP%', 'field': 'number', 'tooltip': 'Spielminuten %'},
                    {'name': '', 'field': 'goals_against', 'tooltip': 'Gegentore', 'img': {'src': '/static/img/goal.png', 'width': 15, 'alt':'TORE'}},
                    {'name': 'GAPP', 'field': 'ga_pp', 'tooltip': 'Gegentore bei eigener Unterzahl'},
                    {'name': 'GASH', 'field': 'ga_sh', 'tooltip': 'Gegentore bei eigener Überzahl'},
                    {'name': 'GAA', 'field': 'gaa', 'tooltip': 'Gegentorschnitt pro Spiel'},
                    {'name': 'SOG', 'field': 'shots_against', 'tooltip': 'Torschüsse'},
                    {'name': 'SA', 'field': 'saves', 'tooltip': 'Saves'},
                    {'name': 'SV%', 'field': 'save_pctg', 'tooltip': 'Fangquote in %', 'classtd': 'score'},
                    {'name': 'SO', 'field': 'so', 'tooltip': 'Shotouts'}]},
            {
                'id': 2,
                'name': 'Gegentore pro Zone',
                'structure': [
                    {'name': 'Name', 'field': 'full_name', 'classth': 'left', 'classtd': 'left'},
                    {'name': '', 'field': 'flag', 'type': 'imgflag',},
                    {'name': '#', 'field': 'number', 'tooltip': 'Nummer'},
                    {'name': '', 'field': 'goals_against', 'tooltip': 'Gegentore', 'img': {'src': '/static/img/goal.png', 'width': 15, 'alt':'TORE'}, 'classtd': 'score'},
                    {'name': '', 'field': 'ga_slot', 'tooltip': 'aus dem Slot', 'icon': 'fa fa-lg fa-dot-circle-o'},
                    {'name': '%', 'field': 'ga_slot_pctg', 'tooltip': 'Slot Prozent'},
                    {'name': '', 'field': 'ga_left', 'tooltip': 'von Links', 'icon': 'fa fa-lg fa-arrow-circle-left'},
                    {'name': '%', 'field': 'ga_left_pctg', 'tooltip': 'Links Prozent'},
                    {'name': '', 'field': 'ga_right', 'tooltip': 'von Rechts', 'icon': 'fa fa-lg fa-arrow-circle-right'},
                    {'name': '%', 'field': 'ga_right_pctg', 'tooltip': 'Rechts Prozent'},
                    {'name': '-', 'field': 'ga_blue_line', 'tooltip': 'von der Blaue Linie'},
                    {'name': '%', 'field': 'ga_blue_pctg', 'tooltip': 'BL Prozent'},
                    {'name': '', 'field': 'ga_neutral_zone', 'tooltip': 'aus der Neutrale Zone', 'icon': 'fa fa-lg fa-arrow-circle-down'},
                    {'name': '%', 'field': 'ga_neutral_pctg', 'tooltip': 'Rückraum Prozent'}]},
            {
                'id': 3,
                'name': 'Saves pro Zone',
                'structure': [
                    {'name': 'Name', 'field': 'full_name', 'classth': 'left', 'classtd': 'left'},
                    {'name': '', 'field': 'flag', 'type': 'imgflag',},
                    {'name': '#', 'field': 'number', 'tooltip': 'Nummer'},
                    {'name': 'SOG', 'field': 'shots_against', 'tooltip': 'Torschüsse'},
                    {'name': 'SV%', 'field': 'save_pctg', 'tooltip': 'Fangquote in %', 'classtd': 'score'},
                    {'name': '', 'field': 'sa_slot', 'tooltip': 'aus dem Slot', 'icon': 'fa fa-lg fa-dot-circle-o'},
                    {'name': '%', 'field': 'save_pctg_slot', 'tooltip': 'SV Slot %'},
                    {'name': '', 'field': 'sa_left', 'tooltip': 'von Links', 'icon': 'fa fa-lg fa-arrow-circle-left'},
                    {'name': '%', 'field': 'save_pctg_left', 'tooltip': 'SV Links %'},
                    {'name': '', 'field': 'sa_right', 'tooltip': 'von Rechts', 'icon': 'fa fa-lg fa-arrow-circle-right'},
                    {'name': '%', 'field': 'save_pctg_right', 'tooltip': 'SV Rechts %'},
                    {'name': '-', 'field': 'sa_blue_line', 'tooltip': 'von der Blaue Linie'},
                    {'name': '%', 'field': 'save_pctg_blue_line', 'tooltip': 'SV BL %'},
                    {'name': '', 'field': 'sa_neutral_zone', 'tooltip': 'aus der Neutrale Zone', 'icon': 'fa fa-lg fa-arrow-circle-down'},
                    {'name': '%', 'field': 'save_pctg_neutral_zone', 'tooltip': 'SV Rückraum %'}]},
            {
                'id': 4,
                'name': 'Fangquoten',
                'structure': [
                    {'name': 'Name', 'field': 'full_name', 'classth': 'left', 'classtd': 'left'},
                    {'name': '', 'field': 'flag', 'type': 'imgflag',},
                    {'name': '#', 'field': 'number', 'tooltip': 'Nummer'},
                    {'name': 'SOG', 'field': 'shots_against', 'tooltip': 'Torschüsse'},
                    {'name': 'SV%', 'field': 'save_pctg', 'tooltip': 'Fangquote in %', 'classtd': 'score'},
                    {'name': 'S5v5', 'field': 'sa_5v5', 'tooltip': 'Torschüsse 5 gegen 5'},
                    {'name': 'G5v5', 'field': 'ga_5v5', 'tooltip': 'Gegentore 5 gegen 5'},
                    {'name': '%', 'field': 'save_pctg_5v5', 'tooltip': 'Fangquote 5v5 %'},
                    {'name': 'S4v4', 'field': 'sa_4v4', 'tooltip': 'Torschüsse 4 gegen 4'},
                    {'name': 'G4v4', 'field': 'ga_4v4', 'tooltip': 'Gegentore 4 gegen 4'},
                    {'name': '%', 'field': 'save_pctg_4v4', 'tooltip': 'Fangquote 4v4 %'},
                    {'name': 'S3v3', 'field': 'sa_3v3', 'tooltip': 'Torschüsse 3 gegen 3'},
                    {'name': 'G3v3', 'field': 'ga_3v3', 'tooltip': 'Gegentore 3 gegen 3'},
                    {'name': '%', 'field': 'save_pctg_3v3', 'tooltip': 'Fangquote 3v3 %'}]},
            {
                'id': 5,
                'name': 'Fangquoten UZ',
                'structure': [
                    {'name': 'Name', 'field': 'full_name', 'classth': 'left', 'classtd': 'left'},
                    {'name': '', 'field': 'flag', 'type': 'imgflag',},
                    {'name': '#', 'field': 'number', 'tooltip': 'Nummer'},
                    {'name': 'SOG', 'field': 'shots_against', 'tooltip': 'Torschüsse'},
                    {'name': 'SV%', 'field': 'save_pctg', 'tooltip': 'Fangquote in %', 'classtd': 'score'},
                    {'name': 'S4v5', 'field': 'sa_4v5', 'tooltip': 'Torschüsse 4 gegen 5'},
                    {'name': 'G4v5', 'field': 'ga_4v5', 'tooltip': 'Gegentore 4 gegen 5'},
                    {'name': '%', 'field': 'save_pctg_4v5', 'tooltip': 'Fangquote 4v5 %'},
                    {'name': 'S3v5', 'field': 'sa_3v5', 'tooltip': 'Torschüsse 3 gegen 5'},
                    {'name': 'G3v5', 'field': 'ga_3v5', 'tooltip': 'Gegentore 3 gegen 5'},
                    {'name': '%', 'field': 'save_pctg_3v5', 'tooltip': 'Fangquote 3v5 %'},
                    {'name': 'S3v4', 'field': 'sa_3v4', 'tooltip': 'Torschüsse 3 gegen 4'},
                    {'name': 'G3v4', 'field': 'ga_3v4', 'tooltip': 'Gegentore 3 gegen 4'},
                    {'name': '%', 'field': 'save_pctg_3v4', 'tooltip': 'Fangquote 3v4 %'}]},
            {
                'id': 6,
                'name': 'Fangquoten ÜZ',
                'structure': [
                    {'name': 'Name', 'field': 'full_name', 'classth': 'left', 'classtd': 'left'},
                    {'name': '', 'field': 'flag', 'type': 'imgflag',},
                    {'name': '#', 'field': 'number', 'tooltip': 'Nummer'},
                    {'name': 'SOG', 'field': 'shots_against', 'tooltip': 'Torschüsse'},
                    {'name': 'SV%', 'field': 'save_pctg', 'tooltip': 'Fangquote in %', 'classtd': 'score'},
                    {'name': 'S5v4', 'field': 'sa_5v4', 'tooltip': 'Torschüsse 5 gegen 4'},
                    {'name': 'G5v4', 'field': 'ga_5v4', 'tooltip': 'Gegentore 5 gegen 4'},
                    {'name': '%', 'field': 'save_pctg_5v4', 'tooltip': 'Fangquote 5v4 %'},
                    {'name': 'S5v3', 'field': 'sa_5v3', 'tooltip': 'Torschüsse 5 gegen 3'},
                    {'name': 'G5v3', 'field': 'ga_5v3', 'tooltip': 'Gegentore 5 gegen 3'},
                    {'name': '%', 'field': 'save_pctg_5v3', 'tooltip': 'Fangquote 5v3 %'},
                    {'name': 'S4v3', 'field': 'sa_4v3', 'tooltip': 'Torschüsse 4 gegen 3'},
                    {'name': 'G4v3', 'field': 'ga_4v3', 'tooltip': 'Gegentore 4 gegen 3'},
                    {'name': '%', 'field': 'save_pctg_4v3', 'tooltip': 'Fangquote 4v3 %'}]}]
    return (player_table_structure, goalie_table_structure)

def convert_graph(debug, url, data, file_name):
    """ send data to server """
    print_debug(debug, 'convert_graph() for {0}'.format(file_name))

    headers = {'Content-Type': 'application/json'}
    try:
        api_response = requests.post(url=url, data=data, headers=headers, verify=False, timeout=15)
        if api_response.ok and api_response.content:
            print_debug(debug, 'We got something useful back. Lets dump it into a file')
            with open(file_name, "wb") as binary_file:
                binary_file.write(api_response.content)
            return (True, None)
        else:
            print_debug(debug, 'Something went south. We got response code: {0}'.format(api_response.status_code))
            # err = api_response.raise_for_status()
            return (False, api_response.status_code)
    except BaseException as _err:
        print_debug(debug, 'Connection error')
        return(None, 'Connection error')

def create_pillow_image(debug, base, back_ground, stat_chart_, file_name):
    """ create image """
    print_debug(debug, 'convert_graph() for {0}'.format(file_name))

    # define font
    font = ImageFont.truetype("/var/www/tipp_game/tools/arialbd.ttf", 30, encoding="unic")

    # open files and create thumbnails
    size = 40, 40
    ebb_logo = Image.open(base + stat_chart_['ebb']['logo'])
    oteam_logo = Image.open(base + stat_chart_['oteam']['logo'])
    ebb_logo.thumbnail(size)
    oteam_logo.thumbnail(size)

    image = Image.open(base + back_ground)
    draw = ImageDraw.Draw(image)

    # bottom images and text
    image.paste(ebb_logo, (20, 165), ebb_logo)
    name = '{0}%'.format(stat_chart_['ebb']['left']['roundpercent'])
    draw.text((70, 165), name, fill='rgb(255, 255, 255)', font=font)
    image.paste(oteam_logo, (20, 220), oteam_logo)
    name = '{0}%'.format(stat_chart_['oteam']['left']['roundpercent'])
    draw.text((70, 220), name, fill='rgb(255, 255, 255)', font=font)

    # center images and text
    image.paste(ebb_logo, (240, 165), ebb_logo)
    name = '{0}%'.format(stat_chart_['ebb']['slot']['roundpercent'])
    draw.text((290, 165), name, fill='rgb(255, 255, 255)', font=font)
    image.paste(oteam_logo, (240, 220), oteam_logo)
    name = '{0}%'.format(stat_chart_['oteam']['slot']['roundpercent'])
    draw.text((290, 220), name, fill='rgb(255, 255, 255)', font=font)

    # top images and text
    image.paste(ebb_logo, (460, 165), ebb_logo)
    name = '{0}%'.format(stat_chart_['ebb']['right']['roundpercent'])
    draw.text((510, 165), name, fill='rgb(255, 255, 255)', font=font)
    image.paste(oteam_logo, (460, 220), oteam_logo)
    name = '{0}%'.format(stat_chart_['oteam']['right']['roundpercent'])
    draw.text((510, 220), name, fill='rgb(255, 255, 255)', font=font)

    # defense images and text
    image.paste(ebb_logo, (240, 315), ebb_logo)
    name = '{0}%'.format(stat_chart_['ebb']['blue_line']['roundpercent'])
    draw.text((290, 315), name, fill='rgb(255, 255, 255)', font=font)
    image.paste(oteam_logo, (240, 370), oteam_logo)
    name = '{0}%'.format(stat_chart_['oteam']['blue_line']['roundpercent'])
    draw.text((290, 370), name, fill='rgb(255, 255, 255)', font=font)

    # save the edited image
    image.save(file_name)

def get_ranking_and_goals(season_id, request):
    """ get data we need for the chart """
    # whats the id of best german hockey team
    ebb_id = get_team_id('EBB')

    match_list = get_matches(request, season_id)

    # data for the chart
    ebb_ranking = list(map(int, Ranking.objects.filter(team_id=ebb_id, season_id=season_id, type='all').order_by('match').values_list('ranking', flat=True)))

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

    return(mday_list, ranking_list, goal_list, ggoal_list)

def get_zone_name(coordinate_x, coordinate_y):
    """ get coordinates """
    (meter_x, meter_y) = convert_shoot_coordinates(coordinate_x, coordinate_y)
    # constructing shot location
    shot_pnt = Point(meter_x, meter_y)
    shot_zone = None
    # determining shot zone
    for poly_name, poly in rd.polygons:
        if poly.intersects(shot_pnt):
            shot_zone = poly_name[5:]
            break

    return shot_zone.lower()

def convert_shoot_coordinates(coordinate_x, coordinate_y):
    """ convert  arbitrary coordinates to actual coordinates in meters sourse: leaffan.net """

    x2m = 0.3048
    y2m = 0.1524

    meter_x = x2m * coordinate_x
    meter_y = y2m * coordinate_y

    return(round(meter_x, 2), round(meter_y, 2))

def get_game_shotmap(match_id, mobile_browser, prefix=None):
    """ shootmap tester """

    # get last rfilter matches and filter match-id from first entry
    match_list = Match.objects.filter(id=match_id, no_bet=False).values('id', 'date', 'matchday', 'home_team__short_name', 'home_team__team_name', 'home_team__logo_url', 'guest_team__short_name', 'guest_team__team_name', 'guest_team__logo_url', 'shots', 'del_date')[:1]

    shot_map_chart = None
    if match_list:

        # these are the shots
        shot_dic = match_list[0]['shots']
        shotmap_list = []

        if shot_dic:
            for shot in shot_dic['match']['shots']:
                # these are shots from EBB
                if shot['team_id'] == 3:
                #    if shot['jersey'] == 44:
                    # convert in meters
                    (m_x, m_y) = convert_shoot_coordinates(shot['coordinate_x'], shot['coordinate_y'])
                    shot['meters_x'] = m_x
                    shot['meters_y'] = m_y
                    shot['minute'] = math.ceil(shot['time']/60)

                    if match_list[0]['home_team__short_name'] == 'EBB':
                        # flip counter clockwise for road_game
                        shot['x'] = shot['coordinate_y'] * -1
                        shot['y'] = shot['coordinate_x']
                    else:
                        # flip clockwise for road_game
                        shot['x'] = shot['coordinate_y']
                        shot['y'] = shot['coordinate_x'] * -1

                    shot['name'] = '{0} {1}'.format(shot['first_name'], shot['last_name'])

                    # append to list
                    shotmap_list.append(shot)

            shot_map_chart = create_shotmap_chart(shotmap_list, mobile_browser, prefix)

    return (shot_map_chart, None)

def create_shotmap_chart(shotmap_list, mobile_browser, prefix):
    """ create shotmap chart """

    data_dic = {1 :[], 2: [], 3: [], 4: [], 5: []}

    for shot in sorted(shotmap_list, key=lambda x: (x['match_shot_resutl_id'])):
        tmp_dic = {
            'x': shot['x'],
            'y': shot['y'],
            'z': 2,
            'jersey': shot['jersey'],
            'name': shot['name'],
            'labelrank': 2,
            'minute': shot['minute'],
            }

        if shot['match_shot_resutl_id'] == 2:
            # tmp_dic['marker'] = {'fillColor': '#d8d9da'}
            tmp_dic['labelrank'] = 1
        elif shot['match_shot_resutl_id'] == 3:
            # tmp_dic['marker'] = {'fillColor': '#000052'}
            tmp_dic['dataLabels'] = {'color': '#ffffff'}
            tmp_dic['labelrank'] = 3
        elif shot['match_shot_resutl_id'] == 4:
            # tmp_dic['marker'] = {'fillColor': '#f01a29'}
            tmp_dic['labelrank'] = 4

        data_dic[shot['match_shot_resutl_id']].append(tmp_dic)

    # we need to change some setting for mobile access
    if mobile_browser:
        label_size = '8px'
        # show_legend = 1
        v_align = 'top'
        marker_size = 10
        label_offset = 11
    else:
        label_size = '10px'
        v_align = 'bottom'
        # show_legend = 1
        marker_size = 15
        label_offset = 13

    title = ''

    # bg_image = '/static/img/shotmap.svg'
    # if prefix:
    #    bg_image = prefix + bg_image
    # we put the bg_image inline to avoid hassle with the export server
    bg_image = "data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iNTkwIiBoZWlnaHQ9IjU5NSIgdmlld0JveD0iMCAwIDU5MCA1OTUiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyIgeG1sbnM6eGxpbms9Imh0dHA6Ly93d3cudzMub3JnLzE5OTkveGxpbmsiPjx0aXRsZT5Hcm91cCBDb3B5PC90aXRsZT48ZGVmcz48cGF0aCBkPSJNNzkgMzMwYzIwLjU0IDAgMzctMTYuNTY1IDM3LTM3cy0xNi41NjUtMzctMzctMzd2NzR6IiBpZD0iYSIvPjxtYXNrIGlkPSJiIiB4PSIwIiB5PSIwIiB3aWR0aD0iMzciIGhlaWdodD0iNzQiIGZpbGw9IiNmZmYiPjx1c2UgeGxpbms6aHJlZj0iI2EiLz48L21hc2s+PC9kZWZzPjxnIHRyYW5zZm9ybT0icm90YXRlKDkwIDI5Mi41IDI5NSkiIGZpbGw9Im5vbmUiIGZpbGwtcnVsZT0iZXZlbm9kZCI+PHBhdGggZD0iTTE0OCAwaDQ0MXY1ODRIMTQ4UzIxLjUwNCA1ODQgLjcwMyA0NDAuNDczVjE0NS4yMDdTMTIuOTIyIDkuOTYxIDE0OCAweiIgc3Ryb2tlPSIjMDAwIiBzdHJva2Utd2lkdGg9IjYiIGZpbGw9IiNGRkYiLz48cGF0aCBkPSJNNTg3IDM4MVYyMDVjLTQ4LjYwMSAwLTg4IDM5LjM5OS04OCA4OHMzOS4zOTkgODggODggODh6IiBzdHJva2U9IiMyNTc1RDIiIHN0cm9rZS13aWR0aD0iMyIvPjxwYXRoIGQ9Ik00MTkgMS41djU4MiIgc3Ryb2tlPSIjMjU3NUQyIiBzdHJva2Utd2lkdGg9IjYiIHN0cm9rZS1saW5lY2FwPSJzcXVhcmUiLz48cGF0aCBkPSJNNzkuNSAyMS41djU0MyIgc3Ryb2tlPSIjRUUyQTQyIiBzdHJva2Utd2lkdGg9IjMiIHN0cm9rZS1saW5lY2FwPSJzcXVhcmUiLz48dXNlIHN0cm9rZT0iI0VFMkE0MiIgbWFzaz0idXJsKCNiKSIgc3Ryb2tlLXdpZHRoPSI2IiBmaWxsLW9wYWNpdHk9Ii4zIiBmaWxsPSIjMjU3NUQyIiB4bGluazpocmVmPSIjYSIvPjxwYXRoIGQ9Ik0xNzkuNSA2MC41djIwNy4wMDJNMjE5LjUgNjAuNXYyMDcuMDAyIiBzdHJva2U9IiNFRTJBNDIiIHN0cm9rZS13aWR0aD0iMyIgc3Ryb2tlLWxpbmVjYXA9InNxdWFyZSIvPjxjaXJjbGUgc3Ryb2tlPSIjRUUyQTQyIiBzdHJva2Utd2lkdGg9IjMiIGZpbGw9IiNGRkYiIGN4PSIxOTkiIGN5PSIxNjQiIHI9Ijg5Ii8+PHBhdGggZD0iTTE0Ny41IDE1Ni41aDM5TTE0Ny41IDE3MS41aDM5TTIxMi41IDE1Ni41aDM5TTIxMi41IDE3MS41aDM5TTE4Ni41IDEzNC41djIyTTIxMi41IDEzNC41djIyTTE4Ni41IDE3MS41djIyTTIxMi41IDE3MS41djIyIiBzdHJva2U9IiNFRTJBNDIiIHN0cm9rZS13aWR0aD0iMyIgc3Ryb2tlLWxpbmVjYXA9InNxdWFyZSIvPjxjaXJjbGUgc3Ryb2tlPSIjRUUyQTQyIiBmaWxsPSIjRUUyQTQyIiBjeD0iMTk5IiBjeT0iMTY0IiByPSI2Ii8+PGNpcmNsZSBzdHJva2U9IiNFRTJBNDIiIGZpbGw9IiNFRTJBNDIiIGN4PSI0NDMiIGN5PSIxNjQiIHI9IjYiLz48cGF0aCBkPSJNMTc5LjUgMzIyLjV2MjA3LjAwMk0yMTkuNSAzMjIuNXYyMDcuMDAyIiBzdHJva2U9IiNFRTJBNDIiIHN0cm9rZS13aWR0aD0iMyIgc3Ryb2tlLWxpbmVjYXA9InNxdWFyZSIvPjxjaXJjbGUgc3Ryb2tlPSIjRUUyQTQyIiBzdHJva2Utd2lkdGg9IjMiIGZpbGw9IiNGRkYiIGN4PSIxOTkiIGN5PSI0MjYiIHI9Ijg5Ii8+PHBhdGggZD0iTTE0Ny41IDQxOC41aDM5TTE0Ny41IDQzMy41aDM5TTIxMi41IDQxOC41aDM5TTIxMi41IDQzMy41aDM5TTE4Ni41IDM5Ni41djIyTTIxMi41IDM5Ni41djIyTTE4Ni41IDQzMy41djIyTTIxMi41IDQzMy41djIyIiBzdHJva2U9IiNFRTJBNDIiIHN0cm9rZS13aWR0aD0iMyIgc3Ryb2tlLWxpbmVjYXA9InNxdWFyZSIvPjxjaXJjbGUgc3Ryb2tlPSIjRUUyQTQyIiBmaWxsPSIjRUUyQTQyIiBjeD0iMTk5IiBjeT0iNDI2IiByPSI2Ii8+PGNpcmNsZSBzdHJva2U9IiNFRTJBNDIiIGZpbGw9IiNFRTJBNDIiIGN4PSI0NDMiIGN5PSI0MjYiIHI9IjYiLz48cGF0aCBkPSJNMTQ4IDBoNDQxdjU4NEgxNDhTMjEuNTA0IDU4NCAuNzAzIDQ0MC40NzNWMTQ1LjIwN1MxMi45MjIgOS45NjEgMTQ4IDB6IiBzdHJva2U9IiMwMDAiIHN0cm9rZS13aWR0aD0iNiIvPjwvZz48L3N2Zz4="
    chart_options = {

        'chart': {
            'type': 'scatter',
            'plotBorderWidth': 0,
            'plotBackgroundImage': bg_image,
            'zoomType': 'xy',
            'height': '110%',
        },

        'exporting': {
            'chartOptions': {
                'plotOptions': {
                    'series': {
                        'dataLabels': {
                            'enabled': 0,
                        },
                    },
                },
            },
            'fallbackToExportServer': 0,
        },

        'legend': {
            'enabled': 1,
            'itemStyle': {'color': '#404040', 'font-size': label_size},
            'verticalAlign': v_align,
            'squareSymbol': 1,
        },

        'title': {
            'text': title,
        },

        'tooltip': {
            'useHTML': 1,
            'headerFormat': '<table class="w3-tiny">',
            'pointFormat': '<tr><td><b>{point.name} ({point.jersey})<b></td></tr>' +
                           '<tr><td>{point.minute}. Minute</td></tr>',
            'footerFormat': '</table>',
            'followPointer': 1,
        },

        'plotOptions': {
            'series': {
                'dataLabels': {
                    'enabled': 1,
                    'color': '#000000',
                    'style': {'textShadow': 0, 'textOutline': 0, 'fontSize': label_size},
                    'y': label_offset,
                    'format': '{point.jersey}',
                    'align': 'center',
                    'allowOverlap': 1,
                },
                'color': '#7cb5ec',
                # 'borderWidth': 0,
                # 'color': 'rgba(189, 191, 193, 6)',
                'lineColor': '#c00c18',
            },
        },

        'xAxis': {
            'visible': 0,
            'labels': {'enabled': 0},
            'min': -100,
            'max': 100,
            'tickInterval': 0,
        },

        'yAxis': {
            'visible': 0,
            'gridLineWidth': 0,
            'title': {
                'text': '',
            },
            'labels': {'enabled': 0},
            'min': 0,
            'max': 105,
            'tickInterval': 0,
        },

        'series': [
            {'name': 'Gehalten', 'data': data_dic[1], 'marker': {'radius': marker_size, 'symbol': 'circle'}},
            {'name': 'Vorbei', 'data': data_dic[2], 'color': '#d8d9da', 'marker': {'symbol': 'circle', 'radius': marker_size}},
            {'name': 'Geblockt', 'color': '#000052', 'data': data_dic[3], 'marker': {'symbol': 'circle', 'radius': marker_size}},
            {'name': 'Tor', 'color': '#f01a29', 'data': data_dic[4], 'marker': {'symbol': 'circle', 'radius': marker_size}},
        ],
    }

    return chart_options

def update_goal_information(match_id, home_match, shot_list, event_list):
    """ update goal information """

    # get goals without zone information
    goal_list = Goal.objects.filter(match_id=match_id).values_list('score', flat=True)

    error_list = []

    if goal_list:
        # store shots in dictionary for faster access
        filtered_shot_list = []
        for shot in shot_list['match']['shots']:
            # adjust times by 5 second
            if shot['match_shot_resutl_id'] == 4:
                filtered_shot_list.append(shot)

        # we rely on the fact that the goals in shot_list and event_list are coming in the same order
        # iterate of events
        filtered_event_list = []
        for period in event_list:
            for event in event_list[period]:
                if event['type'].lower() == 'goal':
                    filtered_event_list.append(event)

        # from pprint import pprint
        # pprint(filtered_shot_list)

        for idx, goal in enumerate(filtered_event_list):

            try:
                shot = filtered_shot_list[idx]
            except BaseException:
                if goal['time'] == 3900:
                    shot = {'coordinate_x': 0, 'coordinate_y': 0, 'time': goal['time'], 'last_name': goal['data']['scorer']['surname'], 'jersey': goal['data']['scorer']['jersey']}
                else:
                    break

            # get score
            score = goal['data']['currentScore']

            # get zone
            zone = get_zone_name(shot['coordinate_x'], shot['coordinate_y'])
            # convert seconds into mm:ss
            (minutes, seconds) = goal['time'] // 60, goal['time'] % 60

            if minutes < 21:
                period = '1. Drittel'
            elif minutes < 41:
                period = '2. Drittel'
            elif minutes < 61:
                period = '3. Drittel'
            elif goal['time'] < 3900:
                period = 'Overtime'
            elif goal['time'] == 3900:
                period = 'Shootout'

            data_dic = {
                'zone': zone,
                'coordinate_x': shot['coordinate_x'],
                'coordinate_y': shot['coordinate_y'],
                'time': '{0}:{1}'.format(minutes, seconds),
                'score': score,
                'period': period,
                'name': '{0}:{1}'.format(goal['data']['scorer']['name'], goal['data']['scorer']['surname']),
                'number': goal['data']['scorer']['jersey'],
                'ebb': False,
                'time_second': goal['time'],
                'attendants': goal['data']['attendants'],
                'assistants': goal['data']['assistants'],
            }

            # classify ebb_goal for faster lookup
            if home_match and goal['data']['team'] == 'home':
                data_dic['ebb'] = True
            if not home_match and goal['data']['team'] == 'visitor':
                data_dic['ebb'] = True

            # store in db
            obj, _created = Goal.objects.update_or_create(match_id=match_id, score=score, defaults=data_dic)
            obj.save()

            # crosscheck compare player numbers
            if shot['jersey'] != goal['data']['scorer']['jersey']:
                error_list.append('X-check failed: from shot_dic: {0}, {1} ({2})/ from event_list: {3}, {4} ({5}) {6}'.format(
                    shot['time'], shot['last_name'], shot['jersey'], goal['time'], goal['data']['scorer']['surname'],
                    goal['data']['scorer']['jersey'], score))

    return error_list

def validate_tip(season_id, match_id, tip, user_id, user_name, user_groups):
    """ additional group specific tip validation  """

    # oma tip check
    error = check_oma_tip(season_id, match_id, tip, user_id, user_name, user_groups)

    return error

def check_oma_tip(season_id, match_id, tip, user_id, _user_name, user_groups):
    """ check oma tip """
    # get list of group_ids
    group_id_list = list(user_groups.keys())

    oma_check = None
    # check groups for oma_tip configuration
    group_list = Groupsetting.objects.filter(group__id__in=group_id_list, oma_tip_ranks__gt=0).values('oma_tip_ranks', 'oma_tip_list', 'group_id', 'group__name')

    if group_list:
        for group_ in group_list:
            # get tipp statistic
            # print(group_['group__name'])
            (_score_dict, _user_dict, sort_list) = get_tipstats(season_id, group_['group__name'], match_id, False, 'EBB', True)

            #  get leaders accoring to group configuration
            leader_list = sort_list[:group_['oma_tip_ranks']]

            # do oma check if required
            if user_id in leader_list:
                oma_tip_list = group_['oma_tip_list'].split(', ')
                if tip in oma_tip_list:
                    oma_check = 'Das ist ein Oma-Tipp. Du darfst nicht {0} tippen...'.format(group_['oma_tip_list'])
                    break

    return oma_check

def get_season_shot_distribution(_match_id, mobile_browser, match_list, sog_filter=False):
    """ get shot distribution for whole season """

    # create dictionary to store data
    shot_distribution_dic = {'ebb': {}, 'others': {}}
    for number in range(1, 6):
        shot_distribution_dic['ebb'][number] = {'count': 0, 'shot_result': {}}
        shot_distribution_dic['others'][number] = {'count': 0, 'shot_result': {}}
        for result in range(1, 6):
            shot_distribution_dic['ebb'][number]['shot_result'][result] = 0
            shot_distribution_dic['others'][number]['shot_result'][result] = 0
    # sum
    shot_distribution_dic['ebb']['sum'] = {'count': 0}
    shot_distribution_dic['others']['sum'] = {'count': 0}

    for match in match_list:
        if match['shots']:
            for shot in match['shots']['match']['shots']:
                # fix shot-time 0
                if shot['time'] == 0:
                    shot['time'] = 1

                # get game period
                period = math.ceil(shot['time']/1200)

                # count shot
                if shot['team_id'] == 3:
                    if sog_filter:
                        # filter goalshots
                        if shot['match_shot_resutl_id'] in (1, 4):
                            shot_distribution_dic['ebb'][period]['count'] += 1
                            shot_distribution_dic['ebb'][period]['shot_result'][shot['match_shot_resutl_id']] += 1
                            shot_distribution_dic['ebb']['sum']['count'] += 1
                    else:
                        shot_distribution_dic['ebb'][period]['count'] += 1
                        shot_distribution_dic['ebb'][period]['shot_result'][shot['match_shot_resutl_id']] += 1
                        shot_distribution_dic['ebb']['sum']['count'] += 1
                else:
                    if sog_filter:
                        # filter goalshots
                        if shot['match_shot_resutl_id'] in (1, 4):
                            shot_distribution_dic['others'][period]['count'] += 1
                            shot_distribution_dic['others'][period]['shot_result'][shot['match_shot_resutl_id']] += 1
                            shot_distribution_dic['others']['sum']['count'] += 1
                    else:
                        shot_distribution_dic['others'][period]['count'] += 1
                        shot_distribution_dic['others'][period]['shot_result'][shot['match_shot_resutl_id']] += 1
                        shot_distribution_dic['others']['sum']['count'] += 1

    for number in range(1, 5):
        shot_distribution_dic['ebb'][number]['roundpercent'] = int(round(shot_distribution_dic['ebb'][number]['count'] * 100 / shot_distribution_dic['ebb']['sum']['count'], 0))
        shot_distribution_dic['others'][number]['roundpercent'] = int(round(shot_distribution_dic['others'][number]['count'] * 100 / shot_distribution_dic['others']['sum']['count'], 0))

    shot_pie = create_season_shot_period_pie(shot_distribution_dic, mobile_browser)
    shot_table = create_season_shotperiod_table(shot_distribution_dic, sog_filter)
    return (shot_pie, shot_table)

def thousand_dot(num_):
    """ set dots to numbers (tausendertrennzeichen) """
    us_num = f"{num_:,}"
    convert_num = us_num.replace('.', ';')
    convert_num = convert_num.replace(',', '.')
    return convert_num.replace(';', ',')

def create_season_shotperiod_table(shot_min_dic, _sog_filter):
    """ create table including shots per persiod """

    table_dic = {'th': ['', '1st', '%', '2nd', '%', '3rd', '%', 'OT', '%', 'Sum'], 'align': ['left', None, None, None, None, None, None, None, None, None], 'td': []}

    ebb_list = ['EBB']
    other_list = ['Gegner']

    for number in range(1, 5):
        ebb_list.append(shot_min_dic['ebb'][number]['count'])
        ebb_list.append(shot_min_dic['ebb'][number]['roundpercent'])
        other_list.append(shot_min_dic['others'][number]['count'])
        other_list.append(shot_min_dic['others'][number]['roundpercent'])

    # sum
    ebb_list.append(thousand_dot(shot_min_dic['ebb']['sum']['count']))
    other_list.append(thousand_dot(shot_min_dic['others']['sum']['count']))

    table_dic['td'].append(ebb_list)
    table_dic['td'].append(other_list)

    return table_dic

def create_season_shot_period_pie(shot_distribution_dic, mobile_browser):
    """ create pie chart about goals per period """

    title = ''

    label_size = '10px'
    distance = -30
    innerdistance = -50
    v_align = 'bottom'
    o_inner_name = 'Gegner'

    period_name_dic = {1: '1st', 2: '2nd', 3: '3rd', 4:  'OT'}
    shot_status_list = [1, 4, 3, 2]
    shot_status_dic = {
        1:  {'name': 'Gehalten', 'color': '#7cb5ec'},
        2:  {'name': 'Vorbei ', 'color': '#d8d9da'},
        3: {'name': 'Geblockt', 'color': '#000052'},
        4: {'name': 'Tor', 'color': '#f01a29'}}

    # 'data': [['f1', 0.1], ['f2', 0.1], ['f2', 0.1]]

    # create drill_down list
    drilldown_list = []
    for num_ in range(1, 5):
        tmp_ebb_dic = {'id': 'ebb_{0}'.format(num_), 'name': period_name_dic[num_], 'data': []}
        tmp_other_dic = {'id': 'others_{0}'.format(num_), 'name': period_name_dic[num_], 'data': []}
        for status in shot_status_list:
            tmp_ebb_dic['data'].append({'name': shot_status_dic[status]['name'], 'y': shot_distribution_dic['ebb'][num_]['shot_result'][status], 'color': shot_status_dic[status]['color']})
            tmp_other_dic['data'].append({'name': shot_status_dic[status]['name'], 'y': shot_distribution_dic['others'][num_]['shot_result'][status], 'color': shot_status_dic[status]['color']})
        drilldown_list.append(tmp_ebb_dic)
        drilldown_list.append(tmp_other_dic)

    outer_pie_dic = {'ebb': [], 'others': []}
    for period in period_name_dic:
        for status in shot_status_list:
            tmp_ebb_dic = {'name': shot_status_dic[status]['name'], 'y': shot_distribution_dic['ebb'][period]['shot_result'][status], 'color': shot_status_dic[status]['color']}
            tmp_others_dic = {'name': shot_status_dic[status]['name'], 'y': shot_distribution_dic['others'][period]['shot_result'][status], 'color': shot_status_dic[status]['color']}
            outer_pie_dic['ebb'].append(tmp_ebb_dic)
            outer_pie_dic['others'].append(tmp_others_dic)

    # we need to change some setting for mobile access
    if mobile_browser:
        label_size = '8px'
        distance = -15
        innerdistance = -30
        v_align = 'top'
        o_inner_name = 'G'

    chart_options = {

        'chart': {
            'plotBackgroundColor': 0,
            'plotBorderWidth': 0,
            'plotShadow': 0,
            'type': 'pie',
            'height': '50%',
        },

        'exporting': {
            'chartOptions': {
                'plotOptions': {
                    'series': {
                        'dataLabels': {
                            'enabled': 0,
                        },
                    },
                },
            },
            'fallbackToExportServer': 0,
        },

        'title': {
            'text': title,
            'style': {'color': '#404040', 'font-size': '12px'},
            'verticalAlign': 'middle',
        },

        'legend': {
            'enabled': 1,
            'itemStyle': {'color': '#404040', 'font-size': label_size},
            'verticalAlign': v_align,
            'symbolRadius': 0,
        },

        'plotOptions': {
            'series': {
                'dataLabels': {
                    'enabled': 1,
                    'useHTML': 1,
                    # 'format': '{point.name}: {point.y}',
                    #'style': {
                    #    "text-decoration": "none",
                    #},
                }
            },
            'pie': {
                'showInLegend': 0,
                'dataLabels': {
                    'distance': distance,
                    'plotShadow': 0,
                }
            }
        },

        'tooltip': {
            'headerFormat': '<span style="font-size:11px">{point.name}</span><br>',
            'pointFormat': '<span style="color:{point.color}"><b>{point.name}:</b></span>{point.y} Schüsse<br/>'
        },

        'xAxis': {
            'visible': 0,
            'title': {
                'text': '',
            },
        },
        'yAxis': {
            'visible': 0,
            'title': {
                'text': '',
            },
        },

        'series': [
            {
                'size': '40%',
                'innerSize': '0%',
                'center': ['25%'],
                'data': [{'name': 'EBB', 'y': shot_distribution_dic['ebb']['sum']['count'], 'color': '#ffffff'}],
                'dataLabels': {'distance': innerdistance},
            }, {
                'name': 'Schüsse pro Drittel',
                'colorByPoint': 1,
                'size': '75%',
                'innerSize': '40%',
                'center': ['25%'],
                'data': [
                    {
                        'name': period_name_dic[1],
                        'y': shot_distribution_dic['ebb'][1]['count'],
                        'color': '#000034',
                    }, {
                        'name': period_name_dic[2],
                        'y': shot_distribution_dic['ebb'][2]['count'],
                        'color': '#000099',
                    }, {
                        'name': period_name_dic[3],
                        'y': shot_distribution_dic['ebb'][3]['count'],
                        'color': '#0000ff',
                    }, {
                        'name': period_name_dic[4],
                        'y': shot_distribution_dic['ebb'][4]['count'],
                        'color': '#6666ff'}
                    ]
            }, {
                'name': 'Schussergebnis',
                'colorByPoint': 1,
                'size': '100%',
                'innerSize': '78%',
                'center': ['25%'],
                'dataLabels': 0,
                'data': outer_pie_dic['ebb'],
            }, {
                'size': '40%',
                'innerSize': '0%',
                'center': ['75%'],
                'data': [{'name': o_inner_name, 'y': shot_distribution_dic['others']['sum']['count'], 'color': '#ffffff'}],
                'dataLabels': {'distance': innerdistance},
            }, {
                'name': 'Gegentore',
                'size': '75%',
                'innerSize': '40%',
                'center': ['75%'],
                'data': [
                    {
                        'name': period_name_dic[1],
                        'y': shot_distribution_dic['others'][1]['count'],
                        'color'  : '#404040',
                    }, {
                        'name': period_name_dic[2],
                        'y': shot_distribution_dic['others'][2]['count'],
                        'color' : '#737373',
                    }, {
                        'name': period_name_dic[3],
                        'y': shot_distribution_dic['others'][3]['count'],
                        'color' : '#a6a6a6',
                    }, {
                        'name': period_name_dic[4],
                        'y': shot_distribution_dic['others'][4]['count'],
                        'color': '#d9d9d9'}]
            }, {
                'name': 'Schussergebnis',
                'colorByPoint': 1,
                'size': '100%',
                'innerSize': '78%',
                'center': ['75%'],
                'dataLabels': 0,
                'data': outer_pie_dic['others'],
            },
            {'name': shot_status_dic[1]['name'], 'color': shot_status_dic[1]['color'], 'type': 'column'},
            {'name': shot_status_dic[2]['name'], 'color': shot_status_dic[2]['color'], 'type': 'column'},
            {'name': shot_status_dic[3]['name'], 'color': shot_status_dic[3]['color'], 'type': 'column'},
            {'name': shot_status_dic[4]['name'], 'color': shot_status_dic[4]['color'], 'type': 'column'},
            ],
    }

    return chart_options

def get_season_shot_result(_match_id, mobile_browser, match_list, _sog_filter=False):
    """ get shot distribution for whole season """

    # create dictionary to store data
    shot_result_dic = {'ebb': {}, 'others': {}}
    for number in range(1, 6):
        shot_result_dic['ebb'][number] = {'count': 0, 'period': {}}
        shot_result_dic['others'][number] = {'count': 0, 'period': {}}
        for result in range(1, 6):
            shot_result_dic['ebb'][number]['period'][result] = 0
            shot_result_dic['others'][number]['period'][result] = 0

    # sum
    shot_result_dic['ebb']['sum'] = {'count': 0}
    shot_result_dic['others']['sum'] = {'count': 0}

    for match in match_list:
        if match['shots']:
            for shot in match['shots']['match']['shots']:
                # fix shot-time 0
                if shot['time'] == 0:
                    shot['time'] = 1

                # get game period
                period = math.ceil(shot['time']/1200)

                # count shot
                if shot['team_id'] == 3:
                    shot_result_dic['ebb'][shot['match_shot_resutl_id']]['count'] += 1
                    shot_result_dic['ebb'][shot['match_shot_resutl_id']]['period'][period] += 1
                    shot_result_dic['ebb']['sum']['count'] += 1
                else:
                    shot_result_dic['others'][shot['match_shot_resutl_id']]['count'] += 1
                    shot_result_dic['others'][shot['match_shot_resutl_id']]['period'][period] += 1
                    shot_result_dic['others']['sum']['count'] += 1

    for number in range(1, 5):
        shot_result_dic['ebb'][number]['roundpercent'] = int(round(shot_result_dic['ebb'][number]['count'] * 100 / shot_result_dic['ebb']['sum']['count'], 0))
        shot_result_dic['others'][number]['roundpercent'] = int(round(shot_result_dic['others'][number]['count'] * 100 / shot_result_dic['others']['sum']['count'], 0))

    shot_pie = create_season_shot_result_pie(shot_result_dic, mobile_browser)
    shot_table = create_season_shot_result_table(shot_result_dic, mobile_browser)


    return (shot_pie, shot_table)


def create_season_shot_result_table(shot_result_dic, _mobile_browser):
    """ create table including shots per persiod """

    table_dic = {'th': ['', 'Eisbären', '%', 'Gegner', '%'], 'align': ['left', None, None, None, None, None], 'td': []}

    shot_status_dic = {
        1:  {'name': 'Gehalten', 'color': '#7cb5ec'},
        2:  {'name': 'Vorbei ', 'color': '#d8d9da'},
        3: {'name': 'Geblockt', 'color': '#000052'},
        4: {'name': 'Tor', 'color': '#f01a29'}}

    for number in [1, 4, 3, 2]:
        table_dic['td'].append([
            shot_status_dic[number]['name'],
            thousand_dot(shot_result_dic['ebb'][number]['count']),
            thousand_dot(shot_result_dic['ebb'][number]['roundpercent']),
            thousand_dot(shot_result_dic['others'][number]['count']),
            thousand_dot(shot_result_dic['others'][number]['roundpercent']),
            ])


    table_dic['td'].append(['Summe', thousand_dot(shot_result_dic['ebb']['sum']['count']), '', thousand_dot(shot_result_dic['others']['sum']['count']), ''])


    return table_dic

def create_season_shot_result_pie(shot_result_dic, mobile_browser):
    """ create pie chart about goals per result """

    title = ''

    label_size = '10px'
    distance = -30
    innerdistance = -50
    v_align = 'bottom'
    o_inner_name = 'Gegner'
    show_label = 1

    period_name_dic = {
        1: {'name': '1st', 'color': '#000034', 'ocolor': '#404040'},
        2: {'name': '2nd', 'color': '#000099', 'ocolor': '#737373'},
        3: {'name': '3rd', 'color': '#0000ff', 'ocolor': '#a6a6a6'},
        4:  {'name': 'OT', 'color': '#6666ff', 'ocolor': '#d9d9d9'}}
    shot_status_list = [1, 4, 3, 2]
    shot_status_dic = {
        1:  {'name': 'Gehalten', 'color': '#7cb5ec'},
        2:  {'name': 'Vorbei ', 'color': '#d8d9da'},
        3: {'name': 'Geblockt', 'color': '#000052'},
        4: {'name': 'Tor', 'color': '#f01a29'}}

    outer_pie_dic = {'ebb': [], 'others': []}
    for status in shot_status_list:
        for period in period_name_dic.keys():
            tmp_ebb_dic = {'name': period_name_dic[period]['name'], 'y': shot_result_dic['ebb'][status]['period'][period], 'color': period_name_dic[period]['color']}
            tmp_others_dic = {'name': period_name_dic[period]['name'], 'y': shot_result_dic['others'][status]['period'][period], 'color': period_name_dic[period]['ocolor']}
            outer_pie_dic['ebb'].append(tmp_ebb_dic)
            outer_pie_dic['others'].append(tmp_others_dic)

   # we need to change some setting for mobile access
    if mobile_browser:
        label_size = '8px'
        distance = -15
        innerdistance = -30
        v_align = 'top'
        o_inner_name = 'G'
        show_label = 0

    chart_options = {

        'chart': {
            'plotBackgroundColor': 0,
            'plotBorderWidth': 0,
            'plotShadow': 0,
            'type': 'pie',
            'height': '50%',
        },

        'exporting': {
            'chartOptions': {
                'plotOptions': {
                    'series': {
                        'dataLabels': {
                            'enabled': 0,
                        },
                    },
                },
            },
            'fallbackToExportServer': 0,
        },

        'title': {
            'text': title,
            'style': {'color': '#404040', 'font-size': '12px'},
            'verticalAlign': 'middle',
        },

        'legend': {
            'enabled': 1,
            'itemStyle': {'color': '#404040', 'font-size': label_size},
            'verticalAlign': v_align,
            'symbolRadius': 0,
        },

        'plotOptions': {
            'series': {
                'dataLabels': {
                    'enabled': show_label,
                    'useHTML': 1,
                    # 'style': {
                    #    'fontSize': '10px',
                    # },
                }
            },
            'pie': {
                'showInLegend': 0,
                'dataLabels': {
                    'distance': distance,
                    'plotShadow': 0,
                }
            }
        },

        'tooltip': {
            'headerFormat': '<span style="font-size:11px">{point.name}</span><br>',
            'pointFormat': '<span style="color:{point.color}"><b>{point.name}:</b></span>{point.y} Schüsse<br/>'
        },

        'xAxis': {
            'visible': 0,
            'title': {
                'text': '',
            },
        },
        'yAxis': {
            'visible': 0,
            'title': {
                'text': '',
            },
        },

        'series': [
            {
                'size': '40%',
                'innerSize': '0%',
                'center': ['25%'],
                'data': [{'name': 'EBB', 'y': shot_result_dic['ebb']['sum']['count'], 'color': '#ffffff'}],
                'dataLabels': {'distance': innerdistance},
            }, {
                'name': 'Schüsse pro Drittel',
                'colorByPoint': 1,
                'size': '75%',
                'innerSize': '40%',
                'center': ['25%'],
                'data': [
                    {
                        'name': shot_status_dic[1]['name'],
                        'y': shot_result_dic['ebb'][1]['count'],
                        'color': shot_status_dic[1]['color']
                    }, {
                        'name': shot_status_dic[4]['name'],
                        'y': shot_result_dic['ebb'][4]['count'],
                        'color': shot_status_dic[4]['color'],
                    }, {
                        'name': shot_status_dic[3]['name'],
                        'y': shot_result_dic['ebb'][3]['count'],
                        'color': shot_status_dic[3]['color'],
                    }, {
                        'name': shot_status_dic[2]['name'],
                        'y': shot_result_dic['ebb'][2]['count'],
                        'color': shot_status_dic[2]['color']}
                    ]
            }, {
                'name': 'Schussergebnis',
                'colorByPoint': 1,
                'size': '100%',
                'innerSize': '78%',
                'center': ['25%'],
                'dataLabels': 0,
                'data': outer_pie_dic['ebb'],
            }, {
                'size': '40%',
                'innerSize': '0%',
                'center': ['75%'],
                'data': [{'name': o_inner_name, 'y': shot_result_dic['others']['sum']['count'], 'color': '#ffffff'}],
                'dataLabels': {'distance': innerdistance},
            }, {
                'name': 'Gegentore',
                'size': '75%',
                'innerSize': '40%',
                'center': ['75%'],
                'data': [
                    {
                        'name': shot_status_dic[1]['name'],
                        'y': shot_result_dic['others'][1]['count'],
                        'color'  : shot_status_dic[1]['color']
                    }, {
                        'name': shot_status_dic[4]['name'],
                        'y': shot_result_dic['others'][4]['count'],
                        'color'  : shot_status_dic[4]['color']
                    }, {
                        'name': shot_status_dic[3]['name'],
                        'y': shot_result_dic['others'][3]['count'],
                        'color'  : shot_status_dic[3]['color']
                    }, {
                        'name': shot_status_dic[2]['name'],
                        'y': shot_result_dic['others'][2]['count'],
                        'color': shot_status_dic[2]['color']}],
            }, {
                'name': 'Schussergebnis',
                'colorByPoint': 1,
                'size': '100%',
                'innerSize': '78%',
                'center': ['75%'],
                'dataLabels': 0,
                'data': outer_pie_dic['others'],
            },
            {'name': shot_status_dic[1]['name'], 'color': shot_status_dic[1]['color'], 'type': 'column'},
            {'name': shot_status_dic[2]['name'], 'color': shot_status_dic[2]['color'], 'type': 'column'},
            {'name': shot_status_dic[3]['name'], 'color': shot_status_dic[3]['color'], 'type': 'column'},
            {'name': shot_status_dic[4]['name'], 'color': shot_status_dic[4]['color'], 'type': 'column'},
            ],

    }
    return chart_options


def get_season_shot_min(_match_id, mobile_browser, match_list, percentage=False):
    """ get shots permin for whole season """

    # create dictionary to store data
    shot_min_dic = {'ebb': {1: {}, 2: {}, 3: {}, 4: {}, 5: {}, 'sum': {}}, 'others': {1: {}, 2: {}, 3: {}, 4: {}, 5: {}, 'sum': {}}}

    # initialize data structure
    for number in range(0, 66):
        for team in shot_min_dic:
            for result in shot_min_dic[team]:
                shot_min_dic[team][result][number] = 0

    # iterate matches and count shots
    for match in match_list:
        if match['shots']:
            for shot in match['shots']['match']['shots']:
                # fix shot-time 0
                if shot['time'] == 0:
                    shot['time'] = 1

                # get game period
                min_ = math.ceil(shot['time']/60)

                # count shot
                if shot['team_id'] == 3:
                    shot_min_dic['ebb'][shot['match_shot_resutl_id']][min_] += 1
                    shot_min_dic['ebb']['sum'][min_] += 1
                else:
                    shot_min_dic['others'][shot['match_shot_resutl_id']][min_] += 1
                    shot_min_dic['others']['sum'][min_] += 1


    shot_chart = create_season_shotmin_chart(shot_min_dic, percentage, mobile_browser)
    if percentage:
        shot_table = create_season_shotminpercentage_table(shot_min_dic)
    else:
        shot_table = create_season_shotmin_table(shot_min_dic)

    return(shot_chart, shot_table)

def create_season_shotmin_chart(shot_min_dic, percentage, mobile_browser):
    """ create area chart for shots per min """

    # data
    min_list = list(shot_min_dic['ebb'][1].keys())

    y_max = 0
    for num_ in shot_min_dic['others']:
        for min_ in shot_min_dic['others'][num_]:
            if y_max < shot_min_dic['ebb'][num_][min_]:
                y_max = shot_min_dic['ebb'][num_][min_]
            if y_max < shot_min_dic['others'][num_][min_]:
                y_max = shot_min_dic['others'][num_][min_]
            shot_min_dic['others'][num_][min_] = shot_min_dic['others'][num_][min_] * -1

    y_max = math.ceil(y_max/10) * 10


    title = ''

    label_size = '10px'
    _show_legend = 1
    v_align = 'bottom'

    # we need to change some setting for mobile access
    if mobile_browser:
        label_size = '8px'
        _show_legend = 1
        v_align = 'top'

    # define stack-type
    if percentage:
        stack_type = 'percent'
        tmp_stack_dic = {'showInLegend': 0}
        y_min = 0
        y_max = 100
    else:
        stack_type = 'normal'
        tmp_stack_dic = {'name': 'Gegner', 'data': list(shot_min_dic['others']['sum'].values()), 'color': '#737373'}
        y_min = y_max * -1

    chart_options = {

        'chart': {
            'type': 'area',
            'height': '60%',
        },

        'exporting': {
            'chartOptions': {
                'plotOptions': {
                    'series': {
                        'dataLabels': {
                            'enabled': 0,
                        },
                    },
                },
            },
            'fallbackToExportServer': 0,
        },

        'title': {
            'text': title,
            'style': {'color': '#404040', 'font-size': '12px'},
        },

        'legend': {
            'itemStyle': {'color': '#404040', 'font-size': label_size},
            'verticalAlign': v_align,
        },

        'tooltip': {
            'shared': 1,
            'headerFormat': '<b>{point.x}.Spielminute</b><br>',
        },

        'plotOptions': {
            'area': {
                'stacking': stack_type,
                'marker': {'enabled': 0}
            }
        },

        'xAxis': {
            'gridLineWidth': 1,
            'minTickInterval': 20,
            'min': 0,
            'max' : 65,
            'endOnTick': 1,
            'tickInterval': 5,
            'showFirstLabel': 1,
            'showLastLabel': 1,
            'plotLines': [{
                'color': '#d8d9da',
                'width': 2,
                'value': 20,
            }, {
                'color': '#d8d9da',
                'width': 2,
                'value': 40,
            }, {
                'color': '#d8d9da',
                'width': 2,
                'value': 60,
            }],
            'categories': min_list,
            'title': {
                'text': 'Minute',
                'style': {'color': '#404040', 'font-size': label_size},
            },
            'crosshair': 1,
        },

        'yAxis': [{
            'title': {
                'text': 'Anzahl Schüsse',
                'style': {'color': '#404040', 'font-size': label_size},
            },
            'min': y_min,
            'max': y_max,
            'tickInterval': 10,
            'showFirstLabel': 1,
            'showLastLabel': 1,
            }],

        'series': [
            tmp_stack_dic,
            {
                'name': 'Vorbei',
                'data': list(shot_min_dic['ebb'][2].values()),
                'color': '#d8d9da',
                'stack': 'ebb'
            }, {
                'name': 'Geblockt',
                'data': list(shot_min_dic['ebb'][3].values()),
                'color': '#000052',
                'stack': 'ebb'
            }, {
                'name': 'Gehalten',
                'data': list(shot_min_dic['ebb'][1].values()),
                'color': '#7cb5ec',
                'stack': 'ebb'
            }, {
                'name': 'Tor',
                'data': list(shot_min_dic['ebb'][4].values()),
                'color': '#f01a29',
                'stack': 'ebb'
            }]
        }
    return chart_options

def create_season_shotmin_table(shot_min_dic, _filter=None):
    """ create table including shots per persiod """

    table_dic = {'th': ['Min', 'Tor', 'Geha.', 'Gebl.', 'Vorb.', 'Sum', 'Gegner',], 'align': [None, None, None, None, None, 'score', None], 'td': []}


    min_list = list(shot_min_dic['ebb'][1].keys())

    for min_ in min_list:
        if min_ > 0:
            table_dic['td'].append([min_, shot_min_dic['ebb'][4][min_], shot_min_dic['ebb'][1][min_], shot_min_dic['ebb'][3][min_], shot_min_dic['ebb'][2][min_], shot_min_dic['ebb']['sum'][min_], shot_min_dic['others']['sum'][min_] * -1])

    return table_dic

def create_season_shotminpercentage_table(shot_min_dic, _filter=None):
    """ create table including shots per persiod """

    table_dic = {'th': ['M', 'Tor', '%', 'Geh.', '%', 'Geb.', '%', 'Vor.', '%'], 'align': [None, None, None, None, None, None, None, None, None], 'td': []}


    min_list = list(shot_min_dic['ebb'][1].keys())

    for min_ in min_list:
        if min_ > 0:
            table_dic['td'].append([
                min_,
                shot_min_dic['ebb'][4][min_],
                '{0}%'.format(int(round(shot_min_dic['ebb'][4][min_] * 100/shot_min_dic['ebb']['sum'][min_], 0))),
                shot_min_dic['ebb'][1][min_],
                '{0}%'.format(int(round(shot_min_dic['ebb'][1][min_] * 100/shot_min_dic['ebb']['sum'][min_], 0))),
                shot_min_dic['ebb'][3][min_],
                '{0}%'.format(int(round(shot_min_dic['ebb'][3][min_] * 100/shot_min_dic['ebb']['sum'][min_], 0))),
                shot_min_dic['ebb'][2][min_],
                '{0}%'.format(int(round(shot_min_dic['ebb'][2][min_] * 100/shot_min_dic['ebb']['sum'][min_], 0))),
            ])
    return table_dic

def get_season_shotmap(_match_id, mobile_browser, match_list, filter_sog=False):
    """ get shots permin for whole season """

    # create dictionary to store data
    shot_map_dic = {'ebb': {1: [], 2: [], 3: [], 4: [], 5: []}, 'others': {1: [], 2: [], 3: [], 4: [], 5: []}}

    # iterate matches and count shots
    for match in match_list:

        # store matchday in variable
        matchday = match['matchday']


        if match['shots']:

            # check home_match
            if match['shots']['match']['home_shortcut'] == 'EBB':
                home_match = True
            else:
                home_match = False


            for shot in match['shots']['match']['shots']:
                # fix shot-time 0
                if shot['time'] == 0:
                    shot['time'] = 1

                # count shot
                if shot['team_id'] == 3:

                    if home_match:
                        # flip counter clockwise for road_game
                        shot['x'] = shot['coordinate_y'] * -1
                        shot['y'] = shot['coordinate_x']
                    else:
                        # flip clockwise for road_game
                        shot['x'] = shot['coordinate_y']
                        shot['y'] = shot['coordinate_x'] * -1

                    # get game period
                    # shot['minute'] = '{0:02d}:{1:02d}'.format(*divmod(shot['time'], 60))
                    tmp_dic = {
                        'x': shot['x'],
                        'y': shot['y'],
                        # 'z': 2,
                        'jersey': shot['jersey'],
                        'name': '{0} {1}'.format(shot['first_name'], shot['last_name']),
                        'labelrank': 2,
                        'minute': '{0:02d}:{1:02d}'.format(*divmod(shot['time'], 60)),
                        'mday': matchday,
                    }
                    if filter_sog:
                        if shot['match_shot_resutl_id'] in (1, 4):
                            shot_map_dic['ebb'][shot['match_shot_resutl_id']].append(tmp_dic)
                    else:
                        shot_map_dic['ebb'][shot['match_shot_resutl_id']].append(tmp_dic)

    shot_map = create_seaon_shotmap_chart(shot_map_dic, mobile_browser, filter_sog)

    return(shot_map, None)

def create_seaon_shotmap_chart(shot_map_dic, mobile_browser, filter_sog, multiplier=1):
    """ create shotmap chart """

    # we need to change some setting for mobile access
    if mobile_browser:
        label_size = '8px'
        # show_legend = 1
        v_align = 'top'
        marker_size = 3 * multiplier
        # label_offset = 11
    else:
        label_size = '10px'
        v_align = 'bottom'
        # show_legend = 1
        marker_size = 4 * multiplier
        # label_offset = 13

    # define some colors for the chart
    # if show_ebb:
    #    scatter_color = '#7cb5ec'
    #    marker_linecolor = '#e3e3ff'
    #else:
    #    scatter_color = '#bdbfc1'
    #    marker_linecolor = '#d8d9da'

    bg_image = "data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iNTkwIiBoZWlnaHQ9IjU5NSIgdmlld0JveD0iMCAwIDU5MCA1OTUiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyIgeG1sbnM6eGxpbms9Imh0dHA6Ly93d3cudzMub3JnLzE5OTkveGxpbmsiPjx0aXRsZT5Hcm91cCBDb3B5PC90aXRsZT48ZGVmcz48cGF0aCBkPSJNNzkgMzMwYzIwLjU0IDAgMzctMTYuNTY1IDM3LTM3cy0xNi41NjUtMzctMzctMzd2NzR6IiBpZD0iYSIvPjxtYXNrIGlkPSJiIiB4PSIwIiB5PSIwIiB3aWR0aD0iMzciIGhlaWdodD0iNzQiIGZpbGw9IiNmZmYiPjx1c2UgeGxpbms6aHJlZj0iI2EiLz48L21hc2s+PC9kZWZzPjxnIHRyYW5zZm9ybT0icm90YXRlKDkwIDI5Mi41IDI5NSkiIGZpbGw9Im5vbmUiIGZpbGwtcnVsZT0iZXZlbm9kZCI+PHBhdGggZD0iTTE0OCAwaDQ0MXY1ODRIMTQ4UzIxLjUwNCA1ODQgLjcwMyA0NDAuNDczVjE0NS4yMDdTMTIuOTIyIDkuOTYxIDE0OCAweiIgc3Ryb2tlPSIjMDAwIiBzdHJva2Utd2lkdGg9IjYiIGZpbGw9IiNGRkYiLz48cGF0aCBkPSJNNTg3IDM4MVYyMDVjLTQ4LjYwMSAwLTg4IDM5LjM5OS04OCA4OHMzOS4zOTkgODggODggODh6IiBzdHJva2U9IiMyNTc1RDIiIHN0cm9rZS13aWR0aD0iMyIvPjxwYXRoIGQ9Ik00MTkgMS41djU4MiIgc3Ryb2tlPSIjMjU3NUQyIiBzdHJva2Utd2lkdGg9IjYiIHN0cm9rZS1saW5lY2FwPSJzcXVhcmUiLz48cGF0aCBkPSJNNzkuNSAyMS41djU0MyIgc3Ryb2tlPSIjRUUyQTQyIiBzdHJva2Utd2lkdGg9IjMiIHN0cm9rZS1saW5lY2FwPSJzcXVhcmUiLz48dXNlIHN0cm9rZT0iI0VFMkE0MiIgbWFzaz0idXJsKCNiKSIgc3Ryb2tlLXdpZHRoPSI2IiBmaWxsLW9wYWNpdHk9Ii4zIiBmaWxsPSIjMjU3NUQyIiB4bGluazpocmVmPSIjYSIvPjxwYXRoIGQ9Ik0xNzkuNSA2MC41djIwNy4wMDJNMjE5LjUgNjAuNXYyMDcuMDAyIiBzdHJva2U9IiNFRTJBNDIiIHN0cm9rZS13aWR0aD0iMyIgc3Ryb2tlLWxpbmVjYXA9InNxdWFyZSIvPjxjaXJjbGUgc3Ryb2tlPSIjRUUyQTQyIiBzdHJva2Utd2lkdGg9IjMiIGZpbGw9IiNGRkYiIGN4PSIxOTkiIGN5PSIxNjQiIHI9Ijg5Ii8+PHBhdGggZD0iTTE0Ny41IDE1Ni41aDM5TTE0Ny41IDE3MS41aDM5TTIxMi41IDE1Ni41aDM5TTIxMi41IDE3MS41aDM5TTE4Ni41IDEzNC41djIyTTIxMi41IDEzNC41djIyTTE4Ni41IDE3MS41djIyTTIxMi41IDE3MS41djIyIiBzdHJva2U9IiNFRTJBNDIiIHN0cm9rZS13aWR0aD0iMyIgc3Ryb2tlLWxpbmVjYXA9InNxdWFyZSIvPjxjaXJjbGUgc3Ryb2tlPSIjRUUyQTQyIiBmaWxsPSIjRUUyQTQyIiBjeD0iMTk5IiBjeT0iMTY0IiByPSI2Ii8+PGNpcmNsZSBzdHJva2U9IiNFRTJBNDIiIGZpbGw9IiNFRTJBNDIiIGN4PSI0NDMiIGN5PSIxNjQiIHI9IjYiLz48cGF0aCBkPSJNMTc5LjUgMzIyLjV2MjA3LjAwMk0yMTkuNSAzMjIuNXYyMDcuMDAyIiBzdHJva2U9IiNFRTJBNDIiIHN0cm9rZS13aWR0aD0iMyIgc3Ryb2tlLWxpbmVjYXA9InNxdWFyZSIvPjxjaXJjbGUgc3Ryb2tlPSIjRUUyQTQyIiBzdHJva2Utd2lkdGg9IjMiIGZpbGw9IiNGRkYiIGN4PSIxOTkiIGN5PSI0MjYiIHI9Ijg5Ii8+PHBhdGggZD0iTTE0Ny41IDQxOC41aDM5TTE0Ny41IDQzMy41aDM5TTIxMi41IDQxOC41aDM5TTIxMi41IDQzMy41aDM5TTE4Ni41IDM5Ni41djIyTTIxMi41IDM5Ni41djIyTTE4Ni41IDQzMy41djIyTTIxMi41IDQzMy41djIyIiBzdHJva2U9IiNFRTJBNDIiIHN0cm9rZS13aWR0aD0iMyIgc3Ryb2tlLWxpbmVjYXA9InNxdWFyZSIvPjxjaXJjbGUgc3Ryb2tlPSIjRUUyQTQyIiBmaWxsPSIjRUUyQTQyIiBjeD0iMTk5IiBjeT0iNDI2IiByPSI2Ii8+PGNpcmNsZSBzdHJva2U9IiNFRTJBNDIiIGZpbGw9IiNFRTJBNDIiIGN4PSI0NDMiIGN5PSI0MjYiIHI9IjYiLz48cGF0aCBkPSJNMTQ4IDBoNDQxdjU4NEgxNDhTMjEuNTA0IDU4NCAuNzAzIDQ0MC40NzNWMTQ1LjIwN1MxMi45MjIgOS45NjEgMTQ4IDB6IiBzdHJva2U9IiMwMDAiIHN0cm9rZS13aWR0aD0iNiIvPjwvZz48L3N2Zz4="


    # we do not want to have a title
    title = ''
    chart_options = {

        'chart': {
            'type': 'scatter',
            'plotBorderWidth': 0,
            'plotBackgroundImage': bg_image,
            'zoomType': 'xy',
            'height': '110%',
        },

        'exporting': {
            'chartOptions': {
                'plotOptions': {
                    'series': {
                        'dataLabels': {
                            'enabled': 0,
                        },
                    },
                },
            },
            'fallbackToExportServer': 0,
        },

        'boost': {
            'useGPUTranslations': 1,
            'usePreAllocated': 1
        },

        'legend': {
            'enabled': 1,
            'itemStyle': {'color': '#404040', 'font-size': label_size},
            'verticalAlign': v_align,
            'squareSymbol': 1,
        },

        'title': {
            'text': title,
        },

        'tooltip': {
            'useHTML': 1,
            'headerFormat': '<table class="w3-tiny">',
            'pointFormat': '<tr><td><b>{point.name} ({point.jersey})<b></td></tr>' +
                           '<tr><td>{point.mday}. Spieltag</td></tr>' +
                           '<tr><td>Zeit: {point.minute}</td></tr>',
            'footerFormat': '</table>',
            'followPointer': 1,
        },

        'plotOptions': {
            'scatter': {
                'marker': {'lineColor': '#e3e3ff', 'lineWidth': 1}
            },
            'series': {
                'borderWidth': 0,
                'lineColor': '#c00c18',
                'turboThreshold': 2000,
            },
        },

        'xAxis': {
            'visible': 0,
            'labels': {'enabled': 0},
            'min': -100,
            'max': 100,
            'tickInterval': 0,
        },

        'yAxis': {
            'visible': 0,
            'gridLineWidth': 0,
            'title': {
                'text': '',
            },
            'labels': {'enabled': 0},
            'min': 0,
            'max': 105,
            'tickInterval': 0,
        },

        'series': [
            {'color': '#7cb5ec', 'name': 'Gehalten', 'data': shot_map_dic['ebb'][1], 'zIndex': 2, 'marker': {'radius': marker_size, 'symbol': 'circle'}},
            {'color': '#d61825', 'name': 'Tor', 'data': shot_map_dic['ebb'][4], 'zIndex': 4, 'marker': {'radius': marker_size, 'symbol': 'circle'}},
        ],
    }

    if not filter_sog:
        chart_options['series'].append({'color': '#d8d9da', 'name': 'Vorbei', 'zIndex': 1, 'data': shot_map_dic['ebb'][2], 'marker': {'radius': marker_size, 'symbol': 'circle'}})
        chart_options['series'].append({'color': '#000052', 'name': 'Geblockt', 'zIndex': 3, 'data': shot_map_dic['ebb'][3], 'marker': {'radius': marker_size, 'symbol': 'circle'}})

    return chart_options

def get_game_toi(match_id, mobile_browser):
    """ get shotzone statistics """

    # get last rfilter matches and filter match-id from first entry
    match_list = Match.objects.filter(id=match_id, no_bet=False).values('id', 'date', 'matchday', 'home_team__short_name', 'home_team__team_name', 'home_team__logo_url', 'guest_team__short_name', 'guest_team__team_name', 'guest_team__logo_url', 'shots', 'del_date', 'shifts', 'playerstats')[:1]

    toi_chart = {}
    toi_table = {}
    if match_list:

        # inititialize dictionaries to store the data
        shifts_dic = {'ebb': {1: {}, 2: {}, 3: {}, 4: {}}}
        tmp_toi_sum_dic = {}

        # shifts and playerstats
        shifts_list = match_list[0]['shifts']
        playerstats = match_list[0]['playerstats']
        if shifts_list:
            # build dictionary based on shifts
            for shift in shifts_list:
                # filter ebb_shifts
                if shift['team']['id'] == 3:
                    # get the shift data we need
                    player_name = shift['player']['name']
                    period = math.ceil(shift['endTime']['time']/1200)
                    shift_duration = (shift['endTime']['time'] - shift['startTime']['time'])

                    if player_name not in shifts_dic['ebb'][period]:
                        shifts_dic['ebb'][period][player_name] = 0

                    shifts_dic['ebb'][period][player_name] += shift_duration
        else:
            # build dictionary based on playerstats (this is live - hopefully)
            for period in sorted(playerstats):
                for player in playerstats[period]:
                    # store values in a temporary dic as playerstats contains aggregated values only
                    if player['name'] not in tmp_toi_sum_dic:
                        tmp_toi_sum_dic[player['name']] = 0
                    if player['statistics']['timeOnIce'] > 0:
                        shifts_dic['ebb'][int(period)][player['name']] = player['statistics']['timeOnIce'] - tmp_toi_sum_dic[player['name']]
                        tmp_toi_sum_dic[player['name']] = player['statistics']['timeOnIce']


        if shifts_dic['ebb'][1]:
            toi_chart = create_gametoi_chart(shifts_dic, mobile_browser)
            toi_table = create_gametoi_table(shifts_dic)

    return(toi_chart, toi_table)

def create_gametoi_table(shifts_dic):
    """ create table including shots per persiod """

    table_dic = {'th': ['Name', '1. Drittel', '2. Drittel', '3. Drittel', 'OT',], 'align': ['left', None, None, None, None], 'td': []}

    playername_list = []
    if 'ebb' in shifts_dic:
        for period in shifts_dic['ebb']:
            for player_name in shifts_dic['ebb'][period]:
                if player_name not in playername_list:
                    playername_list.append(player_name)

    for player_name in sorted(playername_list):

        if player_name not in shifts_dic['ebb'][1]:
            p1_val = '00:00'
        else:
            p1_val = '{0:02d}:{1:02d}'.format(*divmod(shifts_dic['ebb'][1][player_name], 60))

        if player_name not in shifts_dic['ebb'][2]:
            p2_val = '00:00'
        else:
            p2_val = '{0:02d}:{1:02d}'.format(*divmod(shifts_dic['ebb'][2][player_name], 60))

        if player_name not in shifts_dic['ebb'][3]:
            p3_val = '00:00'
        else:
            p3_val = '{0:02d}:{1:02d}'.format(*divmod(shifts_dic['ebb'][3][player_name], 60))

        if player_name not in shifts_dic['ebb'][4]:
            p4_val = '00:00'
        else:
            p4_val = '{0:02d}:{1:02d}'.format(*divmod(shifts_dic['ebb'][4][player_name], 60))


        table_dic['td'].append([player_name, p1_val, p2_val, p3_val, p4_val])

    return table_dic

def create_gametoi_chart(shifts_dic, mobile_browser):
    """  create chart for the shots """

    # we need to change some setting for mobile access
    if mobile_browser:
        label_size = '8px'
        show_legend = 1
        v_align = 'top'
    else:
        label_size = '10px'
        v_align = 'bottom'
        show_legend = 1

    # create x axis with player names
    x_list = []
    y_dic = {1: [], 2: [], 3: [], 4: []}


    if 'ebb' in shifts_dic:
        for period in shifts_dic['ebb']:
            for player_name in shifts_dic['ebb'][period]:
                if player_name not in x_list:
                    x_list.append(player_name)

        for period in shifts_dic['ebb']:
            for player_name in sorted(x_list):
                if player_name in shifts_dic['ebb'][period]:
                    # y_dic[period].append('{0:02d}:{1:02d}'.format(*divmod(shifts_dic['ebb'][period][player_name], 60)))
                    y_dic[period].append({'y': shifts_dic['ebb'][period][player_name]/60, 'label': '{0:02d}:{1:02d}'.format(*divmod(shifts_dic['ebb'][period][player_name], 60))})
                else:
                    y_dic[period].append(0)

    title = ''
    chart_options = {

        'chart': {
            'type': 'bar',
            'height': '120%',
            'alignTicks': 0,
        },

        'exporting': {
            'chartOptions': {
                'plotOptions': {
                    'series': {
                        'dataLabels': {
                            'enabled': 0,
                        },
                    },
                },
            },
            'fallbackToExportServer': 0,
        },

        'title': {
            'text': title,
            'style': {'color': '#404040', 'font-size': '12px'},
        },

        'credits': {
            'text': 'Nach einer Idee von @h_modes',
            'href': 'https://twitter.com/h_modes'
        },

        'plotOptions': {
            'series': {
                'stacking': 'normal'
            }
        },

        'legend': {
            'enabled': show_legend,
            'useHTML': 1,
            'itemStyle': {'color': '#404040', 'font-size': label_size},
            'verticalAlign': v_align,
            'symbolRadius': 0,
        },

        'tooltip': {
            'shared': 1,
            'useHTML': 1,
            'headerFormat': '<span style="font-size: %s"><b>{point.x}</b></span><br/>' % label_size,
            'pointFormat': '<span style="color:{point.color}">\u25CF</span> <span style="font-size: %s">{series.name}: {point.label}</span><br/>' % label_size,
        },

        'xAxis': {
            'categories': sorted(x_list),
            'title': {
                'text': '',
                'style': {'color': '#404040', 'font-size': label_size},
            },
            'labels': {'style': {'fontSize': label_size},},
            'tickInterval': 1,
            'showFirstLabel': 1,
            'showLastLabel': 1,
        },

        'yAxis':
            {
                'title': {
                    'text': 'Eiszeit',
                    'style': {'color': '#404040', 'font-size': label_size},
                },
                #'max': y1_max,
                'reversedStacks': 0,
                'tickInterval': 1,
                'maxPadding': 0.1,
                'labels': {'style': {'fontSize': label_size},},
            },

        'series': [{
            'name': '1. Drittel',
            'data': y_dic[1],
            'color': '#000052',
        }, {
            'name': '2. Drittel',
            'data': y_dic[2],
            'color': '#7cb5ec'
        }, {
            'name': '3. Drittel',
            'data': y_dic[3],
            'color': '#b0b3b5',

        }, {
            'name': 'OT',
            'data': y_dic[4],
            'color': '#68717a',
        }]
    }

    return chart_options

def get_game_corsi(match_id, mobile_browser, five_filter=False, sel_id=10):
    """ get game corsi stats """

    # get last rfilter matches and filter match-id from first entry
    match_list = Match.objects.filter(id=match_id, no_bet=False).values('id', 'date', 'matchday', 'home_team__short_name', 'home_team__team_name', 'home_team__logo_url', 'guest_team__short_name', 'guest_team__team_name', 'guest_team__logo_url', 'shots', 'del_date', 'period_events', 'roster', 'shifts')[:1]

    corsi_chart = {}
    corsi_table = {}

    if match_list:
        player_corsi_dic = get_single_corsi(match_list[0], five_filter)
        if match_list[0]['home_team__short_name'] == 'EBB':
            home_match = True
        else:
            home_match = False

        player_corsi_dic = add_lineup_to_corsi(player_corsi_dic, match_id, home_match)
        if player_corsi_dic:
            if sel_id == 10:
                if player_corsi_dic:
                    corsi_chart = create_corsi_per_player_chart(player_corsi_dic, mobile_browser)
            else:
                corsi_chart = create_corsi_per_player_pctg_chart(player_corsi_dic, mobile_browser)

            corsi_table = create_player_corsi_table(player_corsi_dic, sel_id)

    return(corsi_chart, corsi_table)

def add_lineup_to_corsi(player_corsi_dic, match_id, home_match):
    """ encrich corsi dic with lineup """

    lineup_list = list(Lineup.objects.filter(match_id=match_id).values_list('raw_json', flat=True)[:1])

    tmp_dic = {}
    if lineup_list:
        for player in lineup_list[0]:
            if home_match:
                if player['homePlayerNumber'] and player['lineNumber'] and player['homePlayerName']:
                    tmp_dic[player['homePlayerNumber']] = player['lineNumber']
            else:
                if player['guestPlayerNumber'] and player['lineNumber'] and player['guestPlayerName']:
                    tmp_dic[player['guestPlayerNumber']] = player['lineNumber']

        if player_corsi_dic:
            for player in player_corsi_dic:
                if player_corsi_dic[player]['jersey'] in tmp_dic:
                    player_corsi_dic[player]['line_number'] = tmp_dic[player_corsi_dic[player]['jersey']]

    return player_corsi_dic


def get_single_corsi(match, five_filter):
    """ get corsi stats """

    # print(match)

    # initialize variables
    player_corsi_dic = {}
    home_match = False

    if match['home_team__short_name'] == 'EBB':
        home_match = True
        oteam_name = match['guest_team__short_name']
    else:
        oteam_name = match['home_team__short_name']

    # these are the shifts
    shifts_list = match['shifts']
    (soi_dict, toi_dic) = get_skaters_on_ice(shifts_list, oteam_name)

    # add period events
    period_events = match['period_events']
    soi_dict = add_penalties(soi_dict, period_events, oteam_name, home_match)

    scorer_dic = get_scorers_from_events(period_events)

    # here are the shots
    shot_list = match['shots']
    if shot_list:
        for shot in shot_list['match']['shots']:

            # skip goals
            # if shot['match_shot_resutl_id'] == 4:
            #    continue

            if shot['team_id'] == 3:
                shot_type = 'shots'
            else:
                shot_type = 'shots_against'

            # do we have to count the shot
            if five_filter:
                # 5v5 is ok we can count it
                if soi_dict['EBB'][shot['time']]['count'] == 5 and soi_dict[oteam_name][shot['time']]['count'] == 5:
                # if soi_dict['EBB'][shot['time']]['count'] == soi_dict[oteam_name][shot['time']]['count']:
                    count_it = True
                # elif soi_dict['EBB'][shot['time']]['count'] == 4 and soi_dict[oteam_name][shot['time']]['count'] == 4:
                #     count_it = True
                else:
                    count_it = False
            else:
                count_it = True

            if count_it:
                for player in soi_dict['EBB'][shot['time']]['player_list']:
                    if player not in player_corsi_dic:
                        player_corsi_dic[player] = {'shots': 0, 'shots_against': 0, 'name': player}
                    player_corsi_dic[player][shot_type] += 1

        # here are the roster
        roster_list = match['roster']

        if home_match:
            selector = 'home'
        else:
            selector = 'visitor'

        for player in roster_list[selector]:
            if roster_list[selector][player]['position'] != 'GK':
                player_name = '{0} {1}'.format(roster_list[selector][player]['name'], roster_list[selector][player]['surname'])
                if player_name in player_corsi_dic:
                    player_corsi_dic[player_name]['jersey'] = roster_list[selector][player]['jersey']
                    player_corsi_dic[player_name]['player_id'] = roster_list[selector][player]['playerId']
                else:
                    player_corsi_dic[player_name] = {'shots': 0, 'shots_against': 0, 'name': player_name, 'jersey': roster_list[selector][player]['jersey'], 'player_id': roster_list[selector][player]['playerId']}

                if player_name in toi_dic['EBB']:
                    player_corsi_dic[player_name]['toi'] = toi_dic['EBB'][player_name]
                else:
                    player_corsi_dic[player_name]['toi'] = 1

                if player_corsi_dic[player_name]['jersey'] in scorer_dic['scorer_list']:
                    player_corsi_dic[player_name]['goal'] = True

                if player_corsi_dic[player_name]['jersey'] in scorer_dic['assist_list']:
                    player_corsi_dic[player_name]['assist'] = True

                if player_corsi_dic[player_name]['shots'] + player_corsi_dic[player_name]['shots_against'] == 0:
                    player_corsi_dic[player_name]['cf_pctg'] = 0
                else:
                    player_corsi_dic[player_name]['cf_pctg'] = int(round(player_corsi_dic[player_name]['shots'] * 100/(player_corsi_dic[player_name]['shots'] + player_corsi_dic[player_name]['shots_against']), 0))

                player_corsi_dic[player_name]['corsi'] = player_corsi_dic[player_name]['shots'] - player_corsi_dic[player_name]['shots_against']

    return player_corsi_dic

def create_player_corsi_table(player_corsi_dic, sel_id=10):
    """ create table including shots per persiod """

    if sel_id == 10:
        sorter = 'corsi'
    else:
        sorter = 'cf_pctg'

    table_dic = {'th': ['Name', '#', 'CF 5v5', 'CA 5v5', 'Corsi', 'CF% 5v5', 'Eiszeit'], 'align': ['left', None, None, None, None, None, None], 'tooltip': [None, None, 'Schüsse der Eisbären bei Spieler auf dem Eis', 'Schüsse der Gegner bei Spieler auf dem Eis', 'Plus-/Minus-Bilanz aller Schüsse', 'Prozentuale Plus-/Minus-Bilanz aller Schüsse', None, None], 'td': []}
    #  sorted(shots_per_payer_dic.values(), key=lambda x: x['shots'], reverse=True)
    for player in sorted(player_corsi_dic.values(), key=lambda x: x[sorter], reverse=True):
        # print(player_name)
        table_dic['td'].append([player['name'], player['jersey'], player['shots'], player['shots_against'], player['corsi'], '{0}%'.format(player['cf_pctg']), '{0:02d}:{1:02d}'.format(*divmod(player['toi'], 60))])

    return table_dic

def get_skaters_on_ice(shifts_list, oteam_name):
    """ reconstruct skaters per second """

    skaters_on_ice_dic = {'EBB': {}, oteam_name: {}}
    toi_dic = {'EBB': {}, oteam_name: {}}

    # get time stamp of last entry
    try:
        time_end = shifts_list[-1]['endTime']['time']
    except BaseException:
        time_end = 3900

    # create game timeline in second interval
    for second_ in range(0, time_end + 20):
        skaters_on_ice_dic['EBB'][second_] = {'player_list': [], 'count': 0}
        skaters_on_ice_dic[oteam_name][second_] = {'player_list': [], 'count': 0}

    # add players to timeline based on shifts
    for shift in shifts_list:

        # store some values in variable for faster access
        shift_duration = (shift['endTime']['time'] - shift['startTime']['time'])
        player_name = shift['player']['name']
        # print(shift['startTime']['time'], shift['endTime']['time'], shift['player']['name'], shift['team']['id'])
        if shift['team']['id'] == 3:
            team_name = 'EBB'
        else:
            team_name = oteam_name

        # count time_on_ice per player
        if player_name not in toi_dic[team_name]:
            toi_dic[team_name][player_name] = 0
        toi_dic[team_name][player_name] += shift_duration

        for second_ in range(shift['startTime']['time']+1, shift['endTime']['time']+1):
            skaters_on_ice_dic[team_name][second_]['player_list'].append(player_name)
            skaters_on_ice_dic[team_name][second_]['count'] += 1

    return (skaters_on_ice_dic, toi_dic)

def add_penalties(soi_dic, period_events, oteam_name, home_match=False):
    """ add penalties to game dictionaties """

    for period in period_events:
        for event in period_events[period]:
            if event['type'] == 'penalty':
                if home_match:
                    if event['data']['team'] == 'home':
                        team_name = 'EBB'
                    else:
                        team_name = oteam_name
                else:
                    if event['data']['team'] == 'home':
                        team_name = oteam_name
                    else:
                        team_name = 'EBB'

                # ignoriere match strafen größer als 5min
                if event['data']['duration'] < 301:
                    for second_ in range(event['data']['time']['from']['scoreboardTime']+1, event['data']['time']['to']['scoreboardTime']+1):
                        if 'penalty' in soi_dic[team_name][second_]:
                            soi_dic[team_name][second_]['penalty'] = '{0}, {1}'.format(soi_dic[team_name][second_]['penalty'], event['data']['disciplinedPlayer']['surname'])
                        else:
                            if event['data']['disciplinedPlayer']:
                                soi_dic[team_name][second_]['penalty'] = event['data']['disciplinedPlayer']['surname']
                            else:
                                soi_dic[team_name][second_]['penalty'] = event['data']['replacedPlayer']['surname']

    return soi_dic

def get_scorers_from_events(period_events):
    """ create dictionry containing scorers and assists """

    scorer_dic = {'scorer_list': [], 'assist_list': []}
    for period in period_events:
        for event in period_events[period]:
            if event['type'] == 'goal':
                # store scorer
                if event['data']['scorer']['jersey'] not in scorer_dic['scorer_list']:
                    scorer_dic['scorer_list'].append(event['data']['scorer']['jersey'])
                # store assists
                for player in event['data']['assistants']:
                    if player['jersey'] not in scorer_dic['assist_list']:
                        scorer_dic['assist_list'].append(player['jersey'])

    return scorer_dic

def create_corsi_per_player_chart(player_corsi_dic, mobile_browser):
    """ create bubble chart for shots per player """

    # format data series in a way we need it
    data_list = {}
    tmp_pos_dic = {}

    shotsum_dic = {'shots': 0, 'shots_against': 0}

    scale_max = 0

    for player in sorted(player_corsi_dic.values(), key=lambda x: (x['shots'])):
        # count shotsum
        shotsum_dic['shots'] += player['shots']
        shotsum_dic['shots_against'] += player['shots_against']

        tmp_dic = {
            'x': player['shots'],
            'y': player['shots_against'],
            'mx': player['shots'],
            'my': player['shots_against'],
            'z': math.ceil(player['toi']/60),
            # 'z': 4,
            'name': player['name'],
            'mtoi': '{0:02d}:{1:02d}'.format(*divmod(player['toi'], 60)),
            'jersey': player['jersey'],
            'labelrank': 1,
            }

        if scale_max < player['shots']:
            scale_max = player['shots']
        if scale_max < player['shots_against']:
            scale_max = player['shots_against']

        # hack to fix bubble overlaps
        pos = '{0}:{1} '.format(player['shots'], player['shots_against'])
        if pos in tmp_pos_dic:
            tmp_dic['x'] += 0.5
            tmp_dic['y'] += 0.5
            tmp_pos_dic[pos] = '{0}:{1} '.format(tmp_dic['x'], tmp_dic['y'])
        else:
            tmp_pos_dic[pos] = 1

        if 'line_number' in player:
            if player['line_number'] not in data_list:
                data_list[player['line_number']] = []
            tmp_dic['labelrank'] = 5 - player['line_number']
            data_list[player['line_number']].append(tmp_dic)
        else:
            tmp_dic['labelrank'] = 1
            if 4 not in data_list:
                data_list[4] = []
            data_list[4].append(tmp_dic)

    shotsum_dic['shots_avg'] = round(shotsum_dic['shots'] / len(player_corsi_dic.keys()), 0)
    shotsum_dic['shots_against_avg'] = round(shotsum_dic['shots_against'] / len(player_corsi_dic.keys()), 0)

    # we need to change some setting for mobile access
    if mobile_browser:
        label_size = '8px'
        # show_legend = 1
        v_align = 'top'
        min_size = 3
        max_size = 35
    else:
        label_size = '10px'
        v_align = 'bottom'
        min_size = 3
        max_size = 50
        # show_legend = 1

    title = ''

    chart_options = {

        'chart': {
            'type': 'bubble',
            'plotBorderWidth': 1,
            'zoomType': 'xy',
            'height': '105%',
        },

        'exporting': {
            'chartOptions': {
                'plotOptions': {
                    'series': {
                        'dataLabels': {
                            'enabled': 0,
                        },
                    },
                },
            },
            'fallbackToExportServer': 0,
        },

        'legend': {
            'enabled': 1,
            'itemStyle': {'color': '#404040', 'font-size': label_size},
            'verticalAlign': v_align,
            'squareSymbol': 1,
        },

        'title': {
            'text': title,
        },

        'credits': {
            'text': 'Nach einer Idee von @h_modes',
            'href': 'https://twitter.com/h_modes'
        },

        'tooltip': {
            'useHTML': 1,
            'headerFormat': '<table class="w3-tiny">',
            'pointFormat': '<tr><td colspan="3"><b>{point.name} ({point.jersey})<b></td></tr>' +
                           '<tr><td>Schüsse aufs gegnerische Tor:</td><td>{point.mx}</td></tr>' +
                           '<tr><td>Schüsse aufs eigene Tor:</td><td>{point.my}</td></tr>' +
                           '<tr><td>Eiszeit:</td><td>{point.mtoi}m</td></tr>',
            'footerFormat': '</table>',
            'followPointer': 1,
        },

        'plotOptions': {
            'series': {
                'dataLabels': {
                    'enabled': 1,
                    # 'color': '#000000',
                    'style': {'textShadow': 0, 'textOutline': 0, 'fontSize': label_size},
                    'format': '{point.jersey}',
                },
                # 'color': 'rgba(216, 217, 218, 6)',
                # 'borderWidth': 0,
                'color': 'rgba(189, 191, 193, 6)',
                'lineColor': '#c00c18',
            },
            'bubble': {
                'minSize': min_size,
                'maxSize': max_size,
            }
        },

        'xAxis': {
            'gridLineWidth': 1,
            'title': {
                'text': 'Schüsse der Eisbären mit Spieler auf dem Eis bei 5v5 (CF)',
                'style': {'color': '#404040', 'font-size': label_size},
            },
            'labels': {'style': {'fontSize': label_size}},
            'plotLines': [{'color': '#d8d9da', 'width': 2, 'value': shotsum_dic['shots_avg']}],
            'min': 0,
            # 'max': scale_max,
            'tickInterval': 1,
            'showFirstLabel': 1,
            'showLastLabel': 1,
        },
        'yAxis': {
            'title': {
                'text': 'Schüsse des Gegners mit Spieler auf dem Eis bei 5v5 (CA)',
                'style': {'color': '#404040', 'font-size': label_size},
            },
            'labels': {'style': {'fontSize': label_size},},
            'plotLines': [{'color': '#d8d9da', 'width': 2, 'value': shotsum_dic['shots_against_avg']}],
            'min': 0,
            # 'max': scale_max,
            'reversed': 1,
            'tickInterval': 1,
            'showFirstLabel': 1,
            'showLastLabel': 1,
        },

        'series': [],
    }

    data_dic = {1: '#333333', 2: '#595959', 3: '#8c8c8c', 4: '#bfbfbf', 5: '#f2f2f2'}
    if len(data_list) == 1:
        chart_options['series'].append({'name': 'Spieler', 'data': list(data_list.values())[0], 'zIndex': 1, 'marker': {'fillOpacity': 0.7}})
    else:
        for line in sorted(data_dic.keys()):
            if line in data_list:
                chart_options['series'].append({'name': '{0}. Reihe'.format(line), 'data': data_list[line], 'zIndex': 5-line, 'color': data_dic[line], 'marker': {'fillOpacity': 0.7}})

    return chart_options

def create_corsi_per_player_pctg_chart(player_corsi_dic, mobile_browser):
    """  create chart for the shots """

    # we need to change some setting for mobile access
    if mobile_browser:
        label_size = '8px'
        show_legend = 1
        v_align = 'top'
    else:
        label_size = '10px'
        v_align = 'bottom'
        show_legend = 1

    # create x axis with player names
    x_list = []
    y_dic = {'shots': [], 'shots_against': []}

    shot_sum = 0
    count = 0
    for player in sorted(player_corsi_dic.values(), key=lambda x: x['cf_pctg'], reverse=True):

        x_list.append(player['name'])
        y_dic['shots'].append(player['cf_pctg'])
        y_dic['shots_against'].append(100 - player['cf_pctg'])
        count += 1
        shot_sum = shot_sum + player['cf_pctg']

    title = ''
    chart_options = {

        'chart': {
            'type': 'bar',
            'height': '120%',
            'alignTicks': 0,
        },

        'exporting': {
            'chartOptions': {
                'plotOptions': {
                    'series': {
                        'dataLabels': {
                            'enabled': 0,
                        },
                    },
                },
            },
            'fallbackToExportServer': 0,
        },

        'title': {
            'text': title,
            'style': {'color': '#404040', 'font-size': '12px'},
        },

        'plotOptions': {
            'bar': {
                'stacking': 'percent',
                'dataLabels': {
                    'enabled': 1,
                    'color': '#FFFFFF',
                    'format': '{y} %',
                    'useHTML': 1
                }
            }
        },

        'legend': {
            'enabled': show_legend,
            'useHTML': 1,
            'itemStyle': {'color': '#404040', 'font-size': label_size},
            'verticalAlign': v_align,
            'symbolRadius': 0,
        },

        'tooltip': {
            'enabled': 0,
            'shared': 1,
            'useHTML': 1,
            'headerFormat': '<span style="font-size: %s"><b>{point.x}</b></span><br/>' % label_size,
            'pointFormat': '<span style="color:{point.color}">\u25CF</span> <span style="font-size: %s">{series.name}: {point.label}</span><br/>' % label_size,
        },

        'xAxis': {
            'categories': x_list,
            'title': {
                'text': '',
                'style': {'color': '#404040', 'font-size': label_size},
            },
            'labels': {'style': {'fontSize': label_size},},
            'tickInterval': 1,
            'showFirstLabel': 1,
            'showLastLabel': 1,
        },

        'yAxis':
            {
                'title': {
                    'text': 'Prozentuale Schussquote',
                    'style': {'color': '#404040', 'font-size': label_size},
                },
                #'max': y1_max,
                'reversedStacks': 0,
                'tickInterval': 25,
                'maxPadding': 0.1,
                'labels': {'style': {'fontSize': label_size}},
                'plotLines': [{'color': '#d8d9da', 'width': 3, 'value': int(shot_sum/count)}]
            },

        'series': [{
            'name': 'Schüsse der Eisbären mit Spieler auf dem Eis bei 5v5 (%)',
            'data': y_dic['shots'],
            'color': '#030357'
        }, {
            'name': 'Schüsse des Gegners mit Spieler auf dem Eis bei 5v5 (%)',
            'data': y_dic['shots_against'],
            'color': '#b0b3b5',
            'dataLabels': 0,
        }]
    }

    return chart_options

def get_season_player_corsi(season_id, five_filter=False):
    """ get corsi per player per season """

    # get last rfilter matches and filter match-id from first entry
    match_list = Match.objects.filter(season=season_id, no_bet=False).exclude(matchday=0).values('id', 'date', 'matchday', 'home_team__short_name', 'home_team__team_name', 'home_team__logo_url', 'guest_team__short_name', 'guest_team__team_name', 'guest_team__logo_url', 'shots', 'del_date', 'period_events', 'roster', 'shifts')

    season_player_dic = {}
    if match_list:
        for match in match_list:
            player_corsi_dic = get_single_corsi(match, five_filter)

            for player_name in player_corsi_dic:
                player_id = player_corsi_dic[player_name]['player_id']
                if player_id not in season_player_dic:
                    season_player_dic[player_id] = {'name': player_name, 'jersey': player_corsi_dic[player_name]['jersey'], 'cf_shots': 0, 'ca_shots': 0, 'cf_toi': 0}

                season_player_dic[player_id]['cf_shots'] = season_player_dic[player_id]['cf_shots'] + player_corsi_dic[player_name]['shots']
                season_player_dic[player_id]['ca_shots'] = season_player_dic[player_id]['ca_shots'] + player_corsi_dic[player_name]['shots_against']
                season_player_dic[player_id]['cf_toi'] = season_player_dic[player_id]['cf_toi'] + player_corsi_dic[player_name]['toi']

        # go over dictionary and calculate some values
        for player_id in season_player_dic:
            if season_player_dic[player_id]['cf_shots'] + season_player_dic[player_id]['ca_shots'] == 0:
                season_player_dic[player_id]['cf_pctg'] = 0
            else:
                season_player_dic[player_id]['cf_pctg'] = '{0}%'.format(int(round(season_player_dic[player_id]['cf_shots'] * 100/(season_player_dic[player_id]['cf_shots'] + season_player_dic[player_id]['ca_shots']), 0)))
            season_player_dic[player_id]['cf_corsi'] = season_player_dic[player_id]['cf_shots'] - season_player_dic[player_id]['ca_shots']

    return season_player_dic

def get_playoff_list(u_season_id):
    """" get playoff result """

    playoff_list = []
    playofftree_list = Playofftree.objects.filter(season=u_season_id).values('tree')

    # create team list
    teamlogo_dic = {}
    team_list = Team.objects.order_by('team_id').values('short_name', 'logo_url')
    for team in team_list:
        teamlogo_dic[team['short_name']] = team['logo_url']

    playoff_dic = {
        1: {'class': 'round-one', 'name': '1. Playoff-Runde', 'matches': 2},
        2: {'class': 'round-two', 'name': 'Viertelfinale', 'matches': 4},
        3: {'class': 'round-three', 'name': 'Halbfinale', 'matches': 2},
        4: {'class': 'round-four', 'name': 'Finale', 'matches': 1}
    }

    playoff_list = []
    if playofftree_list:
        playoff_tree = playofftree_list[0]['tree']
        for idx, round_ in enumerate(playoff_tree['round']):
            tmp_dic = {'name': playoff_dic[idx+1]['name'], 'class': playoff_dic[idx+1]['class'], 'series': [], 'active': round_['active']}
            for series in round_['series']:
                home_logo = None
                guest_logo = None
                loop_dic = {'home_name': series['teams'][0]['shortcut'], 'home_wins': series['teams'][0]['seriesScore'], 'home_winner': series['teams'][0]['winner'], 'home_ranking': series['teams'][0]['ranking'], 'guest_name': series['teams'][1]['shortcut'], 'guest_wins': series['teams'][1]['seriesScore'], 'guest_ranking': series['teams'][1]['ranking'], 'guest_winner': series['teams'][1]['winner']}
                if series['teams'][0]['shortcut'] in teamlogo_dic:
                    loop_dic['home_logo'] = teamlogo_dic[series['teams'][0]['shortcut']]
                if series['teams'][1]['shortcut'] in teamlogo_dic:
                    loop_dic['guest_logo'] = teamlogo_dic[series['teams'][1]['shortcut']]
                tmp_dic['series'].append(loop_dic)
            playoff_list.append(tmp_dic)

        if (len(playoff_list) < 4):
            """ we are missing entries in playoff list """
            for num in range(len(playoff_list) + 1, 5):
                tmp_dic = {'name': playoff_dic[num]['name'], 'class': playoff_dic[num]['class'], 'series': [], 'active': 0}
                for match_ in range(0, playoff_dic[num]['matches']):
                    tmp_dic['series'].append({'home_name': '', 'guest_name': ''})
                playoff_list.append(tmp_dic)

        # sort playoff_list ccording to results
        if playoff_list:
            playoff_list = sort_playoff_list(playoff_list)

    return playoff_list

def sort_playoff_list(playoff_list):
    """ sort playoff list more or less successfull"""

    idx_dic = {1: []}

    # define sort list for 2nd round based on results of first round
    if playoff_list[0]['series'][0]['home_winner']:
        idx_dic[1] = [1, 2, 0, 3]
        # if leader wins match get moved to lower part
        if playoff_list[1]['series'][0]['home_winner']:
            idx_dic[2] = [1, 0]
        else:
            idx_dic[2] = [0, 1]
    elif playoff_list[0]['series'][0]['guest_winner']:
        idx_dic[1] = [0, 2, 1, 3]
        if playoff_list[1]['series'][0]['home_winner']:
            idx_dic[2] = [0, 1]
        else:
            idx_dic[2] = [1, 0]
    else:
        idx_dic[1] = [0, 1, 2, 3]

    sorted_playoff_list = []
    for idx, round_ in enumerate(playoff_list):
        # print(idx)
        if idx in idx_dic:
            tmp_list = []
            for cnt in idx_dic[idx]:
                tmp_list.append(round_['series'][cnt])
            round_['series'] = tmp_list
            sorted_playoff_list.append(round_)
        else:
            sorted_playoff_list.append(round_)

    return(sorted_playoff_list)

def get_playernerdstats(mobile_browser, season_id, sel_id, number):
    """ main function to create the nerdstats """

    # stats for a certain player for all season matches
    player_match_list = Playerstatpermatch.objects.filter(season_id=season_id, number=number).order_by('match_id').values('match__date', 'match__matchday', 'match__home_team__short_name', 'match__guest_team__short_name', 'shotsinfo', 'full_name', 'time_on_ice_seconds', 'goals', 'shots', 'shfoi', 'shaoi')

    # unix timestamp
    uts = int(time.time())
    # get list of past season match_days
    matchday_list = list(Match.objects.filter(season_id=season_id, date__lt=uts, no_bet=False).order_by('date', 'matchday').values_list('matchday', flat=True))

    # calculate matchdate
    match_date = 0
    for match in player_match_list:
         if match_date < match['match__date']:
            match_date = match['match__date']

    # get matchdate
    match_date = datetime.datetime.fromtimestamp(int(match_date)).strftime('%d.%m.%Y')

    # filter out shotmap
    if sel_id in (1, 2, 4, 5, 6, 7):
        player_chart = get_playershotspermatch(player_match_list, matchday_list, mobile_browser, sel_id)
    elif sel_id == 3:
        player_chart = get_playershotmap(player_match_list, mobile_browser)
    elif sel_id == 8:
        player_chart = get_playershotzones(player_match_list, mobile_browser)

    return (player_chart, match_date)

def get_player_info(u_season_id, number):
    """ get player_info """

    player_list = get_player_stat_list(u_season_id, 1)

    number_list = []
    player_info_dic = {}
    # go over list and check entries
    for ele in player_list:
        for player in ele:
            if isinstance(player, dict):
                # select number
                if 'number' in player:
                    number_list.append(player['number'])
                    if player['number'] == number:
                        player_info_dic = player

    number_list = sorted(number_list)
    idx = number_list.index(number)

    # calculate index
    pnumber = None
    nnumber = None
    if idx > 0:
        pnumber = number_list[idx-1]
    if idx < len(number_list)-1:
        nnumber = number_list[idx+1]

    # fix player position
    pos_dic = {'S': 'Stürmer', 'V': 'Verteidiger', 'F': 'Stürmer'}
    lr_dic = {'L': 'links', 'R': 'rechts'}
    player_info_dic['position_full'] = pos_dic[player_info_dic['position']]
    player_info_dic['shoots_full'] = lr_dic[player_info_dic['shoots']]

    return (player_info_dic, pnumber, nnumber)

def get_playershotspermatch(match_list, matchday_list, mobile_browser, sel_id):
    """ get shots per match """

    match_shots_dic = {}

    for match in match_list:
        if match['shotsinfo']:
            sog = 0
            # get matchdate
            match_date = datetime.datetime.fromtimestamp(int(match['match__date'])).strftime('%d.%m.%Y')
            # iterate shots
            for shot in match['shotsinfo']:
                if shot['match_shot_resutl_id'] in (1, 4):
                    sog += 1
            match_shots_dic[match['match__matchday']] = {
                'goals': match['goals'],
                'toi': match['time_on_ice_seconds'],
                'sog': sog,
                'shots': match['shots'],
                'shfoi': match['shfoi'],
                'shaoi': match['shaoi'],
                'sog60': round(sog * 3600/ match['time_on_ice_seconds'], 2),
                'sh60': round(match['shots'] * 3600/ match['time_on_ice_seconds'], 2),
                'mname': '{0} vs. {1}'.format(match['match__home_team__short_name'], match['match__guest_team__short_name'])
                }

    # trigger chart creation
    if sel_id == 1:
        stat_chart = create_player_shot_chart(matchday_list, match_shots_dic, mobile_browser)
    elif sel_id == 2:
        stat_chart = create_player_shot_chart(matchday_list, match_shots_dic, mobile_browser, True)
    elif sel_id == 4:
        stat_chart = create_player_scoringpctg_chart(matchday_list, match_shots_dic, mobile_browser)
    elif sel_id == 5:
        stat_chart = create_player_toi_chart(matchday_list, match_shots_dic, mobile_browser)
    elif sel_id == 6:
        stat_chart = create_player_corsi_chart(matchday_list, match_shots_dic, mobile_browser)
    elif sel_id == 7:
        stat_chart = create_player_corsipctg_chart(matchday_list, match_shots_dic, mobile_browser)


    return stat_chart

def get_playershotmap(match_list, mobile_browser):
    """ create shotmap for a player for entire season """

    shot_map_dic = {'ebb': {1: [], 2: [], 3: [], 4: []}}

    for match in match_list:
        if match['shotsinfo']:
            # check home_match
            if match['match__home_team__short_name'] == 'EBB':
                home_match = True
            else:
                home_match = False

            # get matchdate
            match_date = datetime.datetime.fromtimestamp(int(match['match__date'])).strftime('%d.%m.%Y')

            for shot in match['shotsinfo']:
                # fix shot-time 0
                if shot['time'] == 0:
                    shot['time'] = 1

                if home_match:
                    # flip counter clockwise for road_game
                    shot['x'] = shot['coordinate_y'] * -1
                    shot['y'] = shot['coordinate_x']
                else:
                    # flip clockwise for road_game
                    shot['x'] = shot['coordinate_y']
                    shot['y'] = shot['coordinate_x'] * -1

                tmp_dic = {
                    'x': shot['x'],
                    'y': shot['y'],
                    # 'z': 2,
                    'name': match_date,
                    'jersey': '{0} vs. {1}'.format(match['match__home_team__short_name'], match['match__guest_team__short_name']),
                    'minute': '{0:02d}:{1:02d}'.format(*divmod(shot['time'], 60)),
                    'mday': match['match__matchday'],
                }
                shot_map_dic['ebb'][shot['match_shot_resutl_id']].append(tmp_dic)

    shot_map = create_seaon_shotmap_chart(shot_map_dic, mobile_browser, False, 1.2)

    return shot_map

def get_playershotzones(match_list, mobile_browser):
    """ get player shot zones """

    zone_dic = {}

    for match in match_list:
        if match['shotsinfo']:
            for shot in match['shotsinfo']:
                # print(shot['zone'], shot['match_shot_resutl_id'])
                if shot['zone'] not in zone_dic:
                    zone_dic[shot['zone']] = {'shots': 0, 'sog': 0, 'goals': 0}
                # count shots
                zone_dic[shot['zone']]['shots'] += 1
                # count sog
                if shot['match_shot_resutl_id'] in (1, 4):
                    zone_dic[shot['zone']]['sog'] += 1
                    if shot['match_shot_resutl_id'] == 4:
                        zone_dic[shot['zone']]['goals'] += 1

    from pprint import pprint
    pprint(zone_dic)

    return zone_dic
