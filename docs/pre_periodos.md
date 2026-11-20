# Placebo de mudança de participação antes da eleição

Comparamos a participação de cada empresa no empenho de seu município e elemento de despesa em janeiro de 2021 a dezembro de 2022 com a participação em janeiro de 2023 a setembro de 2024. O desfecho é a segunda participação menos a primeira. Agregamos emissões e reforços e deduzimos anulações pela data do evento. Em cada janela, dividimos o saldo líquido positivo da empresa pela soma dos saldos positivos de todos os credores pessoa jurídica no mercado. A participação é zero quando a empresa está ausente, seu saldo é não positivo ou o mercado inteiro tem denominador zero. As duas janelas têm durações distintas. Cada participação usa o total da própria janela.

Fixamos as linhas, os pesos municipais, a margem, o corte e as coortes do painel principal. A elegibilidade continua definida pelo empenho líquido positivo de janeiro de 2021 a setembro de 2024. Em cada categoria, usamos as bandas de estimação e de viés escolhidas para o desfecho de 2025. O intervalo de 95% de cada contraste usa o desvio-padrão de 999 réplicas com reamostragem conjunta de municípios nas coortes, estratificada por lado do corte. O ponto de cada réplica recebe correção de viés. [Método de inferência](inferencia.md).

O placebo examina se a alocação já evoluía de forma descontínua no corte da eleição de 2024. A leitura vale para as coortes e para os fornecedores selecionados com informação até 2024.

## Resultados

Todos os intervalos incluem zero. Na faixa de distância 1 de H2, o ponto do placebo indica uma queda de 2,75 p.p., na mesma direção do contraste de 2025. O intervalo também admite quedas da ordem do contraste de 2025 e aumentos. A precisão do placebo limita o que podemos concluir sobre diferenças anteriores ao pleito.

| Contraste | Estimativa (p.p.) | IC de 95% (p.p.) | Valor-p |
|---|---:|---:|---:|
| H1, conexão direta com A menos sem conexão | −2,85 | −12,40 a 6,71 | 0,559 |
| H2, distância 0 | 0,66 | −4,91 a 6,23 | 0,816 |
| H2, distância 1 | −2,75 | −7,38 a 1,87 | 0,243 |
| H2, distância 2 | −1,95 | −7,49 a 3,59 | 0,491 |
| H2, distância 3+ | −1,06 | −2,68 a 0,56 | 0,200 |

[Resultados por categoria e contraste](../results/tables/sensibilidade_pre_periodos.csv).

## Reprodução

Com os Parquets da aplicação real e as tabelas principais `h1.csv` e `h2.csv` em `$REDES_RESULTS_DIR/tables`, execute na raiz do repositório.

```bash
REDES_DATA_DIR=/caminho/para/dados-reais \
  REDES_RESULTS_DIR="$PWD/results" \
  OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 POLARS_MAX_THREADS=2 \
  uv run --frozen python -m redes.pre_periodos
```

A saída contém apenas estatísticas agregadas das categorias e dos contrastes, com a supressão de contagens aplicada às demais tabelas de RDD. [Resultados](../results/tables/sensibilidade_pre_periodos.csv).
