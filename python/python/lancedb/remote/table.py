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

from datetime import timedelta
import logging
from functools import cached_property
from typing import Dict, Iterable, List, Optional, Union, Literal

from lancedb.index import FTS, BTree, Bitmap, HnswPq, HnswSq, IvfPq, LabelList
from lancedb.remote.db import LOOP
import pyarrow as pa

from lancedb.common import DATA, VEC, VECTOR_COLUMN_NAME
from lancedb.merge import LanceMergeInsertBuilder
from lancedb.embeddings import EmbeddingFunctionRegistry

from ..query import LanceVectorQueryBuilder, LanceQueryBuilder
from ..table import AsyncTable, Query, Table


class RemoteTable(Table):
    def __init__(
        self,
        table: AsyncTable,
        db_name: str,
    ):
        self._table = table
        self.db_name = db_name

    @property
    def name(self) -> str:
        """The name of the table"""
        return self._table.name

    def __repr__(self) -> str:
        return f"RemoteTable({self.db_name}.{self.name})"

    def __len__(self) -> int:
        self.count_rows(None)

    @property
    def schema(self) -> pa.Schema:
        """The [Arrow Schema](https://arrow.apache.org/docs/python/api/datatypes.html#)
        of this Table

        """
        return LOOP.run(self._table.schema())

    @property
    def version(self) -> int:
        """Get the current version of the table"""
        return LOOP.run(self._table.version())

    @cached_property
    def embedding_functions(self) -> dict:
        """
        Get the embedding functions for the table

        Returns
        -------
        funcs: dict
            A mapping of the vector column to the embedding function
            or empty dict if not configured.
        """
        return EmbeddingFunctionRegistry.get_instance().parse_functions(
            self.schema.metadata
        )

    def list_versions(self):
        """List all versions of the table"""
        return self._loop.run_until_complete(self._table.list_versions())

    def to_arrow(self) -> pa.Table:
        """to_arrow() is not yet supported on LanceDB cloud."""
        raise NotImplementedError("to_arrow() is not yet supported on LanceDB cloud.")

    def to_pandas(self):
        """to_pandas() is not yet supported on LanceDB cloud."""
        return NotImplementedError("to_pandas() is not yet supported on LanceDB cloud.")

    def checkout(self, version):
        return self._loop.run_until_complete(self._table.checkout(version))

    def checkout_latest(self):
        return self._loop.run_until_complete(self._table.checkout_latest())

    def list_indices(self):
        """List all the indices on the table"""
        return LOOP.run(self._table.list_indices())

    def index_stats(self, index_uuid: str):
        """List all the stats of a specified index"""
        return LOOP.run(self._table.index_stats(index_uuid))

    def create_scalar_index(
        self,
        column: str,
        index_type: Literal["BTREE", "BITMAP", "LABEL_LIST", "scalar"] = "scalar",
        *,
        replace: bool = False,
    ):
        """Creates a scalar index
        Parameters
        ----------
        column : str
            The column to be indexed.  Must be a boolean, integer, float,
            or string column.
        index_type : str
            The index type of the scalar index. Must be "scalar" (BTREE),
            "BTREE", "BITMAP", or "LABEL_LIST",
        replace : bool
            If True, replace the existing index with the new one.
        """
        if index_type == "scalar" or index_type == "BTREE":
            config = BTree()
        elif index_type == "BITMAP":
            config = Bitmap()
        elif index_type == "LABEL_LIST":
            config = LabelList()
        else:
            raise ValueError(f"Unknown index type: {index_type}")

        LOOP.run(self._table.create_index(column, config=config, replace=replace))

    def create_fts_index(
        self,
        column: str,
        *,
        replace: bool = False,
        with_position: bool = True,
    ):
        config = FTS(with_position=with_position)
        LOOP.run(self._table.create_index(column, config=config, replace=replace))

    def create_index(
        self,
        metric="L2",
        vector_column_name: str = VECTOR_COLUMN_NAME,
        index_cache_size: Optional[int] = None,
        num_partitions: Optional[int] = None,
        num_sub_vectors: Optional[int] = None,
        replace: Optional[bool] = None,
        accelerator: Optional[str] = None,
        index_type="vector",
    ):
        """Create an index on the table.
        Currently, the only parameters that matter are
        the metric and the vector column name.

        Parameters
        ----------
        metric : str
            The metric to use for the index. Default is "L2".
        vector_column_name : str
            The name of the vector column. Default is "vector".

        Examples
        --------
        >>> import lancedb
        >>> import uuid
        >>> from lancedb.schema import vector
        >>> db = lancedb.connect("db://...", api_key="...", # doctest: +SKIP
        ...                      region="...") # doctest: +SKIP
        >>> table_name = uuid.uuid4().hex
        >>> schema = pa.schema(
        ...     [
        ...             pa.field("id", pa.uint32(), False),
        ...            pa.field("vector", vector(128), False),
        ...             pa.field("s", pa.string(), False),
        ...     ]
        ... )
        >>> table = db.create_table( # doctest: +SKIP
        ...     table_name, # doctest: +SKIP
        ...     schema=schema, # doctest: +SKIP
        ... )
        >>> table.create_index("L2", "vector") # doctest: +SKIP
        """

        if num_partitions is not None:
            logging.warning(
                "num_partitions is not supported on LanceDB cloud."
                "This parameter will be tuned automatically."
            )
        if num_sub_vectors is not None:
            logging.warning(
                "num_sub_vectors is not supported on LanceDB cloud."
                "This parameter will be tuned automatically."
            )
        if accelerator is not None:
            logging.warning(
                "GPU accelerator is not yet supported on LanceDB cloud."
                "If you have 100M+ vectors to index,"
                "please contact us at contact@lancedb.com"
            )
        if replace is not None:
            logging.warning(
                "replace is not supported on LanceDB cloud."
                "Existing indexes will always be replaced."
            )

        index_type = index_type.upper()
        if index_type == "VECTOR" or index_type == "IVF_PQ":
            config = IvfPq(distance_type=metric)
        elif index_type == "IVF_HNSW_PQ":
            config = HnswPq(distance_type=metric)
        elif index_type == "IVF_HNSW_SQ":
            config = HnswSq(distance_type=metric)
        else:
            raise ValueError(
                f"Unknown vector index type: {index_type}. Valid options are"
                " 'IVF_PQ', 'IVF_HNSW_PQ', 'IVF_HNSW_SQ'"
            )

        LOOP.run(self._table.create_index(vector_column_name, config=config))

    def add(
        self,
        data: DATA,
        mode: str = "append",
        on_bad_vectors: str = "error",
        fill_value: float = 0.0,
    ) -> int:
        """Add more data to the [Table](Table). It has the same API signature as
        the OSS version.

        Parameters
        ----------
        data: DATA
            The data to insert into the table. Acceptable types are:

            - dict or list-of-dict

            - pandas.DataFrame

            - pyarrow.Table or pyarrow.RecordBatch
        mode: str
            The mode to use when writing the data. Valid values are
            "append" and "overwrite".
        on_bad_vectors: str, default "error"
            What to do if any of the vectors are not the same size or contains NaNs.
            One of "error", "drop", "fill".
        fill_value: float, default 0.
            The value to use when filling vectors. Only used if on_bad_vectors="fill".

        """
        LOOP.run(
            self._table.add(
                data, mode=mode, on_bad_vectors=on_bad_vectors, fill_value=fill_value
            )
        )

    def search(
        self,
        query: Union[VEC, str] = None,
        vector_column_name: Optional[str] = None,
        query_type="auto",
        fts_columns: Optional[Union[str, List[str]]] = None,
        fast_search: bool = False,
    ) -> LanceVectorQueryBuilder:
        """Create a search query to find the nearest neighbors
        of the given query vector. We currently support [vector search][search]

        All query options are defined in [Query][lancedb.query.Query].

        Examples
        --------
        >>> import lancedb
        >>> db = lancedb.connect("db://...", api_key="...", # doctest: +SKIP
        ...                      region="...") # doctest: +SKIP
        >>> data = [
        ...    {"original_width": 100, "caption": "bar", "vector": [0.1, 2.3, 4.5]},
        ...    {"original_width": 2000, "caption": "foo",  "vector": [0.5, 3.4, 1.3]},
        ...    {"original_width": 3000, "caption": "test", "vector": [0.3, 6.2, 2.6]}
        ... ]
        >>> table = db.create_table("my_table", data) # doctest: +SKIP
        >>> query = [0.4, 1.4, 2.4]
        >>> (table.search(query) # doctest: +SKIP
        ...     .where("original_width > 1000", prefilter=True) # doctest: +SKIP
        ...     .select(["caption", "original_width"]) # doctest: +SKIP
        ...     .limit(2) # doctest: +SKIP
        ...     .to_pandas()) # doctest: +SKIP
          caption  original_width           vector  _distance # doctest: +SKIP
        0     foo            2000  [0.5, 3.4, 1.3]   5.220000 # doctest: +SKIP
        1    test            3000  [0.3, 6.2, 2.6]  23.089996 # doctest: +SKIP

        Parameters
        ----------
        query: list/np.ndarray/str/PIL.Image.Image, default None
            The targetted vector to search for.

            - *default None*.
            Acceptable types are: list, np.ndarray, PIL.Image.Image

        vector_column_name: str, optional
            The name of the vector column to search.

            - If not specified then the vector column is inferred from
            the table schema

            - If the table has multiple vector columns then the *vector_column_name*
            needs to be specified. Otherwise, an error is raised.

        fast_search: bool, optional
            Skip a flat search of unindexed data. This may improve
            search performance but search results will not include unindexed data.

            - *default False*.

        Returns
        -------
        LanceQueryBuilder
            A query builder object representing the query.
            Once executed, the query returns

            - selected columns

            - the vector

            - and also the "_distance" column which is the distance between the query
            vector and the returned vector.
        """
        return LanceQueryBuilder.create(
            self,
            query,
            query_type,
            vector_column_name=vector_column_name,
            fts_columns=fts_columns,
            fast_search=fast_search,
        )

    def _execute_query(
        self, query: Query, batch_size: Optional[int] = None
    ) -> pa.RecordBatchReader:
        return LOOP.run(self._table._execute_query(query, batch_size=batch_size))

    def merge_insert(self, on: Union[str, Iterable[str]]) -> LanceMergeInsertBuilder:
        """Returns a [`LanceMergeInsertBuilder`][lancedb.merge.LanceMergeInsertBuilder]
        that can be used to create a "merge insert" operation.

        See [`Table.merge_insert`][lancedb.table.Table.merge_insert] for more details.
        """
        return super().merge_insert(on)

    def _do_merge(
        self,
        merge: LanceMergeInsertBuilder,
        new_data: DATA,
        on_bad_vectors: str,
        fill_value: float,
    ):
        LOOP.run(self._table._do_merge(merge, new_data, on_bad_vectors, fill_value))

    def delete(self, predicate: str):
        """Delete rows from the table.

        This can be used to delete a single row, many rows, all rows, or
        sometimes no rows (if your predicate matches nothing).

        Parameters
        ----------
        predicate: str
            The SQL where clause to use when deleting rows.

            - For example, 'x = 2' or 'x IN (1, 2, 3)'.

            The filter must not be empty, or it will error.

        Examples
        --------
        >>> import lancedb
        >>> data = [
        ...    {"x": 1, "vector": [1, 2]},
        ...    {"x": 2, "vector": [3, 4]},
        ...    {"x": 3, "vector": [5, 6]}
        ... ]
        >>> db = lancedb.connect("db://...", api_key="...", # doctest: +SKIP
        ...                      region="...") # doctest: +SKIP
        >>> table = db.create_table("my_table", data) # doctest: +SKIP
        >>> table.search([10,10]).to_pandas() # doctest: +SKIP
           x      vector  _distance # doctest: +SKIP
        0  3  [5.0, 6.0]       41.0 # doctest: +SKIP
        1  2  [3.0, 4.0]       85.0 # doctest: +SKIP
        2  1  [1.0, 2.0]      145.0 # doctest: +SKIP
        >>> table.delete("x = 2") # doctest: +SKIP
        >>> table.search([10,10]).to_pandas() # doctest: +SKIP
           x      vector  _distance # doctest: +SKIP
        0  3  [5.0, 6.0]       41.0 # doctest: +SKIP
        1  1  [1.0, 2.0]      145.0 # doctest: +SKIP

        If you have a list of values to delete, you can combine them into a
        stringified list and use the `IN` operator:

        >>> to_remove = [1, 3] # doctest: +SKIP
        >>> to_remove = ", ".join([str(v) for v in to_remove]) # doctest: +SKIP
        >>> table.delete(f"x IN ({to_remove})") # doctest: +SKIP
        >>> table.search([10,10]).to_pandas() # doctest: +SKIP
           x      vector  _distance # doctest: +SKIP
        0  2  [3.0, 4.0]       85.0 # doctest: +SKIP
        """
        LOOP.run(self._table.delete(predicate))

    def update(
        self,
        where: Optional[str] = None,
        values: Optional[dict] = None,
        *,
        values_sql: Optional[Dict[str, str]] = None,
    ):
        """
        This can be used to update zero to all rows depending on how many
        rows match the where clause.

        Parameters
        ----------
        where: str, optional
            The SQL where clause to use when updating rows. For example, 'x = 2'
            or 'x IN (1, 2, 3)'. The filter must not be empty, or it will error.
        values: dict, optional
            The values to update. The keys are the column names and the values
            are the values to set.
        values_sql: dict, optional
            The values to update, expressed as SQL expression strings. These can
            reference existing columns. For example, {"x": "x + 1"} will increment
            the x column by 1.

        Examples
        --------
        >>> import lancedb
        >>> data = [
        ...    {"x": 1, "vector": [1, 2]},
        ...    {"x": 2, "vector": [3, 4]},
        ...    {"x": 3, "vector": [5, 6]}
        ... ]
        >>> db = lancedb.connect("db://...", api_key="...", # doctest: +SKIP
        ...                      region="...") # doctest: +SKIP
        >>> table = db.create_table("my_table", data) # doctest: +SKIP
        >>> table.to_pandas() # doctest: +SKIP
           x      vector # doctest: +SKIP
        0  1  [1.0, 2.0] # doctest: +SKIP
        1  2  [3.0, 4.0] # doctest: +SKIP
        2  3  [5.0, 6.0] # doctest: +SKIP
        >>> table.update(where="x = 2", values={"vector": [10, 10]}) # doctest: +SKIP
        >>> table.to_pandas() # doctest: +SKIP
           x        vector # doctest: +SKIP
        0  1    [1.0, 2.0] # doctest: +SKIP
        1  3    [5.0, 6.0] # doctest: +SKIP
        2  2  [10.0, 10.0] # doctest: +SKIP

        """
        LOOP.run(
            self._table.update(where=where, updates=values, updates_sql=values_sql)
        )

    def cleanup_old_versions(self, *_):
        """cleanup_old_versions() is not supported on the LanceDB cloud"""
        raise NotImplementedError(
            "cleanup_old_versions() is not supported on the LanceDB cloud"
        )

    def compact_files(self, *_):
        """compact_files() is not supported on the LanceDB cloud"""
        raise NotImplementedError(
            "compact_files() is not supported on the LanceDB cloud"
        )

    def optimize(
        self,
        *,
        cleanup_older_than: Optional[timedelta] = None,
        delete_unverified: bool = False,
    ):
        """optimize() is not supported on the LanceDB cloud.
        Indices are optimized automatically."""
        raise NotImplementedError(
            "optimize() is not supported on the LanceDB cloud. "
            "Indices are optimized automatically."
        )

    def count_rows(self, filter: Optional[str] = None) -> int:
        return LOOP.run(self._table.count_rows(filter))

    def add_columns(self, transforms: Dict[str, str]):
        raise NotImplementedError(
            "add_columns() is not yet supported on the LanceDB cloud"
        )

    def alter_columns(self, alterations: Iterable[Dict[str, str]]):
        raise NotImplementedError(
            "alter_columns() is not yet supported on the LanceDB cloud"
        )

    def drop_columns(self, columns: Iterable[str]):
        raise NotImplementedError(
            "drop_columns() is not yet supported on the LanceDB cloud"
        )


def add_index(tbl: pa.Table, i: int) -> pa.Table:
    return tbl.add_column(
        0,
        pa.field("query_index", pa.uint32()),
        pa.array([i] * len(tbl), pa.uint32()),
    )
