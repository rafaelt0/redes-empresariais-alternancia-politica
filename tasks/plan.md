# Plano de implementação

Deriva de `SPEC.md`. A lista de tarefas está em `tasks/todo.md`.

## Abordagem

O pipeline é construído em fatias verticais: primeiro ele roda de ponta a ponta sobre a amostra sintética da Figura 1 do projeto, depois cada etapa recebe os dados reais. Assim `make sample` passa a existir cedo e continua servindo de teste de integração.

## Fases e pontos de controle

| Fase | Conteúdo | Ponto de controle (decisão do grupo) |
|---|---|---|
| 0. Esqueleto | Ambiente, Makefile, fixtures, CLI | `make sample` roda etapas vazias |
| 1. Viabilidade | `fetch`, esquemas reais, `elections`, `links` | **PC1:** número de eleições apertadas, taxa de cruzamento sócio–doador, CPF do doador disponível. Decide viabilidade e ajustes de escopo (meses 1 a 3 do projeto). |
| 2. Construção | `ingest-*` completos, `network`, `panel` | **PC2:** distribuição dos componentes e das distâncias; decisão sobre componente gigante. |
| 3. Estimação | H1, H2, H3, diagnósticos, placebos; H4 | **PC3:** leitura dos resultados principais antes da robustez. |
| 4. Robustez e redação | Robustez de rede, relatório, deck, guia, README | **PC4:** revisão dos artefatos; publicação do repositório. |

## Dependências

```
T01 → T02 → T03
T03 → T04 (rfb) ─┐
T03 → T05 (tse) ─┼→ T07 (elections) → T08 (links) → PC1
T03 → T06 (tcesp)┘
T04, T08 → T09 (network) → T10 (descritivas) → PC2
T06, T07, T09 → T11 (panel firma) → T12 (panel rede)
T11 → T13 (RDD núcleo) → T14 (H1, H2) ─┐
T12, T13 → T15 (H3) ───────────────────┼→ PC3 → T17 (robustez)
T12, T13 → T16 (H4) ───────────────────┘
T14–T17 → T18 (figuras) → T19 (relatório), T20 (deck e guia) → T21 (README, publicação) → PC4
```

Paralelizáveis: T04, T05 e T06; T14, T15 e T16; T19 e T20.

## Riscos

| Risco | Efeito | Mitigação |
|---|---|---|
| Disco (7,4 GB livres, ~12 GB de brutos) | `fetch` falha | Ingestão em fluxo, um arquivo por vez, bruto apagado após Parquet; `REDES_DATA_DIR` |
| Memória (7 GB) | Grafo nacional não cabe | Grafo em inteiros compactos no igraph; DuckDB fora da memória; busca limitada a 3 passos |
| Componente gigante | H3 e H4 sem variação | Descritivas antes da estimação (PC2); robustez sem pontos de articulação |
| Poucas eleições apertadas | Intervalos largos | Efeito mínimo detectável reportado; sem troca de desenho |
| CPF do doador mascarado no TSE | Cruzamento mais fraco | Verificado em T05; decisão no PC1 |
| Prefeito em exercício diferente do eleito | Grupo incumbente errado | Eleições suplementares do TSE; demais casos em `exclusoes.csv` |
| Esquema do TCESP diferente do esperado | Ingestão quebra | T06 começa por inspecionar cabeçalhos e layout oficial |
| Baixa vinculação empenho–licitação | Classificação novo/herdado fraca | Taxa reportada; resultado principal não depende dela |
