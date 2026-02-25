/**
 * Bootstrap for Electron main process.
 *
 * Clears ELECTRON_RUN_AS_NODE which may be inherited from parent processes
 * (e.g. Cursor IDE), then loads the compiled Electron entry point.
 */
delete process.env.ELECTRON_RUN_AS_NODE

require('./dist-electron/main.js')
