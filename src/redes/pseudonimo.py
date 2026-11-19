"""Pseudônimo de pessoa física, comum a sócios (Receita) e doadores (TSE).

A Receita publica o CPF do sócio mascarado (`***123456**`) e o TSE publica o CPF completo do
doador; o par (nome normalizado, 6 dígitos centrais) é o que as duas bases têm em comum
(seção 5 do projeto). O HMAC com chave local impede reverter o pseudônimo a partir de nomes
e CPFs públicos sem a chave.
"""

import hashlib
import hmac
import re
import secrets
import tempfile
import unicodedata
from contextlib import suppress
from pathlib import Path

import polars as pl

TAMANHO_PSEUDONIMO = 16
TAMANHO_CHAVE = 32

_NAO_LETRA = re.compile(r"[^A-Z ]+")
_ESPACOS = re.compile(r" +")


def normalizar_nome(nome: str) -> str:
    """Maiúsculas, sem acentos nem pontuação, espaços simples."""
    sem_acento = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode("ascii")
    so_letras = _NAO_LETRA.sub(" ", sem_acento.upper())
    return _ESPACOS.sub(" ", so_letras).strip()


def digitos_centrais(cpf: str) -> str:
    """Os 6 dígitos centrais (posições 4 a 9) de um CPF completo ou mascarado pela Receita."""
    limpo = cpf.strip()
    if re.fullmatch(r"\*{3}\d{6}\*{2}", limpo):
        return limpo[3:9]
    digitos = re.sub(r"[.\-\s]", "", limpo)
    if re.fullmatch(r"\d{11}", digitos):
        return digitos[3:9]
    raise ValueError("CPF fora dos formatos completo (11 dígitos) ou mascarado (***dddddd**)")


def pseudonimo(nome: str, cpf: str, chave: bytes) -> str:
    mensagem = f"{normalizar_nome(nome)}|{digitos_centrais(cpf)}".encode()
    return hmac.new(chave, mensagem, hashlib.sha256).hexdigest()[:TAMANHO_PSEUDONIMO]


def pseudonimizar(nomes: pl.Series, cpfs: pl.Series, chave: bytes) -> pl.Series:
    """Versão vetorial de `pseudonimo`, para as etapas de ingestão."""
    return pl.Series(
        "id_pessoa",
        [pseudonimo(n, c, chave) for n, c in zip(nomes, cpfs, strict=True)],
        dtype=pl.String,
    )


def carregar_chave(caminho: Path) -> bytes:
    """Publica a chave completa com um link atômico, inclusive em ingestões concorrentes."""
    try:
        chave = caminho.read_bytes()
    except FileNotFoundError:
        caminho.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=caminho.parent) as pasta:
            nova = Path(pasta) / "chave"
            nova.touch(mode=0o600)
            nova.write_bytes(secrets.token_bytes(TAMANHO_CHAVE))
            with suppress(FileExistsError):
                caminho.hardlink_to(nova)
        chave = caminho.read_bytes()
    if len(chave) != TAMANHO_CHAVE:
        raise ValueError(f"chave de pseudonimização deve conter {TAMANHO_CHAVE} bytes")
    return chave
