from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("register/", views.register, name="register"),
    path("login/", views.MarketplaceLoginView.as_view(), name="login"),
    path("logout/", views.MarketplaceLogoutView.as_view(), name="logout"),
    path("password-reset/", views.MarketplacePasswordResetView.as_view(), name="password_reset"),
    path("password-reset/done/", views.MarketplacePasswordResetDoneView.as_view(), name="password_reset_done"),
    path("reset/<uidb64>/<token>/", views.MarketplacePasswordResetConfirmView.as_view(), name="password_reset_confirm"),
    path("reset/done/", views.MarketplacePasswordResetCompleteView.as_view(), name="password_reset_complete"),
    path("profile/", views.profile, name="profile"),
    path("orders/", views.order_history, name="order_history"),
    path("sell/", views.seller_onboard, name="seller_onboard"),
    path("sell/status/", views.seller_status, name="seller_status"),
    path("sell/settings/", views.seller_settings, name="seller_settings"),
    path("sell/subscription/payment/<int:subscription_id>/", views.subscription_payment, name="subscription_payment"),
]
