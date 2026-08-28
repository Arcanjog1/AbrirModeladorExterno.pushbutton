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
cache. O modelador externo nao baixa nem importa nada de outro `.pushbutton`;
as pequenas funcoes compartilhadas vivem duplicadas em `nuvem/`.

O download normal é um único arquivo ZIP da revisão pública do GitHub, extraído
atomicamente no cache. Isso evita o limite da API pública que ocorria quando o
loader fazia uma requisição por arquivo; em repositório público, a primeira
execução não exige token apenas pela quantidade de arquivos.

## Senha de acesso (repositório privado — 2026-08-28)

Com o repositório privado, o download exige um token do GitHub — mas o
usuário **não digita token nenhum**: digita apenas uma **senha**, uma vez
por computador. O PAT de leitura do mantenedor viaja **cifrado** dentro do
`script.py` (constante `TOKEN_CIFRADO`, ou o arquivo `token_cifrado.dat`
ao lado dele, que tem prioridade), e a senha é o que o abre. Depois disso o
token decifrado fica salvo com DPAPI em
`%LOCALAPPDATA%\AbrirModeladorExternoPushbutton\token.dat` e nada mais é
perguntado.

Para gerar/trocar a linha cifrada:

```bash
python3 ferramentas/gerar_token_cifrado.py          # gera o blob MB1$...
python3 ferramentas/gerar_token_cifrado.py --verificar   # confere um blob
```

O **mesmo** blob serve para os dois botões, desde que o token tenha
`Contents: Read-only` nos dois repositórios — mas cada botão guarda seu
próprio token salvo, então a senha é pedida uma vez em cada.

Limite honesto: quem tiver o arquivo **e** a senha consegue extrair o
token (a senha é um cadeado, não um cofre). Por isso o PAT tem que ser
fine-grained, só de leitura, só nesses dois repositórios. O passo a passo
completo (gerar o PAT no GitHub, cifrar, distribuir, trocar) está em
`nuvem/LOADER_SETUP.md` do repositório `MeuBotao.pushbutton`.

Enquanto `TOKEN_CIFRADO` estiver vazio e não houver `token_cifrado.dat`, o
loader se comporta como antes (download anônimo).
