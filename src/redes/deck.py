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
from lxml import etree
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
from redes.numeros import Numeros, decimal, percentual
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
    recorte = tabela.filter(
        (
            pl.col(coluna).cast(pl.String) == valor
            if isinstance(valor, str)
            else pl.col(coluna) == valor
        )
        for coluna, valor in filtros.items()
    )
    return recorte.row(0, named=True) if recorte.height else {}


def _numero(valor: float | None, casas: int = 3) -> str:
    return "n.d." if valor is None else decimal(valor, casas)


def _pp(valor: float | None, casas: int = 1) -> str:
    return "n.d." if valor is None else decimal(100 * valor, casas)


def _pct(valor: float | None, casas: int = 1) -> str:
    return "n.d." if valor is None else percentual(valor, casas)


def _pp_sinal(valor: float | None, casas: int = 2) -> str:
    if valor is None:
        return "n.d."
    texto = _pp(valor, casas)
    if valor > 0 and not texto.startswith("-") and any(c in "123456789" for c in texto):
        return f"+{texto} p.p."
    return f"{texto} p.p."


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
    tamanho: int | float = 22,
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


def _sem_estilo(forma) -> None:
    estilo = forma._element.find(qn("p:style"))
    if estilo is not None:
        forma._element.remove(estilo)


def _cor_hyperlink_tema(prs: Apresentacao, cor: str = "862F3D") -> None:
    """Altera as cores de hyperlink do tema para evitar o azul padrão no LibreOffice."""
    ns = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
    for mestre in prs.slide_masters:
        for rel in mestre.part.rels.values():
            if "theme" not in rel.reltype:
                continue
            raiz = etree.fromstring(rel.target_part.blob)
            alterou = False
            for tag in ("hlink", "folHlink"):
                no = raiz.find(f".//a:clrScheme/a:{tag}/a:srgbClr", ns)
                if no is not None:
                    no.set("val", cor)
                    alterou = True
            if alterou:
                rel.target_part.blob = etree.tostring(
                    raiz, xml_declaration=True, encoding="UTF-8", standalone=True
                )


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


def _bloco(
    slide,
    titulo: str,
    texto: str,
    x: float,
    y: float,
    largura: float,
    *,
    tamanho: int | float = 21,
    altura: float = 1.24,
) -> None:
    _texto(slide, titulo, x, y, largura, 0.34, tamanho=17, cor=ACCENT, forte=True)
    _texto(slide, texto, x, y + 0.40, largura, altura, tamanho=tamanho)


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
        _sem_estilo(ponto)
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
    _sem_estilo(ponto)
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
    placebo_tbl = _ler_tabela(pasta, "sensibilidade_placebo")
    comparaveis = _ler_tabela(pasta, "h2_comparaveis")
    auditoria_comp = _ler_tabela(pasta, "auditoria_h2_comparaveis")
    comp_h2 = _ler_tabela(pasta, "comparabilidade_h2")
    conc_gigante_h2 = _ler_tabela(pasta, "concentracao_gigante_h2")
    perfil = _ler_tabela(pasta, "rede_resumo")
    graus = _ler_tabela(pasta, "rede_graus")
    componentes = _ler_tabela(pasta, "rede_componentes")
    distancias_rede = _ler_tabela(pasta, "rede_distancias")
    links_pc1 = _ler_tabela(pasta, "links_pc1")
    descritivas = _ler_tabela(pasta, "descritivas_estimacao")
    h1_tab = _ler_tabela(pasta, "h1")
    h2_tab = _ler_tabela(pasta, "h2")
    h4_tab = _ler_tabela(pasta, "h4")
    escopo_tcesp = _ler_tabela(pasta, "sensibilidade_escopo_tcesp")
    sem_pessoal = _ler_tabela(pasta, "sensibilidade_sem_pessoal_ou_credor_publico")
    sem_auto = _ler_tabela(pasta, "sensibilidade_sem_autofinanciamento")
    apenas_set = _ler_tabela(pasta, "sensibilidade_apenas_setembro")
    robustez_tbl = _ler_tabela(pasta, "robustez")
    sens_gigante = _ler_tabela(pasta, "sensibilidade_gigante")
    val_tcesp = _ler_tabela(pasta, "validacao_tcesp")
    val_tse = _ler_tabela(pasta, "validacao_tse")
    val_panel = _ler_tabela(pasta, "validacao_panel")
    val_rfb = _ler_tabela(pasta, "validacao_rfb")
    ambig_rfb = _ler_tabela(pasta, "ambiguidade_rfb")
    figuras = caminhos.resultados / "figures"
    exemplo = figuras / "figura1_exemplo.png"
    prs = Presentation()
    _cor_hyperlink_tema(prs, "862F3D")
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
        "Vamos apresentar nosso estudo sobre redes empresariais, eleições municipais de 2024 em "
        "São Paulo e empenhos de 2025, cobrindo teoria, método, rede e resultados.",
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
        55,
        "Para Acemoglu, Johnson e Robinson (2005) e Acemoglu e Robinson (2008), grupos com "
        "interesses distintos disputam as regras econômicas. O poder formal, ou de jure, vem das "
        "instituições políticas, como o mandato de quem assume a prefeitura. O poder de fato vem "
        "dos recursos econômicos que permitem organizar e influenciar decisões.\n\n"
        "O diagrama resume por que esse poder pode persistir: quem detém poder político hoje "
        "influencia as regras econômicas, que moldam a distribuição de recursos, e quem acumula "
        "recursos hoje pode ampliar sua influência amanhã.",
        "No esquema completo de Acemoglu e Robinson (2008), o poder político também molda as "
        "instituições políticas futuras; em equilíbrio, elites capturam ou mantêm instituições "
        "favoráveis.",
        "Na literatura empírica no Brasil, Boas et al. (2014) encontram ganhos em contratos "
        "federais para doadoras do PT, enquanto Duarte (2025) obtém estimativas imprecisas para "
        "doadoras diretas em municípios; Guerra et al. (2025) analisam empresas após o fim das "
        "doações empresariais, e Balán et al. (2026) examinam laços familiares como poder "
        "corporativo.",
        "Sobre redes e burocracia: Jackson e Wolinsky (1996) formalizam a formação estratégica de "
        "redes e efeitos indiretos; Akhtari et al. (2022) mostram que a troca de governo gera "
        "rotatividade burocrática capaz de afetar contratos públicos.",
    )

    # 3. Aplicação
    escopo_2025 = _celula(escopo_tcesp, periodo="2025", recorte="amostra")
    frac_excluido = escopo_2025.get("fracao_excluido")
    val_total_2025 = _celula(val_tcesp, ano=2025, medida="valor_liquido", categoria="total").get(
        "valor"
    )
    val_pref_2025 = _celula(
        val_tcesp, ano=2025, medida="valor_por_tipo_orgao", categoria="PREFEITURA"
    ).get("valor")
    frac_nao_pref = (
        (val_total_2025 - val_pref_2025) / val_total_2025
        if val_total_2025 and val_pref_2025 is not None
        else None
    )
    taxa_vinc = numeros.valor("validacao_panel", ("", "vinculacao_valor_2025"), "valor")
    sem_pessoal_h1 = _celula(
        sem_pessoal,
        hipotese="H1",
        tipo="contraste",
        categoria="conectada_menos_sem_conexao",
        resultado="participacao_2025",
    )
    sem_pessoal_h2 = _celula(
        sem_pessoal,
        hipotese="H2",
        tipo="contraste",
        categoria="vencedor_faixa_1",
        resultado="participacao_2025",
    )
    slide = _pagina(prs, "A troca de governo muda a fatia das fornecedoras?", CONTEXTO)
    _bloco(
        slide,
        "Ligação direta ao incumbente (H1)",
        "Quando o grupo incumbente perde por pouco, as fornecedoras ligadas a ele perdem fatia?",
        MARGEM,
        1.90,
        5.42,
    )
    _traco(slide, 6.55, 1.88, 6.55, 3.46)
    _bloco(
        slide,
        "Distância ao incumbente e ao adversário (H2)",
        "Como a fatia das fornecedoras varia conforme a distância societária a cada candidatura?",
        MEIO,
        1.90,
        5.42,
    )
    _traco(slide, MARGEM, 3.64, LARGURA - MARGEM, 3.64)
    _bloco(
        slide,
        "Vínculos antes da eleição de 2024",
        "Sem doações empresariais (ADI 4650), ligamos fornecedoras às candidaturas pelas doações "
        "de sócios ou administradores (PF) e pela rede societária.",
        MARGEM,
        3.86,
        CORPO,
        tamanho=20,
        altura=1.08,
    )
    _bloco(
        slide,
        "Empenhos no primeiro ano após a eleição",
        "Órgãos municipais cobertos pelo TCESP, exceto a capital. Para cada fornecedora "
        "anterior, medimos a fatia no saldo líquido dos empenhos de 2025 por elemento de "
        "despesa, com entrantes no denominador.",
        MARGEM,
        5.38,
        CORPO,
        tamanho=20,
        altura=1.08,
    )
    _nota(
        notas,
        "Voz 1",
        65,
        "Aplicamos essa lógica às eleições para prefeito de 2024 em São Paulo. Primeiro (H1), "
        "perguntamos se a derrota apertada do grupo incumbente — que chamaremos de A — reduz a "
        "fatia de mercado de suas fornecedoras diretas. Segundo (H2), investigamos se essa "
        "vantagem prevista varia conforme a distância societária até A e até o principal "
        "adversário, B.\n\n"
        "Como o STF proibiu doações empresariais na ADI 4650, construímos os vínculos antes do "
        "voto cruzando doações de sócios ou administradores pessoas físicas com o quadro "
        "societário das empresas.\n\n"
        "Depois da eleição, medimos em 2025 a fatia de cada fornecedora anterior no saldo líquido "
        "dos empenhos do respectivo elemento de despesa no TCESP, com novas fornecedoras no "
        "denominador.",
        "A ADI 4650 (2015) proibiu doações de pessoas jurídicas; no TSE, usamos doações de "
        "pessoas físicas (inclusive autofinanciamento dos candidatos) e ligamos ao QSA da "
        "Receita Federal.",
        "Doações e vínculos societários medem conexão observada antes do pleito, e não "
        "influência política direta; a teoria motiva a hipótese.",
        "Nos dados do TCESP (excluída a capital), pessoal ou credores públicos somam "
        f"{_pct(frac_excluido)} do valor com CNPJ válido na amostra de 2025, órgãos fora das "
        f"prefeituras respondem por {_pct(frac_nao_pref)} do saldo líquido de 2025 e "
        f"{_pct(taxa_vinc)} do valor está ligado a ajustes; sem pessoal/credor público, as "
        f"estimativas seguem próximas (H1 {_estimativa_pp(sem_pessoal_h1)} e H2 a 1 passo "
        f"{_estimativa_pp(sem_pessoal_h2, 2)}).",
        "Testes adicionais de compensação dentro da rede e permanência no topo (H3 e H4) foram "
        "preservados apenas nas tabelas em results/tables/, fora do relatório e da apresentação.",
    )

    # 4. Hipóteses com o diagrama de exemplo
    mun_tse = _celula(val_tse, indicador="municipios_2024").get("valor")
    segundo_turno = _celula(val_tse, indicador="municipios_segundo_turno_2024").get("valor")
    sem_eleito = _celula(val_tse, indicador="eleicoes_sem_eleito_unico").get("valor")
    total_sp = mun_tse + 1 if mun_tse is not None else None
    slide = _pagina(
        prs,
        "Ligação direta e distância ao vencedor",
        HIPOTESES,
        "Prefeito · 1º turno de 2024 em SP (sem capital, 2º turno, ruptura — >1 candidato no ramo "
        "— ou ausência de A/B). Diagrama ilustrativo.",
    )
    faixa_ab = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(MARGEM), Inches(1.60), Inches(CORPO), Inches(1.06)
    )
    _sem_estilo(faixa_ab)
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
        60,
        "Definimos A e B em cada município de primeiro turno no interior paulista, sem a "
        "capital e sem ruptura — casos com mais de um candidato no ramo do prefeito. A é o "
        "candidato do grupo incumbente: primeiro o próprio prefeito, depois alguém do partido ou "
        "da coligação. B é o adversário mais votado entre os demais.\n\n"
        "No diagrama, doações de sócios tornam X semente de A e Z semente de B. Na H1, "
        "comparamos X a firmas sem caminho a A nem a B quando A perde por pouco. Na H2, "
        "examinamos se a vantagem ao vencedor cai com a distância societária; Y, por exemplo, "
        "está a um passo de cada candidatura.",
        f"De {_numero(total_sp, 0)} municípios paulistas ({_numero(mun_tse, 0)} fora a capital), "
        f"excluímos {_numero(segundo_turno, 0)} com 2º turno, {_numero(sem_eleito, 0)} sem "
        "eleito único anterior, além de rupturas (>1 candidato no ramo) e cidades sem A ou B "
        f"identificáveis, restando {_destaque(numeros, 'munAnalisaveis')} municípios analisáveis; "
        "a validade externa restringe-se a cidades menores decididas em 1º turno.",
        "O prefeito anterior é o eleito na última eleição antes de 06/10/2024 (incluindo "
        "suplementares); se concorre por outro partido, segue no ramo do prefeito. Nos degraus "
        "2 e 3 (partido ou coligação), trocas partidárias entre 2020 e 2024 podem gerar ruído.",
        "A hierarquia entre hipóteses na apresentação foi definida após a análise; H3 e H4 "
        "permanecem preservadas apenas nas tabelas em results/tables/, fora do relatório.",
    )

    # 5. Desenho empírico
    densidade_margem = (
        resumo.row(0, named=True).get("densidade_p_valor")
        if resumo is not None and resumo.height
        else None
    )
    bandas_h1_h2 = (
        resumo.filter(pl.col("hipotese").is_in(["H1", "H2"]) & pl.col("banda").is_not_null())[
            "banda"
        ]
        if resumo is not None and {"hipotese", "banda"} <= set(resumo.columns)
        else pl.Series(dtype=pl.Float64)
    )
    banda_min = _numero(bandas_h1_h2.min(), 1) if len(bandas_h1_h2) else "n.d."
    banda_max = _numero(bandas_h1_h2.max(), 1) if len(bandas_h1_h2) else "n.d."
    a0_nivel = _celula(
        h2_tab,
        hipotese="H2",
        tipo="categoria",
        categoria="faixa_a_0",
        resultado="participacao_2025",
    )
    a0_diff = _celula(
        placebo_tbl,
        hipotese="H2",
        tipo="categoria",
        categoria="faixa_a_0",
        resultado="variacao_participacao",
    )
    ep_a0_nivel = a0_nivel.get("ep_robusto")
    ep_a0_diff = a0_diff.get("ep_robusto")
    reducao_ep = (
        f"{_numero(100 * (1 - ep_a0_diff / ep_a0_nivel), 0)}%"
        if ep_a0_nivel and ep_a0_diff is not None
        else "n.d."
    )
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
        y = 3.94 + 0.41 * linha
        _texto(slide, simbolo, x, y, 0.25, 0.34, tamanho=18, cor=ACCENT, forte=True)
        _texto(slide, definicao, x + 0.35, y, 5.3, altura, tamanho=18)
    _texto(
        slide,
        "Unidade: empresa–município–elemento (peso igual por município). "
        "Ex.: R$ 10 de R$ 100 = 10% (entrantes no total).",
        MARGEM,
        5.68,
        CORPO,
        0.34,
        tamanho=15,
    )
    _texto(
        slide,
        f"{_destaque(numeros, 'munAnalisaveis')} municípios paulistas (sem capital, 2º turno, "
        "ruptura ou ausência de A/B). Ajuste linear local, placebos"
        + (
            f" e densidade da margem (p = {_numero(densidade_margem, 3)})."
            if densidade_margem is not None
            else "."
        ),
        MARGEM,
        6.14,
        CORPO,
        0.58,
        tamanho=15,
        cor=CINZA,
    )
    _nota(
        notas,
        "Voz 2",
        75,
        "Usamos uma regressão descontínua na margem de votos M: percentual de A menos percentual "
        "de B. À esquerda do zero, A perde e T vale um; à direita, A vence e T vale zero.\n\n"
        "A unidade é empresa, município e elemento de despesa, com peso igual por município por "
        "coorte. Se X recebeu dez reais de cem naquele elemento, sua fatia Y é de dez por cento, "
        "com entrantes no total.\n\n"
        "Ajustamos retas locais dentro da banda b: alfa é a fatia prevista na vitória, beta é o "
        "salto na derrota e gama e teta dão as inclinações, com erro u. Sob continuidade perto "
        "do corte, beta estima o efeito causal local. Checamos placebos pré-eleitorais e o teste "
        "de densidade da margem, sem evidência de manipulação.",
        "Na equação, T = 1 se M < 0 e T = 0 se M ≥ 0; usamos núcleo triangular, banda ótima pelo "
        f"EQM e correção robusta de viés (CCT), com bandas de {banda_min} a {banda_max} p.p. em "
        "H1 e H2 e checagens em b/2 e 2b.",
        "Cada município tem peso unitário por coorte (1/n_m para cada observação no município m), "
        "evitando que cidades maiores dominem a média.",
        f"Em primeiras diferenças (Y_2025 − Y_pré) na coorte direta a A, o erro-padrão cai "
        f"{reducao_ep} ({_pp(ep_a0_nivel, 2)} para {_pp(ep_a0_diff, 2)} p.p.), mantendo "
        f"estimativa nula ({_estimativa_pp(a0_diff, 2)}).",
        f"O teste de densidade de Cattaneo, Jansson e Ma (2020) deu "
        f"p = {_numero(densidade_margem, 3)}; contrastes entre coortes usam reamostragem "
        "municipal em bloco (999 réplicas) com bandas fixas.",
        "Fornecedora anterior é quem teve saldo líquido positivo na janela pré-eleitoral "
        "(2021–set/2024); o denominador de 2025 inclui todas as empresas com saldo positivo no "
        "elemento, inclusive entrantes.",
    )

    # 6. Fontes e estrutura da rede
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
    h1_a = _celula(resumo, hipotese="H1", tipo="categoria", categoria="conectada_incumbente")
    derrotas_a = h1_a.get("municipios_tratados")
    vitorias_a = h1_a.get("municipios_controle")
    pares_0_a = _celula(distancias_rede, variante="PRINCIPAL", grupo="A", faixa="0").get(
        "pares_empresa_municipio"
    )
    pf_501 = _celula(ambig_rfb, tipo_socio="PF", faixa_empresas="501+").get("pessoas")
    max_501 = _celula(ambig_rfb, tipo_socio="PF", faixa_empresas="501+").get("maximo")
    sem_rede_n = _celula(val_panel, variante="PRINCIPAL", medida="n_fornecedoras_sem_rede").get(
        "valor"
    )
    frac_pre_sem_rede = _celula(val_panel, variante="PRINCIPAL", medida="valor_pre_sem_rede").get(
        "valor"
    )
    cand_auto_a = _celula(links_pc1, indicador="candidatos_autofinanciados", grupo="A").get("valor")
    cand_auto_b = _celula(links_pc1, indicador="candidatos_autofinanciados", grupo="B").get("valor")
    so_auto_a = _celula(
        links_pc1, indicador="empresas_conectadas_so_por_autofinanciamento", grupo="A"
    ).get("valor")
    so_auto_b = _celula(
        links_pc1, indicador="empresas_conectadas_so_por_autofinanciamento", grupo="B"
    ).get("valor")
    vinc_out = _celula(val_rfb, medida="socios_linhas_por_origem", categoria="2024-10").get("valor")
    vinc_tot_rfb = _celula(val_rfb, medida="socios_linhas_gravadas", categoria="total").get("valor")
    frac_outubro = vinc_out / vinc_tot_rfb if vinc_out is not None and vinc_tot_rfb else None
    emp_preenchidas = _celula(
        val_rfb, medida="preenchimento_empresas", categoria="preenchidas"
    ).get("valor")
    data_socios0_raw = _celula(
        val_rfb, medida="arquivo_de_outra_extracao", categoria="Socios0.zip"
    ).get("valor")
    data_socios0 = (
        f"{str(int(data_socios0_raw))[6:8]}/{str(int(data_socios0_raw))[4:6]}/"
        f"{str(int(data_socios0_raw))[:4]}"
        if data_socios0_raw is not None
        else "n.d."
    )

    slide = _pagina(
        prs,
        "Uma rede societária para todos os municípios",
        REDE,
        f"Densidade bipartida: {_numero(por_milhao)} vínculo por milhão de pares · "
        f"Assortatividade r = {_numero(assortatividade, 4)} (sem padrão entre graus).",
    )
    faixa = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(MARGEM), Inches(1.58), Inches(CORPO), Inches(1.36)
    )
    _sem_estilo(faixa)
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
                "A firma é semente se um sócio ou administrador doou à candidatura local "
                "até 5/10/2024.",
            ),
            (
                "3. TCESP · Empenhos municipais",
                "Órgãos municipais cobertos pelo TCESP, exceto a capital. "
                "Fornecedoras: 2021–set/24; 2025: fatia do saldo líquido por elemento "
                "(entrantes no denominador).",
            ),
        )
    ):
        x = MARGEM + i * (largura_painel + 0.50)
        if i:
            _traco(slide, x - 0.25, 1.72, x - 0.25, 2.80)
        _texto(
            slide,
            titulo,
            x + 0.10,
            1.68,
            largura_painel - 0.16,
            0.28,
            tamanho=13,
            cor=ACCENT,
            forte=True,
        )
        _texto(slide, corpo, x + 0.10, 1.98, largura_painel - 0.16, 0.90, tamanho=13, cor=INK)

    _texto(
        slide,
        "Calculamos as ligações com A e B em cada município",
        MARGEM,
        3.10,
        CORPO,
        0.33,
        tamanho=17,
        cor=ACCENT,
        forte=True,
    )
    _texto(
        slide,
        "Z fornece nas duas cidades. As doações a A definem uma semente diferente em cada uma.",
        MARGEM,
        3.44,
        CORPO,
        0.30,
        tamanho=15,
    )
    for x, titulo, semente, corpo in (
        (MARGEM, "Município 1", "X", "Sócia de X doou a A. De X a Z, 2 passos."),
        (MEIO, "Município 2", "Y", "Sócio de Y doou a A. De Y a Z, 1 passo."),
    ):
        _texto(slide, titulo, x, 3.80, 5.42, 0.24, tamanho=14, forte=True)
        caminho = _texto(slide, "", x, 4.04, 5.42, 0.38, tamanho=21, forte=True)
        paragrafo = caminho.text_frame.paragraphs[0]
        for trecho in ("X", " — ", "Y", " — ", "Z"):
            run = paragrafo.add_run()
            run.text = f"{trecho} (semente)" if trecho == semente else trecho
            if trecho == semente:
                run.font.color.rgb = ACCENT
        _texto(slide, corpo, x, 4.48, 5.42, 0.28, tamanho=14, cor=CINZA)

    _traco(slide, MARGEM, 4.94, LARGURA - MARGEM, 4.94)
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
            _traco(slide, x - 0.25, 5.12, x - 0.25, 6.80)
        _texto(slide, titulo, x, 5.12, largura_painel, 0.32, tamanho=16, forte=True)
        for j, (rotulo, valor, proporcao) in enumerate(barras):
            _barra_proporcao(slide, rotulo, valor, proporcao, x, 5.52 + j * 0.54, largura_painel)
        if detalhe:
            _texto(slide, detalhe, x, 6.58, largura_painel, 0.25, tamanho=12, cor=CINZA)

    suporte_h1 = (
        _numero(derrotas_a + vitorias_a, 0)
        if derrotas_a is not None and vitorias_a is not None
        else "n.d."
    )
    _nota(
        notas,
        "Voz 3",
        65,
        "Cruzamos três bases: o cadastro nacional da Receita Federal, as doações ao TSE até 5 "
        "de outubro de 2024 e os empenhos do TCESP no interior paulista.\n\n"
        "No centro, mostramos como as distâncias são municipais: se uma sócia de X doou a A na "
        "cidade 1, Z fica a dois passos; se um sócio de Y doou a A na cidade 2, Z fica a um "
        "passo.\n\n"
        "A rede é muito esparsa e fragmentada, mas o maior componente conecta "
        f"{_destaque(numeros, 'fracGigante')} das empresas — percentual que cai para "
        f"{_destaque(numeros, 'fracGiganteSemArt')} sem sócios-ponte. Por fim, nem todos os "
        f"{_destaque(numeros, 'munConexaoA')} municípios com semente de A fornecem ao próprio "
        "município; só os com fornecedoras anteriores entram na estimação.",
        f"A Receita Federal liga {_destaque(numeros, 'empresasRede')} empresas a "
        f"{_destaque(numeros, 'pessoasRede')} vértices de sócios/administradores PF/PJ em "
        f"{_destaque(numeros, 'vinculosRede')} vínculos e "
        f"{_destaque(numeros, 'componentesRede')} componentes (grau médio {_numero(grau_medio, 2)} "
        f"para empresas e {_numero(grau_medio_pessoa, 2)} para sócios; densidade bipartida de "
        f"{_numero(por_milhao)} por milhão; assortatividade r = {_numero(assortatividade, 4)}).",
        f"Dos {_destaque(numeros, 'munConexaoA')} municípios com semente de A "
        f"({_destaque(numeros, 'munConexaoB')} para B), chegamos a {_numero(pares_0_a, 0)} pares "
        f"empresa–município fornecedores ligados diretamente a A, dos quais {suporte_h1} "
        f"municípios ({_numero(derrotas_a, 0)} derrotas e {_numero(vitorias_a, 0)} vitórias) "
        "entram na banda principal de H1.",
        f"Na ambiguidade de nomes da RFB, há {_numero(pf_501, 0)} pseudônimos PF em 501+ "
        f"empresas (máximo de {_numero(max_501, 0)} firmas); retirar pontes de articulação "
        f"({_destaque(numeros, 'fracGiganteSemArt')}) ou administradores "
        f"({_destaque(numeros, 'fracGiganteSemAdm')}) testa essa sensibilidade.",
        f"No painel, {_numero(sem_rede_n, 0)} fornecedoras anteriores sem QSA "
        f"({percentual(frac_pre_sem_rede) if frac_pre_sem_rede is not None else 'n.d.'} do valor "
        'pré-eleitoral) permanecem no grupo "Sem ligação".',
        f"Ligamos a empresas {_destaque(numeros, 'taxaCruzamentoA')} dos doadores de A e "
        f"{_destaque(numeros, 'taxaCruzamentoB')} dos de B; no autofinanciamento, "
        f"{_numero(cand_auto_a, 0)} candidatos A ({_numero(cand_auto_b, 0)} B) conectam "
        f"{_numero(so_auto_a, 0)} firmas A ({_numero(so_auto_b, 0)} B) só por recursos próprios.",
        f"A recomposição de outubro supre "
        f"{percentual(frac_outubro) if frac_outubro is not None else 'n.d.'} dos vínculos "
        f"({_numero(emp_preenchidas, 0)} empresas) porque Socios0.zip da pasta de setembro veio "
        f"da extração de {data_socios0}.",
    )

    # 7. Resultados de H1 (ligação direta)
    h1 = _celula(resumo, hipotese="H1", tipo="contraste")
    h1_sem = _celula(resumo, hipotese="H1", tipo="categoria", categoria="sem_conexao")
    h1_a_ep = _celula(
        h1_tab,
        hipotese="H1",
        tipo="categoria",
        categoria="conectada_incumbente",
        resultado="participacao_2025",
    ).get("ep_robusto")
    h1_c_ep = _celula(
        h1_tab,
        hipotese="H1",
        tipo="contraste",
        categoria="conectada_menos_sem_conexao",
        resultado="participacao_2025",
    ).get("ep_robusto")
    razao_ep = (
        f"{_numero(100 * (h1_c_ep / h1_a_ep - 1), 0)}%"
        if h1_a_ep and h1_c_ep is not None
        else "n.d."
    )
    pre_h1 = _celula(
        pre_periodos, hipotese="H1", tipo="contraste", categoria="conectada_menos_sem_conexao"
    )
    auto_h1 = _celula(
        sem_auto,
        hipotese="H1",
        tipo="contraste",
        categoria="conectada_menos_sem_conexao",
        resultado="participacao_2025",
    )
    set_h1 = _celula(
        apenas_set,
        hipotese="H1",
        tipo="contraste",
        categoria="conectada_menos_sem_conexao",
        resultado="participacao_2025",
    )
    rob_h1 = _celula(
        robustez_tbl,
        hipotese="H1",
        tipo="contraste",
        categoria="conectada_menos_sem_conexao",
        resultado="participacao_2025",
    )
    h4 = _celula(resumo, hipotese="H4", tipo="contraste", categoria="ligada_ao_vencedor_50")
    h4_det = _celula(
        h4_tab,
        hipotese="H4",
        tipo="contraste",
        categoria="ligada_ao_vencedor_50",
        resultado="mantem_posicao_50",
    )
    emd_h4 = h4.get("emd") if h4.get("emd") is not None else h4_det.get("emd")
    h3_ambos_gig = _celula(sens_gigante, coorte="H3_ambos").get("fracao_empenho_gigante")
    h4_a_gig = _celula(sens_gigante, coorte="H4_rdd_A_50").get("fracao_peso_gigante")
    h4_b_gig = _celula(sens_gigante, coorte="H4_rdd_B_50").get("fracao_peso_gigante")
    direta = _celula(descritivas, categoria="faixa_a_0")
    media_direta = direta.get("media_participacao_2025")
    emd_h1 = h1.get("emd")
    escala_emd = (
        f"{decimal(emd_h1 / media_direta, 1)} vezes a fatia média "
        f"({decimal(100 * media_direta, 2)}%) das fornecedoras ligadas a A na banda"
        if emd_h1 is not None and media_direta is not None and media_direta > 0
        else None
    )
    amostra_a = (
        f"{_numero(derrotas_a, 0)} municípios com A derrotado e "
        f"{_numero(vitorias_a, 0)} com A vitorioso"
        if derrotas_a is not None and vitorias_a is not None
        else None
    )
    frase_emd = ""
    if emd_h1 is not None:
        frase_emd = f" O efeito mínimo detectável é de {_pp(emd_h1)} p.p."
        if escala_emd is not None:
            frase_emd += f", que equivale a {escala_emd}."
        else:
            frase_emd += "."
    frase_amostra = (
        f" Na banda, a coorte ligada diretamente a A tem {amostra_a}, "
        "o que limita a precisão do contraste."
        if amostra_a is not None
        else ""
    )
    slide = _pagina(
        prs,
        "As fornecedoras ligadas a A perdem fatia (H1)?",
        RESULTADOS,
        "p.p.: fatia em 2025 por elemento. Categorias: IC robusto analítico (CCT); "
        "contraste: reamostragem municipal (999 réplicas).",
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
            legenda = (
                f"{rotulo} · {_numero(derrotas, 0)} municípios com derrota e "
                f"{_numero(vitorias, 0)} com vitória · banda de {banda} p.p."
            )
            _texto(
                slide,
                legenda,
                MARGEM,
                6.12 + i * 0.28,
                6.45,
                0.26,
                tamanho=12,
                cor=INK if i == 0 else CINZA,
                forte=i == 0,
            )
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
    if emd_h1 is not None:
        _texto(
            slide,
            f"Efeito mínimo detectável: {_pp(emd_h1)} p.p.",
            7.81,
            5.58,
            4.76,
            0.30,
            tamanho=14,
            cor=CINZA,
        )
        if escala_emd is not None:
            _texto(
                slide,
                f"Equivale a {escala_emd}.",
                7.81,
                5.88,
                4.76,
                0.56,
                tamanho=13,
                cor=CINZA,
            )
    _nota(
        notas,
        "Voz 3",
        70,
        "Na H1, comparamos o salto na fatia de 2025 das fornecedoras ligadas diretamente a A com "
        "o salto das empresas sem caminho a A nem a B, cada grupo em sua banda.\n\n"
        f"A estimativa do contraste foi de {_pp(h1.get('estimativa'))} pontos percentuais, com "
        f"intervalo de 95% de {_intervalo(h1)} pontos percentuais. {leitura_h1}"
        f"{frase_emd}{frase_amostra}",
        f"Ligadas a A: {_estimativa_pp(h1_a)} ({_ic_pp(h1_a)}, EP robusto CCT de "
        f"{_pp(h1_a_ep, 2)} p.p.); Sem ligação: {_estimativa_pp(h1_sem)} ({_ic_pp(h1_sem)}). "
        f"O contraste tem EP de {_pp(h1_c_ep, 2)} p.p. por reamostragem municipal (999 réplicas) — "
        f"cerca de {razao_ep} mais largo que o de Ligadas a A por combinar incerteza amostral "
        f"entre coortes com suporte assimétrico ({_numero(derrotas_a, 0)}/{_numero(vitorias_a, 0)} "
        "municípios).",
        "Os dois placebos de H1 incluem zero: nível pré-eleitoral de "
        f"{_pp_sinal(h1.get('placebo_estimativa'), 1)} "
        f"(p = {_numero(h1.get('placebo_p_valor'), 2)}) e tendência pré-eleitoral (2023–24 vs. "
        f"2021–22) de {_pp_sinal(pre_h1.get('estimativa'), 2)} "
        f"(p = {_numero(pre_h1.get('p_valor'), 2)}).",
        f"Sensibilidades de H1: meia banda {_pp_sinal(h1.get('estimativa_meia_banda'), 1)}, "
        f"dobro da banda {_pp_sinal(h1.get('estimativa_dobro_banda'), 1)}, sem autofinanciamento "
        f"{_estimativa_pp(auto_h1)}, apenas setembro {_estimativa_pp(set_h1)}, sem pontes "
        f"{_pp_sinal(rob_h1.get('estimativa_sem_articulacao'), 1)} e sem pessoal/credor público "
        f"{_estimativa_pp(sem_pessoal_h1)}",
        "H3 e H4 ficaram fora da apresentação principal e do relatório, preservadas apenas em "
        f"results/tables/: na H3, a coorte AMBOS concentra "
        f"{percentual(h3_ambos_gig, 2) if h3_ambos_gig is not None else 'n.d.'} do empenho no "
        f"gigante; na H4 a 50%, o EMD é {_pp(emd_h4)} p.p. numa escala de 0 a 100% e "
        f"{percentual(h4_a_gig, 0) if h4_a_gig is not None else 'n.d.'}/"
        f"{percentual(h4_b_gig, 0) if h4_b_gig is not None else 'n.d.'} do peso/empenho nas "
        "bandas está no gigante.",
    )

    # 8. Contrastes por distância
    h2 = {
        faixa: _celula(resumo, hipotese="H2", tipo="contraste", categoria=f"vencedor_faixa_{faixa}")
        for faixa in ("0", "1", "2", "3+")
    }
    pre_b = _celula(pre_periodos, hipotese="H2", tipo="categoria", categoria="faixa_b_1")
    pre_h2 = _celula(pre_periodos, hipotese="H2", tipo="contraste", categoria="vencedor_faixa_1")
    diff_h2_1 = _celula(
        placebo_tbl,
        hipotese="H2",
        tipo="contraste",
        categoria="vencedor_faixa_1",
        resultado="variacao_participacao",
    )
    set_h2_1 = _celula(
        apenas_set,
        hipotese="H2",
        tipo="contraste",
        categoria="vencedor_faixa_1",
        resultado="participacao_2025",
    )
    rob_h2_1 = _celula(
        robustez_tbl,
        hipotese="H2",
        tipo="contraste",
        categoria="vencedor_faixa_1",
        resultado="participacao_2025",
    )
    h2_1_det = _celula(
        h2_tab,
        hipotese="H2",
        tipo="contraste",
        categoria="vencedor_faixa_1",
        resultado="participacao_2025",
    )
    b1 = _celula(
        resumo,
        hipotese="H2",
        tipo="categoria",
        categoria="faixa_b_1",
        resultado="participacao_2025",
    )
    a1 = _celula(
        resumo,
        hipotese="H2",
        tipo="categoria",
        categoria="faixa_a_1",
        resultado="participacao_2025",
    )
    gig_b1 = _celula(conc_gigante_h2, recorte="principal", faixa="1", grupo="B", janela="h")
    gig_a1 = _celula(conc_gigante_h2, recorte="principal", faixa="1", grupo="A", janela="h")
    media_b1 = _celula(descritivas, categoria="faixa_b_1").get("media_participacao_2025")
    media_a1 = _celula(descritivas, categoria="faixa_a_1").get("media_participacao_2025")
    sobrep_0 = _celula(comp_h2, faixa="0").get("sobreposicao_mercado_porte")
    sobrep_1 = _celula(comp_h2, faixa="1").get("sobreposicao_mercado_porte")
    comp_b1 = _celula(
        comparaveis,
        hipotese="H2",
        tipo="categoria",
        categoria="faixa_b_1",
        resultado="participacao_2025",
    )
    destaque_h2 = "Testar se o efeito diminui exige comparar as faixas entre si."
    piso = piso_gigante_h2(pasta)
    comparavel_1 = _celula(
        comparaveis,
        hipotese="H2",
        tipo="contraste",
        categoria="vencedor_faixa_1",
        resultado="participacao_2025",
    )
    sem_suporte_1 = comparaveis is not None and not comparavel_1.get("estimavel", True)
    sinal_oposto = (h2["1"].get("estimativa") or 0) < 0
    slide = _pagina(
        prs,
        "Fatia em 2025 por distância a A e B",
        f"{RESULTADOS}  /  H2",
        "p.p.: pontos percentuais da fatia dos empenhos no elemento de despesa. "
        "ICs por reamostragem municipal. A é o incumbente e B, o adversário.",
    )
    _texto(
        slide,
        "Análise exploratória. Em cada distância, calculamos (salto de B − salto de A) ÷ 2 "
        "(> 0 = vantagem ao vencedor). Coortes pré-eleitorais podem compartilhar firmas.",
        MARGEM,
        1.54,
        CORPO,
        0.58,
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
        6.08,
        6.45,
        0.26,
        tamanho=13,
        cor=CINZA,
    )
    notas_esq_h2 = []
    if piso is not None:
        notas_esq_h2.append(f"A 3+ passos, ao menos {_pp(piso, 0)}% no gigante.")
    if sem_suporte_1:
        notas_esq_h2.append(
            "Estratos (município × elemento × quintil prévio): 1 passo sem suporte."
        )
    if notas_esq_h2:
        _texto(
            slide,
            " ".join(notas_esq_h2),
            MARGEM,
            6.38,
            6.45,
            0.46,
            tamanho=12,
            cor=CINZA,
        )
    _traco(slide, 7.43, 2.26, 7.43, 6.72)
    _texto(
        slide,
        "CONTRASTE A 1 PASSO EM 2025",
        7.75,
        2.26,
        4.83,
        0.26,
        tamanho=12,
        cor=ACCENT,
        forte=True,
    )
    _texto(
        slide,
        _estimativa_pp(h2["1"], 2),
        7.75,
        2.50,
        4.83,
        0.64,
        tamanho=36,
        fonte=FONTE_TITULO,
        cor=ACCENT,
    )
    _texto(
        slide,
        _ic_pp(h2["1"], 2),
        7.75,
        3.14,
        4.83,
        0.26,
        tamanho=13,
        forte=True,
    )
    if sinal_oposto:
        _texto(
            slide,
            "Sinal oposto ao previsto (> 0 = vantagem ao vencedor)",
            7.75,
            3.42,
            4.83,
            0.24,
            tamanho=12.5,
            cor=ACCENT,
            forte=True,
        )

    def _linha_coorte_h2(nome: str, linha: dict, gigante: dict) -> str:
        partes = []
        mun_t, mun_c = linha.get("municipios_tratados"), linha.get("municipios_controle")
        if mun_t is not None and mun_c is not None:
            partes.append(f"{_numero(mun_t, 0)}/{_numero(mun_c, 0)} mun.")
        peso_g = gigante.get("fracao_peso_gigante")
        if peso_g is not None:
            partes.append(f"{_pp(peso_g, 0)}% no gigante")
        detalhe = f" ({', '.join(partes)})" if partes else ""
        return f"{nome}: {_pp_sinal(linha.get('estimativa'), 2)}{detalhe}"

    _texto(
        slide,
        _linha_coorte_h2("B", b1, gig_b1),
        7.75,
        3.70,
        4.83,
        0.24,
        tamanho=12,
        cor=CINZA,
    )
    _texto(
        slide,
        _linha_coorte_h2("A", a1, gig_a1),
        7.75,
        3.94,
        4.83,
        0.24,
        tamanho=12,
        cor=CINZA,
    )
    _traco(slide, 7.75, 4.24, 12.58, 4.24)
    _texto(
        slide,
        "DIAGNÓSTICO E SENSIBILIDADE (1 PASSO)",
        7.75,
        4.34,
        4.83,
        0.26,
        tamanho=12,
        cor=ACCENT,
        forte=True,
    )
    b1_placebo = {"estimativa": b1.get("placebo_estimativa")}
    ic_diff = _intervalo(diff_h2_1, 2)
    sem_suporte = []
    if apenas_set is not None and not set_h2_1.get("estimavel", True):
        sem_suporte.append("set/24")
    if rob_h2_1 and rob_h2_1.get("estimativa_sem_articulacao") is None:
        sem_suporte.append("sem pontes")
    if rob_h2_1 and rob_h2_1.get("estimativa_sem_administrador") is None:
        sem_suporte.append("sem adm.")
    if sem_suporte_1:
        sem_suporte.append("estratos")
    diagnosticos = [
        f"• Pré-eleição em B: salto prévio de {_estimativa_pp(b1_placebo, 2)} (nível) e "
        f"{_estimativa_pp(pre_b, 2)} (tendência 2023–24 vs. 2021–22).",
        f"• Pós − pré (2025 − 2021–24): {_pp_sinal(diff_h2_1.get('estimativa'), 2)}"
        + (f" (IC {ic_diff})." if ic_diff != "n.d." else "."),
    ]
    if len(sem_suporte) > 1:
        diagnosticos.append(f"• Sem suporte em {', '.join(sem_suporte[:-1])} ou {sem_suporte[-1]}.")
    elif sem_suporte:
        diagnosticos.append(f"• Sem suporte em {sem_suporte[0]}.")
    for y_diag, linha_diag in zip((4.66, 5.32, 5.78), diagnosticos, strict=False):
        _texto(
            slide,
            linha_diag,
            7.75,
            y_diag,
            4.83,
            0.58,
            tamanho=12.5,
            cor=INK,
        )

    fragilidades_nota = []
    if apenas_set is not None and not set_h2_1.get("estimavel", True):
        fragilidades_nota.append("apenas setembro")
    if rob_h2_1 and rob_h2_1.get("estimativa_sem_articulacao") is None:
        fragilidades_nota.append("sem pontos de articulação")
    if rob_h2_1 and rob_h2_1.get("estimativa_sem_administrador") is None:
        fragilidades_nota.append("sem administradores")
    if h2_1_det and h2_1_det.get("estimativa_meia_banda") is None:
        fragilidades_nota.append("meia banda")
    apoio_fragilidades = (
        [f"Recortes sem estimação válida a 1 passo: {', '.join(fragilidades_nota)}."]
        if fragilidades_nota
        else []
    )
    _nota(
        notas,
        "Voz 4",
        85,
        "Na H2, olhamos a distância societária a A e a B antes da eleição e calculamos, em cada "
        "faixa, o salto de B menos o de A dividido por dois, em que valores positivos indicam "
        "vantagem ao vencedor.\n\n"
        f"A um passo, o contraste em 2025 foi de {_estimativa_pp(h2['1'], 2)}, com intervalo de "
        f"{_intervalo(h2['1'], 2)} — ou seja, sinal oposto ao previsto, puxado pela queda em B "
        f"({_estimativa_pp(b1, 2)}), enquanto A fica perto de zero "
        f"({_pp_sinal(a1.get('estimativa'), 2)}).\n\n"
        "Além disso, o recorte comparável por estratos fica sem suporte a um passo, e o "
        "diagnóstico pré-eleitoral mostra que B já apresentava salto negativo antes da eleição: "
        f"{_estimativa_pp(b1_placebo, 2)} em nível e {_estimativa_pp(pre_b, 2)} na tendência. "
        "Quando fazemos pós menos pré, o contraste passa para "
        f"{_pp_sinal(diff_h2_1.get('estimativa'), 2)}, com intervalo que inclui zero.",
        f"Decomposição a 1 passo: B tem {_estimativa_pp(b1, 2)} "
        f"(p de Holm = {_numero(b1.get('p_holm'))}, média na banda "
        f"{_pct(media_b1, 2)}) e A tem "
        f"{_pp_sinal(a1.get('estimativa'), 2)} (p de Holm = {_numero(a1.get('p_holm'))}, média "
        f"{_pct(media_a1, 2)}); os grupos diferem em porte.",
        "Três diagnósticos de 1 passo: nível pré-eleitoral de "
        f"{_estimativa_pp({'estimativa': h2['1'].get('placebo_estimativa')}, 2)} no contraste "
        f"({_estimativa_pp(b1_placebo, 2)} em B); tendência pré-eleitoral de "
        f"{_estimativa_pp(pre_h2, 2)} ({_estimativa_pp(pre_b, 2)} em B); e pós − pré de "
        f"{_pp_sinal(diff_h2_1.get('estimativa'), 2)} ({_ic_pp(diff_h2_1, 2)}).",
        *apoio_fragilidades,
        "Nos estratos (município × elemento × quintil prévio), a sobreposição de mercado e porte "
        f"é de {_pct(sobrep_0)} na faixa direta e {_pct(sobrep_1)} a 1 passo; no recorte "
        f"comparável a 1 passo restam {_numero(comp_b1.get('municipios_tratados'), 0)}/"
        f"{_numero(comp_b1.get('municipios_controle'), 0)} municípios, abaixo do mínimo de 10.",
        f"Na banda principal a 1 passo, o suporte é pequeno "
        f"({_numero(b1.get('redes_tratadas'), 0)}/{_numero(b1.get('redes_controle'), 0)} redes "
        f"em B; {_numero(a1.get('redes_tratadas'), 0)}/{_numero(a1.get('redes_controle'), 0)} "
        f"em A; p de rede = {_numero(b1.get('p_valor_rede'))}), com "
        f"{_pct(gig_b1.get('fracao_peso_gigante'))} do peso de B e "
        f"{_pct(gig_a1.get('fracao_peso_gigante'))} do peso de A no componente gigante.",
    )

    # 9. Conclusão
    gig_3_a = _celula(conc_gigante_h2, recorte="principal", faixa="3+", grupo="A", janela="h")
    gig_3_b = _celula(conc_gigante_h2, recorte="principal", faixa="3+", grupo="B", janela="h")
    comp_3 = _celula(
        comparaveis,
        hipotese="H2",
        tipo="contraste",
        categoria="vencedor_faixa_3+",
        resultado="participacao_2025",
    )
    aud_3 = _celula(auditoria_comp, faixa="3+")
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
            MSO_SHAPE.RECTANGLE, Inches(x_card), Inches(2.16), Inches(largura_card), Inches(3.72)
        )
        _sem_estilo(card)
        card.fill.solid()
        card.fill.fore_color.rgb = BRANCO
        card.line.color.rgb = LINHA
        card.line.width = Pt(0.8)

    # Card H1
    _texto(
        slide,
        "H1  ·  LIGAÇÃO DIRETA",
        x_h1 + 0.26,
        2.36,
        3.40,
        0.26,
        tamanho=12,
        cor=ACCENT,
        forte=True,
    )
    _selo(slide, "EM ABERTO", x_h1 + largura_card - 1.72, 2.30, 1.46)
    _texto(
        slide,
        _estimativa_pp(h1),
        x_h1 + 0.26,
        2.70,
        largura_card - 0.52,
        0.64,
        tamanho=38,
        fonte=FONTE_TITULO,
        cor=ACCENT,
    )
    _texto(
        slide,
        _ic_pp(h1),
        x_h1 + 0.26,
        3.36,
        largura_card - 0.52,
        0.26,
        tamanho=13,
        cor=CINZA,
    )
    _mini_barra_ic(slide, h1, x_h1 + 0.26, 3.72, largura_card - 0.52, 0.86)
    _texto(
        slide,
        "•  O intervalo inclui perdas e ganhos relevantes.",
        x_h1 + 0.26,
        4.80,
        largura_card - 0.52,
        0.34,
        tamanho=13.5,
        cor=INK,
    )
    if h1.get("emd") is not None:
        _texto(
            slide,
            f"•  Efeito mínimo detectável de {_pp(h1['emd'])} p.p.",
            x_h1 + 0.26,
            5.26,
            largura_card - 0.52,
            0.34,
            tamanho=13.5,
            cor=INK,
        )

    # Card H2
    _texto(
        slide,
        "H2  ·  DISTÂNCIA AO VENCEDOR",
        x_h2 + 0.26,
        2.36,
        3.40,
        0.26,
        tamanho=12,
        cor=ACCENT,
        forte=True,
    )
    _selo(slide, "EXPLORATÓRIO", x_h2 + largura_card - 2.08, 2.30, 1.82)
    _texto(
        slide,
        _estimativa_pp(h2["1"], 2),
        x_h2 + 0.26,
        2.70,
        largura_card - 0.52,
        0.64,
        tamanho=38,
        fonte=FONTE_TITULO,
        cor=ACCENT,
    )
    _texto(
        slide,
        f"{_ic_pp(h2['1'], 2)} · sinal oposto ao previsto" if sinal_oposto else _ic_pp(h2["1"], 2),
        x_h2 + 0.26,
        3.36,
        largura_card - 0.52,
        0.26,
        tamanho=12.5,
        cor=ACCENT if sinal_oposto else CINZA,
    )
    caixa_placebo = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE,
        Inches(x_h2 + 0.26),
        Inches(3.72),
        Inches(largura_card - 0.52),
        Inches(0.96),
    )
    _sem_estilo(caixa_placebo)
    caixa_placebo.fill.solid()
    caixa_placebo.fill.fore_color.rgb = PALIDO
    caixa_placebo.line.fill.background()
    usa_diff_h2 = diff_h2_1.get("estimativa") is not None
    linha_box = diff_h2_1 if usa_diff_h2 else pre_h2
    _texto(
        slide,
        "VARIAÇÃO PÓS − PRÉ (2025 − 2021–24)"
        if usa_diff_h2
        else "VARIAÇÃO PRÉ-ELEITORAL (2023–24 VS. 2021–22)",
        x_h2 + 0.44,
        3.82,
        3.44,
        0.22,
        tamanho=11,
        cor=CINZA,
        forte=True,
    )
    _texto(
        slide,
        "Contraste (B − A)/2 a 1 passo",
        x_h2 + 0.44,
        4.08,
        3.10,
        0.24,
        tamanho=12,
        cor=CINZA,
    )
    _texto(
        slide,
        _pp_sinal(diff_h2_1.get("estimativa"), 2) if usa_diff_h2 else _estimativa_pp(pre_h2, 2),
        x_h2 + largura_card - 2.16,
        3.88,
        1.72,
        0.46,
        tamanho=24,
        fonte=FONTE_TITULO,
        cor=ACCENT,
        forte=True,
        alinhar=PP_ALIGN.RIGHT,
    )
    _texto(
        slide,
        _ic_pp(linha_box, 2),
        x_h2 + 0.44,
        4.36,
        3.90,
        0.22,
        tamanho=11,
        cor=CINZA,
    )
    nivel_h2_1 = h2["1"].get("placebo_estimativa")
    texto_antes = (
        f"•  Antes do voto: {_estimativa_pp(pre_h2, 2)} na tendência e "
        f"{_pp(nivel_h2_1, 2)} p.p. no nível."
        if nivel_h2_1 is not None
        else f"•  Antes do voto: {_estimativa_pp(pre_h2, 2)} na tendência."
    )
    _texto(
        slide,
        texto_antes,
        x_h2 + 0.26,
        4.80,
        largura_card - 0.52,
        0.44,
        tamanho=12.5,
        cor=INK,
    )
    _texto(
        slide,
        "•  A queda do efeito com a distância segue em aberto.",
        x_h2 + 0.26,
        5.32,
        largura_card - 0.52,
        0.40,
        tamanho=12.5,
        cor=INK,
    )

    _traco(slide, MARGEM, 6.00, LARGURA - MARGEM, 6.00)
    _texto(slide, "LIMITAÇÕES", 0.75, 6.10, 1.35, 0.28, tamanho=11, cor=ACCENT, forte=True)
    taxa_a = numeros.valor("links_pc1", ("taxa_cruzamento", "A"), "valor")
    taxa_b = numeros.valor("links_pc1", ("taxa_cruzamento", "B"), "valor")
    parte_empenhos = (
        f"1 ano de empenhos ({percentual(frac_excluido)} pessoal/credores públicos; "
        f"{percentual(taxa_vinc)} ligados a ajustes)"
        if frac_excluido is not None and taxa_vinc is not None
        else "1 ano de empenhos"
    )
    parte_doadores = (
        f"cruzamento parcial de doadores ({percentual(taxa_a)} A; {percentual(taxa_b)} B) "
        "e firmas sem QSA"
        if taxa_a is not None and taxa_b is not None
        else "cruzamento parcial de doadores e firmas sem QSA"
    )
    _texto(
        slide,
        f"{parte_empenhos} · {parte_doadores} · componente gigante e troca burocrática.",
        2.10,
        6.08,
        10.483,
        0.44,
        tamanho=11.5,
        cor=CINZA,
    )
    link = _texto(
        slide,
        "Código e dados agregados",
        LARGURA - MARGEM - 2.60,
        6.58,
        2.60,
        0.34,
        tamanho=14,
        cor=ACCENT,
        alinhar=PP_ALIGN.RIGHT,
    )
    run = link.text_frame.paragraphs[0].runs[0]
    run.hyperlink.address = "https://github.com/rafaelt0/redes-empresariais-alternancia-politica"
    run.font.color.rgb = ACCENT
    _nota(
        notas,
        "Voz 4",
        50,
        "Para concluir, nenhuma das duas hipóteses se confirma de forma robusta. Em H1, a "
        f"estimativa de {_estimativa_pp(h1)} é imprecisa e admite efeitos grandes nos dois "
        f"sentidos. Em H2 a um passo, o contraste de {_estimativa_pp(h2['1'], 2)} tem sinal "
        "oposto ao esperado, já aparecia antes da eleição e vira "
        f"{_pp_sinal(diff_h2_1.get('estimativa'), 2)} na variação pós menos pré.\n\n"
        "Três limitações explicam essa cautela: um único ano de empenhos com contratos herdados "
        "e folha, cruzamento parcial de doadores e empresas sem QSA, e a concentração no "
        "componente gigante somada à troca burocrática. Obrigado.",
        f"Resumo H2 a 1 passo: {_estimativa_pp(h2['1'], 2)} em 2025, "
        f"{_pp_sinal(diff_h2_1.get('estimativa'), 2)} em pós − pré ({_ic_pp(diff_h2_1, 2)}) e "
        f"{_estimativa_pp(pre_h2, 2)} na tendência pré-eleitoral ({_ic_pp(pre_h2, 2)}).",
        f"A 3+ passos no painel principal, o contraste é "
        f"{_pp_sinal(h2['3+'].get('estimativa'), 2)} ({_ic_pp(h2['3+'], 2)}), mas ao menos "
        f"{_pp(piso, 0)}% das observações ({_pct(gig_3_a.get('fracao_peso_gigante'), 2)} do peso "
        f"de A e {_pct(gig_3_b.get('fracao_peso_gigante'), 2)} do de B) pertencem ao componente "
        "gigante.",
        f"Na auditoria do recorte comparável a 3+ passos, o contraste de "
        f"{_pp(comp_3.get('estimativa'), 3)} p.p. ({_ic_pp(comp_3, 3)}) decorre de sobreposição "
        f"de {_pct(aud_3.get('jaccard'))} (Jaccard) entre A e B nos "
        f"{_numero(aud_3.get('estratos'), 0)} estratos ({_pct(aud_3.get('na_banda_jaccard'))} "
        f"nas bandas), gerando correlação de {_numero(aud_3.get('correlacao_bootstrap'), 3)} no "
        f"bootstrap que reduz o EP de {_pp(aud_3.get('ep_contraste_sem_covariancia'), 3)} para "
        f"{_pp(aud_3.get('ep_contraste_bootstrap'), 3)} p.p.",
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
                    "**Na fala**",
                    "",
                    nota.fala,
                    "",
                )
            )
            if nota.apoio:
                linhas.extend(
                    ("**Se perguntarem**", "", *(f"- {ponto}" for ponto in nota.apoio), "")
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
