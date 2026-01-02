from django.db import models
from django.utils import timezone
from model_utils.models import TimeStampedModel


class PriceSnapshot(TimeStampedModel):
    ts = models.DateTimeField(default=timezone.now, db_index=True)

    # Spot dunia
    xauusd = models.FloatField()
    usdidr = models.FloatField()
    spot_idr_gr = models.FloatField()

    # Lokal (Logam Mulia)
    antam_1g_base = models.BigIntegerField()
    antam_1g_pph = models.BigIntegerField()
    buyback = models.BigIntegerField()
    buyback_ts = models.CharField(max_length=128, blank=True)

    spot_source = models.CharField(max_length=64)
    local_source = models.CharField(max_length=64, default="Logam Mulia")

    class Meta:
        ordering = ["-ts"]


class BroadcastLog(TimeStampedModel):
    KIND_UPDATE = "UPDATE"
    KIND_ALERT = "ALERT"
    KIND_CHOICES = [(KIND_UPDATE, "Update"), (KIND_ALERT, "Alert")]

    kind = models.CharField(max_length=16, choices=KIND_CHOICES)
    sent_at = models.DateTimeField(default=timezone.now, db_index=True)

    # anti-dobel update slot (mis: "2026-01-01@09:00")
    slot_key = models.CharField(max_length=255, blank=True, default="", db_index=True)

    # optional: simpan ringkas message / hash untuk debugging
    message = models.TextField(blank=True, default="")
