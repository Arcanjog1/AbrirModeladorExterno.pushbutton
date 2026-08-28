# Modulacao Automatica (pyRevit) - instrucoes para o Claude Code

## Idioma

Sempre responder ao usuario em portugues do Brasil (pt-BR), em toda
sessao futura deste projeto - independente do idioma usado na pergunta.

## Merge direto na main

O usuario autorizou (2026-08-26): correcoes/commits feitos em branches
`claude/...` podem ser mesclados DIRETO na `main` (merge commit local +
`git push origin main`), sem precisar abrir Pull Request nem esperar
aprovacao. Isso vale para toda sessao futura deste projeto, nao so' a
que recebeu o pedido.

Antes de mesclar:
- `git fetch origin main` + garantir que a branch local `main` esta'
  atualizada (`git pull`/fast-forward) antes do merge.
- Rodar a suite de testes (`python3 -m pytest tests/test_script.py -q`,
  instalando `pytest` se necessario) e so' empurrar se os testes
  passarem.
- Resolver qualquer conflito de merge antes de dar push; se o conflito
  for em logica (nao so' trivial), avisar o usuario antes de decidir.

So' NAO mesclar direto (voltar a pedir/abrir PR) se o usuario disser
explicitamente o contrario numa sessao futura.

## Documentacao da API RevitAPI

Sempre que precisar consultar a API do Revit (classes, metodos, propriedades,
namespaces do RevitAPI), pesquisar no site https://www.revitapidocs.com/2027/
antes de responder ou implementar.

## Atualizacao obrigatoria das regras de modulacao

Sempre que o usuario fizer uma correcao, um ajuste, uma observacao ou
definir uma nova regra relacionada a' modulacao dos blocos, essa
informacao e' considerada uma ATUALIZACAO OFICIAL das regras do projeto.

Depois de implementar ou analisar a correcao pedida, a regra
correspondente DEVE ser adicionada ou atualizada no arquivo:

`REGRAS_MODULACAO_BLOCOS.md`

Esse arquivo e' a fonte unica de verdade e vive no repositorio
`MeuBotao.pushbutton`, em `nuvem/REGRAS_MODULACAO_BLOCOS.md`. Este
repositorio mantem uma copia do motor (`nuvem/core/`), entao a regra deve
ser registrada la' - nunca so' aqui e nunca duplicada em outro arquivo.

### Procedimento obrigatorio

1. Identificar toda correcao ou nova orientacao do usuario relacionada
   a' modulacao.
2. Verificar se essa regra ja' existe no `REGRAS_MODULACAO_BLOCOS.md`.
3. Se nao existir, adicionar a nova regra de forma clara e objetiva.
4. Se ja' existir, atualizar a regra existente para refletir corretamente
   a orientacao mais recente do usuario.
5. Evitar regras duplicadas ou contraditorias.
6. Em caso de conflito com uma regra anterior, a orientacao mais recente
   do usuario tem prioridade.
7. Antes de qualquer alteracao futura na logica de modulacao, consultar
   o `REGRAS_MODULACAO_BLOCOS.md` e garantir que todas as regras e
   correcoes ja' definidas sejam respeitadas.

### Regra fundamental

Nenhuma correcao feita pelo usuario sobre a modulacao dos blocos pode
ficar apenas na conversa ou apenas no codigo. Toda correcao relevante
deve ser registrada permanentemente no `REGRAS_MODULACAO_BLOCOS.md`,
para que nao seja esquecida nem perdida em alteracoes futuras do sistema.
