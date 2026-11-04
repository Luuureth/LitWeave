import fs from 'fs/promises';
import path from 'path';
import { fileURLToPath } from 'url';
import { pool } from './db.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const inputPath = path.join(__dirname, 'display_events.json');
const manualReviewPath = path.join(__dirname, 'display_events_manual_review.json');

function ensureArray(value) {
  return Array.isArray(value) ? value.filter(Boolean) : [];
}

function ensureObject(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : null;
}

function buildManualVideoOverrideMap(items) {
  const map = new Map();
  for (const item of items) {
    const key = `${item.display_event_id || ''}::${item.timeline_id || ''}`;
    map.set(key, {
      representative_video_json: ensureObject(item.representative_video),
      all_video_scenes_json: ensureArray(item.all_video_scenes),
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
  const raw = await fs.readFile(inputPath, 'utf-8');
  const items = JSON.parse(raw);
  if (!Array.isArray(items)) {
    throw new Error('display_events.json must be an array');
  }
  const manualVideoOverrides = await loadManualVideoOverrideMap();

  const conn = await pool.getConnection();
  try {
    await conn.beginTransaction();
    await conn.query('DELETE FROM display_event_character_relations');
    await conn.query('DELETE FROM display_event_location_relations');
    await conn.query('DELETE FROM display_events');

    for (const item of items) {
      if (!item.display_event_id) {
        throw new Error('Each display event must include display_event_id');
      }

      const overrideKey = `${item.display_event_id || ''}::${item.timeline_id || ''}`;
      const videoOverride = manualVideoOverrides.get(overrideKey);
      const characters = ensureArray(item.event_characters_json);
      const locations = ensureArray(item.event_locations_json);
      const representativeText = ensureObject(item.representative_text_json);
      const representativeVideo = videoOverride?.representative_video_json ?? ensureObject(item.representative_video_json);
      const allTextScenes = ensureArray(item.all_text_scenes_json);
      const allVideoScenes = videoOverride?.all_video_scenes_json ?? ensureArray(item.all_video_scenes_json);
      const allLinkIds = ensureArray(item.all_link_ids_json);

      await conn.query(
        `INSERT INTO display_events (
          display_event_id, kb_event_id, event_name, canonical_event_name, summary, timeline_id, timeline_year, timeline_season,
          timeline_event_name, timeline_ref, timeline_status, timeline_sort_year, timeline_sort_season,
          event_characters_json, event_locations_json, representative_text_json, representative_video_json,
          all_text_scenes_json, all_video_scenes_json, all_link_ids_json, matched_link_count, text_scene_count, video_scene_count
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)` ,
        [
          item.display_event_id,
          item.kb_event_id || null,
          item.event_name || null,
          item.canonical_event_name || null,
          item.summary || null,
          item.timeline_id || null,
          item.timeline_year || null,
          item.timeline_season || null,
          item.timeline_event_name || null,
          item.timeline_ref || null,
          item.timeline_status || null,
          Number(item.timeline_sort_year || 0),
          Number(item.timeline_sort_season || 999),
          JSON.stringify(characters),
          JSON.stringify(locations),
          JSON.stringify(representativeText),
          JSON.stringify(representativeVideo),
          JSON.stringify(allTextScenes),
          JSON.stringify(allVideoScenes),
          JSON.stringify(allLinkIds),
          Number(item.matched_link_count || allLinkIds.length || 0),
          Number(item.text_scene_count || allTextScenes.length || 0),
          Number(item.video_scene_count || allVideoScenes.length || 0),
        ]
      );

      const [[displayRow]] = await conn.query('SELECT id FROM display_events WHERE display_event_id = ?', [item.display_event_id]);

      for (const name of characters) {
        await conn.query('INSERT INTO characters (name, display_name) VALUES (?, ?) ON DUPLICATE KEY UPDATE display_name = VALUES(display_name)', [name, name]);
        const [[row]] = await conn.query('SELECT id FROM characters WHERE name = ?', [name]);
        await conn.query('INSERT IGNORE INTO display_event_character_relations (display_event_id, character_id) VALUES (?, ?)', [displayRow.id, row.id]);
      }

      for (const name of locations) {
        await conn.query('INSERT INTO locations (name, display_name) VALUES (?, ?) ON DUPLICATE KEY UPDATE display_name = VALUES(display_name)', [name, name]);
        const [[row]] = await conn.query('SELECT id FROM locations WHERE name = ?', [name]);
        await conn.query('INSERT IGNORE INTO display_event_location_relations (display_event_id, location_id) VALUES (?, ?)', [displayRow.id, row.id]);
      }
    }

    await conn.query(`
      UPDATE characters c
      JOIN (
        SELECT r.character_id, COUNT(DISTINCT r.display_event_id) AS cnt,
               MIN(de.timeline_sort_year * 1000 + de.timeline_sort_season) AS min_sort,
               MAX(de.timeline_sort_year * 1000 + de.timeline_sort_season) AS max_sort
        FROM display_event_character_relations r
        JOIN display_events de ON de.id = r.display_event_id
        GROUP BY r.character_id
      ) x ON x.character_id = c.id
      SET c.event_count = x.cnt, c.first_timeline_sort = x.min_sort, c.last_timeline_sort = x.max_sort
    `);
    await conn.query('UPDATE characters SET event_count = 0, first_timeline_sort = 0, last_timeline_sort = 0 WHERE id NOT IN (SELECT DISTINCT character_id FROM display_event_character_relations)');

    await conn.query(`
      UPDATE locations l
      JOIN (
        SELECT r.location_id, COUNT(DISTINCT r.display_event_id) AS cnt,
               MIN(de.timeline_sort_year * 1000 + de.timeline_sort_season) AS min_sort,
               MAX(de.timeline_sort_year * 1000 + de.timeline_sort_season) AS max_sort
        FROM display_event_location_relations r
        JOIN display_events de ON de.id = r.display_event_id
        GROUP BY r.location_id
      ) x ON x.location_id = l.id
      SET l.event_count = x.cnt, l.first_timeline_sort = x.min_sort, l.last_timeline_sort = x.max_sort
    `);
    await conn.query('UPDATE locations SET event_count = 0, first_timeline_sort = 0, last_timeline_sort = 0 WHERE id NOT IN (SELECT DISTINCT location_id FROM display_event_location_relations)');

    await conn.commit();
    console.log(`Imported ${items.length} display events from ${inputPath}`);
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
