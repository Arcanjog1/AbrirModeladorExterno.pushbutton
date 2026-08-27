# -*- coding: utf-8 -*-
"""Le um DXF (convertido de DWG pelo ODA File Converter, gratuito - ver
README.md) e devolve uma lista simples de segmentos de reta por layer, em
CENTIMETROS.

Nao faz nenhum pareamento/interpretacao de parede aqui - so' geometria
crua do arquivo. O pareamento (par de linhas paralelas -> eixo de parede)
fica em `wall_pairing.py`, que consome a saida desta funcao.

Suporta LINE e LWPOLYLINE/POLYLINE (explodidas em segmentos entre vertices
consecutivos). ARC/CIRCLE/SPLINE sao ignorados de proposito por enquanto -
paredes retas sao o caso comum; curvas ficam para uma iteracao futura se
algum projeto real precisar.

100% Python puro (biblioteca `ezdxf`, gratuita) - nao usa o ODA SDK (pago).
A conversao DWG->DXF deve ser feita ANTES, com o ODA File Converter
(tambem gratuito, ferramenta separada do SDK)."""

import ezdxf

_LINEAR_DXFTYPES = ("LINE", "LWPOLYLINE", "POLYLINE")


def _expand_entity(entity):
    """Gera entidades LINE/LWPOLYLINE/POLYLINE reais a partir de `entity`,
    explodindo INSERT (bloco/referencia) recursivamente - blocos podem
    conter outros blocos. Sem isso, paredes desenhadas DENTRO de um bloco
    (comum em DWGs organizados com simbolos/celulas) ficam invisiveis: o
    modelspace so' tem o INSERT, nao as linhas de verdade.

    Entidades definidas na layer "0" DENTRO do bloco herdam a layer do
    INSERT que o referenciou - a mesma convencao "ByBlock" que o AutoCAD
    usa para layer (blocos frequentemente sao desenhados com a geometria
    interna em "0" de proposito, para que apareçam na layer de quem os
    insere)."""
    if entity.dxftype() != "INSERT":
        yield entity
        return

    insert_layer = entity.dxf.layer
    for virtual_entity in entity.virtual_entities():
        if virtual_entity.dxf.layer == "0":
            virtual_entity.dxf.layer = insert_layer
        for expanded in _expand_entity(virtual_entity):
            yield expanded


def _iter_linear_entities(msp):
    """Itera o modelspace devolvendo so' LINE/LWPOLYLINE/POLYLINE - reais
    ou vindas de dentro de um INSERT (ver _expand_entity). ARC/CIRCLE/
    SPLINE/etc. dentro de blocos tambem sao ignorados aqui, mesmo motivo do
    resto do arquivo (paredes retas sao o caso comum)."""
    for entity in msp:
        for expanded in _expand_entity(entity):
            if expanded.dxftype() in _LINEAR_DXFTYPES:
                yield expanded

# $INSUNITS do cabecalho DXF -> fator de conversao para CENTIMETROS.
# Referencia: grupo de codigo 70 do header, valores documentados pela
# Autodesk (0=sem unidade, 1=polegadas, 2=pes, 4=mm, 5=cm, 6=m, ...).
_INSUNITS_TO_CM = {
    0: 1.0,      # sem unidade -> assume cm (mesma convencao do resto do motor)
    1: 2.54,     # polegadas
    2: 30.48,    # pes
    4: 0.1,      # milimetros
    5: 1.0,      # centimetros
    6: 100.0,    # metros
}


def detect_unit_scale_to_cm(doc):
    """Fator de multiplicacao para converter coordenadas do `doc` (ezdxf)
    para centimetros, a partir do $INSUNITS do cabecalho. Devolve 1.0
    (assume que o desenho ja esta' em cm) se a unidade nao for reconhecida
    - nunca lanca excecao por causa disso, so' um desenho sem unidade
    definida (comum em DXF exportado as pressas)."""
    insunits = doc.header.get("$INSUNITS", 0)
    return _INSUNITS_TO_CM.get(insunits, 1.0)


def read_dxf_segments(path, layers=None, unit_scale_to_cm=None):
    """Le `path` (arquivo .dxf) e devolve uma lista de dicts:
        {"layer": str, "start": (x_cm, y_cm), "end": (x_cm, y_cm)}

    `layers`: se informado (lista de nomes), so' entidades nessas layers
    sao lidas - comparacao case-insensitive. Se None, le' TODAS as layers
    (o chamador filtra depois, ex.: pela UI de configuracao).

    `unit_scale_to_cm`: se informado, sobrescreve a deteccao automatica via
    $INSUNITS (util quando o cabecalho do DXF nao tem a unidade certa)."""
    doc = ezdxf.readfile(path)
    scale = unit_scale_to_cm if unit_scale_to_cm is not None else detect_unit_scale_to_cm(doc)
    layers_lower = set(l.upper() for l in layers) if layers else None

    segments = []
    msp = doc.modelspace()
    for entity in _iter_linear_entities(msp):
        layer = entity.dxf.layer
        if layers_lower is not None and layer.upper() not in layers_lower:
            continue

        dxftype = entity.dxftype()
        if dxftype == "LINE":
            start = (entity.dxf.start.x * scale, entity.dxf.start.y * scale)
            end = (entity.dxf.end.x * scale, entity.dxf.end.y * scale)
            if start != end:
                segments.append({"layer": layer, "start": start, "end": end, "entity_type": dxftype})

        elif dxftype in ("LWPOLYLINE", "POLYLINE"):
            points = [(p[0] * scale, p[1] * scale) for p in entity.get_points("xy")] \
                if dxftype == "LWPOLYLINE" else \
                [(v.dxf.location.x * scale, v.dxf.location.y * scale) for v in entity.vertices]
            is_closed = bool(entity.closed) if dxftype == "LWPOLYLINE" else bool(entity.is_closed)
            n = len(points)
            pair_count = n if is_closed else n - 1
            for i in range(pair_count):
                p0 = points[i]
                p1 = points[(i + 1) % n]
                if p0 != p1:
                    segments.append({"layer": layer, "start": p0, "end": p1, "entity_type": dxftype})

        # ARC/CIRCLE/SPLINE/etc: ignorados de proposito (ver docstring do modulo).

    return segments


def list_layers_with_counts(path):
    """Dict {nome_da_layer: quantidade_de_entidades_lineares} - usado pela
    UI para o usuario escolher a layer das paredes, do mesmo jeito que o
    botao do Revit ja pergunta hoje (Layer ordenado por numero de linhas)."""
    doc = ezdxf.readfile(path)
    counts = {}
    msp = doc.modelspace()
    for entity in _iter_linear_entities(msp):
        layer = entity.dxf.layer
        counts[layer] = counts.get(layer, 0) + 1
    return counts
