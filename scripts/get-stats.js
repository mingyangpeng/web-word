#!/usr/bin/env node

const fs = require('fs');
const path = require('path');

const projectRoot = process.cwd();
const planningDir = path.join(projectRoot, '.planning');
const STATE_FILE = path.join(planningDir, 'STATE.md');
const PHASES_DIR = path.join(planningDir, 'phases');
const GIT_DIR = path.join(projectRoot, '.git');

// Parse STATE.md
function parseState() {
  const state = {
    phases_completed: 0,
    phases_total: 0,
    requirements_complete: 0,
    requirements_total: 0,
    tasks_completed: 0,
    phases: []
  };

  if (!fs.existsSync(STATE_FILE)) {
    return state;
  }

  const content = fs.readFileSync(STATE_FILE, 'utf-8');

  // Parse phases table
  const phasesMatch = content.match(/## Phase Progress.*?(\|.*?\|)/s);
  if (phasesMatch) {
    const lines = phasesMatch[1].trim().split('\n');
    // Skip header, parse rows
    for (let i = 1; i < lines.length; i++) {
      const row = lines[i].trim().split('|').map(s => s.trim()).filter(s => s);
      if (row.length >= 5) {
        state.phases.push({
          name: row[1],
          status: row[2],
          progress: row[3],
          plans: row[4],
          last_updated: row[5]
        });
      }
    }
  }

  // Parse requirements table
  const reqMatch = content.match(/## Requirements Status.*?(\|.*?\|)/s);
  if (reqMatch) {
    const lines = reqMatch[1].trim().split('\n');
    state.requirements_total = lines.length - 1;
    for (let i = 1; i < lines.length; i++) {
      const row = lines[i].trim().split('|').map(s => s.trim()).filter(s => s);
      if (row.length >= 4 && row[3]?.includes('✅')) {
        state.requirements_complete++;
      }
    }
  }

  // Parse tasks completed
  const tasksMatch = content.match(/## Tasks Completed.*?- \[(x| )\]/s);
  if (tasksMatch) {
    const checkboxCount = (tasksMatch[1].match(/x/g) || []).length;
    state.tasks_completed = checkboxCount;
  }

  return state;
}

// Parse phases directory
function parsePhases() {
  const phases = [];
  if (!fs.existsSync(PHASES_DIR)) {
    return phases;
  }

  const entries = fs.readdirSync(PHASES_DIR, { withFileTypes: true });
  for (const entry of entries) {
    if (entry.isDirectory()) {
      const phasePath = path.join(PHASES_DIR, entry.name);
      const files = fs.readdirSync(phasePath);
      const planFile = files.find(f => f.endsWith('.md') && f !== 'STATE.md');
      phases.push({
        name: entry.name,
        has_plan: !!planFile
      });
    }
  }

  return phases;
}

// Get git statistics
function getGitStats() {
  const gitStats = {
    commits: 0,
    first_commit_date: null,
    last_activity: null
  };

  if (!fs.existsSync(GIT_DIR)) {
    return gitStats;
  }

  try {
    const logCmd = `cd "${GIT_DIR}" && git log --oneline --format="%h|%ad|%s" --date=short 2>/dev/null`;
    const logOutput = require('child_process').execSync(logCmd, { encoding: 'utf-8' });
    const lines = logOutput.trim().split('\n');

    if (lines.length > 0) {
      gitStats.commits = lines.length;
      gitStats.first_commit_date = lines[0].split('|')[1];

      // Get last activity date
      const lastLine = lines[lines.length - 1].split('|');
      gitStats.last_activity = lastLine[1];
    }

    // Get project age
    if (gitStats.first_commit_date) {
      gitStats.age_days = Math.floor((Date.now() - new Date(gitStats.first_commit_date).getTime()) / (1000 * 60 * 60 * 24));
    }
  } catch (e) {
    // Git command failed
  }

  return gitStats;
}

// Main
try {
  const state = parseState();
  const phases = parsePhases();
  const gitStats = getGitStats();

  const milestone_version = '0.1.0';
  const milestone_name = 'Project';
  const phases_completed = phases.filter(p => p.has_plan).length;
  const phases_total = phases.length;

  const stats = {
    milestone_version,
    milestone_name,
    phases_completed,
    phases_total,
    total_plans: phases.filter(p => p.has_plan).length,
    total_summaries: 0,
    percent: phases_total > 0 ? Math.round((phases_completed / phases_total) * 100) : 0,
    plan_percent: phases_total > 0 ? Math.round((phases.filter(p => p.has_plan).length / phases_total) * 100) : 0,
    requirements_total: state.requirements_total,
    requirements_complete: state.requirements_complete,
    git_commits: gitStats.commits,
    git_first_commit_date: gitStats.first_commit_date,
    last_activity: gitStats.last_activity,
    project_age_days: gitStats.age_days || 0
  };

  console.log(JSON.stringify(stats, null, 2));
} catch (error) {
  process.exit(1);
}
