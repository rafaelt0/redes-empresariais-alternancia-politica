"""Executor sem shell: `uv run python -m redes.tarefas <alvo>`.

As dependências vêm de ETAPA, como no Makefile. Reexecuta os pré-requisitos em cada
invocação, sem reutilizar marcadores do make; cada etapa conserva seus caches internos.
"""

import argparse
import os
import shutil
import subprocess

from redes import amostra, dicionario, etapas
from redes.config import RAIZ, Caminhos

ALVOS = (
    *etapas.MODULOS,
    "setup",
    "all",
    "test",
    "lint",
    "sample",
    "clean-raw",
    "dicionario",
    "sensibilidades",
    "entrega-revisada",
)


def ordem(alvos: list[str], prontas: tuple[str, ...] = ()) -> list[str]:
    """Ordenação topológica, sem repetir etapas compartilhadas."""
    vistas = set(prontas)
    resultado = []

    def visitar(nome: str) -> None:
        if nome in vistas:
            return
        for dependencia in etapas.modulo(nome).ETAPA.depende:
            visitar(dependencia)
        vistas.add(nome)
        resultado.append(nome)

    for alvo in alvos:
        visitar(alvo)
    return resultado


def comando(*args: str) -> None:
    subprocess.run(["uv", *args], check=True, cwd=RAIZ)


def executar(alvo: str, sem_publicacao: bool = False) -> None:
    caminhos = Caminhos.do_ambiente()
    if alvo == "setup":
        comando("sync", "--frozen")
    elif alvo == "test":
        comando("run", "--frozen", "pytest")
    elif alvo == "lint":
        comando("run", "--frozen", "ruff", "check", ".")
        comando("run", "--frozen", "ruff", "format", "--check", ".")
    elif alvo == "clean-raw":
        shutil.rmtree(caminhos.brutos, ignore_errors=True)
    elif alvo == "dicionario":
        (RAIZ / "docs/dicionario.md").write_text(dicionario.gerar(), encoding="utf-8")
    elif alvo == "sample":
        dados = RAIZ / "data/amostra"
        shutil.rmtree(dados, ignore_errors=True)
        caminhos = Caminhos(dados, dados / "results", dados / "output", caminhos.chave)
        amostra.gravar_amostra(dados)
        alvos = ["estimate"] if sem_publicacao else ["report", "deck"]
        if sem_publicacao:
            print("Amostra sem publicação: report e deck omitidos explicitamente.")
        for nome in ordem(alvos, ("fetch", "ingest-rfb", "ingest-tse", "ingest-tcesp")):
            etapas.rodar(nome, caminhos)
    else:
        revisao = alvo in ("sensibilidades", "entrega-revisada")
        alvos = ["estimate"] if revisao else (["report", "deck"] if alvo == "all" else [alvo])
        for nome in ordem(alvos):
            etapas.rodar(nome, caminhos)
        if revisao:
            comando(
                "run",
                "--frozen",
                "python",
                "-m",
                "redes.sensibilidades",
                "--dados",
                str(caminhos.dados),
                "--cache",
                str(caminhos.dados / "sensibilidades"),
                "--tabelas",
                str(caminhos.resultados / "tables"),
                "--parciais-tcesp",
                os.environ.get("PARCIAIS_TCESP", str(caminhos.dados / "tcesp")),
            )
            for modulo in ("pre_periodos", "auditoria_h2", "rede_coortes"):
                comando("run", "--frozen", "python", "-m", f"redes.{modulo}")
            if alvo == "entrega-revisada":
                for nome in ("report", "deck"):
                    etapas.rodar(nome, caminhos)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("alvo", choices=ALVOS)
    parser.add_argument(
        "--sem-publicacao",
        action="store_true",
        default=os.environ.get("REDES_SEM_PUBLICACAO") == "1",
        help="somente sample: executa até estimate, sem TeX/LibreOffice",
    )
    args = parser.parse_args()
    if args.sem_publicacao and args.alvo != "sample":
        parser.error("--sem-publicacao só se aplica a sample")
    executar(args.alvo, args.sem_publicacao)


if __name__ == "__main__":
    main()
