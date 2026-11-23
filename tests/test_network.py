import polars as pl
import pytest

from redes import amostra, descritivas, etapas, network, schemas
from redes.schemas import CONEXOES_DIRETAS, DISTANCIAS, REDE, SOCIOS

MUNICIPIO = "90001"
X, Y, Z = "00000001", "00000002", "00000003"
ANA, BRUNO, CARLA, DANIEL = (f"{n:016x}" for n in (0xA1, 0xB2, 0xC3, 0xD4))


def pessoa(n: int) -> str:
    return f"{0xF000 + n:016x}"


def socio(cnpj: str, id_socio: str, tipo: str = "PF", vinculo: str = "SOCIO") -> dict:
    return {
        "cnpj_basico": cnpj,
        "id_socio": id_socio,
        "tipo_socio": tipo,
        "vinculo": vinculo,
        "cod_qualificacao": "05" if vinculo == "ADMINISTRADOR_NAO_SOCIO" else "49",
        "data_entrada": None,
        "origem": "2024-09",
    }


def conexao(cnpj: str, id_pessoa: str, grupo: str = "A", municipio: str = MUNICIPIO) -> dict:
    return {
        "cod_municipio_tse": municipio,
        "grupo": grupo,
        "cnpj_basico": cnpj,
        "id_pessoa": id_pessoa,
        "vinculo": "SOCIO",
        "valor_doado": 1000.0,
    }


FIGURA_1 = [
    socio(X, ANA),
    socio(X, BRUNO),
    socio(Y, BRUNO),
    socio(Y, CARLA),
    socio(Z, CARLA),
    socio(Z, DANIEL),
]
CONEXOES_FIGURA_1 = [conexao(X, ANA, "A"), conexao(Z, DANIEL, "B")]


def rodar(socios: list[dict], conexoes: list[dict]) -> dict[str, pl.DataFrame]:
    """Etapa sobre entradas montadas à mão; toda empresa citada é fornecedora de MUNICIPIO."""
    frame_socios = pl.DataFrame(socios, schema=SOCIOS.esquema, orient="row")
    frame_conexoes = pl.DataFrame(conexoes, schema=CONEXOES_DIRETAS.esquema, orient="row")
    schemas.validar(frame_socios, SOCIOS)
    schemas.validar(frame_conexoes, CONEXOES_DIRETAS)
    empresas = frame_socios.select("cnpj_basico").unique()
    alvos = empresas.with_columns(cod_municipio_tse=pl.lit(MUNICIPIO)).lazy()
    resultados = network.calcular(
        network.vinculos_da_fotografia(frame_socios.lazy()),
        network.conexoes_com_chave(frame_conexoes.lazy()),
        network.alvos_dos_empenhos(alvos),
    )
    saida = network.tabelas(resultados)
    for nome, frame in saida.items():
        schemas.validar(frame, schemas.TABELAS[nome])
    return saida


def _linha(saida: dict, cnpj: str, grupo: str, variante: str) -> dict:
    return (
        saida[DISTANCIAS.nome]
        .filter(variante=variante, cod_municipio_tse=MUNICIPIO, grupo=grupo, cnpj_basico=cnpj)
        .row(0, named=True)
    )


def faixa(saida: dict, cnpj: str, grupo: str = "A", variante: str = "PRINCIPAL") -> str:
    return _linha(saida, cnpj, grupo, variante)["faixa"]


def distancia(saida: dict, cnpj: str, grupo: str = "A", variante: str = "PRINCIPAL") -> int | None:
    return _linha(saida, cnpj, grupo, variante)["distancia"]


def mesma_rede(saida: dict, a: str, b: str, variante: str = "PRINCIPAL") -> bool:
    rede = saida[REDE.nome].filter(variante=variante)
    return (
        rede.filter(cnpj_basico=a)["id_rede"].item() == rede.filter(cnpj_basico=b)["id_rede"].item()
    )


def test_distancias_da_figura_1():
    saida = rodar(FIGURA_1, CONEXOES_FIGURA_1)
    esperado = {(X, "A"): 0, (Y, "A"): 1, (Z, "A"): 2, (X, "B"): 2, (Y, "B"): 1, (Z, "B"): 0}
    obtido = {chave: distancia(saida, *chave) for chave in esperado}
    assert obtido == esperado
    assert mesma_rede(saida, X, Y) and mesma_rede(saida, Y, Z)
    assert (
        saida[REDE.nome].filter(variante="PRINCIPAL", cnpj_basico=X)["empresas_na_rede"].item() == 3
    )


def test_empresa_em_outro_componente_tem_distancia_infinita():
    w = "00000004"
    saida = rodar([*FIGURA_1, socio(w, pessoa(1)), socio(w, pessoa(2))], CONEXOES_FIGURA_1)
    assert distancia(saida, w) is None
    assert faixa(saida, w) == "inf"
    assert faixa(saida, Z) == "2"


def test_empresa_a_quatro_passos_fica_na_faixa_3_mais():
    cadeia = [f"{n:08d}" for n in range(11, 16)]
    socios = [socio(cnpj, pessoa(i)) for i, cnpj in enumerate(cadeia)]
    socios += [socio(cnpj, pessoa(i + 1)) for i, cnpj in enumerate(cadeia[:-1])]
    saida = rodar(socios, [conexao(cadeia[0], pessoa(0))])
    assert [distancia(saida, c) for c in cadeia] == [0, 1, 2, 3, None]
    assert [faixa(saida, c) for c in cadeia] == ["0", "1", "2", "3+", "3+"]


def test_socio_pj_cria_vizinhanca_e_some_sem_pj():
    holding, q, r = "00000020", "00000021", "00000022"
    socios = [
        socio(holding, pessoa(1)),
        socio(q, pessoa(2)),
        socio(q, holding, tipo="PJ"),
        socio(r, holding, tipo="PJ"),
    ]
    saida = rodar(socios, [conexao(q, pessoa(2))])
    assert distancia(saida, r) == 1
    assert faixa(saida, holding) == "inf"
    assert faixa(saida, r, variante="SEM_PJ") == "inf"


def test_administrador_nao_socio_cria_vizinhanca_e_some_sem_administrador():
    s, t = "00000030", "00000031"
    socios = [
        socio(s, pessoa(1)),
        socio(s, pessoa(2), vinculo="ADMINISTRADOR_NAO_SOCIO"),
        socio(t, pessoa(2), vinculo="ADMINISTRADOR_NAO_SOCIO"),
    ]
    saida = rodar(socios, [conexao(s, pessoa(1))])
    assert distancia(saida, t) == 1
    assert faixa(saida, t, variante="SEM_ADMINISTRADOR") == "inf"
    assert distancia(saida, t, variante="SEM_PJ") == 1


def test_pontos_de_articulacao_separam_a_figura_1():
    saida = rodar(FIGURA_1, CONEXOES_FIGURA_1)
    assert not mesma_rede(saida, X, Y, "SEM_ARTICULACAO")
    assert not mesma_rede(saida, Y, Z, "SEM_ARTICULACAO")
    assert faixa(saida, Y, variante="SEM_ARTICULACAO") == "inf"
    assert distancia(saida, X, variante="SEM_ARTICULACAO") == 0


def test_conexao_direta_por_socio_removido_nao_vale_na_variante():
    u, v = "00000040", "00000041"
    doador = pessoa(9)
    socios = [
        socio(u, doador, vinculo="ADMINISTRADOR_NAO_SOCIO"),
        socio(u, pessoa(1)),
        socio(v, pessoa(1)),
    ]
    saida = rodar(socios, [conexao(u, doador)])
    assert [distancia(saida, c) for c in (u, v)] == [0, 1]
    assert [faixa(saida, c, variante="SEM_ADMINISTRADOR") for c in (u, v)] == ["inf", "inf"]


def test_doador_ponto_de_articulacao_perde_a_conexao_direta():
    saida = rodar(FIGURA_1, [conexao(Y, BRUNO)])
    assert distancia(saida, Y) == 0
    assert faixa(saida, Y, variante="SEM_ARTICULACAO") == "inf"


def test_etapa_grava_tabelas_e_descritivas_sem_celulas_pequenas(caminhos_amostra):
    conexoes = [
        conexao(X, amostra.id_figura_1("Ana"), "A"),
        conexao(Z, amostra.id_figura_1("Daniel"), "B"),
    ]
    frame = pl.DataFrame(conexoes, schema=CONEXOES_DIRETAS.esquema, orient="row")
    schemas.gravar(frame, CONEXOES_DIRETAS, caminhos_amostra.dados)

    etapas.rodar("network", caminhos_amostra)

    distancias = schemas.ler(DISTANCIAS, caminhos_amostra.dados).collect()
    assert distancias.filter(variante="PRINCIPAL", cnpj_basico=Y)["distancia"].to_list() == [1, 1]
    colunas = {
        "rede_resumo": ("valor",),
        "rede_componentes": ("componentes", "empresas"),
        "rede_graus": ("vertices",),
        "rede_distancias": ("pares_empresa_municipio",),
    }
    assert set(colunas) == set(descritivas.ARQUIVOS)
    for arquivo, medidas in colunas.items():
        tabela = pl.read_csv(
            caminhos_amostra.resultados / "tables" / f"{arquivo}.csv",
            schema_overrides=dict.fromkeys(medidas, pl.Float64),
        )
        assert set(tabela["variante"]) == set(schemas.VARIANTE.categories), arquivo
        if arquivo == "rede_resumo":
            tabela = tabela.filter(
                ~pl.col("indicador").is_in(("fracao_no_maior_componente", "assortatividade_grau"))
            )
        contagens = tabela.select(*medidas).unpivot()["value"]
        assert not contagens.is_between(1, 4).any(), arquivo


@pytest.mark.parametrize("variante", schemas.VARIANTE.categories.to_list())
def test_rede_cobre_todas_as_empresas_em_cada_variante(variante):
    saida = rodar(FIGURA_1, CONEXOES_FIGURA_1)
    assert set(saida[REDE.nome].filter(variante=variante)["cnpj_basico"]) == {X, Y, Z}
