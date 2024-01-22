# Pandas and PyArrow

Because Lance is built on top of [Apache Arrow](https://arrow.apache.org/),
LanceDB is tightly integrated with the Python data ecosystem, including [Pandas](https://pandas.pydata.org/)
and PyArrow. The sequence of steps in a typical workflow is shown below.

## Create dataset

First, we need to connect to a LanceDB database.

```py

import lancedb

db = lancedb.connect("data/sample-lancedb")
```

We can load a Pandas `DataFrame` to LanceDB directly.

```py
import pandas as pd

data = pd.DataFrame({
    "vector": [[3.1, 4.1], [5.9, 26.5]],
    "item": ["foo", "bar"],
    "price": [10.0, 20.0]
})
table = db.create_table("pd_table", data=data)
```

Similar to the [`pyarrow.write_dataset()`](https://arrow.apache.org/docs/python/generated/pyarrow.dataset.write_dataset.html) method, LanceDB's
[`db.create_table()`](python.md/#lancedb.db.DBConnection.create_table) accepts data in a variety of forms.

If you have a dataset that is larger than memory, you can create a table with `Iterator[pyarrow.RecordBatch]` to lazily load the data:

```py

from typing import Iterable
import pyarrow as pa

def make_batches() -> Iterable[pa.RecordBatch]:
    for i in range(5):
        yield pa.RecordBatch.from_arrays(
            [
                pa.array([[3.1, 4.1], [5.9, 26.5]]),
                pa.array(["foo", "bar"]),
                pa.array([10.0, 20.0]),
            ],
            ["vector", "item", "price"])

schema=pa.schema([
    pa.field("vector", pa.list_(pa.float32())),
    pa.field("item", pa.utf8()),
    pa.field("price", pa.float32()),
])

table = db.create_table("iterable_table", data=make_batches(), schema=schema)
```

You will find detailed instructions of creating a LanceDB dataset in
[Getting Started](../basic.md#quick-start) and [API](python.md/#lancedb.db.DBConnection.create_table)
sections.

## Vector search

We can now perform similarity search via the LanceDB Python API.

```py
# Open the table previously created.
table = db.open_table("pd_table")

query_vector = [100, 100]
# Pandas DataFrame
df = table.search(query_vector).limit(1).to_pandas()
print(df)
```

```
    vector     item  price    _distance
0  [5.9, 26.5]  bar   20.0  14257.05957
```

If you have a simple filter, it's faster to provide a `where` clause to LanceDB's `search` method.
For more complex filters or aggregations, you can always resort to using the underlying `DataFrame` methods after performing a search.

```python

# Apply the filter via LanceDB
results = table.search([100, 100]).where("price < 15").to_pandas()
assert len(results) == 1
assert results["item"].iloc[0] == "foo"

# Apply the filter via Pandas
df = results = table.search([100, 100]).to_pandas()
results = df[df.price < 15]
assert len(results) == 1
assert results["item"].iloc[0] == "foo"
```
