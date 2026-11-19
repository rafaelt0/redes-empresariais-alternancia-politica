"""H4: manutenção das principais redes e correção de Holm (T16).

Unidade: rede–município, entre as principais redes de cada limiar. Resultado: continuar
principal em 2025. Como em H2, a ligação ao vencedor muda no corte; as categorias são as redes
ligadas só a B e só a A, e o contraste (β_B − β_A) / 2 é o efeito de estar ligada ao vencedor
em vez de ao derrotado, no subconjunto cuja ligação ao vencedor muda com o resultado.
Redes ligadas aos dois grupos, ou a nenhum, entram como categorias fixas de referência.
Placebo: a participação da rede antes da eleição.
"""

from collections.abc import Sequence

import polars as pl

from redes import config
from redes.estimate import rdd

PLACEBO = "participacao_pre"


def h4(painel: pl.DataFrame) -> pl.DataFrame:
    tabelas = []
    for limiar in config.LIMIARES_PRINCIPAIS_REDES:
        pct = int(limiar * 100)
        principal = pl.col(f"principal_{pct}")
        categorias = {
            f"ligada_{grupo.lower()}_{pct}": principal & (pl.col("ligacao") == grupo)
            for grupo in ("A", "B", "AMBOS", "NENHUM")
        }
        vencedor = rdd.Contraste(
            f"ligada_ao_vencedor_{pct}", {f"ligada_b_{pct}": 0.5, f"ligada_a_{pct}": -0.5}
        )
        tabelas.append(
            rdd.tabela(painel, "H4", categorias, [f"mantem_posicao_{pct}"], PLACEBO, [vencedor])
        )
    return pl.concat(tabelas)


def permanencia(painel: pl.DataFrame) -> pl.DataFrame:
    """Permanência descritiva com/sem vínculo ao vencedor em toda a banda de cinco p.p."""
    vencedor = pl.when(pl.col("tratamento") == 1).then(pl.lit("B")).otherwise(pl.lit("A"))
    perto = painel.filter(pl.col("margem").abs() <= config.JANELA_DESCRITIVA_H4)
    tabelas = []
    for limiar in config.LIMIARES_PRINCIPAIS_REDES:
        pct = int(limiar * 100)
        ligadas = perto.filter(f"principal_{pct}").with_columns(
            ligada_ao_vencedor=(pl.col("ligacao") == vencedor) | (pl.col("ligacao") == "AMBOS")
        )
        taxas = (
            ligadas.group_by("cod_municipio_tse", "ligada_ao_vencedor")
            .agg(permaneceu=pl.col(f"mantem_posicao_{pct}").mean())
            .group_by("ligada_ao_vencedor")
            .agg(n_municipios=pl.len(), permanencia=pl.col("permaneceu").mean())
            .filter(pl.col("n_municipios") >= config.SUPRESSAO_MINIMA)
            .with_columns(limiar=pl.lit(pct))
            .select("limiar", "ligada_ao_vencedor", "n_municipios", "permanencia")
            .sort("ligada_ao_vencedor")
        )
        tabelas.append(taxas)
    return pl.concat(tabelas)


def holm(p_valores: Sequence[float | None]) -> list[float | None]:
    """p-valores ajustados de Holm (1979). Nulos ficam nulos e não contam no tamanho da família."""
    validos = sorted((p, i) for i, p in enumerate(p_valores) if p is not None)
    ajustados: list[float | None] = [None] * len(p_valores)
    maior = 0.0
    for posicao, (p, i) in enumerate(validos):
        maior = max(maior, min(1.0, (len(validos) - posicao) * p))
        ajustados[i] = maior
    return ajustados


def familia_holm() -> pl.Expr:
    """Linhas corrigidas (seção 6: "as demais comparações terão correção"). H1 a H3 são as
    principais: o contraste de H1, os contrastes de H2 e todas as linhas de H3. Entram na
    família os contrastes de H4 e os efeitos de cada categoria isolada em H1, H2 e H4, que são
    componentes das comparações e não hipóteses."""
    hipotese, tipo = pl.col("hipotese"), pl.col("tipo")
    return ~pl.col("placebo") & (
        ((hipotese == "H4") & (tipo == "contraste"))
        | (hipotese.is_in(["H1", "H2", "H4"]) & (tipo == "categoria"))
    )
