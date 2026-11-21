"""Integração sintética da CI; nunca chama ingestão ou fontes reais."""

import os
import shutil
import subprocess
import sys

from redes.portabilidade import ferramenta

ambiente = os.environ.copy()
for nome in ("latexmk", "soffice"):
    try:
        ferramenta(nome)
    except FileNotFoundError as erro:
        print(f"Publicação omitida explicitamente na CI: {erro}", flush=True)
        ambiente["REDES_SEM_PUBLICACAO"] = "1"

comando = (
    ["make", "sample"]
    if sys.platform != "win32" and shutil.which("make")
    else ["uv", "run", "--frozen", "python", "-m", "redes.tarefas", "sample"]
)
subprocess.run(comando, env=ambiente, check=True)
