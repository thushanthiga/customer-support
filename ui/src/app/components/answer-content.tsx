import React from "react";
import ReactMarkdown from "react-markdown";

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

/** Render ERP answers and stored history without executing embedded HTML. */
export default function AnswerContent({ text }: { text: string }) {
    const blocks = parseMarkdownBlocks(text);
    return (
        <div className="answer-content">
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
        </div>
    );
}

