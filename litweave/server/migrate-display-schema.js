import { pool } from './db.js';

async function main() {
  const conn = await pool.getConnection();
  try {
    await conn.beginTransaction();

    await conn.query(`
      CREATE TABLE IF NOT EXISTS display_events (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        display_event_id VARCHAR(128) NOT NULL UNIQUE,
        kb_event_id VARCHAR(64),
        event_name TEXT,
        canonical_event_name TEXT,
        summary TEXT,
        timeline_id VARCHAR(64),
        timeline_year VARCHAR(64),
        timeline_season VARCHAR(64),
        timeline_event_name TEXT,
        timeline_ref TEXT,
        timeline_status VARCHAR(64),
        timeline_sort_year INT DEFAULT 0,
        timeline_sort_season INT DEFAULT 99,
        event_characters_json JSON,
        event_locations_json JSON,
        representative_text_json JSON,
        representative_video_json JSON,
        all_text_scenes_json JSON,
        all_video_scenes_json JSON,
        all_link_ids_json JSON,
        matched_link_count INT DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        INDEX idx_display_events_timeline_sort (timeline_sort_year, timeline_sort_season),
        INDEX idx_display_events_timeline_id (timeline_id),
        INDEX idx_display_events_kb_timeline (kb_event_id, timeline_id)
      )
    `);

    await conn.query(`
      CREATE TABLE IF NOT EXISTS display_event_character_relations (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        display_event_id BIGINT NOT NULL,
        character_id BIGINT NOT NULL,
        UNIQUE KEY uniq_display_event_character (display_event_id, character_id),
        CONSTRAINT fk_decr_display_event FOREIGN KEY (display_event_id) REFERENCES display_events(id) ON DELETE CASCADE,
        CONSTRAINT fk_decr_character FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE
      )
    `);

    await conn.query(`
      CREATE TABLE IF NOT EXISTS display_event_location_relations (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        display_event_id BIGINT NOT NULL,
        location_id BIGINT NOT NULL,
        UNIQUE KEY uniq_display_event_location (display_event_id, location_id),
        CONSTRAINT fk_delr_display_event FOREIGN KEY (display_event_id) REFERENCES display_events(id) ON DELETE CASCADE,
        CONSTRAINT fk_delr_location FOREIGN KEY (location_id) REFERENCES locations(id) ON DELETE CASCADE
      )
    `);

    await conn.commit();
    console.log('Display schema migration completed.');
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
