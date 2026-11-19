from datetime import date

import polars as pl
import pytest

from redes import amostra, etapas, links, schemas
from redes.amostra import EMPRESAS_FIGURA_1, MUNICIPIO_FIGURA_1, id_figura_1
from redes.pseudonimo import pseudonimo

CHAVE = b"teste"
MARIA = pseudonimo("Maria Silva", "11122233344", CHAVE)
MARIA_HOMONIMA = pseudonimo("Maria Silva", "11199999944", CHAVE)
JOAO = pseudonimo("Joao Souza", "55566677788", CHAVE)


def _eleicoes() -> pl.LazyFrame:
    linhas = [("00001", "PREFEITO", "A1", "B1", 1000, 2.0, 0)]
    return pl.LazyFrame(linhas, schema=schemas.ELEICOES.esquema, orient="row")


def _socios(*linhas: tuple[str, str, str, str]) -> pl.LazyFrame:
    completas = [
        (cnpj, id_, tipo, vinculo, "49", None, "2024-09") for cnpj, id_, tipo, vinculo in linhas
    ]
    return pl.LazyFrame(completas, schema=schemas.SOCIOS.esquema, orient="row")


def _doacoes(*linhas: tuple[str, str, date], origem: str = "PESSOA_FISICA") -> pl.LazyFrame:
    completas = [
        (2024, sq, "00001", f"R{n}", id_doador, "PF", origem, data, 100.0)
        for n, (sq, id_doador, data) in enumerate(linhas)
    ]
    return pl.LazyFrame(completas, schema=schemas.DOACOES.esquema, orient="row")


def _conexoes(socios: pl.LazyFrame, doacoes: pl.LazyFrame) -> pl.DataFrame:
    df = links.conexoes_diretas(socios, links.doadores(doacoes, _eleicoes())).collect()
    schemas.validar(df, schemas.CONEXOES_DIRETAS)
    return df


def _pares(df: pl.DataFrame) -> set[tuple[str, str, str]]:
    return set(df.select("grupo", "cnpj_basico", "id_pessoa").iter_rows())


@pytest.mark.parametrize(
    ("data", "conecta"), [(date(2024, 10, 5), True), (date(2024, 10, 6), False)]
)
def test_corte_na_vespera_da_eleicao(data, conecta):
    df = _conexoes(_socios(("00000010", MARIA, "PF", "SOCIO")), _doacoes(("A1", MARIA, data)))
    assert _pares(df) == ({("A", "00000010", MARIA)} if conecta else set())


def test_recursos_proprios_do_candidato_entram_na_regra_do_pc1():
    socios = _socios(("00000010", MARIA, "PF", "SOCIO"))
    doacoes = _doacoes(("A1", MARIA, date(2024, 9, 1)), origem="RECURSOS_PROPRIOS")
    assert _pares(_conexoes(socios, doacoes)) == {("A", "00000010", MARIA)}
    terceiros = links.doadores(doacoes, _eleicoes(), ("PESSOA_FISICA",))
    assert links.conexoes_diretas(socios, terceiros).collect().is_empty()


def test_homonimo_com_outros_digitos_nao_liga():
    df = _conexoes(
        _socios(("00000010", MARIA, "PF", "SOCIO")),
        _doacoes(("B1", MARIA_HOMONIMA, date(2024, 9, 1))),
    )
    assert df.is_empty()


def test_socio_pessoa_juridica_nao_liga():
    df = _conexoes(
        _socios(("00000010", "00000020", "PJ", "SOCIO")),
        _doacoes(("A1", MARIA, date(2024, 9, 1))),
    )
    assert df.is_empty()


def test_doador_sem_empresa_nao_gera_linha():
    df = _conexoes(
        _socios(("00000010", MARIA, "PF", "SOCIO")),
        _doacoes(("A1", MARIA, date(2024, 9, 1)), ("B1", JOAO, date(2024, 9, 1))),
    )
    assert _pares(df) == {("A", "00000010", MARIA)}


def test_doador_de_outro_candidato_nao_gera_linha():
    df = _conexoes(
        _socios(("00000010", MARIA, "PF", "SOCIO")),
        _doacoes(("C1", MARIA, date(2024, 9, 1))),
    )
    assert df.is_empty()


def test_socio_com_varias_empresas_conecta_todas():
    df = _conexoes(
        _socios(
            ("00000010", MARIA, "PF", "SOCIO"),
            ("00000011", MARIA, "PF", "SOCIO"),
            ("00000012", MARIA, "PF", "ADMINISTRADOR_NAO_SOCIO"),
        ),
        _doacoes(("A1", MARIA, date(2024, 9, 1)), ("A1", MARIA, date(2024, 9, 2))),
    )
    assert dict(df.select("cnpj_basico", "vinculo").iter_rows()) == {
        "00000010": "SOCIO",
        "00000011": "SOCIO",
        "00000012": "ADMINISTRADOR_NAO_SOCIO",
    }
    assert df["valor_doado"].to_list() == [200.0] * 3


def test_socio_e_administrador_na_mesma_empresa_conta_como_socio():
    socios = pl.concat(
        [
            _socios(("00000010", MARIA, "PF", "ADMINISTRADOR_NAO_SOCIO")),
            _socios(("00000010", MARIA, "PF", "SOCIO")).with_columns(cod_qualificacao=pl.lit("22")),
        ]
    )
    df = _conexoes(socios, _doacoes(("A1", MARIA, date(2024, 9, 1))))
    assert df.select("cnpj_basico", "vinculo").rows() == [("00000010", "SOCIO")]


def test_resumo_suprime_contagens_pequenas():
    doadores = links.doadores(_doacoes(("A1", MARIA, date(2024, 9, 1))), _eleicoes()).collect()
    conexoes = _conexoes(
        _socios(("00000010", MARIA, "PF", "SOCIO")), _doacoes(("A1", MARIA, date(2024, 9, 1)))
    )
    resumo = links.resumo_pc1(doadores, conexoes, _eleicoes().collect())
    valor = {(i, g): v for i, g, v in resumo.iter_rows()}
    assert valor[("doadores_pf", "A")] is None
    assert valor[("taxa_cruzamento", "A")] is None
    assert valor[("doadores_pf", "B")] == 0
    assert valor[("municipios_com_conexao", "A")] is None
    assert valor[("municipios_com_conexao", "AMBOS")] == 0
    assert valor[("municipios_analisaveis", None)] is None


def _eleicoes_figura_1(tabelas: dict[str, pl.DataFrame]) -> pl.DataFrame:
    sq_a, sq_b = (
        tabelas["candidatos"]
        .filter((pl.col("ano") == 2024) & (pl.col("cod_municipio_tse") == MUNICIPIO_FIGURA_1))[
            "sq_candidato"
        ]
        .sort()
        .head(2)
        .to_list()
    )
    linha = [(MUNICIPIO_FIGURA_1, "PREFEITO", sq_a, sq_b, 10000, -3.0, 1)]
    return pl.DataFrame(linha, schema=schemas.ELEICOES.esquema, orient="row")


def test_figura_1_na_amostra(caminhos_amostra, tabelas_amostra):
    schemas.gravar(_eleicoes_figura_1(tabelas_amostra), schemas.ELEICOES, caminhos_amostra.dados)
    etapas.rodar("links", caminhos_amostra)

    conexoes = schemas.ler(schemas.CONEXOES_DIRETAS, caminhos_amostra.dados).collect()
    figura = set(EMPRESAS_FIGURA_1.values())
    homonima = amostra.id_pessoa(*amostra.HOMONIMA_DE_ANA)
    assert _pares(conexoes.filter(pl.col("cnpj_basico").is_in(figura))) == {
        ("A", EMPRESAS_FIGURA_1["X"], id_figura_1("Ana")),
        ("B", EMPRESAS_FIGURA_1["Z"], id_figura_1("Daniel")),
    }
    assert {id_figura_1("Carla"), homonima}.isdisjoint(conexoes["id_pessoa"])

    resumo = pl.read_csv(caminhos_amostra.resultados / "tables" / links.ARQUIVO_RESUMO)
    assert resumo.columns == ["indicador", "grupo", "valor"]
    assert resumo.filter(pl.col("grupo") == "AMBOS")["valor"].to_list() == [None]
