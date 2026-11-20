SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c

DADOS ?= $(or $(REDES_DATA_DIR),data)
SAIDA := $(or $(REDES_OUTPUT_DIR),output)
RESULTADOS := $(or $(REDES_RESULTS_DIR),results)
export REDES_DATA_DIR := $(abspath $(DADOS))
FEITO := $(DADOS)/.feito
REDES := uv run --frozen python -m redes

ETAPAS := fetch ingest-rfb ingest-tse ingest-tcesp elections links network panel estimate report deck
AMOSTRA := data/amostra
MODO_FONTES := $(FEITO)/fontes.$(if $(filter 1,$(REDES_ESTRITO)),1,0)
AMOSTRA_PRESENTE := $(wildcard $(DADOS)/.amostra-sintetica)
TABELAS := $(RESULTADOS)/tables
FIGURAS := $(RESULTADOS)/figures
SAIDAS_ingest-rfb := $(addprefix $(DADOS)/,socios.parquet empresas.parquet)
SAIDAS_ingest-tse := $(addprefix $(DADOS)/,candidatos.parquet votos.parquet doacoes.parquet pseudonimos_ambiguos.parquet)
SAIDAS_ingest-tcesp := $(addprefix $(DADOS)/,empenhos.parquet licitacoes.parquet municipios.parquet)
ifeq ($(AMOSTRA_PRESENTE),)
SAIDAS_ingest-rfb += $(addprefix $(TABELAS)/,validacao_rfb.csv reconstrucao.csv qualificacoes_rfb.csv ambiguidade_rfb.csv)
SAIDAS_ingest-tse += $(TABELAS)/validacao_tse.csv
SAIDAS_ingest-tcesp += $(TABELAS)/validacao_tcesp.csv
endif
SAIDAS_elections := $(addprefix $(DADOS)/,eleicoes.parquet exclusoes.csv)
SAIDAS_links := $(DADOS)/conexoes_diretas.parquet $(TABELAS)/links_pc1.csv
SAIDAS_network := $(addprefix $(DADOS)/,rede.parquet distancias.parquet) $(addprefix $(TABELAS)/,rede_resumo.csv rede_componentes.csv rede_distancias.csv rede_graus.csv)
SAIDAS_panel := $(addprefix $(DADOS)/,painel_firma.parquet painel_rede.parquet) $(addprefix $(TABELAS)/,validacao_panel.csv mercados_sem_empenho.csv)
SAIDAS_estimate := $(addprefix $(TABELAS)/,h1.csv h2.csv h2_comparaveis.csv h3.csv h4.csv densidade.csv resumo_estimacao.csv robustez.csv validacao.csv comparabilidade_h2.csv sensibilidade_placebo.csv descritivas_estimacao.csv permanencia_h4.csv)
SAIDAS_estimate += $(foreach nome,rdd_h1 rdd_h2 rdd_h3 figura1_exemplo rede_componentes rede_distancias rede_graus rede_exemplo_observado gradiente_h2 decomposicao_h3,$(FIGURAS)/$(nome).pdf $(FIGURAS)/$(nome).png)
SAIDAS_report := $(SAIDA)/relatorio.pdf
SAIDAS_deck := $(addprefix $(SAIDA)/,deck.pptx deck.pdf guia_de_fala.md)
ENTRADAS_PUBLICACAO := $(wildcard $(TABELAS)/*.csv)
faltando = $(shell for arquivo in $(SAIDAS_$(1)); do if ! test -s "$$arquivo"; then echo refazer; break; fi; done)

.PHONY: setup all test lint sample clean-raw dicionario refazer sensibilidades entrega-revisada $(ETAPAS)

all: report deck

# As verificações adicionais recompõem redes e painéis; o alvo explícito evita reutilizar
# diagnósticos antigos ao regenerar uma entrega após mudanças nos dados ou na estimação.
sensibilidades: estimate
	uv run --frozen python -m redes.sensibilidades --dados "$(abspath $(DADOS))" \
		--cache "$(abspath $(DADOS))/sensibilidades" --tabelas "$(abspath $(TABELAS))" \
		--parciais-tcesp "$(or $(PARCIAIS_TCESP),$(abspath $(DADOS))/tcesp)"
	uv run --frozen python -m redes.pre_periodos
	uv run --frozen python -m redes.auditoria_h2
	uv run --frozen python -m redes.rede_coortes

entrega-revisada: sensibilidades
	$(REDES) report
	$(REDES) deck

setup:
	uv sync --frozen

test:
	uv run --frozen pytest

lint:
	uv run --frozen ruff check . && uv run --frozen ruff format --check .

# Cada etapa deixa um marcador em $(FEITO); a etapa refaz quando um pré-requisito ou o próprio
# módulo é mais novo. As dependências espelham `ETAPA.depende` (conferido em tests/test_etapas.py).
# As ingest-* não dependem de fetch: cada uma baixa só o que lê (`fetch.garantir`), porque os
# brutos não cabem todos no disco.
$(ETAPAS): %: $(FEITO)/%

ifneq ($(filter fetch $(FEITO)/fetch,$(MAKECMDGOALS)),)
ifeq ($(AMOSTRA_PRESENTE),)
BRUTOS_FETCH := $(shell REDES_ESTRITO="$(REDES_ESTRITO)" uv run --frozen python -m redes.fetch listar)
SAIDAS_fetch := $(DADOS)/manifest.json $(addprefix $(DADOS)/raw/,$(BRUTOS_FETCH))
$(FEITO)/fetch: $(if $(BRUTOS_FETCH),,refazer)
endif
endif
FONTES_INGESTAO := $(MODO_FONTES) fontes.lock.json $(addprefix src/redes/,fetch.py fontes.py config.py etapas.py schemas.py)
PSEUDONIMO := src/redes/pseudonimo.py
$(FEITO)/fetch: $(FONTES_INGESTAO) $(call faltando,fetch)
$(FEITO)/ingest-rfb: $(FONTES_INGESTAO) $(PSEUDONIMO) src/redes/ingest/rfb.py src/redes/descritivas.py $(call faltando,ingest-rfb)
$(FEITO)/ingest-tse: $(FONTES_INGESTAO) $(PSEUDONIMO) src/redes/ingest/tse.py $(call faltando,ingest-tse)
$(FEITO)/ingest-tcesp: $(FONTES_INGESTAO) $(PSEUDONIMO) src/redes/ingest/tcesp.py src/redes/descritivas.py $(call faltando,ingest-tcesp)
$(FEITO)/elections: $(FEITO)/ingest-tse src/redes/elections.py $(call faltando,elections)
$(FEITO)/links: $(FEITO)/ingest-rfb $(FEITO)/ingest-tse $(FEITO)/elections src/redes/links.py $(call faltando,links)
$(FEITO)/network: $(FEITO)/ingest-rfb $(FEITO)/ingest-tcesp $(FEITO)/links src/redes/network.py src/redes/descritivas.py $(call faltando,network)
$(FEITO)/panel: $(FEITO)/ingest-tcesp $(FEITO)/elections $(FEITO)/network src/redes/panel.py $(call faltando,panel)
$(FEITO)/estimate: $(FEITO)/panel $(wildcard src/redes/estimate/*.py) src/redes/figures.py $(call faltando,estimate)
$(FEITO)/report: $(FEITO)/estimate $(ENTRADAS_PUBLICACAO) $(wildcard $(FIGURAS)/*.pdf) src/redes/report.py src/redes/numeros.py src/redes/leitura_sensibilidades.py report/relatorio.tex report/referencias.bib $(call faltando,report)
$(FEITO)/deck: $(FEITO)/estimate $(ENTRADAS_PUBLICACAO) $(wildcard $(FIGURAS)/*.png) src/redes/deck.py src/redes/numeros.py src/redes/leitura_sensibilidades.py $(call faltando,deck)

$(MODO_FONTES):
	@mkdir -p $(FEITO)
	@rm -f $(FEITO)/fontes.0 $(FEITO)/fontes.1
	@touch $@

$(FEITO)/%:
	$(REDES) $*
	@for arquivo in $(SAIDAS_$*); do test -s "$$arquivo" || { echo "$*: saída ausente ou vazia: $$arquivo" >&2; exit 1; }; done
	@mkdir -p $(FEITO) && touch $@

# A amostra substitui as saídas de fetch e ingest-*; as demais etapas rodam sobre ela, com
# resultados e saída dentro de $(AMOSTRA) para não tocar os versionados.
sample:
	rm -rf $(AMOSTRA)
	REDES_DATA_DIR=$(AMOSTRA) $(REDES) amostra
	mkdir -p $(AMOSTRA)/.feito
	touch $(AMOSTRA)/.feito/fontes.$(if $(filter 1,$(REDES_ESTRITO)),1,0)
	touch $(addprefix $(AMOSTRA)/.feito/,fetch ingest-rfb ingest-tse ingest-tcesp)
	REDES_DATA_DIR=$(abspath $(AMOSTRA)) \
	REDES_RESULTS_DIR=$(abspath $(AMOSTRA))/results \
	REDES_OUTPUT_DIR=$(abspath $(AMOSTRA))/output \
	$(MAKE) --no-print-directory DADOS=$(AMOSTRA) report deck

clean-raw:
	rm -rf $(DADOS)/raw

dicionario:
	uv run --frozen python -m redes.dicionario > docs/dicionario.md
