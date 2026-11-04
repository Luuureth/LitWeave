import { Outlet } from "react-router";
import { TopNavigation } from "../components/TopNavigation";
import { useLanguage } from "../contexts/LanguageContext";

export function RootLayout() {
  const { t } = useLanguage();
  return (
    <div className="min-h-screen bg-background relative">
      <TopNavigation />
      <main className="max-w-7xl mx-auto px-8 py-12 relative z-10">
        <Outlet />
      </main>

      {/* Footer - minimal and refined */}
      <footer className="border-t border-border/50 bg-background py-12 mt-32">
        <div className="max-w-7xl mx-auto px-8 text-center">
          <div className="flex items-center justify-center gap-4 mb-4">
            <div className="h-px w-16 bg-border"></div>
            <div className="w-1 h-1 bg-primary/50 rounded-full"></div>
            <span className="text-sm text-muted-foreground font-serif tracking-widest" style={{ fontWeight: 300 }}>
              LitWeave
            </span>
            <div className="w-1 h-1 bg-primary/50 rounded-full"></div>
            <div className="h-px w-16 bg-border"></div>
          </div>
          <p className="text-xs text-muted-foreground/70 tracking-wide" style={{ fontWeight: 300 }}>
            {t("文学知识多模态重构平台 · 学术研究系统", "Multimodal Literary Knowledge Platform · Academic Research System")}
          </p>
        </div>
      </footer>
    </div>
  );
}
