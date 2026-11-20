import polars as pl
import pytest

from redes import rede_coortes


def test_concentracao_usa_peso_municipal_vezes_nucleo_e_exclui_a_fronteira():
    amostra = pl.DataFrame(
        {
            "x": [-1.0] * 6 + [2.0] * 6 + [4.0],
            "w": [1 / 6] * 12 + [1.0],
            "rede": ["g"] * 6 + ["a", "b", "c", "d", "e", "f", "g"],
            "municipio": ["m1"] * 6 + ["m2"] * 6 + ["m3"],
        }
    )
    r = rede_coortes.concentracao(amostra, "g", 4.0)
    assert r["fracao_observacoes_gigante"] == 0.5
    assert r["fracao_peso_gigante"] == pytest.approx(0.6)
    assert r["redes"] == 7
    assert r["redes_sem_gigante_controle"] == 6
    assert r["municipios_sem_gigante_tratados"] == 0
    assert r["municipios_sem_gigante_controle"] is None
    assert not r["suporte_minimo_sem_gigante"]


def test_concentracao_protege_complemento_pequeno_com_limites():
    amostra = pl.DataFrame(
        {
            "x": [-1.0] * 600 + [2.0] * 601,
            "w": [1 / 600] * 600 + [1 / 601] * 601,
            "rede": ["g"] * 1200 + ["pequena"],
            "municipio": ["m1"] * 600 + ["m2"] * 601,
        }
    )
    r = rede_coortes.concentracao(amostra, "g", 4.0)
    assert r["piso_fracao_observacoes"] == 0.99
    assert r["piso_fracao_peso"] == 0.99
    assert r["fracao_observacoes_gigante"] is None
    assert r["fracao_peso_gigante"] is None
    assert r["redes"] is None
    assert r["redes_sem_gigante_controle"] is None


def test_piso_da_fracao_nao_revela_complemento_em_denominador_pequeno():
    amostra = pl.DataFrame(
        {
            "x": [-1.0] * 25 + [1.0] * 26,
            "w": [1 / 25] * 25 + [1 / 26] * 26,
            "rede": ["g"] * 50 + ["pequena"],
            "municipio": ["m1"] * 25 + ["m2"] * 26,
        }
    )
    r = rede_coortes.concentracao(amostra, "g", 2.0)
    assert r["piso_fracao_observacoes"] == 0.90
    assert r["piso_fracao_peso"] == 0.90
    assert r["fracao_observacoes_gigante"] is None
    assert r["fracao_peso_gigante"] is None
