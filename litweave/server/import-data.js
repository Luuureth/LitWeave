import fs from 'fs/promises';
import path from 'path';
import { fileURLToPath } from 'url';
import { pool } from './db.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const root = path.resolve(__dirname, '..', '..');
const eventsPath = path.join(root, '跨模态事件对齐与事件时间线构建', 'timeline_outputs', 'matched_events_with_timeline.json');

function seasonOrder(season = '') {
  const s = String(season);
  if (s.includes('正月')) return 1;
  if (s.includes('二月')) return 2;
  if (s.includes('三月')) return 3;
  if (s.includes('四月')) return 4;
  if (s.includes('五月')) return 5;
  if (s.includes('六月')) return 6;
  if (s.includes('七月')) return 7;
  if (s.includes('八月')) return 8;
  if (s.includes('九月')) return 9;
  if (s.includes('十月')) return 10;
  if (s.includes('冬末')) return 11;
  if (s.includes('冬季')) return 12;
  if (s.includes('秋冬')) return 13;
  return 99;
}

function yearOrder(year = '') {
  const m = String(year).match(/(\d+)/);
  return m ? Number(m[1]) : 0;
}

async function main() {
  const raw = await fs.readFile(eventsPath, 'utf-8');
  const items = JSON.parse(raw);

  const conn = await pool.getConnection();
  try {
    await conn.beginTransaction();

    for (const item of items) {
      const [timelineRes] = await conn.query(
        `INSERT INTO timeline_nodes (timeline_id, timeline_year, timeline_season, timeline_event_name, timeline_ref, year_order, season_order)
         VALUES (?, ?, ?, ?, ?, ?, ?)
         ON DUPLICATE KEY UPDATE timeline_year=VALUES(timeline_year), timeline_season=VALUES(timeline_season), timeline_event_name=VALUES(timeline_event_name), timeline_ref=VALUES(timeline_ref), year_order=VALUES(year_order), season_order=VALUES(season_order)`,
        [
          item.timeline_id || null,
          item.timeline_year || null,
          item.timeline_season || null,
          item.timeline_event_name || null,
          item.timeline_ref || null,
          yearOrder(item.timeline_year),
          seasonOrder(item.timeline_season),
        ]
      );

      const [eventRes] = await conn.query(
        `INSERT INTO events (link_id, kb_event_id, event_name, canonical_event_name, alignment_score, alignment_type, relation, timeline_id, timeline_year, timeline_season, timeline_event_name, timeline_ref, timeline_status, timeline_sort_year, timeline_sort_season, llm_decision, llm_confidence, llm_reason)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
         ON DUPLICATE KEY UPDATE kb_event_id=VALUES(kb_event_id), event_name=VALUES(event_name), canonical_event_name=VALUES(canonical_event_name), alignment_score=VALUES(alignment_score), alignment_type=VALUES(alignment_type), relation=VALUES(relation), timeline_id=VALUES(timeline_id), timeline_year=VALUES(timeline_year), timeline_season=VALUES(timeline_season), timeline_event_name=VALUES(timeline_event_name), timeline_ref=VALUES(timeline_ref), timeline_status=VALUES(timeline_status), timeline_sort_year=VALUES(timeline_sort_year), timeline_sort_season=VALUES(timeline_sort_season), llm_decision=VALUES(llm_decision), llm_confidence=VALUES(llm_confidence), llm_reason=VALUES(llm_reason)`,
        [
          item.link_id,
          item.kb_event_id || null,
          item.event_name || null,
          item.canonical_event_name || null,
          item.alignment_score ?? null,
          item.alignment_type || null,
          item.relation || null,
          item.timeline_id || null,
          item.timeline_year || null,
          item.timeline_season || null,
          item.timeline_event_name || null,
          item.timeline_ref || null,
          item.timeline_status || null,
          yearOrder(item.timeline_year),
          seasonOrder(item.timeline_season),
          item.llm_review?.decision || null,
          item.llm_review?.confidence ?? null,
          item.llm_review?.reason || null,
        ]
      );

      const [[eventRow]] = await conn.query('SELECT id FROM events WHERE link_id = ?', [item.link_id]);
      const eventId = eventRow.id;

      const text = item.text || {};
      await conn.query(
        `INSERT INTO event_text_scenes (event_id, scene_id, scene_name, scene_summary, source_path, chapter_id, chapter_title, member_count)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?)
         ON DUPLICATE KEY UPDATE scene_id=VALUES(scene_id), scene_name=VALUES(scene_name), scene_summary=VALUES(scene_summary), source_path=VALUES(source_path), chapter_id=VALUES(chapter_id), chapter_title=VALUES(chapter_title), member_count=VALUES(member_count)`,
        [eventId, text.scene_id || null, text.scene_name || null, text.scene_summary || null, text.source_path || null, text.chapter_id || null, text.chapter_title || null, text.member_count ?? 0]
      );

      const video = item.video || {};
      await conn.query(
        `INSERT INTO event_video_scenes (event_id, scene_id, scene_name, scene_summary, source_path, episode_id, episode_title, video_source_path, member_count)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
         ON DUPLICATE KEY UPDATE scene_id=VALUES(scene_id), scene_name=VALUES(scene_name), scene_summary=VALUES(scene_summary), source_path=VALUES(source_path), episode_id=VALUES(episode_id), episode_title=VALUES(episode_title), video_source_path=VALUES(video_source_path), member_count=VALUES(member_count)`,
        [eventId, video.scene_id || null, video.scene_name || null, video.scene_summary || null, video.source_path || null, video.episode_id || null, video.episode_title || null, video.video_source_path || null, video.member_count ?? 0]
      );

      const chars = Array.from(new Set(item.event_characters || item.shared?.characters || []));
      for (const name of chars) {
        await conn.query('INSERT INTO characters (name, display_name) VALUES (?, ?) ON DUPLICATE KEY UPDATE display_name=VALUES(display_name)', [name, name]);
        const [[charRow]] = await conn.query('SELECT id FROM characters WHERE name = ?', [name]);
        await conn.query('INSERT IGNORE INTO event_character_relations (event_id, character_id) VALUES (?, ?)', [eventId, charRow.id]);
      }

      const locs = Array.from(new Set(item.event_locations || item.shared?.locations || []));
      for (const name of locs) {
        await conn.query('INSERT INTO locations (name, display_name) VALUES (?, ?) ON DUPLICATE KEY UPDATE display_name=VALUES(display_name)', [name, name]);
        const [[locRow]] = await conn.query('SELECT id FROM locations WHERE name = ?', [name]);
        await conn.query('INSERT IGNORE INTO event_location_relations (event_id, location_id) VALUES (?, ?)', [eventId, locRow.id]);
      }
    }

    // recompute counts/spans
    await conn.query(`
      UPDATE characters c
      JOIN (
        SELECT ch.id AS character_id, COUNT(DISTINCT e.id) AS cnt, MIN(e.timeline_sort_year * 100 + e.timeline_sort_season) AS min_sort, MAX(e.timeline_sort_year * 100 + e.timeline_sort_season) AS max_sort
        FROM characters ch
        LEFT JOIN event_character_relations r ON r.character_id = ch.id
        LEFT JOIN events e ON e.id = r.event_id
        GROUP BY ch.id
      ) x ON x.character_id = c.id
      SET c.event_count = COALESCE(x.cnt, 0), c.first_timeline_sort = COALESCE(x.min_sort, 0), c.last_timeline_sort = COALESCE(x.max_sort, 0)
    `);

    await conn.query(`
      UPDATE locations l
      JOIN (
        SELECT lo.id AS location_id, COUNT(DISTINCT e.id) AS cnt, MIN(e.timeline_sort_year * 100 + e.timeline_sort_season) AS min_sort, MAX(e.timeline_sort_year * 100 + e.timeline_sort_season) AS max_sort
        FROM locations lo
        LEFT JOIN event_location_relations r ON r.location_id = lo.id
        LEFT JOIN events e ON e.id = r.event_id
        GROUP BY lo.id
      ) x ON x.location_id = l.id
      SET l.event_count = COALESCE(x.cnt, 0), l.first_timeline_sort = COALESCE(x.min_sort, 0), l.last_timeline_sort = COALESCE(x.max_sort, 0)
    `);

    await conn.commit();
    console.log(`Imported ${items.length} events.`);
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
