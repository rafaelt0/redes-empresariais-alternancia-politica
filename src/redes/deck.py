"""Gera o PowerPoint, o PDF e o guia de fala a partir dos resultados agregados."""

import math
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from html import escape
from itertools import accumulate
from pathlib import Path
from string import Template

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

APRESENTADORES = {"Voz 1": "Andrei", "Voz 2": "Felipe", "Voz 3": "João Pedro", "Voz 4": "Rafael"}
VOZES = tuple(APRESENTADORES)
ARQUIVOS_GUIAS = {voz: f"guia_voz_{i}.md" for i, voz in enumerate(VOZES, start=1)}

ETAPA = Etapa(
    nome="deck",
    depende=("estimate",),
    le=(),
    grava=(),
    artefatos=(
        "saida/deck.pptx",
        "saida/deck.pdf",
        "saida/guia_de_fala.md",
        "saida/guia_de_fala.html",
        *(f"saida/{nome}" for nome in ARQUIVOS_GUIAS.values()),
    ),
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
TITULO = "Redes empresariais, eleições e empenhos municipais"
AUTORES = (
    "Felipe Ferreira Alexandre",
    "Andrei Schoschlakow Bonifácio",
    "Rafael Eiki Teruya",
    "João Pedro Ferreira",
)
NUSP = ("13963144", "14558482", "14604204", "14582312")
TEMAS_VOZES = (
    "Economia política e pergunta de pesquisa",
    "Hipóteses e desenho empírico",
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
        linhas = [
            f"{self.pessoa} · {APRESENTADORES[self.pessoa]} · {self.segundos} s",
            "",
            "Na fala",
            self.fala,
        ]
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
        titulo="Contraste entre coortes em 2025 (p.p., IC nominal de 95%)",
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
    descritivas = _ler_tabela(pasta, "descritivas_estimacao")
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
        f"Eleições para prefeito em SP (2024, {_destaque(numeros, 'munAnalisaveis')} municípios) "
        "e empenhos municipais de 2025",
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
        15,
        "Vamos apresentar nosso estudo sobre redes empresariais e eleições municipais "
        "em São Paulo.",
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
        60,
        "Para Acemoglu, Johnson e Robinson, grupos com interesses diferentes disputam as "
        "regras da economia. "
        "O poder formal vem das instituições políticas. Numa prefeitura, por exemplo, "
        "o mandato dá autoridade a quem assume o governo. O poder de fato vem dos recursos "
        "que permitem a empresas e outros grupos se organizar e influenciar decisões.\n\n"
        "O esquema mostra como esse poder pode persistir. Quem tem mais poder político "
        "pode influenciar as regras econômicas, que ajudam a definir quem recebe recursos. "
        "Quem se beneficia dessa distribuição hoje pode ter mais influência nas decisões "
        "de amanhã.",
        "No esquema completo, o poder político também influencia as instituições "
        "políticas do período seguinte.",
    )

    slide = _pagina(prs, "A troca de governo muda a fatia das fornecedoras?", CONTEXTO)
    _bloco(
        slide,
        "Ligação direta com A (H1)",
        "Quando o grupo incumbente perde por pouco, as fornecedoras ligadas a ele perdem fatia?",
        MARGEM,
        1.94,
        5.42,
    )
    _traco(slide, 6.55, 1.92, 6.55, 3.44)
    _bloco(
        slide,
        "Distância a A e B (H2)",
        "Como a fatia das fornecedoras varia conforme a distância a cada candidatura na rede?",
        MEIO,
        1.94,
        5.42,
    )
    _traco(slide, MARGEM, 3.68, LARGURA - MARGEM, 3.68)
    _bloco(
        slide,
        "Vínculos antes da eleição de 2024",
        "Ligamos as fornecedoras às candidaturas pelas doações de seus sócios ou "
        "administradores e pelos vínculos societários entre empresas.",
        MARGEM,
        3.94,
        CORPO,
    )
    _bloco(
        slide,
        "Empenhos no primeiro ano após a eleição",
        "Para cada fornecedora anterior, medimos a fatia dos empenhos de 2025 em sua "
        "categoria de despesa no município.",
        MARGEM,
        5.29,
        CORPO,
    )
    _nota(
        notas,
        "Voz 1",
        70,
        "Nas eleições municipais de 2024 em São Paulo, perguntamos se a derrota apertada "
        "de quem governava mudou a fatia das empresas que já forneciam para a prefeitura. "
        "Observamos as fornecedoras com ligação direta ao incumbente e as que chegam a uma "
        "candidatura por vínculos societários.\n\n"
        "Definimos essas ligações antes do voto, a partir das doações de sócios ou "
        "administradores e dos vínculos entre empresas. Depois da eleição, observamos os "
        "empenhos, que registram os compromissos de despesa da prefeitura. Para cada "
        "fornecedora anterior, calculamos sua fatia dos empenhos de 2025 na respectiva "
        "categoria de despesa.",
        "As doações e os vínculos societários são medidas de conexão observada. "
        "A teoria motiva a hipótese de influência.",
        "O relatório explora se, dentro de uma rede, ganhos de umas empresas compensam "
        "perdas de outras (H3). As estimativas deixam essa hipótese em aberto.",
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
        MSO_SHAPE.RECTANGLE, Inches(MARGEM), Inches(1.60), Inches(CORPO), Inches(1.06)
    )
    estilo = faixa_ab._element.find(qn("p:style"))
    if estilo is not None:
        faixa_ab._element.remove(estilo)
    faixa_ab.fill.solid()
    faixa_ab.fill.fore_color.rgb = PALIDO
    faixa_ab.line.fill.background()
    _texto(
        slide,
        "A e B são definidos em cada município",
        MARGEM + 0.16,
        1.68,
        CORPO - 0.32,
        0.26,
        tamanho=14,
        forte=True,
    )
    _texto(
        slide,
        "A  ·  Candidatura do grupo incumbente",
        MARGEM + 0.16,
        1.99,
        7.15,
        0.26,
        tamanho=13,
        cor=ACCENT,
        forte=True,
    )
    _texto(
        slide,
        "1º Prefeito candidato. 2º Candidato do partido. 3º Da coligação.",
        MARGEM + 0.16,
        2.27,
        7.15,
        0.34,
        tamanho=15,
    )
    _traco(slide, 8.20, 1.97, 8.20, 2.55)
    _texto(
        slide,
        "B  ·  Adversário mais votado",
        8.40,
        1.99,
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
        2.27,
        4.05,
        0.34,
        tamanho=15,
    )
    for i, (rotulo, previsao) in enumerate(
        (
            (
                "H1 · Ligação direta",
                "Se A perde, X (cuja sócia doou a A) perde fatia ante firmas sem caminho a A ou B?",
            ),
            (
                "H2 · Distância ao vencedor",
                "A vantagem prevista diminui com a distância? Y está a 1 passo de A e de B.",
            ),
            (
                "RD · O que medimos",
                "Estimamos o efeito local de A perder. As conexões são definidas antes do voto.",
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
        "Voz 2",
        65,
        "Definimos A e B município por município. A é a candidatura do grupo que já "
        "governava ali. Se o prefeito concorre, ele é A. Na ausência dele, buscamos "
        "primeiro o candidato do seu partido e depois o da coligação que inclui o partido. "
        "B é o adversário mais votado entre os demais candidatos daquele município.\n\n"
        "No diagrama, as doações fazem de X a semente de A e de Z a semente de B. "
        "Na primeira hipótese, perguntamos se X perde fatia quando A perde, em comparação "
        "com empresas sem caminho a A ou B. Na segunda, perguntamos se a vantagem esperada "
        "para quem está ligado ao vencedor diminui com a distância. Y está a um passo de "
        "cada semente, então entra nos dois grupos.",
        "O prefeito anterior é o eleito na última eleição antes de 06/10/2024 (incluindo "
        "suplementares). O prefeito concorrendo por outro partido continua no ramo do prefeito.",
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
        1.68,
        CORPO,
        0.38,
        tamanho=18,
        cor=CINZA,
    )
    _texto(slide, "A perde · T = 1", MARGEM, 2.13, 5.15, 0.42, tamanho=24, fonte=FONTE_TITULO)
    _texto(
        slide,
        "0",
        6.29,
        2.04,
        0.76,
        0.48,
        tamanho=30,
        cor=ACCENT,
        forte=True,
        alinhar=PP_ALIGN.CENTER,
    )
    _texto(
        slide,
        "A vence · T = 0",
        7.44,
        2.13,
        5.14,
        0.42,
        tamanho=24,
        fonte=FONTE_TITULO,
        alinhar=PP_ALIGN.RIGHT,
    )
    _traco(slide, MARGEM, 2.62, LARGURA - MARGEM, 2.62, LINHA, 1.6)
    _traco(slide, LARGURA / 2, 2.52, LARGURA / 2, 2.72, ACCENT, 2.3)
    _texto(
        slide,
        "Regressão descontínua no empate",
        MARGEM,
        2.88,
        CORPO,
        0.44,
        tamanho=26,
        fonte=FONTE_TITULO,
        cor=ACCENT,
    )
    _texto(
        slide,
        "Y = α + βT + γM + θ(T × M) + u,     |M| ≤ b",
        MARGEM,
        3.34,
        CORPO,
        0.51,
        tamanho=28,
        fonte=FONTE_TITULO,
    )
    for x, linha, altura, simbolo, definicao in (
        (
            MARGEM,
            0,
            0.65,
            "Y",
            "Fatia da fornecedora nos empenhos de 2025\n"
            "do município, por tipo de despesa (H1 e H2).",
        ),
        (MARGEM, 2, 0.34, "u", "Fatia observada menos a fatia prevista"),
        (MARGEM, 3, 0.34, "b", "Distância máxima ao empate (em p.p.)"),
        (MEIO, 0, 0.34, "α", "Fatia prevista no empate pelo lado da vitória"),
        (MEIO, 1, 0.34, "β", "Salto no empate (derrota menos vitória)"),
        (MEIO, 2, 0.34, "γ", "Inclinação da reta do lado da vitória"),
        (MEIO, 3, 0.34, "θ", "Diferença de inclinação (derrota menos vitória)"),
    ):
        y = 3.99 + 0.43 * linha
        _texto(slide, simbolo, x, y, 0.25, 0.34, tamanho=18, cor=ACCENT, forte=True)
        _texto(slide, definicao, x + 0.35, y, 5.3, altura, tamanho=18)
    _texto(
        slide,
        "Exemplo de Y · R$ 10 de R$ 100 em material de consumo dão 10%. "
        "O total inclui novas fornecedoras.",
        MARGEM,
        5.91,
        CORPO,
        0.38,
        tamanho=17,
    )
    _texto(
        slide,
        f"{_destaque(numeros, 'munAnalisaveis')} municípios paulistas (eleições para prefeito, "
        "sem capital e sem 2º turno). Ajuste linear local e placebos.",
        MARGEM,
        6.48,
        CORPO,
        0.38,
        tamanho=17,
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
        80,
        "A amostra exclui a capital, que tem tribunal de contas próprio, e usa eleições "
        "decididas no primeiro turno.\n\n"
        "Em H1 e H2, Y é a fatia da fornecedora nos empenhos municipais de 2025 por tipo "
        "de despesa. Se X tem dez reais de um total de cem, sua fatia é de dez por cento. "
        "O total inclui novas fornecedoras.\n\n"
        "M é o percentual de votos válidos de A menos o de B, em pontos percentuais. T vale "
        "um na derrota de A e zero na vitória. A banda b é a distância máxima ao empate para "
        "entrar no ajuste.\n\n"
        "Cada lado tem sua reta. Alfa é a fatia prevista no empate pela reta do lado da "
        "vitória. Gama é a inclinação dessa reta. Teta multiplica T vezes M e mede a mudança "
        "de inclinação na derrota. O termo u é a diferença entre a fatia observada e a "
        "prevista.\n\n"
        "Beta é o salto no empate, a previsão do lado da derrota menos a do lado da vitória. "
        "Esse salto estima o efeito local da derrota se a fatia variar continuamente em cada "
        "cenário perto do empate. Com dados pré-eleitorais, checamos se já havia um salto.",
        "Na equação, T = 1 se M < 0 e T = 0 se M ≥ 0. A reta do lado da derrota tem "
        "inclinação γ + θ e intercepto α + β.",
        "Nossa base de empenhos vem do Tribunal de Contas do Estado. Em disputas com "
        "segundo turno, o líder do primeiro ainda pode perder.",
        "Também excluímos os municípios sem A identificável ou sem adversário. "
        "O suporte na banda varia por coorte.",
        "Usamos núcleo triangular, banda escolhida pelo erro quadrático médio estimado e "
        "correção de viés. Os contrastes reamostram municípios de cada lado em conjunto, "
        "com bandas fixas.",
        f"O teste de densidade da margem deu p = {_numero(densidade_margem)}. "
        "Também verificamos placebos e sensibilidade à metade e ao dobro da banda.",
        "Fornecedora anterior tem saldo líquido positivo na janela pré-eleitoral. "
        "O desfecho de H1 e H2 inclui os saldos positivos das entrantes no denominador.",
    )

    # 6. Fontes e estrutura da rede
    slide = _pagina(prs, "Uma rede societária para todos os municípios", REDE)
    faixa = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(MARGEM), Inches(1.66), Inches(CORPO), Inches(1.12)
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
                "1. Receita Federal · Grafo nacional",
                f"{_destaque(numeros, 'empresasRede')} empresas e "
                f"{_destaque(numeros, 'pessoasRede')} sócios/adm. (PF e PJ) em "
                f"{_destaque(numeros, 'vinculosRede')} vínculos (set/out 2024).",
            ),
            (
                "2. TSE · Doações definem sementes",
                "Semente: sócio ou administrador doou à candidatura local até 5/10/2024.",
            ),
            (
                "3. TCESP · Empenhos municipais",
                "SP (sem a capital): jan/2021–set/2024 define fornecedoras; 2025 mede a fatia.",
            ),
        )
    ):
        x = MARGEM + i * (largura_painel + 0.50)
        if i:
            _traco(slide, x - 0.25, 1.78, x - 0.25, 2.66)
        _texto(
            slide,
            titulo,
            x + 0.10,
            1.75,
            largura_painel - 0.16,
            0.26,
            tamanho=13,
            cor=ACCENT,
            forte=True,
        )
        _texto(slide, corpo, x + 0.10, 2.05, largura_painel - 0.16, 0.66, tamanho=13, cor=INK)

    _texto(
        slide,
        "Calculamos as ligações com A e B em cada município",
        MARGEM,
        2.98,
        CORPO,
        0.33,
        tamanho=17,
        cor=ACCENT,
        forte=True,
    )
    _texto(
        slide,
        "Z fornece nas duas cidades; as doações a A mudam a semente em cada uma.",
        MARGEM,
        3.33,
        CORPO,
        0.30,
        tamanho=15,
    )
    for x, titulo, semente, corpo in (
        (MARGEM, "Município 1", "X", "Sócia de X doou a A. De X a Z, 2 passos."),
        (MEIO, "Município 2", "Y", "Sócio de Y doou a A. De Y a Z, 1 passo."),
    ):
        _texto(slide, titulo, x, 3.70, 5.42, 0.24, tamanho=14, forte=True)
        caminho = _texto(slide, "", x, 3.94, 5.42, 0.38, tamanho=21, forte=True)
        paragrafo = caminho.text_frame.paragraphs[0]
        for trecho in ("X", " — ", "Y", " — ", "Z"):
            run = paragrafo.add_run()
            run.text = f"{trecho} (semente)" if trecho == semente else trecho
            if trecho == semente:
                run.font.color.rgb = ACCENT
        _texto(slide, corpo, x, 4.38, 5.42, 0.26, tamanho=14, cor=CINZA)

    _traco(slide, MARGEM, 4.78, LARGURA - MARGEM, 4.78)
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
            "",
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
            f"{_destaque(numeros, 'componentesRede')} componentes na rede.",
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
            f"De {_destaque(numeros, 'munAnalisaveis')} municípios analisáveis.",
        ),
    )
    for i, (titulo, barras, detalhe) in enumerate(paineis):
        x = MARGEM + i * (largura_painel + 0.50)
        if i:
            _traco(slide, x - 0.25, 4.94, x - 0.25, 6.55)
        _texto(slide, titulo, x, 4.94, largura_painel, 0.32, tamanho=16, forte=True)
        for j, (rotulo, valor, proporcao) in enumerate(barras):
            _barra_proporcao(slide, rotulo, valor, proporcao, x, 5.32 + j * 0.52, largura_painel)
        if detalhe:
            _texto(slide, detalhe, x, 6.36, largura_painel, 0.25, tamanho=12, cor=CINZA)

    _texto(
        slide,
        f"Densidade bipartida: {_numero(por_milhao)} vínculo por milhão de pares possíveis.",
        MARGEM,
        6.78,
        7.10,
        0.34,
        tamanho=12,
        cor=CINZA,
    )
    _texto(
        slide,
        f"Assortatividade r = {_numero(assortatividade, 4)} (sem padrão entre graus).",
        7.95,
        6.78,
        4.63,
        0.34,
        tamanho=12,
        cor=CINZA,
        alinhar=PP_ALIGN.RIGHT,
    )
    _nota(
        notas,
        "Voz 3",
        75,
        "A rede societária é nacional. Calculamos as ligações com A e B para as "
        "candidaturas de cada município. As doações a essas candidaturas definem as "
        "empresas-semente de onde partimos.\n\n"
        "No exemplo do slide, a empresa Z fornece para duas prefeituras. Na primeira, "
        "uma sócia de X doou a A. X é a semente, então contamos dois passos até Z, passando "
        "por Y. Na segunda, um sócio de Y doou a A. Agora a semente é Y, e Z está a um "
        "passo.\n\n"
        "A rede é esparsa, e muitas empresas ficam em grupos separados. Ainda assim, "
        f"o maior grupo conectado reúne {_destaque(numeros, 'fracGigante')} das empresas. "
        "Quando retiramos os sócios ou administradores que funcionam como pontes, "
        "esse grupo encolhe.",
        "A Receita Federal liga "
        f"{_destaque(numeros, 'empresasRede')} empresas a "
        f"{_destaque(numeros, 'pessoasRede')} vértices de sócios/administradores PF/PJ em "
        f"{_destaque(numeros, 'vinculosRede')} vínculos. "
        "O TSE registra as doações às candidaturas. "
        "Os empenhos do TCESP identificam as fornecedoras e mostram sua fatia em 2025.",
        "A rede é fragmentada. Quase toda empresa tem um ou dois vínculos (grau médio de "
        f"{_numero(grau_medio, 2)} para empresas e {_numero(grau_medio_pessoa, 2)} para "
        "sócios) e quase metade não tem vizinha. Entre "
        f"{_destaque(numeros, 'componentesRede')} grupos separados, um único componente "
        f"gigante reúne {_destaque(numeros, 'fracGigante')} das empresas. Sem os sócios ou "
        "administradores que funcionam como ponte, o maior grupo cai para "
        f"{_destaque(numeros, 'fracGiganteSemArt')}.",
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
        "As fornecedoras ligadas a A perdem fatia (H1)?",
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
    for i, (rotulo, coorte) in enumerate((("Ligadas a A", h1_a), ("Sem ligação", h1_sem))):
        derrotas, vitorias = coorte.get("municipios_tratados"), coorte.get("municipios_controle")
        if derrotas is not None and vitorias is not None:
            banda = _numero(coorte.get("banda"), 1)
            legenda = f"{rotulo} · banda de {banda} p.p. · {derrotas} derrotas, {vitorias} vitórias"
            _texto(slide, legenda, MARGEM, 6.12 + i * 0.28, 6.45, 0.26, tamanho=13, cor=CINZA)
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
        "O intervalo admite perdas e ganhos relevantes de participação."
        if _status(h1) == "inclui zero"
        else "A diferença resume o salto na fatia de empenhos de 2025."
    )
    _texto(slide, leitura_h1, 7.81, 4.80, 4.76, 0.80, tamanho=15, cor=CINZA)
    media_pos_h1 = _celula(descritivas, categoria="faixa_a_0").get("media_participacao_2025")
    if h1.get("emd") is not None:
        texto_emd = f"Efeito mínimo detectável: {_pp(h1['emd'])} p.p."
        if media_pos_h1 is not None:
            texto_emd += f"\nMédia em 2025 (ligadas a A): {percentual(media_pos_h1, 2)}"
        _texto(
            slide,
            texto_emd,
            7.81,
            5.58,
            4.76,
            0.60,
            tamanho=14,
            cor=CINZA,
        )
    _nota(
        notas,
        "Voz 3",
        70,
        "Para testar H1, estimamos o salto na fatia das fornecedoras ligadas diretamente a "
        "A quando ele perde perto do empate. Repetimos a estimativa para as empresas sem "
        "caminho a A ou B. Cada grupo tem sua própria janela de margens eleitorais. "
        "O contraste subtrai o salto das empresas sem caminho do salto das ligadas a A.\n\n"
        f"A estimativa foi de {_pp(h1.get('estimativa'))} pontos percentuais. O intervalo "
        f"de confiança de 95% vai de {_intervalo(h1)} pontos percentuais. {leitura_h1}",
        f"A estimativa das ligadas a A é {_estimativa_pp(h1_a)} "
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
    pre_b = _celula(pre_periodos, hipotese="H2", tipo="categoria", categoria="faixa_b_1")
    pre_h2 = _celula(pre_periodos, hipotese="H2", tipo="contraste", categoria="vencedor_faixa_1")
    b1 = _celula(
        resumo,
        hipotese="H2",
        tipo="categoria",
        categoria="faixa_b_1",
        resultado="participacao_2025",
    )
    destaque_h2 = "Testar se o efeito diminui exige comparar as faixas entre si."
    salto_pre_b = _status(pre_b) == _status(b1) == "negativo"
    piso = piso_gigante_h2(pasta)
    slide = _pagina(
        prs,
        "Fatia em 2025 por distância a A e B",
        f"{RESULTADOS}  /  H2",
        "p.p.: pontos percentuais da fatia dos empenhos no elemento de despesa. "
        "ICs por reamostragem municipal. A é o incumbente e B, o adversário.",
    )
    _texto(
        slide,
        "Para cada distância, calculamos (salto da coorte B − salto da coorte A) ÷ 2. "
        "As coortes são definidas antes do voto e podem incluir as mesmas firmas.",
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
        destaque_h2,
        MARGEM,
        6.12,
        6.45,
        0.30,
        tamanho=14,
        cor=CINZA,
    )
    if piso is not None:
        _texto(
            slide,
            f"A 3+ passos, ao menos {_pp(piso, 0)}% das observações estão no componente gigante.",
            MARGEM,
            6.43,
            6.45,
            0.50,
            tamanho=13,
            cor=CINZA,
        )
    _traco(slide, 7.43, 2.34, 7.43, 6.56)
    _texto(
        slide,
        "CONTRASTE ENTRE COORTES A 1 PASSO",
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
        _ic_pp(h2["1"], 2),
        7.81,
        3.32,
        4.76,
        0.28,
        tamanho=14,
    )
    _texto(
        slide,
        "Sinal negativo indica queda na coorte do adversário vencedor (B), "
        "oposto à vantagem prevista por H2.",
        7.81,
        3.62,
        4.76,
        0.54,
        tamanho=13,
        cor=CINZA,
    )
    _traco(slide, 7.81, 4.24, 12.57, 4.24)
    _texto(
        slide,
        "PLACEBO PRÉ-ELEITORAL · COORTE B A 1 PASSO",
        7.81,
        4.38,
        4.76,
        0.26,
        tamanho=13,
        cor=ACCENT,
        forte=True,
    )
    _texto(
        slide,
        "Na mesma coorte B, usamos a mudança de fatia entre jan/2021–dez/2022 e "
        "jan/2023–set/2024. Mantemos a margem e as bandas da análise de 2025.",
        7.81,
        4.68,
        4.76,
        0.86,
        tamanho=13,
        cor=INK,
    )
    comparacao_b = (
        f"O salto em B foi de {_estimativa_pp(pre_b, 2)} antes do voto e de "
        f"{_estimativa_pp(b1, 2)} em 2025."
    )
    leitura_b = " O salto antes do voto enfraquece a leitura causal para B." if salto_pre_b else ""
    _texto(slide, f"{comparacao_b}{leitura_b}", 7.81, 5.58, 4.76, 1.00, tamanho=14)
    _nota(
        notas,
        "Voz 4",
        100,
        "Na H2, formamos grupos pela distância a A e a B na rede, com os vínculos que já "
        "existiam antes do voto. Para cada distância, pegamos o salto do grupo de B, "
        "subtraímos o salto do grupo de A e dividimos por dois. No quadro à esquerda, "
        f"o contraste a um passo em 2025 foi de {_pp(h2['1'].get('estimativa'), 2)} pontos "
        f"percentuais, com intervalo de confiança de 95% de {_intervalo(h2['1'], 2)}. "
        "A leitura desse contraste depende de quão comparáveis são os dois grupos.\n\n"
        "À direita, testamos se o salto já aparecia antes da eleição no grupo a um passo "
        "de B. No placebo, mantemos a margem eleitoral e usamos a mudança de fatia do "
        "biênio 2021–2022 para o período de janeiro de 2023 a setembro de 2024. "
        f"O salto em B foi de {_pp(pre_b.get('estimativa'), 2)} pontos percentuais no "
        f"placebo e de {_pp(b1.get('estimativa'), 2)} em 2025.{leitura_b}",
        "Ler o contraste como vantagem da ligação ao vencedor exige coortes comparáveis e "
        "simetria entre os efeitos de ganhar e perder essa ligação. A mesma firma pode entrar "
        "nas duas coortes, e um passo societário não mede necessariamente proximidade política.",
        f"O placebo para B a um passo tem {_ic_pp(pre_b, 2)} (nominal). Em 2025, "
        f"o salto de B tem p de Holm = {_numero(b1.get('p_holm'))} na família secundária.",
        f"O contraste entre A e B a um passo, no placebo de mudança pré-eleitoral, foi de "
        f"{_estimativa_pp(pre_h2, 2)} ({_ic_pp(pre_h2, 2)}, nominal).",
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
        "A perda de fatia em H1 e o efeito da distância em H2 seguem em aberto.",
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
        "•  O intervalo inclui perdas e ganhos relevantes.",
        x_h1 + 0.26,
        5.04,
        largura_card - 0.52,
        0.34,
        tamanho=14,
        cor=INK,
    )
    if h1.get("emd") is not None:
        _texto(
            slide,
            f"•  Efeito mínimo detectável de {_pp(h1['emd'])} p.p.",
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
    _selo(slide, "EM ABERTO", x_h2 + largura_card - 1.72, 2.42, 1.46)
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
        "Contraste entre coortes a 1 passo em 2025",
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
        "PLACEBO PRÉ-ELEITORAL · SÓ A COORTE B",
        x_h2 + 0.44,
        4.10,
        3.44,
        0.24,
        tamanho=11,
        cor=CINZA,
        forte=True,
    )
    _texto(
        slide,
        "Salto em B a 1 passo antes do voto",
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
        "•  A previsão de queda do efeito com a distância segue em aberto.",
        x_h2 + 0.26,
        5.04,
        largura_card - 0.52,
        0.48,
        tamanho=13,
        cor=INK,
    )
    if salto_pre_b:
        _texto(
            slide,
            "•  O salto pré-eleitoral em B limita a interpretação causal.",
            x_h2 + 0.26,
            5.50,
            largura_card - 0.52,
            0.34,
            tamanho=13,
            cor=INK,
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
    recorte = (
        leitura_h2_comparaveis(comparaveis.iter_rows(named=True)) if comparaveis is not None else ""
    )
    _nota(
        notas,
        "Voz 4",
        45,
        "As duas hipóteses seguem em aberto. A estimativa para a ligação direta é "
        "imprecisa, e o salto a um passo já aparecia em B antes da eleição. Para saber se a "
        "vantagem diminui com a distância, precisamos comparar os resultados entre as faixas. "
        "Obrigado.",
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
    """Reúne os roteiros, o cronograma da apresentação e o apoio para perguntas."""
    total = sum(nota.segundos for nota in notas)
    margem = LIMITE_SEGUNDOS - total
    if margem < 0:
        raise ValueError("O tempo previsto no guia excede dez minutos.")
    por_voz: dict[str, int] = {}
    slides: dict[str, list[int]] = {}
    for i, nota in enumerate(notas, start=1):
        por_voz[nota.pessoa] = por_voz.get(nota.pessoa, 0) + nota.segundos
        slides.setdefault(nota.pessoa, []).append(i)
    if set(por_voz) != set(VOZES) or len(set(por_voz.values())) != 1:
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
            f"| [{voz} · {APRESENTADORES[voz]}]({ARQUIVOS_GUIAS[voz]}) | {tema} | "
            f"{faixa_por_voz[voz]} | {_cronometro(bloco)} |"
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
            voz_anterior = nota.pessoa
            linhas.extend((f"## {voz_anterior} · {APRESENTADORES[voz_anterior]}", ""))
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


def _slides_por_voz(
    notas: list[Nota], titulos: list[str]
) -> dict[str, list[tuple[int, str, Nota]]]:
    slides_por_voz: dict[str, list[tuple[int, str, Nota]]] = {voz: [] for voz in VOZES}
    for i, (titulo, nota) in enumerate(zip(titulos, notas, strict=True), start=1):
        slides_por_voz[nota.pessoa].append((i, titulo, nota))
    return slides_por_voz


def guias_individuais(notas: list[Nota], titulos: list[str]) -> dict[str, str]:
    slides_por_voz = _slides_por_voz(notas, titulos)
    roteiros = {}
    for voz, tema in zip(VOZES, TEMAS_VOZES, strict=True):
        slides = slides_por_voz[voz]
        total = sum(nota.segundos for _, _, nota in slides)
        linhas = [f"# {voz} · {APRESENTADORES[voz]}", "", f"**{tema} · {_cronometro(total)}**", ""]
        inicio = 0
        for i, titulo, nota in slides:
            fim = inicio + nota.segundos
            linhas.extend(
                (
                    f"## Slide {i} · {titulo} ({_cronometro(inicio)}–{_cronometro(fim)})",
                    "",
                    nota.fala,
                    "",
                )
            )
            inicio = fim
        roteiros[ARQUIVOS_GUIAS[voz]] = "\n".join(linhas)
    return roteiros


def guia_html(notas: list[Nota], titulos: list[str], *, amostra: bool = False) -> str:
    """Reúne os roteiros individuais em um documento autônomo para compartilhar."""
    slides_por_voz = _slides_por_voz(notas, titulos)
    atalhos = []
    secoes = []
    for i, (voz, tema) in enumerate(zip(VOZES, TEMAS_VOZES, strict=True), start=1):
        nome = escape(APRESENTADORES[voz])
        slides = slides_por_voz[voz]
        faixa = f"{slides[0][0]}–{slides[-1][0]}"
        atalhos.append(f'<li><a href="#voz-{i}">{nome}<span>Slides {faixa}</span></a></li>')
        inicio = 0
        roteiro = []
        apoio = []
        for numero, titulo, nota in slides:
            fim = inicio + nota.segundos
            paragrafos = "\n".join(f"<p>{escape(p)}</p>" for p in nota.fala.split("\n\n"))
            roteiro.append(
                f'<div class="slide">\n<p class="marcacao">Slide {numero} · '
                f"{_cronometro(inicio)}–{_cronometro(fim)}</p>\n"
                f"<h3>{escape(titulo)}</h3>\n{paragrafos}\n</div>"
            )
            if nota.apoio:
                itens = "\n".join(f"<li>{escape(ponto)}</li>" for ponto in nota.apoio)
                apoio.append(f"<h3>Slide {numero}</h3>\n<ul>\n{itens}\n</ul>")
            inicio = fim
        if apoio:
            roteiro.extend(("<details><summary>Se perguntarem</summary>", *apoio, "</details>"))
        secoes.append(
            "\n".join(
                (
                    f'<section class="voz" id="voz-{i}" aria-labelledby="nome-{i}">',
                    '<header class="voz-cabecalho">',
                    f'<div><h2 id="nome-{i}">{nome}</h2><p>{escape(tema)}</p></div>',
                    f'<p class="duracao">{_cronometro(inicio)} de fala</p>',
                    "</header>",
                    *roteiro,
                    "</section>",
                )
            )
        )
    total = sum(nota.segundos for nota in notas)
    modelo = Path(__file__).with_name("guia_de_fala.html").read_text(encoding="utf-8")
    return Template(modelo).substitute(
        titulo=escape(TITULO),
        total=_cronometro(total),
        margem=_cronometro(LIMITE_SEGUNDOS - total),
        amostra='<p class="amostra">Amostra sintética para teste.</p>' if amostra else "",
        atalhos="\n".join(atalhos),
        roteiros="\n".join(secoes),
    )


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
    roteiros = {"guia_de_fala.md": guia(notas, titulos), **guias_individuais(notas, titulos)}
    amostra = (ctx.caminhos.dados / MARCADOR).is_file()
    prefixo = "> Amostra sintética para teste.\n\n" if amostra else ""
    roteiros = {nome: prefixo + texto for nome, texto in roteiros.items()}
    roteiros["guia_de_fala.html"] = guia_html(notas, titulos, amostra=amostra)
    with tempfile.TemporaryDirectory(dir=ctx.caminhos.saida) as pasta:
        diretorio = Path(pasta)
        pptx = diretorio / "deck.pptx"
        prs.save(str(pptx))
        pdf = converter(pptx, diretorio / "deck.pdf")
        slides = contar_slides(pptx)
        paginas = contar_paginas(pdf)
        if slides != paginas:
            raise RuntimeError(f"deck.pdf tem {paginas} páginas e deck.pptx tem {slides} slides")
        for nome, texto in roteiros.items():
            (diretorio / nome).write_text(texto, encoding="utf-8")
        for arquivo in (pptx, pdf, *(diretorio / nome for nome in roteiros)):
            arquivo.replace(ctx.caminhos.saida / arquivo.name)
