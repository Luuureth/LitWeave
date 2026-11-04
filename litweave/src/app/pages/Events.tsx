import { useEffect, useMemo, useState } from "react";
import { PageHeader } from "../components/PageHeader";
import { SearchBar } from "../components/SearchBar";
import { TimelineGroupHeader } from "../components/TimelineGroupHeader";
import { TimelineCard } from "../components/TimelineCard";
import { EmptyState } from "../components/EmptyState";
import { useLanguage } from "../contexts/LanguageContext";
import { api } from "../lib/api";

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

export function Events() {
  const [searchQuery, setSearchQuery] = useState("");
  const [events, setEvents] = useState<any[]>([]);
  const { t } = useLanguage();

  useEffect(() => {
    api.events()
      .then(setEvents)
      .catch(() => setEvents([]));
  }, []);

  const filtered = useMemo(() => {
    const q = searchQuery.trim();
    const source = [...events].sort((a, b) => {
      const yearDiff = (a.timeline_sort_year || 0) - (b.timeline_sort_year || 0);
      if (yearDiff !== 0) return yearDiff;
      const seasonDiff = (a.timeline_sort_season || seasonRank(a.timeline_season)) - (b.timeline_sort_season || seasonRank(b.timeline_season));
      if (seasonDiff !== 0) return seasonDiff;
      return String(a.timeline_id || a.display_event_id).localeCompare(String(b.timeline_id || b.display_event_id), 'zh-Hans-CN');
    });
    if (!q) return source;
    return source.filter((event) =>
      [event.event_name, event.summary, event.timeline_ref, ...(event.event_characters || []), ...(event.event_locations || [])]
        .filter(Boolean)
        .some((value) => String(value).includes(q))
    );
  }, [events, searchQuery]);

  const eventGroups = useMemo(() => {
    const grouped = new Map<string, { period: string; year?: string; sortYear: number; sortSeason: number; events: any[] }>();
    for (const event of filtered) {
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
        canonicalTitle: event.canonical_event_name || event.timeline_ref,
        time: [event.timeline_year, event.timeline_season].filter(Boolean).join(" · ") || t("时间未定", "Time Unspecified"),
        characters: Array.isArray(event.event_characters) ? event.event_characters : [],
        locations: Array.isArray(event.event_locations) ? event.event_locations : [],
        summary: event.summary || event.timeline_ref || t("暂无摘要", "No summary available"),
      });
    }
    return Array.from(grouped.values()).sort((a, b) => {
      if (a.sortYear !== b.sortYear) return a.sortYear - b.sortYear;
      return a.sortSeason - b.sortSeason;
    });
  }, [filtered, t]);

  return (
    <div>
      <PageHeader
        title={t("事件", "Events")}
        subtitle={t("基于时间线的文学事件浏览与探索", "Timeline-based literary event browsing and exploration")}
      />

      <div className="mb-6">
        <SearchBar
          placeholder={t("搜索事件、人物、地点...", "Search events, characters, locations...")}
          value={searchQuery}
          onChange={setSearchQuery}
        />
      </div>

      {eventGroups.length === 0 ? (
        <EmptyState message={t("未找到相关事件", "No events found")} />
      ) : (
        <div className="space-y-10">
          {eventGroups.map((group, index) => (
            <div key={index}>
              <TimelineGroupHeader period={group.period} year={group.year} />
              <div className="space-y-0">
                {group.events.map((event) => (
                  <TimelineCard key={event.id} {...event} />
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
