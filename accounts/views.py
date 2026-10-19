from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, LogoutView
from django.contrib.auth.views import (
    PasswordResetConfirmView,
    PasswordResetCompleteView,
    PasswordResetDoneView,
    PasswordResetView,
)
from django.db.models import Count, Sum
from django.db.models.functions import Coalesce
from django.shortcuts import redirect, render, get_object_or_404
from django.urls import reverse_lazy
from django.utils import timezone
from decimal import Decimal

from orders.models import Order

from .decorators import seller_required
from .forms import (
    SellerOnboardingForm,
    SellerSettingsForm,
    UserLoginForm,
    UserProfileForm,
    UserRegistrationForm,
)
from .models import SellerProfile, SellerSubscription, SubscriptionPlan, User


class MarketplaceLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = UserLoginForm
    redirect_authenticated_user = True

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['google_oauth_url'] = '/accounts/google/login/'
        return context


class MarketplaceLogoutView(LogoutView):
    next_page = "catalog:home"


def register(request):
    """Create a buyer account using an email address."""
    if request.user.is_authenticated:
        return redirect("catalog:home")

    form = UserRegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        messages.success(request, "Welcome to the marketplace! Your account is ready.")
        return redirect("catalog:home")

    return render(request, "accounts/register.html", {"form": form, "google_oauth_url": '/accounts/google/login/'})


@login_required
def seller_onboard(request):
    """Collect business details and create the seller's storefront."""
    if request.user.is_authenticated and request.user.is_seller:
        return redirect("accounts:seller_status")

    store = getattr(request.user, "seller_store", None)

    initial = {}
    if request.user.is_authenticated:
        initial = {
            "contact_email": request.user.email,
            "contact_phone": request.user.phone,
            "business_address": request.user.shipping_address,
        }

    form = SellerOnboardingForm(
        request.POST or None, request.FILES or None, instance=store, initial=initial
    )

    # Get available subscription plans
    plans = SubscriptionPlan.objects.filter(is_active=True)

    if request.method == "POST" and form.is_valid():
        seller = form.save(commit=False)
        seller.user = request.user

        if settings.MARKETPLACE["AUTO_APPROVE_SELLERS"]:
            seller.status = SellerProfile.Status.APPROVED
            seller.approved_at = timezone.now()

        seller.save()
        request.user.role = User.Role.SELLER
        request.user.save(update_fields=["role"])

        # Create subscription
        plan_id = request.POST.get("subscription_plan")
        if plan_id:
            try:
                plan = SubscriptionPlan.objects.get(id=plan_id, is_active=True)
                subscription = SellerSubscription.objects.create(
                    seller=seller,
                    plan=plan,
                    status="PENDING"
                )
                messages.info(request, f"Please complete payment for the {plan.name} plan (KSh {plan.price}).")
                return redirect("accounts:subscription_payment", subscription.id)
            except SubscriptionPlan.DoesNotExist:
                messages.error(request, "Invalid subscription plan selected.")
        else:
            messages.error(request, "Please select a subscription plan.")
            return redirect("accounts:seller_onboard")

        if seller.is_approved:
            messages.success(request, "Your store is live! Start listing your products.")
            return redirect("sellers:dashboard")

        messages.info(
            request, "Application received. Our team will review it shortly."
        )
        return redirect("accounts:seller_status")

    return render(request, "accounts/seller_onboard.html", {"form": form, "plans": plans})


@login_required
def seller_status(request):
    store = getattr(request.user, "seller_store", None)
    return render(request, "accounts/seller_status.html", {"store": store})


@login_required
@seller_required
def seller_settings(request):
    store = request.seller
    form = SellerSettingsForm(request.POST or None, request.FILES or None, instance=store)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Store settings updated.")
        return redirect("sellers:dashboard")
    return render(
        request, "accounts/seller_settings.html", {"form": form, "store": store}
    )


@login_required
def profile(request):
    form = UserProfileForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Profile updated.")
        return redirect("accounts:profile")
    
    # Fetch buyer stats and activity
    orders = request.user.orders.select_related("seller", "seller__user").prefetch_related("items")
    paid_orders = orders.filter(payment_status=Order.PaymentStatus.PAID)
    
    total_spent = paid_orders.aggregate(total=Sum("total"))["total"] or 0
    total_orders = orders.count()
    
    # Average order value
    avg_order_value = Decimal("0.00")
    if total_orders > 0:
        avg_order_value = total_spent / total_orders
    
    # Favorite sellers (based on order count)
    favorite_sellers = list(
        orders.values("seller__business_name", "seller__slug", "seller_id")
        .annotate(order_count=Count("id"))
        .order_by("-order_count")[:5]
    )
    
    # Recent purchases
    recent_purchases = orders.order_by("-placed_at")[:5]
    
    # Reviews written by user
    from catalog.models import Review
    user_reviews = Review.objects.filter(user=request.user).select_related("product")[:5]
    
    return render(
        request,
        "accounts/profile.html",
        {
            "form": form,
            "total_spent": total_spent,
            "total_orders": total_orders,
            "avg_order_value": avg_order_value,
            "favorite_sellers": favorite_sellers,
            "recent_purchases": recent_purchases,
            "user_reviews": user_reviews,
        },
    )


@login_required
def subscription_payment(request, subscription_id):
    """Mock payment page for seller subscription."""
    subscription = get_object_or_404(SellerSubscription, id=subscription_id, seller__user=request.user)
    
    if request.method == "POST":
        # Mock payment processing
        subscription.activate()
        messages.success(request, f"Payment successful! Your {subscription.plan.name} subscription is now active.")
        return redirect("sellers:dashboard")
    
    return render(request, "accounts/subscription_payment.html", {"subscription": subscription})


@login_required
def order_history(request):
    orders = (
        request.user.orders.select_related("seller", "seller__user")
        .prefetch_related("items")
    )
    paid = [Order.PaymentStatus.PAID]
    totals = orders.filter(payment_status__in=paid).aggregate(
        total=Sum("total"), count=Count("id")
    )
    
    # Additional buyer stats
    recent_orders = orders.order_by("-placed_at")[:5]
    
    # Spending by seller
    spending_by_seller = list(
        orders.values("seller__business_name", "seller_id")
        .annotate(
            order_count=Count("id"),
            total_spent=Coalesce(Sum("total"), Decimal("0.00")),
        )
        .order_by("-total_spent")[:5]
    )
    
    return render(
        request,
        "accounts/order_history.html",
        {
            "orders": orders,
            "total_spent": totals["total"] or 0,
            "order_count": totals["count"],
            "recent_orders": recent_orders,
            "spending_by_seller": spending_by_seller,
        },
    )


class MarketplacePasswordResetView(PasswordResetView):
    """Send a password-reset link to the user's email address."""
    template_name = "accounts/password_reset_form.html"
    email_template_name = "accounts/password_reset_email.html"
    subject_template_name = "accounts/password_reset_subject.txt"
    success_url = reverse_lazy("accounts:password_reset_done")
    from_email = settings.DEFAULT_FROM_EMAIL


class MarketplacePasswordResetDoneView(PasswordResetDoneView):
    """Confirmation that the reset email was sent."""
    template_name = "accounts/password_reset_done.html"


class MarketplacePasswordResetConfirmView(PasswordResetConfirmView):
    """Set a new password using the uidb64/token link from the email."""
    template_name = "accounts/password_reset_confirm.html"
    success_url = reverse_lazy("accounts:password_reset_complete")


class MarketplacePasswordResetCompleteView(PasswordResetCompleteView):
    """Confirmation that the password was changed."""
    template_name = "accounts/password_reset_complete.html"
