from datetime import date

import polars as pl
import pytest

from redes import amostra, config, etapas, schemas
from redes.elections import classificar

MUN = "00001"
D2020 = date(2020, 11, 15)


def _candidato(
    ano: int,
    sq: str,
    pessoa: str,
    partido: str,
    coligacao: tuple[str, ...] = (),
    eleito: bool | None = None,
    data: date | None = None,
    tipo: str = "ORDINARIA",
    mun: str = MUN,
) -> dict:
    datas = {2020: D2020, 2024: config.DATA_ELEICAO}
    return dict(
        ano=ano,
        data_eleicao=data or datas[ano],
        tipo_eleicao=tipo,
        cod_municipio_tse=mun,
        sq_candidato=sq,
        id_pessoa=pessoa * 16,
        sigla_partido=partido,
        sq_coligacao=None,
        partidos_coligacao=list(coligacao or (partido,)),
        situacao_candidatura="DEFERIDO",
        eleito=eleito,
    )


def _voto(sq: str, votos: int, turno: int = 1, mun: str = MUN) -> dict:
    return dict(ano=2024, turno=turno, cod_municipio_tse=mun, sq_candidato=sq, votos=votos)


def _prefeito_2020(partido: str = "PA", pessoa: str = "a") -> list[dict]:
    return [
        _candidato(2020, "p1", pessoa, partido, eleito=True),
        _candidato(2020, "p2", "f", "PZ", eleito=False),
    ]


def _rodar(candidatos: list[dict], votos: list[dict]) -> tuple[pl.DataFrame, pl.DataFrame]:
    c = pl.DataFrame(candidatos, schema=schemas.CANDIDATOS.esquema, orient="row")
    v = pl.DataFrame(votos, schema=schemas.VOTOS.esquema, orient="row")
    eleicoes, exclusoes = (t.collect() for t in classificar(c.lazy(), v.lazy()))
    schemas.validar(eleicoes, schemas.ELEICOES)
    schemas.validar(exclusoes, schemas.EXCLUSOES)
    return eleicoes, exclusoes


def _unica(candidatos: list[dict], votos: list[dict]) -> dict:
    eleicoes, exclusoes = _rodar(candidatos, votos)
    assert exclusoes.is_empty(), exclusoes.to_dicts()
    return eleicoes.row(0, named=True)


def _motivo(candidatos: list[dict], votos: list[dict]) -> str:
    eleicoes, exclusoes = _rodar(candidatos, votos)
    assert eleicoes.is_empty()
    return exclusoes.row(0, named=True)["motivo"]


def test_ramo_prefeito():
    linha = _unica(
        [
            *_prefeito_2020(),
            _candidato(2024, "x1", "a", "PA"),
            _candidato(2024, "x2", "b", "PA"),
            _candidato(2024, "x3", "c", "PC"),
        ],
        [_voto("x1", 400), _voto("x2", 100), _voto("x3", 500)],
    )
    assert (linha["ramo"], linha["sq_candidato_a"], linha["sq_candidato_b"]) == (
        "PREFEITO",
        "x1",
        "x3",
    )


def test_prefeito_por_outro_partido_continua_no_ramo_prefeito():
    linha = _unica(
        [*_prefeito_2020(), _candidato(2024, "x1", "a", "PN"), _candidato(2024, "x2", "b", "PA")],
        [_voto("x1", 300), _voto("x2", 700)],
    )
    assert (linha["ramo"], linha["sq_candidato_a"]) == ("PREFEITO", "x1")


def test_ramo_partido():
    linha = _unica(
        [
            *_prefeito_2020(),
            _candidato(2024, "x1", "b", "PA"),
            _candidato(2024, "x2", "c", "PB", ("PB", "PA")),
        ],
        [_voto("x1", 300), _voto("x2", 700)],
    )
    assert (linha["ramo"], linha["sq_candidato_a"]) == ("PARTIDO", "x1")


def test_ramo_coligacao():
    linha = _unica(
        [
            *_prefeito_2020(),
            _candidato(2024, "x1", "b", "PB", ("PB", "PA")),
            _candidato(2024, "x2", "c", "PC"),
        ],
        [_voto("x1", 300), _voto("x2", 700)],
    )
    assert (linha["ramo"], linha["sq_candidato_a"]) == ("COLIGACAO", "x1")


def test_suplementar_mais_recente_define_o_prefeito():
    suplementares = [
        _candidato(2021, "s1", "b", "PB", eleito=True, data=date(2021, 6, 6), tipo="SUPLEMENTAR"),
        _candidato(2022, "s2", "c", "PC", eleito=True, data=date(2022, 6, 5), tipo="SUPLEMENTAR"),
        _candidato(2022, "s3", "a", "PA", eleito=False, data=date(2022, 6, 5), tipo="SUPLEMENTAR"),
    ]
    linha = _unica(
        [
            *_prefeito_2020(),
            *suplementares,
            _candidato(2024, "x1", "a", "PA"),
            _candidato(2024, "x2", "b", "PB"),
            _candidato(2024, "x3", "c", "PC"),
        ],
        [_voto("x1", 500), _voto("x2", 300), _voto("x3", 200)],
    )
    assert (linha["ramo"], linha["sq_candidato_a"], linha["sq_candidato_b"]) == (
        "PREFEITO",
        "x3",
        "x1",
    )


def test_suplementar_depois_da_eleicao_de_2024_nao_conta():
    posterior = _candidato(
        2024, "s1", "b", "PB", eleito=True, data=date(2024, 12, 1), tipo="SUPLEMENTAR"
    )
    linha = _unica(
        [
            *_prefeito_2020(),
            posterior,
            _candidato(2024, "x1", "a", "PA"),
            _candidato(2024, "x2", "c", "PC"),
        ],
        [_voto("x1", 500), _voto("x2", 300)],
    )
    assert linha["sq_candidato_a"] == "x1"


def test_margem_e_tratamento():
    perde = _unica(
        [
            *_prefeito_2020(),
            _candidato(2024, "x1", "a", "PA"),
            _candidato(2024, "x2", "b", "PB"),
            _candidato(2024, "x3", "c", "PC"),
        ],
        [_voto("x1", 450), _voto("x2", 480), _voto("x3", 70)],
    )
    assert perde["votos_validos"] == 1000
    assert perde["margem"] == pytest.approx(-3.0)
    assert perde["tratamento"] == 1

    vence = _unica(
        [*_prefeito_2020(), _candidato(2024, "x1", "a", "PA"), _candidato(2024, "x2", "b", "PB")],
        [_voto("x1", 600), _voto("x2", 400)],
    )
    assert (vence["margem"], vence["tratamento"]) == (pytest.approx(20.0), 0)


def test_empate_exato_nao_e_tratamento():
    linha = _unica(
        [*_prefeito_2020(), _candidato(2024, "x1", "a", "PA"), _candidato(2024, "x2", "b", "PB")],
        [_voto("x1", 500), _voto("x2", 500)],
    )
    assert (linha["margem"], linha["tratamento"]) == (0.0, 0)


def test_candidatura_sem_voto_valido_nao_concorre():
    linha = _unica(
        [
            *_prefeito_2020(),
            _candidato(2024, "x1", "a", "PA"),
            _candidato(2024, "x2", "b", "PA"),
            _candidato(2024, "x3", "c", "PC"),
        ],
        [_voto("x1", 0), _voto("x2", 400), _voto("x3", 600)],
    )
    assert (linha["ramo"], linha["sq_candidato_a"], linha["votos_validos"]) == (
        "PARTIDO",
        "x2",
        1000,
    )


def test_exclusao_segundo_turno():
    assert (
        _motivo(
            [
                *_prefeito_2020(),
                _candidato(2024, "x1", "a", "PA"),
                _candidato(2024, "x2", "b", "PB"),
            ],
            [
                _voto("x1", 450),
                _voto("x2", 550),
                _voto("x1", 480, turno=2),
                _voto("x2", 520, turno=2),
            ],
        )
        == "SEGUNDO_TURNO"
    )


def test_exclusao_sem_candidato():
    assert (
        _motivo(
            [
                *_prefeito_2020(),
                _candidato(2024, "x1", "b", "PB"),
                _candidato(2024, "x2", "c", "PC"),
            ],
            [_voto("x1", 450), _voto("x2", 550)],
        )
        == "SEM_CANDIDATO"
    )


def test_exclusao_ruptura_quando_o_ramo_tem_dois_candidatos():
    assert (
        _motivo(
            [
                *_prefeito_2020(),
                _candidato(2024, "x1", "b", "PB", ("PB", "PA")),
                _candidato(2024, "x2", "c", "PC", ("PC", "PA")),
                _candidato(2024, "x3", "d", "PD"),
            ],
            [_voto("x1", 450), _voto("x2", 350), _voto("x3", 200)],
        )
        == "RUPTURA"
    )


def test_exclusao_sem_adversario():
    assert (
        _motivo(
            [
                *_prefeito_2020(),
                _candidato(2024, "x1", "a", "PA"),
                _candidato(2024, "x2", "b", "PB"),
            ],
            [_voto("x1", 450), _voto("x2", 0)],
        )
        == "SEM_ADVERSARIO"
    )


@pytest.mark.parametrize(
    "anteriores",
    [
        [],
        [_candidato(2020, "p1", "a", "PA", eleito=False), _candidato(2020, "p2", "f", "PZ")],
        [
            _candidato(2020, "p1", "a", "PA", eleito=True),
            _candidato(2020, "p2", "f", "PZ", eleito=True),
        ],
    ],
    ids=["sem_eleicao_anterior", "nenhum_eleito", "dois_eleitos"],
)
def test_exclusao_prefeito_indefinido(anteriores):
    assert (
        _motivo(
            [*anteriores, _candidato(2024, "x1", "a", "PA"), _candidato(2024, "x2", "b", "PB")],
            [_voto("x1", 450), _voto("x2", 550)],
        )
        == "PREFEITO_INDEFINIDO"
    )


def test_cada_municipio_sai_em_uma_tabela():
    outro = "00002"
    eleicoes, exclusoes = _rodar(
        [
            *_prefeito_2020(),
            _candidato(2024, "x1", "a", "PA"),
            _candidato(2024, "x2", "b", "PB"),
            _candidato(2024, "y1", "c", "PC", mun=outro),
        ],
        [_voto("x1", 450), _voto("x2", 550), _voto("y1", 100, mun=outro)],
    )
    assert eleicoes[schemas.MUNICIPIO.nome].to_list() == [MUN]
    assert exclusoes.select(schemas.MUNICIPIO.nome, "motivo").rows() == [
        (outro, "PREFEITO_INDEFINIDO")
    ]


def test_amostra(caminhos_amostra):
    etapas.rodar("elections", caminhos_amostra)
    eleicoes = schemas.ler(schemas.ELEICOES, caminhos_amostra.dados).collect()
    exclusoes = schemas.ler(schemas.EXCLUSOES, caminhos_amostra.dados).collect()

    motivos = dict(exclusoes.select(schemas.MUNICIPIO.nome, "motivo").iter_rows())
    assert motivos == {
        amostra.codigo(amostra.SEM_ADVERSARIO): "SEM_ADVERSARIO",
        amostra.codigo(amostra.SEGUNDO_TURNO): "SEGUNDO_TURNO",
        amostra.codigo(amostra.SEM_CANDIDATO): "SEM_CANDIDATO",
    }
    assert eleicoes.height + exclusoes.height == amostra.N_MUNICIPIOS

    linhas = {r[schemas.MUNICIPIO.nome]: r for r in eleicoes.iter_rows(named=True)}
    figura = linhas[amostra.MUNICIPIO_FIGURA_1]
    assert figura["margem"] == pytest.approx(-3.0, abs=0.01)
    assert figura["tratamento"] == 1

    for i in range(1, amostra.N_MUNICIPIOS + 1):
        linha = linhas.get(amostra.codigo(i))
        if linha is not None:
            assert linha["ramo"] == amostra.ramo_esperado(i), i
            assert linha["sq_candidato_a"] == f"2024{i:04d}01", i

    suplementar = linhas[amostra.codigo(amostra.SUPLEMENTAR)]
    assert suplementar["sq_candidato_b"] == f"2024{amostra.SUPLEMENTAR:04d}02"
