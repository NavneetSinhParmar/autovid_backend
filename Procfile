web: uvicorn app.main:app --host 0.0.0.0 --port $PORT
worker_video: celery -A app.services.celery_app.celery_app worker -Q render_video --concurrency=$VIDEO_WORKER_CONCURRENCY --loglevel=info
worker_image: celery -A app.services.celery_app.celery_app worker -Q render_image --concurrency=$IMAGE_WORKER_CONCURRENCY --loglevel=info
worker_tts: celery -A app.services.celery_app.celery_app worker -Q tts --concurrency=$TTS_WORKER_CONCURRENCY --loglevel=info
worker_campaign: celery -A app.services.celery_app.celery_app worker -Q campaigns,maintenance --concurrency=1 --loglevel=info
beat: celery -A app.services.celery_app.celery_app beat --loglevel=info
