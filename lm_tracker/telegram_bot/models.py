from django.db import models
from django.utils import timezone
from model_utils.models import TimeStampedModel


class TelegramUser(TimeStampedModel):
    telegram_user_id = models.BigIntegerField(unique=True)
    username = models.CharField(max_length=64, blank=True, default="")
    name = models.CharField(max_length=128, blank=True, default="")

    def __str__(self):
        return f"{self.telegram_user_id} @{self.username}"


class Subscription(TimeStampedModel):
    PLAN_FREE = "FREE"
    PLAN_PRO = "PRO"
    PLAN_CHOICES = [(PLAN_FREE, "Free"), (PLAN_PRO, "Pro")]

    STATUS_ACTIVE = "active"
    STATUS_CANCELED = "canceled"
    STATUS_EXPIRED = "expired"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "active"),
        (STATUS_CANCELED, "canceled"),
        (STATUS_EXPIRED, "expired"),
    ]

    telegram_user = models.OneToOneField(
        TelegramUser,
        on_delete=models.CASCADE,
        related_name="subscription",
    )
    plan = models.CharField(max_length=10, choices=PLAN_CHOICES, default=PLAN_FREE)
    status = models.CharField(
        max_length=12,
        choices=STATUS_CHOICES,
        default=STATUS_ACTIVE,
    )
    current_period_end = models.DateTimeField(null=True, blank=True)

    def is_pro_active(self) -> bool:
        if self.plan != self.PLAN_PRO or self.status != self.STATUS_ACTIVE:
            return False
        if not self.current_period_end:
            return False
        return timezone.now() < self.current_period_end


class ActivationToken(TimeStampedModel):
    token = models.CharField(max_length=64, unique=True)
    plan = models.CharField(max_length=10, default=Subscription.PLAN_PRO)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)

    def is_valid(self) -> bool:
        return (self.used_at is None) and (timezone.now() < self.expires_at)


class Transaction(TimeStampedModel):
    ASSET_GOLD = "GOLD"
    ASSET_SILVER = "SILVER"
    ASSET_CHOICES = [(ASSET_GOLD, "Emas"), (ASSET_SILVER, "Perak")]

    SIDE_BUY = "BUY"
    SIDE_SELL = "SELL"
    SIDE_BUYBACK = "BUYBACK"
    SIDE_FEE = "FEE"
    SIDE_CHOICES = [
        (SIDE_BUY, "Buy"),
        (SIDE_SELL, "Sell"),
        (SIDE_BUYBACK, "Buyback"),
        (SIDE_FEE, "Fee"),
    ]

    telegram_user = models.ForeignKey(
        TelegramUser,
        on_delete=models.CASCADE,
        related_name="transactions",
    )
    asset = models.CharField(max_length=10, choices=ASSET_CHOICES, default=ASSET_GOLD)
    product = models.CharField(
        max_length=64,
        blank=True,
        default="",
    )  # ANTAM/UBS/etc optional
    side = models.CharField(max_length=10, choices=SIDE_CHOICES)

    weight_gram = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        null=True,
        blank=True,
    )
    pcs = models.PositiveIntegerField(default=1)
    total_amount = models.BigIntegerField()  # IDR
    tx_date = models.DateField(default=timezone.now)
    note = models.CharField(max_length=255, blank=True, default="")

    chat_id = models.BigIntegerField(null=True, blank=True)
    message_id = models.BigIntegerField(null=True, blank=True)

    @property
    def total_weight(self):
        if self.weight_gram is None:
            return None
        return self.weight_gram * self.pcs
