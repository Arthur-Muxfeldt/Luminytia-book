# Livro da Aurora

Conteúdo customizado (homebrew) para o **[Aurora Builder](https://aurorabuilder.com/)** — criador de fichas de D&D 5e.

Este repositório reúne itens, raças, classes e magias personalizadas do mundo de **Luminytia**, no formato XML que o Aurora Builder entende.

## Como usar no Aurora Builder

1. Abra o Aurora Builder.
2. Vá em **Additional Content**.
3. Adicione a URL do índice deste repositório:

   ```
   https://raw.githubusercontent.com/Arthur-Muxfeldt/Luminytia-book/main/livro-da-aurora.index
   ```

4. O Aurora vai baixar automaticamente todos os arquivos listados no índice.

> Alternativa manual: baixe os arquivos `.xml` e coloque na pasta
> `Documentos\5e Character Builder\custom\user`.

## Estrutura

```
livro-da-aurora.index   → índice que o Aurora carrega (lista os arquivos)
itens/itens.xml         → itens mágicos e equipamentos
racas/racas.xml         → raças e sub-raças
classes/classes.xml     → arquétipos / subclasses
magias/magias.xml       → magias
```

## Como adicionar conteúdo novo

1. Edite/crie o `.xml` na pasta correspondente.
2. Se for um arquivo novo, adicione ele em **duas partes** do `livro-da-aurora.index`:
   - dentro de `<update>` (para o Aurora saber baixar);
   - dentro de `<index>` (para o Aurora saber carregar).
3. **Aumente o número da versão** em `<update version="...">` — é assim que o Aurora detecta que há atualização.
4. Cada `<element>` precisa de um `id` **único** (convenção: `ID_TIPO_NOME`).
