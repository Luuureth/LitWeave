import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router";
import { Breadcrumb } from "../components/Breadcrumb";
import { TimelineGroupHeader } from "../components/TimelineGroupHeader";
import { TimelineCard } from "../components/TimelineCard";
import { ClassicalDivider } from "../components/ClassicalDivider";
import { MapPin, Calendar } from "lucide-react";
import { api } from "../lib/api";
import { useLanguage } from "../contexts/LanguageContext";

function chineseNumberToInt(input?: string) {
  const value = String(input || "").trim();
  const map: Record<string, number> = {
    元: 1, 一: 1, 二: 2, 三: 3, 四: 4, 五: 5, 六: 6, 七: 7, 八: 8, 九: 9,
    十: 10, 十一: 11, 十二: 12, 十三: 13, 十四: 14, 十五: 15, 十六: 16, 十七: 17, 十八: 18,
    十九: 19, 二十: 20, 二十一: 21, 二十二: 22, 二十三: 23, 二十四: 24, 二十五: 25, 二十六: 26,
    二十七: 27, 二十八: 28, 二十九: 29, 三十: 30,
  };
  if (map[value] != null) return map[value];
  const match = value.match(/(\d+)/);
  return match ? Number(match[1]) : 0;
}

function seasonRank(season?: string) {
  const s = String(season || "");
  if (!s) return 999;
  if (s.includes("正月")) {
    const dayMatch = s.match(/二十一|二十二|二十三|二十四|二十五|二十六|二十七|二十八|二十九|三十|十一|十二|十三|十四|十五|十六|十七|十八|十九|二十|初一|初二|初三|初四|初五|初六|初七|初八|初九|初十|一|二|三|四|五|六|七|八|九|十/);
    const raw = dayMatch?.[0] || "一";
    const normalized = raw.startsWith("初") ? raw.slice(1) : raw;
    return 100 + chineseNumberToInt(normalized);
  }
  const monthMatch = s.match(/([正一二三四五六七八九十\d]+)月/);
  const monthToken = monthMatch?.[1] === "正" ? "一" : monthMatch?.[1] || "";
  const month = chineseNumberToInt(monthToken);
  const dayMatch = s.match(/月(初一|初二|初三|初四|初五|初六|初七|初八|初九|初十|十一|十二|十三|十四|十五|十六|十七|十八|十九|二十|二十一|二十二|二十三|二十四|二十五|二十六|二十七|二十八|二十九|三十|一|二|三|四|五|六|七|八|九|十)?/);
  const rawDay = dayMatch?.[1] || "";
  const normalizedDay = rawDay.startsWith("初") ? rawDay.slice(1) : rawDay;
  return month ? month * 100 + chineseNumberToInt(normalizedDay) : 999;
}

export function LocationDetail() {
  const { name } = useParams();
  const { t } = useLanguage();
  const [location, setLocation] = useState<any | null>(null);

  useEffect(() => {
    if (!name) return;
    api.locationDetail(decodeURIComponent(name))
      .then(setLocation)
      .catch(() => setLocation(null));
  }, [name]);

  const groups = useMemo(() => {
    if (!location?.events) return [];
    const source = [...location.events].sort((a, b) => {
      const yearDiff = (a.timeline_sort_year || 0) - (b.timeline_sort_year || 0);
      if (yearDiff !== 0) return yearDiff;
      const seasonDiff = (a.timeline_sort_season || seasonRank(a.timeline_season)) - (b.timeline_sort_season || seasonRank(b.timeline_season));
      if (seasonDiff !== 0) return seasonDiff;
      return String(a.display_event_id).localeCompare(String(b.display_event_id), 'zh-Hans-CN');
    });
    const grouped = new Map<string, { period: string; year?: string; sortYear: number; sortSeason: number; events: any[] }>();
    for (const event of source) {
      const sortYear = event.timeline_sort_year || 0;
      const sortSeason = event.timeline_sort_season || seasonRank(event.timeline_season);
      const key = `${sortYear}_${sortSeason}_${event.timeline_year || t("未定年", "Unspecified Year")}__${event.timeline_season || t("未定时序", "Unspecified Season")}`;
      if (!grouped.has(key)) {
        grouped.set(key, {
          period: event.timeline_year || t("未定年", "Unspecified Year"),
          year: event.timeline_season || t("未定时序", "Unspecified Season"),
          sortYear,
          sortSeason,
          events: [],
        });
      }
      grouped.get(key)!.events.push({
        id: event.display_event_id,
        title: event.event_name,
        time: [event.timeline_year, event.timeline_season].filter(Boolean).join(" · ") || t("时间未定", "Time Unspecified"),
        characters: Array.isArray(event.event_characters) ? event.event_characters : [],
        summary: event.summary || event.timeline_ref || t("暂无摘要", "No summary available"),
      });
    }
    return Array.from(grouped.values()).sort((a, b) => {
      if (a.sortYear !== b.sortYear) return a.sortYear - b.sortYear;
      return a.sortSeason - b.sortSeason;
    });
  }, [location, t]);

  if (!location) {
    return <div className="py-16 text-center text-muted-foreground">{t("地点数据加载中或不存在", "Location data is loading or unavailable")}</div>;
  }

  return (
    <div>
      <Breadcrumb items={[{ label: t("首页", "Home"), href: "/" }, { label: t("地点", "Locations"), href: "/locations" }, { label: location.name }]} />
      <div className="bg-card border border-border/60 rounded-sm p-10 mb-12"><div className="flex items-start gap-10"><div className="w-24 h-24 bg-secondary/40 border border-border/60 rounded-full flex items-center justify-center flex-shrink-0"><MapPin className="w-12 h-12 text-primary/70" strokeWidth={1.5} /></div><div className="flex-1"><div className="flex items-baseline gap-4 mb-4"><h1 className="text-5xl text-ink font-serif tracking-wide" style={{ fontWeight: 400 }}>{location.name}</h1></div><p className="text-lg text-muted-foreground mb-8 tracking-wide" style={{ fontWeight: 300 }}>{t("统一事件网络中的地点索引节点", "Location index node in the unified event network")}</p><ClassicalDivider variant="simple" /><div className="grid grid-cols-2 gap-10 mt-6"><div className="flex items-start gap-3"><Calendar className="w-5 h-5 text-primary/60 mt-0.5 flex-shrink-0" strokeWidth={1.5} /><div><div className="text-xs text-muted-foreground mb-2 tracking-wide uppercase" style={{ fontWeight: 300 }}>{t("相关事件", "Related Events")}</div><div className="text-sm text-foreground font-serif tracking-wide" style={{ fontWeight: 300 }}>{location.event_count || 0} {t("个", "items")}</div></div></div><div className="flex items-start gap-3"><Calendar className="w-5 h-5 text-primary/60 mt-0.5 flex-shrink-0" strokeWidth={1.5} /><div><div className="text-xs text-muted-foreground mb-2 tracking-wide uppercase" style={{ fontWeight: 300 }}>{t("时间跨度", "Timeline Span")}</div><div className="text-sm text-foreground font-serif tracking-wide" style={{ fontWeight: 300 }}>{location.first_timeline_sort || "-"} ~ {location.last_timeline_sort || "-"}</div></div></div></div></div></div></div>
      <div className="mb-10"><div className="flex items-center gap-2 mb-3"><div className="w-1 h-1 bg-primary/50 rounded-full"></div><h2 className="text-3xl text-ink font-serif tracking-wide" style={{ fontWeight: 400 }}>{t("地点相关事件时间线", "Location-related Event Timeline")}</h2></div><p className="text-sm text-muted-foreground tracking-wide" style={{ fontWeight: 300 }}>{t("该地点发生或关联的统一事件，按时间顺序排列", "Unified events associated with this location, ordered chronologically")}</p><div className="mt-6 h-px bg-border/40"></div></div>
      <div className="space-y-12">{groups.map((group: any, index: number) => <div key={index}><TimelineGroupHeader period={group.period} year={group.year} /><div className="space-y-0">{group.events.map((event: any) => <TimelineCard key={event.id} {...event} />)}</div></div>)}</div>
    </div>
  );
}
