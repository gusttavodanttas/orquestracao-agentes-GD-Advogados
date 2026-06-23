"""
prazos_cpc.py — Cálculo determinístico de prazos processuais (CPC).

Regras implementadas:
  Art. 219  — contam apenas dias úteis (segunda a sexta, excluídos feriados)
  Art. 224  — exclui o dia do início, inclui o dia do vencimento
  Art. 231 I — intimação pelo DJe considera-se realizada no 1º dia útil
               seguinte à data de disponibilização

IMPORTANTE: Art. 220 (suspensão em recesso de janeiro e julho) NÃO está
implementado aqui — cada tribunal define datas exatas de recesso. Verifique
manualmente se a publicação ocorreu próxima de um recesso.
"""
from __future__ import annotations

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
    """Sexta-feira Santa e Corpus Christi (feriados nacionais móveis)."""
    pascoa = _pascoa(ano)
    return {
        pascoa - timedelta(days=2),   # Sexta-feira Santa
        pascoa + timedelta(days=60),  # Corpus Christi
    }


def eh_feriado(d: date) -> bool:
    """Verifica se a data é feriado nacional."""
    if (d.month, d.day) in _FERIADOS_FIXOS:
        return True
    return d in _feriados_moveis(d.year)


def eh_dia_util(d: date) -> bool:
    """True se o dia é útil: segunda–sexta e não é feriado nacional."""
    if d.weekday() >= 5:   # 5 = sábado, 6 = domingo
        return False
    return not eh_feriado(d)


def proximo_dia_util(d: date) -> date:
    """Primeiro dia útil APÓS a data informada."""
    resultado = d + timedelta(days=1)
    while not eh_dia_util(resultado):
        resultado += timedelta(days=1)
    return resultado


def adicionar_dias_uteis(data_inicio: date, dias: int) -> date:
    """
    Conta `dias` dias úteis a partir de data_inicio, excluindo data_inicio.
    Implementa Art. 224 CPC: exclui o primeiro dia, inclui o último.
    """
    d = data_inicio
    contados = 0
    while contados < dias:
        d += timedelta(days=1)
        if eh_dia_util(d):
            contados += 1
    return d


# ---------------------------------------------------------------------------
# Mapeamento tipo de documento → prazo em dias úteis + base legal
# ---------------------------------------------------------------------------
_PRAZOS: dict[str, tuple[int | None, str]] = {
    "Sentença":  (15, "Apelação — Art. 1.003 c/c Art. 1.009 CPC"),
    "Acórdão":   (15, "Recurso — Art. 1.003 CPC"),
    "Decisão":   (15, "Agravo de instrumento ou manifestação — Art. 1.003 CPC"),
    "Despacho":  (5,  "Manifestação — Art. 218 §3 CPC"),
    "Certidão":  (5,  "Manifestação — Art. 218 §3 CPC"),
    "Edital":    (None, "Prazo especificado no edital — verificar manualmente"),
}
_PRAZO_PADRAO: tuple[int, str] = (15, "Manifestação — Art. 218 §3 CPC")


def calcular_prazo(data_disponibilizacao: date, tipo_documento: str | None) -> dict:
    """
    Calcula prazo processual conforme CPC.

    Parâmetros:
        data_disponibilizacao : data em que a publicação saiu no DJe
        tipo_documento        : tipo do ato (Sentença, Decisão, Despacho…)

    Retorna:
        data_intimacao  — 1º dia útil após publicação (Art. 231 I)
        data_fim_prazo  — último dia do prazo (None se indeterminado)
        dias_uteis      — quantidade de dias úteis (None se indeterminado)
        base_legal      — dispositivo do CPC aplicado
    """
    dias, base_legal = _PRAZOS.get(tipo_documento or "", _PRAZO_PADRAO)

    # Art. 231 I: intimação realizada no 1º dia útil após disponibilização no DJe
    data_intimacao = proximo_dia_util(data_disponibilizacao)

    if dias is None:
        return {
            "data_intimacao": data_intimacao,
            "data_fim_prazo": None,
            "dias_uteis": None,
            "base_legal": base_legal,
        }

    # Art. 224: exclui data_intimacao, conta dias a partir do dia seguinte
    data_fim = adicionar_dias_uteis(data_intimacao, dias)

    return {
        "data_intimacao": data_intimacao,
        "data_fim_prazo": data_fim,
        "dias_uteis": dias,
        "base_legal": base_legal,
    }
