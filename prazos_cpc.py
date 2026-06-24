"""
prazos_cpc.py — Cálculo determinístico de prazos processuais.

Regras implementadas:
  CPC (Lei 13.105/2015):
    Art. 219  — contam apenas dias úteis (segunda a sexta, excluídos feriados)
    Art. 224  — exclui o dia do início, inclui o dia do vencimento
    Art. 231 I — intimação pelo DJe considera-se realizada no 1º dia útil
                 seguinte à data de disponibilização

  Juizado Especial Cível (Lei 9.099/95):
    Art. 41   — recurso inominado: 10 dias corridos
    Art. 49   — embargos de declaração: 5 dias corridos
    Demais    — prazos contados em dias corridos (não úteis)

  Juizado Especial Federal (Lei 10.259/2001):
    Art. 5    — prazos em dias corridos

IMPORTANTE: Art. 220 CPC (suspensão em recesso de janeiro e julho) NÃO está
implementado — cada tribunal define datas exatas. Verifique manualmente se a
publicação ocorreu próxima de um recesso.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

# ---------------------------------------------------------------------------
# Feriados nacionais fixos (mês, dia)
# ---------------------------------------------------------------------------
_FERIADOS_FIXOS: set[tuple[int, int]] = {
    (1,  1),   # Confraternização Universal
    (4,  21),  # Tiradentes
    (5,  1),   # Dia do Trabalho
    (9,  7),   # Independência do Brasil
    (10, 12),  # Nossa Senhora Aparecida
    (11, 2),   # Finados
    (11, 15),  # Proclamação da República
    (11, 20),  # Consciência Negra (Lei 14.759/2023)
    (12, 25),  # Natal
}


def _pascoa(ano: int) -> date:
    """Data da Páscoa pelo algoritmo de Gauss."""
    a = ano % 19
    b = ano % 4
    c = ano % 7
    d = (19 * a + 24) % 30
    e = (2 * b + 4 * c + 6 * d + 5) % 7
    dia = 22 + d + e
    mes = 3
    if dia > 31:
        dia -= 31
        mes = 4
        if d == 29 and e == 6:
            dia = 19
        elif d == 28 and e == 6 and a > 10:
            dia = 18
    return date(ano, mes, dia)


def _feriados_moveis(ano: int) -> set[date]:
    pascoa = _pascoa(ano)
    return {
        pascoa - timedelta(days=2),   # Sexta-feira Santa
        pascoa + timedelta(days=60),  # Corpus Christi
    }


def eh_feriado(d: date) -> bool:
    if (d.month, d.day) in _FERIADOS_FIXOS:
        return True
    return d in _feriados_moveis(d.year)


def eh_dia_util(d: date) -> bool:
    if d.weekday() >= 5:
        return False
    return not eh_feriado(d)


def proximo_dia_util(d: date) -> date:
    resultado = d + timedelta(days=1)
    while not eh_dia_util(resultado):
        resultado += timedelta(days=1)
    return resultado


def adicionar_dias_uteis(data_inicio: date, dias: int) -> date:
    """Conta `dias` dias úteis a partir de data_inicio (Art. 224 CPC)."""
    d = data_inicio
    contados = 0
    while contados < dias:
        d += timedelta(days=1)
        if eh_dia_util(d):
            contados += 1
    return d


def adicionar_dias_corridos(data_inicio: date, dias: int) -> date:
    """Conta `dias` dias corridos (calendário) a partir de data_inicio."""
    return data_inicio + timedelta(days=dias)


# ---------------------------------------------------------------------------
# Detecção de Juizado Especial
# ---------------------------------------------------------------------------

def _eh_juizado(nome_orgao: str | None) -> bool:
    if not nome_orgao:
        return False
    n = nome_orgao.upper()
    return "JUIZADO" in n


def _eh_juizado_federal(nome_orgao: str | None) -> bool:
    if not nome_orgao:
        return False
    n = nome_orgao.upper()
    return "JUIZADO" in n and "FEDERAL" in n


# ---------------------------------------------------------------------------
# Tabelas de prazos
# ---------------------------------------------------------------------------

# CPC — dias úteis
_PRAZOS_CPC: dict[str, tuple[int | None, str]] = {
    "Sentença":            (15, "Apelação — Art. 1.003 c/c Art. 1.009 CPC"),
    "Acórdão":             (15, "Recurso — Art. 1.003 CPC"),
    "Decisão":             (15, "Agravo de instrumento ou manifestação — Art. 1.003 CPC"),
    "Despacho":            (5,  "Manifestação — Art. 218 §3 CPC"),
    "Certidão":            (5,  "Manifestação — Art. 218 §3 CPC"),
    "Edital":              (None, "Prazo especificado no edital — verificar manualmente"),
}
_PRAZO_PADRAO_CPC: tuple[int, str] = (15, "Manifestação — Art. 218 §3 CPC")

# Juizado Especial Cível — dias corridos (Lei 9.099/95)
_PRAZOS_JUIZADO: dict[str, tuple[int | None, str]] = {
    "Sentença":            (10, "Recurso inominado — Art. 41 Lei 9.099/95 (dias corridos)"),
    "Acórdão":             (10, "Recurso — Art. 41 Lei 9.099/95 (dias corridos)"),
    "Decisão":             (10, "Recurso — Art. 41 Lei 9.099/95 (dias corridos)"),
    "Despacho":            (5,  "Embargos de declaração — Art. 49 Lei 9.099/95 (dias corridos)"),
    "Certidão":            (5,  "Manifestação — Art. 49 Lei 9.099/95 (dias corridos)"),
    "Edital":              (None, "Prazo especificado no edital — verificar manualmente"),
}
_PRAZO_PADRAO_JUIZADO: tuple[int, str] = (10, "Manifestação — Art. 41 Lei 9.099/95 (dias corridos)")

# Classes que indicam cumprimento de sentença (prazo diferente)
_CLASSES_CUMPRIMENTO = {"CUMPRIMENTO DE SENTENÇA", "CUMPRIMENTO DE SENTENCA",
                         "EXECUÇÃO DE TÍTULO EXTRAJUDICIAL", "EXECUCAO DE TITULO EXTRAJUDICIAL"}


# ---------------------------------------------------------------------------
# Extração de prazo mencionado no texto (regex — determinístico)
# ---------------------------------------------------------------------------

_RE_PRAZO = re.compile(
    r'(?:prazo\s+de\s+|no\s+prazo\s+de\s+|fixo\s+o\s+prazo\s+de\s+)'
    r'(\d+)\s*(?:\([^)]+\)\s*)?\s*dias?',
    re.IGNORECASE,
)


def extrair_prazo_texto(texto: str | None) -> int | None:
    """
    Extrai o primeiro prazo em dias mencionado explicitamente no texto.
    Retorna None se não encontrar. Resultado é determinístico (regex puro).
    """
    if not texto:
        return None
    m = _RE_PRAZO.search(texto)
    if m:
        return int(m.group(1))
    return None


# ---------------------------------------------------------------------------
# Função principal
# ---------------------------------------------------------------------------

def calcular_prazo(
    data_disponibilizacao: date,
    tipo_documento: str | None,
    nome_classe: str | None = None,
    nome_orgao: str | None = None,
    texto: str | None = None,
) -> dict:
    """
    Calcula prazo processual.

    Parâmetros:
        data_disponibilizacao : data em que a publicação saiu no DJe
        tipo_documento        : tipo do ato (Sentença, Decisão, Despacho…)
        nome_classe           : classe processual (ex: CUMPRIMENTO DE SENTENÇA)
        nome_orgao            : nome do órgão julgador (detecta Juizado)
        texto                 : texto da publicação para extração de prazo

    Retorna dict com:
        data_intimacao        — 1º dia útil após publicação (Art. 231 I)
        data_fim_prazo        — último dia do prazo (None se indeterminado)
        dias_uteis            — quantidade de dias do prazo
        base_legal            — dispositivo legal aplicado
        prazo_no_texto        — dias mencionados no texto (None se não encontrado)
        eh_juizado            — True se Juizado Especial detectado
        dias_corridos         — True se prazo em dias corridos (Juizado)
    """
    juizado = _eh_juizado(nome_orgao)
    prazo_no_texto = extrair_prazo_texto(texto)

    # Art. 231 I: intimação no 1º dia útil após disponibilização
    data_intimacao = proximo_dia_util(data_disponibilizacao)

    if juizado:
        dias, base_legal = _PRAZOS_JUIZADO.get(tipo_documento or "", _PRAZO_PADRAO_JUIZADO)
        # Se o texto menciona prazo explícito, usa ele (mais confiável)
        if prazo_no_texto is not None:
            dias = prazo_no_texto
            base_legal = f"Prazo de {dias} dias mencionado no texto — verificar base legal"
        if dias is None:
            return {
                "data_intimacao": data_intimacao,
                "data_fim_prazo": None,
                "dias_uteis": None,
                "base_legal": base_legal,
                "prazo_no_texto": prazo_no_texto,
                "eh_juizado": True,
                "dias_corridos": True,
            }
        data_fim = adicionar_dias_corridos(data_intimacao, dias)
        return {
            "data_intimacao": data_intimacao,
            "data_fim_prazo": data_fim,
            "dias_uteis": dias,
            "base_legal": base_legal,
            "prazo_no_texto": prazo_no_texto,
            "eh_juizado": True,
            "dias_corridos": True,
        }

    # CPC comum — dias úteis
    dias, base_legal = _PRAZOS_CPC.get(tipo_documento or "", _PRAZO_PADRAO_CPC)

    if dias is None:
        return {
            "data_intimacao": data_intimacao,
            "data_fim_prazo": None,
            "dias_uteis": None,
            "base_legal": base_legal,
            "prazo_no_texto": prazo_no_texto,
            "eh_juizado": False,
            "dias_corridos": False,
        }

    data_fim = adicionar_dias_uteis(data_intimacao, dias)
    return {
        "data_intimacao": data_intimacao,
        "data_fim_prazo": data_fim,
        "dias_uteis": dias,
        "base_legal": base_legal,
        "prazo_no_texto": prazo_no_texto,
        "eh_juizado": False,
        "dias_corridos": False,
    }
