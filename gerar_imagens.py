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
    "bomdia":[
    "Bom dia ☀️ Que Deus abençoe cada passo seu hoje, ilumine suas decisões e encha seu coração de paz e esperança. 🙏",
    "Bom dia 🙏 Comece este dia confiando em Deus, Ele já preparou tudo o que você precisa. Tenha fé e siga em frente.",
    "Bom dia 🌤️ Que a presença de Deus te acompanhe hoje, trazendo calma, força e um coração cheio de gratidão.",
    "Bom dia ☀️ Entregue seus planos a Deus e confie que Ele fará o melhor. Hoje será um dia abençoado.",
    "Bom dia 🙏 Respire fundo, confie em Deus e lembre-se: você não caminha sozinho, Ele cuida de tudo.",
    "Bom dia 🌿 Que Deus renove suas forças hoje e te dê sabedoria para cada escolha.",
    "Bom dia ☀️ Acorde com fé no coração e esperança na alma. Deus está com você.",
    "Bom dia 🌤️ Mesmo que existam desafios, Deus já está à frente cuidando de cada detalhe.",
    "Bom dia 🙏 Que a paz de Deus invada seu coração e transforme este dia em um dia cheio de bênçãos.",
    "Bom dia ☀️ Confie seus sonhos a Deus e siga com coragem, Ele sabe exatamente o que faz.",
    "Bom dia 🙏 Que hoje não falte fé, nem esperança, nem a presença de Deus na sua vida.",
    "Bom dia 🌤️ Deus já está trabalhando por você, confie e descanse o coração.",
    "Bom dia ☀️ Que seu dia seja leve, abençoado e guiado pelas mãos de Deus.",
    "Bom dia 🙏 Comece o dia agradecendo, pois Deus te deu mais uma chance de recomeçar.",
    "Bom dia 🌿 Que Deus te dê força para vencer e paz para seguir em frente.",
    "Bom dia ☀️ Entregue suas preocupações a Deus e caminhe com o coração tranquilo.",
    "Bom dia 🙏 Que hoje você sinta o cuidado de Deus em cada pequeno detalhe.",
    "Bom dia 🌤️ Deus está no controle mesmo quando você não entende tudo.",
    "Bom dia ☀️ Que a fé te guie e a esperança te fortaleça hoje.",
    "Bom dia 🙏 Hoje Deus renova suas forças e te lembra que você é capaz.",
    "Bom dia ☀️ Caminhe com fé, pense positivo e confie em Deus.",
    "Bom dia 🌤️ Que a luz de Deus ilumine seu caminho hoje.",
    "Bom dia 🙏 Que não falte coragem, nem fé, nem a presença de Deus.",
    "Bom dia ☀️ Acredite, Deus já está cuidando de tudo o que te preocupa.",
    "Bom dia 🙏 Que a paz de Deus seja seu abrigo neste dia.",
    "Bom dia 🌤️ Mesmo nos dias difíceis, Deus permanece fiel.",
    "Bom dia ☀️ Que hoje você sinta o amor e o cuidado de Deus.",
    "Bom dia 🙏 Deus vai na sua frente abrindo caminhos.",
    "Bom dia 🌿 Que a fé seja maior que o medo.",
    "Bom dia ☀️ Hoje será um dia abençoado, Deus está com você."
    ],
    "boatarde":[
    "Boa tarde ☀️ Que Deus renove suas forças agora, acalme seu coração e te dê sabedoria para seguir até o fim do dia.",
    "Boa tarde 🙏 Mesmo que o dia esteja pesado, confie: Deus continua cuidando de tudo nos mínimos detalhes.",
    "Boa tarde 🌿 Que a paz de Deus invada sua mente, alivie suas preocupações e fortaleça sua fé.",
    "Boa tarde ☀️ Entregue o restante do seu dia nas mãos de Deus e confie que tudo vai se ajeitar.",
    "Boa tarde 🙏 Deus vê o que você sente, conhece suas lutas e não te abandona em nenhum momento.",
    "Boa tarde 🌼 Que Deus te dê calma onde há ansiedade e esperança onde há dúvida.",
    "Boa tarde ☀️ Mesmo cansado, continue. Deus está te sustentando mais do que você imagina.",
    "Boa tarde 🙏 Que a presença de Deus traga equilíbrio, paz e proteção para você agora.",
    "Boa tarde 🌿 Não desista no meio do caminho, Deus está trabalhando por você.",
    "Boa tarde ☀️ Que a fé seja maior que o cansaço e a esperança maior que o medo.",
    "Boa tarde 🙏 Deus está no controle, mesmo quando tudo parece confuso.",
    "Boa tarde 🌼 Que o amor de Deus te envolva e te dê forças para continuar.",
    "Boa tarde ☀️ Confie no tempo de Deus, Ele nunca chega atrasado.",
    "Boa tarde 🙏 Que Deus acalme seu coração e renove sua confiança.",
    "Boa tarde 🌿 Mesmo em silêncio, Deus está agindo na sua vida.",
    "Boa tarde ☀️ Que sua fé te sustente até o fim do dia.",
    "Boa tarde 🙏 Deus caminha ao seu lado, mesmo quando você não percebe.",
    "Boa tarde 🌼 Que a paz de Deus seja seu abrigo agora.",
    "Boa tarde ☀️ Não carregue tudo sozinho, entregue a Deus.",
    "Boa tarde 🙏 Que Deus te fortaleça por dentro.",
    "Boa tarde 🌿 Tudo acontece no tempo certo de Deus.",
    "Boa tarde ☀️ Confie, Deus sabe exatamente o que está fazendo.",
    "Boa tarde 🙏 Que a esperança renasça em seu coração.",
    "Boa tarde 🌼 Deus cuida de você com amor.",
    "Boa tarde ☀️ Que Deus ilumine seus pensamentos.",
    "Boa tarde 🙏 Mesmo cansado, siga com fé.",
    "Boa tarde 🌿 Deus não falha.",
    "Boa tarde ☀️ Que a paz permaneça com você.",
    "Boa tarde 🙏 Deus te sustenta.",
    "Boa tarde 🌼 Você não está sozinho, Deus está com você."
    ],
    "boanoite":[
    "Boa noite 🌙 Entregue tudo a Deus, acalme o coração e descanse sabendo que Ele cuida de você.",
    "Boa noite 🙏 Que Deus leve embora todo cansaço, toda preocupação e te conceda uma noite de paz.",
    "Boa noite 🌟 Descanse em Deus, amanhã Ele continuará cuidando de tudo.",
    "Boa noite 🌙 Que a presença de Deus traga silêncio à mente e paz à alma.",
    "Boa noite 🙏 Deus conhece suas lutas e renova suas forças enquanto você dorme.",
    "Boa noite 🌟 Que Deus proteja seu sono e seu lar.",
    "Boa noite 🌙 Entregue seus medos a Deus e descanse em paz.",
    "Boa noite 🙏 Que seu descanso seja leve e abençoado.",
    "Boa noite 🌟 Deus está no controle, pode descansar.",
    "Boa noite 🌙 Confie seus sonhos nas mãos de Deus.",
    "Boa noite 🙏 Que a fé acalme seu coração nesta noite.",
    "Boa noite 🌟 Mesmo em silêncio, Deus continua trabalhando.",
    "Boa noite 🌙 Descanse, Deus não dorme.",
    "Boa noite 🙏 Que a paz de Deus envolva você agora.",
    "Boa noite 🌟 Amanhã será um novo dia nas mãos de Deus.",
    "Boa noite 🌙 Que Deus renove suas forças durante o sono.",
    "Boa noite 🙏 Entregue tudo e descanse.",
    "Boa noite 🌟 Deus cuida de você com amor.",
    "Boa noite 🌙 Que sua noite seja tranquila.",
    "Boa noite 🙏 Confie, Deus é fiel.",
    "Boa noite 🌟 Que o descanso cure sua alma.",
    "Boa noite 🌙 Deus está presente.",
    "Boa noite 🙏 Acalme a mente e o coração.",
    "Boa noite 🌟 Que a paz reine em seu lar.",
    "Boa noite 🌙 Deus te guarda.",
    "Boa noite 🙏 Amanhã Deus fará novas coisas.",
    "Boa noite 🌟 Descanse com fé.",
    "Boa noite 🌙 Deus está cuidando de tudo.",
    "Boa noite 🙏 Você está nas mãos de Deus.",
    "Boa noite 🌟 Uma noite abençoada para você."
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
        print(f"Falha ao baixar imagem {categoria}_{indice}, pulando...")
        return None

    image = adicionar_texto(image, frase)

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

if __name__ == "__main__":
    gerar_imagens()
