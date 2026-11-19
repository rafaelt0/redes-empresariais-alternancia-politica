"""Esquema canônico de cada tabela intermediária do pipeline.

Uma etapa só grava uma tabela depois de `validar` aceitá-la, e só lê uma tabela cujo esquema
confere com o daqui. `docs/dicionario.md` é gerado a partir deste módulo (`make dicionario`).

Convenções de identificador, comuns a todas as tabelas:
- empresa: `cnpj_basico`, texto de 8 dígitos;
- pessoa física: pseudônimo de 16 caracteres hexadecimais (`redes.pseudonimo`), o mesmo para
  sócios, doadores e candidatos;
- município: `cod_municipio_tse`, texto de 5 dígitos; a tabela `municipios` traduz o
  identificador do TCESP na ingestão, e daí em diante só o código do TSE circula.
"""

import itertools
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

import duckdb
import polars as pl

from redes import config

TIPO_SOCIO = pl.Enum(["PF", "PJ", "ESTRANGEIRO"])
VINCULO = pl.Enum(["SOCIO", "ADMINISTRADOR_NAO_SOCIO"])
FOTOGRAFIA_RFB = pl.Enum(["2024-09", "2024-10"])
TIPO_DOADOR = pl.Enum(["PF", "PJ", "OUTRO"])
ORIGEM_RECEITA = pl.Enum(["PESSOA_FISICA", "RECURSOS_PROPRIOS", "REPASSE", "OUTRA"])
TIPO_ELEICAO = pl.Enum(["ORDINARIA", "SUPLEMENTAR"])
EVENTO = pl.Enum(["EMISSAO", "REFORCO", "ANULACAO"])
GRUPO = pl.Enum(["A", "B"])
RAMO = pl.Enum(["PREFEITO", "PARTIDO", "COLIGACAO"])
MOTIVO_EXCLUSAO = pl.Enum(
    ["SEGUNDO_TURNO", "RUPTURA", "SEM_CANDIDATO", "SEM_ADVERSARIO", "PREFEITO_INDEFINIDO"]
)
FAIXA = pl.Enum(["0", "1", "2", "3+", "inf"])
VARIANTE = pl.Enum(["PRINCIPAL", "SEM_ARTICULACAO", "SEM_PJ", "SEM_ADMINISTRADOR"])
LIGACAO = pl.Enum(["NENHUM", "A", "B", "AMBOS"])
TIPO_ORGAO = pl.Enum(["PREFEITURA", "CAMARA", "PREVIDENCIA", "AUTARQUIA_OU_OUTRA"])


@dataclass(frozen=True)
class Coluna:
    nome: str
    tipo: pl.DataType
    descricao: str
    nula: bool = False


@dataclass(frozen=True)
class Checagem:
    descricao: str
    expr: pl.Expr
    """Booleana por linha; a tabela passa quando vale para todas as linhas."""


@dataclass(frozen=True)
class Tabela:
    nome: str
    descricao: str
    colunas: tuple[Coluna, ...]
    chave: tuple[str, ...]
    checagens: tuple[Checagem, ...] = ()
    formato: Literal["parquet", "csv"] = "parquet"

    @property
    def arquivo(self) -> str:
        return f"{self.nome}.{self.formato}"

    @property
    def esquema(self) -> pl.Schema:
        return pl.Schema({c.nome: c.tipo for c in self.colunas})

    def vazia(self) -> pl.DataFrame:
        return pl.DataFrame(schema=self.esquema)


class EsquemaInvalido(ValueError):
    def __init__(self, tabela: str, problemas: list[str]):
        self.problemas = problemas
        super().__init__(f"{tabela}: " + "; ".join(problemas))


def _digitos(coluna: str, n: int) -> Checagem:
    return Checagem(f"`{coluna}` tem {n} dígitos", pl.col(coluna).str.contains(rf"^\d{{{n}}}$"))


def _pseudonimo(coluna: str) -> Checagem:
    return Checagem(
        f"`{coluna}` é pseudônimo hexadecimal de 16 caracteres",
        pl.col(coluna).str.contains(r"^[0-9a-f]{16}$"),
    )


def _entre(coluna: str, inicio: date, fim: date) -> Checagem:
    return Checagem(
        f"`{coluna}` entre {inicio} e {fim}",
        pl.col(coluna).is_between(inicio, fim) | pl.col(coluna).is_null(),
    )


CNPJ = Coluna("cnpj_basico", pl.String, "CNPJ básico (8 primeiros dígitos) da empresa")
MUNICIPIO = Coluna("cod_municipio_tse", pl.String, "Código do município no TSE (5 dígitos)")
VARIANTE_REDE = Coluna(
    "variante",
    VARIANTE,
    "Versão da rede: principal ou uma das robustezas da seção 5 do projeto",
)

SOCIOS = Tabela(
    "socios",
    "Quadro de sócios e administradores da fotografia da Receita de 2024-09; as empresas sem "
    "sócio nela recebem os de 2024-10 que entraram antes da extração de 2024-09.",
    (
        CNPJ,
        Coluna(
            "id_socio",
            pl.String,
            "Pseudônimo da pessoa física ou estrangeira; CNPJ básico do sócio pessoa jurídica",
        ),
        Coluna("tipo_socio", TIPO_SOCIO, "PF, PJ ou ESTRANGEIRO"),
        Coluna(
            "vinculo",
            VINCULO,
            "SOCIO ou ADMINISTRADOR_NAO_SOCIO, derivado da qualificação",
        ),
        Coluna("cod_qualificacao", pl.String, "Código de qualificação do sócio na Receita"),
        Coluna("data_entrada", pl.Date, "Data de entrada na sociedade", nula=True),
        Coluna(
            "origem",
            FOTOGRAFIA_RFB,
            "Pasta da Receita de onde veio o vínculo: 2024-09 ou, no preenchimento, 2024-10",
        ),
    ),
    chave=("cnpj_basico", "id_socio", "cod_qualificacao"),
    checagens=(
        _digitos("cnpj_basico", 8),
        Checagem(
            "`id_socio` é CNPJ básico para PJ e pseudônimo para os demais",
            pl.when(pl.col("tipo_socio") == "PJ")
            .then(pl.col("id_socio").str.contains(r"^\d{8}$"))
            .otherwise(pl.col("id_socio").str.contains(r"^[0-9a-f]{16}$")),
        ),
        Checagem(
            f"`data_entrada` até a extração ({config.DATA_EXTRACAO_RFB})",
            (pl.col("data_entrada") <= config.DATA_EXTRACAO_RFB) | pl.col("data_entrada").is_null(),
        ),
        Checagem(
            f"vínculo de 2024-10 tem `data_entrada` antes de {config.DATA_EXTRACAO_RFB}",
            (pl.col("origem") == "2024-09")
            | (pl.col("data_entrada") < config.DATA_EXTRACAO_RFB).fill_null(False),
        ),
    ),
)

EMPRESAS = Tabela(
    "empresas",
    "Cadastro das empresas da fotografia 2024-09; sem razão social, que no MEI contém nome e CPF.",
    (
        CNPJ,
        Coluna("cod_natureza_juridica", pl.String, "Código da natureza jurídica"),
        Coluna("porte", pl.String, "Código de porte da Receita", nula=True),
        Coluna("capital_social", pl.Float64, "Capital social declarado, em reais", nula=True),
    ),
    chave=("cnpj_basico",),
    checagens=(_digitos("cnpj_basico", 8),),
)

CANDIDATOS = Tabela(
    "candidatos",
    "Candidatos a prefeito em SP: eleições ordinárias de 2020 e 2024 e suplementares entre elas.",
    (
        Coluna("ano", pl.Int16, "Ano da eleição"),
        Coluna("data_eleicao", pl.Date, "Data do primeiro turno"),
        Coluna("tipo_eleicao", TIPO_ELEICAO, "ORDINARIA ou SUPLEMENTAR"),
        MUNICIPIO,
        Coluna("sq_candidato", pl.String, "Sequencial do candidato no TSE"),
        Coluna(
            "id_pessoa",
            pl.String,
            "Pseudônimo do candidato; liga o prefeito eleito em 2020 ao candidato de 2024",
        ),
        Coluna(
            "sigla_partido",
            pl.String,
            "Partido do candidato; antes de 2024, a sigla sucessora quando o partido se fundiu, "
            "foi incorporado ou mudou de nome até 2024",
        ),
        Coluna("sq_coligacao", pl.String, "Sequencial da coligação ou federação", nula=True),
        Coluna(
            "partidos_coligacao",
            pl.List(pl.String),
            "Siglas dos partidos da coligação, incluindo o do candidato",
        ),
        Coluna("situacao_candidatura", pl.String, "Situação da candidatura no TSE"),
        Coluna("eleito", pl.Boolean, "Eleito no pleito (primeiro ou segundo turno)", nula=True),
    ),
    chave=("ano", "sq_candidato"),
    checagens=(_digitos("cod_municipio_tse", 5), _pseudonimo("id_pessoa")),
)

VOTOS = Tabela(
    "votos",
    "Votos nominais para prefeito por candidato e município, somados sobre as zonas.",
    (
        Coluna("ano", pl.Int16, "Ano da eleição"),
        Coluna("turno", pl.Int8, "1 ou 2"),
        MUNICIPIO,
        Coluna("sq_candidato", pl.String, "Sequencial do candidato no TSE"),
        Coluna("votos", pl.Int64, "Votos nominais válidos"),
    ),
    chave=("ano", "turno", "cod_municipio_tse", "sq_candidato"),
    checagens=(
        _digitos("cod_municipio_tse", 5),
        Checagem("`turno` é 1 ou 2", pl.col("turno").is_in([1, 2])),
        Checagem("`votos` não negativo", pl.col("votos") >= 0),
    ),
)

DOACOES = Tabela(
    "doacoes",
    "Receitas de campanha dos candidatos a prefeito de SP em 2024.",
    (
        Coluna("ano", pl.Int16, "Ano da eleição"),
        Coluna("sq_candidato", pl.String, "Candidato que recebeu"),
        MUNICIPIO,
        Coluna("id_receita", pl.String, "Identificador da receita no TSE"),
        Coluna(
            "id_doador",
            pl.String,
            "Pseudônimo do doador PF; CNPJ básico do doador PJ; nulo nos demais",
            nula=True,
        ),
        Coluna(
            "tipo_doador",
            TIPO_DOADOR,
            "PF (doador com CPF), PJ (partido, campanha ou plataforma, com CNPJ) ou OUTRO",
        ),
        Coluna(
            "origem",
            ORIGEM_RECEITA,
            "PESSOA_FISICA (inclui internet e financiamento coletivo), RECURSOS_PROPRIOS, "
            "REPASSE (de partido ou de outro candidato) ou OUTRA",
        ),
        Coluna("data_receita", pl.Date, "Data da receita, não da declaração (seção 5)"),
        Coluna("valor", pl.Float64, "Valor em reais"),
    ),
    chave=("ano", "sq_candidato", "id_receita"),
    checagens=(
        Checagem(
            "`id_doador` preenchido para PF",
            (pl.col("tipo_doador") != "PF") | pl.col("id_doador").str.contains(r"^[0-9a-f]{16}$"),
        ),
        Checagem("`valor` positivo", pl.col("valor") > 0),
    ),
)

PSEUDONIMOS_AMBIGUOS = Tabela(
    "pseudonimos_ambiguos",
    "Pseudônimos de doadores e candidatos do TSE que correspondem a mais de um CPF completo.",
    (
        Coluna("id_pessoa", pl.String, "Pseudônimo (nome normalizado e seis dígitos centrais)"),
        Coluna("n_cpfs", pl.Int64, "Número de CPFs completos distintos com esse pseudônimo"),
    ),
    chave=("id_pessoa",),
    checagens=(_pseudonimo("id_pessoa"),),
)

EMPENHOS = Tabela(
    "empenhos",
    "Eventos de empenho dos municípios paulistas, credores pessoa jurídica.",
    (
        Coluna("id_evento", pl.String, "Identificador único do evento"),
        Coluna("id_empenho", pl.String, "Empenho ao qual o evento pertence"),
        Coluna("evento", EVENTO, "EMISSAO, REFORCO ou ANULACAO"),
        Coluna("data", pl.Date, "Data do evento"),
        MUNICIPIO,
        CNPJ,
        Coluna(
            "elemento_despesa",
            pl.String,
            "Elemento de despesa, 2 dígitos (5º e 6º da natureza): o mercado, na especificação",
        ),
        Coluna(
            "natureza_despesa",
            pl.String,
            "Natureza da despesa até o subelemento, 8 dígitos, como no TCESP; nula na amostra",
            nula=True,
        ),
        Coluna(
            "tipo_orgao",
            TIPO_ORGAO,
            "Órgão que empenhou, pelo nome: prefeitura, câmara, previdência própria ou outro",
            nula=True,
        ),
        Coluna(
            "valor",
            pl.Float64,
            "Valor com sinal: positivo em emissão e reforço, negativo em anulação",
        ),
        Coluna(
            "id_ajuste",
            pl.String,
            "Licitação ou ajuste vinculado, quando houver",
            nula=True,
        ),
    ),
    chave=("id_evento",),
    checagens=(
        _digitos("cnpj_basico", 8),
        _digitos("cod_municipio_tse", 5),
        Checagem(
            "sinal de `valor` segue o evento",
            pl.when(pl.col("evento") == "ANULACAO")
            .then(pl.col("valor") <= 0)
            .otherwise(pl.col("valor") >= 0),
        ),
        _entre("data", config.INICIO_PRE_ELEICAO, date(config.ANO_RESULTADO, 12, 31)),
    ),
)

LICITACOES = Tabela(
    "licitacoes",
    "Licitações e ajustes do TCESP, usados para marcar empenhos de 2025 como novos.",
    (
        Coluna("id_ajuste", pl.String, "Identificador da licitação ou ajuste"),
        MUNICIPIO,
        Coluna("cnpj_basico", pl.String, "Contratado, quando informado", nula=True),
        Coluna("tipo", pl.String, "Licitação, contrato, aditivo etc., como no TCESP"),
        Coluna("data", pl.Date, "Data da licitação ou da assinatura do ajuste"),
        Coluna("valor", pl.Float64, "Valor em reais", nula=True),
    ),
    chave=("id_ajuste",),
    checagens=(_digitos("cod_municipio_tse", 5),),
)

MUNICIPIOS = Tabela(
    "municipios",
    "Correspondência entre o código do TSE e o identificador do TCESP; sem a capital.",
    (
        MUNICIPIO,
        Coluna("id_municipio_tcesp", pl.String, "Identificador do município no TCESP"),
        Coluna("cod_ibge", pl.String, "Código IBGE (7 dígitos)", nula=True),
        Coluna("nome", pl.String, "Nome do município"),
    ),
    chave=("cod_municipio_tse",),
    checagens=(
        _digitos("cod_municipio_tse", 5),
        Checagem("`id_municipio_tcesp` único", pl.col("id_municipio_tcesp").is_unique()),
    ),
)

ELEICOES = Tabela(
    "eleicoes",
    "Municípios na amostra principal: grupo incumbente, margem M_m e tratamento T_m.",
    (
        MUNICIPIO,
        Coluna("ramo", RAMO, "Ramo do protocolo da seção 6: PREFEITO, PARTIDO ou COLIGACAO"),
        Coluna("sq_candidato_a", pl.String, "Candidato do grupo incumbente (A)"),
        Coluna("sq_candidato_b", pl.String, "Adversário mais votado (B)"),
        Coluna("votos_validos", pl.Int64, "Votos válidos no primeiro turno"),
        Coluna("margem", pl.Float64, "M_m: votos de A menos votos de B, em pontos percentuais"),
        Coluna("tratamento", pl.Int8, "T_m: 1 se A perde (M_m < 0)"),
    ),
    chave=("cod_municipio_tse",),
    checagens=(
        Checagem(
            "`tratamento` = 1 exatamente quando `margem` < 0",
            pl.col("tratamento") == (pl.col("margem") < 0).cast(pl.Int8),
        ),
    ),
)

EXCLUSOES = Tabela(
    "exclusoes",
    "Municípios fora da amostra principal e o motivo.",
    (
        MUNICIPIO,
        Coluna("motivo", MOTIVO_EXCLUSAO, "Primeiro motivo de exclusão que se aplica"),
        Coluna("detalhe", pl.String, "Explicação do caso", nula=True),
    ),
    chave=("cod_municipio_tse",),
    formato="csv",
)

CONEXOES_DIRETAS = Tabela(
    "conexoes_diretas",
    "Empresas com sócio PF que doou ao candidato do grupo até a véspera da eleição.",
    (
        MUNICIPIO,
        Coluna("grupo", GRUPO, "A (incumbente) ou B (adversário)"),
        CNPJ,
        Coluna("id_pessoa", pl.String, "Sócio doador; permite refazer as robustezas"),
        Coluna(
            "vinculo",
            VINCULO,
            "SOCIO se a pessoa tem ao menos uma qualificação de sócio na empresa; "
            "ADMINISTRADOR_NAO_SOCIO se só administra (a variante SEM_ADMINISTRADOR descarta)",
        ),
        Coluna("valor_doado", pl.Float64, "Soma das doações do sócio ao candidato do grupo"),
    ),
    chave=("cod_municipio_tse", "grupo", "cnpj_basico", "id_pessoa"),
    checagens=(_pseudonimo("id_pessoa"), _digitos("cnpj_basico", 8)),
)

REDE = Tabela(
    "rede",
    "Rede societária (componente conexo da vizinhança) de cada empresa, por variante.",
    (
        VARIANTE_REDE,
        CNPJ,
        Coluna("id_rede", pl.Int64, "Identificador do componente"),
        Coluna("empresas_na_rede", pl.Int64, "Número de empresas no componente"),
    ),
    chave=("variante", "cnpj_basico"),
)

DISTANCIAS = Tabela(
    "distancias",
    "δ_ik por município, grupo e variante, para as empresas com empenho no município.",
    (
        VARIANTE_REDE,
        MUNICIPIO,
        Coluna("grupo", GRUPO, "A ou B"),
        CNPJ,
        Coluna(
            "distancia",
            pl.Int8,
            f"δ exato até {config.LIMITE_DISTANCIA}; nulo além disso ou sem caminho",
            nula=True,
        ),
        Coluna("faixa", FAIXA, "0, 1, 2, 3+ ou inf"),
    ),
    chave=("variante", "cod_municipio_tse", "grupo", "cnpj_basico"),
)

_FAIXA_GRUPO = (
    Coluna(
        "faixa_a",
        FAIXA,
        "Faixa de δ até o grupo incumbente; inf se a empresa falta em `distancias`",
    ),
    Coluna("faixa_b", FAIXA, "Faixa de δ até o grupo adversário; idem"),
)
_ID_REDE = Coluna(
    "id_rede",
    pl.Int64,
    "Rede da empresa em `rede`, na variante; a empresa sem sócio na fotografia é uma rede de uma "
    "empresa só, com `id_rede` = −(CNPJ básico) − 1",
)
_DESENHO = (
    Coluna("margem", pl.Float64, "M_m, repetida de `eleicoes`"),
    Coluna("tratamento", pl.Int8, "T_m, repetido de `eleicoes`"),
    Coluna(
        "peso",
        pl.Float64,
        "1 ÷ linhas do município na variante: cada município soma 1 (seção 6 do projeto)",
    ),
)
_JANELA_PRE = "jan/2021 a set/2024"

PAINEL_FIRMA = Tabela(
    "painel_firma",
    "Painel empresa–município–elemento das fornecedoras anteriores do elemento (H1 e H2).",
    (
        VARIANTE_REDE,
        MUNICIPIO,
        Coluna("elemento_despesa", pl.String, "Mercado"),
        CNPJ,
        _ID_REDE,
        *_FAIXA_GRUPO,
        Coluna(
            "empenhado_pre",
            pl.Float64,
            f"Empenho líquido (emissão + reforço − anulação) no elemento, {_JANELA_PRE}; "
            "positivo, pois a linha é de fornecedora anterior",
        ),
        Coluna("empenhado_2025", pl.Float64, "Empenho líquido no elemento em 2025; pode ser ≤ 0"),
        Coluna(
            "empenhado_novo_2025",
            pl.Float64,
            "Parte de `empenhado_2025` em empenhos vinculados a licitação ou ajuste com data "
            "a partir da posse (1/1/2025)",
        ),
        Coluna(
            "participacao_pre",
            pl.Float64,
            "`empenhado_pre` ÷ soma dele entre as fornecedoras anteriores do município e elemento",
        ),
        Coluna(
            "participacao_2025",
            pl.Float64,
            "max(`empenhado_2025`, 0) ÷ empenho líquido positivo de 2025 de todas as empresas do "
            "município e elemento, novas inclusive; nula se ninguém recebeu no elemento em 2025",
            nula=True,
        ),
        *_DESENHO,
    ),
    chave=("variante", "cod_municipio_tse", "elemento_despesa", "cnpj_basico"),
    checagens=(
        Checagem("`empenhado_pre` positivo", pl.col("empenhado_pre") > 0),
        Checagem(
            "participações entre 0 e 1",
            pl.col("participacao_pre").is_between(0, 1)
            & pl.col("participacao_2025").is_between(0, 1).fill_null(True),
        ),
    ),
)

_TERMO = "Σ (empenho de 2025 − média anual pré-eleição) ÷ `gasto_medio_pre`, sobre "
_LIMIARES = tuple(int(p * 100) for p in config.LIMIARES_PRINCIPAIS_REDES)

PAINEL_REDE = Tabela(
    "painel_rede",
    "Painel rede–município das redes com fornecedora anterior no município: termos da equação "
    "(4) e principais redes (H3 e H4).",
    (
        VARIANTE_REDE,
        MUNICIPIO,
        _ID_REDE,
        Coluna(
            "ligacao",
            LIGACAO,
            "Grupos do município conectados diretamente a alguma empresa da rede, forneça "
            "ela ao município ou não",
        ),
        Coluna(
            "termo_r1",
            pl.Float64,
            _TERMO + "R1, fornecedoras anteriores conectadas diretamente ao incumbente",
        ),
        Coluna("termo_r2", pl.Float64, _TERMO + "R2, as demais fornecedoras anteriores"),
        Coluna(
            "termo_r3",
            pl.Float64,
            _TERMO + "R3, empresas da rede sem empenho líquido positivo antes da eleição",
        ),
        Coluna("variacao_total", pl.Float64, "Soma dos três termos"),
        Coluna(
            "gasto_medio_pre",
            pl.Float64,
            f"Empenho líquido do município a todos os credores PJ, {_JANELA_PRE}, "
            f"÷ {config.ANOS_NA_JANELA_PRE} anos",
        ),
        Coluna(
            "anos_com_empenho_pre",
            pl.Int8,
            "Anos de 2021 a 2024 (2024 até setembro) com empenho líquido positivo da rede",
        ),
        Coluna(
            "participacao_pre",
            pl.Float64,
            f"Empenho líquido da rede ÷ o do município, {_JANELA_PRE}",
        ),
        *(
            Coluna(
                f"principal_{p}",
                pl.Boolean,
                f"Entre as redes com empenho em ao menos {config.MINIMO_ANOS_PRINCIPAIS_REDES} "
                f"dos 4 anos, em ordem de empenho pré-eleição, está entre as primeiras que "
                f"alcançam {p}% do empenhado no município",
            )
            for p in _LIMIARES
        ),
        *(
            Coluna(
                f"mantem_posicao_{p}",
                pl.Boolean,
                f"Principal também em 2025: entre as redes com empenho positivo em 2025, em ordem "
                f"de empenho de 2025, está entre as primeiras que alcançam {p}% do empenhado "
                "em 2025; nulo se não era principal",
                nula=True,
            )
            for p in _LIMIARES
        ),
        *_DESENHO,
    ),
    chave=("variante", "cod_municipio_tse", "id_rede"),
    checagens=(
        Checagem(
            "os três termos somam `variacao_total`",
            (
                pl.col("termo_r1")
                + pl.col("termo_r2")
                + pl.col("termo_r3")
                - pl.col("variacao_total")
            ).abs()
            < 1e-9,
        ),
        *(
            Checagem(
                f"`mantem_posicao_{p}` nulo exatamente quando a rede não é principal",
                pl.col(f"mantem_posicao_{p}").is_null() == ~pl.col(f"principal_{p}"),
            )
            for p in _LIMIARES
        ),
        *(
            Checagem(
                f"principal em {menor}% é principal em {maior}%",
                ~pl.col(f"principal_{menor}") | pl.col(f"principal_{maior}"),
            )
            for menor, maior in itertools.pairwise(_LIMIARES)
        ),
    ),
)

TABELAS: dict[str, Tabela] = {
    t.nome: t
    for t in (
        SOCIOS,
        EMPRESAS,
        CANDIDATOS,
        VOTOS,
        DOACOES,
        PSEUDONIMOS_AMBIGUOS,
        EMPENHOS,
        LICITACOES,
        MUNICIPIOS,
        ELEICOES,
        EXCLUSOES,
        CONEXOES_DIRETAS,
        REDE,
        DISTANCIAS,
        PAINEL_FIRMA,
        PAINEL_REDE,
    )
}


def problemas_de_esquema(esquema: pl.Schema, tabela: Tabela) -> list[str]:
    if esquema == tabela.esquema:
        return []
    esperado = tabela.esquema
    problemas = [f"falta coluna `{c}`" for c in esperado if c not in esquema]
    problemas += [f"coluna inesperada `{c}`" for c in esquema if c not in esperado]
    problemas += [
        f"`{c}` é {esquema[c]}, esperado {esperado[c]}"
        for c in esperado
        if c in esquema and esquema[c] != esperado[c]
    ]
    return problemas or ["colunas fora da ordem canônica"]


def _chave_repetida_no_parquet(arquivo: Path, chave: tuple[str, ...]) -> bool:
    """Chave repetida contada pelo DuckDB, que despeja em disco: a tabela de empresas tem 60
    milhões de linhas, e o hash do polars sobre ela não cabe na memória da máquina de 7 GB."""
    colunas = ", ".join(f'"{c}"' for c in chave)
    temporario = arquivo.parent / "tmp" / "validar"
    temporario.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(
        config={
            "memory_limit": "1GB",
            "temp_directory": str(temporario),
            "threads": 2,
        }
    ) as con:
        con.execute("SET enable_progress_bar = false")
        (repetidas,) = con.execute(
            f"SELECT count(*) FROM (SELECT 1 FROM read_parquet(?) GROUP BY {colunas} "
            "HAVING count(*) > 1 LIMIT 1)",
            [str(arquivo)],
        ).fetchone()
    return repetidas > 0


def validar(
    frame: pl.DataFrame | pl.LazyFrame, tabela: Tabela, arquivo: Path | None = None
) -> None:
    """Esquema exato, colunas obrigatórias sem nulos, chave única e checagens da tabela.

    Com `arquivo` (Parquet já gravado), a unicidade da chave é conferida no DuckDB.
    """
    lazy = frame.lazy()
    problemas = problemas_de_esquema(lazy.collect_schema(), tabela)
    if problemas:
        raise EsquemaInvalido(tabela.nome, problemas)

    no_parquet = arquivo is not None and tabela.formato != "csv"
    rotulo_chave = f"chave {tabela.chave} repetida"
    obrigatorias = [c.nome for c in tabela.colunas if not c.nula]
    exprs = {
        **{f"nulos em `{c}`": pl.col(c).null_count() > 0 for c in obrigatorias},
        **({} if no_parquet else {rotulo_chave: pl.struct(tabela.chave).is_duplicated().any()}),
        **{f"falha: {ch.descricao}": ~ch.expr.fill_null(True).all() for ch in tabela.checagens},
    }
    linha = (
        lazy.select(**{f"_{i}": e for i, e in enumerate(exprs.values())})
        .collect(engine="streaming")
        .row(0)
    )
    problemas = [rotulo for rotulo, falhou in zip(exprs, linha, strict=True) if falhou]
    if no_parquet and _chave_repetida_no_parquet(arquivo, tabela.chave):
        problemas.append(rotulo_chave)
    if problemas:
        raise EsquemaInvalido(tabela.nome, problemas)


def ler(tabela: Tabela, diretorio: Path) -> pl.LazyFrame:
    """Abre a tabela e confere o esquema; as checagens de conteúdo ficam na gravação."""
    caminho = diretorio / tabela.arquivo
    if not caminho.exists():
        raise FileNotFoundError(f"{tabela.nome}: {caminho} não existe")
    if tabela.formato == "csv":
        frame = pl.scan_csv(caminho, schema=tabela.esquema)
    else:
        frame = pl.scan_parquet(caminho)
    problemas = problemas_de_esquema(frame.collect_schema(), tabela)
    if problemas:
        raise EsquemaInvalido(tabela.nome, problemas)
    return frame


def gravar(frame: pl.DataFrame | pl.LazyFrame, tabela: Tabela, diretorio: Path) -> Path:
    """Valida e grava de forma atômica, para que uma execução interrompida não deixe meia tabela."""
    df = frame.lazy().collect()
    validar(df, tabela)
    diretorio.mkdir(parents=True, exist_ok=True)
    destino = diretorio / tabela.arquivo
    temporario = destino.with_suffix(destino.suffix + ".tmp")
    if tabela.formato == "csv":
        df.write_csv(temporario)
    else:
        df.write_parquet(temporario)
    temporario.replace(destino)
    return destino


def gravar_em_fluxo(frame: pl.LazyFrame, tabela: Tabela, destino: Path) -> None:
    """Grava sem montar a tabela na memória; o executor valida o arquivo depois."""
    temporario = destino.with_suffix(destino.suffix + ".tmp")
    destino.parent.mkdir(parents=True, exist_ok=True)
    frame.select(pl.col(c).cast(t) for c, t in tabela.esquema.items()).sink_parquet(temporario)
    temporario.replace(destino)
