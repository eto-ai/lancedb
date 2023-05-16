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

<<<<<<<< HEAD:node/examples/ts/src/index.ts
import * as vectordb from 'vectordb';

async function example () {
    const db = await vectordb.connect('data/sample-lancedb')

    const data = [
        { id: 1, vector: [0.1, 0.2], price: 10 },
        { id: 2, vector: [1.1, 1.2], price: 50 }
    ]

    const table = await db.createTable('vectors', data)
    console.log(await db.tableNames())

    const results = await table
        .search([0.1, 0.3])
        .limit(20)
        .execute()
    console.log(results)
}

example().then(_ => { console.log ("All done!") })
========
let nativeLib;

if (process.platform === "darwin" && process.arch === "arm64") {
    nativeLib = require('./darwin_arm64.node')
} else if (process.platform === "linux" && process.arch === "x64") {
    nativeLib = require('./linux-x64.node')
} else {
    throw new Error(`vectordb: unsupported platform ${process.platform}_${process.arch}. Please file a bug report at https://github.com/lancedb/lancedb/issues`)
}

module.exports = nativeLib
>>>>>>>> gsilvestrin/nodejs_linux_1:node/native.js
