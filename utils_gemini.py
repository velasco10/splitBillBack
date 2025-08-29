# utils_gemini.py
import google.generativeai as genai
from fastapi import UploadFile, HTTPException
from PIL import Image
import io
import os
import re, json

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

def extraer_ticket_con_gemini(image_bytes: bytes) -> dict:
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel("gemini-1.5-flash")
    prompt = """
        Eres un extractor de tickets. Devuelve EXCLUSIVAMENTE un JSON válido con esta estructura EXACTA (sin texto extra):
        {
        "comercio": "",
        "fecha": "",
        "lineas": [
            {"producto": "", "cantidad": 0, "importe": 0}
        ],
        "total": 0
        }

        Reglas de extracción y normalización:
        - "comercio": nombre del establecimiento sin CIF/NIF, teléfonos ni dirección.
        - "fecha": en formato YYYY-MM-DD. Si no aparece con claridad, deja "".
        - "lineas": SOLO productos/servicios. Excluye TOTAL, SUBTOTAL, IVA/Tax, CAMBIO, PAGOS (cash/card), PROPINA, códigos de barras y líneas decorativas.
        - "producto": nombre legible (sin códigos internos), sin emojis.
        - "cantidad": número (int o decimal). Si el ticket indica “x2”, “2 uds”, etc., úsalo como cantidad.
        - "importe": PRECIO UNITARIO (no subtotal de línea). Usa PUNTO decimal. Sin símbolo € ni texto.
        - Moneda siempre EUR (no incluirla en el JSON).

        Cálculo y coherencia:
        - Subtotal de cada línea = cantidad * importe (no lo incluyas en el JSON).
        - "total" = SUMA EXACTA de todos los (cantidad * importe), redondeada a 2 decimales con redondeo bancario (half-to-even).
        - Si el ticket muestra un TOTAL diferente, PRIORIZA tu suma; no copies el impreso si hay discrepancias.
        - Si hay DESCUENTOS/OFERTAS en el ticket, añádelos como una línea con:
        {"producto": "Descuento ...", "cantidad": 1, "importe": -valor_unitario}
        - Si aparecen separadores de miles o comas decimales, normaliza: quita separadores de miles y usa punto como decimal (e.g., "1.234,56" → 1234.56).
        - Si una línea es ilegible/inconsistente y rompe la igualdad del total, corrige parsers evidentes (coma/punto, “x” por multiplicación) o elimina solo esa línea dudosa para que cuadre.

        Validación final OBLIGATORIA (antes de responder):
        - Verifica que total == Σ(cantidad*importe) con tolerancia ±0.01.
        - Verifica que todos los números son numéricos (no strings) y con como máximo 2 decimales.
        - No añadas campos ni comentarios. Responde SOLO el JSON final.
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
