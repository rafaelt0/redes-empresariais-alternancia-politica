import stat
from concurrent.futures import ThreadPoolExecutor

import polars as pl
import pytest

from redes.pseudonimo import (
    carregar_chave,
    digitos_centrais,
    normalizar_nome,
    pseudonimizar,
    pseudonimo,
)

CHAVE = b"chave de teste"


def test_socio_mascarado_e_doador_completo_tem_o_mesmo_pseudonimo():
    socio = pseudonimo("JOSÉ  da Silva", "***456789**", CHAVE)
    doador = pseudonimo("Jose da Silva", "123.456.789-01", CHAVE)
    assert socio == doador
    assert len(socio) == 16


def test_homonimos_com_digitos_diferentes_nao_se_ligam():
    assert pseudonimo("Ana Exemplo", "11145678900", CHAVE) != pseudonimo(
        "Ana Exemplo", "11145678000", CHAVE
    )


def test_pseudonimo_depende_da_chave():
    assert pseudonimo("Ana", "11145678900", CHAVE) != pseudonimo("Ana", "11145678900", b"outra")


def test_normalizacao_de_nome():
    assert normalizar_nome("  Conceição d'Ávila-Souza ") == "CONCEICAO D AVILA SOUZA"


@pytest.mark.parametrize("cpf", ["", "123", "***12345**", "1234567890a"])
def test_cpf_invalido_e_rejeitado(cpf):
    with pytest.raises(ValueError):
        digitos_centrais(cpf)


def test_versao_vetorial_coincide_com_a_escalar():
    nomes = pl.Series(["Ana", "Bruno"])
    cpfs = pl.Series(["***456789**", "98765432100"])
    assert pseudonimizar(nomes, cpfs, CHAVE).to_list() == [
        pseudonimo("Ana", "***456789**", CHAVE),
        pseudonimo("Bruno", "98765432100", CHAVE),
    ]


def test_chave_gerada_uma_vez_e_privada(tmp_path):
    caminho = tmp_path / "sub" / "chave"
    primeira = carregar_chave(caminho)
    assert carregar_chave(caminho) == primeira
    assert len(primeira) == 32
    assert stat.S_IMODE(caminho.stat().st_mode) == 0o600


def test_ingestoes_concorrentes_leem_a_mesma_chave(tmp_path):
    caminho = tmp_path / "nova" / "chave"
    with ThreadPoolExecutor(8) as executor:
        chaves = list(executor.map(carregar_chave, [caminho] * 16))
    assert len(set(chaves)) == 1
    assert len(chaves[0]) == 32


def test_chave_incompleta_e_rejeitada(tmp_path):
    caminho = tmp_path / "chave"
    caminho.touch()
    with pytest.raises(ValueError, match="32 bytes"):
        carregar_chave(caminho)
