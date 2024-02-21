/* tslint:disable */
/* eslint-disable */

/* auto-generated by NAPI-RS */

export const enum IndexType {
  Scalar = 0,
  IvfPq = 1
}
export const enum MetricType {
  L2 = 0,
  Cosine = 1,
  Dot = 2
}
export interface ConnectionOptions {
  uri: string
  apiKey?: string
  hostOverride?: string
  /**
   * (For LanceDB OSS only): The interval, in seconds, at which to check for
   * updates to the table from other processes. If None, then consistency is not
   * checked. For performance reasons, this is the default. For strong
   * consistency, set this to zero seconds. Then every read will check for
   * updates from other processes. As a compromise, you can set this to a
   * non-zero value for eventual consistency. If more than that interval
   * has passed since the last check, then the table will be checked for updates.
   * Note: this consistency only applies to read operations. Write operations are
   * always consistent.
   */
  readConsistencyInterval?: number
}
/** Write mode for writing a table. */
export const enum WriteMode {
  Create = 'Create',
  Append = 'Append',
  Overwrite = 'Overwrite'
}
/** Write options when creating a Table. */
export interface WriteOptions {
  mode?: WriteMode
}
export function connect(options: ConnectionOptions): Promise<Connection>
export class Connection {
  /** Create a new Connection instance from the given URI. */
  static new(options: ConnectionOptions): Promise<Connection>
  /** List all tables in the dataset. */
  tableNames(): Promise<Array<string>>
  /**
   * Create table from a Apache Arrow IPC (file) buffer.
   *
   * Parameters:
   * - name: The name of the table.
   * - buf: The buffer containing the IPC file.
   *
   */
  createTable(name: string, buf: Buffer): Promise<Table>
  openTable(name: string): Promise<Table>
  /** Drop table with the name. Or raise an error if the table does not exist. */
  dropTable(name: string): Promise<void>
}
export class IndexBuilder {
  replace(v: boolean): void
  column(c: string): void
  name(name: string): void
  ivfPq(metricType?: MetricType | undefined | null, numPartitions?: number | undefined | null, numSubVectors?: number | undefined | null, numBits?: number | undefined | null, maxIterations?: number | undefined | null, sampleRate?: number | undefined | null): void
  scalar(): void
  build(): Promise<void>
}
/** Typescript-style Async Iterator over RecordBatches  */
export class RecordBatchIterator {
  next(): Promise<Buffer | null>
}
export class Query {
  column(column: string): void
  filter(filter: string): void
  select(columns: Array<string>): void
  limit(limit: number): void
  prefilter(prefilter: boolean): void
  nearestTo(vector: Float32Array): void
  refineFactor(refineFactor: number): void
  nprobes(nprobe: number): void
  executeStream(): Promise<RecordBatchIterator>
}
export class Table {
  /** Return Schema as empty Arrow IPC file. */
  schema(): Promise<Buffer>
  add(buf: Buffer): Promise<void>
  countRows(filter?: string | undefined | null): Promise<bigint>
  delete(predicate: string): Promise<void>
  createIndex(): IndexBuilder
  query(): Query
}
