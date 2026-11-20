"""H1 e H2: conexão direta e gradiente por distância (T14).

Unidade: empresa–município–elemento dos fornecedores anteriores. Resultado: participação no
empenhado de 2025 dentro do elemento de despesa (seção 6 do projeto). Placebo: a participação
de jan/2021 a set/2024, anterior à eleição.

H1 compara as empresas diretamente conectadas ao incumbente (δ_A = 0) com as fornecedoras sem
caminho até nenhum dos grupos (δ_A = δ_B = ∞).

H2 pede a distância até o vencedor, que é δ_B quando T = 1 e δ_A quando T = 0. Uma categoria
construída assim muda no corte e compararia empresas diferentes de cada lado: as próximas de B
à esquerda e as próximas de A à direita. As categorias usam então as faixas fixadas antes da
eleição. β_B(d) é o efeito de T nas empresas a distância d de B (o grupo delas vence), e β_A(d)
é o efeito de T nas empresas a distância d de A (o grupo delas perde). O contraste
(β_B(d) − β_A(d)) / 2 resume, simetricamente, a heterogeneidade entre as duas coortes fixas.
Como as coortes podem diferir em porte, mercado e conexão ao outro grupo, o contraste não
isola o ganho de uma empresa por estar mais perto do vencedor.
"""

import polars as pl

from redes import config
from redes.estimate import rdd

RESULTADO = "participacao_2025"
PLACEBO = "participacao_pre"
FAIXAS_H2 = ("0", "1", "2", "3+")
ESTRATOS_H2 = ("cod_municipio_tse", "elemento_despesa", "porte")
CATEGORIAS_H2 = {
    f"faixa_{grupo}_{faixa}": pl.col(f"faixa_{grupo}") == faixa
    for faixa in FAIXAS_H2
    for grupo in ("b", "a")
}
CONTRASTES_H2 = tuple(
    rdd.Contraste(f"vencedor_faixa_{faixa}", {f"faixa_b_{faixa}": 0.5, f"faixa_a_{faixa}": -0.5})
    for faixa in FAIXAS_H2
)


def h1(painel: pl.DataFrame) -> pl.DataFrame:
    categorias = {
        "conectada_incumbente": pl.col("faixa_a") == "0",
        "sem_conexao": (pl.col("faixa_a") == "inf") & (pl.col("faixa_b") == "inf"),
    }
    diferenca = rdd.Contraste(
        "conectada_menos_sem_conexao", {"conectada_incumbente": 1.0, "sem_conexao": -1.0}
    )
    return rdd.tabela(painel, "H1", categorias, [RESULTADO], PLACEBO, [diferenca])


def h2(painel: pl.DataFrame, *, recorte_comparavel: bool = False) -> pl.DataFrame:
    categorias = CATEGORIAS_H2
    if recorte_comparavel:
        painel, categorias = preparar_recorte_comparavel(painel)
    return rdd.tabela(painel, "H2", categorias, [RESULTADO], PLACEBO, CONTRASTES_H2)


def preparar_recorte_comparavel(painel: pl.DataFrame) -> tuple[pl.DataFrame, dict[str, pl.Expr]]:
    """Marca os estratos com as duas coortes e retorna os filtros por categoria."""
    painel = _com_porte(painel).with_columns(
        (
            (pl.col("faixa_a") == faixa).any().over(ESTRATOS_H2)
            & (pl.col("faixa_b") == faixa).any().over(ESTRATOS_H2)
        ).alias(f"comparavel_{faixa}")
        for faixa in FAIXAS_H2
    )
    categorias = {
        nome: filtro & pl.col(f"comparavel_{nome.rsplit('_', 1)[1]}")
        for nome, filtro in CATEGORIAS_H2.items()
    }
    return painel, categorias


def diagnosticos_h2(
    painel: pl.DataFrame, categorias_pos: pl.DataFrame
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """RDD da variação de participação e descritivas do pós, com bandas originais de H2.

    O desfecho é a diferença entre participações no elemento de despesa em 2025 e no
    acumulado de jan/2021 a set/2024. O mesmo sorteio municipal atua sobre os dois períodos
    em cada réplica porque a diferença é calculada na unidade antes da estimação.
    """
    bandas = {
        nome: (h, b)
        for nome, h, b in categorias_pos.select("categoria", "banda", "banda_vies").iter_rows()
        if h is not None and b is not None
    }
    resultado = "variacao_participacao"
    sensibilidade = rdd.tabela(
        painel.with_columns((pl.col(RESULTADO) - pl.col(PLACEBO)).alias(resultado)),
        "H2",
        CATEGORIAS_H2,
        [resultado],
        None,
        CONTRASTES_H2,
        bandas_fixas=bandas,
    )
    descritivas = pl.DataFrame(
        [
            (nome, h, *rdd.descrever(painel, RESULTADO, CATEGORIAS_H2[nome], h))
            for nome, (h, _) in bandas.items()
        ],
        schema={
            "categoria": pl.String,
            "banda": pl.Float64,
            "media_participacao_2025": pl.Float64,
            "dp_participacao_2025": pl.Float64,
        },
        orient="row",
    )
    return sensibilidade, descritivas


def _com_porte(painel: pl.DataFrame) -> pl.DataFrame:
    porte = (
        painel.group_by("cnpj_basico", "cod_municipio_tse")
        .agg(pl.col("empenhado_pre").sum())
        .with_columns(
            porte=pl.col("empenhado_pre").bin_quantiles(5, labels=False, right_closed=True)
        )
        .select("cnpj_basico", "cod_municipio_tse", "porte")
    )
    return painel.join(porte, on=["cnpj_basico", "cod_municipio_tse"])


def comparabilidade(painel: pl.DataFrame) -> pl.DataFrame:
    """Sobreposição pré-eleitoral em município, mercado e porte (empenho prévio da firma).

    A soma dos mínimos entre as proporções das coortes por célula varia de zero (nenhuma
    sobreposição) a um (distribuições iguais). As células individuais não são publicadas.
    """
    firmas = _com_porte(painel)
    saida = []
    for faixa in FAIXAS_H2:
        grupos = firmas.group_by(ESTRATOS_H2).agg(
            a=(pl.col("faixa_a") == faixa).sum(), b=(pl.col("faixa_b") == faixa).sum()
        )
        n_a, n_b = grupos["a"].sum(), grupos["b"].sum()
        comparaveis = grupos.filter((pl.col("a") > 0) & (pl.col("b") > 0))
        compartilhadas = comparaveis.select(pl.min_horizontal("a", "b").sum()).item()
        sobreposicao = (
            comparaveis.select(pl.min_horizontal(pl.col("a") / n_a, pl.col("b") / n_b).sum()).item()
            if min(n_a, n_b) >= config.SUPRESSAO_MINIMA
            and (compartilhadas == 0 or compartilhadas >= config.SUPRESSAO_MINIMA)
            else None
        )
        saida.append((faixa, sobreposicao))
    return pl.DataFrame(
        saida, schema={"faixa": pl.String, "sobreposicao_mercado_porte": pl.Float64}, orient="row"
    )
