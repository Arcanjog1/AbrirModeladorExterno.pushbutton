# -*- coding: utf-8 -*-
"""Testes de core/engine/progress.py::dispatch_progress_event - ver
tests/README.md e a FASE 1 do plano em
C:\\Users\\CIVIX\\.claude\\plans\\quiet-painting-petal.md.

Cobre a CAUSA REAL do travamento reportado em producao: o closure antigo
`_progress_cb` (core/wall_modeling.py, _WallReviewForm._on_start_click) so'
tratava chamadas de 2 argumentos e descartava em silencio as de 1 e 4
argumentos que find_wall_group_shift_fixes/plan_axis_opening_fix realmente
fazem durante a ETAPA 3C - sem nenhum desses descartados chegar ao
console, Application.DoEvents() nunca rodava e a janela parava de bombear
mensagens pelo tempo que a ETAPA 3C levasse.
"""
import os
import sys
import unittest

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_BUTTON_ROOT = os.path.dirname(_TESTS_DIR)
if _BUTTON_ROOT not in sys.path:
    sys.path.insert(0, _BUTTON_ROOT)

from core.engine.progress import dispatch_progress_event


class _FakeConsole(object):
    """Grava as chamadas recebidas em vez de tocar WinForms/Application.
    DoEvents() de verdade - e' exatamente essa independencia que torna o
    despachante testavel sem Revit/WinForms."""

    def __init__(self):
        self.log_calls = []
        self.progress_calls = []

    def log(self, message):
        self.log_calls.append(message)

    def set_progress(self, done, total, detail=None):
        self.progress_calls.append((done, total, detail))


class DispatchProgressEventTests(unittest.TestCase):
    def test_one_argument_status_message_logs(self):
        """Forma usada por find_wall_group_shift_fixes/plan_axis_opening_fix
        para uma mensagem de status pronta (ex.: "ETAPA 3C: 4 parede(s)
        ainda sem solucao..."). Antes desta correcao, esta forma era
        SILENCIOSAMENTE DESCARTADA pelo closure antigo (`if len(cb_args) ==
        2`) - o bug real do travamento."""
        console = _FakeConsole()
        dispatch_progress_event(console, "TENTAR CORRIGIR (ETAPA 3C): 4 parede(s)...")
        self.assertEqual(console.log_calls, ["TENTAR CORRIGIR (ETAPA 3C): 4 parede(s)..."])
        self.assertEqual(console.progress_calls, [])

    def test_two_argument_done_total_sets_progress(self):
        """Forma usada por process_walls_one_by_one (granularidade ~10%) -
        ja' funcionava antes, precisa continuar funcionando identica."""
        console = _FakeConsole()
        dispatch_progress_event(console, 5, 20)
        self.assertEqual(console.log_calls, [])
        self.assertEqual(len(console.progress_calls), 1)
        done, total, detail = console.progress_calls[0]
        self.assertEqual((done, total), (5, 20))
        self.assertIn("5/20", detail)

    def test_four_argument_attempt_tuple_logs_and_sets_progress(self):
        """Forma usada por find_wall_group_shift_fixes a CADA tentativa de
        re-solve da planta inteira (ate' 120 vezes por padrao) - a MESMA
        forma que o closure antigo tambem descartava em silencio, o
        trecho mais pesado e silencioso da execucao (ver docstring de
        find_wall_group_shift_fixes)."""
        console = _FakeConsole()
        dispatch_progress_event(console, 7, 120, 42, "deslocamento de grupo")
        self.assertEqual(len(console.log_calls), 1)
        self.assertIn("parede 42", console.log_calls[0])
        self.assertIn("7/120", console.log_calls[0])
        self.assertEqual(len(console.progress_calls), 1)
        done, total, detail = console.progress_calls[0]
        self.assertEqual((done, total), (7, 120))

    def test_unknown_argument_shape_is_ignored_not_raised(self):
        """Postura defensiva preservada: uma forma desconhecida (nem 1, 2
        nem 4 argumentos) nunca deve levantar excecao nem tocar o
        console - mesma garantia que o closure antigo tinha para as
        formas que ele conhecia."""
        console = _FakeConsole()
        try:
            dispatch_progress_event(console, "a", "b", "c")  # 3 argumentos
        except Exception as ex:  # pragma: no cover - nao deveria acontecer
            self.fail("dispatch_progress_event nao deveria lancar: {}".format(ex))
        self.assertEqual(console.log_calls, [])
        self.assertEqual(console.progress_calls, [])

    def test_console_method_raising_never_propagates(self):
        """Mesma protecao do _ProgressConsole original: uma falha ao
        atualizar a UI (ex.: controle ja destruido) nunca pode derrubar o
        solver que esta' chamando o callback."""
        class _RaisingConsole(object):
            def log(self, message):
                raise RuntimeError("controle destruido")

        try:
            dispatch_progress_event(_RaisingConsole(), "mensagem qualquer")
        except Exception as ex:  # pragma: no cover
            self.fail("dispatch_progress_event nao deveria propagar: {}".format(ex))


if __name__ == "__main__":
    unittest.main()
