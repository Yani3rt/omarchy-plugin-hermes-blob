import { test } from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { spawn, spawnSync } from 'node:child_process'
import { root } from '../scripts/template.mjs'

const BOB = 'e0195a7d-f804-4688-9191-e2cf3574a6d1'

function runPython(script, args, options = {}) {
  return spawnSync('python3', [path.join(root, script), ...args], {
    encoding: 'utf8',
    input: options.input,
    env: options.env,
    timeout: options.timeout || 15000
  })
}

// A fake install: ~/.hermes with a default profile and named profiles, plus a
// stand-in `hermes` in ~/.local/bin that records its argv and stdin.
function hermesHome({ profiles = {}, hermes = null, desktop = { dispatch: 'hermes' } } = {}) {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'hermes-blob-'))
  const config = path.join(home, '.config', 'omarchy')
  const bin = path.join(home, '.local', 'bin')
  fs.mkdirSync(config, { recursive: true })
  fs.mkdirSync(bin, { recursive: true, mode: 0o755 })
  fs.chmodSync(path.join(home, '.local'), 0o755)
  fs.writeFileSync(path.join(config, 'grokbot-desktop.json'), JSON.stringify(desktop))
  const hermesRoot = path.join(home, '.hermes')
  fs.mkdirSync(hermesRoot, { recursive: true })
  for (const [name, profileYaml] of Object.entries(profiles)) {
    const dir = name === 'default' ? hermesRoot : path.join(hermesRoot, 'profiles', name)
    fs.mkdirSync(dir, { recursive: true })
    fs.writeFileSync(path.join(dir, 'config.yaml'), 'model: {}\n')
    if (profileYaml) fs.writeFileSync(path.join(dir, 'profile.yaml'), profileYaml)
  }
  fs.writeFileSync(path.join(bin, 'hermes'), hermes || [
    '#!/usr/bin/python3',
    'import json, os, sys',
    'data = sys.stdin.read()',
    'open(os.environ["HOME"] + "/hermes-call.json", "w").write(json.dumps({"argv": sys.argv[1:], "stdin": data, "cwd": os.getcwd()}))',
    'print("reply from " + sys.argv[sys.argv.index("-p") + 1])'
  ].join('\n') + '\n', { mode: 0o755 })
  return home
}

const envFor = (home) => ({ PATH: '/usr/bin:/bin', HOME: home, XDG_CONFIG_HOME: path.join(home, '.config') })

function ask(home, payload, timeout) {
  return runPython('bin/grokbot-ask', [], { input: JSON.stringify(payload), env: envFor(home), timeout })
}

test('hermes sync builds one bot per profile from Bot Mode metadata only', () => {
  const home = hermesHome({
    profiles: {
      default: 'ui_meta:\n  hermes-bots:\n    title: Zero\n    shape: squircle\n    color: "#f97316"\n',
      donna: "description: 'Executive assistant. Handles the calendar.'\n",
      padd: 'ui_meta:\n  hermes-bots:\n    title: Padd\n    shape: circle\n    color: "#14b8a6"\n',
      ghost: 'ui_meta:\n  hermes-bots:\n    hidden: true\n',
      lore: 'ui_meta:\n  hermes-bots:\n    shape: blobatar\n    color: hsl(344 68% 58%)\n'
    }
  })
  fs.mkdirSync(path.join(home, '.hermes', 'profiles', 'not-a-profile'))
  const out = path.join(home, 'bots.json')
  const result = runPython('bin/grokbot-sync', ['--auto', '--output', out], { env: envFor(home) })
  assert.equal(result.status, 0, result.stderr)
  assert.match(result.stdout, /Synced 4 bots from Hermes/)
  const bots = JSON.parse(fs.readFileSync(out, 'utf8')).bots
  const byId = Object.fromEntries(bots.map((bot) => [bot.id, bot]))
  assert.deepEqual(Object.keys(byId).sort(), ['default', 'donna', 'lore', 'padd'])
  assert.equal(bots[0].id, 'default', 'the primary profile comes first')
  assert.equal(byId.default.isPrimary, true)
  assert.deepEqual([byId.default.name, byId.default.avatarShape, byId.default.avatarColor], ['Zero', 'squircle', 'orange'])
  assert.deepEqual([byId.padd.avatarShape, byId.padd.avatarColor], ['circle', 'cyan'])
  assert.deepEqual([byId.lore.name, byId.lore.avatarShape, byId.lore.avatarColor], ['Lore', 'blob', 'red'])
  assert.equal(byId.donna.description, 'Executive assistant.')
})

test('hermes sync honours hermesPrimary and refuses a missing install', () => {
  const home = hermesHome({ profiles: { default: '', donna: '' }, desktop: { dispatch: 'hermes', hermesPrimary: 'donna' } })
  const out = path.join(home, 'bots.json')
  assert.equal(runPython('bin/grokbot-sync', ['--hermes', '--output', out], { env: envFor(home) }).status, 0)
  const bots = JSON.parse(fs.readFileSync(out, 'utf8')).bots
  assert.equal(bots[0].id, 'donna')
  assert.equal(bots.filter((bot) => bot.isPrimary).length, 1)

  fs.rmSync(path.join(home, '.hermes'), { recursive: true })
  const missing = runPython('bin/grokbot-sync', ['--hermes', '--output', out], { env: envFor(home) })
  assert.equal(missing.status, 1)
  assert.match(missing.stderr, /No Hermes install/)
})

test('hermes dispatch runs the profile\'s Bot Chat with the prompt on stdin only', () => {
  const home = hermesHome({ profiles: { default: '', donna: '' } })
  const token = 'private-prompt-token'
  const result = ask(home, { botId: 'donna', botName: 'Donna', prompt: token })
  assert.equal(result.status, 0, result.stderr)
  assert.equal(result.stdout.trim(), 'reply from donna')
  const call = JSON.parse(fs.readFileSync(path.join(home, 'hermes-call.json'), 'utf8'))
  assert.deepEqual(call.argv, ['-p', 'donna', 'chat', '--in', home, '-c', 'Bot Chat', '--create-if-missing', '--query-file', '-', '-Q'])
  assert.equal(call.argv.some((part) => part.includes(token)), false)
  assert.match(call.stdin, /^\[via Omarchy desktop bubble[^\n]*\]\n\nprivate-prompt-token$/)

  const zero = ask(home, { botId: 'default', botName: 'Zero', prompt: 'hi' })
  assert.equal(zero.stdout.trim(), 'reply from default')
})

test('hermes dispatch refuses a bot that is not a known profile', () => {
  const home = hermesHome({ profiles: { default: '' } })
  const grok = ask(home, { botId: BOB, botName: 'Bob', prompt: 'hi' })
  assert.equal(grok.status, 127)
  assert.match(grok.stderr, /was not found\. Sync bots again/)
  const gone = ask(home, { botId: 'atlas', botName: 'Atlas', prompt: 'hi' })
  assert.equal(gone.status, 127)
  assert.match(gone.stderr, /atlas was not found/)
  assert.equal(fs.existsSync(path.join(home, 'hermes-call.json')), false)
})

test('hermes dispatch gives Hermes the configured time and reports a timeout', () => {
  const slow = '#!/usr/bin/python3\nimport sys, time\nsys.stdin.read()\ntime.sleep(60)\n'
  const home = hermesHome({ profiles: { default: '' }, hermes: slow, desktop: { dispatch: 'hermes', askTimeoutSeconds: 1 } })
  const started = Date.now()
  const result = ask(home, { botId: 'default', botName: 'Zero', prompt: 'hi' }, 45000)
  assert.equal(result.status, 124)
  assert.match(result.stderr, /timed out/)
  // Clamped to the 30-second floor, not left at 1 second or the 600-second default.
  assert.ok(Date.now() - started >= 29000 && Date.now() - started < 40000)
})

test('stopping an ask ends the Hermes turn instead of orphaning it', async () => {
  const sleeper = [
    '#!/usr/bin/python3',
    'import os, sys, time',
    'sys.stdin.read()',
    'open(os.environ["HOME"] + "/hermes.pid", "w").write(str(os.getpid()))',
    'time.sleep(60)'
  ].join('\n') + '\n'
  const home = hermesHome({ profiles: { default: '' }, hermes: sleeper })
  const child = spawn('python3', [path.join(root, 'bin/grokbot-ask')], { env: envFor(home) })
  child.stdin.end(JSON.stringify({ botId: 'default', botName: 'Zero', prompt: 'hi' }))
  const pidFile = path.join(home, 'hermes.pid')
  for (let i = 0; i < 100 && !fs.existsSync(pidFile); i++) await new Promise((r) => setTimeout(r, 50))
  const pid = Number(fs.readFileSync(pidFile, 'utf8'))
  const exited = new Promise((resolve) => child.on('exit', (code, signal) => resolve({ code, signal })))
  child.kill('SIGTERM')
  const { code } = await exited
  assert.equal(code, 143)
  await new Promise((r) => setTimeout(r, 300))
  assert.throws(() => process.kill(pid, 0), /ESRCH/, 'the hermes process must be gone')
})

test('the shell syncs with --auto and only backstops the helper\'s own timeout', () => {
  const main = fs.readFileSync(path.join(root, 'Main.qml'), 'utf8')
  assert.match(main, /root\.syncHelper, "--auto", "--output", root\.botsPath/)
  assert.match(main, /id: askTimeout\n(\s*\/\/[^\n]*\n)*\s*interval: 1830000/)
})

test('hermes dispatch refuses a malformed bot id before touching the filesystem', () => {
  const home = hermesHome({ profiles: { default: '' } })
  for (const botId of ['Bob', '../default', 'a b']) {
    const result = ask(home, { botId, botName: 'x', prompt: 'hi' })
    if (result.status === 2) continue // rejected by the payload check itself
    assert.equal(result.status, 127, botId)
    assert.match(result.stderr, /isn't a Hermes profile/)
  }
})

test('Hermes mode keeps a bridge on stdin/stdout and falls back to the command line', () => {
  const main = fs.readFileSync(path.join(root, 'Main.qml'), 'utf8')
  // The bridge runs Hermes' own Python, isolated, and only ever hears JSON on stdin.
  assert.match(main, /command: \[root\.hermesPython, "-I", root\.bridgeHelper\]/)
  assert.match(main, /bridgeProc\.write\(JSON\.stringify\(message\) \+ "\\n"\)/)
  assert.match(main, /clearEnvironment: true\n\s*environment: root\.askEnvironment\(\)\n\s*stdinEnabled: true/)
  // Attachments, or a bot the bridge has not attached, take the command-line path.
  assert.match(main, /if \(root\.askedFiles\.length === 0 && bot && root\.bridgeUsable\(bot\.id\)\)/)
  assert.match(main, /if \(ev\.code === "unavailable" && root\.asking\) \{[^}]*root\.startProcessAsk\(\)/)
  // Stop interrupts inside the gateway; a turn nobody here asked for lands as that bot's reply.
  assert.match(main, /root\.bridgeSend\(\{ op: "stop", bot: root\.askBotId \}\)/)
  assert.match(main, /else if \(ev\.askId === undefined && text !== ""\) root\.receiveReply\(bot, text\)/)
  for (const file of ['qml/CompanionShellIpc.qml', 'qml/CompanionIpcHandler.qml']) {
    assert.match(fs.readFileSync(path.join(root, file), 'utf8'), /function status\(\): string \{ return host\.statusJson\(\) \}/)
  }
})

test('the bridge never puts prompt or reply text on its command line or stderr', () => {
  const source = fs.readFileSync(path.join(root, 'bin/hermes-blob-bridge'), 'utf8')
  assert.doesNotMatch(source, /log\([^)]*\btext\b/)
  assert.match(source, /input_id=uuid\.uuid4\(\)\.hex, text=NOTE \+ "\\n\\n" \+ text/)
  assert.match(source, /asyncio\.to_thread\(_session_ticket, self\.home, result\.endpoint\)/)
})
