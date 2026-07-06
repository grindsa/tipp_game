""" admin view """
# pylint: disable=W0212
from datetime import datetime
import pytz
from django.contrib import admin
from django.contrib.auth.models import Group
from django.contrib.auth.admin import GroupAdmin

# Register your models here.
from game.models import Team, Match, Season, Tip, Referee, Refpermatch, Playofftree, Usersetting, Groupsetting, Ranking, Presence, Yowsupd, Delmatch, Goal, Featurerequest, Ehcevent, Lineup, Playerstataggr, Goaliestataggr, Teamstat, Pnalty, Visitor, Playerstatpermatch, Playerstatebb

# unregister group (needed for customization)
admin.site.unregister(Group)
# admin.site.unregister(User)

class TeamAdmin(admin.ModelAdmin):
    """ teamadmin"""
    fields = ['team_name', 'short_name', 'logo_url', 'radio_url', 'latitude', 'longitude', 'matches', 'ebb_wins', 'ebb_losses', 'ebb_ot_wins', 'ebb_ot_losses', 'ebb_ps_wins', 'ebb_ps_losses', 'del_team', 'del_teamid']
    list_display = ('team_name', 'short_name', 'logo_url', 'radio_url', 'latitude', 'longitude', 'matches', 'ebb_wins', 'ebb_losses', 'del_team', 'del_teamid')
    ordering = ('team_name', )

class MatchAdmin(admin.ModelAdmin):
    """ matchadmin """
    list_display = ('id', 'get_season', 'matchday', 'uts_to_date', 'date', 'get_home_team', 'get_guest_team', 'result', 'penalty', 'tv', 'done', 'remaining', 'period_cnt', 'last_ebbticker_id', 'delapp_game_id')
    ordering = ('id', 'season', 'matchday', 'tv', 'done', 'tw_idstr')

    @staticmethod
    def uts_to_date(obj):
        """ convert unix timestamp to date format """
        date_string = datetime.fromtimestamp(obj.date, tz=pytz.timezone('Europe/Berlin')).strftime('%d.%m.%Y %H:%M:%S')
        return date_string

    @staticmethod
    def get_home_team(obj):
        """ get home team """
        return obj.home_team.team_name
    @staticmethod
    def get_guest_team(obj):
        """ get gueest team """
        return obj.guest_team.team_name
    @staticmethod
    def get_season(obj):
        """ get season """
        return obj.season.name

class PlayofftreeAdmin(admin.ModelAdmin):
    """ delmatchadmin"""
    list_display = ['season', 'tree']
    ordering = ['season']

class SeasonAdmin(admin.ModelAdmin):
    """ delmatchadmin"""
    list_display = ['name']
    ordering = ['name']

class DelmatchAdmin(admin.ModelAdmin):
    """ delmatchadmin"""
    list_display = ('get_season', 'matchday', 'date', 'get_home_team', 'get_guest_team', 'result', 'update_date')
    ordering = ('season', 'matchday')

    @staticmethod
    def get_season(obj):
        """ get season """
        return obj.season.name
    @staticmethod
    def get_home_team(obj):
        """ get home team """
        return obj.home_team.team_name
    @staticmethod
    def get_guest_team(obj):
        """ get gueest team """
        return obj.guest_team.team_name

class TipAdmin(admin.ModelAdmin):
    """ tippadmin """
    list_display = ('user', 'match', 'tip')
    ordering = ('match', 'user', 'tip')

class RefereeAdmin(admin.ModelAdmin):
    """ refereeadmin"""
    list_display = ('id', 'name')
    ordering = ('name', 'id')

class RefpermatchAdmin(admin.ModelAdmin):
    """ ref permatchadmin """
    list_display = ('match', 'r1', 'r2')
    ordering = ('match', 'r1', 'r2')

class UsersettingAdmin(admin.ModelAdmin):
    """ usersettingsadmin"""
    list_display = ('user', 'season', 'hide_tips', 'group', 'dkp', 'mobile_number', 'send_ticker')
    ordering = ('user', 'season', 'hide_tips', 'group')

class GroupProfileInline(admin.StackedInline):
    """ groupprofile admin """
    model = Groupsetting
    max_num = 1

class GroupProfileAdmin(GroupAdmin):
    """ groupprofileadmin """
    inlines = [GroupProfileInline]

class RankingAdmin(admin.ModelAdmin):
    """ rankingadmin """
    list_display = ('matchday', 'type', 'ranking', 'source', 'matchday', 'team', 'won', 'wono', 'wonp', 'losto', 'lostp', 'score', 'match', 'goal', 'ggoal', 'penalty')
    ordering = ('matchday', 'type', 'ranking')

class PresenceAdmin(admin.ModelAdmin):
    """ presenceadmin """
    list_display = ('match', 'user', 'date', 'latitude', 'longitude', 'geook')
    ordering = ('match', 'user', 'date', 'latitude', 'longitude', 'geook')

class YowsupdAdmin(admin.ModelAdmin):
    """ yowsupadmin """
    list_display = ('statement')
    ordering = ('statement')

class GoalAdmin(admin.ModelAdmin):
    """ goaladmin """
    list_display = ('match', 'period', 'time_second', 'time', 'name', 'score', 'zone', 'coordinate_x', 'coordinate_y', 'ebb')
    ordering = ('match', 'time_second', 'period', 'time', 'name', 'score')

class PnaltyAdmin(admin.ModelAdmin):
    """ penaltyadmin """
    list_display = ('match', 'period', 'time', 'name', 'duration', 'description', 'ebb')
    ordering = ('id', 'match', 'period', 'time', 'name', 'duration', 'description', 'ebb')

class VisitorAdmin(admin.ModelAdmin):
    """ visitoradmin """
    list_display = ('match', 'number')
    ordering = ('match', 'number')

class FeaturerequestAdmin(admin.ModelAdmin):
    """ featurerequestadmin """
    list_display = ('date', 'user', 'text', 'version')
    ordering = ('date', 'user', 'text', 'version')

class EhceventAdmin(admin.ModelAdmin):
    """ ehceventadmin """
    list_display = ('uts', 'date_human', 'time_human', 'location', 'event', 'lupdate')
    ordering = ('uts', 'date_human', 'time_human', 'location', 'event', 'lupdate')

class LineupAdmin(admin.ModelAdmin):
    """ lineupadmin """
    list_display = ('match', 'gk', 'r1', 'r2', 'r3', 'r4', 'lineup')
    ordering = ('match', 'gk', 'r1', 'r2', 'r3', 'r4', 'lineup')

class PlayerstataggrAdmin(admin.ModelAdmin):
    """ Playerstataggradmin """
    list_display = ('season', 'full_name', 'number', 'flag', 'contract_due', 'active', 'injured', 'position', 'shoots', 'games_played', 'goals', 'assists', 'points', 'pim', 'gw_goals', 'pp_goals', 'sh_goals', 'plus_minus', 'shots_on_goal', 'url')
    ordering = ('season', 'number', 'full_name')

class PlayerstatpermatchAdmin(admin.ModelAdmin):
    """ Playerstataggradmin """
    list_display = ('season', 'match', 'playerid', 'full_name', 'number', 'goals', 'assists', 'shots', 'time_on_ice_seconds', 'shotsinfo')
    ordering = ('season', 'match', 'playerid', 'full_name', 'number', 'goals', 'assists', 'shots', 'time_on_ice_seconds', 'shotsinfo')

class PlayerstatebbAdmin(admin.ModelAdmin):
    """ playerstatebb admin"""
    list_display = [field.name for field in Playerstatebb._meta.get_fields()]

class GoaliestataggrAdmin(admin.ModelAdmin):
    """ goalistatadmin """
    list_display = ('season', 'full_name', 'number', 'flag', 'contract_due', 'games_played', 'mip', 'mipp', 'goals_against', 'shots_against', 'saves', 'so', 'url')
    ordering = ('season', 'number', 'full_name')

class TeamstatAdmin(admin.ModelAdmin):
    """ teamstatadmin """
    list_display = ('date', 'season', 'match', 'wins_home', 'wins_away', 'loss_home', 'loss_away', 'goals_home', 'goals_away', 'ggoals_home', 'ggoals_away', 'ppe', 'she')
    ordering = ('date', 'season', 'match', 'wins_home', 'wins_away', 'loss_home', 'loss_away', 'goals_home', 'goals_away', 'ggoals_home', 'ggoals_away', 'ppe', 'she')

admin.site.register(Team, TeamAdmin)
admin.site.register(Match, MatchAdmin)
admin.site.register(Season, SeasonAdmin)
admin.site.register(Playofftree, PlayofftreeAdmin)
admin.site.register(Tip, TipAdmin)
# admin.site.register(Score, ScoreAdmin)
admin.site.register(Referee, RefereeAdmin)
admin.site.register(Refpermatch, RefpermatchAdmin)
admin.site.register(Usersetting, UsersettingAdmin)
admin.site.register(Group, GroupProfileAdmin)
admin.site.register(Ranking, RankingAdmin)
admin.site.register(Presence, PresenceAdmin)
admin.site.register(Delmatch, DelmatchAdmin)
admin.site.register(Goal, GoalAdmin)
admin.site.register(Pnalty, PnaltyAdmin)
admin.site.register(Visitor, VisitorAdmin)
admin.site.register(Featurerequest, FeaturerequestAdmin)
admin.site.register(Ehcevent, EhceventAdmin)
admin.site.register(Lineup, LineupAdmin)
admin.site.register(Playerstataggr, PlayerstataggrAdmin)
admin.site.register(Playerstatpermatch, PlayerstatpermatchAdmin)
admin.site.register(Playerstatebb, PlayerstatebbAdmin)
admin.site.register(Goaliestataggr, GoaliestataggrAdmin)
admin.site.register(Teamstat, TeamstatAdmin)
admin.site.register(Yowsupd)
