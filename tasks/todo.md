# Tarefas

Ordem por dependência. Cada tarefa termina com `make test` e `make lint` passando. Detalhes em `SPEC.md` e `tasks/plan.md`.

## Fase 0 — Esqueleto

- [x] **T01: Ambiente e estrutura**
  - Aceite: `pyproject.toml` com Python 3.12 e dependências fixadas em `uv.lock`; `Makefile` com os alvos da especificação; `.gitignore` cobre `data/` e a chave de pseudonimização; `docs/projeto.pdf` no repositório.
  - Verificar: `make setup && make lint && make test` em clone limpo.
  - Arquivos: `pyproject.toml`, `uv.lock`, `Makefile`, `.gitignore`, `src/redes/__init__.py`, `src/redes/config.py`

- [x] **T02: CLI e fixtures da Figura 1**
  - Aceite: `python -m redes <etapa>` despacha para cada etapa; `src/redes/amostra.py` gera as tabelas canônicas já ingeridas, com X, Y, Z, Ana, Bruno, Carla e Daniel num município e outros 59 municípios sintéticos com salto conhecido.
  - Verificar: `make sample` percorre todas as etapas (ainda vazias) sem erro.
  - Arquivos: `src/redes/cli.py`, `src/redes/etapas.py`, `src/redes/schemas.py`, `src/redes/amostra.py`, `tests/conftest.py`

## Fase 1 — Viabilidade

- [x] **T03: `fetch` com manifesto**
  - Aceite: baixa em fluxo, retoma download interrompido, grava URL, data e SHA-256 em `data/manifest.json`; falha se o checksum de um arquivo já registrado mudar; aceita `REDES_DATA_DIR`. Registra a página oficial que aponta para o compartilhamento da Receita.
  - Verificar: teste com servidor local; download real de `Socios1.zip` de 2024-09 confere com o manifesto.
  - Arquivos: `src/redes/fetch.py`, `src/redes/config.py`, `tests/test_fetch.py`

- [x] **T04: `ingest-rfb`**
  - Aceite: lê `Socios*.zip` e `Empresas*.zip` de 2024-09 sem extrair para disco; grava `socios.parquet` com CNPJ básico, tipo de sócio, pseudônimo, qualificação e data de entrada; nomes e CPFs não chegam ao Parquet em claro; asserção de que nenhuma data de entrada passa de 14/09/2024.
  - Verificar: `tests/test_ingest_rfb.py`; contagem de linhas reais em `validacao.csv`.
  - Arquivos: `src/redes/ingest/rfb.py`, `src/redes/pseudonimo.py`, `tests/test_ingest_rfb.py`

- [x] **T05: `ingest-tse`**
  - Aceite: candidatos a prefeito de SP em 2020 e 2024, votação de 2024 por município, coligações e receitas de campanha com data da receita; doador pseudonimizado pela mesma chave de T04; confirma se o CPF do doador vem completo (questão 4 da especificação).
  - Verificar: `tests/test_ingest_tse.py`; total de votos válidos de três municípios conferido com o site do TSE.
  - Arquivos: `src/redes/ingest/tse.py`, `tests/test_ingest_tse.py`, `docs/dicionario.md`

- [x] **T06: `ingest-tcesp`**
  - Aceite: inspeciona cabeçalhos e layout oficial antes de ler; empenhos de 2021 a 2025 por município, CNPJ básico, elemento de despesa, data e tipo de evento; valor líquido = emissão + reforço − anulação; credores pessoa física descartados; licitações e ajustes com chave de vinculação.
  - Verificar: `tests/test_ingest_tcesp.py` (anulação maior que emissão, reforço em ano posterior); total empenhado de dois municípios conferido com o portal.
  - Arquivos: `src/redes/ingest/tcesp.py`, `tests/test_ingest_tcesp.py`, `docs/dicionario.md`

- [x] **T07: `elections`**
  - Aceite: aplica o protocolo do grupo incumbente nos três ramos; corrige por eleições suplementares; exclui segundo turno, rupturas e casos sem candidato, gravando o motivo em `exclusoes.csv`; calcula M_m e T_m.
  - Verificar: `tests/test_elections.py` cobre cada ramo e cada exclusão; tabela com número de municípios por faixa de margem.
  - Arquivos: `src/redes/elections.py`, `tests/test_elections.py`

- [x] **T08: `links`**
  - Aceite: cruza sócios pessoa física e doadores por nome normalizado e 6 dígitos centrais do CPF; mantém só receitas até 5/10/2024; grava conexões diretas por empresa, município e grupo; reporta taxa de cruzamento e número de chaves ambíguas.
  - Verificar: `tests/test_links.py` (homônimos com dígitos diferentes não se ligam; doação em 6/10 fica fora).
  - Arquivos: `src/redes/links.py`, `tests/test_links.py`

- [x] **PC1: Viabilidade** (decidido em 16/11/2026, ver `docs/decisoes.md`) — levar ao grupo: eleições apertadas disponíveis, taxa de cruzamento, situação do CPF do doador. Registrar a decisão em `docs/decisoes.md`.

## Fase 2 — Construção

- [x] **T09: `network`**
  - Aceite: grafo bipartido pessoa–empresa em igraph; componentes; δ_ik por município e grupo por busca em largura com várias origens, limitada a 3 passos; variantes sem sócios PJ e sem administradores não sócios construídas pelo mesmo código.
  - Verificar: `tests/test_network.py` reproduz as seis distâncias da Figura 1; uso de memória medido no grafo real.
  - Arquivos: `src/redes/network.py`, `tests/test_network.py`

- [ ] **T10: Descritivas de rede**
  - Aceite: distribuição do tamanho dos componentes, dos graus e das distâncias; pontos de articulação; erro de reconstrução comparando 2024-09 com a fotografia mais recente filtrada pela data de entrada.
  - Verificar: tabelas em `results/tables/rede_*.csv`; supressão de células pequenas testada.
  - Arquivos: `src/redes/network.py`, `src/redes/descritivas.py`, `tests/test_descritivas.py`

- [x] **PC2: Estrutura da rede** (decidido em 16/11/2026, ver `docs/decisoes.md`) — levar ao grupo a distribuição dos componentes e a decisão sobre componente gigante.

- [ ] **T11: `panel` empresa–município**
  - Aceite: fornecedores anteriores (jan/2021 a set/2024); participação no empenhado de 2025 dentro do elemento de despesa; categoria de conexão e faixa de δ; pesos que dão a cada município o mesmo total; marca de empenho novo com taxa de vinculação.
  - Verificar: `tests/test_panel.py` (participações somam 1 por município e elemento; pesos somam igual entre municípios).
  - Arquivos: `src/redes/panel.py`, `tests/test_panel.py`

- [ ] **T12: `panel` rede–município**
  - Aceite: conjuntos R1, R2 e R3 fixados antes da eleição; três termos da equação (4) e total, divididos pelo gasto anual médio pré-eleição; principais redes nos limiares de 25%, 50% e 75% com a regra de três em quatro anos.
  - Verificar: teste de que os três termos somam o total; teste da seleção das principais redes.
  - Arquivos: `src/redes/panel.py`, `tests/test_panel_rede.py`

## Fase 3 — Estimação

- [ ] **T13: Núcleo de RDD**
  - Aceite: função única que recebe painel, resultado e categoria e devolve estimativa, intervalo robusto, banda, contagens por lado, versões com b/2 e 2b, e efeito mínimo detectável; teste de densidade de M_m; agrupamento por município e por rede.
  - Verificar: `tests/test_rdd.py` recupera salto conhecido em dados simulados e não rejeita em dados sem salto.
  - Arquivos: `src/redes/estimate/rdd.py`, `tests/test_rdd.py`

- [ ] **T14: H1 e H2**
  - Aceite: H1 (conectadas ao incumbente contra sem conexão) e H2 (por faixa de δ até o vencedor), com placebo em empenhos de 2021 a 2024; tabelas em `results/tables/h1.csv` e `h2.csv`.
  - Verificar: `make sample` gera as tabelas; conferência manual de uma célula contra o painel.
  - Arquivos: `src/redes/estimate/h1_h2.py`, `tests/test_h1_h2.py`

- [ ] **T15: H3**
  - Aceite: os quatro resultados estimados com a mesma amostra, banda e pesos; incerteza das diferenças por reamostragem de municípios com semente fixa.
  - Verificar: teste de que as quatro estimativas usam a mesma amostra e de que os três termos somam o total estimado.
  - Arquivos: `src/redes/estimate/h3.py`, `tests/test_h3.py`

- [ ] **T16: H4 e múltiplas hipóteses**
  - Aceite: H4 nos três limiares; correção de Holm para H4 e comparações secundárias.
  - Verificar: teste da correção com p-valores conhecidos.
  - Arquivos: `src/redes/estimate/h4.py`, `tests/test_h4.py`

- [ ] **PC3: Resultados principais** — leitura conjunta de H1 a H3 antes da robustez.

## Fase 4 — Robustez e redação

- [ ] **T17: Robustez da rede**
  - Aceite: H1 a H3 reestimadas sem pontos de articulação, sem sócios PJ e sem administradores não sócios; tabela comparativa única.
  - Verificar: `results/tables/robustez.csv` com as quatro versões lado a lado.
  - Arquivos: `src/redes/estimate/robustness.py`, `tests/test_robustness.py`

- [ ] **T18: Figuras**
  - Aceite: gráficos de RDD para H1 a H3, gradiente por distância, decomposição de H3, distribuições da rede e desenho de uma rede real anonimizada (sem nomes, sem CNPJ, sem município).
  - Verificar: inspeção visual; nenhuma figura contém identificador.
  - Arquivos: `src/redes/figures.py`, `tests/test_figures.py`

- [ ] **T19: Relatório**
  - Aceite: `output/relatorio.pdf` com no máximo cinco páginas, quatro autores, estilo de escrita do projeto, citações ABNT; todos os números vêm de macros geradas a partir de `results/`.
  - Verificar: teste que conta páginas e que falha se houver número fora de macro nas seções de resultado.
  - Arquivos: `src/redes/report.py`, `report/relatorio.tex`, `report/referencias.bib`, `tests/test_report.py`

- [ ] **T20: Deck e guia de fala**
  - Aceite: `output/deck.pptx` com 10 a 12 slides; `output/deck.pdf` por conversão com LibreOffice; `output/guia_de_fala.md` com pontos por slide, tempo sugerido e divisão entre quatro pessoas.
  - Verificar: teste que compara o número de slides do `.pptx` com o de páginas do `.pdf`; revisão visual de cada slide.
  - Arquivos: `src/redes/deck.py`, `tests/test_deck.py`

- [ ] **T21: README e publicação**
  - Aceite: README com requisitos, comandos, tempo e espaço necessários, fontes com data de acesso e declaração de uso de IA; verificação final de que não há dado pessoal no histórico do git.
  - Verificar: `make all` em clone limpo; critérios de sucesso 1 a 8 da especificação conferidos um a um.
  - Arquivos: `README.md`, `docs/decisoes.md`

- [ ] **PC4: Revisão final** — o grupo revisa os artefatos e autoriza tornar o repositório público.
