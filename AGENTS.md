# Modulacao Automatica (pyRevit) - instrucoes para o Codex

## Merge direto na main

O usuario autorizou (2026-08-26): correcoes/commits feitos em branches
`Codex/...` podem ser mesclados DIRETO na `main` (merge commit local +
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
