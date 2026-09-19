web: uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1
worker: celery -A app.services.celery_app.celery_app worker -Q render --loglevel=info
