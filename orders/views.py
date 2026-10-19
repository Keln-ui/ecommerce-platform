from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.decorators import seller_required

from .forms import CartAddForm, CartUpdateForm, CheckoutForm
from .models import Order
from .services import (
    add_to_cart,
    cancel_order,
    get_cart_item,
    get_or_create_cart,
    place_orders,
    set_cart_item_quantity,
)


def _safe_next(request, fallback="catalog:product_list"):
    """Only follow relative redirect targets, never absolute external URLs."""
    candidate = request.POST.get("next") or request.GET.get("next") or ""
    if candidate.startswith("/") and not candidate.startswith("//"):
        return candidate
    return fallback


# ----------------------------------------------------------------------- cart


@login_required
def cart_view(request):
    cart = get_or_create_cart(request.user)
    return render(
        request,
        "orders/cart.html",
        {
            "cart": cart,
            "groups": cart.group_by_seller(),
            "seller_count": cart.seller_count(),
            "item_count": cart.item_count,
            "subtotal": cart.subtotal,
            "shipping_fee": cart.shipping_fee(),
            "total": cart.total,
        },
    )


@login_required
@require_POST
def cart_add(request):
    form = CartAddForm(request.POST)
    if not form.is_valid():
        messages.error(
            request, form.errors.get("__all__", ["Could not add that item."])[0]
        )
        return redirect(_safe_next(request))

    product = form.cleaned_data["product_id"]
    _cart, added, error = add_to_cart(
        request.user, product, form.cleaned_data["quantity"]
    )
    if error:
        messages.warning(request, error)
    else:
        messages.success(request, f"Added {added} x {product.name} to your cart.")
    return redirect(_safe_next(request))


@login_required
@require_POST
def cart_update(request):
    form = CartUpdateForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Could not update your cart.")
        return redirect("orders:cart")

    _ok, error = set_cart_item_quantity(
        request.user, form.cleaned_data["item_id"], form.cleaned_data["quantity"]
    )
    if error:
        messages.warning(request, error)
    return redirect("orders:cart")


@login_required
@require_POST
def cart_remove(request, item_id):
    item = get_cart_item(request.user, item_id)
    if item is None:
        messages.error(request, "That item is no longer in your cart.")
    else:
        item.delete()
        messages.success(request, "Item removed from your cart.")
    return redirect("orders:cart")


# ------------------------------------------------------------------- checkout


@login_required
def checkout(request):
    cart = get_or_create_cart(request.user)
    if cart.is_empty:
        messages.info(request, "Your cart is empty.")
        return redirect("catalog:product_list")

    form = CheckoutForm(request.POST or None, user=request.user)

    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            orders = place_orders(
                request.user,
                {
                    "name": data["name"],
                    "phone": data["phone"],
                    "address": data["address"],
                    "notes": data["notes"],
                },
                payment_method=data["payment_method"],
            )
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect("orders:cart")

        if len(orders) == 1:
            messages.success(request, "Order placed successfully.")
        else:
            messages.success(
                request,
                f"Order placed — split into {len(orders)} shipments from "
                f"{len(orders)} different stores.",
            )
        return redirect("orders:order_detail", order_number=orders[0].order_number)

    return render(
        request,
        "orders/checkout.html",
        {
            "form": form,
            "cart": cart,
            "groups": cart.group_by_seller(),
            "seller_count": cart.seller_count(),
            "item_count": cart.item_count,
            "subtotal": cart.subtotal,
            "shipping_fee": cart.shipping_fee(),
            "total": cart.total,
        },
    )


# --------------------------------------------------------------------- orders


@login_required
def order_list(request):
    orders = (
        request.user.orders.select_related("seller", "seller__user")
        .prefetch_related("items")
    )
    paginator = Paginator(orders, 10)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(
        request, "orders/order_list.html", {"page_obj": page_obj, "orders": page_obj}
    )


@login_required
def order_detail(request, order_number):
    order = get_object_or_404(
        Order.objects.prefetch_related("items"), order_number=order_number
    )

    is_buyer = order.buyer_id == request.user.pk
    store = getattr(request.user, "seller_store", None)
    is_seller = bool(store and order.seller_id == store.pk)

    if not (is_buyer or is_seller or request.user.is_staff):
        messages.error(request, "You cannot view that order.")
        return redirect("catalog:home")

    return render(
        request,
        "orders/order_detail.html",
        {"order": order, "is_buyer": is_buyer, "is_seller": is_seller},
    )


@login_required
@require_POST
def order_cancel(request, order_number):
    order = get_object_or_404(Order, order_number=order_number, buyer=request.user)
    ok, message = cancel_order(order)
    (messages.success if ok else messages.error)(request, message)
    return redirect("orders:order_detail", order_number=order.order_number)


# ---------------------------------------------------------------- seller side


@seller_required
@require_POST
def seller_order_update(request, order_number):
    order = get_object_or_404(Order, order_number=order_number, seller=request.seller)

    new_status = request.POST.get("status")
    detail_url = "orders:order_detail"

    if new_status == Order.Status.CANCELLED:
        ok, message = cancel_order(order)
        (messages.success if ok else messages.error)(request, message)
        return redirect(detail_url, order_number=order.order_number)

    if new_status not in Order.ALLOWED_TRANSITIONS.get(order.status, set()):
        messages.error(
            request,
            f"An order that is {order.get_status_display().lower()} cannot move to "
            "that state.",
        )
        return redirect(detail_url, order_number=order.order_number)

    tracking = request.POST.get("tracking_number", "").strip()
    if new_status == Order.Status.SHIPPED and not tracking:
        messages.error(request, "Add a tracking number before marking the order shipped.")
        return redirect(detail_url, order_number=order.order_number)

    order.status = new_status
    fields = ["status", "updated_at"]
    if tracking:
        order.tracking_number = tracking
        fields.append("tracking_number")
    order.save(update_fields=fields)

    messages.success(request, f"Order marked as {order.get_status_display().lower()}.")
    return redirect(detail_url, order_number=order.order_number)
