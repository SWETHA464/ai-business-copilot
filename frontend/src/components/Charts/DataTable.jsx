import { formatCell, titleCase } from "../../utils/format";

/** Generic table. `columns` is a list of header strings, `rows` a list of arrays. */
export default function DataTable({ title, columns, rows, maxHeight = "18rem" }) {
  if (!columns?.length || !rows?.length) return null;
  return (
    <div className="card p-0">
      {title && <div className="border-b border-slate-200 px-4 py-2 text-sm font-semibold text-slate-700">{title}</div>}
      <div className="overflow-auto" style={{ maxHeight }}>
        <table className="min-w-full text-sm">
          <thead className="sticky top-0 bg-slate-50 text-left text-xs uppercase text-slate-500">
            <tr>{columns.map((c) => <th key={c} className="whitespace-nowrap px-3 py-2 font-semibold">{titleCase(c)}</th>)}</tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className="border-t border-slate-100">
                {r.map((v, j) => <td key={j} className="whitespace-nowrap px-3 py-1.5">{formatCell(v)}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** Convenience for the array-of-objects shape returned by the analytics endpoints. */
export function ObjectTable({ title, rows, columns }) {
  if (!rows?.length) return null;
  const cols = columns || Object.keys(rows[0]);
  return <DataTable title={title} columns={cols} rows={rows.map((r) => cols.map((c) => r[c]))} />;
}
