# Celery
BROKER_URL = 'amqp://guest@127.0.0.1//'
CELERY_RESULT_BACKEND = 'rpc://'

# Move to JSON when exceptions are properly handled
CELERY_TASK_SERIALIZER = 'pickle'
CELERY_ACCEPT_CONTENT = ['pickle']
CELERY_RESULT_SERIALIZER = 'pickle'

CELERY_IMPORTS = [
    'unichan.lib.tasks.post_task'
]