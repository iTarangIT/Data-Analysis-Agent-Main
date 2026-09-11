/**
 * The sign-in hero.
 *
 * One English question, a rule, and the SQL it became. That translation is the product, so it
 * is the thing the page opens with, set at nearly the same optical size in the two faces of
 * one superfamily. No marketing copy, no feature list, no gradient: the demonstration is the
 * argument.
 */

const QUESTION = "Which customers bought the most batteries last quarter?";

// Kept inside about fifty characters a line so the panel never needs a scrollbar. A
// horizontal scrollbar under the hero would undercut the claim that this is the finished
// article.
const SQL = [
  ["SELECT", " c.name, SUM(oi.quantity) AS units"],
  ["FROM", " orders o"],
  ["JOIN", " order_items oi ON oi.order_id = o.id"],
  ["JOIN", " customers c ON c.id = o.customer_id"],
  ["WHERE", " o.placed_at >= date_trunc('quarter', now())"],
  ["GROUP BY", " 1"],
  ["ORDER BY", " 2 DESC"],
  ["LIMIT", " 500"],
] as const;

export function AuthHero() {
  return (
    <div className="on-ground hidden flex-col justify-between gap-10 overflow-y-auto bg-ground p-10 lg:flex lg:p-14">
      <p className="font-mono text-sm tracking-tight text-ground-muted">analyst</p>

      <div className="max-w-[46ch]">
        <p className="text-[1.75rem] leading-[1.25] font-normal text-ground-ink">{QUESTION}</p>

        <div className="my-7 h-px w-full bg-rule-ground" />

        <pre className="font-mono text-[0.9375rem] leading-[1.7] text-ground-ink">
          <code>
            {SQL.map(([keyword, rest], i) => (
              // Keyed by position: two lines here begin with JOIN.
              <span key={i} className="block">
                <span className="text-ground-muted">{keyword}</span>
                {rest}
              </span>
            ))}
          </code>
        </pre>
      </div>

      <p className="max-w-[42ch] text-sm leading-relaxed text-ground-muted">
        Every query is checked before it runs, and it only ever reads. You see the SQL, the rows
        it returned, and the answer.
      </p>
    </div>
  );
}
