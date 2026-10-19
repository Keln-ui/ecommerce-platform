from django.contrib import admin

from .models import Cart, CartItem, Order, OrderItem


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    fields = ("product_name", "product_sku", "unit_price", "quantity", "line_total")
    readonly_fields = fields


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "order_number",
        "buyer",
        "seller",
        "status",
        "payment_status",
        "subtotal",
        "commission",
        "seller_payout",
        "placed_at",
    )
    list_filter = ("status", "payment_status", "seller")
    search_fields = ("order_number", "buyer__email", "seller__business_name")
    readonly_fields = (
        "order_number",
        "placed_at",
        "updated_at",
        "subtotal",
        "commission",
        "total",
    )
    inlines = [OrderItemInline]
    date_hierarchy = "placed_at"
    actions = ["mark_shipped", "mark_delivered"]

    @admin.display(description="Seller payout")
    def seller_payout(self, obj):
        return f"{obj.seller_payout:.2f}"

    @admin.action(description="Mark selected orders as shipped")
    def mark_shipped(self, request, queryset):
        self.message_user(
            request,
            f"{queryset.filter(status=Order.Status.PROCESSING).update(status=Order.Status.SHIPPED)} order(s) shipped.",
        )

    @admin.action(description="Mark selected orders as delivered")
    def mark_delivered(self, request, queryset):
        self.message_user(
            request,
            f"{queryset.filter(status=Order.Status.SHIPPED).update(status=Order.Status.DELIVERED)} order(s) delivered.",
        )
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "order_number",
                    "buyer",
                    "seller",
                    "status",
                    "payment_status",
                    "payment_method",
                )
            },
        ),
        ("Money", {"fields": ("subtotal", "shipping_fee", "commission", "total")}),
        (
            "Shipping",
            {
                "fields": (
                    "ship_to_name",
                    "ship_to_phone",
                    "ship_to_address",
                    "tracking_number",
                    "notes",
                )
            },
        ),
        ("Meta", {"fields": ("placed_at", "updated_at")}),
    )


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = ("order", "product_name", "unit_price", "quantity", "line_total")
    search_fields = ("product_name", "product_sku", "order__order_number")


@admin.register(Cart)
class CartAdmin(admin.ModelAdmin):
    list_display = ("user", "item_count", "subtotal", "updated_at")

    @admin.display(description="Items")
    def item_count(self, obj):
        return obj.item_count

    @admin.display(description="Subtotal")
    def subtotal(self, obj):
        return f"{obj.subtotal:.2f}"


@admin.register(CartItem)
class CartItemAdmin(admin.ModelAdmin):
    list_display = ("cart", "product", "quantity", "line_total")
    search_fields = ("product__name", "cart__user__email")
