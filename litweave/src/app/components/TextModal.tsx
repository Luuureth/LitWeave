import { X } from "lucide-react";
import { useEffect } from "react";
import { useLanguage } from "../contexts/LanguageContext";

interface TextModalProps {
  isOpen: boolean;
  onClose: () => void;
  source: string;
  title?: string;
  content: string;
}

export function TextModal({ isOpen, onClose, source, title, content }: TextModalProps) {
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

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink/75 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="relative w-full max-w-3xl mx-4 bg-card border-2 border-border rounded-sm shadow-2xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border/60 bg-secondary/20">
          <div>
            {title && (
              <p className="text-sm text-primary/80 font-serif tracking-wide mb-1" style={{ fontWeight: 400 }}>
                {title}
              </p>
            )}
            <h3 className="text-xl text-ink font-serif tracking-wide" style={{ fontWeight: 400 }}>
              {source}
            </h3>
          </div>
          <button
            onClick={onClose}
            className="w-8 h-8 flex items-center justify-center rounded-sm hover:bg-secondary/50 transition-colors"
          >
            <X className="w-5 h-5 text-muted-foreground" strokeWidth={1.5} />
          </button>
        </div>

        {/* Content */}
        <div className="px-8 py-8 max-h-[70vh] overflow-y-auto">
          <div className="bg-secondary/20 border border-border/30 rounded-sm p-6">
            <p className="text-base text-foreground/90 leading-loose tracking-wide font-serif" style={{ fontWeight: 300, textIndent: '2em' }}>
              {content}
            </p>
          </div>
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-border/60 bg-secondary/10">
          <p className="text-xs text-muted-foreground font-serif tracking-wide" style={{ fontWeight: 300 }}>
            {t("来源", "Source")}：{source}
          </p>
        </div>
      </div>
    </div>
  );
}
