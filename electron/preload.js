/**
 * 预加载脚本：向页面暴露少量桌面环境标识（不开放 Node 能力，保持安全隔离）
 */
const { contextBridge } = require('electron');

contextBridge.exposeInMainWorld('__DESKTOP__', {
  isElectron: true,
  platform: process.platform,
  electronVersion: process.versions.electron
});
