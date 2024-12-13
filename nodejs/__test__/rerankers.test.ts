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

import { RecordBatch } from "apache-arrow";
import * as tmp from "tmp";
import { Connection, Index, Table, connect, makeArrowTable } from "../lancedb";
import { RRFReranker } from "../lancedb/rerankers";

describe("rerankers", function () {
  let tmpDir: tmp.DirResult;
  let conn: Connection;
  let table: Table;

  beforeEach(async () => {
    tmpDir = tmp.dirSync({ unsafeCleanup: true });
    conn = await connect(tmpDir.name);
    table = await conn.createTable("mytable", [
      { vector: [0.1, 0.1], text: "dog" },
      { vector: [0.2, 0.2], text: "cat" },
    ]);
    await table.createIndex("text", {
      config: Index.fts(),
      replace: true,
    });
  });

  it("will query with the custom reranker", async function () {
    const expectedResult = [
      {
        text: "albert",
        // biome-ignore lint/style/useNamingConvention: this is the lance field name
        _relevance_score: 0.99,
      },
    ];
    class MyCustomReranker {
      async rerankHybrid(
        _query: string,
        _vecResults: RecordBatch,
        _ftsResults: RecordBatch,
      ): Promise<RecordBatch> {
        // no reranker logic, just return some static data
        const table = makeArrowTable(expectedResult);
        return table.batches[0];
      }
    }

    let result = await table
      .query()
      .nearestTo([0.1, 0.1])
      .fullTextSearch("dog")
      .rerank(new MyCustomReranker())
      .select(["text"])
      .limit(5)
      .toArray();

    result = JSON.parse(JSON.stringify(result)); // convert StructRow to Object
    expect(result).toEqual([
      {
        text: "albert",
        // biome-ignore lint/style/useNamingConvention: this is the lance field name
        _relevance_score: 0.99,
      },
    ]);
  });

  it("will query with RRFReranker", async function () {
    // smoke test to see if the Rust wrapping Typescript is wired up correctly
    const result = await table
      .query()
      .nearestTo([0.1, 0.1])
      .fullTextSearch("dog")
      .rerank(await RRFReranker.create())
      .select(["text"])
      .limit(5)
      .toArray();

    expect(result).toHaveLength(2);
  });
});
