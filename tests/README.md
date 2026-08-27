# Testes automatizados do core/wall_modeling.py

Estes testes rodam o motor real (`core/wall_modeling.py`) **fora do
Revit**, num Python comum, e existem por um motivo simples: antes deles, a
unica forma de saber se uma alteracao quebrou alguma coisa era abrir o
Revit, selecionar o CAD, escolher Layer/Nivel/altura e esperar a execucao
inteira.

> Ate' 2026-08-24 estes testes carregavam `Script.py` diretamente (ele
> continha toda a logica). Desde entao `Script.py` virou so' um loader que
> baixa `core/wall_modeling.py` do GitHub (ver
> `MinhaAba.tab/MeuPainel.panel/MeuBotao.pushbutton/LOADER_SETUP.md`) - o
> loader usa `System.Net`/`System.Security.Cryptography` de verdade, que
> `revit_stubs.py` nao simula (nao precisa: nada disso e' logica de
> modulacao). `load_script.py` foi repontado para importar
> `core/wall_modeling.py` diretamente, que e' onde a logica testada aqui
> realmente vive hoje.

## Como rodar

```bash
python3 tests/run_tests.py
```

Sem dependencias externas.

## Como funciona

`revit_stubs.py` registra dubles das APIs que o script importa:

- **Geometria de verdade** (`XYZ`, `Line`, `Transform`): as contas sao
  reais, entao os testes de pareamento de linhas, grafo de encontros e
  modulacao exercitam a matematica do script - nao um mock que sempre
  concorda.
- **Resto da API do Revit**: objetos inertes, suficientes para o modulo
  ser importado e para as funcoes de realce/transacao rodarem sem erro.
- **WinForms/Drawing**: controles falsos que guardam propriedades e a
  arvore de `Controls`, permitindo CONSTRUIR cada janela e conferir a
  estrutura dela (abas, colunas, botoes, validacao) sem uma tela.

`load_script.py` importa o `core/wall_modeling.py` com esses dubles no lugar.

## O que esta coberto

| Area | Exemplos |
|---|---|
| Deteccao de paredes | par de linhas vira eixo no meio; espessura fora da tolerancia e' descartada |
| Grafo de encontros | canto L e' UM no'; cruz de 4 pontas e' X; ponta no meio e' T; parede continua quebrada em duas ainda e' T |
| Solver de blocos | canto L gera 2 pecas amarradas; **nenhuma topologia pode gerar colisao na mesma fiada** (varredura de comprimentos) |
| Pipeline parede a parede | ordem geometrica (horizontais cima->baixo/esquerda->direita, depois verticais esquerda->direita/baixo->cima); ajuste so' aceito depois de o solver RE-LANCAR os blocos; a analise nao mexe no estado do chamador |
| Regra #1 (nunca aumentar a parede) | plano com fronteira fora do eixo e' recusado; validacao final reprova crescimento; `apply_axis_opening_fix` recusa antes de tocar no modelo |
| Regras de modulacao | **nao ha' mais regra de digito para paredes** (111cm e 129cm passam); largura de abertura ainda em 1/6/9; pilarete fecha pela aritmetica das juntas; layout de pilarete com juntas |
| Interface | as tres janelas montam; validacao bloqueia Executar; memoria da execucao anterior; abas do resultado |
| Regressoes | cor do realce (Revit x WinForms), log com acento, intervalos duplicados de meio de parede |

Ao mexer no script, rode a suite antes de commitar - varios dos testes
acima nasceram de bugs reais encontrados por eles.
