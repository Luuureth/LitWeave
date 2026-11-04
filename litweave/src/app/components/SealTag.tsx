import { Link } from "react-router";

interface SealTagProps {
  label: string;
  href?: string;
  variant?: "default" | "seal" | "accent";
}

export function SealTag({ label, href, variant = "default" }: SealTagProps) {
  const baseClass = "px-3 py-1.5 text-sm inline-flex items-center gap-1.5 transition-all font-serif tracking-wide";

  const variantClasses = {
    default: "bg-secondary/50 border border-border/60 text-secondary-foreground hover:bg-secondary rounded-sm",
    seal: "bg-cinnabar-muted/80 text-white hover:bg-cinnabar relative rounded-sm shadow-sm",
    accent: "bg-jade/10 border border-jade/20 text-accent-foreground hover:bg-jade/20 rounded-sm",
  };

  const className = `${baseClass} ${variantClasses[variant]}`;

  const content = (
    <>
      {variant === "seal" && (
        <span className="w-1 h-1 bg-white/60 rounded-full"></span>
      )}
      <span>{label}</span>
    </>
  );

  if (href) {
    return (
      <Link to={href} className={className}>
        {content}
      </Link>
    );
  }

  return <span className={className}>{content}</span>;
}
