"""Staff-only dashboard for running the marketplace.

Money convention used throughout: an order's `subtotal` is gross merchandise
value, `commission` is what the platform retains, and `seller_payout` is
subtotal - commission. Revenue reported here is the subtotal (GMV); platform
earnings are reported separately as commission.
"""

import csv
from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.paginator import Paginator
from django.db.models import Count, F, Max, Q, Sum, Avg
from django.db.models.functions import Coalesce, TruncDate
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import SellerProfile, User
from catalog.models import Category, Product, Review
from orders.models import Order, OrderItem
from orders.services import cancel_order

# Orders in these states represent real, settled business activity.
EARNING_STATUSES = [
    Order.Status.PAID,
    Order.Status.PROCESSING,
    Order.Status.SHIPPED,
    Order.Status.DELIVERED,
]

RANGE_CHOICES = [(7, "7 days"), (30, "30 days"), (90, "90 days"), (365, "12 months")]

PER_PAGE = 20


def _money(value):
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


def _date_range(request):
    """Resolve the ?days= window, defaulting to 30."""
    try:
        days = int(request.GET.get("days", 30))
    except (TypeError, ValueError):
        days = 30
    if days not in dict(RANGE_CHOICES):
        days = 30

    end = timezone.now()
    return end - timedelta(days=days), end, days


def _growth(current, previous):
    """Percentage change between two periods, or None when there is no base."""
    if not previous:
        return None
    return round(((current - previous) / previous) * 100, 1)


def _daily_series(orders, start, end):
    """Revenue per calendar day, with empty days filled in as zero."""
    rows = (
        orders.annotate(day=TruncDate("placed_at"))
        .values("day")
        .annotate(
            revenue=Coalesce(Sum("subtotal"), Decimal("0.00")),
            commission=Coalesce(Sum("commission"), Decimal("0.00")),
            orders=Count("id"),
        )
        .order_by("day")
    )
    by_day = {r["day"]: r for r in rows if r["day"]}

    series = []
    cursor = start.date()
    while cursor <= end.date():
        row = by_day.get(cursor)
        series.append(
            {
                "date": cursor,
                "revenue": float(row["revenue"]) if row else 0.0,
                "commission": float(row["commission"]) if row else 0.0,
                "orders": row["orders"] if row else 0,
            }
        )
        cursor += timedelta(days=1)
    return series


# ------------------------------------------------------------------- overview


@staff_member_required
def overview(request):
    start, end, days = _date_range(request)

    current = Order.objects.filter(
        placed_at__gte=start, status__in=EARNING_STATUSES
    )
    previous = Order.objects.filter(
        placed_at__gte=start - timedelta(days=days),
        placed_at__lt=start,
        status__in=EARNING_STATUSES,
    )

    pending_sellers_count = SellerProfile.objects.filter(
        status=SellerProfile.Status.PENDING
    ).count()
    review_queue = Review.objects.filter(is_approved=False).count()
    fulfilment_queue = Order.objects.filter(
        status__in=[Order.Status.PAID, Order.Status.PROCESSING]
    ).count()
    low_stock = Product.objects.filter(
        stock__gt=0, stock__lte=F("low_stock_threshold"), is_active=True
    ).count()

    priority_tasks = [
        {
            "title": "Approve new stores",
            "meta": f"{pending_sellers_count} sellers waiting",
            "link": "backoffice:sellers",
            "link_label": "Review",
            "tone": "warning",
        },
        {
            "title": "Moderate reviews",
            "meta": f"{review_queue} reviews pending",
            "link": "backoffice:reviews",
            "link_label": "Open queue",
            "tone": "danger",
        },
        {
            "title": "Resolve fulfilment",
            "meta": f"{fulfilment_queue} orders still moving",
            "link": "backoffice:orders",
            "link_label": "View orders",
            "tone": "info",
        },
        {
            "title": "Restock inventory",
            "meta": f"{low_stock} products under threshold",
            "link": "backoffice:products",
            "link_label": "Inspect stock",
            "tone": "neutral",
        },
    ]

    totals = current.aggregate(
        revenue=Coalesce(Sum("subtotal"), Decimal("0.00")),
        commission=Coalesce(Sum("commission"), Decimal("0.00")),
        shipping=Coalesce(Sum("shipping_fee"), Decimal("0.00")),
        orders=Count("id"),
        buyers=Count("buyer", distinct=True),
        sellers=Count("seller", distinct=True),
    )
    prev = previous.aggregate(
        revenue=Coalesce(Sum("subtotal"), Decimal("0.00")),
        orders=Count("id"),
    )

    revenue = _money(totals["revenue"])
    commission = _money(totals["commission"])
    order_count = totals["orders"] or 0
    payout = _money(revenue - commission)

    seller_health = {
        "approved": SellerProfile.objects.filter(
            status=SellerProfile.Status.APPROVED, is_active=True
        ).count(),
        "pending": pending_sellers_count,
        "pending_sellers": pending_sellers_count,
        "rejected": SellerProfile.objects.filter(
            status=SellerProfile.Status.REJECTED
        ).count(),
        "suspended": SellerProfile.objects.filter(
            status=SellerProfile.Status.SUSPENDED
        ).count(),
        "inactive": SellerProfile.objects.filter(is_active=False).count(),
    }
    seller_total = (
        seller_health["approved"]
        + seller_health["pending"]
        + seller_health["rejected"]
        + seller_health["suspended"]
        + seller_health["inactive"]
    ) or 1
    seller_health_summary = [
        {
            "key": "approved",
            "label": "Approved",
            "count": seller_health["approved"],
            "width": round((seller_health["approved"] / seller_total) * 100),
        },
        {
            "key": "pending",
            "label": "Pending",
            "count": seller_health["pending"],
            "width": round((seller_health["pending"] / seller_total) * 100),
        },
        {
            "key": "rejected",
            "label": "Rejected",
            "count": seller_health["rejected"],
            "width": round((seller_health["rejected"] / seller_total) * 100),
        },
        {
            "key": "suspended",
            "label": "Suspended",
            "count": seller_health["suspended"],
            "width": round((seller_health["suspended"] / seller_total) * 100),
        },
    ]

    kpis = [
        {
            "label": "Gross merchandise value",
            "value": revenue,
            "growth": _growth(revenue, _money(prev["revenue"])),
            "hint": f"vs previous {days} days",
        },
        {
            "label": "Platform commission",
            "value": commission,
            "growth": None,
            "hint": f"{settings.MARKETPLACE['COMMISSION_RATE']}% of each order",
        },
        {
            "label": "Seller payouts owed",
            "value": payout,
            "growth": None,
            "hint": "revenue less commission",
        },
        {
            "label": "Orders",
            "value": order_count,
            "growth": _growth(order_count, prev["orders"] or 0),
            "hint": f"from {totals['buyers']} buyer(s)",
        },
        {
            "label": "Average order value",
            "value": _money(revenue / order_count) if order_count else _money(0),
            "growth": None,
            "hint": "per order",
        },
        {
            "label": "Active sellers",
            "value": totals["sellers"] or 0,
            "growth": None,
            "hint": "with settled orders",
        },
        {
            "label": "Review queue",
            "value": review_queue,
            "growth": None,
            "hint": "awaiting moderation",
        },
        {
            "label": "Fulfilment queue",
            "value": fulfilment_queue,
            "growth": None,
            "hint": "payments or shipments in motion",
        },
        {
            "label": "Inventory risk",
            "value": low_stock,
            "growth": None,
            "hint": "products at or below threshold",
        },
    ]

    status_rows = (
        Order.objects.values("status")
        .annotate(count=Count("id"))
        .order_by("-count")
    )
    status_labels = dict(Order.Status.choices)
    status_breakdown = [
        {"status": r["status"], "label": status_labels.get(r["status"], r["status"]),
         "count": r["count"]}
        for r in status_rows
    ]

    top_sellers = list(
        current.values("seller__business_name", "seller_id")
        .annotate(
            revenue=Coalesce(Sum("subtotal"), Decimal("0.00")),
            commission=Coalesce(Sum("commission"), Decimal("0.00")),
            orders=Count("id"),
        )
        .order_by("-revenue")[:8]
    )

    category_rows = list(
        OrderItem.objects.filter(order__in=current)
        .values("product__category__name")
        .annotate(
            revenue=Coalesce(Sum("line_total"), Decimal("0.00")),
            units=Coalesce(Sum("quantity"), 0),
        )
        .order_by("-revenue")[:8]
    )

    top_products = list(
        OrderItem.objects.filter(order__in=current)
        .values("product_name", "product__seller__business_name")
        .annotate(
            units=Coalesce(Sum("quantity"), 0),
            revenue=Coalesce(Sum("line_total"), Decimal("0.00")),
        )
        .order_by("-units")[:8]
    )

    pending_sellers = list(
        SellerProfile.objects.filter(status=SellerProfile.Status.PENDING).order_by("created_at")
    )

    stock_alerts = list(
        Product.objects.select_related("seller")
        .filter(stock__lte=F("low_stock_threshold"))
        .order_by("stock", "name")[:10]
    )

    # Activity feed
    recent_users = list(
        User.objects.order_by("-date_joined")[:5]
    )
    recent_products = list(
        Product.objects.select_related("seller", "category")
        .order_by("-created_at")[:5]
    )
    recent_reviews_list = list(
        Review.objects.select_related("product", "product__seller", "user")
        .order_by("-created_at")[:5]
    )

    # Customer insights
    repeat_customers = list(
        User.objects.filter(role=User.Role.BUYER)
        .annotate(order_count=Count("orders"))
        .filter(order_count__gte=2)
        .order_by("-order_count")[:10]
    )
    top_buyers = list(
        current.values("buyer__email", "buyer_id")
        .annotate(
            orders=Count("id"),
            revenue=Coalesce(Sum("subtotal"), Decimal("0.00")),
        )
        .order_by("-revenue")[:8]
    )

    # Performance metrics
    conversion_rate = 0
    total_visits_data = Product.objects.aggregate(total=Sum("views_count"))
    total_visits = total_visits_data["total"] or 0
    if total_visits > 0:
        conversion_rate = round((order_count / total_visits) * 100, 2)

    avg_items_per_order = 0
    if order_count > 0:
        total_items = OrderItem.objects.filter(order__in=current).aggregate(
            total=Sum("quantity")
        )["total"] or 0
        avg_items_per_order = round(total_items / order_count, 2)

    # Shipping analytics
    free_shipping_orders = current.filter(shipping_fee=0).count()
    free_shipping_rate = round((free_shipping_orders / order_count * 100), 2) if order_count > 0 else 0

    return render(
        request,
        "backoffice/overview.html",
        {
            "kpis": kpis,
            "days": days,
            "range_choices": RANGE_CHOICES,
            "series": _daily_series(current, start, end),
            "status_breakdown": status_breakdown,
            "top_sellers": top_sellers,
            "category_rows": category_rows,
            "top_products": top_products,
            "recent_orders": current.select_related("seller", "buyer")[:10],
            "pending_sellers": pending_sellers,
            "stock_alerts": stock_alerts,
            "totals": totals,
            "seller_health": seller_health,
            "seller_health_summary": seller_health_summary,
            "review_queue": review_queue,
            "fulfilment_queue": fulfilment_queue,
            "low_stock": low_stock,
            "pending_sellers_count": pending_sellers_count,
            "priority_tasks": priority_tasks,
            "recent_users": recent_users,
            "recent_products": recent_products,
            "recent_reviews_list": recent_reviews_list,
            "repeat_customers": repeat_customers,
            "top_buyers": top_buyers,
            "conversion_rate": conversion_rate,
            "avg_items_per_order": avg_items_per_order,
            "free_shipping_rate": free_shipping_rate,
            "total_visits": total_visits,
        },
    )


# -------------------------------------------------------------------- sellers


@staff_member_required
def sellers(request):
    stores = SellerProfile.objects.select_related("user").annotate(
        product_total=Count("products", distinct=True),
        order_total=Count("orders", distinct=True),
        revenue=Coalesce(
            Sum("orders__subtotal", filter=Q(orders__status__in=EARNING_STATUSES)),
            Decimal("0.00"),
        ),
        commission=Coalesce(
            Sum("orders__commission", filter=Q(orders__status__in=EARNING_STATUSES)),
            Decimal("0.00"),
        ),
    )

    query = request.GET.get("q", "").strip()
    if query:
        stores = stores.filter(
            Q(business_name__icontains=query)
            | Q(user__email__icontains=query)
            | Q(business_address__icontains=query)
        )

    status = request.GET.get("status")
    if status:
        stores = stores.filter(status=status)

    sort = request.GET.get("sort", "-revenue")
    sort_map = {
        "-revenue": "-revenue",
        "revenue": "revenue",
        "-orders": "-order_total",
        "name": "business_name",
        "newest": "-created_at",
    }
    stores = stores.order_by(sort_map.get(sort, "-revenue"))

    page_obj = Paginator(stores, PER_PAGE).get_page(request.GET.get("page"))

    counts = {
        row["status"]: row["n"]
        for row in SellerProfile.objects.values("status").annotate(n=Count("id"))
    }
    status_tabs = [
        {"value": value, "label": label, "count": counts.get(value, 0)}
        for value, label in SellerProfile.Status.choices
    ]

    return render(
        request,
        "backoffice/sellers.html",
        {
            "page_obj": page_obj,
            "sellers": page_obj,
            "query": query,
            "status": status or "",
            "sort": sort,
            "status_tabs": status_tabs,
            "pending_count": counts.get(SellerProfile.Status.PENDING, 0),
        },
    )


@staff_member_required
def seller_detail(request, pk):
    store = get_object_or_404(SellerProfile.objects.select_related("user"), pk=pk)

    orders = store.orders.select_related("buyer").prefetch_related("items")
    financials = store.orders.filter(status__in=EARNING_STATUSES).aggregate(
        revenue=Coalesce(Sum("subtotal"), Decimal("0.00")),
        commission=Coalesce(Sum("commission"), Decimal("0.00")),
        shipping=Coalesce(Sum("shipping_fee"), Decimal("0.00")),
        orders=Count("id"),
    )

    product_stats = store.products.aggregate(
        total=Count("id"),
        live=Count("id", filter=Q(is_active=True)),
        out_of_stock=Count("id", filter=Q(stock=0)),
        low_stock=Count("id", filter=Q(stock__gt=0, stock__lte=F("low_stock_threshold"))),
        units=Coalesce(Sum("units_sold"), 0),
        stock_on_hand=Coalesce(Sum("stock"), 0),
    )

    return render(
        request,
        "backoffice/seller_detail.html",
        {
            "store": store,
            "orders": orders[:15],
            "order_count": orders.count(),
            "products": store.products.select_related("category")[:15],
            "product_stats": product_stats,
            "financials": financials,
            "payout": _money(financials["revenue"] - financials["commission"]),
            "status_choices": SellerProfile.Status.choices,
            "commission_rate": settings.MARKETPLACE["COMMISSION_RATE"],
        },
    )


@staff_member_required
@require_POST
def seller_status_change(request, pk):
    store = get_object_or_404(SellerProfile, pk=pk)
    new_status = request.POST.get("status")

    if new_status not in dict(SellerProfile.Status.choices):
        messages.error(request, "Unknown status.")
        return redirect("backoffice:seller_detail", pk=store.pk)

    store.status = new_status
    store.approved_at = timezone.now() if new_status == SellerProfile.Status.APPROVED else None
    store.rejection_reason = (
        request.POST.get("reason", "")[:255]
        if new_status in {SellerProfile.Status.REJECTED, SellerProfile.Status.SUSPENDED}
        else ""
    )
    store.save()
    messages.success(request, f"{store.business_name} is now {store.get_status_display().lower()}.")
    return redirect(request.POST.get("next") or "backoffice:sellers")


@staff_member_required
@require_POST
def sellers_bulk_action(request):
    action = request.POST.get("action")
    ids = request.POST.getlist("seller_ids")
    if not action or not ids:
        messages.warning(request, "Select at least one seller and an action.")
        return redirect("backoffice:sellers")

    stores = SellerProfile.objects.filter(pk__in=ids)
    count = stores.count()

    if action == "approve":
        stores.update(
            status=SellerProfile.Status.APPROVED,
            approved_at=timezone.now(),
            rejection_reason="",
        )
        messages.success(request, f"{count} seller(s) approved.")
    elif action == "suspend":
        stores.update(status=SellerProfile.Status.SUSPENDED)
        messages.success(request, f"{count} seller(s) suspended.")
    elif action == "reject":
        stores.update(status=SellerProfile.Status.REJECTED)
        messages.success(request, f"{count} seller(s) rejected.")
    elif action == "close":
        stores.update(is_active=False)
        messages.success(request, f"{count} storefront(s) closed.")
    elif action == "reopen":
        stores.update(is_active=True)
        messages.success(request, f"{count} storefront(s) reopened.")
    else:
        messages.error(request, "Unknown action.")

    return redirect("backoffice:sellers")


# --------------------------------------------------------------------- orders


@staff_member_required
def orders(request):
    queryset = Order.objects.select_related("buyer", "seller")

    query = request.GET.get("q", "").strip()
    if query:
        queryset = queryset.filter(
            Q(order_number__icontains=query)
            | Q(buyer__email__icontains=query)
            | Q(seller__business_name__icontains=query)
        )

    status = request.GET.get("status")
    if status:
        queryset = queryset.filter(status=status)

    if request.GET.get("unpaid") == "1":
        queryset = queryset.filter(payment_status=Order.PaymentStatus.UNPAID)

    queryset = queryset.order_by("-placed_at")
    page_obj = Paginator(queryset, PER_PAGE).get_page(request.GET.get("page"))

    counts = {
        row["status"]: row["n"]
        for row in Order.objects.values("status").annotate(n=Count("id"))
    }
    status_tabs = [
        {"value": value, "label": label, "count": counts.get(value, 0)}
        for value, label in Order.Status.choices
    ]

    return render(
        request,
        "backoffice/orders.html",
        {
            "page_obj": page_obj,
            "orders": page_obj,
            "query": query,
            "status": status or "",
            "status_choices": Order.Status.choices,
            "status_tabs": status_tabs,
            "unpaid_count": Order.objects.filter(
                payment_status=Order.PaymentStatus.UNPAID
            ).count(),
            "total_orders": Order.objects.count(),
        },
    )


@staff_member_required
@require_POST
def order_status_change(request, order_number):
    order = get_object_or_404(Order.objects.select_related("seller"), order_number=order_number)
    new_status = request.POST.get("status")

    if new_status == Order.Status.CANCELLED:
        ok, message = cancel_order(order)
        (messages.success if ok else messages.error)(request, message)
        return redirect(request.POST.get("next") or "backoffice:orders")

    if new_status not in dict(Order.Status.choices):
        messages.error(request, "Unknown status.")
        return redirect(request.POST.get("next") or "backoffice:orders")

    order.status = new_status
    tracking = request.POST.get("tracking_number", "").strip()
    if tracking:
        order.tracking_number = tracking
    order.save(update_fields=["status", "tracking_number", "updated_at"])
    messages.success(request, f"{order.order_number} set to {order.get_status_display().lower()}.")
    return redirect(request.POST.get("next") or "backoffice:orders")


# ------------------------------------------------------------------- products


@staff_member_required
def products(request):
    queryset = Product.objects.select_related("seller", "seller__user", "category")

    query = request.GET.get("q", "").strip()
    if query:
        queryset = queryset.filter(
            Q(name__icontains=query) | Q(sku__icontains=query)
        )

    seller_slug = request.GET.get("seller")
    if seller_slug:
        queryset = queryset.filter(seller__slug=seller_slug)

    category_slug = request.GET.get("category")
    if category_slug:
        queryset = queryset.filter(category__slug=category_slug)

    state = request.GET.get("state")
    if state == "active":
        queryset = queryset.filter(is_active=True)
    elif state == "hidden":
        queryset = queryset.filter(is_active=False)
    elif state == "out_of_stock":
        queryset = queryset.filter(stock=0)
    elif state == "low_stock":
        queryset = queryset.filter(stock__gt=0, stock__lte=F("low_stock_threshold"))
    elif state == "unapproved":
        queryset = queryset.exclude(seller__status=SellerProfile.Status.APPROVED)

    queryset = queryset.order_by("-created_at")
    page_obj = Paginator(queryset, PER_PAGE).get_page(request.GET.get("page"))

    return render(
        request,
        "backoffice/products.html",
        {
            "page_obj": page_obj,
            "products": page_obj,
            "query": query,
            "state": state or "",
            "seller_slug": seller_slug or "",
            "category_slug": category_slug or "",
            "categories": Category.objects.all(),
            "sellers": SellerProfile.objects.all().order_by("business_name"),
            "counts": {
                "total": Product.objects.count(),
                "active": Product.objects.filter(is_active=True).count(),
                "hidden": Product.objects.filter(is_active=False).count(),
                "out_of_stock": Product.objects.filter(stock=0).count(),
                "low_stock": Product.objects.filter(
                    stock__gt=0, stock__lte=F("low_stock_threshold")
                ).count(),
                "unapproved": Product.objects.exclude(
                    seller__status=SellerProfile.Status.APPROVED
                ).count(),
            },
        },
    )


@staff_member_required
@require_POST
def product_toggle(request, pk):
    product = get_object_or_404(Product.objects.select_related("seller"), pk=pk)
    product.is_active = not product.is_active
    product.save(update_fields=["is_active"])
    state = "listed" if product.is_active else "hidden"
    messages.success(request, f'"{product.name}" is now {state}.')
    return redirect(request.POST.get("next") or "backoffice:products")


# ------------------------------------------------------------------ customers


@staff_member_required
def customers(request):
    buyers = User.objects.filter(role=User.Role.BUYER).annotate(
        order_total=Count("orders", distinct=True),
        revenue=Coalesce(
            Sum(
                "orders__subtotal",
                filter=Q(orders__status__in=EARNING_STATUSES),
            ),
            Decimal("0.00"),
        ),
        last_order=Max("orders__placed_at"),
    )

    query = request.GET.get("q", "").strip()
    if query:
        buyers = buyers.filter(
            Q(email__icontains=query)
            | Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
        )

    sort = request.GET.get("sort", "-revenue")
    sort_map = {
        "-revenue": "-revenue",
        "-orders": "-order_total",
        "newest": "-date_joined",
        "name": "first_name",
    }
    buyers = buyers.order_by(sort_map.get(sort, "-revenue"))

    page_obj = Paginator(buyers, PER_PAGE).get_page(request.GET.get("page"))
    summary = User.objects.filter(role=User.Role.BUYER).aggregate(
        total=Count("id"),
        with_orders=Count("id", filter=Q(orders__isnull=False)),
        revenue=Coalesce(
            Sum("orders__subtotal", filter=Q(orders__status__in=EARNING_STATUSES)),
            Decimal("0.00"),
        ),
    )

    return render(
        request,
        "backoffice/customers.html",
        {
            "page_obj": page_obj,
            "customers": page_obj,
            "query": query,
            "sort": sort,
            "summary": summary,
        },
    )


# -------------------------------------------------------------------- reports


@staff_member_required
def reports(request):
    start, end, days = _date_range(request)

    earnings = Order.objects.filter(placed_at__gte=start, status__in=EARNING_STATUSES)

    payout_rows = list(
        earnings.values("seller__business_name", "seller_id")
        .annotate(
            orders=Count("id"),
            revenue=Coalesce(Sum("subtotal"), Decimal("0.00")),
            commission=Coalesce(Sum("commission"), Decimal("0.00")),
            shipping=Coalesce(Sum("shipping_fee"), Decimal("0.00")),
        )
        .order_by("-revenue")
    )
    for row in payout_rows:
        row["payout"] = _money(row["revenue"] - row["commission"])

    category_rows = list(
        OrderItem.objects.filter(order__in=earnings)
        .values("product__category__name")
        .annotate(
            revenue=Coalesce(Sum("line_total"), Decimal("0.00")),
            units=Coalesce(Sum("quantity"), 0),
        )
        .order_by("-revenue")
    )

    product_rows = list(
        OrderItem.objects.filter(order__in=earnings)
        .values("product_name", "product__seller__business_name")
        .annotate(
            units=Coalesce(Sum("quantity"), 0),
            revenue=Coalesce(Sum("line_total"), Decimal("0.00")),
        )
        .order_by("-revenue")[:25]
    )

    buyer_rows = list(
        earnings.values("buyer__email", "buyer_id")
        .annotate(
            orders=Count("id"),
            revenue=Coalesce(Sum("subtotal"), Decimal("0.00")),
        )
        .order_by("-revenue")[:25]
    )

    grand = earnings.aggregate(
        revenue=Coalesce(Sum("subtotal"), Decimal("0.00")),
        commission=Coalesce(Sum("commission"), Decimal("0.00")),
        shipping=Coalesce(Sum("shipping_fee"), Decimal("0.00")),
        orders=Count("id"),
    )
    grand_revenue = _money(grand["revenue"])
    grand_payout = _money(grand_revenue - grand["commission"])

    return render(
        request,
        "backoffice/reports.html",
        {
            "days": days,
            "range_choices": RANGE_CHOICES,
            "payout_rows": payout_rows,
            "category_rows": category_rows,
            "product_rows": product_rows,
            "buyer_rows": buyer_rows,
            "grand": grand,
            "grand_revenue": grand_revenue,
            "grand_payout": grand_payout,
            "commission_rate": settings.MARKETPLACE["COMMISSION_RATE"],
        },
    )


# -------------------------------------------------------------------- reviews


@staff_member_required
def reviews(request):
    queryset = Review.objects.select_related("product", "product__seller", "user")

    if request.GET.get("state") == "pending":
        queryset = queryset.filter(is_approved=False)
    if request.GET.get("state") == "low":
        queryset = queryset.filter(rating__lte=2)

    queryset = queryset.order_by("-created_at")
    page_obj = Paginator(queryset, PER_PAGE).get_page(request.GET.get("page"))

    return render(
        request,
        "backoffice/reviews.html",
        {
            "page_obj": page_obj,
            "reviews": page_obj,
            "state": request.GET.get("state", ""),
            "total": Review.objects.count(),
            "pending": Review.objects.filter(is_approved=False).count(),
            "low": Review.objects.filter(rating__lte=2).count(),
        },
    )


@staff_member_required
@require_POST
def reviews_bulk_action(request):
    """Approve or hide reviews in bulk, then refresh cached product ratings."""
    action = request.POST.get("action")
    ids = request.POST.getlist("review_ids")
    if not action or not ids:
        messages.warning(request, "Select at least one review and an action.")
        return redirect("backoffice:reviews")

    approved = action == "approve"
    # Collect affected products before the update so ratings can be rebuilt.
    product_ids = set(
        Review.objects.filter(pk__in=ids).values_list("product_id", flat=True)
    )
    count = Review.objects.filter(pk__in=ids).update(is_approved=approved)

    for product in Product.objects.filter(pk__in=product_ids):
        product.recalculate_rating()

    messages.success(
        request,
        f"{count} review(s) {'published' if approved else 'hidden'}.",
    )
    return redirect(request.POST.get("next") or "backoffice:reviews")


@staff_member_required
def export_dashboard_csv(request):
    """Export a concise dashboard summary to CSV."""
    start, end, days = _date_range(request)
    revenue_total = Order.objects.filter(
        placed_at__gte=start, status__in=EARNING_STATUSES
    ).aggregate(total=Coalesce(Sum("subtotal"), Decimal("0.00"))) ["total"] or Decimal("0.00")
    commission_total = Order.objects.filter(
        placed_at__gte=start, status__in=EARNING_STATUSES
    ).aggregate(total=Coalesce(Sum("commission"), Decimal("0.00"))) ["total"] or Decimal("0.00")

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["metric", "value"])
    writer.writerow(["period_days", days])
    writer.writerow(["gmv", str(revenue_total)])
    writer.writerow(["commission", str(commission_total)])
    writer.writerow(["order_count", Order.objects.filter(placed_at__gte=start, status__in=EARNING_STATUSES).count()])
    writer.writerow(["pending_sellers", SellerProfile.objects.filter(status=SellerProfile.Status.PENDING).count()])
    writer.writerow(["review_queue", Review.objects.filter(is_approved=False).count()])
    writer.writerow(["low_stock_products", Product.objects.filter(stock__gt=0, stock__lte=F("low_stock_threshold"), is_active=True).count()])
    writer.writerow([])
    writer.writerow(["order_number", "seller", "buyer", "status", "total", "placed_at"])

    for order in (
        Order.objects.filter(placed_at__gte=start, status__in=EARNING_STATUSES)
        .select_related("seller", "buyer")
        .order_by("-placed_at")[:50]
    ):
        writer.writerow([
            order.order_number,
            order.seller.business_name,
            order.buyer.email,
            order.get_status_display(),
            str(order.total),
            order.placed_at.isoformat(),
        ])

    response = HttpResponse(output.getvalue(), content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="marketplace_dashboard.csv"'
    return response
