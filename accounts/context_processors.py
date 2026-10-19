from django.conf import settings


def marketplace(request):
    """Expose site config and a live cart badge to every template."""
    context = {
        "SITE_NAME": settings.SITE_NAME,
        "MARKETPLACE": settings.MARKETPLACE,
    }
    cart = getattr(request.user, "cart", None) if request.user.is_authenticated else None
    context["cart_count"] = cart.item_count if cart else 0
    return context
