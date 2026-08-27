# -*- coding: utf-8 -*-
"""Validacao de sanidade do resultado do pareamento, ANTES do usuario
confiar nos numeros de modulacao de blocos - pedido explicito (2026-08-26):
"Se houver divergencias importantes, pare antes da modulacao e mostre o
diagnostico. Nao quero novamente centenas de blocos sendo colocados em uma
geometria que ja estava errada desde a leitura do DXF."

Nao impede o calculo de rodar (a UI ainda mostra os blocos - o usuario pode
preferir ver mesmo assim), mas devolve um alerta destacado e explicito
sempre que o resultado tem cara de estar errado desde a interpretacao da
planta, com as causas mais provaveis."""

# Acima desta fracao de paredes "face unica" (sem par valido), o resultado
# e' considerado pouco confiavel - nao e' um limiar cientifico, so' o
# suficiente para distinguir "algumas paredes isoladas de verdade" (normal)
# de "quase nada pareou" (sinal de escala/layer/espessura errada).
SINGLE_LINE_RATIO_WARNING = 0.5


def validate_walls(walls, diagnostics):
    """Devolve {"ok": bool, "issues": [str, ...], "single_line_ratio": float}.

    `ok=False` significa que ha' pelo menos um sinal forte de que a
    interpretacao da planta (nao so' a modulacao) pode estar errada - a UI
    deve destacar isso ANTES dos resultados de modulacao."""
    total = len(walls)
    single_line_count = sum(1 for w in walls if w["single_line"])
    single_line_ratio = (single_line_count / total) if total else 0.0

    issues = []

    if total == 0:
        issues.append(
            "Nenhuma parede foi identificada nesta layer - confira se a layer "
            "escolhida e' mesmo a das paredes, e se a unidade/escala do desenho "
            "esta' correta."
        )
    elif single_line_ratio > SINGLE_LINE_RATIO_WARNING:
        issues.append(
            "{:.0f}% das paredes ficaram sem par (face unica) - resultado pouco "
            "confiavel. Causas mais comuns: unidade/escala do DXF incorreta "
            "(confira o seletor 'Unidade/escala do desenho'), layer errada, ou "
            "nenhuma espessura escolhida bate com as paredes reais.".format(
                single_line_ratio * 100.0
            )
        )

    if diagnostics.get("possible_bonecas"):
        issues.append(
            "{} par(es) de linha parecem parede/boneca legitima, mas com espessura "
            "fora das detectadas automaticamente - a modulacao pode estar "
            "incompleta ate' essa espessura ser adicionada.".format(
                len(diagnostics["possible_bonecas"])
            )
        )

    return {
        "ok": not issues,
        "issues": issues,
        "single_line_ratio": round(single_line_ratio, 3),
    }
