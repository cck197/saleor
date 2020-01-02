from django import template

register = template.Library()


@register.simple_tag
def get_product_features(product):
    return product.get_attr_startswith('pf_')

@register.simple_tag
def get_product_price_features(product):
    return product.get_attr_startswith('ppf_')
