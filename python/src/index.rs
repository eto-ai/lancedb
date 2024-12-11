// Copyright 2024 Lance Developers.
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

use lancedb::index::{
    scalar::{BTreeIndexBuilder, FtsIndexBuilder, TokenizerConfig},
    vector::{IvfHnswPqIndexBuilder, IvfHnswSqIndexBuilder, IvfPqIndexBuilder},
    Index as LanceDbIndex,
};
use pyo3::{
    exceptions::{PyKeyError, PyValueError},
    intern, pyclass, pymethods,
    types::PyAnyMethods,
    Bound, FromPyObject, IntoPy, PyAny, PyObject, PyResult, Python,
};

use crate::util::parse_distance_type;

pub fn extract_index_params(source: &Option<Bound<'_, PyAny>>) -> PyResult<LanceDbIndex> {
    if let Some(source) = source {
        let class_name: String = source
            .getattr(intern!(source.py(), "__class__"))?
            .getattr(intern!(source.py(), "__name__"))?
            .extract()?;

        match class_name.rsplit_once('.').map(|v| v.1).unwrap_or(&class_name) {
            "BTree" => Ok(LanceDbIndex::BTree(BTreeIndexBuilder::default())),
            "Bitmap" => Ok(LanceDbIndex::Bitmap(Default::default())),
            "LabelList" => Ok(LanceDbIndex::LabelList(Default::default())),
            "FTS" => {
                let params = source.extract::<FtsParams>()?;
                let inner_opts = TokenizerConfig::default()
                    .base_tokenizer(params.base_tokenizer)
                    .language(&params.language)
                    .map_err(|_| PyValueError::new_err(format!("LanceDB does not support the requested language: \"{}\"", params.language)))?
                    .lower_case(params.lower_case)
                    .max_token_length(params.max_token_length)
                    .remove_stop_words(params.remove_stop_words)
                    .stem(params.stem)
                    .ascii_folding(params.ascii_folding);
                let mut opts = FtsIndexBuilder::default()
                    .with_position(params.with_position);
                opts.tokenizer_configs = inner_opts;
                Ok(LanceDbIndex::FTS(opts))
            },
            "IvfPq" => {
                let params = source.extract::<IvfPqParams>()?;
                let distance_type = parse_distance_type(params.distance_type)?;
                let mut ivf_pq_builder = IvfPqIndexBuilder::default()
                    .distance_type(distance_type)
                    .max_iterations(params.max_iterations)
                    .sample_rate(params.sample_rate)
                    .num_bits(params.num_bits);
                if let Some(num_partitions) = params.num_partitions {
                    ivf_pq_builder = ivf_pq_builder.num_partitions(num_partitions);
                }
                if let Some(num_sub_vectors) = params.num_sub_vectors {
                    ivf_pq_builder = ivf_pq_builder.num_sub_vectors(num_sub_vectors);
                }
                Ok(LanceDbIndex::IvfPq(ivf_pq_builder))
            },
            "HnswPq" => {
                let params = source.extract::<IvfHnswPqParams>()?;
                let distance_type = parse_distance_type(params.distance_type)?;
                let mut hnsw_pq_builder = IvfHnswPqIndexBuilder::default()
                    .distance_type(distance_type)
                    .max_iterations(params.max_iterations)
                    .sample_rate(params.sample_rate)
                    .num_edges(params.m)
                    .ef_construction(params.ef_construction)
                    .num_bits(params.num_bits);
                if let Some(num_partitions) = params.num_partitions {
                    hnsw_pq_builder = hnsw_pq_builder.num_partitions(num_partitions);
                }
                if let Some(num_sub_vectors) = params.num_sub_vectors {
                    hnsw_pq_builder = hnsw_pq_builder.num_sub_vectors(num_sub_vectors);
                }
                Ok(LanceDbIndex::IvfHnswPq(hnsw_pq_builder))
            },
            "HnswSq" => {
                let params = source.extract::<IvfHnswSqParams>()?;
                let distance_type = parse_distance_type(params.distance_type)?;
                let mut hnsw_sq_builder = IvfHnswSqIndexBuilder::default()
                    .distance_type(distance_type)
                    .max_iterations(params.max_iterations)
                    .sample_rate(params.sample_rate)
                    .num_edges(params.m)
                    .ef_construction(params.ef_construction);
                if let Some(num_partitions) = params.num_partitions {
                    hnsw_sq_builder = hnsw_sq_builder.num_partitions(num_partitions);
                }
                Ok(LanceDbIndex::IvfHnswSq(hnsw_sq_builder))
            },
            _ => Err(PyValueError::new_err(format!(
                "Invalid index type '{}'.  Must be one of BTree, Bitmap, LabelList, FTS, IvfPq, IvfHnswPq, or IvfHnswSq",
                class_name
            ))),
        }
    } else {
        Ok(LanceDbIndex::Auto)
    }
}

#[derive(FromPyObject)]
struct FtsParams {
    with_position: bool,
    base_tokenizer: String,
    language: String,
    max_token_length: Option<usize>,
    lower_case: bool,
    stem: bool,
    remove_stop_words: bool,
    ascii_folding: bool,
}

#[derive(FromPyObject)]
struct IvfPqParams {
    distance_type: String,
    num_partitions: Option<u32>,
    num_sub_vectors: Option<u32>,
    num_bits: u32,
    max_iterations: u32,
    sample_rate: u32,
}

#[derive(FromPyObject)]
struct IvfHnswPqParams {
    distance_type: String,
    num_partitions: Option<u32>,
    num_sub_vectors: Option<u32>,
    num_bits: u32,
    max_iterations: u32,
    sample_rate: u32,
    m: u32,
    ef_construction: u32,
}

#[derive(FromPyObject)]
struct IvfHnswSqParams {
    distance_type: String,
    num_partitions: Option<u32>,
    max_iterations: u32,
    sample_rate: u32,
    m: u32,
    ef_construction: u32,
}

#[pyclass(get_all)]
/// A description of an index currently configured on a column
pub struct IndexConfig {
    /// The type of the index
    pub index_type: String,
    /// The columns in the index
    ///
    /// Currently this is always a list of size 1.  In the future there may
    /// be more columns to represent composite indices.
    pub columns: Vec<String>,
    /// Name of the index.
    pub name: String,
}

#[pymethods]
impl IndexConfig {
    pub fn __repr__(&self) -> String {
        format!(
            "Index({}, columns={:?}, name=\"{}\")",
            self.index_type, self.columns, self.name
        )
    }

    // For backwards-compatibility with the old sync SDK, we also support getting
    // attributes via __getitem__.
    pub fn __getitem__(&self, key: String, py: Python<'_>) -> PyResult<PyObject> {
        match key.as_str() {
            "index_type" => Ok(self.index_type.clone().into_py(py)),
            "columns" => Ok(self.columns.clone().into_py(py)),
            "name" | "index_name" => Ok(self.name.clone().into_py(py)),
            _ => Err(PyKeyError::new_err(format!("Invalid key: {}", key))),
        }
    }
}

impl From<lancedb::index::IndexConfig> for IndexConfig {
    fn from(value: lancedb::index::IndexConfig) -> Self {
        let index_type = format!("{:?}", value.index_type);
        Self {
            index_type,
            columns: value.columns,
            name: value.name,
        }
    }
}
