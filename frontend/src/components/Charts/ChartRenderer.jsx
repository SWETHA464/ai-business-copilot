import { Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { compact, formatValue } from "../../utils/format";

const COLORS = ["#2d5bc4", "#16a085", "#e08e0b", "#c0392b", "#8e44ad", "#2c3e50", "#d35400", "#27ae60"];

/** Renders a chart spec produced by the backend: {type, title, xKey, series:[{key,label}], data, valueFormat}. */
export default function ChartRenderer({ spec }) {
  if (!spec || !Array.isArray(spec.data) || spec.data.length === 0) return null;
  const { type, title, xKey, series = [], data, valueFormat = "currency" } = spec;
  const fmt = (v) => formatValue(v, valueFormat);
  const tick = (v) => (valueFormat === "currency" ? `$${compact(v)}` : valueFormat === "percent" ? `${v}%` : compact(v));

  let body;
  if (type === "pie") {
    const key = series[0]?.key;
    body = (
      <PieChart>
        <Pie data={data} dataKey={key} nameKey={xKey} outerRadius="75%" label={(e) => e[xKey]}>
          {data.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
        </Pie>
        <Tooltip formatter={fmt} />
        <Legend />
      </PieChart>
    );
  } else if (type === "line") {
    body = (
      <LineChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
        <XAxis dataKey={xKey} tick={{ fontSize: 11 }} />
        <YAxis tick={{ fontSize: 11 }} tickFormatter={tick} width={56} />
        <Tooltip formatter={fmt} />
        {series.length > 1 && <Legend />}
        {series.map((s, i) => <Line key={s.key} type="monotone" dataKey={s.key} name={s.label} stroke={COLORS[i % COLORS.length]} strokeWidth={2} dot={false} />)}
      </LineChart>
    );
  } else {
    body = (
      <BarChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
        <XAxis dataKey={xKey} tick={{ fontSize: 11 }} interval={0} angle={data.length > 6 ? -25 : 0} textAnchor={data.length > 6 ? "end" : "middle"} height={data.length > 6 ? 70 : 30} />
        <YAxis tick={{ fontSize: 11 }} tickFormatter={tick} width={56} />
        <Tooltip formatter={fmt} />
        {series.length > 1 && <Legend />}
        {series.map((s, i) => <Bar key={s.key} dataKey={s.key} name={s.label} fill={COLORS[i % COLORS.length]} radius={[3, 3, 0, 0]} />)}
      </BarChart>
    );
  }

  return (
    <figure className="card">
      {title && <figcaption className="mb-2 text-sm font-semibold text-slate-700">{title}</figcaption>}
      <div className="h-64 w-full"><ResponsiveContainer width="100%" height="100%">{body}</ResponsiveContainer></div>
    </figure>
  );
}
