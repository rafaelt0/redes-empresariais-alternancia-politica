"""Etapa `panel`: painéis empresa–município e rede–município (T11, T12).

Seção 6 do projeto. No painel empresa–município (H1, H2), cada linha é uma fornecedora anterior
de um município e elemento de despesa, e o resultado é a participação no empenhado de 2025
dentro do elemento. No painel rede–município (H3, H4), cada linha é uma rede com fornecedora
anterior no município, e os resultados são os três termos da equação (4), o total e a
manutenção da posição das principais redes. As escolhas que o projeto deixa abertas estão em
`docs/decisoes.md` (16/11/2026).

Empenho líquido é emissão + reforço − anulação, somados pela data do evento. Nos dados reais,
reforços e anulações caem no ano do próprio empenho (três exceções em 33 milhões de eventos),
então somar pela data do evento ou pelo ano do empenho dá o mesmo. De out/2024 a dez/2024 nada
entra: a janela pré-eleitoral fecha em set/2024 e o resultado é 2025.

Memória: os 33 milhões de eventos são agregados no DuckDB, com limite de memória e despejo em
disco, a uma linha por município, elemento e empresa (1,2 milhão nos dados reais). O resto é
polars sobre esse agregado, uma variante de rede por vez, cada uma gravada em parte antes da
seguinte.
"""

import shutil
from pathlib import Path

import duckdb
import polars as pl

from redes import config, descritivas, schemas
from redes.etapas import Contexto, Etapa
from redes.schemas import (
    DISTANCIAS,
    ELEICOES,
    EMPENHOS,
    FAIXA,
    LICITACOES,
    PAINEL_FIRMA,
    PAINEL_REDE,
    REDE,
    VARIANTE,
)

ETAPA = Etapa(
    nome="panel",
    depende=("ingest-tcesp", "elections", "network"),
    le=(EMPENHOS, LICITACOES, ELEICOES, REDE, DISTANCIAS),
    grava=(PAINEL_FIRMA, PAINEL_REDE),
    artefatos=(
        "resultados/tables/validacao_panel.csv",
        "resultados/tables/mercados_sem_empenho.csv",
    ),
)

MUNICIPIO = "cod_municipio_tse"
MERCADO = (MUNICIPIO, "elemento_despesa")
COLUNAS_PRE = tuple(f"pre_{ano}" for ano in config.ANOS_PRE_ELEICAO)
LIMIARES = tuple(int(p * 100) for p in config.LIMIARES_PRINCIPAIS_REDES)

PRE = pl.sum_horizontal(COLUNAS_PRE)
ANTERIOR = pl.col("empenhado_pre") > 0
"""Fornecedora anterior: empenho líquido positivo de jan/2021 a set/2024 (seção 5)."""


def agregar_empenhos(con: duckdb.DuckDBPyConnection) -> pl.DataFrame:
    """Empenho líquido por município da amostra, elemento de despesa e empresa.

    Lê as relações `empenhos`, `licitacoes` e `eleicoes` de `con`. Colunas: `pre_AAAA` (cada
    ano da janela pré-eleitoral, 2024 até setembro), `empenhado_2025`, `vinculado_2025` (em
    empenhos ligados a algum ajuste, só para a taxa de vinculação) e `empenhado_novo_2025` (em
    empenhos ligados a ajuste com data a partir da posse). Linhas sem evento na janela nem em
    2025 não aparecem.
    """
    na_janela = (
        f"e.data BETWEEN DATE '{config.INICIO_PRE_ELEICAO}' AND DATE '{config.FIM_PRE_ELEICAO}'"
    )
    no_resultado = f"year(e.data) = {config.ANO_RESULTADO}"

    def soma(condicao: str, nome: str) -> str:
        return f"coalesce(sum(e.valor) FILTER (WHERE {condicao}), 0) AS {nome}"

    colunas = ",\n".join(
        [
            *(
                soma(f"{na_janela} AND year(e.data) = {ano}", coluna)
                for ano, coluna in zip(config.ANOS_PRE_ELEICAO, COLUNAS_PRE, strict=True)
            ),
            soma(no_resultado, "empenhado_2025"),
            soma(f"{no_resultado} AND e.id_ajuste IS NOT NULL", "vinculado_2025"),
            soma(f"{no_resultado} AND novo.id_novo IS NOT NULL", "empenhado_novo_2025"),
        ]
    )
    return con.sql(
        f"""
        SELECT e.cod_municipio_tse, e.elemento_despesa, e.cnpj_basico, {colunas}
        FROM empenhos e
        LEFT JOIN (
            SELECT id_ajuste AS id_novo FROM licitacoes WHERE data >= DATE '{config.DATA_POSSE}'
        ) novo ON e.id_ajuste = novo.id_novo
        WHERE e.cod_municipio_tse IN (SELECT cod_municipio_tse FROM eleicoes)
          AND ({na_janela} OR {no_resultado})
        GROUP BY ALL
        ORDER BY ALL
        """
    ).pl()


def com_rede_e_faixas(
    frame: pl.DataFrame, distancias: pl.DataFrame, rede: pl.DataFrame
) -> pl.DataFrame:
    """Acrescenta `id_rede`, `faixa_a` e `faixa_b` a linhas de (município, empresa).

    `distancias` e `rede` são de uma só variante. A empresa sem sócio na fotografia (fora de
    `rede`) é rede de uma empresa só, com id negativo derivado do CNPJ para não colidir com os
    componentes; a que falta em `distancias` fica com faixa inf.
    """
    faixas = distancias.group_by(MUNICIPIO, "cnpj_basico").agg(
        pl.col("faixa").filter(pl.col("grupo") == grupo).first().alias(f"faixa_{grupo.lower()}")
        for grupo in ("A", "B")
    )
    sem_faixa = pl.lit("inf", dtype=FAIXA)
    return (
        frame.join(faixas, on=[MUNICIPIO, "cnpj_basico"], how="left")
        .join(rede.select("cnpj_basico", "id_rede"), on="cnpj_basico", how="left")
        .with_columns(
            pl.col("faixa_a", "faixa_b").fill_null(sem_faixa),
            pl.coalesce("id_rede", -pl.col("cnpj_basico").cast(pl.Int64) - 1),
        )
    )


def _desenho(frame: pl.DataFrame, eleicoes: pl.DataFrame, variante: str) -> pl.DataFrame:
    """Margem, tratamento, peso 1/linhas do município e a variante."""
    return frame.join(
        eleicoes.select(MUNICIPIO, "margem", "tratamento"), on=MUNICIPIO
    ).with_columns(
        peso=1 / pl.len().over(MUNICIPIO),
        variante=pl.lit(variante, dtype=VARIANTE),
    )


def painel_firma(
    agregado: pl.DataFrame,
    distancias: pl.DataFrame,
    rede: pl.DataFrame,
    eleicoes: pl.DataFrame,
    variante: str,
) -> pl.DataFrame:
    """Fornecedoras anteriores de cada município e elemento, com as participações (H1, H2).

    A participação de 2025 é calculada sobre todas as empresas do elemento, inclusive as que não
    forneciam antes, e só o empenho líquido positivo conta, como na definição de fornecedora
    anterior. A participação é zero quando o elemento não teve empenho positivo em 2025.
    A regra preserva os fornecedores selecionados antes da eleição.
    """
    positivo = pl.col("empenhado_2025").clip(lower_bound=0)
    total_2025 = positivo.sum().over(MERCADO)
    return (
        agregado.with_columns(
            empenhado_pre=PRE,
            participacao_2025=pl.when(total_2025 > 0).then(positivo / total_2025).otherwise(0.0),
        )
        .filter(ANTERIOR)
        .with_columns(
            participacao_pre=pl.col("empenhado_pre") / pl.col("empenhado_pre").sum().over(MERCADO)
        )
        .pipe(com_rede_e_faixas, distancias, rede)
        .pipe(_desenho, eleicoes, variante)
        .select(PAINEL_FIRMA.esquema.names())
        .sort(PAINEL_FIRMA.chave)
    )


def marcar_principais(
    redes: pl.DataFrame, valor: str, total: str, elegivel: pl.Expr, prefixo: str
) -> pl.DataFrame:
    """`{prefixo}_25`, `_50` e `_75`: a rede está entre as principais do município.

    Seção 6: as redes elegíveis, em ordem decrescente de `valor`, entram até que a soma alcance
    o limiar de `total` (o empenhado no município, de todas as empresas); a rede que cruza o
    limiar entra. Se as elegíveis não alcançam o limiar, todas são principais. Empates em
    `valor` se resolvem por `id_rede`.
    """
    v = pl.when(elegivel).then(pl.col(valor)).otherwise(0.0)
    antes = (v.cum_sum() - v).over(MUNICIPIO) / pl.col(total)
    return redes.sort([MUNICIPIO, valor, "id_rede"], descending=[False, True, False]).with_columns(
        (elegivel & (antes < p / 100)).alias(f"{prefixo}_{p}") for p in LIMIARES
    )


def painel_rede(
    agregado: pl.DataFrame,
    distancias: pl.DataFrame,
    rede: pl.DataFrame,
    eleicoes: pl.DataFrame,
    variante: str,
) -> pl.DataFrame:
    """Termos da equação (4) e principais redes, por rede e município (H3, H4).

    Seções 4 e 6: a variação da rede é medida em níveis e decomposta em R1 (fornecedoras
    anteriores conectadas diretamente ao incumbente, δ_A = 0), R2 (demais fornecedoras
    anteriores) e R3 (empresas da rede que não forneciam). Os resultados de H3 são os três
    termos e o total "divididos pelo gasto anual médio do município antes da eleição, de modo
    que somem": cada termo é Σ (empenho de 2025 − média anual de jan/2021 a set/2024) sobre as
    empresas do conjunto, dividido pelo empenho líquido médio anual do município no mesmo
    período. Fornecedora anterior aqui é a empresa com empenho líquido positivo no município,
    somados os elementos.

    Entram as redes com ao menos uma fornecedora anterior no município: a amostra fica fixada
    antes da eleição, e uma rede sem fornecedora anterior não tem perda a compensar. As
    principais de 2025, para `mantem_posicao_*`, são escolhidas entre todas as redes do
    município, inclusive as que só passaram a fornecer em 2025.
    """
    media_pre = pl.col("empenhado_pre") / config.ANOS_NA_JANELA_PRE
    variacao = pl.col("empenhado_2025") - media_pre
    r1 = ANTERIOR & (pl.col("faixa_a") == "0")
    conjuntos = {"termo_r1": r1, "termo_r2": ANTERIOR & ~r1, "termo_r3": ~ANTERIOR}

    empresas = (
        agregado.group_by(MUNICIPIO, "cnpj_basico")
        .agg(pl.col(*COLUNAS_PRE, "empenhado_2025").sum())
        .with_columns(empenhado_pre=PRE)
        .pipe(com_rede_e_faixas, distancias, rede)
    )
    municipios = empresas.group_by(MUNICIPIO).agg(
        total_pre=pl.col("empenhado_pre").sum(),
        total_2025=pl.col("empenhado_2025").sum(),
    )
    # Faixa diferente de inf é estar no componente de uma empresa conectada ao grupo, que
    # pode nem fornecer ao município (`network.distancias`).
    ligada = {g: (pl.col(f"faixa_{g.lower()}") != "inf").any() for g in ("A", "B")}
    redes = (
        empresas.group_by(MUNICIPIO, "id_rede")
        .agg(
            *(variacao.filter(conjunto).sum().alias(nome) for nome, conjunto in conjuntos.items()),
            pl.col(*COLUNAS_PRE, "empenhado_pre", "empenhado_2025").sum(),
            ANTERIOR.any().alias("fornecia"),
            ligacao=pl.when(ligada["A"] & ligada["B"])
            .then(pl.lit("AMBOS"))
            .when(ligada["A"])
            .then(pl.lit("A"))
            .when(ligada["B"])
            .then(pl.lit("B"))
            .otherwise(pl.lit("NENHUM")),
        )
        .join(municipios, on=MUNICIPIO)
        .with_columns(gasto_medio_pre=pl.col("total_pre") / config.ANOS_NA_JANELA_PRE)
        .with_columns(pl.col(*conjuntos) / pl.col("gasto_medio_pre"))
        .with_columns(
            variacao_total=pl.sum_horizontal(*conjuntos),
            anos_com_empenho_pre=pl.sum_horizontal(pl.col(c) > 0 for c in COLUNAS_PRE).cast(
                pl.Int8
            ),
            participacao_pre=pl.col("empenhado_pre") / pl.col("total_pre"),
        )
    )
    redes = marcar_principais(
        redes,
        "empenhado_pre",
        "total_pre",
        pl.col("anos_com_empenho_pre") >= config.MINIMO_ANOS_PRINCIPAIS_REDES,
        "principal",
    )
    redes = marcar_principais(
        redes, "empenhado_2025", "total_2025", pl.col("empenhado_2025") > 0, "principal_2025"
    )
    return (
        redes.filter("fornecia")
        .with_columns(
            pl.col("ligacao").cast(PAINEL_REDE.esquema["ligacao"]),
            *(
                pl.when(f"principal_{p}")
                .then(pl.col(f"principal_2025_{p}"))
                .alias(f"mantem_posicao_{p}")
                for p in LIMIARES
            ),
        )
        .pipe(_desenho, eleicoes, variante)
        .select(PAINEL_REDE.esquema.names())
        .sort(PAINEL_REDE.chave)
    )


def resumo(
    variante: str,
    agregado: pl.DataFrame,
    distancias: pl.DataFrame,
    firma: pl.DataFrame,
    rede: pl.DataFrame,
) -> pl.DataFrame:
    """Contagens e taxas da variante para `validacao_panel.csv`; contagens de 1 a 4 saem nulas."""
    empresas = agregado.select(MUNICIPIO, "cnpj_basico").unique()
    sem_rede = firma.filter(pl.col("id_rede") < 0)
    contagens = {
        "n_municipios": firma[MUNICIPIO].n_unique(),
        "n_linhas_painel_firma": firma.height,
        "n_linhas_painel_rede": rede.height,
        "n_fornecedoras_sem_rede": sem_rede["cnpj_basico"].n_unique(),
        "n_empresas_sem_distancia": empresas.join(
            distancias, on=[MUNICIPIO, "cnpj_basico"], how="anti"
        ).height,
        **{
            f"n_redes_ligacao_{g}": rede.filter(pl.col("ligacao") == g).height
            for g in PAINEL_REDE.esquema["ligacao"].categories
        },
        **{f"n_principais_{p}": rede[f"principal_{p}"].sum() for p in LIMIARES},
        **{f"n_mantem_posicao_{p}": rede[f"mantem_posicao_{p}"].sum() for p in LIMIARES},
    }
    n_sem = contagens["n_fornecedoras_sem_rede"]
    valor_pre = firma["empenhado_pre"].sum()
    taxas = {
        "valor_pre_sem_rede": (
            sem_rede["empenhado_pre"].sum() / valor_pre
            if valor_pre and (n_sem == 0 or n_sem >= config.SUPRESSAO_MINIMA)
            else None
        )
    }
    linhas = pl.DataFrame(
        {
            "medida": [*contagens, *taxas],
            "valor": [*map(float, contagens.values()), *taxas.values()],
        }
    )
    return linhas.select(
        pl.lit(variante).alias("variante"),
        "medida",
        pl.when(pl.col("medida").str.starts_with("n_"))
        .then(descritivas.suprimir("valor"))
        .otherwise("valor")
        .alias("valor"),
    )


def suporte_vinculacao(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    """Conta empenhos distintos nos numeradores e complementos das taxas de 2025."""
    consulta = con.sql(
        f"""
        WITH amostra AS (
            SELECT e.id_empenho, e.id_ajuste IS NOT NULL AS ligado,
                   coalesce(l.data >= DATE '{config.DATA_POSSE}', false) AS novo
            FROM empenhos e
            LEFT JOIN licitacoes l ON e.id_ajuste = l.id_ajuste
            WHERE year(e.data) = {config.ANO_RESULTADO}
              AND e.cod_municipio_tse IN (SELECT cod_municipio_tse FROM eleicoes)
        )
        SELECT count(DISTINCT id_empenho) FILTER (WHERE ligado) AS ligados,
               count(DISTINCT id_empenho) FILTER (WHERE NOT ligado) AS sem_ajuste,
               count(DISTINCT id_empenho) FILTER (WHERE novo) AS novos,
               count(DISTINCT id_empenho) FILTER (WHERE NOT novo) AS nao_novos,
               count(DISTINCT id_empenho) FILTER (WHERE ligado AND NOT novo) AS anteriores
        FROM amostra
        """
    )
    return consulta.pl().row(0, named=True)


def vinculacao(agregado: pl.DataFrame, suporte: dict[str, int]) -> pl.DataFrame:
    """Taxas monetárias, protegendo também a diferença entre os valores ligado e novo."""
    minimo = config.SUPRESSAO_MINIMA
    total = agregado["empenhado_2025"].sum()
    publicar_ligados = total and not any(0 < suporte[c] < minimo for c in ("ligados", "sem_ajuste"))
    publicar_novos = total and not any(
        0 < suporte[c] < minimo for c in ("novos", "nao_novos", "anteriores")
    )
    return pl.DataFrame(
        {
            "variante": [None, None],
            "medida": ["vinculacao_valor_2025", "novo_valor_2025"],
            "valor": [
                agregado["vinculado_2025"].sum() / total if publicar_ligados else None,
                agregado["empenhado_novo_2025"].sum() / total if publicar_novos else None,
            ],
        },
        schema={"variante": pl.String, "medida": pl.String, "valor": pl.Float64},
    )


def mercados_sem_empenho(agregado: pl.DataFrame, firma: pl.DataFrame) -> pl.DataFrame:
    """Frequência de mercados sem empenho líquido positivo em 2025 na amostra pré-eleitoral."""
    mercado = agregado.group_by(MERCADO).agg(sem_empenho=~(pl.col("empenhado_2025") > 0).any())
    observacoes = firma.join(mercado, on=MERCADO).with_columns(
        lado=pl.when(pl.col("margem") < 0).then(pl.lit("esquerda")).otherwise(pl.lit("direita"))
    )
    categorias = {
        ("H1", "conectada_incumbente"): pl.col("faixa_a") == "0",
        ("H1", "sem_conexao"): (pl.col("faixa_a") == "inf") & (pl.col("faixa_b") == "inf"),
        **{
            ("H2", f"faixa_{grupo}_{faixa}"): pl.col(f"faixa_{grupo}") == faixa
            for grupo in ("a", "b")
            for faixa in FAIXA.categories
            if faixa != "inf"
        },
    }
    contagens = pl.concat(
        observacoes.filter(filtro)
        .group_by("lado")
        .agg(
            observacoes=pl.len(),
            sem_empenho=pl.col("sem_empenho").sum(),
        )
        .with_columns(hipotese=pl.lit(h), categoria=pl.lit(c))
        for (h, c), filtro in categorias.items()
    )
    publicar = (
        (pl.col("observacoes") >= config.SUPRESSAO_MINIMA)
        & ~pl.col("sem_empenho").is_between(1, config.SUPRESSAO_MINIMA - 1)
        & ~(pl.col("observacoes") - pl.col("sem_empenho")).is_between(
            1, config.SUPRESSAO_MINIMA - 1
        )
    )
    return contagens.select(
        "hipotese",
        "categoria",
        "lado",
        pl.when(publicar).then(pl.col("observacoes")).alias("observacoes"),
        pl.when(publicar).then(pl.col("sem_empenho")).alias("sem_empenho"),
        pl.when(publicar).then(pl.col("sem_empenho") / pl.col("observacoes")).alias("fracao"),
    ).sort("hipotese", "categoria", "lado")


def _agregar_do_disco(dados: Path) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Agrega os empenhos e calcula as taxas públicas; o DuckDB despeja acima de 1 GB."""
    temporario = dados / "tmp" / "panel-duckdb"
    temporario.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(
        config={"memory_limit": "1GB", "temp_directory": str(temporario), "threads": 2}
    ) as con:
        con.execute("SET enable_progress_bar = false")
        for tabela in (EMPENHOS, LICITACOES, ELEICOES):
            caminho = str(dados / tabela.arquivo).replace("'", "''")
            con.execute(f"CREATE VIEW {tabela.nome} AS SELECT * FROM read_parquet('{caminho}')")
        agregado = agregar_empenhos(con)
        taxas = vinculacao(agregado, suporte_vinculacao(con))
    shutil.rmtree(temporario)
    return agregado, taxas


def executar(ctx: Contexto) -> None:
    eleicoes = ctx.ler(ELEICOES).collect()
    agregado, taxas = _agregar_do_disco(ctx.caminhos.dados)
    empresas = agregado.select("cnpj_basico").unique().lazy()
    variantes = ctx.ler(DISTANCIAS).select("variante").unique().collect()["variante"]

    pasta = ctx.caminhos.dados / "tmp" / "panel"
    shutil.rmtree(pasta, ignore_errors=True)
    pasta.mkdir(parents=True)
    resumos = [taxas]
    tabelas = ctx.caminhos.resultados / "tables"
    tabelas.mkdir(parents=True, exist_ok=True)
    for variante in VARIANTE.categories:
        if variante not in variantes:
            continue
        distancias = (
            ctx.ler(DISTANCIAS)
            .filter(pl.col("variante") == variante)
            .join(eleicoes.lazy().select(MUNICIPIO), on=MUNICIPIO, how="semi")
            .select(MUNICIPIO, "grupo", "cnpj_basico", "faixa")
            .collect(engine="streaming")
        )
        rede = (
            ctx.ler(REDE)
            .filter(pl.col("variante") == variante)
            .join(empresas, on="cnpj_basico", how="semi")
            .select("cnpj_basico", "id_rede")
            .collect(engine="streaming")
        )
        firma = painel_firma(agregado, distancias, rede, eleicoes, variante)
        if variante == "PRINCIPAL":
            mercados_sem_empenho(agregado, firma).write_csv(tabelas / "mercados_sem_empenho.csv")
        por_rede = painel_rede(agregado, distancias, rede, eleicoes, variante)
        resumos.append(resumo(variante, agregado, distancias, firma, por_rede))
        firma.write_parquet(pasta / f"{PAINEL_FIRMA.nome}-{variante}.parquet")
        por_rede.write_parquet(pasta / f"{PAINEL_REDE.nome}-{variante}.parquet")
        del distancias, rede, firma, por_rede

    for tabela in (PAINEL_FIRMA, PAINEL_REDE):
        partes = sorted(pasta.glob(f"{tabela.nome}-*.parquet"))
        frame = pl.scan_parquet(partes) if partes else tabela.vazia().lazy()
        schemas.gravar_em_fluxo(frame, tabela, ctx.caminho(tabela))
    shutil.rmtree(pasta)
    pl.concat(resumos).write_csv(tabelas / "validacao_panel.csv")
