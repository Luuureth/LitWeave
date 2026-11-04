import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router";
import { Breadcrumb } from "../components/Breadcrumb";
import { SealTag } from "../components/SealTag";
import { EvidencePanel } from "../components/EvidencePanel";
import { ClassicalDivider } from "../components/ClassicalDivider";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "../components/ui/accordion";
import { Calendar, Users, MapPin, BookOpen } from "lucide-react";
import { useLanguage } from "../contexts/LanguageContext";
import { api } from "../lib/api";

export function EventDetail() {
  const { linkId } = useParams();
  const { t } = useLanguage();
  const [event, setEvent] = useState<any | null>(null);

  useEffect(() => {
    if (!linkId) return;
    api.eventDetail(linkId)
      .then(setEvent)
      .catch(() => setEvent(null));
  }, [linkId]);

  const textEvidence = useMemo(() => {
    if (!event) return [];
    const rep = event.representative_text || {};
    const all = Array.isArray(event.all_text_scenes) ? event.all_text_scenes : [];

    const normalized = all
      .filter((item: any) => item?.scene_summary)
      .map((item: any) => ({
        source: item.chapter_title || item.scene_name || t("文本片段", "Text Fragment"),
        title: item.scene_name || t("文本片段", "Text Fragment"),
        content: item.scene_summary,
      }));

    const deduped = normalized.filter(
      (item: any, index: number, array: any[]) =>
        index === array.findIndex((candidate: any) => candidate.source === item.source && candidate.content === item.content)
    );

    if (deduped.length > 0) {
      return deduped;
    }

    return [
      {
        source: rep.chapter_title || rep.scene_name || t("文本场景", "Text Scene"),
        title: rep.scene_name || t("文本场景", "Text Scene"),
        content: rep.scene_summary || event.summary || t("暂无文本摘要", "No text summary available"),
      },
    ].filter((item) => item.content);
  }, [event, t]);

  const videoEvidence = useMemo(() => {
    if (!event) return [];
    const rep = event.representative_video || {};
    const all = Array.isArray(event.all_video_scenes) ? event.all_video_scenes : [];

    const normalized = all
      .filter((item: any) => item && (item.video_source_path || item.source_path || item.scene_summary))
      .map((item: any) => ({
        source: event.event_name || item.episode_title || item.scene_name || t("视频片段", "Video Fragment"),
        content: item.episode_title || item.scene_name || t("暂无视频来源", "No video source available"),
        timestamp: item.scene_id || undefined,
        videoSourcePath: item.video_source_path || item.source_path || "",
        playableVideoUrl: item.playable_video_url || "",
      }));

    const deduped = normalized.filter(
      (item: any, index: number, array: any[]) =>
        index ===
        array.findIndex(
          (candidate: any) =>
            candidate.videoSourcePath === item.videoSourcePath &&
            candidate.timestamp === item.timestamp
        )
    );

    if (deduped.length > 0) {
      return deduped;
    }

    return [
      {
        source: event.event_name || rep.episode_title || rep.scene_name || t("视频场景", "Video Scene"),
        content: rep.episode_title || rep.scene_name || t("暂无视频来源", "No video source available"),
        timestamp: rep.scene_id || undefined,
        videoSourcePath: rep.video_source_path || rep.source_path || "",
        playableVideoUrl: rep.playable_video_url || "",
      },
    ].filter((item) => item.videoSourcePath || item.content);
  }, [event, t]);

  if (!event) {
    return <div className="py-16 text-center text-muted-foreground">{t("事件数据加载中或不存在", "Event data is loading or unavailable")}</div>;
  }

  return (
    <div>
      <Breadcrumb items={[{ label: t("首页", "Home"), href: "/" }, { label: t("事件", "Events"), href: "/events" }, { label: event.event_name }]} />
      <div className="bg-card border border-border/60 rounded-sm p-10 mb-12">
        <div className="flex items-start justify-between mb-8">
          <div className="flex-1">
            <h1 className="text-5xl text-ink mb-4 font-serif tracking-wide" style={{ fontWeight: 400 }}>{event.event_name}</h1>
            <p className="text-xl text-muted-foreground font-serif tracking-wide" style={{ fontWeight: 300 }}>{event.canonical_event_name || event.timeline_ref || t("统一事件节点", "Unified Event Node")}</p>
          </div>
          <div className="ml-8 px-4 py-2 bg-cinnabar-muted/10 text-cinnabar border border-cinnabar/20 rounded-sm">
            <span className="text-sm font-serif tracking-wide" style={{ fontWeight: 400 }}>{event.timeline_id || t("未定时间线", "Timeline Unspecified")}</span>
          </div>
        </div>
        <ClassicalDivider variant="simple" />
        <div className="grid grid-cols-3 gap-10 mb-8">
          <div className="flex items-start gap-3"><Calendar className="w-5 h-5 text-primary/60 mt-1 flex-shrink-0" strokeWidth={1.5} /><div><div className="text-xs text-muted-foreground mb-2 tracking-wide uppercase" style={{ fontWeight: 300 }}>{t("时间", "TIME")}</div><div className="text-sm text-foreground font-serif tracking-wide" style={{ fontWeight: 300 }}>{[event.timeline_year, event.timeline_season].filter(Boolean).join(" · ") || t("时间未定", "Time Unspecified")}</div></div></div>
          <div className="flex items-start gap-3"><Users className="w-5 h-5 text-primary/60 mt-1 flex-shrink-0" strokeWidth={1.5} /><div><div className="text-xs text-muted-foreground mb-3 tracking-wide uppercase" style={{ fontWeight: 300 }}>{t("相关人物", "CHARACTERS")}</div><div className="flex gap-2 flex-wrap">{(event.event_characters || []).map((char: string) => <SealTag key={char} label={char} href={`/characters/${encodeURIComponent(char)}`} variant="default" />)}</div></div></div>
          <div className="flex items-start gap-3"><MapPin className="w-5 h-5 text-primary/60 mt-1 flex-shrink-0" strokeWidth={1.5} /><div><div className="text-xs text-muted-foreground mb-3 tracking-wide uppercase" style={{ fontWeight: 300 }}>{t("相关地点", "LOCATIONS")}</div><div className="flex gap-2 flex-wrap">{(event.event_locations || []).map((loc: string) => <SealTag key={loc} label={loc} href={`/locations/${encodeURIComponent(loc)}`} variant="accent" />)}</div></div></div>
        </div>
        <ClassicalDivider variant="double" />
        <div className="pt-6"><div className="flex items-center gap-3 mb-5"><BookOpen className="w-5 h-5 text-primary/60" strokeWidth={1.5} /><h3 className="text-2xl text-ink font-serif tracking-wide" style={{ fontWeight: 400 }}>{t("事件概要", "Event Summary")}</h3></div><p className="text-base text-foreground/90 leading-loose tracking-wide" style={{ fontWeight: 300, textIndent: "2em" }}>{event.summary || event.timeline_event_name || t("暂无事件摘要", "No event summary available")}</p></div>
      </div>
      <div className="mb-8"><div className="flex items-center gap-2 mb-2"><div className="w-1 h-1 bg-primary/50 rounded-full"></div><h2 className="text-3xl text-ink font-serif tracking-wide" style={{ fontWeight: 400 }}>{t("事件多模态呈现", "Event Multimodal Presentation")}</h2></div><p className="text-sm text-muted-foreground tracking-wide ml-3" style={{ fontWeight: 300 }}>{t("展示同一事件在文本与视频中的对应内容", "Display corresponding content of the same event in text and video")}</p><div className="mt-6 h-px bg-border/40"></div></div>
      <div className="grid grid-cols-2 gap-8"><EvidencePanel type="text" evidence={textEvidence} /><EvidencePanel type="video" evidence={videoEvidence} /></div>
      <div className="mt-10"><Accordion type="single" collapsible><AccordionItem value="more"><AccordionTrigger>{t("更多对应片段", "More Corresponding Fragments")}</AccordionTrigger><AccordionContent><div className="grid grid-cols-2 gap-6"><div><h4 className="mb-3 font-medium">{t("全部文本片段", "All Text Fragments")}</h4><ul className="space-y-3">{(Array.isArray(event.all_text_scenes) ? event.all_text_scenes : []).map((item: any, idx: number) => <li key={idx} className="text-sm text-muted-foreground">{item.chapter_title || item.scene_name || "-"}：{item.scene_summary || t("无摘要", "No summary")}</li>)}</ul></div><div><h4 className="mb-3 font-medium">{t("全部视频片段", "All Video Fragments")}</h4><ul className="space-y-3">{(Array.isArray(event.all_video_scenes) ? event.all_video_scenes : []).map((item: any, idx: number) => <li key={idx} className="text-sm text-muted-foreground break-all">{item.episode_title || item.scene_name || "-"}：{item.scene_summary || t("无摘要", "No summary")}{item.video_source_path ? ` (${item.video_source_path})` : ""}</li>)}</ul></div></div></AccordionContent></AccordionItem></Accordion></div>
    </div>
  );
}
