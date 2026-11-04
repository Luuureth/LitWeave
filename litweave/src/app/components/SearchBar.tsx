import { Search } from "lucide-react";

interface SearchBarProps {
  placeholder?: string;
  value: string;
  onChange: (value: string) => void;
}

export function SearchBar({ placeholder = "搜索...", value, onChange }: SearchBarProps) {
  return (
    <div className="relative max-w-2xl">
      <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground/50" strokeWidth={1.5} />
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full pl-12 pr-4 py-3 bg-input-background border border-border/60 rounded-sm focus:outline-none focus:border-primary/50 transition-all font-serif tracking-wide"
        style={{ fontWeight: 300 }}
      />
    </div>
  );
}
