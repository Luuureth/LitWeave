import { Link } from "react-router";
import { ChevronRight } from "lucide-react";

interface BreadcrumbItem {
  label: string;
  href?: string;
}

interface BreadcrumbProps {
  items: BreadcrumbItem[];
}

export function Breadcrumb({ items }: BreadcrumbProps) {
  return (
    <nav className="flex items-center gap-2 text-sm mb-10 pb-5 border-b border-border/30">
      {items.map((item, index) => (
        <div key={index} className="flex items-center gap-2">
          {index > 0 && <ChevronRight className="w-3.5 h-3.5 text-muted-foreground/30" strokeWidth={1.5} />}
          {item.href ? (
            <Link to={item.href} className="text-primary hover:text-primary/70 transition-colors font-serif tracking-wide" style={{ fontWeight: 300 }}>
              {item.label}
            </Link>
          ) : (
            <span className="text-muted-foreground font-serif tracking-wide" style={{ fontWeight: 300 }}>
              {item.label}
            </span>
          )}
        </div>
      ))}
    </nav>
  );
}
