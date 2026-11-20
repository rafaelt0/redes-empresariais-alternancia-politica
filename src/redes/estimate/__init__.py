"""Etapa `estimate`: RDD para H1 a H4, diagnósticos, placebos e robustez.

Cada hipótese monta a própria tabela com o núcleo de `rdd`; esta etapa lê os painéis uma
variante de rede por vez, grava as tabelas por hipótese da rede principal, a comparação entre
variantes, o teste de densidade e o resumo que o relatório e o deck leem. Toda tabela tem as
mesmas linhas com qualquer painel: o que não dá para estimar sai com `estimavel` falso e o
motivo. Contagens de 1 a `SUPRESSAO_MINIMA - 1` saem nulas.
"""

import os
import sys
from concurrent.futures import ProcessPoolExecutor
from functools import partial
from multiprocessing import get_context
from pathlib import Path

import polars as pl

from redes import figures
from redes.config import Caminhos
from redes.descritivas import suprimir
from redes.estimate import h1_h2, h3, h4, rdd, robustness
from redes.etapas import Contexto, Etapa
from redes.schemas import ELEICOES, PAINEL_FIRMA, PAINEL_REDE, VARIANTE

HIPOTESES = ("H1", "H2", "H3", "H4")
ARQUIVOS = (
    *(f"{h.lower()}.csv" for h in HIPOTESES),
    "robustez.csv",
    "densidade.csv",
    "resumo_estimacao.csv",
    "validacao.csv",
    "comparabilidade_h2.csv",
    "h2_comparaveis.csv",
    "sensibilidade_placebo.csv",
    "descritivas_estimacao.csv",
    "permanencia_h4.csv",
)

ETAPA = Etapa(
    nome="estimate",
    depende=("panel",),
    le=(PAINEL_FIRMA, PAINEL_REDE, ELEICOES),
    grava=(),
    artefatos=tuple(f"resultados/tables/{a}" for a in ARQUIVOS),
)

COLUNAS_RESUMO = (
    "hipotese",
    "categoria",
    "tipo",
    "resultado",
    "estimavel",
    "motivo",
    "estimativa",
    "ic_inf",
    "ic_sup",
    "p_valor",
    "p_holm",
    "n_testes_holm",
    "banda",
    "municipios_tratados",
    "municipios_controle",
    "unidades_tratadas",
    "unidades_controle",
    "estimativa_meia_banda",
    "estimativa_dobro_banda",
    "emd",
    "p_valor_rede",
    "redes_tratadas",
    "redes_controle",
    "placebo_estimativa",
    "placebo_p_valor",
    "densidade_p_valor",
)


def estimar_variante(painel_firma: pl.DataFrame, painel_rede: pl.DataFrame) -> pl.DataFrame:
    """H1 a H3 de uma variante da rede; H4 só entra na principal."""
    return pl.concat([h1_h2.h1(painel_firma), h1_h2.h2(painel_firma), h3.h3(painel_rede)])


def tabela_densidade(resultado: rdd.Densidade | rdd.NaoEstimavel) -> pl.DataFrame:
    estimado = isinstance(resultado, rdd.Densidade)
    return pl.DataFrame(
        {
            "estimavel": [estimado],
            "motivo": [None if estimado else resultado.motivo],
            "estatistica_t": [resultado.estatistica_t if estimado else None],
            "p_valor": [resultado.p_valor if estimado else None],
            "banda_tratados": [resultado.banda_tratados if estimado else None],
            "banda_controle": [resultado.banda_controle if estimado else None],
            "municipios_tratados": [resultado.contagem.municipios_tratados],
            "municipios_controle": [resultado.contagem.municipios_controle],
        },
        schema_overrides={
            "motivo": pl.String,
            **dict.fromkeys(
                ("estatistica_t", "p_valor", "banda_tratados", "banda_controle"), pl.Float64
            ),
        },
    )


def resumo(principal: pl.DataFrame, densidade: pl.DataFrame) -> pl.DataFrame:
    """Uma linha por categoria e contraste de H1 a H4 na rede principal, com placebo, Holm e
    o p-valor do teste de densidade, comum a todas."""
    chave = ["hipotese", "categoria", "tipo"]
    placebos = principal.filter("placebo").select(
        *chave,
        pl.col("estimativa").alias("placebo_estimativa"),
        pl.col("p_valor").alias("placebo_p_valor"),
    )
    na_familia = principal.select(h4.familia_holm()).to_series()
    p_valores = [
        p if dentro else None for p, dentro in zip(principal["p_valor"], na_familia, strict=True)
    ]
    p_holm = h4.holm(p_valores)
    n_testes_holm = sum(p is not None for p in p_valores)
    return (
        principal.with_columns(
            pl.Series("p_holm", p_holm, dtype=pl.Float64),
            n_testes_holm=pl.lit(n_testes_holm),
        )
        .filter(~pl.col("placebo"))
        .join(placebos, on=chave, how="left", maintain_order="left")
        .with_columns(densidade_p_valor=pl.lit(densidade["p_valor"].item(), pl.Float64))
        .select(COLUNAS_RESUMO)
    )


def suprimir_contagens(tabela: pl.DataFrame) -> pl.DataFrame:
    contagens = [c for c in tabela.columns if c.startswith(("municipios_", "unidades_", "redes_"))]
    if "tipo" in tabela.columns:
        # Cada componente pode ter uma banda diferente. Publicar a união também permite
        # reconstruir células pequenas quando os componentes são mutuamente exclusivos.
        return tabela.with_columns(
            pl.when(pl.col("tipo") != "contraste").then(suprimir(c)).alias(c) for c in contagens
        )
    return tabela.with_columns(suprimir(c) for c in contagens)


def _consolidar_validacao(diretorio: Path) -> None:
    tabelas = []
    for etapa, chaves in (
        ("rfb", {}),
        ("tse", {"indicador": "medida", "recorte": "categoria"}),
        ("tcesp", {}),
        ("panel", {}),
    ):
        arquivo = diretorio / f"validacao_{etapa}.csv"
        if arquivo.exists():
            tabelas.append(
                pl.read_csv(arquivo, schema_overrides={"valor": pl.Float64})
                .rename(chaves)
                .with_columns(etapa=pl.lit(etapa))
            )
    if tabelas:
        pl.concat(tabelas, how="diagonal_relaxed").select(
            "etapa", "medida", pl.exclude("etapa", "medida", "valor"), "valor"
        ).write_csv(diretorio / "validacao.csv")


def _graficos_rdd(
    ctx: Contexto, firma: pl.DataFrame, rede: pl.DataFrame, principal: pl.DataFrame
) -> None:
    graficos = (
        (
            "h1",
            firma,
            "conectada_incumbente",
            pl.col("faixa_a") == "0",
            h1_h2.RESULTADO,
            "Participação · conexão direta com A",
        ),
        (
            "h2",
            firma,
            "faixa_b_0",
            pl.col("faixa_b") == "0",
            h1_h2.RESULTADO,
            "Participação · conexão direta com B",
        ),
        (
            "h3",
            rede,
            "ambos",
            pl.col("ligacao") == "AMBOS",
            "variacao_total",
            "Variação total · redes A e B",
        ),
    )
    for nome, painel, categoria, filtro, resultado, rotulo in graficos:
        banda = (
            principal.filter(
                (pl.col("categoria") == categoria) & (pl.col("resultado") == resultado)
            )
            .get_column("banda")
            .item()
        )
        amostra = (
            painel.filter(filtro & pl.col(resultado).is_finite())
            .group_by("cod_municipio_tse")
            .agg(
                margem=pl.col("margem").first(),
                y=(pl.col("peso") * pl.col(resultado)).sum() / pl.col("peso").sum(),
            )
            .with_columns(peso=pl.lit(1.0))
            .sort("cod_municipio_tse")
        )
        with figures.matplotlib.rc_context(figures.estilo()):
            grafico = figures.rdd_plot(amostra, banda=banda, rotulo_y=rotulo)
            figures.salvar(grafico, f"rdd_{nome}", ctx.caminhos.resultados / "figures")


def _estimar_dados(caminhos: Caminhos, variante: str) -> pl.DataFrame:
    ctx = Contexto(ETAPA, caminhos)
    da_variante = pl.col("variante") == variante
    firma = ctx.ler(PAINEL_FIRMA).filter(da_variante).collect(engine="streaming")
    rede = ctx.ler(PAINEL_REDE).filter(da_variante).collect(engine="streaming")
    resultado = estimar_variante(firma, rede)
    if variante == "PRINCIPAL":
        resultado = pl.concat([resultado, h4.h4(rede)])
        tabelas = caminhos.resultados / "tables"
        h1_h2.comparabilidade(firma).write_csv(tabelas / "comparabilidade_h2.csv")
        h2_comparaveis = h1_h2.h2(firma, recorte_comparavel=True)
        suprimir_contagens(h2_comparaveis).write_csv(tabelas / "h2_comparaveis.csv")
        categorias_h2 = resultado.filter(
            (pl.col("hipotese") == "H2") & (pl.col("tipo") == "categoria") & ~pl.col("placebo")
        )
        sensibilidade, descritivas = h1_h2.diagnosticos_h2(firma, categorias_h2)
        suprimir_contagens(sensibilidade).write_csv(tabelas / "sensibilidade_placebo.csv")
        descritivas.write_csv(tabelas / "descritivas_estimacao.csv")
        h4.permanencia(rede).write_csv(tabelas / "permanencia_h4.csv")
        _graficos_rdd(ctx, firma, rede, resultado)
    print(f"estimate: variante {variante} concluída", file=sys.stderr)
    return resultado


def executar(ctx: Contexto) -> None:
    diretorio = ctx.caminhos.resultados / "tables"
    diretorio.mkdir(parents=True, exist_ok=True)
    variantes = VARIANTE.categories.to_list()
    estimar = partial(_estimar_dados, ctx.caminhos)
    processos = int(os.environ.get("REDES_PROCESSOS_ESTIMACAO", "1"))
    if not 1 <= processos <= len(variantes):
        raise ValueError(f"REDES_PROCESSOS_ESTIMACAO deve estar entre 1 e {len(variantes)}")
    if processos == 1:
        por_variante = {v: estimar(v) for v in variantes}
    else:
        with ProcessPoolExecutor(processos, mp_context=get_context("spawn")) as executor:
            por_variante = dict(zip(variantes, executor.map(estimar, variantes), strict=True))
    principal = por_variante["PRINCIPAL"]
    densidade = tabela_densidade(rdd.densidade(ctx.ler(ELEICOES).collect()))

    tabelas = {
        **{f"{h.lower()}.csv": principal.filter(pl.col("hipotese") == h) for h in HIPOTESES},
        "robustez.csv": robustness.comparar(por_variante),
        "densidade.csv": densidade,
        "resumo_estimacao.csv": resumo(principal, densidade),
    }
    for arquivo, tabela in tabelas.items():
        suprimir_contagens(tabela).write_csv(diretorio / arquivo)
    _consolidar_validacao(diretorio)
    figures.gerar_todas(ctx.caminhos)
