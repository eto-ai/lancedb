#  Copyright 2023 LanceDB Developers
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

from __future__ import annotations

from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Literal, Optional, Tuple, Type, Union

import deprecation
import numpy as np
import pyarrow as pa
import pydantic

from . import __version__
from .common import VEC
from .rerankers.base import Reranker
from .rerankers.linear_combination import LinearCombinationReranker
from .util import safe_import_pandas

if TYPE_CHECKING:
    import PIL
    import polars as pl

    from .pydantic import LanceModel
    from .table import Table

pd = safe_import_pandas()


class Query(pydantic.BaseModel):
    """The LanceDB Query

    Attributes
    ----------
    vector : List[float]
        the vector to search for
    filter : Optional[str]
        sql filter to refine the query with, optional
    prefilter : bool
        if True then apply the filter before vector search
    k : int
        top k results to return
    metric : str
        the distance metric between a pair of vectors,

        can support L2 (default), Cosine and Dot.
        [metric definitions][search]
    columns : Optional[List[str]]
        which columns to return in the results
    nprobes : int
        The number of probes used - optional

        - A higher number makes search more accurate but also slower.

        - See discussion in [Querying an ANN Index][querying-an-ann-index] for
          tuning advice.
    refine_factor : Optional[int]
        Refine the results by reading extra elements and re-ranking them in memory.

        - A higher number makes search more accurate but also slower.

        - See discussion in [Querying an ANN Index][querying-an-ann-index] for
          tuning advice.
    """

    vector_column: Optional[str] = None

    # vector to search for
    vector: Union[List[float], List[List[float]]]

    # sql filter to refine the query with
    filter: Optional[str] = None

    # if True then apply the filter before vector search
    prefilter: bool = False

    # top k results to return
    k: int

    # # metrics
    metric: str = "L2"

    # which columns to return in the results
    columns: Optional[Union[List[str], Dict[str, str]]] = None

    # optional query parameters for tuning the results,
    # e.g. `{"nprobes": "10", "refine_factor": "10"}`
    nprobes: int = 10

    # Refine factor.
    refine_factor: Optional[int] = None

    with_row_id: bool = False


class LanceQueryBuilder(ABC):
    """An abstract query builder. Subclasses are defined for vector search,
    full text search, hybrid, and plain SQL filtering.
    """

    @classmethod
    def create(
        cls,
        table: "Table",
        query: Optional[Union[np.ndarray, str, "PIL.Image.Image", Tuple]],
        query_type: str,
        vector_column_name: str,
    ) -> LanceQueryBuilder:
        """
        Create a query builder based on the given query and query type.

        Parameters
        ----------
        table: Table
            The table to query.
        query: Optional[Union[np.ndarray, str, "PIL.Image.Image", Tuple]]
            The query to use. If None, an empty query builder is returned
            which performs simple SQL filtering.
        query_type: str
            The type of query to perform. One of "vector", "fts", "hybrid", or "auto".
            If "auto", the query type is inferred based on the query.
        vector_column_name: str
            The name of the vector column to use for vector search.
        """
        if query is None:
            return LanceEmptyQueryBuilder(table)

        if query_type == "hybrid":
            # hybrid fts and vector query
            return LanceHybridQueryBuilder(table, query, vector_column_name)

        # remember the string query for reranking purpose
        str_query = query if isinstance(query, str) else None

        # convert "auto" query_type to "vector", "fts"
        # or "hybrid" and convert the query to vector if needed
        query, query_type = cls._resolve_query(
            table, query, query_type, vector_column_name
        )

        if query_type == "hybrid":
            return LanceHybridQueryBuilder(table, query, vector_column_name)

        if isinstance(query, str):
            # fts
            return LanceFtsQueryBuilder(table, query)

        if isinstance(query, list):
            query = np.array(query, dtype=np.float32)
        elif isinstance(query, np.ndarray):
            query = query.astype(np.float32)
        else:
            raise TypeError(f"Unsupported query type: {type(query)}")

        return LanceVectorQueryBuilder(table, query, vector_column_name, str_query)

    @classmethod
    def _resolve_query(cls, table, query, query_type, vector_column_name):
        # If query_type is fts, then query must be a string.
        # otherwise raise TypeError
        if query_type == "fts":
            if not isinstance(query, str):
                raise TypeError(f"'fts' queries must be a string: {type(query)}")
            return query, query_type
        elif query_type == "vector":
            query = cls._query_to_vector(table, query, vector_column_name)
            return query, query_type
        elif query_type == "auto":
            if isinstance(query, (list, np.ndarray)):
                return query, "vector"
            if isinstance(query, tuple):
                return query, "hybrid"
            else:
                conf = table.embedding_functions.get(vector_column_name)
                if conf is not None:
                    query = conf.function.compute_query_embeddings_with_retry(query)[0]
                    return query, "vector"
                else:
                    return query, "fts"
        else:
            raise ValueError(
                f"Invalid query_type, must be 'vector', 'fts', or 'auto': {query_type}"
            )

    @classmethod
    def _query_to_vector(cls, table, query, vector_column_name):
        if isinstance(query, (list, np.ndarray)):
            return query
        conf = table.embedding_functions.get(vector_column_name)
        if conf is not None:
            return conf.function.compute_query_embeddings_with_retry(query)[0]
        else:
            msg = f"No embedding function for {vector_column_name}"
            raise ValueError(msg)

    def __init__(self, table: "Table"):
        self._table = table
        self._limit = 10
        self._columns = None
        self._where = None
        self._with_row_id = False

    @deprecation.deprecated(
        deprecated_in="0.3.1",
        removed_in="0.4.0",
        current_version=__version__,
        details="Use to_pandas() instead",
    )
    def to_df(self) -> "pd.DataFrame":
        """
        *Deprecated alias for `to_pandas()`. Please use `to_pandas()` instead.*

        Execute the query and return the results as a pandas DataFrame.
        In addition to the selected columns, LanceDB also returns a vector
        and also the "_distance" column which is the distance between the query
        vector and the returned vector.
        """
        return self.to_pandas()

    def to_pandas(self, flatten: Optional[Union[int, bool]] = None) -> "pd.DataFrame":
        """
        Execute the query and return the results as a pandas DataFrame.
        In addition to the selected columns, LanceDB also returns a vector
        and also the "_distance" column which is the distance between the query
        vector and the returned vector.

        Parameters
        ----------
        flatten: Optional[Union[int, bool]]
            If flatten is True, flatten all nested columns.
            If flatten is an integer, flatten the nested columns up to the
            specified depth.
            If unspecified, do not flatten the nested columns.
        """
        tbl = self.to_arrow()
        if flatten is True:
            while True:
                tbl = tbl.flatten()
                # loop through all columns to check if there is any struct column
                if any(pa.types.is_struct(col.type) for col in tbl.schema):
                    continue
                else:
                    break
        elif isinstance(flatten, int):
            if flatten <= 0:
                raise ValueError(
                    "Please specify a positive integer for flatten or the boolean "
                    "value `True`"
                )
            while flatten > 0:
                tbl = tbl.flatten()
                flatten -= 1
        return tbl.to_pandas()

    @abstractmethod
    def to_arrow(self) -> pa.Table:
        """
        Execute the query and return the results as an
        [Apache Arrow Table](https://arrow.apache.org/docs/python/generated/pyarrow.Table.html#pyarrow.Table).

        In addition to the selected columns, LanceDB also returns a vector
        and also the "_distance" column which is the distance between the query
        vector and the returned vectors.
        """
        raise NotImplementedError

    def to_list(self) -> List[dict]:
        """
        Execute the query and return the results as a list of dictionaries.

        Each list entry is a dictionary with the selected column names as keys,
        or all table columns if `select` is not called. The vector and the "_distance"
        fields are returned whether or not they're explicitly selected.
        """
        return self.to_arrow().to_pylist()

    def to_pydantic(self, model: Type[LanceModel]) -> List[LanceModel]:
        """Return the table as a list of pydantic models.

        Parameters
        ----------
        model: Type[LanceModel]
            The pydantic model to use.

        Returns
        -------
        List[LanceModel]
        """
        return [
            model(**{k: v for k, v in row.items() if k in model.field_names()})
            for row in self.to_arrow().to_pylist()
        ]

    def to_polars(self) -> "pl.DataFrame":
        """
        Execute the query and return the results as a Polars DataFrame.
        In addition to the selected columns, LanceDB also returns a vector
        and also the "_distance" column which is the distance between the query
        vector and the returned vector.
        """
        import polars as pl

        return pl.from_arrow(self.to_arrow())

    def limit(self, limit: Union[int, None]) -> LanceQueryBuilder:
        """Set the maximum number of results to return.

        Parameters
        ----------
        limit: int
            The maximum number of results to return.
            By default the query is limited to the first 10.
            Call this method and pass 0, a negative value,
            or None to remove the limit.
            *WARNING* if you have a large dataset, removing
            the limit can potentially result in reading a
            large amount of data into memory and cause
            out of memory issues.

        Returns
        -------
        LanceQueryBuilder
            The LanceQueryBuilder object.
        """
        if limit is None or limit <= 0:
            self._limit = None
        else:
            self._limit = limit
        return self

    def select(self, columns: Union[list[str], dict[str, str]]) -> LanceQueryBuilder:
        """Set the columns to return.

        Parameters
        ----------
        columns: list of str, or dict of str to str default None
            List of column names to be fetched.
            Or a dictionary of column names to SQL expressions.
            All columns are fetched if None or unspecified.

        Returns
        -------
        LanceQueryBuilder
            The LanceQueryBuilder object.
        """
        if isinstance(columns, list) or isinstance(columns, dict):
            self._columns = columns
        else:
            raise ValueError("columns must be a list or a dictionary")
        return self

    def where(self, where: str, prefilter: bool = False) -> LanceQueryBuilder:
        """Set the where clause.

        Parameters
        ----------
        where: str
            The where clause which is a valid SQL where clause. See
            `Lance filter pushdown <https://lancedb.github.io/lance/read_and_write.html#filter-push-down>`_
            for valid SQL expressions.
        prefilter: bool, default False
            If True, apply the filter before vector search, otherwise the
            filter is applied on the result of vector search.
            This feature is **EXPERIMENTAL** and may be removed and modified
            without warning in the future.

        Returns
        -------
        LanceQueryBuilder
            The LanceQueryBuilder object.
        """
        self._where = where
        self._prefilter = prefilter
        return self

    def with_row_id(self, with_row_id: bool) -> LanceQueryBuilder:
        """Set whether to return row ids.

        Parameters
        ----------
        with_row_id: bool
            If True, return _rowid column in the results.

        Returns
        -------
        LanceQueryBuilder
            The LanceQueryBuilder object.
        """
        self._with_row_id = with_row_id
        return self


class LanceVectorQueryBuilder(LanceQueryBuilder):
    """
    Examples
    --------
    >>> import lancedb
    >>> data = [{"vector": [1.1, 1.2], "b": 2},
    ...         {"vector": [0.5, 1.3], "b": 4},
    ...         {"vector": [0.4, 0.4], "b": 6},
    ...         {"vector": [0.4, 0.4], "b": 10}]
    >>> db = lancedb.connect("./.lancedb")
    >>> table = db.create_table("my_table", data=data)
    >>> (table.search([0.4, 0.4])
    ...       .metric("cosine")
    ...       .where("b < 10")
    ...       .select(["b", "vector"])
    ...       .limit(2)
    ...       .to_pandas())
       b      vector  _distance
    0  6  [0.4, 0.4]        0.0
    """

    def __init__(
        self,
        table: "Table",
        query: Union[np.ndarray, list, "PIL.Image.Image"],
        vector_column: str,
        str_query: Optional[str] = None,
    ):
        super().__init__(table)
        self._query = query
        self._metric = "L2"
        self._nprobes = 20
        self._refine_factor = None
        self._vector_column = vector_column
        self._prefilter = False
        self._reranker = None
        self._str_query = str_query

    def metric(self, metric: Literal["L2", "cosine"]) -> LanceVectorQueryBuilder:
        """Set the distance metric to use.

        Parameters
        ----------
        metric: "L2" or "cosine"
            The distance metric to use. By default "L2" is used.

        Returns
        -------
        LanceVectorQueryBuilder
            The LanceQueryBuilder object.
        """
        self._metric = metric
        return self

    def nprobes(self, nprobes: int) -> LanceVectorQueryBuilder:
        """Set the number of probes to use.

        Higher values will yield better recall (more likely to find vectors if
        they exist) at the expense of latency.

        See discussion in [Querying an ANN Index][querying-an-ann-index] for
        tuning advice.

        Parameters
        ----------
        nprobes: int
            The number of probes to use.

        Returns
        -------
        LanceVectorQueryBuilder
            The LanceQueryBuilder object.
        """
        self._nprobes = nprobes
        return self

    def refine_factor(self, refine_factor: int) -> LanceVectorQueryBuilder:
        """Set the refine factor to use, increasing the number of vectors sampled.

        As an example, a refine factor of 2 will sample 2x as many vectors as
        requested, re-ranks them, and returns the top half most relevant results.

        See discussion in [Querying an ANN Index][querying-an-ann-index] for
        tuning advice.

        Parameters
        ----------
        refine_factor: int
            The refine factor to use.

        Returns
        -------
        LanceVectorQueryBuilder
            The LanceQueryBuilder object.
        """
        self._refine_factor = refine_factor
        return self

    def to_arrow(self) -> pa.Table:
        """
        Execute the query and return the results as an
        [Apache Arrow Table](https://arrow.apache.org/docs/python/generated/pyarrow.Table.html#pyarrow.Table).

        In addition to the selected columns, LanceDB also returns a vector
        and also the "_distance" column which is the distance between the query
        vector and the returned vectors.
        """
        vector = self._query if isinstance(self._query, list) else self._query.tolist()
        if isinstance(vector[0], np.ndarray):
            vector = [v.tolist() for v in vector]
        query = Query(
            vector=vector,
            filter=self._where,
            prefilter=self._prefilter,
            k=self._limit,
            metric=self._metric,
            columns=self._columns,
            nprobes=self._nprobes,
            refine_factor=self._refine_factor,
            vector_column=self._vector_column,
            with_row_id=self._with_row_id,
        )
        result_set = self._table._execute_query(query)
        if self._reranker is not None:
            result_set = self._reranker.rerank_vector(self._str_query, result_set)

        return result_set

    def where(self, where: str, prefilter: bool = False) -> LanceVectorQueryBuilder:
        """Set the where clause.

        Parameters
        ----------
        where: str
            The where clause which is a valid SQL where clause. See
            `Lance filter pushdown <https://lancedb.github.io/lance/read_and_write.html#filter-push-down>`_
            for valid SQL expressions.
        prefilter: bool, default False
            If True, apply the filter before vector search, otherwise the
            filter is applied on the result of vector search.
            This feature is **EXPERIMENTAL** and may be removed and modified
            without warning in the future.

        Returns
        -------
        LanceQueryBuilder
            The LanceQueryBuilder object.
        """
        self._where = where
        self._prefilter = prefilter
        return self

    def rerank(
        self, reranker: Reranker, query: Optional[str] = None
    ) -> LanceVectorQueryBuilder:
        """Rerank the results using the specified reranker.

        Parameters
        ----------
        reranker: Reranker
            The reranker to use.

        query: Optional[str]
            The query to use for reranking. This needs to be specified explicitly here
            as the query used for vector search may already be vectorized and the
            reranker requires a string query.
            This is only required if the query used for vector search is not a string.
            Note: This doesn't yet support the case where the query is multimodal or a
            list of vectors.

        Returns
        -------
        LanceVectorQueryBuilder
            The LanceQueryBuilder object.
        """
        self._reranker = reranker
        if self._str_query is None and query is None:
            raise ValueError(
                """
                The query used for vector search is not a string.
                In this case, the reranker query needs to be specified explicitly.
                """
            )
        self._str_query = query if query is not None else self._str_query
        return self


class LanceFtsQueryBuilder(LanceQueryBuilder):
    """A builder for full text search for LanceDB."""

    def __init__(self, table: "Table", query: str):
        super().__init__(table)
        self._query = query
        self._phrase_query = False
        self._reranker = None

    def phrase_query(self, phrase_query: bool = True) -> LanceFtsQueryBuilder:
        """Set whether to use phrase query.

        Parameters
        ----------
        phrase_query: bool, default True
            If True, then the query will be wrapped in quotes and
            double quotes replaced by single quotes.

        Returns
        -------
        LanceFtsQueryBuilder
            The LanceFtsQueryBuilder object.
        """
        self._phrase_query = phrase_query
        return self

    def to_arrow(self) -> pa.Table:
        try:
            import tantivy
        except ImportError:
            raise ImportError(
                "Please install tantivy-py `pip install tantivy` to use the full text search feature."  # noqa: E501
            )

        from .fts import search_index

        # get the index path
        index_path = self._table._get_fts_index_path()
        # check if the index exist
        if not Path(index_path).exists():
            raise FileNotFoundError(
                "Fts index does not exist. "
                "Please first call table.create_fts_index(['<field_names>']) to "
                "create the fts index."
            )
        # open the index
        index = tantivy.Index.open(index_path)
        # get the scores and doc ids
        query = self._query
        if self._phrase_query:
            query = query.replace('"', "'")
            query = f'"{query}"'
        row_ids, scores = search_index(index, query, self._limit)
        if len(row_ids) == 0:
            empty_schema = pa.schema([pa.field("score", pa.float32())])
            return pa.Table.from_pylist([], schema=empty_schema)
        scores = pa.array(scores)
        output_tbl = self._table.to_lance().take(row_ids, columns=self._columns)
        output_tbl = output_tbl.append_column("score", scores)
        # this needs to match vector search results which are uint64
        row_ids = pa.array(row_ids, type=pa.uint64())

        if self._where is not None:
            tmp_name = "__lancedb__duckdb__indexer__"
            output_tbl = output_tbl.append_column(
                tmp_name, pa.array(range(len(output_tbl)))
            )
            try:
                # TODO would be great to have Substrait generate pyarrow compute
                # expressions or conversely have pyarrow support SQL expressions
                # using Substrait
                import duckdb

                indexer = duckdb.sql(
                    f"SELECT {tmp_name} FROM output_tbl WHERE {self._where}"
                ).to_arrow_table()[tmp_name]
                output_tbl = output_tbl.take(indexer).drop([tmp_name])
                row_ids = row_ids.take(indexer)

            except ImportError:
                import tempfile

                import lance

                # TODO Use "memory://" instead once that's supported
                with tempfile.TemporaryDirectory() as tmp:
                    ds = lance.write_dataset(output_tbl, tmp)
                    output_tbl = ds.to_table(filter=self._where)
                    indexer = output_tbl[tmp_name]
                    row_ids = row_ids.take(indexer)
                    output_tbl = output_tbl.drop([tmp_name])

        if self._with_row_id:
            output_tbl = output_tbl.append_column("_rowid", row_ids)

        if self._reranker is not None:
            output_tbl = self._reranker.rerank_fts(self._query, output_tbl)
        return output_tbl

    def rerank(self, reranker: Reranker) -> LanceFtsQueryBuilder:
        """Rerank the results using the specified reranker.

        Parameters
        ----------
        reranker: Reranker
            The reranker to use.

        Returns
        -------
        LanceFtsQueryBuilder
            The LanceQueryBuilder object.
        """
        self._reranker = reranker
        return self


class LanceEmptyQueryBuilder(LanceQueryBuilder):
    def to_arrow(self) -> pa.Table:
        ds = self._table.to_lance()
        return ds.to_table(
            columns=self._columns,
            filter=self._where,
            limit=self._limit,
        )


class LanceHybridQueryBuilder(LanceQueryBuilder):
    """
    A query builder that performs hybrid vector and full text search.
    Results are combined and reranked based on the specified reranker.
    By default, the results are reranked using the LinearCombinationReranker.

    To make the vector and fts results comparable, the scores are normalized.
    Instead of normalizing scores, the `normalize` parameter can be set to "rank"
    in the `rerank` method to convert the scores to ranks and then normalize them.
    """

    def __init__(self, table: "Table", query: str, vector_column: str):
        super().__init__(table)
        self._validate_fts_index()
        vector_query, fts_query = self._validate_query(query)
        self._fts_query = LanceFtsQueryBuilder(table, fts_query)
        vector_query = self._query_to_vector(table, vector_query, vector_column)
        self._vector_query = LanceVectorQueryBuilder(table, vector_query, vector_column)
        self._norm = "score"
        self._reranker = LinearCombinationReranker(weight=0.7, fill=1.0)

    def _validate_fts_index(self):
        if self._table._get_fts_index_path() is None:
            raise ValueError(
                "Please create a full-text search index " "to perform hybrid search."
            )

    def _validate_query(self, query):
        # Temp hack to support vectorized queries for hybrid search
        if isinstance(query, str):
            return query, query
        elif isinstance(query, tuple):
            if len(query) != 2:
                raise ValueError(
                    "The query must be a tuple of (vector_query, fts_query)."
                )
            if not isinstance(query[0], (list, np.ndarray, pa.Array, pa.ChunkedArray)):
                raise ValueError(f"The vector query must be one of {VEC}.")
            if not isinstance(query[1], str):
                raise ValueError("The fts query must be a string.")
            return query[0], query[1]
        else:
            raise ValueError(
                "The query must be either a string or a tuple of (vector, string)."
            )

    def to_arrow(self) -> pa.Table:
        with ThreadPoolExecutor() as executor:
            fts_future = executor.submit(self._fts_query.with_row_id(True).to_arrow)
            vector_future = executor.submit(
                self._vector_query.with_row_id(True).to_arrow
            )
            fts_results = fts_future.result()
            vector_results = vector_future.result()

        # convert to ranks first if needed
        if self._norm == "rank":
            vector_results = self._rank(vector_results, "_distance")
            fts_results = self._rank(fts_results, "score")
        # normalize the scores to be between 0 and 1, 0 being most relevant
        vector_results = self._normalize_scores(vector_results, "_distance")

        # In fts higher scores represent relevance. Not inverting them here as
        # rerankers might need to preserve this score to support `return_score="all"`
        fts_results = self._normalize_scores(fts_results, "score")

        results = self._reranker.rerank_hybrid(
            self._fts_query._query, vector_results, fts_results
        )

        if not isinstance(results, pa.Table):  # Enforce type
            raise TypeError(
                f"rerank_hybrid must return a pyarrow.Table, got {type(results)}"
            )

        # apply limit after reranking
        results = results.slice(length=self._limit)

        if not self._with_row_id:
            results = results.drop(["_rowid"])
        return results

    def _rank(self, results: pa.Table, column: str, ascending: bool = True):
        if len(results) == 0:
            return results
        # Get the _score column from results
        scores = results.column(column).to_numpy()
        sort_indices = np.argsort(scores)
        if not ascending:
            sort_indices = sort_indices[::-1]
        ranks = np.empty_like(sort_indices)
        ranks[sort_indices] = np.arange(len(scores)) + 1
        # replace the _score column with the ranks
        _score_idx = results.column_names.index(column)
        results = results.set_column(
            _score_idx, column, pa.array(ranks, type=pa.float32())
        )
        return results

    def _normalize_scores(self, results: pa.Table, column: str, invert=False):
        if len(results) == 0:
            return results
        # Get the _score column from results
        scores = results.column(column).to_numpy()
        # normalize the scores by subtracting the min and dividing by the max
        max, min = np.max(scores), np.min(scores)
        if np.isclose(max, min):
            rng = max
        else:
            rng = max - min
        scores = (scores - min) / rng
        if invert:
            scores = 1 - scores
        # replace the _score column with the ranks
        _score_idx = results.column_names.index(column)
        results = results.set_column(
            _score_idx, column, pa.array(scores, type=pa.float32())
        )
        return results

    def rerank(
        self,
        normalize="score",
        reranker: Reranker = LinearCombinationReranker(weight=0.7, fill=1.0),
    ) -> LanceHybridQueryBuilder:
        """
        Rerank the hybrid search results using the specified reranker. The reranker
        must be an instance of Reranker class.

        Parameters
        ----------
        normalize: str, default "score"
            The method to normalize the scores. Can be "rank" or "score". If "rank",
            the scores are converted to ranks and then normalized. If "score", the
            scores are normalized directly.
        reranker: Reranker, default LinearCombinationReranker(weight=0.7, fill=1.0)
            The reranker to use. Must be an instance of Reranker class.
        Returns
        -------
        LanceHybridQueryBuilder
            The LanceHybridQueryBuilder object.
        """
        if normalize not in ["rank", "score"]:
            raise ValueError("normalize must be 'rank' or 'score'.")
        if reranker and not isinstance(reranker, Reranker):
            raise ValueError("reranker must be an instance of Reranker class.")

        self._norm = normalize
        self._reranker = reranker

        return self

    def limit(self, limit: int) -> LanceHybridQueryBuilder:
        """
        Set the maximum number of results to return for both vector and fts search
        components.

        Parameters
        ----------
        limit: int
            The maximum number of results to return.

        Returns
        -------
        LanceHybridQueryBuilder
            The LanceHybridQueryBuilder object.
        """
        self._vector_query.limit(limit)
        self._fts_query.limit(limit)
        self._limit = limit

        return self

    def select(self, columns: list) -> LanceHybridQueryBuilder:
        """
        Set the columns to return for both vector and fts search.

        Parameters
        ----------
        columns: list
            The columns to return.

        Returns
        -------
        LanceHybridQueryBuilder
            The LanceHybridQueryBuilder object.
        """
        self._vector_query.select(columns)
        self._fts_query.select(columns)
        return self

    def where(self, where: str, prefilter: bool = False) -> LanceHybridQueryBuilder:
        """
        Set the where clause for both vector and fts search.

        Parameters
        ----------
        where: str
            The where clause which is a valid SQL where clause. See
            `Lance filter pushdown <https://lancedb.github.io/lance/read_and_write.html#filter-push-down>`_
            for valid SQL expressions.

        prefilter: bool, default False
            If True, apply the filter before vector search, otherwise the
            filter is applied on the result of vector search.

        Returns
        -------
        LanceHybridQueryBuilder
            The LanceHybridQueryBuilder object.
        """

        self._vector_query.where(where, prefilter=prefilter)
        self._fts_query.where(where)
        return self

    def metric(self, metric: Literal["L2", "cosine"]) -> LanceHybridQueryBuilder:
        """
        Set the distance metric to use for vector search.

        Parameters
        ----------
        metric: "L2" or "cosine"
            The distance metric to use. By default "L2" is used.

        Returns
        -------
        LanceHybridQueryBuilder
            The LanceHybridQueryBuilder object.
        """
        self._vector_query.metric(metric)
        return self

    def nprobes(self, nprobes: int) -> LanceHybridQueryBuilder:
        """
        Set the number of probes to use for vector search.

        Higher values will yield better recall (more likely to find vectors if
        they exist) at the expense of latency.

        Parameters
        ----------
        nprobes: int
            The number of probes to use.

        Returns
        -------
        LanceHybridQueryBuilder
            The LanceHybridQueryBuilder object.
        """
        self._vector_query.nprobes(nprobes)
        return self

    def refine_factor(self, refine_factor: int) -> LanceHybridQueryBuilder:
        """
        Refine the vector search results by reading extra elements and
        re-ranking them in memory.

        Parameters
        ----------
        refine_factor: int
            The refine factor to use.

        Returns
        -------
        LanceHybridQueryBuilder
            The LanceHybridQueryBuilder object.
        """
        self._vector_query.refine_factor(refine_factor)
        return self
