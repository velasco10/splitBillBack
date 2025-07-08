# utils_gemini.py
import google.generativeai as genai
from fastapi import UploadFile, HTTPException
from PIL import Image
import io
import os
import re, json

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

genai.configure(api_key=GEMINI_API_KEY)

def extraer_ticket_con_gemini(image_bytes: bytes) -> dict:
    model = genai.GenerativeModel("gemini-1.5-flash")
    prompt = """
    Eres un extractor de tickets. Devuelve los datos en este formato JSON:
    {
        "comercio": "",
        "fecha": "",
        "lineas": [
            {"producto": "", "cantidad": 0, "importe": 0}
        ],
        "total": 0
    }
    """
    try:
        img = Image.open(io.BytesIO(image_bytes))
        response = model.generate_content([prompt, img])
        # Extrae el texto entre las primeras llaves {} encontradas (suele funcionar bien)
        
        json_match = re.search(r'\{[\s\S]+\}', response.text)
        if not json_match:
            raise ValueError("No se encontró un JSON en la respuesta.")
        return json.loads(json_match.group())
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error al procesar ticket: {e}")
