# AbrirModeladorExterno.pushbutton

Repositorio independente do botao `AbrirModeladorExterno.pushbutton` para
pyRevit.

Esta raiz contem sua propria copia de `core/`, incluindo
`core/wall_modeling.py` e `core/capture_export.py`, para que o botao nao
importe nem leia arquivos de `MeuBotao.pushbutton`.

O botao captura dados do Revit e abre o projeto externo
`ModulacaoVisualizador3D`. Esse visualizador continua sendo uma dependencia
funcional do fluxo do modelador externo, mas nao ha dependencia entre este
repositorio e o repositorio `MeuBotao.pushbutton`.

## Testes

```powershell
py -m pytest tests -q
```
