import { CodeBlock } from "@/components/code-block";

/**
 * The SQL the agent actually ran.
 *
 * Given its own dark surface because the translation from the question above it is the thing
 * worth looking at, and because the person who set up the connection wants to check the query
 * is sane before trusting the number under it.
 */
export function SqlBlock({ sql, label = "Query" }: { sql: string; label?: string }) {
  return <CodeBlock code={sql} label={label} copyLabel="SQL" />;
}
