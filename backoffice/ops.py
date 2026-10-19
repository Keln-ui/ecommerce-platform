"""Reusable aggregates for the admin index and the back office dashboard."""

from django.db.models import Count, F, Q, Sum
from django.db.models.functions import Coalesce

from catalog.models import Product, Review
from orders.models import Order
from accounts.models import SellerProfile

from decimal import Decimal

# Orders that represent settled business activity.
EARNING_STATUSES = [
    Order.Status.PAID,
    Order.Status.PROCESSING,
    Order.Status.SHIPPED,
    Order.Status.DELIVERED,
]


def ops_snapshot(days: int = 30):
    """Headline figures and attention queues for the admin index.

    Used by the Django admin landing page so staff see marketplace health
    without leaving the admin, and by the back office dashboard.
    """
    from django.utils import timezone
    from datetime import timedelta

    start = timezone.now() - timedelta(days=days)

    settled = Order.objects.filter(
        placed_at__gte=start, status__in=EARNING_STATUSES
    )
    totals = settled.aggregate(
        revenue=Coalesce(Sum("subtotal"), Decimal("0.00")),
        commission=Coalesce(Sum("commission"), Decimal("0.00")),
        orders=Count("id"),
    )
    revenue = totals["revenue"] or Decimal("0.00")

    seller_health = {
        "approved": SellerProfile.objects.filter(
            status=SellerProfile.Status.APPROVED, is_active=True
        ).count(),
        "pending": SellerProfile.objects.filter(
            status=SellerProfile.Status.PENDING
        ).count(),
        "pending_sellers": SellerProfile.objects.filter(
            status=SellerProfile.Status.PENDING
        ).count(),
        "rejected": SellerProfile.objects.filter(
            status=SellerProfile.Status.REJECTED
        ).count(),
        "suspended": SellerProfile.objects.filter(
            status=SellerProfile.Status.SUSPENDED
        ).count(),
        "inactive": SellerProfile.objects.filter(is_active=False).count(),
    }

    attention = {
        "pending_sellers": seller_health["pending"],
        "unpaid_orders": Order.objects.filter(
            payment_status=Order.PaymentStatus.UNPAID
        ).count(),
        "awaiting_fulfilment": Order.objects.filter(
            status__in=[Order.Status.PAID, Order.Status.PROCESSING]
        ).count(),
        "out_of_stock": Product.objects.filter(stock=0, is_active=True).count(),
        "low_stock": Product.objects.filter(
            stock__gt=0, stock__lte=F("low_stock_threshold"), is_active=True
        ).count(),
        "hidden_reviews": Review.objects.filter(is_approved=False).count(),
        "review_queue": Review.objects.filter(is_approved=False).count(),
    }

    return {
        "days": days,
        "revenue": revenue,
        "commission": totals["commission"] or Decimal("0.00"),
        "payout": revenue - (totals["commission"] or Decimal("0.00")),
        "orders": totals["orders"] or 0,
        "sellers": SellerProfile.objects.filter(
            status=SellerProfile.Status.APPROVED
        ).count(),
        "products": Product.objects.filter(is_active=True).count(),
        "seller_health": seller_health,
        "attention": attention,
        "attention_total": sum(attention.values()),
        "recent_orders": (
            Order.objects.select_related("seller", "buyer").order_by("-placed_at")[:8]
        ),
        "pending_sellers_list": SellerProfile.objects.filter(
            status=SellerProfile.Status.PENDING
        ).order_by("created_at")[:6],
    }