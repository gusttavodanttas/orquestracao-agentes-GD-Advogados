#!/usr/bin/env python3
"""
bot_telegram.py — Bot Telegram interativo para GD Advogados.
Roda como serviço na VM Oracle e responde a comandos e botões inline.

Comandos:
  /start       — boas-vindas e lista de comandos
  /urgentes    — prazos vencendo em até 3 dias
  /publicacoes — últimas 5 publicações capturadas
  /ajuda       — lista de comandos
"""
from __future__ import annotations

import os
import sys
import logging
from datetime import date

import requests
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv

load_dotenv()

TOKEN       = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID     = int(os.getenv("TELEGRAM_CHAT_ID", "0"))
SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")
ESCRITORIO_ID = os.getenv("ESCRITORIO_ID", "")

if not TOKEN or not CHAT_ID:
    print("TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID são obrigatórios no .env")
    sys.exit(1)


def fmt_data(iso: str | None) -> str:
    """Converte YYYY-MM-DD para DD/MM/YYYY."""
    if not iso:
        return "?"
    try:
        d = date.fromisoformat(iso)
        return d.strftime("%d/%m/%Y")
    except ValueError:
        return iso


def dias_uteis_restantes(data_fim_iso: str | None) -> int | None:
    if not data_fim_iso:
        return None
    try:
        fim = date.fromisoformat(data_fim_iso)
        hoje = date.today()
        delta = (fim - hoje).days
        return delta
    except ValueError:
        return None

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

bot = telebot.TeleBot(TOKEN, parse_mode=None)


# ---------------------------------------------------------------------------
# Helpers Supabase
# ---------------------------------------------------------------------------

def _sb_headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }


def sb_get(tabela: str, params: dict) -> list:
    try:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/{tabela}",
            headers=_sb_headers(),
            params=params,
            timeout=15,
        )
        return r.json() if r.ok else []
    except Exception as exc:
        log.error("Supabase GET erro: %s", exc)
        return []


def sb_post(tabela: str, payload: dict) -> bool:
    try:
        r = requests.post(
            f"{SUPABASE_URL}/rest/v1/{tabela}",
            headers=_sb_headers(),
            json=payload,
            timeout=15,
        )
        return r.ok
    except Exception as exc:
        log.error("Supabase POST erro: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Segurança — só responde ao dono
# ---------------------------------------------------------------------------

def autorizado(chat_id: int) -> bool:
    return chat_id == CHAT_ID


def recusar(msg_or_call):
    log.warning("Acesso não autorizado de chat_id=%s", getattr(msg_or_call, 'chat', getattr(msg_or_call, 'message', None)))


# ---------------------------------------------------------------------------
# /start e /ajuda
# ---------------------------------------------------------------------------

@bot.message_handler(commands=["start", "ajuda"])
def cmd_start(msg):
    if not autorizado(msg.chat.id):
        return recusar(msg)
    bot.send_message(
        CHAT_ID,
        "⚖️ *GD Advogados — Central de Controle*\n\n"
        "Comandos disponíveis:\n"
        "• /urgentes — prazos vencendo em até 3 dias\n"
        "• /publicacoes — últimas 5 publicações\n"
        "• /ajuda — esta mensagem",
        parse_mode="Markdown",
    )


# ---------------------------------------------------------------------------
# /urgentes
# ---------------------------------------------------------------------------

@bot.message_handler(commands=["urgentes"])
def cmd_urgentes(msg):
    if not autorizado(msg.chat.id):
        return recusar(msg)

    prazos = sb_get("prazos", {
        "escritorio_id": f"eq.{ESCRITORIO_ID}",
        "select": "numero_processo,tipo_prazo,data_fim_prazo,publicacao_id",
        "order": "data_fim_prazo.asc",
        "limit": "20",
    })

    hoje = date.today()
    urgentes = []
    for p in prazos:
        dfp = p.get("data_fim_prazo")
        if dfp:
            try:
                fim = date.fromisoformat(dfp)
                dias = (fim - hoje).days
                if dias <= 3:
                    urgentes.append((p, dias))
            except ValueError:
                pass

    if not urgentes:
        bot.send_message(CHAT_ID, "✅ Nenhum prazo urgente no momento.")
        return

    bot.send_message(CHAT_ID, f"🚨 *{len(urgentes)} prazo(s) urgente(s):*", parse_mode="Markdown")

    for p, dias in urgentes:
        rotulo = "🔴 VENCIDO" if dias < 0 else f"⚠️ {abs(dias)} dia(s) útil(eis)"
        texto = (
            f"{rotulo}\n"
            f"Processo: `{p.get('numero_processo','?')}`\n"
            f"Tipo: {p.get('tipo_prazo','?')}\n"
            f"Vence: {fmt_data(p.get('data_fim_prazo'))}"
        )
        kb = _kb_publicacao(p.get("publicacao_id", ""))
        bot.send_message(CHAT_ID, texto, parse_mode="Markdown", reply_markup=kb)


# ---------------------------------------------------------------------------
# /publicacoes
# ---------------------------------------------------------------------------

@bot.message_handler(commands=["publicacoes"])
def cmd_publicacoes(msg):
    if not autorizado(msg.chat.id):
        return recusar(msg)

    pubs = sb_get("publicacoes", {
        "escritorio_id": f"eq.{ESCRITORIO_ID}",
        "select": "id,numero_processo,tipo_documento,data_disponibilizacao,tribunal,visto_em",
        "order": "data_disponibilizacao.desc",
        "limit": "5",
    })

    if not pubs:
        bot.send_message(CHAT_ID, "Nenhuma publicação encontrada.")
        return

    bot.send_message(CHAT_ID, f"📋 *Últimas {len(pubs)} publicações:*", parse_mode="Markdown")

    for p in pubs:
        prazos = sb_get("prazos", {
            "publicacao_id": f"eq.{p['id']}",
            "select": "data_fim_prazo,dias_uteis,base_legal",
            "limit": "1",
        })
        prazo = prazos[0] if prazos else None
        dias = dias_uteis_restantes(prazo["data_fim_prazo"]) if prazo else None

        if dias is None:
            prazo_linha = "Prazo: não calculado"
        elif dias < 0:
            prazo_linha = f"⚠️ Prazo: VENCIDO ({fmt_data(prazo['data_fim_prazo'])})"
        elif dias <= 3:
            prazo_linha = f"🔴 Prazo: {fmt_data(prazo['data_fim_prazo'])} — {dias} dia(s) útil(eis)"
        elif dias <= 7:
            prazo_linha = f"🟡 Prazo: {fmt_data(prazo['data_fim_prazo'])} — {dias} dias úteis"
        else:
            prazo_linha = f"🟢 Prazo: {fmt_data(prazo['data_fim_prazo'])} — {dias} dias úteis"

        visto = "✅ Tratado" if p.get("visto_em") else "🔵 Pendente"
        texto = (
            f"{'✅' if p.get('visto_em') else '📋'} `{p.get('numero_processo','?')}`\n"
            f"Tipo: {p.get('tipo_documento','?')} | {visto}\n"
            f"Data: {fmt_data(p.get('data_disponibilizacao'))} | {p.get('tribunal','?')}\n"
            f"{prazo_linha}"
        )
        kb = _kb_publicacao(p["id"])
        bot.send_message(CHAT_ID, texto, parse_mode="Markdown", reply_markup=kb)


# ---------------------------------------------------------------------------
# Teclado inline reutilizável
# ---------------------------------------------------------------------------

def _kb_publicacao(pub_id: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("📄 Ver teor", callback_data=f"ver|{pub_id}"),
        InlineKeyboardButton("📅 Confirmar prazo", callback_data=f"prazo|{pub_id}"),
    )
    kb.add(
        InlineKeyboardButton("🧠 Acionar orquestrador", callback_data=f"orq|{pub_id}"),
        InlineKeyboardButton("✅ Marcar visto", callback_data=f"visto|{pub_id}"),
    )
    return kb


# ---------------------------------------------------------------------------
# Callbacks dos botões
# ---------------------------------------------------------------------------

@bot.callback_query_handler(func=lambda c: c.data.startswith("ver|"))
def cb_ver_teor(call):
    if not autorizado(call.message.chat.id):
        return
    pub_id = call.data.split("|", 1)[1]
    pubs = sb_get("publicacoes", {
        "id": f"eq.{pub_id}",
        "select": "texto_limpo,numero_processo,tipo_documento,tribunal,data_disponibilizacao,visto_em",
    })
    bot.answer_callback_query(call.id)
    if not pubs:
        bot.send_message(CHAT_ID, "Publicação não encontrada.")
        return
    p = pubs[0]

    prazos = sb_get("prazos", {
        "publicacao_id": f"eq.{pub_id}",
        "select": "data_intimacao,data_fim_prazo,dias_uteis,base_legal",
        "limit": "1",
    })
    prazo = prazos[0] if prazos else None

    visto_em = p.get("visto_em")
    visto_linha = f"\n✅ _Tratado em {fmt_data(visto_em[:10]) if visto_em else '?'}_" if visto_em else ""

    prazo_bloco = ""
    if prazo:
        dias = dias_uteis_restantes(prazo.get("data_fim_prazo"))
        rotulo = "VENCIDO" if dias is not None and dias < 0 else (f"{dias} dias úteis restantes" if dias is not None else "")
        prazo_bloco = (
            f"\n📅 *Prazo:*\n"
            f"Intimação: {fmt_data(prazo.get('data_intimacao'))}\n"
            f"Vencimento: {fmt_data(prazo.get('data_fim_prazo'))} — {prazo.get('dias_uteis','?')} dias úteis CPC\n"
            f"Status: {rotulo}\n"
            f"Base legal: _{prazo.get('base_legal','?')}_\n"
        )

    teor = (p.get("texto_limpo") or "").strip()
    cabecalho = (
        f"📄 *{p.get('tipo_documento','')}*\n"
        f"Processo: `{p.get('numero_processo','')}`\n"
        f"Tribunal: {p.get('tribunal','')} | {fmt_data(p.get('data_disponibilizacao'))}"
        f"{visto_linha}"
        f"{prazo_bloco}\n"
        f"{'─' * 20}\n"
    )
    limite = 4000 - len(cabecalho)
    if len(teor) > limite:
        teor = teor[:limite] + "\n\n_[texto truncado — veja o painel para o teor completo]_"
    bot.send_message(CHAT_ID, cabecalho + teor, parse_mode="Markdown")


@bot.callback_query_handler(func=lambda c: c.data.startswith("prazo|"))
def cb_confirmar_prazo(call):
    if not autorizado(call.message.chat.id):
        return
    bot.answer_callback_query(call.id, "✅ Registrado!")
    bot.send_message(
        CHAT_ID,
        "✅ Prazo confirmado. Acompanhe o calendário no painel.",
    )


@bot.callback_query_handler(func=lambda c: c.data.startswith("orq|"))
def cb_orquestrador(call):
    if not autorizado(call.message.chat.id):
        return
    pub_id = call.data.split("|", 1)[1]
    ok = sb_post("log_orquestrador", {
        "escritorio_id": ESCRITORIO_ID,
        "evento": "acionamento_telegram",
        "agente_origem": "Bot Telegram",
        "agente_destino": "Orquestrador",
        "raciocinio": f"Acionamento manual via Telegram — publicação {pub_id}",
        "acao_tomada": "pendente_analise",
    })
    bot.answer_callback_query(call.id, "🧠 Orquestrador acionado!")
    status = "✅ Registrado na Central de Despacho." if ok else "⚠️ Erro ao registrar — tente pelo painel."
    bot.send_message(CHAT_ID, f"🧠 *Orquestrador acionado*\n{status}", parse_mode="Markdown")


@bot.callback_query_handler(func=lambda c: c.data.startswith("visto|"))
def cb_visto(call):
    if not autorizado(call.message.chat.id):
        return
    pub_id = call.data.split("|", 1)[1]
    from datetime import datetime, timezone
    agora = datetime.now(timezone.utc).isoformat()
    try:
        requests.patch(
            f"{SUPABASE_URL}/rest/v1/publicacoes?id=eq.{pub_id}",
            headers=_sb_headers(),
            json={"visto_em": agora, "visto_via": "telegram"},
            timeout=10,
        )
    except Exception as exc:
        log.warning("Erro ao marcar visto: %s", exc)
    bot.answer_callback_query(call.id, "✅ Marcado como visto!")
    bot.edit_message_reply_markup(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=None,
    )


# ---------------------------------------------------------------------------
# Mensagens de texto livre
# ---------------------------------------------------------------------------

@bot.message_handler(func=lambda m: True)
def echo(msg):
    if not autorizado(msg.chat.id):
        return
    bot.send_message(
        CHAT_ID,
        "Use /ajuda para ver os comandos disponíveis.",
    )


# ---------------------------------------------------------------------------
# Ponto de entrada
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    log.info("Bot GD Advogados iniciado — aguardando comandos...")
    bot.infinity_polling(timeout=30, long_polling_timeout=20)
