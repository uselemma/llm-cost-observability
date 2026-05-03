const HAS_TIMEZONE_SUFFIX = /(?:Z|[+-]\d{2}:\d{2})$/i;

export function parseApiTimestamp(value: string): Date {
  const normalized = value.trim();
  if (!normalized) return new Date(Number.NaN);
  // ClickHouse DateTime/DateTime64 values may come back without timezone info.
  // Treat timezone-less values as UTC so local rendering is correct.
  const input = HAS_TIMEZONE_SUFFIX.test(normalized) ? normalized : `${normalized}Z`;
  return new Date(input);
}
