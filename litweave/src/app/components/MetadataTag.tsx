import { Link } from "react-router";

interface MetadataTagProps {
  label: string;
  href?: string;
  variant?: "default" | "primary" | "accent";
}

export function MetadataTag({ label, href, variant = "default" }: MetadataTagProps) {
  const baseClass = "px-3 py-1 rounded-sm text-sm inline-block transition-colors";

  const variantClasses = {
    default: "bg-secondary text-secondary-foreground hover:bg-muted",
    primary: "bg-primary/10 text-primary hover:bg-primary/20",
    accent: "bg-accent/30 text-accent-foreground hover:bg-accent/40",
  };

  const className = `${baseClass} ${variantClasses[variant]}`;

  if (href) {
    return (
      <Link to={href} className={className}>
        {label}
      </Link>
    );
  }

  return <span className={className}>{label}</span>;
}
