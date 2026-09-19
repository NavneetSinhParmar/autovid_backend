import os

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

MONGO_URL = os.getenv("MONGO_URL")
DB_NAME = os.getenv("DATABASE_NAME")

sync_client = MongoClient(MONGO_URL)
sync_db = sync_client[DB_NAME]
