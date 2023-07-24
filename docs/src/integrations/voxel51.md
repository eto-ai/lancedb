![example](/assets/voxel.gif)

Basic recipe
____________

The basic workflow to use LanceDB to create a similarity index on your FiftyOne
datasets and use this to query your data is as follows:

1)  Load a dataset into FiftyOne

2)  Compute embedding vectors for samples or patches in your dataset, or select
    a model to use to generate embeddings

3)  Use the `compute_similarity()`
    method to generate a LanceDB table for the samples or object
    patches embeddings in a dataset by setting the parameter `backend="lancedb"` and
    specifying a `brain_key` of your choice

4)  Use this LanceDB table to query your data with
    `sort_by_similarity()`

5) If desired, delete the table

The example below demonstrates this workflow.

!!! Note

    You must install the LanceDB Python client to run this
    ```
    pip install lancedb
    ```

```python

import fiftyone as fo
import fiftyone.brain as fob
import fiftyone.zoo as foz

# Step 1: Load your data into FiftyOne
dataset = foz.load_zoo_dataset("quickstart")

# Steps 2 and 3: Compute embeddings and create a similarity index
lancedb_index = fob.compute_similarity(
    dataset, 
    model="clip-vit-base32-torch",
    brain_key="lancedb_index",
    backend="lancedb",
)
```
Once the similarity index has been generated, we can query our data in FiftyOne
by specifying the `brain_key`:

```python
# Step 4: Query your data
query = dataset.first().id  # query by sample ID
view = dataset.sort_by_similarity(
    query, 
    brain_key="lancedb_index",
    k=10,  # limit to 10 most similar samples
)

# Step 5 (optional): Cleanup

# Delete the LanceDB table
lancedb_index.cleanup()

# Delete run record from FiftyOne
dataset.delete_brain_run("lancedb_index")
```

More in depth walkthrough of the integration, visit the LanceDB guide on Voxel51 - [LaceDB x Voxel51](https://docs.voxel51.com/integrations/lancedb.html)
