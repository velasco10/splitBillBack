import os
from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from fastapi import Request
from bson import ObjectId
from utils_gemini import extraer_ticket_con_gemini
import base64
from pydantic import BaseModel
from dotenv import load_dotenv

app = FastAPI()

class ImagenData(BaseModel):
    base64: str
    mimetype: str = "image/jpeg"

class GrupoIdsRequest(BaseModel):
    ids: list[str]

# CORS para permitir peticiones desde tu frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Cambia esto por el dominio de tu app en producción
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MONGO_URL = os.getenv("MONGO_URL")
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
    print("Entra en la ceacion", request.json)
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

@app.post("/procesar_ticket/")
async def procesar_ticket(imagen: ImagenData):
    try:
        image_bytes = base64.b64decode(imagen.base64)
        resultado = extraer_ticket_con_gemini(image_bytes)
        return resultado
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error procesando imagen: {str(e)}")

@app.get("/grupos/creador/{creador_id}")
async def obtener_grupos_por_creador(creador_id: str):
    grupos = []
    cursor = db["grupos"].find({"creadorId": creador_id})
    async for doc in cursor:
        doc["_id"] = str(doc["_id"])
        grupos.append(doc)
    return grupos

@app.post("/grupos/varios")
async def obtener_grupos_por_ids(request: GrupoIdsRequest):
    try:
        object_ids = [ObjectId(id) for id in request.ids]
        grupos = []
        cursor = db["grupos"].find({"_id": {"$in": object_ids}})
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            grupos.append(doc)
        return grupos
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error buscando grupos: {str(e)}")