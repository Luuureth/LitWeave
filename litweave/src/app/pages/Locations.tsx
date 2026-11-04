import { useEffect, useMemo, useState } from "react";
import { PageHeader } from "../components/PageHeader";
import { SearchBar } from "../components/SearchBar";
import { EntityListItem } from "../components/EntityListItem";
import { EmptyState } from "../components/EmptyState";
import { useLanguage } from "../contexts/LanguageContext";
import { api } from "../lib/api";

export function Locations() {
  const [searchQuery, setSearchQuery] = useState("");
  const [locations, setLocations] = useState<any[]>([]);
  const { t } = useLanguage();

  useEffect(() => {
    api.locations()
      .then(setLocations)
      .catch(() => setLocations([]));
  }, []);

  const filteredLocations = useMemo(() => {
    const q = searchQuery.trim();
    if (!q) return locations;
    return locations.filter((loc) => String(loc.name).includes(q));
  }, [locations, searchQuery]);

  return (
    <div>
      <PageHeader title={t("地点", "Locations")} subtitle={t("从地点视角浏览相关事件与时间线", "Browse events and timelines from location perspectives")} />
      <div className="mb-6"><SearchBar placeholder={t("搜索地点...", "Search locations...")} value={searchQuery} onChange={setSearchQuery} /></div>
      {filteredLocations.length === 0 ? <EmptyState message={t("未找到相关地点", "No locations found")} /> : <div className="grid grid-cols-1 gap-4">{filteredLocations.map((location) => <EntityListItem key={location.name} name={location.name} count={location.event_count || 0} href={`/locations/${encodeURIComponent(location.name)}`} description={t("地点事件索引节点", "Location event index node")} />)}</div>}
    </div>
  );
}
