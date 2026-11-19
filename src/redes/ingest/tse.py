"""Etapa `ingest-tse`: candidatos a prefeito, votação de 2024 e receitas de campanha de SP (T05).

Os CSVs do TSE (latin-1, `;`, aspas) são lidos em fluxo de dentro dos zips, um lote por vez,
e só as linhas de prefeito de SP ficam em memória. A capital fica fora desde aqui (SPEC, Limites).

Decisões que os dados impuseram (conferidas em 11/11/2026):

- **CPF do candidato de 2024.** `consulta_cand_2024` e as receitas de 2024 publicam o CPF do
  candidato mascarado (`-4`), mas o título de eleitor e o CPF do doador vêm completos. O CPF do
  candidato de 2024 vem, em ordem de preferência, (1) do candidato de 2020 de SP, de qualquer
  cargo, com o mesmo título de eleitor, e (2) das receitas "Recursos próprios" do candidato,
  quando o nome do doador normalizado é igual ao do candidato. Fontes divergentes deixam o
  candidato sem CPF. Sem CPF, `id_pessoa` é o HMAC do título (ou do sequencial, sem título),
  num espaço de mensagens que nunca coincide com o de nome e CPF: a pessoa não se liga a nada.
  O título também une as candidaturas da mesma pessoa: quem mudou de nome entre 2020 e 2024
  fica com o pseudônimo da candidatura mais recente em todas, para o ramo PREFEITO da seção 6.
- **Partido nas eleições anteriores a 2024.** Fusões, incorporações e mudanças de nome entre
  2020 e 2024 (`SUCESSORES`) são aplicadas às siglas de 2020 e das suplementares, para que o
  ramo PARTIDO da seção 6 encontre o partido do prefeito com a sigla que ele usa em 2024.
- **Coligação.** Em 2024, os partidos vêm de `consulta_coligacao`, que lista cada partido de
  cada federação; partidos com a participação indeferida ou invalidada ficam fora. Antes de 2024
  não há esse arquivo, e os partidos saem de `DS_COMPOSICAO_COLIGACAO`.
- **Votos válidos.** `QT_VOTOS_NOMINAIS_VALIDOS`: votos anulados e anulados sub judice não
  contam, como no total de votos válidos que o TSE divulga.
- **Receitas.** `SQ_RECEITA` se repete quando um recibo tem várias linhas; `id_receita` é o
  sequencial seguido da ordem da linha no arquivo. O nome do doador é `NM_DOADOR_RFB`, o do
  cadastro da Receita, que é o mesmo do quadro de sócios; sem ele, `NM_DOADOR`. O CPF e o CNPJ
  vêm sem zeros à esquerda e são completados. A origem decide se o documento é CPF ou CNPJ; o
  financiamento coletivo traz o CNPJ da plataforma e por isso não tem doador pessoa física.
"""

import hashlib
import hmac
import re
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path

import polars as pl
import pyarrow as pa
import pyarrow.csv as pacsv

from redes import config
from redes.etapas import Contexto, Etapa
from redes.fetch import descartar, garantir
from redes.fontes import ARQUIVOS
from redes.pseudonimo import TAMANHO_PSEUDONIMO, carregar_chave, normalizar_nome, pseudonimo
from redes.schemas import (
    CANDIDATOS,
    DOACOES,
    ORIGEM_RECEITA,
    PSEUDONIMOS_AMBIGUOS,
    TIPO_DOADOR,
    TIPO_ELEICAO,
    VOTOS,
)

ARQUIVO_VALIDACAO = "validacao_tse.csv"

ETAPA = Etapa(
    nome="ingest-tse",
    depende=(),
    le=(),
    grava=(CANDIDATOS, VOTOS, DOACOES, PSEUDONIMOS_AMBIGUOS),
    artefatos=(f"resultados/tables/{ARQUIVO_VALIDACAO}",),
)

ENTRADAS = {
    "cand_2020": "tse-2020/consulta_cand_2020.zip",
    "suplementares_2020": "tse-2020/lista_eleicoes_suplementares_2020.zip",
    "cand_2024": "tse-2024/consulta_cand_2024.zip",
    "coligacao_2024": "tse-2024/consulta_coligacao_2024.zip",
    "votacao_2024": "tse-2024/votacao_candidato_munzona_2024.zip",
    "contas_2024": "tse-2024/prestacao_de_contas_eleitorais_candidatos_2024.zip",
}

COD_CAPITAL = "71072"

SUCESSORES = {
    "DEM": "UNIÃO",
    "PSL": "UNIÃO",
    "PTB": "PRD",
    "PATRIOTA": "PRD",
    "PROS": "SOLIDARIEDADE",
    "PSC": "PODE",
    "PTC": "AGIR",
    "PMN": "MOBILIZA",
}

ORIGENS = {
    "Recursos de pessoas físicas": "PESSOA_FISICA",
    "Doações pela Internet": "PESSOA_FISICA",
    "Recursos de Financiamento Coletivo": "PESSOA_FISICA",
    "Recursos próprios": "RECURSOS_PROPRIOS",
    "Recursos de partido político": "REPASSE",
    "Recursos de outros candidatos": "REPASSE",
}
_ORIGENS_COM_CPF = ("Recursos de pessoas físicas", "Doações pela Internet", "Recursos próprios")

_COLUNAS_CAND = [
    "NM_TIPO_ELEICAO",
    "DT_ELEICAO",
    "SG_UE",
    "DS_CARGO",
    "SQ_CANDIDATO",
    "NM_CANDIDATO",
    "NR_CPF_CANDIDATO",
    "NR_TITULO_ELEITORAL_CANDIDATO",
    "DS_SITUACAO_CANDIDATURA",
    "SG_PARTIDO",
    "SQ_COLIGACAO",
    "DS_COMPOSICAO_COLIGACAO",
    "DS_SIT_TOT_TURNO",
]
_COLUNAS_RECEITA = [
    "NM_TIPO_ELEICAO",
    "SG_UE",
    "DS_CARGO",
    "SQ_PRESTADOR_CONTAS",
    "SQ_CANDIDATO",
    "DS_ORIGEM_RECEITA",
    "NR_CPF_CNPJ_DOADOR",
    "NM_DOADOR",
    "NM_DOADOR_RFB",
    "SQ_RECEITA",
    "DT_RECEITA",
    "VR_RECEITA",
]


def ler_csv(
    zip_: Path, membro: str, colunas: list[str], filtro: pl.Expr | None = None
) -> pl.DataFrame:
    """Colunas pedidas de um CSV do TSE, todas como texto, filtradas lote a lote."""
    opcoes = pacsv.ConvertOptions(
        include_columns=colunas,
        column_types=dict.fromkeys(colunas, pa.string()),
        strings_can_be_null=False,
        quoted_strings_can_be_null=False,
    )
    partes = [pl.DataFrame(schema=dict.fromkeys(colunas, pl.String))]
    with zipfile.ZipFile(zip_) as arquivo, arquivo.open(membro) as entrada:
        leitor = pacsv.open_csv(
            entrada,
            read_options=pacsv.ReadOptions(encoding="latin1", block_size=16 << 20),
            parse_options=pacsv.ParseOptions(delimiter=";"),
            convert_options=opcoes,
        )
        for lote in leitor:
            df = pl.from_arrow(pa.Table.from_batches([lote]))
            partes.append(df if filtro is None else df.filter(filtro))
    return pl.concat(partes)


def _maiusculas(coluna: str) -> pl.Expr:
    return pl.col(coluna).str.to_uppercase()


_PREFEITO_SEM_CAPITAL = (_maiusculas("DS_CARGO") == "PREFEITO") & (pl.col("SG_UE") != COD_CAPITAL)


def _tipo_eleicao(coluna: str) -> pl.Expr:
    texto = _maiusculas(coluna)
    return (
        pl.when(texto.str.contains("SUPLEMENTAR|EXTRAORDIN"))
        .then(pl.lit("SUPLEMENTAR"))
        .when(texto.str.contains("ORDIN"))
        .then(pl.lit("ORDINARIA"))
        .cast(TIPO_ELEICAO)
    )


_ORDINARIA = _tipo_eleicao("NM_TIPO_ELEICAO") == "ORDINARIA"


def _data(coluna: str) -> pl.Expr:
    return pl.col(coluna).str.strptime(pl.Date, "%d/%m/%Y", strict=False)


def _documento(coluna: str, digitos: int) -> pl.Expr:
    """Documento numérico completado com zeros à esquerda; nulo se não cabe em `digitos`."""
    valor = pl.col(coluna).str.strip_chars()
    cabe = valor.str.contains(r"^\d+$") & (valor.str.len_chars() <= digitos)
    return pl.when(cabe & (valor.str.strip_chars_start("0") != "")).then(valor.str.zfill(digitos))


def _normalizado(coluna: str) -> pl.Expr:
    return pl.col(coluna).map_elements(normalizar_nome, return_dtype=pl.String)


def _pseudonimo_sem_cpf(rotulo: str, chave: bytes) -> str:
    mensagem = f"sem-cpf|{rotulo}".encode()
    return hmac.new(chave, mensagem, hashlib.sha256).hexdigest()[:TAMANHO_PSEUDONIMO]


def cpf_valido(cpf: str) -> bool:
    digitos = [int(c) for c in cpf]
    if len(digitos) != 11 or len(set(digitos)) == 1:
        return False
    for n in (9, 10):
        soma = sum(d * (n + 1 - i) for i, d in enumerate(digitos[:n]))
        if soma * 10 % 11 % 10 != digitos[n]:
            return False
    return True


def partidos_da_composicao(composicao: str) -> list[str]:
    """Siglas de `DS_COMPOSICAO_COLIGACAO`, com os partidos de cada federação abertos."""
    federacoes = re.findall(r"Federa\S*\s[^(]*\(([^)]*)\)", composicao)
    membros = [re.sub(r"^\d+-", "", p.strip()) for f in federacoes for p in f.split("/")]
    resto = re.sub(r"Federa\S*\s[^(]*\([^)]*\)", "", composicao)
    return sorted({p.strip() for p in [*resto.split("/"), *membros] if p.strip()})


def candidaturas(cand: pl.DataFrame) -> pl.DataFrame:
    """Uma linha por `SQ_CANDIDATO`; o segundo turno repete a candidatura com outra data."""
    situacao = pl.col("DS_SIT_TOT_TURNO")
    return (
        cand.with_columns(data=_data("DT_ELEICAO"), tipo=_tipo_eleicao("NM_TIPO_ELEICAO"))
        .sort("data")
        .group_by("SQ_CANDIDATO", maintain_order=True)
        .agg(
            pl.col("data").first().alias("data_eleicao"),
            pl.col("tipo").first().alias("tipo_eleicao"),
            pl.exclude("data", "tipo", "DS_SIT_TOT_TURNO", "DT_ELEICAO").first(),
            pl.when((situacao != "#NULO").any()).then((situacao == "ELEITO").any()).alias("eleito"),
        )
        .with_columns(
            pl.col("data_eleicao").dt.year().cast(pl.Int16).alias("ano"),
            _documento("NR_CPF_CANDIDATO", 11).alias("cpf"),
            _documento("NR_TITULO_ELEITORAL_CANDIDATO", 12).alias("titulo"),
        )
    )


@dataclass(frozen=True)
class CpfsDe2024:
    cpfs: pl.DataFrame
    """(SQ_CANDIDATO, cpf, fonte), só para quem tem CPF."""
    contagens: dict[str, int]


def cpfs_de_2024(
    cand_2024: pl.DataFrame, titulos_2020: pl.DataFrame, proprios: pl.DataFrame
) -> CpfsDe2024:
    """CPF do candidato de 2024 pelo título em 2020 ou pelos recursos próprios declarados.

    `titulos_2020`: (titulo, cpf) de todos os candidatos de SP em 2020. `proprios`: receitas de
    recursos próprios com (SQ_CANDIDATO, NM_DOADOR, NM_DOADOR_RFB, cpf).
    """
    por_titulo = (
        titulos_2020.drop_nulls()
        .unique()
        .filter(pl.col("cpf").n_unique().over("titulo") == 1)
        .join(cand_2024.select("SQ_CANDIDATO", "titulo"), on="titulo")
        .select("SQ_CANDIDATO", pl.col("cpf").alias("cpf_titulo"))
        .unique()
    )
    nome = cand_2024.select("SQ_CANDIDATO", _normalizado("NM_CANDIDATO").alias("nome"))
    por_proprios = (
        proprios.drop_nulls("cpf")
        .with_columns(rfb=_normalizado("NM_DOADOR_RFB"), tse=_normalizado("NM_DOADOR"))
        .join(nome, on="SQ_CANDIDATO")
        .filter((pl.col("rfb") == pl.col("nome")) | (pl.col("tse") == pl.col("nome")))
        .group_by("SQ_CANDIDATO")
        .agg(pl.col("cpf").unique())
        .filter(pl.col("cpf").list.len() == 1)
        .select("SQ_CANDIDATO", pl.col("cpf").list.first().alias("cpf_proprios"))
    )
    juntos = (
        cand_2024.select("SQ_CANDIDATO")
        .join(por_titulo, on="SQ_CANDIDATO", how="left")
        .join(por_proprios, on="SQ_CANDIDATO", how="left")
    )
    titulo, proprio = pl.col("cpf_titulo"), pl.col("cpf_proprios")
    fonte = (
        pl.when(titulo.is_not_null() & proprio.is_not_null() & (titulo != proprio))
        .then(pl.lit("CONFLITO"))
        .when(titulo.is_not_null() & proprio.is_not_null())
        .then(pl.lit("TITULO_E_PROPRIOS"))
        .when(titulo.is_not_null())
        .then(pl.lit("TITULO_2020"))
        .when(proprio.is_not_null())
        .then(pl.lit("RECURSOS_PROPRIOS"))
        .otherwise(pl.lit("SEM_CPF"))
    )
    marcados = juntos.with_columns(fonte.alias("fonte"), pl.coalesce(titulo, proprio).alias("cpf"))
    contagens = dict(marcados.group_by("fonte").len().iter_rows())
    return CpfsDe2024(
        marcados.filter(~pl.col("fonte").is_in(["CONFLITO", "SEM_CPF"])).select(
            "SQ_CANDIDATO", "cpf", "fonte"
        ),
        contagens,
    )


def _sucessor(sigla: pl.Expr) -> pl.Expr:
    return sigla.replace(SUCESSORES)


def tabela_candidatos(
    anteriores: pl.DataFrame,
    de_2024: pl.DataFrame,
    coligacoes_2024: pl.DataFrame,
    julgamento_2024: pl.DataFrame,
    cpfs_2024: pl.DataFrame,
) -> pl.DataFrame:
    """Candidaturas já agregadas (`candidaturas`), antes da pseudonimização.

    Devolve as colunas de `CANDIDATOS` exceto `id_pessoa`, mais `NM_CANDIDATO`, `cpf` e `titulo`.
    """
    partidos_2024 = (
        coligacoes_2024.filter(~pl.col("DS_SITUACAO").is_in(["INDEFERIDO", "INVALIDADO"]))
        .group_by("SQ_COLIGACAO")
        .agg(pl.col("SG_PARTIDO").unique().alias("partidos"))
    )
    novos = (
        de_2024.drop("cpf")
        .join(cpfs_2024.select("SQ_CANDIDATO", "cpf"), on="SQ_CANDIDATO", how="left")
        .join(partidos_2024, on="SQ_COLIGACAO", how="left")
        .join(julgamento_2024, on="SQ_CANDIDATO", how="left")
        .with_columns(
            pl.coalesce("DS_SITUACAO_JULGAMENTO", "DS_SITUACAO_CANDIDATURA").alias("situacao"),
            pl.concat_list(
                pl.col("partidos").fill_null(pl.lit([], pl.List(pl.String))), "SG_PARTIDO"
            )
            .list.unique()
            .list.sort()
            .alias("partidos"),
        )
    )
    velhos = anteriores.with_columns(
        _sucessor(pl.col("SG_PARTIDO")).alias("SG_PARTIDO"),
        pl.col("DS_COMPOSICAO_COLIGACAO")
        .map_elements(partidos_da_composicao, return_dtype=pl.List(pl.String))
        .alias("partidos"),
        pl.col("DS_SITUACAO_CANDIDATURA").alias("situacao"),
    ).with_columns(
        pl.concat_list(pl.col("partidos").list.eval(_sucessor(pl.element())), pl.col("SG_PARTIDO"))
        .list.unique()
        .list.sort()
        .alias("partidos")
    )
    colunas = [
        pl.col("ano"),
        pl.col("data_eleicao"),
        pl.col("tipo_eleicao"),
        pl.col("SG_UE").alias("cod_municipio_tse"),
        pl.col("SQ_CANDIDATO").alias("sq_candidato"),
        pl.col("SG_PARTIDO").alias("sigla_partido"),
        pl.when(pl.col("SQ_COLIGACAO").str.contains(r"^\d{5,}$"))
        .then(pl.col("SQ_COLIGACAO"))
        .alias("sq_coligacao"),
        pl.col("partidos").alias("partidos_coligacao"),
        pl.col("situacao").alias("situacao_candidatura"),
        pl.col("eleito"),
        pl.col("NM_CANDIDATO"),
        pl.col("cpf"),
        pl.col("titulo"),
    ]
    return pl.concat([velhos.select(colunas), novos.select(colunas)])


def tabela_votos(votacao: pl.DataFrame) -> pl.DataFrame:
    """Votos válidos de prefeito por candidato, turno e município, somados sobre as zonas."""
    return (
        votacao.group_by("NR_TURNO", "SG_UE", "SQ_CANDIDATO")
        .agg(pl.col("QT_VOTOS_NOMINAIS_VALIDOS").cast(pl.Int64).sum().alias("votos"))
        .select(
            pl.lit(config.ANO_ELEICAO, pl.Int16).alias("ano"),
            pl.col("NR_TURNO").cast(pl.Int8).alias("turno"),
            pl.col("SG_UE").alias("cod_municipio_tse"),
            pl.col("SQ_CANDIDATO").alias("sq_candidato"),
            "votos",
        )
        .sort("turno", "cod_municipio_tse", "sq_candidato")
    )


def receitas(rec: pl.DataFrame) -> pl.DataFrame:
    """Receitas com origem, tipo de doador e documento, antes da pseudonimização.

    Mantém `nome_doador` e `cpf` para pseudonimizar; descarta linhas sem valor positivo ou data.
    """
    origem = pl.col("DS_ORIGEM_RECEITA")
    com_cpf = origem.is_in(_ORIGENS_COM_CPF)
    cpf = _documento("NR_CPF_CNPJ_DOADOR", 11)
    cnpj = _documento("NR_CPF_CNPJ_DOADOR", 14)
    rfb = pl.col("NM_DOADOR_RFB").str.strip_chars()
    return (
        rec.with_columns(
            pl.col("VR_RECEITA").str.replace(",", ".").cast(pl.Float64).alias("valor"),
            _data("DT_RECEITA").alias("data_receita"),
            pl.int_range(pl.len()).over("SQ_CANDIDATO", "SQ_RECEITA").alias("ordem"),
        )
        .filter((pl.col("valor") > 0) & pl.col("data_receita").is_not_null())
        .with_columns(
            origem.replace_strict(ORIGENS, default="OUTRA", return_dtype=ORIGEM_RECEITA).alias(
                "origem"
            ),
            pl.when(com_cpf & cpf.is_not_null())
            .then(pl.lit("PF"))
            .when(~com_cpf & cnpj.is_not_null())
            .then(pl.lit("PJ"))
            .otherwise(pl.lit("OUTRO"))
            .cast(TIPO_DOADOR)
            .alias("tipo_doador"),
            pl.when(com_cpf).then(cpf).alias("cpf"),
            pl.when(~com_cpf).then(cnpj.str.slice(0, 8)).alias("cnpj_basico"),
            pl.when(rfb.is_in(["", "#NULO", "#NE"]))
            .then(pl.col("NM_DOADOR"))
            .otherwise(rfb)
            .alias("nome_doador"),
            pl.format("{}-{}", "SQ_RECEITA", "ordem").alias("id_receita"),
        )
    )


def pseudonimos(pares: pl.DataFrame, chave: bytes) -> pl.DataFrame:
    """(nome, cpf) únicos → id_pessoa, `cpf_valido`."""
    unicos = pares.select("nome", "cpf").unique()
    return unicos.with_columns(
        pl.Series(
            "id_pessoa",
            [pseudonimo(n, c, chave) for n, c in unicos.iter_rows()],
            dtype=pl.String,
        ),
        pl.col("cpf").map_elements(cpf_valido, return_dtype=pl.Boolean).alias("cpf_valido"),
    )


@dataclass(frozen=True)
class Ingestao:
    candidatos: pl.DataFrame
    votos: pl.DataFrame
    doacoes: pl.DataFrame
    ambiguos: pl.DataFrame
    validacao: pl.DataFrame
    eleicoes_sem_eleito_unico: pl.DataFrame


def _uf(prefixo: str) -> str:
    return f"{prefixo}_{config.UF}.csv"


def ingerir(brutos: dict[str, Path], chave: bytes) -> Ingestao:
    """Lê os brutos de `ENTRADAS` e monta as tabelas pseudonimizadas e a validação."""
    sp_prefeito = _PREFEITO_SEM_CAPITAL
    cand_2020 = ler_csv(brutos["cand_2020"], _uf("consulta_cand_2020"), _COLUNAS_CAND)
    anteriores = candidaturas(
        cand_2020.filter(sp_prefeito & (_data("DT_ELEICAO") < config.DATA_ELEICAO))
    )
    de_2024 = candidaturas(
        ler_csv(
            brutos["cand_2024"], _uf("consulta_cand_2024"), _COLUNAS_CAND, sp_prefeito & _ORDINARIA
        )
    )
    coligacoes = ler_csv(
        brutos["coligacao_2024"],
        _uf("consulta_coligacao_2024"),
        ["NM_TIPO_ELEICAO", "SG_UE", "DS_CARGO", "SQ_COLIGACAO", "SG_PARTIDO", "DS_SITUACAO"],
        sp_prefeito & _ORDINARIA,
    )
    votacao = ler_csv(
        brutos["votacao_2024"],
        _uf("votacao_candidato_munzona_2024"),
        [
            "NM_TIPO_ELEICAO",
            "NR_TURNO",
            "SG_UE",
            "DS_CARGO",
            "SQ_CANDIDATO",
            "DS_SITUACAO_JULGAMENTO",
            "QT_VOTOS_NOMINAIS_VALIDOS",
        ],
        sp_prefeito & _ORDINARIA,
    )
    rec = receitas(
        ler_csv(
            brutos["contas_2024"],
            _uf("receitas_candidatos_2024"),
            _COLUNAS_RECEITA,
            sp_prefeito & _ORDINARIA,
        )
    )
    originarios = ler_csv(
        brutos["contas_2024"],
        _uf("receitas_candidatos_doador_originario_2024"),
        ["SQ_PRESTADOR_CONTAS", "SQ_RECEITA", "NR_CPF_CNPJ_DOADOR_ORIGINARIO"],
    )
    lista = ler_csv(
        brutos["suplementares_2020"],
        "lista_eleicoes_suplementares_2020.csv",
        ["CD_ELEICAO", "SG_UF", "DS_CARGO", "CD_MUNICIPIO"],
        (pl.col("SG_UF") == config.UF) & (_maiusculas("DS_CARGO") == "PREFEITO"),
    )

    titulos_2020 = cand_2020.select(
        _documento("NR_TITULO_ELEITORAL_CANDIDATO", 12).alias("titulo"),
        _documento("NR_CPF_CANDIDATO", 11).alias("cpf"),
    )
    cpfs = cpfs_de_2024(de_2024, titulos_2020, rec.filter(pl.col("origem") == "RECURSOS_PROPRIOS"))
    julgamento = votacao.group_by("SQ_CANDIDATO").agg(pl.col("DS_SITUACAO_JULGAMENTO").first())
    cand = tabela_candidatos(anteriores, de_2024, coligacoes, julgamento, cpfs.cpfs)

    pares = pl.concat(
        [
            cand.select(pl.col("NM_CANDIDATO").alias("nome"), "cpf"),
            rec.filter(pl.col("tipo_doador") == "PF").select(
                pl.col("nome_doador").alias("nome"), "cpf"
            ),
        ]
    ).drop_nulls()
    ids = pseudonimos(pares, chave)
    ambiguos = (
        ids.group_by("id_pessoa")
        .agg(pl.col("cpf").n_unique().cast(pl.Int64).alias("n_cpfs"))
        .filter(pl.col("n_cpfs") > 1)
        .sort("id_pessoa")
    )

    sem_cpf = pl.coalesce(pl.col("titulo"), pl.format("sq:{}-{}", "ano", "sq_candidato"))
    candidatos = (
        cand.join(
            ids.select("nome", "cpf", "id_pessoa"),
            left_on=["NM_CANDIDATO", "cpf"],
            right_on=["nome", "cpf"],
            how="left",
        )
        .with_columns(
            pl.coalesce(
                "id_pessoa",
                sem_cpf.map_elements(
                    lambda r: _pseudonimo_sem_cpf(r, chave), return_dtype=pl.String
                ),
            ).alias("id_pessoa")
        )
        .with_columns(
            pl.when(pl.col("titulo").is_not_null())
            .then(pl.col("id_pessoa").sort_by("data_eleicao").last().over("titulo"))
            .otherwise(pl.col("id_pessoa"))
            .alias("id_pessoa")
        )
        .select(CANDIDATOS.esquema.names())
        .sort("ano", "cod_municipio_tse", "sq_candidato")
    )

    doacoes_completas = rec.join(
        ids.select("nome", "cpf", "id_pessoa"),
        left_on=["nome_doador", "cpf"],
        right_on=["nome", "cpf"],
        how="left",
    ).with_columns(
        pl.when(pl.col("tipo_doador") == "PF")
        .then(pl.col("id_pessoa"))
        .when(pl.col("tipo_doador") == "PJ")
        .then(pl.col("cnpj_basico"))
        .alias("id_doador")
    )
    doacoes = doacoes_completas.select(
        pl.lit(config.ANO_ELEICAO, pl.Int16).alias("ano"),
        pl.col("SQ_CANDIDATO").alias("sq_candidato"),
        pl.col("SG_UE").alias("cod_municipio_tse"),
        "id_receita",
        "id_doador",
        "tipo_doador",
        "origem",
        "data_receita",
        "valor",
    ).sort("sq_candidato", "id_receita")

    sem_eleito_unico = (
        candidatos.filter(
            (pl.col("data_eleicao") < config.DATA_ELEICAO) | (pl.col("ano") == config.ANO_ELEICAO)
        )
        .group_by("cod_municipio_tse", "data_eleicao", "tipo_eleicao")
        .agg(pl.col("eleito").fill_null(False).sum().alias("eleitos"))
        .filter(pl.col("eleitos") != 1)
        .sort("data_eleicao", "cod_municipio_tse")
    )
    validacao = _validacao(
        candidatos,
        tabela_votos(votacao),
        doacoes_completas,
        ids,
        ambiguos,
        cpfs,
        de_2024,
        anteriores,
        lista,
        originarios.join(
            rec.select("SQ_PRESTADOR_CONTAS", "SQ_RECEITA").unique(),
            on=["SQ_PRESTADOR_CONTAS", "SQ_RECEITA"],
            how="semi",
        ),
        sem_eleito_unico,
    )
    return Ingestao(
        candidatos, tabela_votos(votacao), doacoes, ambiguos, validacao, sem_eleito_unico
    )


def _validacao(
    candidatos: pl.DataFrame,
    votos: pl.DataFrame,
    doacoes: pl.DataFrame,
    ids: pl.DataFrame,
    ambiguos: pl.DataFrame,
    cpfs: CpfsDe2024,
    de_2024: pl.DataFrame,
    anteriores: pl.DataFrame,
    lista: pl.DataFrame,
    originarios: pl.DataFrame,
    sem_eleito_unico: pl.DataFrame,
) -> pl.DataFrame:
    """Contagens da ingestão em formato longo (indicador, recorte, valor)."""
    linhas: list[tuple[str, str | None, float]] = [
        ("candidatos", f"{ano} {tipo}", n)
        for ano, tipo, n in candidatos.group_by("ano", "tipo_eleicao")
        .len()
        .sort("ano", "tipo_eleicao")
        .iter_rows()
    ]
    suplementares = candidatos.filter(pl.col("tipo_eleicao") == "SUPLEMENTAR")
    for ano, n in (
        suplementares.select("ano", "cod_municipio_tse", "data_eleicao")
        .unique()
        .group_by("ano")
        .len()
        .sort("ano")
        .iter_rows()
    ):
        linhas.append(("eleicoes_suplementares_carregadas", str(ano), n))
    linhas.append(("eleicoes_suplementares_na_lista_oficial", None, lista.height))
    ordinaria_2024 = candidatos.filter(
        (pl.col("ano") == config.ANO_ELEICAO) & (pl.col("tipo_eleicao") == "ORDINARIA")
    )
    linhas += [
        ("municipios_2024", None, ordinaria_2024["cod_municipio_tse"].n_unique()),
        (
            "municipios_segundo_turno_2024",
            None,
            votos.filter(pl.col("turno") == 2)["cod_municipio_tse"].n_unique(),
        ),
        ("eleicoes_sem_eleito_unico", None, sem_eleito_unico.height),
    ]
    for fonte in ("TITULO_2020", "RECURSOS_PROPRIOS", "TITULO_E_PROPRIOS", "CONFLITO", "SEM_CPF"):
        linhas.append(("cpf_candidato_2024", fonte, cpfs.contagens.get(fonte, 0)))
    linhas.append(
        (
            "cpf_candidato_anterior",
            "SEM_CPF",
            anteriores.filter(pl.col("cpf").is_null()).height,
        )
    )
    mesmo_titulo = de_2024.select("titulo", n24=_normalizado("NM_CANDIDATO")).join(
        anteriores.select("titulo", n20=_normalizado("NM_CANDIDATO")), on="titulo"
    )
    linhas.append(
        (
            "candidato_2024_com_nome_diferente_do_anterior",
            None,
            mesmo_titulo.filter(pl.col("n24") != pl.col("n20"))["titulo"].n_unique(),
        )
    )
    for origem, n in doacoes.group_by("origem").len().sort("origem").iter_rows():
        linhas.append(("receitas", str(origem), n))
    pf = doacoes.filter(pl.col("tipo_doador") == "PF")
    terceiros = pf.filter(pl.col("origem") == "PESSOA_FISICA")
    id_candidato = candidatos.select(
        pl.col("sq_candidato").alias("SQ_CANDIDATO"), pl.col("id_pessoa").alias("id_candidato")
    )
    linhas += [
        (
            "receitas_apos_limite",
            str(config.DATA_LIMITE_DOACAO),
            doacoes.filter(pl.col("data_receita") > config.DATA_LIMITE_DOACAO).height,
        ),
        (
            "receitas_pessoa_fisica_sem_cpf",
            None,
            doacoes.filter(
                (pl.col("origem") == "PESSOA_FISICA") & (pl.col("tipo_doador") != "PF")
            ).height,
        ),
        ("doadores_pf_distintos", None, terceiros["id_doador"].n_unique()),
        (
            "doadores_pf_sem_nome_rfb",
            None,
            terceiros.filter(pl.col("NM_DOADOR_RFB").str.strip_chars().is_in(["", "#NULO", "#NE"]))[
                "id_doador"
            ].n_unique(),
        ),
        (
            "receitas_pf_de_terceiros_feitas_pelo_proprio_candidato",
            None,
            terceiros.join(id_candidato, on="SQ_CANDIDATO")
            .filter(pl.col("id_doador") == pl.col("id_candidato"))
            .height,
        ),
        ("cpfs_com_digito_verificador_invalido", None, ids.filter(~pl.col("cpf_valido")).height),
        ("pseudonimos", None, ids["id_pessoa"].n_unique()),
        ("pseudonimos_com_mais_de_um_cpf", None, ambiguos.height),
        (
            "doadores_originarios_pf_distintos",
            None,
            originarios.select(_documento("NR_CPF_CNPJ_DOADOR_ORIGINARIO", 11).alias("c"))
            .drop_nulls()["c"]
            .n_unique(),
        ),
    ]
    return pl.DataFrame(
        linhas,
        schema={"indicador": pl.String, "recorte": pl.String, "valor": pl.Float64},
        orient="row",
    )


def suprimir(validacao: pl.DataFrame) -> pl.DataFrame:
    """Contagens entre 1 e `SUPRESSAO_MINIMA - 1` saem nulas na tabela versionada."""
    valor = pl.col("valor")
    return validacao.with_columns(
        pl.when((valor > 0) & (valor < config.SUPRESSAO_MINIMA))
        .then(None)
        .otherwise(valor)
        .alias("valor")
    )


def _conferir(ingestao: Ingestao) -> None:
    repetidos = ingestao.candidatos.filter(pl.struct("ano", "sq_candidato").is_duplicated())
    if not repetidos.is_empty():
        raise ValueError(f"ingest-tse: sq_candidato repetido no ano ({repetidos.height} linhas)")
    if not ingestao.eleicoes_sem_eleito_unico.is_empty():
        print(
            "aviso: eleições de prefeito sem exatamente um eleito "
            "(município, data, tipo, eleitos):",
            file=sys.stderr,
        )
        for linha in ingestao.eleicoes_sem_eleito_unico.iter_rows():
            print(f"  {linha}", file=sys.stderr)


def executar(ctx: Contexto) -> None:
    brutos = {nome: garantir(ARQUIVOS[chave], ctx.caminhos) for nome, chave in ENTRADAS.items()}
    ingestao = ingerir(brutos, carregar_chave(ctx.caminhos.chave))
    _conferir(ingestao)
    ctx.gravar(CANDIDATOS, ingestao.candidatos)
    ctx.gravar(VOTOS, ingestao.votos)
    ctx.gravar(DOACOES, ingestao.doacoes)
    ctx.gravar(PSEUDONIMOS_AMBIGUOS, ingestao.ambiguos)
    tabelas = ctx.caminhos.resultados / "tables"
    tabelas.mkdir(parents=True, exist_ok=True)
    suprimir(ingestao.validacao).write_csv(tabelas / ARQUIVO_VALIDACAO)
    print(ingestao.validacao, file=sys.stderr)
    for chave in ENTRADAS.values():
        descartar(ARQUIVOS[chave], ctx.caminhos)
