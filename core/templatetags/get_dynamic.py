from django import template
register = template.Library()

@register.filter
def get_week(row, week):
    return row.get(f"week_{week}")
