import numpy as np
import polars as pl
import pytest

from redes import auditoria_h2


@pytest.mark.parametrize("n_ambas", [4, 5])
def test_sobreposicao_protege_intersecao_e_complementos(n_ambas):
    painel = pl.DataFrame(
        {
            "cod_municipio_tse": ["m1"] * (n_ambas + 5) + ["m2"] * 5,
            "elemento_despesa": "30",
            "porte": 0,
            "a": [True] * (n_ambas + 5) + [False] * 5,
            "b": [True] * n_ambas + [False] * 5 + [True] * 5,
        }
    )
    medidas = auditoria_h2.sobreposicao(painel, pl.col("a"), pl.col("b"))
    if n_ambas == 4:
        assert all(v is None for v in medidas.values())
    else:
        assert medidas["observacoes_a"] == medidas["observacoes_b"] == 10
        assert medidas["observacoes_ambas"] == 5
        assert medidas["jaccard"] == pytest.approx(1 / 3)
        assert medidas["estratos"] is None


def test_resumo_bootstrap_compara_replicas_validas_em_ambos_os_componentes():
    replicas = np.array([[0.01, 0.02], [0.03, 0.04], [np.nan, 0.01], [0.05, 0.06]])
    resumo = auditoria_h2.resumo_bootstrap(replicas)
    assert resumo["replicas_validas"] == 3
    assert resumo["correlacao_bootstrap"] == pytest.approx(1)
    assert resumo["ep_contraste_bootstrap"] == pytest.approx(0, abs=1e-16)
    assert resumo["ep_contraste_sem_covariancia"] == pytest.approx(np.sqrt(2) * 0.01)
