from django.contrib import admin

from .models import BroadcastLog
from .models import PriceSnapshot


@admin.register(PriceSnapshot)
class PriceSnapshotAdmin(admin.ModelAdmin):
    list_display = (
        "ts",
        "xauusd",
        "usdidr",
        "spot_idr_gr",
        "antam_1g_base",
        "buyback",
        "spot_source",
    )
    list_filter = ("spot_source",)
    ordering = ("-ts",)


@admin.register(BroadcastLog)
class BroadcastLogAdmin(admin.ModelAdmin):
    list_display = ("kind", "sent_at", "slot_key")
    ordering = ("-sent_at",)
