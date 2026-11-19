"""Contrato das etapas: o que cada uma lê, o que grava e como o executor a chama.

Cada etapa é um módulo que expõe `ETAPA` (declaração) e `executar(ctx)`. O executor confere
que as entradas existem com o esquema canônico antes de chamar a etapa e valida todas as
saídas depois; a etapa só lê e grava pelo `Contexto`.
"""

import importlib
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import polars as pl

from redes import schemas
from redes.config import Caminhos
from redes.schemas import Tabela


@dataclass(frozen=True)
class Etapa:
    nome: str
    depende: tuple[str, ...]
    le: tuple[Tabela, ...]
    grava: tuple[Tabela, ...]
    artefatos: tuple[str, ...] = ()
    """Saídas que não são tabelas canônicas, relativas a `Caminhos` (documentação)."""


@dataclass(frozen=True)
class Contexto:
    etapa: Etapa
    caminhos: Caminhos

    def ler(self, tabela: Tabela) -> pl.LazyFrame:
        if tabela not in self.etapa.le:
            raise KeyError(f"{self.etapa.nome} não declara leitura de {tabela.nome}")
        return schemas.ler(tabela, self.caminhos.dados)

    def gravar(self, tabela: Tabela, frame: pl.DataFrame | pl.LazyFrame) -> None:
        self._exige_saida(tabela)
        schemas.gravar(frame, tabela, self.caminhos.dados)

    def caminho(self, tabela: Tabela) -> Path:
        """Para etapas que gravam direto do DuckDB; o executor valida o arquivo depois."""
        self._exige_saida(tabela)
        return self.caminhos.dados / tabela.arquivo

    def _exige_saida(self, tabela: Tabela) -> None:
        if tabela not in self.etapa.grava:
            raise KeyError(f"{self.etapa.nome} não declara gravação de {tabela.nome}")


class ModuloDeEtapa(Protocol):
    ETAPA: Etapa

    def executar(self, ctx: Contexto) -> None: ...


MODULOS: dict[str, str] = {
    "fetch": "redes.fetch",
    "ingest-rfb": "redes.ingest.rfb",
    "ingest-tse": "redes.ingest.tse",
    "ingest-tcesp": "redes.ingest.tcesp",
    "elections": "redes.elections",
    "links": "redes.links",
    "network": "redes.network",
    "panel": "redes.panel",
    "estimate": "redes.estimate",
    "report": "redes.report",
    "deck": "redes.deck",
}


def modulo(nome: str) -> ModuloDeEtapa:
    return importlib.import_module(MODULOS[nome])  # type: ignore[return-value]


def rodar(nome: str, caminhos: Caminhos) -> None:
    mod = modulo(nome)
    etapa = mod.ETAPA
    for tabela in etapa.le:
        schemas.ler(tabela, caminhos.dados)
    mod.executar(Contexto(etapa, caminhos))
    for tabela in etapa.grava:
        schemas.validar(
            schemas.ler(tabela, caminhos.dados), tabela, caminhos.dados / tabela.arquivo
        )


def gravar_vazias(ctx: Contexto) -> None:
    """Corpo provisório de etapa ainda não implementada: saídas com o esquema e sem linhas."""
    print(f"aviso: {ctx.etapa.nome} é esqueleto; gravou tabelas vazias", file=sys.stderr)
    for tabela in ctx.etapa.grava:
        ctx.gravar(tabela, tabela.vazia())
