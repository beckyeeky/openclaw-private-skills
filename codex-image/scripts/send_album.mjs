#!/usr/bin/env node
/**
 * Telegram Album Sender - Node.js wrapper
 * Usage: node send_album.mjs <image1> [image2] ... [caption]
 */

import { execSync } from 'child_process';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const __dirname = dirname(fileURLToPath(import.meta.url));

const args = process.argv.slice(2);

if (args.length < 1) {
  console.log('Usage: node send_album.mjs <image1> [image2] ... [caption]');
  console.log('Example: node send_album.mjs ./pic1.png ./pic2.png "My photos"');
  console.log('');
  console.log('Send up to 10 photos as a Telegram album/media group.');
  process.exit(1);
}

const pythonScript = join(__dirname, 'send_album.py');
const cmd = `python3 "${pythonScript}" ${args.map(a => `"${a}"`).join(' ')}`;

try {
  execSync(cmd, { stdio: 'inherit' });
} catch (error) {
  console.error('Failed to send album:', error.message);
  process.exit(1);
}
