from fastapi import FastAPI, APIRouter, HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field, EmailStr
from typing import List, Optional
import uuid
from datetime import datetime, timedelta
import bcrypt
import jwt
from emergentintegrations.llm.chat import LlmChat, UserMessage, ImageContent

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ.get('DB_NAME', 'fal_baki_db')]

# Environment variables
EMERGENT_LLM_KEY = os.environ.get('EMERGENT_LLM_KEY', '')
JWT_SECRET = os.environ.get('JWT_SECRET', 'default-secret-key')
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_DAYS = 30

# Create the main app
app = FastAPI(title="Fal Bakı API")

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")

# Security
security = HTTPBearer()

# Models
class UserRegister(BaseModel):
    name: str
    email: EmailStr
    password: str

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class UserResponse(BaseModel):
    id: str
    name: str
    email: str
    created_at: datetime

class FortuneAnalyze(BaseModel):
    image_base64: str

class FortuneResponse(BaseModel):
    id: str
    user_id: str
    image_base64: str
    fortune_text: str
    created_at: datetime

# Helper functions
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))

def create_jwt_token(user_id: str, email: str) -> str:
    expiration = datetime.utcnow() + timedelta(days=JWT_EXPIRATION_DAYS)
    payload = {
        "user_id": user_id,
        "email": email,
        "exp": expiration
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        token = credentials.credentials
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = payload.get("user_id")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Geçersiz token")
        return user_id
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token süresi dolmuş")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Geçersiz token")

# AI Fortune Reading
async def analyze_coffee_fortune(image_base64: str) -> str:
    """OpenAI Vision ile kahve falı analizi"""
    try:
        # Create a new chat instance
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"fortune_{uuid.uuid4()}",
            system_message="Sen bir uzman kahve falı bakıcısısın. Türk kahvesi fallarını detaylı ve mistik bir dille yorumlarsın."
        )
        
        # Use OpenAI GPT-5.2 with vision
        chat.with_model("openai", "gpt-5.2")
        
        # Create image content
        image_content = ImageContent(image_base64=image_base64)
        
        # Create message with image
        user_message = UserMessage(
            text="""Bu kahve falını detaylı bir şekilde yorumla. Şunları içersin:
            
1. Genel Değerlendirme: Fincanda gördüklerinin genel anlamı
2. Aşk ve İlişkiler: Kalp işleri, duygusal durum
3. Kariyer ve Para: İş hayatı, maddi durum
4. Sağlık: Genel sağlık durumu
5. Gelecek: Önümüzdeki günlerde olabilecekler

Pozitif, ümit verici ve mistik bir üslup kullan. Türkçe yaz ve her bölümü emoji ile başlat.""",
            file_contents=[image_content]
        )
        
        # Get AI response
        response = await chat.send_message(user_message)
        return response
        
    except Exception as e:
        logging.error(f"Fortune analysis error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Fal analizi sırasında hata oluştu: {str(e)}")

# Routes
@api_router.get("/")
async def root():
    return {"message": "Fal Bakı API - Hoş Geldiniz"}

@api_router.post("/register")
async def register(user: UserRegister):
    # Check if user exists
    existing_user = await db.users.find_one({"email": user.email})
    if existing_user:
        raise HTTPException(status_code=400, detail="Bu email zaten kayıtlı")
    
    # Create user
    user_id = str(uuid.uuid4())
    user_dict = {
        "id": user_id,
        "name": user.name,
        "email": user.email,
        "password_hash": hash_password(user.password),
        "created_at": datetime.utcnow()
    }
    
    await db.users.insert_one(user_dict)
    
    # Create JWT token
    token = create_jwt_token(user_id, user.email)
    
    return {
        "token": token,
        "user": {
            "id": user_id,
            "name": user.name,
            "email": user.email
        }
    }

@api_router.post("/login")
async def login(credentials: UserLogin):
    # Find user
    user = await db.users.find_one({"email": credentials.email})
    if not user:
        raise HTTPException(status_code=401, detail="Email veya şifre hatalı")
    
    # Verify password
    if not verify_password(credentials.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Email veya şifre hatalı")
    
    # Create JWT token
    token = create_jwt_token(user["id"], user["email"])
    
    return {
        "token": token,
        "user": {
            "id": user["id"],
            "name": user["name"],
            "email": user["email"]
        }
    }

@api_router.post("/fortune/analyze")
async def analyze_fortune(
    fortune_data: FortuneAnalyze,
    user_id: str = Depends(get_current_user)
):
    """Kahve falı fotoğrafını analiz et"""
    
    # Analyze with AI
    fortune_text = await analyze_coffee_fortune(fortune_data.image_base64)
    
    # Save to database
    fortune_id = str(uuid.uuid4())
    fortune_dict = {
        "id": fortune_id,
        "user_id": user_id,
        "image_base64": fortune_data.image_base64,
        "fortune_text": fortune_text,
        "created_at": datetime.utcnow()
    }
    
    await db.fortunes.insert_one(fortune_dict)
    
    return {
        "id": fortune_id,
        "fortune_text": fortune_text,
        "created_at": fortune_dict["created_at"]
    }

@api_router.get("/fortune/history")
async def get_fortune_history(
    user_id: str = Depends(get_current_user)
):
    """Kullanıcının geçmiş fallarını getir"""
    fortunes = await db.fortunes.find({"user_id": user_id}).sort("created_at", -1).to_list(100)
    
    return [
        {
            "id": f["id"],
            "image_base64": f["image_base64"],
            "fortune_text": f["fortune_text"],
            "created_at": f["created_at"]
        }
        for f in fortunes
    ]

@api_router.get("/fortune/{fortune_id}")
async def get_fortune_detail(
    fortune_id: str,
    user_id: str = Depends(get_current_user)
):
    """Tek bir fal detayını getir"""
    fortune = await db.fortunes.find_one({"id": fortune_id, "user_id": user_id})
    
    if not fortune:
        raise HTTPException(status_code=404, detail="Fal bulunamadı")
    
    return {
        "id": fortune["id"],
        "image_base64": fortune["image_base64"],
        "fortune_text": fortune["fortune_text"],
        "created_at": fortune["created_at"]
    }

@api_router.get("/user/me")
async def get_current_user_info(user_id: str = Depends(get_current_user)):
    """Mevcut kullanıcı bilgilerini getir"""
    user = await db.users.find_one({"id": user_id})
    
    if not user:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")
    
    return {
        "id": user["id"],
        "name": user["name"],
        "email": user["email"],
        "created_at": user["created_at"]
    }

# Include the router in the main app
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
