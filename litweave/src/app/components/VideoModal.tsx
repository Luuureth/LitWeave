import { X } from "lucide-react";
import { useEffect } from "react";
import { useLanguage } from "../contexts/LanguageContext";

interface VideoModalProps {
  isOpen: boolean;
  onClose: () => void;
  title: string;
  source: string;
  timestamp?: string;
}

function isPlayableVideo(source: string) {
  return /\.(mp4|webm|ogg|mov)$/i.test(source || "");
}

export function VideoModal({ isOpen, onClose, title, source, timestamp }: VideoModalProps) {
  const { t } = useLanguage();

  useEffect(() => {
    if (isOpen) {
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = "unset";
    }
    return () => {
      document.body.style.overflow = "unset";
    };
  }, [isOpen]);

  if (!isOpen) return null;

  const playable = isPlayableVideo(source);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/75 backdrop-blur-sm" onClick={onClose}>
      <div className="relative w-full max-w-4xl mx-4 bg-card border-2 border-border rounded-sm shadow-2xl overflow-hidden" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-6 py-4 border-b border-border/60 bg-secondary/20">
          <div>
            <h3 className="text-xl text-ink font-serif tracking-wide" style={{ fontWeight: 400 }}>{title}</h3>
            {timestamp && <p className="text-sm text-muted-foreground font-serif mt-1" style={{ fontWeight: 300 }}>{timestamp}</p>}
          </div>
          <button onClick={onClose} className="w-8 h-8 flex items-center justify-center rounded-sm hover:bg-secondary/50 transition-colors">
            <X className="w-5 h-5 text-muted-foreground" strokeWidth={1.5} />
          </button>
        </div>

        <div className="aspect-video bg-black flex items-center justify-center">
          {playable ? (
            <video controls className="w-full h-full" src={source}>
              {t("当前浏览器无法播放该视频。", "This browser cannot play the video.")}
            </video>
          ) : (
            <div className="text-center px-6">
              <p className="text-sm text-muted-foreground font-serif tracking-wide" style={{ fontWeight: 300 }}>
                {t("当前数据源不是可直接播放的视频文件。现存的是场景 JSON 路径，不是 mp4 地址。", "The current source is not a directly playable video file. It is a scene JSON path, not an mp4 URL.")}
              </p>
              <p className="text-xs text-muted-foreground/70 font-serif mt-3 break-all" style={{ fontWeight: 300 }}>{source}</p>
            </div>
          )}
        </div>

        <div className="px-6 py-4 border-t border-border/60 bg-secondary/10">
          <p className="text-xs text-muted-foreground font-serif tracking-wide break-all" style={{ fontWeight: 300 }}>
            {t("来源", "Source")}：{source || t("暂无来源", "No source available")}
          </p>
        </div>
      </div>
    </div>
  );
}
