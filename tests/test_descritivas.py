import math

import numpy as np
import polars as pl
import pytest

from redes import descritivas
from redes.schemas import FAIXA, GRUPO

MUNICIPIO = "90001"


def test_componentes_por_faixa_de_tamanho() -> None:
    rede = pl.DataFrame(
        {
            "id_rede": [0, 0, 1, 2, 2, 2, 3, 3, 3, 3, 3],
            "cnpj_basico": [str(i) for i in range(11)],
            "empresas_na_rede": [2, 2, 1, 3, 3, 3, 5, 5, 5, 5, 5],
        }
    )
    tabela = descritivas.componentes(rede)
    por_faixa = dict(tabela.select("faixa_tamanho", "componentes").rows())
    assert por_faixa == {
        "1": 1,
        "2": 1,
        "3+": 2,
    }
    assert tabela["componentes"].sum() == 4
    assert tabela["empresas"].sum() == 11


def test_graus_de_empresas_e_pessoas_em_faixas_separadas() -> None:
    tabela = descritivas.graus(
        grau_empresa=pl.Series([0, 1, 4, 12]).to_numpy(),
        grau_pessoa=pl.Series([1, 1, 1]).to_numpy(),
    )
    empresa = tabela.filter(pl.col("vertice") == "empresa")
    pessoa = tabela.filter(pl.col("vertice") == "pessoa")
    assert dict(empresa.select("faixa_grau", "vertices").rows()) == {
        "0": 1,
        "1": 1,
        "2": 0,
        "3-5": 1,
        "6-10": 0,
        "11+": 1,
    }
    assert pessoa["vertices"].sum() == 3


def test_assortatividade_emprega_os_graus_das_duas_pontas_por_vinculo() -> None:
    empresas = np.array([0, 0, 0, 1, 1, 2, 3])
    pessoas = np.array([0, 1, 2, 0, 2, 0, 3])
    grau_empresa, grau_pessoa = np.bincount(empresas), np.bincount(pessoas)
    r = descritivas.assortatividade_grau(empresas, pessoas, grau_empresa, grau_pessoa)
    esperado = np.corrcoef(grau_empresa[empresas], grau_pessoa[pessoas])[0, 1]
    assert r == pytest.approx(esperado)

    empresas = np.arange(7)
    pessoas = np.array([0, 0, 0, 1, 1, 2, 3])
    assert (
        descritivas.assortatividade_grau(
            empresas, pessoas, np.bincount(empresas), np.bincount(pessoas)
        )
        is None
    )


def test_graus_publicos_ocultam_diferencas_pequenas_de_cauda_entre_variantes():
    graus = pl.DataFrame(
        {
            "variante": ["principal", "sem_pj", "principal", "sem_pj"],
            "vertice": ["empresa", "empresa", "pessoa", "pessoa"],
            "faixa_grau": ["11+"] * 4,
            "vertices": [6, 5, 10, 5],
        }
    )
    totais = pl.DataFrame(schema={"variante": pl.String, "indicador": pl.String, "valor": pl.Int64})
    assert descritivas.graus_publicos(graus, totais)["vertices"].to_list() == [None, None, 10, 5]


def test_graus_publicos_ocultam_cauda_recuperavel_pelo_total_de_empresas():
    graus = pl.DataFrame(
        {
            "variante": ["principal"] * 6 + ["sem_pj"] * 6,
            "vertice": ["empresa"] * 12,
            "faixa_grau": descritivas.FAIXAS_GRAU * 2,
            "vertices": [10, 10, 10, 10, None, None, 7, 10, 10, 10, 5, 5],
        }
    )
    totais = pl.DataFrame(
        {"variante": ["principal", "sem_pj"], "indicador": ["empresas"] * 2, "valor": [47, 47]}
    )
    assert descritivas.graus_publicos(graus, totais)["vertices"].null_count() == graus.height


def test_faixas_de_distancia_so_contam_municipios_com_conexao_direta() -> None:
    distancias = pl.DataFrame(
        {
            "cod_municipio_tse": [MUNICIPIO, MUNICIPIO, "90002", "90002"],
            "grupo": ["A", "A", "B", "B"],
            "cnpj_basico": ["00000001", "00000002", "00000003", "00000004"],
            "distancia": [0, 1, 0, 2],
            "faixa": ["0", "1", "0", "2"],
        },
        schema_overrides={"grupo": GRUPO, "faixa": FAIXA},
    )
    origens = pl.DataFrame(
        {"cod_municipio_tse": [MUNICIPIO], "grupo": ["A"]},
        schema_overrides={"grupo": GRUPO},
    )
    tabela = descritivas.faixas_de_distancia(distancias, origens)
    pares = {
        (grupo, faixa): n
        for grupo, faixa, n in tabela.select("grupo", "faixa", "pares_empresa_municipio").rows()
    }
    assert pares == {
        ("A", "0"): 1,
        ("A", "1"): 1,
        ("A", "2"): 0,
        ("A", "3+"): 0,
        ("A", "inf"): 0,
        ("B", "0"): 0,
        ("B", "1"): 0,
        ("B", "2"): 0,
        ("B", "3+"): 0,
        ("B", "inf"): 0,
    }


def test_supressao_de_celulas_pequenas() -> None:
    frame = pl.DataFrame({"valor": [0, 1, 4, 5, 10]}).with_columns(descritivas.suprimir("valor"))
    assert frame["valor"].to_list() == [0.0, None, None, 5.0, 10.0]


def test_resumo_reporta_fracao_do_maior_componente() -> None:
    rede = pl.DataFrame(
        {
            "id_rede": [0, 0, 1, 2, 2, 2, 2, 2, 2],
            "cnpj_basico": [str(i) for i in range(9)],
            "empresas_na_rede": [2, 2, 1, 6, 6, 6, 6, 6, 6],
        }
    )
    origens = pl.DataFrame(
        {"cod_municipio_tse": [MUNICIPIO, "90002"], "grupo": ["A", "B"]},
        schema_overrides={"grupo": GRUPO},
    )
    tabela = descritivas.resumo(
        rede,
        grau_pessoa=np.array([1, 2, 3]),
        origens=origens,
        articulacao=0,
        componentes_de_um_socio=1,
    )
    linhas = dict(tabela.select("indicador", "valor").rows())
    assert linhas["componentes"] is None
    assert linhas["pessoas"] is None
    assert linhas["municipios_com_conexao_a"] is None
    assert linhas["municipios_com_conexao_b"] is None
    assert linhas["fracao_no_maior_componente"] == 6 / 9
    assert linhas["pessoas_ponto_de_articulacao"] == 0
    assert linhas["componentes_duas_empresas_um_socio"] is None


def _publicar_rede_de_estrelas(tamanhos):
    n = sum(tamanhos)
    rede = pl.DataFrame(
        {
            "id_rede": np.repeat(np.arange(len(tamanhos)), tamanhos),
            "empresas_na_rede": np.repeat(tamanhos, tamanhos),
        }
    )
    origens = pl.DataFrame(schema={"cod_municipio_tse": pl.String, "grupo": GRUPO})
    distancias = origens.with_columns(pl.lit(None, dtype=FAIXA).alias("faixa"))
    return descritivas.da_variante(
        rede, np.ones(n, dtype=int), np.array(tamanhos), distancias, origens, 0, 0
    )


def test_vinculos_e_faixas_vazias_nao_revelam_um_componente_raro():
    com_componente_grande = _publicar_rede_de_estrelas([1] * 6 + [10001])
    sem_componente_grande = _publicar_rede_de_estrelas([1] * 6 + [10])
    assert all(
        tabela.equals(sem_componente_grande[nome]) for nome, tabela in com_componente_grande.items()
    )


def test_agrupar_cauda_impede_recuperacao_pelo_total_e_pelo_maior_componente():
    # Mesmos vínculos, graus agrupados e totais, com um ou dois componentes acima de 10 mil.
    um = _publicar_rede_de_estrelas([1] * 6 + [12] * 5 + [19999, 9999, 502])
    dois = _publicar_rede_de_estrelas([1] * 6 + [12] * 5 + [19999, 10001, 500])
    assert all(tabela.equals(dois[nome]) for nome, tabela in um.items())
    cauda = um["rede_componentes"].filter(pl.col("faixa_tamanho") == "3+")
    assert cauda["componentes"].item() == 8


def test_rede_numera_componentes_sem_lacunas() -> None:
    """`descritivas.componentes` pressupõe a numeração que `network.redes` produz."""
    frame = pl.DataFrame(
        {
            "id_rede": [0, 0, 1],
            "cnpj_basico": ["1", "2", "3"],
            "empresas_na_rede": [2, 2, 1],
        }
    )
    tabela = descritivas.componentes(frame)
    assert tabela["componentes"].sum() == frame["id_rede"].n_unique()
    assert math.isclose(tabela["empresas"].sum(), frame.height)


def test_particao_suprime_complemento_e_colunas_associadas():
    tabela = pl.DataFrame(
        {
            "variante": ["A"] * 4 + ["B"] * 4,
            "componentes": [100, 20, 1, 0, 4, 40, 13, 10],
            "empresas": [100, 60, 20, 0, 4, 100, 45, 52],
        }
    )
    publica = descritivas.suprimir_particao(tabela, ("componentes", "empresas"), "variante")
    assert publica["componentes"].to_list() == [100, None, None, 0, None, 40, 13, None]
    assert publica["empresas"].to_list() == [100, None, None, 0, None, 100, 45, None]
    assert publica.equals(
        descritivas.suprimir_particao(publica, ("componentes", "empresas"), "variante")
    )
