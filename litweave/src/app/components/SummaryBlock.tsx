interface SummaryBlockProps {
  title: string;
  content: string;
}

export function SummaryBlock({ title, content }: SummaryBlockProps) {
  return (
    <div className="bg-secondary/30 border border-border/40 rounded-sm p-7">
      <h3 className="text-2xl text-ink mb-5 pb-4 border-b border-border/40 font-serif tracking-wide" style={{ fontWeight: 400 }}>
        {title}
      </h3>
      <p className="text-base text-foreground/90 leading-loose tracking-wide" style={{ fontWeight: 300, textIndent: '2em' }}>
        {content}
      </p>
    </div>
  );
}
