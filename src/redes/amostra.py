"""Amostra sintética no nível das tabelas canônicas já ingeridas.

Reproduz a Figura 1 do projeto no município 90001 (empresas X, Y e Z; Ana, Bruno, Carla e
Daniel; Ana doa ao grupo A e Daniel ao grupo B) e a embute em municípios sintéticos suficientes
para uma regressão com descontinuidade: margens dos dois lados do corte, os três ramos do
protocolo do grupo incumbente, cada motivo de exclusão e empenhos de 2021 a 2025 em mais de um
elemento de despesa. Nomes, CPFs, CNPJs e códigos de município são inventados; os CPFs começam
com 999 e não têm dígito verificador válido.

Em 2025, nos municípios em que o incumbente perde, empresas conectadas ao incumbente perdem
metade do empenho e as conectadas ao adversário ganham metade: um salto conhecido para as
etapas de estimação recuperarem.
"""

import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import polars as pl

from redes import config, schemas
from redes.pseudonimo import pseudonimo

CHAVE_AMOSTRA = b"amostra sintetica, sem dado real"
MARCADOR = ".amostra-sintetica"
SEMENTE = 20241006
N_MUNICIPIOS = 60
FIRMAS_POR_MUNICIPIO = 8
ELEMENTOS = ("3.3.90.30", "3.3.90.39", "4.4.90.52")
PARTIDOS = ("PSA", "PSB", "PSC", "PSD", "PSE", "PSF")

MUNICIPIO_FIGURA_1 = "90001"
EMPRESAS_FIGURA_1 = {"X": "00000001", "Y": "00000002", "Z": "00000003"}
PESSOAS_FIGURA_1 = {
    "Ana": ("Ana Exemplo", "99900000199"),
    "Bruno": ("Bruno Exemplo", "99900000299"),
    "Carla": ("Carla Exemplo", "99900000399"),
    "Daniel": ("Daniel Exemplo", "99900000499"),
}
SOCIEDADES_FIGURA_1 = (
    ("Ana", "X"),
    ("Bruno", "X"),
    ("Bruno", "Y"),
    ("Carla", "Y"),
    ("Carla", "Z"),
    ("Daniel", "Z"),
)
# Mesmo nome de Ana, outros dígitos centrais: doa a B e não pode ligar X a B.
HOMONIMA_DE_ANA = ("Ana Exemplo", "99900009999")

# Municípios com caso especial; os demais seguem o ramo PREFEITO.
SUPLEMENTAR = 7
SEM_ADVERSARIO = 57
SEGUNDO_TURNO = 58
SEM_CANDIDATO = 59

DATA_ELEICAO_2020 = date(2020, 11, 15)
DATA_SUPLEMENTAR = date(2022, 6, 5)


def id_pessoa(nome: str, cpf: str) -> str:
    return pseudonimo(nome, cpf, CHAVE_AMOSTRA)


def id_figura_1(rotulo: str) -> str:
    return id_pessoa(*PESSOAS_FIGURA_1[rotulo])


def codigo(i: int) -> str:
    return f"{90000 + i}"


def ramo_esperado(i: int) -> str:
    """Ramo do protocolo que a amostra planta em cada município não excluído."""
    if i % 10 == 0:
        return "PARTIDO"
    if i % 10 == 5:
        return "COLIGACAO"
    return "PREFEITO"


@dataclass
class _Gerador:
    rng: random.Random
    linhas: dict[str, list[dict]] = field(default_factory=dict)
    _proxima_pessoa: int = 1000

    def add(self, tabela: schemas.Tabela, **linha) -> None:
        self.linhas.setdefault(tabela.nome, []).append(linha)

    def pessoa(self) -> tuple[str, str]:
        self._proxima_pessoa += 1
        n = self._proxima_pessoa
        return f"Pessoa Sintetica {n}", f"999{n:06d}99"

    def data(self, inicio: date, fim: date) -> date:
        return inicio + timedelta(days=self.rng.randint(0, (fim - inicio).days))

    def tabelas(self) -> dict[str, pl.DataFrame]:
        tabelas = (
            schemas.SOCIOS,
            schemas.EMPRESAS,
            schemas.CANDIDATOS,
            schemas.VOTOS,
            schemas.DOACOES,
            schemas.PSEUDONIMOS_AMBIGUOS,
            schemas.EMPENHOS,
            schemas.LICITACOES,
            schemas.MUNICIPIOS,
        )
        return {
            t.nome: pl.DataFrame(self.linhas.get(t.nome, []), schema=t.esquema, orient="row")
            for t in tabelas
        }


def _candidato(
    g: _Gerador,
    ano: int,
    i: int,
    k: int,
    pessoa: tuple[str, str],
    partido: str,
    coligacao: tuple[str, ...],
    eleito: bool | None,
) -> str:
    sq = f"{ano}{i:04d}{k:02d}"
    datas = {2020: DATA_ELEICAO_2020, 2022: DATA_SUPLEMENTAR, 2024: config.DATA_ELEICAO}
    g.add(
        schemas.CANDIDATOS,
        ano=ano,
        data_eleicao=datas[ano],
        tipo_eleicao="SUPLEMENTAR" if ano == 2022 else "ORDINARIA",
        cod_municipio_tse=codigo(i),
        sq_candidato=sq,
        id_pessoa=id_pessoa(*pessoa),
        sigla_partido=partido,
        sq_coligacao=f"C{sq}" if len(coligacao) > 1 else None,
        partidos_coligacao=list(coligacao),
        situacao_candidatura="DEFERIDO",
        eleito=eleito,
    )
    return sq


def _eleicoes(g: _Gerador, i: int) -> tuple[str, str | None, float]:
    """Candidatos de 2020, suplementar e 2024 e votos; devolve (sq de A, sq de B, margem)."""
    partido = PARTIDOS[i % len(PARTIDOS)]
    aliado = PARTIDOS[(i + 1) % len(PARTIDOS)]
    outros = [p for p in PARTIDOS if p not in (partido, aliado)]
    prefeito = g.pessoa()
    _candidato(g, 2020, i, 1, prefeito, partido, (partido, aliado), eleito=True)
    _candidato(g, 2020, i, 2, g.pessoa(), outros[0], (outros[0],), eleito=False)

    if i == SUPLEMENTAR:
        cassado = prefeito
        prefeito = g.pessoa()
        partido, aliado = outros[1], outros[2]
        outros = [p for p in PARTIDOS if p not in (partido, aliado)]
        _candidato(g, 2022, i, 1, prefeito, partido, (partido,), eleito=True)
        _candidato(g, 2022, i, 2, g.pessoa(), outros[0], (outros[0],), eleito=False)

    if i == SEM_CANDIDATO:
        a = _candidato(g, 2024, i, 1, g.pessoa(), outros[0], (outros[0], outros[1]), None)
    elif ramo_esperado(i) == "PARTIDO":
        a = _candidato(g, 2024, i, 1, g.pessoa(), partido, (partido,), None)
    elif ramo_esperado(i) == "COLIGACAO":
        a = _candidato(g, 2024, i, 1, g.pessoa(), aliado, (aliado, partido), None)
    else:
        a = _candidato(g, 2024, i, 1, prefeito, partido, (partido, aliado), None)

    if i == SEM_ADVERSARIO:
        g.add(
            schemas.VOTOS,
            ano=2024,
            turno=1,
            cod_municipio_tse=codigo(i),
            sq_candidato=a,
            votos=g.rng.randint(3000, 20000),
        )
        return a, None, 100.0

    adversario = cassado if i == SUPLEMENTAR else g.pessoa()
    b = _candidato(g, 2024, i, 2, adversario, outros[-1], (outros[-1],), None)
    terceiro = None
    if i % 3 == 0 or i == SEGUNDO_TURNO:
        terceiro = _candidato(g, 2024, i, 3, g.pessoa(), outros[-2], (outros[-2],), None)

    margem = -3.0 if i == 1 else round(g.rng.uniform(-20, 20), 2)
    total = g.rng.randint(4000, 60000)
    fatia_terceiro = 0.3 if i == SEGUNDO_TURNO else (0.1 if terceiro else 0.0)
    fatias = {
        a: (1 - fatia_terceiro) / 2 + margem / 200,
        b: (1 - fatia_terceiro) / 2 - margem / 200,
    }
    if terceiro:
        fatias[terceiro] = fatia_terceiro
    for sq, fatia in fatias.items():
        g.add(
            schemas.VOTOS,
            ano=2024,
            turno=1,
            cod_municipio_tse=codigo(i),
            sq_candidato=sq,
            votos=round(total * fatia),
        )
    if i == SEGUNDO_TURNO:
        for sq, fatia in ((a, 0.52), (b, 0.48)):
            g.add(
                schemas.VOTOS,
                ano=2024,
                turno=2,
                cod_municipio_tse=codigo(i),
                sq_candidato=sq,
                votos=round(total * fatia),
            )
    return a, b, margem


def _doacao(
    g: _Gerador,
    i: int,
    sq: str,
    n: int,
    doador: tuple[str, str] | None,
    data: date,
    tipo: str = "PF",
    id_doador: str | None = None,
) -> None:
    g.add(
        schemas.DOACOES,
        ano=2024,
        sq_candidato=sq,
        cod_municipio_tse=codigo(i),
        id_receita=f"R{sq}{n:03d}",
        id_doador=id_pessoa(*doador) if doador else id_doador,
        tipo_doador=tipo,
        origem="PESSOA_FISICA" if tipo == "PF" else "REPASSE",
        data_receita=data,
        valor=float(g.rng.choice((500, 1000, 2500, 5000, 10000))),
    )


def _socio(
    g: _Gerador,
    cnpj: str,
    id_socio: str,
    tipo: str = "PF",
    vinculo: str = "SOCIO",
    qualificacao: str = "49",
) -> None:
    g.add(
        schemas.SOCIOS,
        cnpj_basico=cnpj,
        id_socio=id_socio,
        tipo_socio=tipo,
        vinculo=vinculo,
        cod_qualificacao=qualificacao,
        data_entrada=g.data(date(2000, 1, 1), date(2024, 8, 31)),
        origem="2024-09",
    )


def _municipio(g: _Gerador, i: int) -> None:
    cod = codigo(i)
    g.add(
        schemas.MUNICIPIOS,
        cod_municipio_tse=cod,
        id_municipio_tcesp=f"T{i:03d}",
        cod_ibge=None,
        nome=f"Municipio Sintetico {i:02d}",
    )
    a, b, margem = _eleicoes(g, i)

    firmas = [f"{i:03d}{j:05d}" for j in range(1, FIRMAS_POR_MUNICIPIO + 1)]
    pool = [g.pessoa() for _ in range(8)]
    for cnpj in firmas:
        for pessoa in g.rng.sample(pool, g.rng.choice((1, 1, 2))):
            _socio(g, cnpj, id_pessoa(*pessoa), qualificacao=g.rng.choice(("22", "49")))
    _socio(g, firmas[1], firmas[0], tipo="PJ", qualificacao="22")
    _socio(
        g, firmas[2], id_pessoa(*g.pessoa()), vinculo="ADMINISTRADOR_NAO_SOCIO", qualificacao="05"
    )
    if i % 4 == 0:
        _socio(
            g,
            firmas[3],
            id_pessoa(f"Estrangeira Sintetica {i}", "***999999**"),
            tipo="ESTRANGEIRO",
            qualificacao="37",
        )

    conectadas = {"A": set(), "B": set()}
    doacoes = 0
    if i == 1:
        firmas = [*EMPRESAS_FIGURA_1.values(), *firmas]
        for rotulo, empresa in SOCIEDADES_FIGURA_1:
            _socio(g, EMPRESAS_FIGURA_1[empresa], id_figura_1(rotulo))
        _doacao(g, i, a, 1, PESSOAS_FIGURA_1["Ana"], date(2024, 9, 2))
        _doacao(g, i, b, 2, PESSOAS_FIGURA_1["Daniel"], date(2024, 9, 20))
        _doacao(g, i, a, 3, PESSOAS_FIGURA_1["Carla"], config.DATA_ELEICAO)
        _doacao(g, i, b, 4, HOMONIMA_DE_ANA, date(2024, 9, 25))
        conectadas["A"].add(EMPRESAS_FIGURA_1["X"])
        conectadas["B"].add(EMPRESAS_FIGURA_1["Z"])
        doacoes = 4

    if b is not None:
        socios_de = {
            p: {s["cnpj_basico"] for s in g.linhas["socios"] if s["id_socio"] == id_pessoa(*p)}
            for p in pool
        }
        for grupo, sq in (("A", a), ("B", b)):
            for pessoa in g.rng.sample(pool, 2):
                doacoes += 1
                _doacao(
                    g, i, sq, doacoes, pessoa, g.data(date(2024, 8, 16), config.DATA_LIMITE_DOACAO)
                )
                conectadas[grupo] |= socios_de[pessoa]
            doacoes += 1
            _doacao(g, i, sq, doacoes, g.pessoa(), g.data(date(2024, 8, 16), date(2024, 10, 5)))
        doacoes += 1
        _doacao(g, i, a, doacoes, None, date(2024, 9, 1), tipo="OUTRO")

    tratado = margem < 0
    for n, cnpj in enumerate(firmas):
        g.add(
            schemas.EMPRESAS,
            cnpj_basico=cnpj,
            cod_natureza_juridica="2062",
            porte=g.rng.choice(("01", "03", "05")),
            capital_social=float(g.rng.randint(10, 500) * 1000),
        )
        efeito = 1.0
        if tratado and cnpj in conectadas["A"]:
            efeito *= 0.5
        if tratado and cnpj in conectadas["B"]:
            efeito *= 1.5
        entrante = n == len(firmas) - 1
        for elemento in g.rng.sample(ELEMENTOS, g.rng.choice((1, 2))):
            _empenhos(g, i, cnpj, elemento, efeito, entrante)


def _empenhos(g: _Gerador, i: int, cnpj: str, elemento: str, efeito: float, entrante: bool) -> None:
    """Eventos de um fornecedor num elemento; entrantes só recebem a partir de 2025 (R3)."""
    cod = codigo(i)
    base = g.rng.lognormvariate(10.5, 0.6)
    for ano in config.ANOS_EMPENHO:
        if entrante and ano < config.ANO_RESULTADO:
            continue
        for _ in range(g.rng.randint(1, 2)):
            id_empenho = f"{cod}-{ano}-{len(g.linhas.get('empenhos', [])):06d}"
            valor = round(base * (efeito if ano == config.ANO_RESULTADO else 1.0), 2)
            emissao = g.data(date(ano, 1, 2), date(ano, 12, 15))
            ajuste = None
            if ano == config.ANO_RESULTADO and g.rng.random() < 0.7:
                ajuste = f"A{id_empenho}"
                posterior = g.rng.random() < 0.6
                g.add(
                    schemas.LICITACOES,
                    id_ajuste=ajuste,
                    cod_municipio_tse=cod,
                    cnpj_basico=cnpj,
                    tipo="CONTRATO",
                    data=g.data(date(2025, 1, 2), date(2025, 6, 30))
                    if posterior
                    else g.data(date(2023, 1, 2), date(2024, 12, 20)),
                    valor=valor,
                )
            eventos = [("EMISSAO", emissao, valor)]
            if g.rng.random() < 0.2:
                reforco = emissao + timedelta(days=g.rng.randint(10, 60))
                eventos.append(("REFORCO", reforco, round(valor * 0.2, 2)))
            if g.rng.random() < 0.2:
                anulacao = emissao + timedelta(days=g.rng.randint(5, 30))
                fracao = 1.3 if g.rng.random() < 0.1 else g.rng.uniform(0.1, 0.5)
                eventos.append(("ANULACAO", anulacao, -round(valor * fracao, 2)))
            for k, (evento, data, v) in enumerate(eventos):
                if data.year > config.ANO_RESULTADO:
                    continue
                g.add(
                    schemas.EMPENHOS,
                    id_evento=f"{id_empenho}-{k}",
                    id_empenho=id_empenho,
                    evento=evento,
                    data=data,
                    cod_municipio_tse=cod,
                    cnpj_basico=cnpj,
                    elemento_despesa=elemento,
                    valor=v,
                    id_ajuste=ajuste,
                )


def gerar() -> dict[str, pl.DataFrame]:
    g = _Gerador(random.Random(SEMENTE))
    for i in range(1, N_MUNICIPIOS + 1):
        _municipio(g, i)
    return g.tabelas()


def gravar_amostra(diretorio: Path) -> None:
    for nome, df in gerar().items():
        schemas.gravar(df, schemas.TABELAS[nome], diretorio)
    (diretorio / MARCADOR).touch()
