type Page = { rows: Record<string, unknown>[]; truncated?: boolean };

const columnKey = (value: string) => value.toLowerCase().replace(/[^a-z0-9]/g, "");
const cellValue = (value: unknown): string => {
  const text = (value == null ? "—" : typeof value === "object" ? JSON.stringify(value) : String(value))
    .replace(/\*\*|`/g, "").trim();
  if (/^-?\d[\d,]*(?:\.\d+)?$/.test(text)) {
    return text.replace(/,/g, "").replace(/\.0+$/, "").replace(/(\.\d*?[1-9])0+$/, "$1");
  }
  return text;
};

/** Match the rows actually rendered, including pages with more results available. */
export function pageAppearsInAnswer(answer: string, page: Page): boolean {
  if (!page.rows.length) return false;
  const lines = answer.split("\n");
  const split = (line: string) => line.trim().replace(/^\||\|$/g, "").split("|").map(value => value.trim());
  const keys = [...new Set(page.rows.flatMap(row => Object.keys(row)))];
  for (let index = 0; index < lines.length - 1; index++) {
    if (!lines[index].trim().startsWith("|") || !/^\s*\|?\s*:?-{2,}/.test(lines[index + 1])) continue;
    const headers = split(lines[index]).map(columnKey);
    if (headers.length !== keys.length || !keys.every(key => headers.includes(columnKey(key)))) continue;
    const rendered: string[][] = [];
    for (let row = index + 2; row < lines.length && lines[row].trim().startsWith("|"); row++) {
      rendered.push(split(lines[row]).map(cellValue));
    }
    if (rendered.length !== page.rows.length) continue;
    const expected = page.rows.map(row => headers.map(header => cellValue(row[keys.find(key => columnKey(key) === header)!])));
    const signatures = (rows: string[][]) => rows.map(row => JSON.stringify(row)).sort();
    if (JSON.stringify(signatures(rendered)) === JSON.stringify(signatures(expected))) return true;
  }
  return false;
}

/** Pagination metadata must not cause the same result rows to render twice. */
export function resultPageDisplay(answer: string, page: Page): "table" | "notice" | "none" {
  if (!pageAppearsInAnswer(answer, page)) return "table";
  const paginationInAnswer = /\bmore records (?:exist|are available)\b[\s\S]*?\bnext page\b/i.test(answer);
  return page.truncated && !paginationInAnswer ? "notice" : "none";
}

