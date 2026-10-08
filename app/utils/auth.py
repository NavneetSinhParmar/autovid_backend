import bcrypt
from jose import jwt, JWTError
from passlib.context import CryptContext
from datetime import datetime, timedelta
from fastapi import HTTPException, Depends, status
from fastapi.security import OAuth2PasswordBearer
from app.db.connection import db
from bson import ObjectId
import os
from fastapi import HTTPException
from app.utils.constants import ALLOWED_ROLES


SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM") or "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES") or 60)

if not SECRET_KEY or len(SECRET_KEY.encode("utf-8")) < 32 or SECRET_KEY == "replace_this_with_a_strong_secret":
    raise RuntimeError(
        "SECRET_KEY must be a unique secret of at least 32 bytes; "
        f"the effective value has {len((SECRET_KEY or '').encode('utf-8'))} bytes. "
        "Set a randomly generated key in the project .env.local and restart Uvicorn. "
        "An existing process SECRET_KEY overrides .env.local; remove a stale shell "
        "value if needed. Production must use a deployment secret manager."
    )

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")
optional_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)

def validate_role(role: str):
    """Ensure only allowed roles are used."""
    if role not in ALLOWED_ROLES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid role '{role}'. Allowed roles are: {', '.join(ALLOWED_ROLES)}"
        )
    
def hash_password(password: str) -> str:
    if not password:
        raise ValueError("Password cannot be empty")

    # bcrypt only supports passwords <= 72 bytes
    if len(password.encode('utf-8')) > 72:
        password = password[:72]

    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def verify_password(plain_password: str, hashed_password: str):
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def require_roles(*roles):
    async def wrapper(user=Depends(get_current_user)):
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if user.get("role") not in roles:
            raise HTTPException(status_code=403, detail="Access denied")
        return user
    return wrapper

token_blacklist = set()

def blacklist_token(token: str):
    token_blacklist.add(token)

def is_token_blacklisted(token: str):
    return token in token_blacklist

async def get_current_user(token: str = Depends(oauth2_scheme)):
    if is_token_blacklisted(token):
        raise HTTPException(status_code=401, detail="Token has been revoked. Please log in again.")

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )
    user = None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if user_id is None:
            raise credentials_exception
        user = await db.users.find_one({"_id": ObjectId(user_id)})
    except (JWTError, ValueError):
        raise credentials_exception

    if user is None:
        raise credentials_exception
    return user


async def get_optional_current_user(token: str | None = Depends(optional_oauth2_scheme)):
    if not token:
        return None
    return await get_current_user(token)
