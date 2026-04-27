from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
import os
import sys
import ssl

load_dotenv()  # load .env file

# Use certifi's CA bundle for TLS verification with Atlas
try:
	import certifi
	ca_bundle = certifi.where()
except Exception:
	ca_bundle = None

MONGO_URL = os.getenv("MONGO_URL")
DB_NAME = os.getenv("DATABASE_NAME")

print(f"Connecting to MongoDB at: {MONGO_URL}, Database: {DB_NAME}")
# client = AsyncIOMotorClient(MONGO_URL)

# production code
print("Python:", sys.version.split()[0], "OpenSSL:", ssl.OPENSSL_VERSION)
if ca_bundle:
	print("Using certifi CA bundle:", ca_bundle)
else:
	print("certifi not available; connection will use system CA bundle")


client_kwargs = {
	"serverSelectionTimeoutMS": 20000,
	"socketTimeoutMS": 20000,
}
if ca_bundle:
	client_kwargs.update({"tls": True, "tlsCAFile": ca_bundle})

client = AsyncIOMotorClient(MONGO_URL, **client_kwargs)
db = client[DB_NAME]
