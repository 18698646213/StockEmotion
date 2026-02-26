import { app, BrowserWindow, dialog, Menu, MenuItemConstructorOptions, shell } from 'electron'
import * as path from 'path'
import * as fs from 'fs'
import { spawn, execSync, ChildProcess } from 'child_process'
import * as http from 'http'
import * as net from 'net'

const PYTHON_PORT = 8321
const PYTHON_URL = `http://127.0.0.1:${PYTHON_PORT}`
const VITE_DEV_URL = 'http://127.0.0.1:5173'

const isDev = !app.isPackaged

let mainWindow: BrowserWindow | null = null
let pythonProcess: ChildProcess | null = null
let pythonErrors: string[] = []

// ---------------------------------------------------------------------------
// Python backend management
// ---------------------------------------------------------------------------

function getProjectRoot(): string {
  // desktop/ is a subdirectory of the project root
  if (isDev) {
    return path.resolve(__dirname, '..', '..')
  }
  return path.resolve(process.resourcesPath, 'python')
}

function findPython(): { bin: string; source: string } {
  const root = getProjectRoot()
  // Try multiple venv python paths
  const candidates = [
    path.join(root, 'venv', 'bin', 'python3'),
    path.join(root, 'venv', 'bin', 'python'),
    path.join(root, 'venv', 'bin', 'python3.12'),
    path.join(root, 'venv', 'bin', 'python3.11'),
    path.join(root, 'venv', 'bin', 'python3.10'),
  ]

  for (const candidate of candidates) {
    try {
      fs.accessSync(candidate, fs.constants.X_OK)
      return { bin: candidate, source: `venv (${candidate})` }
    } catch {
      // Try next
    }
  }

  // Fallback: try system python with venv site-packages
  const sitePackages = path.join(root, 'venv', 'lib')
  if (fs.existsSync(sitePackages)) {
    return { bin: 'python3', source: 'system python3 (venv site-packages available)' }
  }

  return { bin: 'python3', source: 'system python3 (no venv found)' }
}

/**
 * Check if a port is already in use. If so, try to determine if it's our
 * backend (by hitting the health endpoint) or some other process.
 */
function checkExistingBackend(): Promise<boolean> {
  return new Promise((resolve) => {
    http
      .get(`${PYTHON_URL}/api/health`, (res) => {
        let body = ''
        res.on('data', (chunk: Buffer) => { body += chunk.toString() })
        res.on('end', () => {
          try {
            const data = JSON.parse(body)
            if (data.status === 'ok') {
              console.log('[Electron] 检测到已有 Python 后端在运行，直接复用')
              resolve(true)
              return
            }
          } catch { /* ignore */ }
          resolve(false)
        })
      })
      .on('error', () => {
        resolve(false)
      })
  })
}

/**
 * Kill any process occupying the target port (best effort).
 */
function killPortProcess(): void {
  try {
    const result = execSync(`lsof -ti:${PYTHON_PORT}`, { encoding: 'utf-8', timeout: 3000 }).trim()
    if (result) {
      console.log(`[Electron] 发现端口 ${PYTHON_PORT} 被占用 (PID: ${result})，正在清理...`)
      execSync(`kill -9 ${result}`, { timeout: 3000 })
      console.log('[Electron] 已清理旧进程')
    }
  } catch {
    // No process on port, or kill failed — that's fine
  }
}

function startPythonBackend(): Promise<void> {
  return new Promise(async (resolve, reject) => {
    // 1. Check if backend is already running (from a previous session)
    const alreadyRunning = await checkExistingBackend()
    if (alreadyRunning) {
      resolve()
      return
    }

    // 2. Kill any zombie process on the port
    killPortProcess()

    const projectRoot = getProjectRoot()
    const { bin: pythonBin, source: pythonSource } = findPython()
    const serverScript = path.join(projectRoot, 'server.py')

    console.log(`[Electron] 项目根目录: ${projectRoot}`)
    console.log(`[Electron] Python 路径: ${pythonBin} (${pythonSource})`)
    console.log(`[Electron] 启动命令: ${pythonBin} ${serverScript} ${PYTHON_PORT}`)

    // Verify server.py exists
    if (!fs.existsSync(serverScript)) {
      reject(new Error(`找不到 server.py: ${serverScript}`))
      return
    }

    pythonErrors = []

    // Build env — include venv site-packages in PYTHONPATH as fallback
    const env = { ...process.env, PYTHONPATH: projectRoot }

    pythonProcess = spawn(pythonBin, [serverScript, String(PYTHON_PORT)], {
      cwd: projectRoot,
      env,
      stdio: ['ignore', 'pipe', 'pipe'],
    })

    pythonProcess.stdout?.on('data', (data: Buffer) => {
      console.log(`[Python] ${data.toString().trim()}`)
    })

    pythonProcess.stderr?.on('data', (data: Buffer) => {
      const msg = data.toString().trim()
      console.error(`[Python] ${msg}`)
      pythonErrors.push(msg)
    })

    let earlyExit = false

    pythonProcess.on('error', (err) => {
      console.error('[Electron] 无法启动 Python 进程:', err)
      earlyExit = true
      reject(new Error(`无法启动 Python: ${err.message}`))
    })

    pythonProcess.on('exit', (code) => {
      console.log(`[Electron] Python 进程退出，代码: ${code}`)
      if (!earlyExit && code !== null && code !== 0) {
        earlyExit = true
        const errorDetail = pythonErrors.slice(-10).join('\n')
        reject(new Error(
          `Python 进程异常退出 (代码 ${code})\n\n最近的错误信息:\n${errorDetail}`
        ))
      }
      pythonProcess = null
    })

    // Poll health endpoint with longer timeout (60 seconds)
    let attempts = 0
    const maxAttempts = 120 // 60 seconds
    const interval = setInterval(() => {
      if (earlyExit) {
        clearInterval(interval)
        return
      }
      attempts++
      http
        .get(`${PYTHON_URL}/api/health`, (res) => {
          if (res.statusCode === 200) {
            clearInterval(interval)
            console.log('[Electron] Python 后端已就绪')
            resolve()
          }
        })
        .on('error', () => {
          if (attempts >= maxAttempts) {
            clearInterval(interval)
            const errorDetail = pythonErrors.slice(-10).join('\n')
            reject(new Error(
              `Python 后端在 60 秒内未启动成功。\n\nPython 路径: ${pythonBin}\n来源: ${pythonSource}\n\n最近的错误信息:\n${errorDetail || '（无错误输出）'}`
            ))
          }
        })
    }, 500)
  })
}

function stopPythonBackend(): void {
  if (pythonProcess) {
    console.log('[Electron] 正在停止 Python 后端...')
    pythonProcess.kill('SIGTERM')

    // Force kill after 3 seconds
    setTimeout(() => {
      if (pythonProcess) {
        pythonProcess.kill('SIGKILL')
        pythonProcess = null
      }
    }, 3000)
  }
}

// ---------------------------------------------------------------------------
// Window management
// ---------------------------------------------------------------------------

async function createWindow(): Promise<void> {
  if (mainWindow !== null) return

  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1000,
    minHeight: 700,
    title: '股票舆情策略分析',
    backgroundColor: '#030712',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  })

  // Open external links (target="_blank") in the system default browser
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith('http://') || url.startsWith('https://')) {
      shell.openExternal(url)
    }
    return { action: 'deny' }
  })

  mainWindow.webContents.on('will-navigate', (event, url) => {
    const isInternal = url.startsWith(VITE_DEV_URL) || url.startsWith('file://')
    if (!isInternal) {
      event.preventDefault()
      shell.openExternal(url)
    }
  })

  if (isDev) {
    mainWindow.loadURL(VITE_DEV_URL)
  } else {
    mainWindow.loadFile(path.join(__dirname, '..', 'dist', 'index.html'))
  }

  mainWindow.on('closed', () => {
    mainWindow = null
  })
}

// ---------------------------------------------------------------------------
// Application menu
// ---------------------------------------------------------------------------

function buildAppMenu(): void {
  const isMac = process.platform === 'darwin'

  const template: MenuItemConstructorOptions[] = [
    // macOS app menu
    ...(isMac ? [{
      label: app.name,
      submenu: [
        { role: 'about' as const, label: '关于' },
        { type: 'separator' as const },
        { role: 'hide' as const, label: '隐藏' },
        { role: 'hideOthers' as const, label: '隐藏其他' },
        { role: 'unhide' as const, label: '显示全部' },
        { type: 'separator' as const },
        { role: 'quit' as const, label: '退出' },
      ],
    }] : []),

    // Edit menu
    {
      label: '编辑',
      submenu: [
        { role: 'undo' as const, label: '撤销' },
        { role: 'redo' as const, label: '重做' },
        { type: 'separator' as const },
        { role: 'cut' as const, label: '剪切' },
        { role: 'copy' as const, label: '复制' },
        { role: 'paste' as const, label: '粘贴' },
        { role: 'selectAll' as const, label: '全选' },
      ],
    },

    // View menu
    {
      label: '视图',
      submenu: [
        { role: 'reload' as const, label: '刷新' },
        { role: 'forceReload' as const, label: '强制刷新' },
        { type: 'separator' as const },
        { role: 'resetZoom' as const, label: '实际大小' },
        { role: 'zoomIn' as const, label: '放大' },
        { role: 'zoomOut' as const, label: '缩小' },
        { type: 'separator' as const },
        { role: 'togglefullscreen' as const, label: '全屏' },
      ],
    },

    // Develop menu
    {
      label: '开发',
      submenu: [
        {
          label: '控制台',
          accelerator: isMac ? 'Cmd+Option+I' : 'Ctrl+Shift+I',
          click: () => {
            if (mainWindow) {
              if (mainWindow.webContents.isDevToolsOpened()) {
                mainWindow.webContents.closeDevTools()
              } else {
                mainWindow.webContents.openDevTools({ mode: 'bottom' })
              }
            }
          },
        },
      ],
    },

    // Window menu
    {
      label: '窗口',
      submenu: [
        { role: 'minimize' as const, label: '最小化' },
        { role: 'zoom' as const, label: '缩放' },
        ...(isMac ? [
          { type: 'separator' as const },
          { role: 'front' as const, label: '前置全部窗口' },
        ] : [
          { role: 'close' as const, label: '关闭' },
        ]),
      ],
    },
  ]

  const menu = Menu.buildFromTemplate(template)
  Menu.setApplicationMenu(menu)
}

// ---------------------------------------------------------------------------
// App lifecycle
// ---------------------------------------------------------------------------

app.whenReady().then(async () => {
  buildAppMenu()

  try {
    await startPythonBackend()
    await createWindow()
  } catch (err: any) {
    console.error('[Electron] 启动失败:', err)
    const msg = err?.message || String(err)
    dialog.showErrorBox(
      '启动错误',
      `Python 后端启动失败。\n\n${msg}\n\n请在终端中手动测试:\n  cd stock-sentiment-strategy\n  ./venv/bin/python3 server.py`
    )
    app.quit()
  }
})

app.on('window-all-closed', () => {
  stopPythonBackend()
  if (process.platform !== 'darwin') {
    app.quit()
  }
})

app.on('activate', async () => {
  if (mainWindow === null) {
    await createWindow()
  }
})

app.on('before-quit', () => {
  stopPythonBackend()
})

// Ensure cleanup on signal
process.on('SIGINT', () => {
  stopPythonBackend()
  process.exit(0)
})

process.on('SIGTERM', () => {
  stopPythonBackend()
  process.exit(0)
})
