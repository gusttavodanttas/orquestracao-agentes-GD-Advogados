#!/usr/bin/env python3
"""
capturar.py — Captura publicações do DJEN via API oficial do PJe
              e grava no Supabase (requer .env configurado).

Uso:
    python capturar.py
    python capturar.py --dias 30
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
import requests
from bs4 import BeautifulSoup

from prazos_cpc import calcular_prazo, eh_dia_util

# ---------------------------------------------------------------------------
# Variáveis de ambiente (.env)
# ---------------------------------------------------------------------------
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")
ESCRITORIO_ID = os.getenv("ESCRITORIO_ID", "")

_SUPABASE_CONFIGURADO = bool(SUPABASE_URL and SUPABASE_KEY and ESCRITORIO_ID)

# ---------------------------------------------------------------------------
# Configurações da API do DJEN
# ---------------------------------------------------------------------------
API_URL = "https://comunicaapi.pje.jus.br/api/v1/comunicacao"
ITENS_POR_PAGINA = 100
INTERVALO_REQ_SEG = 0.5   # 0,5 s entre requisições = ~2 req/s
MAX_TENTATIVAS = 5

ARQUIVO_OABS = Path("oabs.json")
ARQUIVO_VISTOS = Path("vistos.json")
ARQUIVO_SAIDA  = Path("publicacoes.json")
LOG_AUDITORIA  = Path("captura.log")
DIAS_URGENTE   = 3   # prazo em ≤ 3 dias úteis = urgente
DIAS_ATENCAO   = 7   # prazo em ≤ 7 dias úteis = atenção

# ---------------------------------------------------------------------------
# Logging — sem dados de partes (LGPD)
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# Grava também em arquivo — para conferir no dia seguinte
_fh = logging.FileHandler(LOG_AUDITORIA, encoding="utf-8-sig")
_fh.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
))
log.addHandler(_fh)


# ---------------------------------------------------------------------------
# Funções puras
# ---------------------------------------------------------------------------

def limpar_html(texto: str | None) -> str:
    """Remove marcações HTML e devolve texto simples."""
    if not texto:
        return ""
    return BeautifulSoup(texto, "html.parser").get_text(separator=" ", strip=True)


def calcular_periodo(dias: int) -> tuple[str, str]:
    """Devolve (data_inicio, data_fim) no formato YYYY-MM-DD."""
    hoje = datetime.today()
    inicio = hoje - timedelta(days=dias)
    return inicio.strftime("%Y-%m-%d"), hoje.strftime("%Y-%m-%d")


def carregar_json(caminho: Path, padrao):
    if caminho.exists():
        with caminho.open(encoding="utf-8") as arq:
            return json.load(arq)
    return padrao


def salvar_json(caminho: Path, dados) -> None:
    with caminho.open("w", encoding="utf-8") as arq:
        json.dump(dados, arq, ensure_ascii=False, indent=2)


def _dias_uteis_restantes(data_fim: date) -> int:
    """Dias úteis de hoje até data_fim inclusive. Retorna -1 se já venceu."""
    hoje = date.today()
    if data_fim < hoje:
        return -1
    contados, d = 0, hoje
    while d <= data_fim:
        if eh_dia_util(d):
            contados += 1
        d += timedelta(days=1)
    return contados


def _normalizar_data(bruto: dict) -> str | None:
    """Extrai data de disponibilização do item da API (suporta dois formatos)."""
    d = bruto.get("data_disponibilizacao")
    if d:
        return d  # já em YYYY-MM-DD
    d = bruto.get("datadisponibilizacao", "")
    if len(d) == 10 and "/" in d:
        dia, mes, ano = d.split("/")
        return f"{ano}-{mes}-{dia}"
    return None


# ---------------------------------------------------------------------------
# Requisição à API DJEN com controle de taxa e retry
# ---------------------------------------------------------------------------

def requisitar(sessao: requests.Session, params: dict, tentativa: int = 1) -> dict:
    """GET na API com retry em 429 e saída clara em 403."""
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
            "API sinalizou limite de taxa (429). Aguardando %ds (tentativa %d/%d).",
            espera, tentativa, MAX_TENTATIVAS,
        )
        time.sleep(espera)
        return requisitar(sessao, params, tentativa + 1)

    if resposta.status_code == 403:
        log.error(
            "Acesso bloqueado (403) — provável bloqueio geográfico. "
            "Execute este script de um computador ou servidor com IP brasileiro."
        )
        sys.exit(1)

    resposta.raise_for_status()
    return resposta.json()


# ---------------------------------------------------------------------------
# Busca paginada para uma OAB
# ---------------------------------------------------------------------------

def buscar_publicacoes_oab(
    sessao: requests.Session,
    numero_oab: str,
    uf_oab: str,
    data_inicio: str,
    data_fim: str,
) -> list[dict]:
    """Percorre todas as páginas da API e devolve lista de itens brutos."""
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

        itens: list[dict] = dados.get("items") or dados.get("content") or []
        todos.extend(itens)

        ultima_pagina = (
            dados.get("last") is True
            or not itens
            or len(itens) < ITENS_POR_PAGINA
        )
        total = dados.get("totalPages") or dados.get("total_pages")
        if total is not None and pagina + 1 >= int(total):
            ultima_pagina = True

        if ultima_pagina:
            break

        pagina += 1
        time.sleep(INTERVALO_REQ_SEG)

    return todos


# ---------------------------------------------------------------------------
# Integração com Supabase (API REST — sem SDK adicional)
# ---------------------------------------------------------------------------

def _sb_headers(extras: dict | None = None) -> dict:
    """Cabeçalhos padrão para chamadas à API REST do Supabase."""
    h = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }
    if extras:
        h.update(extras)
    return h


def upsert_publicacao(sessao: requests.Session, pub: dict) -> str | None:
    """
    Grava ou atualiza publicação no Supabase.
    Usa upsert pela chave (escritorio_id, numero_comunicacao).
    Retorna o UUID do registro, ou None em caso de erro.
    """
    bruto = pub["dados_brutos"]
    data_disp = _normalizar_data(bruto)
    numero_processo = (
        bruto.get("numero_processo")
        or bruto.get("numeroprocessocommascara")
    )

    payload = {
        "escritorio_id": ESCRITORIO_ID,
        "numero_comunicacao": pub["numero_comunicacao"],
        "bruto": bruto,                              # campo jsonb
        "texto_limpo": pub.get("texto_limpo", ""),
        "tipo_comunicacao": bruto.get("tipoComunicacao"),
        "tipo_documento": bruto.get("tipoDocumento"),
        "data_disponibilizacao": data_disp,
        "numero_processo": numero_processo,
        "tribunal": bruto.get("siglaTribunal"),
    }

    url = (
        f"{SUPABASE_URL}/rest/v1/publicacoes"
        "?on_conflict=escritorio_id,numero_comunicacao"
    )
    resp = sessao.post(
        url,
        json=payload,
        headers=_sb_headers({"Prefer": "resolution=merge-duplicates,return=representation"}),
        timeout=30,
    )

    if not resp.ok:
        log.error(
            "Supabase: erro ao gravar publicação %s — %s",
            pub["numero_comunicacao"], resp.text,
        )
        return None

    dados = resp.json()
    return dados[0]["id"] if dados else None


def criar_tarefa_despacho(
    sessao: requests.Session,
    pub: dict,
    publicacao_id: str,
    prazo_info: dict,
    dias_restantes: int,
) -> None:
    """Cria tarefa na Central de Despacho para prazos urgentes ou de atenção."""
    bruto = pub["dados_brutos"]
    numero_processo = (
        bruto.get("numero_processo")
        or bruto.get("numeroprocessocommascara")
        or "não informado"
    )
    tipo_doc = bruto.get("tipoDocumento") or "Não identificado"
    vence = prazo_info["data_fim_prazo"]

    if dias_restantes < 0:
        prioridade = "alta"
        titulo = f"VENCIDO — {tipo_doc} · {numero_processo}"
    elif dias_restantes <= DIAS_URGENTE:
        prioridade = "alta"
        titulo = f"Prazo urgente ({dias_restantes}d) — {tipo_doc} · {numero_processo}"
    else:
        prioridade = "media"
        titulo = f"Prazo em {dias_restantes} dias — {tipo_doc} · {numero_processo}"

    # Busca o agente Monitor DJEN
    agente_resp = sessao.get(
        f"{SUPABASE_URL}/rest/v1/agentes",
        params={"nome": "eq.Monitor DJEN", "escritorio_id": f"eq.{ESCRITORIO_ID}"},
        headers=_sb_headers({"Accept": "application/json"}),
        timeout=10,
    )
    agente_id = None
    if agente_resp.ok and agente_resp.json():
        agente_id = agente_resp.json()[0]["id"]

    # Gera docket via RPC
    dk_resp = sessao.post(
        f"{SUPABASE_URL}/rest/v1/rpc/proximo_docket",
        json={"p_escritorio_id": ESCRITORIO_ID},
        headers=_sb_headers(),
        timeout=10,
    )
    docket = dk_resp.json() if dk_resp.ok else "GD-AUTO"

    payload = {
        "escritorio_id": ESCRITORIO_ID,
        "agente_id": agente_id,
        "docket": docket,
        "tipo": "prazo_judicial",
        "titulo": titulo,
        "prioridade": prioridade,
        "numero_processo": numero_processo,
        "publicacao_id": publicacao_id,
        "conteudo": {
            "tipo_documento": tipo_doc,
            "data_fim_prazo": vence.isoformat() if vence else None,
            "dias_restantes": dias_restantes,
            "base_legal": prazo_info.get("base_legal", ""),
        },
    }

    url = f"{SUPABASE_URL}/rest/v1/tarefas?on_conflict=publicacao_id"
    resp = sessao.post(
        url,
        json=payload,
        headers=_sb_headers({"Prefer": "resolution=ignore,return=minimal"}),
        timeout=15,
    )
    if resp.ok:
        log.info("Tarefa criada na Central de Despacho: %s | %s", docket, titulo)
    else:
        log.error("Erro ao criar tarefa no despacho: %s", resp.text)


def upsert_prazo(
    sessao: requests.Session,
    pub: dict,
    publicacao_id: str,
    prazo_calculado: dict | None = None,
) -> None:
    """Grava prazo no Supabase. Reutiliza prazo_calculado se já disponível."""
    bruto = pub["dados_brutos"]
    data_disp_str = _normalizar_data(bruto)

    if not data_disp_str:
        log.warning(
            "Publicação %s sem data de disponibilização — prazo não calculado.",
            pub["numero_comunicacao"],
        )
        return

    try:
        data_disp = date.fromisoformat(data_disp_str)
    except ValueError:
        log.warning("Data inválida '%s' — prazo ignorado.", data_disp_str)
        return

    tipo_doc = bruto.get("tipoDocumento")
    prazo = prazo_calculado or calcular_prazo(
        data_disp, tipo_doc,
        nome_classe=bruto.get("nomeClasse"),
        nome_orgao=bruto.get("nomeOrgao"),
        texto=pub.get("texto_limpo"),
    )

    numero_processo = (
        bruto.get("numero_processo")
        or bruto.get("numeroprocessocommascara")
        or "não informado"
    )

    payload = {
        "escritorio_id": ESCRITORIO_ID,
        "publicacao_id": publicacao_id,
        "numero_processo": numero_processo,
        "tipo_prazo": tipo_doc or "Não identificado",
        "data_disponibilizacao": data_disp_str,
        "data_intimacao": prazo["data_intimacao"].isoformat(),
        "data_fim_prazo": (
            prazo["data_fim_prazo"].isoformat()
            if prazo["data_fim_prazo"] else None
        ),
        "dias_uteis": prazo["dias_uteis"],
        "base_legal": prazo["base_legal"],
        "prazo_no_texto": prazo.get("prazo_no_texto"),
        "eh_juizado": prazo.get("eh_juizado", False),
        "dias_corridos": prazo.get("dias_corridos", False),
    }

    url = f"{SUPABASE_URL}/rest/v1/prazos?on_conflict=publicacao_id"
    resp = sessao.post(
        url,
        json=payload,
        headers=_sb_headers({"Prefer": "resolution=merge-duplicates,return=minimal"}),
        timeout=30,
    )

    if not resp.ok:
        log.error(
            "Supabase: erro ao gravar prazo de %s — %s",
            pub["numero_comunicacao"], resp.text,
        )
    else:
        log.info(
            "Prazo gravado: processo %s | %s dias úteis | vence %s",
            numero_processo,
            prazo["dias_uteis"],
            prazo["data_fim_prazo"],
        )


# ---------------------------------------------------------------------------
# Vínculo automático cliente ↔ publicação
# ---------------------------------------------------------------------------

def _norm_processo(numero: str | None) -> str:
    """Remove tudo que não for dígito para comparar números de processo."""
    return "".join(c for c in (numero or "") if c.isdigit())


def _vincular_cliente(sessao: requests.Session, pub_id: str, pub: dict) -> None:
    """
    Busca na tabela `processos` pelo número do processo da publicação.
    Se encontrar, atualiza a publicação com cliente_id e polo.
    """
    bruto = pub["dados_brutos"]
    numero_raw = (
        bruto.get("numero_processo")
        or bruto.get("numeroprocessocommascara")
        or ""
    )
    numero_norm = _norm_processo(numero_raw)
    if not numero_norm:
        return

    # Busca todos os processos do escritório e compara dígitos
    resp = sessao.get(
        f"{SUPABASE_URL}/rest/v1/processos",
        params={
            "escritorio_id": f"eq.{ESCRITORIO_ID}",
            "select": "id,numero_processo,cliente_id,polo",
        },
        headers=_sb_headers({"Accept": "application/json"}),
        timeout=15,
    )
    if not resp.ok:
        return

    for proc in resp.json():
        if _norm_processo(proc.get("numero_processo")) == numero_norm:
            sessao.patch(
                f"{SUPABASE_URL}/rest/v1/publicacoes?id=eq.{pub_id}",
                json={"cliente_id": proc["cliente_id"], "polo": proc["polo"]},
                headers=_sb_headers(),
                timeout=10,
            )
            log.info(
                "Publicação %s vinculada ao processo %s (polo: %s)",
                pub_id, numero_raw, proc["polo"],
            )
            return


# ---------------------------------------------------------------------------
# Notificação via Telegram Bot (API oficial, gratuita)
# ---------------------------------------------------------------------------

def notificar_telegram(urgentes: list[dict], total_novas: int) -> None:
    """Envia resumo no Telegram se houver urgências ou novas publicações."""
    token   = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return
    if not urgentes and total_novas == 0:
        return

    hoje = date.today().strftime("%d/%m/%Y")
    linhas = [f"⚖️ *GD Advogados — {hoje}*"]

    if urgentes:
        linhas.append(f"\n🚨 *{len(urgentes)} prazo(s) urgente(s):*")
        for u in urgentes[:5]:
            rotulo = "VENCIDO ❌" if u["dias"] < 0 else f"{u['dias']}d úteis ⚠️"
            linhas.append(f"• `{u['processo']}` → {rotulo}")
        if len(urgentes) > 5:
            linhas.append(f"  _...e mais {len(urgentes) - 5}_")

    linhas.append(f"\n📥 {total_novas} nova(s) publicação(ões) capturada(s).")

    def _tg_post(payload: dict) -> None:
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json=payload, timeout=15,
            )
            if not r.ok:
                log.warning("Telegram: %s %s", r.status_code, r.text)
        except requests.RequestException as exc:
            log.warning("Falha ao enviar Telegram: %s", exc)

    _tg_post({"chat_id": chat_id, "text": "\n".join(linhas), "parse_mode": "Markdown"})
    log.info("Notificação enviada via Telegram.")


# ---------------------------------------------------------------------------
# Fluxo principal
# ---------------------------------------------------------------------------

def main(dias: int = 15) -> None:
    if not _SUPABASE_CONFIGURADO:
        log.warning(
            "Arquivo .env não encontrado ou incompleto. "
            "Copie .env.exemplo para .env e preencha as credenciais. "
            "Executando apenas com arquivo local (publicacoes.json)."
        )

    env_oabs = os.getenv("OABS_JSON", "").strip()
    if env_oabs:
        try:
            oabs = json.loads(env_oabs)
        except json.JSONDecodeError:
            log.error("Variável OABS_JSON com JSON inválido — verifique o formato.")
            sys.exit(1)
    else:
        oabs = carregar_json(ARQUIVO_OABS, [])
    if not oabs:
        log.error(
            "OABs não encontradas. Crie oabs.json ou defina a variável OABS_JSON. "
            "Formato: [{\"numero\": \"12345\", \"uf\": \"SP\"}, ...]",
        )
        sys.exit(1)

    vistos: set[str] = set(carregar_json(ARQUIVO_VISTOS, []))
    existentes: list[dict] = carregar_json(ARQUIVO_SAIDA, [])
    por_id: dict[str, dict] = {p["numero_comunicacao"]: p for p in existentes}

    data_inicio, data_fim = calcular_periodo(dias)
    log.info("Período: %s até %s (%d dias)", data_inicio, data_fim, dias)
    log.info("OABs a consultar: %d", len(oabs))

    sessao = requests.Session()
    sessao.headers.update({
        "Accept": "application/json",
        "User-Agent": "captura-publicacoes/1.0",
    })

    total_novas = 0
    urgentes: list[dict] = []

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

        log.info("OAB %s/%s: %d resultado(s) recebido(s).", numero_oab, uf_oab, len(itens))
        novas_esta_oab = 0

        for item in itens:
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
                continue

            texto_bruto = item.get("texto") or item.get("conteudo") or ""
            texto_limpo = limpar_html(texto_bruto)  # não logado — LGPD

            registro: dict = {
                "numero_comunicacao": chave,
                "dados_brutos": item,
                "texto_limpo": texto_limpo,
                "capturado_em": datetime.now().isoformat(timespec="seconds"),
            }

            # Calcular prazo localmente (urgência + Supabase)
            prazo_info: dict | None = None
            data_disp_str = _normalizar_data(item)
            if data_disp_str:
                try:
                    prazo_info = calcular_prazo(
                        date.fromisoformat(data_disp_str),
                        item.get("tipoDocumento"),
                        nome_classe=item.get("nomeClasse"),
                        nome_orgao=item.get("nomeOrgao"),
                        texto=texto_limpo,
                    )
                except ValueError:
                    pass

            dias_restantes: int | None = None
            if prazo_info and prazo_info["data_fim_prazo"]:
                dias_restantes = _dias_uteis_restantes(prazo_info["data_fim_prazo"])
                if dias_restantes <= DIAS_URGENTE:
                    urgentes.append({
                        "processo": (
                            item.get("numero_processo")
                            or item.get("numeroprocessocommascara", "?")
                        ),
                        "vence": prazo_info["data_fim_prazo"],
                        "dias": dias_restantes,
                    })

            # Gravar no Supabase (publicação + prazo + tarefa na Central de Despacho)
            if _SUPABASE_CONFIGURADO:
                pub_id = upsert_publicacao(sessao, registro)
                if pub_id:
                    _vincular_cliente(sessao, pub_id, registro)
                    upsert_prazo(sessao, registro, pub_id, prazo_calculado=prazo_info)
                    # Cria tarefa no despacho para prazos urgentes e de atenção
                    if prazo_info and dias_restantes is not None and dias_restantes <= DIAS_ATENCAO:
                        criar_tarefa_despacho(sessao, registro, pub_id, prazo_info, dias_restantes)

            por_id[chave] = registro
            vistos.add(chave)
            novas_esta_oab += 1

        total_novas += novas_esta_oab
        log.info("OAB %s/%s: %d nova(s).", numero_oab, uf_oab, novas_esta_oab)

        # Salvar localmente após cada OAB (preserva progresso)
        salvar_json(ARQUIVO_SAIDA, list(por_id.values()))
        salvar_json(ARQUIVO_VISTOS, list(vistos))

        time.sleep(INTERVALO_REQ_SEG)

    # Resumo no log de auditoria
    if urgentes:
        log.warning(
            "URGENTE: %d prazo(s) vencendo em até %d dias úteis:",
            len(urgentes), DIAS_URGENTE,
        )
        for u in urgentes:
            rotulo = "VENCIDO" if u["dias"] < 0 else f"{u['dias']} dia(s) útil(eis) restante(s)"
            log.warning("  → processo %s | vence %s | %s", u["processo"], u["vence"], rotulo)

    log.info(
        "RESUMO: novas=%d | urgentes=%d | total acumulado=%d",
        total_novas, len(urgentes), len(por_id),
    )

    notificar_telegram(urgentes, total_novas)


# ---------------------------------------------------------------------------
# Ponto de entrada
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Captura publicações do DJEN e grava no Supabase."
    )
    parser.add_argument(
        "--dias", type=int, default=15, metavar="N",
        help="Janela de busca em dias corridos (padrão: 15)",
    )
    args = parser.parse_args()
    main(dias=args.dias)
