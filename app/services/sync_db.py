import os

from pymongo import MongoClient


MONGO_URL = os.getenv("MONGO_URL")
DB_NAME = os.getenv("DATABASE_NAME")

if not MONGO_URL or not DB_NAME:
    raise RuntimeError("Set MONGO_URL and DATABASE_NAME in the project .env.local file or environment")

sync_client = MongoClient(MONGO_URL)
sync_db = sync_client[DB_NAME]
