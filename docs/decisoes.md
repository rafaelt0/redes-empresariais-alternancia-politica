# Registro de decisões

Decisões de desenho e de implementação tomadas depois da especificação, com data e motivo. Toda mudança de especificação, banda ou amostra feita depois de ver um resultado entra aqui (SPEC, "Limites").

## PC1: viabilidade (16/11/2026)

- **Segue o desenho do projeto.** São 506 municípios analisáveis, 78 disputas com margem de até 5 p.p. (42 com derrota do incumbente, 36 com vitória) e 135 até 10 p.p. O poder é limitado. Por isso o efeito mínimo detectável é reportado ao lado de cada estimativa, como prevê a seção 7 do projeto. O desenho não muda.
- **CPF do doador.** Vem completo no TSE. O cruzamento usa nome normalizado e os seis dígitos centrais, como no projeto. Taxa de cruzamento: 36% dos doadores pessoa física do grupo A e 37% dos do grupo B são sócios de alguma empresa (`results/tables/links_pc1.csv`).
- **Autofinanciamento.** O candidato que doa à própria campanha conta como doador. Suas empresas ficam diretamente conectadas ao grupo, pela definição da seção 4 do projeto ("algum de seus sócios doou ao candidato de k").
- **Regras técnicas do protocolo do grupo incumbente.** Empate (M = 0) conta como vitória do incumbente, porque T = 1 só quando M < 0. Candidaturas indeferidas ficam fora do protocolo. Mais de um candidato no mesmo ramo é tratado como ruptura e excluído. A lista está em `data/exclusoes.csv`.

## Lacuna no quadro de sócios de 2024-09 (16/11/2026)

- **Fato.** O `Socios0.zip` da pasta 2024-09 é o mesmo arquivo da pasta 2024-08 (CRC32 b1cf09ca, extração de 10/08/2024). Como a Receita reordena as linhas a cada mês, cerca de 2,76 milhões de empresas ficam sem sócios na mistura de setembro. Entre elas estão 30 mil sociedades limitadas fornecedoras, com R$ 37 bi empenhados de 2021 a set/2024.
- **Decisão.** As empresas sem nenhum sócio em 2024-09 recebem os sócios da fotografia de 2024-10 (extração de 12/10/2024, os dez arquivos) cuja data de entrada é até 13/09/2024. Cada vínculo guarda a origem (`2024-09` ou `2024-10`).
- **Por que não viola "nunca reconstruir pela fotografia atual".** O preenchimento usa a fotografia seguinte, não a atual. Vale só para empresas ausentes de 2024-09 e só para sócios que entraram antes da extração de setembro. Testado nas 10,3 milhões de empresas em que a resposta de setembro é conhecida, reproduz 99,72% dos sócios. O erro se concentra em saídas entre 14/09 e 12/10/2024, que a regra não vê.
- **Alternativas descartadas.** Ficar só com 2024-09 tira da rede 24% das empresas sem relação com o problema estudado. Usar 2024-08 inteira perde as entradas entre 10/08 e 13/09.
- **Transparência.** O número de empresas e de vínculos preenchidos sai em `results/tables/validacao_rfb.csv`.

## PC2: estrutura da rede (16/11/2026)

- **Componente gigante.** Reúne 11,6% das empresas e 13% dos fornecedores municipais anteriores que estão na rede. Sem os pontos de articulação, cai para 1,8% e 2,8%. Isso não esvazia H3 nem H4. Segue o projeto: a distribuição é reportada e a variante sem pontos de articulação entra como robustez.
- **Poder de H2.** Há poucos pares empresa–município com δ de 1 ou 2. H2 é estimada e reportada como sair, com o efeito mínimo detectável.

## Erro de reconstrução (16/11/2026)

- A seção 5 do projeto compara a fotografia pré-eleitoral com "a atual, filtrada pela data de entrada". Usa-se a pasta mais recente do compartilhamento da Receita, com o mesmo filtro de entrada até 13/09/2024. O erro sai como fração de vínculos e de empresas de 2024-09 ausentes da reconstrução e como fração de vínculos reconstruídos ausentes de 2024-09.

## Autoria

- O grupo confirmou o NUSP de João Pedro Ferreira para a capa do relatório e do deck em 18/11/2026.

## Apresentação das estimativas (18/11/2026)

- Os contrastes de H2 comparam efeitos eleitorais em coortes definidas pela distância a A e a B na rede descrita acima. A metade da diferença resume a heterogeneidade. O diagnóstico usa o elemento de despesa em cada município e quintis do empenho prévio da empresa como medida de porte.
- O grupo aprovou uma análise de sensibilidade de H2. Para cada distância, usa-se apenas o suporte comum das duas coortes no mesmo município, elemento de despesa e quintil de porte prévio. A análise usa as mesmas regras de estimação das coortes principais e sai em `h2_comparaveis.csv`.
- Em H1 e H2, o grupo aprovou registrar participação zero para fornecedores anteriores quando o elemento de despesa no município não teve empenho líquido positivo em 2025. Assim a amostra não depende da atividade do mercado após a eleição. `mercados_sem_empenho.csv` registra a frequência por coorte e lado do corte.
- O teste de H3 mostra R1 e a soma R2+R3 dentro das redes ligadas a ambos os grupos. Os dois resultados usam a banda do total e a mesma amostra. O sinal do contraste entre tipos de rede não estabelece compensação dentro de uma rede.
- H4 inclui estimativas de descontinuidade nas quatro categorias de ligação pré-eleitoral. O contraste usa as redes de ligação exclusiva, cuja ligação ao vencedor muda com a eleição. A comparação descritiva com e sem ligação ao vencedor inclui as quatro categorias e usa a janela de cinco pontos percentuais documentada no PC1.
- Para manter posição em H4, a rede principal no período pré-eleitoral precisa permanecer entre as principais no mesmo limiar em 2025. A classificação de 2025 inclui as redes que começaram a fornecer naquele ano.
- A família de Holm inclui os contrastes de H4 e os efeitos isolados por categoria de H1, H2 e H4. Os contrastes principais de H1 a H3 e os componentes da decomposição de H3 preservam a inferência principal.
- O quadro de categorias mostra intervalos corrigidos por viés. O quadro de contrastes usa reamostragem de municípios. Resultados sem suporte suficiente ficam em branco nos CSVs e aparecem como n.d. nos artefatos.
- A comparação com agrupamento por rede usa a banda da estimativa municipal. O valor-p por rede só é calculado com pelo menos dez redes distintas de cada lado. As contagens por lado acompanham as estimativas e seguem a supressão das demais tabelas.
- A distribuição publicada usa três faixas de tamanho: uma empresa, duas empresas e três ou mais. A faixa agregada também pode ser obtida pelos totais da versão pública anterior. Se uma faixa tiver de um a quatro componentes, ficam em branco todos os valores das quatro tabelas descritivas da variante, inclusive os zeros.
- A distribuição de grau agrega vértices com onze ou mais vínculos. Quando a contagem acima de um corte, publicada ou recuperável pelo total, difere por uma a quatro unidades entre variantes, a distribuição daquele tipo de vértice fica em branco em todas elas. A validação estadual do TCESP e a do painel ocultam taxas com poucos empenhos no numerador ou em um complemento recuperável.
