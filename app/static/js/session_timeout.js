// Req 3: go back to the login page after the server's idle time
// (SESSION_TIMEOUT_SECONDS), which the <script> tag passes in.
const IDLE_MS = Number(document.currentScript.dataset.timeoutSeconds || 900) * 1000;

let timeout;
let lastPing = 0;

function resetTimer() {
  clearTimeout(timeout);

  timeout = setTimeout(() => {
    window.location.href = "/auth/login";
  }, IDLE_MS);
}

function recordActivity() {
  resetTimer();

  if (Date.now() - lastPing > 2000) {
    lastPing = Date.now();

    fetch("/auth/activity", {
      method: "POST",
      credentials: "same-origin",
    })
      .then((response) => {
        if (response.status === 401) {
          window.location.href = "/auth/login";
        }
      })
      .catch(() => {});
  }
}

["mousemove", "keydown", "click", "scroll", "touchstart"].forEach((event) => {
  document.addEventListener(event, recordActivity);
});

resetTimer();
