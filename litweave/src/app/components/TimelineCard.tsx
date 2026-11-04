import { Link } from "react-router";
import { Calendar, Users, MapPin } from "lucide-react";

interface TimelineCardProps {
  id: string;
  title: string;
  canonicalTitle?: string;
  time: string;
  characters?: string[];
  locations?: string[];
  summary: string;
}

export function TimelineCard({
  id,
  title,
  canonicalTitle,
  time,
  characters = [],
  locations = [],
  summary
}: TimelineCardProps) {
  return (
    <Link to={`/events/${id}`}>
      <div className="relative pl-8 pb-6 group">
        {/* Timeline marker - more refined */}
        <div className="absolute left-0 top-3 w-3 h-3 border-2 border-primary bg-background rounded-full z-10 group-hover:bg-primary group-hover:scale-110 transition-all"></div>
        <div className="absolute left-1 top-6 w-px h-full bg-border/60 group-hover:bg-border transition-colors"></div>

        <div className="bg-card border border-border/60 hover:border-primary/40 hover:bg-secondary/10 rounded-sm p-5 transition-all relative">
          <div className="flex items-start justify-between mb-3">
            <div className="flex-1">
              <h3 className="text-xl text-ink mb-1.5 group-hover:text-primary transition-colors font-serif tracking-wide" style={{ fontWeight: 400 }}>
                {title}
              </h3>
              {canonicalTitle && (
                <p className="text-sm text-muted-foreground font-serif tracking-wide" style={{ fontWeight: 300 }}>
                  《{canonicalTitle}》
                </p>
              )}
            </div>
            <div className="flex items-center gap-1.5 text-xs text-foreground/70 ml-6 flex-shrink-0">
              <Calendar className="w-3.5 h-3.5" strokeWidth={1.5} />
              <span className="font-serif tracking-wide" style={{ fontWeight: 400 }}>{time}</span>
            </div>
          </div>

          <p className="text-sm text-foreground/80 mb-3 leading-relaxed tracking-wide" style={{ fontWeight: 300 }}>
            {summary}
          </p>

          <div className="flex gap-6 text-sm pt-3 border-t border-border/30">
            {characters.length > 0 && (
              <div className="flex items-center gap-2 text-muted-foreground">
                <Users className="w-4 h-4" strokeWidth={1.5} />
                <span className="font-serif tracking-wide" style={{ fontWeight: 300 }}>
                  {characters.join("、")}
                </span>
              </div>
            )}
            {locations.length > 0 && (
              <div className="flex items-center gap-2 text-muted-foreground">
                <MapPin className="w-4 h-4" strokeWidth={1.5} />
                <span className="font-serif tracking-wide" style={{ fontWeight: 300 }}>
                  {locations.join("、")}
                </span>
              </div>
            )}
          </div>
        </div>
      </div>
    </Link>
  );
}
