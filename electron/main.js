/**
 * Electron 主进程
 * 职责：启动内嵌 Python 后端 → 等待就绪 → 打开桌面窗口
 * 所有解析逻辑仍由 Python 后端提供，桌面版只是把它包装成独立应用。
 */
const { app, BrowserWindow, dialog, shell } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');
const net = require('net');
const http = require('http');

const APP_NAME = 'VidParse';
let backendProcess = null;
let mainWindow = null;
let splashWindow = null;
let backendPort = 0;
let isQuitting = false;

/* ---------------- 单实例锁 ---------------- */
const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });
}

/* ---------------- 路径与 Python 查找 ---------------- */
function getBaseDir() {
  // asar=false, 开发: <root>/electron -> <root>; 打包: resources/app/electron -> resources/app
  return path.resolve(__dirname, '..');
}

function findPython() {
  const base = getBaseDir();
  const candidates = [];

  // 1) 打包后的内嵌运行时（extraResources -> resources/python）
  if (app.isPackaged) {
    candidates.push(path.join(process.resourcesPath, 'python', 'python.exe'));
    candidates.push(path.join(process.resourcesPath, 'python', 'pythonw.exe'));
  }
  // 2) 开发/绿色版：项目内 runtime/python
  candidates.push(path.join(base, 'runtime', 'python', 'python.exe'));
  candidates.push(path.join(base, 'runtime', 'python', 'pythonw.exe'));

  for (const c of candidates) {
    try { if (c && fs.existsSync(c)) return c; } catch (e) { /* ignore */ }
  }

  // 3) 系统 PATH 兜底
  const dirs = (process.env.PATH || '').split(path.delimiter);
  for (const dir of dirs) {
    for (const name of ['python.exe', 'pythonw.exe']) {
      const c = path.join(dir, name);
      try { if (fs.existsSync(c)) return c; } catch (e) { /* ignore */ }
    }
  }
  return null;
}

/* ---------------- 端口与后端 ---------------- */
function getFreePort() {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.unref();
    srv.on('error', reject);
    srv.listen(0, '127.0.0.1', () => {
      const port = srv.address().port;
      srv.close(() => resolve(port));
    });
  });
}

function startBackend(port) {
  const python = findPython();
  if (!python) throw new Error('未找到 Python 运行时，请检查安装是否完整。');
  const base = getBaseDir();
  const script = path.join(base, 'webui.py');
  if (!fs.existsSync(script)) throw new Error('找不到 webui.py，安装可能不完整。');

  // 数据(Cookie/下载)写到用户目录, 避免安装到 Program Files 时的写权限问题
  const dataDir = path.join(app.getPath('userData'), 'data');
  try { fs.mkdirSync(dataDir, { recursive: true }); } catch (e) { /* ignore */ }

  let log = '';
  const append = (buf) => { log = (log + buf.toString()).slice(-4000); };

  backendProcess = spawn(python, [script, '--port', String(port), '--no-browser'], {
    cwd: base,
    windowsHide: true,
    stdio: ['ignore', 'pipe', 'pipe'],
    env: Object.assign({}, process.env, {
      PYTHONUNBUFFERED: '1',
      VIDPARSE_DATA_DIR: dataDir
    })
  });

  if (backendProcess.stdout) backendProcess.stdout.on('data', append);
  if (backendProcess.stderr) backendProcess.stderr.on('data', append);
  backendProcess.on('error', (err) => {
    if (!isQuitting) showFatal('后端启动失败：' + err.message);
  });
  backendProcess.on('exit', (code) => {
    if (!isQuitting) showFatal('后端服务已退出（代码 ' + code + '）。\n\n' + log.slice(-800));
  });
}

function showFatal(msg) {
  if (splashWindow) { try { splashWindow.close(); } catch (e) {} splashWindow = null; }
  if (!isQuitting) dialog.showErrorBox(APP_NAME + ' - 启动失败', String(msg));
  app.quit();
}

function waitForBackend(port, timeoutMs) {
  timeoutMs = timeoutMs || 45000;
  const deadline = Date.now() + timeoutMs;
  return new Promise((resolve, reject) => {
    const check = () => {
      if (isQuitting) return reject(new Error('启动已取消'));
      const req = http.get({ host: '127.0.0.1', port: port, path: '/api/health', timeout: 1500 }, (res) => {
        res.resume();
        if (res.statusCode === 200) resolve();
        else retry();
      });
      req.on('timeout', () => { try { req.destroy(); } catch (e) {} });
      req.on('error', () => retry());
    };
    const retry = () => {
      if (Date.now() > deadline) reject(new Error('本地服务启动超时，请稍后重试。'));
      else setTimeout(check, 250);
    };
    check();
  });
}

/* ---------------- 窗口 ---------------- */
function createSplash() {
  const html = [
    '<style>',
    'body{margin:0;font-family:"Microsoft YaHei",sans-serif;display:flex;flex-direction:column;',
    'align-items:center;justify-content:center;height:100vh;background:#f5f7fa;color:#2c3e50}',
    '.t{font-size:20px;font-weight:600;margin-bottom:12px}',
    '.s{font-size:13px;color:#7f8c8d}',
    '.bar{width:180px;height:4px;background:#e0e6ed;border-radius:2px;margin-top:18px;overflow:hidden}',
    '.bar:after{content:"";display:block;width:40%;height:100%;background:#409eff;border-radius:2px;',
    'animation:m 1.1s infinite ease-in-out}',
    '@keyframes m{0%{transform:translateX(-100%)}100%{transform:translateX(350%)}}',
    '</style>',
    '<div class="t">' + APP_NAME + '</div>',
    '<div class="s">正在启动本地服务，请稍候…</div>',
    '<div class="bar"></div>'
  ].join('');
  splashWindow = new BrowserWindow({
    width: 360, height: 190, frame: false, resizable: false, center: true,
    backgroundColor: '#f5f7fa', icon: path.join(__dirname, 'assets', 'icon.ico'),
    webPreferences: { nodeIntegration: false }
  });
  splashWindow.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent(html));
  splashWindow.on('closed', () => { splashWindow = null; });
}

function createMainWindow(port) {
  mainWindow = new BrowserWindow({
    width: 1200, height: 860, minWidth: 900, minHeight: 600,
    title: APP_NAME,
    icon: path.join(__dirname, 'assets', 'icon.ico'),
    backgroundColor: '#f5f7fa',
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
      spellcheck: false
    }
  });

  mainWindow.loadURL('http://127.0.0.1:' + port + '/');
  mainWindow.once('ready-to-show', () => {
    if (splashWindow) { try { splashWindow.close(); } catch (e) {} splashWindow = null; }
    if (mainWindow) { mainWindow.show(); mainWindow.focus(); }
  });
  mainWindow.on('closed', () => { mainWindow = null; });

  // 站内（本地服务）链接在窗口内打开，外部链接交给系统浏览器
  mainWindow.webContents.setWindowOpenHandler((details) => {
    const url = details.url || '';
    if (url.indexOf('http://127.0.0.1:' + port) === 0) return { action: 'allow' };
    shell.openExternal(url);
    return { action: 'deny' };
  });
}

/* ---------------- 生命周期 ---------------- */
function stopBackend() {
  if (!backendProcess) return;
  const pid = backendProcess.pid;
  backendProcess = null;
  try {
    if (process.platform === 'win32' && pid) {
      spawn('taskkill', ['/pid', String(pid), '/T', '/F'], { windowsHide: true, stdio: 'ignore' });
    } else if (pid) {
      process.kill(pid, 'SIGTERM');
    }
  } catch (e) { /* ignore */ }
}

app.whenReady().then(async () => {
  createSplash();
  try {
    const port = await getFreePort();
    backendPort = port;
    startBackend(port);
    await waitForBackend(port);
    createMainWindow(port);
  } catch (err) {
    showFatal((err && err.message) || String(err));
  }
});

app.on('before-quit', () => { isQuitting = true; stopBackend(); });
app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });
app.on('activate', () => {
  if (mainWindow === null && backendPort) createMainWindow(backendPort);
});
