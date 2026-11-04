import fs from 'fs/promises';
import path from 'path';
import { fileURLToPath } from 'url';
import { pool } from './db.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const outputPath = path.join(__dirname, 'display_events.json');

function safeJsonParse(value, fallback = null) {
  if (value == null) return fallback;
  if (typeof value === 'object') return value;
  try {
    return JSON.parse(value);
  } catch {
    return fallback;
  }
}

async function main() {
  const [rows] = await pool.query(`
    SELECT *
    FROM display_events
    ORDER BY timeline_sort_year ASC, timeline_sort_season ASC,
             COALESCE(NULLIF(timeline_id, ''), display_event_id) ASC, id ASC
  `);

  const normalized = rows.map((row) => ({
    display_event_id: row.display_event_id,
    kb_event_id: row.kb_event_id,
    event_name: row.event_name,
    canonical_event_name: row.canonical_event_name,
    summary: row.summary,
    timeline_id: row.timeline_id,
    timeline_year: row.timeline_year,
    timeline_season: row.timeline_season,
    timeline_event_name: row.timeline_event_name,
    timeline_ref: row.timeline_ref,
    timeline_status: row.timeline_status,
    timeline_sort_year: row.timeline_sort_year,
    timeline_sort_season: row.timeline_sort_season,
    matched_link_count: row.matched_link_count,
    event_characters_json: safeJsonParse(row.event_characters_json, []),
    event_locations_json: safeJsonParse(row.event_locations_json, []),
    representative_text_json: safeJsonParse(row.representative_text_json, null),
    representative_video_json: safeJsonParse(row.representative_video_json, null),
    all_text_scenes_json: safeJsonParse(row.all_text_scenes_json, []),
    all_video_scenes_json: safeJsonParse(row.all_video_scenes_json, []),
    all_link_ids_json: safeJsonParse(row.all_link_ids_json, []),
  }));

  await fs.writeFile(outputPath, `${JSON.stringify(normalized, null, 2)}\n`, 'utf-8');
  console.log(`Exported ${normalized.length} display events to ${outputPath}`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
