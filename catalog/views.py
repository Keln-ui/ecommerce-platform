from datetime import timedelta

from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Avg, Count, F, Q, Sum, Value, CharField
from django.db.models.functions import Coalesce, Concat, Lower, TruncMonth
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.decorators import seller_required
from accounts.models import SellerProfile
from orders.models import Order

from .forms import ProductForm, ProductImageForm, ReviewForm
from .models import Category, Product, ProductImage, Review

SELLABLE_STATUSES = [
    Order.Status.PAID,
    Order.Status.PROCESSING,
    Order.Status.SHIPPED,
    Order.Status.DELIVERED,
]


def page_not_found(request, exception=None):
    return render(request, "errors/404.html", status=404)


def server_error(request):
    return render(request, "errors/500.html", status=500)


def contact(request):
    """Customer service contact page"""
    if request.method == "POST":
        name = request.POST.get("name", "")
        email = request.POST.get("email", "")
        subject = request.POST.get("subject", "")
        message = request.POST.get("message", "")
        
        if name and email and subject and message:
            messages.success(request, "Your message has been sent. We'll get back to you soon!")
            return redirect("catalog:contact")
        else:
            messages.error(request, "Please fill in all fields.")
    
    return render(request, "catalog/contact.html")


def faq(request):
    """FAQ page"""
    return render(request, "catalog/faq.html")


# ------------------------------------------------------------------ storefront


def home(request):
    categories = (
        Category.objects.filter(is_active=True, parent__isnull=True)
        .annotate(product_total=Count("products", filter=Q(products__is_active=True)))
        .order_by("display_order", "name")
    )
    featured = (
        Product.objects.live().filter(is_featured=True).for_display().order_by("-created_at")[:8]
    )
    newest = Product.objects.live().for_display().order_by("-created_at")[:8]
    trending = (
        Product.objects.live()
        .for_display()
        .order_by("-views_count", "-units_sold")[:8]
    )
    deals = (
        Product.objects.live()
        .for_display()
        .filter(compare_at_price__gt=F("price"))
        .order_by("-created_at")[:8]
    )
    top_rated = (
        Product.objects.live()
        .for_display()
        .filter(rating_average__gte=4.0)
        .order_by("-rating_average", "-rating_count")[:8]
    )
    sellers = (
        SellerProfile.objects.filter(
            status=SellerProfile.Status.APPROVED, is_active=True, user__role="SELLER"
        )
        .annotate(
            product_total=Count("products", filter=Q(products__is_active=True)),
            sold_total=Count("products__order_items"),
        )
        .order_by("-rating_average", "-product_total")[:6]
    )
    stats = Product.objects.live().aggregate(total=Count("id"), avg_price=Avg("price"))
    recent_reviews = (
        Review.objects.filter(is_approved=True)
        .select_related("product", "product__seller", "user")
        .order_by("-created_at")[:6]
    )

    return render(
        request,
        "catalog/home.html",
        {
            "categories": categories,
            "featured": featured,
            "newest": newest,
            "trending": trending,
            "deals": deals,
            "top_rated": top_rated,
            "sellers": sellers,
            "recent_reviews": recent_reviews,
            "product_total": stats["total"] or 0,
            "avg_price": stats["avg_price"] or 0,
        },
    )


def _optional_decimal(raw):
    """Parse a non-negative Decimal from the query string, or None."""
    if raw in (None, ""):
        return None
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return value if value >= 0 else None


def product_list(request, slug=None):
    products = Product.objects.live().for_display()
    category = None

    if slug:
        category = get_object_or_404(Category, slug=slug, is_active=True)
        products = products.filter(category=category)

    query = request.GET.get("q", "").strip()
    if query:
        products = products.filter(
            Q(name__icontains=query)
            | Q(description__icontains=query)
            | Q(sku__icontains=query)
            | Q(seller__business_name__icontains=query)
        )

    seller_slug = request.GET.get("seller")
    if seller_slug:
        seller = get_object_or_404(
            SellerProfile, slug=seller_slug, status=SellerProfile.Status.APPROVED
        )
        products = products.filter(seller=seller)

    min_price = _optional_decimal(request.GET.get("min_price"))
    if min_price is not None:
        products = products.filter(price__gte=min_price)

    max_price = _optional_decimal(request.GET.get("max_price"))
    if max_price is not None:
        products = products.filter(price__lte=max_price)

    min_rating = _optional_decimal(request.GET.get("rating"))
    if min_rating is not None:
        products = products.filter(rating_average__gte=min_rating)

    if request.GET.get("in_stock"):
        products = products.filter(stock__gt=0)

    if request.GET.get("on_sale"):
        products = products.filter(compare_at_price__gt=F("price"))

    sort = request.GET.get("sort", "newest")
    sort_map = {
        "newest": "-created_at",
        "price_asc": "price",
        "price_desc": "-price",
        "rating": "-rating_average",
        "popular": "-units_sold",
        "name": Lower("name"),
    }
    products = products.order_by(sort_map.get(sort, "-created_at"))

    paginator = Paginator(products, settings.MARKETPLACE["PRODUCTS_PER_PAGE"])
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "catalog/product_list.html",
        {
            "page_obj": page_obj,
            "products": page_obj,
            "category": category,
            "categories": Category.objects.filter(
                is_active=True, parent__isnull=True
            ).annotate(
                product_total=Count("products", filter=Q(products__is_active=True))
            ),
            "sellers": SellerProfile.objects.filter(
                status=SellerProfile.Status.APPROVED, is_active=True
            ).annotate(
                product_total=Count("products", filter=Q(products__is_active=True))
            ),
            "query": query,
            "sort": sort,
            "seller_slug": seller_slug,
            "price_bounds": (
                products.order_by("price").values_list("price", flat=True).first(),
                products.order_by("-price").values_list("price", flat=True).first(),
            ),
        },
    )


def product_detail(request, slug):
    product = Product.objects.for_display().filter(slug=slug).first()
    if product is None:
        messages.error(request, "That product does not exist.")
        return redirect("catalog:product_list")

    is_owner = request.user.is_authenticated and product.seller.user_id == request.user.pk
    if not (product.is_active and product.seller.is_approved) and not is_owner:
        messages.warning(request, "That product is not available right now.")
        return redirect("catalog:product_list")

    Product.objects.filter(pk=product.pk).update(views_count=F("views_count") + 1)

    related = (
        Product.objects.live()
        .filter(category=product.category)
        .exclude(pk=product.pk)
        .for_display()[:4]
    )
    user_review = None
    if request.user.is_authenticated:
        user_review = product.reviews.filter(user=request.user).first()

    return render(
        request,
        "catalog/product_detail.html",
        {
            "product": product,
            "related": related,
            "review_form": ReviewForm(),
            "user_review": user_review,
        },
    )


def seller_detail(request, slug):
    seller = get_object_or_404(
        SellerProfile.objects.annotate(
            product_total=Count("products", filter=Q(products__is_active=True))
        ),
        slug=slug,
        status=SellerProfile.Status.APPROVED,
        is_active=True,
    )
    products = seller.products.live().for_display()
    paginator = Paginator(products, settings.MARKETPLACE["PRODUCTS_PER_PAGE"])
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "catalog/seller_detail.html",
        {"seller": seller, "page_obj": page_obj, "products": page_obj},
    )


@login_required
@require_POST
def add_review(request, slug):
    product = get_object_or_404(Product, slug=slug)

    if Review.objects.filter(product=product, user=request.user).exists():
        messages.info(request, "You already reviewed this product.")
        return redirect(product.get_absolute_url())

    form = ReviewForm(request.POST)
    if form.is_valid():
        review = form.save(commit=False)
        review.product = product
        review.user = request.user
        review.save()
        product.seller.recalculate_rating()
        messages.success(request, "Thanks for your review!")
    else:
        messages.error(request, "Please correct the highlighted fields.")

    return redirect(product.get_absolute_url())


# ---------------------------------------------------------------- seller area


@seller_required
def seller_dashboard(request):
    store = request.seller
    products = store.products.all()

    sales = store.orders.filter(status__in=SELLABLE_STATUSES)
    revenue = sales.aggregate(v=Sum("subtotal"))["v"] or Decimal("0.00")
    commission = sales.aggregate(v=Sum("commission"))["v"] or Decimal("0.00")

    stats = {
        "product_total": products.count(),
        "active_total": products.filter(is_active=True).count(),
        "out_of_stock": products.filter(stock=0).count(),
        "low_stock": products.filter(stock__gt=0, stock__lte=F("low_stock_threshold")).count(),
        "order_total": store.orders.count(),
        "pending_total": store.orders.filter(status=Order.Status.PAID).count(),
        "revenue": revenue,
        "commission": commission,
        "payout": revenue - commission,
    }

    # Additional metrics
    avg_order_value = Decimal("0.00")
    if stats["order_total"] > 0:
        avg_order_value = revenue / stats["order_total"]

    total_views = products.aggregate(total=Sum("views_count"))["total"] or 0
    conversion_rate = 0
    if total_views > 0:
        conversion_rate = round((stats["order_total"] / total_views) * 100, 2)

    # Recent reviews for seller's products
    recent_reviews = (
        Review.objects.filter(product__seller=store, is_approved=True)
        .select_related("product", "user")
        .order_by("-created_at")[:5]
    )

    # Top customers
    top_customers = list(
        store.orders.values("buyer__email")
        .annotate(
            buyer_name=Coalesce(
                Concat(
                    "buyer__first_name",
                    Value(" "),
                    "buyer__last_name",
                    output_field=CharField(),
                ),
                "buyer__email",
                output_field=CharField(),
            ),
            orders=Count("id"),
            revenue=Coalesce(Sum("total"), Decimal("0.00")),
        )
        .order_by("-revenue")[:5]
    )

    # Monthly sales trend (last 6 months)
    six_months_ago = timezone.now() - timedelta(days=180)
    monthly_sales = (
        store.orders.filter(placed_at__gte=six_months_ago, status__in=SELLABLE_STATUSES)
        .annotate(month=TruncMonth("placed_at"))
        .values("month")
        .annotate(
            revenue=Coalesce(Sum("subtotal"), Decimal("0.00")),
            orders=Count("id"),
        )
        .order_by("month")
    )

    # Inventory health
    inventory_value = products.aggregate(total=Sum(F("price") * F("stock")))["total"] or Decimal("0.00")

    return render(
        request,
        "sellers/dashboard.html",
        {
            "store": store,
            "stats": stats,
            "recent_orders": store.orders.select_related("buyer").prefetch_related("items")[:6],
            "top_products": products.order_by("-units_sold")[:5],
            "recent_reviews": recent_reviews,
            "top_customers": top_customers,
            "avg_order_value": avg_order_value,
            "conversion_rate": conversion_rate,
            "total_views": total_views,
            "monthly_sales": monthly_sales,
            "inventory_value": inventory_value,
        },
    )


@seller_required
def seller_products(request):
    store = request.seller
    all_products = store.products.select_related("category").prefetch_related("images")

    stats = {
        "active_total": all_products.filter(is_active=True).count(),
        "inactive_total": all_products.filter(is_active=False).count(),
        "out_of_stock": all_products.filter(stock=0).count(),
        "low_stock": all_products.filter(stock__gt=0, stock__lte=F("low_stock_threshold")).count(),
    }

    products = all_products

    query = request.GET.get("q", "").strip()
    if query:
        products = products.filter(name__icontains=query)

    status = request.GET.get("status")
    if status == "active":
        products = products.filter(is_active=True)
    elif status == "inactive":
        products = products.filter(is_active=False)
    elif status == "out_of_stock":
        products = products.filter(stock=0)
    elif status == "low_stock":
        products = products.filter(stock__gt=0, stock__lte=F("low_stock_threshold"))

    paginator = Paginator(products.order_by("-created_at"), 15)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "sellers/products.html",
        {
            "store": store,
            "page_obj": page_obj,
            "products": page_obj,
            "stats": stats,
            "query": query,
            "status": status or "",
        },
    )


@seller_required
def product_create(request):
    store = request.seller
    form = ProductForm(request.POST or None)
    image_form = ProductImageForm(request.POST or None, request.FILES or None)

    if request.method == "POST" and form.is_valid():
        product = form.save(commit=False)
        product.seller = store
        product.save()
        _save_uploaded_image(product, image_form)
        messages.success(request, f'"{product.name}" is now listed.')
        return redirect("sellers:products")

    return render(
        request,
        "sellers/product_form.html",
        {
            "form": form,
            "image_form": image_form,
            "product": None,
            "images": ProductImage.objects.none(),
            "title": "New product",
        },
    )


@seller_required
def product_edit(request, pk):
    store = request.seller
    # Scoping by seller means one seller can never open another's product.
    product = get_object_or_404(Product, pk=pk, seller=store)
    form = ProductForm(request.POST or None, instance=product)
    image_form = ProductImageForm(request.POST or None, request.FILES or None)

    if request.method == "POST" and form.is_valid():
        form.save()
        _save_uploaded_image(product, image_form)
        messages.success(request, "Product updated.")
        return redirect("sellers:products")

    return render(
        request,
        "sellers/product_form.html",
        {
            "form": form,
            "image_form": image_form,
            "product": product,
            "images": product.images.all(),
            "title": "Edit product",
        },
    )


def _save_uploaded_image(product, image_form):
    if not image_form.is_valid():
        return
    image = image_form.cleaned_data.get("image")
    if not image:
        return
    make_primary = (
        image_form.cleaned_data.get("is_primary") or not product.images.exists()
    )
    if make_primary:
        product.images.update(is_primary=False)
    ProductImage.objects.create(
        product=product,
        image=image,
        alt_text=image_form.cleaned_data.get("alt_text") or product.name,
        is_primary=make_primary,
    )


@seller_required
def product_delete(request, pk):
    product = get_object_or_404(Product, pk=pk, seller=request.seller)
    name = product.name
    product.delete()
    messages.success(request, f'"{name}" was removed from your catalog.')
    return redirect("sellers:products")


@seller_required
def product_image_delete(request, pk):
    image = get_object_or_404(ProductImage, pk=pk, product__seller=request.seller)
    product_id = image.product_id
    was_primary = image.is_primary
    image.delete()

    if was_primary:
        remaining = ProductImage.objects.filter(product_id=product_id).first()
        if remaining:
            remaining.is_primary = True
            remaining.save(update_fields=["is_primary"])

    messages.success(request, "Image removed.")
    return redirect("sellers:product_edit", pk=product_id)


@seller_required
@require_POST
def product_toggle_active(request, pk):
    product = get_object_or_404(Product, pk=pk, seller=request.seller)
    product.is_active = not product.is_active
    product.save(update_fields=["is_active"])
    state = "listed" if product.is_active else "hidden from shoppers"
    messages.success(request, f'"{product.name}" is now {state}.')
    return redirect(request.POST.get("next") or "sellers:products")


@seller_required
def seller_orders(request):
    store = request.seller
    orders = store.orders.select_related("buyer").prefetch_related("items")

    status = request.GET.get("status")
    if status:
        orders = orders.filter(status=status)

    paginator = Paginator(orders, 15)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "sellers/orders.html",
        {
            "store": store,
            "page_obj": page_obj,
            "orders": page_obj,
            "status": status or "",
            "status_choices": Order.Status.choices,
        },
    )
