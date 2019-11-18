import datetime
import json
import mimetypes
import os
from typing import Union

from django.http import (
    FileResponse,
    HttpResponseNotFound,
    HttpResponsePermanentRedirect,
    JsonResponse,
)
from django.shortcuts import get_object_or_404, redirect
from django.http import Http404
from django.template.response import TemplateResponse
from django.urls import reverse
from draftjs_sanitizer import SafeJSONEncoder

from ..checkout.utils import (
    get_checkout_from_request,
    get_or_create_checkout_from_request,
    set_checkout_cookie,
)
from ..core.utils import serialize_decimal
from ..seo.schema.product import product_json_ld
from .filters import ProductCategoryFilter, ProductCollectionFilter
from .forms import ProductForm
from .models import Category, DigitalContentUrl
from .utils import (
    collections_visible_to_user,
    get_product_images,
    get_product_list_context,
    products_for_checkout,
    products_for_products_list,
    products_with_details,
)
from .utils.availability import get_product_availability
from .utils.digital_products import (
    digital_content_url_is_valid,
    increment_download_count,
)
from .utils.variants_picker import get_variant_picker_data

from .models import Attribute
from ..order.models import Order


def product_details(request, slug, product_id, form=None):
    """Product details page.

    The following variables are available to the template:

    product:
        The Product instance itself.

    is_visible:
        Whether the product is visible to regular users (for cases when an
        admin is previewing a product before publishing).

    form:
        The add-to-checkout form.

    price_range:
        The PriceRange for the product including all discounts.

    undiscounted_price_range:
        The PriceRange excluding all discounts.

    discount:
        Either a Price instance equal to the discount value or None if no
        discount was available.

    local_price_range:
        The same PriceRange from price_range represented in user's local
        currency. The value will be None if exchange rate is not available or
        the local currency is the same as site's default currency.
    """
    products = products_with_details(user=request.user)
    product = get_object_or_404(products, id=product_id)
    if product.get_slug() != slug:
        return HttpResponsePermanentRedirect(product.get_absolute_url())
    today = datetime.date.today()
    is_visible = product.publication_date is None or product.publication_date <= today
    if form is None:
        checkout = get_checkout_from_request(request)
        form = ProductForm(
            checkout=checkout,
            product=product,
            data=request.POST or None,
            discounts=request.discounts,
            country=request.country,
            extensions=request.extensions,
        )
    availability = get_product_availability(
        product,
        discounts=request.discounts,
        country=request.country,
        local_currency=request.currency,
        extensions=request.extensions,
    )
    product_images = get_product_images(product)
    variant_picker_data = get_variant_picker_data(
        product,
        request.discounts,
        request.extensions,
        request.currency,
        request.country,
    )
    # show_variant_picker determines if variant picker is used or select input
    show_variant_picker = all(
        [v["attributes"] for v in variant_picker_data["variants"]]
    )
    json_ld_data = product_json_ld(product)
    ctx = {
        "description_json": product.translated.description_json,
        "description_html": product.translated.description,
        "is_visible": is_visible,
        "form": form,
        "availability": availability,
        "product": product,
        "product_images": product_images,
        "show_variant_picker": show_variant_picker,
        "variant_picker_data": json.dumps(
            variant_picker_data, default=serialize_decimal, cls=SafeJSONEncoder
        ),
        "json_ld_product_data": json.dumps(
            json_ld_data, default=serialize_decimal, cls=SafeJSONEncoder
        ),
    }
    return TemplateResponse(request, "product/details.html", ctx)


def digital_product(request, token: str) -> Union[FileResponse, HttpResponseNotFound]:
    """Return the direct download link to content if given token is still valid."""
    qs = DigitalContentUrl.objects.prefetch_related("line__order__user")
    content_url = get_object_or_404(qs, token=token)  # type: DigitalContentUrl
    if not digital_content_url_is_valid(content_url):
        return HttpResponseNotFound("Url is not valid anymore")

    digital_content = content_url.content
    digital_content.content_file.open()
    opened_file = digital_content.content_file.file
    filename = os.path.basename(digital_content.content_file.name)
    file_expr = 'filename="{}"'.format(filename)

    content_type = mimetypes.guess_type(str(filename))[0]
    response = FileResponse(opened_file)
    response["Content-Length"] = digital_content.content_file.size

    response["Content-Type"] = content_type
    response["Content-Disposition"] = "attachment; {}".format(file_expr)

    increment_download_count(content_url)
    return response


def funnel_add_to_checkout(
    request, funnel_slug, slug, product_id, funnel_index, token=None
):
    return product_add_to_checkout(
        request, slug, product_id, funnel_slug=funnel_slug,
        funnel_index=funnel_index, token=token
    )

def product_add_to_checkout(
    request, slug, product_id, funnel_slug=None, funnel_index=None, token=None
):
    # types: (int, str, dict) -> None

    if not request.method == "POST":
        return redirect(
            reverse("product:details", kwargs={"product_id": product_id, "slug": slug})
        )

    products = products_for_checkout(user=request.user)
    product = get_object_or_404(products, pk=product_id)
    checkout = get_or_create_checkout_from_request(request)
    form = ProductForm(
        checkout=checkout,
        product=product,
        data=request.POST or None,
        discounts=request.discounts,
        country=request.country,
        extensions=request.extensions,
    )
    if form.is_valid():
        form.save()
        next_url = reverse("checkout:index")
        if funnel_slug is not None:
            meta = form.checkout.get_meta('funnel', 'funnel')
            meta.update({
                'slug': funnel_slug,
                'funnel_index': int(funnel_index) + 1,
                'token': token,
            })
            next_url = meta.get('next', next_url)
            # Tag the checkout to identify it as a funnel so we can do the upsell later.
            form.checkout.store_meta('funnel', 'funnel', meta)
            form.checkout.save()
        print(f'product_add_to_checkout: next_url: {next_url} token: {token}')
        if request.is_ajax():
            response = JsonResponse({"next": next_url}, status=200)
        else:
            response = redirect(next_url)
    else:
        if request.is_ajax():
            response = JsonResponse({"error": form.errors}, status=400)
        else:
            response = product_details(request, slug, product_id, form)
    if not request.user.is_authenticated:
        set_checkout_cookie(checkout, response)
    return response


def category_index(request, slug, category_id):
    categories = Category.objects.prefetch_related("translations")
    category = get_object_or_404(categories, id=category_id)
    if slug != category.slug:
        return redirect(
            "product:category",
            permanent=True,
            slug=category.slug,
            category_id=category_id,
        )
    # Check for subcategories
    categories = category.get_descendants(include_self=True)
    products = (
        products_for_products_list(user=request.user)
        .filter(category__in=categories)
        .order_by("name")
        .prefetch_related("collections")
    )
    product_filter = ProductCategoryFilter(
        request.GET, queryset=products, category=category
    )
    ctx = get_product_list_context(request, product_filter)
    ctx.update({"object": category})
    return TemplateResponse(request, "category/index.html", ctx)


def collection_index(request, slug, pk):
    collections = collections_visible_to_user(request.user).prefetch_related(
        "translations"
    )
    collection = get_object_or_404(collections, id=pk)
    if collection.slug != slug:
        return HttpResponsePermanentRedirect(collection.get_absolute_url())
    products = (
        products_for_products_list(user=request.user)
        .filter(collections__id=collection.id)
        .order_by("name")
    )
    product_filter = ProductCollectionFilter(
        request.GET, queryset=products, collection=collection
    )
    ctx = get_product_list_context(request, product_filter)
    ctx.update({"object": collection})
    return TemplateResponse(request, "collection/index.html", ctx)

def funnel_decline(request, token):
    order = get_object_or_404(Order, token=token)
    meta = order.get_meta('funnel', 'funnel')
    funnel_index = meta['funnel_index']
    meta.update({
        'funnel_index': int(funnel_index) + 1,
    })
    order.store_meta('funnel', 'funnel', meta)
    order.save()
    return redirect(meta['next'])


def funnel_index(request, slug, pk, aslug, funnel_index=0, token=None):
    collections = collections_visible_to_user(request.user).prefetch_related(
        "translations"
    )
    print(f'funnel_index: token: {token}')
    collection = get_object_or_404(collections, id=pk)
    if collection.slug != slug:
        return HttpResponsePermanentRedirect(collection.get_absolute_url())
    try:
        product = (
            products_for_products_list(user=request.user)
            .filter(collections__id=collection.id)
            .sort_by_attribute(Attribute.objects.get(slug=aslug))
        )[int(funnel_index)]
    except KeyError:
        raise Http404("Collection doesn't exist")
    today = datetime.date.today()
    is_visible = product.publication_date is None or product.publication_date <= today
    checkout = get_checkout_from_request(request)
    form = ProductForm(
        checkout=checkout,
        product=product,
        data=request.POST or None,
        discounts=request.discounts,
        country=request.country,
        extensions=request.extensions,
    )
    availability = get_product_availability(
        product,
        discounts=request.discounts,
        country=request.country,
        local_currency=request.currency,
        extensions=request.extensions,
    )
    product_images = get_product_images(product)
    variant_picker_data = get_variant_picker_data(
        product,
        request.discounts,
        request.extensions,
        request.currency,
        request.country,
    )
    # show_variant_picker determines if variant picker is used or select input
    show_variant_picker = all(
        [v["attributes"] for v in variant_picker_data["variants"]]
    )
    json_ld_data = product_json_ld(product)
    ctx = {
        "description_json": product.translated.description_json,
        "description_html": product.translated.description,
        "is_visible": is_visible,
        'funnel_slug': collection.slug,
        'funnel_index': funnel_index,
        "form": form,
        "availability": availability,
        "product": product,
        "token": token,
        "product_images": product_images,
        "show_variant_picker": show_variant_picker,
        "variant_picker_data": json.dumps(
            variant_picker_data, default=serialize_decimal, cls=SafeJSONEncoder
        ),
        "json_ld_product_data": json.dumps(
            json_ld_data, default=serialize_decimal, cls=SafeJSONEncoder
        ),
    }
    return TemplateResponse(request, "funnel/index.html", ctx)
