"""Travas de arquivo e descoberta das ferramentas externas nos três sistemas."""

import errno
import os
import shutil
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

WINDOWS = sys.platform == "win32"


@contextmanager
def trava_exclusiva(caminho: Path) -> Iterator[None]:
    """Espera pela exclusão mútua; o SO libera a trava se o processo morrer.

    O arquivo lateral permanece: removê-lo permitiria travar dois inodes diferentes.
    No Windows, reserva o primeiro byte, inclusive num arquivo inicialmente vazio.
    """
    with caminho.open("a+b") as arquivo:
        if WINDOWS:
            import msvcrt

            while True:
                arquivo.seek(0)
                try:
                    msvcrt.locking(arquivo.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError as erro:
                    if erro.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                        raise
                    time.sleep(0.05)
        else:
            import fcntl

            fcntl.flock(arquivo, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if WINDOWS:
                arquivo.seek(0)
                msvcrt.locking(arquivo.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(arquivo, fcntl.LOCK_UN)


def locais_ferramenta(nome: str) -> list[Path]:
    """Instalações usuais; o PATH continua tendo prioridade."""
    if sys.platform == "darwin":
        if nome == "soffice":
            return [Path("/Applications/LibreOffice.app/Contents/MacOS/soffice")]
        return [Path("/Library/TeX/texbin/latexmk")]
    if WINDOWS:
        if nome == "soffice":
            return [
                Path(os.environ.get(var, padrao)) / "LibreOffice/program/soffice.exe"
                for var, padrao in (
                    ("PROGRAMFILES", "C:/Program Files"),
                    ("PROGRAMFILES(X86)", "C:/Program Files (x86)"),
                )
            ]
        raizes = [
            Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "MiKTeX/miktex/bin/x64",
            Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local")))
            / "Programs/MiKTeX/miktex/bin/x64",
        ]
        raizes += sorted(Path("C:/texlive").glob("*/bin/windows"), reverse=True)
        return [raiz / "latexmk.exe" for raiz in raizes]
    return []


def ferramenta(nome: str) -> str:
    """Resolve um executável, sem interpretar comandos de shell ou separar espaços."""
    variavel = f"REDES_{nome.upper()}"
    override = os.environ.get(variavel)
    candidatos = [override] if override else [shutil.which(nome), *locais_ferramenta(nome)]
    for candidato in candidatos:
        if candidato and (resolvido := shutil.which(str(candidato))):
            return resolvido
    pacote = "LibreOffice" if nome == "soffice" else "TeX Live/MacTeX completo (ou MiKTeX e Perl)"
    raise FileNotFoundError(
        f"{nome} não encontrado. Instale {pacote}, adicione ao PATH ou defina "
        f"{variavel} com o caminho completo do executável, sem argumentos."
    )
