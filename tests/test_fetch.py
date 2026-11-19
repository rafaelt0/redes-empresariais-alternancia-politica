import hashlib
import json
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from redes import fetch, fontes
from redes.config import Caminhos
from redes.etapas import Contexto
from redes.fontes import Arquivo

CONTEUDO = bytes(range(256)) * 4096
LAST_MODIFIED = "Tue, 20 May 2025 19:08:09 GMT"


@dataclass
class Servidor:
    base: str
    conteudo: bytes = CONTEUDO
    cortar_primeira_em: int | None = None
    pedidos: list[dict[str, str]] = field(default_factory=list)


@pytest.fixture
def servidor() -> Iterator[Servidor]:
    estado = Servidor(base="")

    class Manipulador(BaseHTTPRequestHandler):
        def do_GET(self):
            estado.pedidos.append(dict(self.headers))
            if self.path != "/dados.zip":
                self.send_error(404)
                return
            corpo = estado.conteudo
            intervalo = self.headers.get("Range")
            if intervalo and self.headers.get("If-Range") == LAST_MODIFIED:
                inicio = int(intervalo.removeprefix("bytes=").rstrip("-"))
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {inicio}-{len(corpo) - 1}/{len(corpo)}")
                corpo = corpo[inicio:]
            else:
                self.send_response(200)
            self.send_header("Content-Length", str(len(corpo)))
            self.send_header("Last-Modified", LAST_MODIFIED)
            self.end_headers()
            if estado.cortar_primeira_em is not None and len(estado.pedidos) == 1:
                corpo = corpo[: estado.cortar_primeira_em]
            self.wfile.write(corpo)

        def log_message(self, *args):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Manipulador)
    estado.base = f"http://127.0.0.1:{httpd.server_port}"
    threading.Thread(target=httpd.serve_forever, args=(0.01,), daemon=True).start()
    yield estado
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture
def caminhos(tmp_path: Path) -> Caminhos:
    return Caminhos(tmp_path / "dados", tmp_path / "results", tmp_path / "output", tmp_path / "c")


@pytest.fixture(autouse=True)
def sem_espera(monkeypatch):
    monkeypatch.setattr(fetch.time, "sleep", lambda _: None)
    monkeypatch.delenv("REDES_ESTRITO", raising=False)
    monkeypatch.delenv("REDES_APAGAR_BRUTOS", raising=False)


def _arquivo(servidor: Servidor, imutavel: bool = True, nome: str = "dados.zip") -> Arquivo:
    return Arquivo("teste", f"{servidor.base}/{nome}", imutavel)


def _manifesto(caminhos: Caminhos) -> dict:
    return json.loads((caminhos.dados / "manifest.json").read_text())


def _trava(tmp_path: Path, sha: str) -> Path:
    trava = tmp_path / "fontes.lock.json"
    trava.write_text(json.dumps({"teste/dados.zip": {"sha256": sha}}))
    return trava


SHA = hashlib.sha256(CONTEUDO).hexdigest()


def test_download_novo_registra_no_manifesto(servidor, caminhos, tmp_path):
    arquivo = _arquivo(servidor)
    caminho = fetch.garantir(arquivo, caminhos, tmp_path / "sem-trava.json")

    assert caminho == caminhos.brutos / "teste" / "dados.zip"
    assert caminho.read_bytes() == CONTEUDO
    registro = _manifesto(caminhos)["teste/dados.zip"]
    assert registro["url"] == arquivo.url
    assert registro["tamanho"] == len(CONTEUDO)
    assert registro["sha256"] == SHA
    assert registro["last_modified"] == LAST_MODIFIED
    assert registro["baixado_em"]
    assert "redes-pipeline" in servidor.pedidos[0]["User-Agent"]


def test_retoma_download_interrompido(servidor, caminhos, tmp_path):
    servidor.cortar_primeira_em = 300_000
    caminho = fetch.garantir(_arquivo(servidor), caminhos, tmp_path / "sem-trava.json")

    assert caminho.read_bytes() == CONTEUDO
    assert len(servidor.pedidos) == 2
    assert servidor.pedidos[1]["Range"] == "bytes=300000-"
    assert not list(caminho.parent.glob("*.parcial*"))


def test_arquivo_presente_e_integro_nao_e_baixado_de_novo(servidor, caminhos, tmp_path):
    trava = tmp_path / "sem-trava.json"
    fetch.garantir(_arquivo(servidor), caminhos, trava)
    fetch.garantir(_arquivo(servidor), caminhos, trava)

    assert len(servidor.pedidos) == 1


def test_arquivo_corrompido_no_disco_e_baixado_de_novo(servidor, caminhos, tmp_path):
    trava = tmp_path / "sem-trava.json"
    caminho = fetch.garantir(_arquivo(servidor), caminhos, trava)
    caminho.write_bytes(b"lixo")
    fetch.garantir(_arquivo(servidor), caminhos, trava)

    assert caminho.read_bytes() == CONTEUDO
    assert len(servidor.pedidos) == 2


def test_divergencia_em_fonte_imutavel_e_erro(servidor, caminhos, tmp_path):
    with pytest.raises(fetch.ErroDeFonte, match="fontes.lock.json registra 0+"):
        fetch.garantir(_arquivo(servidor), caminhos, _trava(tmp_path, "0" * 64))

    assert list((caminhos.brutos / "teste").iterdir()) == []
    assert not (caminhos.dados / "manifest.json").exists()


def test_divergencia_em_fonte_mutavel_e_aviso(servidor, caminhos, tmp_path, capsys):
    fetch.garantir(_arquivo(servidor, imutavel=False), caminhos, _trava(tmp_path, "0" * 64))

    registro = _manifesto(caminhos)["teste/dados.zip"]
    assert registro["sha256"] == SHA
    assert "fontes.lock.json registra 0" in registro["aviso"]
    assert "aviso: teste/dados.zip" in capsys.readouterr().err


def test_divergencia_em_fonte_mutavel_e_erro_no_modo_estrito(
    servidor, caminhos, tmp_path, monkeypatch
):
    monkeypatch.setenv("REDES_ESTRITO", "1")
    with pytest.raises(fetch.ErroDeFonte):
        fetch.garantir(_arquivo(servidor, imutavel=False), caminhos, _trava(tmp_path, "0" * 64))


def test_modo_estrito_exige_hash_registrado_antes_do_download(
    servidor, caminhos, tmp_path, monkeypatch
):
    monkeypatch.setenv("REDES_ESTRITO", "1")
    with pytest.raises(fetch.ErroDeFonte, match="ausente na trava"):
        fetch.garantir(_arquivo(servidor), caminhos, tmp_path / "sem-trava.json")
    assert not servidor.pedidos


def test_fetch_estrito_verifica_apenas_arquivos_registrados(
    servidor, caminhos, tmp_path, monkeypatch
):
    principal = _arquivo(servidor)
    auxiliar = _arquivo(servidor, nome="auxiliar.zip")
    arquivos = {a.chave: a for a in (principal, auxiliar)}
    monkeypatch.setattr(fetch, "ARQUIVOS", arquivos)
    monkeypatch.setattr(fetch, "TRAVA", _trava(tmp_path, SHA))
    monkeypatch.setenv("REDES_ESTRITO", "1")
    chamados = []
    monkeypatch.setattr(fetch, "garantir", lambda a, _: chamados.append(a.chave))
    fetch.executar(Contexto(fetch.ETAPA, caminhos))
    assert chamados == [principal.chave]


def test_conteudo_novo_diverge_do_manifesto_anterior(servidor, caminhos, tmp_path):
    trava = tmp_path / "sem-trava.json"
    caminho = fetch.garantir(_arquivo(servidor), caminhos, trava)
    caminho.unlink()
    servidor.conteudo = CONTEUDO[::-1]

    with pytest.raises(fetch.ErroDeFonte, match=f"manifesto registra {SHA}"):
        fetch.garantir(_arquivo(servidor), caminhos, trava)


def test_trava_igual_ao_baixado_passa_e_travar_regrava(servidor, caminhos, tmp_path):
    trava = _trava(tmp_path, SHA)
    fetch.garantir(_arquivo(servidor), caminhos, trava)
    trava.write_text("{}")
    fetch.travar(caminhos, trava)

    travado = json.loads(trava.read_text())["teste/dados.zip"]
    assert travado == {"url": f"{servidor.base}/dados.zip", "tamanho": len(CONTEUDO), "sha256": SHA}


def test_404_falha_sem_novas_tentativas(servidor, caminhos, tmp_path):
    with pytest.raises(fetch.ErroDeFonte, match="HTTP 404"):
        fetch.garantir(_arquivo(servidor, nome="falta.zip"), caminhos, tmp_path / "t.json")
    assert len(servidor.pedidos) == 1


def test_descartar_so_apaga_com_a_variavel(servidor, caminhos, tmp_path, monkeypatch):
    arquivo = _arquivo(servidor)
    caminho = fetch.garantir(arquivo, caminhos, tmp_path / "sem-trava.json")
    fetch.descartar(arquivo, caminhos)
    assert caminho.exists()

    monkeypatch.setenv("REDES_APAGAR_BRUTOS", "1")
    fetch.descartar(arquivo, caminhos)
    assert not caminho.exists()
    assert "teste/dados.zip" in _manifesto(caminhos)


def test_registro_de_fontes_tem_chaves_unicas_e_https():
    todos = [a for arquivos in fontes.FONTES.values() for a in arquivos]
    assert len(todos) == len(fontes.ARQUIVOS)
    assert all(a.url.startswith("https://") for a in todos)
    assert {a.fonte for a in todos if a.imutavel} == {"rfb-2024-09", "rfb-2024-10"}
