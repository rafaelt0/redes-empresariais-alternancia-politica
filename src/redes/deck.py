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

NUMERO_SLIDES = 9
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
    "Estrutura da rede e ligação direta (H1)",
    "Distância (H2) e conclusão",
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


def _grafico_intervalos(
    slide,
    linhas: list[tuple[str, dict]],
    *,
    titulo: str,
    destaque: str,
    y_topo: float = 3.08,
    espaco: float = 0.75,
) -> None:
    """Pontos e barras de IC editáveis, com a mesma escala em todas as linhas."""
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
        return 2.18 + 4.84 * (valor / passo - inferior) / (superior - inferior)

    _texto(slide, titulo, MARGEM, 2.34, 6.45, 0.33, tamanho=16, forte=True)
    for marca in range(inferior, superior + 1):
        x = posicao(marca * passo)
        _traco(
            slide,
            x,
            2.84,
            x,
            5.60,
            CINZA if marca == 0 else LINHA,
            1.3 if marca == 0 else 0.9,
        )
        _texto(
            slide,
            _numero(marca * passo, 0),
            x - 0.40,
            5.70,
            0.80,
            0.33,
            tamanho=15,
            cor=CINZA,
            alinhar=PP_ALIGN.CENTER,
        )
    for i, (rotulo, linha) in enumerate(linhas):
        y = y_topo + i * espaco
        cor = ACCENT if rotulo == destaque else INK
        _texto(slide, rotulo, MARGEM, y - 0.14, 1.38, 0.38, tamanho=15, cor=cor, forte=True)
        if _status(linha) == "sem estimativa" or linha.get("estimativa") is None:
            _texto(slide, "n.d.", 2.28, y - 0.13, 0.65, 0.28, tamanho=15, cor=CINZA)
            continue
        a, b = (posicao(100 * linha[k]) for k in ("ic_inf", "ic_sup"))
        x = posicao(100 * linha["estimativa"])
        _traco(slide, a, y, b, y, cor, 2.2)
        for ponta in (a, b):
            _traco(slide, ponta, y - 0.08, ponta, y + 0.08, cor, 1.4)
        ponto = slide.shapes.add_shape(
            MSO_SHAPE.OVAL, Inches(x - 0.062), Inches(y - 0.062), Inches(0.124), Inches(0.124)
        )
        ponto.fill.solid()
        ponto.fill.fore_color.rgb = cor
        ponto.line.fill.background()


def _grafico_distancia(slide, linhas: list[tuple[str, dict]]) -> None:
    _grafico_intervalos(
        slide,
        linhas,
        titulo="Contraste em p.p. da fatia de 2025 (IC nominal de 95%)",
        destaque="1 passo",
    )


def _mini_barra_ic(slide, linha: dict, x: float, y: float, largura: float, altura: float) -> None:
    """Faixa compacta com o intervalo de confiança e a linha de referência no zero."""
    caixa = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(largura), Inches(altura)
    )
    estilo = caixa._element.find(qn("p:style"))
    if estilo is not None:
        caixa._element.remove(estilo)
    caixa.fill.solid()
    caixa.fill.fore_color.rgb = PALIDO
    caixa.line.fill.background()
    if _status(linha) == "sem estimativa" or linha.get("estimativa") is None:
        _texto(
            slide,
            "Intervalo indisponível",
            x + 0.18,
            y + 0.26,
            largura - 0.36,
            0.30,
            tamanho=13,
            cor=CINZA,
            alinhar=PP_ALIGN.CENTER,
        )
        return
    est, inf, sup = (100 * linha[k] for k in ("estimativa", "ic_inf", "ic_sup"))
    limite = max(abs(inf), abs(sup), 1.0) * 1.18
    x_esq, x_dir = x + 0.28, x + largura - 0.28

    def pos(valor: float) -> float:
        return x_esq + (x_dir - x_esq) * (valor + limite) / (2 * limite)

    y_eixo = y + 0.34
    x0 = pos(0.0)
    _traco(slide, x_esq, y_eixo, x_dir, y_eixo, LINHA, 1.2)
    _traco(slide, x0, y + 0.14, x0, y + 0.54, CINZA, 1.2)
    a, b, p = pos(inf), pos(sup), pos(est)
    _traco(slide, a, y_eixo, b, y_eixo, ACCENT, 2.8)
    for ponta in (a, b):
        _traco(slide, ponta, y_eixo - 0.08, ponta, y_eixo + 0.08, ACCENT, 1.6)
    ponto = slide.shapes.add_shape(
        MSO_SHAPE.OVAL, Inches(p - 0.068), Inches(y_eixo - 0.068), Inches(0.136), Inches(0.136)
    )
    ponto.fill.solid()
    ponto.fill.fore_color.rgb = ACCENT
    ponto.line.fill.background()
    _texto(slide, f"{decimal(inf, 1)} p.p.", x_esq, y + 0.56, 1.5, 0.24, tamanho=11, cor=CINZA)
    _texto(
        slide,
        "0",
        x0 - 0.25,
        y + 0.56,
        0.50,
        0.24,
        tamanho=11,
        cor=CINZA,
        forte=True,
        alinhar=PP_ALIGN.CENTER,
    )
    _texto(
        slide,
        f"+{decimal(sup, 1)} p.p." if sup > 0 else f"{decimal(sup, 1)} p.p.",
        x_dir - 1.5,
        y + 0.56,
        1.5,
        0.24,
        tamanho=11,
        cor=CINZA,
        alinhar=PP_ALIGN.RIGHT,
    )


def _selo(slide, texto: str, x: float, y: float, largura: float) -> None:
    selo = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(largura), Inches(0.32)
    )
    estilo = selo._element.find(qn("p:style"))
    if estilo is not None:
        selo._element.remove(estilo)
    selo.fill.solid()
    selo.fill.fore_color.rgb = PALIDO
    selo.line.fill.background()
    _texto(
        slide,
        texto,
        x,
        y + 0.06,
        largura,
        0.22,
        tamanho=11,
        cor=ACCENT,
        forte=True,
        alinhar=PP_ALIGN.CENTER,
    )


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
        "Eleições para prefeito em SP (2024, sem a capital) e empenhos municipais de 2025",
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
        "De onde vem o poder político?",
        CONTEXTO,
        "Acemoglu e Robinson (2008), Persistence of Power, Elites, and Institutions.",
    )
    _texto(
        slide,
        "Para Acemoglu, Johnson e Robinson (2005), as regras econômicas resultam do "
        "conflito social pela distribuição de recursos.",
        MARGEM,
        1.66,
        11.4,
        0.82,
        tamanho=22,
    )
    _bloco(
        slide,
        "Poder formal (de jure)",
        "Autoridade conferida pelas instituições políticas.",
        MARGEM,
        2.66,
        5.42,
    )
    _traco(slide, 6.55, 2.64, 6.55, 3.78)
    _bloco(
        slide,
        "Poder de fato (de facto)",
        "Capacidade de influenciar decisões a partir de recursos econômicos.",
        MEIO,
        2.66,
        5.42,
    )
    _traco(slide, MARGEM, 4.36, LARGURA - MARGEM, 4.36)
    _texto(
        slide,
        "Por que o poder pode persistir",
        MARGEM,
        4.65,
        CORPO,
        0.34,
        tamanho=17,
        cor=ACCENT,
        forte=True,
    )
    _texto(
        slide,
        "Poder político  →  Regras econômicas  →  Distribuição de recursos"
        "  →  Poder de fato futuro",
        MARGEM,
        5.08,
        CORPO,
        0.44,
        tamanho=18,
        cor=ACCENT,
        forte=True,
    )
    _texto(
        slide,
        "Quem ganha recursos hoje pode ampliar sua influência amanhã.",
        MARGEM,
        5.68,
        CORPO,
        0.76,
        tamanho=20,
    )
    _nota(
        notas,
        "Voz 1",
        25,
        "Para Acemoglu, Johnson e Robinson, grupos disputam as regras da economia. "
        "O poder formal vem das instituições políticas; o poder de fato, dos recursos "
        "que permitem aos grupos se organizar e influenciar decisões. As regras que "
        "resultam dessa disputa distribuem recursos e podem reforçar a influência de "
        "quem já se beneficia delas.",
        "No esquema completo, o poder político também influencia as instituições "
        "políticas do período seguinte.",
    )

    slide = _pagina(prs, "Muda o governo. Mudam as redes fornecedoras?", CONTEXTO)
    _bloco(
        slide,
        "Muda o comando da prefeitura",
        "Se o incumbente perde, outro grupo passa a decidir sobre as despesas municipais.",
        MARGEM,
        1.94,
        5.42,
    )
    _traco(slide, 6.55, 1.92, 6.55, 3.44)
    _bloco(
        slide,
        "As redes podem persistir",
        "Uma rede societária pode manter vínculos com os dois grupos políticos.",
        MEIO,
        1.94,
        5.42,
    )
    _traco(slide, MARGEM, 3.68, LARGURA - MARGEM, 3.68)
    _bloco(
        slide,
        "A perda fica na empresa ou chega à rede?",
        "Se uma fornecedora ligada ao derrotado perde espaço, ganhos de outras empresas "
        "da mesma rede podem compensar a perda.",
        MARGEM,
        3.94,
        CORPO,
    )
    _bloco(
        slide,
        "Como testamos",
        "Mapeamos conexões pelas doações de campanha nas eleições municipais de 2024 e por "
        "vínculos societários. Em 2025, medimos a fatia dos empenhos de cada grupo de empresas.",
        MARGEM,
        5.05,
        CORPO,
    )
    _texto(
        slide,
        "Os dados não provam influência nem favorecimento.",
        MARGEM,
        6.72,
        CORPO,
        0.34,
        tamanho=15,
        cor=CINZA,
    )
    _nota(
        notas,
        "Voz 1",
        30,
        "A eleição troca quem decide na prefeitura, mas não desfaz os vínculos entre "
        "empresas. Uma rede pode estar ligada aos dois grupos. Se uma fornecedora ligada "
        "ao derrotado perde espaço, ganhos de outras empresas da mesma rede podem "
        "compensar essa perda. Mapeamos essas conexões com doações de campanha nas eleições "
        "municipais de 2024 e vínculos societários e olhamos os empenhos de 2025.",
        "Empenhos são compromissos de despesa, não pagamentos. Os vínculos observados "
        "não medem diretamente poder de fato nem demonstram favorecimento.",
    )

    # 4. Hipóteses com o diagrama de exemplo
    slide = _pagina(
        prs,
        "Ligação direta e distância ao vencedor",
        HIPOTESES,
        "Prefeito · 1º turno de 2024 em SP (sem a capital, 2º turno, ruptura ou ausência de A/B). "
        "Diagrama ilustrativo.",
    )
    faixa_ab = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(MARGEM), Inches(1.60), Inches(CORPO), Inches(0.86)
    )
    estilo = faixa_ab._element.find(qn("p:style"))
    if estilo is not None:
        faixa_ab._element.remove(estilo)
    faixa_ab.fill.solid()
    faixa_ab.fill.fore_color.rgb = PALIDO
    faixa_ab.line.fill.background()
    _texto(
        slide,
        "A  ·  Grupo incumbente",
        MARGEM + 0.16,
        1.70,
        7.15,
        0.26,
        tamanho=13,
        cor=ACCENT,
        forte=True,
    )
    _texto(
        slide,
        "1º prefeito na reeleição  →  2º seu partido  →  3º sua coligação.",
        MARGEM + 0.16,
        2.00,
        7.15,
        0.34,
        tamanho=15,
    )
    _traco(slide, 8.20, 1.72, 8.20, 2.34)
    _texto(
        slide,
        "B  ·  Adversário mais votado",
        8.40,
        1.70,
        4.05,
        0.26,
        tamanho=13,
        cor=ACCENT,
        forte=True,
    )
    _texto(
        slide,
        "Mais votado no 1º turno entre os demais.",
        8.40,
        2.00,
        4.05,
        0.34,
        tamanho=15,
    )
    for i, (rotulo, previsao) in enumerate(
        (
            (
                "H1 · Ligação direta",
                "Se A perde, X (que doou para A) perde espaço ante firmas sem ligação com A ou B?",
            ),
            (
                "H2 · Distância ao vencedor",
                "Estar mais perto de B ajuda? A partir de B: Z (0 passos), Y (1) e X (2).",
            ),
            (
                "RD · O que medimos",
                "O efeito de A perder perto do empate — não o efeito de criar uma conexão.",
            ),
        )
    ):
        y = 2.86 + i * 1.24
        _texto(slide, rotulo, MARGEM, y, 5.15, 0.28, tamanho=14, cor=ACCENT, forte=True)
        _texto(
            slide,
            previsao,
            MARGEM,
            y + 0.32,
            5.15,
            0.74,
            tamanho=16,
            cor=CINZA if rotulo.startswith("RD") else INK,
            forte=rotulo.startswith("H1"),
        )
    if exemplo.is_file():
        figura = slide.shapes.add_picture(
            str(exemplo), Inches(6.22), Inches(2.78), width=Inches(6.35)
        )
        figura._element.nvPicPr.cNvPr.set(
            "descr",
            "X liga-se a A por Ana e a Y por Bruno. Y liga-se a Z por Carla. "
            "Z liga-se a B por Daniel. Y está a um passo de A e de B.",
        )
    _texto(
        slide,
        "Setas tracejadas: doações (sementes). Linhas contínuas: sócio ou administrador em comum.",
        6.22,
        6.18,
        6.35,
        0.48,
        tamanho=13,
        cor=CINZA,
    )
    _nota(
        notas,
        "Voz 1",
        65,
        "No diagrama, definimos A e B no primeiro turno de 2024 em municípios sem segundo "
        "turno e com prefeito anterior definido. A é o grupo incumbente, por ordem de "
        "prioridade: o próprio prefeito concorrendo à reeleição, ou o candidato do seu "
        "partido, ou de coligação com esse partido; sem candidato ou com ruptura, o "
        "município sai da amostra. B é o adversário mais votado entre os demais. As setas "
        "tracejadas são doações: Ana liga X a A e Daniel liga Z a B — essas são as sementes. "
        "As linhas contínuas são vínculos societários: Bruno liga X a Y e Carla liga Y a Z. "
        "Em H1, testamos se X perde espaço quando A perde ante firmas sem caminho a A ou B. "
        "Em H2, exploramos diferenças por distância de B: Z a zero passos, Y a um e X a dois.",
        "O prefeito anterior é o eleito na última eleição antes de 06/10/2024 (incluindo "
        "suplementares). O prefeito concorrendo por outro partido continua no ramo do "
        "prefeito. Municípios sem adversário também são excluídos.",
        "A hierarquia da apresentação foi definida após a análise. O relatório e "
        "as tabelas preservam os testes originais.",
    )

    # 5. Desenho empírico
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
        "Em H1 e H2, o desfecho é a fatia dos empenhos de 2025 no elemento de despesa. "
        "As coortes usam doações e vínculos societários pré-eleitorais.",
        MARGEM,
        5.22,
        11.4,
        0.87,
        tamanho=22,
    )
    _texto(
        slide,
        f"{_destaque(numeros, 'munAnalisaveis')} municípios paulistas (prefeito, sem capital/2º "
        "turno). Estimação linear local e placebos.",
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

    # 6. Fontes e estrutura da rede
    slide = _pagina(prs, "Como montamos a rede e o que ela mostra", REDE)
    faixa = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(MARGEM), Inches(1.66), Inches(CORPO), Inches(1.28)
    )
    estilo = faixa._element.find(qn("p:style"))
    if estilo is not None:
        faixa._element.remove(estilo)
    faixa.fill.solid()
    faixa.fill.fore_color.rgb = PALIDO
    faixa.line.fill.background()
    largura_painel = (CORPO - 1.0) / 3
    for i, (titulo, corpo) in enumerate(
        (
            (
                "1. Receita Federal · Grafo único",
                f"{_destaque(numeros, 'empresasRede')} empresas e "
                f"{_destaque(numeros, 'pessoasRede')} sócios/adm. (PF e PJ) em "
                f"{_destaque(numeros, 'vinculosRede')} vínculos (set/out 2024).",
            ),
            (
                "2. TSE · Doações definem sementes",
                "Em cada município, doações de PF a prefeito (A/B) até 5/10/2024 "
                "marcam as sementes (0 passos no grafo).",
            ),
            (
                "3. TCESP · Empenhos municipais",
                "Prefeituras de SP (sem a capital, fora do TCESP): jan/2021–set/2024 "
                "define fornecedoras; 2025 mede a fatia.",
            ),
        )
    ):
        x = MARGEM + i * (largura_painel + 0.50)
        if i:
            _traco(slide, x - 0.25, 1.80, x - 0.25, 2.80)
        _texto(
            slide,
            titulo,
            x + 0.10,
            1.76,
            largura_painel - 0.16,
            0.28,
            tamanho=13,
            cor=ACCENT,
            forte=True,
        )
        _texto(slide, corpo, x + 0.10, 2.08, largura_painel - 0.16, 0.80, tamanho=13, cor=INK)

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
    paineis = (
        (
            "Maioria pequena ou isolada",
            (
                (
                    "Só 1 ou 2 vínculos",
                    percentual(grau_baixo) if grau_baixo is not None else "n.d.",
                    grau_baixo,
                ),
                (
                    "Sem nenhuma vizinha",
                    percentual(fracao_isoladas) if fracao_isoladas is not None else "n.d.",
                    fracao_isoladas,
                ),
            ),
            "Quase metade das firmas não divide sócio ou administrador com nenhuma outra.",
        ),
        (
            "Um gigante preso por pontes",
            (
                ("No maior componente", _destaque(numeros, "fracGigante"), maior),
                (
                    "Sem sócios-ponte",
                    _destaque(numeros, "fracGiganteSemArt"),
                    maior_sem_art,
                ),
            ),
            f"{_destaque(numeros, 'componentesRede')} redes separadas no grafo "
            f"(várias por município); 1 gigante reúne {_destaque(numeros, 'fracGigante')} "
            "das firmas.",
        ),
        (
            "Municípios com semente",
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
            f"De {_destaque(numeros, 'munAnalisaveis')} municípios analisáveis. "
            "Semente: firma com sócio ou administrador doador.",
        ),
    )
    for i, (titulo, barras, detalhe) in enumerate(paineis):
        x = MARGEM + i * (largura_painel + 0.50)
        if i:
            _traco(slide, x - 0.25, 3.24, x - 0.25, 5.82)
        _texto(slide, titulo, x, 3.24, largura_painel, 0.36, tamanho=16, forte=True)
        for j, (rotulo, valor, proporcao) in enumerate(barras):
            _barra_proporcao(slide, rotulo, valor, proporcao, x, 3.76 + j * 0.68, largura_painel)
        if detalhe:
            _texto(slide, detalhe, x, 5.04, largura_painel, 0.78, tamanho=13, cor=CINZA)

    _traco(slide, MARGEM, 6.04, LARGURA - MARGEM, 6.04)
    _texto(
        slide,
        f"Rede muito esparsa: {_numero(por_milhao)} vínculo por milhão de pares possíveis "
        "(densidade bipartida).",
        MARGEM,
        6.22,
        7.10,
        0.34,
        tamanho=13,
        cor=CINZA,
    )
    _texto(
        slide,
        f"Assortatividade r = {_numero(assortatividade, 4)} (sem padrão entre graus).",
        7.95,
        6.22,
        4.63,
        0.34,
        tamanho=13,
        cor=CINZA,
        alinhar=PP_ALIGN.RIGHT,
    )
    _nota(
        notas,
        "Voz 3",
        85,
        "Montamos a rede em três passos. Primeiro, a Receita Federal liga "
        f"{_destaque(numeros, 'empresasRede')} empresas a "
        f"{_destaque(numeros, 'pessoasRede')} vértices de sócios/administradores PF/PJ em "
        f"{_destaque(numeros, 'vinculosRede')} vínculos. Segundo, as doações de pessoas "
        "físicas do TSE marcam as empresas-semente, aquelas com sócio ou administrador que "
        "doou para A ou B. Terceiro, os empenhos do TCESP mostram quem já fornecia antes da "
        "eleição e qual fatia recebeu em 2025. Por dentro, a rede é muito fragmentada: quase "
        "toda empresa tem só um ou dois vínculos (grau médio de "
        f"{_numero(grau_medio, 2)} para empresas e {_numero(grau_medio_pessoa, 2)} para "
        "sócios) e quase metade não divide sócio com nenhuma outra. Mesmo assim, entre "
        f"{_destaque(numeros, 'componentesRede')} grupos separados, um único componente "
        f"gigante reúne {_destaque(numeros, 'fracGigante')} das empresas. Ele depende de "
        "poucas pessoas que funcionam como ponte: retirando esses pontos de articulação, "
        "como o Bruno no diagrama, o maior grupo cai para "
        f"{_destaque(numeros, 'fracGiganteSemArt')}. "
        f"Nos {_destaque(numeros, 'munAnalisaveis')} municípios analisáveis, encontramos "
        f"sementes de A em {_destaque(numeros, 'munConexaoA')} e de B em "
        f"{_destaque(numeros, 'munConexaoB')}.",
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

    # 7. Resultados de H1 (ligação direta)
    h1 = _celula(resumo, hipotese="H1", tipo="contraste")
    h1_a = _celula(resumo, hipotese="H1", tipo="categoria", categoria="conectada_incumbente")
    h1_sem = _celula(resumo, hipotese="H1", tipo="categoria", categoria="sem_conexao")
    h4 = _celula(resumo, hipotese="H4", tipo="contraste", categoria="ligada_ao_vencedor_50")
    slide = _pagina(
        prs,
        "Quem doou ao incumbente perde espaço (H1)?",
        RESULTADOS,
        "p.p.: pontos percentuais da fatia dos empenhos de 2025 no elemento de despesa. "
        "ICs de 95% (contraste por reamostragem municipal).",
    )
    _texto(
        slide,
        "Teste principal: quando A perde perto do empate, comparamos a fatia de 2025 das "
        "firmas ligadas diretamente a A contra firmas sem ligação a A ou B.",
        MARGEM,
        1.56,
        CORPO,
        0.58,
        tamanho=15,
        cor=CINZA,
    )
    _grafico_intervalos(
        slide,
        [
            ("Ligadas a A", h1_a),
            ("Sem ligação", h1_sem),
            ("Contraste H1", h1),
        ],
        titulo="Salto na fatia de 2025 em p.p. (IC de 95%)",
        destaque="Contraste H1",
        y_topo=3.22,
        espaco=0.92,
    )
    if h1_a.get("municipios_tratados") is not None and h1_a.get("municipios_controle") is not None:
        legenda_h1 = (
            f"Na banda de H1 ({_numero(h1_a.get('banda'), 1)} p.p.): "
            f"{int(h1_a['municipios_tratados'])} municípios onde A perdeu e "
            f"{int(h1_a['municipios_controle'])} onde A venceu (sementes de A)."
        )
    else:
        legenda_h1 = "Contraste = salto das firmas ligadas a A menos salto das sem ligação."
    _texto(slide, legenda_h1, MARGEM, 6.12, 6.45, 0.64, tamanho=14, cor=CINZA)
    _traco(slide, 7.43, 2.34, 7.43, 6.56)
    _texto(
        slide,
        "CONTRASTE PRINCIPAL (H1)",
        7.81,
        2.74,
        4.76,
        0.28,
        tamanho=13,
        cor=ACCENT,
        forte=True,
    )
    _texto(
        slide,
        "Salto das ligadas a A − salto das firmas sem ligação.",
        7.81,
        3.04,
        4.76,
        0.30,
        tamanho=14,
        cor=CINZA,
    )
    _texto(
        slide,
        _estimativa_pp(h1),
        7.81,
        3.42,
        4.76,
        0.84,
        tamanho=46,
        fonte=FONTE_TITULO,
        cor=ACCENT,
    )
    _texto(slide, _ic_pp(h1), 7.81, 4.36, 4.76, 0.34, tamanho=16, forte=True)
    leitura_h1 = (
        "Intervalo vai de queda forte a ganho forte: não há evidência de perda quando A sai."
        if _status(h1) == "inclui zero"
        else "A diferença resume o salto na fatia de empenhos de 2025."
    )
    _texto(slide, leitura_h1, 7.81, 4.80, 4.76, 0.80, tamanho=15, cor=CINZA)
    _nota(
        notas,
        "Voz 3",
        45,
        "Agora vamos ao teste principal, H1. Perguntamos se empresas ligadas diretamente ao "
        "incumbente A perdem fatia dos empenhos de 2025 quando A perde perto do empate, "
        "comparadas a firmas sem ligação a A ou B. O contraste mede o salto das ligadas a A "
        "menos o salto das firmas sem ligação. No gráfico, tanto as ligadas a A quanto "
        "o contraste principal cruzam zero com folga. A estimativa do contraste é de "
        f"{_estimativa_pp(h1)}, com {_ic_pp(h1)} — vai de queda forte a ganho forte, então "
        "não há evidência de perda quando A sai do cargo.",
        f"Na banda principal de H1, a estimativa das ligadas a A é {_estimativa_pp(h1_a)} "
        f"({_ic_pp(h1_a)}) e a das sem ligação é {_estimativa_pp(h1_sem)} ({_ic_pp(h1_sem)}).",
        f"Meia banda: {_pp(h1.get('estimativa_meia_banda'))} p.p.; dobro da banda: "
        f"{_pp(h1.get('estimativa_dobro_banda'))} p.p.; placebo pré-eleitoral: "
        f"{_pp(h1.get('placebo_estimativa'))} p.p. (p = {_numero(h1.get('placebo_p_valor'), 2)}); "
        f"EMD: {_pp(h1.get('emd'))} p.p.",
        "H4 (permanência no topo) ficou fora da apresentação principal por falta de "
        f"uma comparação informativa. No limiar de 50%, o efeito mínimo detectável é "
        f"{_pp(h4.get('emd'))} p.p. numa escala de 0 a 100%. O relatório preserva o teste.",
    )

    # 8. Contrastes por distância
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
    destaque_h2 = "Os contrastes por faixa não testam se o efeito diminui com a distância."
    slide = _pagina(
        prs,
        "A distância ao vencedor muda a fatia em 2025?",
        f"{RESULTADOS}  /  H2",
        "p.p.: pontos percentuais da fatia dos empenhos no elemento de despesa. "
        "ICs por reamostragem municipal. A é o incumbente e B, o adversário.",
    )
    _texto(
        slide,
        "Análise exploratória: quando A perde, B assume. Em cada distância, medimos a vantagem "
        "média de estar ligado ao vencedor (B) sobre o derrotado (A) — (salto de B − salto de A) "
        "÷ 2. Acima de 0 = vantagem do vencedor.",
        MARGEM,
        1.56,
        CORPO,
        0.68,
        tamanho=15,
        cor=CINZA,
    )
    _grafico_distancia(
        slide, list(zip(("Direta", "1 passo", "2 passos", "3+ passos"), h2.values(), strict=True))
    )
    _texto(
        slide,
        f"3 de 4 faixas cruzam zero; só 1 passo se afasta. {destaque_h2}",
        MARGEM,
        6.12,
        6.45,
        0.64,
        tamanho=14,
        cor=CINZA,
    )
    _traco(slide, 7.43, 2.34, 7.43, 6.56)
    _texto(
        slide,
        "1  ·  ÚNICO NÚMERO FORA DO ZERO (1 PASSO)",
        7.81,
        2.34,
        4.76,
        0.28,
        tamanho=13,
        cor=ACCENT,
        forte=True,
    )
    _texto(
        slide,
        _pp(h2["1"].get("estimativa"), 2)
        + (" p.p." if h2["1"].get("estimativa") is not None else ""),
        7.81,
        2.62,
        4.76,
        0.70,
        tamanho=38,
        fonte=FONTE_TITULO,
        cor=ACCENT,
    )
    _texto(
        slide,
        f"{_ic_pp(h2['1'], 2)} — sinal oposto ao de um ganho de fatia do vencedor.",
        7.81,
        3.38,
        4.76,
        0.64,
        tamanho=14,
    )
    _traco(slide, 7.81, 4.10, 12.57, 4.10)
    _texto(
        slide,
        "2  ·  TESTE PLACEBO (ANTES DA ELEIÇÃO)",
        7.81,
        4.24,
        4.76,
        0.26,
        tamanho=13,
        cor=ACCENT,
        forte=True,
    )
    _texto(
        slide,
        "Como foi construído: mesmas firmas, coortes, margem e bandas de 2024, "
        "trocando o desfecho pela mudança de fatia antes do voto "
        "(jan/2023–set/2024 menos jan/2021–dez/2022).",
        7.81,
        4.54,
        4.76,
        0.92,
        tamanho=13,
        cor=INK,
    )
    pre_txt = (
        f"Na coorte B a 1 passo, o salto já dá {_pp(pre_b['estimativa'], 2)} p.p. "
        f"(IC nominal de {_intervalo(pre_b, 2)} p.p.)."
        if pre_b.get("estimativa") is not None
        else "Diagnóstico indisponível."
    )
    if _status(pre_b) == _status(b1) == "negativo":
        pre_txt += " A diferença anterior à eleição enfraquece a leitura causal de 2025."
    _texto(slide, pre_txt, 7.81, 5.52, 4.76, 1.16, tamanho=14, cor=CINZA)
    _nota(
        notas,
        "Voz 4",
        75,
        "Em H2, perguntamos se estar mais perto do vencedor ajuda em 2025. Quando A perde, "
        "B assume. Para cada distância — direta, 1, 2 ou 3+ passos — medimos a vantagem "
        "média de estar ligado ao vencedor B sobre o derrotado A, fazendo salto de B menos "
        "salto de A dividido por dois. Um valor acima de zero indicaria vantagem do vencedor. "
        "No gráfico, três das quatro faixas cruzam zero; só 1 passo se afasta, com "
        f"{_estimativa_pp(h2['1'], 2)} ({_ic_pp(h2['1'], 2)}), já no sinal oposto a um ganho "
        f"do vencedor. Além disso, {destaque_h2.lower()} Para checar se isso é efeito da "
        "eleição, montamos um teste placebo com as mesmas firmas, coortes, margem e bandas "
        "de 2024, trocando o desfecho pela mudança de fatia antes do voto — de jan/2021–dez/2022 "
        f"para jan/2023–set/2024. {pre_txt}",
        "Ler o contraste como vantagem da ligação ao vencedor exige coortes comparáveis e "
        "simetria entre os efeitos de ganhar e perder essa ligação. A mesma firma pode entrar "
        "nas duas coortes, e um passo societário não mede necessariamente proximidade política.",
        f"A um passo, o salto de B em 2025 foi {_pp(b1.get('estimativa'), 2)} p.p. "
        f"(p de Holm = {_numero(b1.get('p_holm'))}). O IC do contraste é nominal. A correção "
        "de Holm se aplica ao salto de B na família de testes secundários.",
        "O placebo da coorte B mede a mudança de participação de 2021–2022 para "
        "2023–setembro de 2024. Ele é distinto do placebo de nível pré do contraste.",
    )

    # 9. Conclusão
    slide = _pagina(
        prs,
        "O que os dados permitem concluir",
        f"{RESULTADOS}  /  CONCLUSÃO",
        "p.p.: pontos percentuais da fatia dos empenhos no elemento de despesa.",
        fundo=PALIDO,
    )
    _texto(
        slide,
        "Sem evidência clara de perda para ligados ao incumbente ou de vantagem ao vencedor.",
        MARGEM,
        1.64,
        CORPO,
        0.42,
        tamanho=19,
        fonte=FONTE_TITULO,
        cor=ACCENT,
        forte=True,
    )
    largura_card = (CORPO - 0.36) / 2
    x_h1 = MARGEM
    x_h2 = MARGEM + largura_card + 0.36
    for x_card in (x_h1, x_h2):
        card = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE, Inches(x_card), Inches(2.26), Inches(largura_card), Inches(3.80)
        )
        estilo = card._element.find(qn("p:style"))
        if estilo is not None:
            card._element.remove(estilo)
        card.fill.solid()
        card.fill.fore_color.rgb = BRANCO
        card.line.color.rgb = LINHA
        card.line.width = Pt(0.8)

    # Card H1
    _texto(
        slide,
        "H1  ·  LIGAÇÃO DIRETA",
        x_h1 + 0.26,
        2.48,
        3.40,
        0.26,
        tamanho=12,
        cor=ACCENT,
        forte=True,
    )
    _selo(slide, "EM ABERTO", x_h1 + largura_card - 1.72, 2.42, 1.46)
    _texto(
        slide,
        _estimativa_pp(h1),
        x_h1 + 0.26,
        2.86,
        largura_card - 0.52,
        0.66,
        tamanho=38,
        fonte=FONTE_TITULO,
        cor=ACCENT,
    )
    _texto(
        slide,
        _ic_pp(h1),
        x_h1 + 0.26,
        3.56,
        largura_card - 0.52,
        0.28,
        tamanho=13,
        cor=CINZA,
    )
    _mini_barra_ic(slide, h1, x_h1 + 0.26, 3.96, largura_card - 0.52, 0.86)
    _texto(
        slide,
        "•  Intervalo cruza zero com folga (queda ou ganho).",
        x_h1 + 0.26,
        5.04,
        largura_card - 0.52,
        0.34,
        tamanho=14,
        cor=INK,
    )
    _texto(
        slide,
        "•  Sem evidência de perda para quem doou a A.",
        x_h1 + 0.26,
        5.46,
        largura_card - 0.52,
        0.34,
        tamanho=14,
        cor=INK,
    )

    # Card H2
    _texto(
        slide,
        "H2  ·  DISTÂNCIA AO VENCEDOR",
        x_h2 + 0.26,
        2.48,
        3.40,
        0.26,
        tamanho=12,
        cor=ACCENT,
        forte=True,
    )
    _selo(slide, "NÃO SE SUSTENTA", x_h2 + largura_card - 2.08, 2.42, 1.82)
    _texto(
        slide,
        _estimativa_pp(h2["1"], 2),
        x_h2 + 0.26,
        2.86,
        largura_card - 0.52,
        0.66,
        tamanho=38,
        fonte=FONTE_TITULO,
        cor=ACCENT,
    )
    _texto(
        slide,
        "Único destaque (1 passo) · sinal oposto ao vencedor",
        x_h2 + 0.26,
        3.56,
        largura_card - 0.52,
        0.28,
        tamanho=13,
        cor=CINZA,
    )
    caixa_placebo = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE,
        Inches(x_h2 + 0.26),
        Inches(3.96),
        Inches(largura_card - 0.52),
        Inches(0.86),
    )
    estilo = caixa_placebo._element.find(qn("p:style"))
    if estilo is not None:
        caixa_placebo._element.remove(estilo)
    caixa_placebo.fill.solid()
    caixa_placebo.fill.fore_color.rgb = PALIDO
    caixa_placebo.line.fill.background()
    _texto(
        slide,
        "PLACEBO PRÉ (COORTE B · 1 PASSO)",
        x_h2 + 0.44,
        4.10,
        3.10,
        0.24,
        tamanho=11,
        cor=CINZA,
        forte=True,
    )
    _texto(
        slide,
        "Antes do voto (2023–24 vs. 2021–22)",
        x_h2 + 0.44,
        4.38,
        3.10,
        0.26,
        tamanho=12,
        cor=CINZA,
    )
    _texto(
        slide,
        _estimativa_pp(pre_b, 2),
        x_h2 + largura_card - 2.16,
        4.14,
        1.72,
        0.48,
        tamanho=24,
        fonte=FONTE_TITULO,
        cor=ACCENT,
        forte=True,
        alinhar=PP_ALIGN.RIGHT,
    )
    _texto(
        slide,
        "•  3 de 4 faixas cruzam zero; só 1 passo se afasta.",
        x_h2 + 0.26,
        5.04,
        largura_card - 0.52,
        0.34,
        tamanho=14,
        cor=INK,
    )
    _texto(
        slide,
        "•  A queda já aparece no placebo antes do voto.",
        x_h2 + 0.26,
        5.46,
        largura_card - 0.52,
        0.34,
        tamanho=14,
        cor=INK,
    )

    _texto(
        slide,
        "Em síntese: eleições de 2024 e empenhos de 2025 não provam efeito causal nem "
        "favorecimento.",
        MARGEM,
        6.30,
        9.10,
        0.40,
        tamanho=14,
        cor=CINZA,
    )
    link = _texto(
        slide,
        "Código e dados agregados",
        LARGURA - MARGEM - 2.60,
        6.30,
        2.60,
        0.34,
        tamanho=14,
        cor=ACCENT,
        alinhar=PP_ALIGN.RIGHT,
    )
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
        "Para concluir, voltamos às duas hipóteses apresentadas. Em H1, o intervalo de "
        "confiança cruza zero com folga, então não há evidência de que empresas ligadas "
        "diretamente ao incumbente percam espaço quando ele sai do cargo. Em H2, três das "
        "quatro distâncias cruzam zero, e o único destaque em 2025 — a 1 passo — já tem "
        "sinal oposto a uma vantagem do vencedor e aparece antes do voto no teste placebo "
        f"({pre_txt}). Em síntese, os dados de 2024 e 2025 deixam em aberto a perda "
        "para ligados ao incumbente e não provam efeito causal nem favorecimento.",
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
