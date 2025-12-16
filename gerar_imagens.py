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

# ================= FRASES =================

MENSAGENS = {
    "bomdia": [
        "Bom dia! Que hoje seja leve, feliz e abençoado.",
        "Que o dia comece com paz e termine com gratidão.",
        "Bom dia! Que não falte fé, amor e esperança hoje.",
        "Um novo dia, uma nova chance de ser feliz.",
        "Acorde com o coração cheio de coisas boas.",
        "Que Deus abençoe cada passo do seu dia.",
        "Bom dia! Que sua manhã seja cheia de luz.",
        "Respire fundo, sorria e siga com fé.",
        "Hoje vai dar certo. Confie.",
        "Que o bem te encontre logo cedo.",
        "Comece o dia com pensamentos positivos.",
        "Bom dia! Que a alegria te acompanhe.",
        "Mais um dia para agradecer e recomeçar.",
        "Que hoje não falte coragem nem motivos para sorrir.",
        "Bom dia! Que a paz seja seu primeiro pensamento.",
        "Um lindo dia começa com um coração grato.",
        "Bom dia! Espalhe coisas boas por onde passar.",
        "Que sua manhã seja doce e seu dia produtivo.",
        "A felicidade começa em um bom dia.",
        "Bom dia! Que hoje seja melhor que ontem.",
        "Que o amor guie seus passos hoje.",
        "Um sorriso muda tudo. Bom dia!",
        "Bom dia! Que não falte luz no seu caminho.",
        "Acredite: coisas boas acontecem.",
        "Que sua manhã seja tranquila e feliz.",
        "Bom dia! Que a vida te surpreenda.",
        "Hoje é dia de vencer.",
        "Que a fé te acompanhe desde cedo.",
        "Bom dia! Aproveite cada instante.",
        "Um novo dia, novas oportunidades."
    ],
    "boatarde": [
        "Boa tarde! Que o resto do dia seja leve.",
        "Que a paz continue com você nesta tarde.",
        "Boa tarde! Respire fundo e siga confiante.",
        "Que sua tarde seja abençoada.",
        "Boa tarde! Ainda dá tempo de sorrir.",
        "Que não falte calma nem esperança nesta tarde.",
        "Boa tarde! Que o bem te acompanhe.",
        "Uma tarde tranquila começa com pensamentos bons.",
        "Boa tarde! Que tudo flua com leveza.",
        "Ainda há muitas coisas boas pela frente.",
        "Boa tarde! Que seu coração esteja em paz.",
        "Que esta tarde traga boas notícias.",
        "Boa tarde! Continue acreditando.",
        "Que sua tarde seja iluminada.",
        "Boa tarde! Não desista, você está indo bem.",
        "Uma tarde abençoada para você.",
        "Boa tarde! Que o dia termine melhor do que começou.",
        "Que a fé renove suas forças nesta tarde.",
        "Boa tarde! Sorria, a vida agradece.",
        "Que sua tarde seja cheia de boas energias.",
        "Boa tarde! Tudo acontece no tempo certo.",
        "Que a calma guie seu restante do dia.",
        "Boa tarde! Ainda há motivos para agradecer.",
        "Que sua tarde seja leve como a brisa.",
        "Boa tarde! Que a alegria permaneça.",
        "Mais uma tarde para espalhar o bem.",
        "Boa tarde! Que o amor esteja presente.",
        "Que sua tarde seja produtiva e feliz.",
        "Boa tarde! Continue com fé.",
        "Uma linda tarde para você."
    ],
    "boanoite": [
        "Boa noite! Que a paz tome conta do seu coração.",
        "Que sua noite seja tranquila e abençoada.",
        "Boa noite! Descanse com o coração em paz.",
        "Que Deus cuide de você nesta noite.",
        "Boa noite! Amanhã será um novo dia.",
        "Que a calma te envolva nesta noite.",
        "Boa noite! Gratidão por mais um dia.",
        "Que seu descanso seja leve.",
        "Boa noite! Que os sonhos sejam bons.",
        "Que a noite traga renovação.",
        "Boa noite! Entregue tudo nas mãos de Deus.",
        "Que a paz reine em seu lar esta noite.",
        "Boa noite! Hora de descansar o corpo e a mente.",
        "Que sua noite seja cheia de serenidade.",
        "Boa noite! Tudo ficará bem.",
        "Que a fé acalme seu coração nesta noite.",
        "Boa noite! Agradeça e descanse.",
        "Que o silêncio da noite traga paz.",
        "Boa noite! Amanhã tem coisas boas esperando.",
        "Que sua noite seja protegida.",
        "Boa noite! Confie no amanhã.",
        "Que os bons pensamentos te acompanhem.",
        "Boa noite! Descanse sem preocupações.",
        "Que a noite leve embora o cansaço.",
        "Boa noite! Que a esperança se renove.",
        "Que sua noite seja iluminada.",
        "Boa noite! Durma com tranquilidade.",
        "Que a paz esteja com você nesta noite.",
        "Boa noite! Descanse e recarregue as energias.",
        "Uma noite abençoada para você."
    ]
}

# ================= TEXTO NA IMAGEM =================

FONT_PATH = "Pacifico-Regular.ttf"
FONT_SIZE = 64

def wrap_text_simple(text, limit):
    palavras = text.split()
    linhas = []
    linha_atual = ""

    for palavra in palavras:
        if len(linha_atual) + len(palavra) + 1 <= limit:
            linha_atual = (linha_atual + " " + palavra).strip()
        else:
            linhas.append(linha_atual)
            linha_atual = palavra

    if linha_atual:
        linhas.append(linha_atual)

    return linhas


def adicionar_texto_a_imagem(image, frase):
    largura_img, altura_img = image.size
    CHAR_LIMIT = 25

    font = ImageFont.truetype(FONT_PATH, FONT_SIZE)
    draw = ImageDraw.Draw(image)

    linhas = wrap_text_simple(frase, CHAR_LIMIT)
    altura_linha = FONT_SIZE + 10
    bloco_altura = len(linhas) * altura_linha
    y = altura_img // 2 - bloco_altura // 2

    for linha in linhas:
        largura_texto = draw.textlength(linha, font=font)
        x = (largura_img - largura_texto) // 2

        for ox, oy in [(-2,-2),(2,2),(-2,2),(2,-2)]:
            draw.text((x+ox, y+oy), linha, font=font, fill=(0,0,0))

        draw.text((x, y), linha, font=font, fill=(255,255,255))
        y += altura_linha

    return image


# ================= DOWNLOAD =================

def baixar_imagem(categoria, indice, frase):
    url = f"https://picsum.photos/1080/1080?random={random.randint(1,999999)}"
    print(f"Baixando {categoria} {indice}")

    response = requests.get(url, timeout=20)
    image = Image.open(BytesIO(response.content)).convert("RGB")

    image = adicionar_texto_a_imagem(image, frase)

    pasta = os.path.join(BASE_DIR, categoria)
    os.makedirs(pasta, exist_ok=True)

    caminho = os.path.join(pasta, f"{categoria}_{indice}.jpg")
    image.save(caminho, "JPEG", quality=90)

    return caminho.replace("\\", "/")


# ================= GERAR =================

def gerar_imagens():
    os.makedirs(BASE_DIR, exist_ok=True)

    index = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "bomdia": [],
        "boatarde": [],
        "boanoite": []
    }

    for categoria in CATEGORIAS:
        frases = random.sample(MENSAGENS[categoria], IMAGENS_POR_CATEGORIA)

        for i in range(IMAGENS_POR_CATEGORIA):
            caminho = baixar_imagem(categoria, i+1, frases[i])
            index[categoria].append(
                f"https://raw.githubusercontent.com/zflipks/imagens-automaticas/main/{caminho}"
            )

    with open("index.json", "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)

    print("index.json gerado com sucesso!")


if __name__ == "__main__":
    gerar_imagens()
