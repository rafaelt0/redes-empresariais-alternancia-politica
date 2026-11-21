"""Etapa `ingest-tcesp`: eventos de empenho, licitações e ajustes, municípios (T06).

Despesas. `despesas-AAAA.zip` traz um CSV de até 16 GB (latin-1, `;`, sem aspas, decimal com
vírgula, data dd/mm/aaaa), lido em fluxo de dentro do zip em blocos de `BLOCO` bytes cortados
na quebra de linha. Cada linha é um evento da despesa: `tp_despesa` vale Empenhado, Reforço,
Anulação, Valor Liquidado ou Valor Pago, e só os três primeiros entram (seção 5 do projeto).
O empenho é identificado por município, órgão e `nr_empenho` ("N-AAAA"): a numeração recomeça
em cada órgão (prefeitura, câmara, autarquias, fundos) do mesmo município.

Cada ano vira um Parquet parcial em `dados/tcesp/` (com as contagens ao lado); a etapa só
refaz o ano cujo parcial falta, é de outra `VERSAO` ou é mais velho que o zip. Em modo estrito,
refaz todos os parciais a partir dos ZIPs verificados e recompõe as tabelas de ajustes.

Mercado. `ds_elemento` traz a natureza da despesa até o subelemento, em 8 dígitos
(categoria, grupo, modalidade em 2, elemento em 2, subelemento em 2: 33903999 é 3.3.90.39.99).
O "elemento de despesa" da especificação é a leitura literal, os dígitos 5 e 6 (30 material de
consumo, 39 serviços de terceiros PJ, 51 obras); a natureza completa fica em `natureza_despesa`.

Licitações e ajustes. Só as linhas de instrumento "Nota de Empenho" dos `ajustes-*.zip` trazem o
número da nota; as de "Contrato" não trazem, e por isso só se ligam empenhos cujo ajuste é a
própria nota. A ligação é determinística: município, órgão (nome normalizado igual a `Entidade`),
número da nota sem zeros à esquerda e ano da data da nota, exatamente a chave de `id_empenho`,
e o mesmo CNPJ básico do credor. Não há ligação aproximada.
"""

import csv
import hashlib
import io
import json
import os
import re
import urllib.request
import zipfile
from collections.abc import Iterable, Iterator
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

import polars as pl
import pyarrow.parquet as pq

from redes import config, descritivas, fetch, pseudonimo, schemas
from redes.config import Caminhos
from redes.etapas import Contexto, Etapa
from redes.fontes import ARQUIVOS, Arquivo
from redes.portabilidade import trava_exclusiva
from redes.pseudonimo import normalizar_nome
from redes.schemas import EMPENHOS, EVENTO, LICITACOES, MUNICIPIOS, TIPO_ORGAO, Tabela

ETAPA = Etapa(
    nome="ingest-tcesp",
    depende=(),
    le=(),
    grava=(EMPENHOS, LICITACOES, MUNICIPIOS),
    artefatos=("dados/tcesp/", "resultados/tables/validacao_tcesp.csv"),
)

VERSAO = 2
BLOCO = 64 << 20

CABECALHO_DESPESAS = (
    "id_despesa_detalhe", "ano_exercicio", "ds_municipio", "codigo_municipio_ibge", "ds_orgao",
    "mes_referencia", "mes_ref_extenso", "tp_despesa", "nr_empenho", "tp_identificador_despesa",
    "nr_identificador_despesa", "ds_despesa", "dt_emissao_despesa", "vl_despesa",
    "ds_funcao_governo", "ds_subfuncao_governo", "cd_programa", "ds_programa", "cd_acao",
    "ds_acao", "ds_fonte_recurso", "ds_cd_aplicacao_fixo", "ds_modalidade_lic", "ds_elemento",
    "historico_despesa",
)  # fmt: skip

EVENTOS = {"Empenhado": "EMISSAO", "Reforço": "REFORCO", "Anulação": "ANULACAO"}
FORA_DE_ESCOPO = ("Valor Liquidado", "Valor Pago")
CREDOR_PJ = "CNPJ - PESSOA JURÍDICA"
CREDOR_PF = "PESSOA FÍSICA"

PARCIAL = pl.Schema(
    {
        "id_evento": pl.String,
        "id_empenho": pl.String,
        "evento": EVENTO,
        "data": pl.Date,
        "cod_ibge": pl.String,
        "municipio": pl.String,
        "orgao": pl.String,
        "cnpj_basico": pl.String,
        "natureza_despesa": pl.String,
        "elemento_despesa": pl.String,
        "valor": pl.Float64,
        "credor_publico": pl.Boolean,
    }
)
"""`credor_publico` não vai para `empenhos`: serve à decisão sobre o escopo de fornecedores."""

CREDOR_PUBLICO = (
    r"\bPREFEITURA\b|\bCAMARA MUNICIPAL\b|\bMUNICIPIO D|\bPM\b|PREVID|\bPREV\b|SEGURIDADE|"
    r"SEG SOCIAL|\bFUNDO (MUNICIPAL|ESPECIAL|NACIONAL|ESTADUAL|DE)\b|\bSECRETARIA\b|"
    r"INSTITUTO NACIONAL DO SEGURO SOCIAL|INSTITUTO NACIONAL SEGURIDADE|\bINSS\b|"
    r"RECEITA FEDERAL|MINISTERIO|\bFAZENDA\b|\bGOVERNO DO ESTADO|\bESTADO DE SAO PAULO\b|"
    r"\bTRIBUNAL\b|\bPODER JUDICIARIO|\bUNIAO\b|SERVICO AUTONOMO|\bSAAE\b|"
    r"DEPARTAMENTO DE AGUA|\bDAE\b|\bAUTARQUIA\b|CONSORCIO INTERMUNICIPAL|CONSORCIO PUBLICO|"
    r"\bFUNDACAO MUNICIPAL|\bPASEP\b|\bTESOURO\b|\bDETRAN\b|SPPREV|\bASSEMBLEIA LEGISLATIVA|"
    r"UNIVERSIDADE (ESTADUAL|FEDERAL)|DEFENSORIA|MINISTERIO PUBLICO"
)
"""Ente público pelo nome do credor (normalizado). Classificação aproximada, só para o relatório
de escopo em `validacao_tcesp.csv`; a natureza jurídica da Receita (`empresas`) é a fonte exata."""

TIPOS_DE_ORGAO: tuple[tuple[str, str], ...] = (
    ("CAMARA", r"\bCAMARA\b"),
    ("PREVIDENCIA", r"PREVID|\bPREV\b|SEGURIDADE|APOSENT|\bIPREM\b|\bRPPS\b"),
    ("PREFEITURA", r"\bPREFEITURA\b"),
)
"""Em ordem: o primeiro padrão que casa com o nome normalizado do órgão decide; o resto é
AUTARQUIA_OU_OUTRA (autarquias de água e esgoto, fundações, faculdades, empresas municipais)."""

UF_SP = "SP"
ESQUEMA_CONTAGENS = pl.Schema(
    {"medida": pl.String, "ano": pl.Int16, "categoria": pl.String, "valor": pl.Float64}
)


class DadoInesperado(RuntimeError):
    pass


@dataclass(frozen=True)
class Contagem:
    medida: str
    ano: int | None
    categoria: str
    valor: float


def executar(ctx: Contexto) -> None:
    caminhos = ctx.caminhos
    pasta = caminhos.dados / "tcesp"
    contagens: list[Contagem] = []
    for ano in config.ANOS_EMPENHO:
        contagens += parcial_do_ano(ano, caminhos, pasta)

    parciais = pl.scan_parquet([_parcial(pasta, a) for a in config.ANOS_EMPENHO])
    zip_tse = fetch.garantir(ARQUIVOS[FONTE_TSE_IBGE], caminhos)
    municipios, sem_tse = montar_municipios(parciais, ler_municipios_tse(zip_tse))
    contagens.append(Contagem("municipio_tcesp_sem_tse", None, "total", len(sem_tse)))

    notas, licitacoes, cont = ajustes_em_cache(caminhos, pasta, parciais, municipios, zip_tse)
    contagens += cont

    empenhos = montar_empenhos(parciais, municipios, notas)
    _gravar_em_fluxo(empenhos, EMPENHOS, ctx.caminho(EMPENHOS))
    ctx.gravar(MUNICIPIOS, municipios)
    ctx.gravar(LICITACOES, licitacoes)
    contagens += resumo(pl.scan_parquet(ctx.caminho(EMPENHOS)), parciais, licitacoes)

    tabelas = caminhos.resultados / "tables"
    tabelas.mkdir(parents=True, exist_ok=True)
    validacao = pl.DataFrame(
        [(c.medida, c.ano, c.categoria, c.valor) for c in contagens],
        schema=ESQUEMA_CONTAGENS,
        orient="row",
    )
    validacao_publica(validacao).write_csv(tabelas / "validacao_tcesp.csv")


def _ocultar_taxas_de_vinculacao(tabela: pl.DataFrame) -> pl.DataFrame:
    medida = pl.col("medida")
    valor = pl.col("valor")
    taxa = medida == "vinculacao_empenhos"
    taxas = (
        tabela.filter(taxa | ((medida == "empenhos") & (pl.col("categoria") == "total")))
        .group_by("ano")
        .agg(
            total=valor.filter(medida == "empenhos").first(),
            taxa_ligados=valor.filter(taxa & (pl.col("categoria") == "ligados")).first(),
            taxa_novos=valor.filter(taxa & (pl.col("categoria") == "novos")).first(),
        )
        .with_columns(
            ligados=(pl.col("taxa_ligados") * pl.col("total")).round(),
            novos=(pl.col("taxa_novos") * pl.col("total")).round(),
        )
    )
    ligados, novos, total = pl.col("ligados"), pl.col("novos"), pl.col("total")
    minimo = config.SUPRESSAO_MINIMA
    alertas = taxas.select(
        "ano",
        ocultar_ligados=ligados.is_between(1, minimo - 1)
        | (total - ligados).is_between(1, minimo - 1),
        ocultar_novos=(
            novos.is_between(1, minimo - 1)
            | (ligados - novos).is_between(1, minimo - 1)
            | (total - novos).is_between(1, minimo - 1)
        ),
    )
    ocultar = medida.is_in(("vinculacao_empenhos", "vinculacao_valor")) & (
        ((pl.col("categoria") == "ligados") & pl.col("ocultar_ligados"))
        | ((pl.col("categoria") == "novos") & pl.col("ocultar_novos"))
    )
    return (
        tabela.join(alertas, on="ano", how="left", maintain_order="left")
        .with_columns(pl.when(~ocultar.fill_null(False)).then(valor).alias("valor"))
        .drop("ocultar_ligados", "ocultar_novos")
    )


def validacao_publica(tabela: pl.DataFrame) -> pl.DataFrame:
    """Suprime contagens pequenas, seus valores e uma célula complementar da partição."""
    medida = pl.col("medida")
    nomes_de_municipios = ("municipio_tcesp_sem_tse", "ajustes_municipio_sem_correspondencia")
    tabela = (
        tabela.with_columns(
            pl.when(medida.is_in(nomes_de_municipios))
            .then(pl.lit("total"))
            .otherwise(pl.col("categoria"))
            .alias("categoria")
        )
        .group_by("medida", "ano", "categoria", maintain_order=True)
        .agg(pl.when(pl.col("valor").count() > 0).then(pl.col("valor").sum()).alias("valor"))
    )
    tabela = _ocultar_taxas_de_vinculacao(tabela)
    grupos = ("eventos", "eventos_por_elemento_despesa", "eventos_por_tipo_orgao", "descarte")
    pequenas = pl.col("valor").is_between(1, config.SUPRESSAO_MINIMA - 1)
    comparavel = pl.col("valor") >= config.SUPRESSAO_MINIMA
    particao = ["medida", "ano"]
    complemento = pl.col("valor").filter(comparavel).min().over(particao)
    pequenos = tabela.filter(
        medida.is_in(grupos)
        & (pequenas | (pequenas.any().over(particao) & (pl.col("valor") == complemento)))
    ).with_columns(
        medida_monetaria=pl.when(medida == "descarte")
        .then(pl.lit("descarte_valor"))
        .otherwise(medida.str.replace("^eventos", "valor"))
    )
    ocultar = (
        pequenos.unpivot(
            index=["ano", "categoria"],
            on=["medida", "medida_monetaria"],
            value_name="medida_oculta",
        )
        .select(
            pl.col("medida_oculta").alias("medida"),
            "ano",
            "categoria",
            pl.lit(True).alias("suprimir"),
        )
        .unique()
    )
    chave = ["medida", "ano", "categoria"]
    return (
        tabela.join(ocultar, on=chave, how="left", nulls_equal=True, maintain_order="left")
        .with_columns(
            pl.when(pl.col("suprimir").fill_null(False))
            .then(None)
            .when(~medida.str.contains(r"^(valor($|_)|descarte_valor$|escopo_|vinculacao_)"))
            .then(descritivas.suprimir("valor"))
            .otherwise(pl.col("valor"))
            .alias("valor")
        )
        .drop("suprimir")
    )


FONTE_TSE_IBGE = "tse-municipios/municipio_tse_ibge.zip"


def ajustes_em_cache(
    caminhos: Caminhos,
    pasta: Path,
    parciais: pl.LazyFrame,
    municipios: pl.DataFrame,
    tabela_tse: Path,
) -> tuple[pl.DataFrame, pl.DataFrame, list[Contagem]]:
    """Reutiliza o resultado só quando os ZIPs e os parciais de despesas conferem."""
    zips = [fetch.garantir(a, caminhos) for a in arquivos_de_ajustes()]
    fontes = [*zips, tabela_tse, *(_parcial(pasta, ano) for ano in config.ANOS_EMPENHO)]
    inspetor = pasta / f"ajustes-fontes.v{VERSAO}.json"
    assinatura = {
        str(f.relative_to(caminhos.dados)): [f.stat().st_size, f.stat().st_mtime_ns] for f in fontes
    }
    for modulo in (Path(__file__), Path(pseudonimo.__file__)):
        assinatura[f"codigo:{modulo.name}"] = [modulo.stat().st_size, modulo.stat().st_mtime_ns]
    arquivos = {
        nome: pasta / f"ajustes-{nome}.v{VERSAO}.{ext}"
        for nome, ext in (("notas", "parquet"), ("licitacoes", "parquet"), ("contagens", "csv"))
    }
    estrito = os.environ.get("REDES_ESTRITO") == "1"
    anterior = None
    if not estrito:
        with suppress(FileNotFoundError, ValueError):
            anterior = json.loads(inspetor.read_text(encoding="utf-8"))
    if estrito or anterior != assinatura or not all(a.exists() for a in arquivos.values()):
        inspetor.unlink(missing_ok=True)
        ajustes = (ler_ajustes(z) for z in zips)
        notas, licitacoes, contagens = montar_ajustes(ajustes, parciais, municipios)
        notas.write_parquet(arquivos["notas"])
        licitacoes.write_parquet(arquivos["licitacoes"])
        _contagens_para_frame(contagens).write_csv(arquivos["contagens"])
        provisoria = inspetor.with_suffix(".tmp")
        provisoria.write_text(json.dumps(assinatura, sort_keys=True), encoding="utf-8")
        provisoria.replace(inspetor)
    contagens = [
        Contagem(*linha)
        for linha in pl.read_csv(arquivos["contagens"], schema=ESQUEMA_CONTAGENS).iter_rows()
    ]
    return (
        pl.read_parquet(arquivos["notas"]),
        pl.read_parquet(arquivos["licitacoes"]).match_to_schema(LICITACOES.esquema),
        contagens,
    )


def arquivos_de_ajustes() -> list[Arquivo]:
    return [
        a for a in ARQUIVOS.values() if a.fonte == "tcesp-licitacoes" and a.nome.startswith("ajust")
    ]


# Despesas -----------------------------------------------------------------------------------


def _parcial(pasta: Path, ano: int) -> Path:
    return pasta / f"empenhos-{ano}.v{VERSAO}.parquet"


def _contagens_parcial(pasta: Path, ano: int) -> Path:
    return pasta / f"contagens-{ano}.v{VERSAO}.csv"


def parcial_do_ano(ano: int, caminhos: Caminhos, pasta: Path) -> list[Contagem]:
    """Grava o parcial do ano, se falta ou está velho, e devolve as contagens dele."""
    arquivo = ARQUIVOS[f"tcesp-despesas/despesas-{ano}.zip"]
    destino, lateral = _parcial(pasta, ano), _contagens_parcial(pasta, ano)
    pasta.mkdir(parents=True, exist_ok=True)
    with trava_exclusiva(destino.with_suffix(".trava")):
        zip_ = fetch.garantir(arquivo, caminhos)
        entradas = (zip_, Path(__file__), Path(pseudonimo.__file__))
        valido = (
            os.environ.get("REDES_ESTRITO") != "1"
            and destino.exists()
            and lateral.exists()
            and lateral.stat().st_mtime_ns
            >= destino.stat().st_mtime_ns
            > max(f.stat().st_mtime_ns for f in entradas)
        )
        if not valido:
            # O CSV confirma que as duas saídas foram gravadas para o mesmo parcial.
            lateral.unlink(missing_ok=True)
            contagens = processar_despesas(zip_, ano, destino)
            temporario = lateral.with_suffix(".csv.tmp")
            _contagens_para_frame(contagens).write_csv(temporario)
            temporario.replace(lateral)
            fetch.descartar(arquivo, caminhos)
        return [
            Contagem(*linha) for linha in pl.read_csv(lateral, schema=ESQUEMA_CONTAGENS).iter_rows()
        ]


def processar_despesas(zip_: Path, ano: int, destino: Path) -> list[Contagem]:
    temporario = destino.with_name(destino.name + ".tmp")
    acumulado: pl.DataFrame | None = None
    escritor: pq.ParquetWriter | None = None
    try:
        for bruto in ler_blocos(zip_):
            mantidos, contagens = eventos_de_empenho(bruto, ano)
            acumulado = contagens if acumulado is None else acumulado.vstack(contagens)
            tabela = mantidos.to_arrow()
            if escritor is None:
                escritor = pq.ParquetWriter(temporario, tabela.schema)
            escritor.write_table(tabela)
    finally:
        if escritor is not None:
            escritor.close()
    if escritor is None or acumulado is None:
        raise DadoInesperado(f"{zip_.name}: CSV vazio")
    temporario.replace(destino)
    resumo_ = (
        acumulado.group_by("medida", "categoria")
        .agg(pl.col("valor").sum())
        .sort("medida", "categoria")
    )
    return [Contagem(m, ano, c, v) for m, c, v in resumo_.iter_rows()]


def ler_blocos(zip_: Path, tamanho: int = BLOCO) -> Iterator[pl.DataFrame]:
    """Linhas do CSV do zip, como texto, em blocos; confere o cabeçalho antes de tudo."""
    with zipfile.ZipFile(zip_) as z:
        (membro,) = z.namelist()
        with z.open(membro) as entrada:
            cabecalho = entrada.readline().decode("latin-1").rstrip("\r\n").split(";")
            if tuple(cabecalho) != CABECALHO_DESPESAS:
                raise DadoInesperado(f"{zip_.name}: cabeçalho diferente do esperado: {cabecalho}")
            resto = b""
            while bloco := entrada.read(tamanho):
                bloco = resto + bloco
                corte = bloco.rfind(b"\n") + 1
                resto = bloco[corte:]
                if corte:
                    yield _parse(bloco[:corte])
            if resto.strip():
                yield _parse(resto)


def _parse(dados: bytes) -> pl.DataFrame:
    return pl.read_csv(
        io.BytesIO(dados.decode("latin-1").encode()),
        separator=";",
        has_header=False,
        new_columns=list(CABECALHO_DESPESAS),
        schema_overrides=dict.fromkeys(CABECALHO_DESPESAS, pl.String),
        infer_schema=False,
        quote_char=None,
        truncate_ragged_lines=True,
        extra_columns="ignore",
    )


def _cnpj_valido(coluna: str) -> pl.Expr:
    """14 dígitos, dígitos verificadores corretos e não todos iguais."""
    d = [pl.col(coluna).str.slice(i, 1).cast(pl.Int32, strict=False) for i in range(14)]

    def dv(pesos: list[int]) -> pl.Expr:
        resto = pl.sum_horizontal(p * x for p, x in zip(pesos, d, strict=False)) % 11
        return pl.when(resto < 2).then(0).otherwise(11 - resto)

    return (
        pl.col(coluna).str.contains(r"^\d{14}$")
        & ~pl.col(coluna).is_in([str(i) * 14 for i in range(10)])
        & (dv([5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]) == d[12])
        & (dv([6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]) == d[13])
    )


MOTIVOS_DE_DESCARTE = (
    "linha_malformada",
    "credor_pessoa_fisica",
    "credor_sem_cnpj",
    "cnpj_invalido",
    "elemento_invalido",
    "data_fora_do_ano",
    "valor_negativo",
)


def eventos_de_empenho(bruto: pl.DataFrame, ano: int) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Eventos de empenho com credor PJ válido e contagens (`medida`, `categoria`, `valor`).

    O valor sai com o sinal do esquema: a anulação vem positiva no TCESP e vira negativa.
    """
    nr = pl.col("nr_empenho").str.strip_chars().str.extract_groups(r"^0*(\d+)-(\d{4})$")
    tabela = bruto.lazy().with_columns(
        pl.col("tp_despesa").replace_strict(EVENTOS, default=None).alias("evento"),
        pl.col("dt_emissao_despesa").str.strptime(pl.Date, "%d/%m/%Y", strict=False).alias("data"),
        pl.col("vl_despesa")
        .str.replace(",", ".", literal=True)
        .cast(pl.Float64, strict=False)
        .alias("v"),
        pl.col("nr_identificador_despesa").str.strip_chars().alias("doc"),
        pl.col("ds_elemento").str.extract(r"^(\d{8})\b").alias("natureza_despesa"),
        nr.struct.field("1").alias("numero"),
        nr.struct.field("2").alias("ano_empenho"),
    )
    motivo = (
        pl.when(
            ~pl.col("id_despesa_detalhe").str.contains(r"^\d+$")
            | pl.col("data").is_null()
            | pl.col("v").is_null()
            | pl.col("numero").is_null()
            | ~pl.col("codigo_municipio_ibge").str.contains(r"^\d{7}$")
            | pl.col("ds_orgao").is_null()
        )
        .then(pl.lit("linha_malformada"))
        .when(pl.col("tp_identificador_despesa") == CREDOR_PF)
        .then(pl.lit("credor_pessoa_fisica"))
        .when(pl.col("tp_identificador_despesa") != CREDOR_PJ)
        .then(pl.lit("credor_sem_cnpj"))
        .when(~_cnpj_valido("doc").fill_null(False))
        .then(pl.lit("cnpj_invalido"))
        .when(pl.col("natureza_despesa").is_null())
        .then(pl.lit("elemento_invalido"))
        .when(pl.col("data").dt.year() != ano)
        .then(pl.lit("data_fora_do_ano"))
        .when(pl.col("v") < 0)
        .then(pl.lit("valor_negativo"))
        .alias("motivo")
    )
    tabela = tabela.with_columns(motivo).collect()

    tp = pl.col("tp_despesa").fill_null("(nulo)")
    contagens = pl.concat(
        [
            tabela.select(
                pl.lit("linhas_lidas").alias("medida"),
                tp.alias("categoria"),
                pl.lit(1.0).alias("valor"),
            ),
            tabela.filter(pl.col("evento").is_not_null() & pl.col("motivo").is_not_null()).select(
                pl.lit("descarte").alias("medida"),
                pl.format("{}|{}", "evento", "motivo").alias("categoria"),
                pl.lit(1.0).alias("valor"),
            ),
            tabela.filter(pl.col("evento").is_not_null() & pl.col("motivo").is_not_null()).select(
                pl.lit("descarte_valor").alias("medida"),
                pl.format("{}|{}", "evento", "motivo").alias("categoria"),
                pl.col("v").fill_null(0.0).alias("valor"),
            ),
        ]
    )
    contagens = contagens.group_by("medida", "categoria").agg(pl.col("valor").sum())

    mantidos = tabela.filter(pl.col("evento").is_not_null() & pl.col("motivo").is_null())
    chaves = _chaves_de_orgao(mantidos["ds_orgao"].unique().to_list())
    publicos = _credores_publicos(mantidos["ds_despesa"].fill_null("").unique().to_list())
    mantidos = mantidos.select(
        pl.col("id_despesa_detalhe").alias("id_evento"),
        pl.concat_str(
            pl.col("codigo_municipio_ibge"),
            pl.col("ds_orgao").replace_strict(chaves),
            pl.col("numero"),
            pl.col("ano_empenho"),
            separator="-",
        ).alias("id_empenho"),
        pl.col("evento").cast(EVENTO),
        "data",
        pl.col("codigo_municipio_ibge").alias("cod_ibge"),
        pl.col("ds_municipio").alias("municipio"),
        pl.col("ds_orgao").alias("orgao"),
        pl.col("doc").str.slice(0, 8).alias("cnpj_basico"),
        "natureza_despesa",
        pl.col("natureza_despesa").str.slice(4, 2).alias("elemento_despesa"),
        pl.when(pl.col("evento") == "ANULACAO")
        .then(-pl.col("v"))
        .otherwise(pl.col("v"))
        .alias("valor"),
        pl.col("ds_despesa").fill_null("").replace_strict(publicos).alias("credor_publico"),
    )
    return mantidos.match_to_schema(PARCIAL), contagens


_CACHE_CREDOR: dict[str, bool] = {}


def _credores_publicos(nomes: Iterable[str]) -> dict[str, bool]:
    for n in nomes:
        if n not in _CACHE_CREDOR:
            _CACHE_CREDOR[n] = re.search(CREDOR_PUBLICO, normalizar_nome(n)) is not None
    return {n: _CACHE_CREDOR[n] for n in nomes}


def chave_de_orgao(orgao: str) -> str:
    """8 hexadecimais estáveis do nome normalizado; a mesma função serve despesas e ajustes."""
    return hashlib.sha1(normalizar_nome(orgao).encode()).hexdigest()[:8]


_CACHE_ORGAO: dict[str, str] = {}


def _chaves_de_orgao(orgaos: Iterable[str]) -> dict[str, str]:
    for o in orgaos:
        if o not in _CACHE_ORGAO:
            _CACHE_ORGAO[o] = chave_de_orgao(o)
    return {o: _CACHE_ORGAO[o] for o in orgaos}


def tipo_de_orgao(orgao: str) -> str:
    nome = normalizar_nome(orgao)
    for tipo, padrao in TIPOS_DE_ORGAO:
        if re.search(padrao, nome):
            return tipo
    return "AUTARQUIA_OU_OUTRA"


def _contagens_para_frame(contagens: list[Contagem]) -> pl.DataFrame:
    return pl.DataFrame(
        [(c.medida, c.ano, c.categoria, c.valor) for c in contagens],
        schema=ESQUEMA_CONTAGENS,
        orient="row",
    )


# Municípios ---------------------------------------------------------------------------------


def ler_municipios_tse(zip_: Path) -> pl.DataFrame:
    with zipfile.ZipFile(zip_) as z:
        (membro,) = [n for n in z.namelist() if n.endswith(".csv")]
        dados = z.read(membro).decode("latin-1").encode()
    tabela = pl.read_csv(io.BytesIO(dados), separator=";", infer_schema=False)
    return tabela.filter(pl.col("SG_UF") == UF_SP).select(
        pl.col("CD_MUNICIPIO_TSE").str.zfill(5).alias("cod_municipio_tse"),
        pl.col("CD_MUNICIPIO_IBGE").str.zfill(7).alias("cod_ibge"),
        pl.col("NM_MUNICIPIO_TSE").alias("nome_tse"),
    )


def montar_municipios(parciais: pl.LazyFrame, tse: pl.DataFrame) -> tuple[pl.DataFrame, list[str]]:
    """Um município por código IBGE do TCESP, com o nome do ano mais recente; a capital não vem."""
    tcesp = (
        parciais.select("cod_ibge", "municipio", pl.col("data").dt.year().alias("ano"))
        .unique()
        .sort("ano")
        .group_by("cod_ibge")
        .agg(pl.col("municipio").last())
        .collect()
    )
    juntos = tcesp.join(tse, on="cod_ibge", how="left")
    sem_tse = juntos.filter(pl.col("cod_municipio_tse").is_null())
    municipios = juntos.filter(pl.col("cod_municipio_tse").is_not_null()).select(
        "cod_municipio_tse",
        pl.col("municipio").alias("id_municipio_tcesp"),
        "cod_ibge",
        pl.col("municipio").alias("nome"),
    )
    rotulos = [f"{c} {m}" for c, m in sem_tse.select("cod_ibge", "municipio").iter_rows()]
    return municipios.sort("cod_municipio_tse").match_to_schema(MUNICIPIOS.esquema), rotulos


# Ajustes ------------------------------------------------------------------------------------

COLUNAS_AJUSTES = {
    "Município": "municipio",
    "Entidade": "orgao",
    "Código do Ajuste": "codigo_ajuste",
    "Instrumento": "instrumento",
    "Nota de Empenho/Documento Similar": "nota",
    "Data da Nota de Empenho/Documento Similar": "data_nota",
    "Valor da Nota de Empenho/Documento Similar": "valor_nota",
    "CNPJ da empresa contratada": "cnpj",
    "Valor total do contrato": "valor_contrato",
    "Vigência do contrato - Data Assinatura": "data_assinatura",
    "Vigência do contrato - Data início": "data_inicio",
}


def ler_ajustes(zip_: Path, lote: int = 50_000) -> pl.DataFrame:
    """Só as colunas de `COLUNAS_AJUSTES`, lidas em fluxo do zip (o objeto tem quebras de linha
    entre aspas, por isso o leitor é o `csv` e não um corte por linha)."""
    with zipfile.ZipFile(zip_) as z:
        (membro,) = z.namelist()
        with z.open(membro) as bruto:
            texto = io.TextIOWrapper(bruto, encoding="utf-8", errors="replace", newline="")
            leitor = csv.reader(texto, delimiter=";")
            cabecalho = next(leitor)
            faltam = [c for c in COLUNAS_AJUSTES if c not in cabecalho]
            if faltam:
                raise DadoInesperado(f"{zip_.name}: faltam colunas {faltam}")
            posicoes = [cabecalho.index(c) for c in COLUNAS_AJUSTES]
            esquema = dict.fromkeys(COLUNAS_AJUSTES.values(), pl.String)
            partes: list[pl.DataFrame] = []
            linhas: list[list[str | None]] = []
            for registro in leitor:
                linhas.append(
                    [registro[i] or None if i < len(registro) else None for i in posicoes]
                )
                if len(linhas) == lote:
                    partes.append(pl.DataFrame(linhas, schema=esquema, orient="row").unique())
                    linhas = []
            partes.append(pl.DataFrame(linhas, schema=esquema, orient="row"))
    return pl.concat(partes).unique()


def _data(coluna: str) -> pl.Expr:
    return pl.col(coluna).str.strptime(pl.Date, "%d/%m/%Y", strict=False)


def _numero(coluna: str) -> pl.Expr:
    return pl.col(coluna).str.replace(",", ".", literal=True).cast(pl.Float64, strict=False)


FORMATOS_DE_NOTA = (
    (r"^0*(\d+)$", 1, None),
    (r"^E?0*(\d+)/(20[12]\d)$", 1, 2),
    (r"^\d*?(20[12]\d)NE0*(\d+)$", 2, 1),
)
"""Formatos do número da nota nos ajustes: (padrão, grupo do número, grupo do ano). Sem ano no
texto, vale o ano da data da nota. Os demais formatos ("OES 042/2024 NE 2519") não ligam."""


def _numero_e_ano_da_nota(nota: pl.Expr) -> tuple[pl.Expr, pl.Expr]:
    numeros = [nota.str.extract(p, g) for p, g, _ in FORMATOS_DE_NOTA]
    anos = [nota.str.extract(p, g) for p, _, g in FORMATOS_DE_NOTA if g is not None]
    return pl.coalesce(numeros).alias("numero"), pl.coalesce(anos).alias("ano_nota")


def montar_ajustes(
    ajustes: Iterable[pl.DataFrame], parciais: pl.LazyFrame, municipios: pl.DataFrame
) -> tuple[pl.DataFrame, pl.DataFrame, list[Contagem]]:
    """Notas de empenho ligáveis (`id_empenho`, `cnpj_basico`, `id_ajuste`) e `licitacoes`.

    O município do ajuste vem só pelo nome; casa com o nome normalizado do TCESP nas despesas.
    `Código do Ajuste` recomeça por entidade, então `id_ajuste` leva município e órgão. Cada
    arquivo é reduzido às chaves antes de juntar, para caber na memória.
    """
    nomes = (
        parciais.select("cod_ibge", "municipio")
        .unique()
        .collect()
        .with_columns(pl.col("municipio").map_elements(normalizar_nome, pl.String).alias("chave"))
        .unique("chave")
        .join(municipios.select("cod_ibge", "cod_municipio_tse"), on="cod_ibge")
        .select("chave", "cod_ibge", "cod_municipio_tse")
    )
    partes, linhas, nao_reconhecidas, sem_municipio = [], 0, 0, set()
    for arquivo in ajustes:
        base, faltam = _reduzir_ajustes(arquivo, nomes)
        linhas += arquivo.height
        nao_reconhecidas += (
            arquivo.filter(pl.col("nota").is_not_null()).height
            - base.filter(pl.col("numero").is_not_null()).height
        )
        sem_municipio |= set(faltam)
        partes.append(base.filter(pl.col("id_ajuste").is_not_null()))
    base = pl.concat(partes).unique()
    del partes

    licitacoes = (
        base.group_by("id_ajuste")
        .agg(
            pl.col("cod_municipio_tse").first(),
            pl.col("cnpj")
            .filter(pl.col("cnpj").str.len_chars() == 14)
            .str.slice(0, 8)
            .min()
            .alias("cnpj_basico"),
            pl.col("instrumento").drop_nulls().min().fill_null("(não informado)").alias("tipo"),
            pl.coalesce(
                pl.col("data_assinatura").min(),
                pl.col("data_nota").min(),
                pl.col("data_inicio").min(),
            ).alias("data"),
            pl.coalesce(
                pl.col("valor_contrato").max(),
                pl.struct("numero", "data_nota", "valor_nota")
                .unique()
                .struct.field("valor_nota")
                .sum(),
            ).alias("valor"),
        )
        .filter(pl.col("data").is_not_null())
        .sort("id_ajuste")
        .match_to_schema(LICITACOES.esquema)
    )

    notas = (
        base.filter(
            pl.col("numero").is_not_null()
            & pl.col("data_nota").is_not_null()
            & pl.col("id_ajuste").is_in(licitacoes["id_ajuste"].implode())
        )
        .select(
            pl.concat_str(
                "cod_ibge",
                "chave_orgao",
                "numero",
                pl.coalesce("ano_nota", pl.col("data_nota").dt.year().cast(pl.String)),
                separator="-",
            ).alias("id_empenho"),
            pl.col("cnpj").str.slice(0, 8).alias("cnpj_basico"),
            "id_ajuste",
        )
        .unique()
    )
    ambiguas = notas.filter(pl.struct("id_empenho", "cnpj_basico").is_duplicated())
    notas = notas.group_by("id_empenho", "cnpj_basico").agg(pl.col("id_ajuste").min())

    contagens = [
        Contagem("ajustes_linhas", None, "total", float(linhas)),
        Contagem("ajustes_linhas", None, "nota_em_formato_nao_reconhecido",
                 float(nao_reconhecidas)),
        Contagem("ajustes_distintos", None, "total", float(licitacoes.height)),
        *(
            Contagem("ajustes_distintos", None, f"tipo|{t}", float(n))
            for t, n in licitacoes.group_by("tipo").len().iter_rows()
        ),
        Contagem("notas_ligaveis", None, "total", float(notas.height)),
        Contagem("notas_ligaveis", None, "com_mais_de_um_ajuste",
                 float(ambiguas.select("id_empenho", "cnpj_basico").unique().height)),
        Contagem("ajustes_municipio_sem_correspondencia", None, "total", len(sem_municipio)),
    ]  # fmt: skip
    return notas, licitacoes, contagens


def _reduzir_ajustes(ajustes: pl.DataFrame, nomes: pl.DataFrame) -> tuple[pl.DataFrame, list[str]]:
    orgaos = _chaves_de_orgao(ajustes["orgao"].drop_nulls().unique().to_list())
    base = ajustes.with_columns(
        pl.col("municipio")
        .map_elements(normalizar_nome, pl.String, skip_nulls=True)
        .alias("chave"),
        pl.col("orgao").replace_strict(orgaos, default=None).alias("chave_orgao"),
    ).join(nomes, on="chave", how="left")
    faltam = base.filter(pl.col("cod_ibge").is_null())["municipio"].drop_nulls().unique().to_list()
    reduzida = base.select(
        pl.concat_str(
            "cod_ibge", "chave_orgao", pl.col("codigo_ajuste").str.strip_chars(), separator="-"
        ).alias("id_ajuste"),
        "cod_ibge",
        "cod_municipio_tse",
        "chave_orgao",
        pl.col("cnpj").str.replace_all(r"\D", "").alias("cnpj"),
        "instrumento",
        _data("data_nota").alias("data_nota"),
        _data("data_assinatura").alias("data_assinatura"),
        _data("data_inicio").alias("data_inicio"),
        _numero("valor_nota").alias("valor_nota"),
        _numero("valor_contrato").alias("valor_contrato"),
        *_numero_e_ano_da_nota(pl.col("nota").str.strip_chars()),
    ).unique()
    return reduzida, faltam


# Montagem -----------------------------------------------------------------------------------


def montar_empenhos(
    parciais: pl.LazyFrame, municipios: pl.DataFrame, notas: pl.DataFrame
) -> pl.LazyFrame:
    tipos = {o: tipo_de_orgao(o) for o in parciais.select("orgao").unique().collect()["orgao"]}
    return (
        parciais.join(
            municipios.lazy().select("cod_ibge", "cod_municipio_tse"), on="cod_ibge", how="inner"
        )
        .join(notas.lazy(), on=["id_empenho", "cnpj_basico"], how="left")
        .with_columns(pl.col("orgao").replace_strict(tipos).cast(TIPO_ORGAO).alias("tipo_orgao"))
    )


def _gravar_em_fluxo(frame: pl.LazyFrame, tabela: Tabela, destino: Path) -> None:
    """Grava sem montar a tabela na memória; o executor valida o arquivo depois."""
    temporario = destino.with_suffix(destino.suffix + ".tmp")
    destino.parent.mkdir(parents=True, exist_ok=True)
    frame.select(pl.col(c).cast(t) for c, t in tabela.esquema.items()).sink_parquet(temporario)
    temporario.replace(destino)


def resumo(
    empenhos: pl.LazyFrame, parciais: pl.LazyFrame, licitacoes: pl.DataFrame
) -> list[Contagem]:
    """Contagens agregadas por ano, uma consulta por ano para caber na memória."""
    contagens: list[Contagem] = []
    for ano in config.ANOS_EMPENHO:
        do_ano = empenhos.filter(pl.col("data").dt.year() == ano)
        contagens += _resumo_do_ano(ano, do_ano, parciais.filter(pl.col("data").dt.year() == ano))
        if ano == config.ANO_RESULTADO:
            contagens += _vinculacao(ano, do_ano, licitacoes)
    return contagens


def _resumo_do_ano(ano: int, empenhos: pl.LazyFrame, parciais: pl.LazyFrame) -> list[Contagem]:
    c: list[Contagem] = []
    for e, n, v in (
        empenhos.group_by("evento").agg(pl.len(), pl.col("valor").sum()).collect().iter_rows()
    ):
        c += [Contagem("eventos", ano, str(e), n), Contagem("valor", ano, str(e), v)]
    totais = empenhos.select(
        pl.len().alias("eventos"),
        pl.col("valor").sum().alias("valor_liquido"),
        pl.col("id_empenho").n_unique().alias("empenhos"),
        pl.col("cnpj_basico").n_unique().alias("empresas"),
        pl.col("cod_municipio_tse").n_unique().alias("municipios"),
    ).collect()
    c += [Contagem(k, ano, "total", float(v)) for k, v in totais.row(0, named=True).items()]
    for coluna in ("elemento_despesa", "tipo_orgao"):
        grupos = empenhos.group_by(coluna).agg(pl.len(), pl.col("valor").sum()).collect()
        for g, n, v in grupos.sort(coluna).iter_rows():
            c += [Contagem(f"eventos_por_{coluna}", ano, str(g), n)]
            c += [Contagem(f"valor_por_{coluna}", ano, str(g), v)]

    escopo = parciais.select(
        pl.col("valor").sum().alias("total"),
        pl.col("valor")
        .filter(pl.col("natureza_despesa").str.starts_with("31"))
        .sum()
        .alias("pessoal"),
        pl.col("valor").filter(pl.col("credor_publico")).sum().alias("credor_publico"),
        pl.col("valor")
        .filter(pl.col("natureza_despesa").str.starts_with("31") | pl.col("credor_publico"))
        .sum()
        .alias("pessoal_ou_credor_publico"),
        pl.col("valor")
        .filter(pl.col("natureza_despesa").str.slice(2, 2) != "90")
        .sum()
        .alias("modalidade_nao_aplicacao_direta"),
    ).collect()
    linha = escopo.row(0, named=True)
    total = linha.pop("total")
    for k, v in linha.items():
        c += [
            Contagem("escopo_valor", ano, k, v),
            Contagem("escopo_participacao", ano, k, v / total),
        ]
    descartados = parciais.join(empenhos.select("id_evento"), on="id_evento", how="anti")
    c += [
        Contagem(
            "descarte", ano, "municipio_sem_tse", descartados.select(pl.len()).collect().item()
        )
    ]
    return c


def _vinculacao(ano: int, empenhos: pl.LazyFrame, licitacoes: pl.DataFrame) -> list[Contagem]:
    """Taxa de vinculação dos empenhos do ano (valor líquido de cada empenho e contagem)."""
    datas = licitacoes.lazy().select("id_ajuste", pl.col("data").alias("data_ajuste"))
    por_empenho = (
        empenhos.group_by("id_empenho")
        .agg(pl.col("valor").sum(), pl.col("id_ajuste").drop_nulls().first())
        .join(datas, on="id_ajuste", how="left")
        .select(
            pl.len().alias("n"),
            pl.col("valor").sum().alias("v"),
            pl.col("id_ajuste").is_not_null().sum().alias("n_ligado"),
            pl.col("valor").filter(pl.col("id_ajuste").is_not_null()).sum().alias("v_ligado"),
            (pl.col("data_ajuste") >= config.DATA_POSSE).sum().alias("n_novo"),
            pl.col("valor")
            .filter(pl.col("data_ajuste") >= config.DATA_POSSE)
            .sum()
            .alias("v_novo"),
        )
        .collect()
        .row(0, named=True)
    )
    n, v = por_empenho["n"], por_empenho["v"]
    return [
        Contagem("vinculacao_empenhos", ano, "ligados", por_empenho["n_ligado"] / n),
        Contagem("vinculacao_valor", ano, "ligados", por_empenho["v_ligado"] / v),
        Contagem("vinculacao_empenhos", ano, "novos", por_empenho["n_novo"] / n),
        Contagem("vinculacao_valor", ano, "novos", por_empenho["v_novo"] / v),
    ]


# Conferência com o portal ---------------------------------------------------------------------

API_PORTAL = "https://transparencia.tce.sp.gov.br/api/json/despesas/{municipio}/{ano}/{mes}"
CONFERENCIA = "conferencia_tcesp.csv"


def empenhado_no_portal(municipio: str, ano: int) -> float:
    """Empenho líquido do ano a credores PJ, somado mês a mês pela API do portal do TCESP.

    Caminho independente do zip: outra origem (JSON por mês) e outra soma (Python puro).
    """
    sinais = {"Empenhado": 1, "Reforço": 1, "Anulação": -1}
    total = 0.0
    for mes in range(1, 13):
        url = API_PORTAL.format(municipio=municipio, ano=ano, mes=mes)
        pedido = urllib.request.Request(url, headers={"User-Agent": fetch.USER_AGENT})
        with urllib.request.urlopen(pedido, timeout=fetch.TIMEOUT) as resposta:
            linhas = json.load(resposta)
        for linha in linhas:
            sinal = sinais.get(linha["evento"])
            tipo, _, doc = linha["id_fornecedor"].rpartition(" - ")
            if sinal and tipo == CREDOR_PJ and re.fullmatch(r"\d{14}", doc.strip()):
                total += sinal * float(linha["vl_despesa"].replace(",", "."))
    return total


def conferir(caminhos: Caminhos, ano: int, municipios: dict[str, str]) -> pl.DataFrame:
    """`municipios`: código IBGE → nome no endereço do portal (ex.: "3504602": "bady-bassitt")."""
    tse = schemas.ler(MUNICIPIOS, caminhos.dados).collect()
    empenhos = schemas.ler(EMPENHOS, caminhos.dados)
    linhas = []
    for ibge, nome in municipios.items():
        cod = tse.filter(pl.col("cod_ibge") == ibge)["cod_municipio_tse"].item()
        etapa = (
            empenhos.filter(
                (pl.col("cod_municipio_tse") == cod) & (pl.col("data").dt.year() == ano)
            )
            .select(pl.col("valor").sum())
            .collect()
            .item()
        )
        portal = empenhado_no_portal(nome, ano)
        linhas.append((ibge, nome, ano, etapa, portal, etapa - portal))
    tabela = pl.DataFrame(
        linhas,
        schema=["cod_ibge", "municipio", "ano", "empenhos_parquet", "portal_api", "diferenca"],
        orient="row",
    )
    destino = caminhos.resultados / "tables" / CONFERENCIA
    destino.parent.mkdir(parents=True, exist_ok=True)
    tabela.write_csv(destino)
    return tabela


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 4 or sys.argv[1] != "conferir":
        sys.exit("uso: python -m redes.ingest.tcesp conferir ANO IBGE=nome-no-portal ...")
    pares = dict(arg.split("=", 1) for arg in sys.argv[3:])
    print(conferir(Caminhos.do_ambiente(), int(sys.argv[2]), pares))
