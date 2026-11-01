// A hidden page that turns the recording into a Blob URL for chrome.downloads: the background
// worker can't create Blob URLs, and a data: URL is capped at 2 MB, which a recording with many
// requests and screenshots easily passes.
chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg?.type !== "offscreen-blob") return false;
  sendResponse(URL.createObjectURL(new Blob([msg.text], { type: "application/json" })));
  return false;
});
