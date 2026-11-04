import express from 'express';
import cors from 'cors';
import dotenv from 'dotenv';
import path from 'path';
import { fileURLToPath } from 'url';
import { pool } from './db.js';

dotenv.config();

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const projectRoot = path.resolve(__dirname, '..');
const mediaRoot = path.resolve(projectRoot, '..', '剧版红楼梦', 'hongloumeng_segments');
const mediaRouteBase = '/media/hongloumeng_segments';

const app = express();
app.use(cors());
app.use(express.json());
app.use(mediaRouteBase, express.static(mediaRoot));

function safeJsonParse(value, fallback = []) {
  if (value == null) return fallback;
  if (Array.isArray(value) || typeof value === 'object') return value;
  try {
    return JSON.parse(value);
  } catch {
    return fallback;
  }
}

function splitConcat(value) {
  return String(value || '')
    .split('、')
    .map((item) => item.trim())
    .filter(Boolean);
}

function normalizeSlashes(value) {
  return String(value || '').replace(/\\/g, '/');
}

function toPlayableVideoUrl(filePath, req) {
  if (!filePath) return '';
  const normalized = normalizeSlashes(filePath);
  const marker = '/剧版红楼梦/hongloumeng_segments/';
  const idx = normalized.indexOf(marker);
  if (idx === -1) return filePath;

  const relativePath = normalized.slice(idx + marker.length);
  return `${req.protocol}://${req.get('host')}${mediaRouteBase}/${encodeURI(relativePath)}`;
}

function mapVideoScene(scene, req) {
  if (!scene || typeof scene !== 'object') return scene;
  const sourcePath = scene.video_source_path || scene.source_path || '';
  return {
    ...scene,
    video_source_path: sourcePath,
    playable_video_url: toPlayableVideoUrl(sourcePath, req),
  };
}

app.get('/api/stats', async (_req, res) => {
  const [[events]] = await pool.query('SELECT COUNT(*) AS count FROM display_events');
  const [[characters]] = await pool.query('SELECT COUNT(DISTINCT character_id) AS count FROM display_event_character_relations');
  const [[locations]] = await pool.query('SELECT COUNT(DISTINCT location_id) AS count FROM display_event_location_relations');
  const [[textScenes]] = await pool.query('SELECT COALESCE(SUM(text_scene_count), 0) AS count FROM display_events');
  const [[videoScenes]] = await pool.query('SELECT COALESCE(SUM(video_scene_count), 0) AS count FROM display_events');
  res.json({
    unifiedEvents: events.count,
    characters: characters.count,
    locations: locations.count,
    multimodalContents: Number(textScenes.count || 0) + Number(videoScenes.count || 0),
    textScenes: Number(textScenes.count || 0),
    videoScenes: Number(videoScenes.count || 0),
  });
});

app.get('/api/events', async (req, res) => {
  const { q = '', character = '', location = '' } = req.query;
  const params = [];
  let where = 'WHERE 1=1';
  if (q) {
    where += ' AND (de.event_name LIKE ? OR de.canonical_event_name LIKE ? OR de.timeline_event_name LIKE ? OR de.summary LIKE ?)';
    params.push(`%${q}%`, `%${q}%`, `%${q}%`, `%${q}%`);
  }
  if (character) {
    where += ' AND EXISTS (SELECT 1 FROM display_event_character_relations r JOIN characters c ON c.id = r.character_id WHERE r.display_event_id = de.id AND c.name LIKE ?)';
    params.push(`%${character}%`);
  }
  if (location) {
    where += ' AND EXISTS (SELECT 1 FROM display_event_location_relations r JOIN locations l ON l.id = r.location_id WHERE r.display_event_id = de.id AND l.name LIKE ?)';
    params.push(`%${location}%`);
  }

  const [rows] = await pool.query(
    `SELECT de.display_event_id, de.kb_event_id, de.event_name, de.canonical_event_name, de.summary,
            de.timeline_id, de.timeline_year, de.timeline_season, de.timeline_event_name, de.timeline_ref,
            de.timeline_status, de.timeline_sort_year, de.timeline_sort_season, de.matched_link_count,
            GROUP_CONCAT(DISTINCT c.name ORDER BY c.name SEPARATOR '、') AS event_characters,
            GROUP_CONCAT(DISTINCT l.name ORDER BY l.name SEPARATOR '、') AS event_locations
     FROM display_events de
     LEFT JOIN display_event_character_relations r1 ON r1.display_event_id = de.id
     LEFT JOIN characters c ON c.id = r1.character_id
     LEFT JOIN display_event_location_relations r2 ON r2.display_event_id = de.id
     LEFT JOIN locations l ON l.id = r2.location_id
     ${where}
     GROUP BY de.id
     ORDER BY de.timeline_sort_year ASC, de.timeline_sort_season ASC,
              COALESCE(NULLIF(de.timeline_id, ''), de.display_event_id) ASC, de.id ASC`,
    params
  );

  res.json(
    rows.map((row) => ({
      ...row,
      event_characters: splitConcat(row.event_characters),
      event_locations: splitConcat(row.event_locations),
    }))
  );
});

app.get('/api/events/:id', async (req, res) => {
  const { id } = req.params;
  const [[event]] = await pool.query('SELECT * FROM display_events WHERE display_event_id = ? OR id = ?', [id, id]);
  if (!event) return res.status(404).json({ message: 'Event not found' });
  const [characters] = await pool.query(
    'SELECT c.name FROM characters c JOIN display_event_character_relations r ON r.character_id = c.id WHERE r.display_event_id = ? ORDER BY c.name',
    [event.id]
  );
  const [locations] = await pool.query(
    'SELECT l.name FROM locations l JOIN display_event_location_relations r ON r.location_id = l.id WHERE r.display_event_id = ? ORDER BY l.name',
    [event.id]
  );

  const representativeText = safeJsonParse(event.representative_text_json, null);
  const representativeVideo = mapVideoScene(safeJsonParse(event.representative_video_json, null), req);
  const allTextScenes = safeJsonParse(event.all_text_scenes_json, []);
  const allVideoScenes = safeJsonParse(event.all_video_scenes_json, []).map((scene) => mapVideoScene(scene, req));

  res.json({
    ...event,
    event_characters: characters.map((x) => x.name),
    event_locations: locations.map((x) => x.name),
    representative_text: representativeText,
    representative_video: representativeVideo,
    all_text_scenes: allTextScenes,
    all_video_scenes: allVideoScenes,
    all_link_ids: safeJsonParse(event.all_link_ids_json, []),
    event_characters_json: safeJsonParse(event.event_characters_json, []),
    event_locations_json: safeJsonParse(event.event_locations_json, []),
  });
});

app.get('/api/characters', async (req, res) => {
  const { q = '' } = req.query;
  const [rows] = await pool.query(
    `SELECT c.name,
            COUNT(DISTINCT r.display_event_id) AS event_count,
            MIN(de.timeline_sort_year * 100 + de.timeline_sort_season) AS first_timeline_sort,
            MAX(de.timeline_sort_year * 100 + de.timeline_sort_season) AS last_timeline_sort
     FROM characters c
     JOIN display_event_character_relations r ON r.character_id = c.id
     JOIN display_events de ON de.id = r.display_event_id
     WHERE c.name LIKE ?
     GROUP BY c.id, c.name
     ORDER BY event_count DESC, first_timeline_sort ASC, c.name ASC`,
    [`%${q}%`]
  );
  res.json(rows);
});

app.get('/api/characters/:name', async (req, res) => {
  const name = decodeURIComponent(req.params.name);
  const [[character]] = await pool.query('SELECT id, name, display_name FROM characters WHERE name = ?', [name]);
  if (!character) return res.status(404).json({ message: 'Character not found' });

  const [events] = await pool.query(
    `SELECT de.display_event_id, de.event_name, de.timeline_year, de.timeline_season, de.timeline_ref,
            de.timeline_sort_year, de.timeline_sort_season, de.summary,
            GROUP_CONCAT(DISTINCT l.name ORDER BY l.name SEPARATOR '、') AS event_locations
     FROM display_events de
     JOIN display_event_character_relations r ON r.display_event_id = de.id
     LEFT JOIN display_event_location_relations rl ON rl.display_event_id = de.id
     LEFT JOIN locations l ON l.id = rl.location_id
     WHERE r.character_id = ?
     GROUP BY de.id
     ORDER BY de.timeline_sort_year ASC, de.timeline_sort_season ASC,
              COALESCE(NULLIF(de.timeline_id, ''), de.display_event_id) ASC, de.id ASC`,
    [character.id]
  );

  res.json({
    ...character,
    event_count: events.length,
    first_timeline_sort: events.length ? events[0].timeline_sort_year * 100 + events[0].timeline_sort_season : 0,
    last_timeline_sort: events.length ? events[events.length - 1].timeline_sort_year * 100 + events[events.length - 1].timeline_sort_season : 0,
    events: events.map((event) => ({
      ...event,
      event_locations: splitConcat(event.event_locations),
    })),
  });
});

app.get('/api/locations', async (req, res) => {
  const { q = '' } = req.query;
  const [rows] = await pool.query(
    `SELECT l.name,
            COUNT(DISTINCT r.display_event_id) AS event_count,
            MIN(de.timeline_sort_year * 100 + de.timeline_sort_season) AS first_timeline_sort,
            MAX(de.timeline_sort_year * 100 + de.timeline_sort_season) AS last_timeline_sort
     FROM locations l
     JOIN display_event_location_relations r ON r.location_id = l.id
     JOIN display_events de ON de.id = r.display_event_id
     WHERE l.name LIKE ?
     GROUP BY l.id, l.name
     ORDER BY event_count DESC, first_timeline_sort ASC, l.name ASC`,
    [`%${q}%`]
  );
  res.json(rows);
});

app.get('/api/locations/:name', async (req, res) => {
  const name = decodeURIComponent(req.params.name);
  const [[location]] = await pool.query('SELECT id, name, display_name FROM locations WHERE name = ?', [name]);
  if (!location) return res.status(404).json({ message: 'Location not found' });

  const [events] = await pool.query(
    `SELECT de.display_event_id, de.event_name, de.timeline_year, de.timeline_season, de.timeline_ref,
            de.timeline_sort_year, de.timeline_sort_season, de.summary,
            GROUP_CONCAT(DISTINCT c.name ORDER BY c.name SEPARATOR '、') AS event_characters
     FROM display_events de
     JOIN display_event_location_relations r ON r.display_event_id = de.id
     LEFT JOIN display_event_character_relations rc ON rc.display_event_id = de.id
     LEFT JOIN characters c ON c.id = rc.character_id
     WHERE r.location_id = ?
     GROUP BY de.id
     ORDER BY de.timeline_sort_year ASC, de.timeline_sort_season ASC,
              COALESCE(NULLIF(de.timeline_id, ''), de.display_event_id) ASC, de.id ASC`,
    [location.id]
  );

  res.json({
    ...location,
    event_count: events.length,
    first_timeline_sort: events.length ? events[0].timeline_sort_year * 100 + events[0].timeline_sort_season : 0,
    last_timeline_sort: events.length ? events[events.length - 1].timeline_sort_year * 100 + events[events.length - 1].timeline_sort_season : 0,
    events: events.map((event) => ({
      ...event,
      event_characters: splitConcat(event.event_characters),
    })),
  });
});

app.listen(process.env.PORT || 4000, () => console.log('API running'));
