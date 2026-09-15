import { Cell, Pie, PieChart, Tooltip } from "recharts";

type ColumnStat = { column_id: string; name: string; position: number; count: number };
type Stats = { columns: ColumnStat[]; total: number };

// palette ciclica: con più colonne di quelle elencate, i colori si ripetono
const PALETTE = ["#4c6fe0", "#2fa66a", "#e0974c", "#a9acb6", "#c0392b", "#8e44ad", "#16a085"];

export default function StatusPieChart({ stats }: { stats: Stats }) {
  if (stats.total === 0) {
    return <p style={{ color: "var(--text-secondary)" }}>Nessuna task da mostrare qui.</p>;
  }

  const data = stats.columns
    .filter((c) => c.count > 0)
    .map((c, i) => ({ key: c.column_id, name: c.name, value: c.count, color: PALETTE[i % PALETTE.length] }));

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 24, flexWrap: "wrap" }}>
      <PieChart width={220} height={200}>
        <Pie data={data} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={80}>
          {data.map((d) => (
            <Cell key={d.key} fill={d.color} />
          ))}
        </Pie>
        <Tooltip />
      </PieChart>

      <ul className="pie-legend">
        {data.map((d) => (
          <li key={d.key}>
            <span className="pie-legend-swatch" style={{ background: d.color }} />
            {d.name}: <strong>{d.value}</strong>
          </li>
        ))}
        <li className="pie-legend-total">Totale: {stats.total}</li>
      </ul>
    </div>
  );
}
