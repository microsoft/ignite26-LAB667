const gameAssetsDialog = document.getElementById('game-assets-dialog');

document.getElementById('open-game-assets').addEventListener('click', () => gameAssetsDialog.showModal());
document.getElementById('close-game-assets').addEventListener('click', () => gameAssetsDialog.close());
document.getElementById('copy-endpoint').addEventListener('click', (event) => Admin.busy(event.currentTarget, async () => {
  await navigator.clipboard.writeText(document.getElementById('mcp-endpoint').textContent);
  Admin.notify('MCP endpoint copied.');
}));
