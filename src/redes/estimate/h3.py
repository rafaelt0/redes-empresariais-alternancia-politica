"""H3: decomposição da variação da rede na equação (4) (T15).

Unidade: rede–município. Os três termos de (4) e o total, já divididos pelo gasto anual médio
pré-eleição no painel, são estimados com a mesma amostra, banda e pesos (seção 6): a banda
MSE-ótima do total vale para os termos, e assim as estimativas dos termos somam a do total.
As redes ligadas aos dois grupos são comparadas às demais por reamostragem de municípios.
Placebo: a participação da rede no município antes da eleição.
"""

import polars as pl

from redes.estimate import rdd

RESULTADOS = ("variacao_total", "termo_r1", "termo_r2", "termo_r3", "termo_compensacao")
PLACEBO = "participacao_pre"


def h3(painel: pl.DataFrame) -> pl.DataFrame:
    painel = painel.with_columns(termo_compensacao=pl.col("termo_r2") + pl.col("termo_r3"))
    categorias = {
        "ambos": pl.col("ligacao") == "AMBOS",
        "demais": pl.col("ligacao") != "AMBOS",
    }
    diferenca = rdd.Contraste("ambos_menos_demais", {"ambos": 1.0, "demais": -1.0})
    return rdd.tabela(painel, "H3", categorias, RESULTADOS, PLACEBO, [diferenca], banda_comum=True)
