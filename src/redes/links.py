"""Etapa `links`: cruzamento sócio–doador e conexões diretas por município e grupo (T08).

Sócios e doadores já chegam com o mesmo pseudônimo (`redes.pseudonimo`), e o cruzamento é
uma junção por ele. Entram as doações de pessoas físicas até `config.DATA_LIMITE_DOACAO`,
incluindo recursos próprios do candidato conforme a decisão do PC1. A fotografia inclui
sócios ou administradores não sócios; a coluna `vinculo` diz qual, para que a variante sem
administradores descarte as linhas do segundo tipo.
Todas as empresas do sócio doador ficam conectadas, em qualquer município do país.
"""

import polars as pl

from redes import config
from redes.etapas import Contexto, Etapa
from redes.schemas import CONEXOES_DIRETAS, DOACOES, ELEICOES, GRUPO, SOCIOS

ARQUIVO_RESUMO = "links_pc1.csv"

ETAPA = Etapa(
    nome="links",
    depende=("ingest-rfb", "ingest-tse", "elections"),
    le=(SOCIOS, DOACOES, ELEICOES),
    grava=(CONEXOES_DIRETAS,),
    artefatos=(f"resultados/tables/{ARQUIVO_RESUMO}",),
)


def candidatos_dos_grupos(eleicoes: pl.LazyFrame) -> pl.LazyFrame:
    """Uma linha por município analisável e grupo: (cod_municipio_tse, grupo, sq_candidato)."""
    return pl.concat(
        eleicoes.select(
            "cod_municipio_tse",
            pl.lit(grupo, GRUPO).alias("grupo"),
            pl.col(f"sq_candidato_{grupo.lower()}").alias("sq_candidato"),
        )
        for grupo in ("A", "B")
    )


def doadores(
    doacoes: pl.LazyFrame,
    eleicoes: pl.LazyFrame,
    origens: tuple[str, ...] = ("PESSOA_FISICA", "RECURSOS_PROPRIOS"),
) -> pl.LazyFrame:
    """Doadores PF de cada grupo até a véspera da eleição: (município, grupo, id_pessoa, valor)."""
    receitas = doacoes.filter(
        (pl.col("ano") == config.ANO_ELEICAO)
        & (pl.col("tipo_doador") == "PF")
        & pl.col("origem").is_in(origens)
        & (pl.col("data_receita") <= config.DATA_LIMITE_DOACAO)
    ).select("sq_candidato", pl.col("id_doador").alias("id_pessoa"), "valor")
    return (
        candidatos_dos_grupos(eleicoes)
        .join(receitas, on="sq_candidato")
        .group_by("cod_municipio_tse", "grupo", "id_pessoa")
        .agg(pl.col("valor").sum().alias("valor_doado"))
    )


def vinculos_pf(socios: pl.LazyFrame) -> pl.LazyFrame:
    """Um vínculo por pessoa física e empresa, SOCIO quando alguma qualificação é de sócio."""
    return (
        socios.filter(pl.col("tipo_socio") == "PF")
        .group_by("cnpj_basico", pl.col("id_socio").alias("id_pessoa"))
        .agg((pl.col("vinculo") == "SOCIO").any().alias("socio"))
        .select(
            "cnpj_basico",
            "id_pessoa",
            pl.when("socio")
            .then(pl.lit("SOCIO"))
            .otherwise(pl.lit("ADMINISTRADOR_NAO_SOCIO"))
            .cast(SOCIOS.esquema["vinculo"])
            .alias("vinculo"),
        )
    )


def conexoes_diretas(socios: pl.LazyFrame, doadores_dos_grupos: pl.LazyFrame) -> pl.LazyFrame:
    pessoas = doadores_dos_grupos.select("id_pessoa").unique()
    vinculos = vinculos_pf(
        socios.join(pessoas, left_on="id_socio", right_on="id_pessoa", how="semi")
    )
    return (
        doadores_dos_grupos.join(vinculos, on="id_pessoa")
        .select(CONEXOES_DIRETAS.esquema.names())
        .sort("cod_municipio_tse", "grupo", "cnpj_basico", "id_pessoa")
    )


def _suprimir(contagem: int) -> int | None:
    return None if 0 < contagem < config.SUPRESSAO_MINIMA else contagem


def resumo_pc1(
    doadores_dos_grupos: pl.DataFrame,
    conexoes: pl.DataFrame,
    eleicoes: pl.DataFrame,
    autofinanciamento: pl.DataFrame | None = None,
    conexoes_autofinanciamento: pl.DataFrame | None = None,
    conexoes_terceiros: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """Agregados nacionais para o PC1, em formato longo (indicador, grupo, valor).

    Contagens de pessoas e empresas entre 1 e `SUPRESSAO_MINIMA - 1` saem nulas, e a taxa de
    cruzamento também quando uma das partes foi suprimida.
    """
    linhas: list[tuple[str, str | None, float | None]] = [
        ("municipios_analisaveis", None, _suprimir(eleicoes.height))
    ]
    municipios: dict[str, set[str]] = {}
    for grupo in ("A", "B"):
        doadores_k = doadores_dos_grupos.filter(pl.col("grupo") == grupo)
        conexoes_k = conexoes.filter(pl.col("grupo") == grupo)
        municipios[grupo] = set(conexoes_k["cod_municipio_tse"])
        n_doadores = _suprimir(doadores_k["id_pessoa"].n_unique())
        n_cruzados = _suprimir(conexoes_k["id_pessoa"].n_unique())
        taxa = n_cruzados / n_doadores if n_doadores and n_cruzados is not None else None
        linhas += [
            ("doadores_pf", grupo, n_doadores),
            ("doadores_pf_com_empresa", grupo, n_cruzados),
            ("taxa_cruzamento", grupo, taxa),
            ("empresas_conectadas", grupo, _suprimir(conexoes_k["cnpj_basico"].n_unique())),
            ("municipios_com_conexao", grupo, _suprimir(len(municipios[grupo]))),
        ]
        if (
            autofinanciamento is not None
            and conexoes_autofinanciamento is not None
            and conexoes_terceiros is not None
        ):
            proprias = conexoes_autofinanciamento.filter(pl.col("grupo") == grupo)
            de_terceiros = conexoes_terceiros.filter(pl.col("grupo") == grupo)
            novas = proprias.join(de_terceiros, on=["cod_municipio_tse", "cnpj_basico"], how="anti")
            linhas += [
                (
                    "candidatos_autofinanciados",
                    grupo,
                    _suprimir(
                        autofinanciamento.filter(pl.col("grupo") == grupo)[
                            "cod_municipio_tse"
                        ].n_unique()
                    ),
                ),
                (
                    "empresas_conectadas_por_autofinanciamento",
                    grupo,
                    _suprimir(proprias["cnpj_basico"].n_unique()),
                ),
                (
                    "empresas_conectadas_so_por_autofinanciamento",
                    grupo,
                    _suprimir(novas["cnpj_basico"].n_unique()),
                ),
            ]
    ambos = _suprimir(len(municipios["A"] & municipios["B"]))
    linhas.append(("municipios_com_conexao", "AMBOS", ambos))
    return pl.DataFrame(
        linhas,
        schema={"indicador": pl.String, "grupo": pl.String, "valor": pl.Float64},
        orient="row",
    )


def executar(ctx: Contexto) -> None:
    eleicoes = ctx.ler(ELEICOES).collect()
    doacoes = ctx.ler(DOACOES)
    doadores_dos_grupos = doadores(doacoes, eleicoes.lazy()).collect()
    conexoes = conexoes_diretas(ctx.ler(SOCIOS), doadores_dos_grupos.lazy()).collect(
        engine="streaming"
    )
    ctx.gravar(CONEXOES_DIRETAS, conexoes)
    autofinanciamento = doadores(doacoes, eleicoes.lazy(), ("RECURSOS_PROPRIOS",)).collect()
    terceiros = doadores(doacoes, eleicoes.lazy(), ("PESSOA_FISICA",)).collect()
    chaves = ["cod_municipio_tse", "grupo", "id_pessoa"]
    conexoes_autofinanciamento = conexoes.join(autofinanciamento, on=chaves, how="semi")
    conexoes_terceiros = conexoes.join(terceiros, on=chaves, how="semi")
    tabelas = ctx.caminhos.resultados / "tables"
    tabelas.mkdir(parents=True, exist_ok=True)
    resumo_pc1(
        doadores_dos_grupos,
        conexoes,
        eleicoes,
        autofinanciamento,
        conexoes_autofinanciamento,
        conexoes_terceiros,
    ).write_csv(tabelas / ARQUIVO_RESUMO)
