import shutil
import string
import zipfile
from datetime import date
from itertools import product
from pathlib import Path

import polars as pl
import pytest

from redes import schemas
from redes.config import Caminhos
from redes.etapas import Contexto
from redes.ingest import rfb
from redes.pseudonimo import carregar_chave, pseudonimo

CNPJ_A, CNPJ_B, CNPJ_C, CNPJ_D = "11111111", "22222222", "33333333", "44444444"


def _zip(caminho: Path, linhas: list[tuple[str | None, ...]], extracao: str = "D40914") -> Path:
    def campo(valor: str | None) -> str:
        return "" if valor is None else '"' + valor.replace('"', '""') + '"'

    texto = "".join(";".join(campo(v) for v in linha) + "\n" for linha in linhas)
    with zipfile.ZipFile(caminho, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"K3241.K03200Y1.{extracao}.CSV", texto.encode("latin-1"))
    return caminho


def _socio(cnpj: str, tipo: str, nome: str, doc: str | None, qual: str, data: str) -> tuple:
    return (cnpj, tipo, nome, doc, qual, data, None, "***000000**", "", "00", "5")


def _enchimento(n: int) -> list[tuple]:
    """Linhas válidas distintas, para que os casos-limite fiquem abaixo de `LIMITE_DESCARTE`."""
    nomes = ("PESSOA " + "".join(p) for p in product(string.ascii_uppercase, repeat=3))
    return [
        _socio(f"9{i:07d}", "2", nome, "***999999**", "22", "20200101")
        for i, nome in zip(range(n), nomes, strict=False)
    ]


SOCIOS_CASOS = [
    _socio(CNPJ_A, "2", "  José   da Silva-Ávila ", "***123456**", "49", "20100102"),
    _socio(CNPJ_A, "1", "EMPRESA SOCIA LTDA", "33333333000144", "22", "20150301"),
    _socio(CNPJ_A, "3", "John O'Neil", None, "37", "20200115"),
    _socio(CNPJ_A, "2", "MARIA ADMINISTRADORA", "***654321**", "05", "20240913"),
    _socio(CNPJ_B, "2", "JOSE DA SILVA AVILA", "***123456**", "22", "20241399"),
    _socio(CNPJ_B, "2", "JOSE DA SILVA AVILA", "***123456**", "22", "20190101"),
    _socio(CNPJ_B, "2", "CPF RUIM", "12345678901", "22", "20200101"),
    _socio(CNPJ_B, "2", "  ... ", "***111111**", "22", "20200101"),
    _socio(CNPJ_B, "2", "SEM DATA", "***222222**", "22", "00000000"),
]

EMPRESAS_CASOS = [
    (CNPJ_A, "RAZAO COM ASPAS", "2062", "49", "1000,50", "01", ""),
    (CNPJ_B, "OUTRA", "2135", "50", "0,00", None, None),
]


def _qualificacoes(caminho: Path, alterar: dict[str, str] | None = None) -> Path:
    descricoes = {c: q.descricao for c, q in rfb.QUALIFICACOES.items()} | (alterar or {})
    return _zip(caminho, list(descricoes.items()))


def _caminhos(tmp_path: Path) -> Caminhos:
    return Caminhos(
        dados=tmp_path / "dados",
        resultados=tmp_path / "results",
        saida=tmp_path / "output",
        chave=tmp_path / "chave",
    )


def _ingerir(
    tmp_path: Path,
    socios: list[tuple],
    qualificacoes: Path | None = None,
    preenchimento: list[tuple] | None = None,
    empresas: list[tuple] = EMPRESAS_CASOS,
    reconstrucao: list[tuple] | None = None,
) -> Caminhos:
    caminhos = _caminhos(tmp_path)
    outubro = tmp_path / "outubro"
    outubro.mkdir(parents=True)
    recente = tmp_path / "recente"
    recente.mkdir(parents=True)
    rfb.ingerir(
        Contexto(rfb.ETAPA, caminhos),
        rfb.Arquivos(
            socios=(_zip(tmp_path / "Socios1.zip", socios),),
            empresas=(_zip(tmp_path / "Empresas1.zip", empresas),),
            qualificacoes=qualificacoes or _qualificacoes(tmp_path / "Qualificacoes.zip"),
            preenchimento=(
                (_zip(outubro / "Socios1.zip", preenchimento, "D41012"),) if preenchimento else ()
            ),
            reconstrucao=(
                (_zip(recente / "Socios1.zip", reconstrucao, "D61010"),) if reconstrucao else ()
            ),
        ),
    )
    return caminhos


@pytest.fixture
def ingerido(tmp_path: Path) -> Caminhos:
    return _ingerir(tmp_path, SOCIOS_CASOS + _enchimento(400))


def _socios(caminhos: Caminhos) -> pl.DataFrame:
    frame = schemas.ler(schemas.SOCIOS, caminhos.dados)
    schemas.validar(frame, schemas.SOCIOS)
    return frame.filter(pl.col("cnpj_basico").is_in([CNPJ_A, CNPJ_B, CNPJ_C, CNPJ_D])).collect()


def _validacao(caminhos: Caminhos) -> dict[tuple[str, str], int | None]:
    tabela = pl.read_csv(caminhos.resultados / "tables" / "validacao_rfb.csv")
    return {(m, c): v for m, c, v in tabela.iter_rows()}


def test_pseudonimo_casa_com_o_do_tse(ingerido: Caminhos) -> None:
    chave = carregar_chave(ingerido.chave)
    doador_tse = pseudonimo("JOSE DA SILVA AVILA", "000.123.456-78", chave)
    linhas = _socios(ingerido).filter(pl.col("id_socio") == doador_tse)
    assert sorted(linhas["cnpj_basico"]) == [CNPJ_A, CNPJ_B]


def test_tipos_vinculos_e_datas(ingerido: Caminhos) -> None:
    socios = _socios(ingerido).filter(pl.col("cnpj_basico") == CNPJ_A).sort("cod_qualificacao")
    assert socios.select("tipo_socio", "vinculo", "cod_qualificacao", "data_entrada").rows() == [
        ("PF", "ADMINISTRADOR_NAO_SOCIO", "05", date(2024, 9, 13)),
        ("PJ", "SOCIO", "22", date(2015, 3, 1)),
        ("ESTRANGEIRO", "SOCIO", "37", date(2020, 1, 15)),
        ("PF", "SOCIO", "49", date(2010, 1, 2)),
    ]
    assert socios.filter(pl.col("tipo_socio") == "PJ")["id_socio"].item() == "33333333"
    assert (
        socios.filter(pl.col("tipo_socio") == "ESTRANGEIRO")["id_socio"]
        .str.contains(r"^[0-9a-f]{16}$")
        .all()
    )


def test_data_invalida_vira_nula_e_repeticao_guarda_a_mais_antiga(ingerido: Caminhos) -> None:
    socios = _socios(ingerido).filter(pl.col("cnpj_basico") == CNPJ_B)
    assert socios.height == 2
    assert sorted(socios["data_entrada"].to_list(), key=str) == [date(2019, 1, 1), None]


def test_descartes_contados_por_motivo(ingerido: Caminhos) -> None:
    validacao = _validacao(ingerido)
    assert validacao[("socios_descarte", "CPF_FORA_DO_FORMATO")] is None
    assert validacao[("socios_descarte", "NOME_VAZIO")] is None
    assert validacao[("socios_descarte", "DUPLICADA")] is None
    assert validacao[("socios_data_invalida_anulada", "Socios1.zip")] is None
    assert validacao[("socios_linhas_lidas", "Socios1.zip")] == len(SOCIOS_CASOS) + 400
    assert validacao[("socios_linhas_gravadas", "total")] == len(SOCIOS_CASOS) + 400 - 3


def test_nome_e_cpf_nao_chegam_ao_parquet(ingerido: Caminhos) -> None:
    conteudo = (ingerido.dados / "socios.parquet").read_bytes()
    for trecho in (b"SILVA", b"Silva", b"ADMINISTRADORA", b"Neil", b"***"):
        assert trecho not in conteudo


def test_empresas(ingerido: Caminhos) -> None:
    empresas = schemas.ler(schemas.EMPRESAS, ingerido.dados).collect()
    assert empresas.sort("cnpj_basico").rows() == [
        (CNPJ_A, "2062", "01", 1000.5),
        (CNPJ_B, "2135", None, 0.0),
    ]


def test_qualificacoes_e_ambiguidade(ingerido: Caminhos) -> None:
    tabelas = ingerido.resultados / "tables"
    qualificacoes = pl.read_csv(
        tabelas / "qualificacoes_rfb.csv", schema_overrides={"cod_qualificacao": pl.String}
    )
    assert qualificacoes.height == len(rfb.QUALIFICACOES)
    assert qualificacoes.filter(pl.col("cod_qualificacao") == "05")["linhas"].item() is None
    ambiguidade = pl.read_csv(tabelas / "ambiguidade_rfb.csv")
    pf = ambiguidade.filter(pl.col("tipo_socio") == "PF")
    assert pf.filter(pl.col("faixa_empresas") == "2-2")["pessoas"].item() is None
    assert ambiguidade.filter(pl.col("tipo_socio") == "ESTRANGEIRO")["pessoas"].item() is None
    validacao = _validacao(ingerido)
    chave = "socios_estrangeiro_em_mais_de_uma_empresa"
    assert validacao[(chave, "pseudonimos")] == 0
    assert (chave, "maximo_empresas") not in validacao


def test_qualificacoes_ocultam_complemento_mesmo_com_duas_contagens_raras() -> None:
    qualificacoes = pl.DataFrame({"vinculo": ["SOCIO"] * 5, "linhas": [80, 11, 1, 2, 0]})
    publicadas = rfb.qualificacoes_publicas(qualificacoes)["linhas"]
    assert publicadas.to_list() == [80, None, None, None, 0]
    assert qualificacoes["linhas"].sum() - publicadas.sum() > 4


def test_data_posterior_a_extracao_vira_nula_e_e_contada(tmp_path: Path) -> None:
    futura = _socio(CNPJ_A, "2", "FULANO", "***123456**", "22", "20240915")
    caminhos = _ingerir(tmp_path, [futura, *_enchimento(10)])
    socios = _socios(caminhos)
    assert socios["data_entrada"].to_list() == [None]
    assert _validacao(caminhos)[("socios_data_posterior_anulada", "Socios1.zip")] is None


def test_csv_de_outra_extracao_falha(tmp_path: Path) -> None:
    outra = tmp_path / "Socios1.zip"
    with zipfile.ZipFile(outra, "w") as z:
        z.writestr("K3241.K03200Y0.D41012.SOCIOCSV", b"")
    with pytest.raises(rfb.DadoInesperado, match="extração"):
        rfb.ingerir(
            Contexto(rfb.ETAPA, _caminhos(tmp_path)),
            rfb.Arquivos(
                (outra,),
                (_zip(tmp_path / "Empresas1.zip", EMPRESAS_CASOS),),
                _qualificacoes(tmp_path / "Qualificacoes.zip"),
            ),
        )


def test_qualificacao_desconhecida_falha(tmp_path: Path) -> None:
    estranha = _socio(CNPJ_A, "2", "FULANO", "***123456**", "99", "20200101")
    with pytest.raises(rfb.DadoInesperado, match="qualificações desconhecidas"):
        _ingerir(tmp_path, [estranha, *_enchimento(10)])


def test_tabela_de_qualificacoes_divergente_falha(tmp_path: Path) -> None:
    alterada = _qualificacoes(tmp_path / "Qualificacoes.zip", {"05": "Outra coisa"})
    with pytest.raises(rfb.DadoInesperado, match="diverge"):
        _ingerir(tmp_path, _enchimento(10), qualificacoes=alterada)


def test_muitos_descartes_falham(tmp_path: Path) -> None:
    ruim = _socio(CNPJ_A, "2", "FULANO", "123", "22", "20200101")
    with pytest.raises(rfb.DadoInesperado, match="layout mudou"):
        _ingerir(tmp_path, [ruim, *_enchimento(10)])


@pytest.mark.parametrize("bloco", [rfb.BLOCO_CSV, 1 << 12], ids=["na_abertura", "no_fluxo"])
def test_erro_de_leitura_nao_vaza_a_linha(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bloco: int
) -> None:
    monkeypatch.setattr(rfb, "BLOCO_CSV", bloco)
    caminhos = _caminhos(tmp_path)
    campo_a_mais = (*_socio(CNPJ_A, "2", "NOME SECRETO", "***123456**", "22", "20200101"), "X")
    quebrado = tmp_path / "Socios1.zip"
    with zipfile.ZipFile(quebrado, "w") as z:
        linhas = [*_enchimento(3000), campo_a_mais]
        z.writestr(
            "K3241.K03200Y0.D40914.SOCIOCSV",
            "".join(";".join(f'"{v or ""}"' for v in li) + "\n" for li in linhas),
        )
    with pytest.raises(rfb.DadoInesperado) as erro:
        rfb.ingerir(
            Contexto(rfb.ETAPA, caminhos),
            rfb.Arquivos(
                (quebrado,),
                (_zip(tmp_path / "Empresas1.zip", EMPRESAS_CASOS),),
                _qualificacoes(tmp_path / "Qualificacoes.zip"),
            ),
        )
    assert "SECRETO" not in str(erro.value)


def test_socios0_de_agosto_entra_e_fica_registrado(tmp_path: Path) -> None:
    caminhos = _caminhos(tmp_path)
    socios0 = tmp_path / "Socios0.zip"
    with zipfile.ZipFile(socios0, "w") as z:
        linhas = _enchimento(20)
        z.writestr(
            "K3241.K03200Y0.D40810.SOCIOCSV",
            "".join(";".join(f'"{v or ""}"' for v in li) + "\n" for li in linhas),
        )
    rfb.ingerir(
        Contexto(rfb.ETAPA, caminhos),
        rfb.Arquivos(
            (socios0, _zip(tmp_path / "Socios1.zip", _enchimento(20))),
            (_zip(tmp_path / "Empresas1.zip", EMPRESAS_CASOS),),
            _qualificacoes(tmp_path / "Qualificacoes.zip"),
        ),
    )
    validacao = _validacao(caminhos)
    assert validacao[("arquivo_de_outra_extracao", "Socios0.zip")] == 20240810
    assert validacao[("socios_descarte", "DUPLICADA")] == 20


PREENCHIMENTO_CASOS = [
    _socio(CNPJ_A, "2", "OUTRA PESSOA", "***777777**", "22", "20200101"),
    _socio(CNPJ_C, "2", "José da Silva Ávila", "***123456**", "49", "20240913"),
    _socio(CNPJ_C, "1", "EMPRESA SOCIA LTDA", "33333333000144", "22", "20100101"),
    _socio(CNPJ_C, "2", "ENTROU DEPOIS", "***888888**", "22", "20240914"),
    _socio(CNPJ_C, "2", "SEM DATA", "***999999**", "22", None),
    _socio(CNPJ_D, "2", "FORA DO CADASTRO", "***555555**", "22", "20200101"),
]


def test_empresa_sem_socio_em_setembro_recebe_os_de_outubro_que_entraram_antes(
    tmp_path: Path,
) -> None:
    antes = _ingerir(tmp_path / "antes", SOCIOS_CASOS + _enchimento(400))
    sem_preenchimento = _socios(antes)
    (tmp_path / "depois").mkdir()
    shutil.copy(antes.chave, tmp_path / "depois" / "chave")
    caminhos = _ingerir(
        tmp_path / "depois",
        SOCIOS_CASOS + _enchimento(400),
        preenchimento=PREENCHIMENTO_CASOS,
        empresas=[*EMPRESAS_CASOS, (CNPJ_C, "TERCEIRA", "2062", "49", "10,00", "01", "")],
    )
    socios = _socios(caminhos)

    assert socios.filter(pl.col("origem") == "2024-09").equals(sem_preenchimento)
    preenchidos = socios.filter(pl.col("origem") == "2024-10").sort("cod_qualificacao")
    assert preenchidos.select("cnpj_basico", "tipo_socio", "data_entrada").rows() == [
        (CNPJ_C, "PJ", date(2010, 1, 1)),
        (CNPJ_C, "PF", date(2024, 9, 13)),
    ]
    pessoa_de_a = socios.filter(
        (pl.col("cnpj_basico") == CNPJ_A) & (pl.col("cod_qualificacao") == "49")
    )["id_socio"]
    assert preenchidos.filter(pl.col("tipo_socio") == "PF")["id_socio"].equals(pessoa_de_a)

    validacao = _validacao(caminhos)
    assert validacao[("preenchimento_empresas", "preenchidas")] is None
    assert validacao[("preenchimento_empresas", "fora_do_cadastro_de_2024_09")] is None
    assert validacao[("preenchimento_vinculos", "entrada_a_partir_da_extracao_de_2024_09")] is None
    assert validacao[("preenchimento_vinculos", "sem_data_de_entrada")] is None
    assert validacao[("preenchimento_linhas_lidas", "Socios1.zip")] == len(PREENCHIMENTO_CASOS)
    assert validacao[("socios_empresas_por_origem", "2024-10")] is None
    assert validacao[("socios_linhas_por_origem", "2024-10")] is None


RECONSTRUCAO_CASOS = [
    _socio(CNPJ_A, "2", "José da Silva-Ávila", "***123456**", "49", "20100102"),
    _socio(CNPJ_A, "2", "OUTRO SOCIO ANTIGO", "***123456**", "22", "20200101"),
    _socio(CNPJ_B, "2", "ENTROU DEPOIS DE SETEMBRO", "***222222**", "22", "20240914"),
]


def test_erro_de_reconstrucao_compara_setembro_com_a_fotografia_mais_recente(
    tmp_path: Path,
) -> None:
    caminhos = _ingerir(tmp_path, SOCIOS_CASOS + _enchimento(400), reconstrucao=RECONSTRUCAO_CASOS)
    tabela = pl.read_csv(caminhos.resultados / "tables" / "reconstrucao.csv")
    assert tabela.height == 14
    assert tabela["valor"].null_count() == 14  # uma interseção de tamanho um


def test_sem_fotografia_recente_nao_ha_estimativa_de_reconstrucao(tmp_path: Path) -> None:
    caminhos = _ingerir(tmp_path, SOCIOS_CASOS + _enchimento(400))
    tabela = dict(pl.read_csv(caminhos.resultados / "tables" / "reconstrucao.csv").rows())
    assert tabela == {}
