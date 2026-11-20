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


@pytest.mark.parametrize("grau", [1, 2])
def test_ajuste_ignora_replica_singular_mesmo_com_erro_de_arredondamento(grau):
    margem = np.linspace(0.1, 0.9, grau)
    momentos_x = np.array([np.sum(margem**j) for j in range(2 * grau + 1)])
    momentos_x[-1] = np.nextafter(momentos_x[-1], np.inf)
    momentos_y = np.ones((1, grau + 1, 1))
    assert np.isnan(rdd._ajustar_polinomio(momentos_x[None, :], momentos_y)).all()


def test_contraste_reamostra_o_salto_corrigido_do_rdrobust_com_municipios_em_comum():
    margem = np.linspace(-10, 10, 81)
    municipio = np.arange(len(margem))
    rng = np.random.default_rng(82)
    choque_municipal = rng.normal(0.0, 0.08, len(margem))
    painel = pl.concat(
        [
            pl.DataFrame(
                {
                    "margem": margem,
                    "cod_municipio_tse": municipio,
                    "id_rede": municipio,
                    "grupo": grupo,
                    "peso": peso,
                    "y": choque_municipal + nivel + (salto + curva * margem**2) * (margem < 0),
                }
            )
            for grupo, salto, curva in [("A", 0.3, 0.06), ("B", 0.2, -0.02)]
            for peso, nivel in [(0.15, 0.4), (0.85, 0.1)]
        ]
    )
    bandas = [(5.5, 8.0), (7.5, 5.0)]
    filtros = [pl.col("grupo") == grupo for grupo in ("A", "B")]
    amostras = [rdd._amostra(painel, "y", filtro) for filtro in filtros]
    saidas = [
        rdd._rdrobust(amostra, "municipio", h, b)
        for amostra, (h, b) in zip(amostras, bandas, strict=True)
    ]
    convencional = (
        -saidas[0].coef.loc["Conventional"].iloc[0] + saidas[1].coef.loc["Conventional"].iloc[0]
    )
    esperados = [-float(saida.coef.loc["Bias-Corrected"].iloc[0]) for saida in saidas]
    assert abs(esperados[0] - esperados[1] - convencional) > 0.1

    estimadas = [
        rdd.estimar(painel, "y", filtro, banda=banda)
        for filtro, banda in zip(filtros, bandas, strict=True)
    ]
    repeticoes, semente = 24, 307
    contraste = rdd.contraste(
        painel,
        "y",
        list(zip([1.0, -1.0], filtros, estimadas, strict=True)),
        repeticoes=repeticoes,
        semente=semente,
    )
    assert isinstance(contraste, rdd.Estimativa)
    assert contraste.estimativa == pytest.approx(esperados[0] - esperados[1], abs=1e-10)
    for estimada, esperado in zip(estimadas, esperados, strict=True):
        assert isinstance(estimada, rdd.Estimativa)
        assert estimada.estimativa == pytest.approx(esperado, abs=1e-10)
        assert (estimada.ic_inf + estimada.ic_sup) / 2 == pytest.approx(esperado, abs=1e-10)

    # Reajusta o rdrobust nas réplicas explícitas e mantém o mesmo sorteio nas duas coortes.
    rng = np.random.default_rng(semente)
    multiplicidades = np.hstack(
        [
            rng.multinomial(n, np.full(n, 1 / n), repeticoes)
            for n in ((margem < 0).sum(), (margem >= 0).sum())
        ]
    )
    replicas = []
    for pesos in multiplicidades:
        saltos = []
        for amostra, (h, b) in zip(amostras, bandas, strict=True):
            replica = amostra.with_columns(w=pl.col("w") * pl.Series(pesos[amostra["municipio"]]))
            saida = rdd._rdrobust(replica.filter(pl.col("w") > 0), "municipio", h, b)
            saltos.append(-float(saida.coef.loc["Bias-Corrected"].iloc[0]))
        replicas.append(saltos[0] - saltos[1])
    assert contraste.ep_robusto == pytest.approx(np.std(replicas, ddof=1), abs=1e-10)
    assert (contraste.ic_inf + contraste.ic_sup) / 2 == pytest.approx(contraste.estimativa)


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
    contraste = tabelas.filter((pl.col("categoria") == "ambos_menos_demais") & ~pl.col("placebo"))
    efeitos = dict(contraste.select("resultado", "estimativa").iter_rows())
    assert efeitos["variacao_total"] == pytest.approx(
        efeitos["termo_r1"] + efeitos["termo_r2"] + efeitos["termo_r3"]
    )
    assert efeitos["termo_compensacao"] == pytest.approx(efeitos["termo_r2"] + efeitos["termo_r3"])


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


def test_sensibilidade_h2_usa_bandas_do_pos_e_reestima_a_variacao():
    margem = np.linspace(-10, 10, 81)
    rng = np.random.default_rng(28)
    anterior = 0.3 + 0.2 * (margem < 0) + rng.normal(0, 0.03, len(margem))
    posterior = anterior + 0.02 * (margem < 0) + rng.normal(0, 0.01, len(margem))
    painel = pl.concat(
        [
            pl.DataFrame(
                {
                    "margem": margem,
                    "cod_municipio_tse": np.arange(len(margem)),
                    "id_rede": np.arange(len(margem)),
                    "peso": 1.0,
                    "faixa_a": "0" if grupo == "A" else "inf",
                    "faixa_b": "0" if grupo == "B" else "inf",
                    "participacao_pre": anterior,
                    "participacao_2025": posterior + salto * (margem < 0),
                }
            )
            for grupo, salto in [("A", 0.0), ("B", 0.1)]
        ]
    )
    principal = pl.DataFrame(
        {"categoria": ["faixa_a_0", "faixa_b_0"], "banda": [6.0, 6.0], "banda_vies": [8.0, 8.0]}
    )
    sensibilidade, descritivas = h1_h2.diagnosticos_h2(painel, principal)
    contraste = sensibilidade.filter(pl.col("categoria") == "vencedor_faixa_0").row(0, named=True)
    assert contraste["estimativa"] == pytest.approx(0.05, abs=1e-10)
    assert sensibilidade.filter(pl.col("estimavel") & (pl.col("tipo") == "categoria"))[
        "banda_vies"
    ].to_list() == [8.0, 8.0]
    assert not sensibilidade.filter(pl.col("categoria") == "vencedor_faixa_1")["estimavel"].item()
    coorte_a = descritivas.filter(pl.col("categoria") == "faixa_a_0").row(0, named=True)
    assert coorte_a["media_participacao_2025"] == pytest.approx(posterior[abs(margem) < 6].mean())
    assert coorte_a["dp_participacao_2025"] == pytest.approx(posterior[abs(margem) < 6].std())
