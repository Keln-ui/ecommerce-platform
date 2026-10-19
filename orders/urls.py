from django.urls import path

from . import views

app_name = "orders"

urlpatterns = [
    path("cart/", views.cart_view, name="cart"),
    path("cart/add/", views.cart_add, name="cart_add"),
    path("cart/update/", views.cart_update, name="cart_update"),
    path("cart/remove/<int:item_id>/", views.cart_remove, name="cart_remove"),
    path("checkout/", views.checkout, name="checkout"),
    path("", views.order_list, name="order_list"),
    path("detail/<str:order_number>/", views.order_detail, name="order_detail"),
    path("cancel/<str:order_number>/", views.order_cancel, name="order_cancel"),
    path(
        "seller/detail/<str:order_number>/",
        views.seller_order_update,
        name="seller_order_update",
    ),
]
