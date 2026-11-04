import { BookOpen, ChevronLeft, ChevronRight, Video } from "lucide-react";
import { useEffect, useState } from "react";
import { VideoPreviewCard } from "./VideoPreviewCard";
import { VideoModal } from "./VideoModal";
import { TextModal } from "./TextModal";
import { useLanguage } from "../contexts/LanguageContext";
import { Button } from "./ui/button";

interface Evidence {
  source: string;
  content: string;
  title?: string;
  timestamp?: string;
  videoSourcePath?: string;
  playableVideoUrl?: string;
}

interface EvidencePanelProps {
  type: "text" | "video";
  evidence: Evidence[];
}

export function EvidencePanel({ type, evidence }: EvidencePanelProps) {
  const [selectedVideo, setSelectedVideo] = useState<Evidence | null>(null);
  const [selectedText, setSelectedText] = useState<Evidence | null>(null);
  const [currentIndex, setCurrentIndex] = useState(0);
  const { t } = useLanguage();
  const Icon = type === "text" ? BookOpen : Video;
  const title = type === "text" ? t("文本呈现", "Text Presentation") : t("视频呈现", "Video Presentation");

  useEffect(() => {
    setCurrentIndex(0);
  }, [type]);

  useEffect(() => {
    setCurrentIndex((prev) => {
      if (evidence.length === 0) return 0;
      if (prev < evidence.length) return prev;
      return 0;
    });
  }, [evidence.length]);

  if (type === "video") {
    const totalVideos = evidence.length;
    const safeIndex = totalVideos === 0 ? 0 : ((currentIndex % totalVideos) + totalVideos) % totalVideos;
    const currentVideo = evidence[safeIndex];
    const progressPercent = totalVideos > 0 ? ((safeIndex + 1) / totalVideos) * 100 : 0;

    const goPrev = () => {
      if (totalVideos <= 1) return;
      setCurrentIndex((prev) => prev - 1);
    };

    const goNext = () => {
      if (totalVideos <= 1) return;
      setCurrentIndex((prev) => prev + 1);
    };

    return (
      <>
        <div className="bg-card border border-border/60 rounded-sm p-7">
          <div className="flex items-center gap-3 mb-6 pb-5 border-b border-border/40">
            <Icon className="w-5 h-5 text-cinnabar/70" strokeWidth={1.5} />
            <h3 className="text-2xl text-ink font-serif tracking-wide" style={{ fontWeight: 400 }}>{title}</h3>
          </div>

          {currentVideo ? (
            <div>
              <div className="mb-4 flex items-center justify-between gap-4">
                <div className="min-w-0">
                  <span className="text-sm text-muted-foreground font-serif truncate block">《{currentVideo.content}》</span>
                </div>
                {totalVideos > 1 && (
                  <div className="flex items-center gap-2 flex-shrink-0">
                    <Button type="button" variant="outline" size="icon" className="h-9 w-9" onClick={goPrev} aria-label={t("上一条视频", "Previous video")}>
                      <ChevronLeft className="w-4 h-4" />
                    </Button>
                    <Button type="button" variant="outline" size="icon" className="h-9 w-9" onClick={goNext} aria-label={t("下一条视频", "Next video")}>
                      <ChevronRight className="w-4 h-4" />
                    </Button>
                  </div>
                )}
              </div>

              <div className="mb-4">
                <div className="h-2 w-full overflow-hidden rounded-full bg-secondary/60 border border-border/30">
                  <div className="h-full rounded-full bg-primary/70 transition-all duration-300" style={{ width: `${progressPercent}%` }} />
                </div>
              </div>

              <VideoPreviewCard
                thumbnail=""
                videoUrl={currentVideo.playableVideoUrl || currentVideo.videoSourcePath}
                timestamp={currentVideo.timestamp}
                title={currentVideo.source}
                onPlay={() => setSelectedVideo(currentVideo)}
              />

            </div>
          ) : (
            <div className="px-4 py-8 text-sm text-muted-foreground text-center border border-border/30 rounded-sm bg-secondary/10">
              {t("暂无视频内容", "No video content available")}
            </div>
          )}
        </div>

        <VideoModal
          isOpen={!!selectedVideo}
          onClose={() => setSelectedVideo(null)}
          title={selectedVideo?.source || ""}
          source={selectedVideo?.playableVideoUrl || selectedVideo?.videoSourcePath || selectedVideo?.source || ""}
          timestamp={selectedVideo?.timestamp}
        />
      </>
    );
  }

  const totalTexts = evidence.length;
  const safeTextIndex = totalTexts === 0 ? 0 : ((currentIndex % totalTexts) + totalTexts) % totalTexts;
  const currentText = evidence[safeTextIndex];
  const textProgressPercent = totalTexts > 0 ? ((safeTextIndex + 1) / totalTexts) * 100 : 0;

  const goPrevText = () => {
    if (totalTexts <= 1) return;
    setCurrentIndex((prev) => prev - 1);
  };

  const goNextText = () => {
    if (totalTexts <= 1) return;
    setCurrentIndex((prev) => prev + 1);
  };

  return (
    <>
      <div className="bg-card border border-border/60 rounded-sm p-7">
        <div className="flex items-center gap-3 mb-6 pb-5 border-b border-border/40">
          <Icon className="w-5 h-5 text-primary/60" strokeWidth={1.5} />
          <h3 className="text-2xl text-ink font-serif tracking-wide" style={{ fontWeight: 400 }}>{title}</h3>
        </div>

        {currentText ? (
          <div>
            <div className="mb-4 flex items-center justify-between gap-4">
              <div className="min-w-0">
                <span className="block text-sm text-muted-foreground font-serif truncate">《{currentText.source}》</span>
              </div>
              {totalTexts > 1 && (
                <div className="flex items-center gap-2 flex-shrink-0">
                  <Button type="button" variant="outline" size="icon" className="h-9 w-9" onClick={goPrevText} aria-label={t("上一条文本", "Previous text")}>
                    <ChevronLeft className="w-4 h-4" />
                  </Button>
                  <Button type="button" variant="outline" size="icon" className="h-9 w-9" onClick={goNextText} aria-label={t("下一条文本", "Next text")}>
                    <ChevronRight className="w-4 h-4" />
                  </Button>
                </div>
              )}
            </div>

            <div className="mb-4">
              <div className="h-2 w-full overflow-hidden rounded-full bg-secondary/60 border border-border/30">
                <div className="h-full rounded-full bg-primary/70 transition-all duration-300" style={{ width: `${textProgressPercent}%` }} />
              </div>
            </div>

            <div
              className="bg-secondary/30 border border-border/40 rounded-sm p-5 cursor-pointer hover:border-primary/30 hover:bg-secondary/40 transition-all group min-h-[320px]"
              onClick={() => setSelectedText(currentText)}
            >
              <div className="mb-4 pb-3 border-b border-border/30" />
              <p className="text-sm text-foreground/90 leading-loose tracking-wide line-clamp-[10]" style={{ fontWeight: 300, textIndent: '2em' }}>{currentText.content}</p>
              <div className="mt-3 pt-3 border-t border-border/20">
                <span className="text-xs text-muted-foreground group-hover:text-primary/60 transition-colors font-serif" style={{ fontWeight: 300 }}>{t("点击阅读全文", "Click to read full text")} →</span>
              </div>
            </div>
          </div>
        ) : (
          <div className="px-4 py-8 text-sm text-muted-foreground text-center border border-border/30 rounded-sm bg-secondary/10">
            {t("暂无文本内容", "No text content available")}
          </div>
        )}
      </div>

      <TextModal isOpen={!!selectedText} onClose={() => setSelectedText(null)} source={selectedText?.source || ""} title={selectedText?.title || ""} content={selectedText?.content || ""} />
    </>
  );
}
