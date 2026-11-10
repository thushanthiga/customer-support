type Page = { rows: Record<string, unknown>[]; truncated?: boolean };

const columnKey = (value: string) => (value || "").toLowerCase().replace(/[^a-z0-9]/g, "");

const cellValue = (value: unknown): string => {
  const text = (value == null ? "—" : typeof value === "object" ? JSON.stringify(value) : String(value))
    .replace(/\*\*|`/g, "").trim();
  if (/^-?\d[\d,]*(?:\.\d+)?$/.test(text)) {
    return text.replace(/,/g, "").replace(/\.0+$/, "").replace(/(\.\d*?[1-9])0+$/, "$1");
  }
  return text;
};

const HEADER_KEY_MAP: Record<string, string[]> = {
  item_name: ["productname", "itemname", "product", "item"],
  product_name: ["productname", "itemname", "product", "item"],
  sku: ["sku"],
  uom: ["unit", "uom"],
  uom_id: ["uomid", "unitid"],
  item_id: ["itemid", "productid"],
  party_id: ["partyid"],
  warehouse_id: ["warehouseid"],
  so_number: ["salesorder", "salesorder#", "so", "sonumber"],
  po_number: ["purchaseorder", "purchaseorder#", "po", "ponumber"],
  invoice_number: ["invoice", "invoice#", "invoicenumber"],
  grn_number: ["grn", "grn#", "grnnumber"],
  gin_number: ["gin", "gin#", "ginnumber"],
  grand_total: ["totalamount", "grandtotal", "total"],
  total_sales: ["totalsales", "sales"],
  total_purchase_order_value: ["totalpovalue", "povalue"],
  amount_due: ["amountdue", "dueamount"],
  amount_settled: ["amountpaid", "settledamount"],
  qty_available: ["availablestock", "availableqty", "quantityavailable"],
  qty_on_hand: ["onhandstock", "onhandqty", "quantityonhand"],
  qty_allocated: ["allocatedstock", "allocatedqty"],
  min_stock_level: ["minimumlevel", "minstocklevel", "minimumstock"],
  max_stock_level: ["maximumlevel", "maxstocklevel", "maximumstock"],
  minimum_quantity: ["minimumlevel", "minquantity", "minimumquantity"],
  stock_quantity: ["currentstock", "stockqty", "stockquantity"],
  reorder_point: ["reorderpoint"],
  reorder_qty: ["reorderqty", "reorderquantity"],
  first_name: ["firstname", "first"],
  last_name: ["lastname", "last"],
  total_quantity_demanded: ["unitssold", "totalquantitydemanded", "quantitydemanded"],
  quantity_sold: ["unitssold", "quantitysold"],
  order_count: ["orderscount", "ordercount"],
  latest_order_date: ["latestorderdate"],
  dispatch_quantity: ["dispatchedqty", "dispatchquantity"],
  received_quantity: ["receivedqty", "receivedquantity"],
  unit_price: ["unitprice"],
  warehouse_name: ["warehouse", "warehousename"],
  customer_name: ["customer", "customername"],
  supplier_name: ["supplier", "suppliername"],
  party_name: ["party", "partyname"],
  name: ["name"],
  code: ["code"],
  city: ["city"],
  status: ["status"],
  location_type: ["locationtype"],
  is_active: ["isactive"],
};

function headerMatchesKey(header: string, key: string): boolean {
  const h = columnKey(header);
  const k = columnKey(key);
  if (h === k) return true;
  const synonyms = HEADER_KEY_MAP[key.toLowerCase()];
  if (synonyms && synonyms.includes(h)) return true;
  for (const syns of Object.values(HEADER_KEY_MAP)) {
    if (syns.includes(k) && syns.includes(h)) return true;
  }
  return false;
}

/** Match the rows actually rendered, including pages with more results available. */
export function pageAppearsInAnswer(answer: string, page: Page): boolean {
  if (!page || !page.rows || !page.rows.length) return false;
  const lines = (answer || "").split("\n");
  const split = (line: string) =>
    line
      .trim()
      .replace(/^\||\|$/g, "")
      .split(/(?<!\\)\|/)
      .map((v) => v.replace(/\\\|/g, "|").trim());

  const keys = [...new Set(page.rows.flatMap((row) => Object.keys(row)))];
  const maxRendered = Math.min(page.rows.length, 500);

  for (let index = 0; index < lines.length - 1; index++) {
    if (!lines[index].trim().startsWith("|") || !/^\s*\|?\s*:?-{2,}/.test(lines[index + 1])) continue;
    const rawHeaders = split(lines[index]);
    const rendered: string[][] = [];
    let r = index + 2;
    while (r < lines.length && lines[r].trim().startsWith("|")) {
      rendered.push(split(lines[r]).map(cellValue));
      r++;
    }
    index = r - 1;

    if (!rendered.length) continue;
    if (rendered.length > page.rows.length && rendered.length !== maxRendered) continue;

    // Check if each rendered column can be mapped to a key in page.rows
    const usedKeys = new Set<string>();
    const colKeys: string[] = [];
    let allColumnsMapped = true;

    for (let c = 0; c < rawHeaders.length; c++) {
      const header = rawHeaders[c];
      // 1. Prefer key matching both header name and all row cell values
      let candidateKey = keys.find((key) => {
        if (usedKeys.has(key)) return false;
        if (!headerMatchesKey(header, key)) return false;
        return rendered.every((row, rowIdx) => row[c] === cellValue(page.rows[rowIdx]?.[key]));
      });

      // 2. If no candidate, match header name if non-empty cell values match
      if (!candidateKey) {
        candidateKey = keys.find((key) => {
          if (usedKeys.has(key)) return false;
          if (!headerMatchesKey(header, key)) return false;
          return rendered.every((row, rowIdx) => {
            const expected = cellValue(page.rows[rowIdx]?.[key]);
            return row[c] === expected || (row[c] === "not recorded" && (expected === "—" || expected === ""));
          });
        });
      }

      // 3. Fallback: match by row cell values across all rendered rows
      if (!candidateKey) {
        candidateKey = keys.find((key) => {
          if (usedKeys.has(key)) return false;
          return rendered.every((row, rowIdx) => row[c] === cellValue(page.rows[rowIdx]?.[key]));
        });
      }

      if (candidateKey) {
        usedKeys.add(candidateKey);
        colKeys.push(candidateKey);
      } else {
        allColumnsMapped = false;
        break;
      }
    }

    if (allColumnsMapped && colKeys.length === rawHeaders.length) {
      const expected = page.rows.slice(0, rendered.length).map((row) =>
        colKeys.map((k) => cellValue(row[k]))
      );
      const signatures = (rows: string[][]) => rows.map((row) => JSON.stringify(row)).sort();
      if (JSON.stringify(signatures(rendered)) === JSON.stringify(signatures(expected))) {
        return true;
      }
    }

    // Direct row-subset heuristic check:
    // If each rendered row has values that are a subset of the corresponding page row
    if (rawHeaders.length <= keys.length) {
      const allRowsMatch = rendered.every((renderedRow, rowIdx) => {
        const pageRow = page.rows[rowIdx];
        if (!pageRow) return false;
        const pageVals = keys.map((k) => cellValue(pageRow[k]));
        return renderedRow.every((cell) => pageVals.includes(cell));
      });
      if (allRowsMatch) {
        return true;
      }
    }
  }
  return false;
}

/** Pagination metadata must not cause the same result rows to render twice. */
export function resultPageDisplay(answer: string, page: Page): "table" | "notice" | "none" {
  if (!page || !page.rows || !page.rows.length) return "none";
  if (!pageAppearsInAnswer(answer, page)) return "table";
  const paginationInAnswer = /\bmore records (?:exist|are available)\b[\s\S]*?\bnext page\b/i.test(answer);
  return page.truncated && !paginationInAnswer ? "notice" : "none";
}
