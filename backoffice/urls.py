from django.urls import path

from . import views

app_name = "backoffice"

urlpatterns = [
    path("", views.overview, name="overview"),
    path("sellers/", views.sellers, name="sellers"),
    path("sellers/<int:pk>/", views.seller_detail, name="seller_detail"),
    path("sellers/<int:pk>/status/", views.seller_status_change, name="seller_status"),
    path("sellers/action/", views.sellers_bulk_action, name="sellers_bulk"),
    path("orders/", views.orders, name="orders"),
    path("orders/<str:order_number>/status/", views.order_status_change, name="order_status"),
    path("products/", views.products, name="products"),
    path("products/<int:pk>/toggle/", views.product_toggle, name="product_toggle"),
    path("customers/", views.customers, name="customers"),
    path("reports/", views.reports, name="reports"),
    path("reviews/", views.reviews, name="reviews"),
    path("reviews/action/", views.reviews_bulk_action, name="reviews_bulk"),
    path("export/", views.export_dashboard_csv, name="export_dashboard_csv"),
]
