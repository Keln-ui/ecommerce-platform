from functools import wraps

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect

from .models import SellerProfile


def seller_required(view_func):
    """Only users with an approved storefront may reach seller tooling."""

    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            messages.info(request, "Please sign in to open a seller store.")
            return redirect("accounts:login")

        if not request.user.is_seller:
            messages.info(request, "Onboard as a seller to manage products.")
            return redirect("accounts:seller_onboard")

        store = get_object_or_404(SellerProfile, user=request.user)
        if not store.is_approved:
            messages.warning(
                request,
                f"Your seller application is {store.get_status_display().lower()}. "
                "You can keep browsing the marketplace meanwhile.",
            )
            return redirect("accounts:seller_status")

        request.seller = store
        return view_func(request, *args, **kwargs)

    return _wrapped
