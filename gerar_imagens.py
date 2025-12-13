import requests
from PIL import Image
from io import BytesIO
import os
import time

def baixar_imagem(categoria, busca, indice):
    url = f"https://source.unsplash.com/featured/1080x1080/?{busca}"
    print(f"Baixando imagem {indice} para {categoria}: {url}")

    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    response = requests.get(url, headers=headers, timeout=20)

    # ✅ valida se é imagem
    content_type = response.headers.get("Content-Type", "")
    if "image" not in content_type:
        print(f"⚠️ Resposta não é imagem ({content_type}), pulando...")
        return None

    try:
        image = Image.open(BytesIO(response.content)).convert("RGB")
    except Exception as e:
        print(f"⚠️ Erro ao abrir imagem: {e}")
        return None

    pasta = f"imagens/{categoria}"
    os.makedirs(pasta, exist_ok=True)

    caminho = f"{pasta}/{categoria}_{indice}.jpg"
    image.save(caminho, "JPEG", quality=95)

    time.sleep(1)  # evita bloqueio do Unsplash
    return caminho
