from datetime import date

import duckdb
import numpy as np
import polars as pl
import pytest
from polars.testing import assert_frame_equal

from redes import panel, pre_periodos


def test_variacao_pre_usa_empenho_liquido_de_todo_o_mercado_e_fixa_o_painel():
    eventos = pl.DataFrame(
        [
            ("a", "30", date(2021, 1, 1), 100.0),
            ("a", "30", date(2022, 12, 31), -60.0),
            ("a", "30", date(2023, 1, 1), 40.0),
            ("a", "30", date(2024, 9, 30), 20.0),
            ("a", "30", date(2024, 10, 1), 900.0),
            ("b", "30", date(2023, 6, 25), 100.0),
            ("c", "30", date(2022, 5, 10), 50.0),
            ("c", "30", date(2023, 5, 10), -60.0),
            ("d", "42", date(2023, 2, 20), 20.0),
            ("e", "45", date(2022, 1, 15), 70.0),
        ],
        schema=["cnpj_basico", "elemento_despesa", "data", "valor"],
        orient="row",
    ).with_columns(cod_municipio_tse=pl.lit("1"), id_ajuste=pl.lit(None, dtype=pl.String))
    base = pl.DataFrame(
        {
            "cnpj_basico": ["e", "a", "d", "b"],
            "elemento_despesa": ["45", "30", "42", "30"],
            "cod_municipio_tse": "1",
            "peso": [0.1, 0.2, 0.3, 0.4],
            "faixa_a": ["0", "1", "2", "3+"],
            "faixa_b": ["inf", "0", "1", "2"],
            "id_rede": [9, 8, 7, 6],
        }
    )
    with duckdb.connect() as con:
        con.register("empenhos", eventos)
        con.register("eleicoes", base.select("cod_municipio_tse").unique())
        con.register("licitacoes", pl.DataFrame(schema={"id_ajuste": pl.String, "data": pl.Date}))
        agregado = panel.agregar_empenhos(con)
    saida = pre_periodos.com_variacao(base, agregado)
    assert_frame_equal(saida.select(base.columns), base)
    assert saida["participacao_2021_2022"].to_list() == pytest.approx([1, 40 / 90, 0, 0])
    assert saida["participacao_2023_set2024"].to_list() == pytest.approx(
        [0, 60 / 160, 1, 100 / 160]
    )
    assert saida["variacao_pre_periodos"].to_list() == pytest.approx(
        [-1, 60 / 160 - 40 / 90, 1, 100 / 160]
    )


def test_estimacao_pre_preserva_as_bandas_pos_e_os_contrastes_de_h1_e_h2():
    margem = np.linspace(-10.0, 10.0, 101)
    municipio = np.arange(len(margem))
    rng = np.random.default_rng(82)
    painel = pl.concat(
        [
            pl.DataFrame(
                {
                    "margem": margem,
                    "cod_municipio_tse": municipio,
                    "id_rede": municipio,
                    "peso": 1.0,
                    "faixa_a": faixa_a,
                    "faixa_b": faixa_b,
                    "variacao_pre_periodos": salto * (margem < 0)
                    + rng.normal(0, 0.002, len(margem)),
                }
            )
            for faixa_a, faixa_b, salto in [
                ("0", "inf", 0.14),
                ("inf", "0", 0.04),
                ("inf", "inf", -0.04),
            ]
        ]
    )
    categorias = pl.DataFrame(
        {
            "hipotese": ["H1", "H1", "H2", "H2", "H2"],
            "categoria": [
                "conectada_incumbente",
                "sem_conexao",
                "faixa_a_0",
                "faixa_b_0",
                "faixa_b_0",
            ],
            "banda": [6.0, 8.0, 6.0, 7.0, 1.0],
            "banda_vies": [5.0, 7.0, 5.0, 9.0, 1.0],
            "tipo": "categoria",
            "resultado": ["participacao_2025"] * 4 + ["participacao_pre"],
            "placebo": [False] * 4 + [True],
            "estimavel": True,
        }
    )
    tabela = pre_periodos.estimar(painel, categorias)
    assert tabela["placebo"].all()
    faixa_b = tabela.filter(pl.col("categoria") == "faixa_b_0").row(0, named=True)
    assert (faixa_b["banda"], faixa_b["banda_vies"]) == (7.0, 9.0)
    h1 = tabela.filter(pl.col("categoria") == "conectada_menos_sem_conexao").row(0, named=True)
    h2 = tabela.filter(pl.col("categoria") == "vencedor_faixa_0").row(0, named=True)
    assert h1["estimativa"] == pytest.approx(0.18, abs=0.01)
    assert h2["estimativa"] == pytest.approx(-0.05, abs=0.01)
    assert h1["ic_inf"] < h1["estimativa"] < h1["ic_sup"]
    assert h2["ic_inf"] < h2["estimativa"] < h2["ic_sup"]
