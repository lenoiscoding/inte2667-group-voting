// Req 16 - password fields are masked by default, with a Show/Hide button.
// A revealed password is hidden again after 10 seconds, when the form is
// submitted (so the browser and password managers see a normal password
// field) and when the page is hidden. Spell-check is turned off so a revealed
// password is never sent to a browser's online spell-checking service.
(function () {
  const REVEAL_MS = 10000;

  document.querySelectorAll('input[type="password"]').forEach((input) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "password-toggle";
    button.setAttribute("aria-controls", input.id);

    const wrapper = document.createElement("span");
    wrapper.className = "password-field";
    input.before(wrapper);
    wrapper.append(input, button);

    input.spellcheck = false;
    input.setAttribute("autocapitalize", "off");
    input.setAttribute("autocorrect", "off");

    let timer;

    function setVisible(visible) {
      clearTimeout(timer);
      input.type = visible ? "text" : "password";
      button.textContent = visible ? "Hide" : "Show";
      button.setAttribute("aria-pressed", String(visible));
      button.setAttribute("aria-label", visible ? "Hide password" : "Show password");
      if (visible) {
        timer = setTimeout(() => setVisible(false), REVEAL_MS);
      }
    }

    button.addEventListener("click", () => setVisible(input.type === "password"));
    input.form.addEventListener("submit", () => setVisible(false));
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) {
        setVisible(false);
      }
    });

    setVisible(false);
  });
})();
