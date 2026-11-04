interface PageHeaderProps {
  title: string;
  subtitle?: string;
  decoration?: boolean;
}

export function PageHeader({ title, subtitle, decoration = true }: PageHeaderProps) {
  return (
    <div className="mb-10">
      {/* Minimal top decoration */}
      {decoration && (
        <div className="flex items-center gap-2 mb-4">
          <div className="w-1 h-1 bg-primary rounded-full"></div>
          <div className="h-px flex-1 bg-border max-w-xs"></div>
        </div>
      )}

      <h1 className="text-5xl text-ink tracking-wider font-serif mb-3" style={{ fontWeight: 400 }}>
        {title}
      </h1>

      {subtitle && (
        <p className="text-sm text-muted-foreground tracking-wide" style={{ fontWeight: 300 }}>
          {subtitle}
        </p>
      )}

      {decoration && (
        <div className="mt-5 h-px bg-gradient-to-r from-border to-transparent max-w-2xl"></div>
      )}
    </div>
  );
}
