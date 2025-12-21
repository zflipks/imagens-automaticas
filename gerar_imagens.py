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
    "boanoite": "good night aesthetic",
    "anonovo": "happy new year aesthetic",
    "aniversario": "birthday aesthetic"
}

IMAGENS_POR_CATEGORIA = 10

# ================= FRASES =================

MENSAGENS = {

    "bomdia": [
        "Bom dia ☀️ Que Deus abençoe cada passo seu hoje, ilumine suas decisões e encha seu coração de paz e esperança. 🙏",
        "Bom dia 🙏 Comece este dia confiando em Deus, Ele já preparou tudo o que você precisa.",
        "Bom dia 🌤️ Que a presença de Deus te acompanhe hoje, trazendo calma, força e gratidão.",
        "Bom dia ☀️ Entregue seus planos a Deus e confie que Ele fará o melhor.",
        "Bom dia 🙏 Respire fundo e confie: Deus está cuidando de tudo.",
        "Bom dia 🌿 Que Deus renove suas forças hoje.",
        "Bom dia ☀️ Acorde com fé no coração.",
        "Bom dia 🌤️ Deus já está à frente de tudo.",
        "Bom dia 🙏 Que a paz de Deus invada seu coração.",
        "Bom dia ☀️ Hoje será um dia abençoado."
    ],

    "boatarde": [
        "Boa tarde ☀️ Que Deus renove suas forças e acalme seu coração agora.",
        "Boa tarde 🙏 Mesmo cansado, confie: Deus cuida de você.",
        "Boa tarde 🌿 Que a paz de Deus te envolva.",
        "Boa tarde ☀️ Entregue o resto do dia nas mãos de Deus.",
        "Boa tarde 🙏 Deus está no controle.",
        "Boa tarde 🌼 Que a esperança renasça.",
        "Boa tarde ☀️ Confie no tempo de Deus.",
        "Boa tarde 🙏 Você não está sozinho.",
        "Boa tarde 🌿 Deus não falha.",
        "Boa tarde ☀️ Que a paz permaneça."
    ],

    "boanoite": [
        "Boa noite 🌙 Entregue tudo a Deus e descanse.",
        "Boa noite 🙏 Que Deus leve embora todo cansaço.",
        "Boa noite 🌟 Amanhã Deus continuará cuidando.",
        "Boa noite 🌙 Descanse em paz.",
        "Boa noite 🙏 Deus não dorme.",
        "Boa noite 🌟 Que seu sono seja abençoado.",
        "Boa noite 🌙 Confie em Deus.",
        "Boa noite 🙏 Acalme o coração.",
        "Boa noite 🌟 Deus está cuidando de tudo.",
        "Boa noite 🌙 Uma noite abençoada."
    ],

    "anonovo": [
        "Feliz Ano Novo 🎉 Que Deus vá à sua frente abrindo caminhos e renovando sua fé.",
        "Que este novo ano seja guiado pela fé, esperança e amor de Deus.",
        "Novo ano, nova chance de confiar ainda mais em Deus.",
        "Que Deus abençoe cada dia deste novo ano.",
        "Que a paz de Deus acompanhe você durante todo o ano.",
        "Novo ano é presente de Deus.",
        "Que seus sonhos estejam nas mãos de Deus.",
        "Comece o ano com gratidão e fé.",
        "Que Deus transforme desafios em vitórias.",
        "Feliz Ano Novo! Deus abençoe sua vida."
    ],

    "aniversario": [
        "Feliz Aniversário 🎂 Que Deus abençoe sua vida com saúde e paz.",
        "Que Deus ilumine seu caminho neste novo ano de vida.",
        "Parabéns 🎉 Que não falte fé, amor e esperança.",
        "Que Deus realize os desejos do seu coração.",
        "Mais um ano de vida abençoado por Deus.",
        "Que este novo ciclo seja de vitórias.",
        "Deus cuide de você hoje e sempre.",
        "Que seu dia seja cheio de alegria.",
        "Parabéns! Que Deus esteja sempre contigo.",
        "Feliz vida! Deus te abençoe."
    ]
}

# ================= TEXTO =================

FONT_PATH = "fonts/Pacifico-Regular.ttf"
FONT_SIZE = 70

def wrap_text(text, limit=25):
    palavras = text.split()
    linhas, atual = [], ""

    for p in palavras:
        if len(atual) + len(p) + 1 <= limit:
            atual = (atual + " " + p).strip()
        else:
            linhas.append(atual)
            atual = p

    if atual:
        linhas.append(atual)

    return linhas

def adicionar_texto(image, frase):
    w, h = image.size
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(FONT_PATH, FONT_SIZE)

    linhas = wrap_text(frase)
    altura = FONT_SIZE + 10
    y = h // 2 - (len(linhas) * altura) // 2

    for linha in linhas:
        largura = draw.textlength(linha, font=font)
        x = (w - largura) // 2

        for ox, oy in [(-2,-2),(2,2),(-2,2),(2,-2)]:
            draw.text((x+ox, y+oy), linha, font=font, fill=(0,0,0))

        draw.text((x, y), linha, font=font, fill=(255,255,255))
        y += altura

    return image

# ================= DOWNLOAD =================

def baixar_imagem(categoria, indice, frase):
    url = f"https://picsum.photos/1080/1080?random={random.randint(1,999999)}"

    try:
        response = requests.get(url, timeout=20)
        image = Image.open(BytesIO(response.content)).convert("RGB")
    except Exception:
        return None

    image = adicionar_texto(image, frase)

    pasta = os.path.join(BASE_DIR, categoria)
    os.makedirs(pasta, exist_ok=True)

    caminho = os.path.join(pasta, f"{categoria}_{indice}.jpg")
    image.save(caminho, "JPEG", quality=90)

    return caminho.replace("\\", "/")

# ================= GERAR =================

def gerar_imagens():
    print(">>>GERADOR INICIADO<<<")
    os.makedirs(BASE_DIR, exist_ok=True)

    index = {"generated_at": datetime.utcnow().isoformat() + "Z"}

    for categoria in CATEGORIAS:
        print("Gerando categoria:",categoria)
        index[categoria] = []
        frases = random.sample(MENSAGENS[categoria], IMAGENS_POR_CATEGORIA)

        i = 1
        while len(index[categoria]) < IMAGENS_POR_CATEGORIA:
            caminho = baixar_imagem(categoria, i, frases[len(index[categoria])])
            if caminho:
                index[categoria].append(
                    f"https://raw.githubusercontent.com/zflipks/imagens-automaticas/main/{caminho}"
                )
            i += 1

    with open("index.json", "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)

    print("index.json gerado com sucesso!")

if __name__ == "_main_":
    gerar_imagens()
