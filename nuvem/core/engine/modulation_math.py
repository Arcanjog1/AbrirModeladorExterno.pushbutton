# -*- coding: utf-8 -*-
"""Aritmetica pura de blocos/pilaretes/aberturas (catalogo, empacotamento,
solver de largura/eixo de abertura, feasibilidade por comprimento) extraida
verbatim de `core/wall_modeling.py` - continuacao mecanica, funcao por
funcao, da extracao fisica do motor de regras para `core/engine/` (ver
ARQUITETURA_INTERATIVA.md, secao "Extracao fisica do motor").

Nenhuma formula mudou. `wall_modeling.py` importa tudo daqui (`from
core.engine.modulation_math import *`, SEM fallback - mesma dependencia
obrigatoria de `core.engine.geometry`) para que todos os call-sites
existentes (por nome solto, dentro do mesmo modulo) continuem funcionando
sem nenhuma alteracao.

`__all__` inclui os nomes com underscore de proposito - `import *` os
ignoraria por padrao, e varias funcoes/constantes "privadas" daqui sao
usadas por nome solto de FORA deste arquivo, dentro de `wall_modeling.py`.

Modulo 100% PURO: nenhuma dependencia do Revit, nem mesmo dos tipos
XYZ/Line (ao contrario de `core/engine/geometry.py`) - so' numeros/tuplas/
dicts em centimetros. Roda em qualquer Python puro, sem `tests/
revit_stubs.py` e sem o pacote `Autodesk.Revit.DB` instalado.

`_wall_length_cm` (le' `wall.Location`, um objeto Revit de verdade)
NAO foi movida para ca' de proposito - continua em `wall_modeling.py`,
logo apos o ponto de onde este bloco saiu, exatamente para nao quebrar
a pureza deste modulo."""

FEET_PER_METER = None
try:
    from core.engine.tolerances import FEET_PER_METER
except Exception:
    FEET_PER_METER = 1.0 / 0.3048

__all__ = [
    "OPENING_VALID_LAST_DIGITS_CM", "PIER_AT_OPENING_TOLERANCE_M",
    "PIER_AT_OPENING_TOLERANCE_FT", "OPENING_SOLVER_MAX_WIDTH_DELTA_CM",
    "OPENING_SOLVER_MAX_AXIS_DELTA_CM", "BLOCK_LENGTHS_CM", "BLOCK_WIDTH_CM",
    "BLOCK_JOINT_CM", "BLOCK_OPENING_JOINT_CM", "PIER_MODULE_CM",
    "BLOCK_COMPENSATORS_ENABLED_BY_DEFAULT", "MODULATION_WHOLE_CM_TOLERANCE_CM",
    "PIER_LAYOUT_TOLERANCE_CM", "pack_pier_with_blocks",
    "_is_valid_opening_width_cm", "solve_opening_modulation",
    "PIER_BOUNDARY_JOINTS_CM", "PIER_BOUNDARY_JOINT_COMBINATIONS_CM",
    "_pier_remaining_cm", "pier_closes_with_blocks_cm",
    "wall_length_closes_with_blocks_cm", "_wall_length_snap_targets_cm",
    "nearest_block_lengths_cm", "nearest_wall_lengths_cm",
    "suggested_block_length_cm", "evaluate_wall_block_length",
    "_nearest_valid_lengths_cm", "_suggested_valid_length_cm",
    "_evaluate_modulation_length",
]

import math

# regra das ABERTURAS (largura do vao)
OPENING_VALID_LAST_DIGITS_CM = (1, 6, 9)

# Folga para decidir "a ponta desta parede esta' no vao desta abertura".
# Pequena de proposito: o script constroi o pilarete terminando EXATAMENTE
# na borda do vao, entao qualquer valor generoso aqui so' aumentaria a
# chance de classificar como pilarete uma parede que apenas passa perto.
PIER_AT_OPENING_TOLERANCE_M = 0.05
PIER_AT_OPENING_TOLERANCE_FT = PIER_AT_OPENING_TOLERANCE_M * FEET_PER_METER

# Limites de busca do solver de aberturas (ver solve_opening_modulation).
# Deliberadamente modestos: o objetivo e' ACERTAR A MODULACAO com o menor
# desvio possivel do projeto original, nao redesenhar a fachada. Uma
# abertura que so' fecharia mudando 30cm de largura deve ser reportada
# como "fora de escopo" para decisao humana, nao ajustada em silencio.
OPENING_SOLVER_MAX_WIDTH_DELTA_CM = 12
OPENING_SOLVER_MAX_AXIS_DELTA_CM = 12


# ==========================================
# BASE MATEMATICA DA MODULACAO POR BLOCOS
#
# Blocos disponiveis (comprimento em cm), largura 14cm, junta de
# assentamento de 1cm ENTRE blocos e ENTRE o bloco e a parede, e junta
# ZERO entre o bloco e a abertura.
#
# DE ONDE SAI A REGRA "PILARETE TERMINA EM 0 OU 5" (nao e' convencao, e'
# consequencia): somando cada bloco com a sua junta temos 39+1=40,
# 34+1=35, 19+1=20, 9+1=10 e 4+1=5 - TODOS multiplos de 5. Logo um
# pilarete montado como junta+bloco+junta+bloco+... vale exatamente a soma
# de (bloco+1), e portanto e' sempre multiplo de 5.
#
# Conferido contra o desenho de referencia do usuario: o pilarete de 55cm
# aparece cotado como 1 | 19 | 1 | 34, e 1+19+1+34 = 55 = (19+1)+(34+1).
#
# Verificado tambem que TODO multiplo de 5 e' construivel com estas cinco
# pecas (o bloco de 4cm fecha qualquer sobra de 5cm), ou seja: os blocos
# NAO impoem nenhuma restricao alem de "multiplo de 5" - o empacotamento
# vira um problema separado, sempre solucionavel.
# ==========================================

BLOCK_LENGTHS_CM = (39, 34, 19, 9, 4)
BLOCK_WIDTH_CM = 14
BLOCK_JOINT_CM = 1            # entre blocos e entre bloco e parede
BLOCK_OPENING_JOINT_CM = 0    # entre bloco e abertura
PIER_MODULE_CM = 5            # = mdc dos (bloco + junta)

# LIGADO POR DEFAULT (2026-08-21). Antes era False, e isso tornava a
# modulacao IMPOSSIVEL na pratica: sem C09/C04 as unicas pecas de
# preenchimento sao B39 e B19, cujos passos (bloco+junta) valem 40cm e 20cm
# - ou seja, so' fechariam pilaretes multiplos de 20cm. Medido na planta
# real do usuario: 493 trechos nao-modulares com os compensadores
# desligados contra 351 com eles ligados, e 7 paredes validas contra 37.
# Os compensadores continuam sendo ULTIMO recurso por construcao, nao por
# configuracao: `_pier_ordered_layout` e' guloso do MAIOR bloco que cabe,
# entao C09/C04 so' entram na sobra que nenhuma peca inteira preenche.
BLOCK_COMPENSATORS_ENABLED_BY_DEFAULT = True

# Quao perto de um numero INTEIRO de centimetros um comprimento/largura real
# precisa estar para contar como "e' um numero inteiro de cm". Absorve o
# ruido de geometria que vem do CAD + das conversoes pes<->cm - medido na
# planta real do usuario: uma borda de encontro sai em 829,99791cm em vez de
# 830cm. Um valor genuinamente fracionario (ex.: 155,5cm) fica MUITO acima
# disso e continua incompativel.
MODULATION_WHOLE_CM_TOLERANCE_CM = 0.05

# Quanto desse ruido o EMPACOTADOR de blocos absorve antes de declarar que
# um trecho "nao fecha" - a MESMA tolerancia, de proposito: quem pre-checa
# (pier_closes_with_blocks_cm) e quem monta de verdade (_pier_ordered_layout)
# nunca podem discordar sobre o que fecha. Antes disto o empacotador usava
# 1e-6 e reprovava por ruido 116 dos 344 trechos "nao-modulares" medidos.
PIER_LAYOUT_TOLERANCE_CM = MODULATION_WHOLE_CM_TOLERANCE_CM

# Tolerancia SEPARADA e bem mais apertada, usada SO' para decidir o realce
# VERMELHO ("comprimento quebrado" - ver evaluate_wall_block_length/
# is_clean_cm, core/wall_modeling.py FASE 2 do plano em
# C:\Users\CIVIX\.claude\plans\quiet-painting-petal.md). NAO reaproveita
# MODULATION_WHOLE_CM_TOLERANCE_CM (0.05cm) de proposito: aquela tolerancia
# foi calibrada para ABSORVER ruido geometrico (o exemplo dos 829,99791cm
# acima) e NUNCA bloquear uma parede por causa dele - mas o usuario pediu
# explicitamente para um residuo pequeno tipo 25,01cm (diferenca de so'
# 0,01cm de 25,00cm - MUITO menor que 0,05cm, ou seja, hoje passaria
# silenciosamente como "limpo") ser detectado e corrigido ANTES de
# modular, nao apenas arredondado por baixo do tapete. 0,005cm (0,05mm)
# fica confortavelmente ABAIXO do ruido geometrico real medido (0,00209cm)
# - nunca falso-positivo por ruido de ponto flutuante - e ACIMA de zero, ou
# seja, so' um comprimento genuinamente EXATO (dentro da precisao de
# calculo do Revit) conta como limpo.
BROKEN_LENGTH_RESIDUE_TOLERANCE_CM = 0.005


def pack_pier_with_blocks(pier_cm):
    """Decompoe um pilarete de `pier_cm` na lista de blocos que o compoe.

    Modelo (ver cabecalho da secao): pilarete = junta + b1 + junta + b2 +
    ... , com junta ZERO contra a abertura; equivale a somar (bloco+1) de
    cada peca. Resolve por programacao dinamica em unidades de 5cm,
    minimizando a QUANTIDADE de pecas - e' o que faz o resultado preferir
    blocos grandes (39/34) em vez de encher de blocos de 4cm.

    Devolve (lista_de_blocos_decrescente, sobra_cm). Sobra 0 significa
    modulacao perfeita; devolve (None, pier_cm) se `pier_cm` nao for
    multiplo de 5 (nao ha' composicao possivel)."""
    if pier_cm <= 0:
        return [], 0.0
    units = int(round(pier_cm / float(PIER_MODULE_CM)))
    if abs(pier_cm - units * PIER_MODULE_CM) > 1e-6:
        return None, pier_cm
    unit_of = [(b, (b + BLOCK_JOINT_CM) // PIER_MODULE_CM) for b in BLOCK_LENGTHS_CM]
    best = [None] * (units + 1)
    choice = [None] * (units + 1)
    best[0] = 0
    for u in range(1, units + 1):
        for block_cm, block_units in unit_of:
            if block_units > u or best[u - block_units] is None:
                continue
            candidate = best[u - block_units] + 1
            if best[u] is None or candidate < best[u]:
                best[u] = candidate
                choice[u] = block_cm
    if best[units] is None:
        return None, pier_cm
    blocks = []
    u = units
    while u > 0:
        block_cm = choice[u]
        blocks.append(block_cm)
        u -= (block_cm + BLOCK_JOINT_CM) // PIER_MODULE_CM
    blocks.sort(reverse=True)
    return blocks, 0.0


def _is_valid_opening_width_cm(width_cm):
    """True se `width_cm` atende a regra de modulacao das ABERTURAS
    (terminar em 1, 6 ou 9 - ver OPENING_VALID_LAST_DIGITS_CM)."""
    rounded = int(round(width_cm))
    return rounded > 0 and (rounded % 10) in OPENING_VALID_LAST_DIGITS_CM


def solve_opening_modulation(axis_cm, width_cm, left_pier_cm,
                             max_width_delta_cm=OPENING_SOLVER_MAX_WIDTH_DELTA_CM,
                             max_axis_delta_cm=OPENING_SOLVER_MAX_AXIS_DELTA_CM,
                             allow_axis_change=True):
    """Melhor combinacao (largura da abertura, pilarete esquerdo, pilarete
    direito, comprimento do eixo) para UMA abertura num eixo de parede.

    Restricoes duras:
      - os dois pilaretes multiplos de 5 (unica forma de fechar em blocos);
      - largura da abertura terminando em 1, 6 ou 9.

    RESTRICAO MATEMATICA que decide se ha' solucao sem mover paredes: os
    pilaretes somam sempre (eixo - largura); para os dois serem multiplos
    de 5 e' preciso que (eixo - largura) tambem seja. Como largura
    terminada em 1/6/9 so' produz resto 1 ou 4 na divisao por 5, isso so'
    e' possivel quando o EIXO tem resto 1 ou 4 - ou seja, em 2 dos 5
    restos possiveis (~40% dos eixos). Por isso existe `allow_axis_change`:
    deixar o eixo crescer/encolher (na pratica, mover a parede
    perpendicular do encontro) leva a cobertura para ~100%.

    Custo, refletindo as prioridades pedidas: mexer na largura da abertura
    pesa 10 por cm, MOVER A PAREDE pesa 30 por cm (e' o mais invasivo, so'
    deve acontecer quando nao ha' alternativa) e deslocar a abertura ao
    longo do eixo pesa 1 por cm (e' o ajuste mais barato).

    Devolve um dict com o plano, ou None se nao houver solucao dentro dos
    limites."""
    axis0 = int(round(axis_cm))
    width0 = int(round(width_cm))
    left0 = int(round(left_pier_cm))

    best = None
    if allow_axis_change:
        axis_deltas = range(-max_axis_delta_cm, max_axis_delta_cm + 1)
    else:
        axis_deltas = [0]

    for axis_delta in axis_deltas:
        axis = axis0 + axis_delta
        if axis <= 0:
            continue
        for width_delta in range(-max_width_delta_cm, max_width_delta_cm + 1):
            width = width0 + width_delta
            if not _is_valid_opening_width_cm(width):
                continue
            remaining = axis - width
            if remaining < 0 or (remaining % PIER_MODULE_CM) != 0:
                continue
            # Pilarete esquerdo: os dois multiplos de 5 que cercam o valor
            # original (o direito sai por diferenca e ja' e' multiplo de 5).
            floor_left = max(0, (left0 // PIER_MODULE_CM) * PIER_MODULE_CM)
            for left in set([floor_left, floor_left + PIER_MODULE_CM]):
                right = remaining - left
                if left < 0 or right < 0:
                    continue
                shift = abs(left - left0)
                cost = abs(width_delta) * 10 + abs(axis_delta) * 30 + shift
                if best is None or cost < best[0]:
                    best = (cost, width, left, right, axis, width_delta, axis_delta, shift)

    if best is None:
        return None
    _cost, width, left, right, axis, width_delta, axis_delta, shift = best
    left_blocks, _ = pack_pier_with_blocks(left)
    right_blocks, _ = pack_pier_with_blocks(right)
    return {
        "width_cm": width,
        "left_cm": left,
        "right_cm": right,
        "axis_cm": axis,
        "width_delta_cm": width_delta,
        "axis_delta_cm": axis_delta,
        "shift_cm": shift,
        "left_blocks": left_blocks or [],
        "right_blocks": right_blocks or [],
        "moved_wall": axis_delta != 0,
        "changed": bool(width_delta or axis_delta or shift),
    }

# MODULATION_WHOLE_CM_TOLERANCE_CM / PIER_LAYOUT_TOLERANCE_CM sao
# definidas mais acima, junto da base matematica dos blocos (precisam
# existir antes do primeiro uso como valor default de parametro).


# ---- FEASIBILIDADE REAL DE UM TRECHO, PELOS BLOCOS (nao por digito) -----
#
# Estas funcoes sao o que SUBSTITUIU a regra de digito final das paredes
# (ver o bloco de comentarios "REGRA DE DIGITO FINAL DAS PAREDES - REMOVIDA
# COMPLETAMENTE" em wall_modeling.py). Sao uma PRE-CHECAGEM barata, com a
# MESMA conta de `_pier_ordered_layout`; a palavra final continua sendo o
# solver de blocos rodado de verdade parede por parede
# (process_walls_one_by_one).

# Juntas de contorno possiveis de um trecho: BLOCK_JOINT_CM quando ele
# encosta em outro bloco/num bloco de encontro, BLOCK_OPENING_JOINT_CM (0)
# quando encosta numa abertura ou numa ponta livre de parede.
PIER_BOUNDARY_JOINTS_CM = (BLOCK_JOINT_CM, BLOCK_OPENING_JOINT_CM)
PIER_BOUNDARY_JOINT_COMBINATIONS_CM = tuple(
    (lead, trail)
    for lead in PIER_BOUNDARY_JOINTS_CM
    for trail in PIER_BOUNDARY_JOINTS_CM
)


def _pier_remaining_cm(pier_cm, leading_joint_cm, trailing_joint_cm):
    """Quanto sobra de `pier_cm` para (bloco + junta de saida) depois de
    descontadas as juntas de CONTORNO - exatamente a conta que
    `_pier_ordered_layout` faz antes de decidir se o trecho fecha. Mantida
    numa funcao unica de proposito para que a pre-checagem e o solver real
    nunca possam divergir."""
    return pier_cm - leading_joint_cm - trailing_joint_cm + BLOCK_JOINT_CM


def pier_closes_with_blocks_cm(pier_cm, leading_joint_cm=BLOCK_JOINT_CM,
                               trailing_joint_cm=BLOCK_OPENING_JOINT_CM,
                               tolerance_cm=MODULATION_WHOLE_CM_TOLERANCE_CM):
    """True se um trecho de `pier_cm` fecha EXATAMENTE com blocos, dadas as
    juntas de contorno REAIS daquele trecho. Nao olha digito nenhum: o que
    vale e' `(trecho - juntas + BLOCK_JOINT_CM)` ser um multiplo nao
    negativo de PIER_MODULE_CM.

    E' um limite SUPERIOR (necessario, nao suficiente): assume o catalogo
    padrao completo, onde qualquer multiplo de 5 e' construivel. Com o
    catalogo reduzido (sem compensadores) o solver real pode ainda assim
    nao fechar - por isso ninguem decide "parede errada" so' com isto."""
    remaining = _pier_remaining_cm(pier_cm, leading_joint_cm, trailing_joint_cm)
    if remaining < -tolerance_cm:
        return False
    if abs(remaining) <= tolerance_cm:
        return True  # trecho vazio (so' as juntas) - nada a preencher
    units = remaining / float(PIER_MODULE_CM)
    return abs(units - round(units)) <= tolerance_cm / float(PIER_MODULE_CM)


def wall_length_closes_with_blocks_cm(length_cm,
                                      tolerance_cm=MODULATION_WHOLE_CM_TOLERANCE_CM):
    """True se EXISTE alguma combinacao de juntas de contorno
    (parede/parede, parede/abertura, abertura/abertura) para a qual
    `length_cm` fecha em blocos. Usada onde so' se conhece o comprimento da
    parede, sem o contexto de encontros/aberturas (ex.: o validador ao
    vivo) - deliberadamente PERMISSIVA, para nunca reprovar por antecipacao
    uma parede que o solver de verdade conseguiria montar."""
    for lead, trail in PIER_BOUNDARY_JOINT_COMBINATIONS_CM:
        if pier_closes_with_blocks_cm(length_cm, lead, trail, tolerance_cm):
            return True
    return False


def _wall_length_snap_targets_cm(current_len_cm, max_delta_cm):
    """Comprimentos-alvo INTEIROS (cm) que passam no pre-filtro aritmetico
    `wall_length_closes_with_blocks_cm`, a no maximo `max_delta_cm` do
    comprimento atual, ordenados pelo MENOR |delta| e, no empate,
    ENCURTAR antes de ALONGAR (regra do usuario, 2026-08-25).

    Devolve [(target_cm, delta_cm), ...]; `delta_cm` e' FRACIONARIO.

    ---------------------------------------------------------------
    POR QUE ESTA FUNCAO EXISTE (bug real, medido em 2026-08-25)
    ---------------------------------------------------------------
    Comprimento que fecha em blocos e' SEMPRE inteiro (medido: 192
    valores validos entre 80 e 400cm, ZERO com parte fracionaria - ver
    `pier_closes_with_blocks_cm`, cuja conta so' fecha em multiplos de
    PIER_MODULE_CM deslocados pelas juntas de contorno, todas inteiras).

    Mas TODOS os mecanismos de ajuste iteravam deltas INTEIROS
    (`range(1, N)`): somar um inteiro a um comprimento FRACIONARIO
    preserva a fracao, entao nenhum deles jamais alcancava um
    comprimento valido. O caso literal reportado pelo usuario:

        89.5 +1 = 90.5 -> False     89.5 -1 = 88.5 -> False
        89.5 +2 = 91.5 -> False     89.5 -2 = 87.5 -> False
        ... os 10 deltas testados -> False

    Em 4000 comprimentos aleatorios que falham a modulacao, 3601 (96%)
    eram IMPOSSIVEIS de corrigir por delta inteiro. Era essa a razao de
    o ajuste automatico "nunca acontecer" na planta real.

    Aqui o delta e' derivado do ALVO (89.5 -> 89 e' delta -0.5), nunca o
    contrario - e' o que torna a correcao alcancavel.

    Os alvos sao INTEIROS de proposito: a revalidacao pos-aplicacao
    (`evaluate_wall_block_length`, via fix_all_wall_modulation_errors)
    exige `is_whole_cm`, entao um alvo fracionario seria revertido logo
    em seguida.

    `wall_length_closes_with_blocks_cm` e' um limite SUPERIOR (necessario,
    nao suficiente - ver o docstring dela): serve so' como pre-filtro
    barato para nao gastar orcamento de verificacao com alvos sem chance.
    O veredito continua sendo o solver de blocos de verdade."""
    targets = []
    if max_delta_cm <= 0:
        return targets
    lowest = int(math.ceil(current_len_cm - max_delta_cm))
    highest = int(math.floor(current_len_cm + max_delta_cm))
    for target_cm in range(lowest, highest + 1):
        if target_cm < 1:
            continue
        delta_cm = target_cm - current_len_cm
        if abs(delta_cm) <= MODULATION_WHOLE_CM_TOLERANCE_CM:
            continue  # ja' esta' (praticamente) neste comprimento
        if abs(delta_cm) > max_delta_cm + 1e-9:
            continue
        if not wall_length_closes_with_blocks_cm(float(target_cm)):
            continue
        targets.append((float(target_cm), delta_cm))
    # menor alteracao primeiro; no empate, ENCURTAR (delta < 0) antes de
    # ALONGAR - `delta_cm > 0` vira False/True, e False ordena primeiro.
    targets.sort(key=lambda item: (round(abs(item[1]), 6), item[1] > 0))
    return targets


def nearest_block_lengths_cm(length_cm, leading_joint_cm=BLOCK_JOINT_CM,
                             trailing_joint_cm=BLOCK_OPENING_JOINT_CM):
    """(maior valido <= , menor valido >=) para um trecho com ESTAS juntas
    de contorno. Substitui `_nearest_valid_lengths_cm` no lado das paredes:
    em vez de varrer digitos, resolve direto pela aritmetica dos blocos
    (validos = base + m * PIER_MODULE_CM, com base = juntas - BLOCK_JOINT_CM
    e m >= 0)."""
    base = leading_joint_cm + trailing_joint_cm - BLOCK_JOINT_CM
    rounded = int(round(length_cm))
    delta = rounded - base
    if delta <= 0:
        return (base, base)
    remainder = delta % PIER_MODULE_CM
    if remainder == 0:
        return (rounded, rounded)
    return (rounded - remainder, rounded - remainder + PIER_MODULE_CM)


def nearest_wall_lengths_cm(length_cm):
    """Mesma ideia de `nearest_block_lengths_cm`, mas sem conhecer as
    juntas: pega o valido mais PROXIMO por baixo e por cima entre TODAS as
    combinacoes de junta. So' informativo (sugestao mostrada ao usuario) -
    nao e' criterio de aprovacao de nada."""
    lowers, uppers = [], []
    for lead, trail in PIER_BOUNDARY_JOINT_COMBINATIONS_CM:
        lower, upper = nearest_block_lengths_cm(length_cm, lead, trail)
        lowers.append(lower)
        uppers.append(upper)
    return (max(lowers), min(uppers))


def suggested_block_length_cm(length_cm):
    """Sugestao UNICA (o valido mais proximo em valor absoluto; empate a
    favor do maior) a partir de `nearest_wall_lengths_cm`."""
    lower, upper = nearest_wall_lengths_cm(length_cm)
    if lower == upper:
        return lower
    return lower if abs(length_cm - lower) < abs(length_cm - upper) else upper


def evaluate_wall_block_length(length_cm):
    """Dict no MESMO formato do antigo `_evaluate_modulation_length`, mas
    julgando por blocos reais em vez de digito final. `compatible` exige
    (a) o comprimento ser um numero inteiro de cm dentro de
    MODULATION_WHOLE_CM_TOLERANCE_CM e (b) existir alguma combinacao de
    juntas de contorno que feche em blocos.

    `is_clean_cm` e' um campo SEPARADO de `is_whole_cm` (ver
    BROKEN_LENGTH_RESIDUE_TOLERANCE_CM) - propositalmente MAIS APERTADO,
    para o realce VERMELHO de "comprimento quebrado" (core/wall_modeling.py,
    FASE 2). Um comprimento pode ser `is_whole_cm=True` (dentro da
    tolerancia LARGA que a aritmetica de modulacao usa, 0,05cm - logo
    tambem pode ser `compatible=True`) e ainda assim `is_clean_cm=False`
    (residuo pequeno tipo 25,01cm que o usuario quer ver sinalizado e
    corrigido, mesmo que a modulacao em si "deixasse passar"). Por
    construcao, `is_clean_cm=True` implica `is_whole_cm=True` (a tolerancia
    apertada e' um subconjunto da larga), nunca o contrario."""
    length_cm_rounded = int(round(length_cm))
    residue_cm = abs(length_cm - length_cm_rounded)
    is_whole_cm = residue_cm <= MODULATION_WHOLE_CM_TOLERANCE_CM
    is_clean_cm = residue_cm <= BROKEN_LENGTH_RESIDUE_TOLERANCE_CM
    return {
        "length_cm": length_cm,
        "length_cm_rounded": length_cm_rounded,
        "is_whole_cm": is_whole_cm,
        "is_clean_cm": is_clean_cm,
        "compatible": is_whole_cm and wall_length_closes_with_blocks_cm(length_cm),
        "nearest_valid_cm": nearest_wall_lengths_cm(length_cm),
        "suggested_cm": suggested_block_length_cm(length_cm),
    }


def _nearest_valid_lengths_cm(length_cm_rounded, valid_digits):
    """(menor_valido, maior_valido): o maior valor valido <= e o menor
    valor valido >= `length_cm_rounded` (um INTEIRO), terminando num digito
    de `valid_digits`. Se o proprio valor ja for valido, devolve
    (length_cm_rounded, length_cm_rounded). Hoje SO' as ABERTURAS
    (OPENING_VALID_LAST_DIGITS_CM) usam esta varredura por digito - as
    PAREDES passaram a ser julgadas pela aritmetica real dos blocos
    (`nearest_block_lengths_cm`), ver a nota da regra removida."""
    if (length_cm_rounded % 10) in valid_digits:
        return (length_cm_rounded, length_cm_rounded)
    lower = length_cm_rounded
    while (lower % 10) not in valid_digits:
        lower -= 1
    upper = length_cm_rounded
    while (upper % 10) not in valid_digits:
        upper += 1
    return (lower, upper)


def _suggested_valid_length_cm(length_cm, valid_digits):
    """Sugestao UNICA de correcao: o valor inteiro valido MAIS PROXIMO do
    comprimento/largura REAL (nao arredondado) por distancia absoluta - ex.:
    155,5cm -> 156 (0,5cm de distancia), nao 151 (4,5cm de distancia), mesmo
    os dois sendo "os valores validos mais proximos" no sentido de
    menor/maior. Empate exato (a meio caminho entre dois validos) e'
    resolvido a favor do valor MAIOR, por uma regra simples e previsivel."""
    lower, upper = _nearest_valid_lengths_cm(int(round(length_cm)), valid_digits)
    if lower == upper:
        return lower
    dist_lower = abs(length_cm - lower)
    dist_upper = abs(length_cm - upper)
    if dist_lower < dist_upper:
        return lower
    return upper


def _evaluate_modulation_length(length_cm, valid_digits):
    """Nucleo da regra por DIGITO - hoje usada SO' por
    evaluate_opening_modulation (largura de abertura). As PAREDES nao
    passam mais por aqui: elas usam `evaluate_wall_block_length`, que julga
    pela aritmetica real dos blocos. `compatible` exige tanto (a) o valor
    ser, dentro de MODULATION_WHOLE_CM_TOLERANCE_CM, um numero INTEIRO de
    centimetros, quanto (b) esse inteiro terminar num digito de
    `valid_digits`."""
    length_cm_rounded = int(round(length_cm))
    is_whole_cm = abs(length_cm - length_cm_rounded) <= MODULATION_WHOLE_CM_TOLERANCE_CM
    compatible = is_whole_cm and (length_cm_rounded % 10) in valid_digits
    return {
        "length_cm": length_cm,
        "length_cm_rounded": length_cm_rounded,
        "is_whole_cm": is_whole_cm,
        "compatible": compatible,
        "nearest_valid_cm": _nearest_valid_lengths_cm(length_cm_rounded, valid_digits),
        "suggested_cm": _suggested_valid_length_cm(length_cm, valid_digits),
    }
