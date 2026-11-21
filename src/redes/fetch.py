"""Etapa `fetch`: baixa os arquivos brutos e registra cada um em `dados/manifest.json` (T03).

Os brutos somam mais do que o disco da máquina de desenvolvimento, por isso a unidade é o
arquivo: cada `ingest-*` chama `garantir` para o que vai ler e `descartar` depois de gravar o
Parquet. A etapa `fetch` baixa tudo, para quem tem disco.

`fontes.lock.json`, versionado, guarda o SHA-256 dos arquivos da execução que gerou os
resultados publicados. Um arquivo novo que diverge dele, ou do que o manifesto já registrava, é
erro numa fonte imutável e aviso numa mutável (erro com `REDES_ESTRITO=1`). Para regravar a
trava a partir do manifesto: `uv run python -m redes.fetch travar`.
"""

import hashlib
import http.client
import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from redes.config import RAIZ, Caminhos
from redes.etapas import Contexto, Etapa
from redes.fontes import ARQUIVOS, Arquivo
from redes.portabilidade import trava_exclusiva

ETAPA = Etapa(
    nome="fetch",
    depende=(),
    le=(),
    grava=(),
    artefatos=("dados/raw/", "dados/manifest.json"),
)

TRAVA = RAIZ / "fontes.lock.json"
USER_AGENT = "redes-pipeline/0.1 (download de dados abertos)"
TIMEOUT = 60
TENTATIVAS = 5
BLOCO = 1 << 20
FOLGA_DE_DISCO = 512 << 20


class ErroDeFonte(RuntimeError):
    pass


def garantir(arquivo: Arquivo, caminhos: Caminhos, trava: Path = TRAVA) -> Path:
    """Devolve o caminho do bruto, baixando-o se falta ou não confere com o manifesto."""
    destino = caminhos.brutos / arquivo.chave
    anterior = _ler_manifesto(caminhos).get(arquivo.chave, {})
    travado = _ler_json(trava).get(arquivo.chave, {})
    if os.environ.get("REDES_ESTRITO") == "1" and not travado.get("sha256"):
        raise ErroDeFonte(f"{arquivo.chave}: SHA-256 ausente na trava de fontes")
    if destino.exists() and anterior and _sha256(destino) == anterior["sha256"]:
        _conferir(arquivo, anterior["sha256"], {"fontes.lock.json": travado})
        return destino

    destino.parent.mkdir(parents=True, exist_ok=True)
    parcial = destino.with_name(destino.name + ".parcial")
    validador = _baixar(arquivo.url, parcial)
    sha = _sha256(parcial)
    try:
        aviso = _conferir(arquivo, sha, {"fontes.lock.json": travado, "manifesto": anterior})
    except ErroDeFonte:
        parcial.unlink()
        raise
    parcial.replace(destino)
    registro = {
        "url": arquivo.url,
        "tamanho": destino.stat().st_size,
        "sha256": sha,
        "baixado_em": datetime.now(UTC).isoformat(timespec="seconds"),
        "last_modified": validador.get("last_modified"),
    }
    if aviso:
        registro["aviso"] = aviso
    with _editar_manifesto(caminhos) as manifesto:
        manifesto[arquivo.chave] = registro
    return destino


def descartar(arquivo: Arquivo, caminhos: Caminhos) -> None:
    """Apaga o bruto já ingerido quando `REDES_APAGAR_BRUTOS=1`; o manifesto fica."""
    if os.environ.get("REDES_APAGAR_BRUTOS") == "1":
        (caminhos.brutos / arquivo.chave).unlink(missing_ok=True)


def travar(caminhos: Caminhos, trava: Path = TRAVA) -> None:
    """Atualiza a trava com o SHA-256 e o tamanho de cada arquivo registrado no manifesto."""
    travado = _ler_json(trava)
    for chave, registro in _ler_manifesto(caminhos).items():
        travado[chave] = {k: registro[k] for k in ("url", "tamanho", "sha256")}
    _gravar_json(trava, travado)


def arquivos_selecionados() -> tuple[Arquivo, ...]:
    chaves = _ler_json(TRAVA) if os.environ.get("REDES_ESTRITO") == "1" else ARQUIVOS
    arquivos = tuple(arquivo for chave, arquivo in ARQUIVOS.items() if chave in chaves)
    if not arquivos:
        raise ErroDeFonte("trava de fontes vazia")
    return arquivos


def executar(ctx: Contexto) -> None:
    for arquivo in arquivos_selecionados():
        garantir(arquivo, ctx.caminhos)


def _conferir(arquivo: Arquivo, sha: str, referencias: dict[str, dict]) -> str | None:
    divergentes = [
        f"{origem} registra {ref['sha256']}"
        for origem, ref in referencias.items()
        if ref and ref["sha256"] != sha
    ]
    if not divergentes:
        return None
    mensagem = f"{arquivo.chave}: SHA-256 {sha} diverge ({'; '.join(divergentes)})"
    if arquivo.imutavel or os.environ.get("REDES_ESTRITO") == "1":
        raise ErroDeFonte(mensagem)
    print(f"aviso: {mensagem}", file=sys.stderr)
    return mensagem


def _baixar(url: str, parcial: Path) -> dict:
    """Baixa em fluxo para `parcial`, retomando de onde parou; devolve o validador do servidor.

    O validador (ETag ou Last-Modified da primeira resposta) fica ao lado do parcial e vai no
    `If-Range` da retomada: se o arquivo mudou no servidor, ele responde 200 e recomeça do zero.
    """
    for tentativa in range(1, TENTATIVAS + 1):
        try:
            return _tentar(url, parcial)
        except urllib.error.HTTPError as erro:
            if erro.code == 416:
                parcial.unlink(missing_ok=True)
            elif erro.code < 500:
                raise ErroDeFonte(f"{url}: HTTP {erro.code}") from erro
            ultimo: Exception = erro
        except (OSError, http.client.HTTPException) as erro:
            ultimo = erro
        print(f"aviso: {url}: tentativa {tentativa} falhou ({ultimo})", file=sys.stderr)
        if tentativa < TENTATIVAS:
            time.sleep(min(2**tentativa, 60))
    raise ErroDeFonte(f"{url}: {TENTATIVAS} tentativas falharam") from ultimo


def _tentar(url: str, parcial: Path) -> dict:
    lateral = parcial.with_name(parcial.name + ".json")
    inicio = parcial.stat().st_size if parcial.exists() else 0
    validador = _ler_json(lateral) if inicio else {}
    cabecalhos = {"User-Agent": USER_AGENT}
    if inicio:
        cabecalhos["Range"] = f"bytes={inicio}-"
        etag = validador.get("etag")
        etag_forte = etag if etag and not etag.startswith("W/") else None
        if if_range := etag_forte or validador.get("last_modified"):
            cabecalhos["If-Range"] = if_range
    pedido = urllib.request.Request(url, headers=cabecalhos)
    with urllib.request.urlopen(pedido, timeout=TIMEOUT) as resposta:
        if resposta.status == 206:
            total = int(resposta.headers["Content-Range"].rsplit("/", 1)[1])
            modo = "ab"
        else:
            inicio, modo = 0, "wb"
            comprimento = resposta.headers.get("Content-Length")
            total = int(comprimento) if comprimento else None
            validador = {
                "etag": resposta.headers.get("ETag"),
                "last_modified": resposta.headers.get("Last-Modified"),
            }
            _gravar_json(lateral, validador)
        if total is not None:
            _exigir_espaco(parcial.parent, total - inicio)
        with parcial.open(modo) as saida:
            shutil.copyfileobj(resposta, saida, BLOCO)
    tamanho = parcial.stat().st_size
    if total is not None and tamanho != total:
        raise http.client.IncompleteRead(b"", total - tamanho)
    lateral.unlink(missing_ok=True)
    return validador


def _exigir_espaco(pasta: Path, faltam: int) -> None:
    livre = shutil.disk_usage(pasta).free
    if livre < faltam + FOLGA_DE_DISCO:
        raise ErroDeFonte(
            f"disco: faltam {faltam / 2**30:.2f} GiB em {pasta} e há {livre / 2**30:.2f} GiB "
            "livres; baixe por etapa (ingest-*) com REDES_APAGAR_BRUTOS=1"
        )


def _sha256(caminho: Path) -> str:
    with caminho.open("rb") as entrada:
        return hashlib.file_digest(entrada, "sha256").hexdigest()


def _manifesto(caminhos: Caminhos) -> Path:
    return caminhos.dados / "manifest.json"


def _ler_manifesto(caminhos: Caminhos) -> dict:
    """Serializa também leitores: no Windows um arquivo aberto pode impedir replace."""
    caminho = _manifesto(caminhos)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with trava_exclusiva(caminho.with_name(caminho.name + ".trava")):
        return _ler_json(caminho)


def _ler_json(caminho: Path) -> dict:
    return json.loads(caminho.read_text(encoding="utf-8")) if caminho.exists() else {}


def _gravar_json(caminho: Path, dados: dict) -> None:
    temporario = caminho.with_name(caminho.name + ".tmp")
    texto = json.dumps(dados, indent=2, ensure_ascii=False, sort_keys=True)
    temporario.write_text(texto + "\n", encoding="utf-8", newline="\n")
    temporario.replace(caminho)


@contextmanager
def _editar_manifesto(caminhos: Caminhos) -> Iterator[dict]:
    """Ler, alterar e gravar sob trava de arquivo: as `ingest-*` rodam em paralelo."""
    caminho = _manifesto(caminhos)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with trava_exclusiva(caminho.with_name(caminho.name + ".trava")):
        manifesto = _ler_json(caminho)
        yield manifesto
        _gravar_json(caminho, manifesto)


if __name__ == "__main__":
    if sys.argv[1:] == ["listar"]:
        print(*(a.chave for a in arquivos_selecionados()), sep="\n")
    elif sys.argv[1:] == ["travar"]:
        travar(Caminhos.do_ambiente())
    else:
        sys.exit("uso: python -m redes.fetch listar|travar")
