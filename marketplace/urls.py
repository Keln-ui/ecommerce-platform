from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from catalog import views as catalog_views

admin.site.site_header = f"{settings.SITE_NAME} administration"
admin.site.site_title = f"{settings.SITE_NAME} admin"
admin.site.index_title = "Operations"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("backoffice/", include("backoffice.urls")),
    path("accounts/", include("allauth.urls")),
    path("", include("catalog.urls")),
    path("", include("accounts.urls")),
    path("", include("orders.urls")),
    path(
        "seller/",
        include(
            (
                [
                    path("", catalog_views.seller_dashboard, name="dashboard"),
                    path("products/", catalog_views.seller_products, name="products"),
                    path(
                        "products/new/",
                        catalog_views.product_create,
                        name="product_create",
                    ),
                    path(
                        "products/<int:pk>/edit/",
                        catalog_views.product_edit,
                        name="product_edit",
                    ),
                    path(
                        "products/<int:pk>/delete/",
                        catalog_views.product_delete,
                        name="product_delete",
                    ),
                    path(
                        "products/<int:pk>/toggle/",
                        catalog_views.product_toggle_active,
                        name="product_toggle",
                    ),
                    path(
                        "products/images/<int:pk>/delete/",
                        catalog_views.product_image_delete,
                        name="product_image_delete",
                    ),
                    path("orders/", catalog_views.seller_orders, name="orders"),
                ],
                "sellers",
            ),
            namespace="sellers",
        ),
    ),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

handler404 = "catalog.views.page_not_found"
handler500 = "catalog.views.server_error"
