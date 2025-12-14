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
FONT_SIZE = 70 

def adicionar_texto_a_imagem(image, categoria):
    
    frase = random.choice(MENSAGENS[categoria])
    largura_img, altura_img = image.size
    
    SCALE_FACTOR = 5 
    
    try:
        font = ImageFont.truetype(FONT_PATH, FONT_SIZE)
        y_offset = 100 
        draw = ImageDraw.Draw(image)
        largura_texto = draw.textlength(frase, font=font)
        x = (largura_img - largura_texto) // 2
        y = altura_img // 2 - y_offset
        
        for offset in [(-2, -2), (2, 2), (-2, 2), (2, -2)]:
             draw.text((x + offset[0], y + offset[1]), frase, font=font, fill=(0, 0, 0))
        draw.text((x, y), frase, font=font, fill=(255, 255, 255))
        
    except IOError:
        
        font_default = ImageFont.load_default()
        
        temp_w = largura_img * SCALE_FACTOR
        temp_h = 300 * SCALE_FACTOR 
        temp_img = Image.new('RGB', (temp_w, temp_h), color='black') 
        temp_draw = ImageDraw.Draw(temp_img)
        
        text_w = temp_draw.textlength(frase, font=font_default)
        text_h = 100 
        
        x_temp = (temp_w - text_w) // 2
        y_temp = (temp_h - text_h) // 2
        
        for offset in [(-2, -2), (2, 2), (-2, 2), (2, -2)]:
            temp_draw.text((x_temp + offset[0], y_temp + offset[1]), frase, font=font_default, fill=(0, 0, 0))

        temp_draw.text((x_temp, y_temp), frase, font=font_default, fill=(255, 255, 255))
        
        bbox = temp_draw.textbbox((x_temp, y_temp), frase, font=font_default)
        
        text_area = temp_img.crop((0, y_temp - 50, temp_w, y_temp + text_h + 50))
        text_area_resized = text_area.resize((largura_img, text_area.height // SCALE_FACTOR))
        
        text_y_pos = (altura_img - text_area_resized.height) // 2 
        image.paste(text_area_resized, (0, text_y_pos))

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
