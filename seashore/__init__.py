# This makes Celery's app instance available as 'default_app' when Django starts,
# so that @shared_task decorators use the correct app.
from .celery import app as celery_app

__all__ = ('celery_app',)
