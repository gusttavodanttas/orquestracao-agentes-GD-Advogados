#!/usr/bin/env python3
"""
gerar_painel.py — Lê publicacoes.json e prazos calculados e gera dois arquivos:
    painel.html        — dashboard completo (abre no navegador, sem servidor)
    relatorio_diario.html — resumo do dia, pronto para imprimir ou copiar

Uso:
    python gerar_painel.py
    python gerar_painel.py --dias 30   (janela de prazos futuros a exibir)
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

from prazos_cpc import calcular_prazo, eh_dia_util

ARQUIVO_PUBLICACOES = Path("publicacoes.json")
ARQUIVO_PAINEL      = Path("painel.html")
ARQUIVO_RELATORIO   = Path("relatorio_diario.html")
DIAS_URGENTE        = 3
DIAS_ATENCAO        = 7


# ---------------------------------------------------------------------------
# Leitura e enriquecimento dos dados
# ---------------------------------------------------------------------------

def _normalizar_data(bruto: dict) -> str | None:
    d = bruto.get("data_disponibilizacao")
    if d:
        return d
    d = bruto.get("datadisponibilizacao", "")
    if len(d) == 10 and "/" in d:
        dia, mes, ano = d.split("/")
        return f"{ano}-{mes}-{dia}"
    return None


def _dias_uteis_restantes(data_fim: date) -> int:
    hoje = date.today()
    if data_fim < hoje:
        return -1
    contados, d = 0, hoje
    while d <= data_fim:
        if eh_dia_util(d):
            contados += 1
        d += timedelta(days=1)
    return contados


def enriquecer(publicacoes: list[dict], janela_dias: int) -> list[dict]:
    resultado = []
    corte = date.today() + timedelta(days=janela_dias)

    for pub in publicacoes:
        bruto = pub.get("dados_brutos", {})
        data_str = _normalizar_data(bruto)
        tipo_doc = bruto.get("tipoDocumento")
        numero_processo = (
            bruto.get("numero_processo")
            or bruto.get("numeroprocessocommascara")
            or pub.get("numero_comunicacao", "?")
        )
        tribunal = bruto.get("siglaTribunal", "")
        oab_ref = bruto.get("numeroOab", "") or bruto.get("numero_oab", "")
        uf_ref  = bruto.get("ufOab", "")  or bruto.get("uf_oab", "")
        oab_label = f"OAB {oab_ref}/{uf_ref}" if oab_ref else ""

        prazo = None
        data_fim = None
        dias_restantes = None
        status = "sem-data"

        if data_str:
            try:
                data_disp = date.fromisoformat(data_str)
                prazo = calcular_prazo(data_disp, tipo_doc)
                data_fim = prazo["data_fim_prazo"]
                if data_fim:
                    if data_fim > corte:
                        continue
                    dias_restantes = _dias_uteis_restantes(data_fim)
                    if dias_restantes < 0:
                        status = "vencido"
                    elif dias_restantes <= DIAS_URGENTE:
                        status = "urgente"
                    elif dias_restantes <= DIAS_ATENCAO:
                        status = "atencao"
                    else:
                        status = "ok"
                else:
                    status = "indeterminado"
            except (ValueError, KeyError):
                pass

        resultado.append({
            "numero_comunicacao": pub.get("numero_comunicacao", ""),
            "numero_processo": numero_processo,
            "tipo_doc": tipo_doc or "Não identificado",
            "oab": oab_label,
            "tribunal": tribunal,
            "data_disponibilizacao": data_str or "",
            "data_intimacao": prazo["data_intimacao"].strftime("%d/%m/%Y") if prazo else "",
            "data_fim_prazo": data_fim.strftime("%d/%m/%Y") if data_fim else "—",
            "data_fim_iso": data_fim.isoformat() if data_fim else "",
            "dias_restantes": dias_restantes,
            "base_legal": prazo["base_legal"] if prazo else "",
            "status": status,
            "capturado_em": pub.get("capturado_em", ""),
        })

    resultado.sort(key=lambda x: (
        {"vencido": 0, "urgente": 1, "atencao": 2, "ok": 3, "indeterminado": 4, "sem-data": 5}.get(x["status"], 9),
        x["data_fim_iso"] or "9999",
    ))
    return resultado


# ---------------------------------------------------------------------------
# Geração do painel.html
# ---------------------------------------------------------------------------

def gerar_painel(registros: list[dict]) -> None:
    dados_js = json.dumps(registros, ensure_ascii=False)
    hoje_str = date.today().strftime("%d/%m/%Y")
    total = len(registros)
    n_urgentes    = sum(1 for r in registros if r["status"] == "urgente")
    n_vencidos    = sum(1 for r in registros if r["status"] == "vencido")
    n_atencao     = sum(1 for r in registros if r["status"] == "atencao")
    n_ok          = sum(1 for r in registros if r["status"] == "ok")
    n_indet       = sum(1 for r in registros if r["status"] == "indeterminado")

    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Painel de Publicações — GD Advogados</title>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f5f5f4; color: #1c1c1b; font-size: 14px; }}
  a {{ color: inherit; text-decoration: none; }}
  header {{ background: #fff; border-bottom: 1px solid #e4e2db; padding: 14px 24px; display: flex; justify-content: space-between; align-items: center; position: sticky; top: 0; z-index: 10; }}
  header h1 {{ font-size: 16px; font-weight: 600; }}
  header span {{ font-size: 12px; color: #888; }}
  main {{ max-width: 1100px; margin: 0 auto; padding: 24px 16px; }}
  .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; margin-bottom: 24px; }}
  .card {{ background: #fff; border-radius: 10px; padding: 14px 16px; border: 1px solid #e4e2db; }}
  .card-num {{ font-size: 28px; font-weight: 600; line-height: 1; margin-bottom: 4px; }}
  .card-lbl {{ font-size: 12px; color: #888; }}
  .card.urgente .card-num {{ color: #a32d2d; }}
  .card.urgente {{ background: #fcebeb; border-color: #f09595; }}
  .card.atencao .card-num {{ color: #854f0b; }}
  .card.atencao {{ background: #faeeda; border-color: #fac775; }}
  .filtros {{ display: flex; gap: 8px; margin-bottom: 16px; flex-wrap: wrap; }}
  .filtros select, .filtros input {{ padding: 7px 10px; border: 1px solid #d3d1c7; border-radius: 8px; font-size: 13px; background: #fff; outline: none; }}
  .filtros select:focus, .filtros input:focus {{ border-color: #888; }}
  table {{ width: 100%; border-collapse: collapse; background: #fff; border-radius: 10px; overflow: hidden; border: 1px solid #e4e2db; }}
  thead {{ background: #f5f5f4; }}
  th {{ padding: 10px 14px; text-align: left; font-size: 12px; font-weight: 600; color: #888; border-bottom: 1px solid #e4e2db; }}
  td {{ padding: 10px 14px; font-size: 13px; border-bottom: 1px solid #f0eeea; vertical-align: top; }}
  tr:last-child td {{ border-bottom: none; }}
  tr:hover td {{ background: #fafaf9; }}
  .badge {{ display: inline-block; padding: 2px 8px; border-radius: 5px; font-size: 11px; font-weight: 600; }}
  .badge-vencido {{ background: #501313; color: #fff; }}
  .badge-urgente {{ background: #fcebeb; color: #a32d2d; }}
  .badge-atencao {{ background: #faeeda; color: #854f0b; }}
  .badge-ok {{ background: #eaf3de; color: #3b6d11; }}
  .badge-indeterminado {{ background: #f1efe8; color: #5f5e5a; }}
  .badge-sem-data {{ background: #f1efe8; color: #888; }}
  .processo {{ font-family: 'Courier New', monospace; font-size: 12px; }}
  .base {{ font-size: 11px; color: #aaa; margin-top: 2px; }}
  .vazio {{ padding: 40px; text-align: center; color: #aaa; }}
  #contagem {{ font-size: 12px; color: #888; margin-bottom: 8px; }}
  @media print {{ header {{ position: static; }} .filtros {{ display: none; }} }}
</style>
</head>
<body>
<header>
  <h1>GD Advogados · Painel de Publicações</h1>
  <span>Gerado em {hoje_str} · Fonte: DJEN / PJe</span>
</header>
<main>
  <div class="cards">
    <div class="card urgente">
      <div class="card-num" id="c-urgente">{n_urgentes + n_vencidos}</div>
      <div class="card-lbl">Urgente / vencido</div>
    </div>
    <div class="card atencao">
      <div class="card-num" id="c-atencao">{n_atencao}</div>
      <div class="card-lbl">Atenção (4–7 dias)</div>
    </div>
    <div class="card">
      <div class="card-num" id="c-ok" style="color:#3b6d11">{n_ok}</div>
      <div class="card-lbl">Em dia</div>
    </div>
    <div class="card">
      <div class="card-num" id="c-total">{total}</div>
      <div class="card-lbl">Total exibidos</div>
    </div>
  </div>

  <div class="filtros">
    <input type="text" id="busca" placeholder="Buscar processo, tipo, OAB..." style="flex:1; min-width:200px;">
    <select id="f-status">
      <option value="">Todos os status</option>
      <option value="vencido">Vencido</option>
      <option value="urgente">Urgente</option>
      <option value="atencao">Atenção</option>
      <option value="ok">Em dia</option>
      <option value="indeterminado">Indeterminado</option>
    </select>
    <select id="f-tipo">
      <option value="">Todos os tipos</option>
      <option value="Sentença">Sentença</option>
      <option value="Acórdão">Acórdão</option>
      <option value="Decisão">Decisão</option>
      <option value="Despacho">Despacho</option>
      <option value="Edital">Edital</option>
    </select>
  </div>

  <p id="contagem"></p>

  <table>
    <thead>
      <tr>
        <th>Processo</th>
        <th>Tipo</th>
        <th>OAB / Tribunal</th>
        <th>Intimação</th>
        <th>Vence em</th>
        <th>Dias úteis</th>
        <th>Status</th>
      </tr>
    </thead>
    <tbody id="tbody"></tbody>
  </table>

  <p style="font-size:11px; color:#aaa; margin-top:16px; text-align:center;">
    Prazos calculados conforme arts. 219, 224 e 231-I do CPC · Feriados nacionais incluídos ·
    Verifique recessos tribunalícios (art. 220 CPC) manualmente.
  </p>
</main>

<script>
const DADOS = {dados_js};
const LABELS = {{ vencido:'Vencido', urgente:'Urgente', atencao:'Atenção', ok:'Em dia', indeterminado:'Verificar', 'sem-data':'Sem data' }};

function render() {{
  const busca  = document.getElementById('busca').value.toLowerCase();
  const fstatus = document.getElementById('f-status').value;
  const ftipo   = document.getElementById('f-tipo').value;

  const filtrados = DADOS.filter(r => {{
    if (fstatus && r.status !== fstatus) return false;
    if (ftipo && r.tipo_doc !== ftipo) return false;
    if (busca && !(r.numero_processo.toLowerCase().includes(busca) ||
                   r.tipo_doc.toLowerCase().includes(busca) ||
                   r.oab.toLowerCase().includes(busca))) return false;
    return true;
  }});

  document.getElementById('contagem').textContent = filtrados.length + ' registro(s) exibido(s).';

  const tbody = document.getElementById('tbody');
  if (!filtrados.length) {{
    tbody.innerHTML = '<tr><td colspan="7" class="vazio">Nenhuma publicação encontrada com esses filtros.</td></tr>';
    return;
  }}
  tbody.innerHTML = filtrados.map(r => {{
    const diasTexto = r.dias_restantes === null ? '—'
      : r.dias_restantes < 0 ? `<span style="color:#a32d2d;font-weight:600">Vencido há ${{Math.abs(r.dias_restantes)}} dia(s)</span>`
      : `${{r.dias_restantes}} dia(s)`;
    return `<tr>
      <td>
        <div class="processo">${{r.numero_processo}}</div>
        <div class="base">${{r.base_legal}}</div>
      </td>
      <td>${{r.tipo_doc}}</td>
      <td>${{r.oab}}<br><span style="color:#aaa;font-size:11px">${{r.tribunal}}</span></td>
      <td>${{r.data_intimacao}}</td>
      <td>${{r.data_fim_prazo}}</td>
      <td>${{diasTexto}}</td>
      <td><span class="badge badge-${{r.status}}">${{LABELS[r.status] || r.status}}</span></td>
    </tr>`;
  }}).join('');
}}

document.getElementById('busca').addEventListener('input', render);
document.getElementById('f-status').addEventListener('change', render);
document.getElementById('f-tipo').addEventListener('change', render);
render();
</script>
</body>
</html>"""

    ARQUIVO_PAINEL.write_text(html, encoding="utf-8")
    print(f"Painel gerado: {ARQUIVO_PAINEL.resolve()}")


# ---------------------------------------------------------------------------
# Geração do relatorio_diario.html
# ---------------------------------------------------------------------------

def gerar_relatorio(registros: list[dict]) -> None:
    hoje = date.today()
    hoje_str = hoje.strftime("%d/%m/%Y")
    dia_semana = ["segunda-feira","terça-feira","quarta-feira","quinta-feira",
                  "sexta-feira","sábado","domingo"][hoje.weekday()]

    urgentes    = [r for r in registros if r["status"] in ("urgente", "vencido")]
    atencao     = [r for r in registros if r["status"] == "atencao"]
    ok          = [r for r in registros if r["status"] == "ok"]
    indets      = [r for r in registros if r["status"] == "indeterminado"]

    def bloco(items: list[dict], cor_bg: str, cor_txt: str, cor_item: str, titulo: str, icone: str) -> str:
        if not items:
            return ""
        linhas = "".join(f"""
          <div style="background:{cor_item};border-radius:6px;padding:10px 12px;margin-bottom:6px;">
            <p style="font-size:13px;font-weight:600;color:{cor_txt};font-family:monospace">{r['numero_processo']}</p>
            <p style="font-size:12px;color:{cor_txt};margin-top:2px">{r['tipo_doc']} &nbsp;·&nbsp; Vence {r['data_fim_prazo']}
              {"&nbsp;·&nbsp; <strong>" + str(r['dias_restantes']) + " dia(s) útil(eis)</strong>" if r['dias_restantes'] is not None and r['dias_restantes'] >= 0 else "&nbsp;·&nbsp; <strong style='color:#501313'>VENCIDO</strong>"}
              {"&nbsp;·&nbsp; " + r['oab'] if r['oab'] else ""}
            </p>
            <p style="font-size:11px;color:{cor_txt};opacity:.7;margin-top:2px">{r['base_legal']}</p>
          </div>""" for r in items)
        return f"""
        <div style="background:{cor_bg};border-radius:10px;padding:14px 16px;margin-bottom:14px;">
          <p style="font-size:13px;font-weight:600;color:{cor_txt};margin-bottom:10px">{icone} {titulo}</p>
          {linhas}
        </div>"""

    b_urgente = bloco(urgentes, "#fcebeb", "#a32d2d", "#fff1f0", f"Urgente / Vencido — {len(urgentes)} processo(s)", "⚠")
    b_atencao = bloco(atencao, "#faeeda", "#854f0b", "#fef6e7", f"Atenção — {len(atencao)} processo(s)", "🕐")
    b_ok_text = ""
    if ok:
        b_ok_text = f"""<div style="border:1px solid #d3e8b8;border-radius:10px;padding:14px 16px;margin-bottom:14px;">
          <p style="font-size:13px;font-weight:600;color:#3b6d11;margin-bottom:4px">✓ Em dia — {len(ok)} processo(s)</p>
          <p style="font-size:12px;color:#5f5e5a">Nenhuma ação imediata necessária.</p></div>"""
    b_indet_text = ""
    if indets:
        lista = "".join(f"<li style='font-size:12px;color:#5f5e5a;margin-bottom:3px'><code>{r['numero_processo']}</code> — {r['tipo_doc']}</li>" for r in indets)
        b_indet_text = f"""<div style="border:1px solid #d3d1c7;border-radius:10px;padding:14px 16px;margin-bottom:14px;">
          <p style="font-size:13px;font-weight:600;color:#5f5e5a;margin-bottom:6px">⚡ Verificar manualmente — {len(indets)} processo(s)</p>
          <ul style="padding-left:16px">{lista}</ul></div>"""

    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<title>Relatório Diário — {hoje_str}</title>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f5f5f4; color: #1c1c1b; }}
  .envelope {{ max-width: 640px; margin: 32px auto; background: #fff; border-radius: 12px; border: 1px solid #e4e2db; padding: 28px; }}
  @media print {{ body {{ background: #fff; }} .envelope {{ margin: 0; border: none; box-shadow: none; }} }}
</style>
</head>
<body>
<div class="envelope">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:20px;padding-bottom:16px;border-bottom:1px solid #e4e2db">
    <div>
      <p style="font-size:18px;font-weight:700">GD Advogados</p>
      <p style="font-size:13px;color:#888;margin-top:2px">Relatório de prazos · {hoje_str} ({dia_semana})</p>
    </div>
    <div style="text-align:right">
      <p style="font-size:12px;color:#aaa">Gerado automaticamente</p>
      <p style="font-size:12px;color:#aaa">Fonte: DJEN / PJe</p>
    </div>
  </div>

  {b_urgente}
  {b_atencao}
  {b_ok_text}
  {b_indet_text}

  <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;text-align:center;padding-top:16px;border-top:1px solid #e4e2db;margin-top:8px">
    <div><p style="font-size:22px;font-weight:700;color:#a32d2d">{len(urgentes)}</p><p style="font-size:11px;color:#888">Urgente/venc.</p></div>
    <div><p style="font-size:22px;font-weight:700;color:#854f0b">{len(atencao)}</p><p style="font-size:11px;color:#888">Atenção</p></div>
    <div><p style="font-size:22px;font-weight:700;color:#3b6d11">{len(ok)}</p><p style="font-size:11px;color:#888">Em dia</p></div>
    <div><p style="font-size:22px;font-weight:700;color:#888">{len(indets)}</p><p style="font-size:11px;color:#888">Verificar</p></div>
  </div>

  <p style="font-size:11px;color:#bbb;margin-top:20px;text-align:center">
    Prazos calculados conforme arts. 219, 224 e 231-I do CPC · Feriados nacionais incluídos ·
    Verifique recessos tribunalícios (art. 220 CPC) manualmente.
  </p>
</div>
</body>
</html>"""

    ARQUIVO_RELATORIO.write_text(html, encoding="utf-8")
    print(f"Relatório gerado: {ARQUIVO_RELATORIO.resolve()}")


# ---------------------------------------------------------------------------
# Ponto de entrada
# ---------------------------------------------------------------------------

def main(janela_dias: int = 60) -> None:
    if not ARQUIVO_PUBLICACOES.exists():
        print(f"Arquivo '{ARQUIVO_PUBLICACOES}' não encontrado. Rode capturar.py primeiro.", file=sys.stderr)
        sys.exit(1)

    with ARQUIVO_PUBLICACOES.open(encoding="utf-8") as arq:
        publicacoes = json.load(arq)

    print(f"{len(publicacoes)} publicação(ões) carregada(s).")
    registros = enriquecer(publicacoes, janela_dias)
    print(f"{len(registros)} publicação(ões) dentro da janela de {janela_dias} dias.")

    gerar_painel(registros)
    gerar_relatorio(registros)
    print("Pronto! Abra os arquivos HTML no navegador para visualizar.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Gera painel.html e relatorio_diario.html a partir de publicacoes.json"
    )
    parser.add_argument(
        "--dias", type=int, default=60, metavar="N",
        help="Janela de prazos futuros a exibir em dias (padrão: 60)",
    )
    args = parser.parse_args()
    main(janela_dias=args.dias)
