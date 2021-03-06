"""Checkout related views."""
import logging
from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.response import TemplateResponse

from ...account.forms import LoginForm
from ...core.taxes import get_display_price, quantize_price, zero_taxed_money
from ...core.utils import format_money, get_user_shipping_country, to_local_currency
from ..forms import CheckoutShippingMethodForm, CountryForm, ReplaceCheckoutLineForm
from ..models import Checkout
from ...product.models import Collection
from ...order.emails import send_order_confirmation
from ..utils import (
    clear_funnel_session,
    clear_payments,
    create_order,
    check_product_availability_and_warn,
    get_checkout_context,
    get_country_code,
    get_or_empty_db_checkout,
    get_shipping_price_estimate,
    get_valid_shipping_methods_for_checkout,
    is_valid_shipping_method,
    prepare_order_data,
    update_checkout_quantity,
    update_shipping_method,
    upsell_order,
    should_redirect,
)
from ...order.models import Order
from ...order.views import start_payment
from ...order.utils import update_order_prices
from .discount import add_voucher_form, validate_voucher
from .shipping import anonymous_user_shipping_address_view, user_shipping_address_view
from .summary import (
    anonymous_summary_without_shipping,
    summary_with_shipping_view,
    summary_without_shipping,
)
from .validators import (
    validate_checkout,
    validate_is_shipping_required,
    validate_shipping_address,
    validate_shipping_method,
)
from ...core import analytics
from ...payment.gateway import process_payment
from ...payment.utils import create_payment


logger = logging.getLogger(__name__)


@get_or_empty_db_checkout(Checkout.objects.for_display())
@validate_checkout
def checkout_login(request, checkout):
    """Allow the user to log in prior to checkout."""
    if request.user.is_authenticated:
        return redirect("checkout:start")
    ctx = {"form": LoginForm()}
    return TemplateResponse(request, "checkout/login.html", ctx)


@get_or_empty_db_checkout(Checkout.objects.for_display())
@validate_checkout
@validate_is_shipping_required
def checkout_start(request, checkout):
    """Redirect to the initial step of checkout."""
    return redirect("checkout:shipping-address")


@get_or_empty_db_checkout(Checkout.objects.for_display())
@validate_voucher
@validate_checkout
@validate_is_shipping_required
@add_voucher_form
def checkout_shipping_address(request, checkout):
    """Display the correct shipping address step."""
    if request.user.is_authenticated:
        return user_shipping_address_view(request, checkout)
    return anonymous_user_shipping_address_view(request, checkout)


@get_or_empty_db_checkout(Checkout.objects.for_display())
@validate_voucher
@validate_checkout
@validate_is_shipping_required
@validate_shipping_address
@add_voucher_form
def checkout_shipping_method(request, checkout):
    """Display the shipping method selection step."""
    discounts = request.discounts
    is_valid_shipping_method(checkout, discounts)

    form = CheckoutShippingMethodForm(
        request.POST or None,
        discounts=discounts,
        instance=checkout,
        initial={"shipping_method": checkout.shipping_method},
    )
    updated = False
    if form.is_valid():
        form.save()
        if should_redirect(request):
            return redirect("checkout:summary")
        else:
            updated = True

    ctx = get_checkout_context(checkout, discounts)
    ctx.update({"shipping_method_form": form, "updated": updated})
    return TemplateResponse(request, "checkout/shipping_method.html", ctx)


@get_or_empty_db_checkout(Checkout.objects.for_display())
@validate_voucher
@validate_checkout
@add_voucher_form
def checkout_order_summary(request, checkout):
    """Display the correct order summary."""
    if checkout.is_shipping_required():
        view = validate_shipping_method(summary_with_shipping_view)
        view = validate_shipping_address(view)
        return view(request, checkout)
    if request.user.is_authenticated:
        return summary_without_shipping(request, checkout)
    return anonymous_summary_without_shipping(request, checkout)


def checkout_index(request, checkout):
    """Display checkout details."""
    discounts = request.discounts
    checkout_lines = []
    check_product_availability_and_warn(request, checkout)

    # refresh required to get updated checkout lines and it's quantity
    try:
        checkout = Checkout.objects.prefetch_related(
            "lines__variant__product__category"
        ).get(pk=checkout.pk)
    except Checkout.DoesNotExist:
        pass

    lines = checkout.lines.select_related("variant__product__product_type")
    lines = lines.prefetch_related(
        "variant__translations",
        "variant__product__translations",
        "variant__product__images",
        "variant__product__product_type__variant_attributes__translations",
        "variant__images",
        "variant__product__product_type__variant_attributes",
    )
    manager = request.extensions
    for line in lines:
        initial = {"quantity": line.quantity}
        form = ReplaceCheckoutLineForm(
            None,
            checkout=checkout,
            variant=line.variant,
            initial=initial,
            discounts=discounts,
        )
        total_line = manager.calculate_checkout_line_total(line, discounts)
        variant_price = quantize_price(total_line / line.quantity, total_line.currency)
        checkout_lines.append(
            {
                "variant": line.variant,
                "get_price": variant_price,
                "get_total": total_line,
                "form": form,
            }
        )

    default_country = get_user_shipping_country(request)
    country_form = CountryForm(initial={"country": default_country})
    shipping_price_range = get_shipping_price_estimate(
        price=manager.calculate_checkout_subtotal(checkout, discounts).gross,
        weight=checkout.get_total_weight(),
        country_code=default_country,
    )

    context = get_checkout_context(
        checkout,
        discounts,
        currency=request.currency,
        shipping_range=shipping_price_range,
    )
    context.update(
        {
            "checkout_lines": checkout_lines,
            "country_form": country_form,
            "shipping_price_range": shipping_price_range,
        }
    )
    return TemplateResponse(request, "checkout/index.html", context)


@get_or_empty_db_checkout(checkout_queryset=Checkout.objects.for_display())
def blank(request, checkout):
    try:
        checkout = Checkout.objects.prefetch_related(
            "lines__variant__product__category"
        ).get(pk=checkout.pk)
    except Checkout.DoesNotExist:
        pass
    discounts = request.discounts
    checkout_lines = []
    lines = checkout.lines.select_related("variant__product__product_type")
    lines = lines.prefetch_related(
        "variant__translations",
        "variant__product__translations",
        "variant__product__images",
        "variant__product__product_type__variant_attributes__translations",
        "variant__images",
        "variant__product__product_type__variant_attributes",
    )
    manager = request.extensions
    for line in lines:
        initial = {"quantity": line.quantity}
        total_line = manager.calculate_checkout_line_total(line, discounts)
        variant_price = quantize_price(total_line / line.quantity, total_line.currency)
        checkout_lines.append(
            {
                "variant": line.variant,
                "get_price": variant_price,
                "get_total": total_line,
            }
        )
    return TemplateResponse(request, "checkout/blank.html")


@get_or_empty_db_checkout(checkout_queryset=Checkout.objects.for_display())
def checkout_index_new(request, checkout):
    """Display checkout details."""
    discounts = request.discounts
    checkout_lines = []

    # refresh required to get updated checkout lines and it's quantity
    try:
        checkout = Checkout.objects.prefetch_related(
            "lines__variant__product__category"
        ).get(pk=checkout.pk)
    except Checkout.DoesNotExist:
        pass

    funnel_index = request.session.get("funnel_index")
    if (
        funnel_index is not None and funnel_index > 0
    ):  # we've already collected payment info
        token = request.session["token"]
        order = get_object_or_404(Order, token=token)
        upsell_order(order, checkout, analytics.get_client_id(request), discounts)
        payment = order.payments.first()
        order_id = "{}_{}".format(order.id, funnel_index)
        if order.total_balance.amount:
            payment_ = create_payment(
                gateway=payment.gateway,
                currency=order.total.gross.currency,
                email=order.user_email,
                billing_address=order.billing_address,
                customer_ip_address=payment.customer_ip_address,
                total=abs(order.total_balance.amount),
                order=order,
                extra_data={"order_id": order_id},
            )
            tx = payment.transactions.first()
            token = tx.gateway_response.get("payment_method", "")
            customer_id = tx.customer_id
            process_payment(
                payment_,
                token,
                store_source=True,
                customer_id=customer_id,
                order_id=order_id,
            )
        funnel_index = funnel_index + 1
        request.session["funnel_index"] = funnel_index
        funnel = get_object_or_404(Collection, slug=request.session["funnel_slug"])
        order.save()
        checkout.delete()
        if funnel.products.count() > funnel_index:
            return redirect("product:funnel", slug=funnel.slug, pk=funnel.id)
        else:
            return redirect("order:payment-success", token=order.token)
    lines = checkout.lines.select_related("variant__product__product_type")
    lines = lines.prefetch_related(
        "variant__translations",
        "variant__product__translations",
        "variant__product__images",
        "variant__product__product_type__variant_attributes__translations",
        "variant__images",
        "variant__product__product_type__variant_attributes",
    )
    manager = request.extensions
    for line in lines:
        initial = {"quantity": line.quantity}
        total_line = manager.calculate_checkout_line_total(line, discounts)
        variant_price = quantize_price(total_line / line.quantity, total_line.currency)
        checkout_lines.append(
            {
                "variant": line.variant,
                "get_price": variant_price,
                "get_total": total_line,
            }
        )
    ctx = {}
    # calling the views below as functions invokes a bunch of decorators
    # that might redirect the request. That's not what we want here for the
    # single page checkout, so set a flag in the request and check in the
    # views and decorators.
    request.redirect = False
    response = anonymous_user_shipping_address_view(request, checkout, get_ctx=False)
    ctx.update({"shipping": response.context_data, "cheesy_clock": True})
    country_code = get_country_code(ctx["shipping"]["address_form"])
    country_form = CountryForm(initial={"country": country_code})
    errors = country_form.errors
    if errors:
        logger.info(f"checkout: country_form.errors: {dict(errors)}")
    shipping_price_range = get_shipping_price_estimate(
        checkout, discounts, country_code=country_code
    )

    ctx.update(
        get_checkout_context(
            checkout,
            discounts,
            currency=request.currency,
            shipping_range=shipping_price_range,
        )
    )
    ctx.update(
        {
            "checkout_lines": checkout_lines,
            "country_form": country_form,
            "shipping_price_range": shipping_price_range,
            "single_page": True,
        }
    )
    response = anonymous_user_shipping_address_view(request, checkout)
    ctx.update({"shipping": response.context_data})
    for key in ("user_form", "address_form"):
        errors = ctx["shipping"][key].errors
        if errors:
            logger.info(f"checkout: {key}.form.errors: {dict(errors)}")
    checkout.refresh_from_db()
    # response = checkout_shipping_method(request)
    # ctx.update({"shipping_method": response.context_data})

    # skip the shipping method form and choose the cheapest
    checkout.shipping_method = get_valid_shipping_methods_for_checkout(
        checkout, discounts, country_code=country_code
    ).first()
    checkout.save()

    order_data = prepare_order_data(
        checkout=checkout,
        tracking_code=analytics.get_client_id(request),
        discounts=discounts,
    )
    order = create_order(
        checkout=checkout,
        order_data=order_data,
        user=request.user,
        send_email=False,  # don't send the conf email yet
    )
    request.session["token"] = order.token

    order.shipping_address = checkout.shipping_address
    if checkout.email:
        order.user_email = checkout.email
    if update_shipping_method(checkout, order):
        clear_payments(order)
    update_order_prices(order, discounts)
    order.save()

    # don't start payment processing until the JS submits the form
    if request.POST.get("payment_method_nonce"):
        gateway = request.POST["gateway"]
        if not order.is_fully_paid():
            response = start_payment(request, token=order.token, gateway=gateway)
        if not order.is_fully_paid():
            ctx[gateway] = response.context_data
            errors = ctx[gateway]["form"].errors
            if errors:
                logger.info(f"checkout: {gateway}.form.errors: {dict(errors)}")
    else:
        for gateway in settings.PAYMENT_GATEWAYS:
            response = start_payment(request, order=order, gateway=gateway)
            ctx[gateway] = response.context_data
    if (
        ctx["shipping"]["updated"]
        # and ctx["shipping_method"]["updated"]
        and order.is_fully_paid()
    ):
        checkout.delete()
        request.session["funnel_index"] = funnel_index + 1
        # send the order conf in the future to allow time for upsells
        send_order_confirmation.apply_async(
            args=[order.pk, request.user and request.user.pk or None],
            countdown=settings.EMAIL_ORDER_CONF_DELAY,
        )
        return redirect("order:payment-success", token=order.token)
    return TemplateResponse(request, "checkout/new.html", ctx)


@get_or_empty_db_checkout(checkout_queryset=Checkout.objects.for_display())
def checkout_shipping_options(request, checkout, single_page=False):
    """Display shipping options to get a price estimate."""
    country_form = CountryForm(request.POST or None)
    if country_form.is_valid():
        shipping_price_range = country_form.get_shipping_price_estimate(
            checkout, request.discounts
        )
    else:
        shipping_price_range = None
    ctx = {
        "shipping_price_range": shipping_price_range,
        "country_form": country_form,
        "single_page": single_page,
    }
    checkout_data = get_checkout_context(
        checkout,
        request.discounts,
        currency=request.currency,
        shipping_range=shipping_price_range,
    )
    ctx.update(checkout_data)
    return TemplateResponse(request, "checkout/_subtotal_table.html", ctx)


@get_or_empty_db_checkout(Checkout.objects.prefetch_related("lines__variant__product"))
def update_checkout_line(request, checkout, variant_id):
    """Update the line quantities."""
    if not request.is_ajax():
        return redirect("checkout:index")

    checkout_line = get_object_or_404(checkout.lines, variant_id=variant_id)
    discounts = request.discounts
    status = None
    form = ReplaceCheckoutLineForm(
        request.POST,
        checkout=checkout,
        variant=checkout_line.variant,
        discounts=discounts,
    )
    manager = request.extensions
    if form.is_valid():
        form.save()
        checkout.refresh_from_db()
        # Refresh obj from db and confirm that checkout still has this line
        checkout_line = checkout.lines.filter(variant_id=variant_id).first()
        line_total = zero_taxed_money(currency=settings.DEFAULT_CURRENCY)
        if checkout_line:
            line_total = manager.calculate_checkout_line_total(checkout_line, discounts)
        subtotal = get_display_price(line_total)
        response = {
            "variantId": variant_id,
            "subtotal": format_money(subtotal),
            "total": 0,
            "checkout": {"numItems": checkout.quantity, "numLines": len(checkout)},
        }

        checkout_total = manager.calculate_checkout_subtotal(checkout, discounts)
        checkout_total = get_display_price(checkout_total)
        response["total"] = format_money(checkout_total)
        local_checkout_total = to_local_currency(checkout_total, request.currency)
        if local_checkout_total is not None:
            response["localTotal"] = format_money(local_checkout_total)

        status = 200
    elif request.POST is not None:
        response = {"error": form.errors}
        status = 400
    return JsonResponse(response, status=status)


@get_or_empty_db_checkout()
def clear_checkout(request, checkout):
    """Clear checkout."""
    if len(checkout):
        checkout.lines.all().delete()
        update_checkout_quantity(checkout)
    clear_funnel_session(request)

    if request.is_ajax():
        response = {"numItems": 0}
        return JsonResponse(response)
    else:
        return redirect("/")  # TODO


@get_or_empty_db_checkout(checkout_queryset=Checkout.objects.for_display())
def checkout_dropdown(request, checkout):
    """Display a checkout summary suitable for displaying on all pages."""
    discounts = request.discounts
    manager = request.extensions

    def prepare_line_data(line):
        first_image = line.variant.get_first_image()
        if first_image:
            first_image = first_image.image
        return {
            "product": line.variant.product,
            "variant": line.variant,
            "quantity": line.quantity,
            "image": first_image,
            "line_total": manager.calculate_checkout_line_total(line, discounts),
            "variant_url": line.variant.get_absolute_url(),
        }

    if checkout.quantity == 0:
        data = {"quantity": 0}
    else:
        data = {
            "quantity": checkout.quantity,
            "total": manager.calculate_checkout_subtotal(checkout, discounts),
            "lines": [prepare_line_data(line) for line in checkout],
        }

    return render(request, "checkout_dropdown.html", data)
