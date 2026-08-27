# AbrirModeladorExterno.pushbutton - organizacao do loader

Esta pasta fica separada em duas partes:

- `script.py`: arquivo local obrigatorio do pyRevit. Deixe solto na raiz da
  pasta `.pushbutton`. Ele e' o loader.
- `nuvem/`: pacote baixavel pelo loader. Aqui ficam o motor real
  (`external_modelador.py`), o exportador JSON (`capture_export_external.py`)
  e o visualizador (`ModulacaoVisualizador3D/`).

Em uma instalacao local do pyRevit, a pasta `nuvem/` pode ser apagada. Ao
clicar no botao, `script.py` baixa a versao mais recente do GitHub para:

```
%LOCALAPPDATA%\AbrirModeladorExternoPushbutton\external_modelador_cache
```

Se o GitHub ou a internet falhar, o loader usa a ultima copia completa em
cache. A copia propria de `nuvem/core/` tambem e' baixada para o mesmo
cache, porque o modelador externo reaproveita funcoes do motor principal sem
depender de outro repositorio.
