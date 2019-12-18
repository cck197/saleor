from django.conf.urls import url

from . import views
from .views.discount import remove_voucher_view

checkout_urlpatterns = [
    url(
        r"^multi$",
        views.checkout_index,
        name="multi",
    ),
    url(
        r"^$",
        views.checkout_index,
        name="index",
        kwargs={"single_page": True, "template": "new.html"},
    ),
    url(r"^start$", views.checkout_start, name="start"),
    url(
        r"^update/(?P<variant_id>\d+)/$", views.update_checkout_line, name="update-line"
    ),
    url(r"^clear/$", views.clear_checkout, name="clear"),
    url(
        r"^shipping-options/$",
        views.checkout_shipping_options,
        name="shipping-options",
    ),
    url(
        r"^shipping-options/single_page$",
        views.checkout_shipping_options,
        name="shipping-options-single",
        kwargs={"single_page": True},
    ),
    url(
        r"^shipping-address/", views.checkout_shipping_address, name="shipping-address"
    ),
    url(r"^shipping-method/", views.checkout_shipping_method, name="shipping-method"),
    url(r"^summary/", views.checkout_order_summary, name="summary"),
    url(r"^dropdown/$", views.checkout_dropdown, name="dropdown"),
    url(r"^remove_voucher/", remove_voucher_view, name="remove-voucher"),
    url(r"^login/", views.checkout_login, name="login"),
]
