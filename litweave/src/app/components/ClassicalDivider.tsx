interface ClassicalDividerProps {
  variant?: "cloud" | "simple" | "double";
}

export function ClassicalDivider({ variant = "simple" }: ClassicalDividerProps) {
  if (variant === "cloud") {
    return (
      <div className="flex items-center gap-3 my-8">
        <div className="flex-1 h-px bg-gradient-to-r from-transparent via-border/50 to-border"></div>
        <svg width="20" height="10" viewBox="0 0 20 10" fill="none" className="text-border">
          <path
            d="M2 5C2 5 4 2 6 2C8 2 8 5 10 5C12 5 12 2 14 2C16 2 18 5 18 5"
            stroke="currentColor"
            strokeWidth="1"
            fill="none"
          />
        </svg>
        <div className="flex-1 h-px bg-gradient-to-l from-transparent via-border/50 to-border"></div>
      </div>
    );
  }

  if (variant === "double") {
    return (
      <div className="my-6 space-y-2">
        <div className="h-px bg-border/40"></div>
        <div className="h-px bg-border/20"></div>
      </div>
    );
  }

  return (
    <div className="my-6 flex items-center gap-2">
      <div className="w-1 h-1 bg-primary/50 rounded-full"></div>
      <div className="flex-1 h-px bg-border/50"></div>
      <div className="w-1 h-1 bg-primary/50 rounded-full"></div>
    </div>
  );
}
