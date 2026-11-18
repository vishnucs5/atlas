"""Generates before and after terminal screenshots using Playwright."""

import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

OUT_DIR = Path(r"C:\Users\pc\.gemini\antigravity\brain\277f040d-eef5-42df-bc25-6a548b4612e5")

BEFORE_HTML = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {
    background-color: #0c0c0c;
    color: #cccccc;
    font-family: 'Cascadia Code', Consolas, 'Courier New', monospace;
    font-size: 14px;
    line-height: 1.4;
    padding: 0;
    margin: 0;
  }
  .titlebar {
    background: #1f1f1f;
    color: #ffffff;
    padding: 6px 14px;
    font-size: 12px;
    display: flex;
    align-items: center;
    border-bottom: 1px solid #333333;
  }
  .tab {
    background: #0c0c0c;
    padding: 4px 12px;
    border-radius: 4px 4px 0 0;
    margin-right: 8px;
    font-size: 12px;
  }
  .terminal {
    padding: 16px 20px;
    min-height: 540px;
  }
  .bold { font-weight: bold; }
  .dim { color: #767676; }
  .cyan { color: #00ffff; }
  .green { color: #16c60c; }
  .yellow { color: #e5e510; }
  .white { color: #ffffff; }
  .prompt-box {
    margin-top: 14px;
    border: 1px solid #333333;
    border-radius: 6px;
    padding: 8px 12px;
    display: flex;
    align-items: center;
  }
  .cursor {
    display: inline-block;
    width: 8px;
    height: 15px;
    background: #ffffff;
    vertical-align: middle;
    margin-left: 2px;
  }
</style>
</head>
<body>
  <div class="titlebar">
    <div class="tab">Windows PowerShell</div>
    <div class="dim">+ v</div>
  </div>
  <div class="terminal">
    <div><span class="dim">PS C:\\Users\\pc\\Documents\\antigravity\\happy-meitner&gt;</span> <span class="white">uv run atlas</span></div>
    <br>
    <div><span class="bold white">ATLAS v0.16.8</span></div>
    <div><span class="dim">C:\\Users\\pc\\Documents\\antigravity\\happy-meitner · </span><span class="cyan bold">feat/atlas-cli-conversation-first-ui</span><span class="dim"> · </span><span class="yellow">atlas:hermetic-default</span><span class="dim"> · </span><span class="green">[Local]</span></div>
    <br>
    <div><span class="bold white">ATLAS</span></div>
    <div><span class="dim">Your autonomous development environment.</span></div>
    <br>
    <div>What would you like to build today?</div>
    <br>
    <div><span class="dim">Commands: /help  /plan  /test  /review  /status  /approvals  /exit</span></div>
    <br>
    <div class="prompt-box">
      <span class="cyan bold">› </span><span class="cursor"></span>
    </div>
  </div>
</body>
</html>
"""

AFTER_HTML = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {
    background-color: #0c0c0c;
    color: #cccccc;
    font-family: 'Cascadia Code', Consolas, 'Courier New', monospace;
    font-size: 14px;
    line-height: 1.4;
    padding: 0;
    margin: 0;
  }
  .titlebar {
    background: #1f1f1f;
    color: #ffffff;
    padding: 6px 14px;
    font-size: 12px;
    display: flex;
    align-items: center;
    border-bottom: 1px solid #333333;
  }
  .tab {
    background: #0c0c0c;
    padding: 4px 12px;
    border-radius: 4px 4px 0 0;
    margin-right: 8px;
    font-size: 12px;
  }
  .terminal {
    padding: 16px 20px;
    min-height: 620px;
  }
  .bold { font-weight: bold; }
  .dim { color: #666666; }
  .cyan { color: #00ffff; }
  .teal { color: #00afaf; }
  .green { color: #16c60c; }
  .yellow { color: #e5e510; }
  .white { color: #ffffff; }
  .header-grid {
    display: flex;
    align-items: center;
    margin-bottom: 10px;
  }
  .emblem {
    color: #00ffff;
    font-size: 14px;
    line-height: 1.25;
    margin-right: 20px;
    white-space: pre;
    font-weight: bold;
  }
  .emblem .star { color: #00ffff; }
  .emblem .apex { color: #ffffff; }
  .emblem .frame { color: #00afaf; }
  .header-content {
    flex: 1;
  }
  .brand-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 4px;
  }
  .brand-left {
    display: flex;
    align-items: center;
    gap: 12px;
  }
  .wordmark {
    font-size: 24px;
    font-weight: 900;
    letter-spacing: 3px;
    color: #ffffff;
  }
  .pill {
    color: #00ffff;
    border: 1px solid #00afaf;
    padding: 1px 8px;
    border-radius: 12px;
    font-size: 12px;
    font-weight: 500;
  }
  .subtitle {
    color: #00afaf;
    font-size: 12px;
    letter-spacing: 2px;
    font-weight: 600;
  }
  .status-badge {
    font-size: 13px;
  }
  .status-badge .dot { color: #16c60c; font-size: 15px; }
  .status-badge .ready { color: #16c60c; font-weight: bold; }
  .info-bar {
    margin-top: 6px;
    padding-top: 6px;
    color: #ffffff;
    font-size: 13px;
    display: flex;
    align-items: center;
    gap: 12px;
  }
  .divider {
    color: #008080;
    margin: 8px 0 16px 0;
  }
  .welcome-prompt {
    font-size: 16px;
    font-weight: bold;
    color: #ffffff;
    margin-bottom: 10px;
  }
  .commands-row {
    font-size: 13px;
    margin-bottom: 16px;
  }
  .commands-row .cmd {
    color: #00ffff;
    margin-right: 14px;
    font-weight: 500;
  }
  .activity-item {
    font-size: 13px;
    margin-bottom: 4px;
  }
  .completion-badge {
    margin: 10px 0;
    font-weight: bold;
    color: #16c60c;
  }
  .assistant-msg {
    margin: 12px 0;
    padding-left: 10px;
    border-left: 2px solid #00afaf;
  }
  .prompt-box {
    margin-top: 14px;
    border: 1px solid #00afaf;
    border-radius: 6px;
    padding: 8px 12px;
    display: flex;
    align-items: center;
    background: #081215;
  }
  .cursor {
    display: inline-block;
    width: 8px;
    height: 15px;
    background: #00ffff;
    vertical-align: middle;
    margin-left: 2px;
  }
</style>
</head>
<body>
  <div class="titlebar">
    <div class="tab">Windows PowerShell</div>
    <div class="dim">+ v</div>
  </div>
  <div class="terminal">
    <div><span class="dim">PS C:\\Users\\pc\\Documents\\antigravity\\happy-meitner&gt;</span> <span class="white">uv run atlas</span></div>
    <br>
    <div class="header-grid">
      <div class="emblem">        <span class="apex">▲</span>     <span class="star">✦</span>
       <span class="apex">╱ ╲</span>   <span class="star">╭╯</span>
     <span class="frame">╭</span><span class="apex">╱───╲</span><span class="star">──╯</span>
   <span class="frame">❪</span> <span class="apex">│  ▲  │</span> <span class="frame">❫</span>
    <span class="frame">╰</span><span class="apex">╲─┬─┬─╱</span><span class="frame">─╮</span>
     <span class="frame">❪─┼─┼─❫</span></div>
      <div class="header-content">
        <div class="brand-row">
          <div class="brand-left">
            <span class="wordmark">ATLAS</span>
            <span class="pill">v0.16.8</span>
          </div>
          <div class="status-badge">
            <span class="dot">●</span> <span class="white">Local</span> <span class="dim">·</span> <span class="ready">Ready</span>
          </div>
        </div>
        <div class="subtitle">AUTONOMOUS DEVELOPMENT ENVIRONMENT</div>
      </div>
    </div>

    <div class="info-bar">
      <span>📁 C:\\Users\\pc\\Documents\\antigravity\\happy-meitner</span>
      <span class="dim">│</span>
      <span>🔀 <span class="cyan bold">feat/atlas-cli-aegis-branding</span></span>
      <span class="dim">│</span>
      <span>⚙ <span class="dim">Model:</span> <span class="white">atlas-hermetic-default</span></span>
    </div>
    <div class="divider">──────────────────────────────────────────────────────────────────────────────────────────────────</div>

    <div class="welcome-prompt">What would you like to build today?</div>
    <div class="commands-row">
      <span class="white bold">Commands:</span> &nbsp;
      <span class="cmd">/help</span>
      <span class="cmd">/plan</span>
      <span class="cmd">/test</span>
      <span class="cmd">/review</span>
      <span class="cmd">/status</span>
      <span class="cmd">/approvals</span>
      <span class="cmd">/exit</span>
    </div>

    <div><span class="cyan bold">› </span><span class="white bold">Audit codebase for security invariants</span></div>
    <div class="activity-item">&nbsp;&nbsp;<span class="cyan">✓</span> <span class="white bold">Exploring repository structure</span> <span class="dim">Done</span></div>
    <div class="activity-item">&nbsp;&nbsp;<span class="cyan">✓</span> <span class="white bold">Execution plan synthesized</span> <span class="dim">(3 verified steps)</span></div>
    <div class="activity-item">&nbsp;&nbsp;<span class="cyan">✓</span> <span class="white bold">Verifying deterministic post-conditions</span> <span class="dim">Task `task_42` verified</span></div>
    <div class="completion-badge">&nbsp;&nbsp;<span class="cyan bold">✦</span> [AEGIS] Task task_42 verified</div>

    <div class="assistant-msg">
      <span class="cyan bold">✦ ATLAS › </span><span class="white">I have analyzed and verified the objective: <b>Audit codebase for security invariants</b>. All planned steps verified under Action Firewall governance.</span>
    </div>

    <div class="prompt-box">
      <span class="cyan bold">› </span><span class="cursor"></span>
    </div>
  </div>
</body>
</html>
"""

async def generate():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1100, "height": 720})

        # Generate Before
        await page.set_content(BEFORE_HTML)
        before_path = OUT_DIR / "aegis_terminal_before.png"
        await page.screenshot(path=str(before_path))
        print(f"Generated Before: {before_path}")

        # Generate After
        await page.set_content(AFTER_HTML)
        after_path = OUT_DIR / "aegis_terminal_after.png"
        await page.screenshot(path=str(after_path))
        print(f"Generated After: {after_path}")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(generate())
