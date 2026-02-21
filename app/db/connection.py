from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
import os

load_dotenv()  # load .env file

MONGO_URL = os.getenv("MONGO_URL")
DB_NAME = os.getenv("DATABASE_NAME")

print(f"Connecting to MongoDB at: {MONGO_URL}, Database: {DB_NAME}")
client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]
