import { useEffect, useMemo, useState } from "react";
import { PageHeader } from "../components/PageHeader";
import { SearchBar } from "../components/SearchBar";
import { EntityListItem } from "../components/EntityListItem";
import { EmptyState } from "../components/EmptyState";
import { useLanguage } from "../contexts/LanguageContext";
import { api } from "../lib/api";

export function Characters() {
  const [searchQuery, setSearchQuery] = useState("");
  const [characters, setCharacters] = useState<any[]>([]);
  const { t } = useLanguage();

  useEffect(() => {
    api.characters()
      .then(setCharacters)
      .catch(() => setCharacters([]));
  }, []);

  const filteredCharacters = useMemo(() => {
    const q = searchQuery.trim();
    if (!q) return characters;
    return characters.filter((char) => String(char.name).includes(q));
  }, [characters, searchQuery]);

  return (
    <div>
      <PageHeader
        title={t("人物", "Characters")}
        subtitle={t("从人物视角浏览相关事件与时间线", "Browse events and timelines from character perspectives")}
      />

      <div className="mb-6">
        <SearchBar
          placeholder={t("搜索人物...", "Search characters...")}
          value={searchQuery}
          onChange={setSearchQuery}
        />
      </div>

      {filteredCharacters.length === 0 ? (
        <EmptyState message={t("未找到相关人物", "No characters found")} />
      ) : (
        <div className="grid grid-cols-1 gap-4">
          {filteredCharacters.map((character) => (
            <EntityListItem
              key={character.name}
              name={character.name}
              count={character.event_count || 0}
              href={`/characters/${encodeURIComponent(character.name)}`}
              description={t("人物事件索引节点", "Character event index node")}
            />
          ))}
        </div>
      )}
    </div>
  );
}
