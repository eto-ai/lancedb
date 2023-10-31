# LanceDB Python API Reference

## Installation

```shell
pip install lancedb
```

## Connection

::: lancedb.connect

::: lancedb.db.DBConnection

## Table

::: lancedb.table.Table

## Querying

::: lancedb.query.Query

::: lancedb.query.LanceQueryBuilder

## Embeddings

::: lancedb.embeddings.registry.EmbeddingFunctionRegistry

::: lancedb.embeddings.base.EmbeddingFunction

::: lancedb.embeddings.base.TextEmbeddingFunction

::: lancedb.embeddings.sentence_transformers.SentenceTransformerEmbeddings

::: lancedb.embeddings.openai.OpenAIEmbeddings

::: lancedb.embeddings.open_clip.OpenClipEmbeddings

::: lancedb.embeddings.with_embeddings

## Context

::: lancedb.context.contextualize

::: lancedb.context.Contextualizer

## Full text search

::: lancedb.fts.create_index

::: lancedb.fts.populate_index

::: lancedb.fts.search_index

## Utilities

::: lancedb.schema.vector

## Integrations

### Pydantic

::: lancedb.pydantic.pydantic_to_schema

::: lancedb.pydantic.vector

::: lancedb.pydantic.LanceModel
