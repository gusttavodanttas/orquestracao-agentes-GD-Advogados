#!/usr/bin/env python3
"""
capturar.py — Captura publicações do DJEN via API oficial do PJe.

Uso:
    python capturar.py
    python capturar.py --dias 30
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Configurações — ajuste aqui se necessário
# ---------------------------------------------------------------------------
API_URL = "https://comunicaapi.pje.jus.br/api/v1/comunicacao"
ITENS_POR_PAGINA = 100
INTERVALO_REQ_SEG = 0.5   # 0,5 s entre requisições = ~2 req/s
MAX_TENTATIVAS = 5

ARQUIVO_OABS = Path("oabs.json")
ARQUIVO_VISTOS = Path("vistos.json")
ARQUIVO_SAIDA = Path("publicacoes.json")

# ---------------------------------------------------------------------------
# Logging — sem dados de partes (LGPD: não logar nomes, CPF ou conteúdo)
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Funções puras (testáveis de forma isolada)
# ---------------------------------------------------------------------------

def limpar_html(texto: str | None) -> str:
    """Remove marcações HTML e devolve texto simples."""
    if not texto:
        return ""
    return BeautifulSoup(texto, "html.parser").get_text(separator=" ", strip=True)


def calcular_periodo(dias: int) -> tuple[str, str]:
    """Devolve (data_inicio, data_fim) no formato YYYY-MM-DD para os últimos N dias."""
    hoje = datetime.today()
    inicio = hoje - timedelta(days=dias)
    return inicio.strftime("%Y-%m-%d"), hoje.strftime("%Y-%m-%d")


def carregar_json(caminho: Path, padrao):
    """Lê arquivo JSON; se não existir, devolve `padrao`."""
    if caminho.exists():
        with caminho.open(encoding="utf-8") as arq:
            return json.load(arq)
    return padrao


def salvar_json(caminho: Path, dados) -> None:
    """Grava `dados` em JSON com indentação legível."""
    with caminho.open("w", encoding="utf-8") as arq:
        json.dump(dados, arq, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Requisição HTTP com controle de taxa e retry
# ---------------------------------------------------------------------------

def requisitar(sessao: requests.Session, params: dict, tentativa: int = 1) -> dict:
    """
    GET na API com:
    - Retry automático em erro 429 (muitas requisições), respeitando Retry-After.
    - Saída imediata com mensagem clara em erro 403 (bloqueio geográfico).
    """
    if tentativa > MAX_TENTATIVAS:
        raise RuntimeError(
            f"A API respondeu com erro 429 por {MAX_TENTATIVAS} vezes seguidas. "
            "Aguarde alguns minutos e tente novamente."
        )

    try:
        resposta = sessao.get(API_URL, params=params, timeout=30)
    except requests.RequestException as exc:
        raise RuntimeError(f"Falha de conexão com a API: {exc}") from exc

    if resposta.status_code == 429:
        espera = int(resposta.headers.get("Retry-After", 30))
        log.warning(
            "API sinalizou excesso de requisições (429). "
            "Aguardando %ds antes de tentar novamente (tentativa %d/%d).",
            espera, tentativa, MAX_TENTATIVAS,
        )
        time.sleep(espera)
        return requisitar(sessao, params, tentativa + 1)

    if resposta.status_code == 403:
        log.error(
            "Acesso bloqueado pela API (403). Isso normalmente indica bloqueio "
            "geográfico — o servidor recusa conexões de fora do Brasil. "
            "SOLUÇÃO: execute este script de um computador ou servidor com IP brasileiro."
        )
        sys.exit(1)

    resposta.raise_for_status()
    return resposta.json()


# ---------------------------------------------------------------------------
# Busca paginada para uma única OAB
# ---------------------------------------------------------------------------

def buscar_publicacoes_oab(
    sessao: requests.Session,
    numero_oab: str,
    uf_oab: str,
    data_inicio: str,
    data_fim: str,
) -> list[dict]:
    """
    Percorre todas as páginas da API para a OAB informada.
    Devolve lista com todos os itens brutos encontrados.
    """
    todos: list[dict] = []
    pagina = 0

    while True:
        params = {
            "numeroOab": numero_oab,
            "ufOab": uf_oab,
            "dataDisponibilizacaoInicio": data_inicio,
            "dataDisponibilizacaoFim": data_fim,
            "itensPorPagina": ITENS_POR_PAGINA,
            "pagina": pagina,
        }

        log.info("OAB %s/%s — consultando página %d …", numero_oab, uf_oab, pagina)
        dados = requisitar(sessao, params)

        # A API pode usar "items" ou "content" dependendo da versão
        itens: list[dict] = dados.get("items") or dados.get("content") or []
        todos.extend(itens)

        # --- Detectar última página (suporta diferentes formatos de resposta) ---
        ultima_pagina = (
            dados.get("last") is True                           # formato Spring Page
            or not itens                                         # lista vazia = fim
            or len(itens) < ITENS_POR_PAGINA                    # menos que o pedido = fim
        )
        total_paginas = dados.get("totalPages") or dados.get("total_pages")
        if total_paginas is not None and pagina + 1 >= int(total_paginas):
            ultima_pagina = True

        if ultima_pagina:
            break

        pagina += 1
        time.sleep(INTERVALO_REQ_SEG)

    return todos


# ---------------------------------------------------------------------------
# Fluxo principal
# ---------------------------------------------------------------------------

def main(dias: int = 15) -> None:
    # 1. Carregar lista de OABs
    oabs = carregar_json(ARQUIVO_OABS, [])
    if not oabs:
        log.error(
            "Arquivo '%s' não encontrado ou vazio. "
            "Crie-o com o formato: [{\"numero\": \"12345\", \"uf\": \"SP\"}, ...]",
            ARQUIVO_OABS,
        )
        sys.exit(1)

    # 2. Estado persistente
    vistos: set[str] = set(carregar_json(ARQUIVO_VISTOS, []))
    existentes: list[dict] = carregar_json(ARQUIVO_SAIDA, [])
    por_id: dict[str, dict] = {p["numero_comunicacao"]: p for p in existentes}

    # 3. Período de busca
    data_inicio, data_fim = calcular_periodo(dias)
    log.info("Período: %s até %s (%d dias)", data_inicio, data_fim, dias)
    log.info("OABs a consultar: %d", len(oabs))

    sessao = requests.Session()
    sessao.headers.update({
        "Accept": "application/json",
        "User-Agent": "captura-publicacoes/1.0",
    })

    total_novas = 0

    for entrada in oabs:
        numero_oab = str(entrada.get("numero", "")).strip()
        uf_oab = str(entrada.get("uf", "")).strip().upper()

        if not numero_oab or not uf_oab:
            log.warning("Entrada inválida em oabs.json (ignorada): %s", entrada)
            continue

        try:
            itens = buscar_publicacoes_oab(
                sessao, numero_oab, uf_oab, data_inicio, data_fim
            )
        except RuntimeError as exc:
            log.error("Erro ao consultar OAB %s/%s: %s", numero_oab, uf_oab, exc)
            continue

        log.info("OAB %s/%s: %d resultado(s) recebido(s) da API.", numero_oab, uf_oab, len(itens))
        novas_esta_oab = 0

        for item in itens:
            # Normaliza a chave — a API pode usar camelCase ou snake_case
            chave = str(
                item.get("numeroComunicacao")
                or item.get("numero_comunicacao")
                or item.get("id")
                or ""
            ).strip()

            if not chave:
                log.warning("Item sem identificador único — ignorado.")
                continue

            if chave in vistos:
                continue  # já capturado em execução anterior

            # Limpar HTML — NÃO logar conteúdo (LGPD)
            texto_bruto = item.get("texto") or item.get("conteudo") or ""
            texto_limpo = limpar_html(texto_bruto)

            por_id[chave] = {
                "numero_comunicacao": chave,
                "dados_brutos": item,
                "texto_limpo": texto_limpo,
                "capturado_em": datetime.now().isoformat(timespec="seconds"),
            }
            vistos.add(chave)
            novas_esta_oab += 1

        total_novas += novas_esta_oab
        log.info("OAB %s/%s: %d nova(s) publicação(ões).", numero_oab, uf_oab, novas_esta_oab)

        # Salvar após cada OAB: protege o progresso em caso de interrupção
        salvar_json(ARQUIVO_SAIDA, list(por_id.values()))
        salvar_json(ARQUIVO_VISTOS, list(vistos))

        time.sleep(INTERVALO_REQ_SEG)

    log.info(
        "Concluído. Novas publicações: %d. Total acumulado em '%s': %d.",
        total_novas, ARQUIVO_SAIDA, len(por_id),
    )


# ---------------------------------------------------------------------------
# Ponto de entrada
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Captura publicações do DJEN via API oficial do PJe."
    )
    parser.add_argument(
        "--dias",
        type=int,
        default=15,
        metavar="N",
        help="Janela de busca em dias corridos (padrão: 15)",
    )
    args = parser.parse_args()
    main(dias=args.dias)
