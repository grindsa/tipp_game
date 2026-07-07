# -*- coding: utf-8 -*-
""" functions for article app """
from __future__ import absolute_import
import time
import math
import random
from datetime import timedelta, datetime
from html.parser import HTMLParser
import html.entities
from article.models import Blacklist, Articletopwords
from game.myfunctions import sort_dic

GERMAN_MONTH_NAMES = {
    1: 'Januar',
    2: 'Februar',
    3: 'Maerz',
    4: 'April',
    5: 'Mai',
    6: 'Juni',
    7: 'Juli',
    8: 'August',
    9: 'September',
    10: 'Oktober',
    11: 'November',
    12: 'Dezember',
}

class HTMLTextExtractor(HTMLParser):
    """ HTMLTextExtractor class """
    def __init__(self):
        HTMLParser.__init__(self)
        self.result = []

    def handle_data(self, d):
        self.result.append(d)

    def handle_charref(self, number):
        codepoint = int(number[1:], 16) if number[0] in (u'x', u'X') else int(number)
        self.result.append(chr(codepoint))

    def handle_entityref(self, name):
        codepoint = html.entities.name2codepoint[name]
        self.result.append(chr(codepoint))

    def get_text(self):
        """ get text """
        return ''.join(self.result)

def strip_tags(html):
    """ strip html tags out """
    tts = HTMLTextExtractor()
    tts.feed(html)
    return tts.get_text()

def get_week_dates(dat_e):
    """ get days of a week """
    start = dat_e - timedelta(days=dat_e.weekday())
    end = start + timedelta(days=6)
    start = start.strftime('%Y-%m-%d')
    end = end.strftime('%Y-%m-%d')
    return (start, end)

def get_month(date_):
    """ get month name """
    month_number = datetime.strptime(date_, "%Y-%m-%d %H:%M:%S").month
    return GERMAN_MONTH_NAMES.get(month_number, '')

def get_month_string(date_):
    """ get month name """
    # get month string
    month_str = datetime.date(date_).strftime('%y-%m')
    return month_str

def get_month_name(month):
    """ get month name """
    month_number = datetime.strptime(month, "%y-%m").month
    return GERMAN_MONTH_NAMES.get(month_number, '')

def get_next_previous_month_strings(date_string):
    """ get previous month """
    d_date = datetime.strptime(date_string, "%y-%m")
    nextmonth = (d_date + timedelta(days=(d_date.max.day - d_date.day)+1)).strftime('%y-%m')
    prevmonth = (d_date.replace(day=1) - timedelta(days=1)).strftime('%y-%m')
    return(nextmonth, prevmonth)

def get_last_day_of_month(date_):
    """ get last day of a month """
    if date_.month == 12:
        return date_.replace(day=31)
    return date_.replace(hour=23, minute=59, second=59, month=date_.month+1, day=1) - timedelta(days=1)

def get_date_range(month_string, dformat='%y-%m'):
    """ get first and last date of a month """
    # convert string to datetime and get first day of month
    from_date = datetime.strptime(month_string, dformat)
    # get last day of month based on from date
    to_date = get_last_day_of_month(from_date)
    return(from_date, to_date)

def get_twittercloud_data(top_tweet_list, _twitter, fieldname):
    """ get data to fill the twiter cloud """
    word_dic = get_top_words(top_tweet_list, fieldname)
    # number of words in the cloud
    element_number = 15
    out_list = []
    # how many different sizes
    divisor = 5
    count = 0
    for word, _sinin in sorted(list(word_dic.items()), key=lambda x: x[1], reverse=True)[:element_number]:
        count = count + 1
        tagid = int(math.ceil(float(count)/float(divisor)))
        out_list.append({'name' : word, 'tag' : tagid})

    random.shuffle(out_list)
    return out_list

def get_word_chart_data(tweet_list, twitter, fieldname):
    """ get word data """
    word_dic = get_top_words(tweet_list, fieldname)

    bubble_data = []
    element_number = 15
    x_list = [12, 1, 0, 8, 5, 9, 6, 2, 4, 11, 14, 3, 13, 9, 10]
    y_list = [12, 1, 11, 0, 14, 8, 7, 15, 3, 5, 0, 9, 5, 14, 0]

    count = 0
    for word, zet in sorted(list(word_dic.items()), key=lambda x: x[1], reverse=True)[:element_number]:
        xaxe = x_list[count]
        # y = random.randint(1,15)
        yaxe = y_list[count]

        t_filter = word.encode('utf8')
        t_filter = str(t_filter).lstrip('#')

        if twitter:
            bubble_data.append({'x': int(xaxe), 'y': int(yaxe), 'z': int(zet), 'name': str(word.encode('utf8')), 'url' : '/article?twitter=1&tweet_filter='+str(t_filter)})
        else:
            bubble_data.append({'x': int(xaxe), 'y': int(yaxe), 'z': int(zet), 'name': str(word.encode('utf8')), 'url' : '/article?tweet_filter='+str(t_filter)})
        # bubble_data.append([x,y,z])
        count = count + 1

    return bubble_data

def shuffle_list(number):
    """ shuffel wordlist """
    new_list = list(range(number))
    # shuffle before list or assignment
    random.shuffle(new_list)
    return new_list

def get_top_words(text_list, fieldname):
    """ list top words """
    # get blacklist from DB
    black_list = list(Blacklist.objects.values())
    blacklist_dic = {}
    for bli in black_list:
        blacklist_dic[bli['text'].lower()] = 1

    # this is the word_dic
    word_dic = {}

    # check for each word in a tweet
    for text in text_list:
        list_ = text[fieldname].split()
        for word in list_:
            word = word.rstrip(',')
            word = word.rstrip('.')
            word = word.rstrip(':')
            # count world only if not included in blacklist
            if word.lower() not in blacklist_dic:
                # check if we already have the word in list (if not create it)
                if word not in word_dic:
                    word_dic[word] = 0
                word_dic[word] = word_dic[word] + 1

    return word_dic

def get_wordcloud_data(_request, wfilter=None):
    """ get wordcloud data """
    # get tas from DB
    word_list = Articletopwords.objects.order_by('-count').values('word', 'count')

    # set divisor for tag splitting
    out_list = []
    divisor = 5
    count = 0

    for word in word_list:
        count = count + 1
        tagid = int(math.ceil(float(count)/float(divisor)))
        if wfilter == word['word']:
            out_list.append({'name' : word['word'], 'tag': tagid, 'filter': True})
        else:
            out_list.append({'name' : word['word'], 'tag': tagid})

    random.shuffle(out_list)
    return out_list

def create_cw_chart(cw_dic, cw_list, mobile_browser, season):
    """ create chart """
    apw_list = []

    for cword in cw_list:
        apw_list.append(cw_dic[cword]['count'])

    # prepare some variables neededfor the chart
    label_size = '10px'

    # we need to change some setting for mobile access
    if mobile_browser:
        label_size = '8px'

    text = 'Artikel pro Woche: Saison ' + season
    chart_options = {

        'chart': {
            'type': 'column',
        },

        'title': {
            'text': str(text),
            'style': {'color': '#404040', 'font-size': '12px'},
        },

        'legend': {
            'enabled': 0,
        },

        'tooltip': {
            'shared': 0,
            'headerFormat': '<b>{point.y}</b>',
            'pointFormat':  '',
        },

        'xAxis': {
            'categories': cw_list,
            'title': {
                'text': 'Woche',
                'style': {'color': '#404040', 'font-size': label_size},
            },
            'crosshair' : 1,
        },
        'yAxis':[{
            'title': {
                'text': 'Artikelanzahl',
                'style': {'color': '#404040', 'font-size': label_size},
                'enabled': 0,
            },
        }],

        'series': [{
            'name': 'Artikelanzahl',
            'data': apw_list,
            'dataLabels': {
                'enabled': 0,
                'style': {
                    'color': '#404040',
                }
            },
            'color': '#7cb5ec',
        }],
    }

    return chart_options

def create_source_chart(source_dic, _cw_list, _mobile_browser, season):
    """ create chart """
    sort_list = sort_dic(source_dic, 'count', 1)

    pie_list = []
    for sli in sort_list:
        pie_list.append({'name': str(sli), 'y': source_dic[sli]['count']})

    text = 'Artikelverteilung: Saison ' + season
    chart_options = {

        'chart': {
            'type': 'pie',
        },

        'title': {
            'text': str(text),
            'style': {'color': '#404040', 'font-size': '12px'},
        },

        'series': [{
            'name': "Artikel",
            'colorByPoint': 1,
            'data': pie_list,
        }]
    }

    return chart_options
