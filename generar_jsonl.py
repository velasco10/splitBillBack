import os
import json

BASE_DIR = r'G:\Mi unidad\PROYECTO\SplitBill\tickets'

for split in ['train', 'val']:
    image_dir = os.path.join(BASE_DIR, split, 'images')
    label_dir = os.path.join(BASE_DIR, split, 'labels')
    salida = os.path.join(BASE_DIR, split, f'{split}.jsonl')
    total, escritos = 0, 0

    if not os.path.exists(image_dir):
        print(f"❌ No existe la carpeta {image_dir}")
        continue
    if not os.path.exists(label_dir):
        print(f"❌ No existe la carpeta {label_dir}")
        continue

    with open(salida, 'w', encoding='utf8') as f_out:
        for nombre in os.listdir(image_dir):
            if nombre.lower().endswith(('.jpg', '.jpeg', '.png')):
                basename = os.path.splitext(nombre)[0]
                img_path = f'images/{nombre}'  # Ruta relativa para HF Datasets
                json_path = os.path.join(label_dir, basename + '.json')
                total += 1
                if os.path.exists(json_path):
                    with open(json_path, encoding='utf8') as fj:
                        gt = json.load(fj)
                    linea = {
                        "image_path": img_path,
                        "task_prompt": "<s_ticket>",
                        "ground_truth": json.dumps(gt, ensure_ascii=False)
                    }
                    f_out.write(json.dumps(linea, ensure_ascii=False) + '\n')
                    escritos += 1
                else:
                    print(f'⚠️ No se encontró JSON para {nombre} en {split}')
    print(f"[{split}] {escritos}/{total} imágenes escritas en {salida}")
    if escritos == 0:
        print(f"❌ ¡No se ha escrito ningún ejemplo en {salida}! Revisa los paths y nombres.")
