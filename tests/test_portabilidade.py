import errno
import sys
from types import SimpleNamespace

import pytest

from redes import portabilidade


@pytest.mark.parametrize("windows", [False, True])
def test_trava_libera_apos_excecao(tmp_path, monkeypatch, windows):
    chamadas = []
    tentativas = iter([False, True, True])

    def locking(fd, modo, tamanho):
        assert tamanho == 1
        chamadas.append(modo)
        if not next(tentativas):
            raise OSError(errno.EACCES, "ocupado")

    monkeypatch.setattr(portabilidade, "WINDOWS", windows)
    monkeypatch.setitem(
        sys.modules, "msvcrt", SimpleNamespace(locking=locking, LK_NBLCK=1, LK_UNLCK=2)
    )
    monkeypatch.setitem(
        sys.modules,
        "fcntl",
        SimpleNamespace(flock=lambda fd, modo: chamadas.append(modo), LOCK_EX=3, LOCK_UN=4),
    )
    monkeypatch.setattr(portabilidade.time, "sleep", lambda _: None)
    with pytest.raises(ValueError), portabilidade.trava_exclusiva(tmp_path / "arquivo.trava"):
        raise ValueError("interrompido")
    assert chamadas == ([1, 1, 2] if windows else [3, 4])


def test_ferramenta_override_e_erro(tmp_path, monkeypatch):
    executavel = tmp_path / "pasta com espaços" / "soffice.exe"
    executavel.parent.mkdir()
    executavel.touch(mode=0o755)
    monkeypatch.setenv("REDES_SOFFICE", str(executavel))
    assert portabilidade.ferramenta("soffice") == str(executavel)
    monkeypatch.setenv("REDES_SOFFICE", str(tmp_path / "ausente"))
    with pytest.raises(FileNotFoundError, match="REDES_SOFFICE"):
        portabilidade.ferramenta("soffice")


def _incrementar(caminho):
    from redes.fetch import _gravar_json, _ler_json
    from redes.portabilidade import trava_exclusiva

    for _ in range(15):
        with trava_exclusiva(caminho.with_suffix(".trava")):
            dados = _ler_json(caminho)
            _gravar_json(caminho, {"ação": dados.get("ação", 0) + 1})


def test_trava_entre_processos_e_json_utf8(tmp_path):
    import multiprocessing

    from redes.fetch import _ler_json

    caminho = tmp_path / "manifest.json"
    ctx = multiprocessing.get_context("spawn")
    processos = [ctx.Process(target=_incrementar, args=(caminho,)) for _ in range(3)]
    for processo in processos:
        processo.start()
    try:
        for processo in processos:
            processo.join(30)
            assert processo.exitcode == 0
    finally:
        for processo in processos:
            if processo.is_alive():
                processo.terminate()
                processo.join()
    assert _ler_json(caminho) == {"ação": 45}
    assert b"\r\n" not in caminho.read_bytes()
    assert "ação" in caminho.read_bytes().decode("utf-8")


@pytest.mark.parametrize(
    "plataforma,windows,nome,trecho",
    [
        ("darwin", False, "soffice", "LibreOffice.app"),
        ("darwin", False, "latexmk", "/Library/TeX"),
        ("win32", True, "soffice", "LibreOffice/program/soffice.exe"),
        ("win32", True, "latexmk", "MiKTeX"),
    ],
)
def test_locais_conhecidos(monkeypatch, plataforma, windows, nome, trecho):
    monkeypatch.setattr(portabilidade.sys, "platform", plataforma)
    monkeypatch.setattr(portabilidade, "WINDOWS", windows)
    assert any(trecho in p.as_posix() for p in portabilidade.locais_ferramenta(nome))


def test_path_tem_prioridade_e_local_conhecido_e_fallback(monkeypatch):
    monkeypatch.delenv("REDES_SOFFICE", raising=False)
    monkeypatch.setattr(portabilidade, "locais_ferramenta", lambda _: ["/app/soffice"])
    monkeypatch.setattr(
        portabilidade.shutil,
        "which",
        lambda p: {
            "soffice": "/path/soffice",
            "/path/soffice": "/path/soffice",
            "/app/soffice": "/app/soffice",
        }.get(p),
    )
    assert portabilidade.ferramenta("soffice") == "/path/soffice"
    monkeypatch.setattr(
        portabilidade.shutil, "which", lambda p: "/app/soffice" if p == "/app/soffice" else None
    )
    assert portabilidade.ferramenta("soffice") == "/app/soffice"
