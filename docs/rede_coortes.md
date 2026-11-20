# Concentração no componente gigante nas coortes de H2

Identificamos o maior componente societário por número de empresas na rede principal. Para cada distância e coorte de H2, contamos os registros empresa–município–elemento e calculamos a parcela que pertence ao componente. Repetimos no recorte de estratos comparáveis, com a definição usada na estimação. A tabela traz a amostra antes da banda, a banda de estimação (h) e a banda de correção de viés (b), quando publicadas para o desfecho de 2025. Os recortes comparáveis nas faixas 0, 1 e 2 aparecem apenas antes das bandas porque o suporte municipal é insuficiente.

Os pesos dos registros somam um por município dentro de cada coorte. Em cada banda, multiplicamos esses pesos por (1-|M|/	ext{banda}), para (|M|<	ext{banda}), e calculamos a fração do peso total no gigante. Antes das bandas, usamos só o peso municipal. As contagens fora do gigante mantêm as coortes, os estratos e as bandas do desenho principal. Em particular, o suporte contado no recorte comparável é um limite superior para o de um recorte refeito após a retirada do componente.

Na faixa 1, o gigante reúne 60,46% do peso de A e 66,68% do de B em (h). Sem o gigante, B fica abaixo do piso de dez municípios por lado mesmo na amostra anterior às bandas. A tem suporte antes da banda e fica abaixo do piso no (h) publicado. Nas faixas 2 e 3+, nenhum dos grupos atinge o piso antes das bandas na amostra principal.

Na faixa 3+, o gigante reúne ao menos 99% dos registros nas quatro coortes dentro de (h). A parcela do peso é de 99,99% em A e 94,82% em B na amostra principal. No recorte comparável, os limites publicados são de ao menos 99% em A e 93% em B. Esses diagnósticos descrevem o suporte da comparação de 2025. [Resultados completos](../results/tables/concentracao_gigante_h2.csv).

## Divulgação

Suprimimos contagens positivas inferiores a cinco. Quando um lado do corte tem de uma a quatro observações no gigante ou fora dele, as frações exatas ficam vazias. Os campos `piso_fracao_observacoes` e `piso_fracao_peso` contêm limites inferiores conservadores. O limite para observações usa faixas de cinco pontos percentuais ou o piso de 99% quando o total é grande o suficiente. O limite de peso usa pontos percentuais inteiros. Os pisos associados à supressão deixam margem para um complemento de pelo menos cinco registros, mesmo com o total conhecido. A coluna booleana de suporte informa se restam pelo menos dez municípios em cada lado após a retirada do gigante. Há também uma indicação separada por lado.

## Reprodução

Com os Parquets reais e as tabelas `h2.csv` e `h2_comparaveis.csv` já disponíveis, execute na raiz do repositório.

```bash
REDES_DATA_DIR=/caminho/para/dados-reais \
  REDES_RESULTS_DIR="$PWD/results" \
  OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 POLARS_MAX_THREADS=2 \
  uv run --frozen python -m redes.rede_coortes
```

O script confere as contagens da amostra em (h) com a tabela publicada antes de gravar o diagnóstico. [Auditoria do recorte comparável](auditoria_h2.md).
