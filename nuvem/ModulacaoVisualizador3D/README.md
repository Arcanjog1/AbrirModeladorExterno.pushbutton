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

Ao ser aberto pelo Revit, o launcher identifica a build dos arquivos visuais.
Ele só reutiliza um servidor local se a build for exatamente a mesma; caso a
porta 8080 pertença a uma versão antiga, inicia a versão atual em outra porta.
O HTML também recebe URLs versionadas e cabeçalhos sem cache para impedir que
o navegador misture a interface nova com CSS ou JavaScript de uma execução
anterior.

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
- `modulation_preview.py`: preview simples para o fluxo DXF, usando o
  empacotador real (`pack_pier_with_blocks`).
- `wall_capture.py`: para capturas JSON do Revit, executa o solver completo
  de amarrações L/T/X por nível e faixa vertical, respeitando juntas,
  aberturas, fiadas e o catálogo real exportado das famílias.
- `server.py` + `viewer/index.html` + `viewer/editor-shell.*`: editor 3D
  local (Three.js) em tela cheia, sem barra lateral fixa, com barra de
  aplicativo BIM, ferramentas agrupadas, drawers e painéis contextuais,
  cache por arquivo, blocos vazados instanciados, renderização incremental,
  elevações reais e inspetor contextual por clique.
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
  (uma por layer do DXF); clique numa parede mostra
  layer/comprimento/espessura/junções/modulação e foca a câmera nela;
  clique numa entidade da planta baixa mostra layer/tipo/comprimento/
  origem e a parede a que ela foi associada (`wall_pairing.
  associate_entities_with_walls` — aproximação geométrica, não um
  rastreamento exato interno do motor).
- Edição dinâmica da captura Revit: selecione uma Wall ou abertura para
  editar numericamente eixo, comprimento, ângulo, espessura, altura,
  posição, largura, peitoril e altura do vão. A abertura também pode ser
  movida, duplicada ou excluída. Cada ação propaga a geometria hospedada e
  recalcula os blocos pelo mesmo solver físico; o inspetor mostra o motivo
  exato caso a Wall deixe de ser modulável.
- Calculadora manual: recebe comprimento, amarrações nas duas pontas, fiada
  e prioridade; enumera e classifica alternativas usando juntas reais e o
  catálogo carregado. Também aceita uma lista JSON de Walls independentes.
- Motor completo do modelo: com uma captura de Walls carregada, o botão
  **Recalcular modelo com motor completo** chama o mesmo solver canônico da
  modulação inicial. Ele apresenta setores, dependências L/T/X, validações e
  regiões sem solução; a calculadora manual não substitui esse fluxo.

## Fluxos e limites

- A captura JSON iniciada pelo botão do Revit é a fonte completa: traz
  Walls, nível/offset de base, portas/janelas e o catálogo real, incluindo
  dimensões, cor e vazios de cada família. Nesse fluxo, o visualizador usa
  a mesma lógica de solver do projeto, preserva parede abaixo/entre/acima
  das aberturas e permite ajuste automático ou manual de abertura somente
  quando uma nova execução do solver comprova melhora sem novos conflitos.
- O fluxo DXF continua sendo um preview geométrico, pois o arquivo não
  contém de forma confiável níveis, hosts, portas/janelas nem a geometria
  das famílias. A análise de layers é opcional e executada apenas pelo
  botão próprio, para não bloquear a geração em desenhos grandes.
- Os ajustes são mantidos na sessão do Modelador Externo. Eles atualizam a
  Wall contínua, suas aberturas hospedadas e a componente de encontros
  afetada. O comando **Enviar ao Revit** entrega o pacote ao host WebView
  quando o conector pyRevit está presente; no navegador comum, exporta o
  mesmo pacote JSON para aplicação posterior pelo comando pyRevit.
- A calculadora manual mostra hipóteses quando a geometria de um T/L/X não
  foi fornecida. A otimização global só será habilitada quando receber o
  grafo de encontros do projeto — não trata paredes isoladas como se fossem
  uma solução global validada.
- Durante o arraste de Wall ou abertura há prévia com debounce; ela calcula
  somente as faixas de nível/base afetadas e não persiste nada. Ao soltar, o
  mesmo solver recalcula e valida a edição antes de atualizar o modelo.
- Editor interativo: toda edição possui um `revision ID`; previews que chegam
  fora de ordem são descartados pela interface, e o servidor rejeita um
  commit que tenha partido de uma versão antiga do modelo. A prévia é cacheada
  por geometria/revisão e nunca altera a captura persistida.
- Histórico atômico de sessão: **Ctrl+Z/Ctrl+Shift+Z** (ou **Ctrl+Y**, além
  dos botões ↶/↷) restaura
  juntos a geometria alterada e os blocos já calculados, sem executar o solver
  novamente. Mover uma abertura e regenerar sua região é uma única operação.
- Interface BIM compacta: viewport em tela inteira, barra superior com
  projeto/sincronização/salvar/exportar, toolbar de ícones por categoria,
  navegação flutuante, ViewCube, eixos XYZ, legenda semântica, barra CAD
  inferior e temas escuro/claro. Importação, calculadora, visibilidade e
  histórico vivem em um drawer sob demanda, sem ocupar permanentemente a
  área do modelo.
- Importação guiada: o drawer preserva os controles e eventos anteriores,
  mas os apresenta nas etapas Origem, Unidades, Layers e Revisão. É possível
  avançar e voltar sem perder valores. A visibilidade tem popover compacto,
  enquanto o diagnóstico usa um dock inferior com Problemas, Diagnóstico,
  Histórico, Log, Dependências e Comandos.
- Controles de editor: seleção simples ou múltipla com **Ctrl+clique**,
  hover com contorno e tooltip, mover, girar,
  medir, snap configurável, Zoom Selected, isolamento/ocultação e modos
  Realista/Blocos/Paredes/Raio-X/Wireframe/Diagnóstico/Aberturas/Estrutural.
  A busca global usa **Ctrl+F** e a paleta de comandos usa **Ctrl+K/Ctrl+P**.
- Manipulação direta: parede ou abertura selecionada pode ser arrastada no
  viewport; handles contextuais alteram extremidades, largura e peitoril. O
  elemento acompanha o mouse a cada frame, enquanto o solver recalcula a
  modulação afetada em segundo plano. O snap oferece 1/5/10/20mm e módulo do
  projeto; **Shift** libera o movimento. A câmera fica bloqueada durante o drag.
- O modo de inspeção de Wall navega anterior/próxima, alterna frente/lateral/
  3D, mostra conectadas, blocos, aberturas, números de fiada e diagnósticos.
  O plano de corte horizontal, vertical ou alinhado à Wall aparece fisicamente
  na cena, possui plano/setas arrastáveis e clipping em tempo real. O valor
  numérico continua disponível como ajuste secundário de precisão; o lado
  visível do corte também pode ser invertido e essa ação entra no Undo.
- O renderizador mantém `InstancedMesh` por tipo e Wall. Em uma edição,
  descarta e reconstrói somente os grupos das Walls afetadas; o restante da
  cena, a câmera e a seleção permanecem estáveis.

## Testes

```bash
py -m unittest discover -s tests -v
```

86 testes cobrindo `dxf_reader.py`, `wall_pairing.py`, `layer_matcher.py`,
`wall_validation.py`, `modulation_preview.py`, `editor_session.py`, edição
geométrica atômica de Walls/aberturas, a interface BIM responsiva e
`oda_converter.py` —
nenhum depende de Revit, pyRevit ou de um arquivo DXF/DWG real (geram os
próprios arquivos de teste com `ezdxf`, e o `oda_converter.py` é testado
com o `subprocess.run` mockado, sem exigir o ODA instalado).
