from __future__ import absolute_import
from django import template
from game.myfunctions import check_live_link
register = template.Library()

@register.filter(name='lookup')
def lookup(dic, index):
    if dic:
        if isinstance(dic, dict):
            if index in dic:
                return dic[index]
            else:
                return ''
        else:
            return ''
    return ''

@register.filter(name='lookup_list')
def lookup_list(dict, index):
    if dict:
        if dict[index]:
            return dict[index]
        else:
            return ''
    return ''

@register.filter(name='chk_live_link')
def chk_live_link(value):

    return(check_live_link(value))

@register.filter
def get_item(dict_data, index):
    # .get() safely returns None if the index is missing
    return dict_data.get(index)

@register.filter
def splarg(string):
    try:
        a,b = string.split('=', 1)
        if string == "user/password/done/":
            return '/'
        else:
            if(b):
              return b
            else:
              return a
    except Exception:
        return '/'

@register.filter(name='formatcurrency')
def formatcurrency(value):
    try:
       number = float(value)
       value = format(number, ",.2f").replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
       pass

    return(value)

@register.filter(name='formatnumber')
def formatnumber(value):
    try:
       number = float(value)
       value = format(number, ",.0f").replace(",", ".")
    except Exception:
       pass

    return(value)

