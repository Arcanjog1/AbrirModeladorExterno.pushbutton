# Destino das alteracoes no GitHub

**Mudou em 2026-08-27:** nao existe mais um repositorio unico. Cada
`.pushbutton` e' um repositorio **independente**, com o conteudo do botao na
**raiz** do repo - nao mais sob `MinhaAba.tab/MeuPainel.panel/...`.

| pasta local | repositorio |
|---|---|
| `MinhaAba.tab/MeuPainel.panel/MeuBotao.pushbutton/` | <https://github.com/Arcanjog1/MeuBotao.pushbutton> |
| `MinhaAba.tab/MeuPainel.panel/AbrirModeladorExterno.pushbutton/` | <https://github.com/Arcanjog1/AbrirModeladorExterno.pushbutton> |

O antigo `Arcanjog1/ModulacaoAutomatica`, que reunia os dois sob
`MinhaAba.tab/MeuPainel.panel/`, foi desativado.

## Como o mapeamento funciona

A pasta local precisa manter a arvore `.tab / .panel / .pushbutton`, porque e'
assim que o pyRevit descobre os botoes. Ja o repositorio de cada botao tem o
conteudo DAQUELE botao na raiz:

```
MeuBotao.pushbutton/   (local)          raiz do repo MeuBotao.pushbutton
├── Script.py                     ->    ├── Script.py
├── nuvem/                              ├── nuvem/
└── tests/                              └── tests/
```

Ou seja: **a raiz do repositorio corresponde ao INTERIOR da pasta
`.pushbutton`**, nao a raiz de `Scripts.extension`. Por isso cada pasta
`.pushbutton` e' seu proprio clone git, com seu proprio `origin` - nao da'
para empurrar as duas a partir de um repositorio unico por fora.

## Observacoes

- **Nada e' compartilhado entre os dois repos.** Cada um carrega sua propria
  copia de `nuvem/core/` (o motor) e de `tests/`. Isso e' deliberado - ver a
  decisao "pushbuttons sem vinculo entre si". O preco e' que **toda mudanca
  no motor precisa ir para os DOIS**; se so' um for atualizado, eles divergem
  em silencio. Ja aconteceu: em 2026-08-27 a copia do AbrirModeladorExterno
  estava sem a otimizacao do Solver 18 e ninguem tinha percebido.
- **Como conferir que as duas copias do motor nao divergiram:** rodar
  `python tests/solver_bench.py --fingerprint` nos dois repos. As duas tem
  que devolver a MESMA assinatura sha256 - ela cobre posicao, codigo,
  rotacao e espelhamento de cada peca decidida pelo solver.
- Antes de empurrar, rodar as suites: `python -m pytest tests/test_script.py -q`
  e, no MeuBotao, tambem `python -m pytest nuvem/tests -q`.
- Merge de branches `claude/...` direto na `main` (sem PR) ja' esta'
  autorizado pelo usuario - ver `CLAUDE.md` na raiz da extensao para as
  regras completas (rodar testes antes, resolver conflitos, etc).
- **O token do GitHub e' por botao.** Cada loader guarda o seu em
  `%LOCALAPPDATA%\MeuBotaoPushbutton\` e
  `%LOCALAPPDATA%\AbrirModeladorExternoPushbutton\`. Um unico PAT
  fine-grained com leitura nos dois repositorios atende os dois botoes, mas
  ele e' colado uma vez em cada. Ver
  `MeuBotao.pushbutton/nuvem/LOADER_SETUP.md`.
