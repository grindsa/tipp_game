""" tippgame models """
from django.db import models
from django.contrib.auth.models import User, Group
import jsonfield

# Create your models here.
class Team(models.Model):
    """ team table """
    team_id = models.AutoField(primary_key=True)
    team_name = models.CharField(max_length=30)
    short_name = models.CharField(max_length=5)
    logo_url = models.CharField(max_length=50)
    radio_url = models.CharField(max_length=100, blank=True, null=True)
    latitude = models.FloatField(default=0)
    longitude = models.FloatField(default=0)
    matches = models.IntegerField(default=0)
    ebb_wins = models.IntegerField(default=0)
    ebb_losses = models.IntegerField(default=0)
    ebb_ot_wins = models.IntegerField(default=0)
    ebb_ot_losses = models.IntegerField(default=0)
    ebb_ps_wins = models.IntegerField(default=0)
    ebb_ps_losses = models.IntegerField(default=0)
    goal = models.IntegerField(default=0)
    ebb_goal = models.IntegerField(default=0)
    del_team = models.BooleanField(default=False)
    del_teamid = models.IntegerField(default=0)
    def __unicode__(self):
        return self.team_name
    def __str__(self):
        return self.team_name

class Season(models.Model):
    """ season table """
    name = models.CharField(max_length=15)
    tournament_id = models.IntegerField(default=0)
    ranking_table = models.IntegerField(default=0)

    def __unicode__(self):
        return self.name
    def __str__(self):
        return self.name

class Playofftree(models.Model):
    """ playoff tree """
    season = models.ForeignKey(Season, on_delete=models.CASCADE)
    tree = jsonfield.JSONField(blank=True)

class Match(models.Model):
    """ match table """
    season = models.ForeignKey(Season, on_delete=models.CASCADE)
    matchday = models.IntegerField()
    date = models.IntegerField()
    home_team = models.ForeignKey(Team, related_name='home_team', on_delete=models.CASCADE)
    guest_team = models.ForeignKey(Team, related_name='guest_team', on_delete=models.CASCADE)
    result = models.CharField(max_length=5, blank=True, null=True)
    remaining = models.CharField(max_length=40, blank=True, null=True)
    tv = models.BooleanField(default=False)
    done = models.BooleanField(default=False)
    no_bet = models.BooleanField(default=False)
    period_cnt = models.IntegerField(default=0)
    video_url = models.CharField(max_length=120, blank=True, null=True)
    del_url = models.CharField(max_length=120, blank=True, null=True)
    tw_idstr = models.CharField(max_length=50, null=True, default=0)
    break_time = models.IntegerField(default=0)
    penalty = models.CharField(max_length=15, blank=True, null=True)
    last_ebbticker_id = models.IntegerField(default=0)
    delapp_game_id = models.IntegerField(default=0)
    scorebyperiod = models.CharField(max_length=50, null=True, default=0)
    gameresult = jsonfield.JSONField(default='["foo":"bar"]')
    roster = jsonfield.JSONField(default='["foo":"bar"]')
    del_date = models.IntegerField(default=0)
    playoff = models.BooleanField(default=False)

    def __str__(self):
        return str(self.matchday) +' - '+ str(self.home_team) + ' vs.' + str(self.guest_team)

class Visitor(models.Model):
    """ visitor table """
    match = models.ForeignKey(Match, on_delete=models.CASCADE)
    number = models.IntegerField(default=0)

class Tip(models.Model):
    """ tipp table """
    match = models.ForeignKey(Match, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    tip = models.CharField(max_length=5)
    date = models.IntegerField(default=0)
    luser = models.CharField(max_length=30, default='admin')

class Usersetting(models.Model):
    """ usersetting table """
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    season = models.ForeignKey(Season, default=1, on_delete=models.CASCADE)
    hide_tips = models.BooleanField(default=False)
    group = models.ForeignKey(Group, default=1, on_delete=models.CASCADE)
    threema = models.CharField(max_length=15, blank=True, null=True)
    threema_pk = models.CharField(max_length=120, blank=True, null=True)
    threema_reminder = models.BooleanField(default=False)
    send_ticker = models.IntegerField(default=0)
    sleep_counter = models.BooleanField(default=False)
    cheat_detector = models.BooleanField(default=False)
    dkp = models.DecimalField(max_digits=6, decimal_places=2, default=355)
    mobile_number = models.CharField(max_length=20, blank=True, null=True)
    dsgvo_ack = models.BooleanField(default=False)

class Groupsetting(models.Model):
    """ group setting table """
    group = models.ForeignKey(Group, on_delete=models.CASCADE)
    contact = models.CharField(max_length=25, blank=True, null=True)
    number = models.CharField(max_length=25, blank=True, null=True)
    p_winloss = models.IntegerField(default=0)
    p_diff = models.IntegerField(default=0)
    p_tipp = models.IntegerField(default=0)
    p_7vs2 = models.IntegerField(default=0)
    p_notip = models.IntegerField(default=0)
    rl_number = models.IntegerField(default=1)
    reminder = models.BooleanField(default=False)
    yao_message = models.BooleanField(default=False)
    alert = models.BooleanField(default=False)
    news_alert = models.BooleanField(default=False)
    oma_tip_ranks = models.IntegerField(default=0)
    oma_tip_list = models.CharField(max_length=25, blank=True)

class Referee(models.Model):
    """ referee names """
    name = models.CharField(max_length=30)
    def __unicode__(self):
        return self.name
    def __str__(self):
        return self.name

class Refpermatch(models.Model):
    """ referees per match """
    match = models.ForeignKey(Match, on_delete=models.CASCADE)
    r1 = models.ForeignKey(Referee, related_name='r1', on_delete=models.CASCADE)
    r2 = models.ForeignKey(Referee, related_name='r2', on_delete=models.CASCADE)

class Ranking(models.Model):
    """ ranking table """
    matchday = models.ForeignKey(Match, on_delete=models.CASCADE)
    ranking = models.IntegerField(default=0)
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    match = models.IntegerField(default=0)
    won = models.IntegerField(default=0)
    wono = models.IntegerField(default=0)
    wonp = models.IntegerField(default=0)
    losto = models.IntegerField(default=0)
    lostp = models.IntegerField(default=0)
    score = models.IntegerField(default=0)
    match = models.IntegerField(default=0)
    goal = models.IntegerField(default=0)
    ggoal = models.IntegerField(default=0)
    penalty = models.IntegerField(default=0)
    ppg = models.IntegerField(default=0)
    pps = models.IntegerField(default=0)
    ppp = models.FloatField(default=0)
    shga = models.IntegerField(default=0)
    ppga = models.IntegerField(default=0)
    shs = models.IntegerField(default=0)
    shp = models.FloatField(default=0)
    shg = models.IntegerField(default=0)
    season = models.ForeignKey(Season, default=4, on_delete=models.CASCADE)
    uts = models.IntegerField(default=0)
    source = models.CharField(max_length=20, blank=True)
    type = models.CharField(max_length=4, default='all')

class Presence(models.Model):
    """ presence table """
    match = models.ForeignKey(Match, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    date = models.IntegerField(default=0)
    latitude = models.FloatField(default=0)
    longitude = models.FloatField(default=0)
    geook = models.BooleanField(default=False)
    cheat = models.BooleanField(default=False)

class Delmatch(models.Model):
    """ del match """
    season = models.ForeignKey(Season, on_delete=models.CASCADE)
    matchday = models.IntegerField()
    date = models.IntegerField()
    home_team = models.ForeignKey(Team, related_name='h_team', on_delete=models.CASCADE)
    guest_team = models.ForeignKey(Team, related_name='g_team', on_delete=models.CASCADE)
    result = models.CharField(max_length=5, blank=True, null=True)
    status = models.CharField(max_length=50, blank=True, null=True)
    update_date = models.IntegerField(default=0)

class Goal(models.Model):
    """ goals """
    match = models.ForeignKey(Match, on_delete=models.CASCADE)
    period = models.CharField(max_length=20, blank=True, null=True)
    time = models.CharField(max_length=5, blank=True, null=True)
    time_second = models.IntegerField(default=0)
    name = models.CharField(max_length=50, blank=True, null=True)
    number = models.IntegerField(default=0)
    assistants = jsonfield.JSONField()
    score = models.CharField(max_length=10, blank=True, null=True)
    zone = models.CharField(max_length=20, blank=True, null=True)
    coordinate_x = models.FloatField(default=0)
    coordinate_y = models.FloatField(default=0)
    ebb = models.BooleanField(default=False)
    attendants = jsonfield.JSONField()

class Pnalty(models.Model):
    """ penalties """
    match = models.ForeignKey(Match, on_delete=models.CASCADE)
    period = models.CharField(max_length=20, blank=True, null=True)
    time = models.CharField(max_length=5, blank=True, null=True)
    name = models.CharField(max_length=50, blank=True, null=True)
    duration = models.IntegerField()
    description = models.IntegerField()
    ebb = models.BooleanField(default=False)

class Featurerequest(models.Model):
    """ feature requests """
    date = models.IntegerField()
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    text = models.CharField(max_length=200, blank=True, null=True)
    version = models.CharField(max_length=10, blank=True, null=True, default='')

class Ehcevent(models.Model):
    """ ehc events """
    uts = models.IntegerField()
    date_human = models.CharField(max_length=20, blank=True, null=True)
    time_human = models.CharField(max_length=20, blank=True, null=True)
    location = models.CharField(max_length=100, blank=True, null=True)
    event = models.CharField(max_length=100, blank=True, null=True)
    lupdate = models.CharField(max_length=20, blank=True, null=True)

class Lineup(models.Model):
    """ lineup """
    match = models.ForeignKey(Match, on_delete=models.CASCADE)
    gk = models.CharField(max_length=300, blank=True, null=True)
    r1 = models.CharField(max_length=300, blank=True, null=True)
    r2 = models.CharField(max_length=300, blank=True, null=True)
    r3 = models.CharField(max_length=300, blank=True, null=True)
    r4 = models.CharField(max_length=300, blank=True, null=True)
    r5 = models.CharField(max_length=300, blank=True, null=True)
    lineup = models.CharField(max_length=3000, blank=True, null=True)
    raw_json = jsonfield.JSONField()

class Playerstatpermatch(models.Model):
    """ playerstats """
    season = models.ForeignKey(Season, on_delete=models.CASCADE)
    match = models.ForeignKey(Match, on_delete=models.CASCADE)
    playerid = models.IntegerField(default=0)
    full_name = models.CharField(max_length=300)
    number = models.IntegerField(default=0)
    goals = models.IntegerField(default=0)
    shots = models.IntegerField(default=0)
    assists = models.IntegerField(default=0)
    shotsinfo = jsonfield.JSONField()
    position = models.CharField(max_length=5, blank=True)
    time_on_ice_seconds = models.IntegerField(default=0)
    shfoi = models.IntegerField(default=0)
    shaoi = models.IntegerField(default=0)

class Playerstataggr(models.Model):
    """ playerstats """
    season = models.ForeignKey(Season, on_delete=models.CASCADE)
    full_name = models.CharField(max_length=300)
    number = models.IntegerField()
    flag = models.CharField(max_length=100, blank=True)
    contract_due = models.CharField(max_length=10, blank=True)
    url = models.CharField(max_length=200, blank=True)
    player_id = models.IntegerField(default=0)
    weight = models.IntegerField(default=0)
    active = models.BooleanField(default=True)
    injured = models.BooleanField(default=False)

    position = models.CharField(max_length=5)
    shoots = models.CharField(max_length=10, blank=True)
    games_played = models.IntegerField(default=0)
    assists = models.IntegerField(default=0)
    points = models.IntegerField(default=0)

    # goals
    goals = models.IntegerField(default=0)
    slot_goals = models.IntegerField(default=0)
    slot_goal_pctg = models.FloatField(default=0)
    left_goals = models.IntegerField(default=0)
    left_goal_pctg = models.FloatField(default=0)
    right_goals = models.IntegerField(default=0)
    right_goal_pctg = models.FloatField(default=0)
    blue_line_goals = models.IntegerField(default=0)
    blue_line_goal_pctg = models.FloatField(default=0)
    neutral_zone_goals = models.IntegerField(default=0)
    neutral_zone_goal_pctg = models.FloatField(default=0)
    gw_goals = models.IntegerField(default=0)

    # shots
    shots = models.IntegerField(default=0)
    slot_shots = models.IntegerField(default=0)
    slot_shot_pctg = models.FloatField(default=0)
    left_shots = models.IntegerField(default=0)
    left_shot_pctg = models.FloatField(default=0)
    right_shots = models.IntegerField(default=0)
    right_shot_pctg = models.FloatField(default=0)
    blue_line_shots = models.IntegerField(default=0)
    blue_line_shot_pctg = models.FloatField(default=0)
    neutral_zone_shots = models.IntegerField(default=0)
    neutral_zone_shot_pctg = models.FloatField(default=0)
    shots_per_game = models.FloatField(default=0)

    # shots on goal
    shots_on_goal = models.IntegerField(default=0)
    slot_on_goal = models.IntegerField(default=0)
    slot_on_goal_pctg = models.FloatField(default=0)
    left_on_goal = models.IntegerField(default=0)
    left_on_goal_pctg = models.FloatField(default=0)
    right_on_goal = models.IntegerField(default=0)
    right_on_goal_pctg = models.FloatField(default=0)
    blue_line_on_goal = models.IntegerField(default=0)
    blue_line_on_goal_pctg = models.FloatField(default=0)
    neutral_zone_on_goal = models.IntegerField(default=0)
    neutral_zone_on_goal_pctg = models.FloatField(default=0)
    shots_on_goal_per_game = models.FloatField(default=0)
    shot_pctg = models.FloatField(default=0)

    # time on ice
    time_on_ice_seconds = models.IntegerField(default=0)
    time_on_ice = models.CharField(max_length=10, blank=True)
    time_on_ice_per_game = models.CharField(max_length=5, blank=True)
    time_on_ice_pp_seconds = models.IntegerField(default=0)
    time_on_ice_pp = models.CharField(max_length=10, blank=True)
    time_on_ice_pp_per_game = models.CharField(max_length=5, blank=True)
    time_on_ice_sh_seconds = models.IntegerField(default=0)
    time_on_ice_sh = models.CharField(max_length=10, blank=True)
    time_on_ice_sh_per_game = models.CharField(max_length=5, blank=True)
    time_on_ice_per_game_seconds = models.FloatField(default=0)
    time_on_ice_pp_per_game_seconds = models.FloatField(default=0)
    time_on_ice_sh_per_game_seconds = models.FloatField(default=0)
    shifts = models.IntegerField(default=0)
    shifts_per_game = models.IntegerField(default=0)
    time_on_ice_per_shift = models.FloatField(default=0)
    plus = models.IntegerField(default=0)
    minus = models.IntegerField(default=0)
    plus_minus = models.FloatField(default=0)

    # special teams
    pp_goals = models.IntegerField(default=0)
    pp_assists = models.IntegerField(default=0)
    pp_points = models.IntegerField(default=0)
    sh_goals = models.IntegerField(default=0)
    sh_assists = models.IntegerField(default=0)
    sh_points = models.IntegerField(default=0)

    # this is for backward compability, will be removed later
    # lr = models.CharField(max_length=1)
    # games = models.IntegerField()
    # score = models.IntegerField()
    # penaltyminutes = models.IntegerField()
    # gwg = models.IntegerField()
    # ppg = models.IntegerField()
    # shg = models.IntegerField()
    # pm = models.CharField(max_length=4)
    # sog = models.IntegerField()

    # faceoff
    faceoffs = models.IntegerField(default=0)
    faceoffs_won = models.IntegerField(default=0)
    faceoffs_won_pctg = models.FloatField(default=0)
    faceoffs_lost = models.IntegerField(default=0)

    # penalty
    pim = models.IntegerField(default=0)
    penalties = models.IntegerField(default=0)
    _2min = models.IntegerField(default=0)
    _5min = models.IntegerField(default=0)
    _10min = models.IntegerField(default=0)
    _20min = models.IntegerField(default=0)
    lazy = models.IntegerField(default=0)
    roughing = models.IntegerField(default=0)
    reckless = models.IntegerField(default=0)
    other = models.IntegerField(default=0)

    def __unicode__(self):
        return self.full_name
    def __str__(self):
        return self.full_name

class Playerstatebb(models.Model):
    """ payerstats """
    assists = models.IntegerField()
    birthday = models.CharField(max_length=10, blank=True)
    birthplace = models.CharField(max_length=100, blank=True)
    firstname = models.CharField(max_length=25, blank=True)
    games = models.IntegerField()
    goals = models.IntegerField()
    id = models.IntegerField(primary_key=True)
    image = models.CharField(max_length=100, blank=True)
    lastname = models.CharField(max_length=50, blank=True)
    nationality = models.CharField(max_length=10, blank=True)
    number = models.IntegerField()
    penaltyMinutes = models.IntegerField()
    points = models.IntegerField()
    position = models.CharField(max_length=10)
    positiveNegative = models.CharField(max_length=4)
    previousClubs = models.TextField(blank=True)
    roster = models.CharField(max_length=20)
    roster_status = models.CharField(max_length=30)
    shotsOnGoal = models.IntegerField()
    size = models.CharField(max_length=10)
    weight = models.CharField(max_length=10)

    def __unicode__(self):
        return self.lastname
    def __str__(self):
        return self.lastname

class Goaliestataggr(models.Model):
    """ goalistats """
    season = models.ForeignKey(Season, on_delete=models.CASCADE)
    full_name = models.CharField(max_length=300, blank=True)
    number = models.IntegerField(default=0)
    contract_due = models.CharField(max_length=10, blank=True)
    active = models.BooleanField(default=True)
    player_id = models.IntegerField(default=0)
    url = models.CharField(max_length=200, blank=True)
    flag = models.CharField(max_length=100, blank=True)
    weight = models.IntegerField(default=0)
    games_played = models.IntegerField(default=0)
    goals_against = models.IntegerField(default=0)
    ga_pp = models.IntegerField(default=0)
    ga_sh = models.IntegerField(default=0)
    gaa = models.IntegerField(default=0)
    shots_against = models.IntegerField(default=0)
    so = models.IntegerField(default=0)
    saves = models.IntegerField(default=0)
    save_pctg = models.FloatField(default=0)

    # do NOT DELETE NEXT TWO LINES!
    mip = models.CharField(max_length=10)
    mipp = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    # goal aginest distribution
    ga_slot = models.IntegerField(default=0)
    ga_slot_pctg = models.FloatField(default=0)
    ga_left = models.IntegerField(default=0)
    ga_left_pctg = models.FloatField(default=0)
    ga_right = models.IntegerField(default=0)
    ga_right_pctg = models.FloatField(default=0)
    ga_blue_line = models.IntegerField(default=0)
    ga_blue_pctg = models.FloatField(default=0)
    ga_neutral_zone = models.IntegerField(default=0)
    ga_neutral_pctg = models.FloatField(default=0)

    # saves
    sa_slot = models.IntegerField(default=0)
    save_pctg_slot = models.FloatField(default=0)
    sa_left = models.IntegerField(default=0)
    save_pctg_left = models.FloatField(default=0)
    sa_right = models.IntegerField(default=0)
    save_pctg_right = models.FloatField(default=0)
    sa_blue_line = models.IntegerField(default=0)
    save_pctg_blue_line = models.FloatField(default=0)
    sa_neutral_zone = models.IntegerField(default=0)
    save_pctg_neutral_zone = models.FloatField(default=0)

    # all kind of save statistics
    sa_5v5 = models.IntegerField(default=0)
    ga_5v5 = models.IntegerField(default=0)
    save_pctg_5v5 = models.FloatField(default=0)
    sa_4v4 = models.IntegerField(default=0)
    ga_4v4 = models.IntegerField(default=0)
    save_pctg_4v4 = models.FloatField(default=0)
    sa_3v3 = models.IntegerField(default=0)
    ga_3v3 = models.IntegerField(default=0)
    save_pctg_3v3 = models.FloatField(default=0)
    sa_5v4 = models.IntegerField(default=0)
    ga_5v4 = models.IntegerField(default=0)
    save_pctg_5v4 = models.FloatField(default=0)
    sa_5v3 = models.IntegerField(default=0)
    ga_5v3 = models.IntegerField(default=0)
    save_pctg_5v3 = models.FloatField(default=0)
    sa_4v3 = models.IntegerField(default=0)
    ga_4v3 = models.IntegerField(default=0)
    save_pctg_4v3 = models.FloatField(default=0)
    sa_3v4 = models.IntegerField(default=0)
    ga_3v4 = models.IntegerField(default=0)
    save_pctg_3v4 = models.FloatField(default=0)
    sa_3v5 = models.IntegerField(default=0)
    ga_3v5 = models.IntegerField(default=0)
    save_pctg_3v5 = models.FloatField(default=0)
    sa_4v5 = models.IntegerField(default=0)
    ga_4v5 = models.IntegerField(default=0)
    save_pctg_4v5 = models.FloatField(default=0)

    # backwards compatitility to oder scripts
    # name = models.CharField(max_length=300)
    # gkd = models.IntegerField()
    # ggoals = models.IntegerField()
    # sa = models.IntegerField()
    # sap = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    # sog = models.IntegerField()
    # contract_due = models.CharField(max_length=10, blank=True)
    # url = models.CharField(max_length=200, blank=True)
    # flag = models.CharField(max_length=100, blank=True)
    def __unicode__(self):
        return self.full_name
    def __str__(self):
        return self.full_name

class Teamstat(models.Model):
    """ teamstat """
    season = models.ForeignKey(Season, on_delete=models.CASCADE)
    match = models.ForeignKey(Match, on_delete=models.CASCADE)
    ppe = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    she = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    wins_home = models.IntegerField(null=True, default=0)
    wins_away = models.IntegerField(null=True, default=0)
    loss_home = models.IntegerField(null=True, default=0)
    loss_away = models.IntegerField(null=True, default=0)
    goals_home = models.IntegerField(null=True, default=0)
    goals_away = models.IntegerField(null=True, default=0)
    ggoals_home = models.IntegerField(null=True, default=0)
    ggoals_away = models.IntegerField(null=True, default=0)
    date = models.CharField(max_length=30, blank=True)
    uts = models.IntegerField()


class Yowsupd(models.Model):
    """ yowsup """
    statement = models.CharField(max_length=100)
    def __unicode__(self):
        return self.statement
    def __str__(self):
        return self.statement
