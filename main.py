from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.common.exceptions import WebDriverException
import time
import re
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, validator
import os
from motor.motor_asyncio import AsyncIOMotorClient
from fastapi import Depends
from fastapi.security import OAuth2PasswordRequestForm
from passlib.context import CryptContext
from dotenv import load_dotenv
from bson import ObjectId

# Cargar variables de entorno
load_dotenv()

# Configuración de MongoDB
MONGODB_URI = os.getenv("MONGODB_URI")
client = AsyncIOMotorClient(MONGODB_URI)
db = client["myzend"]

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Definir la aplicación FastAPI con metadata
app = FastAPI(
    title="YouTube Shorts API",
    description="API para obtener URLs de shorts de YouTube",
    version="1.0.0"
)

# Configurar CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Permitir cualquier origen para desarrollo
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class YTShortsRequest(BaseModel):
    channel_handle: str
    limit: int = 30  # Valor por defecto de 30 videos

    @validator('channel_handle')
    def validate_channel_handle(cls, v):
        # Si es una URL completa, extraer solo el identificador del canal
        if v.startswith('http'):
            v = v.split('/shorts')[0]
            if '/@' in v:
                v = '@' + v.split('/@')[1]
            elif '/c/' in v:
                v = v.split('/c/')[1]
        elif not v.startswith('@'):
            v = '@' + v
        return v

    @validator('limit')
    def validate_limit(cls, v):
        if v < 1:
            raise ValueError("El límite debe ser mayor a 0")
        if v > 50:
            raise ValueError("El límite no puede ser mayor a 50")
        return v

def get_shorts_urls_selenium(channel_handle: str, limit: int = 20) -> list:
    # Construir URL basada en el tipo de identificador
    if channel_handle.startswith('@'):
        url = f"https://www.youtube.com/{channel_handle}/shorts"
    else:
        url = f"https://www.youtube.com/c/{channel_handle}/shorts"

    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    
    try:
        service = Service(executable_path="C:/chromedriver/chromedriver.exe")
        driver = webdriver.Chrome(service=service, options=chrome_options)
        driver.get(url)
        time.sleep(5)  # Aumentamos el tiempo de espera para carga de JS
        
        shorts = set()
        # Usamos By.XPATH para mejor claridad
        links = driver.find_elements(By.XPATH, "//a[contains(@href, '/shorts/')]")
        
        for a in links:
            if len(shorts) >= limit:  # Detener cuando alcancemos el límite
                break
            href = a.get_attribute("href")
            if href and "/shorts/" in href:
                shorts.add(href)
                
        return list(shorts)[:limit]  # Asegurarnos de no exceder el límite
    
    except WebDriverException as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error con ChromeDriver: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error inesperado: {str(e)}"
        )
    finally:
        if 'driver' in locals():
            driver.quit()

@app.post("/youtube/shorts", 
          response_model=dict,
          summary="Obtener URLs de shorts de YouTube",
          description="Obtiene las URLs de shorts de un canal de YouTube (máximo 20 por defecto)")
def youtube_shorts(req: YTShortsRequest):
    try:
        shorts = get_shorts_urls_selenium(req.channel_handle, req.limit)
        if not shorts:
            raise HTTPException(
                status_code=404,
                detail="No se encontraron shorts o el canal es privado/inexistente."
            )
        return {"shorts_urls": shorts}
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class UserRegister(BaseModel):
    email: str
    password: str
    name: str

class UserLogin(BaseModel):
    email: str
    password: str

@app.post("/register", summary="Registrar nuevo usuario")
async def register_user(user: UserRegister):
    existing = await db.users.find_one({"email": user.email})
    if existing:
        raise HTTPException(status_code=400, detail="El usuario ya existe")
    hashed_password = pwd_context.hash(user.password)
    user_dict = user.dict()
    user_dict["password"] = hashed_password
    await db.users.insert_one(user_dict)
    return {"msg": "Usuario registrado correctamente"}

@app.post("/login", summary="Login de usuario")
async def login_user(user: UserLogin):
    db_user = await db.users.find_one({"email": user.email})
    if not db_user or not pwd_context.verify(user.password, db_user["password"]):
        raise HTTPException(status_code=401, detail="Credenciales incorrectas")
    return {"msg": "Login exitoso", "user": {"email": db_user["email"], "name": db_user.get("name", "")}}

class UserInteraction(BaseModel):
    email: str
    video_id: str
    video_url: str = None
    video_title: str = None
    video_thumbnail: str = None
    interaction_type: str  # like, save, report, etc.
    emotion: str = None
    timestamp: float = None

@app.post("/interaction", summary="Guardar interacción de usuario")
async def save_interaction(interaction: UserInteraction):
    await db.interactions.insert_one(interaction.dict())
    return {"msg": "Interacción guardada"}

@app.get("/user/{email}/interactions", summary="Obtener interacciones de usuario")
async def get_user_interactions(email: str):
    interactions = await db.interactions.find({"email": email}).to_list(1000)
    # Solucionar problema de ObjectId no serializable
    for i in interactions:
        if '_id' in i and isinstance(i['_id'], ObjectId):
            i['_id'] = str(i['_id'])
    return {"interactions": interactions}

class EmotionHistory(BaseModel):
    email: str
    emotion: str
    timestamp: float

@app.post("/emotion", summary="Registrar emoción seleccionada por el usuario")
async def save_emotion(emotion_data: EmotionHistory):
    await db.emotions.insert_one(emotion_data.dict())
    return {"msg": "Emoción registrada"}

@app.get("/user/{email}/emotions", summary="Obtener historial de emociones del usuario")
async def get_user_emotions(email: str):
    emotions = await db.emotions.find({"email": email}).sort("timestamp", -1).to_list(1000)
    for e in emotions:
        if '_id' in e and isinstance(e['_id'], ObjectId):
            e['_id'] = str(e['_id'])
    return {"emotions": emotions}

# Verificar conexión a MongoDB al iniciar el backend
import asyncio

async def check_mongo_connection():
    try:
        await client.admin.command('ping')
        print("\033[92mConexión exitosa con MongoDB\033[0m")
    except Exception as e:
        print(f"\033[91mError al conectar con MongoDB: {e}\033[0m")

@app.on_event("startup")
def startup_event():
    loop = asyncio.get_event_loop()
    loop.create_task(check_mongo_connection())