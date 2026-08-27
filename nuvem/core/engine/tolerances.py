# -*- coding: utf-8 -*-
"""Constantes de tolerancia geometrica usadas por `core/engine/geometry.py`
(e por `core/wall_modeling.py`, que as importa daqui - ver o import logo
apos a definicao de FEET_PER_METER la'). Extraidas verbatim de
`wall_modeling.py`, comentarios originais inclusive: nenhum VALOR mudou,
so' o arquivo onde moram.

Modulo PURO: sem import de Revit, sem import de UI.
"""

FEET_PER_METER = 1.0 / 0.3048

# Tolerancia (metros) para considerar dois fragmentos de linha como parte da
# MESMA reta infinita (mesma direcao e mesmo deslocamento perpendicular),
# usada para RECONSTRUIR uma face de parede que o CAD desenhou quebrada em
# varios trechos (ver merge_collinear_fragments).
#
# DELIBERADAMENTE MUITO APERTADA (2mm): cobre apenas ruido de arredondamento
# de ponto flutuante e de import do CAD - NUNCA uma diferenca de desenho
# real. Um valor generoso aqui (2cm, usado ate' esta correcao) e' o que
# causava o deslocamento lateral de ~0,5cm relatado nas bonecas: plantas
# reais frequentemente tem as faces de parede desenhadas com pequenos
# desalinhamentos entre um trecho e outro (meio cm, por exemplo). Com
# tolerancia de 2cm, um trecho CURTO desenhado 0,5cm fora da parede longa
# entrava no mesmo grupo de colinearidade e era REPROJETADO sobre a reta do
# fragmento mais longo (ver _merge_collinear_cluster) - ou seja, o trecho
# curto era fisicamente REALOCADO 0,5cm em relacao a onde ele esta' na
# planta. Como os trechos curtos sao justamente as bonecas ao lado de
# portas/janelas, o erro se concentrava exatamente ali.
#
# Com 2mm, fragmentos genuinamente desalinhados no CAD NAO sao agrupados:
# cada um permanece na sua propria posicao e gera parede exatamente sobre
# as linhas que o representam na planta - que e' o comportamento pedido
# ("todas as paredes exatamente na posicao indicada pelas linhas da
# planta"), mesmo quando a propria planta esta' desalinhada.
COLLINEAR_MATCH_TOLERANCE_M = 0.002
COLLINEAR_MATCH_TOLERANCE_FT = COLLINEAR_MATCH_TOLERANCE_M * FEET_PER_METER

# Fracao MINIMA (0.0 a 1.0) do comprimento da MENOR das duas linhas que
# precisa estar coberta pela outra, medida ao longo da direcao da linha,
# para aceitar duas linhas paralelas como as duas faces da MESMA parede
# (ver lines_overlap_enough). E' apenas um criterio de validacao do
# pareamento (evita casar linhas paralelas e proximas mas sem nenhuma
# relacao real) - NAO recorta nem divide nada: a parede resultante sempre
# usa as linhas INTEIRAS, mesmo que isso a faca se sobrepor a outras
# paredes em encontros T/L/Cruz.
#
# Substituiu um piso ABSOLUTO fixo em cm (ex.: exigir >=10cm de
# sobreposicao) porque nenhum valor fixo serve para os dois casos que esse
# criterio precisa distinguir ao mesmo tempo:
#   - Falso pareamento: duas linhas de PAREDES DIFERENTES que so' se
#     cruzam/tangenciam de raspao perto de um canto e por coincidencia tem
#     a mesma espessura escolhida - a sobreposicao entre elas costuma ser
#     de poucos cm, mas medida contra linhas de VARIOS METROS de
#     comprimento (a fracao coberta e' minuscula, bem menor que 1%).
#   - Boneca curta legitima: um trecho valido de parede entre uma
#     abertura e um encontro proximo, que pode ter so' uns 10~15cm (ou
#     menos) de extensao - mas, sendo uma parede de verdade, as DUAS faces
#     desse trecho cobrem quase 100% uma da outra (a mesma extensao curta,
#     dos dois lados).
# Ou seja, a FRACAO de sobreposicao (nao o valor absoluto) e' o que
# realmente diferencia um par legitimo de um falso positivo, e funciona
# igual para qualquer comprimento/orientacao de parede - inclusive as
# bonecas mais curtas, que antes eram descartadas so' por serem menores
# que o piso fixo em cm.
MIN_WALL_SEGMENT_OVERLAP_RATIO = 0.6

# Piso ABSOLUTO (metros) de sobreposicao, usado so' para descartar
# sobreposicoes numericamente degeneradas (ruido de ponto flutuante,
# linhas de comprimento ~0) - NAO e' mais o criterio principal de validacao
# do pareamento (ver MIN_WALL_SEGMENT_OVERLAP_RATIO acima). Tambem usado
# como comprimento minimo de linha aceito no modo manual "uma parede por
# linha" (ver main()), para nao criar paredes degeneradas a partir de
# fragmentos praticamente pontuais.
MIN_WALL_SEGMENT_ABS_FLOOR_M = 0.02
MIN_WALL_SEGMENT_ABS_FLOOR_FT = MIN_WALL_SEGMENT_ABS_FLOOR_M * FEET_PER_METER

# Tolerancia (metros) MAIS GENEROSA que COLLINEAR_MATCH_TOLERANCE_M, usada
# EXCLUSIVAMENTE para religar dois GRUPOS (clusters) de fragmentos
# colineares ja formados que uma ABERTURA REAL do projeto (porta/janela)
# comprovadamente separa (ver _opening_bridges_gap/_clusters_bridge_via_opening)
# - nunca para o agrupamento "cru" inicial de fragmentos em
# merge_collinear_fragments, que continua exigindo a tolerancia apertada de
# 2mm (COLLINEAR_MATCH_TOLERANCE_M), para nao reintroduzir o deslocamento
# lateral de ~0,5cm ja corrigido em juncoes SEM nenhuma abertura envolvida.
#
# Motivo de precisar ser mais generosa aqui: o CAD real frequentemente
# desenha a face da parede com um pequeno desalinhamento (poucos mm a poucos
# cm) exatamente onde ela e' interrompida por um vao de porta/janela (jambas
# desenhadas a mao, ou geradas por um bloco/simbolo de porta que nao fica
# perfeitamente sobre a reta da parede). Com a tolerancia apertada de 2mm,
# os dois fragmentos NUNCA chegavam sequer a ser TESTADOS como candidatos a
# religar - cada um ficava isolado no seu proprio cluster de colinearidade
# desde a primeira passada, e o religamento pela abertura
# (_opening_bridges_gap) nunca era avaliado entre eles. Resultado: nenhum
# eixo de parede passava pelo vao, entao NEM a "boneca" ao lado nem a parede
# acima da verga tinham onde nascer - mesmo com toda a logica de recorte por
# altura/largura correta (o sintoma relatado: parede inteira faltando
# exatamente na largura da porta/janela, e bonecas entre duas aberturas
# proximas nunca modeladas).
OPENING_BRIDGE_TOLERANCE_M = 0.03
OPENING_BRIDGE_TOLERANCE_FT = OPENING_BRIDGE_TOLERANCE_M * FEET_PER_METER

# ==========================================
# Constantes abaixo extraidas verbatim de core/wall_modeling.py para a
# extracao do bloco de pareamento/juncoes (ver core/engine/wall_pairing.py) -
# nenhum VALOR mudou, so' o arquivo onde moram. wall_modeling.py continua
# com as suas proprias definicoes inline (nao removidas, para zero risco na
# extracao) - os dois lugares tem sempre o mesmo valor.
# ==========================================

# Tolerancia de espessura de parede aceita (metros)
MIN_WALL_THICKNESS_M = 0.05
MAX_WALL_THICKNESS_M = 0.35
MIN_WALL_THICKNESS_FT = MIN_WALL_THICKNESS_M * FEET_PER_METER
MAX_WALL_THICKNESS_FT = MAX_WALL_THICKNESS_M * FEET_PER_METER

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

# Distancia perpendicular extra (metros), alem da meia-espessura da parede,
# tolerada para associar uma abertura a uma linha de parede sendo criada.
OPENING_ASSOC_TOLERANCE_M = 0.05
OPENING_ASSOC_TOLERANCE_FT = OPENING_ASSOC_TOLERANCE_M * FEET_PER_METER

# Comprimento/altura minimos (metros) para um segmento de parede (cheio ou de
# preenchimento acima/abaixo de uma abertura) ser considerado valido - abaixo
# disso o segmento e' descartado por ser geometricamente degenerado (e o
# Revit rejeitaria a criacao).
MIN_SEGMENT_LENGTH_M = 0.01
MIN_SEGMENT_LENGTH_FT = MIN_SEGMENT_LENGTH_M * FEET_PER_METER
MIN_SEGMENT_HEIGHT_M = 0.01
MIN_SEGMENT_HEIGHT_FT = MIN_SEGMENT_HEIGHT_M * FEET_PER_METER

# Quanto (metros) a largura horizontal calculada para o vao de uma abertura
# sobre uma parede (t_hi - t_lo) pode ficar MENOR que `Largura_abertura`
# antes de ser reportada como abertura "cortada" pelo limite da propria
# parede (ver assign_openings_to_walls em core/engine/wall_pairing.py) -
# sinal de que a abertura esta' posicionada perto demais da ponta da
# parede reconstruida a partir do CAD.
OPENING_WIDTH_CLAMP_WARNING_M = 0.02
OPENING_WIDTH_CLAMP_WARNING_FT = OPENING_WIDTH_CLAMP_WARNING_M * FEET_PER_METER

# Desvio MAXIMO (metros), em qualquer uma das pontas do eixo calculado por
# create_centerline, entre a distancia ate' l1 e a distancia ate' l2 (que
# deveriam ser IGUAIS - e' a propria definicao de "eixo central") antes de
# ser reportado como parede com deslocamento suspeito. Bem mais apertado
# que os ~0,5cm relatados como sintoma - serve como alarme precoce para
# qualquer regressao futura no calculo do eixo, nao so' para o caso ja
# corrigido.
AXIS_OFFSET_WARNING_M = 0.001
AXIS_OFFSET_WARNING_FT = AXIS_OFFSET_WARNING_M * FEET_PER_METER

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
CAP_OPENING_SLACK_M = 0.20
CAP_OPENING_SLACK_FT = CAP_OPENING_SLACK_M * FEET_PER_METER
