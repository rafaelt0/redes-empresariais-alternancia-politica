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
from redes.leitura_sensibilidades import leitura as leitura_sensibilidades
from redes.leitura_sensibilidades import piso_gigante_h2
from redes.numeros import Numeros, decimal, leitura_h2_comparaveis
from redes.portabilidade import ferramenta

ETAPA = Etapa(
    nome="deck",
    depende=("estimate",),
    le=(),
    grava=(),
    artefatos=("saida/deck.pptx", "saida/deck.pdf", "saida/guia_de_fala.md"),
)

MINIMO_SLIDES = 10
MAXIMO_SLIDES = 12
LIMITE_SEGUNDOS = 10 * 60
LARGURA, ALTURA = 13.333, 7.5
MARGEM = 0.75
CORPO = LARGURA - 2 * MARGEM
MEIO = 6.93
DIREITA = LARGURA - MARGEM - MEIO
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


def _linhas_robustez(robustez: pl.DataFrame | None) -> list[list[str]]:
    """Contrastes da análise de robustez em p.p. ou em % do empenho prévio."""
    variantes = ("principal", "sem_articulacao", "sem_pj", "sem_administrador")
    linhas = []
    for hipotese, filtros in (
        ("H1", {}),
        ("H2", {"categoria": "vencedor_faixa_0"}),
        ("H3", {"resultado": "variacao_total"}),
    ):
        linha = _celula(robustez, hipotese=hipotese, tipo="contraste", **filtros)
        linhas.append(
            [
                hipotese,
                *(
                    _efeito({k: linha.get(f"{k}_{v}") for k in ("estimativa", "ic_inf", "ic_sup")})
                    for v in variantes
                ),
            ]
        )
    return linhas


def construir(caminhos: Caminhos, numeros: Numeros) -> tuple[Apresentacao, list[Nota]]:
    pasta = caminhos.resultados / "tables"
    resumo = _ler_tabela(pasta, "resumo_estimacao")
    robustez = _ler_tabela(pasta, "robustez")
    pre_periodos = _ler_tabela(pasta, "sensibilidade_pre_periodos")
    comparaveis = _ler_tabela(pasta, "h2_comparaveis")
    concentracao = _ler_tabela(pasta, "sensibilidade_gigante")
    verificacoes = leitura_sensibilidades(pasta)
    exemplo = caminhos.resultados / "figures" / "figura1_exemplo.png"
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(LARGURA), Inches(ALTURA)
    notas: list[Nota] = []

    # 1. Capa
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = PALIDO
    _texto(slide, TITULO, MARGEM, 1.45, 10.8, 1.94, tamanho=51, fonte=FONTE_TITULO, forte=True)
    curso = "FEA-USP  /  EAE1429  /  REDES ECONÔMICAS E SOCIAIS"
    if (caminhos.dados / MARCADOR).is_file():
        curso += "  /  AMOSTRA SINTÉTICA"
    _texto(slide, curso, MARGEM, 0.66, CORPO, 0.32, tamanho=14, cor=ACCENT, forte=True)
    _texto(
        slide,
        "Evidências dos empenhos municipais no estado de São Paulo",
        MARGEM,
        3.66,
        CORPO,
        0.55,
        tamanho=24,
        cor=CINZA,
    )
    _traco(slide, MARGEM, 4.96, LARGURA - MARGEM, 4.96)
    for i, (nome, nusp) in enumerate(zip(AUTORES, NUSP, strict=True)):
        x, y = (MARGEM if i % 2 == 0 else MEIO), 5.25 + 0.49 * (i // 2)
        _texto(slide, f"{nome}  ·  {nusp}", x, y, 5.6, 0.33, tamanho=16)
    _texto(slide, "São Paulo, 2026", MARGEM, 6.72, 5.4, 0.3, tamanho=14, cor=CINZA)
    _nota(
        notas,
        "Voz 1",
        25,
        "Situar as eleições paulistas de 2024 e os empenhos de 2025. A prefeitura pode "
        "trocar de fornecedor e encontrar os mesmos sócios por trás do novo CNPJ.",
    )

    # 2. Pergunta e contribuição
    slide = _pagina(
        prs,
        "A troca de governo e os fornecedores municipais",
        "PERGUNTA DE PESQUISA",
        "Duarte (2025), Guerra, Mattos e Nakaguma (2025), Balán, Dodyk e Puente (2026).",
    )
    _texto(
        slide,
        "Quando o grupo no poder perde a eleição, as despesas da prefeitura passam "
        "a outras redes de empresas ou continuam nas mesmas?",
        MARGEM,
        1.98,
        11.0,
        0.88,
        tamanho=26,
        fonte=FONTE_TITULO,
        cor=ACCENT,
    )
    _traco(slide, MARGEM, 3.30, LARGURA - MARGEM, 3.30)
    _bloco(
        slide,
        "O que já se estudou",
        "Duarte estudou contratos de empresas doadoras e vínculos por sócios em comum "
        "em eleições municipais apertadas.",
        MARGEM,
        3.66,
        5.48,
    )
    _bloco(
        slide,
        "O que investigamos",
        "Partimos das empresas ligadas a doadores de campanha e seguimos os vínculos "
        "por sócios ou administradores em comum.",
        MEIO,
        3.66,
        DIREITA,
    )
    _texto(
        slide,
        "Em São Paulo, acompanhamos os empenhos de 2025 (compromissos de despesa) "
        "após as eleições municipais de 2024.",
        MARGEM,
        5.85,
        CORPO,
        0.62,
        tamanho=20,
        cor=CINZA,
    )
    _nota(
        notas,
        "Voz 1",
        50,
        "Mesmo que uma fornecedora perca espaço após a eleição, parte da despesa pode "
        "continuar na mesma rede se outra empresa ligada a ela ganhar participação. "
        "Usamos os empenhos de 2025 para investigar isso nas prefeituras paulistas após "
        "as eleições de 2024. Começamos pelas empresas ligadas a quem doou às campanhas "
        "como pessoa física. A partir delas, seguimos os vínculos por sócios ou "
        "administradores em comum. O próximo slide mostra como fazemos essa ligação.",
        "Duarte (2025) estudou disputas municipais de 2008 e 2012, encontrou estimativas "
        "imprecisas para doadoras diretas e explorou sócios em comum.",
        "Guerra, Mattos e Nakaguma (2025) associam a proibição de doações empresariais ao aumento "
        "do número de empresas em mercados municipais mais expostos. Balán et al. (2026) observam "
        "doações individuais de famílias controladoras em companhias abertas que já doavam.",
    )

    # 3. Dados e rede
    slide = _pagina(
        prs,
        "Como uma empresa se liga a uma candidatura",
        "DADOS E REDE",
        "Receita Federal, TSE e TCESP. Diagrama ilustrativo do relatório.",
    )
    _bloco(
        slide,
        "Ligação direta",
        "É semente a empresa cujo sócio ou administrador doa como pessoa física à "
        "candidatura local. Sua distância é zero.",
        MARGEM,
        2.08,
        4.65,
    )
    _bloco(
        slide,
        "Distância na rede",
        "Cada passo liga duas empresas com sócio ou administrador em comum. Contamos até a "
        "semente mais próxima.",
        MARGEM,
        4.23,
        4.65,
    )
    if exemplo.is_file():
        figura = slide.shapes.add_picture(
            str(exemplo), Inches(5.73), Inches(1.88), width=Inches(6.85)
        )
        figura._element.nvPicPr.cNvPr.set(
            "descr",
            "X liga-se a A por Ana e a Y por Bruno. Y liga-se a Z por Carla. "
            "Z liga-se a B por Daniel. Y está a um passo de A e de B.",
        )
    _texto(
        slide,
        "A representa o incumbente e B, o adversário mais votado. Y está a um passo da "
        "semente de cada grupo.",
        5.73,
        5.88,
        6.85,
        0.72,
        tamanho=18,
        cor=CINZA,
    )
    _nota(
        notas,
        "Voz 1",
        60,
        "Apontar as doações de Ana a A, o incumbente, e de Daniel a B, o adversário. X e Z "
        "são as sementes. Y compartilha sócios com X e Z, por isso está a um passo de cada grupo.",
        "Um passo entre empresas tem duas arestas no grafo bipartido. Onde não há caminho, "
        "a distância é infinita.",
        "TCESP: empenhos pela data do evento, de 2021 a 2025. TSE: doações de pessoas físicas "
        "até 5/10/2024, incluindo recursos próprios dos candidatos.",
        "Receita Federal: fotografia de setembro de 2024, com complemento de 12/10 apenas para "
        "quadros ausentes e vínculos iniciados até 13/09. Vínculos encerrados até a extração "
        "podem faltar. A leitura eleitoral exige continuidade desse erro perto do empate.",
    )

    # 4. Concentração da rede
    slide = _pagina(
        prs,
        "O maior componente da rede",
        "DADOS E REDE",
        "Receita Federal e TCESP. As porcentagens se referem a empresas.",
    )
    _texto(
        slide,
        f"No grafo de {_destaque(numeros, 'empresasRede')} empresas, cada componente reúne "
        "as que estão interligadas.",
        MARGEM,
        1.85,
        CORPO,
        0.68,
        tamanho=22,
    )
    for x, valor, rotulo in (
        (MARGEM, _destaque(numeros, "fracGigante"), "das empresas no componente gigante"),
        (
            MEIO,
            _destaque(numeros, "fracGiganteSemArt"),
            "das empresas no maior componente após a remoção",
        ),
    ):
        _texto(slide, valor, x, 2.78, 5.5, 1.15, tamanho=66, fonte=FONTE_TITULO, cor=ACCENT)
        _texto(slide, rotulo, x, 4.01, 5.1, 0.85, tamanho=22)
    _traco(slide, MARGEM, 5.12, LARGURA - MARGEM, 5.12)
    _texto(
        slide,
        "A segunda versão retira as pessoas cuja saída divide um componente.",
        MARGEM,
        5.48,
        10.8,
        0.64,
        tamanho=22,
        cor=CINZA,
    )
    _nota(
        notas,
        "Voz 2",
        35,
        "Comparar a parcela de empresas no componente gigante com a parcela no maior "
        "componente depois de retirar as pessoas que ligam partes da rede.",
        f"A rede principal tem {_destaque(numeros, 'empresasRede')} empresas, "
        f"{_destaque(numeros, 'pessoasRede')} vértices de sócios/administradores PF/PJ e "
        f"{_destaque(numeros, 'vinculosRede')} vínculos.",
        "Explicar um ponto de articulação voltando ao exemplo: se Bruno sair, X perde o "
        "caminho para Y e Z. Removê-lo muda quais empresas podem ficar na mesma coorte.",
        "Na reconstrução com a fotografia recente, "
        f"{_destaque(numeros, 'fracVinculosPerdidos')} dos vínculos de setembro ficam de fora e "
        f"{_destaque(numeros, 'fracVinculosExtras')} dos reconstruídos não constam em setembro.",
    )

    # 5. Desenho empírico
    slide = _pagina(
        prs,
        "Comparação perto do empate",
        "DESENHO EMPÍRICO",
        "Calonico, Cattaneo e Titiunik (2014) e Cattaneo, Jansson e Ma (2020).",
    )
    _texto(
        slide,
        "Margem do incumbente em votos válidos (p.p.)",
        MARGEM,
        1.95,
        CORPO,
        0.38,
        tamanho=18,
        cor=CINZA,
    )
    _texto(slide, "O incumbente perde", MARGEM, 2.67, 5.15, 0.52, tamanho=29, fonte=FONTE_TITULO)
    _texto(
        slide,
        "0",
        6.29,
        2.58,
        0.76,
        0.63,
        tamanho=36,
        cor=ACCENT,
        forte=True,
        alinhar=PP_ALIGN.CENTER,
    )
    _texto(
        slide,
        "O incumbente vence",
        7.44,
        2.67,
        5.14,
        0.52,
        tamanho=29,
        fonte=FONTE_TITULO,
        alinhar=PP_ALIGN.RIGHT,
    )
    _traco(slide, MARGEM, 3.30, LARGURA - MARGEM, 3.30, LINHA, 1.6)
    _traco(slide, LARGURA / 2, 3.18, LARGURA / 2, 3.43, ACCENT, 2.3)
    _texto(
        slide,
        "Se os resultados potenciais forem contínuos no empate, o salto de cada "
        "coorte estima o efeito local da derrota do incumbente.",
        MARGEM,
        3.91,
        11.25,
        1.10,
        tamanho=27,
        fonte=FONTE_TITULO,
        forte=True,
    )
    _texto(
        slide,
        f"{_destaque(numeros, 'munAnalisaveis')} municípios analisáveis. O suporte "
        "perto do empate varia por coorte.",
        MARGEM,
        5.67,
        CORPO,
        0.6,
        tamanho=20,
        cor=CINZA,
    )
    densidade = (
        resumo.row(0, named=True).get("densidade_p_valor")
        if resumo is not None and resumo.height
        else None
    )
    _nota(
        notas,
        "Voz 2",
        60,
        "Mostrar os dois lados do corte. Comparamos derrotas e vitórias por margem pequena. "
        "O salto estima o efeito local da derrota se os resultados potenciais forem "
        "contínuos no empate.",
        "A margem é A menos B. O prefeito candidato representa A. Na ausência dele, buscamos "
        "o candidato do seu partido e depois de uma coligação que inclua o partido. Excluímos "
        "capital, segundo turno e disputas sem A identificável ou sem adversário.",
        "Na regressão descontínua (RD), usamos ajuste linear local, núcleo triangular e banda "
        "escolhida pelo erro quadrático médio estimado. Antes do núcleo, o município tem peso "
        "um por coorte. Os ICs das coortes agrupam por município. Os contrastes reamostram os "
        "mesmos municípios por lado em todas as coortes e mantêm as bandas fixas.",
        f"O teste de densidade da margem deu p = {_numero(densidade)}. Também usamos placebos "
        "pré-eleitorais e verificamos sensibilidade à metade e ao dobro da banda.",
    )

    # 6. Conexão direta ao incumbente
    h1 = _celula(resumo, hipotese="H1", tipo="contraste")
    h1_titulo = (
        "A perda de espaço das ligadas ao incumbente é incerta"
        if _status(h1) == "inclui zero"
        else "Participação das ligadas ao incumbente"
    )
    slide = _pagina(
        prs,
        h1_titulo,
        "H1  /  CONEXÃO DIRETA AO INCUMBENTE",
        "Resultados agregados de 2025. IC de 95% por reamostragem municipal.",
    )
    _texto(slide, "Contraste no empate", MARGEM, 1.86, 5.8, 0.30, tamanho=17, forte=True)
    _texto(
        slide,
        _estimativa_pp(h1),
        MARGEM,
        2.17,
        5.8,
        1.27,
        tamanho=68,
        fonte=FONTE_TITULO,
        cor=ACCENT,
    )
    _texto(
        slide,
        _ic_pp(h1),
        MARGEM,
        3.58,
        5.8,
        0.6,
        tamanho=22,
    )
    _bloco(
        slide,
        "Quem entra na comparação",
        "Fornecedoras anteriores com ligação direta a A ou sem caminho a nenhuma candidatura.",
        MEIO,
        2.24,
        DIREITA,
    )
    _bloco(
        slide,
        "O que medimos",
        "A fatia de cada empresa nos empenhos de 2025 do seu elemento de despesa no município.",
        MEIO,
        4.15,
        DIREITA,
    )
    if (emd := h1.get("emd")) is not None:
        _traco(slide, MARGEM, 5.90, LARGURA - MARGEM, 5.90)
        _texto(
            slide,
            f"Efeito mínimo detectável de {_pp(emd)} p.p. com 80% de poder.",
            MARGEM,
            6.14,
            CORPO,
            0.52,
            tamanho=20,
            cor=CINZA,
        )
    _nota(
        notas,
        "Voz 2",
        40,
        "Comparar as fornecedoras anteriores ligadas diretamente ao incumbente com as sem "
        "caminho a nenhuma candidatura. Ler o contraste e explicar o que o intervalo permite.",
        "A hipótese é que a derrota reduza a participação das sementes de A em relação às "
        "fornecedoras sem caminho aos dois grupos. O contraste é o salto da primeira coorte "
        "menos o da segunda.",
        "Uma fornecedora anterior tem saldo líquido positivo de janeiro de 2021 a setembro de "
        "2024. No denominador de 2025 entram todos os saldos positivos, inclusive de entrantes. "
        "A participação é zero quando o denominador é zero.",
        f"O contraste com metade da banda foi "
        f"{_pp(h1.get('estimativa_meia_banda'))} p.p. e com o dobro, "
        f"{_pp(h1.get('estimativa_dobro_banda'))} p.p.",
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
    slide = _pagina(
        prs,
        h2_titulo,
        "H2  /  DISTÂNCIA ÀS CANDIDATURAS",
        "ICs por reamostragem municipal. A é o incumbente e B, o adversário.",
    )
    _texto(
        slide,
        "A cada distância, comparamos metade da diferença entre os saltos de B e de A.",
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
        "A hipótese prevê que a vantagem do vencedor diminua com a distância.",
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
        "Voz 3",
        50,
        "Explicar a comparação dos saltos por distância. Ler o contraste a um passo de 2025 "
        "e o placebo da coorte B. Dar aos dois números o tempo necessário para explicar "
        "por que a diferença anterior à eleição importa para a leitura causal.",
        "A previsão era uma vantagem positiva da ligação ao vencedor que diminuísse com a "
        "distância. A interpretação exige coortes comparáveis e efeitos simétricos de ganhar e "
        "perder a ligação. A mesma firma pode entrar nas duas coortes.",
        f"A um passo, o salto de B em 2025 foi {_pp(b1.get('estimativa'), 2)} p.p. "
        f"(p de Holm = {_numero(b1.get('p_holm'))}). O IC do contraste é nominal. A correção "
        "de Holm se aplica ao salto de B na família de testes secundários.",
        "O placebo da coorte B mede a mudança de participação de 2021–2022 para "
        "2023–setembro de 2024. Ele é distinto do placebo de nível pré do contraste.",
    )

    # 8. Sensibilidades dos contrastes por distância
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
        "O contraste sob outras especificações",
        "H2  /  TESTES DE ROBUSTEZ",
        "Participação no elemento de despesa. Os contrastes usam ICs nominais.",
    )
    _texto(slide, "A um passo", MARGEM, 1.90, 6.3, 0.42, tamanho=23, forte=True)
    _tabela(
        slide,
        ["Especificação", "Contraste (p.p.)", "IC de 95% (p.p.)"],
        [
            [rotulo, _pp(linha.get("estimativa"), 2), _intervalo(linha, 2)]
            for rotulo, linha in (
                ("2025", h2["1"]),
                ("Pós menos pré", pos_menos_pre),
                ("Sem autofinanciamento", sem_auto),
            )
        ],
        MARGEM,
        2.49,
        (3.00, 1.69, 1.86),
        0.57,
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
            "Com o cadastro só de setembro, o contraste a um passo fica sem suporte.",
            MARGEM,
            5.14,
            6.55,
            0.97,
            tamanho=20,
            cor=CINZA,
        )
    _traco(slide, 7.62, 1.9, 7.62, 6.25)
    _texto(slide, "A três passos ou mais", 8.01, 1.90, 4.57, 0.42, tamanho=23, forte=True)
    _texto(
        slide,
        _estimativa_pp(h2["3+"], 2),
        8.01,
        2.61,
        4.57,
        0.77,
        tamanho=43,
        fonte=FONTE_TITULO,
        cor=ACCENT,
    )
    _texto(
        slide,
        _ic_pp(h2["3+"], 2),
        8.01,
        3.45,
        4.57,
        0.45,
        tamanho=19,
    )
    piso = piso_gigante_h2(pasta)
    if piso is not None:
        _texto(
            slide,
            f"Ao menos {_pp(piso, 0)}% das observações nas bandas principais e comparáveis "
            "pertencem ao gigante. A precisão depende da inferência municipal.",
            8.01,
            4.26,
            4.57,
            1.91,
            tamanho=19,
            cor=CINZA,
        )
    recorte = (
        leitura_h2_comparaveis(comparaveis.iter_rows(named=True)) if comparaveis is not None else ""
    )
    _nota(
        notas,
        "Voz 3",
        40,
        "Mostrar o que acontece com o contraste a um passo quando mudam o desfecho e a "
        "amostra. À direita, explicar por que a concentração no componente gigante "
        "limita a leitura a três passos ou mais.",
        "Pós menos pré usa a diferença entre a participação de 2025 e a pré-eleitoral. "
        "O placebo anterior usa a mudança entre dois períodos anteriores à eleição.",
        f"A sobreposição por município, elemento de despesa e quintil de porte entre as "
        f"coortes de ligação direta é de {_destaque(numeros, 'sobreposicaoDireta')}.",
        *((recorte,) if recorte else ()),
        "O intervalo a três passos ou mais pressupõe inferência municipal. A mesma rede "
        "pode gerar dependência entre municípios.",
    )

    # 9. Compensação dentro das redes
    ligados = _celula(
        resumo, hipotese="H3", tipo="categoria", categoria="ambos", resultado="variacao_total"
    )
    total_h3 = _celula(resumo, hipotese="H3", tipo="contraste", resultado="variacao_total")
    r1 = _celula(resumo, hipotese="H3", tipo="categoria", categoria="ambos", resultado="termo_r1")
    r23 = _celula(
        resumo, hipotese="H3", tipo="categoria", categoria="ambos", resultado="termo_compensacao"
    )
    compensacao = _status(r1) == "negativo" and _status(r23) == "positivo"
    ambos_imprecisos = _status(r1) == _status(r23) == "inclui zero"
    sinais_opostos = (r1.get("estimativa") or 0) > 0 > (r23.get("estimativa") or 0)
    slide = _pagina(
        prs,
        "A compensação fica em aberto" if ambos_imprecisos else "Redistribuição dentro da rede",
        "H3  /  REDES LIGADAS ÀS DUAS CANDIDATURAS",
        "Os saltos estão em % do empenho anual médio pré-eleitoral do município.",
    )
    _texto(
        slide,
        "Para haver compensação, as fornecedoras anteriores ligadas diretamente ao "
        "incumbente teriam de perder espaço e as demais da rede, ganhar.",
        MARGEM,
        1.9,
        CORPO,
        0.87,
        tamanho=23,
    )
    _tabela(
        slide,
        ["Empresas em redes ligadas a A e B", "Sinal previsto", "Salto (%)", "IC de 95% (%)"],
        [
            [
                "Anteriores ligadas diretamente a A (R1)",
                "Negativo",
                _pp(r1.get("estimativa"), 2),
                _intervalo(r1, 2),
            ],
            [
                "Demais empresas da rede (R2 + R3)",
                "Positivo",
                _pp(r23.get("estimativa"), 2),
                _intervalo(r23, 2),
            ],
        ],
        MARGEM,
        3.10,
        (5.45, 2.05, 1.72, 2.60),
        0.61,
        17,
    )
    if ambos_imprecisos:
        mensagem = "Os dois intervalos incluem zero."
        if sinais_opostos:
            mensagem = "Os sinais contrariam a previsão. Os dois intervalos incluem zero."
        _texto(slide, mensagem, MARGEM, 5.29, CORPO, 0.75, tamanho=23, cor=ACCENT, forte=True)
    gigante = _celula(concentracao, coorte="H3_ambos")
    peso = gigante.get("fracao_peso_gigante")
    empenho = gigante.get("fracao_empenho_gigante")
    if peso is not None or empenho is not None:
        parcela = (
            f"{_pp(peso)}% do peso municipal"
            if peso is not None
            else f"{_pp(empenho, 2)}% do empenho prévio"
        )
        _texto(
            slide,
            f"Na banda de estimação, o gigante concentra {parcela} dessas redes.",
            MARGEM,
            6.20,
            CORPO,
            0.52,
            tamanho=18,
            cor=CINZA,
        )
    _nota(
        notas,
        "Voz 3",
        45,
        "Explicar o que seria compensação. Nas redes ligadas a ambos, o primeiro grupo "
        "teria de perder espaço e o restante ganhar. Comparar os sinais previstos e os "
        "observados e apontar os intervalos.",
        "R1 são as fornecedoras anteriores diretamente ligadas a A. R2 são as demais "
        "fornecedoras anteriores. R3 são as novas. Os termos somam a mudança total da rede, "
        "normalizada pelo empenho anual médio pré-eleitoral do município.",
        f"O contraste do total, redes ligadas a ambos menos as demais, foi {_efeito(total_h3, 2)}% "
        "do empenho prévio (estimativa e IC de 95%). Na tela estão os saltos dentro de AMBOS.",
        f"Placebo de nível pré-eleitoral dentro de AMBOS: "
        f"{_pp(ligados.get('placebo_estimativa'), 2)} p.p. "
        f"(p nominal = {_numero(ligados.get('placebo_p_valor'), 4)}). Para o contraste do total: "
        f"{_pp(total_h3.get('placebo_estimativa'), 2)} p.p. "
        f"(p nominal = {_numero(total_h3.get('placebo_p_valor'))}).",
    )

    # 10. Permanência das principais redes
    h4 = {
        pct: _celula(resumo, hipotese="H4", tipo="contraste", categoria=f"ligada_ao_vencedor_{pct}")
        for pct in (25, 50, 75)
    }
    central = h4[50]
    holm = central.get("p_holm")
    slide = _pagina(
        prs,
        "Permanência entre as principais redes",
        "H4  /  LIMIAR DE 50%",
        "Resultados exploratórios. O contraste usa redes com ligação exclusiva.",
    )
    _texto(
        slide,
        "O ranking soma empenhos até 50% do total municipal de cada período, incluindo "
        "a rede que cruza o limiar.",
        MARGEM,
        1.72,
        CORPO,
        0.87,
        tamanho=21,
    )
    _texto(
        slide,
        "No pré, o saldo precisa ser positivo em pelo menos três dos quatro anos. "
        "Em 2025, entram também as novas redes.",
        MARGEM,
        2.59,
        CORPO,
        0.67,
        tamanho=19,
        cor=CINZA,
    )
    _bloco(
        slide,
        "Médias a até cinco p.p. do empate",
        "Permanência no ranking de 2025, por situação de ligação ao vencedor.",
        MARGEM,
        3.55,
        5.85,
    )
    for x, valor, rotulo in (
        (MARGEM, _destaque(numeros, "permanenciaComLigacao"), "Com ligação"),
        (3.45, _destaque(numeros, "permanenciaSemLigacao"), "Sem ligação"),
    ):
        _texto(slide, valor, x, 4.92, 2.55, 0.73, tamanho=43, fonte=FONTE_TITULO, cor=ACCENT)
        _texto(slide, rotulo, x, 5.75, 2.55, 0.38, tamanho=18, cor=CINZA)
    _traco(slide, 6.54, 3.55, 6.54, 6.28)
    _texto(
        slide,
        "Contraste no empate via RD",
        MEIO,
        3.55,
        DIREITA,
        0.41,
        tamanho=17,
        cor=ACCENT,
        forte=True,
    )
    _texto(
        slide,
        _estimativa_pp(central),
        MEIO,
        4.06,
        DIREITA,
        0.82,
        tamanho=43,
        fonte=FONTE_TITULO,
    )
    _texto(
        slide,
        _ic_pp(central),
        MEIO,
        4.94,
        DIREITA,
        0.50,
        tamanho=20,
    )
    h4_leitura = f"Após a correção de Holm, p = {_numero(holm)}."
    if holm is not None and holm >= 0.05:
        h4_leitura = f"Estimativa inconclusiva após correção de Holm (p = {_numero(holm)})."
    _texto(slide, h4_leitura, MEIO, 5.56, DIREITA, 0.75, tamanho=20, cor=CINZA)
    if all(
        _celula(concentracao, coorte=f"H4_rdd_{grupo}_50").get("fracao_peso_gigante") == 1
        for grupo in ("A", "B")
    ):
        _texto(
            slide,
            "O componente gigante ocupa integralmente as duas coortes nas bandas do RD.",
            MARGEM,
            6.53,
            CORPO,
            0.36,
            tamanho=16,
            cor=CINZA,
        )
    _nota(
        notas,
        "Voz 4",
        50,
        "Explicar como o ranking de 50% inclui a rede que cruza o limiar. As médias à "
        "esquerda descrevem as disputas próximas. O contraste à direita compara os "
        "saltos de coortes exclusivas e tem um intervalo amplo.",
        "O ranking pré exige saldo positivo em pelo menos três dos quatro anos pré-eleitorais. "
        "Se as elegíveis ficarem abaixo do limiar, todas entram. Em 2025 entram todas as "
        "redes de saldo positivo, inclusive estreantes. Usamos o mesmo percentual sobre "
        "o total de cada período.",
        "As médias na janela incluem as quatro categorias de ligação. O contraste de RD é "
        "metade da diferença dos saltos de redes ligadas só a B e só a A. A leitura como "
        "vantagem do vencedor exige comparabilidade e simetria.",
        f"Estimativas e ICs de 95% em p.p. nos outros limiares: 25%, {_efeito(h4[25])} "
        f"e 75%, {_efeito(h4[75])}. No limiar de 50%, o EMD é de "
        f"{_pp(central.get('emd'))} p.p. e o IC amplo indica instabilidade.",
        *(f for f in verificacoes if f.startswith("Em H4")),
    )

    # 11. Robustez das definições de rede
    slide = _pagina(
        prs,
        "O que muda com outras definições de rede",
        "ROBUSTEZ",
        "ICs de 95% por reamostragem municipal. n.d. indica contraste sem estimativa.",
    )
    _texto(
        slide,
        "Estimativas e intervalos de confiança nos quatro grafos",
        MARGEM,
        1.86,
        CORPO,
        0.46,
        tamanho=21,
    )
    linhas = _linhas_robustez(robustez)
    for linha, rotulo in zip(
        linhas, ("Ligação direta (H1)", "Distância zero (H2)", "Total da rede (H3)"), strict=True
    ):
        linha[0] = rotulo
    _tabela(
        slide,
        [
            "Contraste",
            "Principal",
            "Sem pontos de\narticulação",
            "Sem sócios PJ",
            "Sem\nadministradores",
        ],
        linhas,
        MARGEM,
        2.57,
        (2.34, 2.35, 2.42, 2.30, 2.41),
        0.70,
        16,
    )
    _texto(
        slide,
        "As duas primeiras linhas estão em p.p. A terceira está em % do empenho "
        "anual médio pré-eleitoral do município.",
        MARGEM,
        5.72,
        CORPO,
        0.82,
        tamanho=20,
        cor=CINZA,
    )
    _nota(
        notas,
        "Voz 4",
        40,
        "Escolher a linha do total da rede para mostrar como a definição do grafo muda "
        "os intervalos e o próprio suporte da comparação.",
        "Mudar a rede também altera caminhos, sementes, composição das coortes e suporte. "
        "Na versão sem pontos de articulação, as sementes foram selecionadas de novo.",
        "Quando o total fica sem estimativa, verificar quantos municípios restam de cada lado.",
        *(
            f
            for f in verificacoes
            if f.startswith(("Sem o gigante", "Pessoal ou credores", "Sem esses empenhos"))
        ),
    )

    # 12. Fechamento
    slide = _pagina(
        prs,
        "A persistência dos empenhos após a alternância",
        "CONCLUSÃO",
        "Eleições municipais paulistas de 2024 e empenhos de 2025.",
        fundo=PALIDO,
    )
    fechamento = (
        "Nas redes ligadas às duas candidaturas, os resultados apontam para compensação interna."
        if compensacao
        else (
            "As estimativas deixam em aberto a vantagem da ligação ao vencedor "
            "e a compensação dentro da rede."
        )
    )
    _texto(slide, fechamento, MARGEM, 1.98, 10.8, 1.63, tamanho=34, fonte=FONTE_TITULO, cor=ACCENT)
    _traco(slide, MARGEM, 3.81, LARGURA - MARGEM, 3.81)
    _bloco(
        slide,
        "Alcance",
        "A comparação se refere às disputas apertadas de um único ciclo eleitoral. Para "
        "algumas coortes, quase toda a informação vem de uma só rede.",
        MARGEM,
        4.26,
        5.48,
    )
    _bloco(
        slide,
        "Medida",
        "Os empenhos incluem despesas com pessoal e credores públicos. O cadastro captura "
        "vínculos formais e só parte dos doadores foi ligada a empresas.",
        MEIO,
        4.26,
        DIREITA,
    )
    link = _texto(
        slide,
        "Código, dados agregados e instruções de reprodução",
        MARGEM,
        6.32,
        CORPO,
        0.37,
        tamanho=16,
        cor=ACCENT,
    )
    run = link.text_frame.paragraphs[0].runs[0]
    run.hyperlink.address = "https://github.com/rafaelt0/redes-empresariais-alternancia-politica"
    run.font.color.rgb = ACCENT
    _nota(
        notas,
        "Voz 4",
        45,
        "Responder à pergunta da abertura. Dizer o que as estimativas permitem concluir "
        "sobre a vantagem eleitoral e a compensação. Lembrar que a comparação vale para "
        "disputas apertadas de um único ciclo.",
        "Retomar a pergunta da abertura. A leitura do contraste a um passo depende da "
        "especificação. Os intervalos amplos em várias comparações admitem efeitos relevantes. "
        "A concentração em uma rede pode gerar dependência entre municípios.",
        f"Foi possível ligar a empresas {_destaque(numeros, 'taxaCruzamentoA')} dos doadores de A "
        f"e {_destaque(numeros, 'taxaCruzamentoB')} dos de B. "
        "Vínculos informais ficam fora do cadastro.",
        "A alternância também pode mudar a burocracia municipal, como estudado por Akhtari, "
        "Moreira e Trucco (2022). O possível efeito desse canal nos empenhos fica em aberto.",
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
    bloco = por_voz[VOZES[0]]
    acumulados = accumulate(nota.segundos for nota in notas)
    linhas = [
        "# Guia de fala",
        "",
        f"**Fala prevista de {_cronometro(total)}**, em {len(por_voz)} blocos iguais de "
        f"{_cronometro(bloco)}. Reserve {_cronometro(margem)} para trocas de apresentador e "
        f"variações de ritmo, dentro do limite de {_cronometro(LIMITE_SEGUNDOS)}. Os tempos "
        "acumulados servem de referência no ensaio. A definição de quem apresenta cada bloco "
        "fica para a reunião.",
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
    for i, (titulo, nota) in enumerate(zip(titulos, notas, strict=True), start=1):
        linhas += [
            f"## {i}. {titulo} — {nota.pessoa} ({nota.segundos} s)",
            "",
            "**Na fala**",
            "",
            nota.fala,
            "",
        ]
        if nota.apoio:
            linhas += ["**Se perguntarem**", "", *(f"- {ponto}" for ponto in nota.apoio), ""]
    linhas += [
        "## Divisão",
        "",
        f"Blocos iguais de {_cronometro(bloco)}, sem nomes definidos.",
        "",
        *[
            f"- {voz} (slides {slides[voz][0]}–{slides[voz][-1]}): {segundos} s"
            for voz, segundos in por_voz.items()
        ],
        "",
    ]
    return "\n".join(linhas)


def executar(ctx: Contexto) -> None:
    reconstrucoes = () if (ctx.caminhos.dados / MARCADOR).is_file() else ("reconstrucao",)
    ctx.caminhos.exigir_resultados(
        (
            "resumo_estimacao",
            "robustez",
            "rede_resumo",
            "links_pc1",
            "comparabilidade_h2",
            "h2_comparaveis",
            "permanencia_h4",
            *reconstrucoes,
        ),
        ("figura1_exemplo",),
        "png",
    )
    numeros = Numeros.ler(ctx.caminhos.resultados / "tables")
    prs, notas = construir(ctx.caminhos, numeros)
    if not MINIMO_SLIDES <= len(prs.slides) <= MAXIMO_SLIDES:
        raise RuntimeError(f"deck com {len(prs.slides)} slides; o esperado é de 10 a 12")
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
