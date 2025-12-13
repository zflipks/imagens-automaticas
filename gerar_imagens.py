import os
import json
import requests
from datetime import datetime
from PIL import Image
from io import BytesIO

# Categorias e termos de pesquisa
CATEGORIAS = {
    "bomdia": "good morning aesthetic wallpaper",
    "boatarde": "good afternoon aesthetic wallpaper",
    "boanoite": "good night aesthetic wallpaper"
}

# API para gerar imagens aleatórias
URL_API = "https://source.unsplash.com/featured/1080x1080/?{}"

# Quantidade de imagens por categoria
QTD_IMAGENS = 10

def baixar_imagem(categoria, termo_busca, numero):
    url = URL_API.format(termo_busca)
    print(f"Baixando imagem {numero} para {categoria}: {url}")

    response = requests.get(url)
    image = Image.open(BytesIO(response.content))

    # Nome da imagem
    nome_arquivo = f"{datetime.now().strftime('%Y-%m-%d')}_{numero}.jpg"
    caminho = f"imagens/{categoria}/{nome_arquivo}"

    # Criar diretório
    os.makedirs(f"imagens/{categoria}", exist_ok=True)

    # Salvar imagem
    image.save(caminho, "JPEG")
    print(f"Imagem salva em: {caminho}")

    return caminho

def atualizar_index():
    index_path = "index.json"

    # Carrega se existir
    if os.path.exists(index_path):
        with open(index_path, "r") as f:
            dados = json.load(f)
    else:
        dados = []

    novo_registro = {
        "data": datetime.now().strftime("%Y-%m-%d"),
        "imagens": {}
    }

    # Criar imagens por categoria
    for categoria, busca in CATEGORIAS.items():
        novo_registro["imagens"][categoria] = []

        for i in range(1, QTD_IMAGENS + 1):
            caminho = baixar_imagem(categoria, busca, i)
            novo_registro["imagens"][categoria].append(caminho)

    # Inserir no topo
    dados.insert(0, novo_registro)

    # Salvar index atualizado
    with open(index_path, "w") as f:
        json.dump(dados, f, indent=4)

    print("index.json atualizado com 10 imagens por categoria!")

if __name__ == "__main__":
    atualizar_index()

index = {
    "bomdia": [],
    "boatarde": [],
    "boanoite": []
}

for cat in CATEGORIAS:
    pasta = f"imagens/{cat}"
    arquivos = sorted(os.listdir(pasta))
    for arq in arquivos:
        index[cat].append(f"{pasta}/{arq}")

with open("index.json", "w", encoding="utf-8") as f:
    json.dump(index, f, ensure_ascii=False, indent=2)
