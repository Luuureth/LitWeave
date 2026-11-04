import { FileQuestion } from "lucide-react";

interface EmptyStateProps {
  message: string;
}

export function EmptyState({ message }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-24 text-center">
      <FileQuestion className="w-16 h-16 text-muted-foreground/20 mb-6" strokeWidth={1.5} />
      <p className="text-sm text-muted-foreground font-serif tracking-wide" style={{ fontWeight: 300 }}>
        {message}
      </p>
    </div>
  );
}
