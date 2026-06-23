"""
Testes de test_prazos_cpc.py — cálculo determinístico de prazos (CPC).

Como rodar: python -m pytest tests/ -v
"""
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prazos_cpc import (
    adicionar_dias_uteis,
    calcular_prazo,
    eh_dia_util,
    eh_feriado,
    proximo_dia_util,
)


class TestFeriados(unittest.TestCase):

    def test_natal_e_feriado(self):
        self.assertTrue(eh_feriado(date(2026, 12, 25)))

    def test_tiradentes_e_feriado(self):
        self.assertTrue(eh_feriado(date(2026, 4, 21)))

    def test_dia_comum_nao_e_feriado(self):
        self.assertFalse(eh_feriado(date(2026, 3, 10)))  # terça comum

    def test_sexta_santa_2026(self):
        # Páscoa 2026 = 5 abril; Sexta Santa = 3 abril
        self.assertTrue(eh_feriado(date(2026, 4, 3)))

    def test_corpus_christi_2026(self):
        # Páscoa 2026 = 5 abril; Corpus Christi = 4 junho
        self.assertTrue(eh_feriado(date(2026, 6, 4)))


class TestDiaUtil(unittest.TestCase):

    def test_segunda_util(self):
        self.assertTrue(eh_dia_util(date(2026, 6, 15)))   # segunda-feira

    def test_sabado_nao_util(self):
        self.assertFalse(eh_dia_util(date(2026, 6, 20)))  # sábado

    def test_domingo_nao_util(self):
        self.assertFalse(eh_dia_util(date(2026, 6, 21)))  # domingo

    def test_feriado_nao_util(self):
        self.assertFalse(eh_dia_util(date(2026, 12, 25))) # natal

    def test_sexta_comum_e_util(self):
        self.assertTrue(eh_dia_util(date(2026, 6, 19)))   # sexta comum


class TestProximoDiaUtil(unittest.TestCase):

    def test_sexta_vai_para_segunda(self):
        # Sexta 19/06/2026 → próximo = segunda 22/06/2026
        self.assertEqual(proximo_dia_util(date(2026, 6, 19)), date(2026, 6, 22))

    def test_sabado_vai_para_segunda(self):
        self.assertEqual(proximo_dia_util(date(2026, 6, 20)), date(2026, 6, 22))

    def test_pula_feriado(self):
        # Véspera do Natal (24/12 quinta) → próximo deveria ser 26/12 (sábado) → 28/12 (segunda)
        # Na verdade 25/12 é feriado, 26/12 sábado, 27/12 domingo, 28/12 segunda
        self.assertEqual(proximo_dia_util(date(2026, 12, 24)), date(2026, 12, 28))


class TestAdicionarDiasUteis(unittest.TestCase):

    def test_5_dias_uteis_semana_normal(self):
        # Segunda 01/06/2026 + 5 dias úteis = segunda 08/06/2026
        resultado = adicionar_dias_uteis(date(2026, 6, 1), 5)
        self.assertEqual(resultado, date(2026, 6, 8))

    def test_pula_fim_de_semana(self):
        # Sexta 19/06/2026 + 1 dia útil = segunda 22/06/2026
        resultado = adicionar_dias_uteis(date(2026, 6, 19), 1)
        self.assertEqual(resultado, date(2026, 6, 22))

    def test_15_dias_uteis(self):
        # Testa que retorna um dia útil
        resultado = adicionar_dias_uteis(date(2026, 6, 1), 15)
        self.assertTrue(eh_dia_util(resultado))


class TestCalcularPrazo(unittest.TestCase):

    def test_sentenca_15_dias_uteis(self):
        # Publicação numa sexta → intimação na segunda → 15 dias úteis
        resultado = calcular_prazo(date(2026, 6, 19), "Sentença")
        self.assertEqual(resultado["dias_uteis"], 15)
        self.assertEqual(resultado["data_intimacao"], date(2026, 6, 22))  # segunda
        self.assertTrue(eh_dia_util(resultado["data_fim_prazo"]))

    def test_despacho_5_dias_uteis(self):
        resultado = calcular_prazo(date(2026, 6, 22), "Despacho")
        self.assertEqual(resultado["dias_uteis"], 5)

    def test_edital_sem_prazo(self):
        resultado = calcular_prazo(date(2026, 6, 22), "Edital")
        self.assertIsNone(resultado["data_fim_prazo"])
        self.assertIsNone(resultado["dias_uteis"])

    def test_tipo_desconhecido_usa_padrao_15(self):
        resultado = calcular_prazo(date(2026, 6, 22), "TipoDesconhecido")
        self.assertEqual(resultado["dias_uteis"], 15)

    def test_base_legal_presente(self):
        resultado = calcular_prazo(date(2026, 6, 22), "Sentença")
        self.assertIn("CPC", resultado["base_legal"])

    def test_data_intimacao_e_dia_util(self):
        # A data de intimação deve sempre ser dia útil
        resultado = calcular_prazo(date(2026, 6, 19), "Sentença")
        self.assertTrue(eh_dia_util(resultado["data_intimacao"]))

    def test_data_fim_e_dia_util(self):
        resultado = calcular_prazo(date(2026, 6, 22), "Acórdão")
        self.assertTrue(eh_dia_util(resultado["data_fim_prazo"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
