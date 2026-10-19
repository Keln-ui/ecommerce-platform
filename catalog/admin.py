from django.contrib import admin
from django.db.models import F

from .models import Category, Product, ProductImage, Review


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 1
    fields = ("image", "alt_text", "is_primary", "display_order")


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "parent", "display_order", "is_active", "product_total")
    list_filter = ("is_active",)
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}
    ordering = ("display_order", "name")

    @admin.display(description="Products")
    def product_total(self, obj):
        return obj.active_product_count


class StockStatusFilter(admin.SimpleListFilter):
    """Group products by how urgently they need restocking."""

    title = "stock level"
    parameter_name = "stock_level"

    def lookups(self, request, model_admin):
        return (
            ("out", "Out of stock"),
            ("low", "Low stock"),
            ("healthy", "Healthy"),
        )

    def queryset(self, request, queryset):
        if self.value() == "out":
            return queryset.filter(stock=0)
        if self.value() == "low":
            return queryset.filter(stock__gt=0, stock__lte=F("low_stock_threshold"))
        if self.value() == "healthy":
            return queryset.filter(stock__gt=F("low_stock_threshold"))
        return queryset


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "seller",
        "category",
        "price",
        "stock",
        "stock_status",
        "is_active",
        "is_featured",
    )
    list_filter = ("is_active", "is_featured", "category", "seller", StockStatusFilter)
    search_fields = ("name", "sku", "seller__business_name")
    readonly_fields = (
        "views_count",
        "units_sold",
        "rating_average",
        "rating_count",
        "created_at",
    )
    inlines = [ProductImageInline]
    prepopulated_fields = {"slug": ("name",)}
    list_editable = ("price", "is_active", "is_featured")
    actions = ["activate_products", "deactivate_products"]

    @admin.display(description="Stock level", ordering="stock")
    def stock_status(self, obj):
        if obj.stock == 0:
            return "Out of stock"
        return "Low" if obj.is_low_stock else "Healthy"

    @admin.action(description="List selected products")
    def activate_products(self, request, queryset):
        self.message_user(request, f"{queryset.update(is_active=True)} product(s) listed.")

    @admin.action(description="Hide selected products")
    def deactivate_products(self, request, queryset):
        self.message_user(request, f"{queryset.update(is_active=False)} product(s) hidden.")
    fieldsets = (
        (None, {"fields": ("seller", "category", "name", "slug", "sku")}),
        ("Description", {"fields": ("short_description", "description")}),
        ("Pricing", {"fields": ("price", "compare_at_price", "free_shipping")}),
        ("Inventory", {"fields": ("stock", "low_stock_threshold")}),
        ("Visibility", {"fields": ("is_active", "is_featured")}),
        (
            "Stats",
            {
                "fields": (
                    "views_count",
                    "units_sold",
                    "rating_average",
                    "rating_count",
                    "created_at",
                )
            },
        ),
    )


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ("product", "user", "rating", "is_approved", "created_at")
    list_filter = ("is_approved", "rating", "created_at")
    search_fields = ("product__name", "user__email", "title", "comment")
    list_editable = ("is_approved",)
    actions = ["approve_reviews", "unapprove_reviews"]

    def _set_visibility(self, request, queryset, is_approved):
        """Publish or hide reviews and refresh the cached product ratings.

        `queryset.update()` bypasses `Review.save()`, which is what normally
        keeps `Product.rating_average` in step, so recalculate explicitly.
        """
        product_ids = set(queryset.values_list("product_id", flat=True))
        updated = queryset.update(is_approved=is_approved)

        for product in Product.objects.filter(pk__in=product_ids):
            product.recalculate_rating()

        verb = "approved" if is_approved else "hidden"
        self.message_user(request, f"{updated} review(s) {verb}.")

    @admin.action(description="Approve selected reviews")
    def approve_reviews(self, request, queryset):
        self._set_visibility(request, queryset, True)

    @admin.action(description="Unapprove selected reviews")
    def unapprove_reviews(self, request, queryset):
        self._set_visibility(request, queryset, False)
