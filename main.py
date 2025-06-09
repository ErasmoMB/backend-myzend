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

# Definir la aplicación FastAPI con metadata
app = FastAPI(
    title="YouTube Shorts API",
    description="API para obtener URLs de shorts de YouTube",
    version="1.0.0"
)

# Configurar CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class YTShortsRequest(BaseModel):
    channel_handle: str
    limit: int = 30  # Valor por defecto de 20 videos

    @validator('channel_handle')
    def validate_channel_handle(cls, v):
        # Si es una URL completa, extraer solo el identificador del canal
        if v.startswith('http'):
            # Remover /shorts del final si existe
            v = v.split('/shorts')[0]
            # Extraer el handle o ID del canal
            if '/@' in v:
                v = '@' + v.split('/@')[1]
            elif '/c/' in v:
                v = v.split('/c/')[1]
        # Si solo es el handle sin @, agregarlo
        elif not v.startswith('@'):
            v = '@' + v
        return v

    @validator('limit')
    def validate_limit(cls, v):
        if v < 1:
            raise ValueError("El límite debe ser mayor a 0")
        if v > 50:  # Opcional: establecer un máximo
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