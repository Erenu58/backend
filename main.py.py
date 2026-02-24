from fastapi import FastAPI, APIRouter, HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field, EmailStr
from typing import List, Optional
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv
import os
import uuid
import bcrypt
import jwt
import logging

# --- YAPILANDIRMA ---
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'fal_baki_db')
EMERGENT_LLM_KEY = os.environ.get('EMERGENT_LLM_KEY', '')
JWT_SECRET = os.environ.get('JWT_SECRET', 'gizli-anahtar-buraya')
JWT_ALGORITHM = "HS256"

# --- LOGGING ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- FASTAPI APP ---
# Buradaki başlık /docs sayfasında en üstte görünecek
app = FastAPI(title="Fal Bakı API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- DATABASE ---
client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]
security = HTTPBearer()

# --- MODELLER ---
class UserRegister(BaseModel):
    name: str = Field(..., min_length=2)
    email: EmailStr
    password: str = Field(..., min_length=6)

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class FortuneAnalyze(BaseModel):
    image_base64: str

# --- YARDIMCI FONKSİYONLAR ---
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))

def create_jwt_token(user_id: str):
    expire = datetime.utcnow() + timedelta(days=30)
    to_encode = {"sub": user_id, "exp": expire}
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        token = credentials.credentials
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Geçersiz yetki")
        return user_id
    except:
        raise HTTPException(status_code=401, detail="Oturum geçersiz")

# --- API YOLLARI ---
api_router = APIRouter(prefix="/api")

@api_router.get("/", tags=["Genel"])
async def root():
    return {"status": "ok", "message": "Fal Bakı API Aktif", "author": "Eren"}

@api_router.post("/register", tags=["Auth"])
async def register(user: UserRegister):
    existing = await db.users.find_one({"email": user.email})
    if existing:
        raise HTTPException(status_code=400, detail="Bu email zaten kullanımda")
    user_id = str(uuid.uuid4())
    await db.users.insert_one({
        "id": user_id, "name": user.name, "email": user.email,
        "password_hash": hash_password(user.password), "created_at": datetime.utcnow()
    })
    return {"token": create_jwt_token(user_id), "name": user.name}

@api_router.post("/login", tags=["Auth"])
async def login(credentials: UserLogin):
    user = await db.users.find_one({"email": credentials.email})
    if not user or not verify_password(credentials.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Hatalı giriş")
    return {"token": create_jwt_token(user["id"]), "name": user["name"]}

# --- ROUTER'I EKLE ---
app.include_router(api_router)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()