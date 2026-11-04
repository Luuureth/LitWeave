import { Play } from "lucide-react";

interface VideoPreviewCardProps {
  thumbnail?: string;
  videoUrl?: string;
  duration?: string;
  timestamp?: string;
  title: string;
  onPlay: () => void;
}

export function VideoPreviewCard({
  thumbnail,
  videoUrl,
  duration,
  timestamp,
  title,
  onPlay,
}: VideoPreviewCardProps) {
  return (
    <div
      className="relative bg-secondary/20 border border-border/50 rounded-sm overflow-hidden cursor-pointer group transition-all hover:border-primary/40 hover:shadow-md"
      onClick={onPlay}
    >
      <div className="relative aspect-video bg-gradient-to-br from-secondary/40 to-secondary/60">
        {videoUrl ? (
          <video
            className="w-full h-full object-cover"
            src={videoUrl}
            preload="metadata"
            muted
            playsInline
          />
        ) : thumbnail ? (
          <img src={thumbnail} alt={title} className="w-full h-full object-cover" />
        ) : null}

        <div className="absolute inset-0 bg-ink/10 group-hover:bg-ink/20 transition-colors" />

        <div className="absolute inset-0 flex items-center justify-center">
          <div className="w-16 h-16 rounded-full bg-white border-2 border-white/95 flex items-center justify-center shadow-lg group-hover:bg-white group-hover:scale-110 transition-all">
            <Play className="w-7 h-7 text-black ml-1" fill="currentColor" strokeWidth={0} />
          </div>
        </div>

        {(duration || timestamp) && (
          <div className="absolute bottom-2 right-2 px-2 py-1 bg-ink/85 text-parchment text-xs font-serif rounded-sm">
            {timestamp || duration}
          </div>
        )}
      </div>
    </div>
  );
}
