from django.urls import path

from .billing_views import checkout  # (lihat step 8)
from .billing_views import success  # (lihat step 8)
from .views import telegram_webhook

app_name = "telegram_bot"

urlpatterns = [
    path(
        "telegram/webhook/<str:secret_path>/",
        telegram_webhook,
        name="telegram_webhook",
    ),
    path("billing/checkout/", checkout, name="checkout"),
    path("billing/success/", success, name="success"),
]
