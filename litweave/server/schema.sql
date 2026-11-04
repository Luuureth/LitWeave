CREATE DATABASE IF NOT EXISTS litweave CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE litweave;

CREATE TABLE IF NOT EXISTS timeline_nodes (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  timeline_id VARCHAR(64) NOT NULL UNIQUE,
  timeline_year VARCHAR(64),
  timeline_season VARCHAR(64),
  timeline_event_name TEXT,
  timeline_ref TEXT,
  year_order INT DEFAULT 0,
  season_order INT DEFAULT 99,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS events (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  link_id VARCHAR(64) NOT NULL UNIQUE,
  kb_event_id VARCHAR(64),
  event_name TEXT,
  canonical_event_name TEXT,
  alignment_score DECIMAL(10,6),
  alignment_type VARCHAR(64),
  relation VARCHAR(64),
  timeline_id VARCHAR(64),
  timeline_year VARCHAR(64),
  timeline_season VARCHAR(64),
  timeline_event_name TEXT,
  timeline_ref TEXT,
  timeline_status VARCHAR(64),
  timeline_sort_year INT DEFAULT 0,
  timeline_sort_season INT DEFAULT 99,
  llm_decision VARCHAR(64),
  llm_confidence DECIMAL(10,6),
  llm_reason TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_events_timeline_sort (timeline_sort_year, timeline_sort_season),
  INDEX idx_events_timeline_id (timeline_id),
  FULLTEXT KEY ft_event_text (event_name, canonical_event_name, timeline_event_name)
);

CREATE TABLE IF NOT EXISTS event_text_scenes (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  event_id BIGINT NOT NULL UNIQUE,
  scene_id VARCHAR(64),
  scene_name TEXT,
  scene_summary TEXT,
  source_path TEXT,
  chapter_id VARCHAR(64),
  chapter_title TEXT,
  member_count INT DEFAULT 0,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_text_event FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS event_video_scenes (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  event_id BIGINT NOT NULL UNIQUE,
  scene_id VARCHAR(64),
  scene_name TEXT,
  scene_summary TEXT,
  source_path TEXT,
  episode_id VARCHAR(64),
  episode_title TEXT,
  video_source_path TEXT,
  member_count INT DEFAULT 0,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_video_event FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS characters (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  name VARCHAR(255) NOT NULL UNIQUE,
  display_name VARCHAR(255),
  event_count INT DEFAULT 0,
  first_timeline_sort INT DEFAULT 0,
  last_timeline_sort INT DEFAULT 0,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS locations (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  name VARCHAR(255) NOT NULL UNIQUE,
  display_name VARCHAR(255),
  event_count INT DEFAULT 0,
  first_timeline_sort INT DEFAULT 0,
  last_timeline_sort INT DEFAULT 0,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS event_character_relations (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  event_id BIGINT NOT NULL,
  character_id BIGINT NOT NULL,
  UNIQUE KEY uniq_event_character (event_id, character_id),
  CONSTRAINT fk_ecr_event FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE,
  CONSTRAINT fk_ecr_character FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS event_location_relations (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  event_id BIGINT NOT NULL,
  location_id BIGINT NOT NULL,
  UNIQUE KEY uniq_event_location (event_id, location_id),
  CONSTRAINT fk_elr_event FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE,
  CONSTRAINT fk_elr_location FOREIGN KEY (location_id) REFERENCES locations(id) ON DELETE CASCADE
);

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
);

CREATE TABLE IF NOT EXISTS display_event_character_relations (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  display_event_id BIGINT NOT NULL,
  character_id BIGINT NOT NULL,
  UNIQUE KEY uniq_display_event_character (display_event_id, character_id),
  CONSTRAINT fk_decr_display_event FOREIGN KEY (display_event_id) REFERENCES display_events(id) ON DELETE CASCADE,
  CONSTRAINT fk_decr_character FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS display_event_location_relations (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  display_event_id BIGINT NOT NULL,
  location_id BIGINT NOT NULL,
  UNIQUE KEY uniq_display_event_location (display_event_id, location_id),
  CONSTRAINT fk_delr_display_event FOREIGN KEY (display_event_id) REFERENCES display_events(id) ON DELETE CASCADE,
  CONSTRAINT fk_delr_location FOREIGN KEY (location_id) REFERENCES locations(id) ON DELETE CASCADE
);
