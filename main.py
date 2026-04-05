import os, sys, traceback, base64
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId
from bson.errors import InvalidId
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timedelta
from dotenv import load_dotenv
from utils_gemini import extraer_ticket_con_gemini
import jwt
import bcrypt
import stripe

load_dotenv()

app = FastAPI()

SCANS_FREE_MES   = 5
GRUPOS_FREE_MAX  = 4
JWT_SECRET       = os.getenv("JWT_SECRET", "supersecret_cambiame")
JWT_ALGORITHM    = "HS256"
JWT_EXPIRY_DAYS  = 30
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
STRIPE_PRICE_ID = os.getenv("STRIPE_PRICE_ID")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")

security = HTTPBearer(auto_error=False)

# ── Modelos ───────────────────────────────────────────────────────────────────

class ImagenData(BaseModel):
    base64: str
    mimetype: str = "image/jpeg"

class DivisionItem(BaseModel):
    nombre: str
    porcentaje: float
    importe: float

class PlantillaItem(BaseModel):
    categoria: str
    division: list[dict]

class MiembroIn(BaseModel):
    nombre: str

class GrupoIn(BaseModel):
    nombre: str
    tipo: str = "default"
    miembros: list[str] = []
    creadorId: str
    plantillas: list[PlantillaItem] = []

class GastoIn(BaseModel):
    grupoId: str
    concepto: str
    categoria: str
    importe: float
    emisor: str
    modo_division: str
    division: list[DivisionItem]
    fecha: Optional[str] = None
    ticket: Optional[dict] = None

class UsuarioIn(BaseModel):
    nombre: str
    email: str
    plan: str = "free"
    grupos: list[str] = []

class GrupoIdsRequest(BaseModel):
    ids: list[str]

class RegisterIn(BaseModel):
    nombre: str
    email: str
    password: str

class LoginIn(BaseModel):
    email: str
    password: str

class PagoProgramadoIn(BaseModel):
    grupoId:      str
    concepto:     str
    categoria:    str
    importe:      float
    emisor:       str
    rota:         bool = False          # si el emisor rota entre miembros
    division:     list[DivisionItem]
    modo_division: str = "igualitario"
    dia_mes:      int                   # 1-28, día del mes en que se genera
    activo:       bool = True
    omitir_mes:   Optional[str] = None  # "YYYY-MM" si el usuario pidió no mostrar este mes


class SuscripcionIn(BaseModel):
    success_url: str = "splitbill://perfil?pago=ok"
    cancel_url:  str = "splitbill://perfil?pago=cancelado"


# ── CORS y Middleware ─────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.options("/{path:path}")
async def cors_preflight(path: str):
    return JSONResponse(status_code=200, content={})

@app.middleware("http")
async def _log_errors(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception:
        traceback.print_exc(file=sys.stderr)
        raise

# ── DB ────────────────────────────────────────────────────────────────────────

MONGO_URL = os.getenv("MONGO_URL")

async def get_db():
    client = AsyncIOMotorClient(MONGO_URL)
    try:
        yield client["splitbill_db"]
    finally:
        client.close()

def to_str_id(doc: dict) -> dict:
    doc["_id"] = str(doc["_id"])
    return doc

# ── Auth helpers ──────────────────────────────────────────────────────────────

def crear_token(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "exp": datetime.utcnow() + timedelta(days=JWT_EXPIRY_DAYS)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def verificar_token(token: str) -> Optional[str]:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload.get("sub")
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expirado")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Token inválido")

async def get_usuario_opcional(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db = Depends(get_db)
) -> Optional[dict]:
    if not credentials:
        return None
    user_id = verificar_token(credentials.credentials)
    doc = await db["usuarios"].find_one({"_id": ObjectId(user_id)})
    if doc:
        return to_str_id(doc)
    return None

async def get_usuario_requerido(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db = Depends(get_db)
) -> dict:
    if not credentials:
        raise HTTPException(status_code=401, detail="Autenticación requerida")
    user_id = verificar_token(credentials.credentials)
    doc = await db["usuarios"].find_one({"_id": ObjectId(user_id)})
    if not doc:
        raise HTTPException(status_code=401, detail="Usuario no encontrado")
    return to_str_id(doc)

def usuario_puede_escanear(usuario: Optional[dict]) -> bool:
    if not usuario:
        return True
    if usuario.get("plan") == "premium":
        return True
    return usuario.get("scans_mes", 0) < SCANS_FREE_MES

def usuario_es_premium(usuario: Optional[dict]) -> bool:
    return usuario is not None and usuario.get("plan") == "premium"

# ── Root ──────────────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {"message": "splitBillBack is running 🚀"}

# ── Auth ──────────────────────────────────────────────────────────────────────

@app.post("/auth/registro")
async def registro(body: RegisterIn, db=Depends(get_db)):
    existente = await db["usuarios"].find_one({"email": body.email})
    if existente:
        raise HTTPException(status_code=400, detail="Ya existe una cuenta con ese email")

    hashed = bcrypt.hashpw(body.password.encode(), bcrypt.gensalt()).decode()
    data = {
        "nombre":       body.nombre,
        "email":        body.email,
        "password":     hashed,
        "plan":         "free",
        "scans_mes":    0,
        "scans_reset":  datetime.utcnow().strftime("%Y-%m"),
        "trial_expira": None,
        "creado_en":    datetime.utcnow().isoformat(),
        "grupos":       [],
    }
    result = await db["usuarios"].insert_one(data)
    user_id = str(result.inserted_id)
    token = crear_token(user_id)
    data["_id"] = user_id
    data.pop("password")
    return {"token": token, "usuario": data}

@app.post("/auth/login")
async def login(body: LoginIn, db=Depends(get_db)):
    doc = await db["usuarios"].find_one({"email": body.email})
    if not doc:
        raise HTTPException(status_code=401, detail="Email o contraseña incorrectos")

    password_hash = doc["password"]
    if isinstance(password_hash, str):
        password_hash = password_hash.encode('utf-8')

    if not bcrypt.checkpw(body.password.encode('utf-8'), password_hash):
        raise HTTPException(status_code=401, detail="Email o contraseña incorrectos")

    user_id = str(doc["_id"])
    token = crear_token(user_id)
    doc = to_str_id(doc)
    doc.pop("password", None)
    return {"token": token, "usuario": doc}

@app.get("/auth/me")
async def me(usuario: dict = Depends(get_usuario_requerido)):
    usuario.pop("password", None)
    return usuario

@app.post("/auth/reset-scans")
async def reset_scans(usuario: dict = Depends(get_usuario_requerido), db=Depends(get_db)):
    mes_actual = datetime.utcnow().strftime("%Y-%m")
    if usuario.get("scans_reset") != mes_actual:
        await db["usuarios"].update_one(
            {"_id": ObjectId(usuario["_id"])},
            {"$set": {"scans_mes": 0, "scans_reset": mes_actual}}
        )
    return {"msg": "ok"}

# ── Usuarios ──────────────────────────────────────────────────────────────────

@app.get("/usuarios/{id}")
async def obtener_usuario(id: str, db=Depends(get_db)):
    doc = await db["usuarios"].find_one({"_id": ObjectId(id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    doc = to_str_id(doc)
    doc.pop("password", None)
    return doc

@app.put("/usuarios/{id}")
async def actualizar_usuario(id: str, request: Request, db=Depends(get_db)):
    data = await request.json()
    data.pop("password", None)
    result = await db["usuarios"].update_one({"_id": ObjectId(id)}, {"$set": data})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return {"msg": "Usuario actualizado"}

@app.delete("/usuarios/{id}")
async def eliminar_usuario(id: str, db=Depends(get_db)):
    result = await db["usuarios"].delete_one({"_id": ObjectId(id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return {"msg": "Usuario eliminado"}

# ── Grupos ────────────────────────────────────────────────────────────────────

@app.post("/grupos")
async def crear_grupo(
    body: GrupoIn,
    db = Depends(get_db),
    usuario: Optional[dict] = Depends(get_usuario_opcional)
):
    # Límite de 4 grupos para free
    if usuario and not usuario_es_premium(usuario):
        ids_raw = await AsyncIOMotorClient(MONGO_URL)["splitbill_db"]["grupos"].count_documents(
            {"creadorId": body.creadorId}
        )
        # Más simple: contar directamente
        count = await db["grupos"].count_documents({"creadorId": body.creadorId})
        if count >= GRUPOS_FREE_MAX:
            raise HTTPException(
                status_code=403,
                detail=f"El plan gratuito permite un máximo de {GRUPOS_FREE_MAX} grupos. Hazte Premium para grupos ilimitados."
            )

    data = body.dict()
    data["creado_en"] = datetime.utcnow().isoformat()
    result = await db["grupos"].insert_one(data)
    data["_id"] = str(result.inserted_id)
    return data

@app.get("/grupos/{id}")
async def obtener_grupo(id: str, db=Depends(get_db)):
    try:
        doc = await db["grupos"].find_one({"_id": ObjectId(id)})
    except InvalidId:
        raise HTTPException(status_code=400, detail="ID inválido")
    if not doc:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")
    return to_str_id(doc)

@app.get("/grupos/creador/{creador_id}")
async def obtener_grupos_por_creador(creador_id: str, db=Depends(get_db)):
    grupos = []
    cursor = db["grupos"].find({"creadorId": creador_id})
    async for doc in cursor:
        grupos.append(to_str_id(doc))
    return grupos

@app.put("/grupos/{id}")
async def actualizar_grupo(id: str, request: Request, db=Depends(get_db)):
    data = await request.json()
    result = await db["grupos"].update_one({"_id": ObjectId(id)}, {"$set": data})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")
    return {"msg": "Grupo actualizado"}

@app.delete("/grupos/{id}")
async def eliminar_grupo(id: str, db=Depends(get_db)):
    result = await db["grupos"].delete_one({"_id": ObjectId(id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")
    return {"msg": "Grupo eliminado"}

@app.post("/grupos/{id}/miembros")
async def agregar_miembro(id: str, body: MiembroIn, db=Depends(get_db)):
    grupo = await db["grupos"].find_one({"_id": ObjectId(id)})
    if not grupo:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")
    if body.nombre in grupo.get("miembros", []):
        raise HTTPException(status_code=400, detail="Ya existe un miembro con ese nombre en el grupo")
    await db["grupos"].update_one(
        {"_id": ObjectId(id)},
        {"$addToSet": {"miembros": body.nombre}}
    )
    return {"msg": "Miembro añadido"}

@app.delete("/grupos/{id}/miembros/{nombre}")
async def eliminar_miembro(id: str, nombre: str, db=Depends(get_db)):
    result = await db["grupos"].update_one(
        {"_id": ObjectId(id)},
        {"$pull": {"miembros": nombre}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")
    return {"msg": "Miembro eliminado"}

@app.put("/grupos/{id}/plantillas")
async def actualizar_plantillas(id: str, plantillas: list[PlantillaItem], db=Depends(get_db)):
    result = await db["grupos"].update_one(
        {"_id": ObjectId(id)},
        {"$set": {"plantillas": [p.dict() for p in plantillas]}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")
    return {"msg": "Plantillas actualizadas"}

@app.post("/grupos/varios")
async def obtener_grupos_por_ids(request: GrupoIdsRequest, db=Depends(get_db)):
    try:
        object_ids = [ObjectId(id) for id in request.ids]
        grupos = []
        cursor = db["grupos"].find({"_id": {"$in": object_ids}})
        async for doc in cursor:
            grupos.append(to_str_id(doc))
        return grupos
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error buscando grupos: {str(e)}")

# ── Gastos ────────────────────────────────────────────────────────────────────

@app.post("/gastos")
async def agregar_gasto(body: GastoIn, db=Depends(get_db)):
    data = body.dict()
    if not data.get("fecha"):
        data["fecha"] = datetime.utcnow().strftime("%Y-%m-%d")
    result = await db["gastos"].insert_one(data)
    data["_id"] = str(result.inserted_id)
    return data

@app.get("/gastos/grupo/{grupo_id}")
async def obtener_gastos_por_grupo(grupo_id: str, db=Depends(get_db)):
    gastos = []
    cursor = db["gastos"].find({"grupoId": grupo_id}).sort("fecha", -1)
    async for doc in cursor:
        gastos.append(to_str_id(doc))
    return gastos

@app.get("/gastos/{id}")
async def obtener_gasto(id: str, db=Depends(get_db)):
    doc = await db["gastos"].find_one({"_id": ObjectId(id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Gasto no encontrado")
    return to_str_id(doc)

@app.put("/gastos/{id}")
async def actualizar_gasto(id: str, request: Request, db=Depends(get_db)):
    data = await request.json()
    result = await db["gastos"].update_one({"_id": ObjectId(id)}, {"$set": data})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Gasto no encontrado")
    return {"msg": "Gasto actualizado"}

@app.delete("/gastos/{id}")
async def eliminar_gasto(id: str, db=Depends(get_db)):
    result = await db["gastos"].delete_one({"_id": ObjectId(id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Gasto no encontrado")
    return {"msg": "Gasto eliminado"}

# ── Estadísticas ──────────────────────────────────────────────────────────────

@app.get("/estadisticas/grupo/{grupo_id}")
async def estadisticas_grupo(grupo_id: str, db=Depends(get_db)):
    gastos = []
    cursor = db["gastos"].find({"grupoId": grupo_id})
    async for doc in cursor:
        gastos.append(doc)

    if not gastos:
        return {"total": 0, "por_categoria": {}, "por_persona": {}}

    total = sum(g["importe"] for g in gastos)
    por_categoria = {}
    for g in gastos:
        cat = g.get("categoria", "otros")
        por_categoria[cat] = round(por_categoria.get(cat, 0) + g["importe"], 2)

    por_persona = {}
    for g in gastos:
        for d in g.get("division", []):
            nombre = d["nombre"]
            por_persona[nombre] = round(por_persona.get(nombre, 0) + d["importe"], 2)

    return {
        "total": round(total, 2),
        "por_categoria": por_categoria,
        "por_persona": por_persona
    }

# ── Pagos Programados ─────────────────────────────────────────────────────────

@app.post("/pagos_programados")
async def crear_pago_programado(
    body: PagoProgramadoIn,
    db = Depends(get_db),
    usuario: dict = Depends(get_usuario_requerido)
):
    if not usuario_es_premium(usuario):
        raise HTTPException(
            status_code=403,
            detail="Los pagos programados son una función Premium."
        )
    data = body.dict()
    data["creado_en"]     = datetime.utcnow().isoformat()
    data["creadorId"]     = usuario["_id"]
    data["ultimo_generado"] = None  # "YYYY-MM" del último mes generado
    result = await db["pagos_programados"].insert_one(data)
    data["_id"] = str(result.inserted_id)
    return data

@app.get("/pagos_programados/grupo/{grupo_id}")
async def obtener_pagos_programados(
    grupo_id: str,
    db = Depends(get_db),
    usuario: dict = Depends(get_usuario_requerido)
):
    if not usuario_es_premium(usuario):
        raise HTTPException(status_code=403, detail="Función Premium.")
    pagos = []
    cursor = db["pagos_programados"].find({"grupoId": grupo_id, "activo": True})
    async for doc in cursor:
        pagos.append(to_str_id(doc))
    return pagos

@app.get("/pagos_programados/pendientes")
async def obtener_pagos_pendientes(
    db = Depends(get_db),
    usuario: dict = Depends(get_usuario_requerido)
):
    """
    Devuelve pagos programados que vencen hoy o antes y no se han generado este mes.
    El front llama esto al arrancar para mostrar el aviso.
    """
    if not usuario_es_premium(usuario):
        return []

    hoy        = datetime.utcnow()
    mes_actual = hoy.strftime("%Y-%m")
    dia_actual = hoy.day

    pendientes = []
    cursor = db["pagos_programados"].find({
        "creadorId": usuario["_id"],
        "activo":    True,
    })
    async for doc in cursor:
        # Saltar si ya se generó este mes
        if doc.get("ultimo_generado") == mes_actual:
            continue
        # Saltar si el usuario pidió no mostrar este mes
        if doc.get("omitir_mes") == mes_actual:
            continue
        # Mostrar si el día ya ha llegado
        if dia_actual >= doc.get("dia_mes", 1):
            pendientes.append(to_str_id(doc))

    return pendientes

@app.put("/pagos_programados/{id}")
async def actualizar_pago_programado(
    id: str,
    request: Request,
    db = Depends(get_db),
    usuario: dict = Depends(get_usuario_requerido)
):
    if not usuario_es_premium(usuario):
        raise HTTPException(status_code=403, detail="Función Premium.")
    data = await request.json()
    result = await db["pagos_programados"].update_one(
        {"_id": ObjectId(id)},
        {"$set": data}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Pago programado no encontrado")
    return {"msg": "Pago programado actualizado"}

@app.post("/pagos_programados/{id}/registrar")
async def registrar_pago_programado(
    id: str,
    db = Depends(get_db),
    usuario: dict = Depends(get_usuario_requerido)
):
    """Genera el gasto real a partir del pago programado y marca como generado este mes."""
    if not usuario_es_premium(usuario):
        raise HTTPException(status_code=403, detail="Función Premium.")

    doc = await db["pagos_programados"].find_one({"_id": ObjectId(id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Pago programado no encontrado")

    mes_actual = datetime.utcnow().strftime("%Y-%m")

    # Calcular emisor — si rota, buscar el siguiente en la lista
    emisor = doc["emisor"]
    if doc.get("rota"):
        miembros = [d["nombre"] for d in doc.get("division", [])]
        if miembros:
            ultimo_idx = 0
            try:
                ultimo_idx = miembros.index(emisor)
            except ValueError:
                pass
            emisor = miembros[(ultimo_idx + 1) % len(miembros)]
            # Actualizar emisor para la próxima vez
            await db["pagos_programados"].update_one(
                {"_id": ObjectId(id)},
                {"$set": {"emisor": emisor}}
            )

    gasto = {
        "grupoId":      doc["grupoId"],
        "concepto":     doc["concepto"],
        "categoria":    doc.get("categoria", "otros"),
        "importe":      doc["importe"],
        "emisor":       emisor,
        "modo_division": doc.get("modo_division", "igualitario"),
        "division":     doc["division"],
        "fecha":        datetime.utcnow().strftime("%Y-%m-%d"),
        "ticket":       None,
        "programado":   True,
    }

    result = await db["gastos"].insert_one(gasto)
    gasto["_id"] = str(result.inserted_id)

    # Marcar como generado este mes
    await db["pagos_programados"].update_one(
        {"_id": ObjectId(id)},
        {"$set": {"ultimo_generado": mes_actual}}
    )

    return gasto

@app.post("/pagos_programados/{id}/omitir")
async def omitir_pago_mes(
    id: str,
    db = Depends(get_db),
    usuario: dict = Depends(get_usuario_requerido)
):
    """El usuario no quiere ver este pago este mes."""
    mes_actual = datetime.utcnow().strftime("%Y-%m")
    await db["pagos_programados"].update_one(
        {"_id": ObjectId(id)},
        {"$set": {"omitir_mes": mes_actual}}
    )
    return {"msg": "Pago omitido este mes"}

@app.delete("/pagos_programados/{id}")
async def eliminar_pago_programado(
    id: str,
    db = Depends(get_db),
    usuario: dict = Depends(get_usuario_requerido)
):
    if not usuario_es_premium(usuario):
        raise HTTPException(status_code=403, detail="Función Premium.")
    result = await db["pagos_programados"].delete_one({"_id": ObjectId(id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="No encontrado")
    return {"msg": "Pago programado eliminado"}

# ── Ticket IA ─────────────────────────────────────────────────────────────────

@app.post("/procesar_ticket/")
async def procesar_ticket(
    imagen: ImagenData,
    db = Depends(get_db),
    usuario: Optional[dict] = Depends(get_usuario_opcional)
):
    if usuario:
        if not usuario_puede_escanear(usuario):
            raise HTTPException(
                status_code=403,
                detail="Has alcanzado el límite de 5 scans este mes. Hazte premium para scans ilimitados."
            )
        mes_actual = datetime.utcnow().strftime("%Y-%m")
        if usuario.get("scans_reset") != mes_actual:
            await db["usuarios"].update_one(
                {"_id": ObjectId(usuario["_id"])},
                {"$set": {"scans_mes": 0, "scans_reset": mes_actual}}
            )
            usuario["scans_mes"] = 0

    try:
        base64_str = imagen.base64
        if "," in base64_str:
            base64_str = base64_str.split(",")[1]
        image_bytes = base64.b64decode(base64_str)
        resultado = extraer_ticket_con_gemini(image_bytes, imagen.mimetype)

        if usuario:
            await db["usuarios"].update_one(
                {"_id": ObjectId(usuario["_id"])},
                {"$inc": {"scans_mes": 1}}
            )

        return resultado
    except HTTPException:
        raise
    except Exception as e:
        print(f"DEBUG ERROR TICKET: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Error en el Agente: {str(e)}")
        
# ── Stripe ────────────────────────────────────────────────────────────────────

@app.post("/stripe/crear_suscripcion")
async def crear_suscripcion(
    db = Depends(get_db),
    usuario: dict = Depends(get_usuario_requerido)
):  
    if usuario.get("plan") == "premium":
        raise HTTPException(status_code=400, detail="Ya tienes el plan Premium")

    try:
        # Crear o recuperar cliente de Stripe
        stripe_customer_id = usuario.get("stripe_customer_id")

        if not stripe_customer_id:
            customer = stripe.Customer.create(
                email=usuario["email"],
                name=usuario["nombre"],
                metadata={"usuario_id": usuario["_id"]}
            )
            stripe_customer_id = customer.id
            await db["usuarios"].update_one(
                {"_id": ObjectId(usuario["_id"])},
                {"$set": {"stripe_customer_id": stripe_customer_id}}
            )

        # Crear sesión de pago
        session = stripe.checkout.Session.create(
            customer=stripe_customer_id,
            payment_method_types=["card"],
            line_items=[{
                "price": STRIPE_PRICE_ID,
                "quantity": 1,
            }],
            mode="subscription",
            success_url="splitbill://perfil?pago=ok",
            cancel_url="splitbill://perfil?pago=cancelado",
        )

        return {
            "url":        session.url,
            "session_id": session.id
        }

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/stripe/webhook")
async def stripe_webhook(request: Request, db=Depends(get_db)):
    payload    = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        if STRIPE_WEBHOOK_SECRET:
            event = stripe.Webhook.construct_event(
                payload, sig_header, STRIPE_WEBHOOK_SECRET
            )
        else:
            data  = await request.json()
            event = stripe.Event.construct_from(data, stripe.api_key)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    obj = event["data"]["object"]

    # Pago completado — activar premium
    if event["type"] == "checkout.session.completed":
        customer_id = obj.customer
        sub_id      = obj.subscription
        if customer_id:
            await db["usuarios"].update_one(
                {"stripe_customer_id": customer_id},
                {"$set": {
                    "plan": "premium",
                    "stripe_subscription_id": sub_id,
                }}
            )

    # Suscripción cancelada o pago fallido
    elif event["type"] in ["customer.subscription.deleted", "invoice.payment_failed"]:
        customer_id = obj.customer
        if customer_id:
            await db["usuarios"].update_one(
                {"stripe_customer_id": customer_id},
                {"$set": {"plan": "free"}}
            )

    # Renovación correcta
    elif event["type"] == "invoice.payment_succeeded":
        customer_id = obj.customer
        if customer_id:
            await db["usuarios"].update_one(
                {"stripe_customer_id": customer_id},
                {"$set": {"plan": "premium"}}
            )

    return {"msg": "ok"}

@app.post("/stripe/cancelar")
async def cancelar_suscripcion(
    db = Depends(get_db),
    usuario: dict = Depends(get_usuario_requerido)
):
    sub_id = usuario.get("stripe_subscription_id")
    if not sub_id:
        raise HTTPException(status_code=400, detail="No tienes suscripción activa")

    try:
        # Cancela al final del período actual, no inmediatamente
        stripe.Subscription.modify(sub_id, cancel_at_period_end=True)
        return {"msg": "Suscripción cancelada al final del período"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))