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
    except:
        return '/'
		  
@register.filter(name='formatcurrency')   
def formatcurrency(value):
    import locale
    try:
        locale.setlocale(locale.LC_NUMERIC, "de_DE.utf8")       
    except: 
        locale.setlocale(locale.LC_NUMERIC, "german")   
    try:
       value = locale.format("%.2f", value, grouping = True)
    except:
       pass
	   
    return(value)

@register.filter(name='formatnumber')       
def formatnumber(value):
    import locale
    try:
        locale.setlocale(locale.LC_NUMERIC, "de_DE.utf8")       
    except: 
        locale.setlocale(locale.LC_NUMERIC, "german")   
    try:
       value = locale.format("%.0f", value, grouping = True)
    except:
       pass
	   
    return(value)
		  
