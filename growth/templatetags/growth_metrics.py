from django import template

from growth.metrics_service import metric_comparison

register = template.Library()


@register.inclusion_tag("growth/_metric_panel.html")
def channel_metric_panel(account):
    if not account:
        return {"metric_data": None, "account": None}
    return {"metric_data": metric_comparison(account), "account": account}
