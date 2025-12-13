import os
import json
import requests
from io import BytesIO
from PIL import Image
from datetime import datetime
import random # 🚨 É NECESSÁRIO IMPORTAR RANDOM!

BASE_DIR = "imagens"

CATEGORIAS = {
    "bomdia": "good morning aesthetic",
    "boatarde": "good afternoon aesthetic",
    "boanoite": "good night aesthetic"
}

IMAGENS_POR_CATEGORIA = 10


def baixar_imagem(categoria, busca, indice):
    try:
        url = f"https://picsum.photos/1080/1080?random={random.randint(1, 100000) + indice}"
        print(f"Baixando imagem {indice} para {categoria}: {url}")

        response = requests.get(url, timeout=20) # Aumentei o timeout para 20 segundos

        if response.status_code != 200:
            print(f"Falhou download (status != 200): {response.status_code}")
            return None

        try:
            image = Image.open(BytesIO(response.content)).convert("RGB")
        except Exception as e:
            print(f"Falha ao abrir imagem baixada: {e}")
            return None

        pasta = os.path.join(BASE_DIR, categoria)
        os.makedirs(pasta, exist_ok=True) 

        caminho = os.path.join(pasta, f"{categoria}_{indice}.jpg")
        image.save(caminho, "JPEG", quality=90)

        return caminho.replace("\\", "/")

    except Exception as e:
        print(f"Erro CRÍTICO ao baixar imagem {indice} ({categoria}): {e}")
        return None


def gerar_imagens():
    os.makedirs(BASE_DIR, exist_ok=True) 

    index = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "bomdia": [],
        "boatarde": [],
        "boanoite": []
    }

    for categoria, busca in CATEGORIAS.items():
        print(f"\n--- Iniciando {categoria} ---")
        for i in range(1, IMAGENS_POR_CATEGORIA + 1):
            caminho = baixar_imagem(categoria, busca, i)

            if caminho:
                index[categoria].append(
                    f"https://raw.githubusercontent.com/zflipks/imagens-automaticas/main/{caminho}"
                )
            else:
                print(f"--- Pulando {categoria}_{i} devido a falha. ---")


    with open("index.json", "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)

    print("\nindex.json gerado com sucesso!")


if __name__ == "__main__":
    gerar_imagens()
