import os
import shutil
import json

# 📁 Ruta donde están las imágenes
directorio = "./tickets"  # <-- cambia a tu carpeta

# 📁 Carpeta para los jsons (se crea si no existe)
carpeta_jsons = os.path.join(directorio, "jsons")
os.makedirs(carpeta_jsons, exist_ok=True)

# 🎯 Extensiones de imagen válidas
extensiones_validas = [".jpg", ".jpeg", ".png"]

# 📦 Recorremos y renombramos
imagenes = sorted([f for f in os.listdir(directorio) if os.path.splitext(f)[1].lower() in extensiones_validas])
contador = 1

for img in imagenes:
    ext = os.path.splitext(img)[1]
    nuevo_nombre = f"ticket{contador:03d}{ext}"
    ruta_origen = os.path.join(directorio, img)
    ruta_destino = os.path.join(directorio, nuevo_nombre)

    # Renombrar imagen
    os.rename(ruta_origen, ruta_destino)

    # Crear JSON correspondiente vacío
    json_path = os.path.join(carpeta_jsons, f"ticket{contador:03d}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"gt_parse": {"items": [], "total_ticket": ""}}, f, indent=2)

    print(f"✅ {img} → {nuevo_nombre} + JSON creado")
    contador += 1

print("\n🟢 Proceso completado.")
