const { execSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

const frontendDir = fs.existsSync(path.resolve('frontend/package.json'))
  ? path.resolve('frontend')
  : path.resolve(__dirname, '../frontend');

const distIndex = path.join(frontendDir, 'dist', 'index.html');

if (process.env.STZY_SKIP_FRONTEND_BUILD === '1' && fs.existsSync(distIndex)) {
  console.log('[build_frontend] Using prebuilt frontend/dist');
  process.exit(0);
}

execSync('npm run build', {
  cwd: frontendDir,
  stdio: 'inherit',
});
