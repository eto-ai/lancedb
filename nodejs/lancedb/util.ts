export type IntoSql = string | number | boolean | null | Date | IntoSql[];

export function toSQL(value: IntoSql): string {
  switch (true) {
    case typeof value === "string":
      return `'${value}'`;
    case typeof value === "number":
      return value.toString();
    case typeof value === "boolean":
      return value ? "TRUE" : "FALSE";
    case value === null:
      return "NULL";
    case value instanceof Date:
      return `'${value.toISOString()}'`;
    case Array.isArray(value):
      return `[${value.map(toSQL).join(", ")}]`;
    default:
      throw new Error(
        `Unsupported value type: ${typeof value} value: (${value})`,
      );
  }
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
