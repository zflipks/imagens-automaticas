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
