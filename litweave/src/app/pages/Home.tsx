import { Link } from "react-router";
import { Calendar, Users, MapPin, Network, BarChart3 } from "lucide-react";
import { useEffect, useState } from "react";
import { useLanguage } from "../contexts/LanguageContext";
import { api } from "../lib/api";

export function Home() {
  const { t } = useLanguage();
  const [stats, setStats] = useState({
    unifiedEvents: "-",
    characters: "-",
    locations: "-",
    multimodalContents: "-",
    textScenes: "-",
    videoScenes: "-",
  });

  useEffect(() => {
    api.stats()
      .then((data) => {
        setStats({
          unifiedEvents: String(data.unifiedEvents),
          characters: String(data.characters),
          locations: String(data.locations),
          multimodalContents: String(data.multimodalContents),
          textScenes: String(data.textScenes),
          videoScenes: String(data.videoScenes),
        });
      })
      .catch(() => undefined);
  }, []);

  const modules = [
    {
      icon: Calendar,
      title: t("事件", "Events"),
      description: t("时间线视角下的文学事件重构", "Event-centric reconstruction with timeline view"),
      href: "/events",
    },
    {
      icon: Users,
      title: t("人物", "Characters"),
      description: t("从人物视角浏览相关事件与时间线", "Browse events and timelines from character perspectives"),
      href: "/characters",
    },
    {
      icon: MapPin,
      title: t("地点", "Locations"),
      description: t("从地点视角浏览相关事件与时间线", "Browse events and timelines from location perspectives"),
      href: "/locations",
    },
  ];

  const statItems = [
    { label: t("统一事件数", "Unified Events"), value: stats.unifiedEvents },
    { label: t("人物实体数", "Character Entities"), value: stats.characters },
    { label: t("地点实体数", "Location Entities"), value: stats.locations },
    { label: t("文本数量", "Text Scenes"), value: stats.textScenes },
    { label: t("视频数量", "Video Scenes"), value: stats.videoScenes },
    { label: t("多模态内容", "Multimodal Content"), value: stats.multimodalContents },
  ];

  return (
    <div className="relative">
      <div className="mb-16 text-center relative">
        <div className="mb-8 flex items-center justify-center gap-4">
          <div className="h-px w-24 bg-gradient-to-r from-transparent to-border"></div>
          <div className="flex items-center gap-3">
            <div className="w-1.5 h-1.5 bg-primary rounded-full"></div>
            <div className="w-1 h-1 bg-primary/50 rounded-full"></div>
          </div>
          <div className="h-px w-24 bg-gradient-to-l from-transparent to-border"></div>
        </div>

        <h1 className="text-6xl text-ink mb-5 font-serif tracking-wider" style={{ fontWeight: 400 }}>
          LitWeave
        </h1>

        <div className="mb-6">
          <p className="text-3xl text-primary mb-2 font-serif tracking-wider" style={{ fontWeight: 400 }}>
            {t("面向中国经典文学的多模态知识内容重构与呈现平台", "Multimodal Knowledge Reconstruction and Presentation Platform for Classical Chinese Literature")}
          </p>
          <div className="flex items-center justify-center gap-2 mb-4">
            <div className="h-px w-16 bg-border"></div>
            <div className="w-1 h-1 bg-border rounded-full"></div>
            <div className="h-px w-16 bg-border"></div>
          </div>
        </div>

        <p className="text-base text-muted-foreground max-w-3xl mx-auto leading-loose tracking-wide" style={{ fontWeight: 300 }}>
          {t(
            "贯通原著文本与影视内容，以统一事件为核心，重构人物、场景与叙事时间线的知识结构。",
            "Connecting original texts and visual media content, centered on unified events, to reconstruct knowledge structures of characters, scenes, and narrative timelines."
          )}
        </p>
      </div>

      <div className="grid grid-cols-3 gap-12 mb-20">
        {modules.map((module) => {
          const Icon = module.icon;
          return (
            <Link key={module.href} to={module.href}>
              <div className="group h-full">
                <div className="flex items-center gap-2 mb-6">
                  <div className="h-px flex-1 bg-border group-hover:bg-primary/30 transition-colors"></div>
                  <div className="w-1 h-1 bg-primary rounded-full"></div>
                </div>

                <div className="mb-6 flex items-center justify-center">
                  <div className="w-12 h-12 flex items-center justify-center">
                    <Icon className="w-10 h-10 text-primary/70 group-hover:text-primary transition-colors" strokeWidth={1.5} />
                  </div>
                </div>

                <h2 className="text-4xl text-ink mb-4 text-center font-serif tracking-wider group-hover:text-primary transition-colors" style={{ fontWeight: 400 }}>
                  {module.title}
                </h2>

                <p className="text-sm text-muted-foreground text-center leading-relaxed tracking-wide" style={{ fontWeight: 300 }}>
                  {module.description}
                </p>

                <div className="flex items-center gap-2 mt-6">
                  <div className="w-1 h-1 bg-primary/50 rounded-full"></div>
                  <div className="h-px flex-1 bg-border group-hover:bg-primary/30 transition-colors"></div>
                </div>
              </div>
            </Link>
          );
        })}
      </div>

      <div className="mb-20">
        <div className="text-center mb-12">
          <div className="flex items-center justify-center gap-3 mb-4">
            <div className="h-px w-16 bg-border"></div>
            <BarChart3 className="w-5 h-5 text-primary/50" strokeWidth={1.5} />
            <div className="h-px w-16 bg-border"></div>
          </div>
          <h2 className="text-3xl text-ink font-serif tracking-wider mb-3" style={{ fontWeight: 400 }}>
            {t("数据概览", "Data Overview")}
          </h2>
          <p className="text-sm text-muted-foreground tracking-wide" style={{ fontWeight: 300 }}>
            {t("多模态知识库统计", "Multimodal Knowledge Base Statistics")}
          </p>
        </div>

        <div className="grid grid-cols-3 gap-8 max-w-5xl mx-auto">
          {statItems.map((stat, index) => (
            <div key={index} className="text-center">
              <div className="text-4xl text-primary mb-2 font-serif tracking-wider" style={{ fontWeight: 300 }}>
                {stat.value}
              </div>
              <div className="text-xs text-muted-foreground tracking-wide uppercase" style={{ fontWeight: 300 }}>
                {stat.label}
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="max-w-5xl mx-auto">
        <div className="text-center mb-12">
          <div className="flex items-center justify-center gap-3 mb-4">
            <div className="h-px w-16 bg-border"></div>
            <Network className="w-5 h-5 text-primary/50" strokeWidth={1.5} />
            <div className="h-px w-16 bg-border"></div>
          </div>
          <h2 className="text-3xl text-ink font-serif tracking-wider mb-3" style={{ fontWeight: 400 }}>
            {t("知识重构流程", "Knowledge Reconstruction Pipeline")}
          </h2>
          <p className="text-sm text-muted-foreground tracking-wide" style={{ fontWeight: 300 }}>
            {t("多模态叙事知识重构方法论", "A Multimodal Narrative Knowledge Reconstruction Methodology")}
          </p>
        </div>

        <div className="grid grid-cols-4 gap-12">
          {[
            [t("一", "I"), t("识别事件", "Identify Events"), t("从文本与影像中", "From texts and videos,"), t("提取叙事单元", "extract narrative units")],
            [t("二", "II"), t("贯通场景", "Connect Scenes"), t("建立文本与视频", "Establish correspondences"), t("之间的场景对应", "between text and video")],
            [t("三", "III"), t("梳理时间", "Organize Timeline"), t("确定事件在整体", "Determine temporal"), t("叙事中的时间位置", "positions in narrative")],
            [t("四", "IV"), t("派生索引", "Derive Indexes"), t("生成人物与地点", "Generate character and location"), t("的知识浏览入口", "knowledge browsing entries")],
          ].map(([no, title, line1, line2], idx) => (
            <div key={idx} className="text-center">
              <div className="mb-6 flex items-center justify-center">
                <div className="w-10 h-10 border border-primary/30 rounded-full flex items-center justify-center">
                  <span className="text-lg text-primary font-serif" style={{ fontWeight: 300 }}>{no}</span>
                </div>
              </div>
              <h3 className="text-lg text-ink mb-3 font-serif tracking-wide" style={{ fontWeight: 400 }}>{title}</h3>
              <p className="text-xs text-muted-foreground leading-relaxed tracking-wide" style={{ fontWeight: 300 }}>
                {line1}
                <br />
                {line2}
              </p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
