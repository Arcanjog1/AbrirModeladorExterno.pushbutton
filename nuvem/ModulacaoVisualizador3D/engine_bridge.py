# -*- coding: utf-8 -*-
"""Ponte para reaproveitar o motor puro copiado para este repositorio
(core/engine/geometry.py, modulation_math.py, opening_audit.py,
wall_pairing.py, wall_stepper.py).

Este repositorio carrega sua propria copia de `nuvem/core/`, sem apontar
para `ModulacaoAutomatica` nem para `MeuBotao.pushbutton`.

Como funciona:
1. Acha a pasta `nuvem/` deste repositorio, que contem `core/`.
2. Registra um shim MINIMO de `Autodesk.Revit.DB` em sys.modules, contendo
   so' XYZ/Line/Curve com geometria REAL, reduzido ao que
   `core/engine/geometry.py` realmente importa: `from Autodesk.Revit.DB
   import XYZ, Line`) - assim geometry.py roda AQUI sem nenhuma alteracao e
   sem precisar do Revit/pyRevit instalados.
3. Importa core.engine.geometry / core.engine.modulation_math /
   core.engine.opening_audit e reexporta o que este projeto usa.

Se `core/engine/` ganhar uma funcao nova relevante aqui, so' precisa
adicionar o nome na lista de reexport abaixo."""

import math
import os
import sys

def _get_pushbutton_path():
    return os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


LOCAL_PUSHBUTTON_PATH = _get_pushbutton_path()


def _ensure_path():
    path = _get_pushbutton_path()
    if not os.path.isdir(path):
        raise RuntimeError(
            "Nao encontrei a pasta local do motor em {!r}.".format(path)
        )
    if path not in sys.path:
        sys.path.insert(0, path)


def _install_minimal_revit_db_shim():
    """Registra um `Autodesk.Revit.DB` falso, so' com XYZ/Curve/Line (o
    minimo que core/engine/geometry.py importa), com geometria REAL - nao
    e' um mock que sempre concorda. Nao faz nada se algo real ja estiver
    registrado (ex.: rodando dentro do pyRevit de verdade)."""
    if "Autodesk.Revit.DB" in sys.modules:
        return
    import types

    class XYZ(object):
        def __init__(self, x=0.0, y=0.0, z=0.0):
            self.X = float(x)
            self.Y = float(y)
            self.Z = float(z)

        def __add__(self, other):
            return XYZ(self.X + other.X, self.Y + other.Y, self.Z + other.Z)

        def __sub__(self, other):
            return XYZ(self.X - other.X, self.Y - other.Y, self.Z - other.Z)

        def __mul__(self, k):
            return XYZ(self.X * k, self.Y * k, self.Z * k)

        __rmul__ = __mul__

        def __truediv__(self, k):
            return XYZ(self.X / k, self.Y / k, self.Z / k)

        def __neg__(self):
            return XYZ(-self.X, -self.Y, -self.Z)

        def GetLength(self):
            return math.sqrt(self.X ** 2 + self.Y ** 2 + self.Z ** 2)

        def DistanceTo(self, other):
            return (self - other).GetLength()

        def DotProduct(self, other):
            return self.X * other.X + self.Y * other.Y + self.Z * other.Z

        def CrossProduct(self, other):
            return XYZ(
                self.Y * other.Z - self.Z * other.Y,
                self.Z * other.X - self.X * other.Z,
                self.X * other.Y - self.Y * other.X,
            )

        def Normalize(self):
            length = self.GetLength()
            if length < 1e-12:
                return XYZ(0.0, 0.0, 0.0)
            return XYZ(self.X / length, self.Y / length, self.Z / length)

        def Negate(self):
            return XYZ(-self.X, -self.Y, -self.Z)

        def __repr__(self):
            return "XYZ({:.4f}, {:.4f}, {:.4f})".format(self.X, self.Y, self.Z)

    class Curve(object):
        pass

    class Line(Curve):
        def __init__(self, p0, p1):
            self._p0 = p0
            self._p1 = p1

        @staticmethod
        def CreateBound(p0, p1):
            if p0.DistanceTo(p1) < 1e-9:
                raise ValueError("Line.CreateBound: pontos coincidentes")
            return Line(p0, p1)

        def GetEndPoint(self, index):
            return self._p0 if index == 0 else self._p1

        @property
        def Direction(self):
            return (self._p1 - self._p0).Normalize()

        @property
        def Length(self):
            return self._p0.DistanceTo(self._p1)

        def Evaluate(self, param, normalized=True):
            if not normalized:
                param = param / max(self.Length, 1e-12)
            return self._p0 + (self._p1 - self._p0) * param

        def __repr__(self):
            return "Line({!r} -> {!r})".format(self._p0, self._p1)

    revit_module = types.ModuleType("Autodesk")
    db_module = types.ModuleType("Autodesk.Revit.DB")
    db_module.XYZ = XYZ
    db_module.Curve = Curve
    db_module.Line = Line
    revit_submodule = types.ModuleType("Autodesk.Revit")
    revit_submodule.DB = db_module
    revit_module.Revit = revit_submodule
    sys.modules["Autodesk"] = revit_module
    sys.modules["Autodesk.Revit"] = revit_submodule
    sys.modules["Autodesk.Revit.DB"] = db_module


_ensure_path()
_install_minimal_revit_db_shim()

from core.engine.modulation_math import (  # noqa: E402
    BLOCK_LENGTHS_CM, BLOCK_WIDTH_CM, BLOCK_JOINT_CM, BLOCK_OPENING_JOINT_CM,
    PIER_MODULE_CM, BLOCK_COMPENSATORS_ENABLED_BY_DEFAULT,
    MODULATION_WHOLE_CM_TOLERANCE_CM, pack_pier_with_blocks,
    solve_opening_modulation, pier_closes_with_blocks_cm,
    wall_length_closes_with_blocks_cm, nearest_wall_lengths_cm,
    suggested_block_length_cm, evaluate_wall_block_length,
    PIER_BOUNDARY_JOINT_COMBINATIONS_CM, _pier_remaining_cm,
)
from core.engine.opening_audit import (  # noqa: E402
    merge_axis_intervals, gaps_between_intervals,
    detect_wall_openings_from_courses,
)
from core.engine.geometry import (  # noqa: E402
    are_lines_parallel, get_line_midpoint, project_point_on_line,
    get_distance_between_parallel_lines, create_centerline,
    merge_collinear_fragments, lines_overlap_enough,
)
from core.engine.wall_pairing import (  # noqa: E402
    find_wall_pairs, extend_wall_ends_to_junctions, deduplicate_walls,
    scan_possible_missed_bonecas, classify_unused_line_reason,
    build_wall_graph, build_plan_bounds, build_no_pairs_message,
    scan_candidate_thicknesses_cm, compute_detection_tolerance_ft,
    assign_openings_to_walls, build_wall_segments,
)
# core.engine.wall_stepper: motor de PROCESSAMENTO/MODULACAO parede-a-parede
# (encontros L/T/X, jambs de abertura, laco principal
# process_walls_one_by_one, deslocamento de grupo da ETAPA 3C) - extraido de
# wall_modeling.py com o MESMO padrao de wall_pairing.py acima (ver
# ARQUITETURA_INTERATIVA.md/plano do "modelador externo", 2026-08-26).
# So' reexportamos aqui as entradas
# publicas de alto nivel que o modelador externo precisa chamar - as
# dezenas de helpers privados de que elas dependem continuam vivendo so'
# dentro de wall_stepper.py (import * ja' os traz para o mesmo namespace,
# nao precisam ser citados aqui).
from core.engine.wall_stepper import (  # noqa: E402
    process_walls_one_by_one, order_walls_for_processing,
    solve_all_intersections, solve_all_wall_fill, solve_building_blocks,
    find_wall_group_shift_fixes, validate_wall_modulation,
    classify_wall_orientation, candidates_near_wall,
    validate_same_course_collision, solve_l_corner, solve_t_intersection,
    solve_x_intersection, solve_wall_free_fill,
)
from core.engine.tolerances import (  # noqa: E402
    FEET_PER_METER, MIN_WALL_SEGMENT_OVERLAP_RATIO, MIN_WALL_SEGMENT_ABS_FLOOR_M,
    MIN_WALL_THICKNESS_M, MAX_WALL_THICKNESS_M, MIN_WALL_THICKNESS_FT,
    MAX_WALL_THICKNESS_FT, JUNCTION_FACE_SEARCH_FT, WALL_DETECTION_TOLERANCE_FT,
)

# XYZ/Line: reais quando rodando dentro do Revit (pyRevit), ou o shim leve
# instalado por _install_minimal_revit_db_shim() acima quando rodando aqui
# (CPython puro) - registrados em sys.modules["Autodesk.Revit.DB"] antes
# deste ponto, entao este import pega a MESMA classe que geometry.py/
# wall_pairing.py estao usando.
from Autodesk.Revit.DB import XYZ, Line  # noqa: E402


def make_line(p0_cm, p1_cm):
    """Constroi um `Line` (do shim ou do Revit real) a partir de dois pontos
    em CENTIMETROS `(x, y)` - conversao cm->pe' embutida, para quem chama
    daqui (ex.: wall_pairing.py deste projeto) nao precisar importar
    XYZ/Line nem saber a constante de conversao."""
    scale = FEET_PER_METER / 100.0
    x0, y0 = p0_cm
    x1, y1 = p1_cm
    return Line.CreateBound(XYZ(x0 * scale, y0 * scale, 0.0), XYZ(x1 * scale, y1 * scale, 0.0))


def point_to_cm(xyz):
    """Converte um XYZ (pes, do shim ou do Revit real) para (x_cm, y_cm)."""
    scale = 100.0 / FEET_PER_METER
    return (xyz.X * scale, xyz.Y * scale)


__all__ = [
    "BLOCK_LENGTHS_CM", "BLOCK_WIDTH_CM", "BLOCK_JOINT_CM",
    "BLOCK_OPENING_JOINT_CM", "PIER_MODULE_CM",
    "BLOCK_COMPENSATORS_ENABLED_BY_DEFAULT", "MODULATION_WHOLE_CM_TOLERANCE_CM",
    "pack_pier_with_blocks", "solve_opening_modulation",
    "pier_closes_with_blocks_cm", "wall_length_closes_with_blocks_cm",
    "nearest_wall_lengths_cm", "suggested_block_length_cm",
    "evaluate_wall_block_length", "PIER_BOUNDARY_JOINT_COMBINATIONS_CM",
    "_pier_remaining_cm", "merge_axis_intervals",
    "gaps_between_intervals", "detect_wall_openings_from_courses",
    "are_lines_parallel", "get_line_midpoint", "project_point_on_line",
    "get_distance_between_parallel_lines", "create_centerline",
    "merge_collinear_fragments", "lines_overlap_enough",
    "find_wall_pairs", "extend_wall_ends_to_junctions", "deduplicate_walls",
    "scan_possible_missed_bonecas", "classify_unused_line_reason",
    "build_wall_graph", "build_plan_bounds", "build_no_pairs_message",
    "scan_candidate_thicknesses_cm", "compute_detection_tolerance_ft",
    "assign_openings_to_walls",
    "process_walls_one_by_one", "order_walls_for_processing",
    "solve_all_intersections", "solve_all_wall_fill", "solve_building_blocks",
    "find_wall_group_shift_fixes", "validate_wall_modulation",
    "classify_wall_orientation", "candidates_near_wall",
    "validate_same_course_collision", "solve_l_corner", "solve_t_intersection",
    "solve_x_intersection", "solve_wall_free_fill",
    "FEET_PER_METER", "MIN_WALL_SEGMENT_OVERLAP_RATIO", "MIN_WALL_SEGMENT_ABS_FLOOR_M",
    "MIN_WALL_THICKNESS_M", "MAX_WALL_THICKNESS_M", "MIN_WALL_THICKNESS_FT",
    "MAX_WALL_THICKNESS_FT", "JUNCTION_FACE_SEARCH_FT", "WALL_DETECTION_TOLERANCE_FT",
    "XYZ", "Line", "make_line", "point_to_cm",
    "LOCAL_PUSHBUTTON_PATH",
]
