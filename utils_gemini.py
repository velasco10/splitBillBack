import os
import json
import base64
import requests
from fastapi import HTTPException

MOCK_MODE = os.getenv("MOCK_GEMINI", "false").lower() == "true"

MOCK_RESPONSE = {
    "comercio": "Supermercado Test",
    "fecha": "2026-04-03",
    "lineas": [
        {"producto": "Cerveza", "cantidad": 4, "importe": 1.20},
        {"producto": "Patatas", "cantidad": 1, "importe": 2.50},
        {"producto": "Refresco", "cantidad": 2, "importe": 1.80}
    ],
    "total": 10.90
}

def extraer_ticket_con_gemini(image_bytes: bytes, mime_type: str = "image/jpeg") -> dict:
    SYSTEM_PROMPT = """
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
    - "cantidad": número (int o decimal). Si el ticket indica "x2", "2 uds", etc., úsalo como cantidad.
    - "importe": PRECIO UNITARIO (no subtotal de línea). Usa PUNTO decimal. Sin símbolo € ni texto.
    - Moneda siempre EUR (no incluirla en el JSON).

    Cálculo y coherencia:
    - Subtotal de cada línea = cantidad * importe (no lo incluyas en el JSON).
    - "total" = SUMA EXACTA de todos los (cantidad * importe), redondeada a 2 decimales con redondeo bancario (half-to-even).
    - Si el ticket muestra un TOTAL diferente, PRIORIZA tu suma; no copies el impreso si hay discrepancias.
    - Si hay DESCUENTOS/OFERTAS en el ticket, añádelos como una línea con:
    {"producto": "Descuento ...", "cantidad": 1, "importe": -valor_unitario}
    - Si aparecen separadores de miles o comas decimales, normaliza: quita separadores de miles y usa punto como decimal (e.g., "1.234,56" → 1234.56).
    - Si una línea es ilegible/inconsistente y rompe la igualdad del total, corrige parsers evidentes (coma/punto, "x" por multiplicación) o elimina solo esa línea dudosa para que cuadre.

    Validación final OBLIGATORIA (antes de responder):
    - Verifica que total == Σ(cantidad*importe) con tolerancia ±0.01.
    - Verifica que todos los números son numéricos (no strings) y con como máximo 2 decimales.
    - No añadas campos ni comentarios. Responde SOLO el JSON final.
    """

    if MOCK_MODE:
        print("⚠️  MOCK_MODE activo — no se llama a Gemini")
        return MOCK_RESPONSE

    api_key = os.getenv("GEMINI_API_KEY")
    #url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    image_base64 = base64.b64encode(image_bytes).decode('utf-8')

    payload = {
        "system_instruction": {
            "parts": [{"text": SYSTEM_PROMPT}]
        },
        "contents": [{
            "parts": [
                {
                    "inline_data": {
                        "mime_type": mime_type,
                        "data": image_base64
                    }
                },
                {"text": "Extrae el JSON del ticket."}
            ]
        }],
        "generationConfig": {
            "temperature": 0.1,
            "response_mime_type": "application/json"
        }
    }

    try:
        response = requests.post(url, json=payload, timeout=45)
        res_json = response.json()

        if response.status_code != 200:
            print("--- ERROR DE GOOGLE ---")
            print(json.dumps(res_json, indent=2))
            raise Exception(res_json.get('error', {}).get('message', 'Error en la petición'))

        texto_respuesta = res_json['candidates'][0]['content']['parts'][0]['text']
        return json.loads(texto_respuesta)

    except Exception as e:
        print(f"ERROR FINAL: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Error en el agente: {str(e)}")
