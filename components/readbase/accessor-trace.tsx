/**
 * Which typed accessors ran, and how much of what they returned was used.
 * The model picks among the accessors and narrates what they return; this line
 * is the record of that, and it appears on refusals as well as answers.
 */
export function AccessorTrace({
  accessors,
  result,
}: {
  accessors: string[];
  result: string;
}) {
  return (
    <span className="font-mono text-[10px] tracking-[0.04em] text-muted-foreground">
      read{" "}
      {accessors.map((a, i) => (
        <span key={a}>
          {i > 0 && " · "}
          <b className="font-normal text-primary">{a}</b>
        </span>
      ))}
      {" — "}
      {result}
    </span>
  );
}
