import os
import json
import requests
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont 
from datetime import datetime
import random 

BASE_DIR = "imagens"
CATEGORIAS = {
    "bomdia": "good morning aesthetic",
    "boatarde": "good afternoon aesthetic",
    "boanoite": "good night aesthetic"
}
IMAGENS_POR_CATEGORIA = 10

MENSAGENS = {
    "bomdia": [
        "Bom Dia! Que o seu dia seja leve e repleto de sorrisos.",
        "Acredite no poder de um novo começo.",
        "A felicidade é o caminho. Bom dia!"
    ],
    "boatarde": [
        "Que a sua tarde seja abençoada e produtiva.",
        "Pausa para o café e para sorrir. Boa Tarde!",
        "Metade do dia já foi, siga em frente!"
    ],
    "boanoite": [
        "Boa Noite! Descanse e recarregue as energias.",
        "Que a paz encontre você e te abrace. Boa Noite.",
        "Até amanhã. Que Deus te guarde."
    ]
}

FONT_PATH = "DejaVuSans-Bold.ttf" 
FONT_SIZE = 50 

def adicionar_texto_a_imagem(image, categoria):
    draw = ImageDraw.Draw(image)
    frase = random.choice(MENSAGENS[categoria])
    
    y_offset = 50 
    
    try:
        font = ImageFont.truetype(FONT_PATH, FONT_SIZE)
        y_offset = 100 
    except IOError:
        font = ImageFont.load_default()
        y_offset = 20 
        
    largura_img, altura_img = image.size
    
    largura_texto = draw.textlength(frase, font=font)
    
    x = (largura_img - largura_texto) // 2
    
    y = altura_img // 2 - y_offset 

    for offset in [(-2, -2), (2, 2), (-2, 2), (2, -2)]:
         draw.text((x + offset[0], y + offset[1]), frase, font=font, fill=(0, 0, 0))

    draw.text((x, y), frase, font=font, fill=(255, 255, 255))

    return image


def baixar_imagem(categoria, busca, indice):
    try:
        url = f"https://picsum.photos/1080/1080?random={random.randint(1, 100000) + indice}"
        print(f"Baixando imagem {indice} para {categoria}: {url}")

        response = requests.get(url, timeout=20)
        if response.status_code != 200:
            print(f"Falhou download: {response.status_code}")
            return None

        try:
            image = Image.open(BytesIO(response.content)).convert("RGB")
        except Exception:
            return None
        
        image_editada = adicionar_texto_a_imagem(image, categoria) 

        pasta = os.path.join(BASE_DIR, categoria)
        os.makedirs(pasta, exist_ok=True) 

        caminho = os.path.join(pasta, f"{categoria}_{indice}.jpg")
        image_editada.save(caminho, "JPEG", quality=90) 

        return caminho.replace("\\", "/")

    except Exception as e:
        print(f"Erro CRÍTICO ao baixar/editar imagem {indice} ({categoria}): {e}")
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
