#!/usr/bin/env node
/**
 * One-command installer for the Chem Integrity Auditor skill.
 *
 * Usage:
 *   chem-integrity-auditor                     # ~/.claude/skills/chem-integrity-auditor
 *   chem-integrity-auditor --project           # ./.claude/skills/chem-integrity-auditor
 *   chem-integrity-auditor --skills-dir DIR    # DIR/chem-integrity-auditor
 *   chem-integrity-auditor --target DIR        # exact directory
 *
 * The installer copies only the skill payload (no fixtures, no audit outputs,
 * no gold-set downloads). Python dependencies are NOT installed automatically:
 * the printed next steps ask the agent/user to run pip + check_env, because a
 * global pip install is a machine-level change and should be explicit.
 */

const fs = require("fs");
const os = require("os");
const path = require("path");

const skillName = "chem-integrity-auditor";
const packageRoot = path.resolve(__dirname, "..");
const payload = [
  "SKILL.md",
  "agents",
  "references",
  "scripts",
  "templates",
  "requirements.txt",
  "README.md",
  "CHANGELOG.md",
  "ACKNOWLEDGEMENTS.md",
  "LICENSE",
];

function usage() {
  console.log(`Chem Integrity Auditor skill installer

Usage:
  chem-integrity-auditor [options]

Options:
  --project          Install into ./.claude/skills/${skillName}
  --skills-dir DIR   Install into DIR/${skillName}
  --target DIR       Install directly into DIR
  --help             Show this help

Default target:
  ~/.claude/skills/${skillName}`);
}

function parseArgs(argv) {
  const options = { project: false, skillsDir: null, target: null };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === "--help" || arg === "-h") {
      options.help = true;
    } else if (arg === "--project") {
      options.project = true;
    } else if (arg === "--skills-dir") {
      options.skillsDir = argv[++i];
      if (!options.skillsDir) throw new Error("--skills-dir needs a value");
    } else if (arg === "--target") {
      options.target = argv[++i];
      if (!options.target) throw new Error("--target needs a value");
    } else {
      throw new Error(`Unknown option: ${arg}`);
    }
  }
  return options;
}

function targetDir(options) {
  if (options.target) return path.resolve(options.target);
  if (options.project) {
    return path.resolve(process.cwd(), ".claude", "skills", skillName);
  }
  const skillsDir = options.skillsDir
    ? path.resolve(options.skillsDir)
    : path.join(os.homedir(), ".claude", "skills");
  return path.join(skillsDir, skillName);
}

function copyItem(relativePath, target) {
  const source = path.join(packageRoot, relativePath);
  if (!fs.existsSync(source)) return false;
  const destination = path.join(target, relativePath);
  fs.mkdirSync(path.dirname(destination), { recursive: true });
  fs.cpSync(source, destination, {
    recursive: true,
    force: true,
    errorOnExist: false,
    dereference: false,
    filter: (item) =>
      !item.includes(`${path.sep}__pycache__${path.sep}`) &&
      !item.endsWith(".pyc") &&
      !item.includes(`${path.sep}.git${path.sep}`),
  });
  return true;
}

function main() {
  const options = parseArgs(process.argv.slice(2));
  if (options.help) {
    usage();
    return;
  }
  const target = targetDir(options);
  fs.mkdirSync(target, { recursive: true });
  const copied = payload.filter((item) => copyItem(item, target));
  if (!copied.includes("SKILL.md")) {
    throw new Error("SKILL.md not found in the package; install from the repo root");
  }
  console.log(`Installed ${skillName} to ${target}`);
  console.log("");
  console.log("Next steps:");
  console.log(`  1) python3 -m pip install -r "${path.join(target, "requirements.txt")}"`);
  console.log("  2) install poppler (pdftoppm / pdfimages / pdftotext)");
  console.log(`  3) python3 "${path.join(target, "scripts", "check_env.py")}"`);
  console.log("  4) restart your Agent client if the skill does not appear");
  console.log("");
  console.log("MinerU is optional; set MINERU_API_TOKEN only in the environment.");
}

try {
  main();
} catch (error) {
  console.error(error.message);
  process.exit(1);
}
