from celery import shared_task

from lm_tracker.bot_alert.services.broadcast import run_broadcast


@shared_task
def bot_broadcast_task():
    run_broadcast()
