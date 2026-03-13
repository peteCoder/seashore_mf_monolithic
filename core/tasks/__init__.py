# Import submodules so Celery's autodiscover_tasks() registers all @shared_task functions
from . import loan_tasks, savings_tasks, report_tasks, sms_tasks  # noqa: F401
