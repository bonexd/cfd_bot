import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';

const root = path.resolve(import.meta.dirname, '..');
const start = fs.readFileSync(path.join(root, 'START.bat'), 'utf8');
const live = fs.readFileSync(path.join(root, 'START_LIVE.bat'), 'utf8');
const requirements = fs.readFileSync(path.join(root, 'requirements.txt'), 'utf8');
const updater = fs.readFileSync(path.join(root, 'UPDATE.bat'), 'utf8');
const gitignore = fs.readFileSync(path.join(root, '.gitignore'), 'utf8');

test('demo launcher bootstraps Python and every declared dependency', () => {
  assert.match(start, /winget install -e --id Python\.Python\.3\.12/);
  assert.match(start, /https:\/\/www\.python\.org\/ftp\/python\/3\.12\.10\/python-3\.12\.10-amd64\.exe/);
  assert.match(start, /-m venv \.venv/);
  assert.match(start, /-m pip install -r requirements\.txt/);
  assert.match(start, /import pandas,yaml,dotenv,optuna/);
  assert.match(start, /-m app\.auto --mode demo --skip-tune/);
  for (const packageName of ['pandas', 'numpy', 'pyyaml', 'python-dotenv', 'optuna']) {
    assert.match(requirements.toLowerCase(), new RegExp(`^${packageName}`, 'm'));
  }
});

test('live launcher remembers one-time acknowledgement', () => {
  assert.match(live, /if not exist "\.live_acknowledged"/i);
  assert.match(live, /choice \/C YN/i);
  assert.match(live, />"\.live_acknowledged" echo acknowledged/i);
  assert.match(live, /starting without another prompt/i);
  assert.doesNotMatch(live, /Type LIVE and press Enter to continue/);
  assert.match(live, /-m app\.auto --mode live --skip-tune/);
  assert.doesNotMatch(live, /START\.bat/);
});

test('both launchers show Abbas and Bone as visible authors', () => {
  for (const launcher of [start, live]) {
    assert.match(launcher, /echo\s+\^\|\s+BY ABBAS AND BONE @BONEXD\s+\^\|/i);
    assert.match(launcher, /echo\s+============================================================/);
  }
});

test('ZIP downloads bootstrap GitHub tracking automatically', () => {
  for (const launcher of [start, live]) {
    assert.match(launcher, /if not exist "\.git"/i);
    assert.match(launcher, /call UPDATE\.bat --bootstrap-only/i);
  }
  assert.match(updater, /git init/i);
  assert.match(updater, /git fetch origin main --depth 1/i);
  assert.match(updater, /bonexd\/cfd_bot\.git/i);
  assert.doesNotMatch(updater, /bloodvitr\/cfd_bot/i);
  assert.match(updater, /git branch --set-upstream-to=origin\/main main/i);
});

test('updater preserves local work before resetting to GitHub main', () => {
  assert.match(updater, /git stash push -u/i);
  assert.match(updater, /git branch "!BACKUP_BRANCH!" HEAD/i);
  assert.match(updater, /git reset --hard origin\/main/i);
  assert.match(gitignore, /^\.env$/m);
});
