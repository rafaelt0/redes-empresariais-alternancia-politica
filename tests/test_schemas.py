from datetime import date
from pathlib import Path

import polars as pl
import pytest

from redes import dicionario, schemas
from redes.schemas import EMPENHOS, EXCLUSOES, EsquemaInvalido

RAIZ = Path(__file__).resolve().parents[1]


def test_amostra_obedece_aos_esquemas(tabelas_amostra):
    for nome, df in tabelas_amostra.items():
        schemas.validar(df, schemas.TABELAS[nome])


def _empenhos(tabelas_amostra) -> pl.DataFrame:
    return tabelas_amostra["empenhos"].head(5)


@pytest.mark.parametrize(
    ("estragar", "mensagem"),
    [
        (lambda df: df.drop("valor"), "falta coluna `valor`"),
        (lambda df: df.with_columns(pl.col("valor").cast(pl.Int64)), "`valor` é Int64"),
        (lambda df: pl.concat([df, df.head(1)]), "chave ('id_evento',) repetida"),
        (lambda df: df.with_columns(cnpj_basico=pl.lit(None, pl.String)), "nulos em `cnpj_basico`"),
        (
            lambda df: df.with_columns(evento=pl.lit("ANULACAO", schemas.EVENTO)),
            "sinal de `valor` segue o evento",
        ),
        (lambda df: df.with_columns(data=pl.lit(date(2026, 1, 5))), "`data` entre"),
    ],
)
def test_validar_rejeita_tabela_fora_do_contrato(tabelas_amostra, estragar, mensagem):
    with pytest.raises(
        EsquemaInvalido, match="empenhos: .*" + mensagem.replace("(", r"\(").replace(")", r"\)")
    ):
        schemas.validar(estragar(_empenhos(tabelas_amostra)), EMPENHOS)


def test_gravar_e_ler_preservam_o_esquema(tmp_path, tabelas_amostra):
    for nome, df in tabelas_amostra.items():
        tabela = schemas.TABELAS[nome]
        schemas.gravar(df, tabela, tmp_path)
        assert schemas.ler(tabela, tmp_path).collect().equals(df)

    exclusoes = pl.DataFrame(
        {"cod_municipio_tse": ["90058"], "motivo": ["SEGUNDO_TURNO"], "detalhe": [None]},
        schema=EXCLUSOES.esquema,
    )
    schemas.gravar(exclusoes, EXCLUSOES, tmp_path)
    assert schemas.ler(EXCLUSOES, tmp_path).collect().equals(exclusoes)


def test_gravar_recusa_tabela_invalida_sem_deixar_arquivo(tmp_path, tabelas_amostra):
    with pytest.raises(EsquemaInvalido):
        schemas.gravar(_empenhos(tabelas_amostra).drop("valor"), EMPENHOS, tmp_path)
    assert not (tmp_path / EMPENHOS.arquivo).exists()


def test_dicionario_esta_atualizado():
    assert (RAIZ / "docs" / "dicionario.md").read_text() == dicionario.gerar(), (
        "rode `make dicionario`"
    )


def test_validar_confere_chave_no_parquet_gravado(tmp_path, tabelas_amostra):
    df = _empenhos(tabelas_amostra)
    arquivo = tmp_path / EMPENHOS.arquivo
    df.write_parquet(arquivo)
    schemas.validar(pl.scan_parquet(arquivo), EMPENHOS, arquivo)

    pl.concat([df, df.head(1)]).write_parquet(arquivo)
    with pytest.raises(EsquemaInvalido, match=r"chave \('id_evento',\) repetida"):
        schemas.validar(pl.scan_parquet(arquivo), EMPENHOS, arquivo)
