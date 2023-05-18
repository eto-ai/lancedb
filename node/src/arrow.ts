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

import {
  Field,
  Float32,
  List,
  makeBuilder,
  RecordBatchFileWriter,
  Table,
  type Vector,
  vectorFromArray
} from 'apache-arrow'

export function convertToTable (data: Array<Record<string, unknown>>): Table {
  if (data.length === 0) {
    throw new Error('At least one record needs to be provided')
  }

  const columns = Object.keys(data[0])
  const records: Record<string, Vector> = {}

  for (const columnsKey of columns) {
    if (columnsKey === 'vector') {
      const children = new Field<Float32>('item', new Float32())
      const list = new List(children)
      const listBuilder = makeBuilder({
        type: list
      })
      const vectorSize = (data[0].vector as any[]).length
      for (const datum of data) {
        if ((datum[columnsKey] as any[]).length !== vectorSize) {
          throw new Error(`Invalid vector size, expected ${vectorSize}`)
        }

        listBuilder.append(datum[columnsKey])
      }
      records[columnsKey] = listBuilder.finish().toVector()
    } else {
      const values = []
      for (const datum of data) {
        values.push(datum[columnsKey])
      }
      records[columnsKey] = vectorFromArray(values)
    }
  }

  return new Table(records)
}

export async function fromRecordsToBuffer (data: Array<Record<string, unknown>>): Promise<Buffer> {
  const table = convertToTable(data)
  const writer = RecordBatchFileWriter.writeAll(table)
  return Buffer.from(await writer.toUint8Array())
}
