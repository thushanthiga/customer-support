export type UsagePhase = {
    phase: string;
    input_tokens: number | null;
    output_tokens: number | null;
    total_tokens: number | null;
    model: string;
    source: string;
};
export type ResponseMetrics = {
    input_tokens: number | null;
    output_tokens: number | null;
    total_tokens: number | null;
    token_source: "provider" | "local" | "not_used" | "unavailable" | "text_count" | "estimated_text";
    model: string;
    confidence: number | null;
    confidence_type: string;
    confidence_basis: string;
    resolved_question?: string;
    is_follow_up?: boolean;
    search_type?: string;
    source_type?: string;
    classification_source?: string;
    classification_reason?: string;
    token_encoding?: string;
    usage_note?: string;
    recorded_model_usage?: { input_tokens: number | null; output_tokens: number | null; total_tokens: number | null; token_source: string };
    usage_complete?: boolean;
    usage_phases?: UsagePhase[];
    grounding_version?: string | null;
    confidence_status?: string;
    grounding_summary?: { supported: number; contradicted: number; unverified: number; total: number } | null;
    claim_support?: {claim: string; status: "supported" | "contradicted" | "unverified"; source_id: string | null; reason: string}[];
    grounding_limitations?: string;
    retention_note?: string;
};

const sourceLabels = {
    provider: "Measured model usage reported by the provider",
    local: "Reported by the local model",
    not_used: "No model call was made for this answer",
    unavailable: "The service did not identify the token usage source",
    text_count: "Counted tokens in the saved question and visible answer; these are not historical model billing counts",
    estimated_text: "Estimated tokens in the saved question and visible answer; these are not historical model billing counts",
};
const searchLabels: Record<string, string> = {database: "Database", document: "Documents / RAG", hybrid: "Database + documents", general: "General", clarification: "Clarification", none: "No source read", unknown: "Not retained"};
const confidenceLabels: Record<string, string> = {evidence: "Source evidence", source_grounding: "Claim-to-source support", item_match: "Item match", verified_rule: "Verified rule", model: "Help relevance"};

export default function AnswerMetrics({ metrics }: { metrics?: ResponseMetrics }) {
    const tokens = (value: number | null | undefined) => typeof value === "number" && Number.isFinite(value) && value >= 0 ? value.toLocaleString("en-US") : "Not reported";
    const score = metrics?.confidence;
    const hasScore = typeof score === "number" && Number.isFinite(score) && score >= 0 && score <= 100;
    const textOnly = metrics?.token_source === "text_count" || metrics?.token_source === "estimated_text";
    return (
        <section className="answer-metrics" aria-label="Answer usage and confidence">
            {metrics?.search_type && <div className="metrics-search"><span>Search: <strong>{searchLabels[metrics.search_type] || metrics.search_type}</strong></span>{metrics.source_type && <span>Source used: <strong>{searchLabels[metrics.source_type] || metrics.source_type}</strong></span>}<span className="metrics-classifier">{metrics.classification_source === "openai" || metrics.token_source === "provider" ? "OpenAI classified" : "Live query"}</span></div>}
            <dl className="metrics-summary">
                <div><dt>Input{textOnly ? " text" : ""} tokens</dt><dd>{tokens(metrics?.input_tokens)}</dd></div>
                <div><dt>Output{textOnly ? " text" : ""} tokens</dt><dd>{tokens(metrics?.output_tokens)}</dd></div>
                <div><dt>Total{textOnly ? " text" : ""} tokens</dt><dd>{tokens(metrics?.total_tokens)}</dd></div>
                <div className="confidence-metric"><dt>Confidence{metrics?.confidence_type === "source_grounding" ? " (source support)" : ""}</dt><dd>{hasScore ? `${score.toFixed(1)}%` : metrics?.confidence_status === "needs_recheck" ? "Recheck needed" : metrics?.confidence_status === "not_applicable" ? "Not applicable" : "Not scored"}</dd></div>
            </dl>
            {textOnly && <p className="metrics-note">{metrics?.token_source === "estimated_text" ? "Estimated text counts" : "Saved-text token counts"} · {metrics?.usage_note || "Historical model usage was not recorded"}</p>}
            {metrics?.token_source === "not_used" && <p className="metrics-note">No model call · Direct answer</p>}
            {metrics?.token_source === "provider" && metrics.usage_complete === false && <p className="metrics-note">Recorded usage subtotal · Additional planning usage was not reported</p>}
            {metrics?.grounding_summary && <p className="metrics-grounding">{metrics.grounding_summary.supported} / {metrics.grounding_summary.total} answer claims supported{metrics.grounding_summary.contradicted > 0 && <span className="claim-warning"> · {metrics.grounding_summary.contradicted} contradict source values</span>}{metrics.grounding_summary.unverified > 0 && <span className="claim-warning"> · {metrics.grounding_summary.unverified} unverified</span>}</p>}
            <details className="metrics-details">
                <summary>Answer details</summary>
                <p>{sourceLabels[metrics?.token_source || "unavailable"]}.</p>
                {metrics?.is_follow_up && metrics.resolved_question && <p>Interpreted follow-up: {metrics.resolved_question}</p>}
                {metrics?.classification_reason && <p>Classification: {metrics.classification_reason}</p>}
                {metrics?.model && <p>Model: {metrics.model}</p>}
                {metrics?.usage_phases && <><p>Model tokens cover classification and query planning. Business rows and answer text are formatted locally.</p><div className="table-wrap"><table><thead><tr><th>Stage</th><th>Input</th><th>Output</th><th>Total</th></tr></thead><tbody>{metrics.usage_phases.map((phase, index) => <tr key={index}><td>{phase.phase === "classification" ? "OpenAI classification" : "Support planning"}</td><td>{tokens(phase.input_tokens)}</td><td>{tokens(phase.output_tokens)}</td><td>{tokens(phase.total_tokens)}</td></tr>)}</tbody></table></div></>}
                {metrics?.usage_note && !textOnly && <p>{metrics.usage_note}</p>}{metrics?.recorded_model_usage?.token_source === "not_used" && <p>Original model usage: 0 input / 0 output tokens (no model call). The values above measure saved text instead.</p>}
                {metrics?.token_encoding && <p>Text tokenizer: {metrics.token_encoding}</p>}
                {hasScore && <p>Confidence type: {confidenceLabels[metrics?.confidence_type || ""] || "Service score"}. This score is not a calibrated probability of correctness.</p>}
                <p>{metrics?.confidence_basis || "No confidence score or supporting explanation is available for this saved answer."}</p>
                {metrics?.retention_note && <p>{metrics.retention_note}</p>}{metrics?.grounding_limitations && <p>{metrics.grounding_limitations}</p>}
                {metrics?.claim_support && metrics.claim_support.length > 0 && <details className="claim-audit"><summary>Inspect {metrics.claim_support.length} answer claims</summary><ol>{metrics.claim_support.map((claim, index) => <li key={index} className={`claim-${claim.status}`}><strong>{claim.status === "supported" ? "Supported" : claim.status === "contradicted" ? "Contradicted" : "Unverified"}</strong><span>{claim.claim}</span><small>{claim.reason}{claim.source_id ? ` Source: ${claim.source_id}` : ""}</small></li>)}</ol></details>}
            </details>
        </section>
    );
}

