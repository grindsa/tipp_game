""" functions to generate highcharts """
import json

# copyrigt statement
CREDIT_DIC = {'text': '© 2020 dynamop', 'href': 'https://tippspiel.dynamop.de'}

def create_player_toi_chart(mday_list, match_toi_dic, mobile_browser):
    """ chart for time_on_ice """

    # prepare data
    toi_list = []
    toi_avg_list = []
    avg_toi = 0
    cnt = 0
    for matchday in mday_list:
        if matchday in match_toi_dic:
            cnt += 1
            avg_toi += match_toi_dic[matchday]['toi']
            # toi_list.append(match_toi_dic[matchday])
            toi_list.append({'y': round(match_toi_dic[matchday]['toi']/60, 1), 'mname': match_toi_dic[matchday]['mname'], 'label': '{0:02d}:{1:02d}'.format(*divmod(match_toi_dic[matchday]['toi'], 60))})
            toi_avg_list.append({'y': round(avg_toi/cnt/60, 1), 'label': '{0:02d}:{1:02d}'.format(*divmod(int(avg_toi/cnt), 60))})
        else:
            toi_list.append(0)
            toi_avg_list.append('null')

    # define some values depending on UA
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
            'useHTML': 1,
            'itemStyle': {'color': '#404040', 'font-size': label_size},
            'verticalAlign': v_align,
        },

        'tooltip': {
            'shared': 1,
            'useHTML': 1,
            'headerFormat': '<b>{point.x}.Spieltag {point.point.mname}</b><br>',
            'pointFormat': '<span style="color:{point.color}">\u25CF</span> <span style="font-size: %s">{series.name}: {point.label}min</span><br/>' % label_size,
        },

        'credits': CREDIT_DIC,

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
                'text': 'Eiszeit (min)',
                'style': {'color': '#404040', 'font-size': label_size},
            },
            },],

        'series': [{
            'name': 'Eiszeit pro Spiel',
            'data': toi_list,
            'color': '#7cb5ec',
        }, {
            'type': 'spline',
            'name': 'Ø Eiszeit pro Spiel',
            'data': toi_avg_list,
            'color': '#030357',
        }]
    }

    return json.dumps(chart_options)

def create_player_scoringpctg_chart(mday_list, match_shots_dic, mobile_browser):
    """ chart scoring percentage """

    # prepare data
    sh_list = []
    sh_avg_list = []
    goals = 0
    sog = 0

    cnt = 0
    for matchday in mday_list:
        if matchday in match_shots_dic:
            cnt += 1
            goals += match_shots_dic[matchday]['goals']
            sog += match_shots_dic[matchday]['sog']
            if match_shots_dic[matchday]['sog'] > 0:
                sh_list.append({'y': round(match_shots_dic[matchday]['goals'] * 100 /  match_shots_dic[matchday]['sog'], 2), 'mname': match_shots_dic[matchday]['mname']})
            else:
                sh_list.append(0)
            if sog > 0:
                sh_avg_list.append({'y': round(goals/sog * 100, 2)})
            else:
                sh_avg_list.append(0)
        else:
            sh_list.append('none')
            sh_avg_list.append('none')

    # define some values depending on UA
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
            'useHTML': 1,
            'itemStyle': {'color': '#404040', 'font-size': label_size},
            'verticalAlign': v_align,
        },

        'tooltip': {
            'shared': 1,
            'useHTML': 1,
            'headerFormat': '<b>{point.x}.Spieltag {point.point.mname}</b><br>',
            'pointFormat': '<span style="color:{point.color}">\u25CF</span> <span style="font-size: %s">{series.name}: {point.y}&#37;</span><br/>' % label_size,
        },

        'credits': CREDIT_DIC,

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
                'text': 'Schußquote in %',
                'style': {'color': '#404040', 'font-size': label_size},
            },
            'min': 0,
            'max': 100,
            },],

        'series': [{
            'name': 'Schußquote pro Spiel',
            'data': sh_list,
            'color': '#b0b3b5',
        }, {
            'type': 'spline',
            'name': 'fortlaufende Schußquote',
            'data': sh_avg_list,
            'color': '#030357',
        }]
    }

    return json.dumps(chart_options)

def create_player_shot_chart(matchday_list, match_shots_dic, mobile_browser, v60=None):
    """ chart shot data """

    # prepare data
    sh_list = []
    sog_list = []
    sh_avg_list = []
    sog_avg_list = []
    cnt = 0
    shots = 0
    sog = 0

    if v60:
        sh_name = 'sh60'
        sog_name = 'sog60'
        series1_name = 'SH/60'
        series2_name = 'SOG/60'
        series3_name = 'Ø SH/60'
        series4_name = 'Ø SOG/60'
    else:
        sh_name = 'shots'
        sog_name = 'sog'
        series1_name = 'Schüsse'
        series2_name = 'davon Torschüsse'
        series3_name = 'Ø Schüsse pro Spiel'
        series4_name = 'davon Torschüsse'

    for matchday in matchday_list:
        if matchday in match_shots_dic:
            # increate counters
            cnt += 1
            shots += match_shots_dic[matchday][sh_name]
            sog += match_shots_dic[matchday][sog_name]
            sh_list.append({'mvalue': match_shots_dic[matchday][sh_name], 'y': match_shots_dic[matchday][sh_name] - match_shots_dic[matchday][sog_name], 'mname': match_shots_dic[matchday]['mname']})
            sog_list.append({'mvalue': match_shots_dic[matchday][sog_name], 'y': match_shots_dic[matchday][sog_name]})

            # average values
            sh_avg_list.append({'y': (shots-sog)/cnt, 'mvalue': round(shots/cnt, 2)})
            sog_avg_list.append({'y': sog/cnt, 'mvalue': round(sog/cnt, 2)})

        else:
            sh_list.append('none')
            sog_list.append('none')
            sh_avg_list.append('none')
            sog_avg_list.append('none')

    # define some values depending on UA
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
            'useHTML': 1,
            'itemStyle': {'color': '#404040', 'font-size': label_size},
            'verticalAlign': v_align,
        },

        'tooltip': {
            'shared': 1,
            'useHTML': 1,
            'headerFormat': '<b>{point.x}.Spieltag {point.point.mname}</b><br>',
            'pointFormat': '<span style="color:{point.color}">\u25CF</span> <span style="font-size: %s">{series.name}: {point.mvalue}</span><br/>' % label_size,
        },

        'plotOptions': {
            'series': {
                'stacking': 'normal'
            }
        },

        'credits': CREDIT_DIC,

        'xAxis': {
            'categories': matchday_list,
            'title': {
                'text': 'Spieltag',
                'style': {'color': '#404040', 'font-size': label_size},
            },
            'crosshair': 1,
        },

        'yAxis': [{
            'title': {
                'text': 'Schußquote in %',
                'style': {'color': '#404040', 'font-size': label_size},
            },
            'min': 0,
            }],

        'series': [{
            'name': series1_name,
            'data': sh_list,
            'color': '#7cb5ec',
        }, {
            'name': series2_name,
            'data': sog_list,
            'color': '#b0b3b5',
        }, {
            'type': 'spline',
            'name': series3_name,
            'data': sh_avg_list,
            'color': '#030357',
        }, {
            'type': 'spline',
            'name': series4_name,
            'data': sog_avg_list,
            'color': '#68717a',
        }]
    }

    return json.dumps(chart_options)

def create_player_corsi_chart(matchday_list, match_shots_dic, mobile_browser):
    """ corsi chart for a single player """

    # prepare data
    cf_list = []
    ca_list = []
    corsi_list = []
    corsi_avg_list = []
    cnt = 0
    corsi_sum = 0
    for matchday in matchday_list:
        if matchday in match_shots_dic:
            # increate counters
            cnt += 1
            corsi = match_shots_dic[matchday]['shfoi'] - match_shots_dic[matchday]['shaoi']
            corsi_sum += corsi
            # calculate cf%
            if (match_shots_dic[matchday]['shfoi'] + match_shots_dic[matchday]['shaoi']) > 0:
                cfp = round(match_shots_dic[matchday]['shfoi']/(match_shots_dic[matchday]['shfoi'] + match_shots_dic[matchday]['shaoi']) * 100, 0)
            else:
                cfp = 0
            cf_list.append({'mvalue': match_shots_dic[matchday]['shfoi'], 'y': match_shots_dic[matchday]['shfoi'], 'mname': match_shots_dic[matchday]['mname']})
            ca_list.append({'mvalue': match_shots_dic[matchday]['shaoi'], 'y': match_shots_dic[matchday]['shaoi'] * -1, 'mname': match_shots_dic[matchday]['mname']})
            corsi_list.append({'mvalue': corsi, 'y': corsi, 'mname': match_shots_dic[matchday]['mname']})
            # average values
            corsi_avg_list.append({'y': corsi_sum/cnt, 'mvalue': round(corsi_sum/cnt, 2)})
        else:
            cf_list.append('none')
            ca_list.append('none')
            corsi_list.append('none')
            corsi_avg_list.append('none')

    # define some values depending on UA
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

        'plotOptions': {
            'series': {
                'grouping': False,
                'shadow': False,
            },
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
            'headerFormat': '<b>{point.x}.Spieltag {point.point.mname}</b><br>',
            'pointFormat': '<span style="color:{point.color}">\u25CF</span> <span style="font-size: %s">{series.name}: {point.mvalue}</span><br/>' % label_size,
        },

        'credits': CREDIT_DIC,

        'xAxis': {
            'categories': matchday_list,
            'title': {
                'text': 'Spieltag',
                'style': {'color': '#404040', 'font-size': label_size},
            },
            'crosshair': 1,
        },

        'yAxis': [{'title': {'text': 'Schüsse bei Spieler auf dem Eis', 'style': {'color': '#404040', 'font-size': label_size}}, 'min': -25, 'max': 25}],

        'series': [{
            'name': 'CorsiFor',
            'data': cf_list,
            'color': '#7cb5ec',
            'pointPadding': 0,
        }, {
            'name': 'CorsiAgainst',
            'data': ca_list,
            'color': '#b0b3b5',
            'pointPadding': 0,
        }, {
            'type': 'spline',
            'name': 'Corsi',
            'data': corsi_list,
            'color': '#68717a',
        }, {
            'type': 'spline',
            'name': 'Ø Corsi',
            'data': corsi_avg_list,
            'color': '#030357',
        }]
    }
    return json.dumps(chart_options)

def create_player_corsipctg_chart(matchday_list, match_shots_dic, mobile_browser):
    """ corsi chart for a single player """

    # prepare data
    cfp_list = []
    cfp_avg_list = []
    shfoi_sum = 0
    shaoi_sum = 0
    cnt = 0
    for matchday in matchday_list:
        if matchday in match_shots_dic:
            # increate counters
            cnt += 1
            shfoi_sum += match_shots_dic[matchday]['shfoi']
            shaoi_sum += match_shots_dic[matchday]['shaoi']

            # avergage corsi pctg
            if (shfoi_sum + shaoi_sum) > 0:
                cfp_sum = int(shfoi_sum/(shfoi_sum + shaoi_sum) * 100)
            else:
                cfp_sum = 0
                
            cfp_avg_list.append({'mvalue': '{0}%'.format(cfp_sum), 'y': cfp_sum, 'mname': match_shots_dic[matchday]['mname']})

            # calculate cf%
            if (match_shots_dic[matchday]['shfoi'] + match_shots_dic[matchday]['shaoi']) > 0:
                cfp = int(match_shots_dic[matchday]['shfoi']/(match_shots_dic[matchday]['shfoi'] + match_shots_dic[matchday]['shaoi']) * 100)
            else:
                cfp = 0
            cfp_list.append({'mvalue': '{0}%'.format(cfp), 'y': cfp, 'mname': match_shots_dic[matchday]['mname']})
        else:
            cfp_list.append('none')
            cfp_avg_list.append('none')

    # define some values depending on UA
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

        'plotOptions': {
            'series': {
                'grouping': False,
                'shadow': False,
            },
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
            'headerFormat': '<b>{point.x}.Spieltag {point.point.mname}</b><br>',
            'pointFormat': '<span style="color:{point.color}">\u25CF</span> <span style="font-size: %s">{series.name}: {point.mvalue}</span><br/>' % label_size,
        },

        'credits': CREDIT_DIC,

        'xAxis': {
            'categories': matchday_list,
            'title': {
                'text': 'Spieltag',
                'style': {'color': '#404040', 'font-size': label_size},
            },
            'crosshair': 1,
        },

        'yAxis': [{'title': {'text': 'Schüsse bei Spieler auf dem Eis', 'style': {'color': '#404040', 'font-size': label_size}}, 'min': -0, 'max': 100}],

        'series': [{
            'name': 'CF%',
            'data': cfp_list,
            'color': '#7cb5ec',
            'pointPadding': 0,
        },{
            'type': 'spline',
            'name': 'Ø CF%',
            'data': cfp_avg_list,
            'color': '#030357',
        }]
    }
    return json.dumps(chart_options)

