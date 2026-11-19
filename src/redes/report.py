"""Etapa `report`: macros e tabelas LaTeX a partir de `resultados/` e o PDF do relatório (T19).

`numeros.tex` não é versionado: é função determinística de `results/tables` (já versionado) e
gravá-lo no repositório duplicaria a fonte e geraria conflito quando as etapas de estimação
mudarem as tabelas. Ele nasce no diretório de compilação, `<dados>/build/report`, ao lado de uma
cópia das fontes e das figuras, e só o PDF final vai para `saida`.
"""

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import polars as pl

from redes.amostra import MARCADOR
from redes.config import RAIZ, Caminhos
from redes.etapas import Contexto, Etapa
from redes.numeros import ND, Numeros, decimal, escrever_macros, leitura_h2_comparaveis

ETAPA = Etapa(
    nome="report",
    depende=("estimate",),
    le=(),
    grava=(),
    artefatos=("saida/relatorio.pdf",),
)

FONTES = RAIZ / "report"
MAXIMO_PAGINAS = 5


# O quadro apresenta os contrastes. As linhas por categoria guardam as bandas e o IC do rdrobust.
CONTRASTES = (
    ("H1", "conectada_menos_sem_conexao", "participacao_2025", "H1"),
    *(
        ("H2", f"vencedor_faixa_{d}", "participacao_2025", f"H2 ($\\delta={d}$)")
        for d in ("0", "1", "2", "3+")
    ),
    *(
        ("H3", "ambos_menos_demais", r, f"H3 ({nome})")
        for r, nome in (
            ("variacao_total", "total"),
            ("termo_r1", "R1"),
            ("termo_r2", "R2"),
            ("termo_r3", "R3"),
        )
    ),
    *(
        ("H4", f"ligada_ao_vencedor_{p}", f"mantem_posicao_{p}", rf"H4 ({p}\%)")
        for p in (25, 50, 75)
    ),
)


def _indexar(tabela: pl.DataFrame) -> dict:
    return {
        (r["hipotese"], r["categoria"], r["resultado"], r["tipo"]): r
        for r in tabela.iter_rows(named=True)
    }


def _numero(linha: dict, coluna: str, casas: int = 4) -> str:
    valor = linha.get(coluna)
    return ND if valor is None else decimal(valor, casas)


def _intervalo(linha: dict, sufixo: str = "") -> str:
    inferior = _numero(linha, "ic_inf" + sufixo)
    superior = _numero(linha, "ic_sup" + sufixo)
    return ND if ND in (inferior, superior) else f"[{inferior}, {superior}]"


def _quadro(
    rotulo: str, titulo: str, cabecalho: tuple[str, ...], corpo: list[list[str]], fonte: str
) -> str:
    return "\n".join(
        [
            r"\par\medskip\noindent\begin{minipage}{\linewidth}\centering",
            rf"\legendaquadro{{{rotulo}}}{{{titulo}}}",
            r"\footnotesize\setlength{\tabcolsep}{3.2pt}",
            r"\sbox{\caixaquadro}{%",
            rf"\begin{{tabular}}{{l{'c' * (len(cabecalho) - 1)}}}",
            r"\toprule",
            " & ".join(cabecalho) + r" \\",
            r"\midrule",
            *(" & ".join(linha) + r" \\" for linha in corpo),
            r"\bottomrule",
            r"\end{tabular}}",
            r"\ifdim\wd\caixaquadro>\linewidth",
            r"\resizebox{\linewidth}{!}{\usebox{\caixaquadro}}",
            r"\else\usebox{\caixaquadro}\fi",
            rf"\fonteabnt{{{fonte}}}",
            r"\end{minipage}\par\medskip",
        ]
    )


def tabela_estimativas(resumo: pl.DataFrame) -> str:
    """Contrastes principais e complementares, com os diagnósticos do estimador."""
    linhas = _indexar(resumo)
    corpo = []
    for h, c, r, rotulo in CONTRASTES:
        linha = linhas.get((h, c, r, "contraste"), {})
        corpo.append(
            [
                rotulo,
                _numero(linha, "estimativa"),
                _intervalo(linha),
                _numero(linha, "estimativa_meia_banda"),
                _numero(linha, "estimativa_dobro_banda"),
                _numero(linha, "placebo_estimativa"),
                _numero(linha, "placebo_p_valor", 3),
                _numero(linha, "emd"),
                _numero(linha, "p_holm", 3) if h == "H4" else "---",
            ]
        )
    densidade = _numero(resumo.row(0, named=True), "densidade_p_valor", 3) if resumo.height else ND
    return _quadro(
        "tab:estimativas",
        "Contrastes no corte eleitoral",
        ("Hipótese", "Efeito", "IC", "$b/2$", "$2b$", "Placebo", "$p_{pl}$", "EMD", "$p_{Holm}$"),
        corpo,
        rf"IC por reamostragem de municípios. Teste de densidade (valor-p): {densidade}. "
        rf"EMD: efeito mínimo detectável. Holm se aplica às comparações secundárias.",
    )


def tabela_categorias(resumo: pl.DataFrame) -> str:
    """ICs corrigidos pelo viés, bandas e suporte dos recortes discutidos no texto."""
    linhas = _indexar(resumo)
    recortes = (
        (
            "H1",
            "participacao_2025",
            ("conectada_incumbente", "sem_conexao"),
            ("H1 · incumbente direta", "H1 · sem conexão"),
        ),
        (
            "H2",
            "participacao_2025",
            ("faixa_a_0", "faixa_b_0", "faixa_a_1", "faixa_b_1"),
            ("H2 · A direta", "H2 · B direta", "H2 · A a um passo", "H2 · B a um passo"),
        ),
        ("H3", "variacao_total", ("ambos", "demais"), ("H3 · ambos", "H3 · demais")),
        ("H3", "termo_r1", ("ambos",), ("H3 · R1 em ambos",)),
        ("H3", "termo_compensacao", ("ambos",), ("H3 · R2+R3 em ambos",)),
        (
            "H4",
            "mantem_posicao_50",
            tuple(f"ligada_{g}_50" for g in ("a", "b", "ambos", "nenhum")),
            (
                r"H4 (50\%) · só A",
                r"H4 (50\%) · só B",
                r"H4 (50\%) · ambos",
                r"H4 (50\%) · nenhuma",
            ),
        ),
    )
    corpo = []
    for h, resultado, categorias, rotulos in recortes:
        for categoria, rotulo in zip(categorias, rotulos, strict=True):
            linha = linhas.get((h, categoria, resultado, "categoria"), {})
            corpo.append(
                [
                    rotulo,
                    _numero(linha, "estimativa"),
                    _intervalo(linha),
                    _numero(linha, "banda", 1),
                    _numero(linha, "municipios_tratados", 0),
                    _numero(linha, "municipios_controle", 0),
                    _numero(linha, "p_valor", 3),
                    _numero(linha, "p_valor_rede", 3),
                ]
            )
    return _quadro(
        "tab:categorias",
        "Estimativas em categorias pré-eleitorais",
        ("Categoria", "Efeito", "IC robusto", "$b$", "Esq.", "Dir.", "$p_{{mun}}$", "$p_{{rede}}$"),
        corpo,
        "IC corrigido pelo viés. Bandas em p.p. Esq./Dir. contam os municípios por lado. "
        "O valor-p por rede exige ao menos dez redes por lado. "
        r"As contagens por rede e os demais recortes estão em resumo\_estimacao.csv.",
    )


def _marca_intervalo(linha: dict, variante: str) -> str:
    inferior = linha.get(f"ic_inf_{variante}")
    superior = linha.get(f"ic_sup_{variante}")
    return (
        "*"
        if inferior is not None and superior is not None and not inferior <= 0 <= superior
        else ""
    )


def tabela_robustez(robustez: pl.DataFrame) -> str:
    linhas = _indexar(robustez)
    corpo = [
        [
            rotulo,
            *(
                _numero(linha, f"estimativa_{v}") + _marca_intervalo(linha, v)
                for v in ("principal", "sem_articulacao", "sem_pj", "sem_administrador")
            ),
        ]
        for h, c, r, rotulo in CONTRASTES
        if h != "H4"
        for linha in [linhas.get((h, c, r, "contraste"), {})]
    ]
    return _quadro(
        "tab:robustez",
        "Contrastes nas quatro versões da rede",
        ("Hipótese", "Principal", "Sem articulação", "Sem sócios PJ", "Sem administradores"),
        corpo,
        "Um asterisco indica IC que exclui zero. Os intervalos completos estão em robustez.csv.",
    )


def leitura_resultados(resumo: pl.DataFrame) -> str:
    linhas = _indexar(resumo)
    achados = []
    recortes = {
        "H1": ("conectada_menos_sem_conexao",),
        "H2": ("vencedor_faixa_0", "vencedor_faixa_1"),
        "H3": ("variacao_total",),
        "H4": ("ligada_ao_vencedor_50",),
    }
    for h, c, r, rotulo in CONTRASTES:
        if c not in recortes[h] and r not in recortes[h]:
            continue
        linha = linhas.get((h, c, r, "contraste"), {})
        inferior, superior = linha.get("ic_inf"), linha.get("ic_sup")
        if inferior is None or superior is None:
            leitura = "não foi estimável"
        elif h == "H4" and (linha.get("p_holm") is None or linha["p_holm"] >= 0.05):
            leitura = "permaneceu inconclusivo após a correção de Holm"
        elif inferior > 0:
            leitura = "foi positivo"
        elif superior < 0:
            leitura = "foi negativo"
        else:
            leitura = "teve intervalo que inclui zero"
        achados.append(f"O contraste de {rotulo} {leitura}.")
    r1 = linhas.get(("H3", "ambos", "termo_r1", "categoria"), {})
    compensacao = linhas.get(("H3", "ambos", "termo_compensacao", "categoria"), {})
    if r1.get("ic_sup") is None or compensacao.get("ic_inf") is None:
        achados.append("A compensação dentro das redes ligadas a ambos ficou sem estimativa.")
    elif r1["ic_sup"] < 0 < compensacao["ic_inf"]:
        achados.append(
            "Em redes ligadas a ambos, R1 caiu e R2+R3 cresceu, como prevê a compensação."
        )
    else:
        achados.append(
            "Os intervalos de R1 e R2+R3 em redes ligadas a ambos não confirmam compensação."
        )
    return " ".join(achados)


def _ler_tabela(pasta: Path, nome: str) -> pl.DataFrame:
    return pl.read_csv(pasta / nome) if (pasta / nome).is_file() else pl.DataFrame()


def numeros_tex(pasta: Path, sintetica: bool = False) -> str:
    resumo = _ler_tabela(pasta, "resumo_estimacao.csv")
    robustez = _ler_tabela(pasta, "robustez.csv")
    h2_comparaveis = _ler_tabela(pasta, "h2_comparaveis.csv")
    campos = {
        "tabelaEstimativas": tabela_estimativas(resumo),
        "tabelaCategorias": tabela_categorias(resumo),
        "tabelaRobustez": tabela_robustez(robustez),
        "leituraResultados": leitura_resultados(resumo),
        "leituraHDoisComparaveis": leitura_h2_comparaveis(
            h2_comparaveis.iter_rows(named=True)
        ).replace("%", r"\%"),
        "avisoAmostra": r"\textbf{Amostra sintética para teste.}" if sintetica else "",
    }
    return escrever_macros(Numeros.ler(pasta)) + "".join(
        f"\\newcommand{{\\{nome}}}{{%\n{corpo}\n}}\n" for nome, corpo in campos.items()
    )


def contar_paginas(pdf: Path) -> int:
    """Páginas de um PDF: `pdfinfo` quando existe, senão contagem dos objetos /Type /Page."""
    if shutil.which("pdfinfo"):
        saida = subprocess.run(
            ["pdfinfo", str(pdf)], capture_output=True, text=True, check=True
        ).stdout
        return int(re.search(r"^Pages:\s+(\d+)", saida, re.MULTILINE).group(1))  # type: ignore[union-attr]
    return len(re.findall(rb"/Type\s*/Page(?![a-z])", pdf.read_bytes()))


def preparar(caminhos: Caminhos, destino: Path) -> Path:
    """Copia fontes e figuras para `destino` e grava `numeros.tex`; devolve o `.tex` principal."""
    destino.mkdir(parents=True, exist_ok=True)
    for nome in ("relatorio.tex", "referencias.bib"):
        shutil.copy2(FONTES / nome, destino / nome)
    for antigo in destino.glob("*.pdf"):
        antigo.unlink()
    pasta_figuras = caminhos.resultados / "figures"
    for figura in pasta_figuras.glob("*.pdf") if pasta_figuras.is_dir() else ():
        shutil.copy2(figura, destino / figura.name)
    sint = (caminhos.dados / MARCADOR).is_file()
    (destino / "numeros.tex").write_text(
        numeros_tex(caminhos.resultados / "tables", sint), encoding="utf-8"
    )
    return destino / "relatorio.tex"


def compilar(principal: Path) -> Path:
    subprocess.run(
        ["latexmk", "-pdf", "-interaction=nonstopmode", "-halt-on-error", principal.name],
        cwd=principal.parent,
        check=True,
        capture_output=True,
        text=True,
    )
    return principal.with_suffix(".pdf")


def executar(ctx: Contexto) -> None:
    reconstrucoes = () if (ctx.caminhos.dados / MARCADOR).is_file() else ("reconstrucao",)
    ctx.caminhos.exigir_resultados(
        (
            "resumo_estimacao",
            "robustez",
            "comparabilidade_h2",
            "h2_comparaveis",
            "permanencia_h4",
            "rede_resumo",
            "links_pc1",
            "validacao_panel",
            "mercados_sem_empenho",
            *reconstrucoes,
        ),
        (
            "figura1_exemplo",
            "rede_componentes",
            "rede_distancias",
            "gradiente_h2",
            "decomposicao_h3",
        ),
        "pdf",
    )
    principal = preparar(ctx.caminhos, ctx.caminhos.dados / "build" / "report")
    try:
        pdf = compilar(principal)
    except subprocess.CalledProcessError as erro:
        raise RuntimeError(f"latexmk falhou:\n{erro.stdout[-3000:]}") from erro
    paginas = contar_paginas(pdf)
    if not 0 < paginas <= MAXIMO_PAGINAS:
        raise RuntimeError(f"relatório com {paginas} páginas; o máximo é {MAXIMO_PAGINAS}")
    ctx.caminhos.saida.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=ctx.caminhos.saida) as pasta:
        compilado = Path(pasta) / pdf.name
        shutil.copy2(pdf, compilado)
        compilado.replace(ctx.caminhos.saida / pdf.name)
