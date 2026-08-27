# -*- coding: utf-8 -*-
"""Gera paredes 3D no Revit a partir de duas linhas paralelas de um CAD 2D.

Fluxo:
    1. Usuario seleciona o CAD (importado ou vinculado) no modelo.
    2. Usuario escolhe o Layer onde as paredes estao desenhadas.
    2b. Usuario indica quais familias (tipicamente de Mobiliario) sao as
       PORTAS e JANELAS - selecionando-as no modelo ou deixando o script
       varrer o projeto pelos parametros de abertura. Essa informacao e
       indispensavel: essas aberturas costumam NAO estar desenhadas no
       DWG, entao somente o modelo do Revit sabe onde a parede deve
       continuar (verga acima / peitoril abaixo) em vez de terminar.
    3. Usuario escolhe quais espessuras de parede deseja modelar (uma ou
       mais, dentre candidatas detectadas automaticamente e/ou digitadas),
       o Nivel de insercao e a altura das paredes.
    4. O script reconstroi fragmentos colineares de linha (faces de parede
       que o CAD desenhou quebradas nos pontos onde outra parede cruza, OU
       onde ha' o vao real de uma porta/janela ja' inserida no projeto) na
       linha continua original - a religacao pelo vao de uma abertura usa
       uma tolerancia de colinearidade DELIBERADAMENTE mais generosa que a
       do resto do agrupamento (ver OPENING_BRIDGE_TOLERANCE_M), porque na
       pratica as duas jambas ao redor de uma porta/janela raramente ficam
       desenhadas perfeitamente alinhadas - sem essa folga extra, nenhum
       eixo de parede chegava a passar pelo vao, e nem a "boneca" ao lado
       nem a parede acima da verga eram criadas - agrupa as linhas paralelas do Layer aos
       pares CUJA distancia bata com uma das espessuras escolhidas E cuja
       sobreposicao mutua cubra a MAIOR PARTE do comprimento da menor das
       duas (nao um piso fixo em cm - ver MIN_WALL_SEGMENT_OVERLAP_RATIO -
       para reconhecer igualmente bem uma parede de varios metros ou uma
       "boneca" curta de poucos cm ao lado de uma porta/janela), calcula o
       eixo central EXATO de cada par (bissetriz entre as duas linhas,
       ancorada no ponto de intersecao delas quando ha' algum desvio
       angular - ver create_centerline) cobrindo a uniao (limitada) do
       alcance das duas linhas pareadas, remove paredes duplicadas/
       sobrepostas, LIMITA cada parede as linhas de FECHAMENTO (testas)
       transversais do proprio Layer - o fim fisico da parede, que tem
       prioridade sobre qualquer prolongamento das faces, exceto quando
       caem dentro do vao de uma abertura (ali sao jambas, e a parede
       continua) - estica as pontas NAO travadas de cada parede ate
       qualquer parede perpendicular com que se encontre (fechando
       encontros em T/L sem frestas), associa cada porta/janela do projeto
       a NO MAXIMO uma parede (a mais proxima - ver assign_openings_to_walls)
       para que o trecho de parede acima/ao redor dela fique restrito
       exatamente a largura do vao, valida o resultado contra os limites da
       planta, e cria as paredes correspondentes - fixando a Linha de
       Referencia no NUCLEO estrutural (largura do nucleo INTEIRO, nao so'
       da camada de funcao Estrutura - ver apply_structural_thickness) para
       evitar deslocamento lateral por causa de camadas de acabamento
       assimetricas ou de outras camadas dentro do nucleo - gerando/
       reaproveitando um WallType com a espessura EXATA escolhida pelo
       usuario. Uma etapa final de validacao geometrica (autoverificacoes
       deterministicas, sem depender do Revit) confere deslocamento de
       eixo, bonecas possivelmente ignoradas, vaos recortados fora da
       largura certa e duplicatas residuais, reportando tudo no resumo
       final.
    5. Ja' com as paredes criadas, a MODULACAO DE BLOCOS ESTRUTURAIS e' o
       proximo passo - e ele acontece PAREDE POR PAREDE, com o lancamento
       dos blocos e o eventual ajuste da parede na MESMA passada
       (process_walls_one_by_one): analisa encontros/aberturas/extremidades,
       escolhe a combinacao de blocos, lanca, verifica, ajusta se preciso,
       recalcula, valida - e so' entao vai para a proxima parede. A ordem e'
       geometrica e obrigatoria: primeiro TODAS as horizontais (de cima para
       baixo; da esquerda para a direita dentro de cada nivel), depois TODAS
       as verticais (da esquerda para a direita; de baixo para cima dentro
       de cada alinhamento) - ver order_walls_for_processing.

       NAO EXISTE MAIS nenhuma regra de digito final para paredes (a antiga
       "terminar em 0/5", ou em 0, 1, 6 ou 9cm, foi removida por completo -
       ver a nota "REGRA DE DIGITO FINAL DAS PAREDES"). Uma parede so' e'
       julgada pela aritmetica REAL dos blocos + juntas do trecho, e a
       palavra final e' sempre o solver de blocos rodando de verdade: uma
       parede de 111cm ou 129cm e' perfeitamente valida. A largura das
       aberturas (`Largura_abertura`) continua com a sua propria regra
       (terminar em 1, 6 ou 9cm - ver evaluate_opening_modulation).

       Quando o solver nao fecha, uma correcao e' OFERECIDA tentando NESTA
       ORDEM (a menor mudanca primeiro): deslocar a(s) abertura(s) ao longo
       do eixo; ENCURTAR a parede por uma ponta livre; aumentar a largura de
       uma abertura (nunca diminuir). AUMENTAR A PAREDE E' PROIBIDO em
       qualquer hipotese - assim como prolongar uma extremidade ou criar
       "dentes" - ver plan_axis_opening_fix/validate_wall_modulation.

Sobreposicao entre paredes e' permitida e esperada nos encontros em T, L,
Cruz (+) ou qualquer outra configuracao - inclusive incentivada nas pontas
(ver extend_wall_ends_to_junctions), para que o encontro fique
completamente fechado. O script NAO corta, apara nem divide paredes para
eliminar essa sobreposicao; a prioridade e' sempre preservar exatamente a
geometria e o comprimento calculados a partir do CAD - o auto-join do
Revit tambem e' desativado em cada parede criada para que ele nao altere
as extremidades automaticamente.

Toda a geometria e' tratada por vetores (direcao/perpendicular calculadas a
partir das proprias linhas, nunca por eixo X/Y fixo) - paredes horizontais
e verticais (ou em qualquer outro angulo) passam exatamente pelo mesmo
codigo, sem tratamento especial para nenhuma orientacao.

O resultado aparece numa unica janela MODELESS (ver _PostCreationForm),
SEM abas, com a trilha completa: Analisar Paredes (automatico, ja' pronto
ao abrir) -> Erros encontrados (lista clicavel - clicar numa parede da'
zoom nela no Revit) -> "Ajustar Erros" (corrige parede+abertura juntas,
ver ETAPA 3B) -> "Lancar Blocos" (calcula e cria os blocos estruturais,
ver ETAPA 4/5) -> "Finalizar/Deletar Paredes" (apaga as paredes de
referencia, com 1 confirmacao). Cartoes com os numeros da execucao no
topo e o log completo (o mesmo texto de sempre, linha por linha, tambem
salvo em arquivo) no rodape.

O comportamento do script e' testavel FORA do Revit: `tests/run_tests.py`
carrega este arquivo com a API do Revit/WinForms substituida por dubles
(geometria de verdade, janelas falsas) e exercita deteccao de paredes,
grafo de encontros, solver de blocos, regras de modulacao e a montagem
das janelas. Ver `tests/README.md`.
"""

import os
import math
import traceback
import time
import tempfile
import itertools
import uuid
from datetime import datetime

from pyrevit import revit, forms, script
from Autodesk.Revit.UI.Selection import ObjectType
from Autodesk.Revit.UI import ExternalEvent, IExternalEventHandler
from Autodesk.Revit.DB import (
    Options, Line, PolyLine, GeometryInstance, GraphicsStyle, XYZ, ElementId,
    FilteredElementCollector, Level, Wall, WallType, WallKind, WallUtils,
    WallLocationLine, Transaction, BuiltInParameter, MaterialFunctionAssignment,
    FamilyInstance, LocationPoint, LocationCurve, CompoundStructure,
    Curve, Solid, ViewDetailLevel, OverrideGraphicSettings, FillPatternElement,
    # `Color` do Revit importado com APELIDO de proposito: a secao de
    # interface, mais abaixo, importa System.Drawing.Color com o mesmo nome
    # `Color` no MESMO escopo de modulo. Como o corpo de uma funcao resolve
    # os globais na HORA DA CHAMADA, o `Color` visto por estas funcoes era o
    # do WinForms - que nao tem construtor (r, g, b) - e TODA aplicacao de
    # realce azul/vermelho falhava (silenciosamente, porque as chamadas sao
    # protegidas por try/except e so' acrescentavam uma linha em `failures`).
    Color as RevitColor, IUpdater, UpdaterId, UpdaterRegistry, ChangePriority,
    SubTransaction,
    Element, ElementTransformUtils, ElementClassFilter, FamilySymbol, PlanarFace,
    StorageType, Transform, TransactionGroup, BuiltInCategory, Plane
)
# StructuralType mora em Autodesk.Revit.DB.Structure, NAO em Autodesk.Revit.DB
# (import direto de Autodesk.Revit.DB falha com ImportException em tempo de
# carregamento do modulo - confirmado ao rodar no Revit real).
from Autodesk.Revit.DB.Structure import StructuralType
from System import Guid
from System.Collections.Generic import List

# Alias fixo para Autodesk.Revit.DB.Color, mantido pelo mesmo motivo que o
# import acima ja' usa `Color as RevitColor` (ver comentario no import): a
# secao de interface, mais abaixo, importa System.Drawing.Color com o
# MESMO nome `Color` no MESMO escopo de modulo, e System.Drawing.Color nao
# tem construtor publico (r,g,b), so' Color.FromArgb - qualquer
# `Color(r, g, b)` chamado depois daquele import pegaria o tipo errado.
# `_REVIT_DB_COLOR` e' mantido como segundo nome do MESMO `RevitColor` (em
# vez de trocar todos os usos existentes) para nao duplicar a correcao -
# codigo novo pode usar qualquer um dos dois nomes, nunca o nome solto
# `Color`.
_REVIT_DB_COLOR = RevitColor

doc = revit.doc
uidoc = revit.uidoc

# Janelas de sugestao MODELESS (ver _SuggestionsForm/_SummaryForm, secao
# JANELAS MODELESS mais abaixo) precisam ser mantidas vivas por uma
# referencia FORA de main() - main() retorna assim que a janela e' aberta
# (para nao bloquear o Revit), e sem isso o coletor de lixo do IronPython
# derrubaria a janela (e o ExternalEvent associado) assim que main()
# terminasse. Cada entrada e' uma tupla (form, external_event_ou_None,
# handler_ou_None), removida no evento FormClosed da propria janela.
_ACTIVE_MODELESS_WINDOWS = []

# Cache do ULTIMO solve_result/create_result bem-sucedido, por assinatura
# do conjunto de paredes (pedido explicito do usuario, 2026-08-27: fechar
# a janela de "Lancar Blocos" ANTES de clicar em "criar" nao pode obrigar
# a recalcular o solver do zero). Sobrevive por toda a sessao do Revit
# (modulo Python fica carregado entre cliques do botao dentro da mesma
# sessao do pyRevit) - nao e' persistido em disco/ExtensibleStorage
# porque o catalogo/FamilySymbol dentro de solve_result/create_result sao
# referencias REAIS da API do Revit, validas so' dentro desta sessao. So'
# tem efeito pratico no fluxo "utilizar paredes existentes"
# (run_modulation_on_existing_walls): la' o mesmo conjunto de ElementId
# pode ser re-selecionado numa nova execucao do script; no fluxo classico
# (main(), CAD) cada execucao cria Wall NOVAS (Id diferente a cada vez),
# entao a assinatura nunca bate de proposito - nunca reusa um resultado de
# um conjunto de paredes diferente por engano.
_LAST_MODULATION_STATE = {}


def _eid_int(eid):
    """ElementId -> int, compativel com Revit < 2024 (.IntegerValue) e >= 2024 (.Value).
    O atributo IntegerValue foi removido no Revit 2024; Value e' o substituto."""
    try:
        return eid.IntegerValue
    except AttributeError:
        return int(eid.Value)


def _wall_ids_signature(wall_ids):
    """Assinatura estavel (tupla ordenada de id numerico) de um conjunto
    de ElementId - chave de _LAST_MODULATION_STATE. Devolve None (nunca
    bate com nenhuma chave real) se `wall_ids` for vazio/invalido."""
    try:
        ids = tuple(sorted(_eid_int(eid) for eid in (wall_ids or [])))
    except Exception:
        return None
    return ids or None

# --------------------------------------------------------------------
# UI INTERATIVA: PySide6 foi removido (pedido do usuario, 2026-08-26) - a
# instalacao extra do PySide6 no CPython embutido do pyRevit era a maior
# causa da demora/erros ao abrir o botao (import pesado do Qt, criacao de
# QApplication, download de mais um sub-pacote inteiro pelo loader). O
# fluxo agora e' sempre o WinForms de sempre (ver `ask_setup`/`_SetupForm`
# e a janela de resultado mais abaixo), ja' com um layout modernizado
# (cores/tipografia/cartoes - ver UI_BG/UI_PANEL/_style_primary_button
# etc.), sem nenhuma dependencia binaria extra para instalar.
INTERACTIVE_MODULATION_UI = False
_interactive_modulation_available = False

# Garante que a pasta do botao (pai de `core/`) esteja em sys.path, para os
# `from core.engine.xxx import yyy` logo abaixo (e o `import core.xxx` que o
# loader tambem faz, ver Script.py) resolverem tanto rodando dentro do
# Revit/pyRevit quanto nos testes automatizados (ver tests/load_script.py,
# que exec() este arquivo sem preparar sys.path sozinho).
try:
    import sys as _sys
    _pkg_root = os.path.dirname(os.path.abspath(__file__))
    _button_root = os.path.dirname(_pkg_root)
    if _button_root not in _sys.path:
        _sys.path.insert(0, _button_root)
except Exception:
    pass

# Tolerancia de espessura de parede aceita (metros)
MIN_WALL_THICKNESS_M = 0.05
MAX_WALL_THICKNESS_M = 0.35

# FEET_PER_METER e as tolerancias geometricas abaixo usadas por
# core/engine/geometry.py (COLLINEAR_MATCH_TOLERANCE_*,
# MIN_WALL_SEGMENT_OVERLAP_RATIO, MIN_WALL_SEGMENT_ABS_FLOOR_*,
# OPENING_BRIDGE_TOLERANCE_*) moraram AQUI ate' esta extracao - ver
# core/engine/tolerances.py para o valor + comentario original de cada
# uma (nao mudou nenhum numero, so' o arquivo). O fallback inline existe
# so' para o script nunca quebrar caso o pacote core/engine ainda nao
# tenha sido sincronizado pelo loader (ver Script.py) neste computador.
try:
    from core.engine.tolerances import (
        FEET_PER_METER, COLLINEAR_MATCH_TOLERANCE_M, COLLINEAR_MATCH_TOLERANCE_FT,
        MIN_WALL_SEGMENT_OVERLAP_RATIO, MIN_WALL_SEGMENT_ABS_FLOOR_M,
        MIN_WALL_SEGMENT_ABS_FLOOR_FT, OPENING_BRIDGE_TOLERANCE_M,
        OPENING_BRIDGE_TOLERANCE_FT,
    )
except Exception:
    FEET_PER_METER = 1.0 / 0.3048
    COLLINEAR_MATCH_TOLERANCE_M = 0.002
    COLLINEAR_MATCH_TOLERANCE_FT = COLLINEAR_MATCH_TOLERANCE_M * FEET_PER_METER
    MIN_WALL_SEGMENT_OVERLAP_RATIO = 0.6
    MIN_WALL_SEGMENT_ABS_FLOOR_M = 0.02
    MIN_WALL_SEGMENT_ABS_FLOOR_FT = MIN_WALL_SEGMENT_ABS_FLOOR_M * FEET_PER_METER
    OPENING_BRIDGE_TOLERANCE_M = 0.03
    OPENING_BRIDGE_TOLERANCE_FT = OPENING_BRIDGE_TOLERANCE_M * FEET_PER_METER

MIN_WALL_THICKNESS_FT = MIN_WALL_THICKNESS_M * FEET_PER_METER
MAX_WALL_THICKNESS_FT = MAX_WALL_THICKNESS_M * FEET_PER_METER

# `_dispatch_progress_event` (usada por _WallReviewForm._on_start_click, ver
# FASE 1 do plano em C:\Users\CIVIX\.claude\plans\quiet-painting-petal.md)
# mora em core/engine/progress.py - modulo PURO, testavel sem Revit/WinForms
# (ver tests/test_progress.py). Mesmo padrao de fallback inline acima: nunca
# quebra o botao se core/engine ainda nao tiver sido sincronizado.
try:
    from core.engine.progress import dispatch_progress_event as _dispatch_progress_event
except Exception:
    def _dispatch_progress_event(console, *args):
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

# Tolerancia (metros) usada SOMENTE por deduplicate_walls para decidir se
# dois EIXOS de parede ja calculados ocupam "a mesma posicao" e portanto um
# deles e' duplicata do outro. Continua generosa (2cm) de proposito, e por
# isso e' uma constante SEPARADA de COLLINEAR_MATCH_TOLERANCE_M (que
# precisou ficar apertada, ver acima): aqui o objetivo e' o oposto -
# reconhecer como duplicata uma parede gerada duas vezes quase no mesmo
# lugar (ex.: o CAD tem uma linha de hachura/cota repetida junto da face),
# o que exige tolerar justamente aqueles poucos centimetros de diferenca.
# Reduzir esta tolerancia junto com a outra faria voltarem as paredes
# empilhadas/sobrepostas no mesmo lugar.
DUPLICATE_AXIS_TOLERANCE_M = 0.02
DUPLICATE_AXIS_TOLERANCE_FT = DUPLICATE_AXIS_TOLERANCE_M * FEET_PER_METER

# Maior "buraco" (metros) entre dois fragmentos colineares que ainda e'
# considerado uma quebra de desenho (ex.: o proprio cruzamento com outra
# parede, cuja largura fica dentro da faixa de espessura aceita) e portanto
# e' religado ao reconstruir a linha. Deliberadamente menor que uma abertura
# de porta/janela tipica (>=60cm), para NAO religar fragmentos separados por
# um vao real.
MAX_JUNCTION_GAP_M = 0.40
MAX_JUNCTION_GAP_FT = MAX_JUNCTION_GAP_M * FEET_PER_METER

# MIN_WALL_SEGMENT_OVERLAP_RATIO e MIN_WALL_SEGMENT_ABS_FLOOR_*
# (criterios de validacao do pareamento de linhas paralelas em faces da
# mesma parede, ver lines_overlap_enough) moraram AQUI ate' esta extracao -
# ver core/engine/tolerances.py para o valor + comentario original.

# Distancia maxima (metros), medida a partir da ponta de uma parede, em que
# se procura OUTRA parede perpendicular para fechar um encontro em T/L (ver
# extend_wall_ends_to_junctions). Fisicamente limitada a' espessura MAXIMA
# de parede aceita (MAX_WALL_THICKNESS_M) mais uma pequena folga de desenho:
# um encontro T/L legitimo nunca precisa esticar mais do que isso para
# alcancar a face oposta da parede perpendicular. Um valor maior (ja testado
# e revertido) deixava a ponta "grudar" em paredes que apenas passavam perto
# sem formar encontro ali, fazendo a parede disparar para fora da planta.
JUNCTION_FACE_SEARCH_M = MAX_WALL_THICKNESS_M + 0.05
JUNCTION_FACE_SEARCH_FT = JUNCTION_FACE_SEARCH_M * FEET_PER_METER

# Margem (metros), alem da caixa envolvente (bounding box) de todas as
# linhas do Layer selecionado, tolerada antes de uma parede criada ser
# sinalizada como "fora dos limites da planta" na validacao final. Segue a
# mesma folga fisica de JUNCTION_FACE_SEARCH_M (maior encontro T/L legitimo
# possivel), para nao acusar falso-positivo em cantos normais.
PLAN_BOUNDS_MARGIN_M = JUNCTION_FACE_SEARCH_M
PLAN_BOUNDS_MARGIN_FT = PLAN_BOUNDS_MARGIN_M * FEET_PER_METER

# Tolerancia (metros) para BUSCAR um WallType ja existente/em uso no
# projeto cuja espessura sirva para reaproveitar (em vez de criar um tipo
# novo do zero). Cobre pequenas imprecisoes de desenho no CAD (ex.: 14.3cm
# medido batendo com um "Parede 14" real de 14.0cm) - mas NAO significa que
# o WallType encontrado e' usado como esta' quando a diferenca e' maior que
# EXACT_THICKNESS_TOLERANCE_FT (ver get_or_create_wall_type): usa-lo direto
# faria a parede final ficar ATE' 1cm mais grossa/fina que a espessura
# escolhida, deslocando cada face lateralmente em ate' METADE dessa
# diferenca (0,5cm no pior caso) em relacao ao eixo medido no CAD.
WALL_THICKNESS_MATCH_TOLERANCE_M = 0.01
WALL_THICKNESS_MATCH_TOLERANCE_FT = WALL_THICKNESS_MATCH_TOLERANCE_M * FEET_PER_METER

# Tolerancia (metros) MUITO mais apertada que WALL_THICKNESS_MATCH_TOLERANCE_M,
# usada para decidir se um WallType encontrado pode ser reaproveitado
# EXATAMENTE COMO ESTA' (sem nenhum ajuste de camada) - cobre so' ruido de
# arredondamento de ponto flutuante, nunca uma diferenca real de espessura.
# Qualquer WallType encontrado fora desta tolerancia (mas ainda dentro de
# WALL_THICKNESS_MATCH_TOLERANCE_FT) e' DUPLICADO antes de usar (herdando
# material/aparencia do tipo encontrado) e a espessura da copia e' ajustada
# para o valor EXATO escolhido pelo usuario - o tipo ORIGINAL nunca e'
# modificado, porque ele pode estar em uso por OUTRAS paredes reais do
# projeto (mudar sua espessura mudaria essas paredes tambem).
EXACT_THICKNESS_TOLERANCE_M = 0.0005
EXACT_THICKNESS_TOLERANCE_FT = EXACT_THICKNESS_TOLERANCE_M * FEET_PER_METER

# Tolerancia PADRAO (metros), para mais ou para menos, usada apenas na fase
# de DETECCAO para casar a distancia medida entre duas linhas paralelas do
# CAD com uma das espessuras que o usuario escolheu modelar. NAO afeta a
# espessura final da parede criada (essa e' sempre o valor exato escolhido
# pelo usuario - ver find_wall_pairs). Quando duas espessuras escolhidas
# estao proximas uma da outra (ex.: 14cm e 15cm), essa tolerancia e'
# automaticamente reduzida (ver compute_detection_tolerance_ft) para nao
# deixar as duas faixas se sobrepormos e confundirem uma parede com a outra.
WALL_DETECTION_TOLERANCE_M = 0.025
WALL_DETECTION_TOLERANCE_FT = WALL_DETECTION_TOLERANCE_M * FEET_PER_METER

# Extensao MAXIMA (metros) que o eixo de uma parede pode ganhar, em cada
# ponta, alem do proprio comprimento da linha usada como referencia (l1),
# para acomodar o caso normal de encontro em T/L/Cruz (onde a face pareada,
# l2, e' um pouco mais longa numa ponta). Fisicamente limitada a' mesma
# folga de JUNCTION_FACE_SEARCH_M (espessura maxima de parede aceita + uma
# pequena folga de desenho) - um encontro T/L legitimo nunca precisa de
# mais do que isso. Um valor maior (ja testado e revertido: paredes
# ficaram visivelmente fora dos limites da planta) deixava um pareamento
# equivocado (ex.: l2 e' na verdade uma parede bem mais longa que so' passa
# perto dali) esticar a parede criada muito alem dos limites reais
# desenhados no CAD.
CENTERLINE_MAX_EXTENSION_M = JUNCTION_FACE_SEARCH_M
CENTERLINE_MAX_EXTENSION_FT = CENTERLINE_MAX_EXTENSION_M * FEET_PER_METER

# Nomes dos parametros de instancia que identificam uma familia de "abertura"
# (janela/porta) ja inserida no projeto pelo usuario antes de rodar o script,
# independente da categoria/nome da familia. Todas as 3 precisam existir na
# instancia para ela ser tratada como abertura.
OPENING_WIDTH_PARAM = "Largura_abertura"
OPENING_HEIGHT_PARAM = "Altura_abertura"
OPENING_SILL_PARAM = "Peitoril"
OPENING_LEVEL_OFFSET_PARAM = "Elevacao do nivel"  # sem acento por seguranca; ver get_opening_instances

# Diferenca MAXIMA (metros) tolerada entre a largura MEDIDA na geometria da
# familia de abertura (ao longo do eixo local X dela - ver
# _opening_center_from_geometry) e o parametro `Largura_abertura`, para
# aceitar que a geometria desenhada pela familia E' o proprio retangulo do
# vao e, portanto, que o CENTRO dessa geometria pode ser usado como centro
# real do vao (em vez do ponto de insercao da instancia, que nas familias
# deste projeto fica sistematicamente deslocado - ver a nota extensa em
# _opening_center_from_geometry).
#
# E' uma verificacao de SEGURANCA deliberada, nao uma tolerancia de
# desenho: se a familia tiver qualquer geometria alem do vao (folha de porta
# aberta, arco de abertura, soleira, moldura), a largura medida vai dar
# claramente MAIOR que `Largura_abertura`, a verificacao falha e o script
# volta a usar o ponto de insercao - comportamento anterior, preservado
# como fallback para familias que nao sigam este padrao. 2cm cobre so'
# arredondamento/imprecisao de desenho.
OPENING_GEOMETRY_WIDTH_TOLERANCE_M = 0.02
OPENING_GEOMETRY_WIDTH_TOLERANCE_FT = OPENING_GEOMETRY_WIDTH_TOLERANCE_M * FEET_PER_METER

# Distancia perpendicular extra (metros), alem da meia-espessura da parede,
# tolerada para associar uma abertura a uma linha de parede sendo criada.
OPENING_ASSOC_TOLERANCE_M = 0.05
OPENING_ASSOC_TOLERANCE_FT = OPENING_ASSOC_TOLERANCE_M * FEET_PER_METER

# NOTA HISTORICA (nao reintroduzir): existiu aqui uma constante
# OPENING_AXIS_SLACK_M (30cm) que permitia ESTICAR o eixo de uma parede ate'
# alcancar o vao de uma abertura que caisse fora dele. Ela foi criada para
# resolver o sintoma de aberturas sem verga nenhuma, mas era um paliativo
# para a causa raiz REAL - o centro do vao estava sendo lido do ponto de
# insercao da familia, que fica deslocado (ver _opening_center_from_geometry).
# Com o centro correto, essa folga passou a nunca disparar (0 casos em 71
# aberturas reais), e mante-la so' criaria o risco de mascarar futuras
# regressoes da mesma classe, alem de contrariar o requisito de que o trecho
# de parede de uma abertura NAO deve ganhar nenhuma extensao automatica.

# Distancia perpendicular MAXIMA (metros) tolerada, em merge_collinear_fragments,
# entre o centro de uma abertura e a linha de FACE (nao o eixo) de uma
# parede, para considerar que a quebra ali e' o vao dessa abertura (ver
# _opening_bridges_gap). Igual a' espessura maxima de parede aceita: uma
# linha de face nunca fica mais longe do que isso do centro real da parede
# (e, portanto, do centro de uma abertura que pertence a ela).
OPENING_GAP_PERP_TOLERANCE_FT = MAX_WALL_THICKNESS_FT

# Folga (metros) tolerada entre o tamanho da quebra no CAD e a largura
# medida da abertura (Largura_abertura/bounding box), para cobrir jambas,
# enquadramento ou pequenas imprecisoes de desenho ao redor do vao.
OPENING_GAP_WIDTH_SLACK_M = 0.30
OPENING_GAP_WIDTH_SLACK_FT = OPENING_GAP_WIDTH_SLACK_M * FEET_PER_METER

# OPENING_BRIDGE_TOLERANCE_* (tolerancia mais generosa que
# COLLINEAR_MATCH_TOLERANCE_M, usada so' para religar dois clusters de
# fragmentos colineares que uma abertura real comprovadamente separa - ver
# _opening_bridges_gap/_clusters_bridge_via_opening) morou AQUI ate' esta
# extracao - ver core/engine/tolerances.py para o valor + comentario
# original.

# Comprimento/altura minimos (metros) para um segmento de parede (cheio ou de
# preenchimento acima/abaixo de uma abertura) ser considerado valido - abaixo
# disso o segmento e' descartado por ser geometricamente degenerado (e o
# Revit rejeitaria a criacao).
MIN_SEGMENT_LENGTH_M = 0.01
MIN_SEGMENT_LENGTH_FT = MIN_SEGMENT_LENGTH_M * FEET_PER_METER
MIN_SEGMENT_HEIGHT_M = 0.01
MIN_SEGMENT_HEIGHT_FT = MIN_SEGMENT_HEIGHT_M * FEET_PER_METER

# ==========================================
# TOLERANCIAS DA ETAPA DE VALIDACAO FINAL
# ==========================================
# As duas constantes abaixo NAO controlam a geracao da geometria - so'
# decidem quando a etapa de validacao final (ver validate_generated_geometry
# e find_wall_pairs/assign_openings_to_walls) marca algo como "suspeito" no
# resumo mostrado ao usuario no final da execucao.

# Desvio MAXIMO (metros), em qualquer uma das pontas do eixo calculado por
# create_centerline, entre a distancia ate' l1 e a distancia ate' l2 (que
# deveriam ser IGUAIS - e' a propria definicao de "eixo central") antes de
# ser reportado como parede com deslocamento suspeito. Bem mais apertado
# que os ~0,5cm relatados como sintoma - serve como alarme precoce para
# qualquer regressao futura no calculo do eixo, nao so' para o caso ja
# corrigido.
AXIS_OFFSET_WARNING_M = 0.001
AXIS_OFFSET_WARNING_FT = AXIS_OFFSET_WARNING_M * FEET_PER_METER

# Quanto (metros) a largura horizontal calculada para o vao de uma abertura
# sobre uma parede (t_hi - t_lo) pode ficar MENOR que `Largura_abertura`
# antes de ser reportada como abertura "cortada" pelo limite da propria
# parede (ver assign_openings_to_walls) - sinal de que a abertura esta'
# posicionada perto demais da ponta da parede reconstruida a partir do CAD.
OPENING_WIDTH_CLAMP_WARNING_M = 0.02
OPENING_WIDTH_CLAMP_WARNING_FT = OPENING_WIDTH_CLAMP_WARNING_M * FEET_PER_METER

# ==========================================
# LINHAS DE FECHAMENTO (TOPO/TESTA DE PAREDE)
# ==========================================
# Uma parede desenhada em planta nao e' so' o par de linhas paralelas das
# suas faces: onde ela realmente ACABA, o CAD normalmente desenha uma linha
# TRANSVERSAL, no mesmo Layer, ligando uma face a' outra (a "testa" da
# parede). Essa linha e' o limite fisico da parede, e tem prioridade sobre
# qualquer prolongamento geometrico das faces (ver clip_centerline_to_caps).

# Quanto da espessura da parede uma linha transversal precisa cobrir, de
# face a face, para ser aceita como linha de fechamento. A faixa e' ampla
# dos dois lados de proposito: no minimo, para aceitar uma testa desenhada
# um pouco curta (ou que nao encosta exatamente nas duas faces); no maximo,
# para NAO confundir com uma parede perpendicular que cruza a parede toda
# (bem mais longa que a espessura dela).
CAP_MIN_COVERAGE_RATIO = 0.55
CAP_MAX_COVERAGE_RATIO = 1.60

# Desalinhamento angular maximo aceito entre a linha transversal e a
# perpendicular exata do eixo da parede (valor = |cos| do angulo em relacao
# a' direcao da parede). 0.35 equivale a aceitar ate' uns 20 graus fora da
# perpendicular - cobre testas desenhadas em diagonal/chanfro sem aceitar
# linhas que na verdade correm ao longo da parede.
CAP_MAX_AXIAL_COMPONENT = 0.35

# O quanto (fracao da meia-espessura) o centro da linha transversal pode
# estar fora do eixo da parede e ainda ser considerada uma testa DESTA
# parede - evita capturar testas de paredes vizinhas que passam de raspao.
CAP_MAX_CENTER_OFFSET_RATIO = 0.75

# Folga (metros) alem das pontas do eixo em que ainda se procura uma linha
# de fechamento. Uma testa costuma cair exatamente na ponta, mas o eixo
# reconstruido pode passar alguns cm dela.
CAP_SEARCH_MARGIN_M = JUNCTION_FACE_SEARCH_M
CAP_SEARCH_MARGIN_FT = CAP_SEARCH_MARGIN_M * FEET_PER_METER

# Distancia maxima (metros) entre a ponta de uma linha transversal candidata
# a testa e a ponta de uma linha de FACE real (do mesmo Layer, correndo ao
# longo do eixo) para considerar que elas se TOCAM. Uma testa de verdade
# fecha o fim fisico da parede exatamente onde as duas faces terminam -
# entao suas pontas sempre coincidem (ou quase) com a ponta de uma face.
#
# CASO REAL que motivou esta checagem (2026-08-18, medido via MCP num
# projeto real): uma linha solta de 14cm no CAD, no meio de um pilar entre
# duas janelas, SEM tocar nenhuma face - mas por coincidencia media
# exatamente a espessura da parede e ficava centrada no eixo, entao
# passava por CAP_MIN/MAX_COVERAGE_RATIO e CAP_MAX_CENTER_OFFSET_RATIO e
# era aceita como testa. Isso cortava a parede 63,5cm antes do vao real da
# janela (a face continua, apos merge_collinear_fragments, atravessava o
# pilar sem problema - o corte era so' desta testa fantasma). Diferente de
# CAP_OPENING_SLACK_M/OPENING_GEOMETRY_WIDTH_TOLERANCE_M (tolerancias de
# MEDIDA), esta e' uma checagem de TOPOLOGIA/CONEXAO - por isso o valor
# pode ser pequeno sem risco de mascarar o problema.
CAP_ENDPOINT_TOUCH_TOLERANCE_M = 0.05
CAP_ENDPOINT_TOUCH_TOLERANCE_FT = CAP_ENDPOINT_TOUCH_TOLERANCE_M * FEET_PER_METER

# Folga (metros) somada a' meia-largura de uma abertura ao decidir se uma
# linha transversal cai DENTRO do vao de uma porta/janela. Linhas de
# fechamento nessa situacao sao as JAMBAS do vao desenhadas no CAD - e ali
# a parede NAO termina: ela continua fisicamente acima (verga) e/ou abaixo
# (peitoril) da abertura, entao essas linhas sao deliberadamente ignoradas
# como limite (ver _cap_falls_inside_opening).
#
# Alargada de 5cm para 20cm com base em diagnostico REAL (log de execucao):
# varias aberturas de portas ficaram sistematicamente 17,5-18cm de distancia
# da parede mais proxima, valor IDENTICO repetido em varias unidades
# repetidas da planta (mesma familia/bloco de porta usado em cada uma) -
# sinal de que o bloco de porta do CAD desenha um detalhe fixo (batente/
# marco) ~17,5cm alem do vao nominal, e esse detalhe e' uma linha
# transversal que CAP_OPENING_SLACK_FT precisa alcancar para reconhece-la
# como parte da propria abertura (jamba), nao como fim real da parede - com
# 5cm de folga essa linha ficava fora da zona de exclusao e cortava a
# parede bem antes do vao, deixando a abertura sem verga/peitoril nenhum.
# 20cm da margem suficiente para esse caso especifico sem se aproximar do
# comprimento de uma parede real (mesmo a menor "boneca" costuma ter varias
# dezenas de cm a mais que isso).
CAP_OPENING_SLACK_M = 0.20
CAP_OPENING_SLACK_FT = CAP_OPENING_SLACK_M * FEET_PER_METER

# ==========================================
# FUNCOES AUXILIARES DE GEOMETRIA E LAYER
# ==========================================

def get_layer_name(geom_obj):
    """Obtem o nome do Layer do AutoCAD a partir do GraphicsStyle da linha."""
    style_id = geom_obj.GraphicsStyleId
    if style_id and style_id != ElementId.InvalidElementId:
        style = doc.GetElement(style_id)
        if isinstance(style, GraphicsStyle):
            # GraphicsStyleCategory reflete a subcategoria == Layer do CAD.
            if style.GraphicsStyleCategory:
                return style.GraphicsStyleCategory.Name
            return style.Name
    return None


def extract_lines_by_layer(geom_element, lines_by_layer):
    """Percorre recursivamente a geometria do CAD agrupando linhas por Layer.

    CADs importados/vinculados (ImportInstance) quase sempre expoe suas
    curvas "embrulhadas" dentro de um GeometryInstance. E' preciso descer
    nesse nivel via GetInstanceGeometry() para chegar as linhas reais -
    ignora-lo faz o script nunca encontrar nenhuma linha.

    Paredes desenhadas no CAD como POLILINHA (LWPOLYLINE/POLYLINE) chegam
    ao Revit como um UNICO objeto `PolyLine` (varios vertices), nao como
    varios `Line` separados. Sem tratar esse tipo, essas paredes ficam
    invisiveis para o script mesmo estando no Layer correto - por isso a
    polilinha e' "explodida" aqui em segmentos Line ponta-a-ponta.
    """
    for geom_obj in geom_element:
        if isinstance(geom_obj, GeometryInstance):
            extract_lines_by_layer(geom_obj.GetInstanceGeometry(), lines_by_layer)
            continue

        if isinstance(geom_obj, Line):
            if geom_obj.ApproximateLength < 1e-6:
                continue  # descarta linhas degeneradas (comprimento ~0)
            layer = get_layer_name(geom_obj)
            if layer:
                lines_by_layer.setdefault(layer, []).append(geom_obj)
            continue

        if isinstance(geom_obj, PolyLine):
            layer = get_layer_name(geom_obj)
            if not layer:
                continue
            points = list(geom_obj.GetCoordinates())
            for p0, p1 in zip(points, points[1:]):
                if p0.DistanceTo(p1) < 1e-6:
                    continue  # descarta segmentos degenerados (vertices duplicados)
                lines_by_layer.setdefault(layer, []).append(Line.CreateBound(p0, p1))


# ==========================================
# GEOMETRIA PURA - EXTRAIDA para core/engine/geometry.py
#
# are_lines_parallel, get_line_midpoint, project_point_on_line,
# get_distance_between_parallel_lines, _line_geom_cache,
# _are_parallel_cached, _distance_between_parallel_cached,
# _line_pair_overlap_ft_cached, _xy_deviation_ft, _axis_offset_error_ft,
# create_centerline, os ajudantes de religamento por abertura
# (_opening_bridges_gap, _merge_collinear_cluster, _cluster_axis,
# _cluster_interval, _clusters_bridge_via_opening,
# _bridge_clusters_via_openings), merge_collinear_fragments,
# _line_pair_overlap_ft e lines_overlap_enough moraram AQUI ate' esta
# extracao (ver ARQUITETURA_INTERATIVA.md) - nenhuma formula mudou, so'
# o arquivo. `create_centerline` perdeu o default de `max_extension_ft`
# (o unico call-site ja passava CENTERLINE_MAX_EXTENSION_FT explicito).
from core.engine.geometry import *  # noqa: F401,F403
# ==========================================




def get_basic_wall_types():
    """Retorna apenas os WallType do tipo Basic (paredes simples/empilhaveis)."""
    return [
        wt for wt in FilteredElementCollector(doc).OfClass(WallType).ToElements()
        if wt.Kind == WallKind.Basic
    ]


def get_existing_wall_types_in_use(basic_wall_types):
    """Dentre os WallTypes basicos do projeto, devolve so' os que ja estao
    em uso por pelo menos uma parede REAL ja modelada (nao apenas definidos
    no navegador de tipos, sem nunca terem sido colocados).

    Isso identifica a espessura "real" das paredes existentes no projeto,
    para o script poder reaproveitar esses tipos (com material, aparencia
    etc. ja configurados pelo usuario) em vez de sempre criar um tipo novo
    generico a partir da medicao do CAD.
    """
    used_type_ids = set()
    for wall in FilteredElementCollector(doc).OfClass(Wall).WhereElementIsNotElementType():
        used_type_ids.add(wall.GetTypeId())

    return [wt for wt in basic_wall_types if wt.Id in used_type_ids]


def get_existing_wall_type_by_thickness(thickness_ft, wall_types, tolerance_ft):
    """Procura, entre `wall_types`, aquele cuja espessura total (WallType.Width)
    mais se aproxima de `thickness_ft`, dentro de `tolerance_ft`. Devolve o
    WallType mais proximo, ou None se nenhum estiver dentro da tolerancia."""
    best_type, best_diff = None, None
    for wt in wall_types:
        diff = abs(wt.Width - thickness_ft)
        if diff <= tolerance_ft and (best_diff is None or diff < best_diff):
            best_type, best_diff = wt, diff
    return best_type


def get_wall_type_by_name(wall_types, name):
    """Procura um WallType por nome exato entre `wall_types`."""
    for wt in wall_types:
        name_param = wt.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
        if name_param and name_param.AsString() == name:
            return wt
    return None


def _core_layer_indices(compound_structure, layers):
    """Devolve a lista de indices de `layers` que pertencem ao NUCLEO
    estrutural de `compound_structure`, segundo a definicao de nucleo do
    proprio Revit (GetFirstCoreLayerIndex/GetLastCoreLayerIndex) - o mesmo
    intervalo de camadas que o Revit usa para posicionar a Linha de
    Referencia "CoreCenterline" (ver WALL_KEY_REF_PARAM em main()).

    Devolve None se o WallType nao tiver um nucleo valido definido (caso
    raro/defensivo) - nesse caso quem chamar deve usar um fallback."""
    try:
        first_core = compound_structure.GetFirstCoreLayerIndex()
        last_core = compound_structure.GetLastCoreLayerIndex()
    except Exception:
        return None
    if first_core is None or last_core is None:
        return None
    if first_core < 0 or last_core < first_core or last_core >= len(layers):
        return None
    return list(range(first_core, last_core + 1))


def _core_width_ft(wall_type):
    """Devolve a largura TOTAL do nucleo estrutural de `wall_type` (soma de
    TODAS as camadas dentro do intervalo de nucleo - ver `_core_layer_indices`,
    que pode conter mais de uma camada). Essa e' a grandeza que realmente
    determina onde a Linha de Referencia "CoreCenterline" fica posicionada -
    nao `wall_type.Width` (largura do pacote INTEIRO, incluindo camadas de
    acabamento fora do nucleo), que e' usado aqui so' como fallback quando o
    tipo nao tem um nucleo valido definido."""
    compound_structure = wall_type.GetCompoundStructure()
    if not compound_structure:
        return wall_type.Width
    layers = list(compound_structure.GetLayers())
    if not layers:
        return wall_type.Width
    core_indices = _core_layer_indices(compound_structure, layers)
    if not core_indices:
        return wall_type.Width
    return sum(layers[idx].Width for idx in core_indices)


def _pick_core_material_id(wall_type):
    """Devolve o MaterialId da camada mais representativa do nucleo de
    `wall_type` (a de funcao Estrutura; havendo mais de uma, a mais
    espessa; nao havendo nenhuma, a camada de nucleo mais espessa), para
    que a parede reconstruida por `apply_structural_thickness` preserve o
    material/aparencia do tipo de origem. Devolve ElementId.InvalidElementId
    se nao for possivel determinar."""
    compound_structure = wall_type.GetCompoundStructure()
    if not compound_structure:
        return ElementId.InvalidElementId
    layers = list(compound_structure.GetLayers())
    if not layers:
        return ElementId.InvalidElementId

    core_indices = _core_layer_indices(compound_structure, layers) or list(range(len(layers)))
    structural = [
        idx for idx in core_indices
        if layers[idx].Function == MaterialFunctionAssignment.Structure
    ]
    candidates = structural or core_indices
    best_idx = max(candidates, key=lambda i: layers[i].Width)
    return layers[best_idx].MaterialId


def apply_structural_thickness(wall_type, thickness_ft):
    """Reconstroi `wall_type` como uma parede de CAMADA UNICA, de funcao
    Estrutura, com espessura EXATAMENTE `thickness_ft` - preservando o
    material da camada estrutural do tipo de origem (ver
    `_pick_core_material_id`). So' e' chamada sobre tipos EXCLUSIVOS do
    script (duplicatas recem-criadas ou "Parede CAD - Xcm" de execucoes
    anteriores), nunca sobre um tipo "de verdade" do usuario, que pode
    estar em uso por outras paredes reais do projeto.

    Por que camada UNICA, em vez de so' ajustar a espessura do nucleo
    (comportamento anterior desta funcao): enquanto o tipo tiver QUALQUER
    camada fora do nucleo (reboco, acabamento, membrana), a parede
    DESENHADA fica mais grossa que a espessura medida entre as duas linhas
    do CAD, e essa sobra vai para os lados do nucleo. Com camadas
    assimetricas, ela vai mais para um lado que para o outro - e o lado
    "de fora" de uma parede depende do SENTIDO em que sua curva foi
    desenhada, entao duas paredes colineares desenhadas em sentidos opostos
    no CAD recebem a sobra em direcoes OPOSTAS. Resultado: a parede nunca
    coincide exatamente com as linhas da planta, e o desvio muda de direcao
    de parede para parede (o "deslocamento de 0,5cm ora para baixo, ora
    para outros lados" relatado). Nenhuma compensacao de posicao resolve
    isso de forma geral, porque a espessura desenhada em si esta' diferente
    da medida no CAD.

    Com camada unica, tres coisas passam a valer ao mesmo tempo, por
    construcao: (a) a largura TOTAL da parede e' exatamente a espessura
    escolhida, entao suas duas faces caem exatamente sobre as duas linhas
    do CAD; (b) a parede e' simetrica, entao nao existe "lado de fora"
    privilegiado nem dependencia do sentido do desenho; e (c) o centro do
    pacote coincide com o centro do nucleo (WallCenterline == CoreCenterline),
    o que torna o alinhamento independente de qual Linha de Referencia o
    Revit acabe usando.
    """
    material_id = _pick_core_material_id(wall_type)
    single_layer = CompoundStructure.CreateSingleLayerCompoundStructure(
        MaterialFunctionAssignment.Structure, thickness_ft, material_id
    )
    wall_type.SetCompoundStructure(single_layer)


def get_or_create_wall_type(thickness_ft, base_wall_type, basic_wall_types, preferred_wall_types, cache):
    """Resolve o WallType a usar para uma espessura medida/informada, de
    forma totalmente autonoma - NAO depende de o projeto ja ter um tipo de
    parede pre-configurado com a espessura certa. Ordem de prioridade:

    1. Cache (evita repetir a busca para a mesma espessura ja resolvida
       nesta execucao).
    2. Um WallType ja EM USO por uma parede real do projeto, com espessura
       compativel (dentro de WALL_THICKNESS_MATCH_TOLERANCE_FT) - reaproveita
       o tipo "de verdade" que o usuario ja construiu, com material e
       aparencia corretos. Se a espessura desse tipo nao bater EXATAMENTE
       (dentro de EXACT_THICKNESS_TOLERANCE_FT) com a pedida, o tipo e'
       DUPLICADO (nunca modificado no lugar - ele pode estar em uso por
       OUTRAS paredes reais do projeto) e so' a copia tem sua espessura
       ajustada para o valor exato.
    3. QUALQUER WallType basico do projeto (em uso ou nao) com espessura
       compativel - cobre, por exemplo, um "Parede CAD - Xcm" de uma
       execucao anterior que ja tenha a espessura certa. Mesma regra de
       duplicar em vez de modificar se nao bater exatamente.
    4. Cria um novo WallType. Se ja existir um tipo com o MESMO NOME
       pretendido mas espessura diferente (Revit nao permite nomes
       duplicados, entao duplicar geraria erro), corrige a espessura desse
       tipo em vez de criar outro - assim qualquer sobra quebrada de uma
       execucao anterior com bug se autocorrige (esse tipo e' sempre
       exclusivo do script, nunca um tipo "de verdade" do usuario, entao
       ajusta-lo no lugar e' seguro).

    Usar um WallType cujo NUCLEO (nao o pacote inteiro - ver `_core_width_ft`)
    nao tenha a espessura EXATA pedida (mesmo que dentro da folga
    "compativel" de busca) faz a parede final ficar mais grossa/fina que o
    eixo calculado pressupoe, deslocando cada face lateralmente em ate'
    METADE dessa diferenca em relacao a posicao medida no CAD - por isso,
    em TODOS os casos, a espessura do NUCLEO e' sempre CONFERIDA e
    corrigida via duplicacao antes de devolver o tipo: se mesmo assim nao
    bater (dentro da tolerancia), levanta erro em vez de devolver
    silenciosamente um WallType com a espessura errada. A verificacao usa
    a largura do NUCLEO, e nao `wall_type.Width` (o pacote inteiro,
    incluindo eventuais camadas de acabamento fora do nucleo), porque e' o
    nucleo - nao o pacote inteiro - que fica centralizado sobre o eixo do
    CAD (Linha de Referencia = CoreCenterline, ver main()).
    """
    thickness_cm = round(thickness_ft / FEET_PER_METER * 100.0, 1)

    if thickness_cm in cache:
        return cache[thickness_cm]

    wall_type = get_existing_wall_type_by_thickness(
        thickness_ft, preferred_wall_types, WALL_THICKNESS_MATCH_TOLERANCE_FT
    )
    if not wall_type:
        wall_type = get_existing_wall_type_by_thickness(
            thickness_ft, basic_wall_types, WALL_THICKNESS_MATCH_TOLERANCE_FT
        )

    if wall_type is not None and abs(_core_width_ft(wall_type) - thickness_ft) > EXACT_THICKNESS_TOLERANCE_FT:
        # Tipo encontrado dentro da folga de BUSCA, mas nao com o nucleo na
        # espessura exata - duplica (herdando material/aparencia) em vez de
        # usar como esta' ou de modificar o tipo original no lugar.
        found_name = wall_type.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM).AsString()
        dup_name = "{} - CAD {}cm".format(found_name, thickness_cm)
        existing_dup = get_wall_type_by_name(basic_wall_types, dup_name)
        wall_type = existing_dup if existing_dup is not None else wall_type.Duplicate(dup_name)
        apply_structural_thickness(wall_type, thickness_ft)

    if not wall_type:
        wall_type_name = "Parede CAD - {}cm".format(thickness_cm)
        wall_type = get_wall_type_by_name(basic_wall_types, wall_type_name)
        if wall_type is None:
            wall_type = base_wall_type.Duplicate(wall_type_name)
        apply_structural_thickness(wall_type, thickness_ft)

    final_core_width_ft = _core_width_ft(wall_type)
    if abs(final_core_width_ft - thickness_ft) > WALL_THICKNESS_MATCH_TOLERANCE_FT:
        raise Exception(
            "Nao foi possivel ajustar o nucleo do WallType '{}' para {}cm (ficou em {}cm).".format(
                wall_type.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM).AsString(),
                thickness_cm,
                round(final_core_width_ft / FEET_PER_METER * 100.0, 1)
            )
        )

    cache[thickness_cm] = wall_type
    return wall_type


# ==========================================
# PAREAMENTO/JUNCOES - EXTRAIDO para core/engine/wall_pairing.py
#
# find_wall_pairs, scan_possible_missed_bonecas, classify_unused_line_reason,
# extend_wall_ends_to_junctions e seus helpers de grafo (_wall_node_arms e
# familia), build_wall_graph, build_plan_bounds, deduplicate_walls,
# build_no_pairs_message, scan_candidate_thicknesses_cm,
# compute_detection_tolerance_ft, e as funcoes de linha de fechamento
# (find_cap_positions/clip_centerline_to_caps e helpers privados) moraram
# AQUI ate' esta extracao - ver core/engine/wall_pairing.py para o codigo +
# comentario original de cada uma (nenhuma formula mudou, so' o arquivo).
from core.engine.wall_pairing import *  # noqa: F401,F403
# ==========================================


def ask_wall_thicknesses(lines):
    """Pergunta ao usuario quais espessuras de parede ele deseja modelar,
    permitindo selecionar mais de uma dentre as espessuras candidatas
    detectadas automaticamente no Layer (com a contagem de pares paralelos
    encontrados em cada uma) e/ou digitar espessuras adicionais manualmente.

    Devolve uma lista de espessuras em PES (sem duplicatas, ordenada), ou
    None se o usuario cancelar ou nao informar nenhuma espessura valida.
    """
    counts = scan_candidate_thicknesses_cm(lines)
    sorted_buckets = sorted(counts.keys())

    manual_option = "Digitar outra(s) espessura(s) manualmente..."
    label_to_cm = {}
    options = []
    for cm in sorted_buckets:
        occurrences = counts[cm]
        label = "{} cm  ({} par{} de linhas encontrado{})".format(
            ("%g" % cm), occurrences, "" if occurrences == 1 else "es",
            "" if occurrences == 1 else "s"
        )
        options.append(label)
        label_to_cm[label] = cm
    options.append(manual_option)

    selected = forms.SelectFromList.show(
        options,
        title="Selecione a(s) espessura(s) de parede a modelar",
        button_name="Continuar",
        multiselect=True
    )
    if not selected:
        return None

    chosen_cm = set()
    need_manual = manual_option in selected
    for label in selected:
        if label in label_to_cm:
            chosen_cm.add(label_to_cm[label])

    if need_manual or not sorted_buckets:
        manual_str = forms.ask_for_string(
            default="15;20",
            prompt=(
                "Informe a(s) espessura(s) de parede em cm, separadas por "
                "ponto e virgula (ex: 15;20):"
            ),
            title="Espessuras Manuais"
        )
        if manual_str:
            for token in manual_str.split(";"):
                token = token.strip()
                if not token:
                    continue
                try:
                    value_cm = float(token.replace(",", "."))
                    if value_cm <= 0:
                        raise ValueError
                except ValueError:
                    forms.alert(
                        "Valor de espessura invalido: '{}'. Use numeros positivos, "
                        "ex: 15;20".format(token),
                        exitscript=True
                    )
                    return None
                chosen_cm.add(value_cm)

    if not chosen_cm:
        forms.alert("Nenhuma espessura de parede foi selecionada.", exitscript=True)
        return None

    return sorted((cm / 100.0) * FEET_PER_METER for cm in chosen_cm)


def _param_value_as_feet(param):
    """Devolve o valor de `param` em pes (unidade interna do Revit),
    tratando corretamente os dois casos possiveis:

    - Parametro de COMPRIMENTO: `AsDouble()` ja devolve o valor em pes,
      correto para uso direto.
    - Parametro de NUMERO (sem unidade): `AsDouble()` devolve o numero cru
      exatamente como foi digitado (ex.: 81, 160) - SEM nenhuma conversao.
      As Cotas da familia de abertura do usuario (Largura_abertura,
      Altura_abertura, Peitoril) sao assim: aparecem na paleta de
      Propriedades sem sufixo de unidade (ex.: "81,00"), ou seja, o usuario
      digita o valor direto em CENTIMETROS. Tratar esse numero cru como pes
      (erro cometido antes desta correcao) faz uma abertura de 81cm virar
      81 PES (~24m) de largura - abertura gigante/deslocada, cobrindo a
      parede inteira em vez de abrir um vao no lugar certo.

    Para distinguir os dois casos sem depender de APIs de unidade
    especificas de versao do Revit (ForgeTypeId/SpecTypeId nem sempre
    disponiveis), compara o numero cru de `AsDouble()` com o numero exibido
    em `AsValueString()` (que sempre mostra o valor already formatado nas
    unidades de projeto, com conversao aplicada quando o parametro E' de
    Comprimento): se os dois numeros baterem, e' porque nao houve nenhuma
    conversao de unidade - logo e' parametro de Numero puro, e o valor
    precisa ser convertido de CENTIMETROS para pes aqui. Se forem bem
    diferentes, e' porque AsValueString() ja aplicou a conversao de
    Comprimento - logo AsDouble() ja esta em pes e deve ser usado como esta.
    """
    raw = param.AsDouble()
    try:
        display_str = param.AsValueString()
        display_num = float(display_str.strip().split()[0].replace(".", "").replace(",", "."))
    except (TypeError, ValueError, AttributeError, IndexError):
        return raw
    if abs(raw - display_num) < 0.001:
        # Numero puro sem unidade: valor digitado esta em CENTIMETROS.
        return (raw / 100.0) * FEET_PER_METER
    return raw


def _lookup_param_value(instance, param_names):
    """Procura, em `instance` e, se nao encontrar, no respectivo `Symbol`
    (Tipo), o primeiro parametro cujo nome (dentre `param_names`) exista e
    tenha valor numerico, e devolve seu valor em PES (ver `_param_value_as_feet`
    para a logica de conversao Numero-vs-Comprimento). Devolve None se
    nenhum for encontrado.

    Procurar tambem no Tipo cobre o caso comum de o parametro (ex.: offset
    de nivel, ou ate' Largura_abertura/Altura_abertura/Peitoril) ter sido
    definido como parametro de TIPO em vez de INSTANCIA - Element.LookupParameter
    so' enxerga parametros de instancia, entao um parametro de tipo com o
    mesmo nome passaria despercebido sem este fallback.
    """
    for name in param_names:
        param = instance.LookupParameter(name)
        if param is not None and param.HasValue:
            return _param_value_as_feet(param)
    symbol = getattr(instance, "Symbol", None)
    if symbol is not None:
        for name in param_names:
            param = symbol.LookupParameter(name)
            if param is not None and param.HasValue:
                return _param_value_as_feet(param)
    return None


def _collect_instance_geometry_points(inst):
    """Devolve TODOS os pontos extremos da geometria real de `inst` (curvas
    e arestas de solidos), ja em coordenadas de MUNDO - descendo pelos
    GeometryInstance, como em extract_lines_by_layer, senao a geometria da
    familia nao aparece."""
    options = Options()
    options.IncludeNonVisibleObjects = True
    options.DetailLevel = ViewDetailLevel.Fine

    points = []

    def walk(geom_element):
        for geom_obj in geom_element:
            if isinstance(geom_obj, GeometryInstance):
                walk(geom_obj.GetInstanceGeometry())
            elif isinstance(geom_obj, Curve):
                points.append(geom_obj.GetEndPoint(0))
                points.append(geom_obj.GetEndPoint(1))
            elif isinstance(geom_obj, Solid) and geom_obj.Volume > 1e-9:
                for edge in geom_obj.Edges:
                    curve = edge.AsCurve()
                    points.append(curve.GetEndPoint(0))
                    points.append(curve.GetEndPoint(1))

    geom = inst.get_Geometry(options)
    if geom is not None:
        walk(geom)
    return points


def _opening_center_from_geometry(inst, width_ft):
    """Calcula o centro EM PLANTA do vao de uma abertura a partir da
    GEOMETRIA REAL da familia (o "retangulo do vao" que ela desenha), em vez
    do ponto de insercao da instancia.

    MOTIVO (medido, nao suposto - ver a nota historica abaixo): nas familias
    de abertura deste projeto o ponto de insercao NAO fica no centro do vao.
    Conferido nas 71 instancias de 'Abertura de janela para paredes de
    blocos': a geometria da familia e' exatamente o retangulo do vao
    (Largura_abertura x espessura da parede, sem folha, soleira nem
    qualquer outro adorno), e o ponto de insercao esta' deslocado desse
    centro de forma SISTEMATICA por tipo (17,0cm nas de 86cm; 23,0cm na de
    166cm; 24,5cm em outras) - nunca zero, em 71 de 71. Usar o ponto de
    insercao como centro do vao (comportamento anterior) deslocava
    lateralmente TODO trecho de verga/peitoril por essa mesma distancia, e
    tambem impedia `_opening_bridges_gap` de reconhecer o vao real
    desenhado no CAD (o centro caia fora da quebra), o que fazia nem existir
    eixo de parede passando pela abertura.

    ATENCAO - isto CONTRADIZ deliberadamente uma conclusao anterior desta
    mesma depuracao ("as familias sao inseridas no centro real do vao; a
    diferenca para o centro da bounding box e' ruido de geometria
    assimetrica - nao trocar"). Aquela conclusao foi verificada contra os
    dados reais e esta' ERRADA para estas familias: a geometria aqui nao tem
    nada de assimetrico (e' so' o retangulo do vao), e a diferenca nao e'
    ruido - e' um deslocamento fixo por tipo de familia.

    Robusto a QUALQUER rotacao da familia: os pontos da geometria sao
    projetados nos eixos LOCAIS da propria instancia (Transform.BasisX/
    BasisY), nunca em X/Y do mundo - entao uma abertura desenhada em
    diagonal e' medida igual a uma ortogonal (a bounding box do mundo, por
    outro lado, ficaria bem maior que o vao real nesse caso).

    Devolve (center_xy, measured_width_ft) - `measured_width_ft` e' a
    extensao da geometria ao longo do eixo LOCAL X da familia, para quem
    chama poder CONFERIR contra `Largura_abertura` antes de confiar neste
    centro (ver _build_opening_dict). Devolve (None, None) se a familia nao
    expuser geometria utilizavel.
    """
    points = _collect_instance_geometry_points(inst)
    if not points:
        return None, None

    transform = inst.GetTransform()
    origin = XYZ(transform.Origin.X, transform.Origin.Y, 0.0)
    basis_x = XYZ(transform.BasisX.X, transform.BasisX.Y, 0.0)
    if basis_x.GetLength() < 1e-9:
        return None, None
    basis_x = basis_x.Normalize()
    basis_y = XYZ(-basis_x.Y, basis_x.X, 0.0)  # perpendicular em planta

    us, vs = [], []
    for p in points:
        rel = XYZ(p.X, p.Y, 0.0) - origin
        us.append(rel.DotProduct(basis_x))
        vs.append(rel.DotProduct(basis_y))

    u_mid = (min(us) + max(us)) / 2.0
    v_mid = (min(vs) + max(vs)) / 2.0
    center = origin + basis_x * u_mid + basis_y * v_mid
    return center, (max(us) - min(us))


def _build_opening_dict(inst, allow_bbox_fallback):
    """Monta o dict de UMA abertura (porta/janela) a partir da instancia
    `inst`, em unidade interna (pes): centro em planta, largura do vao e a
    elevacao absoluta do peitoril e da verga.

    A largura vem do parametro `Largura_abertura`, NAO da bounding box 3D:
    a bounding box inclui qualquer geometria visivel da familia (moldura,
    indicador de sentido de abertura, soleira) que costuma passar do vao
    real, o que alargaria/deslocaria o recorte da parede mesmo com a
    familia bem posicionada. Como o resultado e' sempre projetado sobre a
    direcao de CADA parede (ver _project_opening_on_line), tambem nao
    importa qual eixo local da familia corresponde a largura.

    `allow_bbox_fallback` vale para elementos que o usuario SELECIONOU
    explicitamente como porta/janela: ali a intencao ja' esta declarada, e
    seria pior ignorar a selecao do que estimar as dimensoes que faltam a
    partir da bounding box. Na varredura automatica ele e' False - sem os
    tres parametros nao ha como afirmar que a familia e' uma abertura, e
    chutar dimensoes recortaria paredes por engano.

    Devolve (opening_dict, usou_fallback) ou (None, False) se nem assim for
    possivel descrever a abertura.
    """
    width_ft = _lookup_param_value(inst, [OPENING_WIDTH_PARAM])
    height_ft = _lookup_param_value(inst, [OPENING_HEIGHT_PARAM])
    sill_ft = _lookup_param_value(inst, [OPENING_SILL_PARAM])
    missing_params = width_ft is None or height_ft is None or sill_ft is None

    # PERFORMANCE: no modo automatico (`allow_bbox_fallback=False`, ver
    # get_opening_instances), um elemento sem os 3 parametros e' descartado
    # de qualquer jeito logo abaixo - a bbox NUNCA seria usada para ele.
    # get_BoundingBox e' uma chamada real a' API do Revit (nao um campo em
    # cache), repetida aqui para TODO FamilyInstance do projeto (mobiliario,
    # tubulacao, estrutura etc. - a imensa maioria nunca e' porta/janela) -
    # varrer um projeto real com milhares de FamilyInstance pagava essa
    # chamada para cada um deles so' para descartar o resultado no passo
    # seguinte. Adiar a busca para DEPOIS deste corte precoce poupa
    # exatamente esse trabalho, sem mudar nenhum resultado (o `bbox` so'
    # e' lido abaixo quando `missing_params` for True E `allow_bbox_fallback`
    # for True, ou mais adiante como fallback do ponto de insercao).
    if missing_params and not allow_bbox_fallback:
        return None, False

    bbox = inst.get_BoundingBox(None)
    bbox_center_xy = None
    if bbox is not None:
        bbox_mid = (bbox.Min + bbox.Max) * 0.5
        bbox_center_xy = XYZ(bbox_mid.X, bbox_mid.Y, 0.0)

    used_fallback = False
    if missing_params:
        if bbox is None:
            return None, False
        # Estimativa a partir da geometria real da familia selecionada.
        # A largura usa o MAIOR lado horizontal da bounding box: numa porta
        # ou janela o vao e' sempre a maior dimensao em planta, enquanto o
        # lado menor e' a espessura da folha/marco.
        used_fallback = True
        if width_ft is None:
            width_ft = max(bbox.Max.X - bbox.Min.X, bbox.Max.Y - bbox.Min.Y)
        if height_ft is None:
            height_ft = bbox.Max.Z - bbox.Min.Z

    if width_ft is None or width_ft <= 1e-6:
        return None, False
    if height_ft is None or height_ft <= 1e-6:
        return None, False

    location = inst.Location
    if isinstance(location, LocationPoint):
        insertion_point = location.Point
    else:
        if bbox is None:
            return None, False
        insertion_point = (bbox.Min + bbox.Max) * 0.5

    # Centro do vao: preferir o centro da GEOMETRIA REAL da familia (o
    # retangulo do vao que ela desenha) ao ponto de insercao, que nestas
    # familias fica sistematicamente deslocado - ver a nota extensa em
    # _opening_center_from_geometry. So' e' aceito quando a largura MEDIDA
    # na geometria confere com `Largura_abertura` (ver
    # OPENING_GEOMETRY_WIDTH_TOLERANCE_FT): isso prova que a geometria e' o
    # vao puro, sem folha/soleira/moldura que deslocariam o centro medido.
    center_xy = XYZ(insertion_point.X, insertion_point.Y, 0.0)
    center_source = "insercao"
    geometry_center, measured_width_ft = _opening_center_from_geometry(inst, width_ft)
    if (geometry_center is not None and measured_width_ft is not None and
            abs(measured_width_ft - width_ft) <= OPENING_GEOMETRY_WIDTH_TOLERANCE_FT):
        center_xy = geometry_center
        center_source = "geometria"

    level = doc.GetElement(inst.LevelId) if inst.LevelId != ElementId.InvalidElementId else None
    level_elevation_ft = level.Elevation if isinstance(level, Level) else insertion_point.Z
    level_offset_ft = _lookup_param_value(
        inst, [OPENING_LEVEL_OFFSET_PARAM, u"Elevação do nível", u"Elevacao"]
    ) or 0.0

    base_z_abs = level_elevation_ft + level_offset_ft
    if sill_ft is None:
        # Sem o parametro Peitoril: a base real da geometria da familia
        # (bounding box) e' a melhor medida disponivel do peitoril.
        sill_z_abs = bbox.Min.Z
    else:
        sill_z_abs = base_z_abs + sill_ft
    head_z_abs = sill_z_abs + height_ft

    # Direcao LOCAL X da familia (a "mao" dela) em planta - so' para o log
    # de diagnostico por abertura (ver build_opening_trace_log): permite
    # conferir se a familia esta girada como se espera em relacao ao eixo da
    # parede a que ela foi associada.
    try:
        transform = inst.GetTransform()
        hand_xy = XYZ(transform.BasisX.X, transform.BasisX.Y, 0.0)
        hand_xy = hand_xy.Normalize() if hand_xy.GetLength() > 1e-9 else None
    except Exception:
        hand_xy = None

    return {
        "center_xy": center_xy,
        "center_source": center_source,
        "insertion_xy": XYZ(insertion_point.X, insertion_point.Y, 0.0),
        "bbox_center_xy": bbox_center_xy,
        "hand_xy": hand_xy,
        "width_ft": width_ft,
        "sill_z_abs": sill_z_abs,
        "head_z_abs": head_z_abs,
        "element_id": inst.Id.ToString(),
        # ElementId de verdade (nao a string) - necessario para
        # SetElementOverrides no realce azul de incompatibilidade de
        # modulacao (ver evaluate_opening_modulation/_apply_solid_color_override).
        "element_id_obj": inst.Id,
    }, used_fallback


def get_opening_instances():
    """Varre o projeto INTEIRO e devolve as aberturas (portas/janelas ou
    qualquer familia equivalente) identificadas SOMENTE pela presenca dos
    parametros `Largura_abertura`, `Altura_abertura` e `Peitoril`
    (instancia OU tipo) - deliberadamente alheio a categoria/nome da
    familia, ja' que no projeto do usuario essas aberturas sao familias de
    Mobiliario hospedadas em Nivel, nao em parede.

    E' o modo AUTOMATICO, usado quando o usuario opta por nao selecionar as
    portas/janelas manualmente (ver ask_opening_instances)."""
    openings = []
    instances = FilteredElementCollector(doc).OfClass(FamilyInstance).WhereElementIsNotElementType()
    for inst in instances:
        opening, _ = _build_opening_dict(inst, False)
        if opening is not None:
            openings.append(opening)
    return openings


def get_openings_from_selection():
    """Deixa o usuario SELECIONAR no modelo os elementos de Mobiliario (ou
    de qualquer categoria) que representam portas e janelas, e devolve
    `(aberturas, quantidade_ignorada, quantidade_estimada_por_bounding_box)`.

    Selecionar explicitamente e' mais confiavel que a varredura automatica
    por parametros: garante que o script trate como abertura exatamente os
    elementos que o usuario considera porta/janela - nem a mais (um movel
    qualquer que por acaso tenha parametros de mesmo nome) nem a menos (uma
    porta cuja familia nao tenha os tres parametros esperados, que a
    varredura automatica descartaria em silencio).

    Devolve `(None, 0, 0)` se o usuario cancelar a selecao (ESC), para que
    quem chamou possa decidir o que fazer.
    """
    try:
        refs = uidoc.Selection.PickObjects(
            ObjectType.Element,
            "Selecione as portas/janelas (Mobiliario) e clique em Concluir na barra de opcoes"
        )
    except Exception:
        return None, 0, 0  # usuario cancelou com ESC

    openings = []
    skipped = 0
    estimated = 0
    for ref in refs:
        element = doc.GetElement(ref.ElementId)
        if not isinstance(element, FamilyInstance):
            skipped += 1
            continue
        opening, used_fallback = _build_opening_dict(element, True)
        if opening is None:
            skipped += 1
            continue
        if used_fallback:
            estimated += 1
        openings.append(opening)

    return openings, skipped, estimated


def collect_opening_instances(mode, perf_stats=None):
    """Coleta as portas/janelas conforme o modo JA ESCOLHIDO na janela de
    configuracao (`mode`: "pick" = selecionar no modelo, "auto" = varrer o
    projeto pelos parametros) e devolve `(aberturas, mensagem_de_resumo)`.

    A PERGUNTA saiu daqui de proposito: ela agora e' um par de opcoes na
    janela unica de configuracao (ver _SetupForm), junto com Layer, Nivel,
    altura e espessuras - antes era mais uma caixa modal no meio do fluxo,
    numa ordem que o usuario nao controlava.

    Sao dois modos, porque as duas situacoes reais sao diferentes:
      - SELECIONAR no modelo (recomendado): o usuario aponta exatamente
        quais familias de Mobiliario representam portas/janelas. Necessario
        porque essas aberturas frequentemente NAO estao desenhadas no DWG -
        existem so' no modelo do Revit - e portanto sao a unica fonte de
        informacao sobre onde a parede deve CONTINUAR (verga/peitoril) em
        vez de terminar na linha de fechamento do desenho.
      - Detectar AUTOMATICAMENTE todas as familias que tenham os tres
        parametros de abertura, como nas versoes anteriores do script.

    `perf_stats`, se fornecido (lista mutavel - ver PERFORMANCE em main()),
    recebe UMA entrada (rotulo, segundos, detalhe) com o tempo gasto no modo
    escolhido. No modo "pick" isso inclui o tempo de SELECAO INTERATIVA do
    usuario (PickObjects so' retorna quando ele clica em Concluir/ESC) -
    misturado com o processamento de verdade (_build_opening_dict por
    elemento selecionado), porque nao da' para separar os dois sem alterar
    o retorno de get_openings_from_selection; ainda assim, contrastar esse
    tempo com o do modo "auto" (que NUNCA espera o usuario - so' varre o
    projeto) e com a contagem de elementos e' o suficiente para saber se o
    gargalo esta' na selecao em si ou no processamento por elemento.
    """
    t0 = time.time()
    if mode != "pick":
        openings = get_opening_instances()
        if perf_stats is not None:
            perf_stats.append((
                "Coleta de aberturas (modo automatico)", time.time() - t0,
                "{} FamilyInstance no projeto inteiro viraram abertura valida".format(len(openings))
            ))
        return openings, "modo automatico (varredura por parametros)"

    openings, skipped, estimated = get_openings_from_selection()
    if openings is None:
        # Cancelou a selecao - cai para o modo automatico em vez de abortar
        # a execucao inteira.
        fallback = get_opening_instances()
        if perf_stats is not None:
            perf_stats.append((
                "Coleta de aberturas (selecao cancelada -> modo automatico)",
                time.time() - t0, "{} abertura(s) encontrada(s)".format(len(fallback))
            ))
        return fallback, "selecao cancelada - usado o modo automatico"

    if perf_stats is not None:
        perf_stats.append((
            "Coleta de aberturas (selecao manual - inclui o tempo de clique do usuario)",
            time.time() - t0,
            "{} elemento(s) selecionado(s), {} ignorado(s), {} estimado(s) por bounding box".format(
                len(openings), skipped, estimated
            )
        ))

    note = "{} elemento(s) selecionado(s) manualmente".format(len(openings))
    if estimated:
        note += (
            "; {} sem os parametros {}/{}/{}, com dimensoes estimadas pela "
            "geometria da familia".format(
                estimated, OPENING_WIDTH_PARAM, OPENING_HEIGHT_PARAM, OPENING_SILL_PARAM
            )
        )
    if skipped:
        note += "; {} ignorado(s) por nao ser possivel medir o vao".format(skipped)
    return openings, note


# _project_opening_raw, _project_opening_on_line, _merge_opening_matches,
# find_openings_on_line, assign_openings_to_walls moraram para
# core/engine/wall_pairing.py (2026-08-26, "arquitetura do modelador
# externo") - reimportadas acima via `from core.engine.wall_pairing
# import *` (linha ~862). Nenhuma formula mudou, so' o arquivo.


def classify_unassociated_opening_reason(op, walls_to_create):
    """Determina o motivo mais provavel pelo qual `op` (uma abertura
    selecionada no Revit) NAO foi associada a nenhuma parede em
    `walls_to_create` - usada no log final para listar, abertura por
    abertura, o motivo (ver assign_openings_to_walls/main()).

    Compara com a parede MAIS PROXIMA (menor distancia perpendicular) dentre
    TODAS as criadas nesta execucao, mesmo as que falharam no criterio de
    tolerancia/alcance - para reportar "quao perto" ela chegou de ser
    associada, em vez de so' dizer "nao associada"."""
    if not walls_to_create:
        return "nenhuma parede foi criada nesta execucao para comparar"

    best = None  # (perp_dist, thickness_ft, centerline, t_lo, t_hi)
    for centerline, thickness_ft, _locked in walls_to_create:
        t_lo, t_hi, perp_dist = _project_opening_on_line(centerline, op)
        if best is None or perp_dist < best[0]:
            best = (perp_dist, thickness_ft, centerline, t_lo, t_hi)

    best_perp_ft, best_thickness_ft, best_centerline, t_lo, t_hi = best
    dist_cm = round(best_perp_ft / FEET_PER_METER * 100.0, 1)
    thickness_cm = round(best_thickness_ft / FEET_PER_METER * 100.0, 1)
    max_perp_dist_ft = best_thickness_ft / 2.0 + OPENING_ASSOC_TOLERANCE_FT

    if best_perp_ft > max_perp_dist_ft:
        return (
            "parede criada mais proxima (espessura {}cm) fica a {}cm do eixo - "
            "alem da tolerancia de associacao (meia-espessura + {}cm); confira se "
            "a familia esta sobre a linha do CAD certa, ou se a parede dela nao "
            "foi criada (nenhuma parede da espessura/posicao certa por perto)"
        ).format(thickness_cm, dist_cm, round(OPENING_ASSOC_TOLERANCE_M * 100.0, 1))

    axis_len_ft = best_centerline.GetEndPoint(0).DistanceTo(best_centerline.GetEndPoint(1))
    covered_ft = min(t_hi, axis_len_ft) - max(t_lo, 0.0)
    if covered_ft <= MIN_SEGMENT_LENGTH_FT:
        # A parede esta' na distancia/posicao certa, mas sua EXTENSAO (o
        # comprimento do eixo, ja depois de qualquer corte por linha de
        # fechamento/testa) termina antes de alcancar o vao desta abertura -
        # mede exatamente quanto (em cm) faltou E devolve a coordenada real
        # (mundo, em cm) da ponta da parede mais proxima da abertura, para o
        # usuario conseguir localizar EXATAMENTE esse ponto no CAD/Revit -
        # distingue tambem um corte raso (poucos cm/uma espessura de parede -
        # jamba mal reconhecida) de uma parede que, na pratica, nao existe
        # perto dali (faltando METROS - a "mais proxima" e' so' outra parede
        # qualquer, coincidentemente colinear, em outro trecho/comodo da
        # planta - comum em plantas com unidades repetidas/espelhadas).
        if t_hi <= 0.0:
            shortfall_ft = -t_hi
            near_end_point = best_centerline.GetEndPoint(0)
        elif t_lo >= axis_len_ft:
            shortfall_ft = t_lo - axis_len_ft
            near_end_point = best_centerline.GetEndPoint(1)
        else:
            shortfall_ft = 0.0
            near_end_point = best_centerline.GetEndPoint(0)
        shortfall_cm = round(shortfall_ft / FEET_PER_METER * 100.0, 1)
        axis_len_cm = round(axis_len_ft / FEET_PER_METER * 100.0, 1)
        end_point_cm = "({:.0f}, {:.0f})".format(
            near_end_point.X / FEET_PER_METER * 100.0, near_end_point.Y / FEET_PER_METER * 100.0
        )

        if shortfall_cm <= 100.0:
            return (
                "parede criada mais proxima esta' na distancia/posicao certa ({}cm "
                "do eixo, espessura {}cm, comprimento {}cm) e sua ponta em {} fica a "
                "SO' {}cm do vao desta abertura - foi cortada curta demais por pouco "
                "(confira se ha' uma linha de FECHAMENTO/testa do CAD perto desse "
                "ponto que nao foi reconhecida como jamba da propria abertura)"
            ).format(dist_cm, thickness_cm, axis_len_cm, end_point_cm, shortfall_cm)

        return (
            "NENHUMA parede criada nesta execucao chega perto desta abertura - a "
            "'mais proxima' esta' a {}cm de distancia (ponta dela em {}), o que "
            "sugere ser apenas outra parede colinear em outro trecho/comodo da "
            "planta, nao a parede real desta abertura. O trecho de parede que "
            "deveria conter esta abertura provavelmente nunca foi pareado (linhas "
            "de face sem par valido perto desta posicao) - confira as coordenadas "
            "desta abertura diretamente no CAD."
        ).format(shortfall_cm, end_point_cm)

    return (
        "parede compativel foi encontrada (a {}cm do eixo), mas outra abertura "
        "mais proxima levou a exclusividade nesta mesma parede"
    ).format(dist_cm)


def build_opening_trace_log(assignments, walls_to_create, created_opening_segments, max_entries=12):
    """Monta as linhas do log que rastreiam, abertura por abertura, TODO o
    caminho do calculo do trecho de parede (verga/peitoril) dela:

        Largura_abertura (parametro lido)
        -> centro do vao usado, e de ONDE ele veio (geometria da familia ou
           ponto de insercao), com a diferenca entre os dois
        -> orientacao (mao) da familia e direcao do eixo da parede associada
        -> pontos inicial/final CALCULADOS para o trecho, em coordenadas de
           mundo, e o comprimento resultante
        -> pontos inicial/final EFETIVAMENTE ENVIADOS para Wall.Create, e os
           que o Revit devolveu depois de criada a parede

    E' o que permite responder "em qual etapa a posicao/comprimento mudou?"
    sem precisar reinstrumentar o script a cada duvida: se o comprimento
    calculado ja sai diferente de Largura_abertura, o problema esta no
    centro/projecao; se sai certo mas o enviado difere, esta no fatiamento
    (build_wall_segments); se o enviado esta certo mas o devolvido pelo
    Revit nao, e' reposicionamento do proprio Revit (WallType/Linha de
    Referencia).

    `created_opening_segments` e' a lista montada no loop de criacao com os
    pontos realmente usados em Wall.Create; a correspondencia com cada
    abertura e' feita por parede + proximidade dos extremos, porque um mesmo
    eixo pode ter varios trechos de abertura.
    """
    lines = []
    if not assignments:
        return lines

    def cm(value_ft):
        return value_ft / FEET_PER_METER * 100.0

    def fmt_pt(p):
        return "({:.2f}, {:.2f})".format(cm(p.X), cm(p.Y))

    def fmt_dir(v):
        if v is None:
            return "n/d"
        return "({:.4f}, {:.4f})".format(v.X, v.Y)

    ordered = sorted(assignments, key=lambda a: -abs(
        a["op"]["center_xy"].DistanceTo(a["op"]["insertion_xy"])
        if a["op"].get("insertion_xy") is not None else 0.0
    ))

    lines.append("")
    lines.append("--- RASTREIO DO CALCULO POR ABERTURA (maiores correcoes de centro primeiro) ---")
    lines.append(
        "Todas as coordenadas em cm. 'centro (geometria)' = centro do retangulo "
        "que a propria familia desenha; 'centro (insercao)' = ponto de insercao "
        "da instancia. Quando os dois diferem, o script usa o da GEOMETRIA (ver "
        "_opening_center_from_geometry)."
    )

    for entry in ordered[:max_entries]:
        op = entry["op"]
        wall_idx = entry["wall_idx"]
        centerline = walls_to_create[wall_idx][0]
        thickness_ft = walls_to_create[wall_idx][1]

        axis_p0_raw = centerline.GetEndPoint(0)
        axis_p1_raw = centerline.GetEndPoint(1)
        axis_p0 = XYZ(axis_p0_raw.X, axis_p0_raw.Y, 0.0)
        axis_p1 = XYZ(axis_p1_raw.X, axis_p1_raw.Y, 0.0)
        axis_dir = (axis_p1 - axis_p0).Normalize()

        calc_start = axis_p0 + axis_dir * entry["t_lo"]
        calc_end = axis_p0 + axis_dir * entry["t_hi"]
        calc_len_ft = entry["t_hi"] - entry["t_lo"]

        lines.append("")
        lines.append("  * Abertura id {} (espessura da parede: {}cm)".format(
            op.get("element_id", "?"), round(cm(thickness_ft), 1)
        ))
        lines.append("      Largura_abertura (parametro) : {}cm".format(round(cm(op["width_ft"]), 2)))
        lines.append("      centro usado ({:<9})     : {}".format(
            op.get("center_source", "?"), fmt_pt(op["center_xy"])
        ))
        if op.get("insertion_xy") is not None:
            shift_ft = op["center_xy"].DistanceTo(op["insertion_xy"])
            lines.append("      centro (insercao da familia) : {}  -> corrigido em {}cm".format(
                fmt_pt(op["insertion_xy"]), round(cm(shift_ft), 2)
            ))
        lines.append("      orientacao da familia (X)    : {}".format(fmt_dir(op.get("hand_xy"))))
        lines.append("      direcao do eixo da parede    : {}".format(fmt_dir(axis_dir)))
        lines.append("      distancia ao eixo (perp.)    : {}cm".format(
            round(cm(entry.get("perp_dist_ft", 0.0)), 3)
        ))
        lines.append("      CALCULADO  inicio {}  fim {}  -> comprimento {}cm".format(
            fmt_pt(calc_start), fmt_pt(calc_end), round(cm(calc_len_ft), 2)
        ))
        width_error_cm = round(cm(calc_len_ft - op["width_ft"]), 3)
        lines.append("      diferenca para Largura_abertura: {}cm{}".format(
            width_error_cm, "  <-- CONFERIR" if abs(width_error_cm) > 0.1 else " (exato)"
        ))

        # Trecho(s) realmente enviado(s) ao Revit para esta abertura: mesmo
        # eixo e extremos coincidentes (dentro de 1cm) com o calculado.
        matches = [
            seg for seg in created_opening_segments
            if seg["wall_idx"] == wall_idx and
            min(
                max(seg["sent_p0"].DistanceTo(calc_start), seg["sent_p1"].DistanceTo(calc_end)),
                max(seg["sent_p0"].DistanceTo(calc_end), seg["sent_p1"].DistanceTo(calc_start)),
            ) <= (0.01 * FEET_PER_METER)
        ]
        if not matches:
            lines.append("      ENVIADO ao Revit             : nenhum segmento criado para este vao")
        for seg in matches:
            lines.append(
                "      ENVIADO ao Revit  inicio {}  fim {}  (altura {}cm, offset da base {}cm)".format(
                    fmt_pt(seg["sent_p0"]), fmt_pt(seg["sent_p1"]),
                    round(cm(seg["height_ft"]), 1), round(cm(seg["base_offset_ft"]), 1)
                )
            )
            if seg.get("final_p0") is not None:
                dev_ft = max(
                    seg["final_p0"].DistanceTo(seg["sent_p0"]),
                    seg["final_p1"].DistanceTo(seg["sent_p1"]),
                )
                dev_alt_ft = max(
                    seg["final_p0"].DistanceTo(seg["sent_p1"]),
                    seg["final_p1"].DistanceTo(seg["sent_p0"]),
                )
                dev_cm = round(cm(min(dev_ft, dev_alt_ft)), 3)
                lines.append(
                    "      DEVOLVIDO pelo Revit inicio {}  fim {}  -> desvio {}cm{}".format(
                        fmt_pt(seg["final_p0"]), fmt_pt(seg["final_p1"]), dev_cm,
                        "  <-- CONFERIR" if dev_cm > 0.1 else " (ok)"
                    )
                )

    if len(ordered) > max_entries:
        lines.append("")
        lines.append("  * ... e mais {} abertura(s) associadas (mesmo formato).".format(
            len(ordered) - max_entries
        ))

    return lines


def build_wall_segments(centerline, base_z_abs, wall_height_ft, openings_on_line):
    """Fatia a `centerline` de uma parede em um ou mais segmentos, para que
    cada abertura em `openings_on_line` fique livre apenas na sua faixa real
    (peitoril ate verga, na largura do vao) e os vazios entre essa faixa e a
    base/topo da parede sejam preenchidos com parede normalmente.

    Devolve uma lista de (sub_line, height_ft, base_offset_ft, origin), pronta
    para ser usada em Wall.Create (base_offset_ft e' relativo a `base_z_abs`,
    ou seja, ao nivel de insercao da parede). `origin` e' "cad" para um
    trecho cheio normal (determinado so' pelas linhas do AutoCAD) ou
    "abertura" para um trecho de preenchimento (verga/peitoril) cuja
    extensao horizontal foi determinada EXCLUSIVAMENTE pela abertura
    selecionada no Revit - usado so' para o log final (ver main(), secao
    "paredes/trechos gerados a partir de aberturas"), nao afeta a criacao.
    Sem aberturas associadas, devolve a propria `centerline` inteira, altura
    cheia, offset 0, origem "cad" - comportamento identico ao atual.
    """
    if not openings_on_line:
        return [(centerline, wall_height_ft, 0.0, "cad")]

    p0 = centerline.GetEndPoint(0)
    direction = (centerline.GetEndPoint(1) - p0).Normalize()
    length_ft = p0.DistanceTo(centerline.GetEndPoint(1))
    top_z_abs = base_z_abs + wall_height_ft

    def make_horizontal_full_segment(t_a, t_b):
        if t_b - t_a <= MIN_SEGMENT_LENGTH_FT:
            return None
        sub_line = Line.CreateBound(p0 + direction * t_a, p0 + direction * t_b)
        return (sub_line, wall_height_ft, 0.0, "cad")

    def make_infill_segment(t_a, t_b, seg_base_z, seg_top_z):
        if t_b - t_a <= MIN_SEGMENT_LENGTH_FT:
            return None
        if seg_top_z - seg_base_z <= MIN_SEGMENT_HEIGHT_FT:
            return None
        sub_line = Line.CreateBound(p0 + direction * t_a, p0 + direction * t_b)
        return (sub_line, seg_top_z - seg_base_z, seg_base_z - base_z_abs, "abertura")

    segments = []
    cursor_t = 0.0
    for t_lo, t_hi, sill_z_abs, head_z_abs in openings_on_line:
        # Trecho cheio (base->topo) do eixo ANTES desta abertura.
        seg = make_horizontal_full_segment(cursor_t, t_lo)
        if seg:
            segments.append(seg)

        # Preenchimento abaixo do peitoril, na largura do vao.
        seg = make_infill_segment(t_lo, t_hi, base_z_abs, min(sill_z_abs, top_z_abs))
        if seg:
            segments.append(seg)

        # Preenchimento acima da verga, na largura do vao.
        seg = make_infill_segment(t_lo, t_hi, max(head_z_abs, base_z_abs), top_z_abs)
        if seg:
            segments.append(seg)

        cursor_t = t_hi

    # Trecho cheio (base->topo) do eixo DEPOIS da ultima abertura.
    seg = make_horizontal_full_segment(cursor_t, length_ft)
    if seg:
        segments.append(seg)

    return segments


def _apply_solid_color_override(view, element_ids, color, target_doc=None):
    """Aplica um realce solido (linha + preenchimento) de `color` na `view`
    dada sobre `element_ids` - qualquer elemento (parede OU instancia de
    familia de abertura; SetElementOverrides funciona para qualquer
    elemento visivel na vista). Mecanismo generico reaproveitado pelas TRES
    cores de modulacao (ver _apply_modulation_incompatible_overrides/azul e
    _apply_broken_length_overrides/vermelho) - mesmo mecanismo, cor
    diferente. Precisa ser chamada dentro de uma Transacao aberta.

    `target_doc` (default: o `doc` do modulo, ou seja, o documento em que o
    botao foi clicado) e' o documento de onde sai o padrao de preenchimento
    solido. Precisa ser o documento da PROPRIA `view`: um ElementId de
    FillPatternElement so' vale dentro do documento que o criou, e passar um
    id do documento errado faz SetElementOverrides lancar excecao. Os
    updaters ao vivo (ver secao VALIDADOR AO VIVO...) SEMPRE passam o
    documento que receberam no Execute() - eles sao registrados APP-WIDE e
    disparam para paredes de QUALQUER documento aberto, nao so' daquele em
    que o botao foi clicado."""
    if not element_ids:
        return

    fill_doc = target_doc if target_doc is not None else doc
    solid_fill_id = None
    for fp in FilteredElementCollector(fill_doc).OfClass(FillPatternElement):
        if fp.GetFillPattern().IsSolidFill:
            solid_fill_id = fp.Id
            break

    ogs = OverrideGraphicSettings()
    ogs.SetProjectionLineColor(color)
    ogs.SetProjectionLineWeight(6)
    if solid_fill_id is not None:
        ogs.SetSurfaceForegroundPatternColor(color)
        ogs.SetSurfaceForegroundPatternId(solid_fill_id)
        ogs.SetSurfaceForegroundPatternVisible(True)
        ogs.SetCutForegroundPatternColor(color)
        ogs.SetCutForegroundPatternId(solid_fill_id)
        ogs.SetCutForegroundPatternVisible(True)

    for eid in element_ids:
        view.SetElementOverrides(eid, ogs)


# ==========================================
# VALIDACAO DE MODULACAO DE BLOCOS ESTRUTURAIS
# (preparacao para o futuro script de paginacao automatica de blocos - esta
# etapa NAO corrige nada sozinha, so' identifica e sinaliza em azul; as
# funcoes abaixo sao de proposito geral - o futuro script de blocos pode
# importa-las diretamente, sem depender de nada do fluxo interativo de
# main())
# ==========================================

# REGRA DE DIGITO FINAL DAS PAREDES - REMOVIDA COMPLETAMENTE (2026-08-21,
# pedido explicito do usuario). A antiga MODULATION_VALID_LAST_DIGITS_CM
# ((0, 1, 6, 9)) e a PIER_AT_OPENING_VALID_LAST_DIGITS_CM (terminar em 0/5)
# NAO EXISTEM MAIS e nao devem voltar: eram um ARREDONDAMENTO ARTIFICIAL da
# dimensao da parede - olhavam so' o ultimo digito do comprimento, sem saber
# o que os encontros L/T/X e as aberturas reservam de verdade em cada ponta.
# Consequencia pratica: reprovavam paredes perfeitamente construiveis (uma
# parede de 111cm ou de 129cm fecha com o catalogo real, cada uma com a sua
# combinacao de juntas de contorno) e aprovavam outras que nao fechavam.
#
# ==========================================
# ARITMETICA DE BLOCOS/PILARETES - EXTRAIDA para
# core/engine/modulation_math.py
#
# OPENING_VALID_LAST_DIGITS_CM, PIER_AT_OPENING_TOLERANCE_M/FT,
# OPENING_SOLVER_MAX_WIDTH_DELTA_CM, OPENING_SOLVER_MAX_AXIS_DELTA_CM,
# BLOCK_LENGTHS_CM, BLOCK_WIDTH_CM, BLOCK_JOINT_CM, BLOCK_OPENING_JOINT_CM,
# PIER_MODULE_CM, BLOCK_COMPENSATORS_ENABLED_BY_DEFAULT,
# MODULATION_WHOLE_CM_TOLERANCE_CM, PIER_LAYOUT_TOLERANCE_CM,
# pack_pier_with_blocks, _is_valid_opening_width_cm, solve_opening_modulation,
# PIER_BOUNDARY_JOINTS_CM, PIER_BOUNDARY_JOINT_COMBINATIONS_CM,
# _pier_remaining_cm, pier_closes_with_blocks_cm,
# wall_length_closes_with_blocks_cm, _wall_length_snap_targets_cm,
# nearest_block_lengths_cm, nearest_wall_lengths_cm, suggested_block_length_cm,
# evaluate_wall_block_length, _nearest_valid_lengths_cm,
# _suggested_valid_length_cm e _evaluate_modulation_length moraram AQUI ate'
# esta extracao (ver ARQUITETURA_INTERATIVA.md) - nenhuma formula mudou, so'
# o arquivo. `_wall_length_cm` (le' `wall.Location`, Revit de verdade) NAO
# foi movida - continua logo abaixo, de proposito, para o modulo novo ficar
# 100% puro (nem os tipos XYZ/Line - so' numeros/tuplas em centimetros).
from core.engine.modulation_math import *  # noqa: F401,F403
# ==========================================


# ==========================================
# ORIGEM DAS REGRAS DESTE SOLVER (secoes 16/17/27 do prompt de modulacao) -
# este script resolve GEOMETRIA de modulacao, nunca desempenho estrutural
# (resistencia de prisma, argamassa, graute) - essa verificacao depende do
# sistema construtivo/materiais/ensaios do projeto e fica FORA de escopo
# aqui, propositalmente (nao ha' nenhum valor de resistencia hardcoded em
# lugar nenhum deste arquivo). A ABNT NBR 16868 (Alvenaria estrutural) e' a
# referencia normativa GERAL do sistema construtivo, mas as constantes e
# regras abaixo tem origens DIFERENTES e nao devem ser lidas como se
# tivessem uma so' fonte - cada uma esta' rotulada onde e' definida:
#
#   REGRA GEOMETRICA DA FAMILIA - lida em runtime da geometria/parametros
#   reais das FamilySymbol do projeto (comprimento/altura/largura/celulas),
#   nunca hardcoded por familia - ver load_fixed_block_catalog,
#   _extract_block_cells_local_from_symbol, GetCentralVoid-equivalente
#   (_block_smaller_cell_sign/_block_more_central_cell).
#
#   REGRA DO PROJETO (fornecida pelo usuario/plano deste sistema de blocos
#   especifico, NAO extraida de norma) - ex.: BLOCK_JOINT_CM=1cm,
#   FIRST_COURSE_Z_OFFSET_CM=1cm + incremento de 20cm por fiada, L=2xB34,
#   T=B54+B34, X=2xB54, VERTICAL_JOINT_STAGGER_TOLERANCE_CM. Estes valores
#   vieram do prompt de modulacao e/ou de medicao da familia real deste
#   projeto - NAO estao vinculados a um artigo especifico da NBR 16868
#   (nenhuma correspondencia normativa foi confirmada) e devem ser tratados
#   como parametros deste sistema de blocos, nao como exigencia normativa.
#
#   REGRA CONFIGURAVEL PELO USUARIO - `allow_compensators` (permite blocos
#   de ajuste C09/C04 no preenchimento) e o catalogo fixo em
#   BLOCK_FAMILY_CATALOG_DEFINITIONS (qual familia/tipo do Revit corresponde
#   a cada codigo logico B39/B34/B54/B19/C09/C04).
#
# Sempre que uma regra acima parecer exigencia normativa mas a origem real
# for "regra deste projeto/prompt", isso deve ficar sinalizado (este bloco
# de comentarios e' essa sinalizacao) em vez de apresentado como requisito
# da NBR 16868 sem fundamento confirmado.
# ==========================================


# ==========================================
# AUDITORIA DE ABERTURAS EM ALVENARIA JA CONSTRUIDA - EXTRAIDA para
# core/engine/opening_audit.py
#
# OPENING_SYSTEM_1_VERGA_CONTRAVERGA, OPENING_SYSTEM_2_CANALETA,
# OPENING_SYSTEM_UNKNOWN, OPENING_GAP_MIN_CM, OPENING_GAP_MAX_CM,
# OPENING_MIN_CONSEC_COURSES, OPENING_RUN_EDGE_MATCH_TOLERANCE_CM,
# OPENING_DOOR_TOUCHES_BASE_TOLERANCE_CM, CUT_BLOCK_JAMB_JUSTIFICATION_MAX_CM,
# _family_name_matches_keyword, is_canaleta_family_name,
# is_cortado_family_name, is_verga_or_contraverga_family_name,
# merge_axis_intervals, gaps_between_intervals,
# detect_wall_openings_from_courses, nearest_opening_jamb_distance_cm e
# is_cut_block_justified_by_opening moraram AQUI ate' esta extracao (ver
# REGRAS_MODULACAO_BLOCOS.md secao 10 e ARQUITETURA_INTERATIVA.md) -
# nenhuma formula mudou, so' o arquivo. Modulo 100% puro (nenhuma
# dependencia do Revit).
from core.engine.opening_audit import *  # noqa: F401,F403
# ==========================================


def _wall_lines_from_generic_model_instances(target_doc, dim_param_names=("Comprimento_bloco", "Comprimento", "Length")):
    """Le TODAS as instancias de 'Modelos Genericos' ja' colocadas no
    documento (paredes/blocos/canaletas/vergas ja' construidos - nunca
    ativa nenhum FamilySymbol, nunca abre Transaction, 100% leitura) e
    agrupa em 'linhas' de parede por (nivel mais proximo, orientacao,
    coordenada perpendicular arredondada em 5cm) - mesma tecnica ja'
    validada via MCP contra TORRE EASY-LO-R00 (REGRAS_MODULACAO_BLOCOS.md
    secao 10). Devolve dict {(level_index, rot_deg, perp_key_cm):
    [(z_cm, start_cm, end_cm, family_name), ...]}.

    So' funcao Revit-dependente desta secao SEM equivalente pura, porque
    precisa mesmo de FilteredElementCollector/geometria - as decisoes de
    negocio (onde estao os vaos, qual e' porta/janela, o que e' bloco
    cortado justificado) ficam nas funcoes puras acima, chamadas com o
    resultado desta."""
    levels = sorted(
        FilteredElementCollector(target_doc).OfClass(Level),
        key=lambda lv: lv.Elevation,
    )
    level_elev_cm = [lv.Elevation / FEET_PER_METER * 100.0 for lv in levels]

    def _nearest_level_index(z_cm):
        best_i, best_d = 0, None
        for i, elev in enumerate(level_elev_cm):
            d = abs(z_cm - elev)
            if best_d is None or d < best_d:
                best_d, best_i = d, i
        return best_i

    lines = {}
    instances = FilteredElementCollector(target_doc) \
        .OfCategory(BuiltInCategory.OST_GenericModel) \
        .WhereElementIsNotElementType()
    for inst in instances:
        symbol = getattr(inst, "Symbol", None)
        if symbol is None:
            continue
        length_cm = _type_param_cm(symbol, dim_param_names)
        if length_cm is None:
            continue
        try:
            family_name = symbol.Family.Name
        except Exception:
            family_name = None
        try:
            transform = inst.GetTransform()
            origin = transform.Origin
            rotation = getattr(inst, "Rotation", 0.0) or 0.0
        except Exception:
            continue
        rot_deg = int(round((rotation * 180.0 / 3.14159265358979) / 90.0) * 90 % 180)
        x_cm = origin.X / FEET_PER_METER * 100.0
        y_cm = origin.Y / FEET_PER_METER * 100.0
        z_cm = origin.Z / FEET_PER_METER * 100.0
        if rot_deg == 0:
            perp_key = round(y_cm / 5.0) * 5
            axis_pos = x_cm
        else:
            perp_key = round(x_cm / 5.0) * 5
            axis_pos = y_cm
        level_index = _nearest_level_index(z_cm)
        key = (level_index, rot_deg, perp_key)
        lines.setdefault(key, []).append(
            (round(z_cm, 1), axis_pos - length_cm / 2.0, axis_pos + length_cm / 2.0, family_name)
        )
    return lines, [lv.Name for lv in levels]


def detect_opening_system_for_level(target_doc, level_name, min_instances=1):
    """Regra 10.1: decide se um NIVEL usa Sistema 1 (VERGA JANELA/
    CONTRAVERGA dedicadas) ou Sistema 2 (canaleta substituindo verga/
    contraverga), por AMOSTRAGEM DIRETA das familias realmente colocadas
    naquele nivel - nunca assume, nunca mistura os dois automaticamente
    (REGRAS_MODULACAO_BLOCOS.md secao 10.1: escolha de sistema deve ser
    isso, uma deteccao/config explicita, nao inferencia peca a peca).
    100% leitura, nenhuma Transaction."""
    levels = sorted(
        FilteredElementCollector(target_doc).OfClass(Level),
        key=lambda lv: lv.Elevation,
    )
    target_level = next((lv for lv in levels if lv.Name == level_name), None)
    if target_level is None:
        return OPENING_SYSTEM_UNKNOWN
    elevations = [lv.Elevation for lv in levels]
    idx = levels.index(target_level)
    lo = elevations[idx]
    hi = elevations[idx + 1] if idx + 1 < len(elevations) else lo + (elevations[idx] - elevations[idx - 1] if idx > 0 else 1e9)

    n_sistema1 = 0
    n_canaleta = 0
    instances = FilteredElementCollector(target_doc) \
        .OfCategory(BuiltInCategory.OST_GenericModel) \
        .WhereElementIsNotElementType()
    for inst in instances:
        symbol = getattr(inst, "Symbol", None)
        if symbol is None:
            continue
        try:
            family_name = symbol.Family.Name
        except Exception:
            family_name = None
        try:
            z = inst.GetTransform().Origin.Z
        except Exception:
            continue
        if not (lo - 1e-6 <= z < hi + 1e-6):
            continue
        if is_verga_or_contraverga_family_name(family_name):
            n_sistema1 += 1
        elif is_canaleta_family_name(family_name):
            n_canaleta += 1

    if n_sistema1 >= min_instances and n_canaleta == 0:
        return OPENING_SYSTEM_1_VERGA_CONTRAVERGA
    if n_canaleta >= min_instances and n_sistema1 == 0:
        return OPENING_SYSTEM_2_CANALETA
    if n_sistema1 == 0 and n_canaleta == 0:
        return OPENING_SYSTEM_UNKNOWN
    # os dois apareceram no mesmo nivel - nao decide sozinho (secao 10.1:
    # nunca misturar automaticamente), reporta como desconhecido pro
    # chamador tratar manualmente.
    return OPENING_SYSTEM_UNKNOWN


def audit_existing_masonry_openings(target_doc, min_line_size=60):
    """Ponto de entrada da auditoria (secao 10 do REGRAS_MODULACAO_BLOCOS.md):
    100% leitura, nenhuma Transaction, nenhum save. Devolve um relatorio
    dict com, por linha de parede substancial: vaos detectados (com tipo
    provavel porta/janela) e o sistema de abertura do nivel correspondente.
    Nao gera nenhuma geometria nova - so' diagnostico, para uso manual ou
    como insumo de uma futura Etapa geradora (ainda nao implementada, ver
    secao 10 itens 10.2/10.3/10.6/10.7, todos ainda nao confirmados o
    bastante para virar codigo)."""
    lines, level_names = _wall_lines_from_generic_model_instances(target_doc)
    report = {"levels": {}, "lines": []}
    system_cache = {}
    for key, entries in lines.items():
        if len(entries) < min_line_size:
            continue
        level_index, rot_deg, perp_key = key
        level_name = level_names[level_index] if level_index < len(level_names) else None
        if level_name not in system_cache:
            system_cache[level_name] = detect_opening_system_for_level(target_doc, level_name)
        opening_system = system_cache[level_name]

        by_z = {}
        for z_cm, start_cm, end_cm, family_name in entries:
            by_z.setdefault(z_cm, []).append((start_cm, end_cm, family_name))
        courses = [(z_cm, intervals) for z_cm, intervals in by_z.items()]
        openings = detect_wall_openings_from_courses(courses)

        cut_positions = [
            (s + e) / 2.0 for _z, s, e, fam in entries if is_cortado_family_name(fam)
        ]
        cut_report = [
            {"position_cm": pos, "justificado_por_abertura":
                is_cut_block_justified_by_opening(pos, openings)}
            for pos in cut_positions
        ]

        report["lines"].append({
            "nivel": level_name, "rotacao_deg": rot_deg, "perp_cm": perp_key,
            "n_pecas": len(entries), "sistema_abertura": opening_system,
            "vaos": openings, "blocos_cortados": cut_report,
        })
    for level_name, system in system_cache.items():
        report["levels"][level_name] = system
    return report


# ==========================================
# ETAPA 1 - CATALOGO DE BLOCOS (BlockCatalog)
#
# O catalogo e' FIXO: usa sempre as MESMAS familias/tipos de Modelo
# Generico ja carregadas no projeto, identificadas por NOME EXATO de
# familia+tipo em BLOCK_FAMILY_CATALOG_DEFINITIONS (levantado uma unica vez
# por inspecao direta dos elementos reais no Revit via MCP em 2026-08-20,
# nao deduzido por prefixo de nome nem por comprimento). Nao ha' mais
# selecao/montagem manual de catalogo pelo usuario - `load_fixed_block_catalog`
# procura cada familia+tipo no documento inteiro e so' entra no catalogo se
# encontrar exatamente aquele par; o que faltar e' reportado como "familia
# ausente" (bloqueante), nunca substituido por uma peca parecida.
#
# Le as dimensoes e as CELULAS/VAZIOS reais direto da geometria da
# FamilySymbol (nao precisa de nenhuma instancia colocada no modelo - a
# geometria de uma FamilySymbol ja esta' no referencial LOCAL da familia,
# equivalente a pegar a geometria de uma instancia e aplicar o inverso da
# transformacao dela; confirmado batendo os dois metodos via MCP no bloco
# B34 real do projeto). Nao usa BoundingBox para achar as celulas (a bbox
# mede sempre ~2cm a mais que o solido real, confirmado nas 6 pecas da
# Familia 39 deste projeto - folga de renderizacao, nao geometria) - usa a
# FACE HORIZONTAL SUPERIOR do solido e os EdgeLoops dela: o loop 0 e' o
# contorno externo, os loops 1..N sao os vazios. Testado nas 6 pecas reais
# do projeto e confere exatamente com o desenho de referencia do usuario
# (pilarete 55cm = 1+34+1+19).
# ==========================================

# Familia + tipo EXATOS de cada codigo logico, tal como existem hoje no
# projeto (Modelos genericos). NAO adivinhar/trocar por outra familia
# parecida se o nome mudar - atualizar esta tabela so' depois de confirmar
# de novo a familia certa com o usuario/no Revit.
BLOCK_FAMILY_CATALOG_DEFINITIONS = {
    "B39": {"family_name": "BLOCO INTEIRO - 14x19x39", "type_name": "BLOCO INTEIRO - 14x19x39",
            "is_special_bond": False, "is_compensator": False},
    "B34": {"family_name": "BLOCO 34 - 14x19x34", "type_name": "BLOCO 34 - 14x19x34",
            "is_special_bond": True, "is_compensator": False},
    "B54": {"family_name": "BLOCO 54 - 14x19x54", "type_name": "BLOCO 54 - 14x19x54",
            "is_special_bond": True, "is_compensator": False},
    "B19": {"family_name": "MEIO BLOCO - 14x19x19", "type_name": "MEIO BLOCO - 14x19x19",
            "is_special_bond": False, "is_compensator": False},
    "C09": {"family_name": "COMPENSADOR 14x19x9", "type_name": "COMPENSADOR 14x19x9",
            "is_special_bond": False, "is_compensator": True},
    "C04": {"family_name": "PASTILHA - 14x19X4", "type_name": "PASTILHA - 14x19X4",
            "is_special_bond": False, "is_compensator": True},
}


def _type_param_cm(element, param_names):
    """Le o primeiro parametro (de instancia OU tipo) de `param_names` que
    existir, tiver valor E for do tipo Double (comprimento), devolvendo em
    CENTIMETROS. `element` pode ser a FamilySymbol (parametros de TIPO,
    onde as familias de bloco deste projeto realmente guardam
    Comprimento_bloco/Altura_bloco/Largura_bloco - confirmado nas 6 pecas
    selecionadas) ou uma FamilyInstance."""
    for name in param_names:
        try:
            param = element.LookupParameter(name)
        except Exception:
            param = None
        if param is not None and param.HasValue and param.StorageType == StorageType.Double:
            return param.AsDouble() / FEET_PER_METER * 100.0
    return None


def _find_family_symbol_by_exact_name(target_doc, family_name, type_name):
    """Procura no documento INTEIRO, por nome EXATO de familia+tipo (sem
    prefixo/heuristica/tolerancia), a FamilySymbol correspondente. Usada
    pelo catalogo fixo (BLOCK_FAMILY_CATALOG_DEFINITIONS) - devolve o
    symbol ou None se aquela familia/tipo nao estiver carregada no
    projeto."""
    for symbol in FilteredElementCollector(target_doc).OfClass(FamilySymbol):
        try:
            family_name_found = symbol.Family.Name if symbol.Family else None
            if family_name_found != family_name:
                continue
            type_name_param = symbol.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
            type_name_found = type_name_param.AsString() if type_name_param else None
            if type_name_found == type_name:
                return symbol
        except Exception:
            continue
    return None


def _extract_block_cells_local_from_symbol(symbol):
    """Extrai as celulas/vazios do bloco a partir da geometria REAL da
    `symbol` (FamilySymbol, precisa estar ATIVA - ver Activate() no
    chamador). A geometria de uma FamilySymbol ja vem no referencial LOCAL
    da propria familia (nao e' preciso nenhuma instancia colocada nem
    Transform.Inverse - confirmado batendo os dois metodos via MCP no
    bloco B34 real do projeto: mesmo resultado, diferenca <1e-10ft).

    Metodo: acha a face PLANA HORIZONTAL de MAIOR area entre os solidos da
    peca (a face superior) e le os EdgeLoops dela - loop 0 e' sempre o
    contorno externo (Revit garante essa ordem), loops 1..N sao os vazios.

    Devolve lista de dicts {"center_local": (x,y), "size_local": (dx,dy)}
    (unidades internas do Revit/ft) na ORDEM em que apareceram - vazia se
    a peca for maciça (compensador/pastilha) ou se a geometria nao puder
    ser lida (nunca lanca; falha silenciosa devolve lista vazia, o
    catalogo registra isso como aviso)."""
    try:
        options = Options()
        options.DetailLevel = ViewDetailLevel.Fine
        options.IncludeNonVisibleObjects = False
        geometry = symbol.get_Geometry(options)
        if geometry is None:
            return []
        solids = []

        def collect_solids(geom_iterable):
            for item in geom_iterable:
                if isinstance(item, Solid) and item.Volume > 1e-9:
                    solids.append(item)
                elif isinstance(item, GeometryInstance):
                    collect_solids(item.GetInstanceGeometry())

        collect_solids(geometry)
        if not solids:
            return []

        top_face = None
        for solid in solids:
            for face in solid.Faces:
                if not isinstance(face, PlanarFace):
                    continue
                normal = face.FaceNormal
                if abs(normal.Z) <= 0.99 or normal.Z <= 0:
                    continue
                if top_face is None or face.Area > top_face.Area:
                    top_face = face
        if top_face is None:
            return []

        edge_loops = top_face.EdgeLoops
        cells = []
        for loop_index in range(edge_loops.Size):
            if loop_index == 0:
                continue  # contorno externo, nao e' um vazio
            local_points = []
            for edge in edge_loops.get_Item(loop_index):
                for point in edge.Tessellate():
                    local_points.append(point)
            if not local_points:
                continue
            xs = [p.X for p in local_points]
            ys = [p.Y for p in local_points]
            cells.append({
                "center_local": ((min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0),
                "size_local": (max(xs) - min(xs), max(ys) - min(ys)),
            })
        return cells
    except Exception:
        return []


def load_fixed_block_catalog(target_doc):
    """Ponto de entrada da Etapa 1 (AUTOMATICO - substitui a antiga
    montagem manual do catalogo por selecao). Monta o catalogo sempre a
    partir das MESMAS familias/tipos reais do projeto, definidas em
    BLOCK_FAMILY_CATALOG_DEFINITIONS - nunca por selecao do usuario, nunca
    por heuristica de nome/comprimento, nunca substituindo por uma familia
    parecida.

    Para cada codigo logico ausente do documento, nada e' deduzido: o
    codigo entra em `missing` para o chamador reportar exatamente qual
    familia/tipo falta carregar. Os simbolos encontrados sao ativados
    (Activate(), dentro de uma Transacao propria) - necessario tanto para
    ler a geometria/celulas quanto para poder instancia-los depois na
    Etapa 5; mesma ativacao que create_building_blocks ja fazia, so'
    adiantada para o momento da validacao.

    Devolve (catalog, missing):
      - `catalog`: dict {codigo_logico: BlockTypeDefinition} - mesmo
        formato de antes (symbol, logical_code, length_cm, height_cm,
        width_cm, cells_local, is_special_bond, is_compensator,
        source_instance_id), so' para os codigos ENCONTRADOS;
      - `missing`: lista de dicts {"logical_code","family_name",
        "type_name","reason"} - um por familia/tipo nao localizado (ou
        localizado mas sem o parametro 'Comprimento_bloco'), para o
        chamador BLOQUEAR e informar exatamente o que falta em vez de
        prosseguir com um catalogo incompleto."""
    catalog = {}
    missing = []
    found = []  # [(logical_code, definition, symbol)]

    for logical_code, definition in BLOCK_FAMILY_CATALOG_DEFINITIONS.items():
        symbol = _find_family_symbol_by_exact_name(
            target_doc, definition["family_name"], definition["type_name"]
        )
        if symbol is None:
            missing.append({
                "logical_code": logical_code,
                "family_name": definition["family_name"],
                "type_name": definition["type_name"],
                "reason": "familia/tipo nao encontrado no projeto (nao esta carregado).",
            })
            continue
        found.append((logical_code, definition, symbol))

    if found:
        t_activate = Transaction(target_doc, "Ativa tipos do catalogo fixo de blocos")
        t_activate.Start()
        try:
            for _code, _definition, symbol in found:
                if not symbol.IsActive:
                    symbol.Activate()
            # Regenerate() DENTRO da transacao (antes do Commit) - testado
            # ao vivo via MCP em 2026-08-20: chamar Regenerate() DEPOIS do
            # Commit() (padrao usado em create_building_blocks) lanca
            # "Modification of the document is forbidden" nesse ambiente de
            # execucao; dentro da transacao funciona igual e e' igualmente
            # valido pela API (o efeito exigido - Type reprocessado antes de
            # ler geometria/instanciar - acontece de qualquer forma).
            target_doc.Regenerate()
            t_activate.Commit()
        except Exception:
            t_activate.RollBack()
            raise

    for logical_code, definition, symbol in found:
        length_cm = _type_param_cm(symbol, ["Comprimento_bloco"])
        height_cm = _type_param_cm(symbol, ["Altura_bloco"])
        width_cm = _type_param_cm(symbol, ["Largura_bloco"])
        if length_cm is None:
            missing.append({
                "logical_code": logical_code,
                "family_name": definition["family_name"],
                "type_name": definition["type_name"],
                "reason": "encontrada no projeto mas sem o parametro de TIPO 'Comprimento_bloco'.",
            })
            continue

        cells_local = _extract_block_cells_local_from_symbol(symbol)
        catalog[logical_code] = {
            "symbol": symbol,
            "logical_code": logical_code,
            "length_cm": length_cm,
            "height_cm": height_cm,
            "width_cm": width_cm,
            "cells_local": cells_local,
            "is_special_bond": definition["is_special_bond"],
            "is_compensator": definition["is_compensator"],
            "source_instance_id": symbol.Id,
        }

    return catalog, missing


# pack_pier_with_blocks, _is_valid_opening_width_cm e
# solve_opening_modulation moraram para core/engine/modulation_math.py
# (import * feito mais acima, junto do resto da aritmetica de blocos) -
# nenhuma formula mudou, so' o arquivo.


def _wall_length_cm(wall):
    """Comprimento REAL/final de `wall`, lido da LocationCurve (depois de
    todos os ajustes de encontro/alinhamento que este script ja faz - ver
    o passo 2 da criacao, mais acima), em CENTIMETROS. Devolve None se a
    parede nao tiver LocationCurve (nao deveria acontecer para paredes
    basicas criadas por este script)."""
    location = wall.Location
    if not isinstance(location, LocationCurve):
        return None
    return location.Curve.Length / FEET_PER_METER * 100.0


# PIER_BOUNDARY_JOINTS_CM, PIER_BOUNDARY_JOINT_COMBINATIONS_CM,
# _pier_remaining_cm, pier_closes_with_blocks_cm,
# wall_length_closes_with_blocks_cm, _wall_length_snap_targets_cm,
# nearest_block_lengths_cm, nearest_wall_lengths_cm, suggested_block_length_cm,
# evaluate_wall_block_length, _nearest_valid_lengths_cm,
# _suggested_valid_length_cm e _evaluate_modulation_length moraram para
# core/engine/modulation_math.py (import * feito mais acima) - nenhuma
# formula mudou, so' o arquivo.


# Cache dos vaos por documento - ver _get_opening_gaps. Medido neste
# projeto (77 aberturas): montar a lista custa ~164ms, e ela seria montada
# a CADA edicao de parede se nao houvesse cache (o Execute do updater ao
# vivo dispara em toda transacao que toca uma parede). Com o cache, o
# caminho comum vira uma busca em dicionario.
_OPENING_GAP_CACHE = {}


def _invalidate_opening_gap_cache(target_doc=None):
    """Descarta o cache de vaos (ver _get_opening_gaps) - de `target_doc`
    ou de todos. Precisa ser chamado sempre que uma abertura puder ter
    mudado de posicao/largura/quantidade, senao a classificacao
    pilarete-x-parede-comum congela num retrato velho do modelo."""
    if target_doc is None:
        _OPENING_GAP_CACHE.clear()
    else:
        try:
            _OPENING_GAP_CACHE.pop(target_doc.GetHashCode(), None)
        except Exception:
            _OPENING_GAP_CACHE.clear()


def _collect_opening_gaps(target_doc):
    """Lista de (centro_do_vao_achatado_em_Z, meia_largura_ft) de TODA
    abertura do documento - ou seja, de toda FamilyInstance que tenha o
    parametro `Largura_abertura` (ver OPENING_WIDTH_PARAM). E' assim, e nao
    por categoria Portas/Janelas, porque neste projeto as aberturas estao
    modeladas como familias de MOBILIARIO e sem Host - confirmado
    consultando o modelo (77 instancias, categoria "Mobiliario", nenhuma
    com Host). Depender de categoria ou de Host nao funcionaria aqui.

    O centro sai da GEOMETRIA real da familia quando a largura medida
    confere com `Largura_abertura` (mesmo criterio de _build_opening_dict,
    que existe porque o ponto de insercao dessas familias fica
    sistematicamente deslocado); so' cai para o ponto de insercao quando a
    geometria nao serve."""
    gaps = []
    for inst in FilteredElementCollector(target_doc).OfClass(FamilyInstance):
        try:
            width_ft = _lookup_param_value(inst, [OPENING_WIDTH_PARAM])
            if not width_ft or width_ft <= 1e-6:
                continue
            center = None
            geometry_center, measured_width_ft = _opening_center_from_geometry(inst, width_ft)
            if (geometry_center is not None and measured_width_ft is not None and
                    abs(measured_width_ft - width_ft) <= OPENING_GEOMETRY_WIDTH_TOLERANCE_FT):
                center = geometry_center
            else:
                location = inst.Location
                if isinstance(location, LocationPoint):
                    p = location.Point
                    center = XYZ(p.X, p.Y, 0.0)
            if center is None:
                continue
            gaps.append((center, width_ft * 0.5))
        except Exception:
            continue
    return gaps


def _get_opening_gaps(target_doc):
    """_collect_opening_gaps com cache por documento (ver
    _OPENING_GAP_CACHE/_invalidate_opening_gap_cache)."""
    try:
        key = target_doc.GetHashCode()
    except Exception:
        return _collect_opening_gaps(target_doc)
    cached = _OPENING_GAP_CACHE.get(key)
    if cached is None:
        cached = _collect_opening_gaps(target_doc)
        _OPENING_GAP_CACHE[key] = cached
    return cached


def _wall_is_pier_at_opening(wall, opening_gaps, tolerance_ft):
    """True se `wall` e' um PILARETE que encosta num vao: uma parede que
    termina na borda de uma abertura e se estende para FORA dela.

    Os tres testes, contra cada vao de `opening_gaps`:
      1. o centro do vao cai sobre a RETA desta parede (distancia
         perpendicular <= tolerancia) - senao o vao e' de outra parede;
      2. o centro do vao NAO cai dentro do segmento desta parede - e' isto
         que separa o pilarete do trecho de verga/peitoril, que por
         construcao tem exatamente a largura do vao e portanto CONTEM o
         centro dele (ver build_wall_segments);
      3. a ponta mais proxima desta parede esta' a no maximo meia largura
         do vao (+ tolerancia) do centro - ou seja, ela encosta mesmo na
         borda do vao, em vez de so' estar alinhada na mesma reta mais
         adiante.

    Hoje isto NAO decide mais nenhuma regra de aprovacao (a regra de
    digito para pilaretes junto de vao foi removida, e a checagem passou a
    ser a aritmetica real dos blocos, igual para todas as paredes) - serve
    so' para diagnostico e para o updater de abertura saber quais paredes
    reavaliar quando um vao se move. Teste puramente GEOMETRICO sobre o
    modelo atual: nao ha' memoria do que o script decidiu quando criou as
    paredes - o que vale e' onde a parede esta' agora."""
    location = wall.Location
    if not isinstance(location, LocationCurve):
        return False
    curve = location.Curve
    a_raw = curve.GetEndPoint(0)
    b_raw = curve.GetEndPoint(1)
    a = XYZ(a_raw.X, a_raw.Y, 0.0)
    segment = XYZ(b_raw.X - a_raw.X, b_raw.Y - a_raw.Y, 0.0)
    segment_length = segment.GetLength()
    if segment_length < 1e-9:
        return False
    direction = segment.Normalize()

    for center, half_width_ft in opening_gaps:
        t = (center - a).DotProduct(direction)
        perpendicular_ft = (center - (a + direction * t)).GetLength()
        if perpendicular_ft > tolerance_ft:
            continue
        if -tolerance_ft <= t <= segment_length + tolerance_ft:
            continue  # o vao cai DENTRO: e' a verga/peitoril, nao um pilarete
        distance_to_end_ft = -t if t < 0.0 else t - segment_length
        if distance_to_end_ft <= half_width_ft + tolerance_ft:
            return True
    return False


def evaluate_wall_modulation(wall_ids, target_doc=None, opening_gaps=None):
    """Analisa cada Wall em `wall_ids` (ElementId) e classifica se o
    comprimento REAL/final (lido do modelo - ver _wall_length_cm) PODE
    fechar em blocos, pela aritmetica real do catalogo + juntas
    (`evaluate_wall_block_length`). NAO altera nenhuma parede (somente
    leitura).

    NAO EXISTE MAIS nenhuma checagem por digito final aqui (nem 0/5, nem
    0/1/6/9) - removida completamente a pedido do usuario (2026-08-21).
    Uma parede de 111cm ou 129cm passa: cada uma fecha com a sua
    combinacao de juntas de contorno. So' reprova o que NENHUMA combinacao
    de juntas conseguiria montar (ou o que nem numero inteiro de cm e').

    Esta e' uma PRE-CHECAGEM permissiva, para o realce ao vivo. Quem decide
    de verdade se uma parede precisa de ajuste continua sendo o solver de
    blocos rodado parede por parede (process_walls_one_by_one, via
    analyze_created_walls_for_errors) - inclusive para os PILARETES
    encostados num vao (`_wall_is_pier_at_opening`), que continuam sendo
    reportados com a chave "pier_at_opening" so' para diagnostico.

    `target_doc` (default: o `doc` do modulo, ou seja, o documento em que o
    botao foi clicado) e' o documento onde os `wall_ids` sao procurados. Um
    ElementId so' tem significado DENTRO do seu proprio documento: procurar
    um id do documento B dentro do documento A devolve outro elemento
    qualquer (ou None) - ou seja, resultado silenciosamente ERRADO. Por isso
    o updater ao vivo (ver _WallModulationUpdater.Execute) sempre passa o
    documento que recebeu: ele e' registrado APP-WIDE e dispara para paredes
    de QUALQUER documento aberto.

    Devolve uma lista de dicts, um por parede, na MESMA ordem de
    `wall_ids` (paredes sem LocationCurve sao ignoradas silenciosamente -
    nao entram na lista de saida):
        {
            "id": ElementId,
            "length_cm": float,          # comprimento real, sem arredondar
            "length_cm_rounded": int,    # arredondado ao cm mais proximo
            "is_whole_cm": bool,         # tolerancia LARGA (0,05cm) - decide `compatible`
            "is_clean_cm": bool,         # tolerancia APERTADA (0,005cm) - decide VERMELHO
            "compatible": bool,
            "nearest_valid_cm": (menor, maior),  # so' informativo
            "suggested_cm": int,          # sugestao UNICA (mais proxima)
        }
    """
    source_doc = target_doc if target_doc is not None else doc
    if opening_gaps is None:
        opening_gaps = _get_opening_gaps(source_doc)
    results = []
    for wid in wall_ids:
        wall = source_doc.GetElement(wid)
        if wall is None:
            continue
        length_cm = _wall_length_cm(wall)
        if length_cm is None:
            continue
        # MESMA regra para todo mundo (parede comum ou pilarete encostado
        # num vao): a aritmetica real dos blocos, nunca um digito final.
        # `pier_at_opening` continua sendo calculado e reportado porque o
        # updater de abertura usa essa vizinhanca para saber quais paredes
        # reavaliar quando um vao se move - mas ele NAO muda mais o
        # criterio de aprovacao de ninguem.
        is_pier = _wall_is_pier_at_opening(wall, opening_gaps, PIER_AT_OPENING_TOLERANCE_FT)
        entry = evaluate_wall_block_length(length_cm)
        entry["id"] = wid
        entry["pier_at_opening"] = is_pier
        results.append(entry)
    return results


def evaluate_opening_modulation(openings):
    """Mesma ideia de evaluate_wall_modulation, mas para a LARGURA das
    aberturas (portas/janelas) - `openings` e' a lista de dicts ja montada
    por _build_opening_dict (tipicamente `all_openings`), largura vem da
    chave `width_ft` (parametro Largura_abertura). Regra de compatibilidade
    diferente da parede: termina em 1, 6 ou 9cm (SEM o 0 - ver
    OPENING_VALID_LAST_DIGITS_CM), mesma tolerancia de numero inteiro de
    cm. NAO altera nenhuma abertura (somente leitura).

    Devolve uma lista de dicts, um por abertura, na MESMA ordem de
    `openings`:
        {
            "element_id_obj": ElementId,
            "element_id": str,            # so' para exibicao (ver _build_opening_dict)
            "width_cm": float,
            "width_cm_rounded": int,
            "is_whole_cm": bool,
            "compatible": bool,
            "nearest_valid_cm": (menor, maior),
            "suggested_cm": int,
        }
    """
    results = []
    for op in openings:
        width_cm = op["width_ft"] / FEET_PER_METER * 100.0
        entry = _evaluate_modulation_length(width_cm, OPENING_VALID_LAST_DIGITS_CM)
        entry["width_cm"] = entry.pop("length_cm")
        entry["width_cm_rounded"] = entry.pop("length_cm_rounded")
        entry["element_id_obj"] = op["element_id_obj"]
        entry["element_id"] = op["element_id"]
        results.append(entry)
    return results


def _apply_modulation_incompatible_overrides(view, element_ids, target_doc=None):
    """Aplica o realce AZUL (ver _apply_solid_color_override) sobre
    `element_ids` - paredes/aberturas com comprimento/largura LIMPO
    (`is_clean_cm=True` nas paredes - ver evaluate_wall_modulation;
    `is_whole_cm=True` nas aberturas, que nao tem o conceito de residuo
    apertado - ver evaluate_opening_modulation) mas que nao fecha em blocos
    (`compatible=False`). Para paredes, o CHAMADOR precisa checar
    `is_clean_cm` PRIMEIRO e so' cair aqui quando for True - ver
    _apply_broken_length_overrides (vermelho tem precedencia). Precisa ser
    chamada dentro de uma Transacao aberta. `target_doc`: ver
    _apply_solid_color_override."""
    _apply_solid_color_override(view, element_ids, RevitColor(0, 0, 255), target_doc)


def _apply_broken_length_overrides(view, element_ids, target_doc=None):
    """Aplica o realce VERMELHO (ver _apply_solid_color_override) sobre
    `element_ids` - paredes com comprimento "quebrado": `is_clean_cm=False`
    em evaluate_wall_modulation, ou seja, o comprimento REAL lido da
    LocationCurve nao cai dentro da tolerancia APERTADA
    (BROKEN_LENGTH_RESIDUE_TOLERANCE_CM, 0,005cm) de nenhum cm inteiro
    (ex.: 25,01cm em vez de 25,00cm - um residuo pequeno demais para
    reprovar a aritmetica de modulacao, que usa uma tolerancia bem mais
    LARGA de 0,05cm - mas grande o bastante para o usuario querer ver e
    corrigir antes de confiar na modulacao). DIFERENTE de azul (comprimento
    LIMPO mas que nao fecha em blocos - ver
    _apply_modulation_incompatible_overrides): o CHAMADOR e' quem garante
    que os dois nunca se aplicam ao mesmo elemento (checa `is_clean_cm`
    PRIMEIRO, com precedencia sobre `compatible`/azul - ver
    _refresh_wall_modulation_override/main()), nao mais uma exclusao
    puramente aritmetica como antes desta tolerancia separada existir.

    ATE' 2026-08-26 esta cor era usada por uma feature DIFERENTE e ja'
    REMOVIDA por completo a pedido do usuario ("ponta de parede suspeita" -
    fim sem porta/janela nem parede vizinha que explique, ver historico do
    plano em C:\\Users\\CIVIX\\.claude\\plans\\quiet-painting-petal.md) - o
    vermelho foi reaproveitado para este novo significado (comprimento
    quebrado), nao existe mais nenhum uso concorrente da cor. Precisa ser
    chamada dentro de uma Transacao aberta. `target_doc`: ver
    _apply_solid_color_override."""
    _apply_solid_color_override(view, element_ids, RevitColor(255, 0, 0), target_doc)


def _current_override_is_red(view, element_id):
    """True se `element_id` ja' tem o realce VERMELHO (comprimento quebrado
    - ver _apply_broken_length_overrides) aplicado nesta `view`.

    Devolve False (nunca lanca) se a consulta falhar - GetElementOverrides
    lanca excecao para um elemento que nao e' visivel/controlavel NESTA
    `view` (ex.: parede de outro nivel/opcao de projeto), o que passou a
    acontecer com frequencia depois que os updaters ao vivo (mais abaixo)
    passaram a observar QUALQUER parede do DOCUMENTO INTEIRO (nao so' as
    desta execucao) - uma excecao aqui, fora de qualquer try/except do
    chamador, derrubava o Execute() inteiro do updater e o Revit chegava a
    desativa-lo (dialogo "o atualizador de terceiros teve um problema")."""
    try:
        ogs = view.GetElementOverrides(element_id)
    except Exception:
        return False
    color = ogs.ProjectionLineColor
    if color is None or not color.IsValid:
        return False
    return color.Red == 255 and color.Green == 0 and color.Blue == 0


# A antiga ETAPA 1 (ajuste previo de abertura ANTES da criacao das paredes -
# analyze_opening_adjustments/apply_opening_adjustment_plans/
# _OpeningAdjustmentForm) foi REMOVIDA: permitia mudar a LARGURA da
# abertura para fechar a modulacao, o que contraria a regra nova do usuario
# ("largura/altura nunca mudam, so' a posicao"). A correcao agora e' toda
# feita DEPOIS da criacao, sobre os elementos REAIS - ver ETAPA 3B
# (_classify_wall_axis_segments em diante, mais abaixo) e a janela unica.


def describe_block_course(blocks):
    """Texto curto da composicao de um pilarete, no formato que o desenho
    de referencia usa: '1 + 34 + 1 + 19 = 55'. Sem blocos devolve '-'."""
    if not blocks:
        return "-"
    parts = []
    total = 0
    for block_cm in blocks:
        parts.append(str(BLOCK_JOINT_CM))
        parts.append(str(block_cm))
        total += block_cm + BLOCK_JOINT_CM
    return "{} = {}cm".format(" + ".join(parts), total)



# ETAPA 4 (encontros L/T/X, jambs de abertura, preenchimento comum,
# validacao final de parede e o laco principal process_walls_one_by_one) -
# EXTRAIDA para core/engine/wall_stepper.py (mesmo padrao ja' usado para
# core/engine/wall_pairing.py) para que uma ferramenta externa (fora do
# Revit) possa rodar o mesmo motor de modulacao/correcao parede-a-parede
# sem duplicar nenhuma regra. Ver o cabecalho daquele arquivo para o
# inventario completo do que foi movido.
from core.engine.wall_stepper import *  # noqa: F401,F403



# ==========================================
# JANELAS NAO INTERROMPEM A FIADA ABAIXO DO PEITORIL (pedido do usuario,
# 2026-08-21, com imagens de referencia de como ele modula manualmente):
#
# Ate' aqui, `solve_building_blocks` resolvia UM UNICO par de fiadas A/B em
# planta (usando so' t_lo/t_hi de cada abertura - a largura, nunca a
# altura) e `create_building_blocks` repetia ESSE MESMO par em TODAS as
# fiadas fisicas do pe-direito. Para uma PORTA (peitoril=0, vao ate' perto
# do teto) isso e' fisicamente correto - o vao existe em toda fiada. Para
# uma JANELA (peitoril>0), e' ERRADO: as fiadas inteiramente ABAIXO do
# peitoril (ou ACIMA da verga) deveriam continuar SOLIDAS, e o par unico
# repetido tratava a largura da janela como vazia em TODA fiada, inclusive
# as que ficam abaixo do parapeito.
#
# `sill_z_abs`/`head_z_abs` (a faixa vertical REAL do vao - o "X" da
# janela na vista, ja' lido dos parametros reais da familia - Peitoril/
# Altura_abertura, ver _build_opening_dict) sempre estiveram disponiveis em
# `openings_per_wall`, mas o solver de blocos nunca os consultava. As
# funcoes abaixo tornam o lancamento CIENTE de fiada: agrupam as fiadas
# fisicas pelo CONJUNTO de aberturas que realmente aparecem em cada faixa
# vertical (a maioria cai em so' 2-3 grupos distintos - abaixo de todos os
# peitoris, dentro dos vaos, acima de todas as vergas - nao 14 solves
# diferentes) e rodam solve_building_blocks UMA VEZ por grupo.
# ==========================================

# Toleranca (cm) para decidir se o vao real [sill_z_abs, head_z_abs) de uma
# abertura de fato aparece na faixa vertical de UMA fiada - absorve ruido
# de poucos milimetros na leitura dos parametros Peitoril/Altura_abertura
# da familia real ou nas conversoes pes<->cm, mesma ordem de grandeza das
# outras tolerancias deste arquivo (MODULATION_WHOLE_CM_TOLERANCE_CM).
OPENING_COURSE_BAND_TOLERANCE_CM = 0.5
OPENING_COURSE_BAND_TOLERANCE_FT = OPENING_COURSE_BAND_TOLERANCE_CM / 100.0 * FEET_PER_METER


def _block_height_ft(catalog, candidates=None):
    """Altura (ft) SO' do bloco (sem a junta de assentamento) - a extensao
    vertical realmente OCUPADA por uma fiada fisica, usada para decidir se
    ela cai dentro do vao [sill_z_abs, head_z_abs) de uma abertura (ver
    _opening_active_in_course_band). Diferente de `_course_height_ft`, que
    inclui COURSE_JOINT_CM porque mede o PASSO entre o INICIO de uma fiada
    e o INICIO da proxima, nao a fiada em si. `candidates=None` usa o
    catalogo inteiro (mesma regra de `_course_height_ft`)."""
    course_height_ft, err = _course_height_ft(catalog, candidates)
    if course_height_ft is None:
        return None, err
    return course_height_ft - _cm_to_ft(COURSE_JOINT_CM), None


def _course_z_band(base_z_abs, course_index, course_height_ft, block_height_ft):
    """(z_lo_abs, z_hi_abs) - faixa vertical (ft) realmente OCUPADA pela
    fiada fisica `course_index` (0-based), na mesma origem/convencao de
    `_course_z_abs`."""
    z_lo = _course_z_abs(base_z_abs, course_index, course_height_ft)
    return z_lo, z_lo + block_height_ft


def _opening_active_in_course_band(sill_z_abs, head_z_abs, z_lo_abs, z_hi_abs,
                                   tol_ft=OPENING_COURSE_BAND_TOLERANCE_FT):
    """True se o vao real de uma abertura [sill_z_abs, head_z_abs) de fato
    aparece na faixa vertical [z_lo_abs, z_hi_abs) de UMA fiada - ou seja,
    se ha' sobreposicao maior que a tolerancia de ruido. Uma fiada
    inteiramente abaixo do peitoril ou inteiramente acima da verga devolve
    False (a abertura NAO conta ali - a fiada continua solida)."""
    lo = max(sill_z_abs, z_lo_abs)
    hi = min(head_z_abs, z_hi_abs)
    return (hi - lo) > tol_ft


def _filter_openings_per_wall_for_band(openings_per_wall, z_lo_abs, z_hi_abs,
                                       tol_ft=OPENING_COURSE_BAND_TOLERANCE_FT):
    """Copia de `openings_per_wall` mantendo, em cada parede, so' as
    aberturas cujo vao real aparece na faixa vertical [z_lo_abs, z_hi_abs)
    (ver _opening_active_in_course_band). Uma parede cuja(s) abertura(s)
    ficarem TODAS fora dessa faixa vira lista vazia nesta banda - o resto
    do solver ja trata "sem abertura" como parede continua, de graca (nao
    precisou mudar mais nada em X/T/L/jambs/preenchimento comum)."""
    return [
        [row for row in openings
         if _opening_active_in_course_band(row[2], row[3], z_lo_abs, z_hi_abs, tol_ft)]
        for openings in openings_per_wall
    ]


def _group_course_indices_by_opening_band(openings_per_wall, base_z_abs, course_height_ft,
                                          block_height_ft, num_courses,
                                          tol_ft=OPENING_COURSE_BAND_TOLERANCE_FT):
    """Agrupa os `num_courses` indices de fiada fisica (0-based) pelo
    CONJUNTO de aberturas ativas naquela faixa vertical (ver
    _filter_openings_per_wall_for_band) - fiadas com o MESMO conjunto ativo
    (o caso comum: a maioria cai inteira abaixo de todos os peitoris, ou
    inteira acima de todas as vergas) reusam o MESMO solve, em vez de rodar
    o solver da planta inteira uma vez POR fiada (14x seria caro demais -
    ver solve_building_blocks_all_courses).

    Devolve lista [(course_indices, filtered_openings_per_wall), ...], UMA
    entrada por conjunto de aberturas distinto encontrado, na ordem em que
    apareceram (fiada 1 primeiro)."""
    signature_order = []
    by_signature = {}
    for course_index in range(num_courses):
        z_lo, z_hi = _course_z_band(base_z_abs, course_index, course_height_ft, block_height_ft)
        filtered = _filter_openings_per_wall_for_band(openings_per_wall, z_lo, z_hi, tol_ft)
        signature = tuple(
            tuple((round(t_lo, 4), round(t_hi, 4)) for (t_lo, t_hi, _s, _h) in openings)
            for openings in filtered
        )
        if signature not in by_signature:
            by_signature[signature] = {"course_indices": [], "filtered": filtered}
            signature_order.append(signature)
        by_signature[signature]["course_indices"].append(course_index)
    return [(by_signature[sig]["course_indices"], by_signature[sig]["filtered"])
            for sig in signature_order]


def solve_building_blocks_all_courses(nodes, walls_to_create, end_to_node, openings_per_wall,
                                      catalog, base_z_abs, num_courses,
                                      allow_compensators=BLOCK_COMPENSATORS_ENABLED_BY_DEFAULT,
                                      variants_per_course=1,
                                      band_cb=None, progress_cb=None,
                                      wall_start_cb=None, wall_result_cb=None,
                                      stage_cb=None):
    """Como `solve_building_blocks`, mas roda uma vez POR GRUPO de fiadas
    fisicas com o mesmo conjunto de aberturas ativas (ver
    _group_course_indices_by_opening_band), em vez de resolver so' UMA vez
    em planta e repetir o mesmo par A/B cegamente em toda fiada. Necessario
    porque uma JANELA (peitoril > 0) so' e' vazia NA FAIXA VERTICAL REAL do
    seu vao - fiadas abaixo do peitoril (ou acima da verga) continuam
    solidas, regra pedida explicitamente pelo usuario (2026-08-21, com
    imagens de referencia).

    `variants_per_course` (secao 11.7 do REGRAS_MODULACAO_BLOCOS.md,
    2026-08-25 - CAUSA-RAIZ do bug real medido em producao: 118/128
    paredes reprovadas por `audit_wall_bond_quality`/ALTERNATING_JOINT_
    PATTERN so' porque, com `variants_per_course=1` (o default historico
    desta funcao - RETROCOMPATIVEL de proposito, ver abaixo), CADA fiada
    fisica de uma banda com >=1 vao (a maioria das paredes reais) repete
    o layout "A" ou "B" em 100% das fiadas da MESMA paridade, sempre
    acima do limite de 60% de BOND_ALTERNATING_JOINT_RATIO). Repassado
    para `solve_building_blocks` -> `solve_wall_free_fill` (ver la' a
    conta exata de quantas variantes bastam). O CHAMADOR de producao
    (Etapa 4C, `_execute_solve`) passa `PIER_LAYOUT_VARIANTS_PER_COURSE`
    explicitamente; o default desta funcao continua 1 (identico ao
    comportamento anterior a esta correcao) para nao alterar nenhum
    chamador/teste existente que nao pediu a variacao.

    Devolve {"error": None ou motivo (catalogo sem altura utilizavel - ver
    _course_height_ft), "course_candidates": {course_index: [candidatos XY
    da fiada - a LETRA fisica daquele indice (par=A, impar=B) filtrada
    tambem pela VARIANTE que aquele indice recebe dentro da familia, ver
    abaixo]}, "bands": [{"course_indices":[...], "result": <dict de
    solve_building_blocks>}, ...], e as mesmas chaves agregadas de
    solve_building_blocks (candidates/collisions/intersection_failures/
    jamb_exceptions/non_modular, cada uma somando TODAS as bandas) para
    reaproveitar o relatorio existente (_format_block_solve_report) sem
    alteracao."""
    course_height_ft, height_err = _course_height_ft(catalog, None)
    if course_height_ft is None:
        return {
            "error": height_err, "course_candidates": {}, "bands": [],
            "candidates": [], "collisions": [], "intersection_failures": [],
            "jamb_exceptions": [], "non_modular": [], "alignment_conflicts": [],
            "per_wall": [], "validations": [],
            "door_void_violations": [],
        }
    block_height_ft = course_height_ft - _cm_to_ft(COURSE_JOINT_CM)

    groups = _group_course_indices_by_opening_band(
        openings_per_wall, base_z_abs, course_height_ft, block_height_ft, num_courses
    )

    course_candidates = {}
    bands = []
    all_candidates, all_collisions = [], []
    all_intersection_failures, all_jamb_exceptions, all_non_modular = [], [], []
    all_alignment_conflicts = []
    all_per_wall, all_validations = [], []
    all_door_void_violations = []
    total_bands = len(groups)
    for _band_pos, (course_indices, filtered_openings) in enumerate(groups):
        if band_cb is not None:
            try:
                band_cb(_band_pos + 1, total_bands, list(course_indices))
            except Exception:
                pass
        result = solve_building_blocks(
            nodes, walls_to_create, end_to_node, filtered_openings, catalog,
            allow_compensators=allow_compensators, base_z_abs=base_z_abs,
            variants_per_course=variants_per_course,
            progress_cb=progress_cb, wall_start_cb=wall_start_cb, wall_result_cb=wall_result_cb,
            stage_cb=stage_cb,
        )
        bands.append({"course_indices": list(course_indices), "result": result})
        for course_index in course_indices:
            letter = "A" if course_index % 2 == 0 else "B"
            # Secao 11.7: dentro da familia (par/impar), qual das
            # `variants_per_course` composicoes esta fiada FISICA recebe -
            # gira por (course_index // 2) % variants_per_course, NUNCA por
            # `course_index % variants_per_course` direto (isso quebraria a
            # separacao par/impar que o restante do solver - nos/cantos L/T/X,
            # jambs - depende para decidir QUAL das duas fiadas "A"/"B" cada
            # course_index fisico usa). Com variants_per_course=1 (default),
            # variant_index e' sempre 0 - identico ao comportamento historico
            # (course_variant so' existe em candidatos de preenchimento comum
            # e jamb; candidatos de no'/canto nao tem essa chave - `.get(...)
            # is None` inclui-os em TODAS as variantes, ver solve_wall_free_fill
            # e _jamb_build_course_variants).
            variant_index = (course_index // 2) % variants_per_course
            course_candidates[course_index] = [
                c for c in result["candidates"]
                if c["course"] == letter and c.get("course_variant") in (None, variant_index)
            ]
        # AGREGADO para o relatorio (all_candidates/all_collisions): cada
        # banda entra UMA UNICA VEZ aqui, nao uma vez por course_index -
        # `result["collisions"]` sao pares de indice DENTRO da lista
        # `result["candidates"]` DESTA banda (o mesmo formato que
        # solve_building_blocks sempre devolveu); somar `offset` (quantos
        # candidatos ja' foram acumulados antes desta banda) e' o que
        # mantem os pares apontando para a peca CERTA depois da
        # concatenacao (bug real medido ao vivo via MCP 2026-08-21: sem o
        # offset, os pares "colidiam" entre pecas a centenas/milhares de cm
        # de distancia - indices da banda errada). So' agregar uma vez por
        # banda tambem evita duplicar candidatos/colisoes no relatorio
        # quando uma MESMA banda cobre varios course_indices da mesma letra
        # (pe-direito completo, 14 fiadas) - a duplicacao POR FIADA FISICA
        # continua acontecendo, mas so' em `course_candidates` (usado por
        # create_building_blocks), que precisa mesmo de uma entrada por
        # fiada real.
        offset = len(all_candidates)
        all_candidates.extend(result["candidates"])
        all_collisions.extend((i + offset, j + offset) for i, j in result["collisions"])
        all_intersection_failures.extend(result["intersection_failures"])
        all_jamb_exceptions.extend(result["jamb_exceptions"])
        all_per_wall.extend(result.get("per_wall") or [])
        all_validations.extend(result.get("validations") or [])
        all_non_modular.extend(result["non_modular"])
        all_alignment_conflicts.extend(result.get("alignment_conflicts") or [])
        all_door_void_violations.extend(result.get("door_void_violations") or [])

    # ETAPA 4D (regra #3, 2026-08-25): orientacao dos compensadores - roda
    # sobre TODOS os candidatos de uma vez, depois de todo o preenchimento
    # comum de todas as bandas (mutando os proprios dicts - ver docstring
    # de orient_compensator_candidates). Precisa vir ANTES da auditoria de
    # amarracao/relatorio, que so' LE os candidatos.
    if stage_cb is not None:
        try:
            stage_cb("orientando compensadores")
        except Exception:
            pass
    orient_compensator_candidates(all_candidates, walls_to_create, openings_per_wall, catalog)

    if stage_cb is not None:
        try:
            stage_cb("auditando amarracao entre fiadas")
        except Exception:
            pass
    wall_bond_audits = audit_all_walls_bond_quality(
        walls_to_create, course_candidates, catalog, num_courses,
        openings_per_wall=openings_per_wall, nodes=nodes, end_to_node=end_to_node,
    )

    return {
        "error": None,
        "course_candidates": course_candidates,
        "bands": bands,
        "candidates": all_candidates,
        "collisions": all_collisions,
        "intersection_failures": all_intersection_failures,
        "jamb_exceptions": all_jamb_exceptions,
        "non_modular": all_non_modular,
        "alignment_conflicts": all_alignment_conflicts,
        "door_void_violations": all_door_void_violations,
        # ATENCAO ao ler estas duas no relatorio: uma parede que aparece em
        # varias bandas (ex.: uma com janela - abaixo do peitoril, dentro
        # do vao, acima da verga) aparece varias vezes aqui, uma por banda -
        # "reprovada em N bandas" nao e' o mesmo que "reprovada" no sentido
        # antigo de solve_building_blocks (uma unica banda). Mantido assim
        # (em vez de deduplicar) de proposito: as bandas sao validadas
        # INDEPENDENTEMENTE (uma parede pode fechar solida abaixo do
        # peitoril e falhar dentro do vao da janela, ou vice-versa) - a
        # contagem por banda e' informacao real, nao ruido.
        "per_wall": all_per_wall,
        "validations": all_validations,
        # Validacao MULTI-FIADA (ve' a parede inteira de uma vez, nao fiada
        # a fiada isolada) - ver secao "ETAPA 4C" logo acima desta funcao.
        "wall_bond_audits": wall_bond_audits,
    }


# ==========================================
# ETAPA 4C - VALIDACAO DE AMARRACAO ENTRE FIADAS (3D, nao fiada a fiada)
#
# Ate' aqui cada trecho de cada fiada era aceito assim que fechasse
# ARITMETICAMENTE (soma das pecas == comprimento do trecho). Isso NAO
# garante uma modulacao aceitavel: o mesmo par de fiadas A/B calculado por
# solve_wall_free_fill/solve_all_intersections e' repetido fisicamente em
# TODAS as fiadas de uma banda (ver solve_building_blocks_all_courses) -
# entao qualquer peca de amarracao especial (B34/B54/B19 fora de ponta ou
# abertura) ou compensador que uma UNICA decisao de trecho precisou usar
# aparece de novo, na MESMA regiao X, em toda fiada da mesma paridade
# (par ou impar), e as vezes nas duas - exatamente a "faixa vertical"
# reportada pelo usuario com imagem real (colunas repetitivas de 54/34/
# compensador subindo a parede inteira, 2026-08-24).
#
# As funcoes abaixo leem os candidatos JA' POSICIONADOS de TODAS as fiadas
# fisicas de uma parede (nao mais fiada a fiada isolada) e procuram,
# GEOMETRICAMENTE (posicao real no eixo da parede, nunca por nome de
# familia/codigo/indice - regra #12 do pedido):
#   - juntas verticais corridas: mesma coordenada X repetida em muitas
#     fiadas seguidas, DAS DUAS PARIDADES (regra #13) - a coincidencia
#     genuina entre a fiada A e a fiada B, que de fato nunca deveria
#     acontecer;
#   - faixas verticais repetitivas de peca especial/compensador na mesma
#     regiao X, mesmo quando as fiadas nao sao consecutivas (regra #3/5/6),
#     com excecao LOCAL perto de aberturas/pontas de parede (regra #15/20).
#
# (a regra #14 do pedido original - "o mesmo padrao em fiadas alternadas
# par/impar" - foi tentada e revertida em audit_wall_bond_quality: como
# so' existe UM par de fiadas A/B, repetido fisicamente em TODO o
# pe-direito, qualquer junta de UMA fiada SEMPRE repete 100% das vezes na
# paridade dela - isso e' o proprio funcionamento correto da amarracao
# alternada, nao um defeito, e contar isso como reprovacao bloqueava quase
# toda parede real independente de qualquer correcao da Etapa 3B; ver o
# comentario acima de `alternating_joints` para o historico completo).
#
# Uma parede com qualquer um destes problemas sai REPROVADA do relatorio
# final e BLOQUEIA a criacao dos blocos (mesmo padrao ja' usado para
# "door_void_violations" - ver _format_block_solve_report). NAO existe
# ainda busca automatica por uma modulacao alternativa (mover a parede/o
# conjunto conectado alguns cm - regras #8/#9 do pedido, proxima etapa) -
# por isso o relatorio traz a coordenada X exata e as fiadas exatas de
# cada ocorrencia, para o ajuste manual (comprimento da parede, ou o
# encontro que esta' forcando a peca especial) ser rapido.
# ==========================================

BOND_JOINT_CLUSTER_TOLERANCE_CM = 1.5
BOND_CONTINUOUS_JOINT_MIN_COURSES = 4
BOND_CONTINUOUS_JOINT_RATIO = 0.6
BOND_ALTERNATING_JOINT_MIN_COURSES = 3
BOND_ALTERNATING_JOINT_RATIO = 0.6

# ETAPA 4/secao 11.7 (2026-08-25) - quantas variantes DISTINTAS de layout
# `solve_wall_free_fill`/`solve_opening_jamb` precisam gerar por FAMILIA de
# fiada (par/impar - "A"/"B") para o rodizio de `solve_building_blocks_
# all_courses` (course_index -> variante = (course_index//2) % K) nunca
# repetir a MESMA composicao em >= BOND_ALTERNATING_JOINT_RATIO (60%) das
# fiadas da mesma paridade. Com K composicoes por familia e passo 1 dentro
# da paridade (a variante muda a cada fiada fisica da mesma familia, nao a
# cada 2), a fracao MAXIMA que uma unica variante pode ocupar dentro da sua
# paridade e' ceil(total_da_paridade / K) / total_da_paridade - verificado
# por forca bruta (nao suposto) para todo num_courses de 3 a 39 (faixa que
# cobre qualquer pe-direito real, tipicamente 10-16 fiadas): com K=3 o pior
# caso medido e' 42.9% (3 de 7 fiadas), quase 20 pontos percentuais abaixo
# do limite de 60% - script de verificacao no historico desta correcao
# (secao 11.7 do REGRAS_MODULACAO_BLOCOS.md tem a tabela completa). K=2
# NAO basta (e' exatamente o bug original: 100% de repeticao dentro da
# paridade sempre que a banda tem >=1 vao); K=3 e' o menor K>=3 (a
# constante so' tem efeito pratico a partir dai) com margem confortavel.
PIER_LAYOUT_VARIANTS_PER_COURSE = 3

# Peca especial (B34/B54/B19/compensador) repetindo na mesma regiao X: a
# tolerancia e' maior que a de junta (BOND_JOINT_CLUSTER_TOLERANCE_CM)
# porque aqui o que importa e' "aproximadamente a mesma regiao", nao a
# coordenada exata (regra #5 do pedido - "ocupem repetidamente
# aproximadamente o mesmo intervalo X").
BOND_STRIP_CLUSTER_TOLERANCE_CM = 6.0
BOND_STRIP_MIN_COURSES = 3
BOND_STRIP_RATIO = 0.5
# Zona de excecao local (regra #15/#20): perto da ponta da parede ou de
# uma abertura, peca especial repetida NAO e' um defeito - e' a funcao
# normal dela.
BOND_STRIP_EDGE_EXEMPT_CM = 25.0
BOND_STRIP_OPENING_INFLUENCE_CM = 60.0

# BUG REAL corrigido (2026-08-25, log de execucao real do usuario): um no'
# T/X no MEIO de uma parede (a "parede principal" de um T, ou qualquer das
# duas paredes que se cruzam num X) recebe a MESMA peca de amarracao
# (B54 na parede principal do T, B34 na boneca, os dois B54 do X) na MESMA
# posicao X em TODAS as fiadas, por construcao (o no' nao muda de posicao
# entre fiadas - so' alterna qual FIADA fisica recebe o candidato "A" e
# qual recebe o "B", ver solve_all_intersections/_index_node_candidates_
# midspan). Isso e' CORRETO e ESPERADO (secao 5 de REGRAS_MODULACAO_
# BLOCOS.md - "T verdadeiro: B54 centrado no no'"), nao uma falha de
# amarracao - mas sem uma zona de excecao aqui, toda parede com um T/X no
# meio virava REPEATED_VERTICAL_COMPENSATOR_STRIP automaticamente (falso
# positivo confirmado no log real: paredes 4/5/6/7/9, todas com um B54/B34
# de no' de meio de parede, reprovadas so' por causa disso - a mesma
# categoria de falso positivo ja' corrigida para o vao de abertura em
# test_auditoria_de_amarracao_nao_fabrica_junta_no_meio_de_abertura, so'
# que para NOS em vez de ABERTURAS). Mesmo raio de influencia da abertura
# (BOND_STRIP_OPENING_INFLUENCE_CM) - a peca do no' e' tao "normal" ali
# quanto o jamb de uma porta/janela.
BOND_STRIP_NODE_EXEMPT_CM = 60.0

# REDE DE SEGURANCA (2026-08-25, pedido explicito do usuario - regra #2):
# "nao utilizar meio bloco proximo a encontros L, T ou Cruz... penalizar
# fortemente ou rejeitar qualquer solucao que coloque um meio bloco
# proximo a uma amarracao". A geracao ja' proibe isso por construcao
# (_pier_layout_avoiding_joints/_pier_ordered_layout/_merge_adjacent_
# compensator_pairs - B19 so' nasce numa ponta ABERTA de verdade, nunca
# contra um no'), mas esta e' a SEGUNDA verificacao INDEPENDENTE que o
# usuario pediu (regra #7): audit_wall_bond_quality confere de novo, a
# partir da geometria REAL das pecas ja' posicionadas, sem confiar que a
# geracao acertou. Tolerancia pequena (nao e' uma "zona de influencia"
# ampla como BOND_STRIP_*_CM - e' literalmente "o B19 esta' encostado no
# no'", a mesma folga de uma junta de assentamento comum).
HALF_BLOCK_TIE_ADJACENCY_CM = BLOCK_JOINT_CM + PIER_LAYOUT_TOLERANCE_CM
PENALTY_HALF_BLOCK_NEAR_TIE = 80000.0  # a MAIOR penalidade desta auditoria -
# regra #2 e' tao absoluta quanto a #1 (juntas), e o pedido do usuario foi
# "penalize FORTEMENTE" - deliberadamente acima de PENALTY_CONTINUOUS_
# VERTICAL_JOINT.

# Pesos conceituais da regra #11 do pedido (nao literais - a mesma ordem
# de grandeza, ajustada a escala desta implementacao).
PENALTY_CONTINUOUS_VERTICAL_JOINT = 50000.0
PENALTY_ALTERNATING_JOINT_PATTERN = 30000.0
PENALTY_VERTICAL_COMPENSATOR_STRIP = 30000.0

# Dois candidatos consecutivos (por t_start) na MESMA fiada so' formam uma
# junta vertical REAL se estiverem fisicamente encostados - gap de
# BLOCK_JOINT_CM (~1cm) contra outro bloco, ou 0 contra abertura
# (BLOCK_OPENING_JOINT_CM). Sem este teto, dois candidatos de TRECHOS
# diferentes separados por uma abertura (porta/janela) tambem contam como
# "consecutivos" (sao vizinhos na ordenacao por t_start, so' que com uma
# abertura inteira no meio) e o codigo fabricava uma "junta fantasma" bem
# no MEIO do vao da abertura - que, por a abertura ficar na MESMA posicao
# X em toda fiada, aparecia como CONTINUOUS_VERTICAL_JOINT em praticamente
# toda parede com abertura (bug real, achado ao vivo: 125/127 paredes
# reprovadas numa execucao real, a maioria sem nenhum problema de
# amarracao de verdade - uma taxa alta demais pra ser defeito de obra
# genuino).
BOND_MAX_ADJACENT_GAP_CM = 5.0


def _cluster_1d(points, tolerance_cm):
    """[(valor, payload), ...] -> lista de clusters [{"center":..,
    "items":[payload,...]}], agrupando valores a menos de `tolerance_cm`
    um do outro TRANSITIVAMENTE (sweep line ordenado): A perto de B e B
    perto de C agrupa os tres, mesmo que A e C sozinhos estivessem fora da
    tolerancia um do outro."""
    if not points:
        return []
    ordered = sorted(points, key=lambda p: p[0])
    clusters = []
    current = [ordered[0]]
    for value, payload in ordered[1:]:
        if value - current[-1][0] <= tolerance_cm:
            current.append((value, payload))
        else:
            clusters.append(current)
            current = [(value, payload)]
    clusters.append(current)
    out = []
    for cluster in clusters:
        values = [v for v, _p in cluster]
        out.append({"center": sum(values) / len(values), "items": [p for _v, p in cluster]})
    return out


def _index_course_candidates_by_wall(course_candidates, num_courses):
    """{wall_idx: {course_index: [pecas]}} numa UNICA passada por todas as
    fiadas - o mesmo criterio de `_wall_course_candidates` (a peca entra na
    parede "dona" E na secundaria de um encontro), so' que virado do avesso.

    DESEMPENHO (2026-08-27): `audit_all_walls_bond_quality` chamava
    `_wall_course_candidates` uma vez POR PAREDE, e cada chamada relia as
    `num_courses` listas INTEIRAS - O(paredes x fiadas x pecas). Numa
    planta de 306 eixos com 15 fiadas isso era a ordem de dezenas de
    milhoes de leituras, todas depois do solver ja' ter terminado (parte
    do "trava em 99%"). Montado uma vez, custa O(fiadas x pecas)."""
    index = {}
    for course_index in range(num_courses):
        for cand in course_candidates.get(course_index, []):
            for key in ("wall_idx", "secondary_wall_idx"):
                wall_idx = cand.get(key)
                if wall_idx is None:
                    continue
                per_wall = index.get(wall_idx)
                if per_wall is None:
                    per_wall = {}
                    index[wall_idx] = per_wall
                bucket = per_wall.get(course_index)
                if bucket is None:
                    per_wall[course_index] = [cand]
                elif bucket[-1] is not cand:
                    # peca com `wall_idx == secondary_wall_idx` nao pode
                    # entrar duas vezes no mesmo balde.
                    bucket.append(cand)
    return index


def _wall_course_candidates(wall_idx, course_candidates, num_courses, index=None):
    """{course_index: [candidatos desta parede]} - inclui pecas cujo
    `wall_idx` OU `secondary_wall_idx` seja esta parede (uma peca de canto
    pertence fisicamente as DUAS paredes do encontro - regra #12: usar a
    posicao REAL da peca, nao so' a parede "dona").

    `index` (opcional): resultado de `_index_course_candidates_by_wall`
    sobre o MESMO `course_candidates`. Quando dado, so' le' a fatia desta
    parede em vez de varrer todas as fiadas - mesmo conteudo e mesma ordem,
    sem a varredura. `None` mantem o caminho antigo, para quem chama esta
    funcao avulsa (testes) sem ter montado indice nenhum."""
    if index is not None:
        per_wall = index.get(wall_idx) or {}
        return dict(
            (course_index, per_wall.get(course_index) or [])
            for course_index in range(num_courses)
        )
    by_course = {}
    for course_index in range(num_courses):
        by_course[course_index] = [
            c for c in course_candidates.get(course_index, [])
            if c.get("wall_idx") == wall_idx or c.get("secondary_wall_idx") == wall_idx
        ]
    return by_course


def _is_special_block_code(code, catalog):
    """B34/B54/B19 (is_special_bond) e C09/C04 (is_compensator) - as pecas
    que NAO podem virar uma faixa vertical repetitiva (regra #3/#5/#6/#20).
    B39 (peca comum) nunca entra aqui."""
    entry = catalog.get(code) or {}
    return bool(entry.get("is_special_bond") or entry.get("is_compensator"))


def _wall_midspan_node_t_positions_cm(wall_idx, walls_to_create, nodes):
    """t_cm (ao longo do eixo de `wall_idx`) de cada no' L/T/X que toca esta
    parede no MEIO dela (nao numa ponta) - a mainWall de um T_INTERSECTION,
    ou qualquer parede de crossing_walls de um X_INTERSECTION (ver
    _midspan_node_wall_ids). Usada para isentar da auditoria de faixa
    vertical repetitiva (BOND_STRIP_NODE_EXEMPT_CM) a peca de amarracao
    que o proprio no' coloca ali - repetir na mesma posicao X em toda
    fiada e' o comportamento CORRETO de um no' de meio de parede, nao uma
    falha (ver comentario de BOND_STRIP_NODE_EXEMPT_CM)."""
    if not nodes:
        return []
    p0, _p1, wall_dir, _len, _t = _wall_axis_and_length(walls_to_create, wall_idx)
    positions = []
    for node in nodes:
        if wall_idx not in _midspan_node_wall_ids(node):
            continue
        point = node.get("point")
        if point is None:
            continue
        t_ft = (point - p0).DotProduct(wall_dir)
        positions.append(t_ft / FEET_PER_METER * 100.0)
    return positions


def _wall_tie_t_positions_cm(wall_idx, walls_to_create, nodes, end_to_node):
    """t_cm de TODA amarracao real (encontro L/T/X) que toca `wall_idx` -
    nas duas PONTAS (so' quando o no' de la' e' L_CORNER/T_INTERSECTION/
    X_INTERSECTION, nunca FREE_END - reusa `_axis_corner_end_sides`, o
    mesmo criterio ja' usado pelo ajuste geometrico de boneca) E no MEIO
    (reusa `_wall_midspan_node_t_positions_cm`). Usada pela rede de
    seguranca de meio-bloco perto de amarracao (regra #2, ver
    HALF_BLOCK_TIE_ADJACENCY_CM) - diferente da isencao de faixa vertical
    (BOND_STRIP_NODE_EXEMPT_CM), que so' cobre o MEIO (as pontas ja' tem
    sua propria isencao, mais ampla, so' por estarem perto da ponta da
    parede)."""
    length_cm = _wall_axis_and_length(walls_to_create, wall_idx)[3] / FEET_PER_METER * 100.0
    positions = list(_wall_midspan_node_t_positions_cm(wall_idx, walls_to_create, nodes))
    for end_index in _axis_corner_end_sides(wall_idx, end_to_node, nodes):
        positions.append(0.0 if end_index == 0 else length_cm)
    return positions


def audit_wall_bond_quality(wall_idx, walls_to_create, course_candidates, catalog,
                            num_courses, openings_per_wall=None, nodes=None, end_to_node=None,
                            course_candidates_index=None):
    """Validacao MULTI-FIADA de UMA parede - ver cabecalho da secao acima.
    Devolve {"ok": bool, "problems": [str,...], "penalty": float,
    "continuous_joints": [...], "alternating_joints": [...],
    "compensator_strips": [...], "half_blocks_near_ties": [...]}."""
    empty = {"ok": True, "problems": [], "penalty": 0.0,
             "continuous_joints": [], "alternating_joints": [], "compensator_strips": [],
             "half_blocks_near_ties": []}
    if num_courses < BOND_ALTERNATING_JOINT_MIN_COURSES:
        return empty

    p0, _p1, wall_dir, length_ft, _t = _wall_axis_and_length(walls_to_create, wall_idx)
    length_cm = length_ft / FEET_PER_METER * 100.0
    by_course = _wall_course_candidates(
        wall_idx, course_candidates, num_courses, index=course_candidates_index
    )
    if not any(by_course.values()):
        return empty

    opening_edges_cm = []
    if openings_per_wall is not None and wall_idx < len(openings_per_wall):
        for op in (openings_per_wall[wall_idx] or []):
            opening_edges_cm.append(op[0] / FEET_PER_METER * 100.0)
            opening_edges_cm.append(op[1] / FEET_PER_METER * 100.0)
    node_t_positions_cm = _wall_midspan_node_t_positions_cm(wall_idx, walls_to_create, nodes)
    tie_t_positions_cm = _wall_tie_t_positions_cm(wall_idx, walls_to_create, nodes, end_to_node)

    def _near_exempt_zone(t_cm):
        if t_cm <= BOND_STRIP_EDGE_EXEMPT_CM or t_cm >= length_cm - BOND_STRIP_EDGE_EXEMPT_CM:
            return True
        if any(abs(t_cm - edge) <= BOND_STRIP_OPENING_INFLUENCE_CM for edge in opening_edges_cm):
            return True
        return any(abs(t_cm - node_t) <= BOND_STRIP_NODE_EXEMPT_CM for node_t in node_t_positions_cm)

    # ---- juntas verticais entre pecas (regra #12/#13) e pecas especiais
    #      candidatas a faixa (regra #3/#5/#6) - tudo em coordenada REAL no
    #      eixo da parede, projetando o corpo de cada peca (regra #12).
    joint_points = []    # (x_cm, course_index)
    special_points = []  # (x_center_cm, (course_index, code))
    half_block_tie_points = []  # (x_center_cm, (course_index, gap_cm))
    for course_index, items in by_course.items():
        extents = []
        for c in items:
            t_start, t_end = _candidate_extent_on_wall_axis(c, p0, wall_dir)
            extents.append((t_start, t_end, c["logical_code"]))
        extents.sort(key=lambda e: e[0])
        for i in range(len(extents) - 1):
            gap_cm = extents[i + 1][0] - extents[i][1]
            if gap_cm > BOND_MAX_ADJACENT_GAP_CM:
                # Nao encostados de verdade - ha' uma abertura (ou outro
                # vazio) entre eles, nao uma junta de assentamento.
                continue
            joint_points.append(((extents[i][1] + extents[i + 1][0]) / 2.0, course_index))
        for t_start, t_end, code in extents:
            if _is_special_block_code(code, catalog):
                center = (t_start + t_end) / 2.0
                if not _near_exempt_zone(center):
                    special_points.append((center, (course_index, code)))
            if code == HALF_BLOCK_CODE and tie_t_positions_cm:
                # REDE DE SEGURANCA regra #2 (ver HALF_BLOCK_TIE_ADJACENCY_CM):
                # distancia do CORPO do B19 (nao so' do centro) ate' a
                # amarracao mais proxima - 0 se a amarracao cair dentro do
                # proprio intervalo da peca (nunca deveria acontecer, mas
                # tratado do mesmo jeito: distancia zero, violacao clara).
                for tie_t in tie_t_positions_cm:
                    if tie_t < t_start:
                        gap_cm = t_start - tie_t
                    elif tie_t > t_end:
                        gap_cm = tie_t - t_end
                    else:
                        gap_cm = 0.0
                    if gap_cm <= HALF_BLOCK_TIE_ADJACENCY_CM:
                        half_block_tie_points.append(
                            ((t_start + t_end) / 2.0, (course_index, gap_cm))
                        )
                        break

    continuous_joints, alternating_joints, strips, half_blocks_near_ties = [], [], [], []

    total_evens = sum(1 for ci in range(num_courses) if ci % 2 == 0) or 1
    total_odds = sum(1 for ci in range(num_courses) if ci % 2 == 1) or 1
    for cluster in _cluster_1d(joint_points, BOND_JOINT_CLUSTER_TOLERANCE_CM):
        courses = sorted(set(cluster["items"]))
        ratio = len(courses) / float(num_courses)
        if len(courses) >= BOND_CONTINUOUS_JOINT_MIN_COURSES and ratio >= BOND_CONTINUOUS_JOINT_RATIO:
            continuous_joints.append({"x_cm": cluster["center"], "courses": courses})
            continue
        evens = [ci for ci in courses if ci % 2 == 0]
        odds = [ci for ci in courses if ci % 2 == 1]
        if (len(evens) >= BOND_ALTERNATING_JOINT_MIN_COURSES
                and len(evens) / float(total_evens) >= BOND_ALTERNATING_JOINT_RATIO):
            alternating_joints.append({"x_cm": cluster["center"], "courses": evens, "parity": "par"})
        if (len(odds) >= BOND_ALTERNATING_JOINT_MIN_COURSES
                and len(odds) / float(total_odds) >= BOND_ALTERNATING_JOINT_RATIO):
            alternating_joints.append({"x_cm": cluster["center"], "courses": odds, "parity": "impar"})

    for cluster in _cluster_1d(special_points, BOND_STRIP_CLUSTER_TOLERANCE_CM):
        entries = cluster["items"]
        courses = sorted(set(e[0] for e in entries))
        if len(courses) >= BOND_STRIP_MIN_COURSES and len(courses) / float(num_courses) >= BOND_STRIP_RATIO:
            codes = sorted(set(e[1] for e in entries))
            strips.append({"x_cm": cluster["center"], "courses": courses, "codes": codes})

    # regra #2 (rede de seguranca): QUALQUER ocorrencia conta - nunca exige
    # repeticao em varias fiadas como as demais checagens acima (aquelas
    # procuram um PADRAO; esta e' uma proibicao incondicional de UMA peca).
    for cluster in _cluster_1d(half_block_tie_points, BOND_STRIP_CLUSTER_TOLERANCE_CM):
        entries = cluster["items"]
        courses = sorted(set(e[0] for e in entries))
        min_gap_cm = min(e[1] for e in entries)
        half_blocks_near_ties.append({"x_cm": cluster["center"], "courses": courses, "gap_cm": min_gap_cm})

    problems = []
    penalty = 0.0
    if continuous_joints:
        penalty += PENALTY_CONTINUOUS_VERTICAL_JOINT * len(continuous_joints)
        for j in continuous_joints:
            problems.append(
                "CONTINUOUS_VERTICAL_JOINT: junta corrida em X~{:.1f}cm, em {} fiadas ({}{})".format(
                    j["x_cm"], len(j["courses"]),
                    ", ".join(str(c) for c in j["courses"][:10]),
                    "..." if len(j["courses"]) > 10 else "",
                )
            )
    # CAUSA-RAIZ real de "parede corrigida continua reprovada / bloco nunca
    # e' lancado" (investigado 2026-08-25, apos correcao da Etapa 3B ja'
    # estar resolvendo a maioria das paredes e mesmo assim quase nenhuma
    # virar "modulada com sucesso"): `solve_building_blocks_all_courses`
    # resolve UM UNICO par de fiadas A/B em planta e repete ESSE MESMO par
    # fisicamente em TODA fiada par (A) e TODA fiada impar (B) do pe-direito
    # (ver secao "JANELAS NAO INTERROMPEM..." acima e o comentario no topo
    # da secao ETAPA 4C). Isso significa que QUALQUER junta que exista na
    # fiada A aparece, por CONSTRUCAO, em 100% das fiadas pares, e o mesmo
    # vale para qualquer junta da fiada B nas impares - nao ha' como uma
    # parede com mais de um bloco JAMAIS deixar de disparar esta condicao.
    # Ou seja, ALTERNATING_JOINT_PATTERN nao mede um defeito real de
    # amarracao (que e' o que a CONTINUOUS_VERTICAL_JOINT acima ja' cobre:
    # a mesma junta presente nas DUAS paridades, uma coincidencia genuina e
    # rara entre a fiada A e a fiada B) - ele mede o proprio padrao "correr
    # fiada A / fiada B alternadas" que e' exatamente como amarracao de
    # alvenaria em fiadas alternadas FUNCIONA (a junta da fiada A e' coberta
    # pelo corpo do bloco da fiada B logo acima/abaixo, e reaparece na
    # proxima fiada A - isso e' o offset correto, nao uma falha). Contado
    # como "problems"/bloqueando a criacao (regra #1 absoluta), isso
    # reprovava ~92% das paredes de uma planta real (118 de 128) mesmo
    # paredes SEM nenhum erro de geometria/modulacao (Etapa 3B), inclusive
    # todas as que a etapa "Ajustar Erros" corrigia com sucesso - a parede
    # saia valida da 3B e era barrada de novo, sem chance de correcao, pela
    # 4C. Mantido apenas como dado (`alternating_joints`, para diagnostico/
    # futuro), mas NUNCA mais soma penalidade nem entra em `problems` -
    # nunca bloqueia a criacao de bloco por si so'.
    if strips:
        penalty += PENALTY_VERTICAL_COMPENSATOR_STRIP * len(strips)
        for s in strips:
            problems.append(
                "REPEATED_VERTICAL_COMPENSATOR_STRIP: {} repetido(s) em X~{:.1f}cm, em {} fiadas ({}{})".format(
                    "/".join(s["codes"]), s["x_cm"], len(s["courses"]),
                    ", ".join(str(c) for c in s["courses"][:10]),
                    "..." if len(s["courses"]) > 10 else "",
                )
            )
    if half_blocks_near_ties:
        penalty += PENALTY_HALF_BLOCK_NEAR_TIE * len(half_blocks_near_ties)
        for h in half_blocks_near_ties:
            problems.append(
                "HALF_BLOCK_NEAR_TIE: meio bloco (B19) a {:.1f}cm de uma amarracao em X~{:.1f}cm, "
                "em {} fiadas ({}{}) - proibido (regra #2): meio bloco so' perto de aberturas, "
                "nunca como recurso para fechar uma amarracao".format(
                    h["gap_cm"], h["x_cm"], len(h["courses"]),
                    ", ".join(str(c) for c in h["courses"][:10]),
                    "..." if len(h["courses"]) > 10 else "",
                )
            )

    return {
        "ok": not problems,
        "problems": problems,
        "penalty": penalty,
        "continuous_joints": continuous_joints,
        "alternating_joints": alternating_joints,
        "compensator_strips": strips,
        "half_blocks_near_ties": half_blocks_near_ties,
    }


def audit_all_walls_bond_quality(walls_to_create, course_candidates, catalog, num_courses,
                                 openings_per_wall=None, nodes=None, end_to_node=None):
    """Roda audit_wall_bond_quality em toda parede que tenha algum
    candidato lancado. Devolve {wall_idx: resultado} (regra #16/#17 -
    "todas as paredes devem ser auditadas", nao so' as que deram erro
    aritmetico)."""
    wall_indexes = sorted(set(
        c.get("wall_idx") for cs in course_candidates.values() for c in cs
        if c.get("wall_idx") is not None
    ))
    # Montado UMA vez e reusado por todas as paredes - ver
    # _index_course_candidates_by_wall.
    course_candidates_index = _index_course_candidates_by_wall(course_candidates, num_courses)
    return {
        wall_idx: audit_wall_bond_quality(
            wall_idx, walls_to_create, course_candidates, catalog, num_courses,
            openings_per_wall=openings_per_wall, nodes=nodes, end_to_node=end_to_node,
            course_candidates_index=course_candidates_index,
        )
        for wall_idx in wall_indexes
    }


# ==========================================
# ETAPA 4D - ORIENTACAO DOS COMPENSADORES (regra #3, pedido explicito do
# usuario, 2026-08-25)
#
# "O compensador possui um lado aberto e um lado fechado, e a orientacao
# dele e' obrigatoria. O lado fechado deve estar sempre voltado para a
# abertura... ele precisa manter o mesmo sentido construtivo de um bloco
# cortado... a orientacao deve ser determinada automaticamente de acordo
# com a posicao da abertura... o algoritmo tambem deve validar a
# orientacao dos compensadores e corrigir automaticamente qualquer um que
# esteja invertido."
#
# Ate' aqui (secao 1 de REGRAS_MODULACAO_BLOCOS.md) o catalogo tratava
# C09/C04 como pecas MACICAS - sem celulas, sem NENHUMA nocao de
# orientacao (diferente de B34/B54, que ja' tem a convencao do "vao
# menor" - ver _asymmetric_bond_origin_and_axis). As funcoes abaixo
# implementam a orientacao como um passo de VALIDACAO+CORRECAO que roda
# DEPOIS do preenchimento comum (nunca durante a geracao) - decide, pela
# posicao REAL de cada compensador em relacao a' abertura mais proxima,
# se ele precisa ser espelhado, e escreve isso em `candidate["mirrored"]`
# (aplicado de verdade em create_building_blocks via
# ElementTransformUtils.MirrorElement, o mesmo padrao ja' usado para
# `rotation_deg`/RotateElement).
# ==========================================

# ATENCAO - PREMISSA FISICA NAO CONFIRMADA (2026-08-25): esta sessao nao
# tem acesso ao Revit/a familia real do compensador (COMPENSADOR/PASTILHA)
# para medir qual extremidade da peca - local +x ou -x, ANTES de qualquer
# espelhamento - e' de fato o "lado fechado". A familia so' tinha sido
# lida ate' agora como macica (sem celulas - ver _extract_block_cells_
# local_from_symbol), entao o script nunca teve NENHUMA nocao de
# orientacao para C09/C04 - nao ha' dado historico para inferir isso.
#
# ESTA E' A UNICA CONSTANTE QUE PRECISA MUDAR se os compensadores sairem
# invertidos no Revit: crie um compensador de teste (candidate["rotation_
# deg"]==0, sem nenhum espelhamento) e observe qual lado tem a face
# fechada/inteira (sem entalhe/abertura) - se for o lado que aponta para
# +x LOCAL da peca (o mesmo sentido de candidate["x_dir"] quando "mirrored"
# e' False), deixe True; se for o lado -x, mude para False. Um unico valor
# corrige TODAS as instancias de uma vez (a logica de qual lado precisar
# ficar aberto/fechado, a partir da posicao da abertura, ja' esta' certa -
# so' a premissa de "qual lado a familia usa por padrao" pode estar
# invertida).
COMPENSATOR_CLOSED_SIDE_IS_PLUS_X_WHEN_UNMIRRORED = True

# Um compensador so' fica ENCOSTADO DE VERDADE (sem junta de argamassa)
# contra uma ABERTURA real - contra outro bloco ha' sempre BLOCK_JOINT_CM
# (1cm). Tolerancia pequena de proposito: confirma que a "proximidade"
# medida e' realmente esse encontro direto, nao uma coincidencia a
# distancia.
COMPENSATOR_OPENING_ADJACENCY_TOLERANCE_CM = BLOCK_OPENING_JOINT_CM + PIER_LAYOUT_TOLERANCE_CM


def _compensator_required_mirror(candidate, opening_intervals_cm, wall_p0, wall_dir,
                                 tolerance_cm=COMPENSATOR_OPENING_ADJACENCY_TOLERANCE_CM):
    """None se `candidate` (um compensador C09/C04) NAO esta' encostado
    numa abertura de verdade (nenhuma orientacao exigida - a regra e'
    especificamente sobre aberturas, secao 3 de REGRAS_MODULACAO_BLOCOS.md
    - um compensador de preenchimento comum, longe de qualquer abertura,
    fica com `mirrored=False`, nunca espelhado sem motivo). Caso
    contrario, devolve o valor exigido de `mirrored` (True/False) para que
    o lado FECHADO da peca fique voltado para a abertura."""
    t_lo, t_hi = _candidate_t_range_on_wall(candidate, wall_p0, wall_dir)
    closed_toward_wall_plus_t = None
    for gap_lo, gap_hi in opening_intervals_cm:
        if abs(gap_lo - t_hi) <= tolerance_cm:
            # a abertura comeca logo apos o FIM da peca (lado +t da parede)
            # - o lado fechado tem que apontar para +t.
            closed_toward_wall_plus_t = True
            break
        if abs(gap_hi - t_lo) <= tolerance_cm:
            # a abertura termina logo antes do INICIO da peca (lado -t) -
            # o lado fechado tem que apontar para -t.
            closed_toward_wall_plus_t = False
            break
    if closed_toward_wall_plus_t is None:
        return None
    # `candidate["x_dir"]` e' o +x LOCAL da peca, ja' em coordenadas de
    # mundo - pode ou nao coincidir com o sentido de `wall_dir` (+t da
    # parede) dependendo de como o candidato foi construido. Converte a
    # exigencia de "+t da parede" para "+x local da peca" antes de
    # comparar com a premissa (COMPENSATOR_CLOSED_SIDE_IS_PLUS_X_WHEN_
    # UNMIRRORED, que e' sempre em termos do proprio x_dir local).
    x_dir_matches_wall_dir = candidate["x_dir"].DotProduct(wall_dir) >= 0.0
    closed_toward_plus_x = (
        closed_toward_wall_plus_t if x_dir_matches_wall_dir else not closed_toward_wall_plus_t
    )
    return closed_toward_plus_x != COMPENSATOR_CLOSED_SIDE_IS_PLUS_X_WHEN_UNMIRRORED


def orient_compensator_candidates(candidates, walls_to_create, openings_per_wall, catalog):
    """PASSO DE VALIDACAO E CORRECAO da orientacao dos compensadores
    (regra #3, 2026-08-25) - roda sobre TODOS os candidatos de uma vez,
    DEPOIS do preenchimento comum (nunca durante a geracao): para cada
    compensador (C09/C04) de cada parede, recalcula do zero a orientacao
    exigida a partir da posicao REAL da peca em relacao a' abertura mais
    proxima (`_compensator_required_mirror`) e AJUSTA
    `candidate["mirrored"]` para bater com o exigido - mesmo que a peca ja'
    tivesse um valor diferente (ex.: de uma rodada anterior). Esta funcao
    e' sempre a FONTE DA VERDADE final sobre orientacao, chamada por
    ultimo, exatamente o "validar e corrigir automaticamente qualquer um
    que esteja invertido" pedido pelo usuario - nao ha' distincao entre
    "definir pela primeira vez" e "corrigir": e' a MESMA operacao.

    Peca que nao e' compensador (`is_compensator` no catalogo) nunca e'
    tocada (fica sem a chave "mirrored" - `create_building_blocks` trata
    ausencia como False/sem espelhar, o mesmo valor que um compensador
    longe de abertura recebe explicitamente).

    Muta os dicts de `candidates` EM PLACE (o mesmo objeto Python
    referenciado em `course_candidates`/outras listas - ver o uso de
    `id(cand)` como "candidate_key" em create_building_blocks/
    _colliding_created_instance_ids, que depende dessa identidade
    compartilhada) e devolve `candidates` por conveniencia; nunca cria,
    remove ou reordena candidatos."""
    by_wall = {}
    for c in candidates:
        wall_idx = c.get("wall_idx")
        if wall_idx is not None:
            by_wall.setdefault(wall_idx, []).append(c)
    for wall_idx, wall_candidates in by_wall.items():
        if wall_idx >= len(walls_to_create):
            continue
        p0, _p1, wall_dir, _len, _t = _wall_axis_and_length(walls_to_create, wall_idx)
        opening_intervals_cm = _wall_opening_intervals_cm(walls_to_create, openings_per_wall, wall_idx)
        for c in wall_candidates:
            entry = catalog.get(c.get("logical_code")) if catalog else None
            if not entry or not entry.get("is_compensator"):
                continue
            required = _compensator_required_mirror(c, opening_intervals_cm, p0, wall_dir)
            c["mirrored"] = bool(required)
    return candidates


# ==========================================
# ETAPA 5 - CRIACAO NO REVIT
#
# solve_building_blocks (Etapa 4, acima) devolve `candidates` para APENAS
# UM PAR de fiadas (A/B) por posicao em planta - ainda em memoria, nenhuma
# FamilyInstance existe no Revit. Esta secao repete esse par verticalmente
# ate' o pe-direito (BLOCK_JOINT_CM soma na altura tambem: cada fiada vale
# altura_do_bloco + 1cm de junta - por isso 19+1=20cm e 2,80m / 20cm = 14
# fiadas, a mesma logica de PIER_MODULE_CM ja usada no comprimento) e
# efetivamente cria as instancias.
#
# Duas exigencias do plano (secao "Riscos"/"Etapa 5" do
# PLANO_MODULACAO_BLOCOS.md) moldam a forma da funcao abaixo:
#   - nenhum doc.Regenerate() DENTRO do laco de criacao (o laco antigo de
#     criacao de parede, mais abaixo em main(), chama Regenerate() por
#     parede - inviavel aqui, na ordem de ~500 blocos/fiada x 14 fiadas =
#     ~7.000 instancias: um Regenerate por instancia tornaria a operacao
#     impraticavel). So' HA UM Regenerate, uma unica vez, depois de ativar
#     os FamilySymbol - a API do Revit exige isso antes do primeiro
#     NewFamilyInstance de cada tipo recem-ativado.
#   - tudo dentro de um unico TransactionGroup (ativacao dos tipos +
#     criacao de todas as instancias), para que o usuario tenha UM UNICO
#     passo de Undo para desfazer a etapa inteira.
# ==========================================

COURSE_JOINT_CM = BLOCK_JOINT_CM  # junta de assentamento tambem entre fiadas

# REGRA CRITICA do prompt de modulacao (secao 4): a primeira fiada NAO nasce
# na cota bruta do nivel (Z=0) - ela comeca em Z=1cm (junta de assentamento
# entre a base/contrapiso e o bloco), e so' dai' em diante e' que o
# incremento de 20cm por fiada (COURSE_JOINT_CM+altura do bloco) se aplica:
# Fiada 1 -> 1cm, Fiada 2 -> 21cm, Fiada 3 -> 41cm, ... Z(n) = 1 + (n-1)*20.
# Sem este offset, create_building_blocks nascia com a Fiada 1 exatamente
# em base_z_abs (Z=0 relativo ao nivel), contrariando a regra explicita do
# prompt ("Nao criar a primeira fiada em 0 cm"). CONFIRMADO pelo usuario
# direto no Revit (2026-08-21, apos ver os blocos criados): "segunda fiada
# seja lancada no nivel 21" - ver historico de reversao em _course_height_ft.
FIRST_COURSE_Z_OFFSET_CM = 1.0


def _course_height_ft(catalog, candidates):
    """Altura (ft) de UMA fiada = altura do bloco (lida do catalogo, nunca
    hardcoded - mesma regra da secao ETAPA 1) + COURSE_JOINT_CM de junta de
    assentamento.

    HISTORICO 2026-08-21 (mesma sessao, revertido): testado ao vivo pela
    primeira vez via MCP com a Fiada 1 em 1cm e a Fiada 2 saindo em 21cm
    (formula original: bloco+junta=20cm por passo). O usuario reportou "20
    na verdade" e a formula foi mudada para NAO somar junta aqui (passo de
    19cm, dando 1/20/39/58). Depois de conferir os blocos criados no Revit
    (screenshots), o usuario pediu explicitamente "a segunda fiada seja
    lancada no nivel 21" - REVERTENDO a mudanca anterior. Formula atual
    (novamente): passo de COURSE_JOINT_CM+altura do bloco = 20cm, dando
    1/21/41/61. Se isto disparar de novo, NAO alternar mais sem confirmar
    com o usuario qual das duas leituras (20 ou 21) e' a correta - ja
    inverteu duas vezes na mesma sessao.

    Usa os tipos efetivamente presentes em `candidates` (os unicos que
    realmente serao criados); todos devem concordar na altura - peca com
    altura divergente e' um erro de catalogo/familia, reportado pelo
    chamador, nao silenciado aqui. `candidates` vazio/None usa o
    CATALOGO INTEIRO no lugar - util para descobrir a altura de fiada
    ANTES de rodar qualquer solve (ver solve_building_blocks_all_courses,
    que precisa da altura para decidir as bandas verticais antes mesmo de
    saber quais pecas vao ser usadas)."""
    codes_used = set(c["logical_code"] for c in candidates) if candidates else set(catalog.keys())
    heights_cm = set()
    for code in codes_used:
        entry = catalog.get(code)
        if entry is None or not entry.get("height_cm"):
            continue
        heights_cm.add(round(entry["height_cm"], 3))
    if not heights_cm:
        return None, "nenhum bloco usado tem altura valida no catalogo"
    if len(heights_cm) > 1:
        return None, (
            "os blocos usados tem alturas diferentes no catalogo ({}) - "
            "nao da para definir uma unica altura de fiada.".format(
                ", ".join(str(h) for h in sorted(heights_cm))
            )
        )
    return _cm_to_ft(next(iter(heights_cm)) + COURSE_JOINT_CM), None


def _course_z_abs(base_z_abs, course_index, course_height_ft):
    """Cota Z absoluta (ft) da fiada `course_index` (0-based) - formula da
    secao 4 do prompt (REGRA CRITICA): Fiada 1 (course_index=0) fica em
    base_z_abs + 1cm, NAO em base_z_abs (0cm); as seguintes incrementam
    `course_height_ft` (altura do bloco + junta de assentamento) cada uma.
    Extraida de create_building_blocks para poder ser testada isoladamente
    (a criacao de FamilyInstance de verdade so' e' verificavel ao vivo via
    MCP - ver tests/README.md)."""
    return base_z_abs + _cm_to_ft(FIRST_COURSE_Z_OFFSET_CM) + course_index * course_height_ft


def create_building_blocks(target_doc, candidates, catalog, base_z_abs, selected_level, num_courses,
                           course_candidates=None):
    """Ponto de entrada da Etapa 5: cria no Revit, dentro de um unico
    TransactionGroup, as FamilyInstance correspondentes a `candidates` (ver
    solve_building_blocks), repetidas em `num_courses` FIADAS FISICAS
    verticais a partir de `base_z_abs` (mesma referencia usada pelas
    paredes - a base do nivel selecionado). `num_courses` conta fiadas
    fisicas (1a, 2a, 3a, ...), NAO pares A/B - o mesmo numero que
    `num_courses_for_wall_height` ja devolve (ex.: pe-direito 2,80m / 19cm
    de bloco = 14 fiadas fisicas).

    `candidates` representa UM PAR de fiadas (A/B, ja' alternado pelo
    solver da Etapa 4 conforme o campo "course" de cada item) - a cada
    `course_index` de 0 a `num_courses`-1, SO' os candidatos cuja "course"
    bate com a letra fisica daquele indice (par=A, impar=B) sao colocados
    naquela cota (CORRIGIDO 2026-08-21: antes colocava os DOIS conjuntos - A
    e B - na MESMA cota a cada indice, empilhando uma fiada sobre a outra em
    vez de alterna-las verticalmente - bug real achado testando ao vivo).
    Repetir alternando A/B por altura de bloco (sem somar junta de novo -
    ver _course_height_ft) e' o que reproduz a amarracao vertical (fiada B
    sempre por cima do meio da fiada A, e vice-versa) ate' o pe-direito.

    `course_candidates` (opcional): dict {course_index: [candidatos XY
    ja' filtrados so' da letra fisica daquele indice]} - quando dado,
    SUBSTITUI o par unico repetido: cada fiada usa os candidatos da SUA
    PROPRIA banda vertical em vez do mesmo par A/B repetido cegamente.
    Necessario pela regra do usuario (2026-08-21): abaixo do peitoril de
    uma janela (ou acima da verga) a fiada tem que continuar SOLIDA, nao
    repetir o vazio da abertura em toda fiada - ver
    solve_building_blocks_all_courses, que monta este dict. Sem ele
    (None, o default), mantem o comportamento antigo: repete `candidates`
    filtrado por letra em toda fiada, igual antes desta regra existir.

    Nao decide QUANTAS fiadas cabem (`num_courses` vem do chamador, ja'
    calculado a partir do pe-direito real da parede - ver main()); nao
    apaga nada; nao mexe nas paredes. So' cria.

    Devolve dict {"created_count", "failures": [...],
    "course_height_ft"/None, "course_height_error"/None, "created_instances":
    [...]}. Cada item de "created_instances" e' {"id" (ElementId),
    "logical_code", "course", "course_index"} - usado pelo modo debug
    visual da Etapa 6 (colorir por codigo / filtrar Fiada A/B), que precisa
    dos ElementId REAIS (os candidatos sozinhos nao tem - so' existem depois
    desta funcao rodar)."""
    height_source = candidates if candidates else (
        [c for cs in (course_candidates or {}).values() for c in cs]
    )
    course_height_ft, height_error = _course_height_ft(catalog, height_source)
    if course_height_ft is None:
        return {
            "created_count": 0, "failures": [],
            "course_height_ft": None, "course_height_error": height_error,
            "created_instances": [],
        }

    used_codes = sorted(set(c["logical_code"] for c in height_source))
    missing_codes = [code for code in used_codes if code not in catalog]
    failures = [
        "tipo '{}' usado em algum candidato mas ausente do catalogo - "
        "nenhuma instancia dele sera criada.".format(code)
        for code in missing_codes
    ]
    created_count = 0
    created_instances = []

    group = TransactionGroup(target_doc, "Etapa 5 - Cria blocos estruturais")
    group.Start()
    try:
        # Ativacao dos FamilySymbol: precisa de transacao propria porque a
        # API exige um Regenerate() depois de Activate() e antes do
        # primeiro NewFamilyInstance daquele tipo - feito UMA VEZ aqui,
        # nunca dentro do laco de fiadas abaixo. Na pratica, load_fixed_
        # block_catalog ja ativa todos os tipos do catalogo fixo ANTES
        # desta funcao rodar (Etapa 1 automatica) - este bloco fica so'
        # como garantia extra (idempotente, symbol.IsActive ja e' True em
        # uso normal). Regenerate() DENTRO da transacao (nao depois do
        # Commit) - mesmo motivo/teste via MCP de load_fixed_block_catalog.
        t_activate = Transaction(target_doc, "Ativa tipos de bloco")
        t_activate.Start()
        try:
            for code in used_codes:
                entry = catalog.get(code)
                if entry is None:
                    continue
                symbol = entry["symbol"]
                if not symbol.IsActive:
                    symbol.Activate()
            target_doc.Regenerate()
            t_activate.Commit()
        except Exception:
            t_activate.RollBack()
            raise

        t_create = Transaction(target_doc, "Cria instancias de bloco")
        t_create.Start()
        try:
            # BUG REAL #2 medido ao vivo (2026-08-21, mesmo teste que achou o
            # bug do Z absoluto acima): este laco colocava TODOS os
            # candidatos (fiada A e fiada B juntas) na MESMA cota Z a cada
            # `course_index`, ignorando por completo `cand["course"]` - ou
            # seja, as duas fiadas do par nasciam empilhadas UMA EM CIMA DA
            # OUTRA na mesma altura (peca de A e peca de B sobrepostas no
            # mesmo Z), em vez de A numa fiada fisica e B na fiada fisica
            # seguinte (a amarracao vertical que o proprio docstring desta
            # funcao descreve). `course_index` agora e' a FIADA FISICA
            # (0=A, 1=B, 2=A, 3=B, ...) - cada iteracao so' coloca os
            # candidatos da LETRA correspondente, e `num_courses` passa a
            # significar "quantas fiadas fisicas", exatamente o que
            # `num_courses_for_wall_height` ja calculava (nao precisou
            # mudar - so' este laco estava interpretando errado).
            for course_index in range(num_courses):
                course_letter = "A" if course_index % 2 == 0 else "B"
                course_z_abs = _course_z_abs(base_z_abs, course_index, course_height_ft)
                if course_candidates is not None:
                    course_source = course_candidates.get(course_index) or []
                else:
                    course_source = [c for c in candidates if c["course"] == course_letter]
                for cand in course_source:
                    entry = catalog.get(cand["logical_code"])
                    if entry is None:
                        continue  # ja reportado em missing_codes, uma vez, acima
                    symbol = entry["symbol"]
                    origin = cand["origin_world"]
                    # BUG REAL medido ao vivo (2026-08-21, primeiro teste via MCP
                    # de create_building_blocks): o overload NewFamilyInstance(XYZ,
                    # FamilySymbol, Level, StructuralType) trata o Z do ponto como
                    # OFFSET relativo ao proprio `selected_level` - o Revit soma a
                    # elevacao do nivel por conta propria (mesma convencao ja usada
                    # em Wall.Create, cujo parametro chama-se literalmente "Offset
                    # da base"). Passar `course_z_abs` (JA absoluto, com base_z_abs
                    # somado por _course_z_abs) fazia base_z_abs entrar DUAS vezes -
                    # confirmado medindo a instancia real criada (Z saiu deslocado
                    # exatamente por base_z_abs a mais do esperado) e confirmado
                    # pelo usuario: fiada 1 = 1cm de elevacao (nao base_z_abs+1cm),
                    # fiada 2 = 21cm. Por isso aqui usamos o OFFSET (sem base_z_abs),
                    # nao o `course_z_abs` absoluto que os outros usos desta funcao
                    # (log/relatorio) continuam usando.
                    course_offset_ft = course_z_abs - base_z_abs
                    point = XYZ(origin.X, origin.Y, course_offset_ft)
                    try:
                        instance = target_doc.Create.NewFamilyInstance(
                            point, symbol, selected_level, StructuralType.NonStructural
                        )
                        rotation_deg = cand.get("rotation_deg") or 0.0
                        if abs(rotation_deg) > 1e-6:
                            axis = Line.CreateBound(point, XYZ(point.X, point.Y, point.Z + 1.0))
                            ElementTransformUtils.RotateElement(
                                target_doc, instance.Id, axis, math.radians(rotation_deg)
                            )
                        # Orientacao do compensador (regra #3, 2026-08-25 -
                        # ver orient_compensator_candidates/ETAPA 4D, que
                        # ja' decidiu "mirrored" a partir da posicao REAL
                        # da peca em relacao a' abertura). Espelha em torno
                        # de um plano com normal = x_dir da peca (o mesmo
                        # vetor que definiu `rotation_deg` acima) passando
                        # pelo proprio ponto de insercao - inverte qual
                        # extremidade (lado aberto/fechado) fica de que
                        # lado, sem mudar posicao nem largura/altura.
                        if cand.get("mirrored"):
                            mirror_plane = Plane.CreateByNormalAndOrigin(cand["x_dir"], point)
                            ElementTransformUtils.MirrorElement(target_doc, instance.Id, mirror_plane)
                        created_count += 1
                        created_instances.append({
                            "id": instance.Id, "logical_code": cand["logical_code"],
                            "course": cand["course"], "course_index": course_index,
                            # identidade do dict-candidato de origem (o MESMO
                            # objeto Python, por referencia, entre
                            # result["candidates"]/course_candidates e este
                            # `cand`) - usada por _colliding_created_instance_ids
                            # para saber quais instancias REAIS colidiam no
                            # solve, sem precisar comparar geometria de novo.
                            "candidate_key": id(cand),
                        })
                    except Exception as ex:
                        failures.append(
                            "fiada {}/{} - bloco {} ({}) em ({:.2f}, {:.2f}): {}".format(
                                course_index + 1, num_courses, cand["logical_code"],
                                cand.get("placement_reason", "?"), origin.X, origin.Y, str(ex)
                            )
                        )
            t_create.Commit()
        except Exception:
            t_create.RollBack()
            raise
        group.Assimilate()
    except Exception:
        group.RollBack()
        raise

    return {
        "created_count": created_count, "failures": failures,
        "course_height_ft": course_height_ft, "course_height_error": None,
        "created_instances": created_instances,
    }


def _colliding_created_instance_ids(candidates, collisions, created_instances):
    """ElementId REAIS (ja' criados no Revit) das pecas envolvidas em
    `collisions` (lista de pares de indice em `candidates`, devolvida por
    solve_building_blocks/solve_building_blocks_all_courses) - cruza pela
    identidade do dict-candidato (`id(cand)`, ver "candidate_key" em
    create_building_blocks) para saber, de cada par colidente, quais
    instancias FORAM REALMENTE CRIADAS nesta rodada (uma colisao pode
    apontar para uma banda/fiada fora do `num_courses` desta chamada -
    ver o comentario de agregacao em solve_building_blocks_all_courses -
    e nesse caso so' o lado realmente criado entra aqui).

    Pedido explicito do usuario (2026-08-24): "quero q o script lance os
    blocos mesmo q haja colisões, quero q sobrescreva as cores dos blocos
    com uma cor vermelha" - usada por _PostCreationEventHandler.
    _execute_create para aplicar o realce vermelho (ver
    _apply_solid_color_override) nas pecas colidentes, sem bloquear a
    criacao do resto."""
    colliding_keys = set()
    for i, j in collisions or []:
        for idx in (i, j):
            if 0 <= idx < len(candidates):
                colliding_keys.add(id(candidates[idx]))
    if not colliding_keys:
        return []
    return [item["id"] for item in created_instances if item.get("candidate_key") in colliding_keys]


def _bond_reproved_created_instance_ids(candidates, wall_bond_audits, created_instances):
    """ElementId REAIS (ja' criados no Revit) de TODAS as pecas que
    pertencem a uma parede REPROVADA em `wall_bond_audits` (auditoria de
    amarracao entre fiadas - secao ETAPA 4C, audit_all_walls_bond_quality)
    - cruza pelo `wall_idx` de cada candidato (a auditoria e' por parede
    inteira, nao por peca individual, entao toda peca da parede reprovada
    entra aqui, ao contrario de _colliding_created_instance_ids que so'
    marca as duas pecas de cada par colidente).

    HISTORICO: entre 2026-08-25 e 2026-08-26, `_execute_create` chegou a
    FILTRAR as paredes reprovadas ANTES de chamar create_building_blocks -
    nenhuma peca delas era criada. Revertido em 2026-08-26 (pedido
    explicito do usuario: "o diagnostico nao pode impedir a geracao dos
    blocos") - voltou a ser o comportamento de ate' 2026-08-24: cria-se
    tudo, e esta funcao e' usada por `_execute_create` para marcar em
    vermelho, DEPOIS de criadas, as pecas de paredes reprovadas."""
    reproved_wall_idxs = {wi for wi, audit in (wall_bond_audits or {}).items() if not audit["ok"]}
    if not reproved_wall_idxs:
        return []
    reproved_keys = {
        id(cand) for cand in candidates if cand.get("wall_idx") in reproved_wall_idxs
    }
    if not reproved_keys:
        return []
    return [item["id"] for item in created_instances if item.get("candidate_key") in reproved_keys]


def num_courses_for_wall_height(wall_height_ft, catalog, candidates):
    """Quantas fiadas INTEIRAS cabem em `wall_height_ft` (pe-direito real da
    parede) dada a altura de fiada calculada por _course_height_ft a partir
    do catalogo - ex.: 2,80m / 20cm = 14. Devolve (num_courses, erro) - erro
    nao-None quando a altura de fiada nao pode ser determinada (ver
    _course_height_ft); nesse caso num_courses e' 0."""
    course_height_ft, err = _course_height_ft(catalog, candidates)
    if course_height_ft is None or course_height_ft <= 1e-9:
        return 0, err
    return int(math.floor(wall_height_ft / course_height_ft + 1e-6)), None


# A antiga ETAPA 3 (aplicacao de verdade dos planos de ajuste de abertura
# PRE-criacao - _node_neighbor_for_wall_end/_resize_wall_axis_for_opening_plan/
# apply_opening_adjustment_plans) foi REMOVIDA junto com a ETAPA 1 (ver
# comentario acima de describe_block_course) - mesmo motivo: permitia mudar
# largura/comprimento de eixo, o que a regra nova proibe. A correcao
# conjunta de parede+abertura agora e' inteira responsabilidade da ETAPA
# 3B, mais abaixo.


# ==========================================
# VALIDADOR AO VIVO (Dynamic Model Update) - mantem o realce azul de
# modulacao atualizado enquanto o usuario edita o modelo, pelo resto da
# sessao do Revit, sem precisar rodar o botao de novo. So' observa os
# elementos criados/considerados NESTA execucao (ver AddTrigger em main())
# - nao toda parede/abertura do documento.
#
# Mecanismo: IUpdater/Dynamic Model Update, NAO o evento DocumentChanged -
# DocumentChanged e' somente-leitura (nao pode abrir Transacao dentro dele),
# enquanto o Execute() de um IUpdater roda DENTRO da propria transacao que
# esta sendo commitada, podendo chamar SetElementOverrides diretamente (aqui
# envolvido numa SubTransaction, por seguranca/isolamento).
# ==========================================

# GUIDs FIXOS (nunca reutilizar/gerar de novo em outra parte do codigo -
# UpdaterId = AddInId + este Guid; um Guid diferente vira' um updater
# DIFERENTE aos olhos do Revit, perdendo o registro/triggers anteriores).
WALL_MODULATION_UPDATER_GUID = Guid("A1B2C3D4-1111-4A2B-8C3D-000000000001")
OPENING_MODULATION_UPDATER_GUID = Guid("A1B2C3D4-1111-4A2B-8C3D-000000000002")
# GUID 3 (SUSPECT_DEAD_END_UPDATER_GUID) foi da feature "ponta de parede
# suspeita", REMOVIDA por completo (2026-08-26, pedido do usuario) - o
# numero NUNCA e' reaproveitado para outro updater (ver aviso acima).


def _refresh_wall_modulation_override(up_doc, view, wall_id, opening_gaps):
    """Reavalia UMA parede pela regra de modulacao (ja' considerando se ela
    e' um pilarete encostado num vao - ver _wall_is_pier_at_opening) e
    aplica a cor certa, NESTA ordem de prioridade (ver evaluate_wall_
    block_length/is_clean_cm - vermelho tem precedencia mesmo sobre uma
    parede `compatible=True`, ja' que a tolerancia LARGA da aritmetica de
    modulacao absorveria silenciosamente um residuo pequeno tipo 25,01cm):
    VERMELHO (`not is_clean_cm` - comprimento quebrado), AZUL (`is_clean_cm`
    e `not compatible` - integro mas nao fecha em blocos) ou nenhuma
    (`is_clean_cm` e `compatible` - valida). Cada chamada roda na sua
    propria SubTransaction, entao uma parede problematica nao derruba as
    outras.

    Fatorada para ser usada pelos DOIS updaters: o de parede (quando a
    propria parede muda) e o de abertura (quando um vao se move e os
    pilaretes ao redor mudam de regra sem terem sido tocados). Sem isso as
    duas reavaliacoes divergiriam com o tempo.

    ATE' 2026-08-26 havia aqui uma checagem "se ja' esta' vermelho, nao
    mexe" - existia porque o vermelho era de uma feature DIFERENTE (ponta
    suspeita) e concorrente com este updater. Essa feature foi REMOVIDA por
    completo (vermelho reaproveitado para comprimento quebrado, que vem do
    MESMO evaluate_wall_modulation usado aqui) - nao ha' mais nenhuma
    checagem concorrente para proteger, este updater agora e' a UNICA
    fonte da cor de uma parede."""
    results = evaluate_wall_modulation([wall_id], up_doc, opening_gaps)
    if not results:
        return
    entry = results[0]
    st = SubTransaction(up_doc)
    st.Start()
    try:
        if not entry["is_clean_cm"]:
            _apply_broken_length_overrides(view, [wall_id], up_doc)
        elif entry["compatible"]:
            view.SetElementOverrides(wall_id, OverrideGraphicSettings())
        else:
            _apply_modulation_incompatible_overrides(view, [wall_id], up_doc)
        st.Commit()
    except Exception:
        st.RollBack()


def _walls_touching_gaps(up_doc, view, gaps, reach_ft):
    """Ids das paredes cuja RETA passa perto de algum vao de `gaps` e cuja
    ponta mais proxima esta' a `reach_ft` do centro dele - o conjunto de
    paredes que podem ter mudado de classificacao (pilarete <-> parede
    comum) porque a abertura se mexeu. Bem mais barato que reavaliar o
    documento inteiro, e suficiente: uma abertura so' afeta as paredes que
    encostam nela."""
    touched = []
    for wall in FilteredElementCollector(up_doc, view.Id).OfClass(Wall):
        try:
            location = wall.Location
            if not isinstance(location, LocationCurve):
                continue
            curve = location.Curve
            a_raw = curve.GetEndPoint(0)
            b_raw = curve.GetEndPoint(1)
            a = XYZ(a_raw.X, a_raw.Y, 0.0)
            b = XYZ(b_raw.X, b_raw.Y, 0.0)
            for center, half_width_ft in gaps:
                if (min(center.DistanceTo(a), center.DistanceTo(b))
                        <= half_width_ft + reach_ft):
                    touched.append(wall.Id)
                    break
        except Exception:
            continue
    return touched


class _LiveUpdaterBase(IUpdater):
    """Base dos tres updaters ao vivo. Existe por UM motivo especifico:
    guardar, no proprio objeto (`self._g`), o dicionario de globais do
    modulo no instante da criacao.

    POR QUE ISSO E' NECESSARIO (diagnosticado ao vivo, com o updater
    instrumentado): o Execute() de um updater roda muito tempo depois - a
    cada edicao do usuario, pelo resto da sessao do Revit. Ele precisa de
    varios nomes do modulo (evaluate_wall_modulation, SubTransaction,
    _current_override_is_red, ...). Se o dicionario de globais daquela
    execucao do Script.py deixar de estar disponivel, TODA busca de nome
    dentro do Execute falha - e, como o Execute engole excecoes de proposito
    (para nao disparar o dialogo "o atualizador de terceiros teve um
    problema"), o updater passa a aparecer como REGISTRADO e ATIVADO mas
    nao faz absolutamente nada, EM SILENCIO. Foi exatamente esse o sintoma
    observado: parede ajustada para 126cm (valida) continuando azul, com
    IsUpdaterRegistered=True e IsUpdaterEnabled=True.

    Segurar o dicionario aqui garante que ele nao possa sumir enquanto o
    objeto estiver registrado. Os Execute() abaixo resolvem tudo por
    `self._g[...]` em vez de confiar na busca normal de nomes."""

    # __namespace__ e' EXIGIDO pelo pythonnet (engine CPython) para que uma
    # classe Python que deriva de uma interface .NET (IUpdater) vire um tipo
    # CLR que a REFLEXAO enxerga como implementando essa interface de
    # verdade. Sem isso, o objeto ate' responde aos metodos do Python
    # normalmente, mas o proprio Revit falha ao checar via reflexao se ele
    # implementa IUpdater - e' exatamente o erro "object does not implement
    # IUpdater" (confirmado ao vivo; ver tambem
    # https://github.com/pythonnet/pythonnet/issues/1774,
    # "Classes without __namespace__ cannot be used for reflection"). No
    # engine IronPython antigo isso nunca foi necessario, por isso o bug so'
    # apareceu depois da troca para `#! python3` (ver LOADER_SETUP.md).
    #
    # PRECISA SER UNICO A CADA EXECUCAO do Script.py (nao um literal fixo):
    # o loader baixa e reexecuta core/wall_modeling.py a cada clique no
    # botao, redefinindo esta classe (e as concretas abaixo) no MESMO
    # processo/engine CPython, que fica vivo pelo resto da sessao do Revit.
    # Registrar duas vezes o mesmo par namespace+nome de classe no mesmo
    # processo e' o cenario que gera novos tipos CLR colidindo com os
    # anteriores; um uuid4 por execucao evita a colisao sem precisar
    # reiniciar o Revit a cada clique.
    __namespace__ = "ModulacaoAutomatica.LiveUpdaters." + uuid.uuid4().hex

    def __init__(self, addin_id, updater_guid):
        self._updater_id = UpdaterId(addin_id, updater_guid)
        # COPIA (dict(...)), nunca a referencia viva de globals(): guardar o
        # PROPRIO dicionario do modulo nao protege nada - e' o mesmo objeto
        # que o modulo usa, entao ele perde os nomes JUNTO com o modulo numa
        # reexecucao do Script.py, que e' exatamente o que este snapshot
        # deveria evitar.
        self._g = dict(globals())

    def GetUpdaterId(self):
        return self._updater_id

    def GetAdditionalInformation(self):
        # Membro exigido pela interface IUpdater (alem de GetUpdaterId,
        # GetUpdaterName, GetChangePriority e Execute) - sem ele o Revit
        # lanca AttributeError ao tentar descrever o updater (confirmado
        # empiricamente rodando os updaters de verdade).
        return ""


class _WallModulationUpdater(_LiveUpdaterBase):
    """Reavalia SO' as paredes cujo Id foi armado via AddTrigger (ver
    main(), depois da criacao) sempre que algo nelas muda (geometria, tipo,
    o que for - Element.GetChangeTypeAny()). Reusa evaluate_wall_modulation
    - a MESMA regra usada na validacao "de uma vez" (Parte A) - para nunca
    divergir entre a checagem inicial e a ao vivo."""

    def __init__(self, addin_id):
        _LiveUpdaterBase.__init__(self, addin_id, WALL_MODULATION_UPDATER_GUID)

    def GetUpdaterName(self):
        return "Validacao ao vivo - comprimento de parede (modulacao de blocos)"

    def GetChangePriority(self):
        return ChangePriority.FloorsRoofsStructuralWalls

    def Execute(self, data):
        # Try/except EM CADA NIVEL de propósito (por elemento, e um ultimo
        # por fora de tudo): desde que o escopo observado virou "qualquer
        # Wall do documento" (ver AddTrigger em main()), este Execute()
        # passou a rodar para paredes de QUALQUER lugar do projeto - visao
        # 3D, outro nivel, opcao de projeto inativa, etc. Uma excecao NAO
        # CAPTURADA aqui (ex.: view.GetElementOverrides falhando pra uma
        # parede que nao e' controlavel/visivel nesta `view`) escapava ate'
        # o Revit, que cancelava a acao inteira e chegava a OFERECER
        # DESATIVAR O ATUALIZADOR (dialogo "atualizador de terceiros teve
        # um problema") - por isso NENHUMA excecao pode escapar daqui.
        try:
            g = self._g   # ver _LiveUpdaterBase: nada aqui pode depender da
                          # busca normal de nomes do modulo
            refresh = g["_refresh_wall_modulation_override"]
            get_gaps = g["_get_opening_gaps"]

            up_doc = data.GetDocument()
            view = up_doc.ActiveView
            if view is None:
                return
            changed_ids = list(data.GetModifiedElementIds()) + list(data.GetAddedElementIds())
            if not changed_ids:
                return
            # Lista de vaos calculada UMA vez por disparo (e servida do
            # cache entre disparos) - ver _get_opening_gaps.
            opening_gaps = get_gaps(up_doc)
            for wid in changed_ids:
                try:
                    if up_doc.GetElement(wid) is None:
                        continue
                    refresh(up_doc, view, wid, opening_gaps)
                except Exception:
                    continue
        except Exception:
            pass


class _OpeningModulationUpdater(_LiveUpdaterBase):
    """Mesma ideia de _WallModulationUpdater, para a LARGURA das aberturas
    (parametro Largura_abertura). Observa so' os Ids de INSTANCIA armados
    via AddTrigger (nao o Tipo/Symbol) - LIMITACAO CONHECIDA: se
    Largura_abertura estiver gravado como parametro de TIPO (nao de
    instancia - ver _lookup_param_value, que tenta a instancia primeiro e
    cai para o Tipo so' como fallback) e o usuario editar o valor pela
    caixa de Propriedades do TIPO em vez da instancia, esta edicao ao vivo
    nao vai disparar (precisa rodar o script de novo). Optou-se por essa
    limitacao documentada em vez de tambem vigiar o Symbol - vigiar o
    Symbol exigiria mapear "qual Symbol pertence a quais instancias desta
    execucao", que nao sobrevive entre execucoes separadas do botao sem
    guardar estado fora do Python (o proprio objeto updater persiste
    registrado no Revit entre cliques, mas cada clique roda um modulo novo,
    sem referencia ao objeto anterior)."""

    def __init__(self, addin_id):
        _LiveUpdaterBase.__init__(self, addin_id, OPENING_MODULATION_UPDATER_GUID)

    def GetUpdaterName(self):
        return "Validacao ao vivo - largura de abertura (modulacao de blocos)"

    def GetChangePriority(self):
        return ChangePriority.DoorsOpeningsWindows

    def Execute(self, data):
        # Ver os comentarios equivalentes em _LiveUpdaterBase (por que tudo
        # sai de self._g) e em _WallModulationUpdater.Execute (por que
        # nenhuma excecao pode escapar daqui).
        try:
            g = self._g
            is_red = g["_current_override_is_red"]
            lookup = g["_lookup_param_value"]
            width_param = g["OPENING_WIDTH_PARAM"]
            feet_per_meter = g["FEET_PER_METER"]
            evaluate_len = g["_evaluate_modulation_length"]
            valid_digits = g["OPENING_VALID_LAST_DIGITS_CM"]
            SubTrans = g["SubTransaction"]
            OGS = g["OverrideGraphicSettings"]
            paint = g["_apply_modulation_incompatible_overrides"]
            invalidate_gaps = g["_invalidate_opening_gap_cache"]

            up_doc = data.GetDocument()
            view = up_doc.ActiveView
            if view is None:
                return
            changed_ids = list(data.GetModifiedElementIds()) + list(data.GetAddedElementIds())
            # Uma abertura mudou (posicao, largura, ou foi criada): a lista
            # de vaos em cache ficou velha, e e' ela que decide quais
            # paredes contam como PILARETE (ver _wall_is_pier_at_opening).
            # Sem isto, mover um vao nao reclassificaria os pilaretes.
            if not changed_ids:
                return
            invalidate_gaps(up_doc)

            # Reavalia as paredes ao redor dos vaos: mover uma abertura NAO
            # mexe nas paredes vizinhas (elas sao elementos separados,
            # criados por build_wall_segments), entao o updater de PAREDE
            # nunca seria disparado por essa mudanca - mas a regra que vale
            # para elas pode ter acabado de mudar (pilarete <-> parede
            # comum). Sem este passo, afastar um vao deixaria o pilarete
            # com a cor da regra antiga ate' alguem tocar nele.
            try:
                gaps = g["_get_opening_gaps"](up_doc)
                refresh = g["_refresh_wall_modulation_override"]
                reach = g["PIER_AT_OPENING_TOLERANCE_FT"]
                for wall_id in g["_walls_touching_gaps"](up_doc, view, gaps, reach):
                    try:
                        refresh(up_doc, view, wall_id, gaps)
                    except Exception:
                        continue
            except Exception:
                pass

            for eid in changed_ids:
                try:
                    inst = up_doc.GetElement(eid)
                    if inst is None:
                        continue
                    if is_red(view, eid):
                        continue
                    width_ft = lookup(inst, [width_param])
                    if width_ft is None:
                        continue
                    width_cm = width_ft / feet_per_meter * 100.0
                    entry = evaluate_len(width_cm, valid_digits)
                    st = SubTrans(up_doc)
                    st.Start()
                    try:
                        if entry["compatible"]:
                            view.SetElementOverrides(eid, OGS())
                        else:
                            paint(view, [eid], up_doc)
                        st.Commit()
                    except Exception:
                        st.RollBack()
                except Exception:
                    continue
        except Exception:
            pass


# _live_point_explained/_SuspectDeadEndUpdater (feature "ponta de parede
# suspeita") foram REMOVIDOS por completo (2026-08-26, pedido explicito do
# usuario) - vermelho agora e' o comprimento quebrado, calculado pelo MESMO
# evaluate_wall_modulation que ja' decide azul/normal (ver
# _refresh_wall_modulation_override) - nao precisa mais de um terceiro
# updater dedicado.


def _register_modulation_updaters_if_needed():
    """(Re)registra os DOIS updaters ao vivo (ver acima) a cada execucao do
    botao (ate' 2026-08-26 eram tres - o terceiro, de "ponta suspeita", foi
    removido por completo, ver comentario acima de _live_point_explained).
    Registro APP-WIDE (sem amarrar a um Document especifico) porque
    este ponto roda antes de qualquer selecao do usuario; quem define o
    ESCOPO (quais elementos sao observados) e' o AddTrigger, chamado depois
    por main(). Devolve os dois updaters para que main() possa pegar o
    GetUpdaterId() de cada um e chamar AddTrigger.

    SEMPRE DESREGISTRA ANTES DE REGISTRAR - nao basta pular o registro
    quando IsUpdaterRegistered ja' e' True (que foi como isto funcionou
    ate' esta correcao). Motivo, confirmado empiricamente rodando os dois
    caminhos lado a lado: RegisterUpdater guarda a referencia do OBJETO
    Python passado. Cada clique no botao faz o pyRevit reexecutar o
    Script.py do zero, criando objetos NOVOS - mas, com o registro pulado,
    o Revit continuava chamando o Execute() do objeto da PRIMEIRA execucao
    da sessao. Na pratica isso significa que qualquer correcao feita no
    codigo de um Execute() so' passava a valer depois de FECHAR E REABRIR o
    Revit - inclusive as correcoes de robustez que evitam o dialogo "o
    atualizador de terceiros teve um problema".

    Desregistrar tambem descarta os triggers anteriores, o que aqui e'
    desejavel e nao perde nada: main() re-adiciona o escopo completo
    (ElementClassFilter de Wall/FamilyInstance) logo em seguida, a cada
    execucao."""
    addin_id = doc.Application.ActiveAddInId
    wall_updater = _WallModulationUpdater(addin_id)
    opening_updater = _OpeningModulationUpdater(addin_id)
    for updater in (wall_updater, opening_updater):
        updater_id = updater.GetUpdaterId()
        if UpdaterRegistry.IsUpdaterRegistered(updater_id):
            try:
                UpdaterRegistry.UnregisterUpdater(updater_id)
            except Exception:
                # Se por algum motivo nao der para remover o antigo, seguir
                # com ele registrado e' melhor que abortar o script todo -
                # o RegisterUpdater abaixo e' que lancaria de verdade, e por
                # isso tambem esta' protegido.
                pass
        try:
            UpdaterRegistry.RegisterUpdater(updater)
        except Exception:
            pass
    return wall_updater, opening_updater


# ==========================================
# ETAPA 3B - CORRECAO POS-CRIACAO CONJUNTA DE PAREDES E ABERTURAS.
#
# REMOVIDA COMPLETAMENTE (2026-08-21, regra #1 do usuario): a antiga
# "sugestao de ampliacao de comodo" (find_wall_loops /
# suggest_room_enlargement / apply_room_axis_enlargement / _classify_rectangle
# / _walls_share_endpoint / _wall_endpoint_index_touching /
# _rebuild_curve_with_endpoint). Ela existia para AUMENTAR as paredes de um
# comodo retangular ate' a modulacao encaixar - exatamente o que agora e'
# proibido: o script NUNCA aumenta uma parede alem da dimensao original so'
# para acomodar blocos, e nunca cria prolongamento/"dente" na extremidade.
# Nao reintroduzir: se a modulacao nao fecha, a saida e' reavaliar a
# combinacao de blocos (e, no maximo, ENCURTAR uma ponta livre) - ver
# plan_axis_opening_fix.
#
# A ETAPA 3B (_classify_wall_axis_segments em diante) e' o motor NOVO que
# roda automaticamente dentro do passo "Ajustar Erros" da janela unica -
# ver cabecalho dessa secao mais abaixo para o desenho completo. Ela
# SUBSTITUI o antigo mecanismo de deslocamento de 1 abertura por vez
# (suggest_opening_shift/apply_opening_shift, removidos) porque esse
# antigo so' aceitava eixos com exatamente 3 segmentos Wall - uma janela
# real (peitoril + verga) gera 4, entao NUNCA se aplicava a uma janela de
# verdade; alem disso nunca escrevia a correcao de volta em
# openings_per_wall, entao o solver de blocos (Etapa 4/5) calculava sobre
# geometria desatualizada mesmo depois de uma abertura ser corrigida.
# ==========================================

RECTANGLE_PERPENDICULAR_TOLERANCE = 0.05   # mesma escala/ordem de are_lines_parallel
RECTANGLE_SIDE_LENGTH_TOLERANCE_M = 0.05
RECTANGLE_SIDE_LENGTH_TOLERANCE_FT = RECTANGLE_SIDE_LENGTH_TOLERANCE_M * FEET_PER_METER

# Teto (cm) de deslocamento AUTOMATICO de uma abertura - pedido explicito
# do usuario: acima disso a correcao existe matematicamente mas e' grande
# demais para aplicar sozinha, o eixo inteiro vai para revisao manual (ver
# ETAPA 3B mais abaixo, solve_axis_opening_modulation/plan_axis_opening_fix).
AXIS_OPENING_SHIFT_MAX_CM = 5.0

# Teto (cm) de AUMENTO de largura de abertura - ultimo recurso da ETAPA 3B
# (ver cabecalho mais abaixo): so' e' tentado quando nem o deslocamento
# simples nem esticar uma ponta livre da parede resolvem. Pedido explicito
# do usuario (2026-08-20): NUNCA reduzir, NUNCA passar deste teto, e sempre
# preferir a menor alteracao possivel dentre as combinacoes validas.
OPENING_WIDTH_INCREASE_MAX_CM = 5.0

# _axis_free_end_sides MOVEU para core/engine/wall_stepper.py (junto com a
# ETAPA 4/3C) porque find_wall_group_shift_fixes tambem depende dela -
# continua acessivel aqui por nome solto via o `import *` da ETAPA 4 acima.


def _opening_width_increase_options_cm(width_cm, max_increase_cm=OPENING_WIDTH_INCREASE_MAX_CM):
    """Lista (crescente) dos aumentos inteiros de largura, em cm, entre 1 e
    `max_increase_cm`, que fariam `width_cm` continuar valido pela regra das
    ABERTURAS (terminar em 1, 6 ou 9 - ver OPENING_VALID_LAST_DIGITS_CM).
    NUNCA sugere reducao (regra explicita do usuario: so' aumentar)."""
    base = int(round(width_cm))
    options = []
    for delta in range(1, int(max_increase_cm) + 1):
        if ((base + delta) % 10) in OPENING_VALID_LAST_DIGITS_CM:
            options.append(delta)
    return options


def _widen_pier_gaps_for_opening_increase(pier_gaps_cm, opening_deltas_cm, min_pier_cm):
    """Devolve uma copia de `pier_gaps_cm` (N+1 valores) com o efeito de
    aumentar a abertura `i` em `opening_deltas_cm[i]` cm: o pilar VIZINHO
    (tentando primeiro o da DIREITA - indice i+1 - e so' o da ESQUERDA -
    indice i - se o da direita nao tiver folga) encolhe pela mesma
    quantidade, ja que o comprimento do eixo e as demais aberturas nao
    mudam. Devolve None se nenhum dos dois lados tiver folga suficiente
    (pilar resultante menor que `min_pier_cm`) para alguma abertura - nesse
    caso esta combinacao de deltas e' geometricamente inviavel."""
    adjusted = list(pier_gaps_cm)
    for i, delta in enumerate(opening_deltas_cm):
        if not delta:
            continue
        right_idx = i + 1
        left_idx = i
        if adjusted[right_idx] - delta >= min_pier_cm:
            adjusted[right_idx] -= delta
        elif adjusted[left_idx] - delta >= min_pier_cm:
            adjusted[left_idx] -= delta
        else:
            return None
    return adjusted


def _solve_axis_width_increase(pier_gaps_cm, opening_widths_cm, max_shift_cm=AXIS_OPENING_SHIFT_MAX_CM,
                                max_width_increase_cm=OPENING_WIDTH_INCREASE_MAX_CM,
                                min_pier_cm=MIN_SEGMENT_LENGTH_FT / FEET_PER_METER * 100.0,
                                accept=None, include_alternatives=False):
    """TERCEIRA opcao da ETAPA 3B (ver cabecalho mais abaixo): quando nem
    deslocar as aberturas nem esticar uma ponta livre da parede fecham a
    soma dos pilaretes num multiplo de 5cm, procura a MENOR combinacao de
    aumentos de largura (cada abertura no maximo `max_width_increase_cm`,
    cada aumento so' aceito se resultar numa largura ainda valida pela regra
    das aberturas - ver _opening_width_increase_options_cm) cuja soma resolva
    a equacao (a mesma prova de solve_axis_opening_modulation: a soma dos
    pilaretes precisa ser multipla de 5; aumentar `D` cm de abertura reduz
    essa soma em `D`).

    Busca com PARADA ANTECIPADA, nao exaustiva - cada candidato testado
    exige chamar solve_axis_opening_modulation (que por sua vez pode fazer
    uma busca combinatoria propria, ate 4096 combinacoes, sobre os
    pilaretes) - testar TODAS as combinacoes de largura possiveis (que
    cresce exponencialmente com o numero de aberturas do eixo) multiplicava
    as duas buscas e travava por dezenas de minutos em eixos reais com
    varias aberturas (medido ao vivo via MCP, 2026-08-20 - NAO reintroduzir
    a busca exaustiva antiga sem um limite MUITO mais apertado que
    combo_count<=20000, que na pratica nao protegia nada). Em vez disso,
    gera os candidatos em ORDEM CRESCENTE de "menor alteracao" (regra do
    usuario) - primeiro TODAS as aberturas sozinhas com o unico delta
    matematicamente possivel para elas (ver prova no docstring: a soma dos
    pilaretes so' fecha se o total de aumento for congruente a `r` modulo
    PIER_MODULE_CM; com deltas limitados a (0, max_width_increase_cm], o
    UNICO valor congruente a `r` e' o proprio `r`), depois pares de
    aberturas (limitado a MAX_PAIR_ATTEMPTS tentativas, as de menor soma
    primeiro) - e PARA no primeiro candidato que realmente fechar a
    modulacao. Isso reduz o numero de chamadas caras a
    solve_axis_opening_modulation de potencialmente milhares para, no pior
    caso, algumas dezenas.

    Devolve None se nenhum candidato tentado resolver, ou
        (opening_deltas_cm, solution) onde `opening_deltas_cm` e' uma lista
        (1 por abertura, 0 se nao mudou) e `solution` e' o dict devolvido
        por solve_axis_opening_modulation aplicado aos pilaretes ja
        ajustados pelo aumento escolhido."""
    # Baixo DE PROPOSITO: os candidatos ja vem ordenados da MENOR alteracao
    # para a maior (regra do usuario), entao as primeiras tentativas sao as
    # unicas que realmente interessam - e cada uma custa uma chamada
    # completa a solve_axis_opening_modulation. Com 60 (valor inicial) a
    # etapa de analise da planta inteira levava dezenas de minutos.
    MAX_PAIR_ATTEMPTS = 8

    n = len(opening_widths_cm)
    if n == 0:
        return None

    total_cm = sum(pier_gaps_cm)
    total_rounded = int(round(total_cm))
    r = total_rounded % PIER_MODULE_CM
    if r == 0 and not include_alternatives:
        return None  # nada a "consertar" aumentando largura - ver chamador

    per_opening_options = [
        set(_opening_width_increase_options_cm(w, max_width_increase_cm))
        for w in opening_widths_cm
    ]

    def _try(deltas):
        """Testa UM conjunto de aumentos de largura. `accept(deltas,
        solution)`, quando dado, e' quem tem a palavra final - e' por ele
        que o SOLVER DE BLOCOS DE VERDADE entra na decisao (regra #3), em
        vez de a aritmetica sozinha aprovar o ajuste."""
        adjusted = _widen_pier_gaps_for_opening_increase(pier_gaps_cm, deltas, min_pier_cm)
        if adjusted is None:
            return None
        for solution in enumerate_axis_opening_modulations(
                adjusted, max_shift_cm, include_alternatives=include_alternatives):
            if not solution["within_auto_apply_limit"]:
                continue
            if accept is not None and not accept(deltas, solution):
                continue
            return solution
        return None

    # 1) UMA abertura sozinha: o unico delta possivel e' exatamente `r`
    # (qualquer outro valor em (0, max] nao e' congruente a r modulo 5,
    # entao nunca fecharia a soma - nem vale a pena testar).
    for i in range(n):
        options = sorted(per_opening_options[i]) if include_alternatives else (
            [r] if r in per_opening_options[i] else []
        )
        for delta in options:
            deltas = [0] * n
            deltas[i] = delta
            solution = _try(deltas)
            if solution is not None:
                return deltas, solution

    # 2) DUAS aberturas: candidatos (delta_i, delta_j) com
    # (delta_i+delta_j) % 5 == r, ordenados pela MENOR soma total primeiro
    # (regra do usuario - menor alteracao possivel), com um teto de
    # tentativas para nunca degenerar num caso patologico.
    pair_candidates = []
    for i in range(n):
        for di in per_opening_options[i]:
            for j in range(i + 1, n):
                for dj in per_opening_options[j]:
                    if not include_alternatives and (di + dj) % PIER_MODULE_CM != r:
                        continue
                    pair_candidates.append((di + dj, i, di, j, dj))
    pair_candidates.sort(key=lambda c: c[0])

    for total, i, di, j, dj in pair_candidates[:MAX_PAIR_ATTEMPTS]:
        deltas = [0] * n
        deltas[i] = di
        deltas[j] = dj
        solution = _try(deltas)
        if solution is not None:
            return deltas, solution

    return None


def _set_opening_width_param(inst, new_width_ft):
    """Escreve `new_width_ft` (pes) em OPENING_WIDTH_PARAM (`Largura_abertura`)
    - SOMENTE na INSTANCIA, NUNCA no Symbol/FamilySymbol (tipo). Trata os
    dois casos de unidade (Numero puro em CENTIMETROS vs parametro real de
    Comprimento) da mesma forma que `_param_value_as_feet` LE, so' que na
    direcao inversa (ESCRITA). Precisa rodar dentro de uma Transacao/
    SubTransacao ja aberta pelo chamador. Devolve True se conseguiu
    escrever, False senao (nunca lanca excecao para fora).

    NUNCA escreve no Symbol (causa raiz de um incidente real, 2026-08-24):
    quando `Largura_abertura` e' parametro de TIPO (comum em familias de
    porta/janela), Symbol.LookupParameter(...) o' devolve, e escrever ali
    muda a largura de TODAS as instancias daquele tipo no projeto de uma
    vez - a geometria parametrica da familia pode nao aceitar aquela
    combinacao especifica de largura + outros parametros travados, e o
    Revit reage com uma caixa de dialogo cuja unica saida e' 'Excluir
    tipo', que apaga TODAS as instancias daquele tipo do modelo (foi assim
    que 8 aberturas sumiram do projeto, confirmado ao vivo via MCP). Se o
    parametro so' existir no Symbol (nao na instancia), este metodo
    simplesmente devolve False - o chamador trata isso como "nao foi
    possivel", igual a qualquer outra falha de escrita, em vez de arriscar
    o projeto inteiro."""
    param = inst.LookupParameter(OPENING_WIDTH_PARAM)
    if param is None or param.IsReadOnly:
        return False
    try:
        raw = param.AsDouble()
        display_num = None
        try:
            display_str = param.AsValueString()
            display_num = float(display_str.strip().split()[0].replace(".", "").replace(",", "."))
        except (TypeError, ValueError, AttributeError, IndexError):
            display_num = None
        if display_num is not None and abs(raw - display_num) < 0.001:
            param.Set(new_width_ft / FEET_PER_METER * 100.0)  # Numero puro em cm
        else:
            param.Set(new_width_ft)  # parametro real de Comprimento, ja em pes
        return True
    except Exception:
        return False


# ------------------------------------------------------------------------
# ETAPA 3B - CORRECAO POS-CRIACAO DE MODULACAO (pilaretes reais + aberturas)
#
# Roda DEPOIS das paredes reais ja' criadas (diferente da antiga ETAPA 1,
# removida - ver main()), dentro do passo "Ajustar Erros" da janela unica.
# Trata parede e abertura como UMA coisa so': para cada eixo com pilar(es)
# fora da modulacao, encontra o deslocamento MINIMO (nunca de largura, nunca
# de comprimento de eixo - regra nova do usuario) que faz TODOS os pilaretes
# daquele eixo fecharem em multiplos de 5cm, prioriza manter a posicao
# atual, e so' aplica automaticamente ate' AXIS_OPENING_SHIFT_MAX_CM (5cm) -
# acima disso o eixo inteiro vai para revisao manual (nunca aplica um plano
# pela metade, mesma politica de apply_opening_adjustment_plans).
# ------------------------------------------------------------------------

def _axis_t_of_point(centerline, point):
    """Projeta `point` (XYZ) no eixo `centerline` (Line), devolvendo o
    parametro `t` na MESMA convencao usada por assign_openings_to_walls -
    extraida para ser reusada tanto pela leitura ao vivo em
    _classify_wall_axis_segments quanto pela captura do snapshot leve
    (`wall_segment_geometry`) logo apos a criacao das Walls (ver main(),
    Etapa 1) - a MESMA formula nos dois lugares garante que o snapshot
    nunca diverge do que a leitura ao vivo devolveria."""
    p0 = centerline.GetEndPoint(0)
    direction = centerline.Direction
    vec = XYZ(point.X - p0.X, point.Y - p0.Y, 0.0)
    return vec.DotProduct(XYZ(direction.X, direction.Y, 0.0))


def _classify_wall_axis_segments(target_doc, wall_idx, walls_to_create, openings_per_wall,
                                  created_walls_by_axis, tolerance_ft=PIER_AT_OPENING_TOLERANCE_FT,
                                  wall_segment_geometry=None):
    """Classifica os segmentos de UM eixo (piares/vaos) contra as aberturas
    de openings_per_wall[wall_idx], projetando as pontas de cada segmento
    sobre o eixo original (mesmo `t` de assign_openings_to_walls) -
    SUBSTITUI a suposicao rigida de "exatamente 3 segmentos cad/abertura/cad"
    que apply_opening_shift usava (e que rejeitava qualquer janela real com
    peitoril+verga, ja' que essa combinacao gera 4 segmentos) por um
    casamento geometrico que aceita 1 OU 2 segmentos "abertura" por vao.

    `wall_segment_geometry`: snapshot leve opcional (dict {wall_idx:
    [{"element_id", "seg_origin", "t_a", "t_b"}, ...]}), capturado UMA
    UNICA VEZ logo apos a criacao das Walls (ver main(), Etapa 1,
    _axis_t_of_point). Quando fornecido (mesmo que vazio), esta funcao
    NUNCA toca `target_doc` - usa o snapshot e, se ele nao tiver uma
    entrada completa para este eixo, devolve None (fora de escopo) em vez
    de cair para leitura ao vivo. Isso e' o que permite rodar todo o
    planejamento de modulacao (plan_axis_opening_fix e tudo que depende
    dela) numa thread de fundo, sem contexto de API valido. Sem ele
    (None, o default), mantem o comportamento antigo de ler
    target_doc.GetElement(...).Location.Curve ao vivo - usado por
    apply_wall_group_shift, que roda DEPOIS de escritas reais e precisa
    da geometria mais atual.

    Devolve None (fora de escopo - nunca lanca excecao) se created_walls_by_axis
    nao tiver entradas para este eixo, se a parede real nao tiver
    LocationCurve (ou o snapshot estiver incompleto), se o eixo nao tiver
    nenhuma abertura, se algum vao nao tiver nenhum segmento "abertura"
    correspondente, ou se a CONTAGEM de pilaretes reais nao bater com "1 a
    mais que o numero de aberturas" (ex.: abertura encostada na ponta/
    juncao do eixo, sem pilar real ali para editar - este motor so' EDITA
    curvas existentes, nunca cria/apaga topologia).

    Senao devolve:
        {"wall_idx":, "axis_len_ft":,
         "piers": [{"index":k, "element_id":, "t_a":, "t_b":}, ...],  # N+1
         "openings": [{"opening_index":i, "t_lo":, "t_hi":, "sill_z_abs":,
                        "head_z_abs":, "infill_ids": [...]}, ...]}  # N
    """
    entries = created_walls_by_axis.get(wall_idx) or []
    if not entries:
        return None
    centerline, _thickness_ft, _locks = walls_to_create[wall_idx]

    if wall_segment_geometry is not None:
        snapshot = wall_segment_geometry.get(wall_idx)
        if not snapshot or len(snapshot) != len(entries):
            return None
        segments = [dict(s) for s in snapshot]
    else:
        segments = []
        for element_id, seg_origin in entries:
            wall = target_doc.GetElement(element_id)
            if wall is None or not isinstance(wall.Location, LocationCurve):
                return None
            curve = wall.Location.Curve
            t_a = _axis_t_of_point(centerline, curve.GetEndPoint(0))
            t_b = _axis_t_of_point(centerline, curve.GetEndPoint(1))
            if t_a > t_b:
                t_a, t_b = t_b, t_a
            segments.append({"element_id": element_id, "seg_origin": seg_origin,
                              "t_a": t_a, "t_b": t_b})
    segments.sort(key=lambda s: s["t_a"])

    piers = [s for s in segments if s["seg_origin"] == "cad"]
    infills = [s for s in segments if s["seg_origin"] != "cad"]

    openings_here = openings_per_wall[wall_idx] if wall_idx < len(openings_per_wall) else []
    if not openings_here:
        return None
    if len(piers) != len(openings_here) + 1:
        return None

    opening_rows = []
    for opening_index, (t_lo, t_hi, sill_z_abs, head_z_abs) in enumerate(openings_here):
        matched_infills = [
            s for s in infills
            if s["t_a"] >= t_lo - tolerance_ft and s["t_b"] <= t_hi + tolerance_ft
        ]
        if not matched_infills:
            return None
        opening_rows.append({
            "opening_index": opening_index, "t_lo": t_lo, "t_hi": t_hi,
            "sill_z_abs": sill_z_abs, "head_z_abs": head_z_abs,
            "infill_ids": [s["element_id"] for s in matched_infills],
        })

    pier_rows = [{"index": k, "element_id": s["element_id"], "t_a": s["t_a"], "t_b": s["t_b"]}
                 for k, s in enumerate(piers)]

    return {"wall_idx": wall_idx, "axis_len_ft": centerline.Length,
            "piers": pier_rows, "openings": opening_rows}


def _match_openings_for_axis(wall_idx, walls_to_create, openings_per_wall, all_openings,
                              tolerance_ft=0.01 * FEET_PER_METER):
    """Generaliza a antiga _match_wall_opening_for_shift (que so' tratava
    eixos com EXATAMENTE 1 abertura) para TODAS as aberturas de
    openings_per_wall[wall_idx] - openings_per_wall so' guarda o intervalo
    (t_lo, t_hi), nao a identidade da abertura; a re-associacao aqui usa o
    MESMO calculo deterministico de _project_opening_on_line que
    assign_openings_to_walls ja' usou, entao o intervalo bate quase
    exatamente (nao e' uma nova estimativa, e' so' recuperar a referencia
    perdida).

    Devolve {opening_index: opening_dict}."""
    result = {}
    openings_here = openings_per_wall[wall_idx] if wall_idx < len(openings_per_wall) else []
    if not openings_here:
        return result
    centerline, thickness_ft, _locks = walls_to_create[wall_idx]
    max_perp_dist_ft = thickness_ft / 2.0 + OPENING_ASSOC_TOLERANCE_FT
    for opening_index, (t_lo, t_hi, _sill, _head) in enumerate(openings_here):
        best_op, best_diff = None, None
        for op in all_openings:
            op_t_lo, op_t_hi, perp_dist = _project_opening_on_line(centerline, op)
            if perp_dist > max_perp_dist_ft:
                continue
            diff = abs(op_t_lo - t_lo) + abs(op_t_hi - t_hi)
            if diff <= tolerance_ft and (best_diff is None or diff < best_diff):
                best_diff = diff
                best_op = op
        if best_op is not None:
            result[opening_index] = best_op
    return result


# Teto de combinacoes C(n_gaps, remainder_units) que
# solve_axis_opening_modulation enumera exaustivamente antes de cair no
# fallback guloso. Acima disso o custo nao compensa - ver a nota de
# PERFORMANCE dentro da propria funcao.
MODULATION_COMBO_SEARCH_LIMIT = 2000


def _binomial(n, k):
    """C(n, k) - quantas combinacoes de `k` itens entre `n`. Usado so' para
    DECIDIR se vale enumerar exaustivamente (ver
    MODULATION_COMBO_SEARCH_LIMIT); `math.factorial` existe no IronPython
    2.7 do Revit, mas o produto iterativo abaixo evita numeros gigantes
    intermediarios para n grande."""
    if k < 0 or k > n:
        return 0
    k = min(k, n - k)
    result = 1
    for i in range(k):
        result = result * (n - i) // (i + 1)
    return result


def solve_axis_opening_modulation(pier_gaps_cm, max_shift_cm=AXIS_OPENING_SHIFT_MAX_CM,
                                  gap_residues_cm=None):
    """Solver conjunto parede+abertura: dados os N+1 "gaps" (pilaretes, em
    cm) ao redor/entre as N aberturas de UM eixo, encontra a particao
    desses gaps que minimiza o MAIOR deslocamento entre as N aberturas -
    NUNCA muda largura de abertura nem comprimento do eixo (ambos fixos),
    so' a POSICAO dos pontos de corte pilar/abertura/pilar/abertura/....

    `gap_residues_cm`: resto exigido de cada gap na divisao por
    PIER_MODULE_CM. Esse resto NAO e' uma regra de arredondamento - e' a
    aritmetica real das juntas daquele trecho (ver
    `pier_closes_with_blocks_cm`): um pilarete entre parede e abertura
    fecha em 5m, entre duas aberturas em 5m-1, entre duas paredes em 5m+1.
    `None` mantem o comportamento historico (todos os restos = 0); quem
    quer cobrir as outras possibilidades usa
    `enumerate_axis_opening_modulations`, que varre todas elas.

    IMPOSSIBILIDADE (generaliza a prova antiga): a soma R = sum(pier_gaps_cm)
    e' FIXA, entao uma particao valida so' existe se R e sum(restos) forem
    congruentes modulo PIER_MODULE_CM. Se nao forem, devolve None
    (impossivel - nenhum deslocamento, por maior que fosse, resolveria).

    Se o MAIOR deslocamento passar de `max_shift_cm`, ainda devolve o plano
    (com "within_auto_apply_limit": False) - o chamador decide.

    Devolve None ou:
        {"gaps_after_cm": [...],       # N+1 valores
         "opening_shifts_cm": [...],   # N valores (1 por abertura)
         "residues_cm": [...],         # o resto usado em cada gap
         "max_shift_cm": float, "within_auto_apply_limit": bool, "changed": bool}
    """
    n_gaps = len(pier_gaps_cm)
    if n_gaps < 2:
        return None  # sem abertura nenhuma pra deslocar - nada a fazer aqui

    if gap_residues_cm is None:
        residues = [0] * n_gaps
    else:
        if len(gap_residues_cm) != n_gaps:
            return None
        residues = [int(r) % PIER_MODULE_CM for r in gap_residues_cm]

    total_cm = sum(pier_gaps_cm)
    total_rounded = int(round(total_cm))
    if abs(total_cm - total_rounded) > MODULATION_WHOLE_CM_TOLERANCE_CM:
        return None  # eixo/larguras nao inteiros - nao deveria acontecer, rede de seguranca
    if ((total_rounded - sum(residues)) % PIER_MODULE_CM) != 0:
        return None  # IMPOSSIVEL - ver prova acima

    floors = []
    for i, gap_cm in enumerate(pier_gaps_cm):
        value = int(round(gap_cm))
        floor_value = value - ((value - residues[i]) % PIER_MODULE_CM)
        while floor_value < 0:
            floor_value += PIER_MODULE_CM
        floors.append(floor_value)
    base_sum = sum(floors)
    remainder_units = (total_rounded - base_sum) // PIER_MODULE_CM
    if remainder_units < 0 or remainder_units > n_gaps:
        return None  # nao ha' como distribuir a diferenca em passos de 5cm

    def _shifts_for(gaps_after):
        shifts = []
        cumulative = 0.0
        for i in range(n_gaps - 1):
            cumulative += gaps_after[i] - pier_gaps_cm[i]
            shifts.append(cumulative)
        return shifts

    # PERFORMANCE (medido ao vivo, 2026-08-20): esta funcao e' chamada
    # DEZENAS de vezes por eixo, e os eixos com muitas aberturas sao a
    # maioria nesta planta - por isso enumera DIRETAMENTE apenas as
    # combinacoes de `remainder_units` indices (C(n,k), sempre <= 2^n e
    # tipicamente muito menor) em vez de varrer todas as mascaras de bits.
    best = None

    def _consider_candidate(candidate):
        shifts = _shifts_for(candidate)
        max_shift = max([abs(s) for s in shifts]) if shifts else 0.0
        sum_shift = sum([abs(s) for s in shifts])
        return ((max_shift, sum_shift), candidate, shifts, max_shift)

    if remainder_units == 0:
        best = _consider_candidate(tuple(floors))
    else:
        combo_count = _binomial(n_gaps, remainder_units)
        if combo_count <= MODULATION_COMBO_SEARCH_LIMIT:
            for indices in itertools.combinations(range(n_gaps), remainder_units):
                candidate = list(floors)
                for i in indices:
                    candidate[i] += PIER_MODULE_CM
                entry = _consider_candidate(tuple(candidate))
                if best is None or entry[0] < best[0]:
                    best = entry
        else:
            # fallback guloso (eixo com muitas aberturas): sobe os gaps de
            # MAIOR resto primeiro - nao garante o otimo global, mas nunca
            # roda numa combinatoria absurda.
            residual_order = sorted(range(n_gaps), key=lambda i: -(pier_gaps_cm[i] - floors[i]))
            candidate = list(floors)
            for i in residual_order[:remainder_units]:
                candidate[i] += PIER_MODULE_CM
            best = _consider_candidate(tuple(candidate))

    if best is None:
        return None  # rede de seguranca - nao deveria ocorrer dado o calculo acima

    _key, gaps_after, opening_shifts_cm, max_shift_found = best
    return {
        "gaps_after_cm": list(gaps_after),
        "opening_shifts_cm": opening_shifts_cm,
        "residues_cm": list(residues),
        "max_shift_cm": max_shift_found,
        "within_auto_apply_limit": max_shift_found <= max_shift_cm + 1e-6,
        "changed": max_shift_found > 1e-6,
    }


# Restos POSSIVEIS de um pilarete na divisao por PIER_MODULE_CM, deduzidos
# da aritmetica das juntas (ver pier_closes_with_blocks_cm): junta 1+1 -> 1,
# junta 1+0 ou 0+1 -> 0, junta 0+0 -> 4. Nao ha' nenhum outro - e nenhum
# deles e' um "digito bonito" escolhido a mao.
PIER_POSSIBLE_RESIDUES_CM = tuple(sorted(set(
    (lead + trail - BLOCK_JOINT_CM) % PIER_MODULE_CM
    for lead, trail in PIER_BOUNDARY_JOINT_COMBINATIONS_CM
)))

# Acima deste numero de gaps, varrer 3^(N+1) combinacoes de resto sai caro
# demais para o ganho - cai para as duas hipoteses mais comuns. 5 gaps
# (4 aberturas no mesmo eixo) ja' cobre a planta real deste projeto e
# custa 3^5 = 243 particoes aritmeticas, nao 6561.
AXIS_RESIDUE_ENUM_MAX_GAPS = 5

# Quantas particoes candidatas (ja ordenadas da menor para a maior
# perturbacao) valem a pena devolver para o chamador VERIFICAR com o solver
# de blocos de verdade.
AXIS_MODULATION_CANDIDATE_LIMIT = 12

# Teto de VERIFICACOES (cada uma roda o solver de blocos inteiro naquela
# parede) que o planejador pode gastar num unico eixo antes de desistir.
# Sem isto, opcao 1 + opcao 2 (2 pontas x 5 encurtamentos) + opcao 3
# poderiam somar centenas de solves por eixo, e a analise da planta inteira
# voltaria a levar dezenas de minutos - o problema de performance que ja'
# aconteceu neste script (ver a nota em _solve_axis_width_increase).
AXIS_VERIFY_ATTEMPT_LIMIT = 40


def enumerate_axis_opening_modulations(pier_gaps_cm, max_shift_cm=AXIS_OPENING_SHIFT_MAX_CM,
                                       max_candidates=AXIS_MODULATION_CANDIDATE_LIMIT,
                                       include_alternatives=True):
    """Particoes candidatas do eixo, uma por combinacao de restos possiveis
    dos N+1 pilaretes, ORDENADAS do menor para o maior deslocamento maximo
    e sem repetir a mesma particao.

    Existe porque o resto certo de cada pilarete depende do que os
    ENCONTROS (L/T/X) reservam em cada ponta - coisa que so' o solver de
    blocos de verdade sabe. Em vez de adivinhar, este enumerador PROPOE e
    quem chama VERIFICA rodando o solver (ver process_walls_one_by_one):
    proposta barata, veredito caro e correto.

    `include_alternatives=False` devolve SO' a hipotese historica (todos os
    pilaretes multiplos de 5). E' o default de quem chama sem verificador:
    propor uma hipotese que ninguem vai conferir seria trocar um palpite
    por outro - alternativas so' entram quando ha' como testa-las de
    verdade."""
    n_gaps = len(pier_gaps_cm)
    if n_gaps < 2:
        return []

    total_rounded = int(round(sum(pier_gaps_cm)))
    if not include_alternatives:
        residue_sets = [tuple([0] * n_gaps)]
    elif n_gaps <= AXIS_RESIDUE_ENUM_MAX_GAPS:
        residue_sets = itertools.product(PIER_POSSIBLE_RESIDUES_CM, repeat=n_gaps)
    else:
        # Eixo com muitas aberturas: so' as duas hipoteses mais comuns -
        # tudo em 5m, e "pontas contra parede / meios entre aberturas".
        physical = tuple(
            (BLOCK_JOINT_CM if i == 0 else BLOCK_OPENING_JOINT_CM) +
            (BLOCK_JOINT_CM if i == n_gaps - 1 else BLOCK_OPENING_JOINT_CM) - BLOCK_JOINT_CM
            for i in range(n_gaps)
        )
        residue_sets = [tuple([0] * n_gaps), tuple(r % PIER_MODULE_CM for r in physical)]

    seen = set()
    found = []
    for residues in residue_sets:
        if ((total_rounded - sum(residues)) % PIER_MODULE_CM) != 0:
            continue
        solution = solve_axis_opening_modulation(pier_gaps_cm, max_shift_cm, residues)
        if solution is None:
            continue
        key = tuple(solution["gaps_after_cm"])
        if key in seen:
            continue
        seen.add(key)
        found.append(solution)

    found.sort(key=lambda s: (s["max_shift_cm"], sum(abs(x) for x in s["opening_shifts_cm"])))
    return found[:max_candidates]


# Quanto, no MAXIMO, uma ponta LIVRE pode ser ENCURTADA para compatibilizar
# a modulacao. Nunca existe o simetrico "esticar": aumentar parede e' a
# regra #1 do usuario (proibido), e um dos motivos e' que o aumento aparece
# no desenho como um "dente" na extremidade.
AXIS_TRIM_MAX_CM = PIER_MODULE_CM


# Teto (cm) de ajuste AUTOMATICO da "boneca" - o pilarete de PONTA que
# encosta num encontro L/T/X de verdade (nao uma ponta livre) - no padrao de
# correcao pedido pelo usuario (2026-08-21, generalizado em 2026-08-24 para
# os DOIS sentidos - ver _boneca_compensated_solutions): a boneca
# cresce OU encolhe ~1-2cm, a abertura adjacente desloca no MESMO sentido
# em que a boneca mudou, e o pilarete da PONTA OPOSTA do MESMO eixo
# compensa em sentido contrario pelo MESMO valor. Isto NAO viola a regra #1
# (nunca aumentar parede): o comprimento do eixo inteiro fica EXATAMENTE
# igual (o que muda de um lado compensa do outro dentro da MESMA parede) -
# e' a mesma aritmetica de `gaps_after_cm` que a OPCAO 1 ("shift") ja usa,
# so' que restrita as DUAS pontas em encontro e ordenada do menor delta
# (1cm) para o maior, para reproduzir o procedimento manual mais comum do
# usuario em vez de uma redistribuicao difusa por varios pilaretes do meio
# do eixo.
BONECA_ADJUST_MAX_CM = 2.0


def _axis_corner_end_sides(wall_idx, wall_end_to_node, nodes=None):
    """Como `_axis_free_end_sides`, mas devolve as pontas (0 e/ou 1) que
    encostam de verdade num encontro L/T/X (a "boneca") - candidatas ao
    padrao de correcao +1cm/-1cm de BONECA_ADJUST_MAX_CM. Uma ponta sem no'
    conhecido (grafo ausente) ou classificada como FREE_END/STRAIGHT_
    CONTINUATION nao conta como boneca - so' L_CORNER/T_INTERSECTION/
    X_INTERSECTION, exatamente como o usuario descreveu o padrao ("perto de
    encontros/bonecas"). Nunca lanca excecao; devolve [] se o grafo nao
    estiver disponivel."""
    if not wall_end_to_node or not nodes:
        return []
    sides = []
    for end_index in (0, 1):
        node_index = wall_end_to_node.get((wall_idx, end_index))
        if node_index is None:
            continue
        try:
            node = nodes[node_index]
        except (IndexError, TypeError):
            continue
        if isinstance(node, dict) and node.get("kind") in (
                "L_CORNER", "T_INTERSECTION", "X_INTERSECTION"):
            sides.append(end_index)
    return sides


def _boneca_compensated_solutions(pier_gaps_cm, corner_sides, min_pier_cm,
                                   max_delta_cm=BONECA_ADJUST_MAX_CM):
    """Gera solucoes candidatas no padrao "boneca + compensacao" pedido
    pelo usuario (2026-08-21), na ordem certa (MENOR alteracao primeiro):
    desloca RIGIDAMENTE todas as aberturas do eixo em `delta` cm, o que faz
    o pilarete de uma ponta mudar em +delta e o da PONTA OPOSTA em -delta.
    Os pilaretes do MEIO ficam intocados, entao TODAS as aberturas do eixo
    deslocam pelo mesmo valor, no MESMO sentido - exatamente o procedimento
    manual descrito pelo usuario.

    GENERALIZADO EM 2026-08-24 (pedido explicito do usuario, com o exemplo
    da boneca de 11cm): agora testa os DOIS SENTIDOS (+1, -1, +2, -2 - ver
    a ordem em `_signed_deltas` abaixo), nao so' CRESCER a boneca. O caso
    que motivou a mudanca so' fecha ENCOLHENDO: boneca 11cm -> 10cm (que
    e' o que permite o compensador de 9cm + junta de 1cm) e o trecho oposto
    144cm -> 145cm. Antes, com deltas so' positivos, esse eixo caia direto
    em "requer revisao manual" (azul na vista) mesmo tendo solucao trivial
    de 1cm.

    So' considera as pontas em `corner_sides` (encontro L/T/X real, ver
    `_axis_corner_end_sides` - o CHAMADOR ja' filtra por isso, mesma regra
    de sempre: so' a boneca de um encontro real tem "corpo" do bloco de
    amarracao da parede vizinha para crescer/encolher contra). Ordena por
    |delta| CRESCENTE, positivo (cresce) antes do negativo (encolhe) dentro
    do mesmo |delta| - "priorizar a menor alteracao possivel na posicao da
    abertura" e' regra explicita do usuario.

    Nao valida a aritmetica dos blocos aqui - e' papel do `verify` (solver
    de blocos de verdade) do chamador, mesmo padrao "propoe barato, verifica
    caro" ja usado no resto deste arquivo (ver enumerate_axis_opening_modulations).
    So' descarta um candidato quando ALGUM dos dois pilaretes de ponta
    ficaria menor que `min_pier_cm` (compensacao fisicamente impossivel) -
    ao encolher a boneca e' o proprio lado da boneca que pode estourar esse
    limite, coisa que a versao so'-crescer nunca precisava checar.

    So' se aplica a eixos com pelo menos 2 pilaretes (senao nao ha' "ponta
    oposta" para compensar - eixo sem nenhuma abertura). Cada solucao sai no
    MESMO formato que `solve_axis_opening_modulation` devolve, para reusar
    `_build_axis_opening_plan` sem alteracao nenhuma."""
    n_gaps = len(pier_gaps_cm)
    if n_gaps < 2:
        return
    max_steps = int(max_delta_cm)

    # (+1, -1, +2, -2, ...) - |delta| crescente, positivo antes do negativo
    # so' para ter uma ordem estavel entre dois candidatos de mesmo custo.
    signed_deltas = []
    for step in range(1, max_steps + 1):
        signed_deltas.append(step)
        signed_deltas.append(-step)

    for delta in signed_deltas:
        for boneca_side in corner_sides:
            boneca_idx = 0 if boneca_side == 0 else n_gaps - 1
            opposite_idx = n_gaps - 1 if boneca_side == 0 else 0
            if boneca_idx == opposite_idx:
                continue
            adjusted = list(pier_gaps_cm)
            adjusted[boneca_idx] += delta
            adjusted[opposite_idx] -= delta
            if adjusted[boneca_idx] < min_pier_cm or adjusted[opposite_idx] < min_pier_cm:
                continue
            # Sentido em que as aberturas andam ao longo do eixo: crescer o
            # pilarete da ponta 0 empurra tudo para +t; crescer o da ponta 1
            # puxa tudo para -t. Com `delta` negativo o sinal se inverte
            # sozinho (nao ha' caso especial a tratar).
            direction = 1.0 if boneca_side == 0 else -1.0
            shift_cm = direction * delta
            n_openings = n_gaps - 1
            yield {
                "gaps_after_cm": adjusted,
                "opening_shifts_cm": [shift_cm] * n_openings,
                "residues_cm": None,
                "max_shift_cm": float(abs(delta)),
                "within_auto_apply_limit": True,
                "changed": True,
                "boneca_side": boneca_side,
                "boneca_delta_cm": delta,
            }


def _build_axis_opening_plan(wall_idx, axis, matched, solution, width_deltas_cm,
                             tier, trim_info):
    """Monta o dict de plano a partir de uma particao ja escolhida. Devolve
    o plano, ou um dict {"feasible": False, ...} explicando por que aquela
    particao nao serve.

    GUARDA DURA DA REGRA #1: se as fronteiras calculadas sairem do
    intervalo [0, comprimento do eixo] - ou seja, se o "ajuste" fosse na
    verdade um PROLONGAMENTO da parede - o plano e' recusado aqui, nao
    importa de qual opcao ele veio."""
    ft_to_cm = 100.0 / FEET_PER_METER
    axis_len_ft = axis["axis_len_ft"]

    start_t = 0.0
    end_t = axis_len_ft
    if trim_info is not None:
        delta_ft = trim_info["delta_cm"] / ft_to_cm
        if trim_info["side"] == 0:
            start_t = -delta_ft      # delta_cm < 0  =>  start_t > 0 (encurta)
        else:
            end_t = axis_len_ft + delta_ft

    if start_t < -1e-9 or end_t > axis_len_ft + 1e-9:
        return {"feasible": False, "wall_idx": wall_idx,
                "reason": "o ajuste AUMENTARIA a parede (proibido - nunca prolongar a "
                          "extremidade nem criar dente)"}

    gaps_after_ft = [g / ft_to_cm for g in solution["gaps_after_cm"]]
    new_openings = []
    cursor_t = start_t + gaps_after_ft[0]
    for i, row in enumerate(axis["openings"]):
        width_delta_cm = width_deltas_cm[i]
        width_ft = (row["t_hi"] - row["t_lo"]) + (width_delta_cm / ft_to_cm)
        t_lo_new = cursor_t
        t_hi_new = cursor_t + width_ft
        new_openings.append({
            "opening_index": row["opening_index"],
            "t_lo_new": t_lo_new, "t_hi_new": t_hi_new,
            "old_t_lo": row["t_lo"], "old_t_hi": row["t_hi"],
            "shift_ft": t_lo_new - row["t_lo"],
            "width_delta_cm": width_delta_cm,
            "new_width_ft": width_ft,
            "infill_ids": row["infill_ids"],
            "opening": matched[row["opening_index"]],
            "sill_z_abs": row["sill_z_abs"], "head_z_abs": row["head_z_abs"],
        })
        cursor_t = t_hi_new + gaps_after_ft[i + 1]

    boundaries = [start_t]
    for row in new_openings:
        boundaries.append(row["t_lo_new"])
        boundaries.append(row["t_hi_new"])
    boundaries.append(end_t)

    new_piers = []
    for k, pier in enumerate(axis["piers"]):
        t_a_new = boundaries[2 * k]
        t_b_new = boundaries[2 * k + 1]
        if (t_b_new - t_a_new) < MIN_SEGMENT_LENGTH_FT:
            return {"feasible": False, "wall_idx": wall_idx,
                    "reason": "pilarete #{} ficaria com comprimento praticamente "
                              "zero apos o ajuste - requer revisao manual".format(k)}
        new_piers.append({"index": k, "element_id": pier["element_id"],
                           "t_a_new": t_a_new, "t_b_new": t_b_new})

    return {"feasible": True, "wall_idx": wall_idx, "reason": None,
            "already_ok": False, "tier": tier,
            "max_shift_cm": solution["max_shift_cm"],
            "trim_info": trim_info,
            "length_delta_cm": (end_t - start_t - axis_len_ft) * ft_to_cm,
            "axis_start_t_ft": start_t, "axis_end_t_ft": end_t,
            "new_openings": new_openings, "new_piers": new_piers}


def plan_axis_opening_fix(target_doc, wall_idx, walls_to_create, openings_per_wall,
                           created_walls_by_axis, all_openings, wall_end_to_node=None,
                           wall_graph_nodes=None, verify=None, wall_segment_geometry=None):
    """Monta o plano de correcao pos-criacao de UM eixo - parede(s) e
    abertura(s) tratadas JUNTAS. NUNCA aplica nada (so' calcula) e NUNCA
    lanca excecao: qualquer impossibilidade vira plan["feasible"]=False com
    o motivo exato.

    REGRA #1 (absoluta): NENHUMA opcao aqui aumenta a parede. A opcao 2, que
    antes podia ESTICAR uma ponta livre ("extend"), so' ENCURTA agora
    ("trim") - esticar produzia exatamente os prolongamentos/"dentes" nas
    extremidades que o usuario proibiu. `_build_axis_opening_plan` ainda
    recusa, por garantia, qualquer plano cujas fronteiras saiam do
    intervalo do eixo original.

    Tenta, NESTA ORDEM (sempre a MENOR alteracao possivel primeiro, e nunca
    passa para a proxima se a anterior ja resolveu):
      0. "boneca" - so' quando alguma ponta do eixo encosta de verdade num
         encontro L/T/X (ver _axis_corner_end_sides): CRESCE OU ENCOLHE
         (os dois sentidos, generalizado 2026-08-24) o pilarete daquela
         ponta em ~1-2cm (BONECA_ADJUST_MAX_CM), desloca a(s) abertura(s)
         no MESMO sentido, e compensa o pilarete da PONTA OPOSTA do MESMO
         eixo em sentido contrario pelo mesmo valor - comprimento do eixo
         inteiro permanece EXATAMENTE igual. Reproduz o procedimento manual
         mais comum do usuario (2026-08-21) para o caso "parede sem espaco
         suficiente perto de uma boneca" - so' roda quando ha' `verify`
         (precisa do solver de blocos de verdade para confirmar que a nova
         modulacao realmente fecha antes de aceitar).
      1. "shift" - deslocar so' as aberturas (posicao), redistribuindo
         livremente entre TODOS os pilaretes do eixo; largura e
         comprimento do eixo FIXOS.
      2. "trim"  - se alguma extremidade for FREE_END (nao encosta em
         nenhuma outra parede), ENCURTAR so' aquela ponta, no minimo
         necessario e no maximo AXIS_TRIM_MAX_CM.
      3. "widen" - aumentar (nunca reduzir) a largura de uma ou mais
         aberturas do eixo em ate OPENING_WIDTH_INCREASE_MAX_CM cada -
         ultimo recurso.

    `verify(plan)`: quando dado, e' o SOLVER DE BLOCOS DE VERDADE rodando
    sobre a parede ja ajustada em memoria (ver process_walls_one_by_one).
    So' um plano que ele aprova e' devolvido - e' isso que faz o
    lancamento dos blocos participar da decisao de ajuste (regra #3) em vez
    de vir depois dela. Sem `verify`, o planejador se restringe a hipotese
    aritmetica historica (todos os pilaretes multiplos de 5), porque propor
    alternativas que ninguem vai conferir seria so' trocar um palpite por
    outro.

    `wall_segment_geometry`: repassado direto para _classify_wall_axis_segments
    (ver seu docstring) - quando fornecido, esta funcao inteira roda sem
    tocar `target_doc`.
    """
    axis = _classify_wall_axis_segments(target_doc, wall_idx, walls_to_create,
                                         openings_per_wall, created_walls_by_axis,
                                         wall_segment_geometry=wall_segment_geometry)
    if axis is None:
        return {"feasible": False, "wall_idx": wall_idx,
                "reason": "topologia do eixo fora do escopo do ajuste automatico "
                          "(abertura encostada na ponta/juncao, ou os segmentos "
                          "reais nao batem com o esperado) - requer revisao manual"}

    ft_to_cm = 100.0 / FEET_PER_METER
    piers = axis["piers"]
    pier_gaps_cm = [(p["t_b"] - p["t_a"]) * ft_to_cm for p in piers]
    opening_widths_cm = [(row["t_hi"] - row["t_lo"]) * ft_to_cm for row in axis["openings"]]
    min_pier_cm = MIN_SEGMENT_LENGTH_FT * ft_to_cm
    zero_width_deltas = [0] * len(axis["openings"])
    with_alternatives = verify is not None

    matched = _match_openings_for_axis(wall_idx, walls_to_create, openings_per_wall, all_openings)
    if len(matched) != len(axis["openings"]):
        missing = [row["opening_index"] for row in axis["openings"] if row["opening_index"] not in matched]
        return {"feasible": False, "wall_idx": wall_idx,
                "reason": "instancia real nao encontrada para a(s) abertura(s) de "
                          "indice {} deste eixo - requer revisao manual".format(missing)}

    reasons = []
    budget = {"left": AXIS_VERIFY_ATTEMPT_LIMIT}

    def _accept(solution, width_deltas_cm, tier, trim_info):
        plan = _build_axis_opening_plan(wall_idx, axis, matched, solution,
                                        width_deltas_cm, tier, trim_info)
        if not plan.get("feasible"):
            return None
        if verify is None:
            return plan
        if budget["left"] <= 0:
            return None
        budget["left"] -= 1
        return plan if verify(plan) else None

    # --- OPCAO 0: crescer a "boneca" (~1-2cm) e compensar na ponta oposta
    # do MESMO eixo (regra pedida pelo usuario, 2026-08-21). So' faz sentido
    # com `verify` disponivel (precisa do solver de blocos de verdade para
    # confirmar a nova modulacao antes de aceitar - sem verify nao ha' como
    # saber se a nova geometria realmente fecha, e aplicar as cegas
    # contrariaria a regra #6 do usuario, "so' considerar corrigida quando a
    # modulacao estiver efetivamente adequada").
    if verify is not None:
        corner_sides = _axis_corner_end_sides(wall_idx, wall_end_to_node, wall_graph_nodes)
        if corner_sides:
            for solution in _boneca_compensated_solutions(pier_gaps_cm, corner_sides, min_pier_cm):
                plan = _accept(solution, zero_width_deltas, "boneca", None)
                if plan is not None:
                    return plan
            if budget["left"] <= 0:
                return {"feasible": False, "wall_idx": wall_idx,
                        "reason": "; ".join(reasons + [
                            "limite de {} tentativas verificadas atingido neste eixo".format(
                                AXIS_VERIFY_ATTEMPT_LIMIT)]) + " - requer revisao manual"}
            reasons.append(
                "ajuste de boneca (~1-{:.0f}cm, testado crescendo e encolhendo) na ponta em "
                "encontro L/T/X com compensacao na ponta oposta nao fecha a modulacao real"
                .format(BONECA_ADJUST_MAX_CM))

    # --- OPCAO 1: deslocar so' as aberturas ---
    candidates = enumerate_axis_opening_modulations(
        pier_gaps_cm, include_alternatives=with_alternatives
    )
    if not candidates:
        reasons.append(
            "deslocamento simples impossivel (soma dos pilaretes {:.1f}cm incompativel "
            "com os blocos deste catalogo)".format(sum(pier_gaps_cm))
        )
    else:
        # "ja' esta' bom" so' pode ser dito de saida quando NAO ha' quem
        # verifique: com `verify` em maos, quem chamou ja' sabe que os
        # blocos NAO fecharam nesta parede, entao a particao atual precisa
        # passar pelo mesmo veredito que as outras (e, falhando, a busca
        # continua) em vez de encerrar a analise com um falso "nada a fazer".
        if not candidates[0]["changed"] and verify is None:
            return {"feasible": True, "wall_idx": wall_idx, "reason": None,
                    "already_ok": True, "tier": "shift", "max_shift_cm": 0.0,
                    "trim_info": None, "length_delta_cm": 0.0,
                    "axis_start_t_ft": 0.0, "axis_end_t_ft": axis["axis_len_ft"],
                    "new_openings": [], "new_piers": []}
        within_limit = [s for s in candidates if s["within_auto_apply_limit"]]
        if not within_limit:
            reasons.append(
                "deslocamento simples exigiria {:.1f}cm (acima do limite de {:.0f}cm)"
                .format(candidates[0]["max_shift_cm"], AXIS_OPENING_SHIFT_MAX_CM)
            )
        for solution in within_limit:
            plan = _accept(solution, zero_width_deltas, "shift", None)
            if plan is not None:
                return plan
        if within_limit:
            reasons.append("nenhum deslocamento simples dentro do limite fecha a modulacao real")

    if budget["left"] <= 0:
        return {"feasible": False, "wall_idx": wall_idx,
                "reason": "; ".join(reasons + [
                    "limite de {} tentativas verificadas atingido neste eixo".format(
                        AXIS_VERIFY_ATTEMPT_LIMIT)]) + " - requer revisao manual"}

    # --- OPCAO 2: ENCURTAR (nunca esticar) uma ponta LIVRE do eixo ---
    free_sides = _axis_free_end_sides(wall_idx, wall_end_to_node, wall_graph_nodes)
    if not free_sides:
        reasons.append("nenhuma ponta livre neste eixo para encurtar o comprimento da parede")
    else:
        # Os encurtamentos candidatos sao os que levam a SOMA dos pilaretes
        # a um valor INTEIRO - deltas FRACIONARIOS incluidos. Com o antigo
        # `range(1, N)` (so' inteiros), um eixo de comprimento fracionario
        # continuava fracionario depois de qualquer trim, e
        # solve_axis_opening_modulation devolve None de saida nesse caso
        # ("total nao inteiro", ver o guard MODULATION_WHOLE_CM_TOLERANCE_CM
        # la'). Ou seja: em eixo fracionario a OPCAO 1 e a OPCAO 2 nao
        # produziam candidato NENHUM - e eixo fracionario e' o caso comum
        # numa planta vinda de CAD. Continua valendo a regra #1: so'
        # ENCURTA (delta < 0), nunca estica.
        gaps_total_cm = sum(pier_gaps_cm)
        trim_deltas_cm = []
        for step_cm in range(1, int(AXIS_TRIM_MAX_CM) + 1):
            target_total_cm = float(int(math.floor(gaps_total_cm)) - step_cm + 1)
            delta_cm = target_total_cm - gaps_total_cm
            if delta_cm >= -MODULATION_WHOLE_CM_TOLERANCE_CM:
                continue  # nao encurta de verdade
            if abs(delta_cm) > AXIS_TRIM_MAX_CM + 1e-9:
                continue
            trim_deltas_cm.append(delta_cm)

        trimmed_ok = False
        for side in free_sides:
            gap_index = 0 if side == 0 else -1
            for delta_cm in trim_deltas_cm:
                adjusted = list(pier_gaps_cm)
                adjusted[gap_index] += delta_cm
                if adjusted[gap_index] < min_pier_cm:
                    continue
                for solution in enumerate_axis_opening_modulations(
                        adjusted, include_alternatives=with_alternatives):
                    if not solution["within_auto_apply_limit"]:
                        continue
                    if budget["left"] <= 0:
                        break
                    plan = _accept(solution, zero_width_deltas, "trim",
                                   {"side": side, "delta_cm": delta_cm})
                    if plan is not None:
                        return plan
                    trimmed_ok = True
        if not trimmed_ok:
            reasons.append("encurtar uma ponta livre nao fecha a modulacao deste eixo")
        else:
            reasons.append("nenhum encurtamento de ponta livre fecha a modulacao real")

    # --- OPCAO 3: aumentar a largura de uma ou mais aberturas ---
    # DESLIGADA (2026-08-24, incidente real reportado pelo usuario): aplicar
    # esta opcao (que escreve em Largura_abertura via _set_opening_width_param
    # - ver apply_axis_opening_fix) fez o Revit travar numa caixa de dialogo
    # "Nao e' possivel criar o tipo 'Abertura de janela para paredes de
    # blocos'", cuja unica opcao de resolucao oferecida era "Excluir tipo" -
    # que apaga TODAS as instancias daquele tipo no projeto de uma vez (foi
    # assim que 8 aberturas sumiram do modelo, confirmado ao vivo via MCP:
    # 77 esperadas, so' 69 restantes). A causa exata (formula parametrica da
    # familia que nao aceita o novo valor de largura?) nao foi isolada, mas
    # o risco - perda de dados irreversivel numa familia usada no projeto
    # inteiro - e' grande demais para o beneficio (fechar uns poucos eixos a
    # mais que so' 'shift'/'trim' nao fecham). Ate' isolar e testar a causa
    # com seguranca, esta opcao NUNCA propoe um plano: os eixos que so'
    # fechariam aumentando a abertura caem direto em "requer revisao
    # manual", como se _solve_axis_width_increase sempre falhasse.
    reasons.append(
        "aumentar a largura da abertura esta' desligado (causou uma exclusao real de "
        "aberturas no projeto - ver comentario em plan_axis_opening_fix, OPCAO 3)"
    )

    return {"feasible": False, "wall_idx": wall_idx,
            "reason": "; ".join(reasons) + " - requer revisao manual"}
def apply_axis_opening_fix(target_doc, plan, walls_to_create, g=None):
    """Aplica DE VERDADE, no modelo, um plano de plan_axis_opening_fix com
    feasible=True (precisa rodar dentro de uma Transacao/SubTransacao ja
    aberta pelo chamador - nunca abre a propria). Reconstroi CADA pilar por
    `t` inteiro (nao so' "move uma ponta" como a antiga apply_opening_shift -
    um pilar do MEIO, entre duas aberturas que deslocam, tem as DUAS pontas
    moveis), translada RIGIDAMENTE cada segmento de peitoril/verga
    ("abertura") pertencente a' abertura deslocada (corrige o bug da antiga
    apply_opening_shift, que so' movia os pilares e deixava peitoril/verga
    para tras) e move so' a FamilyInstance (nunca largura/altura/peitoril).

    DELIBERADAMENTE NAO toca em `openings_per_wall`/`walls_to_create` - e'
    responsabilidade do CHAMADOR escrever de volta so' DEPOIS de confirmar
    que a Transacao/SubTransacao foi commitada (ver fix_all_wall_modulation_errors),
    senao um RollBack no meio deixaria o Python e o modelo dessincronizados.

    `g`: mesmo dicionario opcional de fix_all_wall_modulation_errors - ver o
    comentario la' (sombreia XYZ/LocationCurve/Line/ElementTransformUtils/
    _set_opening_width_param/_opening_center_from_geometry/FEET_PER_METER
    como variaveis LOCAIS, garantidamente resolviveis, quando chamada a
    partir do ExternalEvent).

    Devolve (applied_opening_count, failures) - NUNCA lanca excecao para
    fora; falhas parciais sao reportadas em `failures` e nao interrompem as
    demais edicoes."""
    if g is not None:
        XYZ = g["XYZ"]
        LocationCurve = g["LocationCurve"]
        Line = g["Line"]
        ElementTransformUtils = g["ElementTransformUtils"]
        _set_opening_width_param = g["_set_opening_width_param"]
        _opening_center_from_geometry = g["_opening_center_from_geometry"]
        FEET_PER_METER = g["FEET_PER_METER"]

    failures = []
    if not plan.get("feasible") or plan.get("already_ok"):
        return 0, failures

    wall_idx = plan["wall_idx"]
    centerline, _thickness_ft, _locks = walls_to_create[wall_idx]

    # ULTIMA BARREIRA da regra #1 (aumentar parede e' proibido), aqui no
    # ponto exato em que o modelo seria alterado: mesmo que um plano
    # invalido escapasse do planejador e da validacao, ele nao chega a
    # tocar no Revit. Nada e' aplicado pela metade - a checagem vem ANTES
    # da primeira edicao.
    axis_len_ft = centerline.Length
    start_t_ft = plan.get("axis_start_t_ft") or 0.0
    end_t_ft = plan.get("axis_end_t_ft")
    if end_t_ft is None:
        end_t_ft = axis_len_ft
    if start_t_ft < -1e-9 or end_t_ft > axis_len_ft + 1e-9:
        failures.append(
            "plano recusado: aumentaria a parede (prolongaria a extremidade / criaria "
            "dente) - nenhuma alteracao foi aplicada"
        )
        return 0, failures
    p0 = centerline.GetEndPoint(0)
    direction = centerline.Direction
    dir_xy = XYZ(direction.X, direction.Y, 0.0)

    for pier in plan["new_piers"]:
        try:
            wall = target_doc.GetElement(pier["element_id"])
            if wall is None or not isinstance(wall.Location, LocationCurve):
                failures.append("pilarete {} nao encontrado no documento".format(pier["element_id"]))
                continue
            old_curve = wall.Location.Curve
            z0 = old_curve.GetEndPoint(0).Z
            z1 = old_curve.GetEndPoint(1).Z
            new_p0 = XYZ(p0.X + dir_xy.X * pier["t_a_new"], p0.Y + dir_xy.Y * pier["t_a_new"], z0)
            new_p1 = XYZ(p0.X + dir_xy.X * pier["t_b_new"], p0.Y + dir_xy.Y * pier["t_b_new"], z1)
            wall.Location.Curve = Line.CreateBound(new_p0, new_p1)
        except Exception as ex:
            failures.append("pilarete {}: {}".format(pier["element_id"], ex))

    applied_opening_count = 0
    for row in plan["new_openings"]:
        try:
            width_delta_cm = row.get("width_delta_cm") or 0
            old_t_lo = row.get("old_t_lo", row["t_lo_new"] - row["shift_ft"])
            old_t_hi = row.get("old_t_hi")
            t_lo_delta_ft = row["t_lo_new"] - old_t_lo
            t_hi_delta_ft = (row["t_hi_new"] - old_t_hi) if old_t_hi is not None else t_lo_delta_ft

            if abs(t_lo_delta_ft) < 1e-9 and abs(t_hi_delta_ft) < 1e-9 and not width_delta_cm:
                applied_opening_count += 1
                continue

            # Cada extremidade do segmento de infill (peitoril/verga) se
            # move pelo SEU PROPRIO delta ao longo do eixo - iguais no caso
            # "shift"/"trim" (largura fixa, ambas bordas andam junto), mas
            # DIFERENTES no caso "widen" (a abertura cresce, entao as duas
            # bordas se afastam uma da outra). Identifica qual ponta fisica
            # de cada infill corresponde a t_lo/t_hi projetando no eixo -
            # mesmo calculo de _classify_wall_axis_segments.
            for infill_id in row["infill_ids"]:
                infill_wall = target_doc.GetElement(infill_id)
                if infill_wall is None or not isinstance(infill_wall.Location, LocationCurve):
                    failures.append("segmento de peitoril/verga {} nao encontrado".format(infill_id))
                    continue
                curve = infill_wall.Location.Curve
                p_a = curve.GetEndPoint(0)
                p_b = curve.GetEndPoint(1)
                t_a = XYZ(p_a.X - p0.X, p_a.Y - p0.Y, 0.0).DotProduct(dir_xy)
                t_b = XYZ(p_b.X - p0.X, p_b.Y - p0.Y, 0.0).DotProduct(dir_xy)
                delta_a_ft = t_lo_delta_ft if t_a <= t_b else t_hi_delta_ft
                delta_b_ft = t_hi_delta_ft if t_a <= t_b else t_lo_delta_ft
                new_p_a = XYZ(p_a.X + dir_xy.X * delta_a_ft, p_a.Y + dir_xy.Y * delta_a_ft, p_a.Z)
                new_p_b = XYZ(p_b.X + dir_xy.X * delta_b_ft, p_b.Y + dir_xy.Y * delta_b_ft, p_b.Z)
                infill_wall.Location.Curve = Line.CreateBound(new_p_a, new_p_b)

            opening_inst = target_doc.GetElement(row["opening"]["element_id_obj"])
            if opening_inst is None:
                failures.append("instancia da abertura #{} nao encontrada".format(row["opening_index"]))
                continue

            if width_delta_cm:
                # Ultimo recurso (OPCAO 3 de plan_axis_opening_fix): aumenta
                # o parametro Largura_abertura E move a instancia pelo
                # deslocamento do CENTRO (nao da borda esquerda) - mais
                # robusto a qualquer deslocamento entre o ponto de insercao
                # e o centro geometrico do vao (ver _opening_center_from_geometry).
                # Depois MEDE a posicao real da geometria recem-regenerada e
                # aplica uma correcao residual, em vez de confiar que o
                # deslocamento calculado bateu exatamente - mesma filosofia
                # de "medir, nao supor" ja usada no resto do arquivo.
                new_width_ft = row["new_width_ft"]
                center_t_new = (row["t_lo_new"] + row["t_hi_new"]) / 2.0
                center_t_old = (old_t_lo + old_t_hi) / 2.0
                center_shift_ft = center_t_new - center_t_old
                center_shift_vec = XYZ(dir_xy.X * center_shift_ft, dir_xy.Y * center_shift_ft, 0.0)

                if not _set_opening_width_param(opening_inst, new_width_ft):
                    failures.append(
                        "abertura #{}: nao foi possivel escrever a nova largura ({:.1f}cm)"
                        .format(row["opening_index"], new_width_ft / FEET_PER_METER * 100.0)
                    )
                    continue
                ElementTransformUtils.MoveElement(target_doc, opening_inst.Id, center_shift_vec)
                target_doc.Regenerate()
                # REDE DE SEGURANCA (2026-08-24, bug real reportado pelo
                # usuario: aberturas sumindo do modelo em vez de so' mudar de
                # posicao) - ver a MESMA checagem, com a explicacao completa,
                # logo depois do `else` abaixo.
                if not opening_inst.IsValidObject:
                    failures.append(
                        "abertura #{}: a instancia deixou de existir no modelo depois do ajuste de "
                        "largura ({:.1f}cm) - alteracao desfeita, nada foi perdido."
                        .format(row["opening_index"], new_width_ft / FEET_PER_METER * 100.0)
                    )
                    continue

                intended_center = XYZ(
                    p0.X + dir_xy.X * center_t_new, p0.Y + dir_xy.Y * center_t_new, 0.0
                )
                measured_center, _measured_width_ft = _opening_center_from_geometry(opening_inst, new_width_ft)
                if measured_center is not None:
                    residual = XYZ(
                        intended_center.X - measured_center.X,
                        intended_center.Y - measured_center.Y, 0.0
                    )
                    if residual.GetLength() > 1e-6:
                        ElementTransformUtils.MoveElement(target_doc, opening_inst.Id, residual)
            else:
                shift_vec = XYZ(dir_xy.X * t_lo_delta_ft, dir_xy.Y * t_lo_delta_ft, 0.0)
                ElementTransformUtils.MoveElement(target_doc, opening_inst.Id, shift_vec)
                # REDE DE SEGURANCA (2026-08-24, bug real reportado pelo
                # usuario, com screenshots): depois de rodar 'Ajustar Erros',
                # ate' 8 aberturas SUMIRAM do modelo (confirmado ao vivo via
                # MCP: 77 esperadas, so' 69 restantes) em vez de so' mudar de
                # posicao - sem NENHUMA excecao lancada por MoveElement, e
                # sem nenhum aviso (doc.GetWarnings() tambem veio vazio).
                # ElementTransformUtils.MoveElement pode, silenciosamente,
                # fazer o Revit invalidar/apagar a instancia durante o
                # Regenerate() seguinte quando a geometria parametrica da
                # familia nao aguenta a nova posicao (a causa exata ainda
                # nao foi isolada - a family "Abertura de janela para
                # paredes de blocos" nao e' hospedada em parede, entao nao e'
                # o caso classico de "host encolheu demais"). Sem este
                # Regenerate()+checagem, o SubTransaction via' o commit como
                # sucesso (nenhuma excecao) e a exclusao ficava permanente e
                # SILENCIOSA - exatamente o que o usuario reportou. Agora, se
                # a instancia sumir, isto vira uma FALHA REPORTADA (o
                # SubTransaction do chamador da' RollBack, ver
                # fix_all_wall_modulation_errors) em vez de um commit mudo.
                target_doc.Regenerate()
                if not opening_inst.IsValidObject:
                    failures.append(
                        "abertura #{}: a instancia deixou de existir no modelo depois do "
                        "deslocamento ({:.1f}cm) - alteracao desfeita, nada foi perdido. Requer "
                        "revisao manual (mover a abertura a mao antes de tentar de novo)."
                        .format(row["opening_index"], t_lo_delta_ft / FEET_PER_METER * 100.0)
                    )
                    continue

            applied_opening_count += 1
        except Exception as ex:
            failures.append("abertura #{}: {}".format(row["opening_index"], ex))

    return applied_opening_count, failures



# ETAPA 3C (deslocamento de grupo de paredes conectadas) - EXTRAIDA para
# core/engine/wall_stepper.py junto com a ETAPA 4 acima (mesmo motivo/
# padrao). Ver o cabecalho daquele arquivo.
from core.engine.wall_stepper import *  # noqa: F401,F403



def apply_wall_group_shift(target_doc, plan, walls_to_create, openings_per_wall,
                           created_walls_by_axis, all_openings, g=None):
    """Aplica DE VERDADE, no modelo, um plano de find_wall_group_shift_fixes
    (feasible=True, kind='group_shift') - precisa rodar dentro de uma
    Transacao/SubTransacao ja aberta pelo chamador. Mesma disciplina de
    apply_axis_opening_fix: Regenerate() + checagem IsValidObject apos cada
    MoveElement de abertura (mesmo incidente de exclusao silenciosa ja
    documentado ali), nunca escreve em walls_to_create/openings_per_wall
    (responsabilidade do CHAMADOR, so' apos o Commit - ver
    fix_all_wall_modulation_errors).

    Membro "shifted": TODOS os segmentos reais do eixo (pilares + infill,
    `created_walls_by_axis[wall_idx]`) e TODAS as aberturas hospedadas nele
    sao TRANSLADADOS rigidamente pelo MESMO vetor (e' uma translacao pura -
    nada muda de tamanho) - calculado comparando a Line ORIGINAL (em
    `walls_to_create`, ainda nao mutado) com `member["new_centerline"]`.

    Membro "neighbor": so' o PILAR REAL mais proximo da ponta afetada
    (achado via `_classify_wall_axis_segments`, mesmo padrao de
    apply_axis_opening_fix) tem o `Location.Curve` editado - a ponta OPOSTA
    (e o resto do eixo, aberturas incluidas) nunca e' tocado.

    Devolve (applied_member_count, failures)."""
    # Sempre atribuidas incondicionalmente (nunca so' dentro de `if g is not
    # None:`) - diferente do padrao de apply_axis_opening_fix, DE PROPOSITO:
    # uma atribuicao condicional a um nome ja' usado como bare-name mais
    # abaixo faz o Python tratar esse nome como LOCAL na funcao INTEIRA
    # (analise estatica, independente do galho realmente executado) - com
    # g=None a atribuicao nunca rodaria e qualquer uso de XYZ/Line mais
    # abaixo lancaria UnboundLocalError. Aqui, ao contrario de
    # apply_axis_opening_fix, os testes automatizados chamam esta funcao SEM
    # `g` e PRECISAM chegar nas linhas que usam XYZ/Line de verdade
    # (nao so' no retorno antecipado) - por isso o fallback explicito via
    # globals() em vez do `if` condicional.
    XYZ = g["XYZ"] if g is not None else globals()["XYZ"]
    Line = g["Line"] if g is not None else globals()["Line"]
    LocationCurve = g["LocationCurve"] if g is not None else globals()["LocationCurve"]
    ElementTransformUtils = g["ElementTransformUtils"] if g is not None else globals()["ElementTransformUtils"]

    failures = []
    applied = 0
    for member in plan["members"]:
        wall_idx = member["wall_idx"]
        new_line = member["new_centerline"]
        try:
            if member["role"] == "shifted":
                old_centerline = walls_to_create[wall_idx][0]
                old_p0 = old_centerline.GetEndPoint(0)
                new_p0 = new_line.GetEndPoint(0)
                translate_vec = XYZ(new_p0.X - old_p0.X, new_p0.Y - old_p0.Y, 0.0)
                if translate_vec.GetLength() < 1e-9:
                    applied += 1
                    continue

                for element_id, _origin in created_walls_by_axis.get(wall_idx, []):
                    wall = target_doc.GetElement(element_id)
                    if wall is None or not isinstance(wall.Location, LocationCurve):
                        failures.append("segmento {} (parede {}) nao encontrado".format(element_id, wall_idx))
                        continue
                    curve = wall.Location.Curve
                    p_a = curve.GetEndPoint(0)
                    p_b = curve.GetEndPoint(1)
                    new_p_a = XYZ(p_a.X + translate_vec.X, p_a.Y + translate_vec.Y, p_a.Z)
                    new_p_b = XYZ(p_b.X + translate_vec.X, p_b.Y + translate_vec.Y, p_b.Z)
                    wall.Location.Curve = Line.CreateBound(new_p_a, new_p_b)

                matched = _match_openings_for_axis(wall_idx, walls_to_create, openings_per_wall, all_openings)
                for opening_index, opening in matched.items():
                    opening_inst = target_doc.GetElement(opening["element_id_obj"])
                    if opening_inst is None:
                        failures.append(
                            "abertura #{} (parede {}) nao encontrada".format(opening_index, wall_idx)
                        )
                        continue
                    ElementTransformUtils.MoveElement(target_doc, opening_inst.Id, translate_vec)
                    target_doc.Regenerate()
                    # Mesma REDE DE SEGURANCA de apply_axis_opening_fix (bug
                    # real reportado pelo usuario: aberturas sumindo do
                    # modelo em vez de so' mudar de posicao apos um MoveElement).
                    if not opening_inst.IsValidObject:
                        failures.append(
                            "abertura #{} (parede {}): a instancia deixou de existir no modelo "
                            "depois do deslocamento de grupo - requer revisao manual."
                            .format(opening_index, wall_idx)
                        )
                        continue
                applied += 1
            else:
                # A ponta afetada e' sempre a que se recalculou contra
                # shift_end/neighbor_end_index em find_wall_group_shift_fixes
                # - aqui so' precisamos saber se e' o PRIMEIRO ou o ULTIMO
                # pilar real do eixo, o que a NOVA Line ja revela: comparar
                # qual ponta dela mudou em relacao a' ORIGINAL
                # walls_to_create[wall_idx][0] diz de que lado ficou o pilar
                # a editar.
                old_centerline = walls_to_create[wall_idx][0]
                old_p0 = old_centerline.GetEndPoint(0)
                old_p1 = old_centerline.GetEndPoint(1)
                new_p0 = new_line.GetEndPoint(0)
                new_p1 = new_line.GetEndPoint(1)
                end_changed = 0 if old_p0.DistanceTo(new_p0) > old_p1.DistanceTo(new_p1) else 1
                new_axis_end_point = new_p0 if end_changed == 0 else new_p1
                old_axis_end_point = old_p0 if end_changed == 0 else old_p1

                # Achar o ELEMENTO real a editar: a maioria das paredes-alvo
                # deste mecanismo NAO tem nenhuma abertura (ver o cabecalho
                # da ETAPA 3C - e' exatamente o caso "sem abertura por
                # perto" que plan_axis_opening_fix nunca conseguia tratar) -
                # nesse caso ha' UM SO' segmento real no eixo inteiro, e
                # _classify_wall_axis_segments (que exige pelo menos uma
                # abertura, ver seu proprio docstring) devolveria None sem
                # motivo. So' usa _classify_wall_axis_segments (mais caro,
                # projeta em `t` e ordena) quando ha' de fato mais de um
                # segmento real (aberturas presentes).
                segments = created_walls_by_axis.get(wall_idx) or []
                if len(segments) == 1:
                    pier_element_id = segments[0][0]
                else:
                    axis = _classify_wall_axis_segments(
                        target_doc, wall_idx, walls_to_create, openings_per_wall, created_walls_by_axis
                    )
                    if axis is None or not axis["piers"]:
                        failures.append(
                            "parede {}: nao foi possivel localizar o pilar real da ponta afetada"
                            .format(wall_idx)
                        )
                        continue
                    pier = axis["piers"][0] if end_changed == 0 else axis["piers"][-1]
                    pier_element_id = pier["element_id"]

                wall = target_doc.GetElement(pier_element_id)
                if wall is None or not isinstance(wall.Location, LocationCurve):
                    failures.append("pilar {} (parede {}) nao encontrado".format(pier_element_id, wall_idx))
                    continue
                curve = wall.Location.Curve
                real_p0 = curve.GetEndPoint(0)
                real_p1 = curve.GetEndPoint(1)
                # Qual extremidade REAL deste pilar (0 ou 1) e' a EXTERNA
                # (perto da ponta do eixo que mudou) - e' essa que recebe o
                # novo ponto; a INTERNA (contra o resto do eixo, dentro do
                # pilar - pode nao ser o proprio p1/p0 do EIXO inteiro, se
                # este pilar for so' o primeiro/ultimo de varios segmentos
                # reais na presenca de aberturas) fica INTOCADA, preservando
                # posicao E Z dela exatamente como lida do modelo real -
                # nunca reconstruida a partir do eixo inteiro.
                replace_index = (
                    0 if real_p0.DistanceTo(old_axis_end_point) <= real_p1.DistanceTo(old_axis_end_point)
                    else 1
                )
                z = (real_p0 if replace_index == 0 else real_p1).Z
                new_point_3d = XYZ(new_axis_end_point.X, new_axis_end_point.Y, z)
                if replace_index == 0:
                    wall.Location.Curve = Line.CreateBound(new_point_3d, real_p1)
                else:
                    wall.Location.Curve = Line.CreateBound(real_p0, new_point_3d)
                applied += 1
        except Exception as ex:
            failures.append("parede {} ({}): {}".format(wall_idx, member["role"], ex))

    return applied, failures


def analyze_created_walls_for_errors(target_doc, walls_to_create, openings_per_wall,
                                      created_walls_by_axis, all_openings,
                                      wall_graph_nodes, wall_end_to_node,
                                      catalog, catalog_missing,
                                      modulation_results, opening_incompatible_modulation,
                                      progress_cb=None, wall_start_cb=None, wall_result_cb=None,
                                      should_cancel_cb=None, should_pause_cb=None,
                                      wall_segment_geometry=None):
    """Passo "Analisar Paredes" da janela unica - agora e' o PIPELINE
    INTEGRADO (regras #3/#4/#5/#8/#9): percorre as paredes UMA A UMA na
    ordem geometrica obrigatoria e, para cada uma, lanca os blocos, verifica
    a modulacao, e SO' ENTAO - se ela nao fechou - procura um ajuste, que e'
    aceito unicamente quando o RE-LANCAMENTO dos blocos comprova que fechou.
    Nao existe mais "primeiro conserta todas as paredes, depois lanca os
    blocos".

    NAO escreve nada no Revit: o pipeline trabalha sobre copias em memoria e
    devolve os planos ja VERIFICADOS, que o passo "Ajustar Erros"
    (fix_all_wall_modulation_errors) aplica de verdade dentro de uma
    Transacao.

    Uma parede so' e' "erro" quando a MODULACAO REAL DE BLOCOS falha ou
    quando ela precisou de um ajuste para fechar - nunca porque o
    comprimento nao termina num digito "bonito" (essa regra foi removida
    por completo; ver a nota "REGRA DE DIGITO FINAL DAS PAREDES").

    Sem catalogo de blocos nao ha' analise possivel (e nao existe mais
    nenhuma regra de digito para usar no lugar): devolve uma unica linha
    dizendo exatamente isso, em vez de fingir um veredito.

    Devolve uma lista de dicts (1 por eixo com problema, na ordem de
    processamento):
        {"wall_idx":, "wall_ids": [ElementId,...], "problem_text": str,
         "auto_fixable": bool, "fix_plan": dict ou None}

    `progress_cb`, se fornecido, e' repassado ao pipeline principal (ver
    process_walls_one_by_one) - visibilidade AO VIVO do que costuma ser o
    trecho mais pesado e silencioso da execucao inteira (ver PERFORMANCE em
    main()).

    `wall_segment_geometry`: snapshot leve capturado uma unica vez na
    criacao das Walls (ver main(), Etapa 1, e _classify_wall_axis_segments)
    - quando fornecido, repassado a plan_axis_opening_fix em `plan_hook` e
    NENHUMA chamada desta funcao (nem de tudo que ela chama:
    process_walls_one_by_one, solve_building_blocks) toca `target_doc`. E'
    o que torna esta funcao segura para rodar fora da thread principal do
    Revit.

    NOTA (2026-08-26): a ETAPA 3C (deslocamento automatico de uma parede
    CONECTADA, sem relacao com abertura - find_wall_group_shift_fixes em
    core/engine/wall_stepper.py) foi RETIRADA do pipeline por pedido
    explicito do usuario, para priorizar velocidade e controle manual: o
    unico ajuste automatico que resta e' o de abertura (`plan_hook` acima).
    A funcao continua existindo em wall_stepper.py (com seus proprios
    testes), so' nao e' mais chamada daqui.
    """
    if catalog_missing:
        return [{
            "wall_idx": None, "wall_ids": [],
            "problem_text": (
                "catalogo de blocos incompleto ({}) - sem ele o solver nao roda, e o "
                "solver e' a UNICA fonte da verdade sobre modulacao. Carregue a(s) "
                "familia(s)/tipo(s) que faltam e rode de novo.".format(
                    ", ".join(str(item) for item in catalog_missing))
            ),
            "auto_fixable": False, "fix_plan": None,
        }]

    plan_failures = {}

    def plan_hook(wall_idx, fill_result, verify):
        """Ajuste candidato para UMA parede. Recebe `verify` - o solver de
        blocos de verdade rodando sobre a parede ja ajustada - e o repassa
        ao planejador, que so' devolve um plano depois de ele aprovar."""
        if not openings_for_wall(openings_per_wall, wall_idx):
            # Sem abertura no eixo nao ha' nada para deslocar: qualquer
            # correcao exigiria mexer num encontro vizinho, o que esta' fora
            # do escopo automatico (e nunca pode virar "aumentar a parede").
            return None
        # try/except POR PAREDE: um caso inesperado num unico eixo nunca
        # pode derrubar a analise da planta inteira.
        try:
            return plan_axis_opening_fix(
                target_doc, wall_idx, walls_to_create, openings_per_wall,
                created_walls_by_axis, all_openings, wall_end_to_node, wall_graph_nodes,
                verify=verify, wall_segment_geometry=wall_segment_geometry,
            )
        except Exception as plan_ex:
            plan_failures[wall_idx] = str(plan_ex)
            return None

    run = process_walls_one_by_one(
        walls_to_create, wall_graph_nodes, wall_end_to_node, openings_per_wall, catalog,
        plan_hook=plan_hook, progress_cb=progress_cb,
        wall_start_cb=wall_start_cb, wall_result_cb=wall_result_cb,
    )

    # ETAPA 3C (deslocamento automatico de uma parede CONECTADA, sem relacao
    # com abertura) foi REMOVIDA (2026-08-26, pedido explicito do usuario):
    # o unico ajuste automatico agora e' o de abertura (`plan_hook` acima,
    # via plan_axis_opening_fix - desloca a abertura e ajusta os pilaretes
    # do MESMO eixo). Qualquer parede que nao feche so' com isso fica
    # marcada azul na vista para o usuario corrigir manualmente - nunca mais
    # tenta deslocar uma OUTRA parede conectada.

    collision_axes = set()
    for i, j in run["collisions"]:
        for index in (i, j):
            axis_idx = run["candidates"][index].get("wall_idx")
            if axis_idx is not None:
                collision_axes.add(axis_idx)

    ft_to_cm = 100.0 / FEET_PER_METER
    rows = []
    for entry in run["per_wall"]:
        wall_idx = entry["wall_idx"]
        validation = entry["validation"]
        has_collision = wall_idx in collision_axes
        if validation["ok"] and not entry["adjusted"] and not has_collision:
            continue

        wall_ids = [eid for eid, _origin in created_walls_by_axis.get(wall_idx, [])]
        segs = entry["non_modular"]
        if segs:
            # `lower_valid_cm`/`upper_valid_cm` vem de nearest_block_lengths_cm
            # como INTEIROS - `{:.0f}` num int lanca "Precision not allowed in
            # integer format specifier" no IronPython 2.7 (diferente do
            # CPython, que aceita). Convertidos explicitamente com float().
            #
            # SEM_ESPACO (2026-08-25): "mais proximo que fecha em blocos: 0cm
            # ou 0cm" nao dizia NADA sobre qual encontro/abertura invade o
            # trecho - impossivel de reproduzir fora do projeto real so' com
            # isso. Quando o conflito e' SEM_ESPACO, mostra os DOIS limites do
            # trecho (tipo + posicao bruta) em vez do par lower/upper, que
            # nesse caso e' sempre (0, 0) e nao ajuda.
            def _seg_desc_one(s):
                if s.get("conflict") == "SEM_ESPACO":
                    return (
                        "trecho #{} (fiada {}) SEM ESPACO: limite esquerdo {} em t={:.1f}cm, "
                        "limite direito {} em t={:.1f}cm (intervalo negativo, {:.1f}cm)"
                    ).format(s["segment_index"], s["course"],
                             s.get("left_kind"), float(s.get("left_t_cm") or 0.0),
                             s.get("right_kind"), float(s.get("right_t_cm") or 0.0),
                             float(s["current_length_cm"]))
                return (
                    "trecho #{} (fiada {}) com {:.1f}cm (mais proximo que fecha em blocos: "
                    "{:.0f}cm ou {:.0f}cm)"
                ).format(s["segment_index"], s["course"], float(s["current_length_cm"]),
                         float(s["lower_valid_cm"]), float(s["upper_valid_cm"]))

            seg_desc = "; ".join(_seg_desc_one(s) for s in segs[:4])
            base_text = "modulacao de blocos nao fecha - " + seg_desc
        elif has_collision:
            base_text = "colisao entre pecas de blocos detectada nesta parede"
        elif entry["adjusted"]:
            base_text = "modulacao so' fecha com um ajuste"
        else:
            base_text = "validacao da parede reprovou - " + "; ".join(validation["problems"])

        if entry["adjusted"] and entry["plan"] is not None:
            plan = entry["plan"]
            tier_text = {
                "shift": "deslocar a(s) abertura(s)",
                "trim": "ENCURTAR uma ponta livre da parede",
                "widen": "aumentar a largura de abertura(s)",
            }.get(plan.get("tier"), plan.get("tier"))
            rows.append({
                "wall_idx": wall_idx, "wall_ids": wall_ids,
                "problem_text": (
                    base_text + " - correcao automatica JA VERIFICADA pelo solver de "
                    "blocos via {} (desloca ate {:.1f}cm; comprimento da parede {})"
                    .format(tier_text, plan["max_shift_cm"],
                            "inalterado" if abs(plan.get("length_delta_cm") or 0.0) < 1e-9
                            else "{:+.1f}cm".format(plan["length_delta_cm"]))
                ),
                "auto_fixable": True, "fix_plan": plan,
            })
            continue

        if wall_idx in plan_failures:
            detail = " - falha ao calcular a correcao ({}) - requer revisao manual".format(
                plan_failures[wall_idx])
        elif entry.get("plan_rejected") is not None:
            detail = (" - o ajuste calculado nao fecha a modulacao quando os blocos sao "
                      "lancados de verdade - requer revisao manual")
        elif entry["plan"] is not None and not entry["plan"].get("feasible"):
            detail = " - " + (entry["plan"].get("reason") or "sem correcao automatica")
        elif entry["plan"] is not None and entry["plan"].get("already_ok"):
            detail = (" - o eixo ja' esta' na melhor posicao possivel sem mexer na parede; "
                      "o que falta depende de um encontro vizinho (e aumentar a parede e' "
                      "proibido) - requer revisao manual")
        elif not openings_for_wall(openings_per_wall, wall_idx):
            detail = (" (sem abertura por perto - nenhuma correcao automatica disponivel; "
                      "aumentar a parede para encaixar os blocos e' proibido) - requer revisao "
                      "manual")
        else:
            detail = (" - nenhuma correcao automatica disponivel para a(s) abertura(s) deste "
                      "eixo - requer revisao manual")

        rows.append({
            "wall_idx": wall_idx, "wall_ids": wall_ids,
            "problem_text": base_text + detail,
            "auto_fixable": False, "fix_plan": None,
        })
    return rows
def fix_all_wall_modulation_errors(target_doc, error_rows, walls_to_create, openings_per_wall,
                                   created_walls_by_axis=None, all_openings=None, g=None,
                                   progress_cb=None, should_cancel_cb=None, should_pause_cb=None):
    """Passo 'Ajustar Erros' da janela unica: aplica plan_axis_opening_fix
    (ou, para linhas kind='group_shift' da ETAPA 3C, apply_wall_group_shift)
    de cada linha auto_fixable, um SubTransaction POR EIXO/GRUPO (isola
    falha de um do resto - mesmo padrao ja usado no validador ao vivo,
    _refresh_wall_modulation_override), revalida com evaluate_wall_modulation
    logo em seguida (pedido explicito do usuario: revalidar apos cada
    alteracao) e SO' escreve em openings_per_wall/walls_to_create quando o
    Commit realmente aconteceu (nunca antes - ver apply_axis_opening_fix).
    Precisa rodar dentro de uma Transacao ja aberta pelo chamador.

    `created_walls_by_axis`/`all_openings`: so' precisos quando algum `row`
    for kind='group_shift' (apply_wall_group_shift le' as pecas reais de
    TODOS os membros do grupo, nao so' de `wall_idx`) - podem ficar `None`
    se o chamador garantir que nenhuma linha e' group_shift (ex.: testes
    antigos que so' testam plan_axis_opening_fix).

    `g`: dicionario opcional (ver _PostCreationEventHandler.__init__/self._g)
    usado para SOMBREAR como variaveis LOCAIS os nomes de modulo usados
    aqui (SubTransaction, apply_axis_opening_fix, apply_wall_group_shift,
    evaluate_wall_modulation, _invalidate_opening_gap_cache) - confirmado
    ao vivo (2026-08-21) que a busca de nome GLOBAL "solta" (bare) pode
    falhar com UnboundNameException quando esta funcao e' chamada a partir
    do ExternalEvent (_PostCreationEventHandler.Execute), mesmo numa janela
    RECEM-criada (nao e' so' uma questao de "janela antiga" - reparar o
    dicionario de globais via `.update()` NAO resolveu; so' variavel LOCAL
    e' garantidamente confiavel). Sem `g` (chamado de outro lugar, ex.: os
    testes offline), usa os nomes globais normais.

    `progress_cb(mensagem)`/`should_cancel_cb()`/`should_pause_cb()`, se
    fornecidos: MESMO contrato/pontos de checagem ja usados por
    find_wall_group_shift_fixes (ver seu docstring) - existiam la' mas nao
    aqui, o que deixava exatamente ESTE laco (o que aplica de verdade cada
    SubTransaction) mudo e sem Cancelar/Pausar enquanto rodava (FASE 0 do
    plano em C:\\Users\\CIVIX\\.claude\\plans\\quiet-painting-petal.md).
    `should_pause_cb()` True faz o laco ESPERAR (bombeando
    Application.DoEvents() para nao travar a UI) antes de aplicar a
    proxima linha - nunca no meio de uma SubTransaction ja aberta.
    `should_cancel_cb()` True para ANTES de abrir a SubTransaction da
    proxima linha, preservando todas as que ja commitaram.

    Devolve (fixed_count, manual_review_count, updated_rows)."""
    # Atribuicao INCONDICIONAL (nunca so' dentro de `if g is not None:`) -
    # mesmo motivo documentado em apply_wall_group_shift: uma atribuicao
    # condicional a um nome ja' usado como bare-name mais abaixo faz o
    # Python tratar esse nome como LOCAL na funcao inteira (analise
    # estatica), e com g=None a atribuicao nunca rodaria - UnboundLocalError
    # na primeira linha que usasse SubTransaction/etc., contrariando o que
    # este docstring promete ("sem g... usa os nomes globais normais").
    SubTransaction = g["SubTransaction"] if g is not None else globals()["SubTransaction"]
    apply_axis_opening_fix = (
        g["apply_axis_opening_fix"] if g is not None else globals()["apply_axis_opening_fix"]
    )
    apply_wall_group_shift = (
        g["apply_wall_group_shift"] if g is not None else globals()["apply_wall_group_shift"]
    )
    evaluate_wall_modulation = (
        g["evaluate_wall_modulation"] if g is not None else globals()["evaluate_wall_modulation"]
    )
    _invalidate_opening_gap_cache = (
        g["_invalidate_opening_gap_cache"] if g is not None else globals()["_invalidate_opening_gap_cache"]
    )

    fixed_count = 0
    updated_rows = []
    # Preenchido quando um group_shift (ETAPA 3C) e' aplicado com sucesso:
    # {wall_idx: shifted_wall_idx} para CADA parede do grupo, inclusive as
    # que so' tinham a linha "resolvida JUNTO" (auto_fixable=False,
    # fix_plan=None - ver analyze_created_walls_for_errors) - usado no
    # segundo passo, mais abaixo, para essas linhas tambem saírem marcadas
    # `resolved=True` (senao manual_review_count as contaria como ainda
    # pendentes, mesmo tendo sido corrigidas junto com a parede primaria).
    group_shift_resolved = {}
    total_rows = len(error_rows)
    for _ri, row in enumerate(error_rows):
        if not row["auto_fixable"] or row["fix_plan"] is None:
            updated_rows.append(row)
            continue
        if should_pause_cb is not None:
            while should_pause_cb():
                Application.DoEvents()
        if should_cancel_cb is not None and should_cancel_cb():
            if progress_cb is not None:
                progress_cb(
                    "CANCELADO pelo usuario durante 'Ajustar Erros' - {} linha(s) ainda "
                    "nao processada(s), mantendo o que ja foi aplicado ate' aqui."
                    .format(total_rows - _ri)
                )
            updated_rows.extend(error_rows[_ri:])
            break
        plan = row["fix_plan"]
        if progress_cb is not None:
            progress_cb(
                "AJUSTAR: eixo {} ({}/{}) - aplicando {}...".format(
                    row.get("wall_idx"), _ri + 1, total_rows, plan.get("kind")
                )
            )
        # Os dois tipos de plano baseados em `members` (deslocamento de
        # grupo e ajuste de comprimento) sao aplicados por
        # apply_wall_group_shift. Dispatchar so' por "group_shift"
        # mandava o plano de comprimento para apply_axis_opening_fix,
        # que faz plan["wall_idx"] - chave que ele NAO tem: KeyError,
        # RollBack, e a linha virava "nao foi possivel aplicar". Era o
        # que mantinha o ajuste de comprimento MORTO em producao.
        is_wall_geometry_plan = plan.get("kind") in ("group_shift", "wall_length_adjust")
        st = SubTransaction(target_doc)
        st.Start()
        try:
            if is_wall_geometry_plan:
                applied_count, failures = apply_wall_group_shift(
                    target_doc, plan, walls_to_create, openings_per_wall,
                    created_walls_by_axis, all_openings, g=g
                )
            else:
                applied_count, failures = apply_axis_opening_fix(target_doc, plan, walls_to_create, g=g)
            if failures:
                raise Exception("; ".join(failures))
            target_doc.Regenerate()
            revalidated = evaluate_wall_modulation(row["wall_ids"], target_doc)
            still_bad = [r for r in revalidated if not r["compatible"]]
            if still_bad:
                raise Exception("revalidacao apos o ajuste ainda aponta erro")
            st.Commit()
            if is_wall_geometry_plan:
                # So' agora, POS-Commit, escreve as novas Line em
                # walls_to_create para CADA membro do grupo (a parede
                # deslocada + as vizinhas cujo comprimento mudou) - mesma
                # disciplina de nunca mutar o espelho Python antes do
                # commit realmente acontecer.
                for member in plan["members"]:
                    m_idx = member["wall_idx"]
                    _old_line, thickness_ft, locks = walls_to_create[m_idx]
                    walls_to_create[m_idx] = (member["new_centerline"], thickness_ft, locks)
                    group_shift_resolved[m_idx] = plan["shifted_wall_idx"]
            else:
                wall_idx = plan["wall_idx"]
                for new_op in plan["new_openings"]:
                    openings_per_wall[wall_idx][new_op["opening_index"]] = (
                        new_op["t_lo_new"], new_op["t_hi_new"],
                        new_op["sill_z_abs"], new_op["head_z_abs"]
                    )
            try:
                _invalidate_opening_gap_cache(target_doc)
            except Exception:
                pass
            fixed_count += 1
            new_row = dict(row)
            if plan.get("kind") == "wall_length_adjust":
                new_row["problem_text"] = (
                    "corrigido automaticamente (comprimento da parede ajustado em "
                    "{:+.1f}cm, em ponta LIVRE)".format(float(plan["shift_delta_cm"]))
                )
            elif is_wall_geometry_plan:
                new_row["problem_text"] = (
                    "corrigido automaticamente (parede conectada deslocada {:+.1f}cm)".format(
                        float(plan["shift_delta_cm"]))
                )
            else:
                new_row["problem_text"] = (
                    "corrigido automaticamente (deslocamento maximo {:.1f}cm)".format(
                        float(plan["max_shift_cm"]))
                )
            new_row["auto_fixable"] = False
            new_row["fix_plan"] = None
            new_row["resolved"] = True
            # ElementId REAIS tocados por este plano - usado so' para o
            # realce VERDE ("parede alterada nesta rodada", pedido explicito
            # do usuario) aplicado pelo CHAMADOR (_execute_fix_errors) DEPOIS
            # do Commit do t externo - nunca lido por nenhuma logica de
            # modulacao, so' UI.
            if is_wall_geometry_plan:
                green_ids = []
                for member in plan["members"]:
                    green_ids.extend(
                        eid for eid, _origin in created_walls_by_axis.get(member["wall_idx"], [])
                    )
                new_row["_just_fixed_wall_ids"] = green_ids
            else:
                new_row["_just_fixed_wall_ids"] = list(row["wall_ids"])
            updated_rows.append(new_row)
            if progress_cb is not None:
                progress_cb("CONCLUIDO: eixo {} - {}.".format(row.get("wall_idx"), new_row["problem_text"]))
        except Exception as ex:
            st.RollBack()
            new_row = dict(row)
            new_row["problem_text"] = "nao foi possivel aplicar: {} - requer revisao manual".format(ex)
            new_row["auto_fixable"] = False
            new_row["fix_plan"] = None
            updated_rows.append(new_row)
            if progress_cb is not None:
                progress_cb("FALHOU: eixo {} - {}.".format(row.get("wall_idx"), new_row["problem_text"]))

    # Segundo passo: a linha "resolvida JUNTO com a parede X" (ver
    # analyze_created_walls_for_errors, ramo `group_plan is not None`) foi
    # copiada para updated_rows como veio - `resolved` nunca foi setado
    # nela, porque a linha em si nunca carregou nenhum fix_plan (so' a
    # PRIMARIA carrega, para nao aplicar o mesmo deslocamento de grupo duas
    # vezes). Agora que sabemos quais grupos realmente commitaram
    # (`group_shift_resolved`), atualiza essas linhas tambem - senao
    # `manual_review_count` as contaria como pendentes mesmo corrigidas.
    if group_shift_resolved:
        for i, row in enumerate(updated_rows):
            if row.get("resolved") or row["wall_idx"] not in group_shift_resolved:
                continue
            # Copia (nunca muta `row` in-place) - o mesmo dict pode ser o
            # OBJETO ORIGINAL de `error_rows` (linhas nao-auto_fixable so'
            # sao repassadas adiante, nunca reconstruidas) e o chamador
            # pode ainda depender dele ate' reatribuir error_rows/self.error_rows.
            new_row = dict(row)
            new_row["resolved"] = True
            new_row["problem_text"] = (
                "corrigido automaticamente junto com a parede {} (deslocamento de grupo "
                "conectado, ETAPA 3C)".format(group_shift_resolved[row["wall_idx"]])
            )
            new_row["_just_fixed_wall_ids"] = [
                eid for eid, _origin in created_walls_by_axis.get(row["wall_idx"], [])
            ]
            updated_rows[i] = new_row

    manual_review_count = sum(1 for r in updated_rows if not r.get("resolved"))
    return fixed_count, manual_review_count, updated_rows


try:
    unicode_type = unicode  # IronPython 2.7 (o Revit roda neste)
except NameError:  # pragma: no cover - so' no Python 3 dos testes
    unicode_type = str


def _copy_text_to_clipboard(text):
    """Tenta copiar `text` para a area de transferencia do Windows -
    forms.alert (pyRevit) nao tem botao de copiar nativo, e o log final pode
    ser longo demais para ler comodamente so' na tela. Tenta primeiro
    System.Windows.Forms.Clipboard e, se essa assembly nao estiver
    disponivel/falhar, cai para System.Windows.Clipboard (WPF) - a
    disponibilidade de cada uma pode variar entre versoes do Revit/pyRevit.
    Devolve True/False; NUNCA lanca excecao - falhar em copiar nao pode
    impedir o restante do script de terminar normalmente (ver _save_log_to_file
    para o fallback em arquivo)."""
    try:
        import clr
        clr.AddReference("System.Windows.Forms")
        from System.Windows.Forms import Clipboard
        Clipboard.SetText(text)
        return True
    except Exception:
        pass
    try:
        import clr
        clr.AddReference("PresentationCore")
        from System.Windows import Clipboard as WpfClipboard
        WpfClipboard.SetText(text)
        return True
    except Exception:
        return False


def _save_log_to_file(text):
    """Salva o log completo num .txt no diretorio temporario do usuario
    (nome com carimbo de data/hora, para nao sobrescrever execucoes
    anteriores) - registro permanente e fallback caso a copia para a area de
    transferencia falhe (ver _copy_text_to_clipboard). Devolve o caminho do
    arquivo ou None se a gravacao falhar (NUNCA lanca excecao)."""
    try:
        filename = "log_paredes_cad_{}.txt".format(datetime.now().strftime("%Y%m%d_%H%M%S"))
        path = os.path.join(tempfile.gettempdir(), filename)
        # UTF-8 EXPLICITO: nomes de Layer/Nivel/familia vem do modelo e
        # frequentemente tem acento ("Nivel 1 - Ceramica", "PAREDE ALVENARIA
        # 14 - AREA TECNICA"). No IronPython 2.7 o `open()` em modo texto
        # grava com o codec ascii e qualquer acento derrubava a gravacao
        # inteira - o log simplesmente nao era salvo, em silencio.
        import codecs
        with codecs.open(path, "w", "utf-8") as log_file:
            log_file.write(text if isinstance(text, unicode_type) else text.decode("utf-8", "replace"))
        return path
    except Exception:
        return None


# ==========================================
# JANELAS MODELESS (nao bloqueiam o Revit) - a janela unica de resultado/
# modulacao (ver _PostCreationForm, mais abaixo) e' modeless.
#
# MOTIVACAO: forms.alert/forms.SelectFromList do pyRevit usam ShowDialog
# (modal) - enquanto abertos, o usuario nao consegue clicar/editar nada no
# Revit, precisando fechar a caixa so' para ir conferir uma parede antes de
# decidir o que fazer. Uma janela WinForms comum, mostrada com .Show() (nao
# .ShowDialog()), e' modeless de verdade: o Revit continua respondendo a
# clique/selecao/edicao com a janela aberta.
#
# LIMITACAO TECNICA que isso implica: uma chamada a Transaction() dentro do
# Click de um controle de uma janela modeless NAO e' um contexto valido da
# API do Revit (o Revit so' garante isso dentro do Execute() do proprio
# comando externo, que ja' terminou quando main() retorna para mostrar a
# janela). Por isso toda escrita de verdade (ajustar erros, solver, criar
# blocos, dar zoom, excluir paredes) precisa ser despachada via
# ExternalEvent - ver _PostCreationEventHandler, mais abaixo - que o Revit
# garante rodar dentro de um contexto valido, mesmo com a janela aberta
# modeless.
# ==========================================
# -*- coding: utf-8 -*-
# ==========================================
# INTERFACE - PALETA, ESTILOS E COMPONENTES COMUNS
#
# Todas as janelas do script usam os mesmos tokens (cor, fonte, espacamento)
# e os mesmos tijolos (_build_header, _build_section, _build_card) para que
# as telas sejam reconheciveis como um unico programa, e nao tres caixas de
# dialogo diferentes coladas.
# ==========================================

import clr
clr.AddReference("System.Windows.Forms")
clr.AddReference("System.Drawing")
from System.Windows.Forms import (
    Form, Label, Button, CheckedListBox, TextBox, DockStyle,
    ScrollBars, AnchorStyles, Padding, Panel,
    ListView, ListViewItem, View, ColumnHeaderStyle, HorizontalAlignment,
    BorderStyle, FlatStyle, FormBorderStyle, FormStartPosition,
    CheckBox, RadioButton, GroupBox,
    ComboBox, ComboBoxStyle, TabControl, TabPage,
    ProgressBar, ProgressBarStyle, Application
)
# `FormStartPosition.CenterScreen` (MEMBRO por nome) nao resolve neste
# engine CPython (pythonnet) do pyRevit - AttributeError real medido em
# producao, 2026-08-27: "type object 'FormStartPosition' has no attribute
# 'CenterScreen'" - so' o MEMBRO, nao o TIPO em si (import acima funciona
# normal). E passar o inteiro CRU (1) direto pra propriedade `Form.
# StartPosition` tambem nao funciona nesta versao do pythonnet - erro
# SEPARADO, tambem real em producao (2026-08-27): "since Python.NET 3.0
# int can not be converted to Enum implicitly. Use Enum(int_value)".
# `FormStartPosition(1)` (a propria correcao que o erro recomenda) contorna
# os dois de uma vez: nao acessa o membro por nome E ja' entrega um enum de
# verdade, pronto pra atribuir a `Form.StartPosition`.
FORM_START_POSITION_CENTER_SCREEN = FormStartPosition(1)  # .CenterScreen
from System.Drawing import Font, FontFamily, Color, Size, FontStyle, Point


from System import Enum as _DotNetEnum


class _EnumFallback(object):
    """Envolve um enum .NET (System.Windows.Forms/System.Drawing) para
    sobreviver ao mesmo bug medido em producao (2026-08-27, ver comentario
    do FORM_START_POSITION_CENTER_SCREEN acima): nesta instalacao/versao
    do engine CPython (pythonnet) do pyRevit, alguns enums importados via
    `from Namespace import EnumType` nao expoem seus membros por atributo
    (`EnumType.Membro` levanta AttributeError, embora o TIPO em si importe
    sem erro). Tenta o atributo real primeiro (funciona normalmente fora
    desse bug); so' cai para a tabela de valores INTEIROS PADRAO do .NET
    (estaveis, documentados, iguais em qualquer versao do Framework/Core)
    quando o atributo de verdade nao resolve.

    Devolve o ENUM DE VERDADE (`self._real(valor_inteiro)`), NUNCA o
    inteiro cru - um bug SEPARADO e' medido tambem em producao (2026-08-27):
    atribuir um int Python direto a uma propriedade .NET tipada como enum
    nao converte implicitamente nesta versao do pythonnet ("since Python.NET
    3.0 int can not be converted to Enum implicitly. Use Enum(int_value)" -
    a mensagem de erro real ja' aponta a correcao certa: chamar o TIPO do
    enum como construtor com o inteiro)."""

    def __init__(self, real_enum_type, known_values):
        self._real = real_enum_type
        self._known = known_values

    def _from_int(self, int_value):
        try:
            return self._real(int_value)
        except Exception:
            try:
                return _DotNetEnum.ToObject(self._real, int_value)
            except Exception:
                return int_value

    def __getattr__(self, name):
        try:
            return getattr(self._real, name)
        except AttributeError:
            if name in self._known:
                return self._from_int(self._known[name])
            raise


DockStyle = _EnumFallback(DockStyle, {
    "None": 0, "Top": 1, "Bottom": 2, "Left": 3, "Right": 4, "Fill": 5,
})
ScrollBars = _EnumFallback(ScrollBars, {
    "None": 0, "Horizontal": 1, "Vertical": 2, "Both": 3,
})
View = _EnumFallback(View, {
    "LargeIcon": 0, "Details": 1, "SmallIcon": 2, "List": 3, "Tile": 4,
})
ColumnHeaderStyle = _EnumFallback(ColumnHeaderStyle, {
    "None": 0, "Nonclickable": 1, "Clickable": 2,
})
BorderStyle = _EnumFallback(BorderStyle, {
    "None": 0, "FixedSingle": 1, "Fixed3D": 2,
})
FlatStyle = _EnumFallback(FlatStyle, {
    "Flat": 0, "Popup": 1, "Standard": 2, "System": 3,
})
ComboBoxStyle = _EnumFallback(ComboBoxStyle, {
    "Simple": 0, "DropDown": 1, "DropDownList": 2,
})
ProgressBarStyle = _EnumFallback(ProgressBarStyle, {
    "Blocks": 0, "Continuous": 1, "Marquee": 2,
})
FontStyle = _EnumFallback(FontStyle, {
    "Regular": 0, "Bold": 1, "Italic": 2, "Underline": 4, "Strikeout": 8,
})
from System.Threading import Timer as _DotNetTimer
# Thread/ThreadStart: usados so' por _PostCreationEventHandler._execute_analyze
# (ver Mudanca 2 do plano de arquitetura em memoria) para rodar o solver de
# modulacao (analyze_created_walls_for_errors, 100% livre de target_doc
# quando `wall_segment_geometry` e' fornecido - ver _classify_wall_axis_segments)
# fora da thread principal do Revit, mantendo a UI responsiva.
from System.Threading import Thread as _DotNetThread, ThreadStart as _DotNetThreadStart
from System import Action

# Paleta unica da interface - definida uma vez para que todas as janelas
# tenham a mesma linguagem visual, em vez das cores padrao do WinForms.
UI_BG = Color.FromArgb(250, 250, 252)
UI_PANEL = Color.FromArgb(255, 255, 255)
UI_HEADER = Color.FromArgb(31, 41, 55)
UI_TEXT = Color.FromArgb(31, 41, 55)
UI_MUTED = Color.FromArgb(107, 114, 128)
UI_ACCENT = Color.FromArgb(37, 99, 235)
UI_OK = Color.FromArgb(16, 133, 88)
UI_WARN = Color.FromArgb(180, 83, 9)
UI_ERROR = Color.FromArgb(185, 28, 28)
UI_LINE = Color.FromArgb(229, 231, 235)
UI_SOFT = Color.FromArgb(243, 244, 246)

# Severidades usadas nas ocorrencias do relatorio final (ver _ResultsForm):
# rotulo mostrado na coluna + cor da linha.
UI_SEVERITY = {
    "erro": ("ERRO", UI_ERROR),
    "atencao": ("ATENCAO", UI_WARN),
    "info": ("INFO", UI_MUTED),
    "ok": ("OK", UI_OK),
}


def _ui_font(size=9.0, bold=False):
    return Font("Segoe UI", size, FontStyle.Bold if bold else FontStyle.Regular)


def _style_primary_button(button):
    """Botao de acao principal - preenchido, sem borda 3D do WinForms."""
    button.FlatStyle = FlatStyle.Flat
    button.FlatAppearance.BorderSize = 0
    button.BackColor = UI_ACCENT
    button.ForeColor = Color.White
    button.Font = _ui_font(9.5, True)
    button.Height = 38


def _style_secondary_button(button):
    """Botao secundario - contorno leve, para acoes nao destrutivas."""
    button.FlatStyle = FlatStyle.Flat
    button.FlatAppearance.BorderSize = 1
    button.FlatAppearance.BorderColor = UI_LINE
    button.BackColor = UI_PANEL
    button.ForeColor = UI_TEXT
    button.Font = _ui_font(9.5)
    button.Height = 38


def _set_button_enabled(button, enabled):
    """Habilita/desabilita mantendo o botao LEGIVEL quando desabilitado (o
    cinza padrao do WinForms sobre fundo azul fica ilegivel)."""
    button.Enabled = enabled
    button.BackColor = UI_ACCENT if enabled else UI_LINE
    button.ForeColor = Color.White if enabled else UI_MUTED


def _build_header(title, subtitle):
    """Faixa de titulo escura no topo das janelas - da' hierarquia visual
    imediata (o que e' esta janela) antes do conteudo."""
    header = Panel()
    header.Dock = DockStyle.Top
    header.Height = 74
    header.BackColor = UI_HEADER

    title_label = Label()
    title_label.Text = title
    title_label.ForeColor = Color.White
    title_label.Font = _ui_font(13.0, True)
    title_label.AutoSize = False
    title_label.Dock = DockStyle.Top
    title_label.Height = 34
    title_label.Padding = Padding(18, 12, 18, 0)

    subtitle_label = Label()
    subtitle_label.Text = subtitle
    subtitle_label.ForeColor = Color.FromArgb(180, 190, 205)
    subtitle_label.Font = _ui_font(8.75)
    subtitle_label.AutoSize = False
    subtitle_label.Dock = DockStyle.Fill
    subtitle_label.Padding = Padding(20, 0, 18, 8)

    header.Controls.Add(subtitle_label)
    header.Controls.Add(title_label)
    return header


def _build_section_label(text, hint=None):
    """Titulo de um bloco do formulario ('1. Layer das paredes'), com uma
    linha de ajuda opcional embaixo - e' o que transforma uma pilha de
    controles soltos numa sequencia de passos legivel."""
    holder = Panel()
    holder.Dock = DockStyle.Top
    holder.Height = 42 if hint else 26
    holder.BackColor = UI_PANEL

    if hint:
        hint_label = Label()
        hint_label.Text = hint
        hint_label.Dock = DockStyle.Bottom
        hint_label.Height = 18
        hint_label.Font = _ui_font(8.25)
        hint_label.ForeColor = UI_MUTED
        holder.Controls.Add(hint_label)

    title = Label()
    title.Text = text
    title.Dock = DockStyle.Top
    title.Height = 22
    title.Font = _ui_font(9.5, True)
    title.ForeColor = UI_TEXT
    holder.Controls.Add(title)
    return holder


def _build_card(caption, value, color):
    """Cartao de numero do resumo ('Paredes criadas: 128') - o numero em
    destaque, o rotulo pequeno embaixo."""
    card = Panel()
    card.Dock = DockStyle.Left
    card.Width = 168
    card.BackColor = UI_PANEL
    card.Padding = Padding(14, 10, 8, 10)

    # O controle de Dock.Fill entra PRIMEIRO na colecao: o WinForms ancora
    # os controles na ordem INVERSA do indice, entao o Fill precisa ser o de
    # menor indice para sobrar com o espaco que os demais nao usaram (mesma
    # convencao do resto do arquivo).
    value_label = Label()
    value_label.Text = str(value)
    value_label.Dock = DockStyle.Fill
    value_label.Font = _ui_font(17.0, True)
    value_label.ForeColor = color
    card.Controls.Add(value_label)

    caption_label = Label()
    caption_label.Text = caption
    caption_label.Dock = DockStyle.Bottom
    caption_label.Height = 18
    caption_label.Font = _ui_font(8.25)
    caption_label.ForeColor = UI_MUTED
    card.Controls.Add(caption_label)

    spacer = Panel()
    spacer.Dock = DockStyle.Left
    spacer.Width = 10
    spacer.BackColor = UI_BG
    return card, spacer


def _monospace_textbox(text):
    box = TextBox()
    box.Multiline = True
    box.ReadOnly = True
    box.ScrollBars = ScrollBars.Both
    box.WordWrap = False
    box.Font = Font(FontFamily.GenericMonospace, 9.0)
    box.BackColor = UI_PANEL
    box.ForeColor = UI_TEXT
    box.BorderStyle = getattr(BorderStyle, "None")
    box.Text = (text or "").replace("\n", "\r\n")
    box.Dock = DockStyle.Fill
    return box


def _styled_listview(columns, checkboxes=False):
    grid = ListView()
    grid.Dock = DockStyle.Fill
    grid.View = View.Details
    grid.FullRowSelect = True
    grid.GridLines = False
    grid.CheckBoxes = checkboxes
    # BorderStyle.None nao pode ser escrito assim: `None` e' palavra
    # reservada do Python, entao o acesso tem que ser por getattr.
    grid.BorderStyle = getattr(BorderStyle, "None")
    grid.BackColor = UI_PANEL
    grid.ForeColor = UI_TEXT
    grid.Font = _ui_font(9.0)
    grid.HeaderStyle = ColumnHeaderStyle.Nonclickable
    for caption, width in columns:
        grid.Columns.Add(caption, width)
    return grid


# ==========================================
# CONSOLE DE PROGRESSO (log AO VIVO + barra de progresso + status) - pedido
# explicito do usuario (2026-08-26): as duas telas do fluxo (Modulacao das
# Paredes / Modulacao dos Blocos) precisam de uma area de log em tempo real,
# uma barra de progresso que nunca fica parada em 0% nem pula pra 100% cedo
# demais, e um status textual da etapa atual - para nunca deixar a
# impressao de "travou" durante o solver (a queixa real reportada, com
# imagem, do "carregamento infinito" no lancamento de blocos).
#
# TRUQUE DE THREADING: `Execute()` (ver _PostCreationEventHandler) roda
# SINCRONO na MESMA thread de UI do WinForms (o Revit hospeda o loop de
# mensagens) - enquanto o solver calcula, a janela NAO processaria
# pintura/scroll normalmente. `Application.DoEvents()`, chamado a cada
# atualizacao de log/progresso (ver `log`/`set_progress` abaixo), bombeia a
# fila de mensagens do WinForms manualmente nesses pontos, entao a janela
# repinta e rola o log MESMO durante o calculo sincrono - e' o mesmo truque
# usado por qualquer script IronPython/pythonnet que precisa de feedback ao
# vivo dentro de um IExternalEventHandler.Execute().
#
# WATCHDOG: quando uma UNICA parede/fiada demora mais que
# SOLVER_SLOW_WARNING_SECONDS SEM nenhuma chamada de log/progresso (loop
# python "preso" numa tentativa pesada, sem nenhum callback disparando), um
# System.Threading.Timer de VERDADE (roda numa thread do ThreadPool,
# independente do loop de mensagens do WinForms - ao contrario de
# System.Windows.Forms.Timer, que so' dispara quando o loop de mensagens
# esta' livre, ou seja, NUNCA durante o Execute() sincrono) verifica
# periodicamente ha' quanto tempo a ultima atualizacao aconteceu e, se
# passou do limite, registra um aviso via `BeginInvoke` (assincrono - a
# thread do timer nunca fica bloqueada esperando a UI, que so' vai
# processar essa mensagem no proximo DoEvents()).
# ==========================================

SOLVER_SLOW_WARNING_SECONDS = 8.0
SOLVER_WATCHDOG_INTERVAL_MS = 3000
# Intervalo de espera (segundos) dos lacos "while should_pause_cb(): ..."
# QUE RODAM NUMA THREAD DE FUNDO (ver find_wall_group_shift_fixes, chamada a
# partir de analyze_created_walls_for_errors numa System.Threading.Thread
# real - Mudanca 2 do plano de arquitetura em memoria). Application.DoEvents()
# so' bombeia o loop de mensagens do Windows da thread QUE O CHAMA - numa
# thread de fundo sem loop de mensagens, e' inutil (na melhor hipotese) ou
# lanca (na pior); time.sleep e' o equivalente correto/seguro em qualquer
# thread. O laco EQUIVALENTE em fix_all_wall_modulation_errors continua
# usando Application.DoEvents() de proposito - aquele roda na thread de UI
# de verdade (escrita real no Revit, ver Mudanca 3), onde bombear a fila
# ainda e' o comportamento certo.
PAUSE_POLL_INTERVAL_S = 0.05


class _ProgressConsole(object):
    """Bloco reutilizavel (status + barra de progresso + log) usado pelas
    duas telas do fluxo (_WallReviewForm/Tela 1 "Modulacao das Paredes" e
    _PostCreationForm/Tela 2 "Modulacao dos Blocos"). `self.panel` e' o
    controle WinForms pronto para `Controls.Add(...)` num Dock.Fill/Top do
    formulario dono."""

    def __init__(self, height=230):
        self._UI_MUTED = UI_MUTED
        self._UI_OK = UI_OK
        self._UI_WARN = UI_WARN
        self._UI_TEXT = UI_TEXT
        self._UI_ACCENT = UI_ACCENT

        self._last_update_time = time.time()
        self._last_watchdog_notice_time = 0.0
        self._current_label = ""
        self._watchdog_timer = None
        self._closed = False

        self.panel = Panel()
        self.panel.Dock = DockStyle.Fill
        self.panel.BackColor = UI_PANEL

        # ORDEM DE Controls.Add() - mesmo aviso do resto do arquivo: para o
        # MESMO DockStyle, o WinForms empilha na ordem INVERSA da insercao.
        top = Panel()
        top.Dock = DockStyle.Top
        top.Height = 74
        top.BackColor = UI_PANEL
        top.Padding = Padding(0, 4, 0, 6)

        self._status_label = Label()
        self._status_label.Dock = DockStyle.Top
        self._status_label.Height = 22
        self._status_label.Font = _ui_font(9.5, True)
        self._status_label.ForeColor = self._UI_TEXT
        self._status_label.Text = "Aguardando..."

        self._progress_bar = ProgressBar()
        self._progress_bar.Dock = DockStyle.Top
        self._progress_bar.Height = 20
        self._progress_bar.Minimum = 0
        self._progress_bar.Maximum = 100
        self._progress_bar.Value = 0
        self._progress_bar.Style = ProgressBarStyle.Continuous

        self._detail_label = Label()
        self._detail_label.Dock = DockStyle.Top
        self._detail_label.Height = 20
        self._detail_label.Font = _ui_font(8.25)
        self._detail_label.ForeColor = self._UI_MUTED
        self._detail_label.Text = ""

        top.Controls.Add(self._detail_label)
        top.Controls.Add(self._progress_bar)
        top.Controls.Add(self._status_label)

        self._log_box = _monospace_textbox("")

        self.panel.Controls.Add(self._log_box)
        self.panel.Controls.Add(top)

    # ------------------------------------------------------------- log
    def _invoke_if_needed(self, fn):
        """Marshala `fn` (sem argumentos) para a thread de UI quando este
        metodo e' chamado de uma thread DIFERENTE da que criou os controles
        (ex.: a thread de fundo do solver de "Analisar Paredes" - ver
        Mudanca 2 do plano de arquitetura em memoria) - mesma tecnica ja'
        comprovada em _on_watchdog_tick (BeginInvoke a partir de uma thread
        do ThreadPool), generalizada aqui para qualquer metodo desta classe.
        Devolve True quando REAGENDOU (o chamador deve retornar sem executar
        o corpo agora - a chamada marshalada vai reentrar no mesmo metodo,
        ja' na thread certa, onde InvokeRequired sera' False). Devolve False
        no caminho normal (mesma thread dos controles, sem overhead nenhum -
        comportamento identico ao de antes desta mudanca)."""
        try:
            if self._log_box.InvokeRequired:
                self._log_box.BeginInvoke(Action(fn))
                return True
        except Exception:
            pass
        return False

    def log(self, message):
        """Acrescenta UMA linha com timestamp `[HH:MM:SS]` e rola pro fim -
        chamado a CADA operacao relevante (nunca so' no final), pedido
        explicito do usuario ("O log deve ser atualizado em tempo real")."""
        if self._closed:
            return
        if self._invoke_if_needed(lambda: self.log(message)):
            return
        try:
            stamp = time.strftime("%H:%M:%S")
            line = "[{}] {}".format(stamp, message)
            if self._log_box.TextLength:
                self._log_box.AppendText("\r\n" + line)
            else:
                self._log_box.AppendText(line)
            self._log_box.SelectionStart = self._log_box.TextLength
            self._log_box.ScrollToCaret()
            self._touch(message)
            Application.DoEvents()
        except Exception:
            pass

    def full_text(self):
        return self._log_box.Text

    # -------------------------------------------------------- status/bar
    def set_status(self, text, kind="info"):
        if self._invoke_if_needed(lambda: self.set_status(text, kind)):
            return
        color = {
            "ok": self._UI_OK, "warn": self._UI_WARN, "error": self._UI_WARN,
        }.get(kind, self._UI_TEXT)
        try:
            self._status_label.Text = text
            self._status_label.ForeColor = color
            Application.DoEvents()
        except Exception:
            pass

    def set_progress(self, done, total, detail=None):
        """Atualiza a barra (NUNCA fica em 0% enquanto `done>0`, NUNCA
        chega a 100% antes de `done>=total` - pedido explicito do
        usuario)."""
        if self._invoke_if_needed(lambda: self.set_progress(done, total, detail)):
            return
        try:
            total = max(1, int(total or 1))
            done = max(0, min(int(done or 0), total))
            pct = int(round(100.0 * done / total))
            if done > 0:
                pct = max(pct, 1)
            if done < total:
                pct = min(pct, 99)
            self._progress_bar.Style = ProgressBarStyle.Continuous
            self._progress_bar.Maximum = 100
            self._progress_bar.Value = pct
            self._detail_label.Text = detail or "{}/{} processado(s) - {}%".format(done, total, pct)
            self._touch(detail or "")
            Application.DoEvents()
        except Exception:
            pass

    def set_indeterminate(self, detail=None):
        """Quando o total ainda nao e' conhecido (ex.: preparando o
        solver) - marquee em vez de uma barra parada em 0%, para nunca
        parecer travado."""
        if self._invoke_if_needed(lambda: self.set_indeterminate(detail)):
            return
        try:
            self._progress_bar.Style = ProgressBarStyle.Marquee
            self._progress_bar.MarqueeAnimationSpeed = 30
            if detail:
                self._detail_label.Text = detail
            self._touch(detail or "")
            Application.DoEvents()
        except Exception:
            pass

    def mark_complete(self, text):
        if self._invoke_if_needed(lambda: self.mark_complete(text)):
            return
        try:
            self._progress_bar.Style = ProgressBarStyle.Continuous
            self._progress_bar.Maximum = 100
            self._progress_bar.Value = 100
            self.set_status(text, "ok")
            self._detail_label.Text = "Concluido."
            Application.DoEvents()
        except Exception:
            pass

    def mark_failed(self, text):
        if self._invoke_if_needed(lambda: self.mark_failed(text)):
            return
        try:
            self.set_status(text, "error")
            Application.DoEvents()
        except Exception:
            pass

    # ------------------------------------------------------------ watchdog
    def _touch(self, label):
        self._last_update_time = time.time()
        if label:
            self._current_label = label

    def start_watchdog(self):
        """Liga o vigia (ver cabecalho da secao) - seguro chamar mais de
        uma vez (para/recria)."""
        self.stop_watchdog()
        self._last_update_time = time.time()
        self._last_watchdog_notice_time = 0.0
        try:
            self._watchdog_timer = _DotNetTimer(
                self._on_watchdog_tick, None, SOLVER_WATCHDOG_INTERVAL_MS, SOLVER_WATCHDOG_INTERVAL_MS
            )
        except Exception:
            self._watchdog_timer = None

    def stop_watchdog(self):
        if self._watchdog_timer is not None:
            try:
                self._watchdog_timer.Dispose()
            except Exception:
                pass
            self._watchdog_timer = None

    def close(self):
        """Chamado no FormClosed da janela dona - impede o timer de tentar
        `Invoke` num controle ja' destruido."""
        self._closed = True
        self.stop_watchdog()

    def _on_watchdog_tick(self, _state):
        # Roda numa thread do ThreadPool (ver cabecalho da secao) - NUNCA
        # pode deixar uma excecao escapar (derrubaria a thread do timer em
        # silencio) nem tocar direto num controle WinForms (so' via
        # BeginInvoke, que agenda para a thread de UI).
        if self._closed:
            return
        try:
            now = time.time()
            elapsed = now - self._last_update_time
            if elapsed < SOLVER_SLOW_WARNING_SECONDS:
                return
            if (now - self._last_watchdog_notice_time) < SOLVER_SLOW_WARNING_SECONDS:
                return  # ja' avisou recentemente sobre ESTA mesma demora
            self._last_watchdog_notice_time = now
            label = self._current_label or "operacao atual"
            message = (
                "Ainda processando ({:.0f}s sem atualizacao) - elemento atual: {}".format(
                    elapsed, label
                )
            )

            def _flush():
                if not self._closed:
                    self.log(message)

            self._log_box.BeginInvoke(Action(_flush))
        except Exception:
            pass


# _dispatch_progress_event ja' foi importada de core/engine/progress.py
# (com fallback inline) perto do topo do arquivo, logo apos
# MIN_WALL_THICKNESS_FT/MAX_WALL_THICKNESS_FT - nao redefinir aqui.


# ==========================================
# JANELA DE CONFIGURACAO (uma tela para tudo o que o script pergunta)
#
# ANTES: o script fazia CINCO caixas de dialogo do pyRevit em sequencia
# (Layer -> Nivel -> Altura -> portas/janelas -> espessuras), cada uma
# modal e sem volta: errar o Layer no primeiro passo so' era descoberto no
# fim, e a unica saida era cancelar e recomecar do zero, incluindo a
# selecao do CAD. Nenhuma delas mostrava o efeito da escolha (quantas
# linhas tem aquele Layer? que espessuras existem la' dentro?).
#
# AGORA: uma janela unica, com os passos numerados, mostrando ao lado de
# cada Layer quantas linhas ele tem e, para o Layer selecionado, quais
# espessuras foram medidas no proprio desenho e quantos pares de linhas
# sustentam cada uma. Trocar de Layer recalcula as espessuras na hora. O
# botao Executar so' habilita quando a configuracao esta' completa, e o
# rodape diz exatamente o que falta - em vez de deixar o usuario descobrir
# no meio da execucao.
# ==========================================

# Teto de linhas usadas na VARREDURA DE ESPESSURAS de um Layer (so' na
# sugestao da interface - a deteccao de verdade em find_wall_pairs continua
# usando todas). A varredura e' O(n^2) e roda a cada troca de Layer; sem
# teto, um Layer com milhares de linhas congelaria a janela por segundos.
SETUP_THICKNESS_SCAN_MAX_LINES = 900


class _SetupForm(Form):
    """Configuracao completa da execucao: Layer, espessuras, Nivel, altura
    e como identificar portas/janelas. MODAL de proposito - nada existe no
    modelo ainda, nao ha' o que conferir no Revit enquanto se decide."""

    def __init__(self, lines_by_layer, level_names, defaults=None):
        # OBRIGATORIO no engine CPython (pythonnet) - ver Script.py: ao
        # contrario do IronPython classico, subclassar um tipo .NET (Form)
        # em CPython/pythonnet NAO inicializa o objeto CLR sozinho so' por
        # heranca. Sem chamar o construtor base EXPLICITAMENTE, aqui, ANTES
        # de qualquer propriedade .NET ser lida/escrita (self.Text, etc.),
        # o objeto CLR subjacente fica com os campos internos nulos e
        # QUALQUER acesso a uma propriedade real do WinForms (nao um
        # atributo Python comum) lanca NullReferenceException - bug real
        # medido em producao (2026-08-27): "at System.Windows.Forms.
        # Form.get_Text() / Control.set_Text(...)" na PRIMEIRA linha do
        # metodo, `self.Text = ...`. As mesmas 3 classes (_SetupForm/
        # _WallReviewForm/_PostCreationForm) tinham esse bug.
        Form.__init__(self)
        defaults = defaults or {}
        self._lines_by_layer = lines_by_layer
        self._thickness_cache = {}
        self._layer_fallback = None
        self._thickness_values_cm = []
        self.result = None

        self.Text = "Modulacao Automatica - Configuracao"
        self.Width = 1010
        self.Height = 680
        self.MinimumSize = Size(880, 600)
        self.StartPosition = FORM_START_POSITION_CENTER_SCREEN
        self.BackColor = UI_BG

        body = Panel()
        body.Dock = DockStyle.Fill
        body.BackColor = UI_BG
        body.Padding = Padding(14, 12, 14, 6)

        # ---- coluna direita: espessuras + nivel + altura + aberturas ----
        right = Panel()
        right.Dock = DockStyle.Fill
        right.BackColor = UI_PANEL
        right.Padding = Padding(16, 12, 16, 12)

        self._openings_auto = RadioButton()
        self._openings_auto.Text = ("Detectar automaticamente (varre o projeto pelos "
                                    "parametros de abertura)")
        self._openings_auto.Dock = DockStyle.Top
        self._openings_auto.Height = 24
        self._openings_auto.Font = _ui_font(9.0)
        self._openings_auto.ForeColor = UI_TEXT

        self._openings_pick = RadioButton()
        self._openings_pick.Text = "Vou selecionar as portas/janelas no modelo (recomendado)"
        self._openings_pick.Dock = DockStyle.Top
        self._openings_pick.Height = 24
        self._openings_pick.Font = _ui_font(9.0)
        self._openings_pick.ForeColor = UI_TEXT
        self._openings_pick.Checked = defaults.get("openings_mode", "pick") != "auto"
        self._openings_auto.Checked = not self._openings_pick.Checked

        self._height_box = TextBox()
        self._height_box.Dock = DockStyle.Top
        self._height_box.Height = 26
        self._height_box.Font = _ui_font(10.0)
        self._height_box.Text = str(defaults.get("height_m", "2.80"))
        self._height_box.TextChanged += self._on_changed

        self._level_combo = ComboBox()
        self._level_combo.Dock = DockStyle.Top
        self._level_combo.Height = 26
        self._level_combo.Font = _ui_font(10.0)
        self._level_combo.DropDownStyle = ComboBoxStyle.DropDownList
        for name in level_names:
            self._level_combo.Items.Add(name)
        remembered_level = defaults.get("level")
        if remembered_level in level_names:
            self._level_combo.SelectedIndex = list(level_names).index(remembered_level)
        elif level_names:
            self._level_combo.SelectedIndex = 0
        self._level_combo.SelectedIndexChanged += self._on_changed

        self._extra_box = TextBox()
        self._extra_box.Dock = DockStyle.Top
        self._extra_box.Height = 26
        self._extra_box.Font = _ui_font(10.0)
        self._extra_box.Text = defaults.get("extra_thicknesses", "")
        self._extra_box.TextChanged += self._on_changed

        self._thickness_list = CheckedListBox()
        self._thickness_list.Dock = DockStyle.Top
        self._thickness_list.Height = 132
        self._thickness_list.Font = _ui_font(9.5)
        self._thickness_list.CheckOnClick = True
        self._thickness_list.BorderStyle = getattr(BorderStyle, "None")
        self._thickness_list.BackColor = UI_SOFT
        self._thickness_list.ItemCheck += self._on_item_check

        # ordem de insercao = de baixo para cima (Dock.Top empilha ao
        # contrario da ordem em que os controles entram na colecao)
        right.Controls.Add(self._openings_auto)
        right.Controls.Add(self._openings_pick)
        right.Controls.Add(_build_section_label(
            "5. Portas e janelas",
            "Sao elas que dizem onde a parede continua (verga/peitoril) em vez de terminar."
        ))
        right.Controls.Add(self._height_box)
        right.Controls.Add(_build_section_label(
            "4. Altura da parede (m)", "Altura desconectada, a partir do nivel escolhido."
        ))
        right.Controls.Add(self._level_combo)
        right.Controls.Add(_build_section_label("3. Nivel de insercao"))
        right.Controls.Add(self._extra_box)
        right.Controls.Add(_build_section_label(
            "Outras espessuras (cm, separadas por ;)", "Ex.: 15;20 - opcional."
        ))
        right.Controls.Add(self._thickness_list)
        right.Controls.Add(_build_section_label(
            "2. Espessuras a modelar",
            "Medidas no proprio Layer selecionado, com quantos pares de linhas sustentam cada uma."
        ))

        # ---- coluna esquerda: layers ----
        left = Panel()
        left.Dock = DockStyle.Left
        left.Width = 400
        left.BackColor = UI_PANEL
        left.Padding = Padding(16, 12, 16, 12)

        self._layer_grid = _styled_listview([("Layer", 250), ("Linhas", 70)])
        self._layer_grid.MultiSelect = False
        self._layer_grid.HideSelection = False
        ordered_layers = sorted(
            lines_by_layer.keys(), key=lambda name: (-len(lines_by_layer[name]), name)
        )
        for name in ordered_layers:
            row = ListViewItem(name)
            row.SubItems.Add(str(len(lines_by_layer[name])))
            self._layer_grid.Items.Add(row)
        self._layer_grid.SelectedIndexChanged += self._on_layer_changed

        left.Controls.Add(self._layer_grid)
        left.Controls.Add(_build_section_label(
            "1. Layer das paredes",
            "Ordenado por quantidade de linhas - o Layer de parede costuma ser o maior."
        ))

        gap = Panel()
        gap.Dock = DockStyle.Left
        gap.Width = 12
        gap.BackColor = UI_BG

        body.Controls.Add(right)
        body.Controls.Add(gap)
        body.Controls.Add(left)

        # ---- rodape ----
        footer = Panel()
        footer.Dock = DockStyle.Bottom
        footer.Height = 64
        footer.BackColor = UI_PANEL
        footer.Padding = Padding(16, 13, 16, 13)

        self._run_button = Button()
        self._run_button.Text = "Executar"
        self._run_button.Dock = DockStyle.Right
        self._run_button.Width = 170
        _style_primary_button(self._run_button)
        self._run_button.Click += self._on_run

        spacer = Panel()
        spacer.Dock = DockStyle.Right
        spacer.Width = 10
        spacer.BackColor = UI_PANEL

        cancel_button = Button()
        cancel_button.Text = "Cancelar"
        cancel_button.Dock = DockStyle.Right
        cancel_button.Width = 120
        _style_secondary_button(cancel_button)
        cancel_button.Click += self._on_cancel

        self._status = Label()
        self._status.Dock = DockStyle.Fill
        self._status.Font = _ui_font(9.0)
        self._status.ForeColor = UI_MUTED
        self._status.Text = ""

        footer.Controls.Add(self._status)
        footer.Controls.Add(cancel_button)
        footer.Controls.Add(spacer)
        footer.Controls.Add(self._run_button)

        self.Controls.Add(body)
        self.Controls.Add(footer)
        self.Controls.Add(_build_header(
            "Modulacao Automatica de Paredes",
            "Uma tela para toda a configuracao. Nada e' criado no modelo ate' voce clicar em Executar."
        ))

        remembered_layer = defaults.get("layer")
        target_row = 0
        for index, name in enumerate(ordered_layers):
            if name == remembered_layer:
                target_row = index
                break
        self._layer_fallback = ordered_layers[target_row] if ordered_layers else None
        if self._layer_grid.Items.Count:
            self._layer_grid.Items[target_row].Selected = True
        self._reload_thicknesses(defaults.get("thicknesses_cm") or [])
        self._validate()

    # ------------------------------------------------------------ estado
    @property
    def _selected_layer(self):
        """Layer escolhido. Le a selecao do controle, mas guarda o ultimo
        valor conhecido: um ListView pode nao reportar selecao antes de a
        janela ser efetivamente exibida (o handle nativo ainda nao existe),
        e a janela ja' precisa saber o Layer inicial para montar a lista de
        espessuras."""
        for item in self._layer_grid.SelectedItems:
            return item.Text
        return self._layer_fallback

    def _scan_layer(self, layer_name):
        """Espessuras candidatas do Layer, em cache (a varredura e' O(n^2) e
        seria refeita a cada clique sem isto)."""
        if layer_name not in self._thickness_cache:
            lines = self._lines_by_layer.get(layer_name) or []
            self._thickness_cache[layer_name] = scan_candidate_thicknesses_cm(
                lines[:SETUP_THICKNESS_SCAN_MAX_LINES]
            )
        return self._thickness_cache[layer_name]

    def _reload_thicknesses(self, preselected_cm=None):
        layer_name = self._selected_layer
        counts = self._scan_layer(layer_name) if layer_name else {}
        preselected = set(round(float(v), 1) for v in (preselected_cm or []))
        self._thickness_list.Items.Clear()
        self._thickness_values_cm = []
        for cm in sorted(counts.keys(), key=lambda c: (-counts[c], c)):
            occurrences = counts[cm]
            self._thickness_list.Items.Add("{} cm    -    {} par{} de linhas".format(
                ("%g" % cm), occurrences, "" if occurrences == 1 else "es"
            ))
            self._thickness_values_cm.append(cm)
        if not self._thickness_values_cm:
            self._thickness_list.Items.Add(
                "Nenhuma espessura de parede detectada neste Layer - use o campo abaixo."
            )
        else:
            for index, cm in enumerate(self._thickness_values_cm):
                if round(cm, 1) in preselected:
                    self._thickness_list.SetItemChecked(index, True)

    def _checked_thicknesses_cm(self, pending=None):
        """Espessuras marcadas na lista + as digitadas no campo livre.
        `pending` (indice, marcado) aplica a mudanca que o evento ItemCheck
        ainda nao gravou no controle."""
        chosen = set()
        for index, cm in enumerate(self._thickness_values_cm):
            checked = self._thickness_list.GetItemChecked(index)
            if pending is not None and pending[0] == index:
                checked = pending[1]
            if checked:
                chosen.add(cm)
        for token in (self._extra_box.Text or "").replace(",", ".").split(";"):
            token = token.strip()
            if not token:
                continue
            try:
                value = float(token)
            except ValueError:
                return None, "Espessura invalida no campo livre: '{}'.".format(token)
            if value <= 0:
                return None, "Espessura invalida no campo livre: '{}'.".format(token)
            chosen.add(value)
        return sorted(chosen), None

    def _parsed_height_m(self):
        raw = (self._height_box.Text or "").strip().replace(",", ".")
        try:
            value = float(raw)
        except ValueError:
            return None
        return value if value > 0 else None

    def _validate(self, pending_thickness=None):
        problems = []
        if not self._selected_layer:
            problems.append("escolha o Layer das paredes")
        thicknesses, error = self._checked_thicknesses_cm(pending_thickness)
        if error:
            problems.append(error)
        elif not thicknesses:
            problems.append("marque ao menos uma espessura")
        if self._level_combo.SelectedItem is None:
            problems.append("escolha o Nivel")
        if self._parsed_height_m() is None:
            problems.append("informe uma altura valida em metros (ex.: 2.80)")

        if problems:
            self._status.ForeColor = UI_WARN
            self._status.Text = "Falta: " + "; ".join(problems) + "."
            _set_button_enabled(self._run_button, False)
            return False

        self._status.ForeColor = UI_MUTED
        self._status.Text = (
            "Layer '{}' | {} espessura(s): {} | Nivel '{}' | altura {:.2f}m | "
            "portas/janelas: {}".format(
                self._selected_layer, len(thicknesses),
                ", ".join("%gcm" % t for t in thicknesses),
                self._level_combo.SelectedItem, self._parsed_height_m(),
                "selecionar no modelo" if self._openings_pick.Checked else "deteccao automatica"
            )
        )
        _set_button_enabled(self._run_button, True)
        return True

    # ------------------------------------------------------------ eventos
    def _on_layer_changed(self, sender, args):
        for item in self._layer_grid.SelectedItems:
            self._layer_fallback = item.Text
            break
        self._reload_thicknesses()
        self._validate()

    def _on_item_check(self, sender, args):
        # ItemCheck dispara ANTES de o estado mudar no controle - por isso o
        # indice/valor novo entram como `pending` na validacao.
        try:
            index = args.Index
            checked = str(args.NewValue) != "Unchecked"
        except Exception:
            index, checked = None, None
        self._validate((index, checked) if index is not None else None)

    def _on_changed(self, sender, args):
        self._validate()

    def _on_run(self, sender, args):
        if not self._validate():
            return
        thicknesses_cm, _error = self._checked_thicknesses_cm()
        self.result = {
            "layer": self._selected_layer,
            "thicknesses_cm": thicknesses_cm,
            "extra_thicknesses": (self._extra_box.Text or "").strip(),
            "level": self._level_combo.SelectedItem,
            "height_m": self._parsed_height_m(),
            "openings_mode": "pick" if self._openings_pick.Checked else "auto",
        }
        self.Close()

    def _on_cancel(self, sender, args):
        self.result = None
        self.Close()


def _setup_defaults_path():
    return os.path.join(tempfile.gettempdir(), "modulacao_automatica_setup.json")


def _recall_setup_defaults():
    """Le as escolhas da ultima execucao (Layer, espessuras, Nivel, altura,
    modo das aberturas) para ja' vir preenchido - rodar o script duas vezes
    seguidas no mesmo projeto e' o caso normal, nao a excecao. NUNCA lanca:
    sem arquivo, ou com arquivo corrompido, a janela abre em branco."""
    try:
        import json
        with open(_setup_defaults_path(), "r") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _remember_setup_defaults(setup):
    """Guarda as escolhas da execucao atual (ver _recall_setup_defaults).
    NUNCA lanca - falhar em lembrar nao pode derrubar a automacao."""
    try:
        import json
        with open(_setup_defaults_path(), "w") as handle:
            json.dump({
                "layer": setup.get("layer"),
                "thicknesses_cm": setup.get("thicknesses_cm"),
                "extra_thicknesses": setup.get("extra_thicknesses"),
                "level": setup.get("level"),
                "height_m": setup.get("height_m"),
                "openings_mode": setup.get("openings_mode"),
            }, handle)
    except Exception:
        pass


def _format_exception_detail(ex):
    """Detalhe COMPLETO de uma excecao para os logs de fallback WinForms
    (ver ask_setup/_show_wall_review_window/_run_stage2_modulation abaixo) -
    ate' 2026-08-26 esses logs mostravam so' `traceback.format_exc().
    splitlines()[-1]` (a ULTIMA linha do traceback), que para uma excecao
    .NET envolvida pelo pythonnet (TargetInvocationException etc.) e' so'
    a ultima linha do STACK TRACE .NET embutido na mensagem (ex.:
    "at System.Reflection.MethodBaseInvoker.InvokeWithOneArg(...)") -
    generico o suficiente para NUNCA apontar qual linha do NOSSO codigo
    falhou, deixando o bug impossivel de localizar so' com o que o usuario
    consegue reportar. Isto devolve o traceback Python INTEIRO (todas as
    linhas, nao so' a ultima) MAIS a cadeia de InnerException do .NET, se
    o pythonnet expuser esse atributo no objeto (acontece quando a
    excecao real veio de dentro do CLR) - a combinacao das duas e' o que
    da' um local de verdade para corrigir."""
    parts = [traceback.format_exc()]
    inner = getattr(ex, "InnerException", None)
    depth = 0
    while inner is not None and depth < 5:
        try:
            parts.append("InnerException[{}]: {}: {}".format(
                depth, type(inner).__name__, inner
            ))
            stack_trace = getattr(inner, "StackTrace", None)
            if stack_trace:
                parts.append(str(stack_trace))
        except Exception:
            break
        inner = getattr(inner, "InnerException", None)
        depth += 1
    return "\n".join(parts)


def ask_setup(lines_by_layer, level_names):
    """Abre a janela de configuracao unica (WinForms, `_SetupForm`) e
    devolve o dict de configuracao, ou None se o usuario cancelar. Qualquer
    falha ao montar essa janela (uma versao de Revit/pyRevit em que algum
    controle nao exista, por exemplo) cai automaticamente para a sequencia
    antiga de caixas do pyRevit em vez de derrubar o script - ver
    _ask_setup_legacy."""
    try:
        window = _SetupForm(lines_by_layer, level_names, _recall_setup_defaults())
        window.ShowDialog()
        if window.result:
            _remember_setup_defaults(window.result)
        return window.result
    except Exception as ex:
        detail = _format_exception_detail(ex)
        script.get_output().print_md(
            "- **Tela WinForms de configuracao tambem falhou** ({0}); "
            "usando a sequencia antiga de caixas (Layer -> Nivel -> altura -> "
            "aberturas), sem espessuras/preview.\n\n```\n{1}\n```".format(
                traceback.format_exc().splitlines()[-1], detail
            )
        )
        return _ask_setup_legacy(lines_by_layer, level_names)


def _ask_setup_legacy(lines_by_layer, level_names):
    """Sequencia antiga de caixas do pyRevit (Layer -> Nivel -> altura ->
    portas/janelas), usada so' como plano B de ask_setup. As espessuras
    ficam de fora aqui: elas continuam sendo perguntadas por
    ask_wall_thicknesses, ja' com as linhas reconstruidas."""
    selected_layer = forms.SelectFromList.show(
        sorted(lines_by_layer.keys()), title="Selecione o Layer das Paredes", multiselect=False
    )
    if not selected_layer:
        return None
    selected_level_name = forms.SelectFromList.show(
        sorted(level_names), title="Selecione o Nivel de Insercao", multiselect=False
    )
    if not selected_level_name:
        return None
    height_text = forms.ask_for_string(
        default="2.80", prompt="Informe a altura da parede em metros:", title="Altura Desconectada"
    )
    if not height_text:
        return None
    try:
        height_m = float(height_text.strip().replace(",", "."))
        if height_m <= 0:
            raise ValueError
    except ValueError:
        forms.alert("Valor de altura invalido. Use um numero positivo, ex: 2.80")
        return None
    wants_manual = forms.alert(
        "Como o script deve identificar as PORTAS e JANELAS?\n\n"
        "Sim = vou SELECIONAR os elementos no modelo (recomendado)\n"
        "Nao = detectar automaticamente todas as familias que tenham os "
        "parametros {}/{}/{}".format(
            OPENING_WIDTH_PARAM, OPENING_HEIGHT_PARAM, OPENING_SILL_PARAM
        ),
        title="Selecionar portas/janelas (Mobiliario)", yes=True, no=True
    )
    return {
        "layer": selected_layer,
        "thicknesses_cm": None,  # perguntadas depois, por ask_wall_thicknesses
        "extra_thicknesses": "",
        "level": selected_level_name,
        "height_m": height_m,
        "openings_mode": "pick" if wants_manual else "auto",
    }



# ==========================================
# RELATORIO ESTRUTURADO DA JANELA DE RESULTADO
#
# O log de texto continua sendo a fonte completa (aba "Log completo"). As
# duas funcoes abaixo destilam dele o que precisa ser visto PRIMEIRO: os
# numeros da execucao e as ocorrencias que pedem acao humana, ja'
# classificadas por severidade. Nenhuma informacao nova e' inventada aqui -
# tudo vem das mesmas variaveis que alimentam o log.
# ==========================================

def build_report_highlights(layer_name, detected_count, axes_count, created_count,
                            cad_segments, opening_segments, level_name,
                            all_openings, openings_used, openings_source_note,
                            modulation_results, incompatible_modulation,
                            opening_modulation_results, opening_incompatible_modulation,
                            wall_error_rows, failures):
    """Bloco de texto curto da aba 'Resumo' - o que aconteceu, em ordem de
    importancia, sem os detalhes item a item que ficam no log."""
    lines = [
        "Layer '{}'  ->  {} par(es) de linha reconhecido(s) como parede.".format(
            layer_name, detected_count
        ),
        "",
        "PAREDES",
        "  {} eixo(s) viraram {} elemento(s) Wall no Nivel '{}'".format(
            axes_count, created_count, level_name
        ),
        "  {} trecho(s) cheio(s) do CAD + {} trecho(s) de verga/peitoril".format(
            cad_segments, opening_segments
        ),
    ]
    if failures:
        lines.append("  {} segmento(s) FALHARAM ao ser criados - ver aba Ocorrencias".format(
            len(failures)
        ))

    lines.extend([
        "",
        "PORTAS E JANELAS",
        "  {} abertura(s) consideradas ({})".format(len(all_openings), openings_source_note),
        "  {} associada(s) a uma parede criada".format(openings_used),
        "",
        "MODULACAO DE BLOCOS",
        "  Paredes: {} de {} dentro da regra de comprimento".format(
            len(modulation_results) - len(incompatible_modulation), len(modulation_results)
        ),
        "  Aberturas: {} de {} dentro da regra de largura".format(
            len(opening_modulation_results) - len(opening_incompatible_modulation),
            len(opening_modulation_results)
        ),
        "  As incompativeis estao em AZUL na vista, e o validador ao vivo",
        "  continua ligado: o realce some sozinho quando voce corrige.",
    ])
    if wall_error_rows:
        auto_fixable_count = sum(1 for r in wall_error_rows if r["auto_fixable"])
        lines.extend([
            "",
            "ERROS DE MODULACAO (parede + abertura)",
            "  {} eixo(s) fora da modulacao - {} com correcao automatica "
            "disponivel ('Ajustar Erros'), {} exigem revisao manual."
            .format(len(wall_error_rows), auto_fixable_count,
                    len(wall_error_rows) - auto_fixable_count),
        ])
    return lines


def build_report_issues(failures, ambiguous_lines, modulation_results,
                        opening_incompatible_modulation, unassigned_openings,
                        possible_missed_bonecas, recovery_mode_used,
                        openings_capped_at_top):
    """Lista [(severidade, item, texto)] da aba 'Ocorrencias', da mais
    grave para a mais leve. Severidades: erro (algo NAO foi feito),
    atencao (feito, mas precisa de conferencia humana), info.

    `modulation_results` e' a lista COMPLETA (evaluate_wall_modulation,
    TODAS as paredes, nao so' as incompativeis) - precisa ser a lista
    cheia, nao so' as que falharam `compatible`, porque uma parede com
    residuo pequeno (nao `is_clean_cm`) entra na categoria VERMELHO mesmo
    quando `compatible=True` (ver FASE 2 do plano em
    C:\\Users\\CIVIX\\.claude\\plans\\quiet-painting-petal.md - mesma
    prioridade de _refresh_wall_modulation_override/main())."""
    issues = []

    for message in failures[:30]:
        issues.append((
            "erro", "Falha ao criar/ajustar",
            "{}".format(message)
        ))
    if len(failures) > 30:
        issues.append((
            "erro", "Falha ao criar/ajustar",
            "... e mais {} falha(s) - lista completa no log.".format(len(failures) - 30)
        ))

    if recovery_mode_used:
        issues.append((
            "atencao", "Modo de recuperacao manual",
            "Nenhum par de linhas bateu com as espessuras escolhidas: cada linha do "
            "Layer virou o eixo de uma parede. Confira se e' isso mesmo."
        ))

    for text in ambiguous_lines:
        issues.append(("atencao", "Geometria a conferir", text.lstrip("- ").strip()))

    # Mesma prioridade de main()/_refresh_wall_modulation_override: VERMELHO
    # (`not is_clean_cm`) tem precedencia mesmo sobre uma parede
    # `compatible=True` (residuo pequeno que a tolerancia LARGA da
    # aritmetica de modulacao deixaria passar em silencio).
    broken_length_issues = [r for r in modulation_results if not r["is_clean_cm"]]
    non_modular_issues = [
        r for r in modulation_results if r["is_clean_cm"] and not r["compatible"]
    ]
    if broken_length_issues:
        issues.append((
            "erro", "Comprimento quebrado",
            "{} parede(s) marcadas em VERMELHO na vista - o comprimento nao cai "
            "dentro da tolerancia de nenhum numero inteiro de cm (residuo/"
            "imprecisao geometrica) - corrija ANTES de tentar modular. "
            "Comprimento sugerido para cada uma no log.".format(len(broken_length_issues))
        ))
    if non_modular_issues:
        issues.append((
            "atencao", "Comprimento fora da modulacao",
            "{} parede(s) marcadas em AZUL na vista - o comprimento e' um numero "
            "inteiro de cm, mas nenhuma combinacao de blocos+juntas fecha nele "
            "(pilaretes junto de abertura nao entram nesta checagem - ver "
            "'Analisar Paredes'/'Ajustar Erros' na janela unica). Sugestao de "
            "valor valido para cada uma no log.".format(len(non_modular_issues))
        ))
    if opening_incompatible_modulation:
        issues.append((
            "atencao", "Largura de vao fora da modulacao",
            "{} abertura(s) marcadas em AZUL na vista - a largura nao termina em "
            "1, 6 ou 9cm.".format(len(opening_incompatible_modulation))
        ))
    if unassigned_openings:
        issues.append((
            "atencao", "Abertura sem parede",
            "{} abertura(s) nao ficaram perto de nenhuma parede criada e por isso nao "
            "geraram verga/peitoril - motivo de cada uma no log.".format(len(unassigned_openings))
        ))
    if openings_capped_at_top:
        issues.append((
            "atencao", "Sem parede acima da verga",
            "{} abertura(s) tem altura lida >= ao pe-direito, entao nao sobra trecho de "
            "parede acima delas - confira Altura_abertura/Peitoril dessas familias."
            .format(openings_capped_at_top)
        ))
    large_misses = [pair for pair in (possible_missed_bonecas or []) if pair[1] >= 100.0]
    if large_misses:
        thicknesses = sorted(set(d for d, _o in large_misses))
        issues.append((
            "atencao", "Espessura possivelmente esquecida",
            "{} par(es) de linhas com mais de 1m de sobreposicao ficaram sem parede: "
            "parecem paredes inteiras de {}cm, espessura(s) que nao foram selecionadas "
            "nesta execucao.".format(
                len(large_misses), ", ".join("%g" % t for t in thicknesses)
            )
        ))
    elif possible_missed_bonecas:
        issues.append((
            "info", "Bonecas possivelmente ignoradas",
            "{} par(es) de linhas curtas sem parede criada, em espessura fora das "
            "escolhidas - detalhes no log.".format(len(possible_missed_bonecas))
        ))
    return issues


# ==========================================
# JANELA UNICA DE MODULACAO (substitui as 3 janelas antigas - ajuste previo
# de aberturas, resultado em abas, assistente de blocos por etapas - por
# UMA SO', sem sub-abas, pedido explicito do usuario) + EXCLUSAO DAS
# PAREDES DE REFERENCIA
#
# Trilha visual (o estado sempre visivel na janela, de cima para baixo):
#   Analisar Paredes -> Erros encontrados -> Ajustar Erros ->
#   Modulacao concluida -> Lancar Blocos -> Finalizar/Deletar Paredes
#
# Decisoes de fluxo combinadas com o usuario:
#   - As paredes REAIS ja' foram criadas quando esta janela abre (main() ja
#     rodou a Transacao de criacao) - "Analisar Paredes" roda ANTES da
#     janela existir (main() chama analyze_created_walls_for_errors logo
#     apos criar, ver ETAPA 3B mais acima) e chega pronto no handler.
#   - "Ajustar Erros" roda de uma vez para TODOS os eixos auto-corrigiveis
#     (nao um por um) - ver fix_all_wall_modulation_errors (ETAPA 3B).
#   - "Lancar Blocos" fica liberado assim que "Ajustar Erros" rodou (ou
#     direto, se nao havia nada auto-corrigivel para ajustar), mesmo que
#     sobrem eixos em revisao manual - mesmo principio de seguranca do
#     NON_MODULAR_WALL do solver de blocos (nunca bloqueia o fluxo inteiro
#     por causa de um trecho que nao fecha, so' reporta).
#   - "Finalizar/Deletar Paredes" continua exigindo 1 confirmacao explicita
#     (MessageBox) antes de excluir - unica pausa manual pedida pelo
#     usuario no fluxo; todo o resto roda encadeado sem parar para
#     perguntar.
#   - Clicar numa linha da lista de erros da' zoom/selecao na(s) parede(s)
#     daquele eixo na vista ativa do Revit (acao "zoom" do handler abaixo -
#     primeira vez que este script usa uidoc.ShowElements/Selection.
#     SetElementIds).
#
# Toda escrita/leitura de elementos VIVOS do Revit passa pelo MESMO
# ExternalEvent (_PostCreationEventHandler) - nunca direto no Click de um
# botao (a janela e' MODELESS, ver secao JANELAS MODELESS acima).
# ==========================================

# Paleta fixa de cores do modo debug "colorir por codigo" - uma cor por
# peca, usando o alias _REVIT_DB_COLOR (ver topo do arquivo) para garantir
# que e' Autodesk.Revit.DB.Color, nao System.Drawing.Color (que passa a
# sombrear o nome solto `Color` a partir do import da secao JANELAS
# MODELESS, mais acima).
DEBUG_BLOCK_CODE_COLORS = {
    "B39": _REVIT_DB_COLOR(230, 126, 34),   # laranja - peca inteira, a mais comum
    "B34": _REVIT_DB_COLOR(39, 174, 96),    # verde - amarracao L
    "B54": _REVIT_DB_COLOR(142, 68, 173),   # roxo - amarracao T/X
    "B19": _REVIT_DB_COLOR(41, 128, 185),   # azul - meio bloco
    "C09": _REVIT_DB_COLOR(127, 140, 141),  # cinza - compensador
    "C04": _REVIT_DB_COLOR(120, 80, 40),    # marrom - pastilha
}

# Folga (metros) ao redor da bounding box da(s) parede(s) com erro ao dar
# zoom nelas (ver _PostCreationEventHandler._execute_zoom) - generosa o
# bastante pra' enquadrar tambem a abertura e os trechos vizinhos
# envolvidos na modulacao, pedido explicito do usuario ("o zoom deve
# enquadrar... permitindo visualizar tambem as aberturas e os trechos
# adjacentes"), nao so' a propria parede.
ZOOM_TO_ERROR_MARGIN_M = 2.5
ZOOM_TO_ERROR_MARGIN_FT = ZOOM_TO_ERROR_MARGIN_M * FEET_PER_METER


def _format_block_solve_report(result, catalog):
    """Texto do relatorio do passo "Lancar Blocos" (solver) - contagem por
    peca (com % de B39, o indicador de eficiencia do preenchimento comum
    pedido no plano), encontros L/T/X resolvidos x falhos, jambs com
    excecao, paredes nao-modulares e colisoes residuais. Usado tanto na
    janela quanto (se quiser) num log salvo - por isso devolve so' texto
    simples, sem depender de nenhum widget."""
    candidates = result["candidates"]
    lines = []
    lines.append("=== Solver de blocos ===")
    lines.append("Total de candidatos (1 par de fiadas A/B): {}".format(len(candidates)))

    # Resumo do processamento PAREDE A PAREDE (ordem geometrica obrigatoria
    # + validacao final de cada uma antes de passar para a proxima).
    per_wall = result.get("per_wall") or []
    if per_wall:
        horizontals = sum(1 for w in per_wall if w["orientation"] == "H")
        verticals = sum(1 for w in per_wall if w["orientation"] == "V")
        diagonals = len(per_wall) - horizontals - verticals
        reproved = [w for w in per_wall if not w["validation"]["ok"]]
        adjusted = [w for w in per_wall if w["adjusted"]]
        lines.append(
            "Processadas uma a uma, na ordem geometrica: {} horizontal(is) (cima->baixo, "
            "esquerda->direita), depois {} vertical(is) (esquerda->direita, baixo->cima)"
            "{}.".format(horizontals, verticals,
                         ", mais {} diagonal(is)".format(diagonals) if diagonals else "")
        )
        lines.append("Paredes que precisaram de ajuste para fechar: {}".format(len(adjusted)))
        lines.append("Paredes reprovadas na validacao final: {}".format(len(reproved)))
        for entry in reproved[:15]:
            lines.append("  - parede {}: {}".format(
                entry["wall_idx"], "; ".join(entry["validation"]["problems"])
            ))
        if len(reproved) > 15:
            lines.append("  - ... e mais {}.".format(len(reproved) - 15))

    by_code = {}
    for c in candidates:
        by_code.setdefault(c["logical_code"], 0)
        by_code[c["logical_code"]] += 1
    total = len(candidates) or 1
    lines.append("Contagem por peca:")
    for code in sorted(by_code.keys()):
        count = by_code[code]
        lines.append("  - {}: {} ({:.1f}%)".format(code, count, 100.0 * count / total))
    b39_pct = 100.0 * by_code.get("B39", 0) / total
    lines.append("  -> B39 (peca inteira) = {:.1f}% do total - quanto maior, mais eficiente o preenchimento.".format(b39_pct))

    reasons = {}
    for c in candidates:
        reasons.setdefault(c.get("placement_reason", "?"), 0)
        reasons[c.get("placement_reason", "?")] += 1
    lines.append("Por motivo de posicionamento:")
    for reason in sorted(reasons.keys()):
        lines.append("  - {}: {}".format(reason, reasons[reason]))

    failures = result["intersection_failures"]
    lines.append("Encontros L/T/X que NAO fecharam: {}".format(len(failures)))
    for node_index, reason in failures[:15]:
        lines.append("  - no' {}: {}".format(node_index, reason))
    if len(failures) > 15:
        lines.append("  - ... e mais {}.".format(len(failures) - 15))

    jamb_exceptions = result["jamb_exceptions"]
    lines.append("Jambs de abertura com excecao (nao alinharam limpo): {}".format(len(jamb_exceptions)))

    non_modular = result["non_modular"]
    lines.append("Trechos NAO-MODULARES (nenhuma combinacao de blocos fecha): {}".format(len(non_modular)))
    for entry in non_modular[:15]:
        lines.append(
            "  - parede {} / fiada {} / trecho {}: {:.1f}cm (mais proximo que fecha "
            "em blocos: {}cm)".format(
                entry["wall_idx"], entry["course"], entry["segment_index"],
                entry["current_length_cm"], entry["lower_valid_cm"]
            )
        )
    if len(non_modular) > 15:
        lines.append("  - ... e mais {}.".format(len(non_modular) - 15))

    collisions = result["collisions"]
    lines.append("Colisoes residuais entre blocos de fiadas diferentes: {}".format(len(collisions)))
    if collisions:
        lines.append("  -> NAO bloqueia mais a criacao (pedido explicito do usuario, 2026-08-24): os "
                      "blocos sao criados mesmo assim, e as pecas colidentes ficam marcadas em VERMELHO "
                      "solido na vista para revisao manual. Cada linha abaixo e' UM par de "
                      "pecas que se sobrepoem - a coordenada (X, Y)cm e' a ORIGEM de cada peca, no "
                      "mesmo sistema de coordenadas do Revit (cole em Gerenciar > Inspecionar > "
                      "Coordenadas de Ponto, ou compare com o CAD, para localizar):")
        for i, j in collisions[:15]:
            a, b = candidates[i], candidates[j]
            lines.append("  - {}".format(describe_block_candidate_oneline(a)))
            lines.append("    x {}".format(describe_block_candidate_oneline(b)))
        if len(collisions) > 15:
            lines.append("  - ... e mais {} par(es).".format(len(collisions) - 15))
        # Agrupamento por parede: normalmente a MESMA parede (ou o encontro
        # entre duas) concentra varias colisoes - saber ISSO primeiro (sem
        # precisar ler par por par) ajuda a decidir por onde comecar.
        by_wall = {}
        for i, j in collisions:
            for c in (candidates[i], candidates[j]):
                key = c.get("wall_idx")
                by_wall[key] = by_wall.get(key, 0) + 1
        if len(by_wall) > 1:
            ranked = sorted(by_wall.items(), key=lambda kv: -kv[1])
            lines.append("  Concentracao por parede (contagem de PECAS envolvidas, nao de pares): " +
                         ", ".join("parede {}: {}".format(w, n) for w, n in ranked[:10]))

    # Validacao MULTI-FIADA (secao "ETAPA 4C" - ve' a parede inteira de
    # uma vez, comparando fiada com fiada, nao mais fiada a fiada isolada).
    wall_bond_audits = result.get("wall_bond_audits") or {}
    reproved_bond = {wi: audit for wi, audit in wall_bond_audits.items() if not audit["ok"]}
    lines.append("=== Auditoria de amarracao entre fiadas (validacao 3D) ===")
    lines.append("Paredes auditadas: {} | REPROVADAS por modulacao ruim: {}".format(
        len(wall_bond_audits), len(reproved_bond)
    ))
    if reproved_bond:
        lines.append("  -> NAO bloqueia a criacao (regra revista 2026-08-26, pedido explicito do "
                      "usuario: 'o diagnostico nao pode impedir a geracao dos blocos' - reverte a "
                      "regra #1 absoluta de 2026-08-25): estas paredes RECEBEM bloco normalmente em "
                      "'Lancar Blocos - criar' e as pecas criadas nelas ficam marcadas em VERMELHO na "
                      "vista para revisao manual (ver _execute_create/_bond_reproved_created_instance_ids). "
                      "Junta corrida entre as duas fiadas, faixa vertical de peca especial/compensador ou "
                      "meio bloco perto de amarracao detectados comparando as fiadas entre si, mesmo que "
                      "cada trecho feche aritmeticamente sozinho (o padrao alternado par/impar de junta "
                      "comum entre fiada A e fiada B NAO conta como reprovacao - e' o proprio efeito "
                      "esperado de repetir o mesmo par de fiadas em todo o pe-direito, nao um defeito de "
                      "amarracao - ver comentario em audit_wall_bond_quality).")
        for wall_idx in sorted(reproved_bond.keys())[:15]:
            audit = reproved_bond[wall_idx]
            lines.append("  - parede {}: score {:.0f}".format(wall_idx, audit["penalty"]))
            for problem in audit["problems"][:6]:
                lines.append("      * {}".format(problem))
        if len(reproved_bond) > 15:
            lines.append("  - ... e mais {}.".format(len(reproved_bond) - 15))

    door_violations = result.get("door_void_violations") or []
    lines.append("Violacoes da zona de exclusao (bloco dentro do vao de porta sem peitoril): {}"
                 .format(len(door_violations)))
    if door_violations:
        lines.append("  -> NAO bloqueia mais a criacao (regra revista 2026-08-26, pedido explicito "
                      "do usuario: 'o diagnostico nao pode impedir a geracao dos blocos' - reverte a "
                      "regra absoluta de 2026-08-21): o bloco e' criado mesmo assim e a peca envolvida "
                      "fica marcada em VERMELHO na vista para revisao manual (ver _execute_create).")
        for v in door_violations[:15]:
            lines.append("  - {} invade {:.1f}cm do vao da porta (parede {}, abertura #{})".format(
                describe_block_candidate_oneline(v["candidate"]), v["overlap_cm"],
                v["wall_idx"], v["opening_index"]
            ))
        if len(door_violations) > 15:
            lines.append("  - ... e mais {}.".format(len(door_violations) - 15))

    # REGRA REVISTA 2026-08-26 (pedido explicito do usuario: "o diagnostico
    # nao pode impedir a geracao dos blocos... MODULAR PRIMEIRO ->
    # DIAGNOSTICAR O RESULTADO -> INFORMAR OS ERROS"). Nenhum diagnostico
    # (colisao entre blocos, violacao de vao de porta, reprovacao na
    # auditoria de amarracao entre fiadas) bloqueia mais a criacao dos
    # blocos, nem por parede nem pela planta inteira - todos passam a
    # funcionar como a colisao ja' funcionava desde 2026-08-24: cria-se a
    # peca mesmo assim e ela fica marcada em VERMELHO na vista para revisao
    # manual (ver _execute_create/_bond_reproved_created_instance_ids). Isto
    # reverte as regras absolutas de bloqueio de 2026-08-21 (vao de porta) e
    # 2026-08-25 (auditoria de amarracao). `ready_to_create` e' mantido
    # apenas por compatibilidade com quem chama esta funcao - sempre True.
    ready_to_create = True
    return "\n".join(lines), ready_to_create


# ==========================================
# RELATORIO FINAL CONSOLIDADO (pedido explicito do usuario, 2026-08-25,
# item 4/5): "quantidade de paredes analisadas; quantidade inicialmente
# com erro; quantidade corrigida; quantidade modulada com sucesso;
# quantidade que permaneceu sem solucao; motivo de cada parede que nao
# pode ser resolvida."
#
# Junta as DUAS fontes de problema que o script conhece sobre uma parede -
# nunca foram uma so' fonte de verdade antes disto:
#   - `error_rows` (analyze_created_walls_for_errors/fix_all_wall_
#     modulation_errors, ETAPA 3B): a modulacao ARITMETICA de algum trecho
#     nao fecha (ou so' fechou depois de um ajuste geometrico).
#   - `wall_bond_audits` (audit_all_walls_bond_quality, ETAPA 4C): os
#     trechos fecham aritmeticamente, mas a AMARRACAO entre fiadas (junta
#     corrida, padrao alternado, faixa vertical repetitiva, meio bloco
#     perto de amarracao) reprova - a parede fica sem bloco nenhum (regra
#     #1/#2, ver _execute_create).
# Uma parede so' conta como "modulada com sucesso" quando passa nas DUAS -
# regra #5 do usuario ("nao faz sentido uma parede estar... correta e
# mesmo assim o sistema lancar blocos nela como se ainda estivesse sendo
# tratada como uma parede com erro" - aqui e' o inverso simetrico: nao faz
# sentido contar como "sucesso" uma parede que passou na Etapa 3B mas
# reprovou na 4C, ou vice-versa).
# ==========================================

def build_final_modulation_report(walls_to_create, error_rows, wall_bond_audits=None,
                                  skipped_wall_idxs=None):
    """Consolida o resultado final de TODOS os eixos numa unica estrutura.
    Devolve {"total_analyzed":, "initially_with_error":,
    "corrected_automatically":, "modulated_successfully":,
    "unresolved_count":, "unresolved": [{"wall_idx":, "reasons": [str,...]},...]}
    (`unresolved` ordenado por wall_idx, cada motivo prefixado pela etapa
    de origem)."""
    wall_bond_audits = wall_bond_audits or {}
    skipped_wall_idxs = set(skipped_wall_idxs or [])

    total_analyzed = len(walls_to_create)
    initially_with_error = len(error_rows)
    corrected_automatically = sum(1 for r in error_rows if r.get("resolved"))

    reasons_by_wall = {}
    for r in error_rows:
        wall_idx = r.get("wall_idx")
        if r.get("resolved") or wall_idx is None:
            continue
        reasons_by_wall.setdefault(wall_idx, []).append(
            "modulacao/geometria (Etapa 3B): " + r.get("problem_text", "motivo nao registrado")
        )
    for wall_idx in skipped_wall_idxs:
        audit = wall_bond_audits.get(wall_idx) or {}
        problems = audit.get("problems") or ["reprovada na auditoria de amarracao entre fiadas"]
        for problem in problems:
            reasons_by_wall.setdefault(wall_idx, []).append(
                "amarracao entre fiadas (Etapa 4C): " + problem
            )

    unresolved = [
        {"wall_idx": wi, "reasons": reasons}
        for wi, reasons in sorted(reasons_by_wall.items(), key=lambda kv: kv[0])
    ]
    unresolved_count = len(unresolved)
    modulated_successfully = max(0, total_analyzed - unresolved_count)

    return {
        "total_analyzed": total_analyzed,
        "initially_with_error": initially_with_error,
        "corrected_automatically": corrected_automatically,
        "modulated_successfully": modulated_successfully,
        "unresolved_count": unresolved_count,
        "unresolved": unresolved,
    }


def _format_final_modulation_report(report):
    """Texto do relatorio final consolidado - ver build_final_modulation_
    report. Formato simples, sem depender de widget nenhum (mesmo padrao
    de _format_block_solve_report)."""
    lines = ["=== Relatorio final de modulacao das paredes ==="]
    lines.append("Paredes (eixos) analisadas: {}".format(report["total_analyzed"]))
    lines.append("Inicialmente com erro: {}".format(report["initially_with_error"]))
    lines.append("Corrigidas automaticamente: {}".format(report["corrected_automatically"]))
    lines.append("Moduladas com sucesso (aprovadas em TODAS as regras): {}".format(
        report["modulated_successfully"]
    ))
    lines.append("Permaneceram SEM SOLUCAO: {}".format(report["unresolved_count"]))
    if report["unresolved"]:
        lines.append("Motivo de cada parede sem solucao:")
        for entry in report["unresolved"][:40]:
            lines.append("  - eixo {}:".format(entry["wall_idx"]))
            for reason in entry["reasons"][:6]:
                lines.append("      * {}".format(reason))
            if len(entry["reasons"]) > 6:
                lines.append("      * ... e mais {}.".format(len(entry["reasons"]) - 6))
        if len(report["unresolved"]) > 40:
            lines.append("  - ... e mais {} parede(s).".format(len(report["unresolved"]) - 40))
    return "\n".join(lines)


class _PostCreationEventHandler(IExternalEventHandler):
    """Ponte UNICA entre a API do Revit e as DUAS janelas modeless deste
    script - _WallReviewForm (Etapa 1 -> Etapa 2, ver _show_wall_review_
    window) e _PostCreationForm (janela de resultado, ver
    _show_post_creation_window) - substitui as antigas
    _ApplySuggestionsEventHandler e _BlockWizardEventHandler (ambas
    removidas). Acoes possiveis, despachadas por `self.action`: "analyze"
    (roda analyze_created_walls_for_errors - so' leitura, nenhuma escrita -
    ver _execute_analyze; e' o que o botao "Iniciar Modulacao" de
    _WallReviewForm dispara), "zoom" (selecionar+enquadrar elementos na
    vista ativa), "fix_errors" (ETAPA 3B - corrige os eixos
    auto-corrigiveis), "solve"/"create"/"debug_view" (solver e criacao de
    blocos, identicos aos da antiga _BlockWizardEventHandler) e "delete"
    (exclusao das paredes de referencia).

    PROPOSITADAMENTE UMA UNICA CLASSE implementando IExternalEventHandler
    neste modulo (2026-08-26): uma segunda classe separada
    (_StartModulationEventHandler, so' para a acao "analyze") quebrava a
    criacao de instancia em producao com "TypeError: interface takes
    exactly one argument" (confirmado ao vivo, engine CPython/pyRevitLabs.
    PythonNet) - o proprio pythonnet parece nao suportar bem DUAS classes
    Python distintas implementando a MESMA interface .NET no mesmo modulo
    exec()'d. A acao "analyze" foi incorporada aqui em vez disso.

    2a RECIDIVA do MESMO sintoma (2026-08-26, mais tarde no mesmo dia):
    mesmo com UMA SO' classe implementando IExternalEventHandler no
    modulo, "TypeError: interface takes exactly one argument" voltou a
    acontecer ao vivo, agora bem na PRIMEIRA instanciacao de
    _PostCreationEventHandler apos a criacao das Walls (dentro de
    _show_wall_review_window) - ou seja, a causa-raiz NUNCA foi "duas
    classes distintas", e sim a mesma que ja tinha side documentada (e
    corrigida) em _LiveUpdaterBase logo acima: o loader reexecuta este
    Script.py do zero a CADA clique no botao, redefinindo esta classe no
    MESMO processo/engine CPython (que fica vivo pelo resto da sessao do
    Revit) - sem um `__namespace__` UNICO por execucao, o pythonnet gera o
    tipo CLR desta classe com o mesmo nome/namespace da execucao anterior,
    colidindo com o tipo ja existente e quebrando a chamada ao construtor
    logo na proxima vez que o usuario roda o addin na mesma sessao do
    Revit (por isso o problema nao aparecia no primeiro clique de cada
    teste isolado). Mesma correcao aplicada aqui: __namespace__ com um
    uuid4 novo por exec() - ver o comentario completo em
    _LiveUpdaterBase.__namespace__, acima.

    Dados fixos desta execucao preenchidos UMA VEZ por
    _show_wall_review_window/_show_post_creation_window; action/on_done
    mudam a cada clique/uso."""

    # Ver o comentario extenso acima (2a RECIDIVA) e o comentario irmao em
    # _LiveUpdaterBase.__namespace__: OBRIGATORIO e' PRECISA SER UNICO A
    # CADA EXECUCAO do Script.py, senao o pythonnet reutiliza/colide com o
    # tipo CLR gerado pela execucao anterior desta MESMA classe no mesmo
    # processo do engine CPython.
    __namespace__ = "ModulacaoAutomatica.PostCreationEventHandler." + uuid.uuid4().hex

    def __init__(self):
        self.action = None
        self.on_done = None
        # dados fixos desta execucao
        self.walls_to_create = []
        self.openings_per_wall = []
        self.created_walls_by_axis = {}
        # snapshot leve de geometria dos segmentos (ver wall_segment_geometry
        # em main(), Etapa 1, e _classify_wall_axis_segments) - permite que
        # "Analisar Paredes" rode sem tocar target_doc, inclusive fora da
        # thread principal (ver _execute_analyze).
        self.wall_segment_geometry = {}
        self.all_openings = []
        self.wall_graph_nodes = []
        self.wall_end_to_node = {}
        self.created_wall_ids_all = []
        self.selected_level = None
        self.base_z_abs = 0.0
        self.wall_height_ft = 0.0
        self.catalog = {}
        self.catalog_missing = []
        # estado mutavel, atualizado a cada passo concluido
        self.error_rows = []
        self.pending_zoom_ids = []
        self.solve_result = None
        self.create_result = None
        self.debug_color_by_code = False
        self.debug_course_filter = None  # None (ambas) / "A" / "B"
        # so' usados pela acao "analyze" (ver _execute_analyze) - o
        # RESULTADO dela e' escrito em self.error_rows, o mesmo atributo
        # que "fix_errors" ja' le/atualiza.
        self.modulation_results = []
        self.opening_incompatible_modulation = []
        self.progress_cb = None
        # granularidade parede-a-parede do progresso da acao "analyze" (ver
        # process_walls_one_by_one) - mesma ideia de self.progress_cb, so'
        # que chamados a CADA parede, nao a cada ~10%.
        self.wall_start_cb = None
        self.wall_result_cb = None
        # devolve True quando o usuario clicou "Cancelar" - checado nos
        # mesmos pontos onde a ETAPA 3C ja' checa o orcamento de tentativas
        # (ver find_wall_group_shift_fixes). None = sem suporte a
        # cancelamento (comportamento antigo).
        self.should_cancel_cb = None
        # mesma ideia de should_cancel_cb, devolve True enquanto o usuario
        # quer PAUSAR (nao cancelar) - checado nos mesmos pontos, FASE 1 do
        # plano em C:\Users\CIVIX\.claude\plans\quiet-painting-petal.md.
        # None = sem suporte a pausa (comportamento antigo).
        self.should_pause_cb = None
        # so' usado pela acao "analyze" (ver _execute_analyze, Mudanca 2 do
        # plano de arquitetura em memoria): callback `ui_invoke_cb(fn)` que
        # marshala `fn` (sem argumentos) para a thread de UI - configurado
        # por _WallReviewForm._on_start_click com um Control real
        # (mesma tecnica de _ProgressConsole._invoke_if_needed). Quando
        # None (chamador antigo/teste que nao configurou), _execute_analyze
        # roda SINCRONO, exatamente como antes desta mudanca - nunca quebra
        # compatibilidade com quem chama a acao "analyze" direto.
        self.ui_invoke_cb = None
        # so' usado pela acao "solve" (ver _execute_solve) - callback de
        # progresso AO VIVO do solver de blocos (Etapa 4, "Lancar Blocos"),
        # que ate' 2026-08-26 nao tinha NENHUM feedback (a causa raiz do
        # "carregamento infinito" reportado pelo usuario). Dict opcional
        # com as chaves "band_cb"/"progress_cb"/"wall_start_cb"/
        # "wall_result_cb" (mesmos nomes de solve_building_blocks_all_courses)
        # - None desabilita (comportamento antigo, silencioso).
        self.solve_progress_cb = None
        # Funcoes capturadas como atributos de instancia (nao pelo nome do
        # modulo) - mesmo motivo dos dois handlers antigos que este
        # substitui: o pyRevit reexecuta este Script.py do zero a cada
        # clique, e o dicionario de globais de uma execucao anterior nao
        # sobrevive.
        self._Transaction = Transaction
        self._analyze_created_walls_for_errors = analyze_created_walls_for_errors
        self._fix_all_wall_modulation_errors = fix_all_wall_modulation_errors
        self._solve_building_blocks = solve_building_blocks
        self._solve_building_blocks_all_courses = solve_building_blocks_all_courses
        self._create_building_blocks = create_building_blocks
        self._num_courses_for_wall_height = num_courses_for_wall_height
        self._OverrideGraphicSettings = OverrideGraphicSettings
        self._REVIT_DB_COLOR = _REVIT_DB_COLOR
        self._DEBUG_BLOCK_CODE_COLORS = DEBUG_BLOCK_CODE_COLORS
        self._colliding_created_instance_ids = _colliding_created_instance_ids
        self._bond_reproved_created_instance_ids = _bond_reproved_created_instance_ids
        self._apply_solid_color_override = _apply_solid_color_override
        # FONTE UNICA DE GEOMETRIA (ver _execute_fix_errors abaixo): depois
        # de aplicar uma correcao que muda a Line de uma ou mais Walls
        # (ETAPA 3C - group_shift/wall_length_adjust), o grafo de
        # encontros (self.wall_graph_nodes/self.wall_end_to_node) precisa
        # ser reconstruido a partir da MESMA geometria nova - senao
        # node["point"] (usado por solve_l_corner/solve_t_intersection/
        # solve_x_intersection para posicionar os blocos de encontro) fica
        # congelado na posicao ANTIGA, mesmo com a Wall real (e
        # self.walls_to_create) ja' na posicao corrigida. Mesma chamada
        # usada pela verificacao em memoria da propria ETAPA 3C, ver
        # find_wall_group_shift_fixes.
        self._extend_wall_ends_to_junctions = extend_wall_ends_to_junctions
        self._build_wall_graph = build_wall_graph
        self._JUNCTION_FACE_SEARCH_FT = JUNCTION_FACE_SEARCH_FT

        # Rede de seguranca ADICIONAL para o mesmo problema (ver
        # _LiveUpdaterBase, onde este padrao foi diagnosticado e provado ao
        # vivo primeiro): capturar so' as funcoes de fronteira acima NAO
        # basta, porque o CORPO delas (fix_all_wall_modulation_errors,
        # analyze_created_walls_for_errors, solve_building_blocks, ...) faz
        # dezenas de buscas de nome bare PROPRIAS (SubTransaction,
        # Transaction, evaluate_wall_modulation, Wall, XYZ, ...) contra o
        # dicionario de globais do MODULO - o mesmo dicionario que pode
        # ficar stale (confirmado ao vivo, 2x: "name 'UI_OK'"/"name
        # 'SubTransaction' is not defined" ao clicar em botoes desta
        # janela). `.__globals__` de uma funcao ja' capturada (nao
        # `globals()` puro) e' o jeito CONFIAVEL de guardar essa
        # referencia: e' um atributo comum do objeto funcao, sem depender
        # de qual "frame atual" o interpretador acha que esta - o mesmo
        # cuidado se aplica em Execute() abaixo (ver comentario la').
        #
        # E TEM QUE SER UMA COPIA (`dict(...)`): guardar `__globals__` direto
        # nao protege nada - e' o MESMO objeto que o modulo usa, entao perde
        # os nomes junto com ele e o `.update(self._g)` de Execute() vira um
        # no-op. Essa foi a causa real do erro "Falha ao disparar a correcao:
        # SubTransaction" ao clicar 'Ajustar Erros': com o lookup via
        # `g["SubTransaction"]`, o nome que sumia deixou de virar
        # UnboundNameException e passou a virar KeyError (cujo str() e' so' o
        # nome da chave), mas a causa raiz continuava exatamente a mesma.
        self._g = dict(self._fix_all_wall_modulation_errors.__globals__)

    def Execute(self, uiapp):
        try:
            # Reinjeta o snapshot de globais capturado no __init__ (ver
            # comentario la') no dicionario REAL do modulo - conserta
            # qualquer nome que tenha ficado stale entre a criacao da
            # janela e este clique, para esta chamada E para toda funcao
            # transitivamente chamada abaixo (fix_all_wall_modulation_errors,
            # analyze_created_walls_for_errors, solve_building_blocks, etc. -
            # todas compartilham o MESMO dicionario de globais deste modulo).
            #
            # IMPORTANTE (corrigido 2026-08-21, 2a tentativa - a 1a usava
            # `globals()` chamado AQUI DENTRO e nao resolveu o crash de
            # verdade no Revit do usuario, so' no teste offline): `Execute`
            # e' invocado pelo Revit via callback de interop .NET
            # (IExternalEventHandler), nao por uma chamada Python normal -
            # `globals()` chamado NESTE frame pode nao devolver o mesmo
            # dicionario que o corpo de fix_all_wall_modulation_errors
            # consulta (suspeita: o `LookupGlobalInstruction` do IronPython
            # usa o Scope/CodeContext do frame ATUAL, que pode divergir do
            # modulo real quando a chamada vem de fora do Python). Em vez
            # de confiar em `globals()` daqui, usamos `.__globals__` de uma
            # funcao JA' CAPTURADA como referencia direta (atributo comum,
            # sem ambiguidade de frame/escopo) - qualquer funcao definida
            # neste modulo aponta para o MESMO dicionario real.
            self._fix_all_wall_modulation_errors.__globals__.update(self._g)
            app_uidoc = uiapp.ActiveUIDocument
            app_doc = app_uidoc.Document
            if self.action == "analyze":
                self._refresh_geometry_from_document(app_doc)
                self._execute_analyze(app_doc)
            elif self.action == "zoom":
                self._execute_zoom(app_uidoc)
            elif self.action == "fix_errors":
                self._execute_fix_errors(app_doc)
            elif self.action == "solve":
                self._refresh_geometry_from_document(app_doc)
                self._execute_solve()
            elif self.action == "create":
                self._refresh_geometry_from_document(app_doc)
                self._execute_create(app_doc)
            elif self.action == "delete":
                self._execute_delete(app_doc)
            elif self.action == "debug_view":
                self._execute_debug_view(app_doc)
        except Exception as ex:
            # Este except e' a UNICA rede de seguranca entre um bug do
            # script e uma excecao nao tratada chegando ate' o Revit -
            # confirmado ao vivo (2026-08-21) que isso pode DERRUBAR O
            # REVIT INTEIRO (nao so' mostrar um dialogo), entao o proprio
            # `self.on_done(...)` tambem precisa estar protegido: se o
            # callback da UI (ex.: _on_fix_done) lancar por qualquer motivo
            # (inclusive um SEGUNDO nome stale), essa segunda excecao NAO
            # pode escapar daqui tambem.
            try:
                if self.on_done:
                    # str(ex) pode vir VAZIO (ex.: `raise Exception()`, sem
                    # mensagem) - `kind` ("error") ja' e' o sinal real de
                    # falha para quem consome isto (ver os `_on_*_done` de
                    # _PostCreationForm, que checam `kind == "error"`, nunca
                    # `if error:`), mas mesmo assim uma mensagem vazia na
                    # tela ("Falha: ") esconde que algo tem detalhe nenhum
                    # para mostrar - `repr(ex)` sempre traz ao menos o tipo
                    # da excecao.
                    self.on_done("error", str(ex) or repr(ex))
            except Exception:
                pass
        finally:
            self.action = None

    def _refresh_geometry_from_document(self, app_doc):
        """GEOMETRIA ATUAL COMO FONTE DA VERDADE (pedido explicito do
        usuario, 2026-08-26): antes de "Analisar Paredes", "Lancar Blocos -
        calcular" (solve) ou "Lancar Blocos - criar", releia a posicao REAL
        de cada Wall ja' criada em `self.created_walls_by_axis` diretamente
        do `app_doc` - nunca confie so' no snapshot leve capturado na Etapa
        1 (`self.wall_segment_geometry`) ou em `self.walls_to_create`
        parado desde entao. Isso cobre o caso relatado pelo usuario: ele
        ajusta uma parede manualmente no proprio Revit (fora do botao
        "Ajustar Erros", que era o UNICO lugar que atualizava esta
        geometria antes) e depois pede para modular - sem este refresh, o
        solver e a criacao usariam a posicao ANTIGA, anterior ao ajuste
        manual.

        Roda SEMPRE na thread principal da API (dentro de Execute(), antes
        de qualquer analyze/solve/create - nunca dentro da thread de fundo
        de _execute_analyze), exatamente como main() Etapa 1 fez a captura
        original: para cada eixo, projeta os DOIS extremos reais atuais de
        TODOS os seus segmentos (Wall.Location.Curve, ao vivo) na MESMA
        direcao do eixo original (`walls_to_create[wall_idx][0].Direction`)
        - isso cobre estender/encurtar/deslocar ao longo do proprio eixo, o
        tipo de ajuste manual que o usuario realmente faz nesta parede
        (rotacionar o eixo inteiro nao e' suportado em nenhum outro lugar
        deste pipeline). Reconstroi `self.walls_to_create[wall_idx]` (nova
        centerline) e `self.wall_segment_geometry[wall_idx]` (novo t_a/t_b
        por segmento) a partir disso, depois refaz o grafo de encontros
        (`self.wall_graph_nodes`/`self.wall_end_to_node`) - mesmo par de
        chamadas que `_execute_fix_errors` ja usava, so' que agora
        incondicional, a cada acao, nunca so' "se algo mudou por Ajustar
        Erros".

        Um eixo cuja Wall foi apagada/invalidada fora do script (ElementId
        nao resolve mais, ou perdeu LocationCurve) e' deixado como estava -
        nunca derruba o refresh dos demais eixos nem lanca excecao."""
        any_updated = False
        for wall_idx, entries in self.created_walls_by_axis.items():
            if not entries or wall_idx >= len(self.walls_to_create):
                continue
            try:
                old_centerline, thickness_ft, locked_ends = self.walls_to_create[wall_idx]
                direction = old_centerline.Direction
                dir_xy = XYZ(direction.X, direction.Y, 0.0).Normalize()
                origin_ref = old_centerline.GetEndPoint(0)

                seg_curves = []
                for element_id, _seg_origin in entries:
                    elem = app_doc.GetElement(element_id)
                    if elem is None or not isinstance(elem.Location, LocationCurve):
                        seg_curves = None
                        break
                    seg_curves.append(elem.Location.Curve)
                if not seg_curves:
                    continue  # eixo fora de escopo - mantem geometria antiga

                all_ts = []
                for curve in seg_curves:
                    for k in (0, 1):
                        p = curve.GetEndPoint(k)
                        t = XYZ(p.X - origin_ref.X, p.Y - origin_ref.Y, 0.0).DotProduct(dir_xy)
                        all_ts.append((t, p))
                min_t, min_p = min(all_ts, key=lambda tp: tp[0])
                max_t, max_p = max(all_ts, key=lambda tp: tp[0])
                if (max_t - min_t) < 1e-6:
                    continue  # eixo colapsado - nunca substitui por lixo

                new_p0 = XYZ(origin_ref.X + dir_xy.X * min_t, origin_ref.Y + dir_xy.Y * min_t, min_p.Z)
                new_p1 = XYZ(origin_ref.X + dir_xy.X * max_t, origin_ref.Y + dir_xy.Y * max_t, min_p.Z)
                new_centerline = Line.CreateBound(new_p0, new_p1)

                new_segments = []
                for (element_id, seg_origin), curve in zip(entries, seg_curves):
                    t_a = XYZ(curve.GetEndPoint(0).X - origin_ref.X, curve.GetEndPoint(0).Y - origin_ref.Y, 0.0).DotProduct(dir_xy)
                    t_b = XYZ(curve.GetEndPoint(1).X - origin_ref.X, curve.GetEndPoint(1).Y - origin_ref.Y, 0.0).DotProduct(dir_xy)
                    if t_a > t_b:
                        t_a, t_b = t_b, t_a
                    new_segments.append({"element_id": element_id, "seg_origin": seg_origin,
                                          "t_a": t_a, "t_b": t_b})

                self.walls_to_create[wall_idx] = (new_centerline, thickness_ft, locked_ends)
                self.wall_segment_geometry[wall_idx] = new_segments
                any_updated = True
            except Exception:
                continue  # nunca derruba o refresh dos demais eixos

        if any_updated:
            walls_ext, junction_map = self._extend_wall_ends_to_junctions(
                self.walls_to_create, self._JUNCTION_FACE_SEARCH_FT
            )
            self.walls_to_create = walls_ext
            self.wall_graph_nodes, self.wall_end_to_node = self._build_wall_graph(
                self.walls_to_create, junction_map
            )

    def _execute_analyze(self, app_doc):
        """Acao "analyze" - disparada pelo botao "Iniciar Modulacao" de
        _WallReviewForm (ver _show_wall_review_window). Roda
        analyze_created_walls_for_errors (SO' LEITURA - nenhuma Transaction,
        ver docstring dela) sobre as Walls JA' CRIADAS na Etapa 1 e guarda o
        resultado em self.error_rows - o mesmo atributo que "fix_errors" ja'
        consome/atualiza, entao a Etapa 2 (janela de resultado aberta em
        seguida por quem chamou _show_wall_review_window) enxerga exatamente
        os mesmos dados que main() calculava antes desta separacao Etapa
        1/Etapa 2.

        MUDANCA 2 do plano de arquitetura em memoria (2026-08-26): quando
        `self.wall_segment_geometry` foi preenchido na Etapa 1 (ver main()),
        analyze_created_walls_for_errors roda 100% livre de `target_doc` (ver
        _classify_wall_axis_segments) - entao roda numa `System.Threading.
        Thread` de VERDADE, fora da thread principal do Revit, em vez de
        bloquear `Execute()` (que e' a propria thread de UI do Revit) pela
        duracao inteira do solver, como acontecia antes. `self.on_done` so'
        e' chamado quando a thread termina, marshalado de volta para a UI via
        `self.ui_invoke_cb` (configurado pelo chamador com um Control real -
        ver _WallReviewForm._on_start_click). Sem `ui_invoke_cb` (chamador
        antigo/teste que nao configurou), roda SINCRONO exatamente como
        antes desta mudanca - nunca quebra quem chama a acao "analyze" sem
        passar por essa janela."""
        def _worker():
            error_detail = None
            result = None
            try:
                result = self._analyze_created_walls_for_errors(
                    app_doc, self.walls_to_create, self.openings_per_wall,
                    self.created_walls_by_axis, self.all_openings,
                    self.wall_graph_nodes, self.wall_end_to_node,
                    self.catalog, self.catalog_missing,
                    self.modulation_results, self.opening_incompatible_modulation,
                    progress_cb=self.progress_cb,
                    wall_start_cb=self.wall_start_cb, wall_result_cb=self.wall_result_cb,
                    should_cancel_cb=self.should_cancel_cb, should_pause_cb=self.should_pause_cb,
                    wall_segment_geometry=self.wall_segment_geometry,
                )
            except Exception as worker_ex:
                error_detail = str(worker_ex) or repr(worker_ex)

            def _finish():
                if error_detail is not None:
                    if self.on_done:
                        self.on_done("error", error_detail)
                    return
                self.error_rows = result
                if self.on_done:
                    self.on_done("analyze", None)

            if self.ui_invoke_cb is not None:
                self.ui_invoke_cb(_finish)
            else:
                _finish()

        if self.ui_invoke_cb is not None:
            thread = _DotNetThread(_DotNetThreadStart(_worker))
            thread.IsBackground = True
            thread.Start()
        else:
            _worker()

    def _execute_zoom(self, app_uidoc):
        """Primeira vez que este script da' zoom/selecao numa vista ao vivo
        a partir de uma janela modeless.

        ShowElements sozinho SO' GARANTE visibilidade - se os elementos ja'
        estao em algum canto da vista atual (o caso comum logo apos rodar o
        script, com a planta inteira visivel bem afastada), ele nao muda o
        zoom nem centraliza de verdade, entao "clicar na linha e nao
        acontecer nada visivel" e' o comportamento documentado da API, nao
        um bug de wiring. Por isso: ShowElements primeiro (troca de vista
        se a parede nao estiver visivel na atual) e DEPOIS um
        UIView.ZoomAndCenterRectangle na bounding box real dos elementos
        (com folga, ver ZOOM_TO_ERROR_MARGIN_FT) - isso sim forca o zoom."""
        ids = List[ElementId]()
        for eid in self.pending_zoom_ids:
            ids.Add(eid)
        if ids.Count == 0:
            if self.on_done:
                self.on_done("zoom", None)
            return

        app_uidoc.Selection.SetElementIds(ids)
        app_uidoc.ShowElements(ids)

        doc = app_uidoc.Document
        view = doc.ActiveView  # pode ter mudado - ShowElements troca de vista se precisar
        min_pt, max_pt = None, None
        for eid in self.pending_zoom_ids:
            elem = doc.GetElement(eid)
            if elem is None:
                continue
            bbox = elem.get_BoundingBox(view)
            if bbox is None:
                continue
            if min_pt is None:
                min_pt = XYZ(bbox.Min.X, bbox.Min.Y, bbox.Min.Z)
                max_pt = XYZ(bbox.Max.X, bbox.Max.Y, bbox.Max.Z)
            else:
                min_pt = XYZ(min(min_pt.X, bbox.Min.X), min(min_pt.Y, bbox.Min.Y), min(min_pt.Z, bbox.Min.Z))
                max_pt = XYZ(max(max_pt.X, bbox.Max.X), max(max_pt.Y, bbox.Max.Y), max(max_pt.Z, bbox.Max.Z))

        if min_pt is not None:
            min_pt = XYZ(min_pt.X - ZOOM_TO_ERROR_MARGIN_FT, min_pt.Y - ZOOM_TO_ERROR_MARGIN_FT, min_pt.Z)
            max_pt = XYZ(max_pt.X + ZOOM_TO_ERROR_MARGIN_FT, max_pt.Y + ZOOM_TO_ERROR_MARGIN_FT, max_pt.Z)
            for ui_view in app_uidoc.GetOpenUIViews():
                if ui_view.ViewId == view.Id:
                    ui_view.ZoomAndCenterRectangle(min_pt, max_pt)
                    break

        if self.on_done:
            self.on_done("zoom", None)

    def _execute_fix_errors(self, app_doc):
        t = self._Transaction(app_doc, "Ajusta erros de modulacao (parede + abertura)")
        t.Start()
        try:
            _fixed_count, _manual_review_count, updated_rows = self._fix_all_wall_modulation_errors(
                app_doc, self.error_rows, self.walls_to_create, self.openings_per_wall,
                created_walls_by_axis=self.created_walls_by_axis, all_openings=self.all_openings,
                g=self._g,
                progress_cb=self.progress_cb, should_cancel_cb=self.should_cancel_cb,
                should_pause_cb=self.should_pause_cb,
            )
            t.Commit()
        except Exception:
            t.RollBack()
            raise
        self.error_rows = updated_rows

        # Realce VERDE (pedido explicito do usuario, 2026-08-26) nas paredes
        # REAIS alteradas NESTA rodada de "Ajustar Erros" - `updated_rows`
        # so' carrega `_just_fixed_wall_ids` nas linhas que fix_all_wall_
        # modulation_errors realmente commitou agora (ver seu docstring/
        # corpo). Roda numa Transacao PROPRIA, DEPOIS do `t` acima ja ter
        # commitado (nunca dentro dela) - mesmo motivo de
        # _refresh_wall_modulation_override rodar em SubTransacao separada:
        # um SetElementOverrides nunca deve arriscar o RollBack de uma
        # correcao geometrica ja aceita. Tambem roda DEPOIS do `t` de
        # proposito: os updaters ao vivo (_WallModulationUpdater) ja
        # dispararam durante o Regenerate()/Commit() de `t` e ja limparam o
        # azul/vermelho antigo daquelas paredes - o verde aplicado aqui e' a
        # ULTIMA palavra sobre a cor, ate' a proxima edicao real de alguma
        # delas (quando o updater ao vivo reavalia e substitui pela cor
        # certa de novo - ver _refresh_wall_modulation_override, que nao
        # conhece "verde", so' vermelho/azul/nenhuma).
        green_ids = []
        seen_green = set()
        for row in updated_rows:
            for eid in row.get("_just_fixed_wall_ids") or []:
                key = eid.ToString() if hasattr(eid, "ToString") else eid
                if key in seen_green:
                    continue
                seen_green.add(key)
                green_ids.append(eid)
        if green_ids:
            t_green = self._Transaction(app_doc, "Realce verde das paredes corrigidas (Ajustar Erros)")
            t_green.Start()
            try:
                self._apply_solid_color_override(
                    app_doc.ActiveView, green_ids, self._REVIT_DB_COLOR(0, 180, 0), target_doc=app_doc
                )
                t_green.Commit()
            except Exception:
                t_green.RollBack()

        # FONTE UNICA DE GEOMETRIA - ver comentario em __init__ sobre
        # self._extend_wall_ends_to_junctions/self._build_wall_graph.
        # fix_all_wall_modulation_errors so' escreve em self.walls_to_create
        # (mutando os itens IN-PLACE) DEPOIS do Commit de cada SubTransaction
        # ter acontecido de verdade (ver o proprio docstring dela) - nunca
        # antes. Aqui, no ponto seguinte, e' onde o grafo de encontros desta
        # janela precisa alcancar essa geometria nova: se pelo menos uma
        # correcao foi aplicada (`_fixed_count > 0`), refaz o mesmo par de
        # chamadas (extend_wall_ends_to_junctions + build_wall_graph) usado
        # pela propria ETAPA 3C para verificar seus candidatos em memoria -
        # assim self.wall_graph_nodes/self.wall_end_to_node passam a
        # descrever EXATAMENTE a mesma geometria que self.walls_to_create (e
        # a Wall real no Revit) tem agora, e qualquer "Analisar Paredes"/
        # "Lancar Blocos" clicado DEPOIS deste "Ajustar Erros" usa encontros
        # (node["point"]) na posicao NOVA, nunca na antiga.
        if _fixed_count:
            walls_ext, junction_map = self._extend_wall_ends_to_junctions(
                self.walls_to_create, self._JUNCTION_FACE_SEARCH_FT
            )
            self.walls_to_create = walls_ext
            self.wall_graph_nodes, self.wall_end_to_node = self._build_wall_graph(
                self.walls_to_create, junction_map
            )

        if self.on_done:
            self.on_done("fix_errors", None)

    def _execute_solve(self):
        # Ciente de fiada (2026-08-21, pedido do usuario): uma JANELA
        # (peitoril>0) so' fica vazia na faixa vertical REAL do seu vao -
        # fiadas abaixo do peitoril (ou acima da verga) continuam solidas.
        # Precisa saber quantas fiadas fisicas cabem no pe-direito ANTES de
        # resolver (para agrupar as bandas verticais) - `[]` usa a altura
        # do CATALOGO INTEIRO, disponivel mesmo sem nenhum candidato ainda
        # resolvido (ver _course_height_ft).
        num_courses, num_courses_err = self._num_courses_for_wall_height(
            self.wall_height_ft, self.catalog, []
        )
        if num_courses <= 0:
            self.solve_result = {
                "error": num_courses_err, "course_candidates": {}, "bands": [],
                "candidates": [], "collisions": [], "intersection_failures": [],
                "jamb_exceptions": [], "non_modular": [], "per_wall": [], "validations": [],
                "door_void_violations": [],
            }
        else:
            cbs = self.solve_progress_cb or {}
            self.solve_result = self._solve_building_blocks_all_courses(
                self.wall_graph_nodes, self.walls_to_create, self.wall_end_to_node,
                self.openings_per_wall, self.catalog, self.base_z_abs, num_courses,
                variants_per_course=PIER_LAYOUT_VARIANTS_PER_COURSE,
                band_cb=cbs.get("band_cb"), progress_cb=cbs.get("progress_cb"),
                wall_start_cb=cbs.get("wall_start_cb"), wall_result_cb=cbs.get("wall_result_cb"),
                stage_cb=cbs.get("stage_cb"),
            )
        self.solve_result["num_courses"] = num_courses
        self._save_modulation_state_cache()
        if self.on_done:
            self.on_done("solve", None)

    def _execute_create(self, app_doc):
        # IDEMPOTENCIA / INTEGRIDADE DO CONJUNTO (bug real corrigido
        # 2026-08-25, reportado pelo usuario com imagem: parte da parede
        # "andou" e parte ficou na posicao antiga apos recalcular).
        # create_building_blocks NUNCA apaga nada, so' cria (ver seu
        # proprio docstring) - "Lancar Blocos - criar" pode ser clicado
        # mais de uma vez na MESMA janela (os dois botoes ficam habilitados
        # de novo depois de cada uso, ver _on_solve_done/_on_create_done em
        # _PostCreationForm), por exemplo depois de "Ajustar Erros" mudar
        # uma abertura e o usuario recalcular para conferir. Sem apagar o
        # lote anterior, um segundo clique empilhava um SEGUNDO conjunto de
        # instancias por cima do primeiro: as pecas de encontro L/T/X (que
        # nao mudam de posicao entre dois calculos, o no' e' o mesmo ponto
        # fisico) ficavam PERFEITAMENTE sobrepostas - invisiveis, pareciam
        # "nao ter mudado" - enquanto o preenchimento comum (que SIM muda
        # quando uma abertura se deslocou) sobrava DUPLICADO nas duas
        # posicoes ao mesmo tempo. O resultado visual era exatamente "parte
        # da modulacao deslocou, parte ficou parada" - nunca aceitavel
        # (regra do usuario, 2026-08-25: a parede + todos os blocos dela +
        # amarracoes formam um UNICO conjunto que tem que ser recalculado e
        # reposicionado JUNTO, sempre). Apagando o lote anterior por
        # completo ANTES de criar o novo, cada clique em "criar" passa a
        # ser uma SUBSTITUICAO atomica (nunca uma soma) - o modelo nunca
        # mistura pecas de dois calculos diferentes.
        previous_instances = (self.create_result or {}).get("created_instances") or []
        if previous_instances:
            t_cleanup = self._Transaction(app_doc, "Remove lote anterior de blocos (recalculo)")
            t_cleanup.Start()
            try:
                for item in previous_instances:
                    try:
                        elem = app_doc.GetElement(item["id"])
                        if elem is not None:
                            app_doc.Delete(item["id"])
                    except Exception:
                        pass  # peca ja' apagada/invalida - nunca trava a recriacao
                t_cleanup.Commit()
            except Exception:
                t_cleanup.RollBack()

        course_candidates = self.solve_result.get("course_candidates") if self.solve_result else None
        candidates = self.solve_result["candidates"] if self.solve_result else []
        num_courses = self.solve_result.get("num_courses", 0) if self.solve_result else 0
        if num_courses <= 0:
            err = self.solve_result.get("error") if self.solve_result else None
            self.create_result = {
                "created_count": 0, "failures": [err or "numero de fiadas invalido"],
                "course_height_ft": None, "course_height_error": err,
                "created_instances": [],
            }
        else:
            # REGRA REVISTA 2026-08-26 (pedido explicito do usuario:
            # "MODULAR PRIMEIRO -> DIAGNOSTICAR O RESULTADO -> INFORMAR OS
            # ERROS... o diagnostico nao pode impedir a geracao dos
            # blocos... mesmo que exista algum problema dimensional...
            # quero conseguir enxergar o resultado no Revit"). Isto reverte
            # a regra #1/#6/#7 de 2026-08-25 que excluia POR PAREDE os
            # candidatos reprovados na auditoria de amarracao entre fiadas
            # antes de chamar create_building_blocks. Agora NENHUM
            # diagnostico (amarracao entre fiadas, colisao entre pecas, vao
            # de porta) filtra candidatos - todos os candidatos calculados
            # pelo solver chegam a create_building_blocks e viram
            # FamilyInstance real; os problemas encontrados so' marcam as
            # pecas envolvidas em VERMELHO DEPOIS de criadas, para revisao
            # manual (nunca impedem a criacao).
            wall_bond_audits = (self.solve_result or {}).get("wall_bond_audits") or {}
            reproved_wall_idxs = {wi for wi, audit in wall_bond_audits.items() if not audit["ok"]}

            self.create_result = self._create_building_blocks(
                app_doc, candidates, self.catalog, self.base_z_abs,
                self.selected_level, num_courses, course_candidates=course_candidates
            )
            # Nao ha' mais "parede sem bloco": skipped_* fica sempre vazio,
            # mantido so' por compatibilidade com quem le' create_result.
            self.create_result["skipped_wall_count"] = 0
            self.create_result["skipped_wall_idxs"] = []
            self.create_result["reproved_wall_count"] = len(reproved_wall_idxs)
            self.create_result["reproved_wall_idxs"] = sorted(reproved_wall_idxs)
            # Colisao entre pecas: pedido explicito do usuario (2026-08-24)
            # continua valendo - lanca mesmo assim, so' marca em vermelho.
            collisions = (self.solve_result or {}).get("collisions") or []
            colliding_ids = self._colliding_created_instance_ids(
                candidates, collisions, self.create_result.get("created_instances") or []
            )
            self.create_result["colliding_instance_count"] = len(colliding_ids)
            # Pecas de paredes reprovadas na auditoria de amarracao - agora
            # FORAM criadas (ver acima), entao marcam a PECA em vermelho
            # (nao mais a parede de referencia vazia, ja' que ha' pecas).
            bond_reproved_ids = self._bond_reproved_created_instance_ids(
                candidates, wall_bond_audits, self.create_result.get("created_instances") or []
            )
            highlight_ids = list(set(colliding_ids) | set(bond_reproved_ids))
            if highlight_ids:
                t_highlight = self._Transaction(app_doc, "Realce vermelho de colisoes/paredes sem modulacao aprovada")
                t_highlight.Start()
                try:
                    # Vermelho generico (ver _apply_solid_color_override) -
                    # significado DIFERENTE do vermelho de comprimento
                    # quebrado (ver _apply_broken_length_overrides, Tela 1):
                    # aqui marca colisao de pecas/parede sem bloco aprovado
                    # na auditoria de amarracao (Tela 2, "Lancar Blocos").
                    # Chamado DIRETO em vez de por um wrapper dedicado
                    # (antigo _apply_suspect_wall_overrides, removido junto
                    # com a feature "ponta suspeita" que ele servia) - nao
                    # ha' mais nenhum wrapper de proposito unico para isto.
                    self._apply_solid_color_override(
                        app_doc.ActiveView, highlight_ids, self._REVIT_DB_COLOR(255, 0, 0), target_doc=app_doc
                    )
                    t_highlight.Commit()
                except Exception:
                    t_highlight.RollBack()
        self._save_modulation_state_cache()
        if self.on_done:
            self.on_done("create", None)

    def _save_modulation_state_cache(self):
        """Guarda solve_result/create_result em _LAST_MODULATION_STATE,
        por assinatura do conjunto de paredes (ver docstring da' - pedido
        explicito do usuario, 2026-08-27: fechar a janela ANTES de clicar
        em "criar" nao pode obrigar a recalcular o solver do zero). Chamado
        no fim de _execute_solve/_execute_create, sempre que houver ao
        menos um candidato calculado - nunca sobrescreve o cache com um
        resultado vazio (ex.: erro de altura de fiada)."""
        if not (self.solve_result and self.solve_result.get("candidates")):
            return
        sig = _wall_ids_signature(self.created_wall_ids_all)
        if sig is None:
            return
        _LAST_MODULATION_STATE[sig] = {
            "solve_result": self.solve_result, "create_result": self.create_result,
        }

    def _execute_delete(self, app_doc):
        # NUNCA excluir a parede de referencia de um eixo que ficou SEM
        # bloco (reprovado na auditoria de amarracao entre fiadas - regra
        # #1, 2026-08-25, ver _execute_create): apagar essa parede junto
        # deixaria o vao COMPLETAMENTE vazio (nem parede de referencia, nem
        # bloco nenhum) - exatamente o problema "parede some sem explicacao"
        # que a regra #4 do usuario probe. A parede de referencia PRECISA
        # continuar ali, marcada em vermelho (ja' aplicado em
        # _execute_create), ate' a revisao manual resolver o eixo.
        skipped_wall_idxs = set((self.create_result or {}).get("skipped_wall_idxs") or [])
        skipped_wall_ids = set()
        for wi in skipped_wall_idxs:
            skipped_wall_ids.update(eid for eid, _origin in self.created_walls_by_axis.get(wi, []))

        deleted = 0
        delete_failures = []
        t = self._Transaction(app_doc, "Exclui paredes substituidas pelos blocos")
        t.Start()
        try:
            for wall_id in self.created_wall_ids_all:
                if wall_id in skipped_wall_ids:
                    continue
                try:
                    wall_elem = app_doc.GetElement(wall_id)
                    if wall_elem is not None:
                        app_doc.Delete(wall_id)
                        deleted += 1
                except Exception as ex:
                    delete_failures.append(str(ex))
            t.Commit()
        except Exception as ex:
            t.RollBack()
            delete_failures.append("Falha inesperada, nenhuma parede foi excluida: {}".format(ex))
            deleted = 0
        if self.create_result is None:
            self.create_result = {}
        self.create_result["deleted_wall_count"] = deleted
        self.create_result["delete_failures"] = delete_failures
        self.create_result["kept_wall_count_no_blocks"] = len(
            skipped_wall_ids & set(self.created_wall_ids_all)
        )
        if self.on_done:
            self.on_done("delete", None)

    def _execute_debug_view(self, app_doc):
        """Aplica o modo debug visual ("colorir por codigo de bloco e
        filtrar Fiada A/Fiada B") sobre os blocos REAIS ja' criados
        (self.create_result["created_instances"] - so' existe depois de
        "Lancar Blocos"). Precisa de uma Transacao (SetElementOverrides e
        Hide/UnhideElements sao operacoes de documento)."""
        instances = (self.create_result or {}).get("created_instances") or []
        view = app_doc.ActiveView

        # Mesmo padrao de _apply_solid_color_override (ver secao VALIDACAO DE
        # MODULACAO...): sem o FillPatternId de um preenchimento SOLIDO do
        # PROPRIO documento, SetSurfaceForegroundPatternColor sozinho nao
        # produz nenhum preenchimento visivel na vista - so' a cor de linha.
        solid_fill_id = None
        for fp in FilteredElementCollector(app_doc).OfClass(FillPatternElement):
            if fp.GetFillPattern().IsSolidFill:
                solid_fill_id = fp.Id
                break

        t = self._Transaction(app_doc, "Modo debug visual dos blocos")
        t.Start()
        try:
            # Sempre REVELA todo mundo primeiro, incondicionalmente: View.
            # HideElements lanca excecao se algum id da colecao ja estiver
            # oculto na vista - sem este reset, alternar o filtro Fiada
            # A/B/Ambas duas vezes seguidas (um id que ficou oculto na
            # chamada anterior sendo escondido de novo) quebraria a acao.
            # Unhide de algo ja visivel e' inofensivo (idempotente).
            all_ids = List[ElementId]()
            for item in instances:
                all_ids.Add(item["id"])
            if all_ids.Count > 0:
                view.UnhideElements(all_ids)

            to_hide = List[ElementId]()
            to_unhide = List[ElementId]()
            for item in instances:
                element_id = item["id"]
                show_this = (
                    self.debug_course_filter is None or
                    item["course"] == self.debug_course_filter
                )
                if show_this:
                    to_unhide.Add(element_id)
                else:
                    to_hide.Add(element_id)

                override = self._OverrideGraphicSettings()
                if self.debug_color_by_code:
                    color = self._DEBUG_BLOCK_CODE_COLORS.get(
                        item["logical_code"], self._REVIT_DB_COLOR(80, 80, 80)
                    )
                    override.SetProjectionLineColor(color)
                    if solid_fill_id is not None:
                        override.SetSurfaceForegroundPatternColor(color)
                        override.SetSurfaceForegroundPatternId(solid_fill_id)
                        override.SetSurfaceForegroundPatternVisible(True)
                view.SetElementOverrides(element_id, override)

            if to_hide.Count > 0:
                view.HideElements(to_hide)
            if to_unhide.Count > 0:
                view.UnhideElements(to_unhide)
            t.Commit()
        except Exception:
            t.RollBack()
            raise
        if self.on_done:
            self.on_done("debug_view", None)

    def GetName(self):
        return "Modulacao automatica - resultado (analise/ajuste/blocos/exclusao)"


class _PostCreationForm(Form):
    """Janela UNICA e MODELESS (ver cabecalho da secao JANELA UNICA DE
    MODULACAO acima) com a trilha completa: analise (ja' pronta ao abrir,
    ver _show_post_creation_window) -> lista de erros (linha clicavel, da'
    zoom na parede) -> "Ajustar Erros" -> bloco "Lancar Blocos" -> bloco
    "Finalizar/Deletar Paredes" -> log no rodape. Substitui as antigas
    _ResultsForm e _BlockWizardForm (ambas removidas), sem nenhuma
    TabControl - tudo numa unica tela, pedido explicito do usuario."""

    def __init__(self, report, external_event, handler, created_wall_ids_all):
        # OBRIGATORIO no engine CPython (pythonnet) - ver o mesmo comentario
        # em _SetupForm.__init__ (bug real medido em producao, 2026-08-27):
        # sem chamar o construtor .NET base ANTES de qualquer propriedade
        # WinForms real ser tocada, o objeto CLR fica com campos internos
        # nulos e `self.Text = ...` (a primeira linha de verdade abaixo)
        # lanca NullReferenceException.
        Form.__init__(self)
        self._report = report
        self._external_event = external_event
        self._handler = handler
        self._created_wall_count = len(created_wall_ids_all)
        # Capturadas como atributos de instancia (nao pelo nome do modulo)
        # pelo MESMO motivo ja documentado em _PostCreationEventHandler.
        # __init__/_ApplySuggestionsEventHandler (removida): metodos desta
        # janela sao invocados DEPOIS, por um Click/SelectedIndexChanged
        # que pode disparar muito tempo apos main() ter terminado - o
        # pyRevit reexecuta o Script.py do zero a cada clique no botao do
        # addin, e uma referencia pelo NOME (nao capturada agora) quebra
        # com "UnboundNameException" quando isso acontece com a janela
        # ainda aberta (confirmado empiricamente - ver _on_copy/
        # _on_solve_done, que sao os dois metodos desta classe que chamam
        # uma funcao do modulo por fora do handler).
        self._copy_text_to_clipboard = _copy_text_to_clipboard
        self._format_block_solve_report = _format_block_solve_report
        self._build_final_modulation_report = build_final_modulation_report
        self._format_final_modulation_report = _format_final_modulation_report
        # Paleta de cores TAMBEM capturada como atributo de instancia, mesmo
        # motivo acima - confirmado empiricamente em 2026-08-21 que constantes
        # de modulo (nao so' funcoes) sofrem do mesmo UnboundNameException
        # quando referenciadas por NOME dentro de um metodo desta janela que
        # roda depois de o pyRevit reexecutar o Script.py (bug real reportado
        # no botao "Ajustar Erros": "name 'UI_OK' is not defined").
        self._UI_BG = UI_BG
        self._UI_PANEL = UI_PANEL
        self._UI_TEXT = UI_TEXT
        self._UI_MUTED = UI_MUTED
        self._UI_OK = UI_OK
        self._UI_WARN = UI_WARN


        self.Text = "Modulacao Automatica - Tela 2: Modulacao dos Blocos (nao bloqueia o Revit)"
        self.Width = 1100
        self.Height = 1000
        self.MinimumSize = Size(920, 760)
        self.StartPosition = FORM_START_POSITION_CENTER_SCREEN
        self.BackColor = self._UI_BG

        # ATENCAO - ORDEM DE Controls.Add() NO WINFORMS: para controles com o
        # MESMO DockStyle, o WinForms empilha o layout na ordem INVERSA da
        # insercao (o ULTIMO Add() com Dock.Top fica MAIS PROXIMO do topo) -
        # ver os blocos "ORDEM DOS CONTROLES" mais abaixo.
        header = _build_header(
            report.get("title") or "Tela 2 - Modulacao dos Blocos",
            report.get("subtitle") or
            "Modulacao das paredes ja concluida na Tela 1 - abaixo, os erros "
            "herdados (ainda podem ser ajustados) e, em seguida, o Solver 18 "
            "(lancamento de blocos X->T->L->jambs->trechos livres) com log e "
            "progresso AO VIVO -> Lancar Blocos - criar -> Finalizar/Deletar "
            "Paredes. Esta janela nao bloqueia o Revit."
        )

        cards = Panel()
        cards.Dock = DockStyle.Top
        cards.Height = 86
        cards.BackColor = self._UI_BG
        # Dock.Left empilha da esquerda para a direita na ordem INVERSA de
        # insercao, entao os cartoes entram de tras para frente.
        for caption, value, color in reversed(report.get("kpis") or []):
            card, spacer = _build_card(caption, value, color)
            cards.Controls.Add(spacer)
            cards.Controls.Add(card)

        footer = Panel()
        footer.Dock = DockStyle.Bottom
        footer.Height = 46
        footer.BackColor = self._UI_BG
        footer.Padding = Padding(18, 4, 18, 8)

        close_button = Button()
        close_button.Text = "Fechar"
        close_button.Dock = DockStyle.Right
        close_button.Width = 120
        _style_secondary_button(close_button)
        close_button.Click += lambda s, e: self.Close()

        gap1 = Panel(); gap1.Dock = DockStyle.Right; gap1.Width = 10

        copy_button = Button()
        copy_button.Text = "Copiar log"
        copy_button.Dock = DockStyle.Right
        copy_button.Width = 130
        _style_secondary_button(copy_button)
        copy_button.Click += self._on_copy

        self._footer_note = Label()
        self._footer_note.Dock = DockStyle.Fill
        self._footer_note.Font = _ui_font(8.5)
        self._footer_note.ForeColor = self._UI_MUTED
        log_path = report.get("log_path")
        self._footer_note.Text = (
            "Log salvo em: {}".format(log_path) if log_path
            else "Nao foi possivel salvar o log em arquivo - use 'Copiar log'."
        )

        footer.Controls.Add(self._footer_note)
        footer.Controls.Add(copy_button)
        footer.Controls.Add(gap1)
        footer.Controls.Add(close_button)

        # --- secao "Analisar Paredes" / "Erros encontrados" / "Ajustar Erros" ---
        errors_panel = Panel()
        errors_panel.Dock = DockStyle.Top
        errors_panel.Height = 250
        errors_panel.BackColor = self._UI_PANEL
        errors_panel.Padding = Padding(18, 10, 18, 10)

        self._errors_status = Label()
        self._errors_status.Dock = DockStyle.Top
        self._errors_status.Height = 22
        self._errors_status.Font = _ui_font(8.5)

        error_rows = handler.error_rows
        auto_fixable_count = sum(1 for r in error_rows if r["auto_fixable"])
        if report.get("wall_analysis_skipped"):
            # Pedido explicito do usuario (2026-08-27, botao "Pular para
            # Modulacao dos Blocos" em _WallReviewForm) - `error_rows` vazio
            # aqui significa "nunca analisado", NUNCA "planta validada",
            # entao o texto precisa deixar isso explicito (senao parece que
            # a modulacao das paredes rodou e nao achou problema).
            self._errors_status.ForeColor = self._UI_WARN
            self._errors_status.Text = (
                "Analisar Paredes: PULADO a pedido do usuario - eixos fora "
                "da modulacao NAO foram analisados nem corrigidos."
            )
        elif error_rows:
            self._errors_status.ForeColor = self._UI_WARN
            self._errors_status.Text = (
                "Analisar Paredes: {} eixo(s) fora da modulacao ({} com correcao "
                "automatica disponivel). Clique numa linha para dar zoom na "
                "parede no Revit.".format(len(error_rows), auto_fixable_count)
            )
        else:
            self._errors_status.ForeColor = self._UI_OK
            self._errors_status.Text = "Analisar Paredes: nenhum eixo fora da modulacao."

        self._errors_grid = _styled_listview([
            ("Eixo", 60), ("Problema", 560), ("Situacao", 200),
        ])
        self._errors_grid.MultiSelect = False
        self._errors_grid.SelectedIndexChanged += self._on_error_row_selected
        # Clique simples ja' muda a selecao (dispara SelectedIndexChanged
        # acima), mas um SEGUNDO clique/duplo-clique na MESMA linha ja'
        # selecionada nao muda o indice selecionado - SelectedIndexChanged
        # nao dispara de novo nesse caso. DoubleClick garante que o gesto
        # mais natural (clicar duas vezes pra "ir la'") sempre funciona,
        # mesmo repetido na mesma linha.
        self._errors_grid.DoubleClick += self._on_error_row_selected
        self._populate_error_rows(error_rows)

        errors_holder = Panel()
        errors_holder.Dock = DockStyle.Fill
        errors_holder.BackColor = self._UI_PANEL
        errors_holder.Controls.Add(self._errors_grid)

        fix_row = Panel()
        fix_row.Dock = DockStyle.Bottom
        fix_row.Height = 40

        # Pausar/Continuar e Cancelar (pedido explicito do usuario,
        # 2026-08-26) - "Ajustar Erros" era o UNICO botao desta janela sem
        # nenhum dos dois (ver fix_all_wall_modulation_errors, FASE 0/1 do
        # plano). Mesma regra de ordem de Dock.Right do resto do arquivo: o
        # ULTIMO Controls.Add() fica mais perto da borda - _fix_button
        # continua sendo adicionado por ultimo (fica na borda direita, onde
        # ja estava), Cancelar e Pausar ficam a esquerda dele.
        self._pause_button = Button()
        self._pause_button.Text = "Pausar"
        self._pause_button.Dock = DockStyle.Right
        self._pause_button.Width = 130
        _style_secondary_button(self._pause_button)
        self._pause_button.Click += self._on_pause_click
        self._pause_button.Visible = False
        fix_row.Controls.Add(self._pause_button)

        cancel_gap = Panel(); cancel_gap.Dock = DockStyle.Right; cancel_gap.Width = 10
        fix_row.Controls.Add(cancel_gap)

        self._fix_cancel_button = Button()
        self._fix_cancel_button.Text = "Cancelar"
        self._fix_cancel_button.Dock = DockStyle.Right
        self._fix_cancel_button.Width = 130
        _style_secondary_button(self._fix_cancel_button)
        self._fix_cancel_button.Click += self._on_fix_cancel_click
        self._fix_cancel_button.Visible = False
        fix_row.Controls.Add(self._fix_cancel_button)

        fix_gap = Panel(); fix_gap.Dock = DockStyle.Right; fix_gap.Width = 10
        fix_row.Controls.Add(fix_gap)

        self._fix_button = Button()
        self._fix_button.Text = "Ajustar Erros"
        self._fix_button.Dock = DockStyle.Right
        self._fix_button.Width = 200
        self._fix_button.Enabled = auto_fixable_count > 0
        _style_primary_button(self._fix_button)
        self._fix_button.Click += self._on_fix_click
        fix_row.Controls.Add(self._fix_button)

        self._fix_cancel_requested = False
        self._fix_paused = False

        errors_panel.Controls.Add(errors_holder)
        errors_panel.Controls.Add(fix_row)
        errors_panel.Controls.Add(self._errors_status)

        # --- secao "Lancar Blocos" / "Finalizar - Deletar Paredes" ---
        steps_panel = Panel()
        steps_panel.Dock = DockStyle.Top
        steps_panel.Height = 520
        steps_panel.BackColor = self._UI_BG
        steps_panel.Padding = Padding(18, 10, 18, 10)

        # --- catalogo (AUTOMATICO - sem botao, ja carregado antes desta
        # janela existir, ver _show_post_creation_window). Aqui so'
        # mostramos o resultado: OK com a contagem de tipos, ou a lista
        # exata de familia(s)/tipo(s) que faltam carregar no projeto.
        self._catalog_status = Label()
        self._catalog_status.Dock = DockStyle.Top
        self._catalog_status.Height = 22
        self._catalog_status.Font = _ui_font(8.5)
        self._catalog_status.ForeColor = self._UI_MUTED
        self._catalog_status.Text = "Catalogo: verificando familias fixas..."

        spacer1 = Panel(); spacer1.Dock = DockStyle.Top; spacer1.Height = 8

        # --- Lancar Blocos: calcular ---
        self._solve_button = Button()
        self._solve_button.Text = "Lancar Blocos - calcular (solver X->T->L->jambs->trechos livres)"
        self._solve_button.Dock = DockStyle.Top
        self._solve_button.Height = 34
        self._solve_button.Enabled = False
        _style_primary_button(self._solve_button)
        self._solve_button.Click += self._on_solve_click

        self._solve_status = Label()
        self._solve_status.Dock = DockStyle.Top
        self._solve_status.Height = 22
        self._solve_status.Font = _ui_font(8.5)
        self._solve_status.ForeColor = self._UI_MUTED
        self._solve_status.Text = "Aguardando 'Ajustar Erros' (ou o catalogo, se ja liberado)."

        # --- console de progresso AO VIVO do solver de blocos ("Solver 18",
        # ver _ProgressConsole) - pedido explicito do usuario (2026-08-26)
        # para acabar com o "carregamento infinito sem feedback" durante o
        # lancamento de blocos, ate' entao a etapa mais pesada e mais muda
        # do pipeline inteiro (_execute_solve nao tinha NENHUM callback de
        # progresso antes desta mudanca).
        solve_console_holder = Panel()
        solve_console_holder.Dock = DockStyle.Top
        solve_console_holder.Height = 190
        solve_console_holder.Padding = Padding(0, 4, 0, 4)
        self._solve_console = _ProgressConsole()
        self._solve_console.set_status("Aguardando 'Lancar Blocos - calcular'.")
        solve_console_holder.Controls.Add(self._solve_console.panel)

        spacer2 = Panel(); spacer2.Dock = DockStyle.Top; spacer2.Height = 8

        # --- Lancar Blocos: criar ---
        self._create_button = Button()
        self._create_button.Text = "Lancar Blocos - criar no Revit (todas as fiadas ate o pe-direito)"
        self._create_button.Dock = DockStyle.Top
        self._create_button.Height = 34
        self._create_button.Enabled = False
        _style_primary_button(self._create_button)
        self._create_button.Click += self._on_create_click

        self._create_status = Label()
        self._create_status.Dock = DockStyle.Top
        self._create_status.Height = 22
        self._create_status.Font = _ui_font(8.5)
        self._create_status.ForeColor = self._UI_MUTED
        self._create_status.Text = "Aguardando o solver fechar sem colisoes."

        spacer3 = Panel(); spacer3.Dock = DockStyle.Top; spacer3.Height = 8

        # --- debug visual ---
        debug_row = Panel()
        debug_row.Dock = DockStyle.Top
        debug_row.Height = 30

        self._debug_color_check = CheckBox()
        self._debug_color_check.Text = "Colorir por codigo de bloco"
        self._debug_color_check.AutoSize = True
        self._debug_color_check.Left = 0
        self._debug_color_check.Top = 4
        self._debug_color_check.Enabled = False
        self._debug_color_check.CheckedChanged += self._on_debug_change
        debug_row.Controls.Add(self._debug_color_check)

        self._debug_filter_both = RadioButton()
        self._debug_filter_both.Text = "Ambas as fiadas"
        self._debug_filter_both.AutoSize = True
        self._debug_filter_both.Left = 230
        self._debug_filter_both.Top = 4
        self._debug_filter_both.Checked = True
        self._debug_filter_both.Enabled = False
        self._debug_filter_both.CheckedChanged += self._on_debug_change
        debug_row.Controls.Add(self._debug_filter_both)

        self._debug_filter_a = RadioButton()
        self._debug_filter_a.Text = "So Fiada A"
        self._debug_filter_a.AutoSize = True
        self._debug_filter_a.Left = 380
        self._debug_filter_a.Top = 4
        self._debug_filter_a.Enabled = False
        self._debug_filter_a.CheckedChanged += self._on_debug_change
        debug_row.Controls.Add(self._debug_filter_a)

        self._debug_filter_b = RadioButton()
        self._debug_filter_b.Text = "So Fiada B"
        self._debug_filter_b.AutoSize = True
        self._debug_filter_b.Left = 500
        self._debug_filter_b.Top = 4
        self._debug_filter_b.Enabled = False
        self._debug_filter_b.CheckedChanged += self._on_debug_change
        debug_row.Controls.Add(self._debug_filter_b)

        spacer4 = Panel(); spacer4.Dock = DockStyle.Top; spacer4.Height = 8

        # --- Finalizar: exclusao das paredes ---
        review_row = Panel()
        review_row.Dock = DockStyle.Top
        review_row.Height = 26
        self._review_check = CheckBox()
        self._review_check.Text = (
            "Revisao humana concluida (confirmo que os blocos criados foram "
            "conferidos e estao corretos)"
        )
        self._review_check.AutoSize = True
        self._review_check.Left = 0
        self._review_check.Top = 2
        self._review_check.CheckedChanged += self._on_review_change
        review_row.Controls.Add(self._review_check)

        self._delete_button = Button()
        self._delete_button.Text = "Finalizar - Excluir as {} parede(s) de referencia".format(
            self._created_wall_count
        )
        self._delete_button.Dock = DockStyle.Top
        self._delete_button.Height = 34
        self._delete_button.Enabled = False
        _style_secondary_button(self._delete_button)
        self._delete_button.Click += self._on_delete_click

        # --- log/relatorio ---
        self._log_box = TextBox()
        self._log_box.Multiline = True
        self._log_box.ReadOnly = True
        self._log_box.ScrollBars = ScrollBars.Both
        self._log_box.WordWrap = False
        self._log_box.Font = Font(FontFamily.GenericMonospace, 9.0)
        self._log_box.Dock = DockStyle.Fill
        self._log_box.Text = ""

        # --- ORDEM DOS CONTROLES (ver aviso no topo do metodo) ---
        # Dentro de steps_panel, todos com Dock.Top: inseridos na ordem
        # INVERSA da posicao visual desejada (o ultimo Add() fica no topo).
        for ctrl in (
            self._delete_button, review_row, spacer4, debug_row, spacer3,
            self._create_status, self._create_button, spacer2,
            solve_console_holder,
            self._solve_status, self._solve_button, spacer1,
            self._catalog_status,
        ):
            steps_panel.Controls.Add(ctrl)

        # Nivel da janela: o Dock.Fill (log_box) PRECISA ser o PRIMEIRO
        # Controls.Add de todos, senao ele ocupa o painel inteiro e esconde
        # qualquer ancorado (Top/Bottom) adicionado antes dele - mesma regra
        # ja usada em _SetupForm (body antes de footer/header), e coberta
        # pelo teste test_controles_dock_fill_entram_antes_dos_ancorados.
        # Footer (Bottom) pode vir em qualquer ordem em relacao aos Top,
        # so' precisa vir DEPOIS do Fill. Os Top (steps_panel/errors_panel/
        # cards/header) continuam em ordem INVERSA da posicao visual
        # desejada (header por ultimo, para ficar no topo de tudo).
        self.Controls.Add(self._log_box)
        self.Controls.Add(footer)
        self.Controls.Add(steps_panel)
        self.Controls.Add(errors_panel)
        self.Controls.Add(cards)
        self.Controls.Add(header)

        # Log inicial: mesmo conteudo que as antigas abas Resumo/Ocorrencias
        # (build_report_highlights/build_report_issues, chamadas em main()),
        # agora tudo junto no rodape em vez de abas separadas.
        initial_log_parts = []
        if report.get("highlights"):
            initial_log_parts.append("\n".join(report["highlights"]))
        issues = report.get("issues") or []
        if issues:
            issue_lines = ["=== Ocorrencias ==="]
            for severity, category, text in issues:
                issue_lines.append("[{}] {}: {}".format(severity.upper(), category, text))
            initial_log_parts.append("\n".join(issue_lines))
        if initial_log_parts:
            self._log_box.Text = "\r\n\r\n".join(p.replace("\n", "\r\n") for p in initial_log_parts)

        self._apply_catalog_status()

    # ---------------------------------------------- erros / ajustar erros
    def _populate_error_rows(self, error_rows):
        self._errors_grid.Items.Clear()
        for row in error_rows:
            item = ListViewItem("-" if row.get("wall_idx") is None else str(row["wall_idx"]))
            item.SubItems.Add(row["problem_text"])
            item.SubItems.Add(
                "Corrigido" if row.get("resolved")
                else ("Auto-corrigivel" if row["auto_fixable"] else "Revisao manual")
            )
            item.ForeColor = (
                self._UI_OK if row.get("resolved")
                else (self._UI_TEXT if row["auto_fixable"] else self._UI_WARN)
            )
            item.Tag = list(row["wall_ids"])
            self._errors_grid.Items.Add(item)

    def _on_error_row_selected(self, sender, args):
        selected = self._errors_grid.SelectedItems
        if len(selected) == 0:
            return
        item = selected[0]
        wall_ids = item.Tag
        if not wall_ids:
            return
        self._handler.pending_zoom_ids = wall_ids
        self._raise_action("zoom", self._on_zoom_done, self._errors_status)

    def _on_zoom_done(self, kind, error):
        # O efeito principal e' na vista do Revit (nao ha' widget pra
        # atualizar aqui) - mas uma falha NUNCA pode ficar muda: sem isto,
        # "clicar na linha e nao acontecer nada visivel" era indistinguivel
        # de um bug de zoom de verdade.
        #
        # `if kind == "error":` (nao `if error:`) DE PROPOSITO em TODOS os
        # `_on_*_done` desta janela (ver os outros abaixo): `error` e'
        # `str(ex)` (ver Execute() de _PostCreationEventHandler) e uma
        # excecao levantada SEM mensagem (ex.: `raise Exception()`) tem
        # `str(ex) == ""` - uma string vazia e' falsy em Python, entao
        # `if error:` tratava esse caso como SUCESSO silencioso mesmo tendo
        # havido uma excecao de verdade. `kind` e' o sinal inequivoco (a
        # string literal "error", atribuida so' no ramo `except` de
        # Execute()) - nunca depende do CONTEUDO da mensagem.
        if kind == "error":
            self._errors_status.ForeColor = self._UI_WARN
            self._errors_status.Text = "Falha ao dar zoom na parede: {}".format(error)

    def _on_fix_click(self, sender, args):
        self._set_busy(self._fix_button, "Ajustando...")
        self._fix_cancel_requested = False
        self._fix_paused = False

        # Callbacks AO VIVO (mesmo padrao de _WallReviewForm._on_start_click)
        # - "Ajustar Erros" era o unico botao desta janela sem log
        # incremental nem Cancelar/Pausar (ver fix_all_wall_modulation_errors,
        # FASE 0/1 do plano em C:\Users\CIVIX\.claude\plans\quiet-painting-petal.md).
        def _progress_cb(*cb_args):
            if len(cb_args) == 1:
                self._append_log(cb_args[0])

        def _should_cancel():
            return self._fix_cancel_requested

        def _should_pause():
            return self._fix_paused

        self._handler.progress_cb = _progress_cb
        self._handler.should_cancel_cb = _should_cancel
        self._handler.should_pause_cb = _should_pause

        self._fix_cancel_button.Visible = True
        self._fix_cancel_button.Enabled = True
        self._fix_cancel_button.Text = "Cancelar"
        self._pause_button.Visible = True
        self._pause_button.Enabled = True
        self._pause_button.Text = "Pausar"

        if not self._raise_action("fix_errors", self._on_fix_done, self._errors_status):
            self._fix_button.Text = "Ajustar Erros"
            self._fix_button.Enabled = True
            self._fix_cancel_button.Visible = False
            self._pause_button.Visible = False

    def _on_fix_cancel_click(self, sender, args):
        # Mesma semantica do Cancelar de _WallReviewForm: so' PEDE, nunca
        # desfaz o que ja foi commitado (cada linha e' um SubTransaction
        # isolado - ver fix_all_wall_modulation_errors). `_fix_paused` e'
        # zerado aqui pelo mesmo motivo documentado em
        # _WallReviewForm._on_cancel_click.
        self._fix_cancel_requested = True
        self._fix_paused = False
        self._fix_cancel_button.Enabled = False
        self._fix_cancel_button.Text = "Cancelando..."
        self._pause_button.Enabled = False
        self._append_log("Cancelamento solicitado pelo usuario - parando assim que possivel, mantendo o que ja foi aplicado.")

    def _on_pause_click(self, sender, args):
        self._fix_paused = not self._fix_paused
        if self._fix_paused:
            self._pause_button.Text = "Continuar"
            self._append_log("PAUSADO - clique em 'Continuar' para retomar.")
        else:
            self._pause_button.Text = "Pausar"
            self._append_log("Retomado pelo usuario.")

    def _on_fix_done(self, kind, error):
        self._fix_button.Text = "Ajustar Erros"
        self._fix_cancel_button.Visible = False
        self._pause_button.Visible = False
        if kind == "error":
            self._errors_status.ForeColor = self._UI_WARN
            self._errors_status.Text = "Falha ao ajustar: {}".format(error)
            self._append_log("=== Ajustar Erros ===\nFalha ao disparar a correcao: {}".format(error))
            self._fix_button.Enabled = True
            return
        updated_rows = self._handler.error_rows
        self._populate_error_rows(updated_rows)
        fixed_count = sum(1 for r in updated_rows if r.get("resolved"))
        manual_count = len(updated_rows) - fixed_count
        self._errors_status.ForeColor = self._UI_OK if manual_count == 0 else self._UI_WARN
        self._errors_status.Text = (
            "Modulacao concluida: {} corrigida(s) automaticamente, {} exigem "
            "revisao manual.".format(fixed_count, manual_count)
        )
        # Motivo POR EIXO no log - antes so' existia na coluna "Situacao" da
        # grade (facil de nao notar, ver relato do usuario "clico e nada
        # acontece": o botao mudava para "Concluido" mesmo com 0 corrigidas,
        # sem nenhuma explicacao visivel do motivo). Lista SO' as linhas que
        # continuam nao resolvidas - as ja corrigidas ja tem seu texto no
        # proprio problem_text ("corrigido automaticamente...").
        unresolved_details = [
            "  - eixo {}: {}".format(r.get("wall_idx"), r.get("problem_text"))
            for r in updated_rows if not r.get("resolved")
        ]
        log_lines = [
            "=== Ajustar Erros ===",
            "{} corrigida(s) automaticamente, {} exigem revisao manual.".format(
                fixed_count, manual_count
            ),
        ]
        if unresolved_details:
            log_lines.append("Motivo de cada eixo nao corrigido:")
            log_lines.extend(unresolved_details)
        self._append_log("\n".join(log_lines))
        self._fix_button.Enabled = False
        # "Concluido" sozinho, com 0 corrigidas, parecia sucesso quando na
        # verdade nada mudou no modelo - texto agora reflete o resultado real.
        self._fix_button.Text = "Concluido" if fixed_count > 0 else "Nenhuma corrigida"
        self._release_solve_step_if_ready()

    # ---------------------------------------------------- catalogo/blocos
    def _release_solve_step_if_ready(self):
        if self._handler.catalog_missing:
            return
        self._solve_button.Enabled = True
        self._solve_status.Text = "Pronto para calcular."
        self._solve_status.ForeColor = self._UI_TEXT

    def _apply_catalog_status(self):
        """Mostra o resultado do catalogo FIXO (ja carregado por
        load_fixed_block_catalog antes desta janela existir, ver
        _show_post_creation_window). Nunca oferece montar/selecionar
        catalogo de novo - familia ausente e' erro bloqueante, reportado
        exatamente. "Lancar Blocos" so' libera de fato depois de "Ajustar
        Erros" (ver _on_fix_done) OU direto aqui, se nao havia nenhum erro
        auto-corrigivel para ajustar."""
        catalog = self._handler.catalog
        missing = self._handler.catalog_missing
        codes = sorted(catalog.keys())
        if missing:
            self._catalog_status.Text = (
                "Catalogo: {} tipo(s) OK, {} ausente(s) - veja o log.".format(
                    len(codes), len(missing)
                )
            )
            self._catalog_status.ForeColor = self._UI_WARN
            report_lines = ["=== Catalogo fixo de blocos ==="]
            report_lines.append("Tipos encontrados: {}".format(", ".join(codes) or "nenhum"))
            report_lines.append("Familia(s)/tipo(s) FALTANDO no projeto ({}):".format(len(missing)))
            for m in missing:
                report_lines.append(
                    "  - {}: familia '{}' / tipo '{}' - {}".format(
                        m["logical_code"], m["family_name"], m["type_name"], m["reason"]
                    )
                )
            report_lines.append(
                "Carregue a(s) familia(s)/tipo(s) acima no projeto (exatamente "
                "com este nome) e rode o botao de novo - o sistema nao "
                "substitui por outra familia parecida."
            )
            self._append_log("\n".join(report_lines))
            self._solve_status.Text = "Bloqueado: falta(m) familia(s) no catalogo (veja o log)."
            self._solve_status.ForeColor = self._UI_WARN
            # Alerta MODAL (nao so' o rotulo laranja acima, facil de passar
            # despercebido numa tela com bastante informacao) - pedido do
            # usuario: nenhuma etapa pode deixar o usuario sem saber o que
            # fazer. Disparado uma unica vez, ao abrir a Tela 2 (nao a cada
            # re-render de status).
            missing_lines = "\n".join(
                "  - {}: familia '{}' / tipo '{}'".format(
                    m["logical_code"], m["family_name"], m["type_name"]
                ) for m in missing
            )
            forms.alert(
                "Nao e' possivel lancar os blocos ainda - {} familia(s)/tipo(s) do "
                "catalogo fixo NAO estao carregadas neste projeto:\n\n{}\n\n"
                "Carregue essa(s) familia(s)/tipo(s) no Revit (Inserir > Carregar "
                "Familia), com EXATAMENTE esses nomes, e reabra a Tela 2 (reselecione "
                "as paredes) para continuar.".format(len(missing), missing_lines),
                title="Modulacao Automatica - Etapa 2: familia(s) de bloco faltando"
            )
            return

        self._catalog_status.Text = "Catalogo: {} tipo(s) OK ({}).".format(
            len(codes), ", ".join(codes)
        )
        self._catalog_status.ForeColor = self._UI_OK
        report_lines = ["=== Catalogo fixo de blocos ===", "Tipos: {}".format(", ".join(codes))]
        for code in codes:
            entry = catalog[code]
            report_lines.append(
                "  - {}: {:.1f} x {:.1f} x {:.1f} cm (comp x larg x alt), {} celula(s)".format(
                    code, entry["length_cm"], entry["width_cm"], entry["height_cm"],
                    len(entry.get("cells_local") or [])
                )
            )
        self._append_log("\n".join(report_lines))
        if not self._fix_button.Enabled:
            # nao ha' (ou nao havia) nenhum erro auto-corrigivel esperando
            # "Ajustar Erros" - libera "Lancar Blocos" direto, sem obrigar
            # um clique num botao que nao teria nada para fazer.
            self._release_solve_step_if_ready()

    def _append_log(self, text):
        current = self._log_box.Text
        sep = "\r\n\r\n" if current else ""
        self._log_box.Text = current + sep + text.replace("\n", "\r\n")
        self._log_box.SelectionStart = len(self._log_box.Text)
        self._log_box.ScrollToCaret()

    def _set_busy(self, button, busy_text):
        button.Enabled = False
        button.Text = busy_text

    def _raise_action(self, action, on_done, status_label):
        """Dispara `action` no ExternalEvent - trecho comum aos botoes
        desta janela. `Raise()` (e a preparacao do handler logo antes)
        rodam no thread da UI, FORA do Execute() do ExternalEvent - o
        try/except de Execute() nao protege esta parte. Um try/except
        aqui tambem evita que qualquer falha nesta preparacao (canal
        indisponivel, estado inconsistente) derrube o Revit inteiro com
        uma excecao nao tratada em vez de so' aparecer no status."""
        if self._external_event is None:
            status_label.ForeColor = self._UI_WARN
            status_label.Text = "Canal de aplicacao indisponivel nesta execucao."
            return False
        try:
            self._handler.action = action
            self._handler.on_done = on_done
            self._external_event.Raise()
            return True
        except Exception as ex:
            status_label.ForeColor = self._UI_WARN
            status_label.Text = "Falha ao disparar a acao: {}".format(ex)
            return False

    def _on_solve_click(self, sender, args):
        self._set_busy(self._solve_button, "Calculando...")
        console = self._solve_console
        console.log("Iniciando Solver 18 (lancamento de blocos X->T->L->jambs->trechos livres)...")
        console.set_status("Iniciando Solver 18...")
        console.set_indeterminate("Preparando bandas/fiadas...")
        console.start_watchdog()

        # Callbacks AO VIVO do Solver 18 - closures locais (nao pelo nome do
        # modulo), mesmo cuidado documentado no __init__ desta janela: o
        # handler pode chamar isto bem depois, com o Script.py ja
        # reexecutado por outro clique.
        # Paredes ja concluidas NESTA banda - ver o comentario em
        # `_wall_result_cb` (bug da barra parada em 99%).
        solved_count = {"done": 0}

        def _band_cb(band_idx, total_bands, course_indices):
            try:
                label = "banda {}/{} (fiada(s) {})".format(
                    band_idx, total_bands, ", ".join(str(c + 1) for c in course_indices)
                )
                console.log("Solver 18: iniciando {}...".format(label))
                console.set_status("Solver 18: processando {}...".format(label))
                # cada banda percorre as paredes de novo, do zero.
                solved_count["done"] = 0
            except Exception:
                pass

        def _progress_cb(done, total):
            try:
                console.set_progress(done, total, "{}/{} parede(s) processada(s) nesta banda".format(done, total))
            except Exception:
                pass

        # BUG REAL (2026-08-27): a barra NUNCA chegava a 100%. `_wall_start_cb`
        # reportava `pos - 1` ("paredes ja concluidas"), e o laco de
        # `process_walls_one_by_one` chama `progress_cb` ANTES de
        # `wall_start_cb` - entao o 306/306 que o `_progress_cb` marcava na
        # ultima volta era imediatamente sobrescrito de volta para 305/306
        # (99%) pelo `set_progress(pos - 1, total)` daquela mesma volta. A
        # barra ficava parada em "305/306 processado(s) - 99%" durante TODA a
        # etapa final (colisoes, vaos de porta, auditoria de amarracao), que
        # e' justamente onde o solver mais demorava - dando a impressao de
        # travamento exatamente onde nada mais estava sendo reportado.
        # Agora quem avanca a barra e' o RESULTADO de cada parede (a parede
        # concluida de verdade), contado aqui na closure - `wall_result_cb`
        # e' chamado uma vez por parede nos DOIS caminhos do laco (resolvida
        # e reusada do baseline), entao o total bate sempre.
        def _wall_start_cb(wall_idx, total, pos):
            try:
                console.log("Solver 18 analisando parede (eixo {})... ({}/{})".format(wall_idx, pos, total))
                console.set_status("Solver 18 buscando solucao - eixo {}...".format(wall_idx))
                console.set_progress(min(solved_count["done"], pos - 1), total)
            except Exception:
                pass

        def _wall_result_cb(wall_idx, total, ok, detail):
            try:
                if ok:
                    console.log("Eixo {}: solucao encontrada.".format(wall_idx))
                else:
                    console.log("Eixo {}: tentativa falhou ({}) - tentando alternativa/proxima parede.".format(
                        wall_idx, detail
                    ))
                solved_count["done"] += 1
                console.set_progress(solved_count["done"], total)
            except Exception:
                pass

        def _stage_cb(label):
            # ETAPA FINAL (depois da ultima parede de cada banda): as
            # checagens globais - colisoes, vaos de porta, compensadores,
            # auditoria de amarracao. Nao ha' contador de parede para mostrar
            # aqui, entao a barra vira marquee e o texto diz o que esta
            # rodando: sem isso a janela ficava muda justamente no trecho que
            # ja' travou o script em producao (2026-08-27).
            try:
                console.log("Solver 18: {}...".format(label))
                console.set_status("Solver 18: {}...".format(label))
                console.set_indeterminate(label)
            except Exception:
                pass

        self._handler.solve_progress_cb = {
            "band_cb": _band_cb, "progress_cb": _progress_cb,
            "wall_start_cb": _wall_start_cb, "wall_result_cb": _wall_result_cb,
            "stage_cb": _stage_cb,
        }
        if not self._raise_action("solve", self._on_solve_done, self._solve_status):
            console.stop_watchdog()
            console.mark_failed("Falha ao disparar o Solver 18.")
            self._solve_button.Text = "Lancar Blocos - calcular (solver X->T->L->jambs->trechos livres)"
            self._solve_button.Enabled = True

    def _on_solve_done(self, kind, error, auto_create=True):
        self._solve_console.stop_watchdog()
        self._solve_button.Text = "Lancar Blocos - calcular (solver X->T->L->jambs->trechos livres)"
        self._solve_button.Enabled = True
        if kind == "error":
            self._solve_status.Text = "Falha: {}".format(error)
            self._solve_status.ForeColor = self._UI_WARN
            self._solve_console.mark_failed("Solver 18 falhou: {}".format(error))
            return
        result = self._handler.solve_result
        self._solve_console.mark_complete(
            "Solver 18 concluido - {} candidato(s) de bloco calculado(s).".format(
                len(result.get("candidates") or [])
            )
        )
        report, _ready_to_create = self._format_block_solve_report(result, self._handler.catalog)
        self._append_log(report)
        door_violations = result.get("door_void_violations") or []
        wall_bond_audits = result.get("wall_bond_audits") or {}
        reproved_bond_count = sum(1 for audit in wall_bond_audits.values() if not audit["ok"])
        # REGRA REVISTA 2026-08-26: nenhum diagnostico (colisao, vao de
        # porta, auditoria de amarracao) bloqueia mais o botao "criar" - o
        # unico motivo para desabilita-lo agora e' nao haver candidato
        # nenhum para criar. Os problemas continuam sendo mostrados aqui e
        # no log, e as pecas envolvidas saem marcadas em vermelho depois de
        # criadas (ver _execute_create) - nunca impedem a criacao.
        self._solve_status.Text = (
            "{} candidato(s), {} colisao(oes), {} violacao(oes) de vao de porta, "
            "{} parede(s) reprovada(s) na auditoria de amarracao entre fiadas "
            "[todos criados mesmo assim, marcados em vermelho para revisao]."
        ).format(
            len(result["candidates"]), len(result["collisions"]), len(door_violations),
            reproved_bond_count
        )
        has_candidates = len(result["candidates"]) > 0
        self._solve_status.ForeColor = self._UI_OK if has_candidates else self._UI_WARN
        self._create_button.Enabled = has_candidates
        if not has_candidates:
            self._solve_status.Text += " Nenhum candidato de bloco calculado - veja o log, mais abaixo."
            self._create_status.Text = "Nada para criar: o solver nao calculou nenhum candidato de bloco."
            self._create_status.ForeColor = self._UI_WARN
        elif door_violations or reproved_bond_count or result["collisions"]:
            self._create_status.Text = (
                "Pronto para criar. {} problema(s) encontrado(s) (colisao/vao de porta/amarracao) - "
                "os blocos serao criados mesmo assim e as pecas/paredes envolvidas ficarao marcadas em "
                "vermelho para revisao manual; nada e' bloqueado."
            ).format(len(door_violations) + reproved_bond_count + len(result["collisions"]))
            self._create_status.ForeColor = self._UI_WARN
        else:
            self._create_status.Text = "Pronto para criar."
            self._create_status.ForeColor = self._UI_TEXT

        # Pedido explicito do usuario (2026-08-27): a Etapa 2 nunca pode
        # parar so' no calculo - "nao quero que o script apenas calcule,
        # mostre sugestoes... os blocos precisam ser fisicamente inseridos
        # no modelo do Revit". Assim que houver ao menos um candidato,
        # dispara a criacao automaticamente, sem esperar um segundo clique
        # manual em "Lancar Blocos - criar" (que continua existindo/
        # habilitado, para o usuario poder re-disparar depois de um novo
        # "Ajustar Erros"/recalculo). `auto_create=False` so' quando este
        # metodo e' chamado para REPLAY de um solve_result em cache (janela
        # reaberta com o MESMO conjunto de paredes - ver _show_post_creation_
        # window/initial_solve_result) - nesse caso nunca cria sozinho, so'
        # mostra o estado ja calculado (o replay de create_result, se
        # houver, e' feito separadamente pelo chamador).
        if has_candidates and auto_create:
            self._on_create_click(None, None)

    def _on_create_click(self, sender, args):
        self._set_busy(self._create_button, "Criando blocos...")
        if not self._raise_action("create", self._on_create_done, self._create_status):
            self._create_button.Text = "Lancar Blocos - criar no Revit (todas as fiadas ate o pe-direito)"
            self._create_button.Enabled = True

    def _on_create_done(self, kind, error, show_summary_alert=True):
        self._create_button.Text = "Lancar Blocos - criar no Revit (todas as fiadas ate o pe-direito)"
        self._create_button.Enabled = True
        if kind == "error":
            self._create_status.Text = "Falha: {}".format(error)
            self._create_status.ForeColor = self._UI_WARN
            return
        result = self._handler.create_result
        report_lines = ["=== Criacao dos blocos no Revit ==="]
        if result.get("course_height_error"):
            report_lines.append("Erro: {}".format(result["course_height_error"]))
        else:
            report_lines.append(
                "Altura de fiada: {:.2f}cm - {} instancia(s) criada(s).".format(
                    result["course_height_ft"] / FEET_PER_METER * 100.0 if result["course_height_ft"] else 0.0,
                    result["created_count"]
                )
            )
        if result["failures"]:
            report_lines.append("Falhas ({}):".format(len(result["failures"])))
            for f in result["failures"][:20]:
                report_lines.append("  - {}".format(f))
            if len(result["failures"]) > 20:
                report_lines.append("  - ... e mais {}.".format(len(result["failures"]) - 20))
        colliding_count = result.get("colliding_instance_count") or 0
        reproved_wall_count = result.get("reproved_wall_count") or 0
        if colliding_count:
            report_lines.append(
                "Marcados em VERMELHO para revisao manual: {} peca(s) em colisao.".format(colliding_count)
            )
        if reproved_wall_count:
            report_lines.append(
                "{} parede(s) reprovada(s) na auditoria de amarracao entre fiadas - os blocos foram "
                "criados normalmente mesmo assim (regra revista 2026-08-26: diagnostico nao bloqueia "
                "criacao) e as pecas dessas paredes ficam marcadas em VERMELHO na vista para revisao "
                "manual. Eixo(s): {}.".format(
                    reproved_wall_count,
                    ", ".join(str(wi) for wi in (result.get("reproved_wall_idxs") or [])[:30])
                )
            )
        if result["created_count"] == 0:
            report_lines.append(
                "!!! NENHUM BLOCO FOI CRIADO NO REVIT !!! Verifique o motivo acima "
                "(erro de altura de fiada, falhas por candidato, ou nenhum candidato calculado no "
                "solver) - a modulacao NAO pode ser considerada concluida enquanto created_count for 0."
            )
        self._append_log("\n".join(report_lines))

        # RELATORIO FINAL CONSOLIDADO (pedido explicito do usuario,
        # 2026-08-25, item 4/5) - so' pode ser montado AQUI, no fim de
        # tudo: precisa do resultado da Etapa 3B (self._handler.error_rows,
        # ja' com "resolved" preenchido por "Ajustar Erros") E da Etapa 4C
        # (wall_bond_audits/reproved_wall_idxs, so' existem apos "Lancar
        # Blocos - criar"). Paredes reprovadas JA' recebem bloco (marcado em
        # vermelho) desde 2026-08-26, mas continuam entrando aqui como "nao
        # totalmente bem sucedidas" para fins de relatorio/revisao manual.
        final_report = self._build_final_modulation_report(
            self._handler.walls_to_create, self._handler.error_rows,
            wall_bond_audits=(self._handler.solve_result or {}).get("wall_bond_audits"),
            skipped_wall_idxs=result.get("reproved_wall_idxs"),
        )
        self._append_log(self._format_final_modulation_report(final_report))

        self._create_status.Text = "{} bloco(s) criado(s), {} falha(s).".format(
            result["created_count"], len(result["failures"])
        )
        if colliding_count:
            self._create_status.Text += " {} peca(s) em colisao marcada(s) em vermelho.".format(colliding_count)
        if reproved_wall_count:
            self._create_status.Text += " {} parede(s) com amarracao reprovada (criadas e marcadas em vermelho).".format(reproved_wall_count)
        if result["created_count"] == 0:
            self._create_status.Text = "ALERTA: nenhum bloco foi criado! " + self._create_status.Text
        self._create_status.ForeColor = self._UI_OK if result["created_count"] > 0 else self._UI_WARN

        has_blocks = result["created_count"] > 0
        for ctrl in (self._debug_color_check, self._debug_filter_both,
                     self._debug_filter_a, self._debug_filter_b):
            ctrl.Enabled = has_blocks
        self._update_delete_enabled()

        # RESUMO FINAL, em ALERTA MODAL - pedido explicito do usuario (item
        # 8): "ao terminar, mostrar um resumo simples: paredes selecionadas;
        # paredes processadas; blocos inseridos; paredes com erro; motivo
        # dos erros". O log acima ja tem tudo em detalhe, mas um log rolavel
        # e' facil de nao ler ate o fim - o alerta garante que o resultado
        # chega ao usuario de qualquer jeito. So' dispara na execucao REAL
        # (nunca ao reabrir a janela com um create_result em cache - ver
        # _show_post_creation_window/initial_create_result).
        if show_summary_alert:
            self._show_final_block_summary_alert(result)

    def _show_final_block_summary_alert(self, create_result):
        solve_result = self._handler.solve_result or {}
        per_wall = solve_result.get("per_wall") or []
        walls_selected = len(self._handler.walls_to_create or [])
        walls_processed = len(per_wall)

        problem_walls = {}
        for entry in per_wall:
            validation = entry.get("validation") or {}
            if not validation.get("ok", True):
                problem_walls[entry["wall_idx"]] = list(validation.get("problems") or [
                    "reprovada na validacao final do solver"
                ])
        for entry in (solve_result.get("non_modular") or []):
            problem_walls.setdefault(entry["wall_idx"], []).append(
                "trecho nao-modular: fiada {} trecho {} ({:.1f}cm, mais proximo que fecha: "
                "{}cm)".format(
                    entry["course"], entry["segment_index"],
                    entry["current_length_cm"], entry["lower_valid_cm"]
                )
            )
        for failure_text in (create_result.get("failures") or []):
            problem_walls.setdefault("?", []).append(str(failure_text))

        lines = [
            "Paredes selecionadas: {}".format(walls_selected),
            "Paredes processadas: {}".format(walls_processed),
            "Blocos inseridos no Revit: {}".format(create_result["created_count"]),
            "Paredes com erro: {}".format(len(problem_walls)),
        ]
        if problem_walls:
            lines.append("")
            lines.append("Motivo de cada parede com erro:")
            for wall_idx, reasons in sorted(problem_walls.items(), key=lambda kv: str(kv[0]))[:30]:
                lines.append("  - eixo {}: {}".format(wall_idx, "; ".join(reasons[:3])))
            if len(problem_walls) > 30:
                lines.append("  - ... e mais {}.".format(len(problem_walls) - 30))
        if create_result["created_count"] == 0:
            lines.insert(0, "!!! NENHUM BLOCO FOI CRIADO NO REVIT - veja os motivos abaixo. !!!")

        forms.alert(
            "\n".join(lines),
            title="Modulacao Automatica - Resumo final da Etapa 2 (Modulacao dos Blocos)"
        )

    def _on_debug_change(self, sender, args):
        if not (self._handler.create_result and self._handler.create_result.get("created_instances")):
            return
        self._handler.debug_color_by_code = self._debug_color_check.Checked
        if self._debug_filter_a.Checked:
            self._handler.debug_course_filter = "A"
        elif self._debug_filter_b.Checked:
            self._handler.debug_course_filter = "B"
        else:
            self._handler.debug_course_filter = None
        if self._external_event is None:
            self._append_log("Falha ao aplicar modo debug visual: canal de aplicacao indisponivel.")
            return
        try:
            self._handler.action = "debug_view"
            self._handler.on_done = self._on_debug_done
            self._external_event.Raise()
        except Exception as ex:
            self._append_log("Falha ao aplicar modo debug visual: {}".format(ex))

    def _on_debug_done(self, kind, error):
        if kind == "error":
            self._append_log("Falha ao aplicar modo debug visual: {}".format(error))

    def _on_review_change(self, sender, args):
        self._update_delete_enabled()

    def _update_delete_enabled(self):
        solve_ok = bool(
            self._handler.solve_result
            and len(self._handler.solve_result["collisions"]) == 0
            and len(self._handler.solve_result.get("door_void_violations") or []) == 0
        )
        create_ok = bool(
            self._handler.create_result and self._handler.create_result.get("created_count", 0) > 0
        )
        self._delete_button.Enabled = (
            solve_ok and create_ok and self._review_check.Checked
        )

    def _on_delete_click(self, sender, args):
        # `forms.alert(..., yes=True, no=True)` em vez de `MessageBox.Show`
        # direto: MessageBox.Show quebrou no mesmo engine CPython (pythonnet)
        # deste pyRevit ("type object 'MessageBox' has no attribute 'Show'",
        # AttributeError real medido em producao, 2026-08-27) - `forms.alert`
        # ja' e' o `_compat_alert` do loader (Script.py), que contorna esse
        # bug usando Microsoft.VisualBasic.Interaction.MsgBox.
        confirm = forms.alert(
            "Isto vai excluir permanentemente as {} parede(s) de referencia "
            "criadas nesta execucao (ja substituidas pelos blocos). Esta acao "
            "NAO pode ser desfeita pelo botao 'Cancelar' - so pelo Undo "
            "(Ctrl+Z) do Revit logo em seguida.\n\nConfirma a exclusao?".format(
                self._created_wall_count
            ),
            title="Finalizar - Confirmar exclusao das paredes",
            yes=True, no=True
        )
        if not confirm:
            return
        self._set_busy(self._delete_button, "Excluindo...")
        if self._external_event is None:
            self._append_log("Falha ao excluir paredes: canal de aplicacao indisponivel.")
            self._delete_button.Enabled = True
            return
        try:
            self._handler.action = "delete"
            self._handler.on_done = self._on_delete_done
            self._external_event.Raise()
        except Exception as ex:
            self._append_log("Falha ao excluir paredes: {}".format(ex))
            self._delete_button.Enabled = True

    def _on_delete_done(self, kind, error):
        self._delete_button.Text = "Finalizar - Excluir as {} parede(s) de referencia".format(
            self._created_wall_count
        )
        if kind == "error":
            self._append_log("Falha ao excluir paredes: {}".format(error))
            self._delete_button.Enabled = True
            return
        result = self._handler.create_result or {}
        deleted = result.get("deleted_wall_count", 0)
        delete_failures = result.get("delete_failures", [])
        kept_no_blocks = result.get("kept_wall_count_no_blocks", 0)
        report_lines = [
            "=== Finalizar - Exclusao das paredes ===",
            "{} parede(s) excluida(s).".format(deleted),
        ]
        if kept_no_blocks:
            report_lines.append(
                "{} parede(s) de referencia MANTIDA(S) de proposito (reprovadas na auditoria de "
                "amarracao entre fiadas - regra #1, nunca ficaram sem bloco E sem parede de "
                "referencia ao mesmo tempo) - revise manualmente e rode o script de novo nesse "
                "trecho quando corrigir.".format(kept_no_blocks)
            )
        if delete_failures:
            report_lines.append("Falhas ({}):".format(len(delete_failures)))
            for f in delete_failures[:20]:
                report_lines.append("  - {}".format(f))
        self._append_log("\n".join(report_lines))
        self._delete_button.Enabled = False
        self._delete_button.Text = "Concluido - {} parede(s) excluida(s).".format(deleted)

    # ------------------------------------------------------------- outros
    def _on_copy(self, sender, args):
        ok = self._copy_text_to_clipboard(self._log_box.Text)
        self._footer_note.ForeColor = self._UI_OK if ok else self._UI_WARN
        self._footer_note.Text = (
            "Log copiado para a area de transferencia (Ctrl+V para colar)." if ok
            else "Nao foi possivel copiar - o log continua salvo em: {}".format(
                self._report.get("log_path") or "(arquivo nao gravado)"
            )
        )


def _show_post_creation_window(report, walls_to_create, openings_per_wall, created_walls_by_axis,
                               created_wall_ids_all, all_openings, wall_graph_nodes,
                               wall_end_to_node, selected_level, base_z_abs, wall_height_ft,
                               wall_error_rows, catalog=None, catalog_missing=None,
                               wall_segment_geometry=None, initial_solve_result=None,
                               initial_create_result=None, precreated_event=None,
                               precreated_handler=None):
    """Cria o ExternalEvent + handler (_PostCreationEventHandler) e mostra a
    janela unica de modulacao (_PostCreationForm) - guarda a referencia em
    _ACTIVE_MODELESS_WINDOWS pelo mesmo motivo/cuidado documentado no topo
    da secao JANELAS MODELESS (main() retorna assim que a janela abre, e
    sem essa referencia o coletor de lixo do IronPython derrubaria janela e
    ExternalEvent junto).

    O catalogo de blocos e' PASSADO pelo chamador (`catalog`/`catalog_missing`)
    desde que main() passou a precisar dele mais cedo, para
    analyze_created_walls_for_errors rodar o solver de blocos de verdade
    (ETAPA 3B reescrita 2026-08-20) - se vier None (chamador antigo/teste),
    ainda carrega aqui como antes, so' pra manter compatibilidade. Se alguma
    familia estiver faltando, a janela ainda abre (para o usuario ver o log
    com a lista exata do que falta), so' com "Lancar Blocos" bloqueado - ver
    _PostCreationForm._apply_catalog_status.

    O cleanup no FormClosed e' um closure LOCAL (nao uma lambda chamando
    uma funcao do modulo pelo nome) DE PROPOSITO - mesmo cuidado
    documentado nas janelas modeless anteriores: o pyRevit reexecuta este
    Script.py do zero a cada clique no botao, e uma lambda que resolve um
    NOME de funcao do modulo so' na hora do evento quebra com
    "UnboundNameException".

    `initial_solve_result`/`initial_create_result` (pedido explicito do
    usuario, 2026-08-27): quando o CHAMADOR ja' tem um resultado de solve/
    create de uma execucao anterior para este MESMO conjunto de paredes
    (ver _LAST_MODULATION_STATE/_wall_ids_signature - so' acontece hoje no
    fluxo "utilizar paredes existentes", onde reselecionar as mesmas Wall
    devolve os mesmos ElementId), a janela abre JA' "resolvida"/"criada" -
    os botoes "Lancar Blocos - calcular"/"criar" refletem esse estado
    reaproveitado (ver _on_solve_done/_on_create_done abaixo) em vez de
    exigir clicar em "calcular" de novo so' porque a janela anterior foi
    fechada."""
    if catalog is None:
        catalog, catalog_missing = load_fixed_block_catalog(doc)

    # `precreated_event`/`precreated_handler` (corrige bug real 2026-08-27,
    # "Attempting to create an ExternalEvent outside of a standard API
    # execution"): quem chama esta funcao a partir de um callback de
    # sucesso do `_PostCreationEventHandler` da ETAPA 1 (acao "analyze",
    # ver _execute_analyze) chega aqui via `self.on_done` marshalado de
    # volta pro thread de UI com `Control.BeginInvoke` (ui_invoke_cb) - ou,
    # no botao "Pular para Modulacao dos Blocos", direto de um Click de
    # WinForms - nenhum dos dois casos esta' mais dentro da execucao da
    # API do Revit (Execute() ja retornou), entao `ExternalEvent.Create`
    # AQUI lanca `InvalidOperationException`. O chamador (ver
    # run_modulation_on_existing_walls/main(), fluxo classico) agora cria
    # ESTE ExternalEvent mais cedo, ainda dentro da execucao sincrona da
    # API (antes de abrir a janela da ETAPA 1), e passa a instancia pronta
    # adiante - sem precisar criar outro aqui.
    if precreated_handler is not None:
        handler = precreated_handler
    else:
        handler = _PostCreationEventHandler()
    handler.walls_to_create = walls_to_create
    handler.openings_per_wall = openings_per_wall
    handler.created_walls_by_axis = created_walls_by_axis
    handler.wall_segment_geometry = wall_segment_geometry or {}
    handler.all_openings = all_openings
    handler.wall_graph_nodes = wall_graph_nodes
    handler.wall_end_to_node = wall_end_to_node
    handler.created_wall_ids_all = created_wall_ids_all
    handler.selected_level = selected_level
    handler.base_z_abs = base_z_abs
    handler.wall_height_ft = wall_height_ft
    handler.catalog = catalog
    handler.catalog_missing = catalog_missing
    handler.error_rows = wall_error_rows
    handler.solve_result = initial_solve_result
    handler.create_result = initial_create_result
    external_event = precreated_event if precreated_event is not None else ExternalEvent.Create(handler)

    window = _PostCreationForm(report, external_event, handler, created_wall_ids_all)
    if initial_solve_result is not None:
        # Reaproveita o MESMO caminho que um solve/create de verdade usa
        # para atualizar a janela (status/log/botoes) - nunca uma segunda
        # implementacao paralela que poderia divergir.
        window._on_solve_done("solve", None, auto_create=False)
        if initial_create_result is not None:
            window._on_create_done("create", None, show_summary_alert=False)
    entry = (window, external_event, handler)
    active_list = _ACTIVE_MODELESS_WINDOWS
    active_list.append(entry)

    def _on_closed(sender, args):
        if entry in active_list:
            active_list.remove(entry)
        window._solve_console.close()  # para o watchdog do Solver 18 (ver _ProgressConsole.close)

    window.FormClosed += _on_closed
    window.Show()


# ==========================================
# JANELA DE REVISAO DAS WALLS (ETAPA 1 -> ETAPA 2)
#
# REGRA PRINCIPAL do usuario: criar as Walls e lancar os blocos sao DUAS
# operacoes DIFERENTES. O simples fato de terminar a criacao das Walls
# NUNCA pode iniciar sozinho a modulacao (nem so' o SOLVER em memoria,
# ver analyze_created_walls_for_errors - ETAPA 3B/3C/multi-fiada/
# auditoria inteiras, mesmo sem escrever nada ainda no Revit). main()
# termina a ETAPA 1 (deteccao + criacao das Walls + bonecas + encontros)
# e PARA - abre so' esta janela leve, com o resumo da CRIACAO (nenhum
# dado de modulacao ainda existe nesse momento) e um UNICO botao,
# "Iniciar Modulacao". O usuario decide QUANDO (e SE) clicar, depois de
# orbitar/dar zoom/conferir as Walls reais no Revit. So' esse clique
# dispara a acao "analyze" de _PostCreationEventHandler (ver
# _execute_analyze) e, no callback de sucesso, a janela de resultado de
# verdade (_show_post_creation_window) - exatamente como main() fazia
# tudo de uma vez antes desta separacao.
#
# PROPOSITADAMENTE reaproveita _PostCreationEventHandler (nao uma classe
# nova) - ver o docstring dela para o motivo (uma segunda classe
# implementando IExternalEventHandler quebrava em producao com "interface
# takes exactly one argument").
# ==========================================

class _WallReviewForm(Form):
    """Janela leve mostrada assim que a ETAPA 1 (criacao das Walls) termina
    - ver cabecalho da secao acima. So' tem o resumo da CRIACAO (nenhum
    numero de modulacao/erro/bloco aparece aqui, porque nenhuma analise
    rodou ainda) e o botao "Iniciar Modulacao". MODELESS, igual
    _PostCreationForm - o usuario pode orbitar/dar zoom no Revit com esta
    janela aberta."""

    def __init__(self, stage1_report, external_event, handler, on_start_success, on_start_error):
        # OBRIGATORIO no engine CPython (pythonnet) - ver o mesmo comentario
        # em _SetupForm.__init__ (bug real medido em producao, 2026-08-27,
        # exatamente o crash reportado pelo usuario nesta janela): sem
        # chamar o construtor .NET base ANTES de qualquer propriedade
        # WinForms real ser tocada, o objeto CLR fica com campos internos
        # nulos e `self.Text = ...` (a primeira linha de verdade abaixo)
        # lanca NullReferenceException.
        Form.__init__(self)
        self._handler = handler
        self._external_event = external_event
        self._on_start_success = on_start_success
        self._on_start_error = on_start_error
        # Checado por _dispatch_progress_event/find_wall_group_shift_fixes
        # via self._handler.should_cancel_cb (ver _on_start_click) - so'
        # fica viavel de verdade porque a FASE 1 tambem corrigiu o
        # bombeamento de mensagens durante a ETAPA 3C (sem isso o clique no
        # botao "Cancelar" nunca chegaria ate' aqui enquanto a ETAPA 3C
        # estivesse rodando).
        self._cancel_requested = False
        self._paused = False
        # Mesmo motivo de _PostCreationForm.__init__: capturar como
        # atributo de instancia, nao confiar em resolver pelo nome do
        # modulo quando o Click chegar (pode ser bem depois, com o
        # Script.py ja tendo sido reexecutado do zero por outro clique).
        self._UI_BG = UI_BG
        self._UI_PANEL = UI_PANEL
        self._UI_TEXT = UI_TEXT
        self._UI_MUTED = UI_MUTED
        self._UI_WARN = UI_WARN

        self.Text = "Modulacao Automatica - Tela 1: Modulacao das Paredes (nao bloqueia o Revit)"
        self.Width = 860
        self.Height = 700
        self.MinimumSize = Size(680, 520)
        self.StartPosition = FORM_START_POSITION_CENTER_SCREEN
        self.BackColor = self._UI_BG

        header = _build_header(
            stage1_report.get("title") or "Tela 1 - Modulacao das Paredes",
            stage1_report.get("subtitle") or (
                "Confira as Walls no Revit (orbite, de' zoom, verifique bonecas, "
                "aberturas e encontros) e clique em 'Iniciar Modulacao das Paredes' - "
                "erros e ajustes aparecem AO VIVO no log abaixo. So' depois desta "
                "etapa concluir a Tela 2 (Modulacao dos Blocos) libera. Esta janela "
                "nao bloqueia o Revit."
            )
        )

        cards = Panel()
        cards.Dock = DockStyle.Top
        cards.Height = 86
        cards.BackColor = self._UI_BG
        for caption, value, color in reversed(stage1_report.get("kpis") or []):
            card, spacer = _build_card(caption, value, color)
            cards.Controls.Add(spacer)
            cards.Controls.Add(card)

        footer = Panel()
        footer.Dock = DockStyle.Bottom
        footer.Height = 46
        footer.BackColor = self._UI_BG
        footer.Padding = Padding(18, 4, 18, 8)

        close_button = Button()
        close_button.Text = "Fechar (nao modular agora)"
        close_button.Dock = DockStyle.Right
        close_button.Width = 190
        _style_secondary_button(close_button)
        close_button.Click += lambda s, e: self.Close()

        gap1 = Panel(); gap1.Dock = DockStyle.Right; gap1.Width = 10

        self._status_label = Label()
        self._status_label.Dock = DockStyle.Fill
        self._status_label.Font = _ui_font(8.5)
        self._status_label.ForeColor = self._UI_MUTED
        self._status_label.Text = (
            "As Walls sao elementos normais do Revit - conferidas, clique em "
            "'Iniciar Modulacao' para comecar a Etapa 2."
        )

        footer.Controls.Add(self._status_label)
        footer.Controls.Add(gap1)
        footer.Controls.Add(close_button)

        start_bar = Panel()
        start_bar.Dock = DockStyle.Bottom
        start_bar.Height = 54
        start_bar.BackColor = self._UI_BG
        start_bar.Padding = Padding(18, 8, 18, 0)

        # ORDEM DE Controls.Add() neste container - mesmo aviso do resto do
        # arquivo: Dock.Fill PRECISA ser o PRIMEIRO Controls.Add() (senao os
        # ancorados somem, ver test_controles_dock_fill_entram_antes_dos_
        # ancorados). Entre os Dock.Right, o ULTIMO adicionado fica mais
        # perto da borda - por isso cancel_gap entra antes de
        # self._cancel_button (gap encostado no botao Fill, botao Cancelar
        # na borda direita).
        self._start_button = Button()
        self._start_button.Text = "Iniciar Modulacao das Paredes"
        self._start_button.Dock = DockStyle.Fill
        _style_primary_button(self._start_button)
        self._start_button.Click += self._on_start_click
        if external_event is None:
            self._start_button.Enabled = False
        # Dock.Fill PRECISA ser adicionado ANTES do Dock.Right (mesma regra
        # documentada em _PostCreationForm - ORDEM DOS CONTROLES): senao o
        # Fill ocupa a largura inteira e o botao Right some.
        start_bar.Controls.Add(self._start_button)

        # Pedido explicito do usuario (2026-08-27): opcao para pular a
        # analise/ajuste de erros de parede (Passo 1) e ir DIRETO para a
        # Tela 2 (Modulacao dos Blocos) usando as Walls que acabaram de ser
        # criadas - util quando o usuario ja confirmou visualmente que a
        # planta esta' correta e nao quer esperar o solver de paredes rodar
        # de novo. Continua exigindo confirmacao (ver _on_skip_click) porque
        # pula a validacao que detecta/corrige eixos fora da modulacao.
        self._skip_button = Button()
        self._skip_button.Text = "Pular para Modulacao dos Blocos"
        self._skip_button.Dock = DockStyle.Right
        self._skip_button.Width = 240
        _style_secondary_button(self._skip_button)
        self._skip_button.Click += self._on_skip_click
        start_bar.Controls.Add(self._skip_button)

        # Entre os Dock.Right, o ULTIMO adicionado fica mais perto da
        # borda - por isso o gap do Cancelar entra DEPOIS do botao Pular,
        # deixando "Cancelar" na borda direita (so' visivel/habilitado
        # enquanto a analise/ETAPA 3C esta' rodando - ver _on_start_click/
        # _on_cancel_click, FASE 1 do plano em
        # C:\Users\CIVIX\.claude\plans\quiet-painting-petal.md).
        # Pausar/Continuar (pedido explicito do usuario, 2026-08-26) - entra
        # ANTES do Cancelar na ordem de insercao para ficar mais LONGE da
        # borda direita (Cancelar, a acao destrutiva, fica mais perto dela -
        # mesma regra de ordem de Dock.Right documentada acima).
        pause_gap = Panel(); pause_gap.Dock = DockStyle.Right; pause_gap.Width = 10
        start_bar.Controls.Add(pause_gap)

        self._pause_button = Button()
        self._pause_button.Text = "Pausar"
        self._pause_button.Dock = DockStyle.Right
        self._pause_button.Width = 130
        _style_secondary_button(self._pause_button)
        self._pause_button.Click += self._on_pause_click
        self._pause_button.Visible = False
        start_bar.Controls.Add(self._pause_button)

        cancel_gap = Panel(); cancel_gap.Dock = DockStyle.Right; cancel_gap.Width = 10
        start_bar.Controls.Add(cancel_gap)

        self._cancel_button = Button()
        self._cancel_button.Text = "Cancelar"
        self._cancel_button.Dock = DockStyle.Right
        self._cancel_button.Width = 130
        _style_secondary_button(self._cancel_button)
        self._cancel_button.Click += self._on_cancel_click
        self._cancel_button.Visible = False
        start_bar.Controls.Add(self._cancel_button)

        body = Panel()
        body.Dock = DockStyle.Fill
        body.Padding = Padding(18, 12, 18, 12)
        body.BackColor = self._UI_BG
        self._console = _ProgressConsole()
        self._console.set_status("Aguardando - clique em 'Iniciar Modulacao das Paredes'.")
        initial_log = stage1_report.get("log") or ""
        if initial_log:
            for line in initial_log.replace("\r\n", "\n").split("\n"):
                if line:
                    self._console.log(line)
        body.Controls.Add(self._console.panel)

        # ORDEM DE Controls.Add() - ver o mesmo aviso em _PostCreationForm:
        # Dock.Top/Bottom empilham na ordem INVERSA da insercao.
        self.Controls.Add(body)
        self.Controls.Add(start_bar)
        self.Controls.Add(footer)
        self.Controls.Add(cards)
        self.Controls.Add(header)

    def _on_start_click(self, sender, args):
        if self._external_event is None:
            self._status_label.ForeColor = self._UI_WARN
            self._status_label.Text = "Canal de aplicacao indisponivel nesta execucao."
            return
        self._cancel_requested = False
        self._paused = False
        self._start_button.Enabled = False
        self._start_button.Text = "Analisando/modulando as paredes... (veja o log abaixo)"
        self._cancel_button.Visible = True
        self._cancel_button.Enabled = True
        self._cancel_button.Text = "Cancelar"
        self._pause_button.Visible = True
        self._pause_button.Enabled = True
        self._pause_button.Text = "Pausar"
        self._status_label.ForeColor = self._UI_MUTED
        self._status_label.Text = (
            "Rodando o solver de blocos (ETAPA 3B/3C, multi-fiada, auditoria) "
            "sobre as Walls existentes - pode levar bem mais tempo que a "
            "criacao das Walls. O log abaixo mostra o progresso o tempo todo "
            "(inclusive durante a ETAPA 3C) - use 'Pausar' para segurar sem "
            "perder nada, ou 'Cancelar' se quiser parar e manter so' o que ja "
            "foi corrigido ate' ali."
        )
        self._console.log("ANALISAR: iniciando modulacao das paredes...")
        self._console.set_status("Analisando paredes...")
        self._console.set_indeterminate("Preparando o solver...")
        self._console.start_watchdog()

        # Callbacks AO VIVO (ver docstring de process_walls_one_by_one) -
        # capturados como closures locais (nao pelo nome do modulo), mesmo
        # cuidado documentado no __init__ desta classe: o handler pode
        # chamar isto bem depois, com o Script.py ja reexecutado.
        console = self._console

        def _progress_cb(*cb_args):
            # Ver _dispatch_progress_event - unica forma correta de
            # consumir este callback (a versao antiga so' tratava 2
            # argumentos e descartava em silencio as chamadas de 1/4
            # argumentos da ETAPA 3C, a causa real do travamento "Nao esta
            # respondendo" reportado em producao).
            _dispatch_progress_event(console, *cb_args)

        def _wall_start_cb(wall_idx, total, pos):
            try:
                console.log("ANALISAR: eixo {}... ({}/{})".format(wall_idx, pos, total))
                console.set_status("ANALISAR: eixo {}/{}...".format(pos, total))
                console.set_progress(pos - 1, total)
            except Exception:
                pass

        def _wall_result_cb(wall_idx, total, ok, detail):
            try:
                if ok:
                    console.log("VALIDAR: eixo {}: modulacao valida. CONCLUIDO.".format(wall_idx))
                else:
                    console.log(
                        "DIAGNOSTICAR: eixo {}: erro de modulacao identificado ({})."
                        .format(wall_idx, detail)
                    )
            except Exception:
                pass

        def _should_cancel():
            return self._cancel_requested

        def _should_pause():
            return self._paused

        # Marshala de volta para a UI (mesma tecnica de _ProgressConsole.
        # _invoke_if_needed, aqui usando o proprio Form como Control) -
        # ver Mudanca 2 do plano de arquitetura em memoria: "analyze" agora
        # roda numa thread de fundo (_PostCreationEventHandler._execute_analyze),
        # entao self.on_done (_on_analyze_done, mais abaixo) precisa ser
        # chamado na thread de UI, nao na thread do solver.
        def _ui_invoke(fn):
            try:
                if self.InvokeRequired:
                    self.BeginInvoke(Action(fn))
                else:
                    fn()
            except Exception:
                pass

        self._handler.progress_cb = _progress_cb
        self._handler.wall_start_cb = _wall_start_cb
        self._handler.wall_result_cb = _wall_result_cb
        self._handler.should_cancel_cb = _should_cancel
        self._handler.should_pause_cb = _should_pause
        self._handler.ui_invoke_cb = _ui_invoke
        try:
            self._handler.action = "analyze"
            self._handler.on_done = self._on_analyze_done
            self._external_event.Raise()
        except Exception as ex:
            self._console.stop_watchdog()
            self._start_button.Enabled = True
            self._start_button.Text = "Iniciar Modulacao das Paredes"
            self._cancel_button.Visible = False
            self._pause_button.Visible = False
            self._status_label.ForeColor = self._UI_WARN
            self._status_label.Text = "Falha ao disparar a analise: {}".format(ex)
            self._console.mark_failed("Falha ao disparar a analise: {}".format(ex))

    def _on_cancel_click(self, sender, args):
        # So' PEDE o cancelamento - a ETAPA 3C checa isto no mesmo ponto
        # onde ja' checa o orcamento de tentativas (ver should_cancel_cb em
        # find_wall_group_shift_fixes) e para assim que perceber, mantendo
        # qualquer correcao JA' verificada. So' vira viavel de verdade
        # porque a FASE 1 tambem corrigiu o bombeamento de mensagens
        # durante a ETAPA 3C (senao este clique nunca chegaria ate' aqui
        # enquanto ela estivesse rodando).
        # `_paused` e' zerado aqui de proposito: se o usuario cancelar
        # enquanto pausado, o laco de espera de should_pause_cb (que so'
        # checa should_cancel_cb DEPOIS de sair do `while should_pause_cb()`)
        # nunca chegaria a perceber o cancelamento sem isso.
        self._cancel_requested = True
        self._paused = False
        self._cancel_button.Enabled = False
        self._cancel_button.Text = "Cancelando..."
        self._pause_button.Enabled = False
        self._console.log(
            "Cancelamento solicitado pelo usuario - parando assim que possivel, "
            "mantendo o que ja foi corrigido ate' aqui."
        )

    def _on_pause_click(self, sender, args):
        # So' alterna uma flag lida pelos MESMOS pontos de checagem do
        # Cancelar (should_pause_cb) - o laco de espera bombeia
        # Application.DoEvents() para a UI continuar respondendo mesmo
        # parado (ver ETAPA 3C/fix_all_wall_modulation_errors).
        self._paused = not self._paused
        if self._paused:
            self._pause_button.Text = "Continuar"
            self._console.set_status("PAUSADO - clique em 'Continuar' para retomar.")
            self._console.log("Pausado pelo usuario - nenhuma alteracao esta sendo feita agora.")
        else:
            self._pause_button.Text = "Pausar"
            self._console.log("Retomado pelo usuario.")

    def _on_analyze_done(self, kind, error):
        # `kind == "error"` (nunca `if error:`) - ver o mesmo cuidado
        # documentado em _PostCreationForm._on_zoom_done: uma excecao sem
        # mensagem nao pode virar sucesso silencioso. Sucesso chega como
        # kind=="analyze" (ver _PostCreationEventHandler._execute_analyze) -
        # o resultado em si NAO vem no payload, fica em
        # self._handler.error_rows (mesmo atributo que "fix_errors" ja'
        # le/atualiza).
        self._console.stop_watchdog()
        self._cancel_button.Visible = False
        self._pause_button.Visible = False
        if kind == "error":
            self._start_button.Enabled = True
            self._start_button.Text = "Iniciar Modulacao das Paredes"
            self._status_label.ForeColor = self._UI_WARN
            self._status_label.Text = "Falha ao iniciar a modulacao: {}".format(error)
            self._console.mark_failed("FALHOU: {}".format(error))
            if self._on_start_error:
                self._on_start_error(error)
            return
        error_rows = self._handler.error_rows or []
        total = len(error_rows)
        cancel_note = " (cancelado pelo usuario antes do fim)" if self._cancel_requested else ""
        self._console.log(
            ("CONCLUIDO{}: {} eixo(s) com erro de modulacao.".format(cancel_note, total)
             if total else "CONCLUIDO{}: nenhum erro de modulacao.".format(cancel_note))
        )
        self._console.mark_complete(
            "MODULAR: modulacao das paredes concluida{} - {} erro(s) encontrado(s). "
            "Abrindo Tela 2 (Modulacao dos Blocos)...".format(cancel_note, total)
        )
        # REGRA PRINCIPAL do usuario (ver docstring da classe, topo do
        # metodo _on_start_click): a Tela 2 so' pode comecar quando esta
        # analise chega ao fim com sucesso - NUNCA antes, NUNCA sozinha (ou
        # seja, nunca por _WallReviewForm existir sozinha, so' depois deste
        # callback). Uma vez aqui, avanca DIRETO (sem exigir mais um
        # clique) - o log acima ja registrou os erros encontrados, e a
        # Tela 2 mostra a mesma lista para revisar/ajustar antes de
        # lancar os blocos.
        self._start_button.Text = "Modulacao das paredes concluida"
        if self._on_start_success:
            self._on_start_success(self._handler.error_rows)
        self.Close()

    def _on_skip_click(self, sender, args):
        """Pedido explicito do usuario (2026-08-27): pular a Etapa 1
        (analise/ajuste de erros de parede) e ir DIRETO para a Tela 2
        (Modulacao dos Blocos) com as Walls que acabaram de ser criadas.
        Nunca dispara sozinho (mesma regra do _on_start_click) - so' quando
        o usuario clica E confirma explicitamente, porque pular a analise
        significa que nenhum eixo fora da modulacao sera' detectado/
        corrigido antes do lancamento de blocos."""
        # `forms.alert(..., yes=True, no=True)` em vez de `MessageBox.Show`
        # direto - mesmo motivo do comentario em `_on_delete_click` acima.
        confirm = forms.alert(
            "Isto pula a analise/ajuste de erros de modulacao das paredes "
            "(Passo 1) e abre direto a Tela 2 (Modulacao dos Blocos) com as "
            "Walls ja criadas.\n\nEixos fora da modulacao NAO serao "
            "detectados nem corrigidos automaticamente antes do "
            "lancamento de blocos - use so' se ja conferiu a planta e "
            "quer ganhar tempo.\n\nConfirma pular para a Tela 2?",
            title="Modulacao Automatica - Pular para Modulacao dos Blocos",
            yes=True, no=True
        )
        if not confirm:
            return
        self._console.log(
            "Modulacao das paredes PULADA a pedido do usuario - abrindo "
            "Tela 2 (Modulacao dos Blocos) direto."
        )
        self._console.set_status("Modulacao das paredes pulada - abrindo Tela 2...", "warn")
        self._start_button.Enabled = False
        self._skip_button.Enabled = False
        self._skip_button.Text = "Pulado - abrindo Tela 2..."
        # error_rows vazio (nunca analisado) - a Tela 2 mostra "nenhum eixo
        # fora da modulacao" so' porque nao rodou, nao porque a planta
        # esta' de fato validada; o texto acima ja deixa isso explicito.
        self._handler.error_rows = []
        try:
            if self._on_start_success:
                # `None` (nunca `[]`) - e' o unico jeito de
                # `_run_stage2_existing_walls` (ver skipped_wall_analysis =
                # wall_error_rows is None) distinguir "pulou a analise" de
                # "analisou e nao achou nenhum erro"; `[]` tambem e' o
                # resultado normal de uma analise sem erros, entao passar
                # `[]` aqui sempre fazia o log da Tela 2 dizer "analise
                # concluida" mesmo quando ela nunca rodou.
                self._on_start_success(None)
        except Exception as ex:
            # Bug real reportado pelo usuario (2026-08-27): clicar em
            # "Pular para Modulacao dos Blocos" -> "Sim" nao fazia
            # absolutamente nada visivel quando algo dentro do callback
            # falhava - o Click do WinForms roda fora da execucao da API
            # do Revit, entao uma excecao aqui escapava direto sem
            # nenhum alerta. Agora sempre mostra o erro de verdade e
            # devolve os botoes ao estado normal para o usuario tentar de
            # novo, em vez de deixar a janela travada com "Pulado -
            # abrindo Tela 2..." para sempre.
            detail = _format_exception_detail(ex)
            self._console.mark_failed("FALHOU ao pular para a Tela 2: {}".format(detail))
            self._start_button.Enabled = True
            self._skip_button.Enabled = True
            self._skip_button.Text = "Pular para Modulacao dos Blocos"
            forms.alert(
                "Falha ao pular para a Tela 2 (Modulacao dos Blocos).\n\n"
                "Erro: {}\n\n"
                "Nenhuma Wall foi alterada - pode tentar novamente ou usar "
                "'Iniciar Modulacao das Paredes' em vez disso.".format(detail),
                title="Modulacao Automatica - Pular para Modulacao dos Blocos falhou"
            )
            return
        self.Close()


def _show_wall_review_window(stage1_report, handler_data, on_start_modulation):
    """Cria o ExternalEvent + handler (_PostCreationEventHandler, acao
    "analyze" - ver o docstring dela) e mostra a janela de revisao das
    Walls (_WallReviewForm) - equivalente, para a ETAPA 1, do que
    _show_post_creation_window ja faz para a ETAPA 2 (que cria sua PROPRIA
    instancia nova de _PostCreationEventHandler, separada desta - so' a
    CLASSE e' compartilhada, nao a instancia). Guarda a referencia em
    _ACTIVE_MODELESS_WINDOWS pelo mesmo motivo/cuidado documentado la'
    (main() retorna assim que a janela abre).

    `handler_data`: dict com as chaves walls_to_create/openings_per_wall/
    created_walls_by_axis/wall_segment_geometry/all_openings/wall_graph_nodes/
    wall_end_to_node/catalog/catalog_missing/modulation_results/opening_
    incompatible_modulation/progress_cb - copiadas 1:1 para o handler.

    `on_start_modulation(wall_error_rows)`: chamado (na UI thread, depois
    de Execute() ja ter terminado) quando a analise termina com sucesso -
    e' quem monta e abre a janela de resultado de verdade (ver
    _run_stage2_modulation, dentro de main())."""
    handler = _PostCreationEventHandler()
    handler.walls_to_create = handler_data["walls_to_create"]
    handler.openings_per_wall = handler_data["openings_per_wall"]
    handler.wall_segment_geometry = handler_data.get("wall_segment_geometry") or {}
    handler.created_walls_by_axis = handler_data["created_walls_by_axis"]
    handler.all_openings = handler_data["all_openings"]
    handler.wall_graph_nodes = handler_data["wall_graph_nodes"]
    handler.wall_end_to_node = handler_data["wall_end_to_node"]
    handler.catalog = handler_data["catalog"]
    handler.catalog_missing = handler_data["catalog_missing"]
    handler.modulation_results = handler_data["modulation_results"]
    handler.opening_incompatible_modulation = handler_data["opening_incompatible_modulation"]
    handler.progress_cb = handler_data.get("progress_cb")
    external_event = ExternalEvent.Create(handler)

    def _on_success(wall_error_rows):
        on_start_modulation(wall_error_rows)

    window = _WallReviewForm(stage1_report, external_event, handler, _on_success, None)
    entry = (window, external_event, handler)
    active_list = _ACTIVE_MODELESS_WINDOWS
    active_list.append(entry)

    def _on_closed(sender, args):
        if entry in active_list:
            active_list.remove(entry)
        window._console.close()  # para o watchdog (ver _ProgressConsole.close)

    window.FormClosed += _on_closed
    window.Show()


# ==========================================
# FLUXO "UTILIZAR PAREDES EXISTENTES" (pedido explicito do usuario,
# 2026-08-26 - Etapa 1 do fluxo, opcao "Pular criacao/verificacao inicial
# das paredes": "muitas vezes as paredes ja estao modeladas e ajustadas no
# Revit e eu quero ir diretamente para a modulacao dos blocos").
#
# Ao contrario do fluxo classico (main(), abaixo - extrai linhas de um
# vinculo/importacao de CAD e CRIA novas Wall no Revit), este caminho
# NUNCA cria nenhuma Wall nova: o usuario SELECIONA, no proprio modelo, as
# Wall que ja existem e ja estao corretas, e o script monta a MESMA
# estrutura de dados interna (walls_to_create/created_walls_by_axis/
# wall_segment_geometry/openings_per_wall/wall_graph_nodes) que o fluxo
# classico monta depois de criar as paredes - a partir dai' as duas telas
# seguintes (_show_wall_review_window/_show_post_creation_window, Etapa 2
# e Etapa 3/4 do fluxo pedido) sao EXATAMENTE as mesmas, sem nenhuma
# duplicacao de codigo: "Analisar Paredes"/"Ajustar Erros"/"Lancar Blocos"
# funcionam identico nos dois fluxos.
#
# Cada Wall selecionada vira UM UNICO segmento "cad" (nao ha' segmentos
# "abertura" separados, ja' que a Wall e' real e ja' inclui o vao da porta/
# janela na sua propria geometria) - por isso _classify_wall_axis_segments
# (Etapa 3B, correcao automatica de pilaretes) devolve "fora de escopo"
# para estes eixos quando ha' abertura (exige pelo menos um segmento
# "abertura" - ver seu docstring). Isso e' aceitavel aqui: o usuario ja'
# confirmou que a parede esta' correta, entao Etapa 3B nao precisa
# corrigir nada nela - so' "Lancar Blocos" (que NUNCA depende de
# created_walls_by_axis estar segmentada, so' de walls_to_create/
# openings_per_wall/wall_graph_nodes, puramente geometricos) precisa
# funcionar, e funciona sem alteracao nenhuma.
# ==========================================

class _WallSourceModeForm(Form):
    """Tela inicial 'Preparacao das paredes' - escolha estilizada entre os
    dois fluxos (CAD ou paredes existentes), com o mesmo layout de cartoes
    e paleta usados nas demais janelas do script."""

    def __init__(self):
        Form.__init__(self)
        self.result = None  # "cad" | "existing" | None (cancelou)

        self.Text = "Modulacao Automatica"
        self.Width = 520
        self.Height = 400
        self.StartPosition = FORM_START_POSITION_CENTER_SCREEN
        self.BackColor = UI_BG
        self.MaximizeBox = False
        self.MinimizeBox = False

        header = _build_header(
            "Preparacao das paredes",
            "Como as paredes desta modulacao serao preparadas?"
        )

        body = Panel()
        body.Dock = DockStyle.Fill
        body.BackColor = UI_BG
        body.Padding = Padding(20, 16, 20, 8)

        # ---- cartao: CAD ----
        self._rb_cad = RadioButton()
        self._rb_cad.Text = "Criar paredes a partir da planta (CAD)"
        self._rb_cad.Font = _ui_font(10.0, True)
        self._rb_cad.ForeColor = UI_TEXT
        self._rb_cad.Checked = True
        self._rb_cad.AutoSize = False
        self._rb_cad.Height = 24
        self._rb_cad.Dock = DockStyle.Top

        desc_cad = Label()
        desc_cad.Text = ("Importa as linhas de um arquivo CAD (.dwg) e cria as "
                         "paredes automaticamente no nivel selecionado.")
        desc_cad.Font = _ui_font(8.75)
        desc_cad.ForeColor = UI_MUTED
        desc_cad.Dock = DockStyle.Fill
        desc_cad.Padding = Padding(22, 2, 4, 4)
        desc_cad.AutoSize = False

        card_cad = Panel()
        card_cad.Dock = DockStyle.Top
        card_cad.Height = 80
        card_cad.BackColor = UI_PANEL
        card_cad.Padding = Padding(12, 14, 12, 4)
        card_cad.Controls.Add(desc_cad)
        card_cad.Controls.Add(self._rb_cad)
        card_cad.Click += lambda s, e: setattr(self._rb_cad, "Checked", True)
        desc_cad.Click += lambda s, e: setattr(self._rb_cad, "Checked", True)

        # ---- cartao: paredes existentes ----
        self._rb_existing = RadioButton()
        self._rb_existing.Text = "Utilizar paredes existentes"
        self._rb_existing.Font = _ui_font(10.0, True)
        self._rb_existing.ForeColor = UI_TEXT
        self._rb_existing.AutoSize = False
        self._rb_existing.Height = 24
        self._rb_existing.Dock = DockStyle.Top

        desc_existing = Label()
        desc_existing.Text = ("Pula a criacao e verificacao inicial - usa Walls "
                              "ja modeladas no projeto, selecionadas a seguir.")
        desc_existing.Font = _ui_font(8.75)
        desc_existing.ForeColor = UI_MUTED
        desc_existing.Dock = DockStyle.Fill
        desc_existing.Padding = Padding(22, 2, 4, 4)
        desc_existing.AutoSize = False

        card_existing = Panel()
        card_existing.Dock = DockStyle.Top
        card_existing.Height = 80
        card_existing.BackColor = UI_PANEL
        card_existing.Padding = Padding(12, 14, 12, 4)
        card_existing.Controls.Add(desc_existing)
        card_existing.Controls.Add(self._rb_existing)
        card_existing.Click += lambda s, e: setattr(self._rb_existing, "Checked", True)
        desc_existing.Click += lambda s, e: setattr(self._rb_existing, "Checked", True)

        spacer = Panel()
        spacer.Height = 8
        spacer.Dock = DockStyle.Top
        spacer.BackColor = UI_BG

        # DockStyle.Top: ultimo Add = mais ao topo visualmente
        body.Controls.Add(card_existing)
        body.Controls.Add(spacer)
        body.Controls.Add(card_cad)

        # ---- rodape ----
        footer = Panel()
        footer.Dock = DockStyle.Bottom
        footer.Height = 56
        footer.BackColor = UI_BG
        footer.Padding = Padding(20, 9, 20, 9)

        self._ok_btn = Button()
        self._ok_btn.Text = "Continuar"
        self._ok_btn.Width = 130
        self._ok_btn.Dock = DockStyle.Right
        _style_primary_button(self._ok_btn)
        self._ok_btn.Click += self._on_ok

        cancel_btn = Button()
        cancel_btn.Text = "Cancelar"
        cancel_btn.Width = 100
        cancel_btn.Dock = DockStyle.Right
        _style_secondary_button(cancel_btn)
        cancel_btn.Click += self._on_cancel

        footer.Controls.Add(self._ok_btn)
        footer.Controls.Add(cancel_btn)

        # Fill primeiro, Bottom depois, Top por ultimo (header)
        self.Controls.Add(body)
        self.Controls.Add(footer)
        self.Controls.Add(header)

    def _on_ok(self, sender, event):
        self.result = "existing" if self._rb_existing.Checked else "cad"
        self.Close()

    def _on_cancel(self, sender, event):
        self.result = None
        self.Close()


def _ask_wall_source_mode():
    """Primeira pergunta do script (Etapa 1 - "Preparacao das paredes"):
    como as paredes desta modulacao devem ser preparadas. Devolve "cad"
    (fluxo classico - gera Walls novas a partir de um CAD), "existing"
    (pula a geracao/verificacao inicial - usa Walls JA' MODELADAS,
    escolhidas pelo usuario) ou None (cancelou, ESC/fechar).

    Usa _WallSourceModeForm (WinForms estilizado) com fallback para
    forms.SelectFromList quando a janela nao pode ser construida."""
    try:
        form = _WallSourceModeForm()
        form.ShowDialog()
        return form.result
    except Exception:
        # Fallback: SelectFromList basico - funciona em qualquer ambiente
        option_cad = "Criar paredes a partir da planta (CAD)"
        option_existing = "Utilizar paredes existentes (pular criacao/verificacao inicial)"
        choice = forms.SelectFromList.show(
            [option_cad, option_existing],
            title="Modulacao Automatica - Preparacao das paredes",
            button_name="Continuar",
            multiselect=False
        )
        if choice == option_existing:
            return "existing"
        if choice == option_cad:
            return "cad"
        return None


def _select_existing_walls_for_modulation():
    """Deixa o usuario selecionar, no proprio modelo, as Wall JA'
    EXISTENTES a modular. Devolve (walls_to_create, created_walls_by_axis,
    wall_ids, selected_level, wall_height_ft, skipped_count) ou (None, None,
    None, None, None, 0) se a selecao for cancelada (ESC) ou nao resultar em
    nenhuma Wall valida (sem LocationCurve, ou com comprimento menor que
    MIN_SEGMENT_LENGTH_FT). `skipped_count` e' quantos dos elementos
    SELECIONADOS pelo usuario foram ignorados (nao sao Wall, sem
    LocationCurve, ou curtos demais) - devolvido para o chamador poder
    reportar isso explicitamente (pedido do usuario: "validar se os
    elementos escolhidos sao realmente paredes validas e informar quantas
    foram reconhecidas").

    Cada Wall vira o proprio eixo inteiro (`walls_to_create[i][0]` = a
    Location.Curve REAL dela, lida agora mesmo - nunca um snapshot antigo),
    com a espessura real (`Wall.Width`)."""
    # Instrucao objetiva ANTES da selecao (pedido do usuario: cada etapa
    # precisa explicar claramente a proxima acao) - a dica da barra de
    # status do PickObjects abaixo tambem existe, mas e' pequena e facil de
    # nao notar; este alerta modal garante que ninguem comeca a selecao sem
    # saber o que fazer.
    forms.alert(
        "Selecione no modelo as paredes existentes que deseja modular e "
        "clique em 'Concluir' na barra de opcoes do Revit (ou Esc para "
        "cancelar).",
        title="Modulacao Automatica - Etapa 1: Selecao das paredes"
    )
    try:
        refs = uidoc.Selection.PickObjects(
            ObjectType.Element,
            "Selecione as paredes existentes a modular e clique em Concluir na barra de opcoes"
        )
    except Exception:
        return None, None, None, None, None, 0  # ESC

    walls_to_create = []
    created_walls_by_axis = {}
    wall_ids = []
    skipped = 0
    level_votes = {}
    max_height_ft = 0.0

    for ref in refs:
        wall = doc.GetElement(ref.ElementId)
        if not isinstance(wall, Wall):
            skipped += 1
            continue
        location = wall.Location
        if not isinstance(location, LocationCurve):
            skipped += 1
            continue
        curve = location.Curve
        try:
            if curve.Length < MIN_SEGMENT_LENGTH_FT:
                skipped += 1
                continue
        except Exception:
            skipped += 1
            continue

        wall_idx = len(walls_to_create)
        walls_to_create.append((curve, wall.Width, (False, False)))
        created_walls_by_axis[wall_idx] = [(wall.Id, "cad")]
        wall_ids.append(wall.Id)

        level = doc.GetElement(wall.LevelId)
        if isinstance(level, Level):
            _lid = _eid_int(level.Id)
            level_votes[_lid] = (level_votes.get(_lid, (0, level))[0] + 1, level)

        # Altura real da parede (parametro de usuario, ex.: "Nao conectada" -
        # 0.0 quando a parede e' restrita a um Nivel de topo em vez de uma
        # altura fixa; nesse caso cai no fallback por bounding box abaixo,
        # mesmo padrao ja usado em _build_opening_dict para portas/janelas
        # sem os parametros esperados).
        height_ft = 0.0
        try:
            height_param = wall.get_Parameter(BuiltInParameter.WALL_USER_HEIGHT_PARAM)
            if height_param is not None:
                height_ft = height_param.AsDouble()
        except Exception:
            height_ft = 0.0
        if height_ft <= 1e-6:
            try:
                bbox = wall.get_BoundingBox(None)
                if bbox is not None:
                    height_ft = bbox.Max.Z - bbox.Min.Z
            except Exception:
                height_ft = 0.0
        if height_ft > max_height_ft:
            max_height_ft = height_ft

    if not walls_to_create:
        return None, None, None, None, None, skipped

    selected_level = None
    if level_votes:
        # Nivel MAIS COMUM entre as paredes selecionadas - a mesma
        # convencao que o fluxo classico ja usa (um unico Nivel para toda a
        # modulacao, escolhido em ask_setup).
        selected_level = max(level_votes.values(), key=lambda pair: pair[0])[1]
    if selected_level is None:
        levels = FilteredElementCollector(doc).OfClass(Level).ToElements()
        selected_level = levels[0] if levels else None

    return walls_to_create, created_walls_by_axis, wall_ids, selected_level, max_height_ft, skipped


def run_modulation_on_existing_walls():
    """Fluxo "utilizar paredes existentes" - ver cabecalho da secao acima.
    Nunca cria nenhuma Wall nova; monta a mesma estrutura de dados interna
    que o fluxo classico (main(), abaixo) monta depois da Etapa 1, e abre
    a MESMA janela de revisao/modulacao (_show_wall_review_window)."""
    output = script.get_output()

    walls_to_create, created_walls_by_axis, wall_ids, selected_level, wall_height_ft, skipped_count = (
        _select_existing_walls_for_modulation()
    )
    if walls_to_create is None:
        return
    if selected_level is None:
        forms.alert("Nenhum Nivel foi encontrado no projeto.", exitscript=True)
        return
    if wall_height_ft <= 1e-6:
        forms.alert(
            "Nao foi possivel determinar a altura de nenhuma das paredes "
            "selecionadas (parametro de altura vazio e bounding box "
            "invalida).",
            exitscript=True
        )
        return

    base_z_abs = selected_level.Elevation

    output.print_md("**Coletando aberturas (portas/janelas) do projeto...**")
    all_openings, openings_source_note = collect_opening_instances("auto", None)

    opening_diagnostics = {
        "clamped_opening_count": 0, "opening_center_gap_max_ft": 0.0,
        "opening_off_center_count": 0, "assignments": [], "unassigned_openings": [],
    }
    openings_per_wall = assign_openings_to_walls(walls_to_create, all_openings, opening_diagnostics)
    unassigned_openings = opening_diagnostics["unassigned_openings"]

    opening_modulation_results = evaluate_opening_modulation(all_openings)
    opening_incompatible_modulation = [r for r in opening_modulation_results if not r["compatible"]]

    walls_to_create, junction_map = extend_wall_ends_to_junctions(walls_to_create, JUNCTION_FACE_SEARCH_FT)
    wall_graph_nodes, wall_end_to_node = build_wall_graph(walls_to_create, junction_map)

    # Snapshot leve de geometria (ver wall_segment_geometry no fluxo
    # classico) - UM segmento "cad" por eixo, cobrindo o eixo INTEIRO (ja'
    # possivelmente esticado por extend_wall_ends_to_junctions acima).
    wall_segment_geometry = {}
    for wall_idx, entries in created_walls_by_axis.items():
        centerline = walls_to_create[wall_idx][0]
        t_a = _axis_t_of_point(centerline, centerline.GetEndPoint(0))
        t_b = _axis_t_of_point(centerline, centerline.GetEndPoint(1))
        if t_a > t_b:
            t_a, t_b = t_b, t_a
        wall_segment_geometry[wall_idx] = [
            {"element_id": eid, "seg_origin": seg_origin, "t_a": t_a, "t_b": t_b}
            for eid, seg_origin in entries
        ]

    modulation_results = evaluate_wall_modulation(wall_ids, target_doc=doc)
    incompatible_modulation = [r for r in modulation_results if not r["compatible"]]

    catalog, catalog_missing = load_fixed_block_catalog(doc)

    # ExternalEvent da ETAPA 2 (Tela de Modulacao dos Blocos) criado JA'
    # AQUI, ainda dentro da execucao sincrona da API do Revit (main() ainda
    # rodando) - ver comentario em _show_post_creation_window sobre
    # `precreated_event`/`precreated_handler` (bug real 2026-08-27:
    # ExternalEvent.Create so' e' valido dentro da execucao da API, e
    # `_run_stage2_existing_walls` abaixo e' chamada ou de um
    # `Control.BeginInvoke` (fim da acao "analyze") ou direto de um Click
    # de WinForms ("Pular para Modulacao dos Blocos") - nenhum dos dois
    # ainda esta' dentro dessa execucao).
    stage2_handler = _PostCreationEventHandler()
    stage2_external_event = ExternalEvent.Create(stage2_handler)

    def _run_stage2_existing_walls(wall_error_rows):
        skipped_wall_analysis = wall_error_rows is None
        if skipped_wall_analysis:
            wall_error_rows = []
        try:
            if skipped_wall_analysis:
                output.print_md(
                    "**Analise/ajuste das paredes PULADA a pedido do usuario - "
                    "indo direto para a Tela 2 (Modulacao dos Blocos).**"
                )
            else:
                output.print_md(
                    "**Analise de paredes existentes concluida - {} parede(s) "
                    "com problema encontrada(s).**".format(len(wall_error_rows))
                )
        except Exception:
            pass

        # TUDO abaixo (montagem do log/report, cache de solve/create
        # anteriores e abertura da Tela 2) agora fica dentro de UM UNICO
        # try/except (bug real reportado pelo usuario, 2026-08-27: clicar
        # em "Pular para Modulacao dos Blocos" -> "Sim" nao fazia
        # absolutamente nada visivel - a janela ficava com os botoes
        # desabilitados e nunca abria a Tela 2, sem NENHUM alerta de erro).
        # Antes, o try/except so' cobria a chamada a
        # `_show_post_creation_window` - qualquer excecao ANTES dela (por
        # exemplo em `_wall_ids_signature`/cache/`build_report_issues`)
        # escapava direto do Click do WinForms, que roda fora da execucao
        # da API do Revit: nesse contexto o pythonnet/engine do pyRevit
        # engole a excecao (nunca chega a um "unhandled exception" visivel
        # nem ao log do pyRevit), entao o usuario via a janela travada e
        # nada mais - exatamente o sintoma relatado ("nada acontece").
        # Agora QUALQUER falha em qualquer ponto deste bloco cai no mesmo
        # alerta modal com o erro de verdade.
        try:
            log_lines = [
                "=== Modulacao sobre paredes EXISTENTES (Etapa 1 pulada) ===",
                "", "{} parede(s) existente(s) selecionada(s).".format(len(walls_to_create)),
                "{} abertura(s) consideradas ({}).".format(len(all_openings), openings_source_note),
            ]
            if unassigned_openings:
                log_lines.append(
                    "{} abertura(s) nao ficaram perto de nenhuma parede selecionada.".format(
                        len(unassigned_openings)
                    )
                )
            if wall_error_rows:
                log_lines.append(
                    "Correcao pos-criacao (ETAPA 3B): {} eixo(s) fora da modulacao "
                    "(pilaretes/aberturas - so' se aplica quando a parede real ja' "
                    "estiver dividida em segmentos; a maioria das paredes "
                    "existentes fica 'fora de escopo' aqui, o que e' esperado - "
                    "ver cabecalho da secao).".format(len(wall_error_rows))
                )
            # Reaproveita solve_result/create_result de uma execucao anterior
            # deste MESMO conjunto de paredes, se a janela daquela vez tiver
            # sido fechada antes de clicar em "criar" (pedido explicito do
            # usuario, 2026-08-27 - ver _LAST_MODULATION_STATE/_wall_ids_
            # signature/_save_modulation_state_cache). So' o solve_result e'
            # sempre valido (a geometria e' a mesma - as Wall selecionadas nao
            # mudaram desde entao); o create_result so' e' reaproveitado JUNTO
            # se as instancias que ele referencia ainda existirem no documento
            # (o usuario pode ter apagado os blocos manualmente entre as duas
            # execucoes) - nunca mostra "criado" para pecas que nao existem
            # mais.
            cache_key = _wall_ids_signature(wall_ids)
            cached_state = _LAST_MODULATION_STATE.get(cache_key) if cache_key else None
            cached_solve_result = None
            cached_create_result = None
            if cached_state:
                cached_solve_result = cached_state.get("solve_result")
                candidate_create_result = cached_state.get("create_result")
                if candidate_create_result and candidate_create_result.get("created_instances"):
                    still_exists = all(
                        doc.GetElement(item["id"]) is not None
                        for item in candidate_create_result["created_instances"]
                    )
                    if still_exists:
                        cached_create_result = candidate_create_result
                log_lines.append(
                    "Resultado de uma execucao anterior sobre este MESMO conjunto de paredes foi "
                    "reaproveitado (nao precisou recalcular o solver){}.".format(
                        " - blocos ja' criados detectados no documento" if cached_create_result else ""
                    )
                )

            summary = "\n".join(log_lines)
            log_file_path = _save_log_to_file(summary)

            report = {
                "title": "Paredes existentes - {} eixo(s) prontos para modular".format(len(walls_to_create)),
                "subtitle": (
                    "Etapa 1 - Selecao das paredes: CONCLUIDA | Etapa 2 - Modulacao com blocos: "
                    "EM EXECUCAO | Nivel '{}' | altura {:.2f}m | paredes existentes (nenhuma foi "
                    "criada nesta execucao) | esta janela nao bloqueia o Revit."
                    .format(selected_level.Name, wall_height_ft / FEET_PER_METER)
                ),
                "kpis": [
                    ("Paredes selecionadas", len(walls_to_create), UI_TEXT),
                    ("Aberturas usadas", len(all_openings) - len(unassigned_openings), UI_TEXT),
                    ("Fora da modulacao",
                     len(incompatible_modulation) + len(opening_incompatible_modulation),
                     UI_WARN if (incompatible_modulation or opening_incompatible_modulation) else UI_OK),
                ],
                "highlights": [
                    "{} parede(s) existente(s) usada(s) como eixo de modulacao (nenhuma Wall nova "
                    "foi criada).".format(len(walls_to_create)),
                    "{} abertura(s) do projeto consideradas ({}).".format(
                        len(all_openings), openings_source_note
                    ),
                ],
                "issues": build_report_issues(
                    [], [], modulation_results, opening_incompatible_modulation,
                    unassigned_openings, [], False, 0
                ),
                "log": summary,
                "log_path": log_file_path,
                "wall_analysis_skipped": skipped_wall_analysis,
            }

            _show_post_creation_window(
                report, walls_to_create, openings_per_wall, created_walls_by_axis,
                wall_ids, all_openings, wall_graph_nodes, wall_end_to_node,
                selected_level, base_z_abs, wall_height_ft, wall_error_rows,
                catalog, catalog_missing, wall_segment_geometry=wall_segment_geometry,
                initial_solve_result=cached_solve_result, initial_create_result=cached_create_result,
                precreated_event=stage2_external_event, precreated_handler=stage2_handler
            )
        except Exception as ex:
            # NUNCA mostrar um resumo de "tudo certo" (paredes selecionadas/
            # aberturas consideradas) como se fosse o resultado - isso
            # escondia por completo o fato de a Tela 2 ter falhado e de
            # NENHUM bloco ter sido calculado/criado (bug real reportado
            # pelo usuario, 2026-08-27, com print de tela). O alerta agora
            # deixa isso explicito e mostra o erro de verdade, nao so' o
            # log do pyRevit que o usuario normalmente nao esta' olhando.
            detail = _format_exception_detail(ex)
            last_line = traceback.format_exc().splitlines()[-1]
            try:
                output.print_md(
                    "- **Tela 2 (Modulacao dos Blocos) FALHOU AO ABRIR** ({0}); "
                    "NENHUMA modulacao nem criacao de blocos rodou.\n\n```\n{1}\n```".format(
                        last_line, detail
                    )
                )
            except Exception:
                pass
            forms.alert(
                "A Tela 2 (Modulacao dos Blocos) FALHOU AO ABRIR - NENHUM bloco foi "
                "calculado ou criado no Revit.\n\n"
                "Erro: {0}\n\n"
                "As {1} parede(s) selecionadas continuam intactas (nenhuma Wall foi "
                "criada/alterada). Copie o texto completo do erro no painel de saida do "
                "pyRevit (mais detalhado) e tente novamente - se persistir, reporte esse "
                "texto exato para diagnostico.".format(last_line, len(walls_to_create)),
                title="Modulacao Automatica - Tela 2 falhou (nenhum bloco criado)"
            )

    skipped_note = (
        " | {} elemento(s) selecionado(s) foram IGNORADOS (nao sao Wall validas, sem "
        "eixo, ou curtos demais)".format(skipped_count) if skipped_count else ""
    )
    stage1_report = {
        "title": "Paredes existentes selecionadas - {} eixo(s)".format(len(walls_to_create)),
        "subtitle": (
            "Etapa 1 - Selecao das paredes: CONCLUIDA | Etapa 2 - Modulacao com blocos: "
            "aguardando | Nivel '{}' | altura {:.2f}m | nenhuma Wall foi criada - reveja a "
            "selecao no Revit antes de modular.{}"
            .format(selected_level.Name, wall_height_ft / FEET_PER_METER, skipped_note)
        ),
        "kpis": [
            ("Paredes selecionadas", len(walls_to_create), UI_ACCENT),
            ("Aberturas consideradas", len(all_openings), UI_TEXT),
        ] + ([("Elementos ignorados", skipped_count, UI_WARN)] if skipped_count else []),
        "log": (
            "=== Paredes existentes selecionadas ===\n\n"
            "{} parede(s) reconhecida(s) e valida(s) no Revit (nenhuma foi criada).{}\n"
            "Nivel '{}' | altura {:.2f}m.\n\n"
            "Nenhuma analise de modulacao rodou ainda - clique em 'Iniciar "
            "Modulacao' quando estiver pronto, ou 'Pular para Modulacao dos "
            "Blocos' para ir direto (as paredes ja' estao prontas)."
            .format(
                len(walls_to_create),
                "\n{} elemento(s) selecionado(s) foram ignorados (nao sao Wall validas, "
                "sem eixo, ou curtos demais).".format(skipped_count) if skipped_count else "",
                selected_level.Name, wall_height_ft / FEET_PER_METER
            )
        ),
    }

    try:
        _show_wall_review_window(
            stage1_report,
            {
                "walls_to_create": walls_to_create,
                "openings_per_wall": openings_per_wall,
                "created_walls_by_axis": created_walls_by_axis,
                "wall_segment_geometry": wall_segment_geometry,
                "all_openings": all_openings,
                "wall_graph_nodes": wall_graph_nodes,
                "wall_end_to_node": wall_end_to_node,
                "catalog": catalog,
                "catalog_missing": catalog_missing,
                "modulation_results": modulation_results,
                "opening_incompatible_modulation": opening_incompatible_modulation,
                "progress_cb": None,
            },
            _run_stage2_existing_walls,
        )
    except Exception as ex:
        detail = _format_exception_detail(ex)
        output.print_md(
            "- **Tela WinForms de revisao das paredes falhou** ({0}).\n\n```\n{1}\n```"
            .format(traceback.format_exc().splitlines()[-1], detail)
        )
        quer_modular = forms.alert(
            "A tela de revisao das paredes falhou nesta execucao.\n\n"
            "Iniciar a modulacao de blocos direto (sem analisar erros de "
            "parede primeiro)?",
            title="Modulacao Automatica - Paredes existentes", yes=True, no=True
        )
        if not quer_modular:
            return
        _run_stage2_existing_walls(None)


# ==========================================
# EXECUCAO PRINCIPAL DO SCRIPT
# ==========================================

def main():
    # 0. Arma o validador AO VIVO (ver secao VALIDADOR AO VIVO... mais
    # acima) - registra os dois updaters uma unica vez por sessao (seguro
    # rodar o botao varias vezes seguidas, ver
    # _register_modulation_updaters_if_needed). So' o REGISTRO acontece
    # aqui; o ESCOPO (quais elementos sao observados) e' definido mais
    # abaixo, via AddTrigger, com os Ids desta execucao.
    wall_modulation_updater, opening_modulation_updater = (
        _register_modulation_updaters_if_needed()
    )

    # PERFORMANCE: cronometro por etapa, reportado no log final (ver secao
    # "6. LOG FINAL ESTRUTURADO" mais abaixo) E impresso AO VIVO na janela
    # de output do pyRevit conforme cada etapa comeca/termina. O log final
    # so' existe se o pipeline chegar ate' o fim - se travar (ou so'
    # demorar mais do que o usuario espera) ANTES disso, nenhum log e'
    # escrito e nao ha' como saber qual etapa estava rodando. A janela de
    # output do pyRevit e' uma janela PROPRIA (nao a barra de status do
    # Revit), que renderiza cada print/print_md assim que ele acontece -
    # entao "Etapa X iniciada" aparecendo e nunca sendo seguido do
    # "concluida" aponta exatamente qual etapa travou/esta' demorando,
    # em vez do usuario so' ver o Revit "Nao esta' respondendo" sem
    # nenhuma pista de onde. Cada entrada de `perf_stats` e' (rotulo,
    # segundos, detalhe_opcional).
    output = script.get_output()
    perf_stats = []

    def _perf_begin(label):
        output.print_md("**{}...**".format(label))
        return time.time()

    def _perf_mark(t0, label, detail=""):
        elapsed = time.time() - t0
        perf_stats.append((label, elapsed, detail))
        if detail:
            output.print_md("- concluido em {:.1f}s ({})".format(elapsed, detail))
        else:
            output.print_md("- concluido em {:.1f}s".format(elapsed))
        return time.time()

    # PERFORMANCE: repassado a analyze_created_walls_for_errors (etapa
    # "Analisar Paredes" - ver docstring de la') como `progress_cb` - e'
    # de longe a etapa que mais precisa de visibilidade AO VIVO: roda o
    # solver de blocos de VERDADE sobre cada parede (process_walls_one_by_one)
    # e, para as que nao fecham de primeira, chega a tentar ate'
    # WALL_GROUP_SHIFT_VERIFY_BUDGET vezes um deslocamento/ajuste de
    # comprimento diferente, RE-SOLVENDO A PLANTA INTEIRA a cada tentativa
    # so' para verificar se ela funcionou (ver find_wall_group_shift_fixes) -
    # um numero FINITO e limitado de tentativas, mas potencialmente muitos
    # segundos cada uma em plantas grandes, e sem nenhum feedback ate' aqui
    # nada disso aparecia na janela de output, mesmo com o resto do
    # pipeline (extracao/aberturas/pareamento/criacao das paredes) ja'
    # instrumentado. Aceita as DUAS assinaturas possiveis (ver
    # process_walls_one_by_one x find_wall_group_shift_fixes).
    def _solver_progress_cb(*args):
        # try/except em volta do corpo inteiro (2026-08-26): desde a
        # separacao ETAPA 1/ETAPA 2 (ver PARADA OBRIGATORIA... mais abaixo)
        # esta funcao pode ser chamada bem DEPOIS de main() ja ter
        # retornado - de dentro de _PostCreationEventHandler.Execute()
        # (acao "analyze", ver _execute_analyze),
        # disparado pelo clique em "Iniciar Modulacao" na janela de revisao
        # das Walls. Nesse ponto a janela de output do pyRevit desta
        # execucao pode ja ter sido fechada/reciclada - um erro aqui NUNCA
        # pode interromper o solver de blocos de verdade (que e' o que
        # importa), so' perder a linha de progresso.
        try:
            if len(args) == 1:
                # Heartbeat de UMA linha de texto (ver ETAPA 3C em
                # find_wall_group_shift_fixes): existe porque o laco de
                # candidatos ali pode descartar MUITAS tentativas como "nao
                # plausiveis" (geometria nao fecha) sem nunca gastar orcamento
                # de verificacao - e sem orcamento gasto, o progress_cb de 4
                # argumentos nunca e' chamado. Sem este heartbeat, a janela de
                # output ficava muda entre "parede 128/128 do solver
                # principal..." e o log final, exatamente o tipo de silencio
                # que faz o usuario achar que o script travou.
                (message,) = args
                output.print_md("    - {}".format(message))
            elif len(args) == 2:
                done, total = args
                output.print_md("    - parede {}/{} do solver principal...".format(done, total))
            elif len(args) == 4:
                attempt, total_attempts, wall_idx, kind = args
                output.print_md(
                    "    - tentativa de correcao {}/{} (parede {}, {})...".format(
                        attempt, total_attempts, wall_idx, kind
                    )
                )
        except Exception:
            pass

    # Feedback parede-a-parede (ver docstring de process_walls_one_by_one) na
    # janela de output do pyRevit - usados tanto pelo fluxo modeless quanto
    # pelo FALLBACK sincrono (ver o `except` em torno de
    # _show_wall_review_window, mais abaixo: quando a janela WinForms falha,
    # este e' o UNICO feedback ao vivo que o usuario tem, entao precisa das
    # mesmas mensagens "Solver 18"/eixo-a-eixo que a janela mostraria).
    def _solver_wall_start_cb(wall_idx, total, pos):
        try:
            output.print_md("    - analisando eixo {} ({}/{})...".format(wall_idx, pos, total))
        except Exception:
            pass

    def _solver_wall_result_cb(wall_idx, total, ok, detail):
        try:
            if ok:
                output.print_md("    - eixo {}: modulacao valida.".format(wall_idx))
            else:
                output.print_md("    - eixo {}: erro de modulacao ({}).".format(wall_idx, detail))
        except Exception:
            pass

    # 1. Seleciona o CAD no projeto
    cad_ref = revit.pick_element("Selecione a importacao/vinculo do AutoCAD")
    if not cad_ref:
        return

    # 2. Extrai todas as linhas e mapeia os Layers disponiveis
    t_step = _perf_begin("Extraindo linhas do CAD")
    options = Options()
    options.IncludeNonVisibleObjects = True
    geom_element = cad_ref.get_Geometry(options)
    if geom_element is None:
        forms.alert("O elemento selecionado nao possui geometria (nao parece ser um CAD).", exitscript=True)
        return

    cad_lines_by_layer = {}
    extract_lines_by_layer(geom_element, cad_lines_by_layer)
    t_step = _perf_mark(
        t_step, "Extracao de linhas do CAD",
        "{} layer(s), {} linha(s) no total".format(
            len(cad_lines_by_layer), sum(len(v) for v in cad_lines_by_layer.values())
        )
    )

    if not cad_lines_by_layer:
        forms.alert(
            "Nenhuma linha valida foi encontrada no CAD selecionado.\n"
            "Verifique se o elemento e' realmente um vinculo/importacao de CAD "
            "e se ha linhas retas (LINE) visiveis nele.",
            exitscript=True
        )
        return

    levels = FilteredElementCollector(doc).OfClass(Level).ToElements()
    level_dict = {lvl.Name: lvl for lvl in levels}
    if not level_dict:
        forms.alert("Nenhum Nivel foi encontrado no projeto.", exitscript=True)
        return

    # 3. CONFIGURACAO - uma unica janela para Layer, espessuras, Nivel,
    # altura e modo de identificacao das portas/janelas (ver _SetupForm; a
    # sequencia antiga de cinco caixas encadeadas continua disponivel como
    # plano B dentro de ask_setup).
    setup = ask_setup(cad_lines_by_layer, sorted(level_dict.keys()))
    if not setup:
        return

    selected_layer = setup["layer"]
    selected_level_name = setup["level"]
    selected_level = level_dict[selected_level_name]
    wall_height_value = setup["height_m"]
    wall_height_ft = wall_height_value * FEET_PER_METER

    # WallType base para duplicar (precisa ser uma parede Basica)
    basic_wall_types = get_basic_wall_types()
    if not basic_wall_types:
        forms.alert(
            "Nenhum Tipo de Parede Basica (Basic Wall) foi encontrado no "
            "projeto para servir de modelo.",
            exitscript=True
        )
        return
    base_wall_type = basic_wall_types[0]

    # WallTypes ja em uso por paredes reais do projeto - usados para casar
    # a espessura medida no CAD com um tipo "de verdade" ja existente, em
    # vez de sempre criar um "Parede CAD - Xcm" generico.
    preferred_wall_types = get_existing_wall_types_in_use(basic_wall_types)

    # Aberturas (janelas/portas) ja inseridas no projeto - coletadas AQUI,
    # antes da reconstrucao das linhas do Layer, porque merge_collinear_fragments
    # precisa delas para religar fragmentos separados pelo vao real de uma
    # porta/janela (ver _opening_bridges_gap). Sem isso, o vao de uma porta
    # (normalmente bem maior que MAX_JUNCTION_GAP_FT) nunca e' religado, e
    # NENHUM eixo de parede chega a passar por ali - o que faz tanto a
    # "boneca" ao lado da porta quanto o preenchimento acima da verga
    # ficarem sem onde nascer, mesmo com a logica de recorte por altura
    # correta.
    # A mensagem inicial e' generica de proposito (modo "pick" so' e'
    # decidido DENTRO de collect_opening_instances, que ja registra seu
    # proprio tempo/detalhe em `perf_stats` - ver a docstring de la'). No
    # modo "pick" esta etapa inclui o tempo de SELECAO INTERATIVA do
    # usuario (PickObjects so' retorna quando ele clica em Concluir/ESC) -
    # se a janela de output parar exatamente aqui, e' porque o Revit esta'
    # esperando o clique, nao porque o script travou.
    output.print_md("**Coletando aberturas (portas/janelas)...**")
    all_openings, openings_source_note = collect_opening_instances(setup["openings_mode"], perf_stats)
    if perf_stats:
        _label, _elapsed, _detail = perf_stats[-1]
        output.print_md(
            "- concluido em {:.1f}s ({})".format(_elapsed, _detail) if _detail
            else "- concluido em {:.1f}s".format(_elapsed)
        )

    # Validacao de modulacao de blocos estruturais (largura das aberturas -
    # ver cabecalho da secao VALIDACAO DE MODULACAO... mais acima). Leitura
    # pura de `all_openings`, sem nenhuma dependencia do modelo de paredes -
    # pode rodar aqui, antes de qualquer parede existir.
    t_step = _perf_begin("Validando modulacao das aberturas")
    opening_modulation_results = evaluate_opening_modulation(all_openings)
    opening_incompatible_modulation = [
        r for r in opening_modulation_results if not r["compatible"]
    ]
    opening_compatible_modulation_count = (
        len(opening_modulation_results) - len(opening_incompatible_modulation)
    )

    t_step = _perf_mark(t_step, "Validacao de modulacao das aberturas (evaluate_opening_modulation)")

    # Reconstroi fragmentos colineares (faces de parede que o CAD desenhou
    # quebradas nos pontos onde outra parede cruza, OU onde ha' uma porta/
    # janela real) na linha continua original, ANTES de formar os pares -
    # senao um fragmento sem par fica sem parede, dando a impressao de
    # parede "cortada" pela metade.
    t_step = _perf_begin("Religando fragmentos colineares de linha")
    lines_before_merge = len(cad_lines_by_layer[selected_layer])
    lines_to_process = merge_collinear_fragments(
        cad_lines_by_layer[selected_layer],
        COLLINEAR_MATCH_TOLERANCE_FT,
        MAX_JUNCTION_GAP_FT,
        all_openings,
        OPENING_GAP_PERP_TOLERANCE_FT,
        OPENING_GAP_WIDTH_SLACK_FT
    )
    t_step = _perf_mark(
        t_step, "Religamento de fragmentos colineares (merge_collinear_fragments)",
        "{} linha(s) do Layer -> {} linha(s) apos religar, {} abertura(s) usadas na busca".format(
            lines_before_merge, len(lines_to_process), len(all_openings)
        )
    )
    if len(lines_to_process) < 2:
        forms.alert("O Layer '{}' possui menos de 2 linhas - impossivel formar pares.".format(selected_layer))
        return

    # 3b. Pergunta ao usuario quais espessuras de parede ele deseja modelar
    # (uma ou mais). Somente pares de linhas cuja distancia perpendicular
    # corresponda a uma dessas espessuras (dentro da tolerancia de deteccao)
    # serao aceitos como parede em find_wall_pairs.
    if setup.get("thicknesses_cm"):
        target_thicknesses_ft = sorted(
            (cm / 100.0) * FEET_PER_METER for cm in setup["thicknesses_cm"]
        )
    else:
        # Plano B (_ask_setup_legacy): a janela unica nao pode ser
        # construida, entao as espessuras ainda nao foram perguntadas.
        target_thicknesses_ft = ask_wall_thicknesses(lines_to_process)
    if not target_thicknesses_ft:
        return
    detection_tolerance_ft = compute_detection_tolerance_ft(target_thicknesses_ft)

    # 4. Agrupamento de linhas paralelas e calculo do eixo central
    diagnostics = {
        "parallel_pairs": 0, "min_dist_ft": None, "max_dist_ft": None,
        "offset_suspect_count": 0, "offset_suspect_max_ft": 0.0,
        "cap_clipped_count": 0,
    }
    # `lines_to_process` e' passado tambem como fonte das LINHAS DE
    # FECHAMENTO (testas): sao linhas do MESMO Layer, transversais as faces,
    # que marcam onde cada parede fisicamente acaba (ver find_cap_positions).
    # `all_openings` entra aqui para que uma testa que caia dentro do vao de
    # uma porta/janela seja reconhecida como JAMBA e nao corte a parede -
    # que e' a excecao pedida para aberturas que so' existem no Revit.
    t_step = _perf_begin("Formando pares de linhas em paredes")
    walls_to_create, unused_lines = find_wall_pairs(
        lines_to_process, target_thicknesses_ft, detection_tolerance_ft,
        lines_to_process, all_openings, diagnostics
    )
    t_step = _perf_mark(
        t_step, "Formacao de pares de linhas em paredes (find_wall_pairs)",
        "{} linha(s) -> {} parede(s) formadas, {} linha(s) sem par".format(
            len(lines_to_process), len(walls_to_create), len(lines_to_process) - 2 * len(walls_to_create)
        )
    )

    # Paredes DETECTADAS no AutoCAD = pares validos (paralelismo + espessura
    # + sobreposicao + linhas de fechamento) encontrados por find_wall_pairs
    # ANTES de qualquer deduplicacao/extensao - usado no log final ("paredes
    # detectadas no AutoCAD" vs "paredes criadas"). Fica em 0 se a rodada
    # normal de deteccao nao formou nenhum par (modo de recuperacao manual
    # abaixo, se usado, e' contado separadamente).
    detected_count = len(walls_to_create)
    recovery_mode_used = False

    if not walls_to_create:
        # Nao foi possivel casar nenhum par de linhas paralelas com as
        # espessuras escolhidas - em vez de simplesmente desistir, oferece
        # ao usuario gerar uma parede para cada linha do Layer usando uma
        # das espessuras ja escolhidas (util para CADs onde a parede e'
        # desenhada com uma unica linha, sem par).
        wants_manual = forms.alert(
            build_no_pairs_message(
                selected_layer, len(lines_to_process), diagnostics,
                target_thicknesses_ft, detection_tolerance_ft
            ) +
            "\n\nDeseja gerar uma parede para CADA linha do Layer (cada linha "
            "vira o eixo de uma parede), usando uma das espessuras escolhidas?",
            title="Nenhum par valido encontrado",
            yes=True, no=True
        )
        if not wants_manual:
            return

        if len(target_thicknesses_ft) == 1:
            manual_thickness_ft = target_thicknesses_ft[0]
        else:
            thickness_labels = {
                "{} cm".format(round(t / FEET_PER_METER * 100.0, 1)): t
                for t in target_thicknesses_ft
            }
            chosen_label = forms.SelectFromList.show(
                sorted(thickness_labels.keys()),
                title="Espessura para as linhas sem par",
                multiselect=False
            )
            if not chosen_label:
                return
            manual_thickness_ft = thickness_labels[chosen_label]

        walls_to_create = [
            (line, manual_thickness_ft, (False, False))
            for line in lines_to_process
            if line.ApproximateLength >= MIN_WALL_SEGMENT_ABS_FLOOR_FT
        ]
        if not walls_to_create:
            forms.alert(
                "Nenhuma linha do Layer '{}' tem comprimento suficiente para virar parede.".format(selected_layer),
                exitscript=True
            )
            return
        unused_lines = []
        recovery_mode_used = True
        detected_count = len(walls_to_create)

    # 4a. NAO existe mais recuperacao "cega" de linhas sem par: transformar
    # QUALQUER linha nao pareada em parede (usando a propria linha como
    # eixo, so' porque havia uma parede qualquer por perto) criava paredes
    # em lugares onde nao ha par de linhas na espessura escolhida - ou seja,
    # o script passava a desenhar parede em cima de praticamente toda linha
    # do Layer, nao so' das que realmente representam uma parede de 14cm (ou
    # outra espessura escolhida). Uma parede so' e' criada quando find_wall_pairs
    # confirma duas linhas PARALELAS na distancia certa (ver find_wall_pairs).
    # As linhas que sobram aqui sao apenas contabilizadas para diagnostico.
    still_missing_count = len(unused_lines)

    # 4a1. Validacao final: entre as linhas que sobraram sem par (acima),
    # procura pares que MESMO ASSIM parecem geometricamente uma
    # parede/boneca legitima, so' que em espessura(s) fora das escolhidas
    # pelo usuario - ver scan_possible_missed_bonecas. Nao cria nada
    # automaticamente a partir disso; so' avisa no resumo final.
    t_step = _perf_begin("Procurando bonecas perdidas em espessuras nao escolhidas")
    possible_missed_bonecas = scan_possible_missed_bonecas(unused_lines)
    t_step = _perf_mark(t_step, "Busca de bonecas perdidas (scan_possible_missed_bonecas)")

    # 4a2. Remove paredes duplicadas/sobrepostas na mesma posicao (mesmo
    # eixo, mesma espessura) - ex.: mais de uma linha paralela no CAD
    # representando a mesma face (hachura/cota duplicada), que produziria
    # mais de uma parede empilhada no mesmo lugar.
    t_step = _perf_begin("Removendo paredes duplicadas/sobrepostas")
    walls_to_create, duplicates_removed_count = deduplicate_walls(walls_to_create)
    t_step = _perf_mark(
        t_step, "Deduplicacao de paredes (deduplicate_walls)",
        "{} parede(s) removida(s) por duplicidade".format(duplicates_removed_count)
    )

    # 4b. Fecha encontros em T/L: estica a ponta de cada parede ate' a FACE
    # OPOSTA da parede perpendicular com a qual ela se encontra (nao apenas
    # ate' o eixo dela), garantindo sobreposicao real e o encontro fechado
    # sem frestas. So' estica pontas que ja estao perto de um encontro
    # legitimo - nunca encurta nada.
    t_step = _perf_begin("Fechando encontros em T/L entre paredes")
    walls_to_create, wall_junction_map = extend_wall_ends_to_junctions(
        walls_to_create, JUNCTION_FACE_SEARCH_FT
    )
    t_step = _perf_mark(
        t_step, "Fechamento de encontros T/L (extend_wall_ends_to_junctions)",
        "{} parede(s) no total".format(len(walls_to_create))
    )

    # 4b1. ETAPA 2 - grafo de paredes: classifica cada encontro (ponta livre,
    # continuacao reta, canto L, T ou cruz X) a partir do MESMO calculo
    # geometrico que acabou de fechar os encontros acima (`wall_junction_map`
    # - ver o docstring de extend_wall_ends_to_junctions e build_wall_graph).
    # So' leitura - nao altera walls_to_create nem cria nada no Revit ainda;
    # o grafo e' consumido pelas proximas etapas (ajuste de aberturas perto
    # de encontro, e o solver de blocos L/T/X).
    t_step = _perf_begin("Montando o grafo de encontros entre paredes")
    wall_graph_nodes, wall_end_to_node = build_wall_graph(walls_to_create, wall_junction_map)
    t_step = _perf_mark(t_step, "Grafo de paredes (build_wall_graph)", "{} no(s)".format(len(wall_graph_nodes)))

    # 4b2. Validacao final: extend_wall_ends_to_junctions so' alonga pontas
    # em direcao a paredes PERPENDICULARES (nunca paralelas - ver a propria
    # funcao), entao nao deveria introduzir duplicatas novas entre paredes
    # colineares - mas confere de novo aqui (sem remover nada desta vez,
    # so' contando) como rede de seguranca contra esse caso raro, cobrindo
    # o requisito de que a correcao dos outros itens nao gere paredes
    # duplicadas/sobrepostas.
    _, residual_duplicates_count = deduplicate_walls(walls_to_create)

    # 4c. Validacao final da geometria: paredes cujo eixo cair fora dos
    # limites reais desenhados na planta (bounding box de todas as linhas do
    # Layer, com uma margem para encontros/cantos legitimos) sao sinalizadas
    # - nao sao descartadas automaticamente (podem ser um encontro legitimo
    # com uma parede de um Layer vizinho), mas o usuario e' avisado no resumo
    # final para poder conferir.
    plan_x_min, plan_x_max, plan_y_min, plan_y_max = build_plan_bounds(lines_to_process, PLAN_BOUNDS_MARGIN_FT)

    def _wall_out_of_bounds(centerline):
        for idx in (0, 1):
            p = centerline.GetEndPoint(idx)
            if not (plan_x_min <= p.X <= plan_x_max and plan_y_min <= p.Y <= plan_y_max):
                return True
        return False

    out_of_bounds_count = sum(1 for centerline, _, _ in walls_to_create if _wall_out_of_bounds(centerline))

    # 4d. `all_openings' ja foi coletado antes (ver acima, usado tambem por
    # merge_collinear_fragments). Cada parede a criar sera fatiada para
    # deixar livre apenas a faixa real (peitoril->verga, na largura do vao)
    # de qualquer abertura alinhada a ela, preenchendo com parede os vazios
    # remanescentes acima/abaixo (incluindo o trecho ACIMA da verga ate' o
    # topo do pe-direito). A associacao abertura->parede e' feita UMA VEZ
    # aqui para todas as paredes de uma vez (nao parede a parede dentro do
    # loop de criacao abaixo), porque assign_openings_to_walls precisa
    # comparar TODAS as paredes candidatas entre si para escolher, para
    # cada abertura, a mais proxima com exclusividade (ver docstring) -
    # isso e' o que garante que a "parede acima" de uma porta/janela nunca
    # seja recortada em mais de uma parede ao mesmo tempo.
    opening_diagnostics = {
        "clamped_opening_count": 0,
        "opening_off_center_count": 0,
        "opening_center_gap_max_ft": 0.0,
        "unassigned_openings": [],
    }
    t_step = _perf_begin("Associando aberturas as paredes mais proximas")
    openings_per_wall = assign_openings_to_walls(walls_to_create, all_openings, opening_diagnostics)
    t_step = _perf_mark(
        t_step, "Associacao de aberturas as paredes (assign_openings_to_walls)",
        "{} parede(s) x {} abertura(s)".format(len(walls_to_create), len(all_openings))
    )

    # A antiga ETAPA 1 (ajuste previo de abertura ANTES da criacao, com
    # janela modal de confirmacao) foi REMOVIDA - decisao explicita do
    # usuario: as paredes agora nascem sempre dos eixos originais do CAD
    # (equivale a sempre "Cancelar" na antiga janela) e toda a correcao de
    # parede+abertura passa a acontecer DEPOIS, sobre os elementos REAIS ja'
    # criados, na janela unica (ver ETAPA 3B, secao acima de
    # _classify_wall_axis_segments, chamada logo apos a Transacao de
    # criacao mais abaixo).

    # 4e. Trechos suspeitos (paredes travadas por uma testa REAL do CAD sem
    # abertura/parede vizinha que explique) - feature REMOVIDA por completo
    # (2026-08-26, pedido explicito do usuario). O vermelho agora sinaliza
    # comprimento quebrado (ver secao ETAPA 2/FASE 2 - evaluate_wall_
    # modulation/_apply_broken_length_overrides), nao mais este diagnostico.

    base_z_abs = selected_level.Elevation
    top_z_abs = base_z_abs + wall_height_ft
    openings_used = 0

    # Diagnostico: aberturas cuja altura lida (Peitoril + Altura_abertura)
    # chega a encostar ou ultrapassar o pe-direito da parede - nesse caso
    # NAO sobra espaco para o preenchimento ACIMA da verga (build_wall_segments
    # nao cria esse segmento porque a altura resultante seria zero/negativa).
    # Isso nao e' um bug de calculo: se a altura lida realmente e' >= ao
    # pe-direito, nao ha, geometricamente, nenhuma parede para desenhar ali
    # em cima - o problema esta' no valor gravado no parametro
    # `Altura_abertura` (ou `Peitoril`) dessa instancia/tipo no Revit.
    openings_capped_at_top = 0
    capped_head_cm_samples = []

    # Validacao final MEDIDA dentro do Revit: quantas paredes, depois de
    # criadas e realinhadas pelo nucleo, ainda ficaram fora da posicao
    # pretendida em planta, e qual foi o pior desvio (ver o passo 2 do bloco
    # de criacao). Diferente das demais verificacoes deste script (que sao
    # puramente geometricas, sobre as linhas do CAD), esta le de volta a
    # posicao REAL da parede no modelo.
    placement_deviation_count = 0
    placement_deviation_max_ft = 0.0

    # 5. Transacao no Revit - criacao das paredes
    wall_type_cache = {}
    created_count = 0
    cad_segments_created = 0
    opening_segments_created = 0
    walls_with_opening_segments = set()
    # Lista de falhas desta execucao - alimenta o resumo final mais abaixo
    # (a antiga Etapa 1 de ajuste previo de abertura, que tambem escrevia
    # aqui, foi removida - ver comentario logo acima de openings_per_wall).
    failures = []

    # Rastreio dos trechos de verga/peitoril realmente enviados ao Revit
    # (pontos passados a Wall.Create e pontos lidos de volta depois) - ver
    # build_opening_trace_log.
    created_opening_segments = []

    # TODOS os ElementIds de Wall criados nesta execucao (segmentos "cad" E
    # "abertura" - ver evaluate_wall_modulation) - usados pela validacao de
    # modulacao de blocos estruturais logo apos o loop de criacao abaixo.
    created_wall_ids_all = []

    # Por EIXO (wall_idx em walls_to_create): lista de (ElementId, seg_origin)
    # na ORDEM em que os segmentos aparecem ao longo do eixo - usada pela
    # Parte C (sugestao de ampliacao de comodo/deslocamento de abertura,
    # ver mais abaixo) para localizar os elementos Wall reais de um eixo
    # especifico. Um eixo sem nenhuma abertura tem exatamente 1 entrada
    # ("cad"); um eixo com abertura(s) tem varias, intercalando "cad" e
    # "abertura".
    created_walls_by_axis = {}

    # MODELO INTERNO LEVE (solver-em-memoria): por EIXO, a mesma lista de
    # created_walls_by_axis mas com t_a/t_b (posicao no eixo) ja projetada -
    # capturado UMA UNICA VEZ logo apos cada Wall ser criada/realinhada
    # abaixo (ver _axis_t_of_point). A partir do clique em "Iniciar
    # Modulacao", toda a analise/planejamento (_classify_wall_axis_segments,
    # plan_axis_opening_fix, process_walls_one_by_one,
    # find_wall_group_shift_fixes, analyze_created_walls_for_errors) usa
    # este snapshot em vez de reler target_doc.GetElement(...).Location.Curve
    # a cada tentativa - a geometria real so' muda de novo em "Ajustar
    # Erros" (que continua lendo/escrevendo ao vivo). So' tipos primitivos
    # (float/ElementId) - nunca Wall/LocationCurve - para poder ser usado
    # com seguranca fora da thread principal da API.
    wall_segment_geometry = {}

    t_step = _perf_begin("Criando as paredes no Revit ({} eixo(s))".format(len(walls_to_create)))
    t = Transaction(doc, "Gerar Paredes Automaticas do CAD")
    t.Start()
    try:
        for wall_idx, (centerline, thickness_ft, _locked_ends) in enumerate(walls_to_create):
            openings_on_line = openings_per_wall[wall_idx]
            if openings_on_line:
                openings_used += len(openings_on_line)
                for _, _, sill_z_abs, head_z_abs in openings_on_line:
                    if head_z_abs >= top_z_abs - MIN_SEGMENT_HEIGHT_FT:
                        openings_capped_at_top += 1
                        if len(capped_head_cm_samples) < 6:
                            capped_head_cm_samples.append(
                                round((head_z_abs - base_z_abs) / FEET_PER_METER * 100.0, 1)
                            )
            segments = build_wall_segments(centerline, base_z_abs, wall_height_ft, openings_on_line)

            try:
                wall_type = get_or_create_wall_type(
                    thickness_ft, base_wall_type, basic_wall_types, preferred_wall_types, wall_type_cache
                )
            except Exception as type_ex:
                failures.append(str(type_ex))
                continue

            # Cada SEGMENTO e' criado em seu proprio try/except: sem isso,
            # uma falha num unico segmento (ex.: o preenchimento acima da
            # verga de uma porta) abortava a criacao de TODOS os segmentos
            # restantes dessa mesma parede (inclusive os que viriam depois
            # dele), deixando trechos da parede sumidos sem nenhum aviso.
            for sub_line, seg_height_ft, seg_base_offset_ft, seg_origin in segments:
                try:
                    new_wall = Wall.Create(
                        doc,
                        sub_line,
                        wall_type.Id,
                        selected_level.Id,
                        seg_height_ft,
                        seg_base_offset_ft,  # Offset da base
                        False,  # Flip
                        False   # Structural
                    )
                    # Desliga o auto-join do Revit nas duas pontas ANTES de
                    # qualquer reposicionamento abaixo: por padrao o Revit
                    # tenta "limpar" o encontro entre paredes que se tocam ou
                    # se cruzam, esticando/aparando a extremidade para formar
                    # um canto/uniao bonito. Isso alteraria a geometria e a
                    # posicao calculadas pelo script (incluindo os segmentos
                    # fatiados ao redor de aberturas), entao e' desativado
                    # para que cada segmento permaneca exatamente como criado.
                    WallUtils.DisallowWallJoinAtEnd(new_wall, 0)
                    WallUtils.DisallowWallJoinAtEnd(new_wall, 1)

                    # Wall.Create posiciona a parede pelo centro do PACOTE
                    # INTEIRO de camadas (WallCenterline, padrao deste
                    # overload). Se o WallType tiver camadas NAO estruturais
                    # assimetricas entre os dois lados (ex.: reboco/acabamento
                    # so' num lado, comum em tipos reais reaproveitados do
                    # projeto), o NUCLEO - que e' o que precisa coincidir com
                    # o eixo medido no CAD - nasce deslocado lateralmente por
                    # METADE dessa assimetria. Com 1cm de acabamento de um
                    # lado so', isso da' exatamente os ~0,5cm relatados.
                    #
                    # Regenerar aqui resolve a geometria da parede recem
                    # criada (Wall.Create so' AGENDA a criacao) para que as
                    # duas etapas seguintes operem sobre referencias reais.
                    doc.Regenerate()

                    # Passo 1: declara que a Linha de Referencia desta parede
                    # e' o NUCLEO (CoreCenterline). ATENCAO - e' essencial
                    # entender o que este passo faz e o que NAO faz: mudar a
                    # Linha de Referencia de uma parede JA EXISTENTE **nao
                    # move a parede** (mesmo comportamento da interface do
                    # Revit). A parede fica fisicamente onde esta' e o Revit
                    # apenas passa a reportar/aceitar a curva de localizacao
                    # medida no novo plano de referencia. Uma versao anterior
                    # deste script parava aqui, presumindo que este Set
                    # reposicionaria o pacote de camadas - nao reposiciona, e
                    # por isso o deslocamento de ~0,5cm sobrevivia intacto.
                    loc_line_param = new_wall.get_Parameter(BuiltInParameter.WALL_KEY_REF_PARAM)
                    if loc_line_param is not None and not loc_line_param.IsReadOnly:
                        loc_line_param.Set(int(WallLocationLine.CoreCenterline))
                        doc.Regenerate()

                    # Passo 2: e' ESTE passo que efetivamente alinha a parede.
                    # Com a Linha de Referencia agora sendo o NUCLEO, reescrever
                    # a curva de localizacao MOVE a parede ate' que o nucleo
                    # caia exatamente sobre `sub_line` - independentemente de
                    # quais camadas de acabamento o WallType tenha e de que
                    # lado elas estejam. Isso tambem elimina uma segunda fonte
                    # de erro da versao anterior: como o lado "externo" de uma
                    # parede depende do SENTIDO em que sua curva foi desenhada,
                    # duas paredes colineares desenhadas em sentidos opostos no
                    # CAD recebiam o desvio de acabamento em direcoes OPOSTAS -
                    # ficando ~1cm deslocadas UMA DA OUTRA, o que e' justamente
                    # onde o erro mais aparece: bonecas e trechos curtos ao
                    # lado de portas/janelas, encostados em paredes longas.
                    #
                    # A curva alvo e' reconstruida na elevacao Z ATUAL da
                    # parede (nivel + offset de base), nao na elevacao do CAD
                    # que `sub_line` carrega - so' o alinhamento em PLANTA
                    # (XY) deve ser imposto aqui; mexer no Z brigaria com o
                    # nivel/offset ja definidos na criacao.
                    wall_location = new_wall.Location
                    if isinstance(wall_location, LocationCurve):
                        current_curve = wall_location.Curve
                        wall_z = current_curve.GetEndPoint(0).Z
                        target_curve = Line.CreateBound(
                            XYZ(sub_line.GetEndPoint(0).X, sub_line.GetEndPoint(0).Y, wall_z),
                            XYZ(sub_line.GetEndPoint(1).X, sub_line.GetEndPoint(1).Y, wall_z)
                        )
                        wall_location.Curve = target_curve
                        doc.Regenerate()

                        # Validacao final MEDIDA DENTRO DO REVIT (nao
                        # presumida): le de volta onde a parede realmente
                        # ficou e compara, em planta, com onde ela deveria
                        # estar. Qualquer desvio residual e' contabilizado e
                        # reportado no resumo - e' a unica forma de confirmar
                        # o alinhamento sem depender de suposicoes sobre o
                        # comportamento interno do Revit.
                        final_curve = new_wall.Location.Curve
                        deviation_ft = _xy_deviation_ft(final_curve, target_curve)
                        if deviation_ft > AXIS_OFFSET_WARNING_FT:
                            placement_deviation_count += 1
                            placement_deviation_max_ft = max(
                                placement_deviation_max_ft, deviation_ft
                            )
                    created_count += 1
                    created_wall_ids_all.append(new_wall.Id)
                    created_walls_by_axis.setdefault(wall_idx, []).append((new_wall.Id, seg_origin))
                    # Captura do snapshot leve (ver wall_segment_geometry,
                    # declarado antes deste laco) - mesma projecao que
                    # _classify_wall_axis_segments faria ao vivo, feita AQUI
                    # (uma unica vez, com a Wall ja regenerada/realinhada)
                    # para nunca mais precisar reler isto depois.
                    try:
                        _seg_curve = new_wall.Location.Curve
                        _seg_t_a = _axis_t_of_point(centerline, _seg_curve.GetEndPoint(0))
                        _seg_t_b = _axis_t_of_point(centerline, _seg_curve.GetEndPoint(1))
                        if _seg_t_a > _seg_t_b:
                            _seg_t_a, _seg_t_b = _seg_t_b, _seg_t_a
                        wall_segment_geometry.setdefault(wall_idx, []).append({
                            "element_id": new_wall.Id, "seg_origin": seg_origin,
                            "t_a": _seg_t_a, "t_b": _seg_t_b,
                        })
                    except Exception:
                        # Nunca pode derrubar a criacao das paredes por causa
                        # do snapshot - na pior hipotese este eixo fica com
                        # uma entrada incompleta e _classify_wall_axis_segments
                        # trata como "fora de escopo" (len(snapshot) !=
                        # len(entries), ver seu docstring) em vez de usar
                        # dado parcial/errado.
                        pass
                    if seg_origin == "abertura":
                        opening_segments_created += 1
                        walls_with_opening_segments.add(wall_idx)
                        # Guarda os pontos EXATOS enviados a Wall.Create e os
                        # que o Revit devolveu, achatados em Z para poderem
                        # ser comparados em planta no log (ver
                        # build_opening_trace_log).
                        final_curve_pts = None
                        try:
                            fc = new_wall.Location.Curve
                            final_curve_pts = (
                                XYZ(fc.GetEndPoint(0).X, fc.GetEndPoint(0).Y, 0.0),
                                XYZ(fc.GetEndPoint(1).X, fc.GetEndPoint(1).Y, 0.0),
                            )
                        except Exception:
                            pass
                        created_opening_segments.append({
                            "wall_idx": wall_idx,
                            "sent_p0": XYZ(sub_line.GetEndPoint(0).X, sub_line.GetEndPoint(0).Y, 0.0),
                            "sent_p1": XYZ(sub_line.GetEndPoint(1).X, sub_line.GetEndPoint(1).Y, 0.0),
                            "final_p0": final_curve_pts[0] if final_curve_pts else None,
                            "final_p1": final_curve_pts[1] if final_curve_pts else None,
                            "height_ft": seg_height_ft,
                            "base_offset_ft": seg_base_offset_ft,
                        })
                    else:
                        cad_segments_created += 1
                except Exception as wall_ex:
                    failures.append(str(wall_ex))

        # Validacao de modulacao de blocos estruturais (comprimento das
        # paredes - ver cabecalho VALIDACAO DE MODULACAO... mais acima).
        # Le o comprimento REAL/final de cada Wall criado (ja' depois do
        # realinhamento pelo nucleo feito acima) e destaca em AZUL as
        # incompativeis, junto com as aberturas incompativeis calculadas
        # antes da transacao (ver opening_incompatible_modulation).
        #
        # O cache de vaos e' descartado ANTES: as aberturas desta execucao
        # acabaram de ser consideradas e as paredes acabaram de ser criadas,
        # entao qualquer lista de vaos anterior esta' velha. E' ela que
        # decide quais paredes valem como PILARETE - e essas, desde
        # 2026-08-21, sempre voltam compatible=True daqui (ver
        # PIER_AT_OPENING_VALID_LAST_DIGITS_CM/evaluate_wall_modulation);
        # so' o solver de blocos real (Etapa 3B) decide se precisam de ajuste.
        _invalidate_opening_gap_cache(doc)
        modulation_results = evaluate_wall_modulation(created_wall_ids_all, doc)
        incompatible_modulation = [r for r in modulation_results if not r["compatible"]]
        compatible_modulation_count = len(modulation_results) - len(incompatible_modulation)
        # Tres categorias, checadas NESTA ordem de prioridade (ver
        # evaluate_wall_block_length/is_clean_cm) - VERMELHO tem
        # PRECEDENCIA sobre azul, inclusive sobre uma parede que a
        # aritmetica de modulacao classificaria como `compatible=True`
        # (tolerancia LARGA de MODULATION_WHOLE_CM_TOLERANCE_CM absorve um
        # residuo pequeno tipo 25,01cm silenciosamente - o usuario pediu
        # para ver isso sinalizado e corrigido de qualquer forma, ANTES de
        # confiar na modulacao):
        #   VERMELHO: `not is_clean_cm` (residuo/imprecisao geometrica -
        #     ver _apply_broken_length_overrides), qualquer que seja
        #     `compatible`;
        #   AZUL: `is_clean_cm` E `not compatible` (comprimento limpo mas
        #     nenhuma combinacao de blocos+juntas fecha nele - ver
        #     _apply_modulation_incompatible_overrides);
        #   normal: `is_clean_cm` E `compatible`.
        # Aberturas continuam so' azul (regra de digito final, nao tem o
        # mesmo conceito de residuo).
        broken_length_walls = [r for r in modulation_results if not r["is_clean_cm"]]
        non_modular_walls = [
            r for r in modulation_results if r["is_clean_cm"] and not r["compatible"]
        ]
        try:
            _apply_broken_length_overrides(
                doc.ActiveView, [r["id"] for r in broken_length_walls]
            )
        except Exception as override_ex:
            failures.append(
                "Falha ao aplicar realce vermelho de comprimento quebrado: {}".format(override_ex)
            )
        try:
            _apply_modulation_incompatible_overrides(
                doc.ActiveView,
                [r["id"] for r in non_modular_walls] +
                [r["element_id_obj"] for r in opening_incompatible_modulation]
            )
        except Exception as override_ex:
            failures.append(
                "Falha ao aplicar realce azul de incompatibilidade de modulacao: {}".format(override_ex)
            )

        t.Commit()
    except Exception:
        t.RollBack()
        raise
    t_step = _perf_mark(
        t_step, "Criacao das paredes no Revit (Transaction + Wall.Create)",
        "{} elemento(s) Wall criado(s)".format(created_count)
    )

    # Arma o ESCOPO do validador ao vivo (ver secao VALIDADOR AO VIVO... e
    # _register_modulation_updaters_if_needed, mais acima).
    #
    # ESCOPO: QUALQUER Wall / QUALQUER FamilyInstance do DOCUMENTO INTEIRO
    # (ElementClassFilter), NAO so' os Ids criados/considerados NESTA
    # execucao. Antes disto era uma lista fixa de ElementIds (so'
    # created_wall_ids_all/opening_instance_ids) - o problema reportado
    # (parede editada para um comprimento valido e o azul nao sumia
    # sozinho) apontou para casos em que a parede ficava fora dessa lista
    # fixa (ex.: reestruturada por um ajuste pos-criacao, que pode
    # mexer em segmentos fora desta lista) - um filtro por CLASSE elimina essa categoria
    # inteira de bug, ao custo de tambem vigiar paredes/instancias que
    # nunca fizeram parte do resumo desta automacao (qualquer parede do
    # projeto passa a ganhar/perder o azul sozinha ao ter o comprimento
    # editado - decisao deliberada, ver conversa que motivou esta troca).
    #
    # Falha aqui e' so' registrada no log, nunca interrompe o script (o
    # validador "de uma vez" ja' rodou e ja' aplicou o azul/vermelho acima
    # de qualquer forma).
    # DOIS ChangeType por escopo, nao um so': Element.GetChangeTypeAny()
    # cobre MODIFICACAO de um elemento que ja' existia, mas NAO cobre a
    # ADICAO de um elemento novo - confirmado empiricamente (criar uma
    # parede vizinha nao disparava nada; mover essa mesma parede logo
    # depois disparava). Sem GetChangeTypeElementAddition() o
    # GetAddedElementIds() lido dentro dos Execute() e' codigo morto.
    try:
        wall_class_filter = ElementClassFilter(Wall)
        family_instance_filter = ElementClassFilter(FamilyInstance)
        change_types = (Element.GetChangeTypeAny(), Element.GetChangeTypeElementAddition())

        for change_type in change_types:
            UpdaterRegistry.AddTrigger(
                wall_modulation_updater.GetUpdaterId(), doc,
                wall_class_filter, change_type
            )
            UpdaterRegistry.AddTrigger(
                opening_modulation_updater.GetUpdaterId(), doc,
                family_instance_filter, change_type
            )
    except Exception as trigger_ex:
        failures.append(
            "Falha ao armar o validador ao vivo de modulacao: {}".format(trigger_ex)
        )

    # Catalogo de blocos - carregado AQUI (antes precisava esperar a janela
    # abrir) porque "Analisar Paredes" agora precisa dele para rodar o
    # solver de blocos DE VERDADE (ver analyze_created_walls_for_errors,
    # ETAPA 3B reescrita 2026-08-20). Passado adiante para
    # _show_post_creation_window nao carregar de novo.
    catalog, catalog_missing = load_fixed_block_catalog(doc)

    # ==========================================
    # PARADA OBRIGATORIA - FIM DA ETAPA 1 (CRIAR WALLS)
    # ==========================================
    # Regra do usuario: criar as Walls e lancar os blocos sao operacoes
    # DIFERENTES - terminar a criacao das Walls nunca pode, sozinho,
    # comecar a modulacao (nem so' o SOLVER em memoria de
    # analyze_created_walls_for_errors, que ja e' o pipeline INTEIRO -
    # ETAPA 3B/3C/multi-fiada/auditoria - mesmo sem escrever nada ainda
    # no Revit). Em vez de chamar analyze_created_walls_for_errors direto
    # daqui (como esta funcao fazia antes desta separacao), a execucao
    # PARA: abre so' _WallReviewForm, com o resumo da CRIACAO das Walls
    # (nenhum numero de modulacao aparece - nenhuma analise rodou ainda)
    # e um unico botao, "Iniciar Modulacao". So' o CLIQUE nesse botao (ver
    # _PostCreationEventHandler._execute_analyze) dispara analyze_created_walls_for_errors
    # e tudo que vinha depois dele - a secao "6. LOG FINAL ESTRUTURADO" e a
    # janela de resultado de verdade (_show_post_creation_window) - reunido
    # abaixo em `_run_stage2_modulation`, chamado UNICAMENTE por esse
    # clique (nunca automaticamente).
    if not created_wall_ids_all:
        forms.alert(
            "Nenhuma parede foi criada nesta execucao - nada para revisar "
            "ou modular.",
            title="Modulacao Automatica - Resultado"
        )
        return

    # ExternalEvent da ETAPA 2 (Tela de Modulacao dos Blocos) criado JA'
    # AQUI, ainda dentro da execucao sincrona da API do Revit - mesmo
    # motivo/comentario de stage2_external_event no fluxo "utilizar
    # paredes existentes" (run_modulation_on_existing_walls) e em
    # _show_post_creation_window (`precreated_event`/`precreated_handler`):
    # `_run_stage2_modulation` abaixo so' e' chamada depois que main() ja'
    # retornou (via Control.BeginInvoke no fim da acao "analyze", ou direto
    # de um Click de WinForms no botao "Pular"), entao criar o
    # ExternalIEvent LA' DENTRO lanca "Attempting to create an ExternalEvent
    # outside of a standard API execution" (bug real reportado pelo
    # usuario, 2026-08-27).
    stage2_handler = _PostCreationEventHandler()
    stage2_external_event = ExternalEvent.Create(stage2_handler)

    def _run_stage2_modulation(wall_error_rows):
        # `wall_error_rows is None` (nunca `[]`, que e' o resultado legitimo
        # de "analisou e nao achou erro") e' o sinal de que o usuario clicou
        # "Pular para Modulacao dos Blocos" em _WallReviewForm (2026-08-27) -
        # a analise de erros de parede NUNCA rodou. `skipped_wall_analysis`
        # carrega essa distincao para o relatorio/janela da Tela 2 (ver
        # `report["wall_analysis_skipped"]` abaixo e
        # _PostCreationForm._populate_error_rows).
        skipped_wall_analysis = wall_error_rows is None
        if skipped_wall_analysis:
            wall_error_rows = []
        try:
            # ver o mesmo cuidado documentado em _solver_progress_cb: esta
            # funcao roda depois de main() ja ter retornado.
            if skipped_wall_analysis:
                output.print_md(
                    "**Modulacao das paredes PULADA a pedido do usuario - "
                    "indo direto para a Tela 2 (Modulacao dos Blocos).**"
                )
            else:
                output.print_md(
                    "**Analise/modulacao de blocos concluida - {} parede(s) com "
                    "problema encontrada(s).**".format(len(wall_error_rows))
                )
        except Exception:
            pass
        # ==========================================
        # 6. LOG FINAL ESTRUTURADO
        # ==========================================
        # Reorganiza TODOS os diagnosticos coletados ao longo da execucao (nao
        # so' o resultado final) nas categorias pedidas: paredes detectadas no
        # AutoCAD, paredes criadas, paredes ignoradas (com motivo individual),
        # pequenos trechos/bonecas, paredes/trechos gerados a partir de
        # aberturas selecionadas no Revit, e segmentos com geometria ambigua a
        # conferir manualmente. Nenhum diagnostico existente foi removido - so'
        # reagrupado sob esses titulos.
        axes_created_count = len(walls_to_create)
        ignored_lines_count = len(unused_lines) + duplicates_removed_count

        lines = []
        lines.append("=== LOG DE MODELAGEM - Layer '{}' ===".format(selected_layer))
        lines.append("")

        # --- Diagnostico de performance (ver PERFORMANCE em main()) ---
        # Tempo (e contagens) de cada etapa desde a extracao do CAD ate' a
        # criacao das paredes no Revit - ANTES da modulacao de blocos (que tem
        # seu proprio relatorio, ver build_final_modulation_report). As mesmas
        # linhas ja apareceram AO VIVO na janela de output conforme cada etapa
        # rodava (ver _perf_begin/_perf_mark) - aqui ficam reunidas num unico
        # lugar, junto com o resto do log. Existe para que, se o script ainda
        # parecer lento (ou travado) em algum projeto real, o proximo relato
        # traga numeros concretos (qual etapa, quantas linhas/aberturas/paredes)
        # em vez de precisar adivinhar de novo - e, se a janela de output
        # mostrar uma etapa "iniciada" sem nunca aparecer "concluida", essa e' a
        # que travou (o log final abaixo, por definicao, so' existe se o
        # pipeline chegou ate' o fim).
        if perf_stats:
            total_perf_s = sum(elapsed for _label, elapsed, _detail in perf_stats)
            lines.append("--- Diagnostico de performance (deteccao + criacao das paredes) ---")
            for label, elapsed, detail in perf_stats:
                if detail:
                    lines.append("  {}: {:.1f}s ({})".format(label, elapsed, detail))
                else:
                    lines.append("  {}: {:.1f}s".format(label, elapsed))
            lines.append("  TOTAL ate' a criacao das paredes: {:.1f}s".format(total_perf_s))
            lines.append("")

        # --- Paredes detectadas no AutoCAD ---
        if recovery_mode_used:
            lines.append(
                "Paredes detectadas no AutoCAD: 0 pares validos (nenhuma linha "
                "formou par na(s) espessura(s) escolhida(s) - usado o modo de "
                "recuperacao manual: {} linha(s) viraram eixo de parede "
                "individualmente).".format(detected_count)
            )
        else:
            lines.append("Paredes detectadas no AutoCAD (pares validos): {}.".format(detected_count))

        # --- Paredes criadas ---
        lines.append(
            "Paredes criadas: {} eixo(s) de parede -> {} elemento(s) Wall no "
            "Revit ({} trecho(s) cheio(s) definidos pelo AutoCAD + {} trecho(s) "
            "de verga/peitoril definidos por abertura selecionada) no Nivel "
            "'{}'.".format(
                axes_created_count, created_count, cad_segments_created,
                opening_segments_created, selected_level.Name
            )
        )
        if duplicates_removed_count:
            lines.append(
                "  - {} parede(s) duplicada(s)/sobreposta(s) na mesma posicao "
                "foram descartadas automaticamente antes da criacao (mantida "
                "apenas a mais longa de cada grupo)."
                .format(duplicates_removed_count)
            )
        if failures:
            lines.append("  - {} segmento(s) FALHARAM ao criar a parede no Revit.".format(len(failures)))

        # --- Paredes ignoradas + motivo ---
        lines.append("")
        lines.append("Paredes ignoradas: {} linha(s) do Layer '{}'.".format(ignored_lines_count, selected_layer))
        if duplicates_removed_count:
            lines.append(
                "  - {} por serem duplicata/sobreposicao de outra parede ja "
                "criada (ver acima)."
                .format(duplicates_removed_count)
            )
        if unused_lines:
            reason_lines = []
            for line in unused_lines[:15]:
                reason = classify_unused_line_reason(
                    line, lines_to_process, target_thicknesses_ft, detection_tolerance_ft
                )
                reason_lines.append("    * {}: {}".format(_fmt_line_cm(line), reason))
            lines.append(
                "  - {} sem par valido - motivo de cada uma (coordenadas em cm):"
                .format(len(unused_lines))
            )
            lines.extend(reason_lines)
            if len(unused_lines) > 15:
                lines.append("    * ... e mais {} linha(s) (mesmas categorias de motivo acima).".format(
                    len(unused_lines) - 15
                ))

        # --- Pequenos trechos / bonecas ---
        lines.append("")
        small_axes = [
            (centerline, thickness_ft)
            for centerline, thickness_ft, _locked in walls_to_create
            if centerline.GetEndPoint(0).DistanceTo(centerline.GetEndPoint(1)) < (0.5 * FEET_PER_METER)
        ]
        lines.append("Pequenos trechos/bonecas (< 0,5m) CRIADOS: {}.".format(len(small_axes)))
        if possible_missed_bonecas:
            # Maior sobreposicao primeiro: um par com sobreposicao de VARIOS
            # METROS (nao poucos cm) e' quase certamente uma parede INTEIRA
            # esquecida (nao uma "boneca") so' porque a espessura dela nao foi
            # escolhida pelo usuario - vale destacar isso separado, senao fica
            # escondido no meio de coincidencias curtas irrelevantes.
            ordered_missed = sorted(possible_missed_bonecas, key=lambda pair: -pair[1])
            samples = ", ".join(
                "{}cm de espessura / {}cm de sobreposicao".format(d, o)
                for d, o in ordered_missed[:6]
            )
            lines.append(
                "Pequenos trechos/bonecas possivelmente IGNORADOS: {} par(es) de "
                "linhas sem parede criada que ainda assim parecem geometricamente "
                "uma parede/boneca valida, so' que em espessura(s) fora das "
                "escolhidas (maiores sobreposicoes primeiro: {}{}) - confira se "
                "alguma delas deveria ter sido selecionada."
                .format(len(possible_missed_bonecas), samples, ", ..." if len(possible_missed_bonecas) > 6 else "")
            )
            large_misses = [(d, o) for d, o in possible_missed_bonecas if o >= 100.0]
            if large_misses:
                thicknesses_involved = sorted(set(d for d, _o in large_misses))
                lines.append(
                    "  - ATENCAO: {} desses par(es) tem MAIS DE 1 METRO de "
                    "sobreposicao - nao sao bonecas, sao provavelmente PAREDES "
                    "INTEIRAS de espessura {}cm que ficaram de fora so' porque essa "
                    "espessura nao foi selecionada nesta execucao. Rode novamente "
                    "incluindo essa espessura se for o caso."
                    .format(
                        len(large_misses),
                        ", ".join("%g" % t for t in thicknesses_involved)
                    )
                )
        else:
            lines.append("Pequenos trechos/bonecas possivelmente ignorados: nenhum encontrado.")

        # --- Paredes geradas a partir de aberturas selecionadas ---
        lines.append("")
        lines.append("Portas/janelas - origem: {}.".format(openings_source_note))
        if wall_error_rows:
            auto_fixable_count = sum(1 for r in wall_error_rows if r["auto_fixable"])
            lines.append(
                "Analise pos-criacao (ETAPA 3B): {} eixo(s) fora da modulacao, {} "
                "com correcao automatica disponivel (ver botao 'Ajustar Erros' na "
                "janela de resultado), {} exigindo revisao manual."
                .format(len(wall_error_rows), auto_fixable_count,
                        len(wall_error_rows) - auto_fixable_count)
            )
        else:
            lines.append("Analise pos-criacao (ETAPA 3B): nenhum eixo fora da modulacao.")
        lines.append("Aberturas consideradas: {}.".format(len(all_openings)))
        lines.append("Aberturas associadas a alguma parede criada: {}.".format(openings_used))
        lines.append(
            "Trechos de parede gerados EXCLUSIVAMENTE a partir de aberturas "
            "selecionadas no Revit (verga/peitoril): {} segmento(s), em {} "
            "parede(s) diferentes.".format(opening_segments_created, len(walls_with_opening_segments))
        )
        if all_openings and not openings_used:
            lines.append(
                "  - Aberturas foram detectadas mas NENHUMA ficou perto o bastante "
                "do eixo de nenhuma parede criada - verifique se a familia esta "
                "posicionada sobre a linha do CAD, dentro de ~{}cm de tolerancia "
                "alem da meia-espessura da parede."
                .format(round(OPENING_ASSOC_TOLERANCE_M * 100.0, 1))
            )
        unassigned_openings = opening_diagnostics.get("unassigned_openings", [])
        if unassigned_openings:
            lines.append(
                "  - {} abertura(s) selecionada(s) NAO foram associadas a nenhuma "
                "parede criada (por isso nao tiveram nenhum recorte/verga gerado) "
                "- motivo de cada uma (posicao do centro em cm):"
                .format(len(unassigned_openings))
            )
            for op in unassigned_openings[:15]:
                c = op["center_xy"]
                reason = classify_unassociated_opening_reason(op, walls_to_create)
                lines.append(
                    "    * ({:.0f}, {:.0f}), largura {}cm: {}".format(
                        round(c.X / FEET_PER_METER * 100.0), round(c.Y / FEET_PER_METER * 100.0),
                        round(op["width_ft"] / FEET_PER_METER * 100.0, 1), reason
                    )
                )
            if len(unassigned_openings) > 15:
                lines.append(
                    "    * ... e mais {} abertura(s) (mesmas categorias de motivo acima)."
                    .format(len(unassigned_openings) - 15)
                )
        # Quantas aberturas tiveram o centro do vao corrigido pela GEOMETRIA da
        # familia (em vez do ponto de insercao) - ver _opening_center_from_geometry.
        # E' a informacao mais importante para conferir alinhamento de verga:
        # quando esse numero e' alto e as correcoes sao grandes, e' sinal de que
        # as familias tem a origem fora do centro do vao (normal nestas
        # familias), e o script esta compensando isso.
        geometry_centered = [
            op for op in all_openings if op.get("center_source") == "geometria"
        ]
        if geometry_centered:
            shifts_cm = [
                op["center_xy"].DistanceTo(op["insertion_xy"]) / FEET_PER_METER * 100.0
                for op in geometry_centered if op.get("insertion_xy") is not None
            ]
            lines.append(
                "  - Centro do vao lido da GEOMETRIA da familia (retangulo do vao) "
                "em {} de {} abertura(s) - a largura medida na geometria confere "
                "com Largura_abertura. Correcao aplicada em relacao ao ponto de "
                "insercao: {}cm no maximo, {}cm em media.".format(
                    len(geometry_centered), len(all_openings),
                    round(max(shifts_cm), 2) if shifts_cm else 0,
                    round(sum(shifts_cm) / len(shifts_cm), 2) if shifts_cm else 0
                )
            )
        fallback_centered = len(all_openings) - len(geometry_centered)
        if fallback_centered:
            lines.append(
                "  - {} abertura(s) usaram o PONTO DE INSERCAO como centro do vao "
                "(a geometria da familia nao bateu com Largura_abertura - "
                "provavelmente a familia desenha folha/soleira/moldura alem do "
                "vao). Se a verga dessas ficar deslocada, confira a origem dessa "
                "familia.".format(fallback_centered)
            )
        if opening_diagnostics["opening_off_center_count"]:
            lines.append(
                "  - Nota (nao necessariamente um problema): em {} abertura(s), o "
                "ponto de insercao da familia difere do centro da BOUNDING BOX 3D "
                "dela em ate' {}cm ao longo da parede - normal quando a geometria "
                "da familia e' assimetrica (folha aberta, soleira, marco), e NAO "
                "afeta o calculo: o centro do vao vem da GEOMETRIA da familia "
                "(retangulo do vao), com o ponto de insercao so' como reserva - "
                "ver a linha 'Centro do vao lido da GEOMETRIA' acima."
                .format(
                    opening_diagnostics["opening_off_center_count"],
                    round(opening_diagnostics["opening_center_gap_max_ft"] / FEET_PER_METER * 100.0, 1)
                )
            )
        if openings_capped_at_top:
            lines.append(
                "  - ATENCAO: {} abertura(s) NAO tiveram parede criada acima da "
                "verga (sem espaco sobrando ate o pe-direito de {}m). Altura lida "
                "do piso ate a verga (Peitoril + {}) nessas aberturas, em cm: {}. "
                "Se esse valor deveria ser MENOR que o pe-direito, o parametro "
                "'{}' (ou '{}') dessa(s) familia(s)/instancia(s) esta gravado com "
                "um valor maior do que deveria no Revit."
                .format(
                    openings_capped_at_top, round(wall_height_value, 2), OPENING_HEIGHT_PARAM,
                    ", ".join(str(v) for v in capped_head_cm_samples),
                    OPENING_HEIGHT_PARAM, OPENING_SILL_PARAM
                )
            )

        # --- Segmentos com geometria ambigua / a conferir ---
        lines.append("")
        ambiguous_lines = []
        if out_of_bounds_count:
            ambiguous_lines.append(
                "- {} parede(s) criada(s) com pelo menos uma extremidade fora dos "
                "limites da planta (bounding box das linhas do Layer, margem de "
                "{}cm) - revise possiveis pareamentos incorretos."
                .format(out_of_bounds_count, round(PLAN_BOUNDS_MARGIN_M * 100.0, 1))
            )
        if diagnostics["cap_clipped_count"]:
            ambiguous_lines.append(
                "- {} parede(s) tiveram inicio e/ou fim definidos pela LINHA DE "
                "FECHAMENTO (testa) do proprio Layer, em vez do prolongamento das "
                "duas faces - essas pontas nao foram esticadas para fechar "
                "encontros em T/L."
                .format(diagnostics["cap_clipped_count"])
            )
        if placement_deviation_count:
            ambiguous_lines.append(
                "- {} parede(s) MEDIDAS DENTRO DO MODELO ficaram fora da posicao "
                "pretendida em planta (maior desvio: {}cm) - o Revit pode nao ter "
                "aceitado o realinhamento pelo nucleo nessa(s) parede(s)."
                .format(placement_deviation_count, round(placement_deviation_max_ft / FEET_PER_METER * 100.0, 3))
            )
        if diagnostics["offset_suspect_count"]:
            ambiguous_lines.append(
                "- {} eixo(s) de parede calculados NAO ficaram perfeitamente "
                "centralizados entre as duas linhas do CAD (maior desvio: {}cm) - "
                "possivel deslocamento lateral residual; revise o pareamento "
                "correspondente."
                .format(
                    diagnostics["offset_suspect_count"],
                    round(diagnostics["offset_suspect_max_ft"] / FEET_PER_METER * 100.0, 3)
                )
            )
        if opening_diagnostics["clamped_opening_count"]:
            ambiguous_lines.append(
                "- {} abertura(s) tiveram o vao recortado mais ESTREITO que a "
                "propria Largura_abertura, por estarem perto demais da ponta da "
                "parede reconstruida - a parede acima/ao redor dessa(s) "
                "abertura(s) pode nao cobrir a largura toda do vao."
                .format(opening_diagnostics["clamped_opening_count"])
            )
        if residual_duplicates_count:
            ambiguous_lines.append(
                "- {} parede(s) ficaram duplicadas/sobrepostas mesmo depois da "
                "remocao automatica (apos fechar os encontros em T/L) - revise "
                "manualmente."
                .format(residual_duplicates_count)
            )
        if broken_length_walls:
            ambiguous_lines.append(
                "- {} parede(s) marcadas em VERMELHO na vista: comprimento QUEBRADO "
                "(nao cai dentro de {}cm de nenhum numero inteiro de cm - residuo/"
                "imprecisao geometrica, ex.: 25,01cm em vez de 25,00cm). Corrija "
                "antes de tentar modular - blocos so' existem em cm inteiro."
                .format(len(broken_length_walls), round(MODULATION_WHOLE_CM_TOLERANCE_CM, 2))
            )
        # Total de ITENS afetados (nao numero de categorias/mensagens acima) -
        # soma cada contagem individual, ja que uma mesma parede pode aparecer em
        # mais de uma categoria (ex.: deslocada E duplicada) e por isso este
        # total pode ultrapassar o numero de paredes distintas envolvidas.
        ambiguous_total = (
            out_of_bounds_count + diagnostics["cap_clipped_count"] + placement_deviation_count +
            diagnostics["offset_suspect_count"] + opening_diagnostics["clamped_opening_count"] +
            residual_duplicates_count + len(broken_length_walls)
        )
        lines.append(
            "Segmentos com geometria ambigua (a conferir manualmente): {} item(ns) em {} "
            "categoria(s) abaixo.".format(ambiguous_total, len(ambiguous_lines))
        )
        lines.extend(ambiguous_lines)
        if not ambiguous_lines:
            lines.append(
                "Nenhum caso ambiguo detectado - todas as paredes criadas foram "
                "conferidas uma a uma (posicao real lida de volta do modelo) "
                "dentro de {}cm de tolerancia.".format(round(AXIS_OFFSET_WARNING_M * 100.0, 1))
            )

        # --- Validacao de modulacao de blocos estruturais (preparacao para o
        # futuro script de paginacao de blocos - ver evaluate_wall_modulation/
        # evaluate_opening_modulation) ---
        lines.append("")
        lines.append("Validacao de modulacao de blocos estruturais:")
        lines.append("")
        pier_count = sum(1 for r in modulation_results if r.get("pier_at_opening"))
        lines.append(
            "Paredes: {} parede(s) analisada(s) - {} compativel(is), {} "
            "incompativel(is) (nenhuma combinacao de juntas de contorno fecha "
            "esse comprimento com os blocos do catalogo, ou ele nao e' um "
            "numero inteiro de cm).".format(
                len(modulation_results), compatible_modulation_count, len(incompatible_modulation)
            )
        )
        lines.append(
            "  - NAO ha' mais nenhuma regra de digito final aqui (a antiga "
            "'terminar em 0/5', ou em 0/1/6/9, foi removida): o criterio e' a "
            "aritmetica real dos blocos + juntas, entao 111cm e 129cm passam. "
            "Esta e' so' uma pre-checagem permissiva para o realce ao vivo - "
            "quem decide de verdade se uma parede precisa de ajuste e' o solver "
            "de blocos rodando parede por parede, no passo 'Analisar Paredes'/"
            "'Ajustar Erros'. ({} dela(s) sao pilaretes encostados num vao.)"
            .format(pier_count)
        )
        if broken_length_walls:
            lines.append(
                "  - Marcadas em VERMELHO na vista: comprimento QUEBRADO (residuo/"
                "imprecisao, corrija ANTES de tentar modular - ver FASE 2 do "
                "plano):"
            )
            for r in broken_length_walls[:20]:
                lines.append(
                    "    * Parede {}\n"
                    "      Comprimento atual: {}cm\n"
                    "      Status: COMPRIMENTO QUEBRADO\n"
                    "      Comprimento sugerido: {}cm\n"
                    "      Correcao necessaria: {:+.2f}cm".format(
                        r["id"].ToString(), round(r["length_cm"], 2),
                        r["length_cm_rounded"],
                        r["length_cm_rounded"] - r["length_cm"]
                    )
                )
            if len(broken_length_walls) > 20:
                lines.append(
                    "    * ... e mais {} parede(s).".format(len(broken_length_walls) - 20)
                )
        if non_modular_walls:
            lines.append(
                "  - Marcadas em AZUL na vista para revisao manual (comprimento "
                "integro de cm, mas nenhuma combinacao de blocos+juntas fecha "
                "nele):"
            )
            for r in non_modular_walls[:20]:
                # `nearest_valid_cm` vem de nearest_wall_lengths_cm - o valor
                # que fecha em blocos mais proximo por baixo e por cima,
                # considerando todas as combinacoes de junta de contorno.
                lower, upper = r["nearest_valid_cm"]
                other = upper if r["suggested_cm"] == lower else lower
                other_note = " | outra opcao proxima: {}cm".format(other) if other != r["suggested_cm"] else ""
                lines.append(
                    "    * Parede ID {} | comprimento atual: {}cm | SUGESTAO: {}cm{}".format(
                        r["id"].ToString(), round(r["length_cm"], 2),
                        r["suggested_cm"], other_note
                    )
                )
            if len(non_modular_walls) > 20:
                lines.append(
                    "    * ... e mais {} parede(s).".format(len(non_modular_walls) - 20)
                )
        if not broken_length_walls and not non_modular_walls:
            lines.append("  - Todas as paredes criadas ja atendem a regra de modulacao.")

        lines.append("")
        lines.append(
            "Aberturas (portas/janelas): {} abertura(s) analisada(s) - {} "
            "compativel(is), {} incompativel(is) (largura de Largura_abertura "
            "nao termina em 1, 6 ou 9cm, ou nao e' um numero inteiro de "
            "cm).".format(
                len(opening_modulation_results), opening_compatible_modulation_count,
                len(opening_incompatible_modulation)
            )
        )
        if opening_incompatible_modulation:
            lines.append("  - Marcadas em AZUL na vista para revisao manual:")
            for r in opening_incompatible_modulation[:20]:
                lower, upper = r["nearest_valid_cm"]
                whole_note = "" if r["is_whole_cm"] else " (nao e' inteiro de cm)"
                other = upper if r["suggested_cm"] == lower else lower
                other_note = " | outra opcao proxima: {}cm".format(other) if other != r["suggested_cm"] else ""
                lines.append(
                    "    * Abertura ID {} | largura atual: {}cm{} | SUGESTAO: {}cm{}".format(
                        r["element_id"], round(r["width_cm"], 2), whole_note,
                        r["suggested_cm"], other_note
                    )
                )
            if len(opening_incompatible_modulation) > 20:
                lines.append(
                    "    * ... e mais {} abertura(s).".format(len(opening_incompatible_modulation) - 20)
                )
        else:
            lines.append("  - Todas as aberturas consideradas ja atendem a regra de modulacao.")

        lines.append(
            "  - Validador AO VIVO armado: estas {} parede(s) e {} abertura(s) "
            "continuam sendo monitoradas pelo resto desta sessao do Revit - o "
            "azul aparece/some automaticamente conforme voce corrige (ou "
            "quebra) o comprimento/largura, e o vermelho (testa suspeita) some "
            "automaticamente quando a parede passa a ter as duas pontas "
            "explicadas por outra parede/abertura vizinha - tudo sem precisar "
            "rodar o botao de novo."
            .format(len(created_wall_ids_all), len(all_openings))
        )

        # --- Correcao pos-criacao de modulacao (ETAPA 3B) - so' diagnostico
        # aqui; a aplicacao de verdade (parede + abertura juntas) acontece
        # quando o usuario clica "Ajustar Erros" na janela de resultado. ---
        lines.append("")
        if wall_error_rows:
            auto_fixable_count = sum(1 for r in wall_error_rows if r["auto_fixable"])
            lines.append(
                "Correcao pos-criacao (ETAPA 3B): {} eixo(s) fora da modulacao, "
                "{} com correcao automatica disponivel (deslocamento minimo da "
                "abertura, ate {}cm - largura/altura nunca mudam), {} exigem "
                "revisao manual.".format(
                    len(wall_error_rows), auto_fixable_count,
                    int(AXIS_OPENING_SHIFT_MAX_CM), len(wall_error_rows) - auto_fixable_count
                )
            )
        else:
            lines.append("Correcao pos-criacao (ETAPA 3B): nenhum eixo fora da modulacao.")

        # --- Rastreio detalhado por abertura (Largura_abertura -> centro ->
        # eixo -> pontos calculados -> pontos enviados/devolvidos pelo Revit) ---
        lines.extend(build_opening_trace_log(
            opening_diagnostics.get("assignments", []),
            walls_to_create,
            created_opening_segments
        ))

        summary = "\n".join(lines)

        # Log salvo em arquivo (registro permanente - ver _save_log_to_file). A
        # COPIA para a area de transferencia deixou de ser automatica: fazer
        # isso sem pedir apagava o que o usuario tivesse copiado antes de rodar
        # o botao. Agora e' o botao "Copiar log" da janela de resultado.
        log_file_path = _save_log_to_file(summary)

        # Relatorio ESTRUTURADO da janela de resultado (ver _PostCreationForm).
        # Os mesmos numeros e avisos que ja' existiam no log de texto, agora
        # tambem em forma de dados - o log completo continua identico, so' que
        # agora no rodape da janela unica em vez de numa aba separada.
        report = {
            "title": "Automacao concluida - {} parede(s) criada(s)".format(created_count),
            "subtitle": (
                "Layer '{}' | Nivel '{}' | altura {:.2f}m | esta janela nao bloqueia o Revit."
                .format(selected_layer, selected_level.Name, wall_height_value)
            ),
            "kpis": [
                ("Paredes criadas", created_count, UI_ACCENT),
                ("Eixos detectados", detected_count, UI_TEXT),
                ("Aberturas usadas", openings_used, UI_TEXT),
                ("Fora da modulacao",
                 len(incompatible_modulation) + len(opening_incompatible_modulation),
                 UI_WARN if (incompatible_modulation or opening_incompatible_modulation) else UI_OK),
                ("A conferir", ambiguous_total, UI_WARN if ambiguous_total else UI_OK),
            ],
            "highlights": build_report_highlights(
                selected_layer, detected_count, axes_created_count, created_count,
                cad_segments_created, opening_segments_created, selected_level.Name,
                all_openings, openings_used, openings_source_note,
                modulation_results, incompatible_modulation,
                opening_modulation_results, opening_incompatible_modulation,
                wall_error_rows, failures
            ),
            "issues": build_report_issues(
                failures, ambiguous_lines, modulation_results,
                opening_incompatible_modulation, unassigned_openings,
                possible_missed_bonecas, recovery_mode_used, openings_capped_at_top
            ),
            "log": summary,
            "log_path": log_file_path,
            "wall_analysis_skipped": skipped_wall_analysis,
        }
        if skipped_wall_analysis:
            report["subtitle"] = (
                "ATENCAO: Modulacao das paredes foi PULADA (eixos fora da "
                "modulacao NAO foram analisados/corrigidos) - " + report["subtitle"]
            )

        # ==========================================
        # 7. JANELA UNICA DE MODULACAO (analisar -> ajustar erros -> lancar
        # blocos -> finalizar/deletar paredes, ver cabecalho da secao "JANELA
        # UNICA DE MODULACAO..." mais acima)
        # ==========================================
        # So' faz sentido abrir se pelo menos uma parede foi de fato criada
        # nesta execucao - sem isso nao ha nada para analisar, modular em
        # blocos nem excluir. Sem nenhuma parede criada, cai no forms.alert
        # (modal, pyRevit) so' com o resumo em texto - paridade com o
        # comportamento anterior, que sempre mostrava alguma coisa.
        if created_wall_ids_all:
            # Qualquer falha ao montar a janela WinForms de resultado (mesma
            # familia de erro documentada em ask_setup/_show_wall_review_
            # window - ambiente com algum controle .NET indisponivel) NAO
            # pode derrubar o script neste ponto: a modulacao de blocos ja'
            # rodou (leitura E, dependendo do fluxo, escrita no documento) e
            # o usuario precisa ver o resultado de algum jeito - cai para o
            # resumo em texto (forms.alert), paridade com o caminho "nenhuma
            # parede criada" logo abaixo.
            try:
                _show_post_creation_window(
                    report, walls_to_create, openings_per_wall, created_walls_by_axis,
                    created_wall_ids_all, all_openings, wall_graph_nodes, wall_end_to_node,
                    selected_level, base_z_abs, wall_height_ft, wall_error_rows,
                    catalog, catalog_missing, wall_segment_geometry=wall_segment_geometry,
                    precreated_event=stage2_external_event, precreated_handler=stage2_handler
                )
            except Exception as ex:
                # NUNCA mostrar `summary` (o resumo da Etapa 1, "tudo certo")
                # como se fosse o resultado final - as Walls foram criadas,
                # mas a Tela 2 falhou e NENHUM bloco foi calculado/criado
                # (mesmo bug real reportado pelo usuario no fluxo "paredes
                # existentes", 2026-08-27 - ver run_modulation_on_existing_
                # walls). O alerta agora deixa isso explicito e mostra o
                # erro de verdade.
                detail = _format_exception_detail(ex)
                last_line = traceback.format_exc().splitlines()[-1]
                output.print_md(
                    "- **Tela 2 (Modulacao dos Blocos) FALHOU AO ABRIR** ({0}); "
                    "as paredes foram criadas mas NENHUM bloco foi calculado/criado."
                    "\n\n```\n{1}\n```".format(last_line, detail)
                )
                forms.alert(
                    "As paredes foram criadas, mas a Tela 2 (Modulacao dos Blocos) "
                    "FALHOU AO ABRIR - NENHUM bloco foi calculado ou criado no Revit.\n\n"
                    "Erro: {0}\n\n"
                    "Copie o texto completo do erro no painel de saida do pyRevit (mais "
                    "detalhado) e tente novamente - se persistir, reporte esse texto "
                    "exato para diagnostico.".format(last_line),
                    title="Modulacao Automatica - Tela 2 falhou (nenhum bloco criado)"
                )
        else:
            forms.alert(summary, title="Modulacao Automatica - Resultado")
    stage1_kpis = [
        ("Paredes criadas", created_count, UI_ACCENT),
        ("Eixos detectados", detected_count, UI_TEXT),
        ("Ignoradas", len(unused_lines) + duplicates_removed_count, UI_TEXT),
        ("Falhas na criacao", len(failures), UI_WARN if failures else UI_OK),
    ]
    stage1_log_lines = [
        "=== ETAPA 1 CONCLUIDA - Layer '{}' ===".format(selected_layer),
        "",
        "Paredes criadas: {} elemento(s) Wall no Nivel '{}'.".format(created_count, selected_level.Name),
        "Eixos detectados no AutoCAD: {}.".format(detected_count),
        "Linhas ignoradas: {}.".format(len(unused_lines) + duplicates_removed_count),
    ]
    if failures:
        stage1_log_lines.append("")
        stage1_log_lines.append("ATENCAO - {} segmento(s) falharam ao criar:".format(len(failures)))
        for _f in failures[:20]:
            stage1_log_lines.append("  - {}".format(_f))
    stage1_log_lines.append("")
    stage1_log_lines.append(
        "Nenhuma analise de modulacao rodou ainda - confira as Walls no "
        "Revit (bonecas, aberturas, encontros T/L/X, limites da planta) e "
        "clique em 'Iniciar Modulacao' quando estiver pronto."
    )
    stage1_report = {
        "title": "Etapa 1 concluida - {} parede(s) criada(s)".format(created_count),
        "subtitle": (
            "Layer '{}' | Nivel '{}' | altura {:.2f}m | reveja as Walls no Revit antes de modular."
            .format(selected_layer, selected_level.Name, wall_height_value)
        ),
        "kpis": stage1_kpis,
        "log": "\n".join(stage1_log_lines),
    }

    try:
        _show_wall_review_window(
            stage1_report,
            {
                "walls_to_create": walls_to_create,
                "openings_per_wall": openings_per_wall,
                "created_walls_by_axis": created_walls_by_axis,
                "wall_segment_geometry": wall_segment_geometry,
                "all_openings": all_openings,
                "wall_graph_nodes": wall_graph_nodes,
                "wall_end_to_node": wall_end_to_node,
                "catalog": catalog,
                "catalog_missing": catalog_missing,
                "modulation_results": modulation_results,
                "opening_incompatible_modulation": opening_incompatible_modulation,
                "progress_cb": _solver_progress_cb,
            },
            _run_stage2_modulation,
        )
    except Exception as ex:
        # Mesma familia de falha documentada em ask_setup (WinForms/pythonnet
        # indisponivel neste ambiente) - so' que aqui as Walls JA' FORAM
        # CRIADAS E COMMITADAS no Revit (ver PARADA OBRIGATORIA acima); um
        # crash nao tratado neste ponto derrubava o script inteiro (traceback
        # cru no output do pyRevit) sem nenhuma forma de o usuario prosseguir
        # para a Etapa 2, mesmo com as paredes ja' presentes no modelo. Cai
        # para o fluxo antigo/sincrono (sem janela modeless, sem
        # ExternalEvent - dispensavel aqui: main() ja' esta' rodando dentro
        # do contexto valido da API do Revit, exatamente como
        # analyze_created_walls_for_errors era chamada direto daqui antes da
        # separacao Etapa 1/Etapa 2, ver comentario na PARADA OBRIGATORIA).
        #
        # DIAGNOSTICO COMPLETO (2026-08-26): ate' aqui so' a ULTIMA linha do
        # traceback ia pro log - para uma excecao .NET envolvida pelo
        # pythonnet isso e' so' o fim de um stack trace do CLR (ex.:
        # "at System.Reflection.MethodBaseInvoker.InvokeWithOneArg(...)"),
        # generico demais para apontar QUAL linha do NOSSO codigo (dentro de
        # _show_wall_review_window/_WallReviewForm) realmente falhou -
        # ver _format_exception_detail. Log em arquivo (nao so' no output do
        # pyRevit, que pode ja' ter sido fechado/reciclado) para sobreviver
        # ao fallback e dar um ponto de partida real na proxima ocorrencia.
        detail = _format_exception_detail(ex)
        try:
            crash_log_path = os.path.join(tempfile.gettempdir(), "modulacao_automatica_wall_review_crash.log")
            with open(crash_log_path, "a") as _fh:
                _fh.write("=== {} ===\n{}\n\n".format(time.strftime("%Y-%m-%d %H:%M:%S"), detail))
        except Exception:
            crash_log_path = None
        output.print_md(
            "- **Tela WinForms de revisao das Walls tambem falhou** ({0}); "
            "as {1} Wall(s) desta execucao ja' foram criadas no Revit (nao "
            "serao desfeitas). Usando o fluxo antigo: pergunta simples em "
            "vez da janela de revisao.\n\n```\n{2}\n```{3}".format(
                traceback.format_exc().splitlines()[-1], created_count, detail,
                "\n\nDetalhe tambem salvo em: {}".format(crash_log_path) if crash_log_path else ""
            )
        )
        quer_modular = forms.alert(
            "{0}\n\nA tela de revisao das Walls falhou nesta execucao, mas "
            "as paredes acima ja' foram criadas no Revit.\n\n"
            "Iniciar a modulacao de blocos agora?".format(stage1_report["log"]),
            title="Modulacao Automatica - Etapa 1 concluida", yes=True, no=True
        )
        if not quer_modular:
            return
        try:
            wall_error_rows = analyze_created_walls_for_errors(
                doc, walls_to_create, openings_per_wall, created_walls_by_axis,
                all_openings, wall_graph_nodes, wall_end_to_node,
                catalog, catalog_missing, modulation_results,
                opening_incompatible_modulation, progress_cb=_solver_progress_cb,
                wall_start_cb=_solver_wall_start_cb, wall_result_cb=_solver_wall_result_cb,
                wall_segment_geometry=wall_segment_geometry,
            )
        except Exception as analyze_ex:
            forms.alert(
                "Falha ao analisar as paredes: {}".format(analyze_ex),
                title="Modulacao Automatica - Erro"
            )
            return
        _run_stage2_modulation(wall_error_rows)


def run():
    """Ponto de entrada real do script - primeiro pergunta COMO as
    paredes devem ser preparadas (Etapa 1 do fluxo pedido pelo usuario,
    2026-08-26: "Selecionar a planta/gerar as paredes" OU "Pular criacao/
    verificacao inicial das paredes - usar as que ja existem"), so' depois
    despacha para o fluxo escolhido. Ver _ask_wall_source_mode/
    run_modulation_on_existing_walls (fluxo novo) e main() (fluxo classico,
    inalterado)."""
    mode = _ask_wall_source_mode()
    if mode == "existing":
        run_modulation_on_existing_walls()
    elif mode == "cad":
        main()
    # None (ESC/fechou sem escolher) - nao faz nada, mesma convencao do
    # resto do script (cad_ref/setup cancelados tambem so' fazem `return`).


if __name__ == "__main__":
    run()
