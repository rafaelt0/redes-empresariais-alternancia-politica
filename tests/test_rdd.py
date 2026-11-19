import numpy as np
import polars as pl
import pytest

from redes.estimate import h1_h2, h3, h4, rdd


@pytest.mark.parametrize("salto", [0.0, 0.25])
def test_rdd_recupera_o_salto_na_direcao_do_tratamento(salto):
    rng = np.random.default_rng(41)
    margens = np.linspace(-20.0, 20.0, 241)
    resultados = 0.5 + 0.005 * margens + salto * (margens < 0)
    resultados += rng.normal(0, 0.04, len(margens))
    painel = pl.DataFrame(
        {
            "margem": margens,
            "participacao": resultados,
            "peso": 1.0,
            "cod_municipio_tse": list(range(len(margens))),
            "id_rede": list(range(len(margens))),
        }
    )
    estimado = rdd.estimar(painel, "participacao", banda=(12, 18))
    assert isinstance(estimado, rdd.Estimativa)
    assert estimado.estimativa == pytest.approx(salto, abs=0.04)
    assert estimado.ic_inf <= salto <= estimado.ic_sup
    assert estimado.contagem.municipios_controle == estimado.contagem.municipios_tratados + 1
    assert estimado.emd > 0


def test_diagnostico_suprime_p_por_rede_quando_um_lado_tem_poucas_redes():
    rng = np.random.default_rng(8)
    margens = np.linspace(-10.0, 10.0, 121)
    painel = pl.DataFrame(
        {
            "margem": margens,
            "participacao": 0.4 + 0.1 * (margens < 0) + rng.normal(0, 0.03, len(margens)),
            "peso": 1.0,
            "cod_municipio_tse": np.arange(len(margens)),
            "id_rede": np.where(margens < 0, 0, np.arange(len(margens))),
        }
    )
    tabela = rdd.tabela(
        painel.with_columns(placebo=pl.col("participacao")),
        "H1",
        {"todos": pl.lit(True)},
        ["participacao"],
        "placebo",
    )
    linha = tabela.filter(~pl.col("placebo")).row(0, named=True)
    assert linha["estimavel"]
    assert linha["redes_tratadas"] == 1
    assert linha["redes_controle"] >= 10
    assert linha["p_valor_rede"] is None


def test_holm_preserva_a_ordem_das_hipoteses():
    assert h4.holm([0.04, None, 0.005, 0.01]) == pytest.approx([0.04, None, 0.015, 0.02])


def test_intercepto_ignora_replica_singular_mesmo_com_erro_de_arredondamento():
    somas = np.array([[2.0, 2.2, np.nextafter(2.42, np.inf), 6.0, 6.6]])
    assert np.isnan(rdd._intercepto(somas)).all()


def test_h3_termos_e_total_usam_as_mesmas_bandas_e_somam():
    rng = np.random.default_rng(71)
    x = np.linspace(-20, 20, 241)
    margem = np.tile(x, 2)
    n = len(margem)
    perda, demais, entrantes = (
        salto * (margem < 0) + rng.normal(0, 0.04, n) for salto in (-0.10, 0.06, 0.02)
    )
    painel = pl.DataFrame(
        {
            "margem": margem,
            "peso": 0.5,
            "cod_municipio_tse": np.tile(np.arange(len(x)), 2),
            "id_rede": np.arange(n),
            "ligacao": ["AMBOS"] * len(x) + ["A"] * len(x),
            "termo_r1": perda,
            "termo_r2": demais,
            "termo_r3": entrantes,
            "variacao_total": perda + demais + entrantes,
            "participacao_pre": rng.normal(0.1, 0.01, n),
        }
    )
    tabelas = h3.h3(painel)
    ambos = tabelas.filter((pl.col("categoria") == "ambos") & ~pl.col("placebo"))
    assert ambos["estimavel"].all()
    assert ambos["banda"].n_unique() == 1
    assert ambos["banda_vies"].n_unique() == 1
    assert ambos["municipios_tratados"].n_unique() == 1
    efeito = dict(ambos.select("resultado", "estimativa").iter_rows())
    assert efeito["variacao_total"] == pytest.approx(
        efeito["termo_r1"] + efeito["termo_r2"] + efeito["termo_r3"]
    )
    assert efeito["termo_compensacao"] == pytest.approx(efeito["termo_r2"] + efeito["termo_r3"])


def test_h2_comparavel_exige_a_outra_coorte_no_mesmo_municipio_e_elemento():
    painel = pl.DataFrame(
        {
            "cnpj_basico": ["001", "002", "003", "004", "005"],
            "cod_municipio_tse": ["1", "1", "1", "2", "3"],
            "elemento_despesa": ["30", "30", "42", "30", "30"],
            "empenhado_pre": [100.0] * 5,
            "margem": [2.0, 2.0, 2.0, -1.0, -2.0],
            "peso": [1 / 3, 1 / 3, 1 / 3, 1, 1],
            "id_rede": [0, 1, 2, 3, 4],
            "faixa_a": ["0", "inf", "0", "inf", "0"],
            "faixa_b": ["inf", "0", "inf", "0", "inf"],
            "participacao_2025": [0.2] * 5,
            "participacao_pre": [0.1] * 5,
        }
    )
    resultado = h1_h2.h2(painel, recorte_comparavel=True).filter(
        pl.col("categoria").is_in(["faixa_a_0", "faixa_b_0"]) & ~pl.col("placebo")
    )
    assert resultado["unidades_controle"].to_list() == [1, 1]
    assert resultado["unidades_tratadas"].to_list() == [0, 0]
