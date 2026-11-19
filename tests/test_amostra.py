import polars as pl

from redes import amostra, config
from redes.amostra import EMPRESAS_FIGURA_1, MUNICIPIO_FIGURA_1, id_figura_1


def test_geracao_deterministica(tabelas_amostra):
    novas = amostra.gerar()
    assert all(novas[nome].equals(df) for nome, df in tabelas_amostra.items())


def test_sociedades_da_figura_1(tabelas_amostra):
    figura = set(EMPRESAS_FIGURA_1.values())
    socios = tabelas_amostra["socios"].filter(pl.col("cnpj_basico").is_in(figura))
    pares = set(socios.select("id_socio", "cnpj_basico").iter_rows())
    esperado = {(id_figura_1(p), EMPRESAS_FIGURA_1[e]) for p, e in amostra.SOCIEDADES_FIGURA_1}
    assert pares == esperado


def test_doacoes_da_figura_1(tabelas_amostra):
    candidatos = tabelas_amostra["candidatos"].filter(
        (pl.col("ano") == 2024) & (pl.col("cod_municipio_tse") == MUNICIPIO_FIGURA_1)
    )
    sq_a, sq_b = candidatos["sq_candidato"].sort().head(2).to_list()
    doacoes = tabelas_amostra["doacoes"].filter(pl.col("data_receita") <= config.DATA_LIMITE_DOACAO)

    def doou(rotulo: str, sq: str) -> bool:
        return (
            doacoes.filter(
                (pl.col("id_doador") == id_figura_1(rotulo)) & (pl.col("sq_candidato") == sq)
            ).height
            > 0
        )

    assert doou("Ana", sq_a) and doou("Daniel", sq_b)
    assert not any(doou(p, sq) for p in ("Bruno", "Carla") for sq in (sq_a, sq_b))
    homonima = amostra.id_pessoa(*amostra.HOMONIMA_DE_ANA)
    assert homonima != id_figura_1("Ana")
    assert doacoes.filter(pl.col("id_doador") == homonima)["sq_candidato"].to_list() == [sq_b]


def test_margens_dos_dois_lados_do_corte(tabelas_amostra):
    votos = tabelas_amostra["votos"].filter(pl.col("turno") == 1)
    lados = (
        votos.sort("sq_candidato")
        .group_by("cod_municipio_tse")
        .agg(pl.col("votos").first().alias("a"), pl.col("votos").slice(1, 1).first().alias("b"))
        .drop_nulls()
        .select((pl.col("a") > pl.col("b")).alias("incumbente_vence"))["incumbente_vence"]
    )
    assert lados.sum() >= 20 and (~lados).sum() >= 20


def test_empenhos_cobrem_anos_e_mercados(tabelas_amostra):
    empenhos = tabelas_amostra["empenhos"]
    assert set(empenhos["data"].dt.year().unique()) == set(config.ANOS_EMPENHO)
    assert empenhos["elemento_despesa"].n_unique() == len(amostra.ELEMENTOS)
    assert set(empenhos["evento"].unique()) == {"EMISSAO", "REFORCO", "ANULACAO"}


def test_nenhum_identificador_em_claro(tabelas_amostra):
    for df in tabelas_amostra.values():
        for coluna in df.select(pl.col(pl.String)).columns:
            assert not df[coluna].str.contains(r"Exemplo|Sintetica|^999\d{8}$|\*\*\*").any(), coluna
