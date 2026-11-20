"""Etapa `deck`: `.pptx`, `.pdf` por conversão do LibreOffice e guia de fala (T20).

O deck é montado a partir das tabelas de `resultados/` — nenhum número é digitado à mão — e das
figuras em `resultados/figures`. A interpretação de cada hipótese é escolhida pela posição do
intervalo em relação a zero: o mesmo texto que hoje diz "não distinguível de zero" passa a dizer
"positivo" ou "negativo" se a estimativa mudar, e o deck é regenerado com os números novos.

`output/deck.pdf` é a conversão do `.pptx`; a etapa falha se o número de páginas do PDF não for o
de slides do `.pptx` (critério 8 da especificação). O guia de fala traz, por slide, os pontos a
cobrir, o tempo sugerido e a pessoa responsável, sem texto para leitura.
"""

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import polars as pl
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

from redes.amostra import MARCADOR
from redes.config import Caminhos
from redes.etapas import Contexto, Etapa
from redes.leitura_sensibilidades import leitura as leitura_sensibilidades
from redes.leitura_sensibilidades import limite_h2
from redes.numeros import Numeros, decimal, leitura_h2_comparaveis

ETAPA = Etapa(
    nome="deck",
    depende=("estimate",),
    le=(),
    grava=(),
    artefatos=("saida/deck.pptx", "saida/deck.pdf", "saida/guia_de_fala.md"),
)

MINIMO_SLIDES = 10
MAXIMO_SLIDES = 12

LARGURA, ALTURA = Inches(13.333), Inches(7.5)
MARGEM = Inches(0.75)
INK = RGBColor(0x1A, 0x1A, 0x1A)
ACCENT = RGBColor(0x8C, 0x2F, 0x2F)
CINZA = RGBColor(0x5A, 0x5A, 0x5A)
PALIDO = RGBColor(0xF2, 0xF0, 0xEC)
FONTE_TITULO = "Liberation Serif"
FONTE_CORPO = "Liberation Sans"

AUTORES = (
    "Felipe Ferreira Alexandre",
    "Andrei Schoschlakow Bonifácio",
    "Rafael Eiki Teruya",
    "João Pedro Ferreira",
)
NUSP = ("13963144", "14558482", "14604204", "14582312")


@dataclass(frozen=True)
class Nota:
    """Roteiro de um slide para o guia de fala, não texto para ler em voz alta."""

    pessoa: str
    segundos: int
    pontos: tuple[str, ...]


def _numero(valor: float | None, casas: int = 3) -> str:
    return "n.d." if valor is None else decimal(valor, casas)


def _pp(valor: float | None, casas: int = 1) -> str:
    return "n.d." if valor is None else decimal(100 * valor, casas)


def _valor_unidade(valor: str, unidade: str) -> str:
    if valor == "n.d.":
        return "n.d."
    return f"{valor}{unidade}" if unidade.startswith("%") else f"{valor} {unidade}"


def _celula(tabela: pl.DataFrame | None, **filtros: object) -> dict[str, object] | None:
    """Primeira linha que satisfaz os filtros, ou None. Tabela ausente também devolve None."""
    if tabela is None or tabela.is_empty():
        return None
    recorte = tabela
    for coluna, valor in filtros.items():
        if coluna not in recorte.columns:
            return None
        recorte = recorte.filter(pl.col(coluna) == valor)
    return recorte.row(0, named=True) if recorte.height else None


def _linha(tabela: pl.DataFrame | None, hipotese: str, **filtros: object) -> dict | None:
    return _celula(tabela, hipotese=hipotese, **filtros)


def _efeito(linha: dict | None, casas: int = 3) -> str:
    """`0,012 (IC 95%: −0,004 a 0,028)`; "não estimável" quando a linha não existe."""
    if linha is None or linha.get("estimativa") is None:
        motivo = (linha or {}).get("motivo") or "sem estimativa"
        return f"não estimável ({motivo})"
    return (
        f"{_numero(linha['estimativa'], casas)} "
        f"(IC 95%: {_numero(linha['ic_inf'], casas)} a {_numero(linha['ic_sup'], casas)})"
    )


def _status(linha: dict | None, hipotese: str = "") -> str:
    if linha is None or linha.get("ic_inf") is None or linha.get("ic_sup") is None:
        return "indefinido"
    if hipotese == "H4" and (linha.get("p_holm") is None or linha["p_holm"] >= 0.05):
        return "inconclusivo_holm"
    if linha["ic_inf"] > 0:
        return "positivo"
    if linha["ic_sup"] < 0:
        return "negativo"
    return "nulo"


def _leitura(linha: dict | None) -> str:
    """Frase que segue sinal, significância e precisão (EMD), sem digitar o resultado."""
    if linha is None or linha.get("estimativa") is None:
        return "A estimativa não é reportável nesta amostra."
    inferior, superior = linha["ic_inf"], linha["ic_sup"]
    if inferior is not None and superior is not None and inferior <= 0 <= superior:
        emd = linha.get("emd")
        if emd is not None:
            return (
                f"O intervalo cruza zero (EMD de {_pp(emd)} p.p.): efeito impreciso, "
                f"não distinguível de zero a 5%."
            )
        return "O intervalo cruza zero: o efeito não é distinguível de zero a 5%."
    if (linha["estimativa"] or 0) > 0:
        return "O intervalo fica acima de zero: o efeito estimado é positivo a 5%."
    return "O intervalo fica abaixo de zero: o efeito estimado é negativo a 5%."


def _sintese_curta(resumo: pl.DataFrame | None) -> str:
    """Antecipação do achado principal em uma frase (estilo triangular) para o slide 2."""
    h1 = _linha(resumo, "H1", tipo="contraste")
    h2_0 = _linha(resumo, "H2", tipo="contraste", categoria="vencedor_faixa_0")
    h3 = _linha(resumo, "H3", tipo="contraste", resultado="variacao_total")
    st_h1, st_h2, st_h3 = _status(h1, "H1"), _status(h2_0, "H2"), _status(h3, "H3")
    if all(s == "indefinido" for s in (st_h1, st_h2, st_h3)):
        return "Achado principal: estimativas reportadas a partir dos dados públicos de 2024–2025."
    if st_h1 == st_h2 == st_h3 == "nulo":
        emd_h1 = _pp((h1 or {}).get("emd"))
        detalhe = f" (EMD de {emd_h1} p.p. em H1)" if emd_h1 != "n.d." else ""
        return (
            "Achado principal: em disputas apertadas de 2024, H1, H2 (δ = 0) e H3 cruzam zero "
            f"com intervalos largos{detalhe} — sem evidência clara de vantagem ou compensação."
        )
    return (
        f"Achado principal: H1 = {_pp((h1 or {}).get('estimativa'))} p.p., "
        f"H2 (δ = 0) = {_pp((h2_0 or {}).get('estimativa'))} p.p. e "
        f"H3 = {_pp((h3 or {}).get('estimativa'))}% do gasto anual pré-eleitoral."
    )


def _sintese_final(resumo: pl.DataFrame | None) -> list[str]:
    """Síntese orientada a achados, precisão e interpretação econômica para o slide 11."""
    h1 = _linha(resumo, "H1", tipo="contraste")
    h2_0 = _linha(resumo, "H2", tipo="contraste", categoria="vencedor_faixa_0")
    h2_1 = _linha(resumo, "H2", tipo="contraste", categoria="vencedor_faixa_1")
    h2_3 = _linha(resumo, "H2", tipo="contraste", categoria="vencedor_faixa_3+")
    h3 = _linha(resumo, "H3", tipo="contraste", resultado="variacao_total")
    r1 = _linha(resumo, "H3", tipo="categoria", categoria="ambos", resultado="termo_r1")
    r23 = _linha(resumo, "H3", tipo="categoria", categoria="ambos", resultado="termo_compensacao")
    h4 = _linha(resumo, "H4", tipo="contraste", categoria="ligada_ao_vencedor_50")

    def _desc(linha: dict | None, unidade: str, unidade_emd: str, h: str = "") -> str:
        st = _status(linha, h)
        if st == "indefinido":
            return "não estimável nesta amostra"
        est = _valor_unidade(_pp((linha or {}).get("estimativa")), unidade)
        emd = _valor_unidade(_pp((linha or {}).get("emd")), unidade_emd)
        if st == "inconclusivo_holm":
            return f"{est}, inconclusivo após Holm (EMD {emd})"
        if st == "nulo":
            return (
                f"{est}, intervalo cruza zero (EMD {emd})"
                if emd != "n.d."
                else f"{est}, intervalo cruza zero"
            )
        return f"{est} (IC nominal exclui zero na principal)" if h == "H2" else f"{est} ({st} a 5%)"

    comp_ok = (
        r1 is not None
        and r23 is not None
        and r1.get("ic_sup") is not None
        and r23.get("ic_inf") is not None
        and r1["ic_sup"] < 0 < r23["ic_inf"]
    )
    comp_txt = (
        "R1 cai e R2+R3 cresce em redes ligadas a ambos (sinal de compensação)"
        if comp_ok
        else "R1 e R2+R3 não confirmam compensação interna em redes ligadas a ambos"
    )

    h2_extra = (
        f"δ = 1: {_desc(h2_1, 'p.p.', 'p.p.', 'H2')}; δ = 3+: {_desc(h2_3, 'p.p.', 'p.p.', 'H2')}."
        if h2_1 is not None or h2_3 is not None
        else "Sem gradiente consistente por distância."
    )
    h2_extra += (
        " A precisão depende da especificação; o pré-eleitoral fragiliza a leitura de δ = 1."
    )
    return [
        f"H1 (conexão direta ao incumbente): {_desc(h1, 'p.p.', 'p.p.', 'H1')}.",
        f"H2 (coortes de distância): δ = 0 em {_desc(h2_0, 'p.p.', 'p.p.', 'H2')}; {h2_extra}",
        f"H3 (redes): total em {_desc(h3, '% do gasto prévio', '%', 'H3')}; {comp_txt}.",
        f"H4 (principais redes, 50%): {_desc(h4, 'p.p.', 'p.p.', 'H4')}.",
        "Imprecisão não é ausência de efeito: intervalos largos ainda admitem efeitos relevantes, "
        "e o IC estreito em δ = 3+ é condicional a coortes dominadas pelo gigante "
        "e à inferência municipal.",
    ]


def _nota_robustez(robustez: pl.DataFrame | None) -> str:
    """Nota curta sob a tabela de robustez (slide 10), explicando estabilidade e n.d."""
    if robustez is None or robustez.is_empty():
        return "Fonte: elaboração própria. H2 usa δ = 0 e H3 usa o total."
    return (
        "Fonte: elaboração própria. H2 usa δ = 0 e H3 usa o total; IC de 95% por reamostragem "
        "de municípios. Sem articulação: sementes reselecionadas; sementes fixas são uma "
        "sensibilidade adicional distinta. n.d.: menos de dez municípios por lado."
    )


def _detalhes(linha: dict | None, componentes: tuple[dict | None, ...]) -> str:
    """Linha de apoio: banda, municípios de cada lado, b/2, 2b, placebo, densidade e EMD."""
    if linha is None:
        return "Banda, contagens, placebo e efeito mínimo detectável: n.d."
    bandas = " / ".join(_numero((c or {}).get("banda"), 1) for c in componentes)
    n = " e ".join(
        f"{_numero((c or {}).get('municipios_tratados'), 0)}/"
        f"{_numero((c or {}).get('municipios_controle'), 0)}"
        for c in componentes
    )
    return (
        f"Bandas das categorias direta / sem conexão: {bandas} p.p.; municípios (esq./dir.): {n}. "
        f"b/2 = {_numero(linha.get('estimativa_meia_banda'))}; "
        f"2b = {_numero(linha.get('estimativa_dobro_banda'))}; "
        f"placebo de nível pré (fração) = {_numero(linha.get('placebo_estimativa'))} "
        f"(p = {_numero(linha.get('placebo_p_valor'))})."
    )


# --- montagem dos slides ---------------------------------------------------------------------


def _texto(slide, x, y, largura, altura):
    caixa = slide.shapes.add_textbox(x, y, largura, altura)
    caixa.text_frame.word_wrap = True
    caixa.text_frame.margin_left = 0
    caixa.text_frame.margin_right = 0
    caixa.text_frame.margin_top = 0
    caixa.text_frame.margin_bottom = 0
    return caixa.text_frame


def _titulo(slide, texto: str, numero: int) -> None:
    tf = _texto(slide, MARGEM, Inches(0.42), LARGURA - 2 * MARGEM, Inches(0.75))
    p = tf.paragraphs[0]
    p.text = texto
    p.font.name = FONTE_TITULO
    p.font.size = Pt(26)
    p.font.bold = True
    p.font.color.rgb = INK
    linha = slide.shapes.add_connector(1, MARGEM, Inches(1.22), LARGURA - MARGEM, Inches(1.22))
    linha.line.color.rgb = ACCENT
    linha.line.width = Pt(1.2)
    rodape = _texto(
        slide, LARGURA - MARGEM - Inches(0.6), ALTURA - Inches(0.55), Inches(0.6), Inches(0.3)
    )
    pr = rodape.paragraphs[0]
    pr.text = str(numero)
    pr.alignment = PP_ALIGN.RIGHT
    pr.font.name = FONTE_CORPO
    pr.font.size = Pt(10)
    pr.font.color.rgb = CINZA


def _fonte(slide, texto: str) -> None:
    tf = _texto(
        slide, MARGEM, ALTURA - Inches(0.55), LARGURA - 2 * MARGEM - Inches(0.7), Inches(0.3)
    )
    p = tf.paragraphs[0]
    p.text = texto
    p.font.name = FONTE_CORPO
    p.font.size = Pt(9)
    p.font.color.rgb = CINZA


def _marcadores(slide, itens: list[str], x=None, y=None, largura=None, altura=None, tamanho=18):
    y = Inches(1.55) if y is None else y
    x = MARGEM if x is None else x
    largura = LARGURA - 2 * MARGEM if largura is None else largura
    altura = ALTURA - y - Inches(0.8) if altura is None else altura
    tf = _texto(slide, x, y, largura, altura)
    for i, item in enumerate(itens):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = "•  " + item
        p.font.name = FONTE_CORPO
        p.font.size = Pt(tamanho)
        p.font.color.rgb = INK
        p.space_after = Pt(10)
        p.line_spacing = 1.05


def _figura(slide, caminho: Path, x, y, largura, altura) -> None:
    if caminho.exists():
        slide.shapes.add_picture(str(caminho), x, y, width=largura)
        return
    caixa = slide.shapes.add_shape(1, x, y, largura, altura)
    caixa.fill.solid()
    caixa.fill.fore_color.rgb = PALIDO
    caixa.line.color.rgb = CINZA
    tf = caixa.text_frame
    tf.text = "[figura a gerar]"
    tf.paragraphs[0].font.name = FONTE_CORPO
    tf.paragraphs[0].font.size = Pt(11)
    tf.paragraphs[0].font.color.rgb = CINZA
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    tf.paragraphs[0].alignment = PP_ALIGN.CENTER


def _tabela(slide, cabecalho: list[str], linhas: list[list[str]], x, y, largura, altura) -> None:
    forma = slide.shapes.add_table(len(linhas) + 1, len(cabecalho), x, y, largura, altura)
    tabela = forma.table
    for j, texto in enumerate(cabecalho):
        celula = tabela.cell(0, j)
        celula.text = texto
        for p in celula.text_frame.paragraphs:
            p.font.name = FONTE_CORPO
            p.font.size = Pt(12)
            p.font.bold = True
            p.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        celula.fill.solid()
        celula.fill.fore_color.rgb = INK
    for i, linha in enumerate(linhas, start=1):
        for j, texto in enumerate(linha):
            celula = tabela.cell(i, j)
            celula.text = texto
            for p in celula.text_frame.paragraphs:
                p.font.name = FONTE_CORPO
                p.font.size = Pt(11)
                p.font.color.rgb = INK
            celula.fill.solid()
            celula.fill.fore_color.rgb = RGBColor(0xFF, 0xFF, 0xFF) if i % 2 else PALIDO


# --- conteúdo --------------------------------------------------------------------------------


def _destaque(numeros: Numeros, apelido: str) -> str:
    """Macro semântica; "n.d." quando a tabela que a alimenta ainda não existe."""
    try:
        return numeros[apelido]
    except KeyError:
        return "n.d."


def _tabelas(resultados: Path) -> dict[str, pl.DataFrame | None]:
    def ler(nome: str) -> pl.DataFrame | None:
        caminho = resultados / "tables" / f"{nome}.csv"
        return pl.read_csv(caminho) if caminho.exists() else None

    return {
        nome: ler(nome)
        for nome in (
            "resumo_estimacao",
            "robustez",
            "rede_resumo",
            "rede_componentes",
            "links_pc1",
            "reconstrucao",
            "h2_comparaveis",
            "permanencia_h4",
        )
    }


def construir(caminhos: Caminhos, numeros: Numeros) -> tuple[Presentation, list[Nota]]:
    tabelas = _tabelas(caminhos.resultados)
    verificacoes = leitura_sensibilidades(caminhos.resultados / "tables")
    figuras = caminhos.resultados / "figures"
    resumo, robustez = tabelas["resumo_estimacao"], tabelas["robustez"]
    prs = Presentation()
    prs.slide_width = LARGURA
    prs.slide_height = ALTURA
    vazio = prs.slide_layouts[6]
    notas: list[Nota] = []

    # 1. Capa
    slide = prs.slides.add_slide(vazio)
    tf = _texto(slide, MARGEM, Inches(1.55), LARGURA - 2 * MARGEM, Inches(1.8))
    p = tf.paragraphs[0]
    p.text = "Redes empresariais e persistência econômica sob alternância política"
    p.font.name = FONTE_TITULO
    p.font.size = Pt(34)
    p.font.bold = True
    p.font.color.rgb = INK
    linha = slide.shapes.add_connector(1, MARGEM, Inches(3.42), Inches(4.6), Inches(3.42))
    linha.line.color.rgb = ACCENT
    linha.line.width = Pt(2)
    subtitulo = _texto(slide, MARGEM, Inches(3.65), Inches(11.6), Inches(1.1))
    par = subtitulo.paragraphs[0]
    par.text = "Evidências dos empenhos municipais no estado de São Paulo"
    par.font.name = FONTE_CORPO
    par.font.size = Pt(19)
    par.font.color.rgb = CINZA
    autores = _texto(slide, MARGEM, Inches(4.75), Inches(11.6), Inches(1.2))
    for i, (nome, nusp) in enumerate(zip(AUTORES, NUSP, strict=True)):
        pp = autores.paragraphs[0] if i == 0 else autores.add_paragraph()
        pp.text = f"{nome} — {nusp}"
        pp.font.name = FONTE_CORPO
        pp.font.size = Pt(13)
        pp.font.color.rgb = INK
    curso = _texto(slide, MARGEM, Inches(6.35), Inches(11.6), Inches(0.4))
    pc = curso.paragraphs[0]
    pc.text = "EAE1429 — Redes Econômicas e Sociais · FEA-USP · 2026"
    if (caminhos.dados / MARCADOR).is_file():
        pc.text += " · AMOSTRA SINTÉTICA"
    pc.font.name = FONTE_CORPO
    pc.font.size = Pt(11)
    pc.font.color.rgb = CINZA
    notas.append(
        Nota(
            "Felipe",
            40,
            (
                "Abrir com a pergunta do projeto, não com a literatura.",
                "Dizer em uma frase o que o grupo encontrou ou não encontrou.",
                "Apresentar a divisão: desenho, resultados, robustez.",
            ),
        )
    )

    # 2. Motivação
    slide = prs.slides.add_slide(vazio)
    _titulo(slide, "O que sobrevive quando o governo muda", 2)
    _marcadores(
        slide,
        [
            "A alternância troca nomes na prefeitura. Para quem vende ao município, "
            "a pergunta é se o acesso aos empenhos sobrevive.",
            "Olhando só os CNPJs, há renovação de fornecedores. Olhando os sócios, pode haver "
            "continuidade dentro de uma rede.",
            "O desenho identifica o efeito da vitória eleitoral sobre a alocação; a transmissão "
            "pela rede é a hipótese examinada (e não corrupção por definição).",
            _sintese_curta(resumo),
            *(f for f in verificacoes if f.startswith("O gigante")),
        ],
        largura=Inches(11.9),
        tamanho=17,
    )
    _fonte(slide, "Fonte: elaboração própria, a partir do projeto de pesquisa.")
    notas.append(
        Nota(
            "Felipe",
            40,
            (
                "Contraste entre rotatividade de CNPJ e continuidade de sócios.",
                "Antecipar a conclusão central já aqui, sem esperar o final.",
                "Deixar claro o que o desenho identifica (vitória eleitoral) e o que é hipótese.",
            ),
        )
    )

    # 3. Dados e rede
    slide = prs.slides.add_slide(vazio)
    _titulo(slide, "Dados e construção da rede", 3)
    _marcadores(
        slide,
        [
            "TCESP: empenhos de 2021 a 2025 pela data do evento. TSE: eleições e doações "
            "até 5/10/2024. Receita: fotografia de setembro de 2024.",
            f"{_destaque(numeros, 'munAnalisaveis')} municípios analisáveis, sem a capital e sem "
            "segundo turno; cada coorte RDD tem suporte próprio.",
            f"{_destaque(numeros, 'empresasRede')} empresas, "
            f"{_destaque(numeros, 'pessoasRede')} vértices de sócios/administradores PF/PJ e "
            f"{_destaque(numeros, 'vinculosRede')} vínculos na rede principal.",
            "Vizinhança é compartilhar sócio ou administrador. δ conta passos entre empresas "
            "(dois no bipartido). δ = 0 quando um sócio ou administrador PF doa ao candidato.",
            "O complemento societário foi extraído após a eleição (12/10/2024) e inclui "
            "vínculos com entrada até 13/09/2024.",
        ],
        largura=Inches(7.1),
    )
    _figura(
        slide, figuras / "figura1_exemplo.png", Inches(7.9), Inches(1.7), Inches(4.8), Inches(3.9)
    )
    _fonte(slide, "Fonte: Receita Federal, TSE e TCESP; elaboração própria.")
    notas.append(
        Nota(
            "Andrei",
            50,
            (
                "Explicar a unidade empresa e a distância com o exemplo de três empresas da Figura "
                "1.",
                "Dizer por que a fotografia é de setembro e não a atual.",
                "Para empresas sem sócios em setembro, usamos a extração de 12/10/2024, "
                "após a eleição, com entrada até 13/09/2024. Vínculos encerrados antes "
                "da extração podem ficar de fora.",
            ),
        )
    )

    # 4. Descritivas
    slide = prs.slides.add_slide(vazio)
    _titulo(slide, "A rede e seu componente gigante", 4)
    componentes = tabelas["rede_componentes"]
    unitarios = ""
    if componentes is not None:
        principal = componentes.filter(pl.col("variante") == "PRINCIPAL")
        total = principal["componentes"].sum()
        um = principal.filter(pl.col("faixa_tamanho").cast(pl.Utf8) == "1")["componentes"]
        if total and um.len() == 1 and um.item() is not None:
            unitarios = f"{_numero(100 * um.item() / total, 1)}% têm uma empresa. "
    _marcadores(
        slide,
        [
            f"O maior componente reúne {_destaque(numeros, 'fracGigante')} das empresas; "
            f"sem os pontos de articulação, {_destaque(numeros, 'fracGiganteSemArt')}.",
            f"{_destaque(numeros, 'componentesRede')} componentes; {unitarios}"
            "O gráfico distribui empresas, não componentes.",
            f"Na reconstrução com a fotografia recente, "
            f"{_destaque(numeros, 'fracVinculosPerdidos')} dos vínculos de setembro ficam de fora; "
            f"{_destaque(numeros, 'fracVinculosExtras')} dos reconstruídos faltam em setembro.",
        ],
        largura=Inches(7.1),
    )
    _figura(
        slide, figuras / "rede_componentes.png", Inches(7.9), Inches(1.7), Inches(4.8), Inches(3.9)
    )
    _fonte(slide, "Fonte: elaboração própria, com dados da Receita Federal e do TCESP.")
    notas.append(
        Nota(
            "Andrei",
            55,
            (
                "Mostrar que a rede nacional não é um bloco único.",
                "Explicar o que muda ao remover pontos de articulação.",
                "Relacionar o componente gigante às sensibilidades de caminhos e sementes.",
            ),
        )
    )

    # 5. Desenho
    slide = prs.slides.add_slide(vazio)
    _titulo(slide, "Eleições apertadas como choque", 5)
    densidade = (
        _numero(resumo.row(0, named=True).get("densidade_p_valor"))
        if resumo is not None and not resumo.is_empty() and "densidade_p_valor" in resumo.columns
        else "n.d."
    )
    _marcadores(
        slide,
        [
            "M é a diferença de votos válidos entre o grupo incumbente e o adversário mais votado "
            "(em p.p.); T = 1 quando o incumbente perde (M < 0).",
            "Hipótese de identificação: continuidade dos resultados potenciais em M = 0 — efeito "
            "local em disputas apertadas, não em vitórias folgadas.",
            "Linear local, núcleo triangular, banda MSE-ótima. Pontos corrigidos pelo viés: "
            "IC CCT nas categorias; reamostragem municipal com bandas fixas nos contrastes.",
            f"Diagnósticos: teste de densidade (p = {densidade}), b/2 e 2b, placebo (2021–2024) "
            "e efeito mínimo detectável (EMD, poder de 80%, nível de 5%).",
            "H1 a H3 são principais; H4 e comparações secundárias recebem correção de Holm.",
        ],
        largura=Inches(11.9),
        tamanho=17,
    )
    _fonte(
        slide,
        "Fonte: elaboração própria; Calonico, Cattaneo e Titiunik (2014); Cattaneo, Jansson e Ma "
        "(2020).",
    )
    notas.append(
        Nota(
            "Andrei",
            55,
            (
                "Explicar a hipótese de continuidade no corte sem entrar na fórmula.",
                "Frisar que a estimativa de RDD é local (disputas apertadas) e que o teste de "
                "densidade não sugere manipulação.",
                "Mencionar poder limitado e EMD antes dos resultados.",
            ),
        )
    )

    # 6. H1
    h1 = _linha(resumo, "H1", tipo="contraste")
    slide = prs.slides.add_slide(vazio)
    _titulo(slide, "H1 — conexão direta ao incumbente", 6)
    _marcadores(
        slide,
        [
            f"Estimativa: {_efeito(h1)}.",
            _leitura(h1),
            "Comparamos fornecedoras anteriores diretamente ligadas ao incumbente "
            "com as que não têm caminho a nenhum grupo (fração da participação no elemento).",
            _detalhes(
                h1,
                tuple(
                    _linha(resumo, "H1", categoria=c)
                    for c in ("conectada_incumbente", "sem_conexao")
                ),
            ),
        ],
        largura=Inches(7.1),
        tamanho=16,
    )
    _figura(slide, figuras / "rdd_h1.png", Inches(7.9), Inches(1.7), Inches(4.8), Inches(3.9))
    _fonte(
        slide,
        "Fonte: elaboração própria. Fração da participação (2025). "
        "Gráfico: ajuste linear convencional da categoria A, não o contraste corrigido.",
    )
    notas.append(
        Nota(
            "Rafael",
            50,
            (
                "Ler a estimativa em p.p. e o intervalo, não a tabela inteira.",
                "Interpretar o placebo: se o pré-período também salta, o desenho tem problema.",
                "Comparar o efeito com o EMD: intervalo largo é imprecisão, não zero preciso.",
            ),
        )
    )

    # 7. H2
    slide = prs.slides.add_slide(vazio)
    _titulo(slide, "H2 — contrastes entre coortes de distância", 7)
    faixas = []
    for faixa in ("1",):
        achado = _linha(resumo, "H2", tipo="contraste", categoria=f"vencedor_faixa_{faixa}")
        faixas.append(f"δ = {faixa}: {_efeito(achado)}")
    _marcadores(
        slide,
        [
            *faixas,
            "Contraste = (βB − βA)/2. As coortes podem compartilhar firmas: heterogeneidade "
            "eleitoral entre coortes, sem identificar efeito causal da distância. "
            "Os contrastes de H2 são principais, com testes nominais.",
            f"Sobreposição de mercado e porte na conexão direta: "
            f"{_destaque(numeros, 'sobreposicaoDireta')}.",
            *(
                f
                for f in verificacoes
                if f.startswith(("Em H2", "Sem autofinanciamento", "Na coorte B"))
            ),
        ],
        largura=Inches(7.1),
        altura=Inches(4.0),
        tamanho=15,
    )
    if aviso_rede := limite_h2(caminhos.resultados / "tables"):
        _marcadores(slide, [aviso_rede], y=Inches(5.65), altura=Inches(0.95), tamanho=13)
    _figura(slide, figuras / "gradiente_h2.png", Inches(7.9), Inches(1.7), Inches(4.8), Inches(3.9))
    _fonte(
        slide,
        "Fonte: elaboração própria. Unidade: fração da participação no elemento (2025), "
        "com a rede descrita no slide 3.",
    )
    h2_comparaveis = tabelas["h2_comparaveis"]
    sensibilidade = (
        leitura_h2_comparaveis(h2_comparaveis.iter_rows(named=True))
        if h2_comparaveis is not None
        else ""
    )
    notas.append(
        Nota(
            "Rafael",
            55,
            (
                "Sob comparabilidade, a vantagem prevista é positiva e decrescente. O ponto "
                "negativo em δ = 1 contraria essa direção; os diagnósticos limitam a leitura.",
                "Ler δ = 1 junto ao placebo, ao suporte pequeno e à sensibilidade de banda; "
                "não interpretar composição como gradiente causal da distância.",
                *((sensibilidade,) if sensibilidade else ()),
                "Distinguir imprecisão das coortes próximas do IC estreito do contraste médio "
                "em δ = 3+, sem limitar efeitos individuais.",
            ),
        )
    )

    # 8. H3
    slide = prs.slides.add_slide(vazio)
    _titulo(slide, "H3 — decomposição do contraste AMBOS−demais", 8)
    termos = []
    for resultado, rotulo in (
        ("variacao_total", "Total"),
        ("termo_r1", "R1 (anteriores diretamente ligadas a A)"),
        ("termo_r2", "R2 (demais fornecedoras anteriores)"),
        ("termo_r3", "R3 (novas fornecedoras)"),
    ):
        achado = _linha(resumo, "H3", tipo="contraste", resultado=resultado)
        termos.append(f"{rotulo}: {_efeito(achado, casas=4)}")
    r1_ambos = _linha(resumo, "H3", tipo="categoria", categoria="ambos", resultado="termo_r1")
    r23_ambos = _linha(
        resumo, "H3", tipo="categoria", categoria="ambos", resultado="termo_compensacao"
    )
    h3_total = _linha(resumo, "H3", tipo="contraste", resultado="variacao_total") or {}
    sinais_inversos = (
        _status(r1_ambos) == _status(r23_ambos) == "nulo"
        and ((r1_ambos or {}).get("estimativa") or 0) > 0
        and ((r23_ambos or {}).get("estimativa") or 0) < 0
    )
    _marcadores(
        slide,
        [
            "Resultado: Δempenho da rede / gasto anual médio pré do município. Inclui redes com "
            "fornecedoras anteriores no município. Peso municipal um por coorte antes do núcleo.",
            *termos,
            f"Dentro das redes ligadas a ambos: R1, {_efeito(r1_ambos, casas=4)}; "
            f"R2+R3, {_efeito(r23_ambos, casas=4)}.",
            *(
                [
                    "Compensação exige R1 < 0 e R2+R3 > 0. Os pontos internos têm os sinais "
                    "inversos; os dois ICs cruzam zero."
                ]
                if sinais_inversos
                else []
            ),
            f"Placebo de nível pré: {_pp(h3_total.get('placebo_estimativa'))} p.p. de participação "
            f"(p = {_numero(h3_total.get('placebo_p_valor'))}). Requer cautela sobre continuidade.",
        ],
        largura=Inches(7.1),
        tamanho=14,
    )
    _figura(
        slide, figuras / "decomposicao_h3.png", Inches(7.9), Inches(1.7), Inches(4.8), Inches(3.9)
    )
    _fonte(
        slide,
        "Fonte: elaboração própria. Quatro linhas/gráfico: AMBOS menos demais. Linhas internas: "
        "efeitos em AMBOS. Unidade: Δempenho da rede / gasto anual médio pré do município. "
        "Demais: só A, só B ou nenhum. AMBOS é dominada por uma rede.",
    )
    notas.append(
        Nota(
            "Rafael",
            60,
            (
                "Explicar R1, R2 e R3 com um exemplo de rede.",
                "Mostrar que os termos somam o total, não são hipóteses separadas.",
                "Apontar que os intervalos não confirmam compensação interna e notar o placebo "
                "pré-eleitoral de H3.",
            ),
        )
    )

    # 9. H4
    slide = prs.slides.add_slide(vazio)
    _titulo(slide, "H4 — permanência das principais redes", 9)
    limiares = []
    for pct in (25, 50, 75):
        achado = _linha(resumo, "H4", tipo="contraste", categoria=f"ligada_ao_vencedor_{pct}")
        b_b = _linha(resumo, "H4", tipo="categoria", categoria=f"ligada_b_{pct}")
        nota_banda = (
            f" Banda da coorte B: {_numero(b_b.get('banda'), 1)} p.p."
            if pct == 75 and b_b is not None
            else ""
        )
        limiares.append(
            f"Limiar de {pct}%: {_efeito(achado)}. p de Holm: "
            f"{_numero((achado or {}).get('p_holm')).rstrip('.')}.{nota_banda}"
        )
    n_com = _celula(tabelas["permanencia_h4"], limiar=50, ligada_ao_vencedor=True) or {}
    n_sem = _celula(tabelas["permanencia_h4"], limiar=50, ligada_ao_vencedor=False) or {}
    _marcadores(
        slide,
        [
            "Contraste = (βB − βA)/2 nas redes de ligação exclusiva. Principais: ranking "
            "acumulado até o limiar e fornecimento em pelo menos três dos quatro anos prévios. "
            "O ranking de 2025 inclui entrantes.",
            *limiares,
            f"Permanência em disputas de até cinco p.p., no limiar central: "
            f"{_destaque(numeros, 'permanenciaComLigacao')} com ligação ao vencedor e "
            f"{_destaque(numeros, 'permanenciaSemLigacao')} sem ligação "
            f"({_numero(n_com.get('n_municipios'), 0)} e {_numero(n_sem.get('n_municipios'), 0)} "
            "municípios). São médias municipais na janela; o contraste usa saltos no corte "
            "em coortes exclusivas e não é sua diferença nem o efeito de criar uma ligação.",
            "Bandas amplas e ICs além do suporte probabilístico indicam extrapolação instável; "
            "H4 é exploratória.",
        ],
        largura=Inches(11.9),
        tamanho=16,
    )
    _fonte(
        slide,
        "Fonte: elaboração própria. Unidade: probabilidade de permanência entre as principais "
        "redes. O critério de fornecimento vale para o período pré-eleitoral.",
    )
    notas.append(
        Nota(
            "João Pedro",
            45,
            (
                "Explicar o que é uma rede principal e por que o limiar muda a amostra.",
                "Mostrar os p-valores ajustados (Holm), não os brutos.",
                "Lembrar que H4 é secundária e tem EMD muito alto no limiar de 50%.",
            ),
        )
    )

    # 10. Robustez
    slide = prs.slides.add_slide(vazio)
    _titulo(slide, "Robustez: a rede alternativa muda a conclusão?", 10)
    linhas = _linhas_robustez(robustez)
    _tabela(
        slide,
        ["Hipótese", "Principal", "Sem articulação", "Sem sócios PJ", "Sem administradores"],
        linhas,
        MARGEM,
        Inches(1.75),
        LARGURA - 2 * MARGEM,
        Inches(4.4),
    )
    _fonte(slide, _nota_robustez(robustez))
    notas.append(
        Nota(
            "João Pedro",
            50,
            (
                "Não ler a tabela: apontar que H1 e H2 (δ = 0) seguem cruzando zero em todas as "
                "variantes.",
                "Explicar por que aparecem n.d.: remover pontos de articulação ou administradores "
                "fragmenta componentes e derruba o suporte municipal.",
                "Comparar H3 total sem sócios PJ com o intervalo da versão principal; "
                "a mudança do grafo também reclassifica as coortes.",
            ),
        )
    )

    # 11. Leitura conjunta
    slide = prs.slides.add_slide(vazio)
    _titulo(slide, "O que os resultados permitem dizer", 11)
    _marcadores(
        slide,
        _sintese_final(resumo)
        + [f for f in verificacoes if f.startswith(("Só com setembro", "Sem autofinanciamento"))],
        largura=Inches(11.9),
        tamanho=16,
    )
    _fonte(slide, "Fonte: elaboração própria, a partir de resumo_estimacao.csv.")
    notas.append(
        Nota(
            "Felipe",
            55,
            (
                "Amarrar os achados das quatro hipóteses com magnitudes e precisão.",
                "Distinguir imprecisão de contraste médio pequeno em coortes dominadas pelo "
                "gigante; a precisão é condicional à inferência municipal.",
                "Relacionar à literatura (Boas et al., Baltrunaite): doações individuais pós-ADI "
                "4650 em um ciclo municipal não reproduzem ganhos claros.",
            ),
        )
    )

    # 12. Limites
    slide = prs.slides.add_slide(vazio)
    _titulo(slide, "Limites e o que ficou de fora", 12)
    _marcadores(
        slide,
        [
            "Validade local do RDD: os resultados valem para eleições apertadas nos municípios "
            "paulistas do TCESP (sem a capital).",
            "Doação é medida parcial de conexão: vínculos informais, parentesco e interpostas "
            "pessoas não são observados.",
            "Compartilhar sócios não é controle nem direito econômico; homônimos e seis dígitos do "
            "CPF geram erro de cruzamento.",
            "Empenho não é contrato; um ciclo eleitoral limita o poder e efeitos indistinguíveis "
            "não são iguais a zero.",
            *(f for f in verificacoes if f.startswith(("O gigante", "Em H4", "Sem o gigante"))),
        ],
        largura=Inches(11.9),
        tamanho=16,
    )
    _fonte(slide, "Fonte: elaboração própria. Código e dados públicos: repositório do projeto.")
    notas.append(
        Nota(
            "Felipe",
            45,
            (
                "Fechar com o que o grupo faria diferente com mais ciclos eleitorais.",
                "Deixar claro o que é limitação de medida, de validade local e de poder.",
                "Convidar à pergunta sobre o mecanismo.",
            ),
        )
    )

    return prs, notas


def _linhas_robustez(robustez: pl.DataFrame | None) -> list[list[str]]:
    """Uma linha por hipótese: estimativa (IC) em cada variante da rede."""
    if robustez is None or robustez.is_empty():
        return [[h, "n.d.", "n.d.", "n.d.", "n.d."] for h in ("H1", "H2", "H3")]
    rotulos = (
        ("principal", "Principal"),
        ("sem_articulacao", "Sem articulação"),
        ("sem_pj", "Sem sócios PJ"),
        ("sem_administrador", "Sem administradores"),
    )
    linhas = []
    for hipotese in ("H1", "H2", "H3"):
        # H2 tem quatro contrastes; a linha da tabela usa o contraste de δ = 0.
        recorte = robustez.filter(
            (pl.col("hipotese") == hipotese)
            & (pl.col("tipo") == "contraste")
            & (
                (pl.col("categoria") == "vencedor_faixa_0")
                if hipotese == "H2"
                else (
                    (pl.col("resultado") == "variacao_total") if hipotese == "H3" else pl.lit(True)
                )
            )
        )
        celulas = [hipotese]
        for chave, _ in rotulos:
            coluna = f"estimativa_{chave}"
            if recorte.height and coluna in recorte.columns:
                valor = recorte[coluna][0]
                inferior = recorte[f"ic_inf_{chave}"][0]
                superior = recorte[f"ic_sup_{chave}"][0]
                celulas.append(
                    "n.d."
                    if valor is None
                    else f"{_numero(valor)} ({_numero(inferior)}; {_numero(superior)})"
                )
            else:
                celulas.append("n.d.")
        linhas.append(celulas)
    return linhas


# --- conversão e artefatos -------------------------------------------------------------------


def contar_slides(pptx: Path) -> int:
    return len(Presentation(str(pptx)).slides)


def contar_paginas(pdf: Path) -> int:
    """Páginas do PDF: `pdfinfo` quando existe, senão os objetos `/Type /Page`."""
    if shutil.which("pdfinfo"):
        saida = subprocess.run(
            ["pdfinfo", str(pdf)], capture_output=True, text=True, check=True
        ).stdout
        return int(re.search(r"^Pages:\s+(\d+)", saida, re.MULTILINE).group(1))  # type: ignore[union-attr]
    return len(re.findall(rb"/Type\s*/Page(?![a-z])", pdf.read_bytes()))


def converter(pptx: Path, pdf: Path) -> Path:
    """Converte com o LibreOffice em modo headless, com perfil temporário próprio."""
    with tempfile.TemporaryDirectory(prefix="deck-") as tmp:
        perfil = Path(tmp) / "perfil"
        subprocess.run(
            [
                "soffice",
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
        )
        gerado = Path(tmp) / pptx.with_suffix(".pdf").name
        pdf.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(gerado, pdf)
    return pdf


def guia(notas: list[Nota], titulos: list[str]) -> str:
    """`output/guia_de_fala.md`: pontos por slide, tempo e divisão entre as quatro pessoas."""
    total = sum(nota.segundos for nota in notas)
    linhas = [
        "# Guia de fala",
        "",
        f"Deck de {len(notas)} slides, cerca de {total / 60:.0f} minutos. Os tempos são sugestões; "
        "os pontos são o que precisa ser dito, não um texto para ler.",
        "",
        "| Slide | Tema | Pessoa | Tempo |",
        "|---|---|---|---|",
        *[
            f"| {i} | {titulo} | {nota.pessoa} | {nota.segundos} s |"
            for i, (titulo, nota) in enumerate(zip(titulos, notas, strict=True), start=1)
        ],
        "",
    ]
    for i, (titulo, nota) in enumerate(zip(titulos, notas, strict=True), start=1):
        linhas += [f"## {i}. {titulo} — {nota.pessoa} ({nota.segundos} s)", ""]
        linhas += [f"- {ponto}" for ponto in nota.pontos]
        linhas.append("")
    por_pessoa: dict[str, int] = {}
    for nota in notas:
        por_pessoa[nota.pessoa] = por_pessoa.get(nota.pessoa, 0) + nota.segundos
    linhas += [
        "## Divisão",
        "",
        *[f"- {pessoa}: {segundos} s" for pessoa, segundos in por_pessoa.items()],
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
        ("rede_distancias", "rede_componentes", "rdd_h1", "gradiente_h2", "decomposicao_h3"),
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
