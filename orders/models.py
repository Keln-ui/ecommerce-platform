import uuid
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.urls import reverse


class Cart(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="cart"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Cart for {self.user.email}"

    @property
    def line_items(self):
        """Cart lines with product and seller preloaded.

        Named `line_items` because `items` is already the reverse relation name.
        """
        return self.items.select_related("product", "product__seller").all()

    @property
    def item_count(self):
        return sum(item.quantity for item in self.line_items)

    @property
    def subtotal(self):
        return sum((item.line_total for item in self.line_items), Decimal("0.00"))

    @property
    def is_empty(self):
        return not self.items.exists()

    def shipping_fee(self):
        """Flat fee charged once per distinct seller in the cart."""
        if self.is_empty:
            return Decimal("0.00")
        return self._fee() * self.seller_count()

    @property
    def total(self):
        return self.subtotal + self.shipping_fee()

    def seller_count(self):
        return len({item.product.seller_id for item in self.line_items})

    @staticmethod
    def _fee():
        return Decimal(str(settings.MARKETPLACE["SHIPPING_FEE"]))

    def group_by_seller(self):
        """Group cart lines per seller.

        Returns {seller: {items, subtotal, shipping, total}} so templates can show
        a per-store summary without custom template filters.
        """
        buckets = {}
        for item in self.line_items:
            buckets.setdefault(item.product.seller, []).append(item)

        fee = self._fee()
        grouped = {}
        for seller, items in buckets.items():
            subtotal = sum((i.line_total for i in items), Decimal("0.00"))
            # Free shipping on every item waives the whole seller order's fee.
            shipping = Decimal("0.00") if all(
                i.product.free_shipping for i in items
            ) else fee
            grouped[seller] = {
                "seller": seller,
                "items": items,
                "subtotal": subtotal,
                "shipping": shipping,
                "total": subtotal + shipping,
            }
        return grouped


class CartItem(models.Model):
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(
        "catalog.Product", on_delete=models.CASCADE, related_name="cart_items"
    )
    quantity = models.PositiveIntegerField(
        default=1, validators=[MinValueValidator(1)]
    )
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["cart", "product"], name="unique_cart_product")
        ]

    def __str__(self):
        return f"{self.quantity} x {self.product.name}"

    @property
    def line_total(self):
        return self.product.price * self.quantity

    @property
    def exceeds_stock(self):
        return self.quantity > self.product.stock


class Order(models.Model):
    """One order per seller: a single checkout across N stores creates N orders."""

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending payment"
        PAID = "PAID", "Paid"
        PROCESSING = "PROCESSING", "Being prepared"
        SHIPPED = "SHIPPED", "Shipped"
        DELIVERED = "DELIVERED", "Delivered"
        CANCELLED = "CANCELLED", "Cancelled"
        REFUNDED = "REFUNDED", "Refunded"

    class PaymentStatus(models.TextChoices):
        UNPAID = "UNPAID", "Unpaid"
        PAID = "PAID", "Paid"
        REFUNDED = "REFUNDED", "Refunded"
        FAILED = "FAILED", "Failed"

    # Which status moves are legal. Enforced in views.seller_order_update.
    ALLOWED_TRANSITIONS = {
        Status.PAID: {Status.PROCESSING, Status.CANCELLED},
        Status.PROCESSING: {Status.SHIPPED, Status.CANCELLED},
        Status.SHIPPED: {Status.DELIVERED},
    }

    order_number = models.CharField(max_length=32, unique=True, editable=False)
    buyer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="orders"
    )
    seller = models.ForeignKey(
        "accounts.SellerProfile", on_delete=models.PROTECT, related_name="orders"
    )

    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    payment_status = models.CharField(
        max_length=10, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID
    )
    payment_method = models.CharField(max_length=32, default="COD")

    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    shipping_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    commission = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # Snapshot of the delivery address so later profile edits never rewrite history.
    ship_to_name = models.CharField(max_length=150)
    ship_to_phone = models.CharField(max_length=32, blank=True)
    ship_to_address = models.TextField(blank=True)

    tracking_number = models.CharField(max_length=64, blank=True)
    notes = models.CharField(max_length=255, blank=True)
    placed_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-placed_at"]
        indexes = [
            models.Index(fields=["buyer", "-placed_at"]),
            models.Index(fields=["seller", "status"]),
        ]

    def __str__(self):
        return self.order_number

    def save(self, *args, **kwargs):
        if not self.order_number:
            self.order_number = self._generate_order_number()
        super().save(*args, **kwargs)

    @staticmethod
    def _generate_order_number():
        return f"ORD-{uuid.uuid4().hex[:12].upper()}"

    def get_absolute_url(self):
        return reverse("orders:order_detail", kwargs={"order_number": self.order_number})

    @property
    def item_count(self):
        return sum(item.quantity for item in self.items.all())

    @property
    def seller_payout(self):
        """What the seller earns: subtotal less platform commission."""
        return self.subtotal - self.commission

    @property
    def is_cancellable(self):
        return self.status in {self.Status.PENDING, self.Status.PAID, self.Status.PROCESSING}


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    # The product may later be edited or deleted; the snapshot fields still render.
    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="order_items",
    )
    product_name = models.CharField(max_length=180)
    product_sku = models.CharField(max_length=64)
    product_image = models.ImageField(upload_to="order-snapshots/", null=True, blank=True)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.PositiveIntegerField(default=1)
    line_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["order", "product"], name="unique_order_product")
        ]

    def __str__(self):
        return f"{self.quantity} x {self.product_name}"

    def save(self, *args, **kwargs):
        if not self.line_total:
            self.line_total = self.unit_price * self.quantity
        super().save(*args, **kwargs)
