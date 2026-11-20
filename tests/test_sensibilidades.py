import duckdb
import polars as pl

from redes import sensibilidades as sens


def test_rede_sem_socios_preserva_fornecedor_como_rede_unitaria():
    agregados = pl.DataFrame({"cod_municipio_tse": ["00001"], "cnpj_basico": ["00000099"]})
    rede = pl.DataFrame(schema={"cnpj_basico": pl.String, "id_rede": pl.Int64})
    distancias = pl.DataFrame(
        schema={
            "cod_municipio_tse": pl.String,
            "cnpj_basico": pl.String,
            "grupo": sens.schemas.GRUPO,
            "faixa": sens.schemas.FAIXA,
        }
    )
    linha = sens.panel.com_rede_e_faixas(agregados, distancias, rede).row(0, named=True)
    assert (linha["id_rede"], linha["faixa_a"], linha["faixa_b"]) == (-100, "inf", "inf")


def test_exclusao_do_gigante_mantem_denominadores_e_ranking():
    redes = pl.DataFrame(
        {"id_rede": [10, 20], "participacao_pre": [0.6, 0.4], "principal_50": [True, False]}
    )
    assert sens.sem_gigante(redes, 10).row(0) == (20, 0.4, False)


def test_dominancia_distingue_as_redes_principais_das_exclusivas():
    redes = pl.DataFrame(
        {
            "cod_municipio_tse": [str(i) for i in range(20) for _ in range(3)],
            "id_rede": [10, 20, 30] * 20,
            "margem": [-1.0] * 30 + [1.0] * 30,
            "tratamento": [1] * 30 + [0] * 30,
            "gasto_medio_pre": [100.0] * 60,
            "participacao_pre": [0.6, 0.3, 0.1] * 20,
            "ligacao": ["A", "NENHUM", "NENHUM"] * 20,
            **{f"principal_{p}": [True, True, False] * 20 for p in (25, 50, 75)},
        }
    )
    tabela = sens.dominancia_gigante(redes, 10, 5.0)
    principais = tabela.filter(pl.col("coorte") == "H4_principais_50")
    exclusivas = tabela.filter(pl.col("coorte") == "H4_exclusivas_50")
    assert principais.item(0, "fracao_peso_gigante") == 0.5
    assert principais.item(0, "fracao_empenho_gigante") == 2 / 3
    assert exclusivas.item(0, "fracao_peso_gigante") == 1.0
    assert exclusivas.item(0, "municipios_sem_gigante") == 0
    assert tabela.filter(pl.col("coorte") == "H3_ambos").item(0, "fracao_peso_gigante") is None
    rd = sens.dominancia_gigante(redes, 10, 5.0, bandas_h4={"A": 2.0})
    coorte_rd = rd.filter(pl.col("coorte") == "H4_rdd_A_50")
    assert coorte_rd.item(0, "fracao_peso_gigante") == 1.0
    assert coorte_rd.item(0, "redes_municipio") == 20

    pequeno_complemento = redes.filter(
        ~((pl.col("cod_municipio_tse") == "0") & (pl.col("id_rede") == 10))
    )
    protegido = sens.dominancia_gigante(pequeno_complemento, 10, 5.0).filter(
        pl.col("coorte") == "H4_principais_50"
    )
    assert protegido.item(0, "fracao_peso_gigante") is None
    assert protegido.item(0, "municipios_com_gigante") is None
    assert protegido.item(0, "fracao_empenho_gigante") > 0.6


def test_auditoria_escopo_desconta_intersecao_e_anulacoes():
    with duckdb.connect() as con:
        con.execute("""
            CREATE TABLE eleicoes AS
                SELECT i AS cod_municipio_tse, 1 AS tratamento, -2 AS margem
                FROM range(10) AS m(i);
            CREATE TABLE classificados AS
                SELECT i AS cod_municipio_tse, DATE '2025-01-10' AS data,
                    tipo IN (1, 3) AS pessoal, tipo IN (2, 3) AS credor_publico,
                    CASE WHEN tipo = 3 THEN -10.0 ELSE 20.0 END AS valor
                FROM range(10) AS m(i) CROSS JOIN range(4) AS evento(tipo);
        """)
        linha = sens.auditoria_escopo(con).filter(pl.col("recorte") == "amostra").row(0, named=True)
    assert linha["empenho_liquido"] == 500.0
    assert linha["fracao_pessoal"] == 0.2
    assert linha["fracao_credor_publico"] == 0.2
    assert linha["fracao_excluido"] == 0.6
