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
from redes.leitura_sensibilidades import leitura as leitura_sensibilidades
from redes.leitura_sensibilidades import limite_h2
from redes.numeros import ND, Numeros, decimal, escrever_macros, leitura_h2_comparaveis, percentual
from redes.portabilidade import ferramenta

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
)


def _indexar(tabela: pl.DataFrame) -> dict:
    return {
        (r["hipotese"], r["categoria"], r["resultado"], r["tipo"]): r
        for r in tabela.iter_rows(named=True)
    }


def _numero(linha: dict, coluna: str, casas: int = 4) -> str:
    valor = linha.get(coluna)
    return ND if valor is None else decimal(valor, casas)


def _decimal_math(valor: float, casas: int = 3) -> str:
    """Formata decimal para modo matemático em PT-BR (`0{,}993`), sem espaço após a vírgula."""
    return decimal(valor, casas).replace(",", "{,}")


def _pp(linha: dict, coluna: str, casas: int = 1) -> str:
    valor = linha.get(coluna)
    return ND if valor is None else decimal(100 * valor, casas)


def _valor_unidade(valor: str, unidade: str) -> str:
    """Junta valor e unidade sem espaço antes de `%`, com espaço nas demais (`-1,1 p.p.`)."""
    if valor == ND:
        return ND
    return f"{valor}{unidade}" if unidade.startswith(r"\%") else f"{valor} {unidade}"


def _intervalo(linha: dict, sufixo: str = "") -> str:
    inferior = _numero(linha, "ic_inf" + sufixo)
    superior = _numero(linha, "ic_sup" + sufixo)
    return ND if ND in (inferior, superior) else f"[{inferior}, {superior}]"


def _status_contraste(linha: dict) -> str:
    inferior, superior = linha.get("ic_inf"), linha.get("ic_sup")
    if inferior is None or superior is None:
        return "indefinido"
    if inferior > 0:
        return "positivo"
    if superior < 0:
        return "negativo"
    return "nulo"


def _juntar_lista(itens: list[str]) -> str:
    if not itens:
        return ""
    if len(itens) == 1:
        return itens[0]
    return ", ".join(itens[:-1]) + " e " + itens[-1]


def _quadro(
    rotulo: str, titulo: str, cabecalho: tuple[str, ...], corpo: list[list[str]], fonte: str
) -> str:
    return "\n".join(
        [
            r"\par\medskip\noindent\begin{minipage}{\linewidth}\centering",
            rf"\legendaquadro{{{rotulo}}}{{{titulo}}}",
            r"\footnotesize\setstretch{1}\renewcommand{\arraystretch}{0.92}",
            r"\setlength{\tabcolsep}{3.2pt}",
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
            rf"\fonteabnt{{Fonte: elaboração própria. {fonte}}}",
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
            ]
        )
    densidade = _numero(resumo.row(0, named=True), "densidade_p_valor", 3) if resumo.height else ND
    return _quadro(
        "tab:estimativas",
        "Contrastes no corte eleitoral",
        (
            "Hipótese",
            "Efeito",
            "IC",
            "$b/2$",
            "$2b$",
            "Placebo",
            "$p$ do placebo",
            "EMD",
        ),
        corpo,
        rf"Unidades conforme o desenho empírico. Estimativas corrigidas pelo viés e ICs normais "
        rf"de 95\% por reamostragem municipal com bandas fixas. O placebo usa a participação "
        rf"prévia. n.d. indica falta de dados ou falha no ajuste. "
        rf"Valor-p da densidade de {densidade}.",
    )


def tabela_categorias(resumo: pl.DataFrame) -> str:
    """ICs corrigidos pelo viés, bandas e suporte dos recortes discutidos no texto."""
    linhas = _indexar(resumo)
    recortes = (
        (
            "H1",
            "participacao_2025",
            ("conectada_incumbente", "sem_conexao"),
            ("H1 · A direta", "H1 · sem conexão"),
        ),
        (
            "H2",
            "participacao_2025",
            ("faixa_a_0", "faixa_b_0", "faixa_a_1", "faixa_b_1"),
            ("H2 · A direta", "H2 · B direta", "H2 · A a um passo", "H2 · B a um passo"),
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
        (
            "Categoria",
            "Efeito",
            "IC robusto",
            "$b$",
            "Derrotas",
            "Vitórias",
            r"$p_{\mathrm{mun}}$",
            r"$p_{\mathrm{rede}}$",
        ),
        corpo,
        r"IC robusto de 95\% com correção de viés. $b$ está em p.p. Derrotas e vitórias contam "
        r"municípios na banda. Valores-$p$ agrupados por município ($p_{\mathrm{mun}}$) ou por "
        r"rede ($p_{\mathrm{rede}}$, com pelo menos dez redes por lado). Poucas unidades "
        r"fragilizam a aproximação assintótica. Outros recortes em resumo\_estimacao.csv.",
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
        for linha in [linhas.get((h, c, r, "contraste"), {})]
    ]
    return _quadro(
        "tab:robustez",
        "Contrastes nas quatro versões da rede",
        ("Hipótese", "Principal", "Sem articulação", "Sem sócios PJ", "Sem administradores"),
        corpo,
        r"Unidades como no Quadro~\ref{tab:estimativas}. O asterisco marca os ICs de 95\% "
        r"que excluem zero. n.d.\ indica menos de dez municípios em um dos lados. "
        r"A coluna sem articulação recalcula as ligações diretas e os caminhos (robustez.csv). "
        r"A variante que preserva as ligações diretas e os intervalos estão nos respectivos CSVs.",
    )


def _efeito_com_ic(linha: dict, unidade: str, casas: int = 2) -> str:
    estimativa, inferior, superior = (
        _pp(linha, campo, casas) for campo in ("estimativa", "ic_inf", "ic_sup")
    )
    efeito = _valor_unidade(estimativa, unidade)
    if ND in (inferior, superior):
        return efeito
    return rf"{efeito} (IC de 95\% de {inferior} a {_valor_unidade(superior, unidade)})"


def leitura_resultados(
    resumo: pl.DataFrame, *, placebo_pre_b: dict | None = None
) -> dict[str, str]:
    """Gera as leituras na ordem das hipóteses discutidas no artigo."""
    linhas = _indexar(resumo)
    leituras = {}
    frases = []

    dens = resumo.row(0, named=True).get("densidade_p_valor") if resumo.height else None
    if dens is not None:
        if dens >= 0.05:
            frases.append(
                "A densidade da margem é compatível com a continuidade no corte "
                f"($p = {_decimal_math(dens, 3)}$)."
            )
        else:
            frases.append(
                f"O teste de densidade sugere descontinuidade na margem "
                f"($p = {_decimal_math(dens, 3)}$)."
            )

    leituras["leituraDensidade"] = " ".join(frases)

    h1 = linhas.get(("H1", "conectada_menos_sem_conexao", "participacao_2025", "contraste"), {})
    frases = []
    if h1.get("estimativa") is not None:
        contraste = (
            f"Em H1, o contraste entre fornecedoras diretamente ligadas a A e aquelas sem "
            f"caminho observado para A ou B foi de {_efeito_com_ic(h1, 'p.p.', 1)}"
        )
        if _status_contraste(h1) == "nulo":
            contraste += ", intervalo que admite perdas e ganhos de participação"
        frases.append(f"{contraste}.")
        if h1.get("emd") is not None:
            frases.append(f"Nessa comparação, o EMD é de {_pp(h1, 'emd')} p.p.")
        meia_banda = h1.get("estimativa_meia_banda")
        if meia_banda is not None and h1["estimativa"] * meia_banda < 0:
            frases.append("Com metade da banda, o contraste muda de sinal.")

    leituras["leituraHUm"] = " ".join(frases)

    h2_0 = linhas.get(("H2", "vencedor_faixa_0", "participacao_2025", "contraste"), {})
    h2_1 = linhas.get(("H2", "vencedor_faixa_1", "participacao_2025", "contraste"), {})
    h2_3 = linhas.get(("H2", "vencedor_faixa_3+", "participacao_2025", "contraste"), {})
    b1 = linhas.get(("H2", "faixa_b_1", "participacao_2025", "categoria"), {})
    frases = []
    if h2_1.get("estimativa") is not None:
        frases.append(
            f"No exercício exploratório de H2, o contraste a um passo foi de "
            f"{_efeito_com_ic(h2_1, 'p.p.')} em 2025."
        )
        if (h2_1.get("placebo_estimativa") or 0) * h2_1["estimativa"] > 0 and (
            h2_1.get("placebo_p_valor") is not None
        ):
            frases.append(
                f"O contraste já tinha esse sinal no placebo de nível pré-eleitoral "
                f"({_pp(h2_1, 'placebo_estimativa')} p.p., "
                f"$p={_decimal_math(h2_1['placebo_p_valor'], 3)}$)."
            )
    if b1.get("p_holm") is not None:
        frases.append(
            rf"O IC nominal refere-se ao contraste, e o salto da coorte B a um passo tem "
            rf"$p_{{Holm}}={_decimal_math(b1['p_holm'], 3)}$ na família secundária."
        )

    if placebo_pre_b and placebo_pre_b.get("estimativa") is not None:
        frases.append(
            f"No placebo de mudança pré-eleitoral, o salto para a coorte a um passo de B foi de "
            f"{_efeito_com_ic(placebo_pre_b, 'p.p.')}."
        )
        if _status_contraste(placebo_pre_b) == _status_contraste(b1) == "negativo":
            frases.append(
                "Como a diferença nessa coorte já aparecia antes da eleição, a leitura causal "
                "do salto de 2025 fica enfraquecida."
            )
    if _status_contraste(h2_0) == "nulo":
        frases.append("O IC da faixa de ligação direta inclui zero.")
    if _status_contraste(h2_3) == "nulo" and h2_3.get("emd") is not None:
        frases.append(
            rf"Para as coortes em $\delta=3+$, o contraste é de {_pp(h2_3, 'estimativa')} p.p. "
            rf"e o EMD é de {_pp(h2_3, 'emd')} p.p. sob inferência municipal."
        )
    leituras["leituraHDois"] = " ".join(frases)

    return leituras


def leitura_robustez(robustez: pl.DataFrame) -> str:
    """Resume estabilidade entre variantes da rede e explica células n.d. por perda de suporte."""
    if robustez.is_empty():
        return ""
    linhas = _indexar(robustez)
    variantes = ("principal", "sem_articulacao", "sem_pj", "sem_administrador")

    def _significativa(linha: dict, v: str) -> bool | None:
        inf, sup = linha.get(f"ic_inf_{v}"), linha.get(f"ic_sup_{v}")
        if inf is None or sup is None:
            return None
        return not (inf <= 0 <= sup)

    h1 = linhas.get(("H1", "conectada_menos_sem_conexao", "participacao_2025", "contraste"), {})
    h2_0 = linhas.get(("H2", "vencedor_faixa_0", "participacao_2025", "contraste"), {})

    frases = [
        "Como cada versão da rede redefine as coortes e seleciona suas próprias bandas, as "
        "diferenças entre colunas refletem também quem entra em cada comparação."
    ]
    estaveis_nulos = []
    for nome, linha in (("H1", h1), (r"H2 em $\delta=0$", h2_0)):
        validos = [e for v in variantes if (e := _significativa(linha, v)) is not None]
        if validos and not any(validos):
            estaveis_nulos.append(nome)
    if estaveis_nulos:
        frases.append(
            f"Os ICs dos contrastes diretos ({_juntar_lista(estaveis_nulos)}) incluem zero "
            f"em todas as variantes estimáveis."
        )

    tem_nd = any(
        linhas.get((h, c, r, "contraste"), {}).get(f"estimativa_{v}") is None
        for h, c, r, _ in CONTRASTES
        for v in ("sem_articulacao", "sem_administrador")
    )
    if tem_nd:
        frases.append(
            "A retirada de pontos de articulação ou administradores fragmenta a rede e deixa "
            "alguns contrastes com menos de dez municípios em um dos lados "
            "do corte (n.d.)."
        )
    return " ".join(frases)


def sintese_discussao(resumo: pl.DataFrame) -> str:
    """Abertura concreta da seção de discussão, ancorada nas estimativas e na literatura."""
    if resumo.is_empty():
        return ""
    linhas = _indexar(resumo)
    h1 = linhas.get(("H1", "conectada_menos_sem_conexao", "participacao_2025", "contraste"), {})
    if _status_contraste(h1) == "nulo":
        return (
            "Nas disputas próximas do empate, o contraste de H1 admite perdas e ganhos de "
            "participação para as fornecedoras ligadas diretamente ao incumbente, em relação "
            "às sem caminho observado para A ou B. Em H2, a composição pré-eleitoral das "
            "coortes, a sensibilidade das estimativas e o peso do gigante limitam a interpretação "
            "dos contrastes por distância."
        )
    return (
        r"A evidência varia entre conexões diretas e indiretas. Para comparar esses resultados "
        r"com \citeonline{boas2014} e \citeonline{baltrunaite2020}, consideramos os intervalos "
        r"de confiança, os placebos pré-eleitorais e os EMDs."
    )


def _ler_tabela(pasta: Path, nome: str) -> pl.DataFrame:
    return pl.read_csv(pasta / nome) if (pasta / nome).is_file() else pl.DataFrame()


def _perfil_rede(numeros: Numeros) -> str:
    empresas = numeros.valor("rede_resumo", ("PRINCIPAL", "empresas"), "valor")
    if not empresas:
        return ""
    grau_um = numeros.valor("rede_graus", ("PRINCIPAL", "empresa", "1"), "vertices")
    grau_dois = numeros.valor("rede_graus", ("PRINCIPAL", "empresa", "2"), "vertices")
    isoladas = numeros.valor("rede_componentes", ("PRINCIPAL", "1"), "empresas")
    pessoas = numeros.valor("rede_resumo", ("PRINCIPAL", "pessoas"), "valor")
    vinculos = numeros.valor("rede_resumo", ("PRINCIPAL", "vinculos"), "valor")
    assortatividade = numeros.valor("rede_resumo", ("PRINCIPAL", "assortatividade_grau"), "valor")
    graus = []
    if grau_um is not None and grau_dois is not None:
        proporcao = percentual((grau_um + grau_dois) / empresas)
        graus.append(f"{proporcao} têm um ou dois vínculos")
    if isoladas is not None:
        graus.append(f"{percentual(isoladas / empresas)} não têm vizinha societária")
    frases = [f"Entre as empresas, {_juntar_lista(graus)}."] if graus else []
    medidas = []
    if pessoas and vinculos is not None:
        densidade = decimal(1_000_000 * vinculos / (empresas * pessoas), 3)
        medidas.append(f"há {densidade} vínculo por milhão de pares possíveis")
    if assortatividade is not None:
        medidas.append(
            "a correlação entre os graus nas duas pontas dos vínculos é "
            rf"$r={_decimal_math(assortatividade, 4)}$"
        )
    if medidas:
        frases.append(f"Na rede, {_juntar_lista(medidas)}.")
    return " ".join(frases).replace("%", r"\%")


def numeros_tex(pasta: Path, sintetica: bool = False) -> str:
    resumo = _ler_tabela(pasta, "resumo_estimacao.csv")
    robustez = _ler_tabela(pasta, "robustez.csv")
    h2_comparaveis = _ler_tabela(pasta, "h2_comparaveis.csv")
    auditoria = _ler_tabela(pasta, "auditoria_h2_comparaveis.csv")
    placebo_pre = _indexar(_ler_tabela(pasta, "sensibilidade_pre_periodos.csv"))
    nota_auditoria = ""
    if not auditoria.is_empty():
        a = auditoria.row(0, named=True)
        if all(a.get(c) is not None for c in ("estratos", "jaccard", "correlacao_bootstrap")):
            nota_auditoria = (
                f"Antes de aplicar as bandas, nos {decimal(a['estratos'], 0)} estratos do recorte, "
                f"{decimal(100 * a['jaccard'], 1)}\\% das observações de uma coorte ou da outra "
                "aparecem nas duas. Os saltos, estimados em suas respectivas bandas, têm "
                f"correlação de {decimal(a['correlacao_bootstrap'], 3)} nas "
                f"{decimal(a['replicas_validas'], 0)} reamostragens válidas, "
                "o que ajuda a explicar o IC estreito do contraste."
            )
    verificacoes = leitura_sensibilidades(pasta)

    def texto_verificacoes(frases: list[str]) -> str:
        return " ".join(frases).replace("%", r"\%").replace("δ = 1", r"$\delta=1$")

    numeros = Numeros.ler(pasta)
    campos = {
        "tabelaEstimativas": tabela_estimativas(resumo),
        "tabelaCategorias": tabela_categorias(resumo),
        "tabelaRobustez": tabela_robustez(robustez),
        "perfilRede": _perfil_rede(numeros),
        **leitura_resultados(
            resumo,
            placebo_pre_b=placebo_pre.get(
                ("H2", "faixa_b_1", "variacao_pre_periodos", "categoria")
            ),
        ),
        "leituraRobustez": leitura_robustez(robustez),
        "placeboContrasteHDois": texto_verificacoes(verificacoes["placebo H2"]),
        "leituraSensibilidadesHDois": texto_verificacoes(verificacoes["sensibilidade H2"]),
        "leituraSensibilidades": texto_verificacoes(verificacoes["gerais"])
        .replace("(DP ", "(desvio-padrão de ")
        .replace("CNPJ", "cadastro de pessoa jurídica"),
        "sinteseDiscussao": sintese_discussao(resumo),
        "leituraHDoisComparaveis": leitura_h2_comparaveis(
            h2_comparaveis.iter_rows(named=True)
        ).replace("%", r"\%")
        + " "
        + nota_auditoria
        + " "
        + limite_h2(pasta).replace("%", r"\%"),
        "avisoAmostra": r"\textbf{Amostra sintética para teste.}" if sintetica else "",
    }
    return escrever_macros(numeros) + "".join(
        f"\\newcommand{{\\{nome}}}{{%\n{corpo}\n}}\n" for nome, corpo in campos.items()
    )


def contar_paginas(pdf: Path) -> int:
    """Páginas de um PDF: `pdfinfo` quando existe, senão contagem dos objetos /Type /Page."""
    if shutil.which("pdfinfo"):
        saida = subprocess.run(
            ["pdfinfo", str(pdf)], capture_output=True, text=True, errors="replace", check=True
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
        [
            ferramenta("latexmk"),
            "-pdf",
            "-interaction=nonstopmode",
            "-halt-on-error",
            principal.name,
        ],
        cwd=principal.parent,
        check=True,
        capture_output=True,
        text=True,
        errors="replace",
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
