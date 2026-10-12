let timeout;
let lastPing = 0;

function resetTimer() {
  clearTimeout(timeout);

  timeout = setTimeout(() => {
    window.location.href = "/auth/login";
  }, 10000);
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
