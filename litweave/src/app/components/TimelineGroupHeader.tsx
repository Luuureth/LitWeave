interface TimelineGroupHeaderProps {
  period: string;
  year?: string;
}

export function TimelineGroupHeader({ period, year }: TimelineGroupHeaderProps) {
  return (
    <div className="relative flex items-center gap-4 mb-8 mt-6">
      <div className="inline-flex items-center gap-3 font-serif">
        <div className="w-2 h-2 bg-primary rounded-full"></div>
        <span className="text-xl text-ink tracking-wide" style={{ fontWeight: 400 }}>
          {period}
        </span>
        {year && (
          <span className="text-sm text-foreground/60 tracking-wide" style={{ fontWeight: 400 }}>
            {year}
          </span>
        )}
      </div>
      <div className="flex-1 h-px bg-gradient-to-r from-border to-transparent"></div>
    </div>
  );
}
