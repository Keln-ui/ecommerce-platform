from django.urls import path

from . import views

app_name = "catalog"

urlpatterns = [
    path("", views.home, name="home"),
    path("products/", views.product_list, name="product_list"),
    path("category/<slug:slug>/", views.product_list, name="product_list_by_category"),
    path("product/<slug:slug>/", views.product_detail, name="product_detail"),
    path("store/<slug:slug>/", views.seller_detail, name="seller_detail"),
    path("product/<slug:slug>/review/", views.add_review, name="add_review"),
    path("contact/", views.contact, name="contact"),
    path("faq/", views.faq, name="faq"),
]
