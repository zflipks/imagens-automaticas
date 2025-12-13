import os
import json
import requests
from io import BytesIO
from PIL import Image
from datetime import datetime

BASE_DIR = "imagens"

CATEGORIAS = {
    "bomdia": "good morning aesthetic",
    "boatarde": "good afternoon aesthetic",
    "boanoite": "good night aesthetic"
}

IMAGENS_POR_CATEGORIA = 10


def baixar_imagem(categoria, busca, indice):
    try:
        url = f"https://source.unsplash.com/featured/1080x1080/?{busca}"
        print(f"Baixando imagem {indice} para {categoria}: {url}")

        response = requests.get(url, timeout=15)

        # Se não for sucesso, ignora
        if response.status_code != 200:
            print("Falhou download (status != 200)")
            return None

        image = Image.open(BytesIO(response.content)).convert("RGB")

        pasta = os.path.join(BASE_DIR, categoria)
        os.makedirs(pasta, exist_ok=True)

        caminho = os.path.join(pasta, f"{categoria}_{indice}.jpg")
        image.save(caminho, "JPEG", quality=90)

        return caminho.replace("\\", "/")

    except Exception as e:
        print(f"Erro ao baixar imagem {indice} ({categoria}): {e}")
        return None


def gerar_imagens():
    index = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "bomdia": [],
        "boatarde": [],
        "boanoite": []
    }

    for categoria, busca in CATEGORIAS.items():
        for i in range(1, IMAGENS_POR_CATEGORIA + 1):
            caminho = baixar_imagem(categoria, busca, i)

            if not caminho:
                continue  # 🔴 AQUI ESTÁ O LOOP CORRIGIDO

            index[categoria].append(
                f"https://raw.githubusercontent.com/zflipks/imagens-automaticas/main/{caminho}"
            )

    with open("index.json", "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)

    print("index.json gerado com sucesso")


if __name__ == "__main__":
    gerar_imagens()
