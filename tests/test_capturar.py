"""
Testes do capturar.py.

Como rodar:
    python -m pytest tests/ -v
"""
import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

# Permite importar capturar.py a partir da pasta raiz do projeto
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import capturar


# ---------------------------------------------------------------------------
# 1. Limpeza de HTML
# ---------------------------------------------------------------------------
class TestLimparHtml(unittest.TestCase):

    def test_remove_tags_basicas(self):
        self.assertEqual(capturar.limpar_html("<p>Olá <b>mundo</b></p>"), "Olá mundo")

    def test_string_vazia_retorna_vazio(self):
        self.assertEqual(capturar.limpar_html(""), "")

    def test_none_retorna_vazio(self):
        self.assertEqual(capturar.limpar_html(None), "")

    def test_texto_sem_tags_e_mantido(self):
        self.assertEqual(capturar.limpar_html("Texto puro"), "Texto puro")

    def test_html_juridico_sem_angulares(self):
        html = "<div><p>Intima-se o advogado do processo <strong>0001234-56.2024.8.26.0100</strong>.</p></div>"
        resultado = capturar.limpar_html(html)
        self.assertIn("Intima-se", resultado)
        self.assertIn("0001234-56.2024.8.26.0100", resultado)
        self.assertNotIn("<", resultado)
        self.assertNotIn(">", resultado)


# ---------------------------------------------------------------------------
# 2. Cálculo de período
# ---------------------------------------------------------------------------
class TestCalcularPeriodo(unittest.TestCase):

    def test_retorna_formato_yyyy_mm_dd(self):
        inicio, fim = capturar.calcular_periodo(15)
        # Não deve lançar exceção — valida o formato
        datetime.strptime(inicio, "%Y-%m-%d")
        datetime.strptime(fim, "%Y-%m-%d")

    def test_diferenca_em_dias_correta(self):
        inicio, fim = capturar.calcular_periodo(15)
        d_i = datetime.strptime(inicio, "%Y-%m-%d")
        d_f = datetime.strptime(fim, "%Y-%m-%d")
        self.assertEqual((d_f - d_i).days, 15)

    def test_um_dia(self):
        inicio, fim = capturar.calcular_periodo(1)
        d_i = datetime.strptime(inicio, "%Y-%m-%d")
        d_f = datetime.strptime(fim, "%Y-%m-%d")
        self.assertEqual((d_f - d_i).days, 1)

    def test_trinta_dias(self):
        inicio, fim = capturar.calcular_periodo(30)
        d_i = datetime.strptime(inicio, "%Y-%m-%d")
        d_f = datetime.strptime(fim, "%Y-%m-%d")
        self.assertEqual((d_f - d_i).days, 30)


# ---------------------------------------------------------------------------
# 3. Comportamento HTTP da função `requisitar`
# ---------------------------------------------------------------------------
class TestRequisitar(unittest.TestCase):

    @staticmethod
    def _mock_resposta(status, json_data=None, headers=None):
        """Cria uma resposta HTTP falsa para os testes (sem chamar a internet)."""
        resp = MagicMock()
        resp.status_code = status
        resp.json.return_value = json_data or {}
        resp.headers = headers or {}
        if status >= 400:
            resp.raise_for_status.side_effect = Exception(f"HTTP {status}")
        else:
            resp.raise_for_status = MagicMock()
        return resp

    def test_200_devolve_json(self):
        sessao = MagicMock()
        sessao.get.return_value = self._mock_resposta(200, {"content": [], "last": True})
        resultado = capturar.requisitar(sessao, {})
        self.assertEqual(resultado["content"], [])

    def test_403_encerra_com_mensagem_clara(self):
        """Erro 403 deve encerrar o script imediatamente (bloqueio geográfico)."""
        sessao = MagicMock()
        sessao.get.return_value = self._mock_resposta(403)
        with self.assertRaises(SystemExit):
            capturar.requisitar(sessao, {})

    @patch("capturar.time.sleep")
    def test_429_aguarda_retry_after_e_tenta_novamente(self, mock_sleep):
        """Erro 429 deve aguardar o tempo informado pelo servidor e repetir."""
        sessao = MagicMock()
        sessao.get.side_effect = [
            self._mock_resposta(429, headers={"Retry-After": "7"}),
            self._mock_resposta(200, {"content": [], "last": True}),
        ]
        resultado = capturar.requisitar(sessao, {})
        mock_sleep.assert_called_once_with(7)   # aguardou exatamente 7 segundos
        self.assertIn("content", resultado)

    @patch("capturar.time.sleep")
    def test_429_para_apos_limite_de_tentativas(self, _mock_sleep):
        """Após MAX_TENTATIVAS erros 429 seguidos, deve lançar RuntimeError."""
        sessao = MagicMock()
        sessao.get.return_value = self._mock_resposta(429, headers={"Retry-After": "1"})
        with self.assertRaises(RuntimeError):
            # Chama já na última tentativa permitida
            capturar.requisitar(sessao, {}, tentativa=capturar.MAX_TENTATIVAS + 1)


# ---------------------------------------------------------------------------
# 4. Deduplicação entre execuções
# ---------------------------------------------------------------------------
class TestDeduplicacao(unittest.TestCase):

    def _mock_carregar(self, oabs, vistos_ids, publicacoes):
        """Simula carregar_json para os três arquivos diferentes."""
        def lado(caminho, padrao):
            nome = str(caminho)
            if "oabs" in nome:
                return oabs
            if "vistos" in nome:
                return vistos_ids
            if "publicacoes" in nome:
                return publicacoes
            return padrao
        return lado

    @patch("capturar.salvar_json")
    @patch("capturar.buscar_publicacoes_oab")
    @patch("capturar.carregar_json")
    def test_item_ja_visto_nao_e_salvo_de_novo(self, mock_carregar, mock_buscar, mock_salvar):
        """Se um ID já está em vistos.json, não deve aparecer nas novas publicações."""
        mock_carregar.side_effect = self._mock_carregar(
            oabs=[{"numero": "12345", "uf": "SP"}],
            vistos_ids=["ID-ANTIGO"],
            publicacoes=[],
        )
        mock_buscar.return_value = [
            {"numeroComunicacao": "ID-ANTIGO", "texto": "<p>já processado</p>"},
            {"numeroComunicacao": "ID-NOVO",   "texto": "<p>novo item</p>"},
        ]

        capturar.main(dias=15)

        # Pega a última gravação em publicacoes.json
        chamadas = [c for c in mock_salvar.call_args_list if "publicacoes" in str(c.args[0])]
        publicacoes_salvas = chamadas[-1].args[1]
        ids = {p["numero_comunicacao"] for p in publicacoes_salvas}

        self.assertIn("ID-NOVO", ids)
        self.assertNotIn("ID-ANTIGO", ids)

    @patch("capturar.salvar_json")
    @patch("capturar.buscar_publicacoes_oab")
    @patch("capturar.carregar_json")
    def test_texto_limpo_sem_tags_html(self, mock_carregar, mock_buscar, mock_salvar):
        """O campo texto_limpo deve conter apenas texto, sem marcação HTML."""
        mock_carregar.side_effect = self._mock_carregar(
            oabs=[{"numero": "99999", "uf": "MG"}],
            vistos_ids=[],
            publicacoes=[],
        )
        mock_buscar.return_value = [
            {"numeroComunicacao": "ID-001", "texto": "<p>Texto <b>limpo</b> aqui</p>"},
        ]

        capturar.main(dias=15)

        chamadas = [c for c in mock_salvar.call_args_list if "publicacoes" in str(c.args[0])]
        pub = chamadas[-1].args[1][0]

        self.assertEqual(pub["texto_limpo"], "Texto limpo aqui")
        self.assertNotIn("<", pub["texto_limpo"])

    @patch("capturar.salvar_json")
    @patch("capturar.buscar_publicacoes_oab")
    @patch("capturar.carregar_json")
    def test_ids_vistos_sao_atualizados(self, mock_carregar, mock_buscar, mock_salvar):
        """Após capturar, vistos.json deve incluir o novo ID."""
        mock_carregar.side_effect = self._mock_carregar(
            oabs=[{"numero": "11111", "uf": "RJ"}],
            vistos_ids=[],
            publicacoes=[],
        )
        mock_buscar.return_value = [
            {"numeroComunicacao": "ID-ABC", "texto": ""},
        ]

        capturar.main(dias=15)

        chamadas_vistos = [c for c in mock_salvar.call_args_list if "vistos" in str(c.args[0])]
        vistos_salvos = chamadas_vistos[-1].args[1]

        self.assertIn("ID-ABC", vistos_salvos)


if __name__ == "__main__":
    unittest.main(verbosity=2)
