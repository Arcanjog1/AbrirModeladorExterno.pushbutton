# Modulação Visualizador 3D (externo ao Revit)

Ferramenta local do `AbrirModeladorExterno.pushbutton` para ler uma planta
em DWG/DXF, detectar paredes e mostrar um preview rápido da modulação de
blocos.

## Por que um projeto separado

Este repositório contém sua própria cópia do motor puro em `../core/`
(`geometry.py`, `modulation_math.py`, `opening_audit.py`,
`wall_pairing.py`, `wall_stepper.py`), carregada por `engine_bridge.py`.
Não é necessário manter checkout de outro repositório ao lado.

## Como rodar

### Com um clique

Dê duplo-clique em **`Visualizador de Modulação 3D.lnk`** (ou em
`Iniciar Visualizador.bat` diretamente) nesta pasta. Ele:

1. verifica se o servidor já está rodando na porta 8080 (se estiver, só
   abre o navegador);
2. senão, sobe o servidor numa janela minimizada chamada
   "Servidor - Visualizador de Modulacao" (procure na barra de tarefas
   para ver logs ou fechar/parar);
3. abre `http://localhost:8080/` no navegador padrão automaticamente.

Para PARAR o servidor, feche a janela minimizada dele (ou use o
Gerenciador de Tarefas, processo `py.exe`/`python.exe`).

### Manual

```bash
pip install -r requirements.txt
py server.py 8080
```

Abra `http://localhost:8080/` no navegador. Cole o caminho de um `.dxf`
(veja abaixo como converter DWG), opcionalmente a(s) layer(s) das paredes,
e clique em "Gerar modulação".

### Convertendo DWG para DXF

Este projeto lê DXF (via `ezdxf`, biblioteca gratuita). A conversão de
DWG agora é automática: clique em **"Selecionar DWG"** no visualizador,
escolha o arquivo `.dwg` na caixa de seleção nativa do Windows e o
servidor aciona sozinho o **ODA File Converter**
(https://www.opendesign.com/guestfiles/oda_file_converter) já instalado
no computador — gratuito, ferramenta de linha de comando/GUI separada do
SDK pago da Open Design Alliance; **não é necessário licenciar o ODA SDK
completo** para este fluxo. O DXF resultante é salvo ao lado do DWG de
origem (mesmo nome, extensão `.dxf`) e carregado automaticamente.

Detalhes de implementação:

- `file_dialog.py`: abre a caixa de seleção de arquivo nativa do Windows
  (via PowerShell + `System.Windows.Forms.OpenFileDialog`) para escolher
  o `.dwg`.
- `oda_converter.py`: localiza a instalação do ODA File Converter
  (procura em `C:\Program Files\ODA\ODAFileConverter*\ODAFileConverter.exe`
  e, se não achar, no registro do Windows) e aciona o modo batch dele
  (`entrada -> saída`) para gerar o DXF.
- Se o ODA não estiver instalado, a interface mostra uma mensagem clara
  pedindo para instalá-lo — nenhuma etapa trava a aplicação.

Se preferir converter manualmente (sem usar o botão), o ODA File
Converter também pode ser usado direto pela sua própria interface
gráfica ou linha de comando, e o DXF resultante colado no campo "Caminho
do arquivo DXF".

## O que já funciona

- `dxf_reader.py`: lê LINE/LWPOLYLINE/POLYLINE por layer, converte unidade
  para centímetros (via `$INSUNITS` do cabeçalho DXF, ou manual — ver
  seletor "Unidade/escala do desenho" na UI, importante quando o DXF vem
  de um DWG com o cabeçalho de unidade incorreto/inconsistente com o
  desenho real).
- `wall_pairing.py`: pareia linhas em paredes usando a MESMA orquestração
  real de pareamento/junções de `core/wall_modeling.py`
  (`find_wall_pairs`/`extend_wall_ends_to_junctions`/`deduplicate_walls`/
  `scan_candidate_thicknesses_cm`, extraída para
  `core/engine/wall_pairing.py` especificamente para este projeto poder
  consumi-la),
  não mais uma reimplementação simplificada própria. Detecta encontros em
  L/T/X e reporta possíveis bonecas fora das espessuras escolhidas (ver
  `diagnostics` na resposta de `/api/load`).
- `modulation_preview.py`: preview de blocos por parede ISOLADA, usando o
  empacotador real (`pack_pier_with_blocks`).
- `server.py` + `viewer/index.html`: visualizador 3D local (Three.js) —
  carrega um DXF, mostra as paredes coloridas por status de modulação,
  lista o detalhamento de blocos por parede.
- `file_dialog.py` + `oda_converter.py`: botão "Selecionar DWG" ->
  caixa de seleção nativa do Windows -> conversão automática para DXF
  via ODA File Converter instalado -> carregamento automático no
  visualizador, sem etapa manual.
- `layer_matcher.py`: analisa cada layer do DXF com uma nota de confiança
  (geometria real via os mesmos helpers do motor + similaridade de nome
  contra o que o usuário digitar) — nunca escolhe sozinho, só relata
  `[OK]`/`[ATENÇÃO]` com % de confiança para o usuário decidir.
- `wall_validation.py`: valida o resultado do pareamento ANTES do preview
  de modulação (proporção de paredes sem par, bonecas fora das espessuras
  detectadas) — banner destacado na UI quando o resultado parece errado
  desde a leitura da planta, não só na modulação.
- `viewer/index.html`: planta baixa (todas as entidades do DXF, não só as
  paredes) desenhada no plano do chão da mesma cena 3D, nas mesmas
  coordenadas/escala das paredes; navegação estilo Revit (esquerdo
  seleciona, scroll zoom, botão do meio pan, Shift+meio orbita); botões de
  vista padrão (Topo/Frente/Lateral/Isométrica/Zoom Extents); toggles de
  modo (Planta DXF/Walls/Blocos/Eixos/Paredes com erro) e de camada
  (uma por layer do DXF); clique numa parede (no 3D ou na lista) mostra
  layer/comprimento/espessura/junções/modulação e foca a câmera nela;
  clique numa entidade da planta baixa mostra layer/tipo/comprimento/
  origem e a parede a que ela foi associada (`wall_pairing.
  associate_entities_with_walls` — aproximação geométrica, não um
  rastreamento exato interno do motor).

## Limitações conhecidas (de propósito, não escondidas)

- **O preview de modulação trata cada parede como isolada** — não há
  amarração L/T/X na modulação de blocos em si. Isto **não é falta de
  extração** (investigado a fundo, 2026-08-26): `solve_l_corner`/
  `solve_t_intersection`/`solve_x_intersection` em `wall_modeling.py` são
  puros, mas dependem de um `catalog` cujas células internas
  (`cells_local`) vêm da **geometria 3D real das famílias de bloco
  carregadas num projeto Revit** (`symbol.get_Geometry()` — vazios/
  chanfros modelados na família). Isso não tem equivalente fora de um
  projeto Revit real — é o mesmo tipo de limite estrutural das aberturas
  abaixo, não um "ainda não fizemos". Uma parede "fecha" aqui pode mudar
  de peça quando entrar em contato com uma amarração de verdade. As
  linhas de divisão de blocos na view 3D são uma referência visual
  aproximada (soma dos comprimentos de bloco), não um desenho de
  execução.
- **Aberturas (portas/janelas) não são lidas daqui** — confirmado que os
  DWGs reais não carregam essas dimensões em atributos de bloco; no motor
  real elas vêm de instâncias já colocadas no Revit. Decisão tomada
  (2026-08-26): deixar de fora por enquanto, não inventar uma fonte
  alternativa sem necessidade real comprovada.
- **Sem edição interativa ainda** (arrastar parede/abertura e recalcular
  ao vivo) — a Fase B completa do plano geral. A versão atual é só
  importar e visualizar, não editar.
- **Sem envio de volta para o Revit** — isso é a Fase C do plano geral,
  ainda não iniciada aqui.

## Testes

```bash
py -m unittest discover -s tests -v
```

41 testes cobrindo `dxf_reader.py`, `wall_pairing.py`, `layer_matcher.py`,
`wall_validation.py`, `modulation_preview.py` e `oda_converter.py` —
nenhum depende de Revit, pyRevit ou de um arquivo DXF/DWG real (geram os
próprios arquivos de teste com `ezdxf`, e o `oda_converter.py` é testado
com o `subprocess.run` mockado, sem exigir o ODA instalado).

## Próximos passos (não implementados ainda)

1. Edição interativa no visualizador (mover parede/abertura, recalcular).
2. Exportar solução aprovada em JSON e aplicar no Revit via o mecanismo de
   escrita que já existe no motor copiado em `../core/`.

Os dois itens do pedido original que ficaram de fora (amarração L/T/X real
na modulação de blocos, e aberturas) não são "próximos passos" — são
limites estruturais documentados acima (dependem de dados que só existem
dentro de um projeto Revit real).
