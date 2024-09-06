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

import asyncio
import os
from abc import abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Dict, Iterable, List, Literal, Optional, Union

import pyarrow as pa
from overrides import EnforceOverrides, override
from pyarrow import fs

from lancedb.common import data_to_reader, validate_schema

from ._lancedb import connect as lancedb_connect
from .table import (
    AsyncTable,
    LanceTable,
    Table,
    _table_path,
    sanitize_create_table,
)
from .util import (
    fs_from_uri,
    get_uri_location,
    get_uri_scheme,
    validate_table_name,
)

if TYPE_CHECKING:
    from .pydantic import LanceModel
    from datetime import timedelta

    from ._lancedb import Connection as LanceDbConnection
    from .common import DATA, URI
    from .embeddings import EmbeddingFunctionConfig


class DBConnection(EnforceOverrides):
    """An active LanceDB connection interface."""

    @abstractmethod
    def table_names(
        self, page_token: Optional[str] = None, limit: int = 10
    ) -> Iterable[str]:
        """List all tables in this database, in sorted order

        Parameters
        ----------
        page_token: str, optional
            The token to use for pagination. If not present, start from the beginning.
            Typically, this token is last table name from the previous page.
            Only supported by LanceDb Cloud.
        limit: int, default 10
            The size of the page to return.
            Only supported by LanceDb Cloud.

        Returns
        -------
        Iterable of str
        """
        pass

    @abstractmethod
    def create_table(
        self,
        name: str,
        data: Optional[DATA] = None,
        schema: Optional[Union[pa.Schema, LanceModel]] = None,
        mode: str = "create",
        exist_ok: bool = False,
        on_bad_vectors: str = "error",
        fill_value: float = 0.0,
        embedding_functions: Optional[List[EmbeddingFunctionConfig]] = None,
    ) -> Table:
        """Create a [Table][lancedb.table.Table] in the database.

        Parameters
        ----------
        name: str
            The name of the table.
        data: The data to initialize the table, *optional*
            User must provide at least one of `data` or `schema`.
            Acceptable types are:

            - dict or list-of-dict

            - pandas.DataFrame

            - pyarrow.Table or pyarrow.RecordBatch
        schema: The schema of the table, *optional*
            Acceptable types are:

            - pyarrow.Schema

            - [LanceModel][lancedb.pydantic.LanceModel]
        mode: str; default "create"
            The mode to use when creating the table.
            Can be either "create" or "overwrite".
            By default, if the table already exists, an exception is raised.
            If you want to overwrite the table, use mode="overwrite".
        exist_ok: bool, default False
            If a table by the same name already exists, then raise an exception
            if exist_ok=False. If exist_ok=True, then open the existing table;
            it will not add the provided data but will validate against any
            schema that's specified.
        on_bad_vectors: str, default "error"
            What to do if any of the vectors are not the same size or contains NaNs.
            One of "error", "drop", "fill".
        fill_value: float
            The value to use when filling vectors. Only used if on_bad_vectors="fill".

        Returns
        -------
        LanceTable
            A reference to the newly created table.

        !!! note

            The vector index won't be created by default.
            To create the index, call the `create_index` method on the table.

        Examples
        --------

        Can create with list of tuples or dictionaries:

        >>> import lancedb
        >>> db = lancedb.connect("./.lancedb")
        >>> data = [{"vector": [1.1, 1.2], "lat": 45.5, "long": -122.7},
        ...         {"vector": [0.2, 1.8], "lat": 40.1, "long":  -74.1}]
        >>> db.create_table("my_table", data)
        LanceTable(connection=..., name="my_table")
        >>> db["my_table"].head()
        pyarrow.Table
        vector: fixed_size_list<item: float>[2]
          child 0, item: float
        lat: double
        long: double
        ----
        vector: [[[1.1,1.2],[0.2,1.8]]]
        lat: [[45.5,40.1]]
        long: [[-122.7,-74.1]]

        You can also pass a pandas DataFrame:

        >>> import pandas as pd
        >>> data = pd.DataFrame({
        ...    "vector": [[1.1, 1.2], [0.2, 1.8]],
        ...    "lat": [45.5, 40.1],
        ...    "long": [-122.7, -74.1]
        ... })
        >>> db.create_table("table2", data)
        LanceTable(connection=..., name="table2")
        >>> db["table2"].head()
        pyarrow.Table
        vector: fixed_size_list<item: float>[2]
          child 0, item: float
        lat: double
        long: double
        ----
        vector: [[[1.1,1.2],[0.2,1.8]]]
        lat: [[45.5,40.1]]
        long: [[-122.7,-74.1]]

        Data is converted to Arrow before being written to disk. For maximum
        control over how data is saved, either provide the PyArrow schema to
        convert to or else provide a [PyArrow Table](pyarrow.Table) directly.

        >>> custom_schema = pa.schema([
        ...   pa.field("vector", pa.list_(pa.float32(), 2)),
        ...   pa.field("lat", pa.float32()),
        ...   pa.field("long", pa.float32())
        ... ])
        >>> db.create_table("table3", data, schema = custom_schema)
        LanceTable(connection=..., name="table3")
        >>> db["table3"].head()
        pyarrow.Table
        vector: fixed_size_list<item: float>[2]
          child 0, item: float
        lat: float
        long: float
        ----
        vector: [[[1.1,1.2],[0.2,1.8]]]
        lat: [[45.5,40.1]]
        long: [[-122.7,-74.1]]


        It is also possible to create an table from `[Iterable[pa.RecordBatch]]`:


        >>> import pyarrow as pa
        >>> def make_batches():
        ...     for i in range(5):
        ...         yield pa.RecordBatch.from_arrays(
        ...             [
        ...                 pa.array([[3.1, 4.1], [5.9, 26.5]],
        ...                     pa.list_(pa.float32(), 2)),
        ...                 pa.array(["foo", "bar"]),
        ...                 pa.array([10.0, 20.0]),
        ...             ],
        ...             ["vector", "item", "price"],
        ...         )
        >>> schema=pa.schema([
        ...     pa.field("vector", pa.list_(pa.float32(), 2)),
        ...     pa.field("item", pa.utf8()),
        ...     pa.field("price", pa.float32()),
        ... ])
        >>> db.create_table("table4", make_batches(), schema=schema)
        LanceTable(connection=..., name="table4")

        """
        raise NotImplementedError

    def __getitem__(self, name: str) -> LanceTable:
        return self.open_table(name)

    def open_table(self, name: str, *, index_cache_size: Optional[int] = None) -> Table:
        """Open a Lance Table in the database.

        Parameters
        ----------
        name: str
            The name of the table.
        index_cache_size: int, default 256
            Set the size of the index cache, specified as a number of entries

            The exact meaning of an "entry" will depend on the type of index:
            * IVF - there is one entry for each IVF partition
            * BTREE - there is one entry for the entire index

            This cache applies to the entire opened table, across all indices.
            Setting this value higher will increase performance on larger datasets
            at the expense of more RAM

        Returns
        -------
        A LanceTable object representing the table.
        """
        raise NotImplementedError

    def drop_table(self, name: str):
        """Drop a table from the database.

        Parameters
        ----------
        name: str
            The name of the table.
        """
        raise NotImplementedError

    def rename_table(self, cur_name: str, new_name: str):
        """Rename a table in the database.

        Parameters
        ----------
        cur_name: str
            The current name of the table.
        new_name: str
            The new name of the table.
        """
        raise NotImplementedError

    def drop_database(self):
        """
        Drop database
        This is the same thing as dropping all the tables
        """
        raise NotImplementedError

    @property
    def uri(self) -> str:
        return self._uri


class LanceDBConnection(DBConnection):
    """
    A connection to a LanceDB database.

    Parameters
    ----------
    uri: str or Path
        The root uri of the database.
    read_consistency_interval: timedelta, default None
        The interval at which to check for updates to the table from other
        processes. If None, then consistency is not checked. For performance
        reasons, this is the default. For strong consistency, set this to
        zero seconds. Then every read will check for updates from other
        processes. As a compromise, you can set this to a non-zero timedelta
        for eventual consistency. If more than that interval has passed since
        the last check, then the table will be checked for updates. Note: this
        consistency only applies to read operations. Write operations are
        always consistent.

    Examples
    --------
    >>> import lancedb
    >>> db = lancedb.connect("./.lancedb")
    >>> db.create_table("my_table", data=[{"vector": [1.1, 1.2], "b": 2},
    ...                                   {"vector": [0.5, 1.3], "b": 4}])
    LanceTable(connection=..., name="my_table")
    >>> db.create_table("another_table", data=[{"vector": [0.4, 0.4], "b": 6}])
    LanceTable(connection=..., name="another_table")
    >>> sorted(db.table_names())
    ['another_table', 'my_table']
    >>> len(db)
    2
    >>> db["my_table"]
    LanceTable(connection=..., name="my_table")
    >>> "my_table" in db
    True
    >>> db.drop_table("my_table")
    >>> db.drop_table("another_table")
    """

    def __init__(
        self, uri: URI, *, read_consistency_interval: Optional[timedelta] = None
    ):
        if not isinstance(uri, Path):
            scheme = get_uri_scheme(uri)
        is_local = isinstance(uri, Path) or scheme == "file"
        if is_local:
            if isinstance(uri, str):
                uri = Path(uri)
            uri = uri.expanduser().absolute()
            Path(uri).mkdir(parents=True, exist_ok=True)
        self._uri = str(uri)

        self._entered = False
        self.read_consistency_interval = read_consistency_interval

    def __repr__(self) -> str:
        val = f"{self.__class__.__name__}({self._uri}"
        if self.read_consistency_interval is not None:
            val += f", read_consistency_interval={repr(self.read_consistency_interval)}"
        val += ")"
        return val

    async def _async_get_table_names(self, start_after: Optional[str], limit: int):
        conn = AsyncConnection(await lancedb_connect(self.uri))
        return await conn.table_names(start_after=start_after, limit=limit)

    @override
    def table_names(
        self, page_token: Optional[str] = None, limit: int = 10
    ) -> Iterable[str]:
        """Get the names of all tables in the database. The names are sorted.

        Returns
        -------
        Iterator of str.
            A list of table names.
        """
        try:
            asyncio.get_running_loop()
            # User application is async.  Soon we will just tell them to use the
            # async version.  Until then fallback to the old sync implementation.
            try:
                filesystem = fs_from_uri(self.uri)[0]
            except pa.ArrowInvalid:
                raise NotImplementedError("Unsupported scheme: " + self.uri)

            try:
                loc = get_uri_location(self.uri)
                paths = filesystem.get_file_info(fs.FileSelector(loc))
            except FileNotFoundError:
                # It is ok if the file does not exist since it will be created
                paths = []
            tables = [
                os.path.splitext(file_info.base_name)[0]
                for file_info in paths
                if file_info.extension == "lance"
            ]
            tables.sort()
            return tables
        except RuntimeError:
            # User application is sync.  It is safe to use the async implementation
            # under the hood.
            return asyncio.run(self._async_get_table_names(page_token, limit))

    def __len__(self) -> int:
        return len(self.table_names())

    def __contains__(self, name: str) -> bool:
        return name in self.table_names()

    @override
    def create_table(
        self,
        name: str,
        data: Optional[DATA] = None,
        schema: Optional[Union[pa.Schema, LanceModel]] = None,
        mode: str = "create",
        exist_ok: bool = False,
        on_bad_vectors: str = "error",
        fill_value: float = 0.0,
        embedding_functions: Optional[List[EmbeddingFunctionConfig]] = None,
    ) -> LanceTable:
        """Create a table in the database.

        See
        ---
        DBConnection.create_table
        """
        if mode.lower() not in ["create", "overwrite"]:
            raise ValueError("mode must be either 'create' or 'overwrite'")
        validate_table_name(name)

        tbl = LanceTable.create(
            self,
            name,
            data,
            schema,
            mode=mode,
            exist_ok=exist_ok,
            on_bad_vectors=on_bad_vectors,
            fill_value=fill_value,
            embedding_functions=embedding_functions,
        )
        return tbl

    @override
    def open_table(
        self, name: str, *, index_cache_size: Optional[int] = None
    ) -> LanceTable:
        """Open a table in the database.

        Parameters
        ----------
        name: str
            The name of the table.

        Returns
        -------
        A LanceTable object representing the table.
        """
        return LanceTable.open(self, name, index_cache_size=index_cache_size)

    @override
    def drop_table(self, name: str, ignore_missing: bool = False):
        """Drop a table from the database.

        Parameters
        ----------
        name: str
            The name of the table.
        ignore_missing: bool, default False
            If True, ignore if the table does not exist.
        """
        try:
            table_uri = _table_path(self.uri, name)
            filesystem, path = fs_from_uri(table_uri)
            filesystem.delete_dir(path)
        except FileNotFoundError:
            if not ignore_missing:
                raise

    @override
    def drop_database(self):
        dummy_table_uri = _table_path(self.uri, "dummy")
        uri = dummy_table_uri.removesuffix("dummy.lance")
        filesystem, path = fs_from_uri(uri)
        filesystem.delete_dir(path)


class AsyncConnection(object):
    """An active LanceDB connection

    To obtain a connection you can use the [connect_async][lancedb.connect_async]
    function.

    This could be a native connection (using lance) or a remote connection (e.g. for
    connecting to LanceDb Cloud)

    Local connections do not currently hold any open resources but they may do so in the
    future (for example, for shared cache or connections to catalog services) Remote
    connections represent an open connection to the remote server.  The
    [close][lancedb.db.AsyncConnection.close] method can be used to release any
    underlying resources eagerly.  The connection can also be used as a context manager.

    Connections can be shared on multiple threads and are expected to be long lived.
    Connections can also be used as a context manager, however, in many cases a single
    connection can be used for the lifetime of the application and so this is often
    not needed.  Closing a connection is optional.  If it is not closed then it will
    be automatically closed when the connection object is deleted.

    Examples
    --------

    >>> import lancedb
    >>> async def doctest_example():
    ...   with await lancedb.connect_async("/tmp/my_dataset") as conn:
    ...     # do something with the connection
    ...     pass
    ...   # conn is closed here
    """

    def __init__(self, connection: LanceDbConnection):
        self._inner = connection

    def __repr__(self):
        return self._inner.__repr__()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def is_open(self):
        """Return True if the connection is open."""
        return self._inner.is_open()

    def close(self):
        """Close the connection, releasing any underlying resources.

        It is safe to call this method multiple times.

        Any attempt to use the connection after it is closed will result in an error."""
        self._inner.close()

    async def table_names(
        self, *, start_after: Optional[str] = None, limit: Optional[int] = None
    ) -> Iterable[str]:
        """List all tables in this database, in sorted order

        Parameters
        ----------
        start_after: str, optional
            If present, only return names that come lexicographically after the supplied
            value.

            This can be combined with limit to implement pagination by setting this to
            the last table name from the previous page.
        limit: int, default 10
            The number of results to return.

        Returns
        -------
        Iterable of str
        """
        return await self._inner.table_names(start_after=start_after, limit=limit)

    async def create_table(
        self,
        name: str,
        data: Optional[DATA] = None,
        schema: Optional[Union[pa.Schema, LanceModel]] = None,
        mode: Optional[Literal["create", "overwrite"]] = None,
        exist_ok: Optional[bool] = None,
        on_bad_vectors: Optional[str] = None,
        fill_value: Optional[float] = None,
        storage_options: Optional[Dict[str, str]] = None,
        *,
        data_storage_version: Optional[str] = None,
        use_legacy_format: Optional[bool] = None,
        enable_v2_manifest_paths: Optional[bool] = None,
    ) -> AsyncTable:
        """Create an [AsyncTable][lancedb.table.AsyncTable] in the database.

        Parameters
        ----------
        name: str
            The name of the table.
        data: The data to initialize the table, *optional*
            User must provide at least one of `data` or `schema`.
            Acceptable types are:

            - dict or list-of-dict

            - pandas.DataFrame

            - pyarrow.Table or pyarrow.RecordBatch
        schema: The schema of the table, *optional*
            Acceptable types are:

            - pyarrow.Schema

            - [LanceModel][lancedb.pydantic.LanceModel]
        mode: Literal["create", "overwrite"]; default "create"
            The mode to use when creating the table.
            Can be either "create" or "overwrite".
            By default, if the table already exists, an exception is raised.
            If you want to overwrite the table, use mode="overwrite".
        exist_ok: bool, default False
            If a table by the same name already exists, then raise an exception
            if exist_ok=False. If exist_ok=True, then open the existing table;
            it will not add the provided data but will validate against any
            schema that's specified.
        on_bad_vectors: str, default "error"
            What to do if any of the vectors are not the same size or contains NaNs.
            One of "error", "drop", "fill".
        fill_value: float
            The value to use when filling vectors. Only used if on_bad_vectors="fill".
        storage_options: dict, optional
            Additional options for the storage backend. Options already set on the
            connection will be inherited by the table, but can be overridden here.
            See available options at
            https://lancedb.github.io/lancedb/guides/storage/
        data_storage_version: optional, str, default "legacy"
            The version of the data storage format to use. Newer versions are more
            efficient but require newer versions of lance to read.  The default is
            "legacy" which will use the legacy v1 version.  See the user guide
            for more details.
        use_legacy_format: bool, optional, default True. (Deprecated)
            If True, use the legacy format for the table. If False, use the new format.
            The default is True while the new format is in beta.
            This method is deprecated, use `data_storage_version` instead.
        enable_v2_manifest_paths: bool, optional, default False
            Use the new V2 manifest paths. These paths provide more efficient
            opening of datasets with many versions on object stores.  WARNING:
            turning this on will make the dataset unreadable for older versions
            of LanceDB (prior to 0.13.0). To migrate an existing dataset, instead
            use the
            [AsyncTable.migrate_manifest_paths_v2][lancedb.table.AsyncTable.migrate_manifest_paths_v2]
            method.


        Returns
        -------
        AsyncTable
            A reference to the newly created table.

        !!! note

            The vector index won't be created by default.
            To create the index, call the `create_index` method on the table.

        Examples
        --------

        Can create with list of tuples or dictionaries:

        >>> import lancedb
        >>> async def doctest_example():
        ...     db = await lancedb.connect_async("./.lancedb")
        ...     data = [{"vector": [1.1, 1.2], "lat": 45.5, "long": -122.7},
        ...             {"vector": [0.2, 1.8], "lat": 40.1, "long":  -74.1}]
        ...     my_table = await db.create_table("my_table", data)
        ...     print(await my_table.query().limit(5).to_arrow())
        >>> import asyncio
        >>> asyncio.run(doctest_example())
        pyarrow.Table
        vector: fixed_size_list<item: float>[2]
          child 0, item: float
        lat: double
        long: double
        ----
        vector: [[[1.1,1.2],[0.2,1.8]]]
        lat: [[45.5,40.1]]
        long: [[-122.7,-74.1]]

        You can also pass a pandas DataFrame:

        >>> import pandas as pd
        >>> data = pd.DataFrame({
        ...    "vector": [[1.1, 1.2], [0.2, 1.8]],
        ...    "lat": [45.5, 40.1],
        ...    "long": [-122.7, -74.1]
        ... })
        >>> async def pandas_example():
        ...     db = await lancedb.connect_async("./.lancedb")
        ...     my_table = await db.create_table("table2", data)
        ...     print(await my_table.query().limit(5).to_arrow())
        >>> asyncio.run(pandas_example())
        pyarrow.Table
        vector: fixed_size_list<item: float>[2]
          child 0, item: float
        lat: double
        long: double
        ----
        vector: [[[1.1,1.2],[0.2,1.8]]]
        lat: [[45.5,40.1]]
        long: [[-122.7,-74.1]]

        Data is converted to Arrow before being written to disk. For maximum
        control over how data is saved, either provide the PyArrow schema to
        convert to or else provide a [PyArrow Table](pyarrow.Table) directly.

        >>> custom_schema = pa.schema([
        ...   pa.field("vector", pa.list_(pa.float32(), 2)),
        ...   pa.field("lat", pa.float32()),
        ...   pa.field("long", pa.float32())
        ... ])
        >>> async def with_schema():
        ...     db = await lancedb.connect_async("./.lancedb")
        ...     my_table = await db.create_table("table3", data, schema = custom_schema)
        ...     print(await my_table.query().limit(5).to_arrow())
        >>> asyncio.run(with_schema())
        pyarrow.Table
        vector: fixed_size_list<item: float>[2]
          child 0, item: float
        lat: float
        long: float
        ----
        vector: [[[1.1,1.2],[0.2,1.8]]]
        lat: [[45.5,40.1]]
        long: [[-122.7,-74.1]]


        It is also possible to create an table from `[Iterable[pa.RecordBatch]]`:


        >>> import pyarrow as pa
        >>> def make_batches():
        ...     for i in range(5):
        ...         yield pa.RecordBatch.from_arrays(
        ...             [
        ...                 pa.array([[3.1, 4.1], [5.9, 26.5]],
        ...                     pa.list_(pa.float32(), 2)),
        ...                 pa.array(["foo", "bar"]),
        ...                 pa.array([10.0, 20.0]),
        ...             ],
        ...             ["vector", "item", "price"],
        ...         )
        >>> schema=pa.schema([
        ...     pa.field("vector", pa.list_(pa.float32(), 2)),
        ...     pa.field("item", pa.utf8()),
        ...     pa.field("price", pa.float32()),
        ... ])
        >>> async def iterable_example():
        ...     db = await lancedb.connect_async("./.lancedb")
        ...     await db.create_table("table4", make_batches(), schema=schema)
        >>> asyncio.run(iterable_example())
        """
        metadata = None

        # Defining defaults here and not in function prototype.  In the future
        # these defaults will move into rust so better to keep them as None.
        if on_bad_vectors is None:
            on_bad_vectors = "error"

        if fill_value is None:
            fill_value = 0.0

        data, schema = sanitize_create_table(
            data, schema, metadata, on_bad_vectors, fill_value
        )
        validate_schema(schema)

        if exist_ok is None:
            exist_ok = False
        if mode is None:
            mode = "create"
        if mode == "create" and exist_ok:
            mode = "exist_ok"

        if not data_storage_version:
            data_storage_version = (
                "legacy" if use_legacy_format is None or use_legacy_format else "stable"
            )

        if data is None:
            new_table = await self._inner.create_empty_table(
                name,
                mode,
                schema,
                storage_options=storage_options,
                data_storage_version=data_storage_version,
                enable_v2_manifest_paths=enable_v2_manifest_paths,
            )
        else:
            data = data_to_reader(data, schema)
            new_table = await self._inner.create_table(
                name,
                mode,
                data,
                storage_options=storage_options,
                data_storage_version=data_storage_version,
                enable_v2_manifest_paths=enable_v2_manifest_paths,
            )

        return AsyncTable(new_table)

    async def open_table(
        self,
        name: str,
        storage_options: Optional[Dict[str, str]] = None,
        index_cache_size: Optional[int] = None,
    ) -> AsyncTable:
        """Open a Lance Table in the database.

        Parameters
        ----------
        name: str
            The name of the table.
        storage_options: dict, optional
            Additional options for the storage backend. Options already set on the
            connection will be inherited by the table, but can be overridden here.
            See available options at
            https://lancedb.github.io/lancedb/guides/storage/
        index_cache_size: int, default 256
            Set the size of the index cache, specified as a number of entries

            The exact meaning of an "entry" will depend on the type of index:
            * IVF - there is one entry for each IVF partition
            * BTREE - there is one entry for the entire index

            This cache applies to the entire opened table, across all indices.
            Setting this value higher will increase performance on larger datasets
            at the expense of more RAM

        Returns
        -------
        A LanceTable object representing the table.
        """
        table = await self._inner.open_table(name, storage_options, index_cache_size)
        return AsyncTable(table)

    async def drop_table(self, name: str):
        """Drop a table from the database.

        Parameters
        ----------
        name: str
            The name of the table.
        """
        await self._inner.drop_table(name)

    async def drop_database(self):
        """
        Drop database
        This is the same thing as dropping all the tables
        """
        await self._inner.drop_db()
