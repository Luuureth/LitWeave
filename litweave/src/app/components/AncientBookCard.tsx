import { ReactNode } from "react";

interface AncientBookCardProps {
  children: ReactNode;
  variant?: "default" | "elevated";
  className?: string;
}

export function AncientBookCard({ children, variant = "default", className = "" }: AncientBookCardProps) {
  return (
    <div
      className={`
        bg-card border-2 border-border rounded-sm relative
        ${variant === "elevated" ? "shadow-lg" : ""}
        ${className}
      `}
      style={{
        backgroundImage: `
          linear-gradient(to right, rgba(201, 190, 168, 0.1) 1px, transparent 1px),
          linear-gradient(to bottom, rgba(201, 190, 168, 0.05) 1px, transparent 1px)
        `,
        backgroundSize: '20px 20px',
      }}
    >
      {/* Corner decorations */}
      <div className="absolute top-0 left-0 w-4 h-4 border-t-2 border-l-2 border-primary/20"></div>
      <div className="absolute top-0 right-0 w-4 h-4 border-t-2 border-r-2 border-primary/20"></div>
      <div className="absolute bottom-0 left-0 w-4 h-4 border-b-2 border-l-2 border-primary/20"></div>
      <div className="absolute bottom-0 right-0 w-4 h-4 border-b-2 border-r-2 border-primary/20"></div>

      <div className="relative z-10">
        {children}
      </div>
    </div>
  );
}
