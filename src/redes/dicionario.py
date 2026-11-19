"""Gera `docs/dicionario.md` a partir de `redes.schemas` e das declarações das etapas."""

import inspect

import polars as pl

from redes import etapas, schemas

CABECALHO = """\
# Dicionário de dados

Gerado por `make dicionario` a partir de `src/redes/schemas.py`; não edite à mão.
`tests/test_schemas.py` falha quando este arquivo e o módulo divergem.

Todas as tabelas ficam em `$REDES_DATA_DIR` (padrão `data/`), fora do git.

## Convenções

{convencoes}

Tipos enumerados aceitam só os valores listados entre chaves.
"""


def _tipo(tipo: pl.DataType) -> str:
    if isinstance(tipo, pl.Enum):
        return "Enum{" + ", ".join(tipo.categories.to_list()) + "}"
    return str(tipo)


def _convencoes() -> str:
    doc = inspect.getdoc(schemas) or ""
    return doc.split("Convenções de identificador, comuns a todas as tabelas:\n", 1)[1].strip()


def gerar() -> str:
    produtora = {t.nome: e for e in etapas.MODULOS for t in etapas.modulo(e).ETAPA.grava}
    leitoras: dict[str, list[str]] = {}
    for e in etapas.MODULOS:
        for t in etapas.modulo(e).ETAPA.le:
            leitoras.setdefault(t.nome, []).append(e)

    secoes = [CABECALHO.format(convencoes=_convencoes())]
    for tabela in schemas.TABELAS.values():
        lida_por = ", ".join(f"`{e}`" for e in leitoras.get(tabela.nome, [])) or "nenhuma etapa"
        secao = (
            f"## `{tabela.arquivo}`\n\n{tabela.descricao}\n\n"
            f"Gravada por `{produtora[tabela.nome]}`; lida por {lida_por}. "
            f"Chave primária: {', '.join(f'`{c}`' for c in tabela.chave)}.\n\n"
            "| Coluna | Tipo | Nula | Descrição |\n|---|---|---|---|\n"
            + "".join(
                f"| `{c.nome}` | {_tipo(c.tipo)} | {'sim' if c.nula else 'não'} | {c.descricao} |\n"
                for c in tabela.colunas
            )
        )
        if tabela.checagens:
            secao += "\nChecagens na gravação:\n\n" + "".join(
                f"- {ch.descricao}\n" for ch in tabela.checagens
            )
        secoes.append(secao)
    return "\n".join(secoes)


if __name__ == "__main__":
    print(gerar(), end="")
