# -*- coding: utf-8 -*-
""" functions for tippgame """
# pylint: disable=C0302
from __future__ import print_function
from __future__ import absolute_import
import datetime
import time
import random
from functools import reduce
from urllib.request import urlopen
import binascii
import urllib3
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
from game.models import Team, Match, Tip, Referee, Usersetting, Groupsetting, Season, Presence, Yowsupd, Ranking, Delmatch, Refpermatch, Visitor, Playofftree
from game.libthreema import decode_key, tr_get_credits, encrypt, send_e2e, tr_lookup_pubkey, convert_byte_to_string
from trgw.models import Whatsappmessage
from trgw.models import Threemacredit
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
    if not Match.objects.filter(season=season_id).exclude(matchday=0).exists():
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

