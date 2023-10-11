// Copyright 2023 Lance Developers.
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

use arrow_array::RecordBatchIterator;
use lance::dataset::optimize::CompactionOptions;
use lance::dataset::{WriteMode, WriteParams};
use lance::io::object_store::ObjectStoreParams;

use crate::arrow::arrow_buffer_to_record_batch;
use neon::prelude::*;
use neon::types::buffer::TypedArray;
use vectordb::Table;

use crate::error::ResultExt;
use crate::{get_aws_creds, get_aws_region, runtime, JsDatabase};

pub(crate) struct JsTable {
    pub table: Table,
}

impl Finalize for JsTable {}

impl From<Table> for JsTable {
    fn from(table: Table) -> Self {
        JsTable { table }
    }
}

impl JsTable {
    pub(crate) fn js_create(mut cx: FunctionContext) -> JsResult<JsPromise> {
        let db = cx
            .this()
            .downcast_or_throw::<JsBox<JsDatabase>, _>(&mut cx)?;
        let table_name = cx.argument::<JsString>(0)?.value(&mut cx);
        let buffer = cx.argument::<JsBuffer>(1)?;
        let (batches, schema) =
            arrow_buffer_to_record_batch(buffer.as_slice(&mut cx)).or_throw(&mut cx)?;

        // Write mode
        let mode = match cx.argument::<JsString>(2)?.value(&mut cx).as_str() {
            "overwrite" => WriteMode::Overwrite,
            "append" => WriteMode::Append,
            "create" => WriteMode::Create,
            _ => {
                return cx.throw_error("Table::create only supports 'overwrite' and 'create' modes")
            }
        };

        let rt = runtime(&mut cx)?;
        let channel = cx.channel();

        let (deferred, promise) = cx.promise();
        let database = db.database.clone();

        let aws_creds = get_aws_creds(&mut cx, 3)?;
        let aws_region = get_aws_region(&mut cx, 6)?;

        let params = WriteParams {
            store_params: Some(ObjectStoreParams::with_aws_credentials(
                aws_creds, aws_region,
            )),
            mode: mode,
            ..WriteParams::default()
        };

        rt.spawn(async move {
            let batch_reader = RecordBatchIterator::new(batches.into_iter().map(Ok), schema);
            let table_rst = database
                .create_table(&table_name, batch_reader, Some(params))
                .await;

            deferred.settle_with(&channel, move |mut cx| {
                let table = table_rst.or_throw(&mut cx)?;
                Ok(cx.boxed(JsTable::from(table)))
            });
        });
        Ok(promise)
    }

    pub(crate) fn js_add(mut cx: FunctionContext) -> JsResult<JsPromise> {
        let js_table = cx.this().downcast_or_throw::<JsBox<JsTable>, _>(&mut cx)?;
        let buffer = cx.argument::<JsBuffer>(0)?;
        let write_mode = cx.argument::<JsString>(1)?.value(&mut cx);
        let (batches, schema) =
            arrow_buffer_to_record_batch(buffer.as_slice(&mut cx)).or_throw(&mut cx)?;
        let rt = runtime(&mut cx)?;
        let channel = cx.channel();
        let mut table = js_table.table.clone();

        let (deferred, promise) = cx.promise();
        let write_mode = match write_mode.as_str() {
            "create" => WriteMode::Create,
            "append" => WriteMode::Append,
            "overwrite" => WriteMode::Overwrite,
            s => return cx.throw_error(format!("invalid write mode {}", s)),
        };
        let aws_creds = get_aws_creds(&mut cx, 2)?;
        let aws_region = get_aws_region(&mut cx, 5)?;

        let params = WriteParams {
            store_params: Some(ObjectStoreParams::with_aws_credentials(
                aws_creds, aws_region,
            )),
            mode: write_mode,
            ..WriteParams::default()
        };

        rt.spawn(async move {
            let batch_reader = RecordBatchIterator::new(batches.into_iter().map(Ok), schema);
            let add_result = table.add(batch_reader, Some(params)).await;

            deferred.settle_with(&channel, move |mut cx| {
                let _added = add_result.or_throw(&mut cx)?;
                Ok(cx.boxed(JsTable::from(table)))
            });
        });
        Ok(promise)
    }

    pub(crate) fn js_count_rows(mut cx: FunctionContext) -> JsResult<JsPromise> {
        let js_table = cx.this().downcast_or_throw::<JsBox<JsTable>, _>(&mut cx)?;
        let rt = runtime(&mut cx)?;
        let (deferred, promise) = cx.promise();
        let channel = cx.channel();
        let table = js_table.table.clone();

        rt.spawn(async move {
            let num_rows_result = table.count_rows().await;

            deferred.settle_with(&channel, move |mut cx| {
                let num_rows = num_rows_result.or_throw(&mut cx)?;
                Ok(cx.number(num_rows as f64))
            });
        });
        Ok(promise)
    }

    pub(crate) fn js_delete(mut cx: FunctionContext) -> JsResult<JsPromise> {
        let js_table = cx.this().downcast_or_throw::<JsBox<JsTable>, _>(&mut cx)?;
        let rt = runtime(&mut cx)?;
        let (deferred, promise) = cx.promise();
        let predicate = cx.argument::<JsString>(0)?.value(&mut cx);
        let channel = cx.channel();
        let mut table = js_table.table.clone();

        rt.spawn(async move {
            let delete_result = table.delete(&predicate).await;

            deferred.settle_with(&channel, move |mut cx| {
                delete_result.or_throw(&mut cx)?;
                Ok(cx.boxed(JsTable::from(table)))
            })
        });
        Ok(promise)
    }

    pub(crate) fn js_cleanup(mut cx: FunctionContext) -> JsResult<JsPromise> {
        let js_table = cx.this().downcast_or_throw::<JsBox<JsTable>, _>(&mut cx)?;
        let rt = runtime(&mut cx)?;
        let (deferred, promise) = cx.promise();
        let table = js_table.table.clone();
        let channel = cx.channel();

        let older_than: i64 = cx
            .argument_opt(0)
            .and_then(|val| val.downcast::<JsNumber, _>(&mut cx).ok())
            .map(|val| val.value(&mut cx) as i64)
            .unwrap_or_else(|| 2 * 7 * 24 * 60); // 2 weeks
        let older_than = chrono::Duration::minutes(older_than);
        let delete_unverified: bool = cx
            .argument_opt(1)
            .and_then(|val| val.downcast::<JsBoolean, _>(&mut cx).ok())
            .map(|val| val.value(&mut cx))
            .unwrap_or_default();

        rt.spawn(async move {
            let stats = table
                .cleanup_old_versions(older_than, Some(delete_unverified))
                .await;

            deferred.settle_with(&channel, move |mut cx| {
                let stats = stats.or_throw(&mut cx)?;

                let output_metrics = JsObject::new(&mut cx);
                let bytes_removed = cx.number(stats.bytes_removed as f64);
                output_metrics.set(&mut cx, "bytesRemoved", bytes_removed)?;

                let old_versions = cx.number(stats.old_versions as f64);
                output_metrics.set(&mut cx, "oldVersions", old_versions)?;

                let output_table = cx.boxed(JsTable::from(table));

                let output = JsObject::new(&mut cx);
                output.set(&mut cx, "metrics", output_metrics)?;
                output.set(&mut cx, "newTable", output_table)?;

                Ok(output)
            })
        });
        Ok(promise)
    }

    pub(crate) fn js_compact(mut cx: FunctionContext) -> JsResult<JsPromise> {
        let js_table = cx.this().downcast_or_throw::<JsBox<JsTable>, _>(&mut cx)?;
        let rt = runtime(&mut cx)?;
        let (deferred, promise) = cx.promise();
        let mut table = js_table.table.clone();
        let channel = cx.channel();

        let js_options = cx.argument::<JsObject>(0)?;
        let mut options = CompactionOptions::default();

        if let Some(target_rows) =
            js_options.get_opt::<JsNumber, _, _>(&mut cx, "targetRowsPerFragment")?
        {
            options.target_rows_per_fragment = target_rows.value(&mut cx) as usize;
        }
        if let Some(max_per_group) =
            js_options.get_opt::<JsNumber, _, _>(&mut cx, "maxRowsPerGroup")?
        {
            options.max_rows_per_group = max_per_group.value(&mut cx) as usize;
        }
        if let Some(materialize_deletions) =
            js_options.get_opt::<JsBoolean, _, _>(&mut cx, "materializeDeletions")?
        {
            options.materialize_deletions = materialize_deletions.value(&mut cx);
        }
        if let Some(materialize_deletions_threshold) =
            js_options.get_opt::<JsNumber, _, _>(&mut cx, "materializeDeletionsThreshold")?
        {
            options.materialize_deletions_threshold =
                materialize_deletions_threshold.value(&mut cx) as f32;
        }
        if let Some(num_threads) = js_options.get_opt::<JsNumber, _, _>(&mut cx, "numThreads")? {
            options.num_threads = num_threads.value(&mut cx) as usize;
        }

        rt.spawn(async move {
            let stats = table.compact_files(options).await;

            deferred.settle_with(&channel, move |mut cx| {
                let stats = stats.or_throw(&mut cx)?;

                let output_metrics = JsObject::new(&mut cx);
                let fragments_removed = cx.number(stats.fragments_removed as f64);
                output_metrics.set(&mut cx, "fragmentsRemoved", fragments_removed)?;

                let fragments_added = cx.number(stats.fragments_added as f64);
                output_metrics.set(&mut cx, "fragmentsAdded", fragments_added)?;

                let files_removed = cx.number(stats.files_removed as f64);
                output_metrics.set(&mut cx, "filesRemoved", files_removed)?;

                let files_added = cx.number(stats.files_added as f64);
                output_metrics.set(&mut cx, "filesAdded", files_added)?;

                let output_table = cx.boxed(JsTable::from(table));

                let output = JsObject::new(&mut cx);
                output.set(&mut cx, "metrics", output_metrics)?;
                output.set(&mut cx, "newTable", output_table)?;

                Ok(output)
            })
        });
        Ok(promise)
    }
}
