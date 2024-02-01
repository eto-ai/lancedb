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

use std::sync::Arc;

use arrow_array::RecordBatchReader;
use async_trait::async_trait;

use crate::Result;

#[async_trait]
pub(super) trait MergeInsert: Send + Sync {
    async fn do_merge_insert(
        &self,
        params: MergeInsertBuilder,
        new_data: Box<dyn RecordBatchReader + Send>,
    ) -> Result<()>;
}

/// A builder used to create and run a merge insert operation
///
/// See [`super::Table::merge_insert`] for more context
pub struct MergeInsertBuilder {
    table: Arc<dyn MergeInsert>,
    pub(super) on: Vec<String>,
    pub(super) when_matched_update_all: bool,
    pub(super) when_not_matched_insert_all: bool,
    pub(super) when_not_matched_by_source_delete: bool,
    pub(super) when_not_matched_by_source_delete_filt: Option<String>,
}

impl MergeInsertBuilder {
    pub(super) fn new(table: Arc<dyn MergeInsert>, on: Vec<String>) -> Self {
        Self {
            table,
            on,
            when_matched_update_all: false,
            when_not_matched_insert_all: false,
            when_not_matched_by_source_delete: false,
            when_not_matched_by_source_delete_filt: None,
        }
    }

    /// Rows that exist in both the source table (new data) and
    /// the target table (old data) will be updated, replacing
    /// the old row with the corresponding matching row.
    ///
    /// If there are multiple matches then the behavior is undefined.
    /// Currently this causes multiple copies of the row to be created
    /// but that behavior is subject to change.
    pub fn when_matched_update_all(&mut self) -> &mut Self {
        self.when_matched_update_all = true;
        self
    }

    /// Rows that exist only in the source table (new data) should
    /// be inserted into the target table.
    pub fn when_not_matched_insert_all(&mut self) -> &mut Self {
        self.when_not_matched_insert_all = true;
        self
    }

    /// Rows that exist only in the target table (old data) will be
    /// deleted.  An optional condition can be provided to limit what
    /// data is deleted.
    ///
    /// # Arguments
    ///
    /// * `condition` - If None then all such rows will be deleted.
    ///   Otherwise the condition will be used as an SQL filter to
    ///   limit what rows are deleted.
    pub fn when_not_matched_by_source_delete(&mut self, filter: Option<String>) -> &mut Self {
        self.when_not_matched_by_source_delete = true;
        self.when_not_matched_by_source_delete_filt = filter;
        self
    }

    /// Executes the merge insert operation
    ///
    /// Nothing is returned but the [`super::Table`] is updated
    pub async fn execute(self, new_data: Box<dyn RecordBatchReader + Send>) -> Result<()> {
        self.table.clone().do_merge_insert(self, new_data).await
    }
}
