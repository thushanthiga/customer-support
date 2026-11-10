import React from "react";
import ReactMarkdown from "react-markdown";
import { resultPageDisplay } from "../lib/result-pages";

export type DataPage = {
    title?: string;
    rows: Record<string, unknown>[];
    truncated?: boolean;
    scope?: Record<string, unknown>;
    read_at?: string;
};

export interface AnswerContentProps {
    text: string;
    dataPages?: DataPage[];
    rows?: Record<string, unknown>[];
}

type Block =
    | { type: "markdown"; content: string }
    | { type: "table"; headers: string[]; rows: string[][] };

function parseMarkdownBlocks(text: string): Block[] {
    const lines = (text || "").split("\n");
    const blocks: Block[] = [];
    let mdBuffer: string[] = [];
    let i = 0;

    const splitCells = (line: string) =>
        line
            .trim()
            .replace(/^\||\|$/g, "")
            .split(/(?<!\\)\|/)
            .map((cell) => cell.replace(/\\\|/g, "|").trim());

    while (i < lines.length) {
        if (
            i + 1 < lines.length &&
            lines[i].trim().startsWith("|") &&
            /^\s*\|?\s*:?-{2,}/.test(lines[i + 1])
        ) {
            if (mdBuffer.length > 0) {
                blocks.push({ type: "markdown", content: mdBuffer.join("\n") });
                mdBuffer = [];
            }
            const headers = splitCells(lines[i]);
            i += 2;
            const rows: string[][] = [];
            while (i < lines.length && lines[i].trim().startsWith("|")) {
                rows.push(splitCells(lines[i]));
                i++;
            }
            blocks.push({ type: "table", headers, rows });
        } else {
            mdBuffer.push(lines[i]);
            i++;
        }
    }
    if (mdBuffer.length > 0) {
        blocks.push({ type: "markdown", content: mdBuffer.join("\n") });
    }
    return blocks;
}

function extractAuditSection(text: string): { mainText: string; auditText: string | null } {
    if (!text) return { mainText: "", auditText: null };

    // Matches divider and header for Technical Execution & Pipeline Audit,
    // including optional <details><summary> wrappers if present.
    const regex = /(?:^|\n)(?:---\s*\n+)?(?:<details[^>]*>\s*\n*(?:<summary[^>]*>[\s\S]*?<\/summary>\s*\n*)?)?###\s+🔍?\s*Technical Execution & Pipeline Audit/i;
    const match = text.match(regex);

    if (!match || match.index === undefined) {
        return { mainText: text, auditText: null };
    }

    const mainText = text.slice(0, match.index).trim();
    let auditText = text.slice(match.index + match[0].length).trim();

    // Clean up any trailing </details> tag if present
    auditText = auditText.replace(/<\/details>\s*$/i, "").trim();

    return { mainText, auditText };
}

function RawResultTable({ page }: { page: DataPage }) {
    const columns = [...new Set(page.rows.flatMap(row => Object.keys(row)))];
    const displayCell = (value: unknown) =>
        value == null ? "—" : typeof value === "object" ? JSON.stringify(value) : String(value);
    const formatCol = (col: string) => col.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());

    return (
        <div className="raw-table-wrapper">
            {page.rows.length ? (
                <div className="table-wrap">
                    <table>
                        <thead>
                            <tr>
                                {columns.map(key => (
                                    <th key={key}>{formatCol(key)}</th>
                                ))}
                            </tr>
                        </thead>
                        <tbody>
                            {page.rows.map((row, index) => (
                                <tr key={index}>
                                    {columns.map(key => (
                                        <td key={key}>{displayCell(row[key])}</td>
                                    ))}
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            ) : (
                <p className="muted">No records in this result.</p>
            )}
            {page.truncated && (
                <small className="result-pagination">More records are available. Ask for the next page.</small>
            )}
        </div>
    );
}

function BlocksRenderer({ blocks }: { blocks: Block[] }) {
    return (
        <>
            {blocks.map((block, idx) =>
                block.type === "table" ? (
                    <div className="table-wrap" key={idx}>
                        <table>
                            <thead>
                                <tr>
                                    {block.headers.map((h, hIdx) => (
                                        <th key={hIdx}>{h}</th>
                                    ))}
                                </tr>
                            </thead>
                            <tbody>
                                {block.rows.map((row, rIdx) => (
                                    <tr key={rIdx}>
                                        {block.headers.map((_, cIdx) => (
                                            <td key={cIdx}>{row[cIdx] ?? ""}</td>
                                        ))}
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                ) : (
                    <ReactMarkdown
                        key={idx}
                        skipHtml
                        components={{
                            table: ({ children }) => (
                                <div className="table-wrap">
                                    <table>{children}</table>
                                </div>
                            ),
                            a: ({ href, children }) => (
                                <a href={href} target="_blank" rel="noopener noreferrer">
                                    {children}
                                </a>
                            ),
                        }}
                    >
                        {block.content}
                    </ReactMarkdown>
                )
            )}
        </>
    );
}

/** Render ERP answers and stored history without executing embedded HTML. */
export default function AnswerContent({ text, dataPages, rows }: AnswerContentProps) {
    const { mainText, auditText } = extractAuditSection(text);
    const mainBlocks = parseMarkdownBlocks(mainText);
    const mainHasTable = mainBlocks.some(b => b.type === "table");

    // Collect candidate data pages
    const candidatePages: DataPage[] = [];
    if (dataPages && dataPages.length > 0) {
        candidatePages.push(...dataPages);
    } else if (rows && rows.length > 0) {
        candidatePages.push({ rows });
    }

    // Filter to pages that do not already appear in the main synthesized text
    const unrenderedPages = candidatePages.filter(
        page => page.rows && page.rows.length > 0 && resultPageDisplay(mainText, page) === "table"
    );

    // If main text has no table at all, the first unrendered page serves as the primary visual table
    let primaryPage: DataPage | null = null;
    let dropdownPages: DataPage[] = unrenderedPages;
    if (!mainHasTable && unrenderedPages.length > 0) {
        primaryPage = unrenderedPages[0];
        dropdownPages = unrenderedPages.slice(1);
    }

    const hasRawPages = dropdownPages.length > 0;
    const hasAccordion = Boolean(auditText || hasRawPages);

    const accordionTitle = hasRawPages
        ? "Technical Execution & Query Details"
        : "Technical Execution & Pipeline Audit";

    const rawPagesBadge = hasRawPages
        ? dropdownPages.map((p, idx) => {
            if (p.title) {
                const clean = p.title.replace(/\s*\([^)]*\)/, "").trim();
                return clean || `Result ${idx + 1}`;
            }
            return `Result ${idx + 1}`;
        }).join(", ")
        : null;

    return (
        <div className="answer-content">
            <BlocksRenderer blocks={mainBlocks} />

            {primaryPage && (
                <div className="primary-result-table">
                    {primaryPage.title && <h3>{primaryPage.title}</h3>}
                    <RawResultTable page={primaryPage} />
                </div>
            )}

            {hasAccordion && (
                <details className="audit-accordion">
                    <summary className="audit-summary">
                        <span className="audit-summary-left">
                            <span className="audit-icon">🔍</span>
                            <span className="audit-title">{accordionTitle}</span>
                            {rawPagesBadge && (
                                <span
                                    className="audit-badge"
                                    title={dropdownPages.map(p => p.title).filter(Boolean).join(" | ")}
                                >
                                    {rawPagesBadge}
                                </span>
                            )}
                        </span>
                        <span className="audit-pill">Click to expand</span>
                    </summary>
                    <div className="audit-content">
                        {hasRawPages && (
                            <div className="audit-raw-section">
                                <h4 className="audit-section-heading">
                                    <span className="audit-section-icon">📊</span>
                                    <span>Detailed Records</span>
                                </h4>
                                <p className="audit-section-desc">
                                    Individual operational records retrieved to evaluate this request:
                                </p>
                                {dropdownPages.map((page, pIdx) => (
                                    <div key={pIdx} className="raw-result-block">
                                        {page.title && <h5 className="raw-result-title">{page.title}</h5>}
                                        <RawResultTable page={page} />
                                    </div>
                                ))}
                                {auditText && <hr className="audit-divider" />}
                            </div>
                        )}

                        {auditText && (
                            <div className="audit-pipeline-section">
                                <h4 className="audit-section-heading">
                                    <span className="audit-section-icon">🔍</span>
                                    <span>Technical Execution & Pipeline Audit</span>
                                </h4>
                                <BlocksRenderer blocks={parseMarkdownBlocks(auditText)} />
                            </div>
                        )}
                    </div>
                </details>
            )}
        </div>
    );
}
