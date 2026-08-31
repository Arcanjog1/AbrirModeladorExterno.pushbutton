# -*- coding: utf-8 -*-
"""Estado transacional do editor interativo.

O solver continua puro: esta classe não conhece geometria, Revit ou regras
de modulação. Ela apenas mantém snapshots de uma captura, revision IDs,
cache de previews e histórico atômico para a camada HTTP/UI.
"""

import copy
import threading
from collections import OrderedDict


class EditorSession(object):
    """Sessão isolada de um modelo carregado no editor 3D.

    Previews nunca alteram ``capture``. Uma edição definitiva só é aceita se
    tiver partido da revisão atual, evitando que um worker lento substitua uma
    alteração mais nova. Cada commit é uma única entrada de undo, incluindo a
    geometria e os blocos regenerados por ele.
    """

    def __init__(self, capture, candidates=None, diagnostics=None, cache_limit=48):
        self._lock = threading.RLock()
        self._cache_limit = max(1, int(cache_limit))
        self._preview_cache = OrderedDict()
        self._revision = 0
        self._history = [self._snapshot(capture, candidates, diagnostics, None)]
        self._history_index = 0

    @staticmethod
    def _snapshot(capture, candidates, diagnostics, action):
        return {
            "capture": copy.deepcopy(capture),
            "candidates": copy.deepcopy(candidates or []),
            "diagnostics": copy.deepcopy(diagnostics or {}),
            "action": copy.deepcopy(action),
        }

    @property
    def revision(self):
        with self._lock:
            return self._revision

    def current(self):
        """Devolve uma cópia consistente para cálculo fora da thread da UI."""
        with self._lock:
            state = self._history[self._history_index]
            return self._revision, self._snapshot(
                state["capture"], state["candidates"], state["diagnostics"], state["action"]
            )

    def preview(self, key, build):
        """Calcula ou reutiliza uma prévia sem tocar no histórico."""
        with self._lock:
            cached = self._preview_cache.get(key)
            if cached is not None:
                self._preview_cache.move_to_end(key)
                return copy.deepcopy(cached), True
        value = build()
        with self._lock:
            self._preview_cache[key] = copy.deepcopy(value)
            self._preview_cache.move_to_end(key)
            while len(self._preview_cache) > self._cache_limit:
                self._preview_cache.popitem(last=False)
        return value, False

    def commit(self, expected_revision, capture, candidates, diagnostics, action):
        """Persiste uma edição se não houver conflito de geração.

        Retorna ``(ok, revision, state)``. Em caso de conflito, ``state`` é a
        versão atual para que a API possa responder sem aplicar resultado
        obsoleto.
        """
        with self._lock:
            if expected_revision is not None and int(expected_revision) != self._revision:
                state = self._history[self._history_index]
                return False, self._revision, self._snapshot(
                    state["capture"], state["candidates"], state["diagnostics"], state["action"]
                )
            self._history = self._history[:self._history_index + 1]
            state = self._snapshot(capture, candidates, diagnostics, action)
            self._history.append(state)
            self._history_index += 1
            self._revision += 1
            self._preview_cache.clear()
            return True, self._revision, self._snapshot(
                state["capture"], state["candidates"], state["diagnostics"], state["action"]
            )

    def undo(self, expected_revision=None):
        return self._move_history(-1, expected_revision)

    def redo(self, expected_revision=None):
        return self._move_history(1, expected_revision)

    def _move_history(self, direction, expected_revision):
        with self._lock:
            if expected_revision is not None and int(expected_revision) != self._revision:
                return False, "stale", self._revision, None
            new_index = self._history_index + direction
            if new_index < 0 or new_index >= len(self._history):
                return False, "unavailable", self._revision, None
            self._history_index = new_index
            self._revision += 1
            self._preview_cache.clear()
            state = self._history[self._history_index]
            return True, "ok", self._revision, self._snapshot(
                state["capture"], state["candidates"], state["diagnostics"], state["action"]
            )

    def history_summary(self):
        with self._lock:
            return {
                "revision": self._revision,
                "can_undo": self._history_index > 0,
                "can_redo": self._history_index < len(self._history) - 1,
                "entries": [copy.deepcopy(item.get("action")) for item in self._history[1:]],
            }
