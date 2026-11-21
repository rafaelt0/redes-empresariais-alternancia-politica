from redes import etapas, tarefas
from redes.config import RAIZ


def test_ordem_respeita_todas_as_dependencias():
    for alvo in etapas.MODULOS:
        ordem = tarefas.ordem([alvo])
        assert ordem[-1] == alvo
        assert len(ordem) == len(set(ordem))
        for indice, nome in enumerate(ordem):
            assert set(etapas.modulo(nome).ETAPA.depende) <= set(ordem[:indice])
    assert set(tarefas.ordem(["report", "deck"])) == set(etapas.MODULOS) - {"fetch"}


def test_sample_isola_saidas_sem_download(monkeypatch):
    chamadas = []
    monkeypatch.setattr(tarefas.shutil, "rmtree", lambda *a, **kw: None)
    monkeypatch.setattr(tarefas.amostra, "gravar_amostra", lambda p: chamadas.append(p))
    monkeypatch.setattr(tarefas.etapas, "rodar", lambda n, c: chamadas.append((n, c)))
    tarefas.executar("sample")
    assert chamadas[0] == RAIZ / "data/amostra"
    assert [n for n, _ in chamadas[1:]] == list(etapas.MODULOS)[4:]
    for _, caminhos in chamadas[1:]:
        assert caminhos.resultados == RAIZ / "data/amostra/results"
        assert caminhos.saida == RAIZ / "data/amostra/output"


def test_sample_sem_publicacao_explicito(monkeypatch, capsys):
    chamadas = []
    monkeypatch.setattr(tarefas.shutil, "rmtree", lambda *a, **kw: None)
    monkeypatch.setattr(tarefas.amostra, "gravar_amostra", lambda p: None)
    monkeypatch.setattr(tarefas.etapas, "rodar", lambda n, c: chamadas.append(n))
    tarefas.executar("sample", sem_publicacao=True)
    assert chamadas == list(etapas.MODULOS)[4:-2]
    assert "omitidos explicitamente" in capsys.readouterr().out


def test_alvos_da_spec_e_auxiliares_preservados():
    assert set(etapas.MODULOS) <= set(tarefas.ALVOS)
    assert {
        "all",
        "setup",
        "sample",
        "test",
        "lint",
        "clean-raw",
        "dicionario",
        "sensibilidades",
        "entrega-revisada",
    } <= set(tarefas.ALVOS)


def test_falha_interrompe_dependentes(monkeypatch):
    import pytest

    chamadas = []

    def rodar(nome, caminhos):
        chamadas.append(nome)
        raise RuntimeError("falha na ingestão")

    monkeypatch.setattr(tarefas.etapas, "rodar", rodar)
    with pytest.raises(RuntimeError, match="falha na ingestão"):
        tarefas.executar("all")
    assert chamadas == ["ingest-tcesp"]


def test_test_e_lint_usam_uv_sem_shell(monkeypatch):
    chamadas = []
    monkeypatch.setattr(tarefas.subprocess, "run", lambda args, **kw: chamadas.append((args, kw)))
    for alvo in ("setup", "test", "lint"):
        tarefas.executar(alvo)
    assert [args for args, _ in chamadas] == [
        ["uv", "sync", "--frozen"],
        ["uv", "run", "--frozen", "pytest"],
        ["uv", "run", "--frozen", "ruff", "check", "."],
        ["uv", "run", "--frozen", "ruff", "format", "--check", "."],
    ]
    assert all(kw == {"check": True, "cwd": RAIZ} for _, kw in chamadas)
