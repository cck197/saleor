from django.conf.urls import url

from ..core import TOKEN_PATTERN
from . import views

urlpatterns = [
    url(
        r"^(?P<slug>[a-z0-9-_]+?)-(?P<product_id>[0-9]+)/$",
        views.product_details,
        name="details",
    ),
    url(
        r"^digital-download/(?P<token>[0-9A-Za-z_\-]+)/$",
        views.digital_product,
        name="digital-product",
    ),
    url(
        r"^category/(?P<slug>[a-z0-9-_]+?)-(?P<category_id>[0-9]+)/$",
        views.category_index,
        name="category",
    ),
    url(
        r"(?P<slug>[a-z0-9-_]+?)-(?P<product_id>[0-9]+)/add/$",
        views.product_add_to_checkout,
        name="add-to-checkout",
    ),
    url(
        r"^funnel-decline/$",
        views.funnel_decline,
        name="funnel-decline",
    ),
    url(
        r"^collection/(?P<slug>[a-z0-9-_/]+?)-(?P<pk>[0-9]+)/$",
        views.collection_index,
        name="collection",
    ),
    url(
        r"^funnel/(?P<slug>[a-z0-9-_/]+?)-(?P<pk>[0-9]+)/$",
        views.funnel_index,
        name="funnel",
        kwargs={'aslug': 'funnel_order'},
    ),
    url(
        r"^funnel/(?P<slug>[a-z0-9-_]+?)/(?P<variant_id>[0-9]+)/add/$",
        views.variant_add_to_checkout,
        name="variant-add-to-checkout",
    ),
]
