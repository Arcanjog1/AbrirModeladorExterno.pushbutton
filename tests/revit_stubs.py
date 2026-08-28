# -*- coding: utf-8 -*-
"""Duble (stub) da API do Revit/pyRevit/.NET para rodar o Script.py FORA do
Revit, num Python comum, so' para teste automatizado.

Motivacao: o Script.py so' roda dentro do Revit (pyRevit/IronPython 2.7), e
por isso nunca teve como ser testado antes de ser usado no projeto real -
qualquer erro de digitacao numa funcao pouco usada so' aparecia no meio de
uma execucao, depois do usuario ja ter escolhido CAD/Layer/Nivel.

Estes dubles implementam:
  - GEOMETRIA DE VERDADE (XYZ, Line, Transform) - contas reais, para que os
    testes de geometria/modulacao exercitem a matematica do script, nao um
    mock que sempre concorda;
  - o resto da API do Revit como objetos inertes (registram o que foi
    chamado e nao fazem nada), suficiente para o modulo ser importado;
  - WinForms/Drawing como controles falsos que guardam propriedades e a
    arvore de Controls - e' isso que permite CONSTRUIR cada janela do script
    e conferir a estrutura dela sem uma tela.

Nada aqui e' usado em producao: o Revit real substitui tudo isto.
"""

import math
import sys
import types


# ----------------------------------------------------------------- geometria
class XYZ(object):
    """Ponto/vetor 3D com a mesma superficie que o script usa do XYZ real."""

    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.X = float(x)
        self.Y = float(y)
        self.Z = float(z)

    # operadores (o script usa p + v, p - q, v * escalar)
    def __add__(self, other):
        return XYZ(self.X + other.X, self.Y + other.Y, self.Z + other.Z)

    def __sub__(self, other):
        return XYZ(self.X - other.X, self.Y - other.Y, self.Z - other.Z)

    def __mul__(self, k):
        return XYZ(self.X * k, self.Y * k, self.Z * k)

    __rmul__ = __mul__

    def __truediv__(self, k):
        return XYZ(self.X / k, self.Y / k, self.Z / k)

    __div__ = __truediv__

    def __neg__(self):
        return XYZ(-self.X, -self.Y, -self.Z)

    def Negate(self):
        return -self

    def __getitem__(self, index):
        # o XYZ do Revit expoe um indexador (Item[int]) - o script usa
        # size_local[0]/size_local[1] em _block_smaller_cell.
        return (self.X, self.Y, self.Z)[index]

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

    def __repr__(self):
        return "XYZ({:.4f}, {:.4f}, {:.4f})".format(self.X, self.Y, self.Z)


XYZ.Zero = XYZ(0.0, 0.0, 0.0)
XYZ.BasisX = XYZ(1.0, 0.0, 0.0)
XYZ.BasisY = XYZ(0.0, 1.0, 0.0)
XYZ.BasisZ = XYZ(0.0, 0.0, 1.0)


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

    @staticmethod
    def CreateUnbound(origin, direction):
        return Line(origin, origin + direction)

    def GetEndPoint(self, index):
        return self._p0 if index == 0 else self._p1

    @property
    def Direction(self):
        return (self._p1 - self._p0).Normalize()

    @property
    def Length(self):
        return self._p0.DistanceTo(self._p1)

    @property
    def ApproximateLength(self):
        return self.Length

    def Evaluate(self, param, normalized=True):
        if not normalized:
            param = param / max(self.Length, 1e-12)
        return self._p0 + (self._p1 - self._p0) * param

    def Tessellate(self):
        return [self._p0, self._p1]

    def __repr__(self):
        return "Line({!r} -> {!r})".format(self._p0, self._p1)


class Transform(object):
    """So' o suficiente para _extract_block_cells_local: identidade + origem."""

    def __init__(self, origin=None, basis_x=None, basis_y=None):
        self.Origin = origin or XYZ(0.0, 0.0, 0.0)
        self.BasisX = basis_x or XYZ(1.0, 0.0, 0.0)
        self.BasisY = basis_y or XYZ(0.0, 1.0, 0.0)
        self.BasisZ = XYZ(0.0, 0.0, 1.0)

    @staticmethod
    def Identity():
        return Transform()

    def OfPoint(self, point):
        return XYZ(
            self.Origin.X + self.BasisX.X * point.X + self.BasisY.X * point.Y,
            self.Origin.Y + self.BasisX.Y * point.X + self.BasisY.Y * point.Y,
            self.Origin.Z + point.Z,
        )

    @property
    def Inverse(self):
        return Transform()


# ------------------------------------------------------- objetos inertes
class _Inert(object):
    """Objeto que aceita qualquer atributo/chamada sem explodir - usado para
    as classes do Revit que o script so' menciona (nunca exercita nos
    testes)."""

    def __init__(self, *args, **kwargs):
        self._args = args

    def __getattr__(self, name):
        return _Inert()

    def __call__(self, *args, **kwargs):
        return _Inert()

    def __iter__(self):
        return iter(())

    def __bool__(self):
        return False

    __nonzero__ = __bool__


def _inert_class(name):
    return type(str(name), (_Inert,), {})


class _ThreadStub(object):
    """Stub de System.Threading.Thread para os testes offline (usado por
    _PostCreationEventHandler._execute_analyze - ver Mudanca 2 do plano de
    arquitetura "solver em memoria/aplicacao unica"). `Start()` roda o
    callback (`target`) SINCRONO na hora, na mesma thread do teste -
    suficiente para testar o CONTRATO (o resultado/erro chega em on_done
    de qualquer forma) sem depender de concorrencia real; threading .NET
    de verdade so' e' verificavel ao vivo no Revit, nunca aqui.

    `CurrentThread` (atributo de CLASSE, como no .NET real): sempre devolve
    o mesmo stub "thread principal" (IsBackground=False) - os testes offline
    nunca rodam de verdade em thread separada (ver Start() acima), entao nao
    ha' como this stub distinguir "chamado de dentro do worker" de "chamado
    da thread do teste". Usado por core/engine/wall_stepper.py
    (_pump_ui_events_if_needed) para decidir DoEvents() vs time.sleep -
    aqui sempre cai no ramo DoEvents() (que por sua vez e' outro _Inert,
    no-op)."""

    CurrentThread = _Inert()
    CurrentThread.IsBackground = False

    def __init__(self, target):
        self._target = target
        self.IsBackground = False

    def Start(self):
        self._target()


class _DotNetList(list):
    """Duble de System.Collections.Generic.List<T>: uma list do Python com
    o `.Add()`/`.Count` do .NET por cima. So' o suficiente para o codigo do
    motor que monta um ICollection<ElementId> de verdade - `List[ElementId]()`
    em _execute_create (Delete em lote do lote anterior) e em _execute_zoom."""

    def Add(self, item):
        self.append(item)

    @property
    def Count(self):
        return len(self)


class _GenericTypeStub(object):
    """`List[Tipo]` no .NET fecha um tipo generico; aqui basta devolver algo
    chamavel que produza um _DotNetList. Aceita tambem `List()` direto, para
    nao quebrar nenhum chamador antigo do duble anterior (`lambda: []`)."""

    def __getitem__(self, _item_type):
        return _DotNetList

    def __call__(self, *args, **kwargs):
        return _DotNetList()


class ElementId(object):
    InvalidElementId = None

    def __init__(self, value=-1):
        self.IntegerValue = int(value)

    def ToString(self):
        return str(self.IntegerValue)

    def __eq__(self, other):
        return isinstance(other, ElementId) and other.IntegerValue == self.IntegerValue

    def __hash__(self):
        return hash(self.IntegerValue)

    def __repr__(self):
        return "ElementId({})".format(self.IntegerValue)


ElementId.InvalidElementId = ElementId(-1)


class _FakeFamilyInstance(object):
    """Devolvido por _StubCreate.NewFamilyInstance - so' o suficiente
    (Id) para create_building_blocks montar created_instances/created_count
    de verdade, sem precisar do Revit real. RotateElement/MirrorElement
    (ElementTransformUtils, stubado como _Inert em outro lugar deste
    arquivo) nunca leem nada desta instancia, so' o Id."""
    _next_int = [1000]

    def __init__(self):
        self.Id = ElementId(_FakeFamilyInstance._next_int[0])
        _FakeFamilyInstance._next_int[0] += 1


class _StubCreate(object):
    """Duble de `Document.Create` - so' o metodo que create_building_blocks
    realmente chama (NewFamilyInstance), para poder exercitar essa funcao
    de ponta a ponta nos testes offline (ver test_create_building_blocks_*
    em test_script.py) em vez de so' mockar `_create_building_blocks`
    inteira como o resto da suite faz."""

    def NewFamilyInstance(self, point, symbol, level, structural_type):
        return _FakeFamilyInstance()


class _StubDoc(object):
    def __init__(self):
        self.ActiveView = _Inert()
        self.Application = _Inert()
        self.regenerate_calls = 0
        self.Create = _StubCreate()

    def Regenerate(self):
        self.regenerate_calls += 1

    def GetElement(self, element_id):
        return None


class _StubUIDoc(object):
    def __init__(self, document):
        self.Document = document
        self.Selection = _Inert()


class _StubExternalEvent(_Inert):
    """Duble de Autodesk.Revit.UI.ExternalEvent - so' o suficiente
    (`Create` como factory estatica, `Raise` inerte) para codigo que faz
    `ExternalEvent.Create(handler)` rodar nos testes offline (ver
    _show_wall_review_window/_show_post_creation_window). `_inert_class`
    sozinho nao bastava aqui: `__getattr__` e' um metodo de INSTANCIA -
    nunca intercepta o acesso a um atributo de CLASSE (`ExternalEvent.
    Create`, antes de qualquer instancia existir), entao virava
    AttributeError em vez de devolver um _Inert() como o resto do
    modulo faz."""

    @classmethod
    def Create(cls, handler):
        return cls()


class _StubPlane(object):
    """Duble de Autodesk.Revit.DB.Plane - so' a fabrica que
    create_building_blocks usa (CreateByNormalAndOrigin), guardando normal
    e origem para o teste conferir em torno de QUE plano a peca foi
    espelhada."""

    def __init__(self, normal, origin):
        self.Normal = normal
        self.Origin = origin

    @staticmethod
    def CreateByNormalAndOrigin(normal, origin):
        return _StubPlane(normal, origin)


class _StubElementTransformUtils(object):
    """Duble de ElementTransformUtils que REGISTRA as transformacoes
    pedidas (`calls`), em vez de so' nao explodir.

    Por que uma INSTANCIA (nao uma classe inerte como o resto): `_Inert.
    __getattr__` e' metodo de instancia e nunca intercepta acesso a
    atributo de CLASSE - `ElementTransformUtils.RotateElement` estourava
    AttributeError, e como create_building_blocks tem try/except por
    candidato, a peca rotacionada/espelhada virava "falha" em silencio.
    Resultado: os dois unicos caminhos de create_building_blocks que
    chamam a API de transformacao NUNCA foram exercitados pela suite
    offline. Registrando as chamadas da' para testar de fora do Revit o
    que ate' entao so' dava para conferir ao vivo: QUAIS pecas rotacionam,
    em torno de que eixo e por que angulo, e quais espelham em que plano.
    Metodos nao declarados aqui (MoveElement, CopyElement, ...) continuam
    estourando AttributeError como antes - de proposito, para nao mudar em
    silencio o comportamento de nenhum outro teste ja existente.

    NAO substitui conferencia no Revit real (o duble nao move nada de
    verdade) - ver tests/README.md."""

    def __init__(self):
        self.calls = []

    def RotateElement(self, document, element_id, axis, angle_radians):
        self.calls.append(("rotate", element_id, axis, angle_radians))

    def MirrorElement(self, document, element_id, plane):
        self.calls.append(("mirror", element_id, plane))


class _StubTransaction(object):
    log = []

    def __init__(self, document, name):
        self.name = name

    def Start(self):
        _StubTransaction.log.append(("start", self.name))

    def Commit(self):
        _StubTransaction.log.append(("commit", self.name))

    def RollBack(self):
        _StubTransaction.log.append(("rollback", self.name))


# ------------------------------------------------------------- WinForms
class _EventSlot(object):
    """Simula `control.Click += handler` guardando os handlers."""

    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def __isub__(self, handler):
        if handler in self.handlers:
            self.handlers.remove(handler)
        return self

    def fire(self, sender=None, args=None):
        for handler in list(self.handlers):
            handler(sender, args)


class _ControlCollection(list):
    def Add(self, control):
        self.append(control)

    def AddRange(self, controls):
        self.extend(controls)

    def Clear(self):
        del self[:]

    @property
    def Count(self):
        return len(self)


class _Control(object):
    """Controle WinForms falso: aceita qualquer propriedade, guarda os
    filhos em .Controls e expoe eventos que podem ser disparados no teste."""

    _EVENTS = (
        "Click", "FormClosed", "SelectedIndexChanged", "TextChanged",
        "CheckedChanged", "ItemCheck", "KeyDown", "Shown", "Load",
        "SelectedValueChanged", "DoubleClick", "Resize",
    )

    def __init__(self, *args, **kwargs):
        object.__setattr__(self, "_props", {})
        self.Controls = _ControlCollection()
        self.Text = ""
        self.Name = ""
        self.Enabled = True
        self.Visible = True
        self.Tag = None
        for event in _Control._EVENTS:
            object.__setattr__(self, event, _EventSlot())

    # aceita qualquer propriedade nao declarada (Dock, Padding, BackColor...)
    def __getattr__(self, name):
        # As janelas do script sao subclasses de Form que NAO chamam
        # Form.__init__ (no IronPython o construtor da classe .NET base roda
        # sozinho) - por isso a inicializacao aqui e' PREGUICOSA.
        if name in ("_props", "Controls") or not name.startswith("_"):
            if "_props" not in self.__dict__:
                _Control.__init__(self)
                return object.__getattribute__(self, name) if name in self.__dict__ \
                    else self.__dict__["_props"].setdefault(name, _Inert())
        if name.startswith("_"):
            raise AttributeError(name)
        props = object.__getattribute__(self, "_props")
        if name not in props:
            props[name] = _Inert()
        return props[name]

    def __setattr__(self, name, value):
        object.__setattr__(self, name, value)

    def Show(self):
        self.shown = True

    def ShowDialog(self):
        self.shown_modal = True
        return None

    def Close(self):
        self.closed = True
        self.FormClosed.fire(self, None)

    def Focus(self):
        pass

    def Refresh(self):
        pass

    def SuspendLayout(self):
        pass

    def ResumeLayout(self, *args):
        pass

    def Dispose(self):
        pass

    def PerformClick(self):
        self.Click.fire(self, None)

    def descendants(self):
        for child in self.Controls:
            yield child
            for sub in child.descendants():
                yield sub


class Form(_Control):
    pass


class Label(_Control):
    pass


class Button(_Control):
    def __init__(self, *args, **kwargs):
        _Control.__init__(self, *args, **kwargs)
        self.FlatAppearance = _Inert()


class Panel(_Control):
    pass


class GroupBox(_Control):
    pass


class TextBox(_Control):
    pass


class CheckBox(_Control):
    def __init__(self, *args, **kwargs):
        _Control.__init__(self, *args, **kwargs)
        self.Checked = False


class RadioButton(CheckBox):
    pass


class ComboBox(_Control):
    def __init__(self, *args, **kwargs):
        _Control.__init__(self, *args, **kwargs)
        self.Items = _ControlCollection()
        self.SelectedIndex = -1
        self.SelectedItem = None

    def __setattr__(self, name, value):
        if name == "SelectedIndex":
            object.__setattr__(self, "SelectedIndex", value)
            items = getattr(self, "Items", [])
            object.__setattr__(
                self, "SelectedItem",
                items[value] if 0 <= value < len(items) else None
            )
            slot = self.__dict__.get("SelectedIndexChanged")
            if slot is not None:
                slot.fire(self, None)
            return
        object.__setattr__(self, name, value)


class ListBox(ComboBox):
    pass


class CheckedListBox(_Control):
    def __init__(self, *args, **kwargs):
        _Control.__init__(self, *args, **kwargs)
        self.Items = _ControlCollection()
        self._checked = set()

    def SetItemChecked(self, index, value):
        if value:
            self._checked.add(index)
        else:
            self._checked.discard(index)

    def GetItemChecked(self, index):
        return index in self._checked

    @property
    def CheckedItems(self):
        return [self.Items[i] for i in sorted(self._checked) if i < len(self.Items)]

    @property
    def CheckedIndices(self):
        return sorted(self._checked)


class ListViewSubItemCollection(list):
    def Add(self, text):
        item = _Inert()
        item.Text = text
        self.append(text)
        return item


class ListViewItem(object):
    def __init__(self, text=""):
        self.Text = text
        self.SubItems = ListViewSubItemCollection([text])
        self.ForeColor = None
        self.BackColor = None
        self.Tag = None
        self.Checked = False
        self.Selected = False
        self.UseItemStyleForSubItems = True

    @property
    def cells(self):
        return list(self.SubItems)


class _ColumnCollection(list):
    def Add(self, caption, width=None, align=None):
        self.append((caption, width))
        return _Inert()


class _ItemCollection(list):
    def Add(self, item):
        self.append(item)
        return item

    def AddRange(self, items):
        self.extend(items)

    def Clear(self):
        del self[:]

    def RemoveAt(self, index):
        del self[index]

    @property
    def Count(self):
        return len(self)


class ListView(_Control):
    def __init__(self, *args, **kwargs):
        _Control.__init__(self, *args, **kwargs)
        self.Columns = _ColumnCollection()
        self.Items = _ItemCollection()

    @property
    def CheckedItems(self):
        return [i for i in self.Items if getattr(i, "Checked", False)]

    @property
    def SelectedItems(self):
        return [i for i in self.Items if getattr(i, "Selected", False)]


class TabPage(_Control):
    def __init__(self, text=""):
        _Control.__init__(self)
        self.Text = text


class TabControl(_Control):
    def __init__(self, *args, **kwargs):
        _Control.__init__(self, *args, **kwargs)
        self.TabPages = _ControlCollection()
        self.SelectedIndex = 0


class ProgressBar(_Control):
    pass


class _Enum(object):
    """Duble de um TIPO de enum .NET (System.Windows.Forms/System.Drawing).
    Alem de responder por atributo (`DockStyle.Top` -> "DockStyle.Top",
    ja' existia), tambem e' CHAMAVEL com um inteiro (`FormStartPosition(1)`
    -> "FormStartPosition(1)") - o codigo real usa exatamente essa chamada
    (`TipoDoEnum(int_value)`) como correcao ao bug real de producao
    "since Python.NET 3.0 int can not be converted to Enum implicitly. Use
    Enum(int_value)" (2026-08-27); sem `__call__` aqui o modulo nem carrega
    nos testes (`TypeError: '_Enum' object is not callable`)."""

    def __init__(self, name):
        self._name = name

    def __getattr__(self, item):
        return "{}.{}".format(self._name, item)

    def __call__(self, value):
        return "{}({})".format(self._name, value)


class Padding(object):
    def __init__(self, *args):
        self.args = args


class Size(object):
    def __init__(self, w=0, h=0):
        self.Width = w
        self.Height = h


class Color(object):
    """System.Drawing.Color. Como no .NET real, NAO tem construtor publico:
    so' se cria por FromArgb. Isso e' o que permite ao teste de regressao
    perceber quando um `Color(r, g, b)` destinado ao Revit acaba resolvendo
    para esta classe (ver test_realce_usa_a_cor_do_revit)."""

    White = "White"
    Black = "Black"
    Transparent = "Transparent"

    def __init__(self, *args):
        raise TypeError(
            "System.Drawing.Color nao tem construtor publico - use Color.FromArgb"
        )

    @staticmethod
    def FromArgb(*args):
        if len(args) == 4:
            args = args[1:]
        created = Color.__new__(Color)
        created.R, created.G, created.B = args
        return created

    def __repr__(self):
        return "Color({}, {}, {})".format(self.R, self.G, self.B)


class Font(object):
    def __init__(self, family, size, style=None):
        self.FontFamily = family
        self.Size = size
        self.Style = style


class FontFamily(object):
    GenericMonospace = "GenericMonospace"
    GenericSansSerif = "GenericSansSerif"

    def __init__(self, name):
        self.Name = name


def install():
    """Registra todos os dubles em sys.modules. Chamar ANTES de importar o
    Script.py."""

    def module(name, **attrs):
        mod = types.ModuleType(name)
        for key, value in attrs.items():
            setattr(mod, key, value)
        sys.modules[name] = mod
        return mod

    # clr
    clr = module("clr")
    clr.AddReference = lambda *a, **k: None
    clr.GetClrType = lambda t: t

    # System / System.Drawing / System.Windows.Forms
    system = module("System")
    system.Guid = type("Guid", (object,), {"__init__": lambda self, s=None: None})
    system.Object = object
    system.Action = lambda target=None: target
    # `System.Enum.ToObject(TipoDoEnum, int)` - usado como 2o fallback (ver
    # `_EnumFallback._from_int` / `_enum` do loader) quando `TipoDoEnum(int)`
    # falha; o duble `_Enum` real ja' aceita `__call__`, entao esta funcao
    # nunca precisa disparar nos testes - existe so' para o `from System
    # import Enum` no topo do modulo nao quebrar a carga.
    system.Enum = type("Enum", (object,), {
        "ToObject": staticmethod(lambda enum_type, value: enum_type(value)),
    })
    module(
        "System.Threading", Timer=_inert_class("Timer"),
        Thread=_ThreadStub, ThreadStart=(lambda target: target),
    )
    module("System.Collections")
    module("System.Collections.Generic", List=_GenericTypeStub())
    module(
        "System.Drawing",
        Font=Font, FontFamily=FontFamily, Color=Color, Size=Size,
        FontStyle=_Enum("FontStyle"), Point=lambda *a: _Inert(),
    )
    winforms = module(
        "System.Windows.Forms",
        Form=Form, Label=Label, Button=Button, Panel=Panel, TextBox=TextBox,
        CheckBox=CheckBox, RadioButton=RadioButton, ComboBox=ComboBox,
        ListBox=ListBox, CheckedListBox=CheckedListBox, ListView=ListView,
        ListViewItem=ListViewItem, TabControl=TabControl, TabPage=TabPage,
        ProgressBar=ProgressBar, ProgressBarStyle=_Enum("ProgressBarStyle"), GroupBox=GroupBox,
        DockStyle=_Enum("DockStyle"), FormStartPosition=_Enum("FormStartPosition"),
        ScrollBars=_Enum("ScrollBars"), AnchorStyles=_Enum("AnchorStyles"),
        Padding=Padding, View=_Enum("View"),
        ColumnHeaderStyle=_Enum("ColumnHeaderStyle"),
        HorizontalAlignment=_Enum("HorizontalAlignment"),
        BorderStyle=_Enum("BorderStyle"), FlatStyle=_Enum("FlatStyle"),
        DialogResult=_Enum("DialogResult"), FormBorderStyle=_Enum("FormBorderStyle"),
        Clipboard=_Inert(), Application=_Inert(), Keys=_Enum("Keys"),
        ComboBoxStyle=_Enum("ComboBoxStyle"), SelectionMode=_Enum("SelectionMode"),
        MessageBox=_Inert(), Screen=_Inert(),
        MessageBoxButtons=_Enum("MessageBoxButtons"), MessageBoxIcon=_Enum("MessageBoxIcon"),
    )
    module("System.Windows", Clipboard=_Inert())

    # Autodesk.Revit.DB
    db_names = [
        "Options", "PolyLine", "GeometryInstance", "GraphicsStyle",
        "FilteredElementCollector", "Level", "Wall", "WallType", "WallKind",
        "WallUtils", "WallLocationLine", "BuiltInCategory",
        "MaterialFunctionAssignment", "FamilyInstance", "LocationPoint",
        "LocationCurve", "CompoundStructure", "Solid", "ViewDetailLevel",
        "OverrideGraphicSettings", "FillPatternElement", "IUpdater",
        "UpdaterId", "UpdaterRegistry", "ChangePriority", "SubTransaction",
        "Element", "ElementClassFilter",
        "FamilySymbol", "PlanarFace", "StorageType", "TransactionGroup",
    ]
    db_attrs = dict((name, _inert_class(name)) for name in db_names)
    db_attrs["Color"] = _inert_class("RevitColor")
    db_attrs.update({
        "XYZ": XYZ, "Line": Line, "Curve": Curve, "Transform": Transform,
        "ElementId": ElementId, "Transaction": _StubTransaction,
        # instancia (nao classe) de proposito - ver _StubElementTransformUtils
        "ElementTransformUtils": _StubElementTransformUtils(), "Plane": _StubPlane,
        # _Enum (instancia), nao _inert_class: BuiltInParameter e' sempre
        # usado como namespace de constantes (BuiltInParameter.ALGO), nunca
        # instanciado/subclasseado - um _Enum de verdade responde a
        # QUALQUER nome de parametro sem lancar AttributeError, permitindo
        # testar de ponta a ponta um codigo que le' Parameter por
        # BuiltInParameter (ver _select_existing_walls_for_modulation em
        # test_script.py).
        "BuiltInParameter": _Enum("BuiltInParameter"),
    })
    autodesk = module("Autodesk")
    revit_ns = module("Autodesk.Revit")
    autodesk.Revit = revit_ns
    db = module("Autodesk.Revit.DB", **db_attrs)
    revit_ns.DB = db
    # StructuralType mora em Autodesk.Revit.DB.Structure, nao em
    # Autodesk.Revit.DB (ver mesmo comentario no import real do Script.py).
    db_structure = module("Autodesk.Revit.DB.Structure", StructuralType=_Enum("StructuralType"))
    db.Structure = db_structure
    ui = module(
        "Autodesk.Revit.UI",
        ExternalEvent=_StubExternalEvent,
        IExternalEventHandler=_inert_class("IExternalEventHandler"),
        TaskDialog=_Inert(),
    )
    revit_ns.UI = ui
    selection = module(
        "Autodesk.Revit.UI.Selection",
        ObjectType=_Enum("ObjectType"), ISelectionFilter=_inert_class("ISelectionFilter"),
    )
    ui.Selection = selection

    # pyrevit
    stub_doc = _StubDoc()
    revit_helper = types.SimpleNamespace(
        doc=stub_doc,
        uidoc=_StubUIDoc(stub_doc),
        pick_element=lambda *a, **k: None,
    )
    forms_helper = types.SimpleNamespace(
        SelectFromList=_Inert(),
        ask_for_string=lambda *a, **k: None,
        alert=lambda *a, **k: None,
    )
    pyrevit = module("pyrevit", revit=revit_helper, forms=forms_helper, script=_Inert())
    sys.modules["pyrevit.revit"] = revit_helper
    sys.modules["pyrevit.forms"] = forms_helper
    return pyrevit
