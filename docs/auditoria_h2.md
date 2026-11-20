# Sobreposição das coortes comparáveis na faixa 3+ de H2

O recorte de H2 retém em cada faixa os estratos de município, elemento de despesa e quintil de empenho anterior com pelo menos uma empresa de cada coorte. Contamos observações empresa–município–elemento. Uma observação comum pertence à faixa 3+ de A e de B. O índice de Jaccard divide a interseção pela união das coortes.

| Amostra da faixa 3+ | Estratos | Coorte A | Coorte B | Observações comuns | Jaccard |
|---|---:|---:|---:|---:|---:|
| Recorte comparável inteiro | 2.674 | 29.354 | 29.464 | 29.028 | 97,44% |
| Dentro da banda de estimação de cada coorte | 1.638 | 14.810 | 16.898 | 14.566 | 84,97% |

A segunda linha aplica a cada coorte sua banda de estimação publicada. Uma observação comum nessa linha pertence às duas bandas. As contagens são agregadas. Se uma célula de interseção ou diferença contém de uma a quatro unidades, também são suprimidos os totais e o Jaccard que permitiriam recuperá-la.

As duas estimativas usam o mesmo sorteio de municípios em cada réplica, com as bandas de estimação e de viés fixas nas escolhas publicadas. Nas 999 réplicas válidas, a correlação dos saltos de A e B é 0,971. A variância de `(B − A)/2` é a soma das variâncias de A e B menos duas vezes a covariância, dividida por quatro. O erro-padrão obtido, de 0,0276 p.p., coincide com o publicado. Com a covariância posta em zero e as mesmas variâncias marginais das réplicas, ele seria de 0,1589 p.p. A coocorrência da mesma observação e o sorteio conjunto de municípios ajudam a explicar a correlação. O contraste de 0,055 p.p. é uma comparação exploratória entre coortes com grande sobreposição. [Dados da auditoria](../results/tables/auditoria_h2_comparaveis.csv).

## Reprodução

Com o painel real e a tabela `h2_comparaveis.csv` nos caminhos abaixo, execute na raiz do repositório.

```bash
REDES_DATA_DIR=/caminho/para/dados-reais \
  REDES_RESULTS_DIR="$PWD/results" \
  OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 POLARS_MAX_THREADS=2 \
  uv run --frozen python -m redes.auditoria_h2
```

O programa verifica as contagens locais de cada categoria e o erro-padrão do contraste contra `h2_comparaveis.csv` antes de escrever o CSV da auditoria. [Método de inferência](inferencia.md).
