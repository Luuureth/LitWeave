import fs from 'fs/promises';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const displayPath = path.join(__dirname, 'display_events.json');
const manualReviewPath = path.join(__dirname, 'display_events_manual_review.json');

function buildManualIndex(items) {
  const map = new Map();
  for (const item of items) {
    const key = `${item.display_event_id || ''}::${item.timeline_id || ''}`;
    map.set(key, item);
  }
  return map;
}

async function readJson(filePath) {
  const raw = await fs.readFile(filePath, 'utf-8');
  return JSON.parse(raw);
}

async function main() {
  const [displayItems, manualItems] = await Promise.all([
    readJson(displayPath),
    readJson(manualReviewPath),
  ]);

  if (!Array.isArray(displayItems)) {
    throw new Error('display_events.json must be an array');
  }
  if (!Array.isArray(manualItems)) {
    throw new Error('display_events_manual_review.json must be an array');
  }

  const manualIndex = buildManualIndex(manualItems);
  let updated = 0;

  for (const item of displayItems) {
    const key = `${item.display_event_id || ''}::${item.timeline_id || ''}`;
    const manualItem = manualIndex.get(key);
    if (!manualItem) continue;

    item.representative_video_json = manualItem.representative_video ?? null;
    item.all_video_scenes_json = Array.isArray(manualItem.all_video_scenes)
      ? manualItem.all_video_scenes
      : [];
    updated += 1;
  }

  await fs.writeFile(displayPath, `${JSON.stringify(displayItems, null, 2)}\n`, 'utf-8');
  console.log(`Synced video paths for ${updated} display events.`);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
