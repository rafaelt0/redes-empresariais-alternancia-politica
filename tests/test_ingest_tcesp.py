import zipfile
from datetime import date
from os import utime
from pathlib import Path

import polars as pl
import pytest

from redes.config import Caminhos
from redes.ingest import tcesp

PREFEITURA = "PREFEITURA MUNICIPAL DE EXEMPLÓPOLIS"
CAMARA = "CÂMARA MUNICIPAL DE EXEMPLÓPOLIS"
IBGE = "3599999"
CNPJ_A = "11222333000181"
CNPJ_B = "45997418000153"
CNPJ_DV_ERRADO = "11222333000182"


def test_validacao_suprime_valores_monetarios_e_impede_subtracao_do_total():
    linhas = [
        ("eventos_por_elemento_despesa", 2025, "pequeno", 1),
        ("eventos_por_elemento_despesa", 2025, "segundo", 10),
        ("eventos_por_elemento_despesa", 2025, "maior", 20),
        ("valor_por_elemento_despesa", 2025, "pequeno", 44),
        ("valor_por_elemento_despesa", 2025, "segundo", 123),
        ("valor_por_elemento_despesa", 2025, "maior", 567),
        ("descarte", 2025, "descarte isolado", 2),
        ("descarte_valor", 2025, "descarte isolado", 490),
        ("ajustes_municipio_sem_correspondencia", None, "nome a omitir", 1),
    ]
    tabela = pl.DataFrame(linhas, schema=tcesp.ESQUEMA_CONTAGENS, orient="row")
    publica = tcesp.validacao_publica(tabela)
    valores = {(m, c): v for m, _, c, v in publica.iter_rows()}
    assert valores["valor_por_elemento_despesa", "pequeno"] is None
    assert valores["valor_por_elemento_despesa", "segundo"] is None
    assert valores["valor_por_elemento_despesa", "maior"] == 567
    assert valores["descarte_valor", "descarte isolado"] is None
    assert valores["ajustes_municipio_sem_correspondencia", "total"] is None
    assert "nome a omitir" not in publica["categoria"].to_list()


@pytest.mark.parametrize("novos, publicar", [(17, False), (15, True), (0, True)])
def test_validacao_suprime_a_taxa_e_o_valor_quando_o_complemento_revela_poucos_novos(
    novos, publicar
):
    linhas = [
        ("empenhos", 2025, "total", 100.0),
        ("vinculacao_empenhos", 2025, "ligados", 0.2),
        ("vinculacao_empenhos", 2025, "novos", novos / 100),
        ("vinculacao_valor", 2025, "ligados", 0.35),
        ("vinculacao_valor", 2025, "novos", 0.34 if novos else 0.0),
    ]
    tabela = pl.DataFrame(linhas, schema=tcesp.ESQUEMA_CONTAGENS, orient="row")
    publica = tcesp.validacao_publica(tabela)
    assert publica.filter(categoria="ligados")["valor"].to_list() == [0.2, 0.35]
    assert publica.filter(categoria="novos")["valor"].is_not_null().all() == publicar


def test_modo_estrito_refaz_parcial_mais_recente_que_o_zip(tmp_path, monkeypatch):
    caminhos = Caminhos(tmp_path, tmp_path / "results", tmp_path / "output", tmp_path / "chave")
    fonte = tmp_path / "fonte.zip"
    fonte.touch()
    utime(fonte, (1, 1))
    pasta = tmp_path / "tcesp"
    acoes = []

    def processar(zip_, ano, destino):
        acoes.append((zip_, ano))
        destino.touch()
        return [tcesp.Contagem("eventos", ano, "emissao", len(acoes))]

    monkeypatch.setattr(tcesp.fetch, "garantir", lambda *_: fonte)
    monkeypatch.setattr(tcesp, "processar_despesas", processar)
    monkeypatch.delenv("REDES_APAGAR_BRUTOS", raising=False)
    monkeypatch.delenv("REDES_ESTRITO", raising=False)
    assert tcesp.parcial_do_ano(2025, caminhos, pasta)[0].valor == 1
    assert tcesp.parcial_do_ano(2025, caminhos, pasta)[0].valor == 1
    monkeypatch.setenv("REDES_ESTRITO", "1")
    assert tcesp.parcial_do_ano(2025, caminhos, pasta)[0].valor == 2


def test_parcial_refaz_contagens_apos_interrupcao_entre_parquet_e_csv(tmp_path, monkeypatch):
    caminhos = Caminhos(tmp_path, tmp_path / "results", tmp_path / "output", tmp_path / "chave")
    fonte = tmp_path / "fonte.zip"
    fonte.touch()
    utime(fonte, (2, 2))
    pasta = tmp_path / "tcesp"
    pasta.mkdir()
    destino = tcesp._parcial(pasta, 2025)
    destino.touch()
    utime(destino, (1, 1))
    anterior = tcesp.Contagem("eventos", 2025, "emissao", 11)
    tcesp._contagens_para_frame([anterior]).write_csv(tcesp._contagens_parcial(pasta, 2025))
    acoes = []

    def processar(zip_, ano, parquet):
        acoes.append(ano)
        parquet.touch()
        return [tcesp.Contagem("eventos", ano, "emissao", 22)]

    def interromper(_):
        raise OSError("gravação interrompida")

    monkeypatch.setattr(tcesp.fetch, "garantir", lambda *_: fonte)
    monkeypatch.setattr(tcesp, "processar_despesas", processar)
    monkeypatch.delenv("REDES_APAGAR_BRUTOS", raising=False)
    monkeypatch.delenv("REDES_ESTRITO", raising=False)
    with monkeypatch.context() as falha:
        falha.setattr(tcesp, "_contagens_para_frame", interromper)
        with pytest.raises(OSError, match="gravação interrompida"):
            tcesp.parcial_do_ano(2025, caminhos, pasta)

    assert tcesp.parcial_do_ano(2025, caminhos, pasta)[0].valor == 22
    assert tcesp.parcial_do_ano(2025, caminhos, pasta)[0].valor == 22
    assert acoes == [2025, 2025]


def test_modo_estrito_refaz_ajustes_ainda_que_o_cache_confira(tmp_path, monkeypatch):
    caminhos = Caminhos(tmp_path, tmp_path / "results", tmp_path / "output", tmp_path / "chave")
    pasta = tmp_path / "tcesp"
    pasta.mkdir()
    tse = pasta / "tse.zip"
    tse.touch()
    for ano in tcesp.config.ANOS_EMPENHO:
        tcesp._parcial(pasta, ano).touch()
    acoes = []

    def montar(*_):
        acoes.append(True)
        return (
            pl.DataFrame({"id": [1]}),
            pl.DataFrame(schema=tcesp.LICITACOES.esquema),
            [tcesp.Contagem("ajustes", 2025, "total", len(acoes))],
        )

    monkeypatch.setattr(tcesp, "arquivos_de_ajustes", list)
    monkeypatch.setattr(tcesp, "montar_ajustes", montar)
    monkeypatch.delenv("REDES_ESTRITO", raising=False)
    argumentos = (caminhos, pasta, pl.LazyFrame(), pl.DataFrame(), tse)
    assert tcesp.ajustes_em_cache(*argumentos)[2][0].valor == 1
    assert tcesp.ajustes_em_cache(*argumentos)[2][0].valor == 1
    monkeypatch.setenv("REDES_ESTRITO", "1")
    assert tcesp.ajustes_em_cache(*argumentos)[2][0].valor == 2
    (assinatura,) = pasta.glob("ajustes-fontes.*.json")
    assinatura.write_text("{")
    assert tcesp.ajustes_em_cache(*argumentos)[2][0].valor == 3


def _linha(
    id_: int,
    tp: str,
    nr: str,
    data: str,
    valor: str,
    doc: str = CNPJ_A,
    tipo_doc: str = tcesp.CREDOR_PJ,
    orgao: str = PREFEITURA,
    elemento: str = "33903999 - OUTROS SERVIÇOS DE TERCEIROS - PESSOA JURÍDICA",
    ano: int = 2025,
) -> str:
    campos = dict.fromkeys(tcesp.CABECALHO_DESPESAS, "x")
    campos |= {
        "id_despesa_detalhe": str(id_),
        "ano_exercicio": str(ano),
        "ds_municipio": "Exemplópolis",
        "codigo_municipio_ibge": IBGE,
        "ds_orgao": orgao,
        "tp_despesa": tp,
        "nr_empenho": f" {nr}",
        "tp_identificador_despesa": tipo_doc,
        "nr_identificador_despesa": doc,
        "dt_emissao_despesa": data,
        "vl_despesa": valor,
        "ds_elemento": elemento,
        "historico_despesa": "texto livre; com ponto e vírgula",
    }
    return ";".join(campos[c] for c in tcesp.CABECALHO_DESPESAS)


def _zip(pasta: Path, ano: int, linhas: list[str], cabecalho=tcesp.CABECALHO_DESPESAS) -> Path:
    caminho = pasta / f"despesas-{ano}.zip"
    texto = "\r\n".join([";".join(cabecalho), *linhas]) + "\r\n"
    with zipfile.ZipFile(caminho, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"despesas-{ano}.csv", texto.encode("latin-1"))
    return caminho


def _processar(tmp_path: Path, ano: int, linhas: list[str]) -> tuple[pl.DataFrame, dict]:
    destino = tmp_path / f"empenhos-{ano}.parquet"
    contagens = tcesp.processar_despesas(_zip(tmp_path, ano, linhas), ano, destino)
    return pl.read_parquet(destino), {(c.medida, c.categoria): c.valor for c in contagens}


def test_anulacao_maior_que_emissao_deixa_liquido_negativo(tmp_path):
    eventos, _ = _processar(
        tmp_path,
        2025,
        [
            _linha(1, "Empenhado", "10-2025", "02/01/2025", "1000,00"),
            _linha(2, "Anulação", "10-2025", "10/02/2025", "1500,50"),
        ],
    )
    assert eventos.sort("id_evento")["valor"].to_list() == [1000.0, -1500.5]
    assert eventos["valor"].sum() == pytest.approx(-500.5)
    assert eventos["id_empenho"].n_unique() == 1


def test_reforco_em_ano_posterior_soma_ao_empenho_original(tmp_path):
    em_2024, _ = _processar(
        tmp_path, 2024, [_linha(1, "Empenhado", "5-2024", "10/12/2024", "100,00", ano=2024)]
    )
    em_2025, _ = _processar(tmp_path, 2025, [_linha(2, "Reforço", "5-2024", "15/01/2025", "40,00")])
    juntos = pl.concat([em_2024, em_2025])
    assert juntos["id_empenho"].n_unique() == 1
    assert em_2025["data"].item() == date(2025, 1, 15)
    assert em_2025["evento"].item() == "REFORCO"
    assert juntos["valor"].sum() == pytest.approx(140.0)


def test_descarta_pessoa_fisica_cnpj_invalido_e_fases_fora_do_escopo(tmp_path):
    eventos, contagens = _processar(
        tmp_path,
        2025,
        [
            _linha(1, "Empenhado", "1-2025", "02/01/2025", "10,00"),
            _linha(2, "Empenhado", "2-2025", "02/01/2025", "20,00", "123456", tcesp.CREDOR_PF),
            _linha(3, "Empenhado", "3-2025", "02/01/2025", "30,00", CNPJ_DV_ERRADO),
            _linha(4, "Empenhado", "4-2025", "02/01/2025", "40,00", "1122233300018"),
            _linha(5, "Valor Liquidado", "1-2025", "03/01/2025", "10,00"),
            _linha(6, "Valor Pago", "1-2025", "04/01/2025", "10,00"),
            _linha(7, "Empenhado", "7-2025", "31/12/2024", "70,00"),
        ],
    )
    assert eventos["id_evento"].to_list() == ["1"]
    assert contagens[("descarte", "EMISSAO|credor_pessoa_fisica")] == 1
    assert contagens[("descarte", "EMISSAO|cnpj_invalido")] == 2
    assert contagens[("descarte", "EMISSAO|data_fora_do_ano")] == 1
    assert contagens[("descarte_valor", "EMISSAO|cnpj_invalido")] == pytest.approx(70.0)
    assert contagens[("linhas_lidas", "Valor Pago")] == 1


def test_valor_com_virgula_elemento_e_cnpj_basico(tmp_path):
    eventos, _ = _processar(
        tmp_path,
        2025,
        [
            _linha(
                1,
                "Empenhado",
                "0042-2025",
                "02/01/2025",
                "1234567,89",
                elemento="44905191 - OBRAS EM ANDAMENTO",
            )
        ],
    )
    linha = eventos.row(0, named=True)
    assert linha["valor"] == pytest.approx(1234567.89)
    assert linha["natureza_despesa"] == "44905191"
    assert linha["elemento_despesa"] == "51"
    assert linha["cnpj_basico"] == "11222333"
    assert linha["id_empenho"].endswith("-42-2025")


def test_numeracao_recomeca_por_orgao(tmp_path):
    eventos, _ = _processar(
        tmp_path,
        2025,
        [
            _linha(1, "Empenhado", "1-2025", "02/01/2025", "10,00"),
            _linha(2, "Empenhado", "1-2025", "02/01/2025", "20,00", orgao=CAMARA),
        ],
    )
    assert eventos["id_empenho"].n_unique() == 2


def test_blocos_pequenos_leem_as_mesmas_linhas(tmp_path):
    linhas = [_linha(i, "Empenhado", f"{i}-2025", "02/01/2025", "1,00") for i in range(1, 50)]
    zip_ = _zip(tmp_path, 2025, linhas)
    lidas = pl.concat(tcesp.ler_blocos(zip_, tamanho=300))
    assert lidas["id_despesa_detalhe"].to_list() == [str(i) for i in range(1, 50)]


def test_cabecalho_diferente_falha(tmp_path):
    zip_ = _zip(tmp_path, 2025, [], cabecalho=("id", *tcesp.CABECALHO_DESPESAS[1:]))
    with pytest.raises(tcesp.DadoInesperado):
        list(tcesp.ler_blocos(zip_))


def _ajuste(nota: str | None, data: str, cnpj: str, codigo: str = "2025000000007", **extra) -> dict:
    return {
        "municipio": "Exemplópolis",
        "orgao": PREFEITURA,
        "codigo_ajuste": codigo,
        "instrumento": "Nota de Empenho" if nota else "Contrato",
        "nota": nota,
        "data_nota": data if nota else None,
        "valor_nota": "10,0",
        "cnpj": cnpj,
        "valor_contrato": None,
        "data_assinatura": None if nota else data,
        "data_inicio": None,
        **extra,
    }


def test_liga_empenho_a_nota_do_ajuste_pelo_numero_ano_orgao_e_cnpj(tmp_path):
    eventos, _ = _processar(
        tmp_path,
        2025,
        [
            _linha(1, "Empenhado", "33-2025", "20/02/2025", "10,00"),
            _linha(2, "Empenhado", "34-2025", "20/02/2025", "10,00"),
            _linha(3, "Empenhado", "35-2025", "20/02/2025", "10,00"),
            _linha(4, "Empenhado", "33-2025", "20/02/2025", "10,00", orgao=CAMARA),
        ],
    )
    parciais = eventos.lazy()
    municipios = pl.DataFrame(
        {
            "cod_municipio_tse": ["99999"],
            "id_municipio_tcesp": ["Exemplópolis"],
            "cod_ibge": [IBGE],
            "nome": ["Exemplópolis"],
        }
    )
    ajustes = pl.DataFrame(
        [
            _ajuste("33", "20/02/2025", "11.222.333/0001-81"),
            _ajuste("34", "20/02/2025", "45.997.418/0001-53", codigo="2025000000008"),
            _ajuste("0035", "20/02/2024", "11.222.333/0001-81", codigo="2025000000009"),
            _ajuste(None, "01/03/2025", "11.222.333/0001-81", codigo="2025000000010"),
        ],
        schema=dict.fromkeys(tcesp.COLUNAS_AJUSTES.values(), pl.String),
    )
    notas, licitacoes, _ = tcesp.montar_ajustes([ajustes], parciais, municipios)
    empenhos = tcesp.montar_empenhos(parciais, municipios, notas).collect()

    ligados = dict(empenhos.select("id_evento", "id_ajuste").iter_rows())
    assert ligados["1"] is not None and ligados["1"].endswith("-2025000000007")
    assert ligados["2"] is None, "CNPJ do ajuste difere do credor"
    assert ligados["3"] is None, "nota de outro ano"
    assert ligados["4"] is None, "mesmo número em outro órgão"
    assert licitacoes.height == 4
    contrato = licitacoes.filter(pl.col("tipo") == "Contrato").row(0, named=True)
    assert contrato["data"] == date(2025, 3, 1)
    assert set(empenhos["tipo_orgao"].to_list()) == {"PREFEITURA", "CAMARA"}


@pytest.mark.parametrize(
    ("orgao", "tipo"),
    [
        (PREFEITURA, "PREFEITURA"),
        (CAMARA, "CAMARA"),
        ("I.P.M.T. - INSTITUTO DE PREV. DO MUNICIPIO DE TAUBATÉ", "PREVIDENCIA"),
        ("FUNDO MUNICIPAL DE SEGURIDADE SOCIAL - PARISI", "PREVIDENCIA"),
        ("SAAE - SERVIÇO AUTÔNOMO DE ÁGUA E ESGOTO", "AUTARQUIA_OU_OUTRA"),
    ],
)
def test_tipo_de_orgao(orgao, tipo):
    assert tcesp.tipo_de_orgao(orgao) == tipo
