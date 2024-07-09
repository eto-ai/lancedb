export type IntoSql = string | number | boolean | null | Date | IntoSql[];

export function toSQL(value: IntoSql): string {
  if (typeof value === "string") {
    return `'${value}'`;
  }

  if (typeof value === "number") {
    return value.toString();
  }

  if (typeof value === "boolean") {
    return value ? "TRUE" : "FALSE";
  }

  if (value === null) {
    return "NULL";
  }

  if (value instanceof Date) {
    return `'${value.toISOString()}'`;
  }

  if (Array.isArray(value)) {
    return `[${value.map(toSQL).join(", ")}]`;
  }

  // eslint-disable-next-line @typescript-eslint/restrict-template-expressions
  throw new Error(`Unsupported value type: ${typeof value} value: (${value})`);
}

export class TTLCache {
  // biome-ignore lint/suspicious/noExplicitAny: <explanation>
  private readonly cache: Map<string, { value: any; expires: number }>;

  /**
   * @param ttl Time to live in milliseconds
   */
  constructor(private readonly ttl: number) {
    this.cache = new Map();
  }

  // biome-ignore lint/suspicious/noExplicitAny: <explanation>
  get(key: string): any | undefined {
    const entry = this.cache.get(key);
    if (entry === undefined) {
      return undefined;
    }

    if (entry.expires < Date.now()) {
      this.cache.delete(key);
      return undefined;
    }

    return entry.value;
  }

  // biome-ignore lint/suspicious/noExplicitAny: <explanation>
  set(key: string, value: any): void {
    this.cache.set(key, { value, expires: Date.now() + this.ttl });
  }

  delete(key: string): void {
    this.cache.delete(key);
  }
}
