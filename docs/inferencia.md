# Reestimação com correção de viés

O ponto de cada categoria é a estimativa Bias-Corrected do rdrobust, com sinal de perda do incumbente. Os intervalos e testes das categorias usam a variância robusta de Calonico, Cattaneo e Titiunik, com agrupamento municipal. Em cada lado do corte, o intercepto linear local em h é corrigido pela projeção de (M/h)² sobre a base linear em h, multiplicada pelo coeficiente quadrático estimado em b e convertido para a escala h. Ambos os ajustes usam núcleo triangular e peso total unitário por município na categoria.

Os contrastes usam as mesmas combinações lineares dos pontos corrigidos. Para o erro-padrão, sorteiam-se municípios com reposição, separadamente de cada lado do corte, em 999 réplicas com semente 20241006. A multiplicidade de cada município vale simultaneamente para todas as categorias no contraste. Mantêm-se h e b de cada categoria em todas as réplicas e reestimam-se os polinômios linear e quadrático com os pesos multiplicados pela frequência sorteada. Réplicas singulares em algum ajuste ficam fora do cálculo do erro-padrão. O IC de 95% usa a aproximação normal centrada no contraste corrigido, condicionada a h e b. O EMD usa o mesmo erro-padrão. A correção de viés também vale para os pontos reportados com h/2 e 2h (em cada refit, b é igual à banda alternativa h). H3 herda h e b do total em cada categoria e repete o mesmo sorteio para os termos, preservando as identidades da decomposição.

A sensibilidade H2 usa a diferença unitária entre a participação no elemento de despesa em 2025 e a participação no acumulado de jan/2021 a set/2024, com h e b do desfecho pós de cada coorte. Como a diferença é calculada antes do RD, o bootstrap incorpora a covariância entre os períodos e entre as coortes. É uma comparação descritiva de janelas diferentes. As médias e desvios-padrão descritivos de 2025 usam as observações dentro de h, sem peso de núcleo e com peso total igual por município. A família de Holm tem 20 testes estimáveis na aplicação real. O resumo registra esse tamanho em n_testes_holm.

Reprodução a partir dos painéis reais disponíveis:

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 POLARS_MAX_THREADS=2 \
  REDES_DATA_DIR=/home/rafael/.t3/projects/redes-economicas-e-sociais-2/data/verificacao-real \
  REDES_RESULTS_DIR="$PWD/results" uv run --frozen python -m redes estimate
```

verificacao-real reproduz os coeficientes, as bandas e os tamanhos de amostra dos resultados anteriores. As pastas revisao-entrega e revisao-cache contêm cópias dos CSVs da aplicação real e painéis da amostra sintética. O teste de regressão compara o contraste corrigido e seu desvio-padrão com reajustes explícitos do rdrobust em todas as réplicas de um caso com bandas h e b distintas, curvatura e pesos heterogêneos.

Auditoria das réplicas. H4-50 teve 998 de 999 réplicas válidas. Os quantis 2,5% e 97,5% das estimativas reamostradas foram −0,575 e 2,298. As duas maiores contribuições ao quadrado somaram 23,8% da variância amostral. A amplitude do IC normal reflete a instabilidade desses ajustes locais no suporte disponível. H2 na distância 1 teve 999 réplicas válidas e quantis −0,0721 e −0,0105.

