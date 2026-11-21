# Redes empresariais e persistência econômica sob alternância política

Projeto de EAE1429 (FEA-USP) sobre como a derrota do grupo incumbente em eleições
municipais apertadas se relaciona com a distribuição das compras públicas entre
empresas e redes societárias paulistas. O [relatório](report/relatorio.tex) define
H1 a H4 e o desenho; o [dicionário de dados](docs/dicionario.md) descreve as tabelas
que o pipeline grava.

Felipe Ferreira Alexandre, Andrei Schoschlakow Bonifácio, Rafael Eiki Teruya e
João Pedro Ferreira.

## Reprodução

Em Linux, use Python 3.12 com `uv`, GNU Make, LibreOffice (`soffice`), Poppler
(`pdfinfo`) e uma distribuição TeX com `latexmk`, pdfLaTeX, BibTeX e
`abntex2cite`. Reserve cerca de 25 GB de disco livre para os ZIPs, Parquet e
temporários e 8 GB de RAM. O tempo com dados reais depende da conexão e da máquina.
A amostra sintética normalmente termina em menos de dois minutos.

```sh
make setup
make sample
make test
make lint
make all
```

`make sample` gera os artefatos em `data/amostra/output/`. `make all` baixa as
fontes necessárias, constrói os painéis e gera em `output/` o relatório PDF, o
deck em PowerPoint e PDF e o guia de fala. As tabelas e figuras agregadas ficam
em `results/`. A lista de municípios excluídos e seus motivos fica em
`data/exclusoes.csv`. `make panel` e os outros alvos por etapa executam os
pré-requisitos necessários.

`DADOS=/caminho/absoluto` ou `REDES_DATA_DIR` apontam para outro disco.
`REDES_RESULTS_DIR` e `REDES_OUTPUT_DIR` separam resultados e artefatos entre
execuções. Ao trocar esses diretórios, use também um diretório de dados separado
para que os marcadores de etapa correspondam à execução. Os ZIPs ficam no disco
por padrão. O manifesto local em `data/manifest.json` registra URL, data de
download e SHA-256 de cada ZIP. A chave HMAC local é compartilhada entre as
ingestões da Receita e do TSE.

Em máquinas com memória disponível, `REDES_PROCESSOS_ESTIMACAO=2` ou `3`
processa variantes da rede em paralelo. Para limitar a concorrência dentro de
cada processo, use também `OPENBLAS_NUM_THREADS=1` e `POLARS_MAX_THREADS=2`.

## Fontes

- [Receita Federal, dados abertos do CNPJ](https://www.gov.br/receitafederal/pt-br/acesso-a-informacao/dados-abertos/cadastros/cnpj).
  Fotografias de setembro e outubro de 2024 para a rede, com a de outubro de 2026 para o diagnóstico de reconstrução. Acesso em novembro de 2026.
- [Portal de Dados Abertos do TSE](https://dadosabertos.tse.jus.br/).
  Candidaturas, votação e prestações de contas de eleições municipais. Acesso em novembro de 2026.
- [TCESP, Portal da Transparência Municipal](https://transparencia.tce.sp.gov.br/conjunto-de-dados).
  Despesas de 2021 a 2025, licitações e ajustes. Acesso em novembro de 2026.

As fontes do TSE e do TCESP podem ser republicadas. A trava de fontes documenta
os hashes da versão usada para a entrega. A execução aceita atualizações de
fontes mutáveis por padrão. Use `REDES_ESTRITO=1 make all` para exigir os hashes da
ingestão e reconstruir os intermediários do TCESP sempre que a etapa de ingestão
for executada. O alvo opcional `fetch` cobre também arquivos auxiliares que não entram
na análise. Em modo estrito, `fetch` baixa somente os arquivos registrados na trava.

## Verificações da revisão

`make entrega-revisada` recompõe as sensibilidades de origem dos vínculos,
componente gigante, sementes diretas após remoção de articulações, autofinanciamento
e escopo da despesa e então regenera os artefatos. Esse alvo exige os intermediários
reais da ingestão, inclusive a pasta `tcesp/`; `PARCIAIS_TCESP=/caminho` permite
localizá-la separadamente. As redes são processadas em sequência. Para limitar
recursos, use `POLARS_MAX_THREADS=2 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1`.
As sensibilidades têm universo e hipóteses próprios, documentados em
[sensibilidades](docs/sensibilidades.md) e na [nota de inferência](docs/inferencia.md).
O alvo inclui o [placebo de variação pré-eleitoral](docs/pre_periodos.md), entre
2021–2022 e 2023–setembro de 2024, que preserva as coortes e bandas do pós.
A [auditoria do recorte comparável](docs/auditoria_h2.md) quantifica a sobreposição
das coortes e sua covariância na reamostragem conjunta.
O [diagnóstico de concentração de H2](docs/rede_coortes.md) verifica quanto essas
coortes dependem do componente gigante e o suporte que resta fora dele.
`make all` pode ler sensibilidades já presentes em `results/tables/`; após mudar
dados ou estimação, use `make entrega-revisada` para evitar diagnósticos antigos.

## Uso de IA

Assistentes de IA foram usados para implementar o pipeline e elaborar testes.
Os resultados são calculados pelo pipeline a partir das bases registradas.
