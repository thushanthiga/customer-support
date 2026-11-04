import ReactMarkdown from "react-markdown";

/** Render evidence tables without interpreting HTML embedded in database text. */
export default function AnswerContent({ content }: { content: string }) {
  const lines = content.split("\n");
  const blocks: React.ReactNode[] = [];
  const markdown: string[] = [];
  const flush = () => {
    if (!markdown.length) return;
    blocks.push(<div key={`text-${blocks.length}`} className="space-y-2 [&_h3]:font-semibold [&_h3]:text-indigo-300 [&_ul]:list-disc [&_ul]:pl-4"><ReactMarkdown>{markdown.join("\n")}</ReactMarkdown></div>);
    markdown.length = 0;
  };
  const cells = (line: string) => line.trim().replace(/^\|/, "").replace(/\|$/, "").split(/(?<!\\)\|/).map(v => v.trim().replace(/\\\|/g, "|").replace(/&lt;/g, "<").replace(/&gt;/g, ">"));
  for (let index = 0; index < lines.length; index++) {
    if (lines[index].trim().startsWith("|") && /^\s*\|(?:\s*:?-+:?\s*\|)+\s*$/.test(lines[index + 1] || "")) {
      flush();
      const headers = cells(lines[index]);
      const rows: string[][] = [];
      index += 2;
      while (index < lines.length && lines[index].trim().startsWith("|")) rows.push(cells(lines[index++]));
      index--;
      blocks.push(<div key={`table-${blocks.length}`} className="max-w-full overflow-x-auto rounded border border-slate-700"><table className="w-full border-collapse text-left text-xs"><thead className="bg-slate-800"><tr>{headers.map((h, i) => <th className="whitespace-nowrap p-2" key={i}>{h}</th>)}</tr></thead><tbody>{rows.map((row, i) => <tr className="border-t border-slate-800" key={i}>{headers.map((_, j) => <td className="p-2 align-top" key={j}>{row[j] ?? ""}</td>)}</tr>)}</tbody></table></div>);
    } else markdown.push(lines[index]);
  }
  flush();
  return <div className="min-w-0 space-y-3">{blocks}</div>;
}

export interface DataPage { title: string; rows: Record<string, unknown>[]; truncated: boolean }

export function DownloadPage({ page }: { page: DataPage }) {
  function download() {
    const columns = Object.keys(page.rows[0] || {});
    const value = (input: unknown) => {
      let text = input == null ? "" : typeof input === "object" ? JSON.stringify(input) : String(input);
      // Prevent spreadsheet formula execution when a record starts with =,+,-,@.
      if (/^[=+\-@\t\r]/.test(text)) text = "'" + text;
      return '"' + text.replace(/"/g, '""') + '"';
    };
    const csv = [columns.map(value).join(","), ...page.rows.map(row => columns.map(column => value(row[column])).join(","))].join("\r\n");
    const url = URL.createObjectURL(new Blob(["\ufeff", csv], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a"); link.href = url; link.download = "assistant-records.csv"; link.click();
    URL.revokeObjectURL(url);
  }
  return <button onClick={download} className="mt-2 rounded border border-slate-600 px-2 py-1 text-xs text-indigo-200">Download {page.rows.length} retrieved rows: {page.title}{page.truncated ? " (partial page)" : ""}</button>;
}
