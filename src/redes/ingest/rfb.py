"""Etapa `ingest-rfb`: sócios e empresas da fotografia 2024-09, pseudonimizados (T04).

Cada zip da Receita traz um CSV sem cabeçalho, separado por `;`, com aspas duplicadas como
escape e codificação latin-1. O membro é lido em fluxo pelo pyarrow e entregue ao DuckDB em
lotes; nada é extraído para o disco.

Pessoa física vira `pseudonimo(nome, CPF mascarado)`, o mesmo do TSE; o pseudônimo é calculado
numa função Python registrada no DuckDB, e nome e CPF não saem do temporário. Estrangeiro não tem
CPF na Receita: o pseudônimo é o HMAC do nome normalizado com o prefixo `ESTRANGEIRO|`, que não
colide com o de pessoa física (nome normalizado não tem dígitos). Sócio pessoa jurídica é
identificado pelo CNPJ básico.

Linhas descartadas são contadas por motivo em `validacao_rfb.csv`; a etapa falha se o CSV não é
da extração da sua `Fotografia` (o nome do membro traz a data, `D40914`), se aparece qualificação
fora de `QUALIFICACOES` ou se os descartes de leitura passam de `LIMITE_DESCARTE` das linhas
(sinal de que o layout mudou). Data de entrada inválida ou
posterior à extração vira nula e é contada: um registro de uma fotografia não pode ter entrado
depois dela, então a data está errada, não o vínculo (em 2024-09 há um caso).

Os arquivos de sócios são cortados por número de linhas (2.019.150 cada), não por CNPJ: uma
empresa pode ter linhas em dois arquivos, e a mesma linha em dois arquivos conta como `DUPLICADA`.

Preenchimento. A pasta 2024-09 traz o `Socios0` de agosto, e a empresa que
só o `Socios0` de setembro traria fica sem sócio. A empresa do cadastro de 2024-09 sem nenhum
sócio na fotografia recebe os sócios da fotografia de 2024-10 (`OUTUBRO`) com data de entrada
anterior à extração de 2024-09; `origem` diz de qual pasta veio cada vínculo.
"""

import hashlib
import hmac
import tempfile
import zipfile
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Literal

import duckdb
import polars as pl
import pyarrow as pa
import pyarrow.csv as pacsv

from redes import config, descritivas, fetch
from redes.etapas import Contexto, Etapa
from redes.fontes import ARQUIVOS, Arquivo
from redes.pseudonimo import TAMANHO_PSEUDONIMO, carregar_chave, normalizar_nome, pseudonimo
from redes.schemas import EMPRESAS, FOTOGRAFIA_RFB, SOCIOS, TIPO_SOCIO, VINCULO, Tabela

ETAPA = Etapa(
    nome="ingest-rfb",
    depende=(),
    le=(),
    grava=(SOCIOS, EMPRESAS),
    artefatos=(
        "resultados/tables/validacao_rfb.csv",
        "resultados/tables/qualificacoes_rfb.csv",
        "resultados/tables/ambiguidade_rfb.csv",
        "resultados/tables/reconstrucao.csv",
    ),
)

MEMORIA_DUCKDB = "1500MB"
THREADS_DUCKDB = 2
LIMITE_DESCARTE = 0.01
BLOCO_CSV = 8 << 20


def _marca(dia: date) -> str:
    """Data no nome do membro do zip, com um dígito de ano: `K3241.K03200Y1.D40914.SOCIOCSV`."""
    return f".D{dia.year % 10}{dia:%m%d}."


@dataclass(frozen=True)
class Fotografia:
    """Uma pasta mensal da Receita e a data da extração que o nome de cada membro deve trazer."""

    fonte: str
    extracao: date
    medida: str
    """Prefixo das contagens dos arquivos de sócios desta pasta em `validacao_rfb.csv`."""
    outra_extracao: Mapping[str, date] = field(default_factory=dict)
    """Arquivos da pasta que a Receita publicou de outra extração."""

    def extracao_do(self, zip_: Path) -> date:
        return self.outra_extracao.get(zip_.name, self.extracao)


SETEMBRO = Fotografia(
    "rfb-2024-09", config.DATA_EXTRACAO_RFB, "socios", {"Socios0.zip": date(2024, 8, 10)}
)
"""A fotografia do desenho. Conferido em 11/11/2026: `Socios0.zip` é a extração de 10/08/2024,
com 6.355.263 linhas, 4.622.904 delas idênticas a linhas de `Socios1` a `Socios9`. O `Socios0` de
setembro não está publicado na pasta."""
OUTUBRO = Fotografia("rfb-2024-10", date(2024, 10, 12), "preenchimento")

RECENTE = Fotografia("rfb-2026-10", date(2026, 10, 10), "reconstrucao")
"""Fotografia mais recente do compartilhamento, usada só no erro de reconstrução (T10).

O erro mede o que se perderia ao reconstruir a rede de 2024-09 pela fotografia atual: é o número
que a seção 5 do projeto manda reportar, não uma substituta da fotografia do desenho."""

Vinculo = Literal["SOCIO", "ADMINISTRADOR_NAO_SOCIO"]
_SOC: Vinculo = "SOCIO"
_ADM: Vinculo = "ADMINISTRADOR_NAO_SOCIO"


@dataclass(frozen=True)
class Qualificacao:
    descricao: str
    """Como em `Qualificacoes.zip`; a etapa falha se a tabela da Receita divergir."""
    vinculo: Vinculo
    duvidoso: bool = False


QUALIFICACOES: dict[str, Qualificacao] = {
    "00": Qualificacao("Não informada", _ADM, duvidoso=True),
    "05": Qualificacao("Administrador", _ADM),
    "08": Qualificacao("Conselheiro de Administração", _ADM),
    "09": Qualificacao("Curador", _ADM, duvidoso=True),
    "10": Qualificacao("Diretor", _ADM),
    "11": Qualificacao("Interventor", _ADM, duvidoso=True),
    "12": Qualificacao("Inventariante", _ADM, duvidoso=True),
    "13": Qualificacao("Liquidante", _ADM, duvidoso=True),
    "14": Qualificacao("Mãe", _ADM, duvidoso=True),
    "15": Qualificacao("Pai", _ADM, duvidoso=True),
    "16": Qualificacao("Presidente", _ADM),
    "17": Qualificacao("Procurador", _ADM, duvidoso=True),
    "18": Qualificacao("Secretário", _ADM),
    "19": Qualificacao("Síndico (Condomínio)", _ADM, duvidoso=True),
    "20": Qualificacao("Sociedade Consorciada", _SOC, duvidoso=True),
    "21": Qualificacao("Sociedade Filiada", _SOC, duvidoso=True),
    "22": Qualificacao("Sócio", _SOC),
    "23": Qualificacao("Sócio Capitalista", _SOC),
    "24": Qualificacao("Sócio Comanditado", _SOC),
    "25": Qualificacao("Sócio Comanditário", _SOC),
    "26": Qualificacao("Sócio de Indústria", _SOC),
    "28": Qualificacao("Sócio-Gerente", _SOC),
    "29": Qualificacao("Sócio Incapaz ou Relat.Incapaz (exceto menor)", _SOC),
    "30": Qualificacao("Sócio Menor (Assistido/Representado)", _SOC),
    "31": Qualificacao("Sócio Ostensivo", _SOC),
    "32": Qualificacao("Tabelião", _ADM, duvidoso=True),
    "33": Qualificacao("Tesoureiro", _ADM),
    "34": Qualificacao("Titular de Empresa Individual Imobiliária", _SOC),
    "35": Qualificacao("Tutor", _ADM, duvidoso=True),
    "37": Qualificacao("Sócio Pessoa Jurídica Domiciliado no Exterior", _SOC),
    "38": Qualificacao("Sócio Pessoa Física Residente no Exterior", _SOC),
    "39": Qualificacao("Diplomata", _ADM, duvidoso=True),
    "40": Qualificacao("Cônsul", _ADM, duvidoso=True),
    "41": Qualificacao("Representante de Organização Internacional", _ADM, duvidoso=True),
    "42": Qualificacao("Oficial de Registro", _ADM, duvidoso=True),
    "43": Qualificacao("Responsável", _ADM, duvidoso=True),
    "46": Qualificacao("Ministro de Estado das Relações Exteriores", _ADM, duvidoso=True),
    "47": Qualificacao("Sócio Pessoa Física Residente no Brasil", _SOC),
    "48": Qualificacao("Sócio Pessoa Jurídica Domiciliado no Brasil", _SOC),
    "49": Qualificacao("Sócio-Administrador", _SOC),
    "50": Qualificacao("Empresário", _SOC),
    "51": Qualificacao("Candidato a cargo Político Eletivo", _ADM, duvidoso=True),
    "52": Qualificacao("Sócio com Capital", _SOC),
    "53": Qualificacao("Sócio sem Capital", _SOC),
    "54": Qualificacao("Fundador", _SOC, duvidoso=True),
    "55": Qualificacao("Sócio Comanditado Residente no Exterior", _SOC),
    "56": Qualificacao("Sócio Comanditário Pessoa Física Residente no Exterior", _SOC),
    "57": Qualificacao("Sócio Comanditário Pessoa Jurídica Domiciliado no Exterior", _SOC),
    "58": Qualificacao("Sócio Comanditário Incapaz", _SOC),
    "59": Qualificacao("Produtor Rural", _SOC, duvidoso=True),
    "60": Qualificacao("Cônsul Honorário", _ADM, duvidoso=True),
    "61": Qualificacao("Responsável indígena", _ADM, duvidoso=True),
    "62": Qualificacao("Representante da Instituição Extraterritorial", _ADM, duvidoso=True),
    "63": Qualificacao("Cotas em Tesouraria", _SOC, duvidoso=True),
    "64": Qualificacao("Administrador Judicial", _ADM, duvidoso=True),
    "65": Qualificacao("Titular Pessoa Física Residente ou Domiciliado no Brasil", _SOC),
    "66": Qualificacao("Titular Pessoa Física Residente ou Domiciliado no Exterior", _SOC),
    "67": Qualificacao(
        "Titular Pessoa Física Incapaz ou Relativamente Incapaz (exceto menor)", _SOC
    ),
    "68": Qualificacao("Titular Pessoa Física Menor (Assistido/Representado)", _SOC),
    "69": Qualificacao("Beneficiário Final", _SOC, duvidoso=True),
    "70": Qualificacao("Administrador Residente ou Domiciliado no Exterior", _ADM),
    "71": Qualificacao("Conselheiro de Administração Residente ou Domiciliado no Exterior", _ADM),
    "72": Qualificacao("Diretor Residente ou Domiciliado no Exterior", _ADM),
    "73": Qualificacao("Presidente Residente ou Domiciliado no Exterior", _ADM),
    "74": Qualificacao("Sócio-Administrador Residente ou Domiciliado no Exterior", _SOC),
    "75": Qualificacao("Fundador Residente ou Domiciliado no Exterior", _SOC, duvidoso=True),
    "78": Qualificacao("Titular Pessoa Jurídica Domiciliada no Brasil", _SOC),
    "79": Qualificacao("Titular Pessoa Jurídica Domiciliada no Exterior", _SOC),
}

TIPOS = {"1": "PJ", "2": "PF", "3": "ESTRANGEIRO"}

COLUNAS_SOCIOS = (
    "cnpj_basico",
    "identificador_socio",
    "nome_socio",
    "cnpj_cpf_socio",
    "qualificacao_socio",
    "data_entrada_sociedade",
    "pais",
    "representante_legal",
    "nome_representante",
    "qualificacao_representante",
    "faixa_etaria",
)
COLUNAS_EMPRESAS = (
    "cnpj_basico",
    "razao_social",
    "natureza_juridica",
    "qualificacao_responsavel",
    "capital_social",
    "porte",
    "ente_federativo_responsavel",
)

_MOTIVO_SOCIO = r"""
    case
        when not regexp_full_match(coalesce(cnpj_basico, ''), '\d{8}') then 'CNPJ_INVALIDO'
        when coalesce(identificador_socio, '') not in ('1', '2', '3') then 'TIPO_INVALIDO'
        when identificador_socio = '2'
            and not regexp_full_match(coalesce(cnpj_cpf_socio, ''), '\*{3}\d{6}\*{2}')
            then 'CPF_FORA_DO_FORMATO'
        when identificador_socio = '1'
            and not regexp_full_match(coalesce(cnpj_cpf_socio, ''), '\d{14}')
            then 'CNPJ_SOCIO_INVALIDO'
    end
"""
_MOTIVO_EMPRESA = r"""
    case
        when not regexp_full_match(coalesce(cnpj_basico, ''), '\d{8}') then 'CNPJ_INVALIDO'
        when not regexp_full_match(coalesce(natureza_juridica, ''), '\d{4}')
            then 'NATUREZA_INVALIDA'
    end
"""


class DadoInesperado(ValueError):
    pass


@dataclass(frozen=True)
class Arquivos:
    socios: tuple[Path, ...]
    empresas: tuple[Path, ...]
    qualificacoes: Path
    preenchimento: tuple[Path, ...] = ()
    """Sócios de `OUTUBRO`."""
    reconstrucao: tuple[Path, ...] = ()
    """Sócios de `RECENTE`, só para o erro de reconstrução."""


def executar(ctx: Contexto) -> None:
    baixados: list[Arquivo] = []

    def baixar(fotografia: Fotografia, nome: str) -> Path:
        arquivo = ARQUIVOS[f"{fotografia.fonte}/{nome}"]
        baixados.append(arquivo)
        return fetch.garantir(arquivo, ctx.caminhos)

    socios = [f"Socios{i}.zip" for i in range(10)]
    arquivos = Arquivos(
        socios=tuple(baixar(SETEMBRO, nome) for nome in socios),
        empresas=tuple(baixar(SETEMBRO, f"Empresas{i}.zip") for i in range(10)),
        qualificacoes=baixar(SETEMBRO, "Qualificacoes.zip"),
        preenchimento=tuple(baixar(OUTUBRO, nome) for nome in socios),
        reconstrucao=tuple(baixar(RECENTE, nome) for nome in socios),
    )
    ingerir(ctx, arquivos)
    for arquivo in baixados:
        if arquivo.nome != "Qualificacoes.zip":
            fetch.descartar(arquivo, ctx.caminhos)


def ingerir(ctx: Contexto, arquivos: Arquivos) -> None:
    oficiais = ler_qualificacoes(arquivos.qualificacoes)
    nossas = {c: q.descricao for c, q in QUALIFICACOES.items()}
    if oficiais != nossas:
        divergentes = sorted(set(oficiais.items()) ^ set(nossas.items()))
        raise DadoInesperado(f"Qualificacoes.zip diverge de QUALIFICACOES: {divergentes}")
    chave = carregar_chave(ctx.caminhos.chave)
    contagens: list[tuple[str, str, int]] = [
        ("arquivo_de_outra_extracao", caminho.name, int(f"{SETEMBRO.extracao_do(caminho):%Y%m%d}"))
        for caminho in (*arquivos.socios, *arquivos.empresas)
        if caminho.name in SETEMBRO.outra_extracao
    ]
    with _area(ctx.caminhos.dados) as (con, pasta):
        _registrar_funcoes(con, chave)
        con.execute(
            "create table qualificacoes as select * from (values "
            + ", ".join(f"('{c}', '{q.vinculo}')" for c, q in QUALIFICACOES.items())
            + ") t(cod, vinculo)"
        )
        for i, zip_ in enumerate(arquivos.socios):
            contagens += _socios_do_arquivo(con, zip_, SETEMBRO, pasta / f"socios_{i}.parquet")
        for i, zip_ in enumerate(arquivos.preenchimento):
            parte = pasta / f"preenchimento_{i}.parquet"
            contagens += _socios_do_arquivo(con, zip_, OUTUBRO, parte)
        for i, zip_ in enumerate(arquivos.reconstrucao):
            parte = pasta / f"reconstrucao_{i}.parquet"
            _socios_do_arquivo(con, zip_, RECENTE, parte)
        for i, zip_ in enumerate(arquivos.empresas):
            contagens += _empresas_do_arquivo(con, zip_, pasta / f"empresas_{i}.parquet")
        contagens += _consolidar_empresas(con, pasta, ctx.caminho(EMPRESAS))
        contagens += _consolidar_socios(con, pasta, ctx.caminho(SOCIOS))
        _exigir_poucos_descartes(contagens)
        contagens += _resumo_socios(con, ctx.caminho(SOCIOS))
        qualificacoes = _tabela_qualificacoes(con, ctx.caminho(SOCIOS))
        ambiguidade = diagnostico_ambiguidade(con, ctx.caminho(SOCIOS))
        reconstrucao = _erro_de_reconstrucao(con, ctx.caminho(SOCIOS), ctx.caminho(EMPRESAS), pasta)

    tabelas = ctx.caminhos.resultados / "tables"
    tabelas.mkdir(parents=True, exist_ok=True)
    validacao = (
        pl.DataFrame(contagens, schema=["medida", "categoria", "valor"], orient="row")
        .group_by("medida", "categoria", maintain_order=True)
        .agg(pl.col("valor").sum())
    )
    validacao.with_columns(descritivas.suprimir("valor")).write_csv(tabelas / "validacao_rfb.csv")
    qualificacoes_publicas(qualificacoes).write_csv(tabelas / "qualificacoes_rfb.csv")
    ambiguidade_publica(ambiguidade).write_csv(tabelas / "ambiguidade_rfb.csv")
    reconstrucao.write_csv(tabelas / "reconstrucao.csv")


def ler_qualificacoes(zip_: Path) -> dict[str, str]:
    with zipfile.ZipFile(zip_) as z:
        (membro,) = z.namelist()
        texto = z.read(membro).decode("latin-1")
    linhas = [linha.split(";", 1) for linha in texto.splitlines() if linha.strip()]
    return {cod.strip('"'): desc.strip('"') for cod, desc in linhas}


@contextmanager
def _area(dados: Path) -> Iterator[tuple[duckdb.DuckDBPyConnection, Path]]:
    dados.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=dados, prefix=".ingest-rfb-") as nome:
        pasta = Path(nome)
        con = duckdb.connect(
            config={
                "memory_limit": MEMORIA_DUCKDB,
                "threads": THREADS_DUCKDB,
                "temp_directory": str(pasta / "duckdb"),
                "preserve_insertion_order": False,
            }
        )
        try:
            yield con, pasta
        finally:
            con.close()


def _registrar_funcoes(con: duckdb.DuckDBPyConnection, chave: bytes) -> None:
    def id_socio(tipos: pa.Array, nomes: pa.Array, documentos: pa.Array) -> pa.Array:
        return pa.array(
            [
                identificar(t, n, d, chave)
                for t, n, d in zip(
                    tipos.to_pylist(), nomes.to_pylist(), documentos.to_pylist(), strict=True
                )
            ],
            type=pa.string(),
        )

    con.create_function(
        "id_socio",
        id_socio,
        ["VARCHAR", "VARCHAR", "VARCHAR"],
        "VARCHAR",
        type="arrow",
        null_handling="special",
    )


def identificar(tipo: str, nome: str | None, documento: str | None, chave: bytes) -> str | None:
    """`id_socio` de uma linha já validada; nulo quando o nome normalizado fica vazio."""
    if tipo == "1":
        return (documento or "")[:8]
    normalizado = normalizar_nome(nome or "")
    if not normalizado:
        return None
    if tipo == "2":
        return pseudonimo(normalizado, documento or "", chave)
    mensagem = f"ESTRANGEIRO|{normalizado}".encode()
    return hmac.new(chave, mensagem, hashlib.sha256).hexdigest()[:TAMANHO_PSEUDONIMO]


@contextmanager
def _lotes(zip_: Path, extracao: date, colunas: tuple[str, ...]) -> Iterator[pa.RecordBatchReader]:
    """O CSV do zip em lotes, sem extrair; campo vazio vira nulo, como no `read_csv` do DuckDB."""
    with zipfile.ZipFile(zip_) as z:
        (membro,) = z.namelist()
        if _marca(extracao) not in membro:
            raise DadoInesperado(f"{zip_.name}: membro {membro} não é da extração de {extracao}")
        with z.open(membro) as entrada:
            try:
                leitor = pacsv.open_csv(
                    entrada,
                    read_options=pacsv.ReadOptions(
                        column_names=list(colunas), encoding="latin-1", block_size=BLOCO_CSV
                    ),
                    parse_options=pacsv.ParseOptions(delimiter=";", quote_char='"'),
                    convert_options=pacsv.ConvertOptions(
                        column_types=dict.fromkeys(colunas, pa.string()),
                        null_values=[""],
                        strings_can_be_null=True,
                    ),
                )
            except pa.ArrowException:
                raise _falha_de_leitura(zip_, "pyarrow") from None
            yield leitor


def _falha_de_leitura(origem: Path, leitor: str) -> DadoInesperado:
    """Erros do leitor citam a linha do CSV, com nome e CPF; a mensagem não é repassada."""
    return DadoInesperado(
        f"{origem.name}: falha do {leitor}; mensagem omitida por conter dados pessoais"
    )


def _executar(con: duckdb.DuckDBPyConnection, sql: str, origem: Path) -> list[tuple]:
    try:
        return con.execute(sql).fetchall()
    except (duckdb.Error, pa.ArrowException) as erro:
        raise _falha_de_leitura(origem, f"DuckDB ({type(erro).__name__})") from None


def _copiar_lotes(
    con: duckdb.DuckDBPyConnection,
    lotes: pa.RecordBatchReader,
    select: str,
    destino: Path,
    origem: Path,
) -> None:
    """Grava `select`, que lê da relação `lotes`, numa só passada pelo fluxo."""
    con.register("lotes", lotes)
    try:
        _executar(con, f"copy ({select}) to '{destino}' (format parquet)", origem)
    finally:
        con.unregister("lotes")


def _socios_do_arquivo(
    con: duckdb.DuckDBPyConnection, zip_: Path, fotografia: Fotografia, parte: Path
) -> list[tuple[str, str, int]]:
    """Grava em `parte` as linhas válidas, pseudonimizadas; as contagens saem de um Parquet
    intermediário com o motivo de descarte de cada linha e sem nome nem CPF."""
    bruto = parte.with_name(f"bruto_{parte.name}")
    with _lotes(zip_, fotografia.extracao_do(zip_), COLUNAS_SOCIOS) as lotes:
        _copiar_lotes(
            con,
            lotes,
            f"""select cnpj_basico, identificador_socio, qualificacao_socio, motivo,
                case when motivo is null
                    then id_socio(identificador_socio, nome_socio, cnpj_cpf_socio)
                end as id_socio,
                try_strptime(data_entrada_sociedade, '%Y%m%d')::date as data_lida,
                data_entrada_sociedade is not null as tem_data
            from (select *, {_MOTIVO_SOCIO} as motivo from lotes)""",
            bruto,
            zip_,
        )
    extracao = fotografia.extracao
    linhas = _executar(
        con,
        f"""select coalesce(motivo, ''), count(*),
            count(*) filter (qualificacao_socio not in (select cod from qualificacoes)),
            count(*) filter (data_lida > DATE '{extracao}'),
            count(*) filter (data_lida is null and tem_data)
        from '{bruto}' group by 1""",
        zip_,
    )
    validas = next((linha for linha in linhas if linha[0] == ""), ("", 0, 0, 0, 0))
    if validas[2]:
        codigos = _executar(
            con,
            f"select distinct qualificacao_socio from '{bruto}' where motivo is null "
            "and qualificacao_socio not in (select cod from qualificacoes)",
            zip_,
        )
        raise DadoInesperado(f"{zip_.name}: qualificações desconhecidas {codigos}")
    _executar(
        con,
        f"""copy (
            select
                cnpj_basico,
                id_socio,
                case identificador_socio
                    {" ".join(f"when '{k}' then '{v}'" for k, v in TIPOS.items())}
                end as tipo_socio,
                q.vinculo,
                qualificacao_socio as cod_qualificacao,
                case when data_lida <= DATE '{extracao}' then data_lida end as data_entrada
            from '{bruto}' join qualificacoes q on q.cod = qualificacao_socio
            where motivo is null
        ) to '{parte}' (format parquet)""",
        zip_,
    )
    bruto.unlink()
    medida = fotografia.medida
    return [
        (f"{medida}_linhas_lidas", zip_.name, sum(linha[1] for linha in linhas)),
        *((f"{medida}_descarte", linha[0], linha[1]) for linha in sorted(linhas) if linha[0]),
        (f"{medida}_data_posterior_anulada", zip_.name, validas[3]),
        (f"{medida}_data_invalida_anulada", zip_.name, validas[4]),
    ]


def _empresas_do_arquivo(
    con: duckdb.DuckDBPyConnection, zip_: Path, parte: Path
) -> list[tuple[str, str, int]]:
    """Grava todas as linhas, com o motivo de descarte; a consolidação fica só com as válidas."""
    with _lotes(zip_, SETEMBRO.extracao_do(zip_), COLUNAS_EMPRESAS) as lotes:
        _copiar_lotes(
            con,
            lotes,
            f"""select
                cnpj_basico,
                natureza_juridica as cod_natureza_juridica,
                nullif(trim(porte), '') as porte,
                try_cast(replace(capital_social, ',', '.') as double) as capital_social,
                {_MOTIVO_EMPRESA} as motivo
            from lotes""",
            parte,
            zip_,
        )
    linhas = _executar(
        con, f"select coalesce(motivo, ''), count(*) from '{parte}' group by 1", zip_
    )
    return [
        ("empresas_linhas_lidas", zip_.name, sum(n for _, n in linhas)),
        *(("empresas_descarte", m, n) for m, n in sorted(linhas) if m),
    ]


def _faixa_cnpj(digito: str) -> str:
    proximo = chr(ord(digito) + 1)
    return f"cnpj_basico >= '{digito}' and cnpj_basico < '{proximo}'"


def _consolidar_socios(
    con: duckdb.DuckDBPyConnection, pasta: Path, destino: Path
) -> list[tuple[str, str, int]]:
    """Une as partes, preenche as empresas sem sócio e remove repetições da chave, guardando a
    data de entrada mais antiga. Lê `empresas.parquet` de `_consolidar_empresas`.

    `id_socio` nulo marca nome que a normalização esvazia; sem nome, o pseudônimo juntaria
    pessoas distintas com os mesmos 6 dígitos.
    """
    setembro = f"'{pasta}/socios_*.parquet'"
    ((validas, sem_nome),) = con.execute(
        f"select count(*), count(*) filter (id_socio is null) from {setembro}"
    ).fetchall()
    contagens = _separar_preenchimento(con, pasta, setembro)
    (preenchidos,) = con.execute("select count(*) from preenchidos").fetchone()
    outubro = pasta / "preenchidos.parquet"
    con.execute(f"copy preenchidos to '{outubro}' (format parquet)")
    for tabela in ("preenchidos", "no_cadastro", "ausentes", "presentes"):
        con.execute(f"drop table {tabela}")

    # A chave começa pelo CNPJ. Cada prefixo pode ser deduplicado independentemente, limitando
    # os arquivos de ordenação do DuckDB na fotografia nacional.
    unicas = []
    for digito in "0123456789":
        faixa = _faixa_cnpj(digito)
        unica = pasta / f"vinculos_unicos_{digito}.parquet"
        con.execute(
            f"""copy (
                select cnpj_basico, id_socio, any_value(tipo_socio) as tipo_socio,
                    any_value(vinculo) as vinculo, cod_qualificacao,
                    min(data_entrada) as data_entrada, any_value(origem) as origem
                from (
                    select *, '2024-09' as origem from {setembro}
                    where {faixa} and id_socio is not null
                    union all by name
                    select *, '2024-10' as origem from '{outubro}' where {faixa}
                )
                group by cnpj_basico, id_socio, cod_qualificacao
                order by cnpj_basico, id_socio, cod_qualificacao
            ) to '{unica}' (format parquet)"""
        )
        unicas.append(unica)
    por_origem = dict(
        con.execute(
            f"select origem, count(*) from '{pasta}/vinculos_unicos_*.parquet' group by 1"
        ).fetchall()
    )
    _gravar_com_esquema(
        pl.scan_parquet(unicas).with_columns(
            pl.col("tipo_socio").cast(TIPO_SOCIO),
            pl.col("vinculo").cast(VINCULO),
            pl.col("origem").cast(FOTOGRAFIA_RFB),
        ),
        SOCIOS,
        destino,
    )
    return [
        ("socios_descarte", "NOME_VAZIO", sem_nome),
        ("socios_descarte", "DUPLICADA", validas - sem_nome - por_origem.get("2024-09", 0)),
        *contagens,
        ("preenchimento_vinculos", "DUPLICADA", preenchidos - por_origem.get("2024-10", 0)),
    ]


def _contagens_de_reconstrucao(
    con: duckdb.DuckDBPyConnection,
    socios: Path,
    empresas: Path,
    recentes: list[Path],
    faixa: str,
) -> tuple[int, ...]:
    con.execute(
        f"""create or replace temp table setembro as
            select distinct cnpj_basico, id_socio, cod_qualificacao
            from '{socios}' where origem = '2024-09' and id_socio is not null and {faixa}"""
    )
    con.execute(
        f"""create or replace temp table atual as
            select distinct cnpj_basico, id_socio, cod_qualificacao
            from read_parquet({[str(p) for p in recentes]})
            where id_socio is not null and {faixa}
              and data_entrada < DATE '{config.DATA_EXTRACAO_RFB}'
              and cnpj_basico in (select cnpj_basico from '{empresas}' where {faixa})"""
    )

    def contar(expressao: str) -> int:
        ((numero,),) = con.execute(f"select {expressao}").fetchall()
        return int(numero)

    setembro_vinculos = contar("count(*) from setembro")
    ausentes_vinculos = contar(
        """count(*) from setembro s where not exists (
            select 1 from atual a
            where a.cnpj_basico = s.cnpj_basico and a.id_socio = s.id_socio
              and a.cod_qualificacao = s.cod_qualificacao)"""
    )
    setembro_empresas = contar("count(distinct cnpj_basico) from setembro")
    ausentes_empresas = contar(
        """count(distinct cnpj_basico) from setembro s where not exists (
            select 1 from atual a where a.cnpj_basico = s.cnpj_basico)"""
    )
    reconstruidos_vinculos = contar("count(*) from atual")
    reconstruidos_ausentes = contar(
        """count(*) from atual a where not exists (
            select 1 from setembro s
            where s.cnpj_basico = a.cnpj_basico and s.id_socio = a.id_socio
              and s.cod_qualificacao = a.cod_qualificacao)"""
    )
    reconstruidas_empresas = contar("count(distinct cnpj_basico) from atual")
    reconstruidas_ausentes = contar(
        """count(distinct cnpj_basico) from atual a where not exists (
            select 1 from setembro s where s.cnpj_basico = a.cnpj_basico)"""
    )
    encontrados_no_preenchimento = contar(
        f"""count(*) from atual a where exists (
            select 1 from (select * from '{socios}' where {faixa}) s where origem = '2024-10'
            and s.cnpj_basico = a.cnpj_basico and s.id_socio = a.id_socio
            and s.cod_qualificacao = a.cod_qualificacao)"""
    )

    con.execute("drop table setembro; drop table atual")
    return (
        setembro_vinculos,
        ausentes_vinculos,
        setembro_empresas,
        ausentes_empresas,
        reconstruidos_vinculos,
        reconstruidos_ausentes,
        reconstruidas_empresas,
        reconstruidas_ausentes,
        encontrados_no_preenchimento,
    )


def _erro_de_reconstrucao(
    con: duckdb.DuckDBPyConnection, socios: Path, empresas: Path, pasta: Path
) -> pl.DataFrame:
    """Quanto da rede de 2024-09 se perde ao reconstruí-la pela fotografia de `RECENTE` (T10).

    Compara os vínculos de setembro com os da fotografia mais recente restritos ao cadastro de
    2024-09 e à data de entrada anterior à extração de setembro, o mesmo filtro do preenchimento.
    Devolve contagens e frações: vínculos e empresas de setembro ausentes da
    reconstrução, e vínculos e empresas reconstruídos ausentes de setembro. Sem os arquivos da
    fotografia recente (testes de outras partes da ingestão), não produz comparações.
    """
    recentes = sorted(pasta.glob("reconstrucao_*.parquet"))
    if not recentes:
        return pl.DataFrame(schema={"medida": pl.String, "valor": pl.Float64})
    parciais = [
        _contagens_de_reconstrucao(con, socios, empresas, recentes, _faixa_cnpj(d))
        for d in "0123456789"
    ]
    (
        setembro_vinculos,
        ausentes_vinculos,
        setembro_empresas,
        ausentes_empresas,
        reconstruidos_vinculos,
        reconstruidos_ausentes,
        reconstruidas_empresas,
        reconstruidas_ausentes,
        encontrados_no_preenchimento,
    ) = (sum(parte) for parte in zip(*parciais, strict=True))

    linhas = [
        ("vinculos_setembro", setembro_vinculos),
        ("vinculos_setembro_ausentes_na_reconstrucao", ausentes_vinculos),
        ("empresas_setembro", setembro_empresas),
        ("empresas_setembro_ausentes_na_reconstrucao", ausentes_empresas),
        ("vinculos_reconstruidos", reconstruidos_vinculos),
        ("vinculos_reconstruidos_ausentes_em_setembro", reconstruidos_ausentes),
        ("empresas_reconstruidas", reconstruidas_empresas),
        ("empresas_reconstruidas_ausentes_em_setembro", reconstruidas_ausentes),
        ("vinculos_extras_tambem_no_preenchimento", encontrados_no_preenchimento),
    ]
    fracoes = [
        ("fracao_vinculos_setembro_ausentes_na_reconstrucao", ausentes_vinculos, setembro_vinculos),
        ("fracao_empresas_setembro_ausentes_na_reconstrucao", ausentes_empresas, setembro_empresas),
        (
            "fracao_vinculos_reconstruidos_ausentes_em_setembro",
            reconstruidos_ausentes,
            reconstruidos_vinculos,
        ),
        (
            "fracao_empresas_reconstruidas_ausentes_em_setembro",
            reconstruidas_ausentes,
            reconstruidas_empresas,
        ),
        (
            "fracao_vinculos_extras_tambem_no_preenchimento",
            encontrados_no_preenchimento,
            reconstruidos_ausentes,
        ),
    ]
    return reconstrucao_publica(
        pl.DataFrame(
            {
                "medida": [nome for nome, _ in linhas] + [nome for nome, _, _ in fracoes],
                "valor": [float(v) for _, v in linhas]
                + [parte / total if total else None for _, parte, total in fracoes],
            },
            schema={"medida": pl.String, "valor": pl.Float64},
        )
    )


def reconstrucao_publica(tabela: pl.DataFrame) -> pl.DataFrame:
    """Se uma das partes é pequena, oculta as medidas que permitiriam deduzi-la."""
    valores = dict(tabela.iter_rows())
    ocultar = []
    for radical, plural in (
        ("vinculos", "vinculos_reconstruidos"),
        ("empresas", "empresas_reconstruidas"),
    ):
        total = valores.get(f"{radical}_setembro")
        perdido = valores.get(f"{radical}_setembro_ausentes_na_reconstrucao")
        extra = valores.get(f"{plural}_ausentes_em_setembro")
        partes = [
            perdido,
            extra,
            total - perdido if total is not None and perdido is not None else None,
        ]
        if any(v is None or 0 < v < config.SUPRESSAO_MINIMA for v in partes):
            ocultar.append(radical)
    extra = valores.get("vinculos_reconstruidos_ausentes_em_setembro")
    preenchidos = valores.get("vinculos_extras_tambem_no_preenchimento")
    if preenchidos is not None and (
        0 < preenchidos < config.SUPRESSAO_MINIMA
        or (extra is not None and 0 < extra - preenchidos < config.SUPRESSAO_MINIMA)
    ):
        ocultar.append("vinculos_extras")
    return pl.DataFrame(
        [(m, None if any(r in m for r in ocultar) else v) for m, v in valores.items()],
        schema={"medida": pl.String, "valor": pl.Float64},
        orient="row",
    )


def _separar_preenchimento(
    con: duckdb.DuckDBPyConnection, pasta: Path, setembro: str
) -> list[tuple[str, str, int]]:
    """Cria a tabela `preenchidos`: vínculos de 2024-10 das empresas do cadastro de 2024-09
    sem sócio em 2024-09, com entrada antes da extração de 2024-09."""
    outubro = sorted(pasta.glob("preenchimento_*.parquet"))
    origem = (
        f"read_parquet({[str(p) for p in outubro]})"
        if outubro
        else f"(select * from {setembro} limit 0)"
    )
    con.execute(
        f"""
        create or replace temp table presentes as
            select distinct cnpj_basico from {setembro} where id_socio is not null;
        create or replace temp table ausentes as
            select o.* from {origem} o anti join presentes using (cnpj_basico)
            where o.id_socio is not null;
        create or replace temp table no_cadastro as
            select cnpj_basico from '{pasta}/empresas.parquet'
            semi join (select distinct cnpj_basico from ausentes) using (cnpj_basico);
        create or replace temp table preenchidos as
            select * from ausentes semi join no_cadastro using (cnpj_basico)
            where data_entrada < DATE '{config.DATA_EXTRACAO_RFB}';
        """
    )
    ((empresas, fora, linhas_fora, preenchidas, posteriores, sem_data),) = con.execute(
        f"""select count(distinct cnpj_basico),
            count(distinct cnpj_basico) filter (not no_cadastro),
            count(*) filter (not no_cadastro),
            count(distinct cnpj_basico) filter (no_cadastro and preenche),
            count(*) filter (no_cadastro and data_entrada >= DATE '{config.DATA_EXTRACAO_RFB}'),
            count(*) filter (no_cadastro and data_entrada is null)
        from (
            select cnpj_basico, data_entrada,
                cnpj_basico in (select cnpj_basico from no_cadastro) as no_cadastro,
                data_entrada < DATE '{config.DATA_EXTRACAO_RFB}' as preenche
            from ausentes
        )"""
    ).fetchall()
    return [
        ("preenchimento_empresas", "sem_socio_em_2024_09_com_socio_em_2024_10", empresas),
        ("preenchimento_empresas", "fora_do_cadastro_de_2024_09", fora),
        ("preenchimento_empresas", "preenchidas", preenchidas),
        ("preenchimento_vinculos", "fora_do_cadastro_de_2024_09", linhas_fora),
        ("preenchimento_vinculos", "entrada_a_partir_da_extracao_de_2024_09", posteriores),
        ("preenchimento_vinculos", "sem_data_de_entrada", sem_data),
    ]


def _consolidar_empresas(
    con: duckdb.DuckDBPyConnection, pasta: Path, destino: Path
) -> list[tuple[str, str, int]]:
    unica = pasta / "empresas.parquet"
    validas = f"(select * exclude (motivo) from '{pasta}/empresas_*.parquet' where motivo is null)"
    ((partes,),) = con.execute(f"select count(*) from {validas}").fetchall()
    (gravadas,) = con.execute(
        f"""copy (
            select * from {validas}
            qualify row_number() over (
                partition by cnpj_basico order by cod_natureza_juridica, porte, capital_social
            ) = 1
            order by cnpj_basico
        ) to '{unica}' (format parquet)"""
    ).fetchone()
    _gravar_com_esquema(pl.scan_parquet(unica), EMPRESAS, destino)
    return [("empresas_descarte", "DUPLICADA", partes - gravadas)]


def _gravar_com_esquema(frame: pl.LazyFrame, tabela: Tabela, destino: Path) -> None:
    """Grava em fluxo, sem montar a tabela na memória; o executor valida o arquivo depois."""
    temporario = destino.with_suffix(destino.suffix + ".tmp")
    destino.parent.mkdir(parents=True, exist_ok=True)
    frame.select(pl.col(c).cast(t) for c, t in tabela.esquema.items()).sink_parquet(temporario)
    temporario.replace(destino)


def _exigir_poucos_descartes(contagens: list[tuple[str, str, int]]) -> None:
    """Repetição não conta: os cortes dos arquivos de sócios se sobrepõem (`SETEMBRO`)."""
    for tabela in ("socios", "preenchimento", "empresas"):
        lidas = sum(v for m, _, v in contagens if m == f"{tabela}_linhas_lidas")
        descartadas = sum(
            v for m, c, v in contagens if m == f"{tabela}_descarte" and c != "DUPLICADA"
        )
        if lidas and descartadas > LIMITE_DESCARTE * lidas:
            raise DadoInesperado(
                f"{tabela}: {descartadas} de {lidas} linhas descartadas; o layout mudou?"
            )


def _resumo_socios(con: duckdb.DuckDBPyConnection, socios: Path) -> list[tuple[str, str, int]]:
    por_tipo = con.execute(
        f"select tipo_socio || '_' || vinculo, count(*) from '{socios}' group by 1 order by 1"
    ).fetchall()
    distintos = con.execute(
        f"select tipo_socio, count(distinct id_socio) from '{socios}' group by 1 order by 1"
    ).fetchall()
    por_origem = con.execute(
        f"select origem, count(*), count(distinct cnpj_basico) from '{socios}' "
        "group by 1 order by 1"
    ).fetchall()
    ((estrangeiros_em_varias,),) = con.execute(
        f"""select count(*) filter (n > 1) from (
            select count(distinct cnpj_basico) as n from '{socios}'
            where tipo_socio = 'ESTRANGEIRO' group by id_socio
        )"""
    ).fetchall()
    ((empresas, sem_data, total),) = con.execute(
        f"select count(distinct cnpj_basico), count(*) filter (data_entrada is null), count(*) "
        f"from '{socios}'"
    ).fetchall()
    return [
        ("socios_linhas_gravadas", "total", total),
        *(("socios_linhas", k, n) for k, n in por_tipo),
        *(("socios_linhas_por_origem", k, n) for k, n, _ in por_origem),
        ("socios_data_entrada_nula", "total", sem_data),
        ("socios_empresas_distintas", "total", empresas),
        *(("socios_empresas_por_origem", k, n) for k, _, n in por_origem),
        *(("socios_distintos", k, n) for k, n in distintos),
        ("socios_estrangeiro_em_mais_de_uma_empresa", "pseudonimos", estrangeiros_em_varias),
    ]


def _tabela_qualificacoes(con: duckdb.DuckDBPyConnection, socios: Path) -> pl.DataFrame:
    linhas = dict(
        con.execute(f"select cod_qualificacao, count(*) from '{socios}' group by 1").fetchall()
    )
    return pl.DataFrame(
        [
            (cod, q.descricao, q.vinculo, q.duvidoso, linhas.get(cod, 0))
            for cod, q in QUALIFICACOES.items()
        ],
        schema=["cod_qualificacao", "descricao", "vinculo", "duvidoso", "linhas"],
        orient="row",
    )


def qualificacoes_publicas(tabela: pl.DataFrame) -> pl.DataFrame:
    # Os totais por vínculo também estão na validação e expõem a soma das células raras.
    return descritivas.suprimir_particao(tabela, ("linhas",), "vinculo", complementar_sempre=True)


FAIXAS_AMBIGUIDADE = ((1, 1), (2, 2), (3, 5), (6, 10), (11, 20), (21, 50), (51, 100), (101, 500))


def diagnostico_ambiguidade(con: duckdb.DuckDBPyConnection, socios: Path) -> pl.DataFrame:
    """Pessoas físicas e estrangeiras por número de empresas distintas, em faixas.

    Pseudônimos com centenas de empresas são candidatos a homônimos com os mesmos 6 dígitos
    centrais ou a administradores profissionais. O estrangeiro é identificado só pelo nome, então
    nele a junção de homônimos é mais provável. Só agregados saem daqui.
    """
    casos = " ".join(f"when n between {a} and {b} then '{a}-{b}'" for a, b in FAIXAS_AMBIGUIDADE)
    ultima = FAIXAS_AMBIGUIDADE[-1][1] + 1
    return con.sql(
        f"""
        with por_pessoa as (
            select tipo_socio::varchar as tipo_socio, id_socio, count(distinct cnpj_basico) as n
            from '{socios}' where tipo_socio in ('PF', 'ESTRANGEIRO') group by 1, 2
        )
        select tipo_socio, case {casos} else '{ultima}+' end as faixa_empresas,
            count(*) as pessoas, sum(n) as vinculos, max(n) as maximo
        from por_pessoa group by 1, 2 order by 1 desc, min(n)
        """
    ).pl()


def ambiguidade_publica(tabela: pl.DataFrame) -> pl.DataFrame:
    pequeno = pl.col("pessoas").is_between(1, config.SUPRESSAO_MINIMA - 1)
    complemento = (
        pl.col("pessoas")
        .filter(pl.col("pessoas") >= config.SUPRESSAO_MINIMA)
        .min()
        .over("tipo_socio")
    )
    ocultar = pequeno | (pequeno.any().over("tipo_socio") & (pl.col("pessoas") == complemento))
    return tabela.with_columns(
        pl.when(~ocultar.fill_null(False)).then(pl.col(c)).alias(c)
        for c in ("pessoas", "vinculos", "maximo")
    )
