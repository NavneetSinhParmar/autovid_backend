# autovid_backend

Basic step Of run this app

# Create Virtual Environment (Optional)

python -m venv venv
source venv/bin/activate # macOS/Linux
source venv/Scripts/activate # Windows

# Install nacessary Libraries

pip install -r requirements.txt

uvicorn main:app --reload
uvicorn app.main:app --reload

# change Mango URI: (Paste Your Mongo server URI)

MONGO_URI = "mongodb+srv://<username>:<password>@<cluster>/<db_name>?retryWrites=true&w=majority"

pip install python-multipart
ffmpeg -v debug -i C:\Users\viren\Downloads\videodata\datadummy\sample-5s.mp4 output.mp4.

now docker setup

## Production render queue

Run the API, Redis, and a Celery render worker as separate processes.

Required environment:

```
REDIS_URL=redis://localhost:6379/0
MONGO_URL=<mongodb-uri>
DATABASE_NAME=<database-name>
BASE_URL=https://<api-host>
FFMPEG_WORKER_CONCURRENCY=2
FFMPEG_THREADS=1
```

Commands:

```
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
celery -A app.services.celery_app.celery_app worker -Q render --loglevel=info
```

`FFMPEG_WORKER_CONCURRENCY` controls how many renders can run at once per worker process. Extra jobs remain in Redis as `QUEUED` until a worker slot is free. `FFMPEG_THREADS` limits each FFmpeg subprocess so concurrent jobs do not consume the whole machine.
