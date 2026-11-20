"""Placebo de mudança de participação entre duas janelas pré-eleitorais de H1 e H2."""

from pathlib import Path
from tempfile import TemporaryDirectory

import duckdb
import polars as pl

from redes import config, panel, schemas
from redes.estimate import h1_h2, rdd, suprimir_contagens

CHAVE = schemas.PAINEL_FIRMA.chave[1:]
PRIMEIRA = "participacao_2021_2022"
SEGUNDA = "participacao_2023_set2024"
RESULTADO = "variacao_pre_periodos"
ARQUIVO = "sensibilidade_pre_periodos.csv"


def com_variacao(painel: pl.DataFrame, agregado: pl.DataFrame) -> pl.DataFrame:
    """Acrescenta o desfecho pré-eleitoral às linhas da amostra principal."""
    saldos = agregado.select(
        *CHAVE,
        pl.sum_horizontal(panel.COLUNAS_PRE[:2]).clip(lower_bound=0).alias(PRIMEIRA),
        pl.sum_horizontal(panel.COLUNAS_PRE[2:]).clip(lower_bound=0).alias(SEGUNDA),
    )
    participacoes = []
    for coluna in (PRIMEIRA, SEGUNDA):
        positivo = pl.col(coluna)
        total = positivo.sum().over(panel.MERCADO)
        participacoes.append(pl.when(total > 0).then(positivo / total).otherwise(0.0).alias(coluna))
    return (
        painel.join(
            saldos.with_columns(participacoes),
            on=CHAVE,
            how="left",
            validate="1:1",
            maintain_order="left",
        )
        .with_columns(pl.col(PRIMEIRA, SEGUNDA).fill_null(0))
        .with_columns((pl.col(SEGUNDA) - pl.col(PRIMEIRA)).alias(RESULTADO))
    )


def estimar(painel: pl.DataFrame, referencia: pl.DataFrame) -> pl.DataFrame:
    """Estima os contrastes com as bandas das categorias do desfecho de 2025."""
    principal = referencia.filter(
        (pl.col("tipo") == "categoria")
        & (pl.col("resultado") == h1_h2.RESULTADO)
        & ~pl.col("placebo")
        & pl.col("estimavel")
    )
    h1_categorias = {
        "conectada_incumbente": h1_h2.CATEGORIAS_H2["faixa_a_0"],
        "sem_conexao": (pl.col("faixa_a") == "inf") & (pl.col("faixa_b") == "inf"),
    }
    h1_contraste = rdd.Contraste(
        "conectada_menos_sem_conexao", {"conectada_incumbente": 1.0, "sem_conexao": -1.0}
    )
    resultados = []
    for hipotese, categorias, contrastes in (
        ("H1", h1_categorias, (h1_contraste,)),
        ("H2", h1_h2.CATEGORIAS_H2, h1_h2.CONTRASTES_H2),
    ):
        bandas = {
            nome: (h, b)
            for nome, h, b in principal.filter(hipotese=hipotese)
            .select("categoria", "banda", "banda_vies")
            .iter_rows()
        }
        resultados.append(
            rdd.tabela(
                painel, hipotese, categorias, [RESULTADO], None, contrastes, bandas_fixas=bandas
            )
        )
    return suprimir_contagens(pl.concat(resultados).with_columns(placebo=pl.lit(True)))


def executar(caminhos: config.Caminhos) -> Path:
    """Reproduz o placebo com os Parquets locais e as tabelas principais de H1 e H2."""
    tabelas = caminhos.resultados / "tables"
    referencia = pl.concat(
        pl.read_csv(tabelas / f"{h}.csv", schema=rdd.ESQUEMA) for h in ("h1", "h2")
    )
    painel = (
        schemas.ler(schemas.PAINEL_FIRMA, caminhos.dados)
        .filter(variante="PRINCIPAL")
        .collect(engine="streaming")
    )
    with TemporaryDirectory(prefix=".pre-periodos-", dir=tabelas) as tmp:
        with duckdb.connect(
            config={"memory_limit": "800MB", "temp_directory": tmp, "threads": 2}
        ) as con:
            for entrada in (schemas.EMPENHOS, schemas.LICITACOES, schemas.ELEICOES):
                con.read_parquet(str(caminhos.dados / entrada.arquivo)).create_view(entrada.nome)
            agregado = panel.agregar_empenhos(con)
        provisorio = Path(tmp) / ARQUIVO
        estimar(com_variacao(painel, agregado), referencia).write_csv(provisorio)
        return provisorio.replace(tabelas / ARQUIVO)


if __name__ == "__main__":
    print(executar(config.Caminhos.do_ambiente()))
