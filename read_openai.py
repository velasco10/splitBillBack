import google.generativeai as genai
from PIL import Image

# Pon aquí tu clave API
API_KEY = "AIzaSyDJbUgvuk9G7ek6EK6PtFc8iHLcySuCKpc"
genai.configure(api_key=API_KEY)

def extraer_ticket_con_gemini(img_path):
    # Cambia el modelo aquí
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
    img = Image.open(img_path)
    response = model.generate_content([prompt, img])
    return response.text

# Ejemplo de uso:
resultado = extraer_ticket_con_gemini("tickets/train/images/ticket001.jpg")
print(resultado)
