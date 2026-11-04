import fs from 'fs/promises';
import path from 'path';
import { fileURLToPath } from 'url';
import { pool } from './db.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const root = path.resolve(__dirname, '..', '..');
const eventsPath = path.join(root, '跨模态事件对齐与事件时间线构建', 'timeline_outputs', 'matched_events_with_timeline.json');
const manualReviewPath = path.join(__dirname, 'display_events_manual_review.json');

const MANUAL_TIMELINE_RULES = {
  风雨夕闷制风雨词: {
    timeline_id: 'TL054',
    timeline_year: '红楼十三年',
    timeline_season: '九月',
    timeline_event_name: '风雨夕闷制风雨词',
    timeline_ref: 'TL054 风雨夕闷制风雨词',
    timeline_status: 'aligned',
  },
  黛玉葬花: {
    timeline_id: 'TL031',
    timeline_year: '红楼十三年',
    timeline_season: '四月二十六',
    timeline_event_name: '黛玉葬花',
    timeline_ref: 'TL031 黛玉葬花',
    timeline_status: 'aligned',
  },
  金钏之死: {
    timeline_id: 'TL034',
    timeline_year: '红楼十三年',
    timeline_season: '五月初四',
    timeline_event_name: '金钏之死',
    timeline_ref: 'TL034 金钏之死',
    timeline_status: 'aligned',
  },
  宝玉挨打: {
    timeline_id: 'TL038',
    timeline_year: '红楼十三年',
    timeline_season: '五月初四',
    timeline_event_name: '宝玉挨打',
    timeline_ref: 'TL038 宝玉挨打',
    timeline_status: 'aligned',
  },
  听曲文宝玉悟禅机: {
    timeline_id: 'TL_SUPP_BAOYU_WUCHANJI',
    timeline_year: '红楼十三年',
    timeline_season: '正月内（约正月二十一前后）',
    timeline_event_name: '听曲文宝玉悟禅机',
    timeline_ref: '时间线补充节点',
    timeline_status: 'supplemental',
  },
  宝黛共读西厢: {
    timeline_id: 'TL030A',
    timeline_year: '红楼十三年',
    timeline_season: '四月二十六前后',
    timeline_event_name: '宝黛共读西厢',
    timeline_ref: '时间线补充节点',
    timeline_status: 'supplemental',
  },
};

function normalizeKey(value) {
  const v = String(value || '').trim();
  return v && v !== 'unknown' && v !== 'Unknown' ? v : '';
}

function normalizeText(value) {
  return String(value || '').replace(/\s+/g, '').trim();
}

function containsAny(text, keywords) {
  const normalized = normalizeText(text);
  return keywords.some((keyword) => normalized.includes(normalizeText(keyword)));
}

function chineseNumberToInt(input = '') {
  const value = String(input || '').trim();
  if (!value) return null;
  const directMap = {
    元: 1,
    一: 1,
    二: 2,
    三: 3,
    四: 4,
    五: 5,
    六: 6,
    七: 7,
    八: 8,
    九: 9,
    十: 10,
    十一: 11,
    十二: 12,
    十三: 13,
    十四: 14,
    十五: 15,
    十六: 16,
    十七: 17,
    十八: 18,
    十九: 19,
    二十: 20,
    二十一: 21,
    二十二: 22,
    二十三: 23,
    二十四: 24,
    二十五: 25,
    二十六: 26,
    二十七: 27,
    二十八: 28,
    二十九: 29,
    三十: 30,
  };
  if (directMap[value] != null) return directMap[value];
  const digitMatch = value.match(/(\d+)/);
  if (digitMatch) return Number(digitMatch[1]);
  return null;
}

function extractChineseSegment(source = '', token = '年') {
  const value = String(source || '');
  const index = value.indexOf(token);
  if (index === -1) return '';
  const prefix = value.slice(0, index);
  const match = prefix.match(/([元一二三四五六七八九十百零\d]+)$/);
  return match ? match[1] : '';
}

function yearOrder(year = '') {
  const numeric = chineseNumberToInt(extractChineseSegment(year, '年'));
  if (numeric != null) return numeric;
  const m = String(year).match(/(\d+)/);
  return m ? Number(m[1]) : 0;
}

function seasonOrder(season = '') {
  const s = String(season || '');
  if (!s) return 999;
  if (s.includes('正月')) {
    const day = chineseNumberToInt(extractChineseSegment(s, '前后')) || chineseNumberToInt(extractChineseSegment(s, '左右')) || chineseNumberToInt(extractChineseSegment(s, '日')) || chineseNumberToInt(extractChineseSegment(s, '前')) || 1;
    return 100 + day;
  }
  const monthMatch = s.match(/([正一二三四五六七八九十冬腊元\d]+)月/);
  const monthToken = monthMatch?.[1] || '';
  const normalizedMonthToken = monthToken === '正' ? '一' : monthToken;
  const month = chineseNumberToInt(normalizedMonthToken);
  if (month != null) {
    const dayTokenMatch = s.match(/月([初十廿卅元一二三四五六七八九十\d]+)/);
    const dayToken = dayTokenMatch?.[1] || '';
    let day = 0;
    if (dayToken.startsWith('初')) day = chineseNumberToInt(dayToken.slice(1)) || 0;
    else if (dayToken.startsWith('廿')) day = 20 + (chineseNumberToInt(dayToken.slice(1)) || 0);
    else if (dayToken.startsWith('卅')) day = 30;
    else day = chineseNumberToInt(dayToken) || 0;
    return month * 100 + day;
  }
  if (s.includes('冬末')) return 1100;
  if (s.includes('冬季')) return 1200;
  if (s.includes('秋冬')) return 1300;
  return 999;
}

function sortKey(item) {
  return `${item.timeline_sort_year || 0}-${String(item.timeline_sort_season || 99).padStart(2, '0')}`;
}

function extractSummaryText(item) {
  return [item?.text?.scene_summary, item?.video?.scene_summary, item?.timeline_event_name, item?.event_name].filter(Boolean).join(' ');
}

function applyManualCorrections(item) {
  const corrected = JSON.parse(JSON.stringify(item));
  let canonical = corrected.canonical_event_name || corrected.event_name || '';
  const summaryText = extractSummaryText(corrected);

  if (canonical === '金钏之死' && containsAny(summaryText, ['贾政痛打宝玉', '宝玉挨打', '贾政笞挞宝玉', '痛打宝玉'])) {
    canonical = '宝玉挨打';
  }

  if (canonical === '黛玉葬花' && containsAny(summaryText, ['共读西厢', '宝黛共读西厢', '西厢'])) {
    canonical = '宝黛共读西厢';
  }

  corrected.canonical_event_name = canonical || corrected.canonical_event_name;
  corrected.event_name = canonical || corrected.event_name;

  const timelineRule = MANUAL_TIMELINE_RULES[canonical];
  if (timelineRule) {
    corrected.timeline_id = timelineRule.timeline_id;
    corrected.timeline_year = timelineRule.timeline_year;
    corrected.timeline_season = timelineRule.timeline_season;
    corrected.timeline_event_name = timelineRule.timeline_event_name;
    corrected.timeline_ref = timelineRule.timeline_ref;
    corrected.timeline_status = timelineRule.timeline_status;
    corrected.timeline_sort_year = yearOrder(timelineRule.timeline_year);
    corrected.timeline_sort_season = seasonOrder(timelineRule.timeline_season);
  } else {
    corrected.timeline_sort_year = yearOrder(corrected.timeline_year);
    corrected.timeline_sort_season = seasonOrder(corrected.timeline_season);
  }

  return corrected;
}

function buildDisplayKey(item) {
  const kb = normalizeKey(item.kb_event_id);
  const timeline = normalizeKey(item.timeline_id);
  const canonical = normalizeKey(item.canonical_event_name);
  if (kb && timeline) return `${kb}__${timeline}`;
  if (timeline && canonical) return `${canonical}__${timeline}`;
  if (kb) return `${kb}__${timeline || canonical || item.event_name || item.link_id}`;
  if (canonical) return canonical;
  return item.link_id;
}

function uniqueArray(values) {
  return Array.from(new Set((values || []).filter(Boolean)));
}

function chooseBestScene(scenes, type) {
  return [...scenes].sort((a, b) => {
    const summaryScoreA = a.scene_summary ? 1 : 0;
    const summaryScoreB = b.scene_summary ? 1 : 0;
    if (summaryScoreA !== summaryScoreB) return summaryScoreB - summaryScoreA;
    if ((b.member_count || 0) !== (a.member_count || 0)) return (b.member_count || 0) - (a.member_count || 0);
    const fieldA = type === 'text' ? (a.chapter_title || '') : (a.episode_title || '');
    const fieldB = type === 'text' ? (b.chapter_title || '') : (b.episode_title || '');
    const sourcePathA = type === 'text' ? (a.source_path || '') : (a.video_source_path || a.source_path || '');
    const sourcePathB = type === 'text' ? (b.source_path || '') : (b.video_source_path || b.source_path || '');
    return (fieldB.length + sourcePathB.length) - (fieldA.length + sourcePathA.length);
  })[0] || null;
}

function summarize(displayEvent) {
  const base = displayEvent.timeline_event_name || displayEvent.canonical_event_name || displayEvent.event_name || '事件';
  const pieces = [base];
  const text = displayEvent.representative_text_json?.scene_summary;
  const video = displayEvent.representative_video_json?.scene_summary;
  if (text) pieces.push(text.replace(/\s+/g, ' ').slice(0, 56));
  if (video && video !== text) pieces.push(video.replace(/\s+/g, ' ').slice(0, 56));
  return pieces.filter(Boolean).join('；').slice(0, 150);
}

function parseScene(scene, mediaType) {
  if (!scene) return null;
  return {
    ...scene,
    media_type: mediaType,
  };
}

function buildManualVideoOverrideMap(items) {
  const map = new Map();
  for (const item of items) {
    const key = `${item.display_event_id || ''}::${item.timeline_id || ''}`;
    map.set(key, {
      representative_video_json: item.representative_video || null,
      all_video_scenes_json: Array.isArray(item.all_video_scenes) ? item.all_video_scenes : [],
    });
  }
  return map;
}

async function loadManualVideoOverrideMap() {
  try {
    const raw = await fs.readFile(manualReviewPath, 'utf-8');
    const items = JSON.parse(raw);
    if (!Array.isArray(items)) return new Map();
    return buildManualVideoOverrideMap(items);
  } catch (error) {
    if (error && error.code === 'ENOENT') {
      return new Map();
    }
    throw error;
  }
}

async function main() {
  const raw = await fs.readFile(eventsPath, 'utf-8');
  const items = JSON.parse(raw).map(applyManualCorrections);
  const manualVideoOverrides = await loadManualVideoOverrideMap();
  const grouped = new Map();

  for (const item of items) {
    const key = buildDisplayKey(item);
    if (!grouped.has(key)) grouped.set(key, []);
    grouped.get(key).push(item);
  }

  const displayEvents = [];

  for (const [key, group] of grouped.entries()) {
    const sorted = [...group].sort((a, b) => sortKey(a).localeCompare(sortKey(b)));
    const first = sorted[0];
    const textScenes = sorted.map((x) => parseScene(x.text, 'text')).filter(Boolean);
    const videoScenes = sorted.map((x) => parseScene(x.video, 'video')).filter(Boolean);
    const chars = uniqueArray(sorted.flatMap((x) => x.event_characters || x.shared?.characters || []));
    const locs = uniqueArray(sorted.flatMap((x) => x.event_locations || x.shared?.locations || []));
    const repText = chooseBestScene(textScenes, 'text');
    const repVideo = chooseBestScene(videoScenes, 'video');
    const displayEvent = {
      display_event_id: `display_${key.replace(/[^a-zA-Z0-9_-]/g, '_')}`,
      kb_event_id: first.kb_event_id || null,
      event_name: first.event_name || first.canonical_event_name || first.timeline_event_name || null,
      canonical_event_name: first.canonical_event_name || null,
      timeline_id: first.timeline_id || null,
      timeline_year: first.timeline_year || null,
      timeline_season: first.timeline_season || null,
      timeline_event_name: first.timeline_event_name || null,
      timeline_ref: first.timeline_ref || null,
      timeline_status: first.timeline_status || null,
      timeline_sort_year: yearOrder(first.timeline_year),
      timeline_sort_season: seasonOrder(first.timeline_season),
      representative_text_json: repText,
      representative_video_json: repVideo,
      all_text_scenes_json: textScenes,
      all_video_scenes_json: videoScenes,
      all_link_ids_json: sorted.map((x) => x.link_id),
      matched_link_count: sorted.length,
      text_scene_count: uniqueArray(textScenes.map((x) => x.scene_id || x.scene_name || JSON.stringify(x))).length,
      video_scene_count: uniqueArray(videoScenes.map((x) => x.scene_id || x.scene_name || JSON.stringify(x))).length,
      event_characters_json: chars,
      event_locations_json: locs,
    };
    const overrideKey = `${displayEvent.display_event_id || ''}::${displayEvent.timeline_id || ''}`;
    const videoOverride = manualVideoOverrides.get(overrideKey);
    if (videoOverride) {
      displayEvent.representative_video_json = videoOverride.representative_video_json;
      displayEvent.all_video_scenes_json = videoOverride.all_video_scenes_json;
      displayEvent.video_scene_count = uniqueArray(
        displayEvent.all_video_scenes_json.map((x) => x.scene_id || x.scene_name || JSON.stringify(x))
      ).length;
    }
    displayEvent.summary = summarize(displayEvent);
    displayEvents.push(displayEvent);
  }

  const conn = await pool.getConnection();
  try {
    await conn.beginTransaction();
    await conn.query('DELETE FROM display_event_character_relations');
    await conn.query('DELETE FROM display_event_location_relations');
    await conn.query('DELETE FROM display_events');

    for (const item of displayEvents) {
      await conn.query(
        `INSERT INTO display_events (
          display_event_id, kb_event_id, event_name, canonical_event_name, summary, timeline_id, timeline_year, timeline_season,
          timeline_event_name, timeline_ref, timeline_status, timeline_sort_year, timeline_sort_season,
          event_characters_json, event_locations_json, representative_text_json, representative_video_json,
          all_text_scenes_json, all_video_scenes_json, all_link_ids_json, matched_link_count
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)` ,
        [
          item.display_event_id,
          item.kb_event_id,
          item.event_name,
          item.canonical_event_name,
          item.summary,
          item.timeline_id,
          item.timeline_year,
          item.timeline_season,
          item.timeline_event_name,
          item.timeline_ref,
          item.timeline_status,
          item.timeline_sort_year,
          item.timeline_sort_season,
          JSON.stringify(item.event_characters_json || []),
          JSON.stringify(item.event_locations_json || []),
          JSON.stringify(item.representative_text_json || null),
          JSON.stringify(item.representative_video_json || null),
          JSON.stringify(item.all_text_scenes_json || []),
          JSON.stringify(item.all_video_scenes_json || []),
          JSON.stringify(item.all_link_ids_json || []),
          item.matched_link_count,
        ]
      );
      const [[row]] = await conn.query('SELECT id FROM display_events WHERE display_event_id = ?', [item.display_event_id]);
      for (const name of item.event_characters_json || []) {
        await conn.query('INSERT INTO characters (name, display_name) VALUES (?, ?) ON DUPLICATE KEY UPDATE display_name=VALUES(display_name)', [name, name]);
        const [[c]] = await conn.query('SELECT id FROM characters WHERE name = ?', [name]);
        await conn.query('INSERT IGNORE INTO display_event_character_relations (display_event_id, character_id) VALUES (?, ?)', [row.id, c.id]);
      }
      for (const name of item.event_locations_json || []) {
        await conn.query('INSERT INTO locations (name, display_name) VALUES (?, ?) ON DUPLICATE KEY UPDATE display_name=VALUES(display_name)', [name, name]);
        const [[l]] = await conn.query('SELECT id FROM locations WHERE name = ?', [name]);
        await conn.query('INSERT IGNORE INTO display_event_location_relations (display_event_id, location_id) VALUES (?, ?)', [row.id, l.id]);
      }
    }

    await conn.query(`
      UPDATE characters c
      JOIN (
        SELECT r.character_id, COUNT(DISTINCT r.display_event_id) AS cnt,
               MIN(de.timeline_sort_year * 100 + de.timeline_sort_season) AS min_sort,
               MAX(de.timeline_sort_year * 100 + de.timeline_sort_season) AS max_sort
        FROM display_event_character_relations r
        JOIN display_events de ON de.id = r.display_event_id
        GROUP BY r.character_id
      ) x ON x.character_id = c.id
      SET c.event_count = x.cnt, c.first_timeline_sort = x.min_sort, c.last_timeline_sort = x.max_sort
    `);

    await conn.query(`UPDATE characters SET event_count = 0, first_timeline_sort = 0, last_timeline_sort = 0 WHERE id NOT IN (SELECT DISTINCT character_id FROM display_event_character_relations)`);

    await conn.query(`
      UPDATE locations l
      JOIN (
        SELECT r.location_id, COUNT(DISTINCT r.display_event_id) AS cnt,
               MIN(de.timeline_sort_year * 100 + de.timeline_sort_season) AS min_sort,
               MAX(de.timeline_sort_year * 100 + de.timeline_sort_season) AS max_sort
        FROM display_event_location_relations r
        JOIN display_events de ON de.id = r.display_event_id
        GROUP BY r.location_id
      ) x ON x.location_id = l.id
      SET l.event_count = x.cnt, l.first_timeline_sort = x.min_sort, l.last_timeline_sort = x.max_sort
    `);

    await conn.query(`UPDATE locations SET event_count = 0, first_timeline_sort = 0, last_timeline_sort = 0 WHERE id NOT IN (SELECT DISTINCT location_id FROM display_event_location_relations)`);

    await conn.commit();
    const rawCount = items.length;
    const displayCount = displayEvents.length;
    console.log(`Raw matched events: ${rawCount}`);
    console.log(`Display events: ${displayCount}`);
    console.log(`Deduplicated ${rawCount - displayCount} duplicated scene links`);
    for (const [key, group] of grouped.entries()) {
      console.log(`${key}: ${group.length}`);
    }
  } catch (err) {
    await conn.rollback();
    throw err;
  } finally {
    conn.release();
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
