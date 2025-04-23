import os
import easyocr
import io

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from fastapi import Request
from bson import ObjectId
from fastapi import UploadFile, File
from PIL import Image
import numpy as np
import re    



app = FastAPI()

reader = easyocr.Reader(['es']) 

# CORS para permitir peticiones desde tu frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Cambia esto por el dominio de tu app en producción
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")
client = AsyncIOMotorClient(MONGO_URL)
db = client["splitbill_db"]

@app.get("/")
async def root():
    return {"message": "splitBillBack is running 🚀"}

@app.post("/usuarios")
async def crear_usuario(request: Request):
    data = await request.json()
    result = await db["usuarios"].insert_one(data)
    data["_id"] = str(result.inserted_id)
    return data

@app.get("/usuarios")
async def obtener_usuarios():
    usuarios = []
    cursor = db["usuarios"].find()
    async for doc in cursor:
        doc["_id"] = str(doc["_id"])
        usuarios.append(doc)
    return usuarios

@app.get("/usuarios/{id}")
async def obtener_usuario(id: str):
    usuario = await db["usuarios"].find_one({"_id": ObjectId(id)})
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    usuario["_id"] = str(usuario["_id"])
    return usuario

@app.put("/usuarios/{id}")
async def actualizar_usuario(id: str, request: Request):
    data = await request.json()
    result = await db["usuarios"].update_one({"_id": ObjectId(id)}, {"$set": data})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return {"msg": "Usuario actualizado"}

@app.delete("/usuarios/{id}")
async def eliminar_usuario(id: str):
    result = await db["usuarios"].delete_one({"_id": ObjectId(id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return {"msg": "Usuario eliminado"}

@app.post("/grupos")
async def crear_grupo(request: Request):
    data = await request.json()
    result = await db["grupos"].insert_one(data)
    data["_id"] = str(result.inserted_id)
    return data

@app.get("/grupos")
async def obtener_grupos():
    grupos = []
    cursor = db["grupos"].find()
    async for doc in cursor:
        doc["_id"] = str(doc["_id"])
        grupos.append(doc)
    return grupos

@app.get("/grupos/{id}")
async def obtener_grupo(id: str):
    grupo = await db["grupos"].find_one({"_id": ObjectId(id)})
    if not grupo:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")
    grupo["_id"] = str(grupo["_id"])
    return grupo

@app.put("/grupos/{id}")
async def actualizar_grupo(id: str, request: Request):
    data = await request.json()
    result = await db["grupos"].update_one({"_id": ObjectId(id)}, {"$set": data})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")
    return {"msg": "Grupo actualizado"}

@app.delete("/grupos/{id}")
async def eliminar_grupo(id: str):
    result = await db["grupos"].delete_one({"_id": ObjectId(id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")
    return {"msg": "Grupo eliminado"}

@app.post("/gastos")
async def agregar_gasto(request: Request):
    data = await request.json()
    result = await db["gastos"].insert_one(data)
    data["_id"] = str(result.inserted_id)
    return data

@app.get("/gastos")
async def obtener_gastos():
    gastos = []
    cursor = db["gastos"].find()
    async for doc in cursor:
        doc["_id"] = str(doc["_id"])
        gastos.append(doc)
    return gastos

@app.get("/gastos/grupo/{grupo_id}")
async def obtener_gastos_por_grupo(grupo_id: str):
    gastos = []
    cursor = db["gastos"].find({"grupoId": grupo_id})
    async for doc in cursor:
        doc["_id"] = str(doc["_id"])
        gastos.append(doc)
    return gastos

@app.put("/gastos/{id}")
async def actualizar_gasto(id: str, request: Request):
    data = await request.json()
    result = await db["gastos"].update_one({"_id": ObjectId(id)}, {"$set": data})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Gasto no encontrado")
    return {"msg": "Gasto actualizado"}

@app.delete("/gastos/{id}")
async def eliminar_gasto(id: str):
    result = await db["gastos"].delete_one({"_id": ObjectId(id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Gasto no encontrado")
    return {"msg": "Gasto eliminado"}

@app.post("/ocr")
async def procesar_ticket(file: UploadFile = File(...)):
    try:
        contents = await file.read()
        image = Image.open(io.BytesIO(contents))
        image_array = np.array(image)

        # OCR con coordenadas
        resultados = reader.readtext(image_array, detail=1)

        # Extraer texto + coordenadas verticales (Y)
        lineas_ocr = []
        for bbox, texto, _ in resultados:
            y = int(bbox[0][1])  # coordenada Y de la esquina superior izquierda
            lineas_ocr.append({
                "texto": texto,
                "y": y
            })

        # Ordenar de arriba hacia abajo
        lineas_ocr.sort(key=lambda x: x["y"])

        return {
            "lineas_ocr": lineas_ocr
        }

    except Exception as e:
        print("❌ ERROR OCR:", e)
        raise HTTPException(status_code=500, detail=f"Error en OCR: {str(e)}")

from fastapi import Request

@app.post("/interpretar")
async def interpretar_ticket(request: Request):
    try:
        datos = await request.json()
        lineas = datos.get("lineas_ocr", [])

        # --- Paso 1: Ordenar líneas por coordenada Y ---
        lineas.sort(key=lambda l: l["y"])

        # --- Paso 2: Buscar índice de la cabecera y final de tabla ---
        indice_inicio = None
        indice_fin = None

        for i, linea in enumerate(lineas):
            texto = linea["texto"].lower()

            if any(pal in texto for pal in ["descr", "und", "pvp", "precio"]):
                indice_inicio = i
            if any(pal in texto for pal in ["pagar", "total"]):
                indice_fin = i
                break

        if indice_inicio is None or indice_fin is None:
            raise HTTPException(status_code=422, detail="No se encontró tabla reconocible")

        # --- Paso 3: Extraer y limpiar cabecera ---
        cabecera_texto = lineas[indice_inicio]["texto"].lower()
        posibles_claves = {
            "descr": "descripcion",
            "und": "cantidad",
            "x": "cantidad",
            "pvp": "precio_unitario",
            "precio": "precio_total"
        }

        claves = []
        for palabra in cabecera_texto.split():
            for key in posibles_claves:
                if key in palabra:
                    claves.append(posibles_claves[key])
                    break

        # --- Paso 4: Recorrer filas y asignar valores ---
        items = []
        for linea in lineas[indice_inicio+1:indice_fin]:
            valores = linea["texto"].replace(",", ".").split()
            if len(valores) != len(claves):
                continue  # salto si la fila no coincide con la cabecera

            item = {}
            for idx, clave in enumerate(claves):
                valor = valores[idx]
                if clave in ["precio_unitario", "precio_total"]:
                    try:
                        item[clave] = float(valor)
                    except:
                        item[clave] = None
                elif clave == "cantidad":
                    item[clave] = int(valor.replace("x", ""))
                else:
                    item[clave] = valor

            items.append(item)

        # --- Paso 5: Detectar total de ticket ---
        total_detectado = None
        for linea in lineas[indice_fin:]:
            if "pagar" in linea["texto"].lower():
                match = re.search(r"\d+[\.,]?\d*", linea["texto"])
                if match:
                    total_detectado = float(match.group().replace(",", "."))
                    break

        return {
            "items": items,
            "items_detectados": len(items),
            "total_detectado": total_detectado
        }

    except Exception as e:
        print("❌ ERROR INTERPRETAR:", e)
        raise HTTPException(status_code=500, detail=f"Error interpretando OCR: {str(e)}")
