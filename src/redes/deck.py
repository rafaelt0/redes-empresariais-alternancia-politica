"""Gera o PowerPoint, o PDF e o guia de fala a partir dos resultados agregados."""

import math
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from itertools import accumulate
from pathlib import Path

import polars as pl
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.presentation import Presentation as Apresentacao
from pptx.util import Inches, Pt

from redes.amostra import MARCADOR
from redes.config import Caminhos
from redes.etapas import Contexto, Etapa
from redes.leitura_sensibilidades import piso_gigante_h2
from redes.numeros import Numeros, decimal, leitura_h2_comparaveis, percentual
from redes.portabilidade import ferramenta

ETAPA = Etapa(
    nome="deck",
    depende=("estimate",),
    le=(),
    grava=(),
    artefatos=("saida/deck.pptx", "saida/deck.pdf", "saida/guia_de_fala.md"),
)

NUMERO_SLIDES = 8
LIMITE_SEGUNDOS = 10 * 60
LARGURA, ALTURA = 13.333, 7.5
MARGEM = 0.75
CORPO = LARGURA - 2 * MARGEM
MEIO = 6.93
INK = RGBColor.from_string("221F20")
ACCENT = RGBColor.from_string("862F3D")
CINZA = RGBColor.from_string("56504E")
PALIDO = RGBColor.from_string("F6F0EB")
LINHA = RGBColor.from_string("DFD5CE")
BRANCO = RGBColor.from_string("FFFFFF")
FONTE_TITULO = "Liberation Serif"
FONTE_CORPO = "Liberation Sans"
TITULO = "Redes empresariais e persistência econômica sob alternância política"
AUTORES = (
    "Felipe Ferreira Alexandre",
    "Andrei Schoschlakow Bonifácio",
    "Rafael Eiki Teruya",
    "João Pedro Ferreira",
)
NUSP = ("13963144", "14558482", "14604204", "14582312")
# Blocos de fala de igual duração. A definição de quem apresenta cada bloco fica para a reunião.
VOZES = ("Voz 1", "Voz 2", "Voz 3", "Voz 4")
TEMAS_VOZES = (
    "Economia política e hipóteses",
    "Desenho empírico e fontes",
    "Estrutura da rede e resultados de H1, H3 e H4",
    "Resultados de H2 e conclusão",
)
CONTEXTO = "I  /  ECONOMIA POLÍTICA"
HIPOTESES = "II  /  HIPÓTESES"
DESENHO = "III  /  DESENHO EMPÍRICO"
REDE = "IV  /  REDE SOCIETÁRIA"
RESULTADOS = "V  /  APLICAÇÃO E RESULTADOS"


@dataclass(frozen=True)
class Nota:
    pessoa: str
    segundos: int
    fala: str
    apoio: tuple[str, ...]

    def texto(self) -> str:
        linhas = [f"{self.pessoa} · {self.segundos} s", "", "Na fala", self.fala]
        if self.apoio:
            linhas.extend(("", "Se perguntarem", *self.apoio))
        return "\n".join(linhas)


def _nota(notas: list[Nota], pessoa: str, segundos: int, fala: str, *apoio: str) -> None:
    notas.append(Nota(pessoa, segundos, fala, apoio))


def _ler_tabela(pasta: Path, nome: str) -> pl.DataFrame | None:
    arquivo = pasta / f"{nome}.csv"
    return pl.read_csv(arquivo) if arquivo.is_file() else None


def _celula(tabela: pl.DataFrame | None, **filtros: object) -> dict:
    if tabela is None or not filtros.keys() <= set(tabela.columns):
        return {}
    recorte = tabela.filter(pl.col(coluna) == valor for coluna, valor in filtros.items())
    return recorte.row(0, named=True) if recorte.height else {}


def _numero(valor: float | None, casas: int = 3) -> str:
    return "n.d." if valor is None else decimal(valor, casas)


def _pp(valor: float | None, casas: int = 1) -> str:
    return "n.d." if valor is None else decimal(100 * valor, casas)


def _destaque(numeros: Numeros, apelido: str) -> str:
    try:
        return numeros[apelido]
    except KeyError:
        return "n.d."


def _intervalo(linha: dict, casas: int = 1) -> str:
    inferior, superior = linha.get("ic_inf"), linha.get("ic_sup")
    if inferior is None or superior is None:
        return "n.d."
    return f"{_pp(inferior, casas)} a {_pp(superior, casas)}"


def _efeito(linha: dict, casas: int = 1) -> str:
    if linha.get("estimativa") is None:
        return "n.d."
    return f"{_pp(linha['estimativa'], casas)} ({_intervalo(linha, casas)})"


def _estimativa_pp(linha: dict, casas: int = 1) -> str:
    valor = linha.get("estimativa")
    return f"{_pp(valor, casas)} p.p." if valor is not None else "n.d."


def _ic_pp(linha: dict, casas: int = 1) -> str:
    intervalo = _intervalo(linha, casas)
    return f"IC de 95% de {intervalo} p.p." if intervalo != "n.d." else "IC de 95% n.d."


def _status(linha: dict) -> str:
    inferior, superior = linha.get("ic_inf"), linha.get("ic_sup")
    if inferior is None or superior is None:
        return "sem estimativa"
    if inferior > 0:
        return "positivo"
    if superior < 0:
        return "negativo"
    return "inclui zero"


def _texto(
    slide,
    texto: str,
    x: float,
    y: float,
    largura: float,
    altura: float,
    *,
    tamanho: int = 22,
    cor: RGBColor = INK,
    fonte: str = FONTE_CORPO,
    forte: bool = False,
    alinhar: PP_ALIGN = PP_ALIGN.LEFT,
):
    caixa = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(largura), Inches(altura))
    tf = caixa.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = Pt(0)
    p = tf.paragraphs[0]
    p.text = texto
    p.font.name, p.font.size, p.font.bold = fonte, Pt(tamanho), forte
    p.font.color.rgb = cor
    p.alignment, p.line_spacing = alinhar, 1.06
    return caixa


def _traco(slide, x1, y1, x2, y2, cor=LINHA, peso=0.9) -> None:
    traco = slide.shapes.add_connector(
        MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1), Inches(x2), Inches(y2)
    )
    estilo = traco._element.find(qn("p:style"))
    if estilo is not None:
        traco._element.remove(estilo)
    traco.line.color.rgb, traco.line.width = cor, Pt(peso)


def _pagina(prs, titulo: str, secao: str, fonte: str = "", *, fundo: RGBColor = BRANCO):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = fundo
    _texto(slide, titulo, MARGEM, 0.83, CORPO, 1.13, tamanho=35, fonte=FONTE_TITULO, forte=True)
    _texto(slide, secao, MARGEM, 0.46, CORPO, 0.25, tamanho=13, cor=ACCENT, forte=True)
    if fonte:
        _texto(slide, fonte, MARGEM, 7.01, CORPO - 0.65, 0.25, tamanho=12, cor=CINZA)
    _texto(
        slide,
        str(len(prs.slides)),
        LARGURA - MARGEM - 0.35,
        7.01,
        0.35,
        0.25,
        tamanho=12,
        cor=CINZA,
        alinhar=PP_ALIGN.RIGHT,
    )
    return slide


def _bloco(slide, titulo: str, texto: str, x: float, y: float, largura: float) -> None:
    _texto(slide, titulo, x, y, largura, 0.34, tamanho=17, cor=ACCENT, forte=True)
    _texto(slide, texto, x, y + 0.40, largura, 1.24, tamanho=21)


def _barra_proporcao(
    slide, rotulo: str, valor: str, proporcao: float | None, x: float, y: float, largura: float
) -> None:
    _texto(slide, rotulo, x, y, largura - 0.85, 0.31, tamanho=15)
    _texto(
        slide,
        valor,
        x + largura - 0.77,
        y,
        0.77,
        0.31,
        tamanho=16,
        cor=ACCENT,
        forte=True,
        alinhar=PP_ALIGN.RIGHT,
    )
    base = y + 0.40
    _traco(slide, x, base, x + largura, base, LINHA, 5)
    if proporcao is not None and proporcao > 0:
        _traco(slide, x, base, x + largura * proporcao, base, ACCENT, 5)


def _tabela(
    slide,
    cabecalho: list[str],
    linhas: list[list[str]],
    x: float,
    y: float,
    larguras: tuple[float, ...],
    altura_linha: float,
    tamanho: int = 17,
) -> None:
    forma = slide.shapes.add_table(
        len(linhas) + 1,
        len(cabecalho),
        Inches(x),
        Inches(y),
        Inches(sum(larguras)),
        Inches(altura_linha * (len(linhas) + 1)),
    )
    tabela = forma.table
    tabela.first_row = tabela.horz_banding = False
    for coluna, largura in zip(tabela.columns, larguras, strict=True):
        coluna.width = Inches(largura)
    for i, linha in enumerate([cabecalho, *linhas]):
        tabela.rows[i].height = Inches(altura_linha)
        for j, texto in enumerate(linha):
            celula = tabela.cell(i, j)
            celula.text = texto
            celula.margin_left = celula.margin_right = Inches(0.10)
            celula.margin_top = celula.margin_bottom = Pt(0)
            celula.vertical_anchor = MSO_ANCHOR.MIDDLE
            celula.fill.solid()
            celula.fill.fore_color.rgb = ACCENT if i == 0 else (PALIDO if i % 2 else BRANCO)
            for p in celula.text_frame.paragraphs:
                p.font.name, p.font.size, p.font.bold = FONTE_CORPO, Pt(tamanho), i == 0 or j == 0
                p.font.color.rgb = BRANCO if i == 0 else INK
                p.alignment = PP_ALIGN.LEFT if j == 0 else PP_ALIGN.CENTER


def _grafico_distancia(slide, linhas: list[tuple[str, dict]]) -> None:
    """Pontos e barras de IC editáveis, com a mesma escala em todas as distâncias."""
    valores = [0.0]
    for _, linha in linhas:
        valores.extend(
            100 * linha[chave]
            for chave in ("estimativa", "ic_inf", "ic_sup")
            if linha.get(chave) is not None
        )
    ordem = 10 ** math.floor(math.log10(max((max(valores) - min(valores)) / 5, 1)))
    passo = next(
        ordem * multiplicador
        for multiplicador in (1, 2, 5, 10)
        if ordem * multiplicador >= (max(valores) - min(valores)) / 5
    )
    inferior = min(0, math.floor(min(valores) / passo))
    superior = max(1, math.ceil(max(valores) / passo))

    def posicao(valor: float) -> float:
        return 1.94 + 5.08 * (valor / passo - inferior) / (superior - inferior)

    _texto(
        slide,
        "Contraste em p.p. e IC nominal de 95%",
        MARGEM,
        2.25,
        6.4,
        0.33,
        tamanho=17,
        forte=True,
    )
    for marca in range(inferior, superior + 1):
        x = posicao(marca * passo)
        _traco(slide, x, 2.77, x, 5.60, CINZA if marca == 0 else LINHA)
        _texto(
            slide,
            _numero(marca * passo, 0),
            x - 0.40,
            5.71,
            0.80,
            0.33,
            tamanho=15,
            cor=CINZA,
            alinhar=PP_ALIGN.CENTER,
        )
    for i, (rotulo, linha) in enumerate(linhas):
        y = 3.02 + i * 0.76
        cor = ACCENT if rotulo == "1 passo" else INK
        _texto(slide, rotulo, MARGEM, y - 0.14, 1.19, 0.38, tamanho=16, cor=cor, forte=True)
        if _status(linha) == "sem estimativa" or linha.get("estimativa") is None:
            _texto(slide, "n.d.", 2.06, y - 0.13, 0.65, 0.28, tamanho=15, cor=CINZA)
            continue
        a, b = (posicao(100 * linha[k]) for k in ("ic_inf", "ic_sup"))
        x = posicao(100 * linha["estimativa"])
        _traco(slide, a, y, b, y, cor, 2.05)
        for ponta in (a, b):
            _traco(slide, ponta, y - 0.075, ponta, y + 0.075, cor, 1.4)
        ponto = slide.shapes.add_shape(
            MSO_SHAPE.OVAL, Inches(x - 0.058), Inches(y - 0.058), Inches(0.116), Inches(0.116)
        )
        ponto.fill.solid()
        ponto.fill.fore_color.rgb = cor
        ponto.line.fill.background()


def _estatistica_rede(tabela: pl.DataFrame | None, indicador: str) -> float | None:
    return _celula(tabela, variante="PRINCIPAL", indicador=indicador).get("valor")


def construir(caminhos: Caminhos, numeros: Numeros) -> tuple[Apresentacao, list[Nota]]:
    pasta = caminhos.resultados / "tables"
    resumo = _ler_tabela(pasta, "resumo_estimacao")
    pre_periodos = _ler_tabela(pasta, "sensibilidade_pre_periodos")
    comparaveis = _ler_tabela(pasta, "h2_comparaveis")
    perfil = _ler_tabela(pasta, "rede_resumo")
    graus = _ler_tabela(pasta, "rede_graus")
    componentes = _ler_tabela(pasta, "rede_componentes")
    figuras = caminhos.resultados / "figures"
    exemplo = figuras / "figura1_exemplo.png"
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(LARGURA), Inches(ALTURA)
    notas: list[Nota] = []

    # 1. Capa
    curso = "FEA-USP  /  EAE1429  /  REDES ECONÔMICAS E SOCIAIS"
    if (caminhos.dados / MARCADOR).is_file():
        curso += "  /  AMOSTRA SINTÉTICA"
    slide = _pagina(prs, TITULO, curso, fundo=PALIDO)
    _texto(
        slide,
        "Eleições municipais paulistas de 2024 e empenhos de 2025",
        MARGEM,
        2.15,
        CORPO,
        0.38,
        tamanho=19,
        cor=CINZA,
    )
    _traco(slide, MARGEM, 4.80, LARGURA - MARGEM, 4.80)
    for i, (nome, nusp) in enumerate(zip(AUTORES, NUSP, strict=True)):
        x, y = (MARGEM if i % 2 == 0 else MEIO), 5.08 + 0.40 * (i // 2)
        _texto(slide, f"{nome}  ·  {nusp}", x, y, 5.6, 0.34, tamanho=15)
    _nota(
        notas,
        "Voz 1",
        10,
        "Estudamos as eleições municipais paulistas de 2024 e os empenhos de 2025 "
        "para saber se a troca de governo muda quais redes empresariais recebem recursos.",
    )

    # 2. Economia política
    slide = _pagina(
        prs,
        "Como o poder persiste após a alternância?",
        CONTEXTO,
        "Acemoglu, Johnson e Robinson (2005) e Acemoglu e Robinson (2008).",
    )
    _texto(
        slide,
        "Na abordagem do conflito social, grupos disputam as regras que definem "
        "quem recebe os recursos.",
        MARGEM,
        1.66,
        11.4,
        0.82,
        tamanho=22,
    )
    _bloco(
        slide,
        "Poder formal (de jure)",
        "As instituições políticas definem quem tem autoridade para decidir.",
        MARGEM,
        2.66,
        5.42,
    )
    _traco(slide, 6.55, 2.64, 6.55, 3.78)
    _bloco(
        slide,
        "Poder de fato (de facto)",
        "Recursos econômicos ampliam a capacidade de organização e influência.",
        MEIO,
        2.66,
        5.42,
    )
    _traco(slide, MARGEM, 4.05, LARGURA - MARGEM, 4.05)
    _texto(
        slide,
        "Poder político  →  Instituições econômicas  →  Distribuição de recursos"
        "  →  Poder de fato futuro",
        MARGEM,
        4.35,
        CORPO,
        0.44,
        tamanho=18,
        cor=ACCENT,
        forte=True,
    )
    _texto(
        slide,
        "Os grupos beneficiados ganham meios para preservar as regras que os favorecem.",
        MARGEM,
        4.87,
        CORPO,
        0.39,
        tamanho=19,
    )
    _bloco(
        slide,
        "Aplicação aos empenhos municipais",
        "Após uma troca de governo, os empenhos podem passar para outras fornecedoras "
        "das mesmas redes societárias.",
        MARGEM,
        5.59,
        11.45,
    )
    _nota(
        notas,
        "Voz 1",
        55,
        "Para Acemoglu e coautores, grupos disputam as regras que distribuem os recursos. "
        "As instituições políticas conferem autoridade formal. Os recursos econômicos "
        "dão poder de fato ao ampliar a capacidade de organização. As duas fontes de "
        "poder moldam as regras da economia. Os grupos que se beneficiam dessas regras "
        "ganham recursos para preservar sua influência no período seguinte. Uma eleição "
        "pode mudar quem comanda a prefeitura e preservar os recursos que sustentam "
        "essa influência. Nos empenhos, isso poderia aparecer se uma fornecedora "
        "perdesse espaço e outras empresas da mesma rede ganhassem participação.",
        "No esquema completo, o poder político também influencia as instituições "
        "políticas do período seguinte.",
        "Empenhos são compromissos de despesa. Usamos vínculos societários e doações "
        "observáveis para investigar a persistência das redes fornecedoras.",
    )

    # 3. Hipóteses com o diagrama de exemplo
    slide = _pagina(
        prs,
        "Quatro hipóteses a partir dos vínculos de campanha",
        HIPOTESES,
        "Diagrama ilustrativo do relatório.",
    )
    if exemplo.is_file():
        figura = slide.shapes.add_picture(
            str(exemplo), Inches(6.03), Inches(2.02), width=Inches(6.54)
        )
        figura._element.nvPicPr.cNvPr.set(
            "descr",
            "X liga-se a A por Ana e a Y por Bruno. Y liga-se a Z por Carla. "
            "Z liga-se a B por Daniel. Y está a um passo de A e de B.",
        )
    for i, (rotulo, previsao) in enumerate(
        (
            ("H1", "Se A perde, X perde espaço ante as empresas sem caminho a A ou B."),
            ("H2", "Se B vence, a vantagem cai de Z (0) para Y (1) e X (2 passos)."),
            ("H3", "Na rede ligada a A e B, ganhos de Y e Z podem compensar a perda de X."),
            ("H4", "Redes ligadas ao vencedor tendem a seguir entre as maiores fornecedoras."),
        )
    ):
        y = 1.92 + i * 1.11
        _texto(slide, rotulo, MARGEM, y, 0.60, 0.36, tamanho=19, cor=ACCENT, forte=True)
        _texto(slide, previsao, 1.42, y, 4.37, 0.96, tamanho=19, forte=rotulo == "H2")
    _texto(
        slide,
        "A é o incumbente. B é o adversário mais votado. Cada passo une duas "
        "empresas com sócio ou administrador em comum.",
        6.03,
        5.96,
        6.54,
        0.65,
        tamanho=17,
        cor=CINZA,
    )
    _nota(
        notas,
        "Voz 1",
        65,
        "No diagrama, as setas tracejadas são doações. Ana liga a empresa X ao grupo "
        "incumbente A. Daniel liga Z ao adversário B. Essas empresas são as sementes. "
        "As linhas contínuas mostram os vínculos societários. Bruno conecta X a Y, e "
        "Carla conecta Y a Z. Se B vencer, H2 prevê a maior vantagem para Z, que está "
        "diretamente ligada a B. Y está a um passo e X a dois, então a vantagem deveria "
        "diminuir nessa ordem. H1 pergunta se X perde participação diante de empresas "
        "sem caminho aos dois grupos. Como a rede liga A e B, H3 pergunta se ganhos de "
        "Y e Z compensam a perda de X. H4 pergunta se redes ligadas ao vencedor "
        "permanecem entre as maiores fornecedoras.",
        "No teste de H2, comparamos coortes à mesma distância de A e B em vários "
        "municípios. As empresas do desenho ilustram a contagem de passos.",
    )

    # 4. Desenho empírico
    slide = _pagina(
        prs,
        "O efeito da derrota perto do empate",
        DESENHO,
        "Calonico, Cattaneo e Titiunik (2014) e Cattaneo, Jansson e Ma (2020).",
    )
    _texto(
        slide,
        "Margem M = % de votos válidos de A − % de votos válidos de B (em p.p.)",
        MARGEM,
        1.81,
        CORPO,
        0.38,
        tamanho=18,
        cor=CINZA,
    )
    _texto(slide, "A perde", MARGEM, 2.42, 5.15, 0.52, tamanho=28, fonte=FONTE_TITULO)
    _texto(
        slide,
        "0",
        6.29,
        2.34,
        0.76,
        0.58,
        tamanho=34,
        cor=ACCENT,
        forte=True,
        alinhar=PP_ALIGN.CENTER,
    )
    _texto(
        slide,
        "A vence",
        7.44,
        2.42,
        5.14,
        0.52,
        tamanho=28,
        fonte=FONTE_TITULO,
        alinhar=PP_ALIGN.RIGHT,
    )
    _traco(slide, MARGEM, 3.06, LARGURA - MARGEM, 3.06, LINHA, 1.6)
    _traco(slide, LARGURA / 2, 2.94, LARGURA / 2, 3.19, ACCENT, 2.3)
    _texto(
        slide,
        "Regressão descontínua no empate",
        MARGEM,
        3.45,
        CORPO,
        0.51,
        tamanho=29,
        fonte=FONTE_TITULO,
        cor=ACCENT,
    )
    _texto(
        slide,
        "Y = α + βT + γM + θ(T × M) + u,     |M| ≤ b",
        MARGEM,
        4.03,
        CORPO,
        0.51,
        tamanho=28,
        fonte=FONTE_TITULO,
    )
    _texto(
        slide,
        "T = 1 quando A perde. β é o salto no empate. b delimita a janela de estimação.",
        MARGEM,
        4.62,
        CORPO,
        0.38,
        tamanho=18,
        cor=CINZA,
    )
    _texto(
        slide,
        "O desfecho é a fatia dos empenhos de 2025 no elemento de despesa do município. "
        "As coortes são definidas antes da eleição pela distância a A e B.",
        MARGEM,
        5.22,
        11.4,
        0.87,
        tamanho=22,
    )
    _texto(
        slide,
        f"{_destaque(numeros, 'munAnalisaveis')} municípios analisáveis. Estimação linear local "
        "e testes placebo com dados pré-eleitorais.",
        MARGEM,
        6.37,
        CORPO,
        0.42,
        tamanho=19,
        cor=CINZA,
    )
    densidade_margem = (
        resumo.row(0, named=True).get("densidade_p_valor")
        if resumo is not None and resumo.height
        else None
    )
    _nota(
        notas,
        "Voz 2",
        130,
        "Subtraímos a porcentagem de votos de B da de A. À esquerda do empate, A perde "
        "e B assume. À direita, A vence. Comparamos municípios dos dois lados, perto de "
        "zero. Para cada grupo de empresas, ajustamos uma reta de cada lado e medimos o "
        "salto na fatia dos empenhos de 2025. O salto estima o efeito local da derrota "
        "se os resultados potenciais variarem continuamente ao redor do empate. Para H2, "
        "definimos os grupos pela distância às candidaturas usando os vínculos e as doações "
        "anteriores à eleição. Também aplicamos a comparação a dados anteriores à eleição "
        "como teste placebo. A Receita Federal fornece o quadro societário. Cada aresta liga "
        "uma empresa a um sócio ou administrador, que pode ser pessoa física ou jurídica. "
        "Usamos os votos do TSE para calcular a margem eleitoral e cruzamos o cadastro com as "
        "doações individuais, incluindo recursos próprios dos candidatos, para identificar "
        "as empresas-semente. Por fim, cruzamos os CNPJs com os empenhos do Tribunal de Contas. "
        "Os empenhos anteriores à eleição identificam quem já fornecia e os de 2025 mostram "
        "a fatia de cada grupo.",
        "A especificação é Y = α + βT + γM + θ(T × M) + u. β é o salto no empate "
        "e T indica derrota de A.",
        "A é o prefeito candidato ou, na ausência dele, representante de seu partido ou "
        "coligação. Excluímos a capital, os municípios com segundo turno e aqueles sem A "
        "identificável ou sem adversário. O suporte na banda varia por coorte.",
        "Usamos núcleo triangular, banda escolhida pelo erro quadrático médio estimado e "
        "correção de viés. Os contrastes reamostram municípios de cada lado em conjunto, "
        "com bandas fixas.",
        f"O teste de densidade da margem deu p = {_numero(densidade_margem)}. "
        "Também verificamos placebos e sensibilidade à metade e ao dobro da banda.",
        "Fornecedora anterior tem saldo líquido positivo na janela pré-eleitoral. "
        "O desfecho de H1 e H2 inclui os saldos positivos das entrantes no denominador.",
    )

    # 5. Fontes e estrutura da rede
    slide = _pagina(prs, "Poucos vínculos por empresa", REDE)
    faixa = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(MARGEM), Inches(1.68), Inches(CORPO), Inches(1.03)
    )
    estilo = faixa._element.find(qn("p:style"))
    if estilo is not None:
        faixa._element.remove(estilo)
    faixa.fill.solid()
    faixa.fill.fore_color.rgb = PALIDO
    faixa.line.fill.background()
    largura_indicador = CORPO / 4
    for i, (apelido, rotulo) in enumerate(
        (
            ("empresasRede", "Empresas"),
            ("pessoasRede", "Sócios e administradores (PF e PJ)"),
            ("vinculosRede", "Vínculos societários"),
            ("componentesRede", "Componentes"),
        )
    ):
        x = MARGEM + i * largura_indicador
        _texto(
            slide,
            _destaque(numeros, apelido),
            x,
            1.80,
            largura_indicador,
            0.50,
            tamanho=31,
            fonte=FONTE_TITULO,
            forte=True,
            alinhar=PP_ALIGN.CENTER,
        )
        _texto(
            slide,
            rotulo,
            x,
            2.32,
            largura_indicador,
            0.29,
            tamanho=13,
            cor=CINZA,
            alinhar=PP_ALIGN.CENTER,
        )
        if i:
            _traco(slide, x, 1.88, x, 2.51)

    empresas = _estatistica_rede(perfil, "empresas")
    pessoas = _estatistica_rede(perfil, "pessoas")
    vinculos = _estatistica_rede(perfil, "vinculos")
    grau_medio = vinculos / empresas if empresas and vinculos is not None else None
    grau_medio_pessoa = vinculos / pessoas if pessoas and vinculos is not None else None
    por_milhao = grau_medio * 1_000_000 / pessoas if pessoas and grau_medio is not None else None
    contagem_1_2 = [
        _celula(graus, variante="PRINCIPAL", vertice="empresa", faixa_grau=faixa).get("vertices")
        for faixa in ("1", "2")
    ]
    grau_baixo = (
        sum(contagem_1_2) / empresas
        if empresas and all(n is not None for n in contagem_1_2)
        else None
    )
    assortatividade = _estatistica_rede(perfil, "assortatividade_grau")
    isoladas = _celula(componentes, variante="PRINCIPAL", faixa_tamanho="1").get("empresas")
    fracao_isoladas = isoladas / empresas if empresas and isoladas is not None else None
    maior = numeros.valor("rede_resumo", ("PRINCIPAL", "fracao_no_maior_componente"), "valor")
    maior_sem_art = numeros.valor(
        "rede_resumo", ("SEM_ARTICULACAO", "fracao_no_maior_componente"), "valor"
    )
    municipios = numeros.valor("links_pc1", ("municipios_analisaveis", ""), "valor")
    mun_a = _estatistica_rede(perfil, "municipios_com_conexao_a")
    mun_b = _estatistica_rede(perfil, "municipios_com_conexao_b")
    largura_painel = (CORPO - 1.0) / 3
    paineis = (
        (
            "Perfil das empresas",
            (
                (
                    "1 ou 2 vínculos",
                    percentual(grau_baixo) if grau_baixo is not None else "n.d.",
                    grau_baixo,
                ),
                (
                    "Sem vizinha societária",
                    percentual(fracao_isoladas) if fracao_isoladas is not None else "n.d.",
                    fracao_isoladas,
                ),
            ),
            "",
        ),
        (
            "Empresas no maior componente",
            (
                ("Rede principal", _destaque(numeros, "fracGigante"), maior),
                (
                    "Sem pontos de articulação",
                    _destaque(numeros, "fracGiganteSemArt"),
                    maior_sem_art,
                ),
            ),
            "Sem os sócios e administradores que, ao sair, separam partes da rede.",
        ),
        (
            "Conexão eleitoral",
            (
                (
                    "Com semente de A",
                    _destaque(numeros, "munConexaoA"),
                    mun_a / municipios if municipios and mun_a is not None else None,
                ),
                (
                    "Com semente de B",
                    _destaque(numeros, "munConexaoB"),
                    mun_b / municipios if municipios and mun_b is not None else None,
                ),
            ),
            f"De {_destaque(numeros, 'munAnalisaveis')} municípios analisáveis.",
        ),
    )
    for i, (titulo, barras, detalhe) in enumerate(paineis):
        x = MARGEM + i * (largura_painel + 0.50)
        if i:
            _traco(slide, x - 0.25, 2.99, x - 0.25, 5.15)
        _texto(slide, titulo, x, 2.99, largura_painel, 0.40, tamanho=16, forte=True)
        for j, (rotulo, valor, proporcao) in enumerate(barras):
            _barra_proporcao(slide, rotulo, valor, proporcao, x, 3.55 + j * 0.66, largura_painel)
        if detalhe:
            _texto(slide, detalhe, x, 4.79, largura_painel, 0.49, tamanho=13, cor=CINZA)

    _texto(
        slide,
        f"Densidade bipartida  ·  {_numero(por_milhao)} vínculo por milhão de pares possíveis",
        MARGEM,
        5.39,
        7.75,
        0.33,
        tamanho=14,
        cor=CINZA,
    )
    _texto(
        slide,
        f"Assortatividade de grau  ·  r = {_numero(assortatividade, 4)}",
        8.75,
        5.39,
        3.8,
        0.33,
        tamanho=14,
        cor=CINZA,
        alinhar=PP_ALIGN.RIGHT,
    )
    _traco(slide, MARGEM, 5.82, LARGURA - MARGEM, 5.82)
    for i, (titulo, corpo) in enumerate(
        (
            ("Receita Federal · Quadro societário", "Set/2024, com complemento de out/2024."),
            (
                "TSE · Eleições e doações",
                "Votos de 2024 e doações de pessoas físicas até 5/10/2024.",
            ),
            (
                "TCESP · Empenhos municipais",
                "Jan/2021–set/2024 para identificar fornecedoras anteriores. "
                "Empenhos de 2025 no desfecho.",
            ),
        )
    ):
        x = MARGEM + i * (largura_painel + 0.50)
        _texto(slide, titulo, x, 6.00, largura_painel, 0.27, tamanho=13, cor=ACCENT, forte=True)
        _texto(slide, corpo, x, 6.31, largura_painel, 0.66, tamanho=13, cor=CINZA)
    _nota(
        notas,
        "Voz 3",
        95,
        "A partir das fontes listadas na base do slide, construímos a rede principal com "
        f"{_destaque(numeros, 'empresasRede')} empresas, "
        f"{_destaque(numeros, 'pessoasRede')} vértices de sócios/administradores PF/PJ e "
        f"{_destaque(numeros, 'vinculosRede')} vínculos. A maioria das empresas tem "
        f"um ou dois vínculos. O grau médio é de {_numero(grau_medio, 2)} para empresas e "
        f"{_numero(grau_medio_pessoa, 2)} para sócios ou administradores. "
        "Um componente é um conjunto de empresas ligadas por caminhos societários. "
        "Muitas empresas estão sozinhas, mas o maior componente reúne "
        f"{_destaque(numeros, 'fracGigante')} delas. No diagrama das hipóteses, retirar "
        "Bruno separaria X de Y e Z. Quando retiramos os sócios ou administradores que "
        f"funcionam assim, o maior componente cai para {_destaque(numeros, 'fracGiganteSemArt')}. "
        "Na conexão eleitoral, contamos os municípios com ao menos uma empresa-semente de A "
        "ou de B. "
        "A rede tem poucos vínculos em relação ao número de pares possíveis. A assortatividade "
        "próxima de zero indica pouca associação linear entre os graus nas pontas dos vínculos.",
        "O complemento de 12/10/2024 só usa vínculos iniciados até 13/09/2024 "
        "em empresas do cadastro de setembro sem quadro válido naquela fotografia. "
        "Vínculos encerrados até outubro podem faltar.",
        f"Ligamos a empresas {_destaque(numeros, 'taxaCruzamentoA')} dos doadores de A "
        f"e {_destaque(numeros, 'taxaCruzamentoB')} dos de B.",
        "A assortatividade é a correlação de Pearson entre os graus da empresa e do "
        "sócio ou administrador em cada aresta. A densidade divide o número de arestas "
        "pelo produto das duas contagens de vértices.",
        "Na versão sem pontos de articulação, o universo de empresas é mantido e os "
        "caminhos societários mudam.",
    )

    # 6. Resultados de H1, H3 e H4
    h1 = _celula(resumo, hipotese="H1", tipo="contraste")
    total_h3 = _celula(resumo, hipotese="H3", tipo="contraste", resultado="variacao_total")
    r1 = _celula(resumo, hipotese="H3", tipo="categoria", categoria="ambos", resultado="termo_r1")
    r23 = _celula(
        resumo, hipotese="H3", tipo="categoria", categoria="ambos", resultado="termo_compensacao"
    )
    leitura_h3 = "O teste compara os sinais dos dois termos nas redes ligadas a A e B."
    if (r1.get("estimativa") or 0) > 0 > (r23.get("estimativa") or 0):
        leitura_h3 = "Os dois sinais contrariam a previsão de compensação na mesma rede."
    h4 = _celula(resumo, hipotese="H4", tipo="contraste", categoria="ligada_ao_vencedor_50")
    slide = _pagina(
        prs,
        "Ligação direta, compensação e permanência",
        RESULTADOS,
        "ICs de 95% dos contrastes por reamostragem municipal. "
        "H3 em % do empenho anual médio pré-eleitoral.",
    )
    for y, titulo, valor, detalhe, leitura in (
        (
            1.89,
            "H1  ·  Ligação direta",
            _estimativa_pp(h1),
            _ic_pp(h1),
            "Fatia dos empenhos de sementes de A ante firmas sem caminho a A ou B.",
        ),
        (
            3.42,
            "H3  ·  Compensação",
            f"{_pp(r1.get('estimativa'), 2)}% e {_pp(r23.get('estimativa'), 2)}%",
            "Ligadas diretamente a A e demais da rede",
            leitura_h3,
        ),
        (
            4.95,
            "H4  ·  Permanência",
            _estimativa_pp(h4),
            _ic_pp(h4),
            "Permanência entre as redes que somam 50% do empenho. Análise exploratória.",
        ),
    ):
        _texto(slide, titulo, MARGEM, y + 0.06, 3.28, 0.48, tamanho=19, cor=ACCENT, forte=True)
        _texto(slide, valor, 4.17, y, 3.76, 0.43, tamanho=24, fonte=FONTE_TITULO, forte=True)
        _texto(slide, detalhe, 4.17, y + 0.48, 3.83, 0.56, tamanho=15, cor=CINZA)
        _texto(slide, leitura, 8.26, y + 0.07, 4.31, 0.91, tamanho=17)
        _traco(slide, MARGEM, y + 1.23, LARGURA - MARGEM, y + 1.23)
    if all(_status(linha) == "inclui zero" for linha in (h1, r1, r23, h4)):
        _texto(
            slide,
            "Os intervalos de confiança incluem zero em H1, H3 e H4.",
            MARGEM,
            6.41,
            CORPO,
            0.40,
            tamanho=19,
            forte=True,
        )
    _nota(
        notas,
        "Voz 3",
        35,
        "Em H1, comparamos a participação das empresas ligadas diretamente ao incumbente "
        f"com a das empresas sem caminho a A ou B. Em H3, olhamos a compensação. {leitura_h3} "
        "Em H4, olhamos a permanência das redes entre as maiores. "
        "Os intervalos mostram a precisão dessas estimativas. A seguir, H2 examina "
        "a participação dos fornecedores em cada distância.",
        "Em H3, as unidades estão em % do empenho anual médio pré-eleitoral do município. "
        f"ICs de 95% de {_intervalo(r1, 2)}% para as anteriores ligadas diretamente a A e "
        f"de {_intervalo(r23, 2)}% para as demais. O contraste do total, redes ligadas a ambos "
        f"menos as demais, é {_efeito(total_h3, 2)}% do empenho prévio.",
        "Em H4, o ranking inclui a rede que cruza o limiar de 50%. Na janela de cinco p.p., "
        f"a permanência média descritiva é {_destaque(numeros, 'permanenciaComLigacao')} entre "
        f"as ligadas ao vencedor e {_destaque(numeros, 'permanenciaSemLigacao')} entre as demais. "
        f"O contraste usa ligações exclusivas e tem p de Holm = {_numero(h4.get('p_holm'))}.",
    )

    # 7. Contrastes por distância
    h2 = {
        faixa: _celula(resumo, hipotese="H2", tipo="contraste", categoria=f"vencedor_faixa_{faixa}")
        for faixa in ("0", "1", "2", "3+")
    }
    pre_b = _celula(pre_periodos, tipo="categoria", categoria="faixa_b_1")
    b1 = _celula(
        resumo,
        hipotese="H2",
        tipo="categoria",
        categoria="faixa_b_1",
        resultado="participacao_2025",
    )
    h2_titulo = (
        "A um passo, o contraste de 2025 é negativo"
        if _status(h2["1"]) == "negativo"
        else "A participação de 2025 por distância"
    )
    destaque_h2 = "H2 prevê uma vantagem positiva, decrescente com a distância."
    if _status(h2["1"]) == "negativo" and all(
        _status(h2[faixa]) == "inclui zero" for faixa in ("0", "2", "3+")
    ):
        destaque_h2 = "O IC nominal exclui zero a um passo. O sinal é contrário ao previsto."
    slide = _pagina(
        prs,
        h2_titulo,
        f"{RESULTADOS}  /  H2",
        "ICs por reamostragem municipal. A é o incumbente e B, o adversário.",
    )
    _texto(
        slide,
        "Para cada distância, o contraste é (salto de B − salto de A) ÷ 2.",
        MARGEM,
        1.74,
        CORPO,
        0.43,
        tamanho=20,
    )
    _grafico_distancia(
        slide, list(zip(("Direta", "1 passo", "2 passos", "3+ passos"), h2.values(), strict=True))
    )
    _texto(
        slide,
        destaque_h2,
        MARGEM,
        6.13,
        6.32,
        0.62,
        tamanho=17,
        cor=CINZA,
    )
    _traco(slide, 7.43, 2.25, 7.43, 6.22)
    _texto(slide, "Contraste a um passo em 2025", 7.81, 2.26, 4.76, 0.35, tamanho=17, forte=True)
    _texto(
        slide,
        _pp(h2["1"].get("estimativa"), 2)
        + (" p.p." if h2["1"].get("estimativa") is not None else ""),
        7.81,
        2.66,
        4.76,
        0.75,
        tamanho=41,
        fonte=FONTE_TITULO,
        cor=ACCENT,
    )
    _texto(
        slide,
        _ic_pp(h2["1"], 2),
        7.81,
        3.49,
        4.76,
        0.37,
        tamanho=17,
    )
    _texto(
        slide,
        "Placebo de mudança pré-eleitoral na coorte B a um passo",
        7.81,
        4.15,
        4.76,
        0.70,
        tamanho=18,
        forte=True,
    )
    pre_txt = (
        f"{_pp(pre_b['estimativa'], 2)} p.p. (IC nominal de {_intervalo(pre_b, 2)} p.p.)."
        if pre_b.get("estimativa") is not None
        else "Diagnóstico indisponível."
    )
    if _status(pre_b) == _status(b1) == "negativo":
        pre_txt += " A diferença anterior à eleição enfraquece a leitura causal de 2025."
    _texto(slide, pre_txt, 7.81, 4.97, 4.76, 1.48, tamanho=19, cor=CINZA)
    _nota(
        notas,
        "Voz 4",
        75,
        "A cada distância, calculamos o salto para as empresas ligadas ao adversário B "
        "e para as ligadas ao incumbente A. Subtraímos o salto de A do de B e dividimos por "
        "dois para expressar a vantagem da ligação ao vencedor, sob simetria dos efeitos. "
        f"A um passo, o contraste de 2025 é {_estimativa_pp(h2['1'], 2)} "
        f"({_ic_pp(h2['1'], 2)}). {destaque_h2} "
        "O placebo examina a mudança de participação das empresas a um passo de B "
        f"antes da eleição. O salto estimado foi de {pre_txt}",
        "A previsão era uma vantagem positiva da ligação ao vencedor que diminuísse com a "
        "distância. A interpretação exige coortes comparáveis e efeitos simétricos de ganhar e "
        "perder a ligação. A mesma firma pode entrar nas duas coortes.",
        f"A um passo, o salto de B em 2025 foi {_pp(b1.get('estimativa'), 2)} p.p. "
        f"(p de Holm = {_numero(b1.get('p_holm'))}). O IC do contraste é nominal. A correção "
        "de Holm se aplica ao salto de B na família de testes secundários.",
        "O placebo da coorte B mede a mudança de participação de 2021–2022 para "
        "2023–setembro de 2024. Ele é distinto do placebo de nível pré do contraste.",
    )

    # 8. Sensibilidades e conclusão
    pos_menos_pre = _celula(
        _ler_tabela(pasta, "sensibilidade_placebo"), tipo="contraste", categoria="vencedor_faixa_1"
    )
    sem_auto = _celula(
        _ler_tabela(pasta, "sensibilidade_sem_autofinanciamento"),
        tipo="contraste",
        categoria="vencedor_faixa_1",
    )
    slide = _pagina(
        prs,
        "O resultado a um passo depende da especificação",
        f"{RESULTADOS}  /  H2",
        "Participação no elemento de despesa. Os contrastes usam ICs nominais.",
        fundo=PALIDO,
    )
    _texto(slide, "Contraste a um passo", MARGEM, 1.96, 6.3, 0.42, tamanho=23, forte=True)
    _tabela(
        slide,
        ["Especificação", "Contraste (p.p.)", "IC de 95% (p.p.)"],
        [
            [rotulo, _pp(linha.get("estimativa"), 2), _intervalo(linha, 2)]
            for rotulo, linha in (
                ("Principal (2025)", h2["1"]),
                ("Pós menos pré", pos_menos_pre),
                ("Sem autofinanciamento", sem_auto),
            )
        ],
        MARGEM,
        2.55,
        (3.00, 1.69, 1.86),
        0.65,
        15,
    )
    setembro = _celula(
        _ler_tabela(pasta, "sensibilidade_apenas_setembro"),
        tipo="contraste",
        categoria="vencedor_faixa_1",
    )
    if setembro.get("estimavel") is False:
        _texto(
            slide,
            "O cadastro só de setembro tem observações insuficientes para estimar o contraste.",
            MARGEM,
            5.46,
            6.55,
            0.78,
            tamanho=17,
            cor=CINZA,
        )
    robustez_inclui_zero = all(
        _status(linha) == "inclui zero" for linha in (pos_menos_pre, sem_auto)
    )
    _traco(slide, 7.66, 1.96, 7.66, 6.28)
    _texto(slide, "O que os dados sustentam", 8.02, 1.96, 4.55, 0.42, tamanho=23, forte=True)
    leitura_robustez = (
        "Os dois intervalos das especificações alternativas incluem zero."
        if robustez_inclui_zero
        else "As especificações alternativas testam a sensibilidade da estimativa."
    )
    _texto(
        slide,
        leitura_robustez,
        8.02,
        2.60,
        4.55,
        1.35,
        tamanho=26,
        fonte=FONTE_TITULO,
        cor=ACCENT,
    )
    _texto(
        slide,
        "A vantagem que H2 previa perto do vencedor segue em aberto.",
        8.02,
        4.32,
        4.55,
        1.00,
        tamanho=21,
    )
    link = _texto(slide, "Código e dados agregados", 8.02, 5.87, 4.55, 0.34, tamanho=15, cor=ACCENT)
    run = link.text_frame.paragraphs[0].runs[0]
    run.hyperlink.address = "https://github.com/rafaelt0/redes-empresariais-alternancia-politica"
    run.font.color.rgb = ACCENT
    piso = piso_gigante_h2(pasta)
    recorte = (
        leitura_h2_comparaveis(comparaveis.iter_rows(named=True)) if comparaveis is not None else ""
    )
    _nota(
        notas,
        "Voz 4",
        55,
        "Primeiro, medimos a mudança da participação pré-eleitoral para 2025. Depois, "
        "voltamos à participação de 2025 e excluímos as doações dos candidatos às próprias "
        f"campanhas. {leitura_robustez} Voltando à pergunta inicial, observamos "
        "como a participação varia com a distância ao vencedor. A persistência "
        "do acesso aos empenhos após a alternância continua em aberto nas eleições analisadas.",
        "Pós menos pré usa a diferença entre a participação de 2025 e a pré-eleitoral. "
        "O placebo do slide anterior usa a mudança entre dois períodos anteriores à eleição.",
        f"A três passos ou mais, o contraste é {_estimativa_pp(h2['3+'], 2)} "
        f"({_ic_pp(h2['3+'], 2)}).",
        *(
            (
                f"Ao menos {_pp(piso, 0)}% das observações nas bandas dessa faixa pertencem "
                "ao componente gigante. A mesma rede pode gerar dependência entre municípios.",
            )
            if piso is not None
            else ()
        ),
        *((recorte,) if recorte else ()),
    )

    for slide, nota in zip(prs.slides, notas, strict=True):
        slide.notes_slide.notes_text_frame.text = nota.texto()
    return prs, notas


def contar_slides(pptx: Path) -> int:
    return len(Presentation(str(pptx)).slides)


def contar_paginas(pdf: Path) -> int:
    """Páginas do PDF: `pdfinfo` quando existe, senão os objetos `/Type /Page`."""
    if shutil.which("pdfinfo"):
        saida = subprocess.run(
            ["pdfinfo", str(pdf)], capture_output=True, text=True, errors="replace", check=True
        ).stdout
        return int(re.search(r"^Pages:\s+(\d+)", saida, re.MULTILINE).group(1))  # type: ignore[union-attr]
    return len(re.findall(rb"/Type\s*/Page(?![a-z])", pdf.read_bytes()))


def converter(pptx: Path, pdf: Path) -> Path:
    """Converte com o LibreOffice em modo headless, com perfil temporário próprio."""
    with tempfile.TemporaryDirectory(prefix="deck-") as tmp:
        perfil = Path(tmp) / "perfil"
        subprocess.run(
            [
                ferramenta("soffice"),
                "--headless",
                f"-env:UserInstallation={perfil.as_uri()}",
                "--convert-to",
                "pdf",
                "--outdir",
                tmp,
                str(pptx),
            ],
            check=True,
            capture_output=True,
            text=True,
            errors="replace",
        )
        gerado = Path(tmp) / pptx.with_suffix(".pdf").name
        pdf.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(gerado, pdf)
    return pdf


def _cronometro(segundos: int) -> str:
    minutos, resto = divmod(segundos, 60)
    return f"{minutos}:{resto:02d}"


def guia(notas: list[Nota], titulos: list[str]) -> str:
    """`output/guia_de_fala.md`: pontos por slide, tempo e blocos de fala equilibrados.

    Cada bloco soma o mesmo tempo, e os blocos ainda não têm dono: a distribuição entre as
    pessoas fica para a reunião.
    """
    total = sum(nota.segundos for nota in notas)
    margem = LIMITE_SEGUNDOS - total
    if margem < 0:
        raise ValueError("O tempo previsto no guia excede dez minutos.")
    por_voz: dict[str, int] = {}
    slides: dict[str, list[int]] = {}
    for i, nota in enumerate(notas, start=1):
        por_voz[nota.pessoa] = por_voz.get(nota.pessoa, 0) + nota.segundos
        slides.setdefault(nota.pessoa, []).append(i)
    if len(por_voz) != len(VOZES) or len(set(por_voz.values())) != 1:
        detalhe = ", ".join(f"{voz}: {segundos} s" for voz, segundos in por_voz.items())
        raise ValueError(f"os {len(VOZES)} blocos de fala precisam ter o mesmo tempo ({detalhe})")
    faixa_por_voz = {
        voz: str(faixa[0]) if len(faixa) == 1 else f"{faixa[0]}–{faixa[-1]}"
        for voz, faixa in slides.items()
    }
    bloco = por_voz[VOZES[0]]
    acumulados = accumulate(nota.segundos for nota in notas)
    linhas = [
        "# Guia de fala",
        "",
        f"**Fala prevista de {_cronometro(total)}**, em {len(por_voz)} blocos iguais de "
        f"{_cronometro(bloco)}. Reserve {_cronometro(margem)} para trocas de apresentador e "
        f"variações de ritmo, dentro do limite de {_cronometro(LIMITE_SEGUNDOS)}. Os tempos "
        "acumulados servem de referência no ensaio.",
        "",
        "## Divisão entre participantes",
        "",
        "| Participante | Bloco | Slides | Tempo de fala |",
        "|---|---|---|---|",
        *[
            f"| {voz} | {tema} | {faixa_por_voz[voz]} | {_cronometro(bloco)} |"
            for voz, tema in zip(VOZES, TEMAS_VOZES, strict=True)
        ],
        "",
        "## Cronograma por slide",
        "",
        "| Slide | Tema | Voz | Tempo | Até |",
        "|---|---|---|---|---|",
        *[
            f"| {i} | {titulo} | {nota.pessoa} | {nota.segundos} s | {_cronometro(ate)} |"
            for i, (titulo, nota, ate) in enumerate(
                zip(titulos, notas, acumulados, strict=True), start=1
            )
        ],
        "",
    ]
    voz_anterior = None
    for i, (titulo, nota) in enumerate(zip(titulos, notas, strict=True), start=1):
        if nota.pessoa != voz_anterior:
            linhas.extend((f"## {nota.pessoa} · {TEMAS_VOZES[VOZES.index(nota.pessoa)]}", ""))
            voz_anterior = nota.pessoa
        linhas += [
            f"### {i}. {titulo} ({nota.segundos} s)",
            "",
            "**Na fala**",
            "",
            nota.fala,
            "",
        ]
        if nota.apoio:
            linhas += ["**Se perguntarem**", "", *(f"- {ponto}" for ponto in nota.apoio), ""]
    return "\n".join(linhas)


def executar(ctx: Contexto) -> None:
    ctx.caminhos.exigir_resultados(
        (
            "resumo_estimacao",
            "rede_resumo",
            "rede_graus",
            "rede_componentes",
            "links_pc1",
            "comparabilidade_h2",
            "h2_comparaveis",
            "permanencia_h4",
        ),
        ("figura1_exemplo",),
        "png",
    )
    numeros = Numeros.ler(ctx.caminhos.resultados / "tables")
    prs, notas = construir(ctx.caminhos, numeros)
    if len(prs.slides) != NUMERO_SLIDES:
        raise RuntimeError(f"deck com {len(prs.slides)} slides, eram esperados {NUMERO_SLIDES}")
    ctx.caminhos.saida.mkdir(parents=True, exist_ok=True)
    titulos = [slide.shapes[0].text_frame.text for slide in prs.slides]
    texto = guia(notas, titulos)
    if (ctx.caminhos.dados / MARCADOR).is_file():
        texto = "> Amostra sintética para teste.\n\n" + texto
    with tempfile.TemporaryDirectory(dir=ctx.caminhos.saida) as pasta:
        diretorio = Path(pasta)
        pptx = diretorio / "deck.pptx"
        prs.save(str(pptx))
        pdf = converter(pptx, diretorio / "deck.pdf")
        slides = contar_slides(pptx)
        paginas = contar_paginas(pdf)
        if slides != paginas:
            raise RuntimeError(f"deck.pdf tem {paginas} páginas e deck.pptx tem {slides} slides")
        roteiro = diretorio / "guia_de_fala.md"
        roteiro.write_text(texto, encoding="utf-8")
        for arquivo in (pptx, pdf, roteiro):
            arquivo.replace(ctx.caminhos.saida / arquivo.name)
