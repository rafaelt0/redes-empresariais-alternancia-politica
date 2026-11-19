"""Robustez da rede: H1 a H3 reestimadas nas variantes da rede (T17).

As variantes da seção 5 do projeto (sem pontos de articulação, sem sócios PJ, sem
administradores não sócios) já vêm calculadas nos painéis; aqui as estimativas de cada uma
ficam lado a lado com as da rede principal.
"""

from functools import reduce

import polars as pl

CHAVE = ("hipotese", "categoria", "tipo", "resultado")
VALORES = (
    "estimativa",
    "ic_inf",
    "ic_sup",
    "p_valor",
    "municipios_tratados",
    "municipios_controle",
)
HIPOTESES = ("H1", "H2", "H3")


def comparar(por_variante: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Uma linha por hipótese, categoria e resultado, com colunas `<valor>_<variante>`."""
    lados = [
        tabela.filter(pl.col("hipotese").is_in(HIPOTESES) & ~pl.col("placebo")).select(
            *CHAVE, *(pl.col(v).alias(f"{v}_{variante.lower()}") for v in VALORES)
        )
        for variante, tabela in por_variante.items()
    ]
    return reduce(lambda a, b: a.join(b, on=CHAVE, how="left", maintain_order="left"), lados)
