from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils import timezone
from django.utils.html import format_html

from .models import SellerProfile, SellerSubscription, SubscriptionPlan, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("email", "full_name", "role_badge", "is_staff_badge", "date_joined")
    list_display_links = ("email",)
    list_filter = ("role", "is_staff", "is_superuser", "is_active")
    search_fields = ("email", "first_name", "last_name")
    ordering = ("-date_joined",)
    readonly_fields = ("date_joined", "last_login", "email", "shipping_address_summary")

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Profile", {
            "fields": (
                "first_name",
                "last_name",
                "phone",
                "role",
                "shipping_address_summary",
            ),
        }),
        ("Permissions", {
            "fields": (
                "is_active",
                "is_staff",
                "is_superuser",
                "groups",
                "user_permissions",
            ),
            "classes": ("collapse",),
        }),
        ("Important dates", {
            "fields": ("last_login", "date_joined"),
            "classes": ("collapse",),
        }),
        ("Address", {
            "fields": (
                "address_line1",
                "address_line2",
                "city",
                "postal_code",
                "country",
            ),
            "classes": ("collapse",),
        }),
    )

    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": (
                "email",
                "first_name",
                "last_name",
                "role",
                "password1",
                "password2",
            ),
        }),
    )

    def full_name(self, obj):
        return obj.get_full_name() or obj.email
    full_name.short_description = "Name"
    full_name.admin_order_field = "first_name"

    def role_badge(self, obj):
        colors = {
            User.Role.BUYER: "#0d6b3e",
            User.Role.SELLER: "#5b21b6",
            User.Role.STAFF: "#c77700",
        }
        color = colors.get(obj.role, "#6b7382")
        return format_html(
            '<span style="background:{1}20;color:{1};border:1px solid {1}40;padding:2px 8px;border-radius:999px;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.03em">{0}</span>',
            obj.get_role_display(),
            color,
        )
    role_badge.short_description = "Role"

    def is_staff_badge(self, obj):
        if obj.is_staff:
            return format_html('<span style="color:#0d6b3e;font-weight:700;">&#10003;</span>')
        return format_html('<span style="color:#c62828;">&#10007;</span>')
    is_staff_badge.short_description = "Staff"

    def shipping_address_summary(self, obj):
        addr = obj.shipping_address
        return addr if addr else "—"
    shipping_address_summary.short_description = "Shipping address"


@admin.register(SellerProfile)
class SellerProfileAdmin(admin.ModelAdmin):
    list_display = ("business_name", "user_email", "status_badge", "is_active_badge", "rating_average", "created_at")
    list_display_links = ("business_name",)
    list_filter = ("status", "is_active")
    search_fields = ("business_name", "user__email", "business_address")
    readonly_fields = ("created_at", "updated_at", "approved_at", "rating_average", "rating_count")
    actions = [
        "approve_sellers",
        "suspend_sellers",
        "reject_sellers",
        "close_storefronts",
        "reopen_storefronts",
    ]

    fieldsets = (
        (None, {
            "fields": (
                "user",
                "business_name",
                "slug",
                "tagline",
                "description",
            ),
        }),
        ("Status & Visibility", {
            "fields": (
                "status",
                "is_active",
                "rejection_reason",
            ),
        }),
        ("Contact", {
            "fields": (
                "contact_email",
                "contact_phone",
                "business_address",
                "tax_id",
            ),
        }),
        ("Branding", {
            "fields": (
                "logo",
                "banner",
            ),
        }),
        ("Ratings", {
            "fields": (
                "rating_average",
                "rating_count",
            ),
            "classes": ("collapse",),
        }),
        ("Timestamps", {
            "fields": (
                "created_at",
                "updated_at",
                "approved_at",
            ),
            "classes": ("collapse",),
        }),
    )

    def user_email(self, obj):
        return obj.user.email
    user_email.short_description = "Owner"
    user_email.admin_order_field = "user__email"

    def status_badge(self, obj):
        colors = {
            SellerProfile.Status.PENDING: "#c77700",
            SellerProfile.Status.APPROVED: "#0d6b3e",
            SellerProfile.Status.REJECTED: "#c62828",
            SellerProfile.Status.SUSPENDED: "#6b7382",
        }
        color = colors.get(obj.status, "#6b7382")
        return format_html(
            '<span style="background:{1}20;color:{1};border:1px solid {1}40;padding:2px 8px;border-radius:999px;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.03em">{0}</span>',
            obj.get_status_display(),
            color,
        )
    status_badge.short_description = "Status"

    def is_active_badge(self, obj):
        if obj.is_active:
            return format_html('<span style="color:#0d6b3e;font-weight:700;">&#10003;</span>')
        return format_html('<span style="color:#c62828;">&#10007;</span>')
    is_active_badge.short_description = "Active"

    @admin.action(description="Approve selected sellers")
    def approve_sellers(self, request, queryset):
        updated = queryset.update(
            status=SellerProfile.Status.APPROVED,
            approved_at=timezone.now(),
            rejection_reason="",
        )
        self.message_user(request, f"{updated} seller(s) approved.")

    @admin.action(description="Suspend selected sellers")
    def suspend_sellers(self, request, queryset):
        count = queryset.update(status=SellerProfile.Status.SUSPENDED)
        self.message_user(request, f"{count} seller(s) suspended.")

    @admin.action(description="Reject selected sellers")
    def reject_sellers(self, request, queryset):
        count = queryset.update(status=SellerProfile.Status.REJECTED)
        self.message_user(request, f"{count} seller(s) rejected.")

    @admin.action(description="Close selected storefronts")
    def close_storefronts(self, request, queryset):
        count = queryset.update(is_active=False)
        self.message_user(request, f"{count} storefront(s) closed.")

    @admin.action(description="Reopen selected storefronts")
    def reopen_storefronts(self, request, queryset):
        count = queryset.update(is_active=True)
        self.message_user(request, f"{count} storefront(s) reopened.")


@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    list_display = ("name", "plan_type", "price", "is_active", "created_at")
    list_display_links = ("name",)
    list_filter = ("plan_type", "is_active")
    search_fields = ("name", "description")
    ordering = ("price",)


@admin.register(SellerSubscription)
class SellerSubscriptionAdmin(admin.ModelAdmin):
    list_display = ("seller_link", "plan", "status_badge", "start_date", "end_date", "auto_renew")
    list_display_links = ("seller_link",)
    list_filter = ("status", "plan__plan_type", "auto_renew")
    search_fields = ("seller__business_name", "seller__user__email")
    readonly_fields = ("created_at", "updated_at")
    actions = ["activate_subscriptions", "expire_subscriptions"]

    fieldsets = (
        (None, {
            "fields": (
                "seller",
                "plan",
                "status",
                "auto_renew",
            ),
        }),
        ("Period", {
            "fields": (
                "start_date",
                "end_date",
            ),
        }),
        ("Timestamps", {
            "fields": (
                "created_at",
                "updated_at",
            ),
            "classes": ("collapse",),
        }),
    )

    def seller_link(self, obj):
        return obj.seller.business_name
    seller_link.short_description = "Seller"
    seller_link.admin_order_field = "seller__business_name"

    def status_badge(self, obj):
        colors = {
            "ACTIVE": "#0d6b3e",
            "EXPIRED": "#c62828",
            "CANCELLED": "#6b7382",
            "PENDING": "#c77700",
        }
        color = colors.get(obj.status, "#6b7382")
        return format_html(
            '<span style="background:{1}20;color:{1};border:1px solid {1}40;padding:2px 8px;border-radius:999px;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.03em">{0}</span>',
            obj.get_status_display(),
            color,
        )
    status_badge.short_description = "Status"

    @admin.action(description="Activate selected subscriptions")
    def activate_subscriptions(self, request, queryset):
        for sub in queryset:
            sub.activate()
        self.message_user(request, f"{queryset.count()} subscription(s) activated.")

    @admin.action(description="Expire selected subscriptions")
    def expire_subscriptions(self, request, queryset):
        count = queryset.update(status="EXPIRED")
        self.message_user(request, f"{count} subscription(s) expired.")
