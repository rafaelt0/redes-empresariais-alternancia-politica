"""Etapa `elections`: grupo incumbente, margem M_m, tratamento T_m e exclusões (T07).

Cada município com candidatos a prefeito em 2024 sai em exatamente uma das duas tabelas:
`eleicoes`, se é analisável, ou `exclusoes`, com o primeiro motivo que se aplica, nesta ordem:
segundo turno, prefeito indefinido, sem candidato do grupo incumbente, ruptura, sem adversário.

Casos de borda que a seção 6 do projeto não fixa, resolvidos pela leitura mais literal:
- concorre quem tem voto válido no primeiro turno de 2024; candidaturas indeferidas, renunciadas
  ou com votos anulados não contam para o protocolo nem como adversário;
- o prefeito que concorre por outro partido continua no ramo PREFEITO;
- mais de um candidato no primeiro ramo que encontra alguém (partido ou coligação) é RUPTURA,
  pois o grupo incumbente não é identificável sem escolher entre eles;
- empate de votos no segundo lugar escolhe B pelo menor `sq_candidato`, o que não muda M_m;
- empate exato entre A e B dá M_m = 0 e T_m = 0, já que T_m = 1 só quando M_m < 0.
"""

import sys

import polars as pl

from redes import config
from redes.etapas import Contexto, Etapa
from redes.schemas import CANDIDATOS, ELEICOES, EXCLUSOES, MOTIVO_EXCLUSAO, RAMO, VOTOS

ETAPA = Etapa(
    nome="elections",
    depende=("ingest-tse",),
    le=(CANDIDATOS, VOTOS),
    grava=(ELEICOES, EXCLUSOES),
)

MUN = "cod_municipio_tse"

# Ordem do protocolo da seção 6: o primeiro ramo com algum candidato decide.
RAMOS = (
    ("PREFEITO", pl.col("id_pessoa") == pl.col("id_prefeito")),
    ("PARTIDO", pl.col("sigla_partido") == pl.col("partido_prefeito")),
    ("COLIGACAO", pl.col("partidos_coligacao").list.contains(pl.col("partido_prefeito"))),
)

_ORDINARIA_2024 = (pl.col("ano") == config.ANO_ELEICAO) & (pl.col("tipo_eleicao") == "ORDINARIA")


def prefeitos(candidatos: pl.LazyFrame) -> pl.LazyFrame:
    """Eleitos na eleição mais recente anterior a 6/10/2024 de cada município.

    A suplementar mais recente substitui a ordinária de 2020 (decisão registrada na SPEC).
    `n_eleitos` diferente de 1 deixa o prefeito indefinido.
    """
    anteriores = candidatos.filter(pl.col("data_eleicao") < config.DATA_ELEICAO)
    ultima = anteriores.filter(pl.col("data_eleicao") == pl.col("data_eleicao").max().over(MUN))
    eleito = pl.col("eleito").fill_null(False)
    return ultima.group_by(MUN).agg(
        pl.col("data_eleicao").first().alias("data_ultima_eleicao"),
        eleito.sum().cast(pl.Int64).alias("n_eleitos"),
        pl.col("id_pessoa").filter(eleito).first().alias("id_prefeito"),
        pl.col("sigla_partido").filter(eleito).first().alias("partido_prefeito"),
    )


def concorrentes(candidatos: pl.LazyFrame, votos: pl.LazyFrame) -> pl.LazyFrame:
    """Candidatos de 2024 com voto válido no primeiro turno, com seus votos."""
    primeiro_turno = votos.filter(
        (pl.col("ano") == config.ANO_ELEICAO) & (pl.col("turno") == 1) & (pl.col("votos") > 0)
    ).select(MUN, "sq_candidato", "votos")
    return (
        candidatos.filter(_ORDINARIA_2024)
        .select(MUN, "sq_candidato", "id_pessoa", "sigla_partido", "partidos_coligacao")
        .join(primeiro_turno, on=[MUN, "sq_candidato"], how="inner")
    )


def classificar(candidatos: pl.LazyFrame, votos: pl.LazyFrame) -> tuple[pl.LazyFrame, pl.LazyFrame]:
    """Aplica o protocolo do grupo incumbente; devolve (`eleicoes`, `exclusoes`)."""
    municipios = candidatos.filter(_ORDINARIA_2024).select(MUN).unique()
    segundo_turno = (
        votos.filter((pl.col("ano") == config.ANO_ELEICAO) & (pl.col("turno") == 2))
        .select(MUN)
        .unique()
        .with_columns(pl.lit(True).alias("segundo_turno"))
    )
    prefeito = prefeitos(candidatos)
    marcados = (
        concorrentes(candidatos, votos)
        .join(prefeito.filter(pl.col("n_eleitos") == 1), on=MUN, how="left")
        .with_columns(expr.fill_null(False).alias(ramo) for ramo, expr in RAMOS)
    )

    ramo_decisivo = pl.coalesce(
        pl.when(pl.col(f"n_{ramo}") > 0).then(pl.lit(ramo)) for ramo, _ in RAMOS
    )
    n_decisivo = pl.coalesce(
        pl.when(pl.col(f"n_{ramo}") > 0).then(pl.col(f"n_{ramo}")) for ramo, _ in RAMOS
    )
    por_municipio = (
        marcados.group_by(MUN)
        .agg(
            pl.col("votos").sum().alias("votos_validos"),
            *(pl.col(ramo).sum().cast(pl.Int64).alias(f"n_{ramo}") for ramo, _ in RAMOS),
        )
        .with_columns(ramo_decisivo.alias("ramo"), n_decisivo.alias("n_decisivo"))
    )

    no_ramo = pl.coalesce(pl.when(pl.col("ramo") == r).then(pl.col(r)) for r, _ in RAMOS)
    candidato_a = (
        marcados.join(por_municipio.select(MUN, "ramo", "n_decisivo"), on=MUN)
        .filter(no_ramo & (pl.col("n_decisivo") == 1))
        .select(
            MUN, pl.col("sq_candidato").alias("sq_candidato_a"), pl.col("votos").alias("votos_a")
        )
    )
    candidato_b = (
        marcados.join(candidato_a, on=MUN)
        .filter(pl.col("sq_candidato") != pl.col("sq_candidato_a"))
        .sort(["votos", "sq_candidato"], descending=[True, False])
        .group_by(MUN, maintain_order=True)
        .first()
        .select(
            MUN, pl.col("sq_candidato").alias("sq_candidato_b"), pl.col("votos").alias("votos_b")
        )
    )

    motivo = (
        pl.when(pl.col("segundo_turno").fill_null(False))
        .then(
            pl.struct(motivo=pl.lit("SEGUNDO_TURNO"), detalhe=pl.lit("houve segundo turno em 2024"))
        )
        .when(pl.col("n_eleitos").is_null())
        .then(
            pl.struct(
                motivo=pl.lit("PREFEITO_INDEFINIDO"),
                detalhe=pl.lit("sem eleição para prefeito anterior a 2024"),
            )
        )
        .when(pl.col("n_eleitos") != 1)
        .then(
            pl.struct(
                motivo=pl.lit("PREFEITO_INDEFINIDO"),
                detalhe=pl.format(
                    "{} eleitos na eleição de {}", "n_eleitos", "data_ultima_eleicao"
                ),
            )
        )
        .when(pl.col("ramo").is_null())
        .then(
            pl.struct(
                motivo=pl.lit("SEM_CANDIDATO"),
                detalhe=pl.format(
                    "prefeito não concorre; nenhum candidato do {} nem de coligação com ele",
                    "partido_prefeito",
                ),
            )
        )
        .when(pl.col("n_decisivo") > 1)
        .then(
            pl.struct(
                motivo=pl.lit("RUPTURA"),
                detalhe=pl.format("{} candidatos no ramo {}", "n_decisivo", "ramo"),
            )
        )
        .when(pl.col("sq_candidato_b").is_null())
        .then(
            pl.struct(
                motivo=pl.lit("SEM_ADVERSARIO"),
                detalhe=pl.lit("único candidato com voto válido no primeiro turno"),
            )
        )
    )
    todos = (
        municipios.join(segundo_turno, on=MUN, how="left")
        .join(prefeito, on=MUN, how="left")
        .join(por_municipio, on=MUN, how="left")
        .join(candidato_a, on=MUN, how="left")
        .join(candidato_b, on=MUN, how="left")
        .with_columns(motivo.alias("exclusao"))
        .unnest("exclusao")
        .sort(MUN)
    )

    margem = (pl.col("votos_a") - pl.col("votos_b")) / pl.col("votos_validos") * 100
    eleicoes = todos.filter(pl.col("motivo").is_null()).select(
        MUN,
        pl.col("ramo").cast(RAMO),
        "sq_candidato_a",
        "sq_candidato_b",
        "votos_validos",
        margem.alias("margem"),
        (margem < 0).cast(pl.Int8).alias("tratamento"),
    )
    exclusoes = todos.filter(pl.col("motivo").is_not_null()).select(
        MUN, pl.col("motivo").cast(MOTIVO_EXCLUSAO), "detalhe"
    )
    return eleicoes, exclusoes


def resumo(eleicoes: pl.DataFrame, exclusoes: pl.DataFrame) -> str:
    """Contagens para o ponto de controle de viabilidade: ramos, motivos e |M_m| acumulada."""
    absoluta = pl.col("margem").abs()
    partes = [
        eleicoes.group_by("ramo").len().sort("ramo"),
        exclusoes.group_by("motivo").len().sort("motivo"),
        eleicoes.select(
            *((absoluta <= p).sum().alias(f"|M| <= {p}") for p in (2, 5, 10, 20)),
            pl.len().alias("total"),
        ),
    ]
    return "\n".join(str(p) for p in partes)


def executar(ctx: Contexto) -> None:
    eleicoes, exclusoes = (t.collect() for t in classificar(ctx.ler(CANDIDATOS), ctx.ler(VOTOS)))
    if eleicoes.is_empty():
        raise ValueError(f"elections: nenhum município analisável ({exclusoes.height} excluídos)")
    ctx.gravar(ELEICOES, eleicoes)
    ctx.gravar(EXCLUSOES, exclusoes)
    print(resumo(eleicoes, exclusoes), file=sys.stderr)
