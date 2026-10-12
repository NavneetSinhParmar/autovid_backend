web: uvicorn app.main:app --host 0.0.0.0 --port $PORT
worker_video: python scripts/run_worker.py render_video
worker_image: python scripts/run_worker.py render_image
worker_tts: python scripts/run_worker.py tts
worker_campaign: python scripts/run_worker.py campaigns,maintenance
beat: python scripts/run_worker.py beat
