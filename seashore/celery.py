"""
Celery Application
==================
Entry point for the Celery worker and Celery Beat scheduler.

Start worker (Windows):
    celery -A seashore worker -l info --pool=solo

Start beat scheduler:
    celery -A seashore beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
"""

import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'seashore.settings')

app = Celery('seashore')

# Read Celery config from Django settings, using the CELERY_ namespace
app.config_from_object('django.conf:settings', namespace='CELERY')

# Auto-discover tasks in all INSTALLED_APPS
app.autodiscover_tasks()


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    print(f'Request: {self.request!r}')
