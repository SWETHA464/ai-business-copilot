export const money = (v) =>
  v == null || Number.isNaN(Number(v)) ? "-" : new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(Number(v));
export const money2 = (v) =>
  v == null || Number.isNaN(Number(v)) ? "-" : new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(Number(v));
export const num = (v) => (v == null || Number.isNaN(Number(v)) ? "-" : new Intl.NumberFormat("en-US").format(Number(v)));
export const pct = (v) => (v == null || Number.isNaN(Number(v)) ? "-" : `${Number(v).toFixed(1)}%`);
export const compact = (v) => new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(Number(v));

export function formatValue(v, kind = "currency") {
  if (kind === "currency") return money(v);
  if (kind === "percent") return pct(v);
  return num(v);
}

export function formatCell(v) {
  if (v == null) return "-";
  if (typeof v === "number") return Number.isInteger(v) ? num(v) : v.toLocaleString("en-US", { maximumFractionDigits: 2 });
  return String(v);
}

export const dateTime = (iso) => {
  if (!iso) return "";
  const d = new Date(iso.endsWith("Z") || /[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleString();
};

export const bytes = (n) => (n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1048576).toFixed(1)} MB`);

export const titleCase = (s) => String(s).replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
