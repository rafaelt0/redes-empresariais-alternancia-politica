import csv
import io
import zipfile
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from redes import schemas
from redes.ingest import tse
from redes.pseudonimo import pseudonimo

CHAVE = b"teste"
MUN = "90001"
SUPLEMENTAR = "90003"

ANA = ("Ana Exemplo", "99900000199", "101")
ANA_CASADA = "Ana Exemplo Souza"
BRUNO = ("Bruno Exemplo", "99900000299", "202")
CARLA = ("Carla Exemplo", "99900000399", "303")
DANIEL = ("Daniel Exemplo", "99900000499", "404")
EVA = ("Eva Exemplo", "-4", "505")
DOADORA = ("Fabia Exemplo", "1234567890")
DOADORA_RFB = "Fabia Exemplo Receita"
HOMONIMA = ("Fabia Exemplo Receita", "99934567800")
VICE = ("Gil Exemplo", "99900000799")
CNPJ_PARTIDO = "1234567000199"
CNPJ_PLATAFORMA = "22333444000155"


def _zip(caminho: Path, membro: str, linhas: list[dict]) -> Path:
    texto = io.StringIO()
    escritor = csv.DictWriter(
        texto, fieldnames=list(linhas[0]), delimiter=";", quoting=csv.QUOTE_ALL
    )
    escritor.writeheader()
    escritor.writerows(linhas)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(caminho, "a") as arquivo:
        arquivo.writestr(membro, texto.getvalue().encode("latin-1"))
    return caminho


def _cand(
    pessoa, sq, data, ue=MUN, eleito="NÃO ELEITO", partido="PSDB", coligacao="PSDB", **outros
):
    nome, cpf, titulo = pessoa
    linha = {
        "NM_TIPO_ELEICAO": "ELEIÇÃO ORDINÁRIA",
        "NR_TURNO": "1",
        "DT_ELEICAO": data,
        "SG_UE": ue,
        "DS_CARGO": "PREFEITO",
        "SQ_CANDIDATO": sq,
        "NM_CANDIDATO": nome,
        "NR_CPF_CANDIDATO": cpf,
        "NR_TITULO_ELEITORAL_CANDIDATO": titulo,
        "DS_SITUACAO_CANDIDATURA": "APTO",
        "SG_PARTIDO": partido,
        "SQ_COLIGACAO": f"9{sq}",
        "DS_COMPOSICAO_COLIGACAO": coligacao,
        "DS_SIT_TOT_TURNO": eleito,
    }
    return linha | outros


def _receita(sq, origem, doc, nome, rfb, sq_receita, valor="100,00", **outros):
    linha = {
        "NM_TIPO_ELEICAO": "ORDINÁRIA",
        "SG_UE": MUN,
        "DS_CARGO": "Prefeito",
        "SQ_PRESTADOR_CONTAS": f"P{sq}",
        "SQ_CANDIDATO": sq,
        "DS_ORIGEM_RECEITA": origem,
        "NR_CPF_CNPJ_DOADOR": doc,
        "NM_DOADOR": nome,
        "NM_DOADOR_RFB": rfb,
        "SQ_RECEITA": sq_receita,
        "DT_RECEITA": "02/09/2024",
        "VR_RECEITA": valor,
    }
    return linha | outros


def _votos(sq, turno, zona_validos, destinacao="Válido", ue=MUN):
    return {
        "NM_TIPO_ELEICAO": "Eleição Ordinária",
        "NR_TURNO": turno,
        "SG_UE": ue,
        "DS_CARGO": "Prefeito",
        "SQ_CANDIDATO": sq,
        "DS_SITUACAO_JULGAMENTO": "DEFERIDO",
        "NM_TIPO_DESTINACAO_VOTOS": destinacao,
        "QT_VOTOS_NOMINAIS_VALIDOS": zona_validos,
    }


@pytest.fixture(scope="module")
def brutos(tmp_path_factory) -> dict[str, Path]:
    raiz = tmp_path_factory.mktemp("raw")
    caminhos = {nome: raiz / chave for nome, chave in tse.ENTRADAS.items()}

    _zip(
        caminhos["cand_2020"],
        "consulta_cand_2020_SP.csv",
        [
            _cand(ANA, "1", "15/11/2020", eleito="ELEITO", partido="DEM", coligacao="DEM / PTB"),
            _cand(BRUNO, "2", "15/11/2020"),
            _cand(CARLA, "3", "15/11/2020", DS_CARGO="VEREADOR"),
            _cand(DANIEL, "4", "15/11/2020", ue=SUPLEMENTAR),
            _cand(
                DANIEL,
                "5",
                "05/06/2022",
                ue=SUPLEMENTAR,
                eleito="ELEITO",
                NM_TIPO_ELEICAO="ELEIÇÃO SUPLEMENTAR",
            ),
            _cand(BRUNO, "6", "15/11/2020", ue=tse.COD_CAPITAL, eleito="ELEITO"),
        ],
    )
    _zip(
        caminhos["suplementares_2020"],
        "lista_eleicoes_suplementares_2020.csv",
        [{"CD_ELEICAO": "1", "SG_UF": "SP", "DS_CARGO": "Prefeito", "CD_MUNICIPIO": SUPLEMENTAR}],
    )
    mascara = {"NR_CPF_CANDIDATO": "-4", "DS_SITUACAO_CANDIDATURA": "#NE"}
    _zip(
        caminhos["cand_2024"],
        "consulta_cand_2024_SP.csv",
        [
            _cand(
                (ANA_CASADA, "-4", "101"),
                "24001",
                "06/10/2024",
                partido="UNIÃO",
                eleito="2º TURNO",
                DS_SITUACAO_CANDIDATURA="#NE",
            ),
            _cand(
                (ANA_CASADA, "-4", "101"),
                "24001",
                "27/10/2024",
                partido="UNIÃO",
                eleito="ELEITO",
                NR_TURNO="2",
            ),
            _cand((CARLA[0], "-4", "303"), "24002", "06/10/2024", **mascara),
            _cand((DOADORA[0], "-4", "999"), "24003", "06/10/2024", **mascara),
            _cand(EVA, "24004", "06/10/2024", **mascara),
            _cand(
                (CARLA[0], "-4", "303"),
                "24009",
                "08/06/2025",
                NM_TIPO_ELEICAO="ELEIÇÃO SUPLEMENTAR",
            ),
        ],
    )
    coligacao = {"NM_TIPO_ELEICAO": "ELEIÇÃO ORDINÁRIA", "SG_UE": MUN, "DS_CARGO": "PREFEITO"}
    _zip(
        caminhos["coligacao_2024"],
        "consulta_coligacao_2024_SP.csv",
        [
            coligacao | {"SQ_COLIGACAO": "924001", "SG_PARTIDO": p, "DS_SITUACAO": s}
            for p, s in (("UNIÃO", "DEFERIDO"), ("PT", "DEFERIDO"), ("PV", "INDEFERIDO"))
        ],
    )
    _zip(
        caminhos["votacao_2024"],
        "votacao_candidato_munzona_2024_SP.csv",
        [
            _votos("24001", "1", "100"),
            _votos("24001", "1", "50"),
            _votos("24002", "1", "120"),
            _votos("24004", "1", "0", destinacao="Anulado"),
            _votos("24001", "2", "300"),
            _votos("24002", "2", "200"),
            _votos("77", "1", "999", ue=tse.COD_CAPITAL),
        ],
    )
    nome_doadora, cpf_doadora = DOADORA
    contas = caminhos["contas_2024"]
    _zip(
        contas,
        "receitas_candidatos_2024_SP.csv",
        [
            _receita(
                "24002", "Recursos de pessoas físicas", cpf_doadora, nome_doadora, DOADORA_RFB, "1"
            ),
            _receita("24002", "Doações pela Internet", HOMONIMA[1], HOMONIMA[0], "#NULO", "2"),
            _receita("24002", "Recursos de Financiamento Coletivo", CNPJ_PLATAFORMA, "P", "P", "3"),
            _receita("24002", "Recursos de partido político", CNPJ_PARTIDO, "X", "X", "4"),
            _receita("24002", "Recursos de partido político", CNPJ_PARTIDO, "X", "X", "4"),
            _receita("24003", "Recursos próprios", "99900000599", nome_doadora, "#NULO", "5"),
            _receita("24003", "Recursos próprios", VICE[1], VICE[0], VICE[0], "6"),
            _receita("24002", "#NULO", "-1", "#NULO", "#NULO", "7", valor="0,00", DT_RECEITA=""),
            _receita(
                "24002",
                "Recursos de pessoas físicas",
                cpf_doadora,
                nome_doadora,
                DOADORA_RFB,
                "8",
                DT_RECEITA="20/10/2024",
            ),
            _receita(
                "24009",
                "Recursos de pessoas físicas",
                "1",
                "Z",
                "Z",
                "9",
                NM_TIPO_ELEICAO="SUPLEMENTAR",
            ),
            _receita(
                "24002", "Recursos de pessoas físicas", "1", "Z", "Z", "10", DS_CARGO="Vereador"
            ),
        ],
    )
    _zip(
        contas,
        "receitas_candidatos_doador_originario_2024_SP.csv",
        [
            {
                "SQ_PRESTADOR_CONTAS": "P24002",
                "SQ_RECEITA": "3",
                "NR_CPF_CNPJ_DOADOR_ORIGINARIO": "99900000899",
            }
        ],
    )
    return caminhos


@pytest.fixture(scope="module")
def ingestao(brutos) -> tse.Ingestao:
    return tse.ingerir(brutos, CHAVE)


def _id(nome: str, cpf: str) -> str:
    return pseudonimo(nome, cpf, CHAVE)


def _candidato(ingestao, sq: str) -> dict:
    return ingestao.candidatos.filter(pl.col("sq_candidato") == sq).row(0, named=True)


def _valor(ingestao, indicador: str, recorte: str | None = None) -> float:
    linhas = ingestao.validacao.filter(
        (pl.col("indicador") == indicador)
        & (pl.col("recorte").is_null() if recorte is None else pl.col("recorte") == recorte)
    )
    return linhas["valor"].item()


def test_tabelas_obedecem_aos_esquemas(ingestao):
    schemas.validar(ingestao.candidatos, schemas.CANDIDATOS)
    schemas.validar(ingestao.votos, schemas.VOTOS)
    schemas.validar(ingestao.doacoes, schemas.DOACOES)
    schemas.validar(ingestao.ambiguos, schemas.PSEUDONIMOS_AMBIGUOS)


def test_nome_e_cpf_nao_chegam_as_tabelas(ingestao):
    proibidos = {
        p for pessoa in (ANA, BRUNO, CARLA, DANIEL, DOADORA, HOMONIMA, VICE) for p in pessoa[:2]
    } | {ANA_CASADA, DOADORA_RFB, "99900000599", "01234567890"}
    for tabela in (ingestao.candidatos, ingestao.doacoes, ingestao.votos, ingestao.ambiguos):
        texto = str(tabela.to_dicts())
        assert not any(p in texto for p in proibidos if p != "-4")


def test_capital_e_eleicoes_posteriores_ficam_fora(ingestao):
    for tabela in (ingestao.candidatos, ingestao.votos, ingestao.doacoes):
        assert tse.COD_CAPITAL not in tabela["cod_municipio_tse"].to_list()
    assert "24009" not in ingestao.candidatos["sq_candidato"].to_list()
    assert ingestao.candidatos["data_eleicao"].max() == date(2024, 10, 6)


def test_candidatura_com_dois_turnos_vira_uma_linha_eleita(ingestao):
    ana = _candidato(ingestao, "24001")
    assert (ana["data_eleicao"], ana["eleito"], ana["tipo_eleicao"]) == (
        date(2024, 10, 6),
        True,
        "ORDINARIA",
    )
    assert ingestao.candidatos.filter(pl.col("sq_candidato") == "24001").height == 1


def test_prefeito_de_2020_e_candidato_de_2024_tem_o_mesmo_id_mesmo_mudando_de_nome(ingestao):
    assert _candidato(ingestao, "1")["id_pessoa"] == _candidato(ingestao, "24001")["id_pessoa"]
    assert _candidato(ingestao, "24001")["id_pessoa"] == _id(ANA_CASADA, ANA[1])


def test_cpf_de_2024_pelo_titulo_e_pelos_recursos_proprios(ingestao):
    assert _candidato(ingestao, "24002")["id_pessoa"] == _id(CARLA[0], CARLA[1])
    assert _candidato(ingestao, "24003")["id_pessoa"] == _id(DOADORA[0], "99900000599")
    assert _valor(ingestao, "cpf_candidato_2024", "TITULO_2020") == 2
    assert _valor(ingestao, "cpf_candidato_2024", "RECURSOS_PROPRIOS") == 1
    assert _valor(ingestao, "cpf_candidato_2024", "SEM_CPF") == 1


def test_candidato_sem_cpf_nao_se_liga_a_ninguem(ingestao):
    eva = _candidato(ingestao, "24004")["id_pessoa"]
    assert len(eva) == 16
    assert eva not in ingestao.doacoes["id_doador"].to_list()


def test_partido_anterior_a_2024_usa_a_sigla_sucessora(ingestao):
    ana_2020 = _candidato(ingestao, "1")
    assert ana_2020["sigla_partido"] == "UNIÃO"
    assert ana_2020["partidos_coligacao"] == ["PRD", "UNIÃO"]


def test_coligacao_de_2024_vem_do_arquivo_sem_partido_indeferido(ingestao):
    assert _candidato(ingestao, "24001")["partidos_coligacao"] == ["PT", "UNIÃO"]
    assert _candidato(ingestao, "24002")["partidos_coligacao"] == ["PSDB"]


def test_suplementar_entra_e_eleicao_sem_eleito_e_listada(ingestao):
    suplementar = _candidato(ingestao, "5")
    assert (suplementar["tipo_eleicao"], suplementar["ano"], suplementar["eleito"]) == (
        "SUPLEMENTAR",
        2022,
        True,
    )
    sem_eleito = ingestao.eleicoes_sem_eleito_unico
    assert sem_eleito.select("cod_municipio_tse", "data_eleicao").rows() == [
        (SUPLEMENTAR, date(2020, 11, 15))
    ]


def test_votos_validos_somam_zonas_e_ignoram_anulados(ingestao):
    votos = {(t, sq): v for _, t, _, sq, v in ingestao.votos.iter_rows()}
    assert votos[(1, "24001")] == 150
    assert votos[(1, "24004")] == 0
    assert votos[(2, "24001")] == 300


def test_doacoes_tem_origem_tipo_e_documento_completo(ingestao):
    d = {r["id_receita"]: r for r in ingestao.doacoes.iter_rows(named=True)}
    assert d["1-0"]["id_doador"] == _id(DOADORA_RFB, "01234567890")
    assert (d["1-0"]["origem"], d["1-0"]["tipo_doador"]) == ("PESSOA_FISICA", "PF")
    assert d["2-0"]["id_doador"] == _id(*HOMONIMA)
    assert (d["3-0"]["origem"], d["3-0"]["tipo_doador"], d["3-0"]["id_doador"]) == (
        "PESSOA_FISICA",
        "PJ",
        "22333444",
    )
    assert (d["4-0"]["origem"], d["4-1"]["id_doador"]) == ("REPASSE", "01234567")
    assert d["5-0"]["origem"] == "RECURSOS_PROPRIOS"
    assert d["8-0"]["data_receita"] == date(2024, 10, 20)
    assert "7-0" not in d


def test_pseudonimo_com_dois_cpfs_e_contado(ingestao):
    assert ingestao.ambiguos["id_pessoa"].to_list() == [_id(*HOMONIMA)]
    assert _valor(ingestao, "pseudonimos_com_mais_de_um_cpf") == 1
    assert _valor(ingestao, "doadores_originarios_pf_distintos") == 1
    assert _valor(ingestao, "receitas_apos_limite", "2024-10-05") == 1


def test_validacao_versionada_suprime_contagens_pequenas(ingestao):
    suprimida = tse.suprimir(ingestao.validacao)
    assert suprimida.filter(pl.col("valor").is_between(1, 4))["valor"].len() == 0
    assert suprimida.filter(pl.col("indicador") == "cpf_candidato_2024")["valor"].null_count() > 0


@pytest.mark.parametrize(
    ("composicao", "partidos"),
    [
        ("PSDB", ["PSDB"]),
        ("PP / MDB", ["MDB", "PP"]),
        (
            "SOLIDARIEDADE / Federação PSDB CIDADANIA (45-PSDB / 23-CIDADANIA) / UNIÃO",
            ["CIDADANIA", "PSDB", "SOLIDARIEDADE", "UNIÃO"],
        ),
        (
            "PDT / Federação BRASIL DA ESPERANÇA - FE BRASIL(PT/PC do B/PV)",
            ["PC do B", "PDT", "PT", "PV"],
        ),
    ],
)
def test_partidos_da_composicao(composicao, partidos):
    assert tse.partidos_da_composicao(composicao) == partidos


def test_cpf_valido():
    assert tse.cpf_valido("52998224725")
    assert not tse.cpf_valido("52998224726")
    assert not tse.cpf_valido("11111111111")
