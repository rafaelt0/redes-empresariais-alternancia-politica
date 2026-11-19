"""`python -m redes <etapa> [<etapa> ...]`, ou `python -m redes amostra`."""

import argparse
import time

from redes import amostra, etapas
from redes.config import Caminhos


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m redes", description=__doc__)
    parser.add_argument(
        "etapas",
        nargs="+",
        choices=[*etapas.MODULOS, "amostra"],
        help="etapas a rodar, na ordem dada; `amostra` grava a amostra sintética",
    )
    args = parser.parse_args(argv)
    caminhos = Caminhos.do_ambiente()
    for nome in args.etapas:
        inicio = time.perf_counter()
        if nome == "amostra":
            amostra.gravar_amostra(caminhos.dados)
        else:
            etapas.rodar(nome, caminhos)
        print(f"{nome}: ok em {time.perf_counter() - inicio:.1f}s")
