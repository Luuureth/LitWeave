import { Link, useLocation } from "react-router";
import { useLanguage } from "../contexts/LanguageContext";
import { Languages } from "lucide-react";

export function TopNavigation() {
  const location = useLocation();
  const { language, setLanguage, t } = useLanguage();

  const navItems = [
    { path: "/", label: t("首页", "Home") },
    { path: "/events", label: t("事件", "Events") },
    { path: "/characters", label: t("人物", "Characters") },
    { path: "/locations", label: t("地点", "Locations") },
  ];

  const isActive = (path: string) => {
    if (path === "/") {
      return location.pathname === "/";
    }
    return location.pathname.startsWith(path);
  };

  return (
    <nav className="border-b border-border bg-card/80 backdrop-blur-sm relative">
      <div className="max-w-7xl mx-auto px-8 py-6 flex items-center gap-16 relative z-10">
        <Link to="/" className="flex items-center gap-4 group">
          {/* Minimal logo mark */}
          <div className="w-8 h-8 border border-primary/30 rounded-full flex items-center justify-center group-hover:border-primary/50 transition-colors">
            <div className="w-2 h-2 bg-primary rounded-full"></div>
          </div>

          <div>
            <span className="text-2xl tracking-widest text-ink font-serif block" style={{ fontWeight: 400 }}>
              LitWeave
            </span>
            <span className="text-xs text-muted-foreground tracking-wider" style={{ fontWeight: 300 }}>
              {t("文学知识编织", "Literary Knowledge Weaving")}
            </span>
          </div>
        </Link>

        <div className="flex gap-8 ml-auto items-center">
          {navItems.map((item) => (
            <Link
              key={item.path}
              to={item.path}
              className={`px-1 py-1 transition-all font-serif tracking-wide relative ${
                isActive(item.path)
                  ? "text-primary"
                  : "text-muted-foreground hover:text-foreground"
              }`}
              style={{ fontWeight: 400 }}
            >
              {item.label}
              {isActive(item.path) && (
                <div className="absolute -bottom-1 left-0 right-0 h-px bg-primary"></div>
              )}
            </Link>
          ))}
          
          {/* Language Switcher */}
          <button
            onClick={() => setLanguage(language === "zh" ? "en" : "zh")}
            className="flex items-center gap-2 px-3 py-1.5 text-muted-foreground hover:text-foreground transition-colors border border-border hover:border-primary/30 rounded"
            title={t("切换语言", "Switch Language")}
          >
            <Languages className="w-4 h-4" strokeWidth={1.5} />
            <span className="text-sm font-serif tracking-wide" style={{ fontWeight: 300 }}>
              {language === "zh" ? "EN" : "中"}
            </span>
          </button>
        </div>
      </div>
    </nav>
  );
}