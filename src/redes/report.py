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


def _status_contraste(linha: dict, hipotese: str = "") -> str:
    inferior, superior = linha.get("ic_inf"), linha.get("ic_sup")
    if inferior is None or superior is None:
        return "indefinido"
    if hipotese == "H4" and (linha.get("p_holm") is None or linha["p_holm"] >= 0.05):
        return "inconclusivo_holm"
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
                _numero(linha, "p_holm", 3) if h == "H4" else "---",
            ]
        )
    densidade = _numero(resumo.row(0, named=True), "densidade_p_valor", 3) if resumo.height else ND
    n_holm = _numero(resumo.row(0, named=True), "n_testes_holm", 0) if resumo.height else ND
    nota_holm = (
        rf" Holm: {n_holm} testes (categorias de H1/H2/H4 e contrastes de H4)."
        if n_holm != ND
        else ""
    )
    return _quadro(
        "tab:estimativas",
        "Contrastes no corte eleitoral",
        (
            "Hipótese",
            "Efeito",
            "IC",
            "$b/2$",
            "$2b$",
            "Pré (nível)",
            "$p_{pl}$",
            "EMD",
            "$p_{Holm}$",
        ),
        corpo,
        rf"Unidades: fração da participação no elemento (H1--H2), fração do gasto anual médio "
        rf"pré-eleitoral (H3) e probabilidade de permanência (H4). Pontos corrigidos pelo viés; "
        rf"IC normal de 95\% com erro-padrão por reamostragem de municípios e bandas fixas. "
        rf"Pré (nível): participação anterior, inclusive em H4; "
        rf"H3 repete o mesmo teste nos termos. "
        rf"n.d.: sem suporte/ajuste estimável. Densidade: "
        rf"{densidade}. EMD: poder de 80\%, nível de 5\%. Bandas e suporte por categoria no CSV."
        + nota_holm,
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
        r"Pontos e IC robusto de 95\% corrigidos pelo viés (CCT). Bandas em p.p.; Esq./Dir. contam "
        r"municípios com derrota ($T_m=1$) e vitória ($T_m=0$) na banda. O valor-p por rede "
        r"exige ao menos dez redes por lado. Contagens por rede e demais recortes em "
        r"resumo\_estimacao.csv. Linhas em AMBOS são saltos internos (IC CCT); o Quadro 1 "
        r"subtrai o salto nas demais redes (IC bootstrap). "
        r"Pontos próximos não implicam ICs iguais. "
        r"A aproximação assintótica é frágil com poucas unidades.",
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
        r"Unidades como no Quadro~\ref{tab:estimativas}. Asterisco indica IC de 95\% que exclui "
        r"zero; n.d.\ indica suporte insuficiente (menos de dez municípios em um dos lados). "
        r"Sem articulação: sementes reselecionadas, como em robustez.csv. A sensibilidade "
        r"adicional com sementes fixas é distinta. Intervalos completos nos respectivos CSVs.",
    )


def sintese_principal(resumo: pl.DataFrame) -> str:
    """Resumo enxuto dos achados principais para antecipar o resultado na seção 1."""
    if resumo.is_empty():
        return ""
    linhas = _indexar(resumo)
    h1 = linhas.get(("H1", "conectada_menos_sem_conexao", "participacao_2025", "contraste"), {})
    h2_0 = linhas.get(("H2", "vencedor_faixa_0", "participacao_2025", "contraste"), {})
    h2_1 = linhas.get(("H2", "vencedor_faixa_1", "participacao_2025", "contraste"), {})
    h3 = linhas.get(("H3", "ambos_menos_demais", "variacao_total", "contraste"), {})
    nulos = []
    destaques = []
    for nome, linha, unidade, h in (
        ("H1", h1, "p.p.", "H1"),
        (r"H2 ($\delta=0$)", h2_0, "p.p.", "H2"),
        ("H3", h3, r"\% do gasto prévio", "H3"),
    ):
        st = _status_contraste(linha, h)
        if st == "nulo":
            nulos.append(nome)
        elif st in ("positivo", "negativo"):
            destaques.append(f"{nome} ({_valor_unidade(_pp(linha, 'estimativa'), unidade)})")

    if not nulos and not destaques:
        return ""

    partes = []
    if nulos and not destaques:
        emd_h1 = _pp(h1, "emd")
        trecho_emd = (
            f" — mas com intervalos largos (EMD de {emd_h1} p.p. em H1)" if emd_h1 != ND else ""
        )
        partes.append(
            f"Nas eleições paulistas de 2024, os contrastes principais de {_juntar_lista(nulos)} "
            f"são estatisticamente indistinguíveis de zero{trecho_emd}."
        )
    elif destaques and not nulos:
        partes.append(
            f"Nas eleições paulistas de 2024, observamos efeitos distintos de zero em "
            f"{_juntar_lista(destaques)}."
        )
    else:
        partes.append(
            f"Nas eleições paulistas de 2024, {_juntar_lista(destaques)} diferem de zero, "
            f"enquanto {_juntar_lista(nulos)} incluem zero."
        )

    extras = []
    st_h2_1 = _status_contraste(h2_1, "H2")
    if st_h2_1 == "negativo":
        extras.append(
            rf"o IC nominal a um passo ($\delta=1$) exclui zero na especificação principal "
            rf"({_pp(h2_1, 'estimativa')} p.p.), mas a leitura depende dos diagnósticos "
            r"pré-eleitorais"
        )
    elif st_h2_1 == "positivo":
        extras.append(
            rf"o contraste a um passo ($\delta=1$) é positivo ({_pp(h2_1, 'estimativa')} p.p.)"
        )

    if extras:
        primeira = extras[0][0].upper() + extras[0][1:]
        resto = "; ".join([primeira, *extras[1:]])
        partes.append(resto + ".")
    return " ".join(partes)


def leitura_resultados(resumo: pl.DataFrame) -> str:
    """Leitura orientada a magnitude, precisão (EMD) e diagnósticos de placebo/densidade."""
    if resumo.is_empty():
        return ""
    linhas = _indexar(resumo)
    frases = []

    dens = resumo.row(0, named=True).get("densidade_p_valor")
    if dens is not None:
        if dens >= 0.05:
            frases.append(
                f"O teste de densidade não indica manipulação da margem no corte "
                f"($p = {_decimal_math(dens, 3)}$)."
            )
        else:
            frases.append(
                f"O teste de densidade sugere descontinuidade na margem "
                f"($p = {_decimal_math(dens, 3)}$)."
            )

    h1 = linhas.get(("H1", "conectada_menos_sem_conexao", "participacao_2025", "contraste"), {})
    h2_0 = linhas.get(("H2", "vencedor_faixa_0", "participacao_2025", "contraste"), {})
    h2_1 = linhas.get(("H2", "vencedor_faixa_1", "participacao_2025", "contraste"), {})
    h2_3 = linhas.get(("H2", "vencedor_faixa_3+", "participacao_2025", "contraste"), {})
    h3 = linhas.get(("H3", "ambos_menos_demais", "variacao_total", "contraste"), {})
    h4 = linhas.get(("H4", "ligada_ao_vencedor_50", "mantem_posicao_50", "contraste"), {})

    nulos_imprecisos = []
    for rotulo, linha, unidade, unidade_emd, h in (
        ("H1", h1, "p.p.", "p.p.", "H1"),
        (r"H2 em $\delta=0$", h2_0, "p.p.", "p.p.", "H2"),
        ("H3 total", h3, r"\% do gasto prévio", r"\%", "H3"),
    ):
        st = _status_contraste(linha, h)
        if st == "nulo":
            est = _valor_unidade(_pp(linha, "estimativa"), unidade)
            emd = _valor_unidade(_pp(linha, "emd"), unidade_emd)
            detalhe = f"{est}; EMD {emd}" if emd != ND else est
            nulos_imprecisos.append(f"{rotulo} ({detalhe})")
        elif st in ("positivo", "negativo"):
            direcao = "positivo" if st == "positivo" else "negativo"
            est = _valor_unidade(_pp(linha, "estimativa"), unidade)
            frases.append(f"O contraste de {rotulo} foi {direcao} ({est}).")

    if nulos_imprecisos:
        frases.append(
            f"Os contrastes de {_juntar_lista(nulos_imprecisos)} cruzam zero com intervalos "
            f"largos, o que impede descartar efeitos economicamente relevantes."
        )
    instaveis = [
        nome
        for nome, linha in (("H1", h1), (r"H2 em $\delta=0$", h2_0))
        if linha.get("estimativa") is not None
        and linha.get("estimativa_meia_banda") is not None
        and linha["estimativa"] * linha["estimativa_meia_banda"] < 0
    ]
    if instaveis:
        frases.append(
            f"{_juntar_lista(instaveis)} mudam de sinal em meia banda, reforçando a instabilidade."
        )

    if (
        _status_contraste(h2_3, "H2") == "nulo"
        and h2_3.get("emd") is not None
        and h2_3["emd"] < 0.01
    ):
        frases.append(
            r"Condicional às coortes e à inferência municipal, o contraste em $\delta=3+$ "
            r"tem magnitudes "
            rf"pequenas ({_pp(h2_3, 'estimativa')} p.p.; EMD de {_pp(h2_3, 'emd')} p.p.)."
        )

    st_h2_1 = _status_contraste(h2_1, "H2")
    if st_h2_1 in ("positivo", "negativo"):
        direcao = "negativo" if st_h2_1 == "negativo" else "positivo"
        nota_pl = ""
        if h2_1.get("placebo_estimativa") is not None and h2_1.get("placebo_p_valor") is not None:
            nota_pl = (
                f", mas o placebo pré-eleitoral aponta na mesma direção "
                f"({_pp(h2_1, 'placebo_estimativa')} p.p., "
                f"$p = {_decimal_math(h2_1['placebo_p_valor'], 3)}$)"
                if (h2_1["placebo_estimativa"] * h2_1["estimativa"] > 0)
                else ""
            )
        frases.append(
            rf"Em H2 ($\delta=1$), o contraste foi {direcao} "
            rf"({_pp(h2_1, 'estimativa')} p.p.){nota_pl}."
        )
        if direcao == "negativo":
            frases.append(
                "O ponto contraria a vantagem ao vencedor prevista sob comparabilidade; "
                "os diagnósticos fragilizam essa leitura."
            )
    elif st_h2_1 == "nulo":
        frases.append(r"O contraste de H2 ($\delta=1$) também inclui zero.")

    b1 = linhas.get(("H2", "faixa_b_1", "participacao_2025", "categoria"), {})
    if b1.get("p_holm") is not None:
        frases.append(
            rf"H2 é contraste principal com inferência nominal; o efeito isolado de B a um "
            rf"passo tem $p_{{Holm}}={_decimal_math(b1['p_holm'], 3)}$ na família secundária."
        )

    if h3.get("placebo_p_valor") is not None and h3.get("placebo_estimativa") is not None:
        direcao = (
            " no mesmo sentido do contraste pós,"
            if h3.get("estimativa") is not None and h3["placebo_estimativa"] * h3["estimativa"] > 0
            else ""
        )
        frases.append(
            rf"O placebo de nível de H3 é {_pp(h3, 'placebo_estimativa')} p.p. de participação "
            rf"prévia ($p={_decimal_math(h3['placebo_p_valor'], 3)}$),{direcao} exigindo cautela "
            r"sobre continuidade; ele mede nível prévio, não a variação normalizada do pós."
        )

    st_h4 = _status_contraste(h4, "H4")
    if st_h4 == "inconclusivo_holm":
        emd_h4 = _pp(h4, "emd")
        sufixo = f" (EMD de {emd_h4} p.p.)" if emd_h4 != ND else ""
        frases.append(
            rf"O contraste de H4 (50\%) permaneceu inconclusivo após a correção de Holm{sufixo}."
        )
        if h4.get("emd") is not None and h4["emd"] > 1:
            frases.append(
                "Seu EMD excede o suporte probabilístico: o teste tem pouco poder prático."
            )
        b75 = linhas.get(("H4", "ligada_b_75", "mantem_posicao_75", "categoria"), {})
        if b75.get("banda") is not None:
            frases.append(
                rf"A banda de H4 (75\%), coorte B, é {_numero(b75, 'banda', 1)} p.p., "
                "restringindo sua leitura como comparação local."
            )
    elif st_h4 in ("positivo", "negativo"):
        frases.append(
            rf"O contraste de H4 (50\%) foi {st_h4} ({_pp(h4, 'estimativa')} p.p.) mesmo após Holm."
        )
    elif st_h4 == "indefinido":
        frases.append(r"O contraste de H4 (50\%) não foi estimável.")

    r1 = linhas.get(("H3", "ambos", "termo_r1", "categoria"), {})
    compensacao = linhas.get(("H3", "ambos", "termo_compensacao", "categoria"), {})
    if r1.get("ic_sup") is None or compensacao.get("ic_inf") is None:
        frases.append("A compensação dentro das redes ligadas a ambos ficou sem estimativa.")
    elif r1["ic_sup"] < 0 < compensacao["ic_inf"]:
        frases.append(
            "Em redes ligadas a ambos, R1 caiu e R2+R3 cresceu, como prevê a compensação."
        )
    else:
        frases.append(
            "Dentro das redes ligadas a ambos, os intervalos de R1 e R2+R3 "
            "não confirmam compensação."
        )
        if (
            _status_contraste(r1) == _status_contraste(compensacao) == "nulo"
            and (r1.get("estimativa") or 0) > 0
            and (compensacao.get("estimativa") or 0) < 0
        ):
            frases.append(
                "Os pontos têm sinais inversos aos previstos para compensação "
                "(R1 negativo e R2+R3 positivo), sem rejeitar zero."
            )
    return " ".join(frases)


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
    h3_tot = linhas.get(("H3", "ambos_menos_demais", "variacao_total", "contraste"), {})
    h3_r2 = linhas.get(("H3", "ambos_menos_demais", "termo_r2", "contraste"), {})

    frases = [
        "As variantes reconstroem coortes e reselecionam bandas; diferenças entre colunas "
        "também refletem composição, sem manter fixo o estimando."
    ]
    estaveis_nulos = []
    for nome, linha in (("H1", h1), (r"H2 em $\delta=0$", h2_0)):
        validos = [e for v in variantes if (e := _significativa(linha, v)) is not None]
        if validos and not any(validos):
            estaveis_nulos.append(nome)
    if estaveis_nulos:
        frases.append(
            f"Os contrastes diretos ({_juntar_lista(estaveis_nulos)}) permanecem indistinguíveis "
            f"de zero em todas as variantes da rede."
        )

    pj_sig = []
    for nome, linha in (("H3 total", h3_tot), ("H3 R2", h3_r2)):
        if _significativa(linha, "sem_pj") and not _significativa(linha, "principal"):
            pj_sig.append(f"{nome} ({_pp(linha, 'estimativa_sem_pj')}\\%)")
    if pj_sig:
        frases.append(
            f"Sem sócios PJ, {_juntar_lista(pj_sig)} passam a excluir zero no sentido negativo, "
            f"mas sem evidência de ganho compensatório em R3."
        )

    tem_nd = any(
        linhas.get((h, c, r, "contraste"), {}).get(f"estimativa_{v}") is None
        for h, c, r, _ in CONTRASTES
        if h != "H4"
        for v in ("sem_articulacao", "sem_administrador")
    )
    if tem_nd:
        frases.append(
            "A remoção de pontos de articulação ou de administradores fragmenta os componentes "
            "e reduz o suporte municipal abaixo de dez municípios por lado em alguns contrastes "
            "indiretos e de rede (n.d.)."
        )
    return " ".join(frases)


def sintese_discussao(resumo: pl.DataFrame) -> str:
    """Abertura concreta da seção de discussão, ancorada nas estimativas e na literatura."""
    if resumo.is_empty():
        return ""
    linhas = _indexar(resumo)
    h1 = linhas.get(("H1", "conectada_menos_sem_conexao", "participacao_2025", "contraste"), {})
    h2_0 = linhas.get(("H2", "vencedor_faixa_0", "participacao_2025", "contraste"), {})
    h3 = linhas.get(("H3", "ambos_menos_demais", "variacao_total", "contraste"), {})
    r1 = linhas.get(("H3", "ambos", "termo_r1", "categoria"), {})
    comp = linhas.get(("H3", "ambos", "termo_compensacao", "categoria"), {})

    sem_ganho_direto = _status_contraste(h1, "H1") in ("nulo", "negativo") and _status_contraste(
        h2_0, "H2"
    ) in ("nulo", "negativo")
    sem_comp = not (
        r1.get("ic_sup") is not None
        and comp.get("ic_inf") is not None
        and r1["ic_sup"] < 0 < comp["ic_inf"]
    )
    if sem_ganho_direto and sem_comp:
        return (
            r"Não há evidência consistente de ganho para firmas ligadas ao vencedor nem de "
            r"compensação interna na rede dominante. Os ICs admitem efeitos relevantes. "
            r"A precisão de H2 indireta é condicional à inferência municipal na rede observada; "
            r"seu alcance não se estende a outros componentes. "
            r"Diferimos dos retornos sob doações "
            r"PJ ou compras federais \cite{boas2014,baltrunaite2020}: doações PF podem ser sinal "
            r"mais fraco de conexão; o desenho não distingue isso de ausência de transmissão."
        )
    if _status_contraste(h3, "H3") in ("positivo", "negativo") or not sem_comp:
        return (
            r"Os resultados indicam assimetrias na alocação após disputas apertadas que dialogam "
            r"com a literatura sobre conexões políticas em compras públicas "
            r"\cite{boas2014,baltrunaite2020}, mas exigem leitura conjunta com os placebos, os "
            r"EMDs e a sensibilidade à definição da rede."
        )
    return (
        r"Os resultados oferecem evidência mista entre conexões diretas e indiretas, devendo ser "
        r"lidos em conjunto com os intervalos de confiança, os placebos pré-eleitorais e os EMDs "
        r"em comparação com \citeonline{boas2014} e \citeonline{baltrunaite2020}."
    )


def _ler_tabela(pasta: Path, nome: str) -> pl.DataFrame:
    return pl.read_csv(pasta / nome) if (pasta / nome).is_file() else pl.DataFrame()


def numeros_tex(pasta: Path, sintetica: bool = False) -> str:
    resumo = _ler_tabela(pasta, "resumo_estimacao.csv")
    robustez = _ler_tabela(pasta, "robustez.csv")
    h2_comparaveis = _ler_tabela(pasta, "h2_comparaveis.csv")
    auditoria = _ler_tabela(pasta, "auditoria_h2_comparaveis.csv")
    nota_auditoria = ""
    if not auditoria.is_empty():
        a = auditoria.row(0, named=True)
        if all(a.get(c) is not None for c in ("estratos", "jaccard", "correlacao_bootstrap")):
            nota_auditoria = (
                f"Nesse recorte exploratório, há {decimal(a['estratos'], 0)} estratos e "
                f"Jaccard de {decimal(100 * a['jaccard'], 1)}\\%; nas bandas próprias, "
                "a correlação "
                f"dos saltos reamostrados é {decimal(a['correlacao_bootstrap'], 3)} "
                f"({decimal(a['replicas_validas'], 0)} réplicas válidas), explicando o IC estreito "
                "da pequena diferença entre coortes quase coincidentes."
            )
    verificacoes = leitura_sensibilidades(pasta)
    estrutural = [f for f in verificacoes if f.startswith("O gigante")]

    def texto_verificacoes(frases: list[str]) -> str:
        return " ".join(frases).replace("%", r"\%").replace("δ = 1", r"$\delta=1$")

    campos = {
        "tabelaEstimativas": tabela_estimativas(resumo),
        "tabelaCategorias": tabela_categorias(resumo),
        "tabelaRobustez": tabela_robustez(robustez),
        "sintesePrincipal": sintese_principal(resumo),
        "leituraResultados": leitura_resultados(resumo),
        "leituraRobustez": leitura_robustez(robustez),
        "leituraSensibilidades": texto_verificacoes(
            [f for f in verificacoes if f not in estrutural]
        ),
        "sinteseEstrutural": texto_verificacoes(estrutural).replace(
            "AMBOS", "redes ligadas aos dois grupos"
        ),
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
