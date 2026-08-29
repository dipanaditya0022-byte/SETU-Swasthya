from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import jwt
from pydantic import BaseModel

router = APIRouter(tags=["Auth"])

SECRET_KEY = "setu-swasthya-day1-secret"
ALGORITHM = "HS256"

USERS = {
    "aditya": {"password": "aditya123", "role": "admin"},
    "iqra": {"password": "iqra123", "role": "health_worker"},
}


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/login")
def login(data: LoginRequest):
    user = USERS.get(data.username)

    if not user or user["password"] != data.password:
        raise HTTPException(status_code=401, detail="Invalid username or password")

    payload = {
        "sub": data.username,
        "role": user["role"],
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }

    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

    return {
        "access_token": token,
        "token_type": "bearer",
        "role": user["role"],
    }


security = HTTPBearer()


@router.get("/me")
def me(
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    token = credentials.credentials

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return {
        "username": payload.get("sub"),
        "role": payload.get("role"),
    }
