# -*- coding: utf-8 -*-
"""Despacho de eventos de progresso usados pela janela WinForms (Tela 1 -
ver `core/wall_modeling.py`, `_WallReviewForm`/`_ProgressConsole`).

Modulo PURO: sem import de Revit, sem import de UI - `_dispatch_progress_event`
so' chama metodos (`log`/`set_progress`) num objeto `console` recebido por
parametro (duck typing), nunca importa `System.Windows.Forms` nem qualquer
tipo do WinForms. Isso permite testar o CONTRATO de despacho (quais formas de
chamada existem e o que cada uma deve disparar) sem Revit/WinForms - ver
`tests/test_progress.py`.
"""


def dispatch_progress_event(console, *args):
    """UNICA forma correta de consumir um `progress_cb(...)` deste projeto -
    existe porque um closure antigo (`_progress_cb` de
    `_WallReviewForm._on_start_click`, em `core/wall_modeling.py`) so'
    tratava chamadas de 2 argumentos (`done, total`) e DESCARTAVA EM
    SILENCIO as chamadas de 1 argumento (mensagem de status pronta - ver
    `find_wall_group_shift_fixes`, `plan_axis_opening_fix`) e de 4
    argumentos (`tentativa, total, wall_idx, tipo` - ETAPA 3C). Como
    `Application.DoEvents()` so' roda de dentro dos metodos de
    `_ProgressConsole` (log/set_status/set_progress), esse descarte
    silencioso parava de bombear a fila de mensagens do Windows durante a
    ETAPA 3C inteira - a CAUSA REAL de um travamento ("Nao esta
    respondendo") reportado em producao, mesmo sem nenhum loop infinito de
    verdade no motor (ver FASE 1 do plano em
    C:\\Users\\CIVIX\\.claude\\plans\\quiet-painting-petal.md). QUALQUER
    callback `progress_cb` novo deste projeto deve passar por aqui - nunca
    reintroduzir um `if len(cb_args) == N` isolado.

    Formas aceitas, na ordem em que sao checadas:
    - `(mensagem,)` -> `console.log(mensagem)` (status pronto, ETAPA 3B/3C).
    - `(done, total)` -> `console.set_progress(done, total, "<done>/<total>
      parede(s) processada(s)")` (granularidade ~10% de
      `process_walls_one_by_one`).
    - `(tentativa, total_tentativas, wall_idx, tipo)` -> `console.log(...)`
      com a fase "TENTAR CORRIGIR" e o detalhe da tentativa, mais
      `console.set_progress(...)` com o mesmo par tentativa/total (ETAPA
      3C, ver `find_wall_group_shift_fixes`).
    Qualquer outra forma e' ignorada (nunca lanca) - mesma postura
    defensiva do closure antigo, so' que agora cobrindo TODAS as formas
    realmente chamadas em vez de so' uma.

    Nunca deixa uma excecao escapar (mesmo cuidado do `_ProgressConsole`
    original - uma falha de log nunca pode derrubar o solver)."""
    try:
        if len(args) == 1:
            console.log(args[0])
        elif len(args) == 2:
            done, total = args
            console.set_progress(done, total, "{}/{} parede(s) processada(s)".format(done, total))
        elif len(args) == 4:
            attempt, total_attempts, wall_idx, tipo = args
            console.log(
                "TENTAR CORRIGIR: parede {} - tentativa {}/{} ({})...".format(
                    wall_idx, attempt, total_attempts, tipo
                )
            )
            console.set_progress(
                attempt, total_attempts,
                "ETAPA 3C: tentativa {}/{} (parede {}, {})".format(
                    attempt, total_attempts, wall_idx, tipo
                ),
            )
    except Exception:
        pass
