import re
from django import template

register = template.Library()


def _digits(value):
    return re.sub(r"\D", "", str(value or ""))


@register.filter
def e164_in(value):
    d = _digits(value)
    if not d:
        return ""
    if d.startswith("91") and len(d) == 12:
        return f"+{d}"
    if len(d) == 10:
        return f"+91{d}"
    if str(value).strip().startswith("+"):
        return str(value).strip()
    return f"+{d}"


@register.filter
def wa_in(value):
    d = _digits(value)
    if not d:
        return ""
    if d.startswith("91") and len(d) == 12:
        return d
    if len(d) == 10:
        return f"91{d}"
    return d

