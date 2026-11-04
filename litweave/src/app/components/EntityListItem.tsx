import { Link } from "react-router";
import { ChevronRight } from "lucide-react";
import { useLanguage } from "../contexts/LanguageContext";

interface EntityListItemProps {
  name: string;
  count: number;
  href: string;
  description?: string;
  image?: string;
}

export function EntityListItem({ name, count, href, description, image }: EntityListItemProps) {
  const { t } = useLanguage();
  return (
    <Link to={href}>
      <div className="bg-card border border-border/60 rounded-sm p-4 hover:border-primary/40 hover:bg-secondary/10 hover:shadow-sm transition-all group">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3 flex-1">
            {/* Avatar/Image Circle */}
            <div className="w-16 h-16 rounded-full bg-secondary/40 border border-border/60 flex-shrink-0 overflow-hidden">
              {image ? (
                <img src={image} alt={name} className="w-full h-full object-cover" />
              ) : (
                <div className="w-full h-full flex items-center justify-center">
                  <span className="text-xl text-primary/30 font-serif" style={{ fontWeight: 300 }}>
                    {name.charAt(0)}
                  </span>
                </div>
              )}
            </div>

            {/* Text Content */}
            <div className="flex-1 min-w-0">
              <h3 className="text-xl text-ink mb-1 group-hover:text-primary transition-colors font-serif tracking-wide" style={{ fontWeight: 400 }}>
                {name}
              </h3>
              {description && (
                <p className="text-sm text-muted-foreground tracking-wide truncate" style={{ fontWeight: 300 }}>
                  {description}
                </p>
              )}
            </div>
          </div>

          <div className="flex items-center gap-3 ml-6 flex-shrink-0">
            <span className="text-xs text-muted-foreground font-serif tracking-wide" style={{ fontWeight: 300 }}>
              {count} {t("个事件", "events")}
            </span>
            <ChevronRight className="w-5 h-5 text-muted-foreground/40 group-hover:text-primary group-hover:translate-x-0.5 transition-all" strokeWidth={1.5} />
          </div>
        </div>
      </div>
    </Link>
  );
}
